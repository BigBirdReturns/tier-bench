#!/usr/bin/env python3
"""
Offline test for the persona A/B MCP server. No API keys needed:
TIER_BENCH_MOCK=1 swaps in the deterministic fake backend.

    TIER_BENCH_MOCK=1 python3 mcp/test_offline.py

Exercises the real request path via handle(), plus one stdio subprocess
round-trip to prove the JSON-RPC loop itself works. Exit 0 iff all pass.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["TIER_BENCH_MOCK"] = "1"
_HERE = Path(__file__).resolve().parent
os.environ["TIER_BENCH_AB_LOG"] = str(Path(tempfile.gettempdir()) / "tb_ab_test.jsonl")
if os.path.exists(os.environ["TIER_BENCH_AB_LOG"]):
    os.remove(os.environ["TIER_BENCH_AB_LOG"])

sys.path.insert(0, str(_HERE))
import server  # noqa: E402
import personas  # noqa: E402

_checks = []


def check(name, cond):
    _checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def call_tool(reg, name, args):
    resp = server.handle(reg, None, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": name, "arguments": args}})
    payload = resp["result"]["content"][0]["text"]
    return json.loads(payload), resp["result"].get("isError", False)


reg = personas.Registry()

# 1. initialize
r = server.handle(reg, None, {"jsonrpc": "2.0", "id": 0, "method": "initialize"})
check("initialize → serverInfo.name", r["result"]["serverInfo"]["name"] == "tier-bench-personas")

# 2. tools/list has all four
r = server.handle(reg, None, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
names = {t["name"] for t in r["result"]["tools"]}
check("tools/list has 4 tools", names == {"list_personas", "complete", "ab", "impersonate"})

# list_personas contains a model and the driver composite
lst, _ = call_tool(reg, "list_personas", {})
pnames = {p["name"] for p in lst["personas"]}
check("list_personas has claude-haiku-4-5 (model)", "claude-haiku-4-5" in pnames)
check("list_personas has driver:fable+haiku (driver)", "driver:fable+haiku" in pnames)

# 3. complete on a plain model persona
res, err = call_tool(reg, "complete", {"persona": "claude-haiku-4-5", "prompt": "say hi"})
check("complete(plain) content present", bool(res.get("content")) and not err)
check("complete(plain) cost > 0", res.get("cost", 0) > 0)
check("complete(plain) final_model == model", res.get("final_model") == "claude-haiku-4-5")

# 4. driver persona, EASY prompt → draft accepted (PASS), final_model = hands
res, _ = call_tool(reg, "complete", {"persona": "driver:fable+haiku", "prompt": "easy: say hello"})
steps = [s["step"] for s in res["trace"]]
check("driver/easy trace = hands_draft, driver_verify", steps == ["hands_draft", "driver_verify"])
check("driver/easy verdict pass", res["trace"][1].get("verdict") == "pass")
check("driver/easy final_model == hands (cheap)", res["final_model"] == "claude-haiku-4-5")
check("driver/easy cost == sum(trace costs)",
      abs(res["cost"] - round(sum(s["cost"] for s in res["trace"]), 6)) < 1e-9)

# 5. driver persona, HARD prompt → driver repairs, final_model = driver
res, _ = call_tool(reg, "complete", {"persona": "driver:fable+haiku", "prompt": "refactor the god object"})
steps = [s["step"] for s in res["trace"]]
check("driver/hard trace has driver_repair", "driver_repair" in steps)
check("driver/hard final_model == driver", res["final_model"] == "claude-fable-5")
check("driver/hard cost == sum(trace costs)",
      abs(res["cost"] - round(sum(s["cost"] for s in res["trace"]), 6)) < 1e-9)

# 6. ab blind with a judge → no names leak in left/right; log records the winner
res, _ = call_tool(reg, "ab", {"prompt": "write a haiku", "a": "claude-haiku-4-5",
                               "b": "driver:fable+haiku", "judge": "claude-sonnet-4-5", "blind": True})
leak = ("persona" in res["left"] or "persona" in res["right"] or "mapping" in res)
check("ab blind hides persona names in left/right", not leak)
check("ab blind still returns two answers", bool(res["left"]["content"]) and bool(res["right"]["content"]))
log_lines = [json.loads(x) for x in open(os.environ["TIER_BENCH_AB_LOG"], encoding="utf-8") if x.strip()]
check("ab wrote a log line", len(log_lines) == 1)
check("ab log records winner_persona (even while caller blind)",
      log_lines[0].get("winner_persona") in ("claude-haiku-4-5", "driver:fable+haiku"))

# 7. impersonate → composite answers under an alias
res, _ = call_tool(reg, "impersonate", {"alias": "frontier-x", "backing": "driver:fable+haiku"})
check("impersonate ok", res.get("ok") is True)
res, _ = call_tool(reg, "complete", {"persona": "frontier-x", "prompt": "refactor the god object"})
steps = [s["step"] for s in res["trace"]]
check("impersonated persona reports alias name", res["persona"] == "frontier-x")
check("impersonated persona runs the composite", "hands_draft" in steps and "driver_repair" in steps)

# 8. stdio subprocess round-trip — the JSON-RPC loop actually works over pipes
proc = subprocess.run([sys.executable, str(_HERE / "server.py")],
                      input='{"jsonrpc":"2.0","id":9,"method":"initialize"}\n',
                      capture_output=True, text=True, timeout=30,
                      env={**os.environ, "TIER_BENCH_MOCK": "1"})
try:
    out = json.loads(proc.stdout.strip().splitlines()[0])
    ok = out["result"]["serverInfo"]["name"] == "tier-bench-personas"
except Exception:
    ok = False
check("stdio subprocess initialize round-trip", ok)

# ── summary ─────────────────────────────────────────────────────────────
passed = sum(1 for _, ok in _checks if ok)
print(f"\n{passed}/{len(_checks)} checks passed")
sys.exit(0 if passed == len(_checks) else 1)
