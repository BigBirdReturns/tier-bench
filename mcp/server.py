#!/usr/bin/env python3
"""
tier-bench persona A/B MCP server — stdio JSON-RPC 2.0, standard library only.

Exposes every model and every driver-composite as a swappable *persona*, plus
blind A/B and impersonation, so any MCP client can ask: can the $0.03 composite
pass for the $0.50 frontier model in my actual workflow?

Tools:
  list_personas   models + driver-composites, flattened to one interface
  complete        run one persona on a prompt
  ab              run two, return them blind as left/right, optional judge,
                  log every duel to ab_log.jsonl (the durable record)
  impersonate     register a persona under another name (the "acts like" core)

Keyless testing: TIER_BENCH_MOCK=1 swaps in a deterministic fake backend.
Add to an MCP client via the claude_desktop_config.json snippet in README.md.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # import personas as a sibling
import personas  # noqa: E402

AB_LOG = os.environ.get("TIER_BENCH_AB_LOG",
                        str(Path(__file__).resolve().parent.parent / "ab_log.jsonl"))

TOOLS = [
    {
        "name": "list_personas",
        "description": "List callable personas: every model and every live driver-composite, with backing and availability.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "complete",
        "description": "Run one persona on a prompt. A driver-composite persona drafts with a cheap model then has the frontier model review (PASS or fix). Returns content, cost, final_model, and the step trace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "string", "description": "persona name from list_personas (or an impersonation alias)"},
                "prompt": {"type": "string"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["persona", "prompt"],
        },
    },
    {
        "name": "ab",
        "description": "Run two personas on the same prompt and return them blind as left/right (names withheld unless blind=false). Optional judge persona picks a winner. Every duel is logged to ab_log.jsonl.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "a": {"type": "string", "description": "first persona"},
                "b": {"type": "string", "description": "second persona"},
                "blind": {"type": "boolean", "default": True},
                "judge": {"type": "string", "description": "optional persona to pick the better answer"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["prompt", "a", "b"],
        },
    },
    {
        "name": "impersonate",
        "description": "Register an alias so one persona presents under another name — e.g. make driver:fable+haiku answer as 'frontier-x' for a blind A/B against the real frontier.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "alias": {"type": "string"},
                "backing": {"type": "string", "description": "the real persona name the alias resolves to"},
            },
            "required": ["alias", "backing"],
        },
    },
]


def _log_ab(record):
    with open(AB_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _blind_order(ra, a, rb, b):
    """Assign left/right by content hash — deterministic, but does not leak
    which of the caller's two personas landed where."""
    ha = hashlib.sha256((ra["content"] or "").encode("utf-8")).hexdigest()
    hb = hashlib.sha256((rb["content"] or "").encode("utf-8")).hexdigest()
    if ha <= hb:
        return (ra, a), (rb, b)
    return (rb, b), (ra, a)


def _tool_ab(reg, guard, args):
    prompt, a, b = args["prompt"], args["a"], args["b"]
    blind = args.get("blind", True)
    judge = args.get("judge")
    max_tokens = args.get("max_tokens")

    ra = reg.complete(guard, a, prompt, max_tokens)
    rb = reg.complete(guard, b, prompt, max_tokens)
    (lr, lname), (rr, rname) = _blind_order(ra, a, rb, b)

    winner_side = winner_persona = judge_used = None
    if judge:
        if reg.resolve(judge) is None:
            raise ValueError(f"unknown judge persona: {judge}")
        jmsg = ("Two assistants answered the same request. Reply with exactly LEFT or RIGHT — "
                "whichever answer is better, nothing else.\n\n"
                f"REQUEST:\n{prompt}\n\nLEFT:\n{lr['content']}\n\nRIGHT:\n{rr['content']}")
        jr = reg.complete(guard, judge, jmsg, max_tokens)
        judge_used = judge
        winner_side = "right" if (jr["content"] or "").strip().upper().startswith("RIGHT") else "left"
        winner_persona = rname if winner_side == "right" else lname

    # Durable record: the winner IS recorded here even when the caller is kept blind.
    _log_ab({"a": a, "b": b, "a_cost": ra["cost"], "b_cost": rb["cost"],
             "blind": bool(blind), "judge": judge_used,
             "winner_side": winner_side, "winner_persona": winner_persona})

    def side(r, name):
        if blind:
            return {"content": r["content"], "cost": r["cost"]}
        return {"content": r["content"], "cost": r["cost"], "persona": name,
                "final_model": r["final_model"], "trace": r["trace"]}

    resp = {"blind": bool(blind), "left": side(lr, lname), "right": side(rr, rname)}
    if judge_used:
        resp["judge_persona"] = judge_used
        resp["winner_side"] = winner_side
        if not blind:
            resp["winner_persona"] = winner_persona
    if not blind:
        resp["mapping"] = {"left": lname, "right": rname}
    return resp


def dispatch(reg, guard, name, args):
    if name == "list_personas":
        return {"personas": reg.listing(), "roles": reg.roles}
    if name == "complete":
        return reg.complete(guard, args["persona"], args["prompt"], args.get("max_tokens"))
    if name == "ab":
        return _tool_ab(reg, guard, args)
    if name == "impersonate":
        reg.impersonate(args["alias"], args["backing"])
        return {"alias": args["alias"], "backing": args["backing"], "ok": True}
    raise ValueError(f"unknown tool: {name}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def handle(reg, guard, req):
    mid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        return _ok(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                         "serverInfo": {"name": "tier-bench-personas", "version": "0.1.0"}})
    if method == "notifications/initialized":
        return None  # notification: no response
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = dispatch(reg, guard, name, args)
            return _ok(mid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except Exception as e:  # tool error → MCP isError result, loop survives
            return _ok(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})

    if mid is None:
        return None  # unknown notification — ignore
    return _err(mid, -32601, f"method not found: {method}")


def main():
    reg = personas.Registry()
    guard = personas.make_guard()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(reg, guard, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
