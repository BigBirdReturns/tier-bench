"""
Persona layer — models and driver-composites behind one interface.

A *persona* turns a prompt into a completion. Two kinds ship live:

  ModelPersona   one per model in models.json. complete() is one call.
  DriverPersona  one per driver_repair composite. The cheap "hands" model
                 drafts; the frontier "driver" model REVIEWS the draft (replies
                 PASS, or the fix). When the draft is good the driver only reads
                 — a short "PASS" — instead of regenerating the whole answer.
                 That is why the composite can be cheaper than the frontier
                 alone: judgment tokens are cheaper than generation tokens.

cascade / best_of_n composites are validator-bound (they need a task's
deterministic validators to pick a winner), so they are NOT live personas here
— a raw chat prompt has no validator. They are listed as benchmark-only.

Every model call funnels through _invoke(), the single seam the mock backend
replaces so the whole stack is testable with no API keys (TIER_BENCH_MOCK=1).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import json  # noqa: E402

_DRIVER_SPEC = _REPO / "driver" / "README.md"

_VERIFY_MARKER = "reply with exactly the single word PASS"


# ── registry access ────────────────────────────────────────────────────
def _load_registry():
    reg = json.loads((_REPO / "models.json").read_text(encoding="utf-8"))
    return reg.get("models", {}), reg.get("roles", {})


# ── mock backend (keyless testing) ─────────────────────────────────────
# Illustrative, not real pricing — mock exists to prove the plumbing. But it
# weights OUTPUT over input, because that is where the driver-persona economy
# lives: a short "PASS" review is cheap even from a frontier model, while a
# full generation is dear. So the composite genuinely undercuts the frontier
# when the cheap draft holds — and costs about the same when it must repair.
_MOCK_RATES = [  # $ per 1k output chars
    (("fable", "opus", "gpt-5.5", "gpt-5.2", "gpt-5.1", "gemini-3.1-pro", "-large"), 0.050),
    (("sonnet", "gpt-5", "devstral", "gemini-3.5"), 0.015),
    (("haiku", "mini", "nano", "flash", "-small", "nemo"), 0.004),
]


def _mock_cost(model: str, in_len: int, out_len: int) -> float:
    rate = 0.020
    m = model.lower()
    for subs, r in _MOCK_RATES:
        if any(s in m for s in subs):
            rate = r
            break
    # input billed at a quarter weight, output full — output is what costs.
    return round(rate * (in_len * 0.25 + out_len) / 1000.0, 6)


def _mock_invoke(model, messages, system):
    user = messages[-1].get("content", "") if messages else ""
    # System (the driver role spec) is a fixed prompt providers cache, so bill
    # it lightly — otherwise mock unfairly penalizes the driver persona for
    # re-sending its spec each review.
    in_len = sum(len(msg.get("content", "")) for msg in messages) + (int(len(system) * 0.1) if system else 0)
    if system and _VERIFY_MARKER in user:
        # Driver review call. Extract the original request; PASS the easy ones,
        # repair the rest, so tests hit both branches deterministically.
        req = user.split("USER REQUEST:", 1)[1] if "USER REQUEST:" in user else user
        if "easy" in req.lower():
            content = "PASS"
        else:
            content = f"[{model}] repaired: " + " ".join(req.split())[:80]
    elif _VERIFY_MARKER in user and "REQUEST:" in user and "LEFT:" in user:
        # Judge call — deterministic pick for testability.
        content = "LEFT"
    elif "Reply with exactly LEFT or RIGHT" in user:
        content = "LEFT"
    else:
        content = f"[{model}] " + " ".join(user.split())[:80]
    out_len = len(content)
    return {"content": content, "cost": _mock_cost(model, in_len, out_len), "status": "ok",
            "in_tok": in_len // 4, "out_tok": max(1, out_len // 4)}  # ~4 chars/token


def _invoke(guard, model, messages, system=None, max_tokens=None):
    """The one seam. Mock when TIER_BENCH_MOCK is set, else the real guard."""
    if os.environ.get("TIER_BENCH_MOCK"):
        return _mock_invoke(model, messages, system)
    res = guard.call(messages=messages, model=model, system=system, max_output_tokens=max_tokens)
    usage = res.get("usage") or {}
    return {
        "content": res.get("content"),
        "cost": float(res.get("cost", 0.0) or 0.0),
        "status": res.get("status", "error"),
        "reason": res.get("reason"),
        "in_tok": int(usage.get("input_tokens", 0) or 0),
        "out_tok": int(usage.get("output_tokens", 0) or 0),
    }


def make_guard():
    """Real mode needs a CostGuard; mock mode never touches it."""
    if os.environ.get("TIER_BENCH_MOCK"):
        return None
    try:
        from cost_guard import CostGuard
        return CostGuard()
    except Exception:
        return None


# ── personas ───────────────────────────────────────────────────────────
class ModelPersona:
    kind = "model"

    def __init__(self, name, model_id=None):
        self.name = name
        self.model_id = model_id or name

    def complete(self, guard, prompt, max_tokens=None):
        r = _invoke(guard, self.model_id, [{"role": "user", "content": prompt}], None, max_tokens)
        cost = round(r["cost"], 6)
        in_tok, out_tok = r.get("in_tok", 0), r.get("out_tok", 0)
        return {
            "persona": self.name,
            "final_model": self.model_id,
            "content": r["content"],
            "cost": cost,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "status": r["status"],
            "trace": [{"step": "model", "model": self.model_id, "cost": cost,
                       "in_tok": in_tok, "out_tok": out_tok, "status": r["status"]}],
        }


class DriverPersona:
    kind = "driver"

    def __init__(self, name, driver, hands, max_repairs=1):
        self.name = name
        self.driver = driver
        self.hands = hands
        self.max_repairs = max(int(max_repairs), 1)

    def complete(self, guard, prompt, max_tokens=None):
        spec = _DRIVER_SPEC.read_text(encoding="utf-8") if _DRIVER_SPEC.exists() else "You are the driver."
        trace = []
        total = 0.0
        in_sum = out_sum = 0

        def _step(kind, model, r, **extra):
            nonlocal total, in_sum, out_sum
            total += r["cost"]
            in_sum += r.get("in_tok", 0)
            out_sum += r.get("out_tok", 0)
            trace.append({"step": kind, "model": model, "cost": round(r["cost"], 6),
                          "in_tok": r.get("in_tok", 0), "out_tok": r.get("out_tok", 0),
                          "status": r["status"], **extra})

        # 1. cheap hands draft
        d = _invoke(guard, self.hands, [{"role": "user", "content": prompt}], None, max_tokens)
        current = d["content"] or ""
        final_model = self.hands
        _step("hands_draft", self.hands, d)

        # 2. driver review / repair, bounded
        for _ in range(self.max_repairs):
            vmsg = (
                "You are the driver reviewing a cheaper model's answer. "
                f"USER REQUEST:\n{prompt}\n\n"
                f"CHEAPER MODEL'S ANSWER:\n{current}\n\n"
                "If the answer is correct, complete, and honest, reply with exactly the single word PASS. "
                "Otherwise reply with the corrected, complete answer (no preamble)."
            )
            v = _invoke(guard, self.driver, [{"role": "user", "content": vmsg}], spec, max_tokens)
            reply = (v["content"] or "").strip()
            if reply.startswith("PASS"):
                _step("driver_verify", self.driver, v, verdict="pass")
                break
            current = v["content"] or current
            final_model = self.driver
            _step("driver_repair", self.driver, v)

        return {
            "persona": self.name,
            "final_model": final_model,
            "content": current,
            "cost": round(total, 6),
            "input_tokens": in_sum,
            "output_tokens": out_sum,
            "status": "ok",
            "trace": trace,
        }


# ── registry with impersonation aliases ────────────────────────────────
class Registry:
    def __init__(self):
        models, roles = _load_registry()
        self.models = models
        self.roles = roles
        self.personas = {}
        for mid in models:
            self.personas[mid] = ModelPersona(mid)
        # driver_repair composites become live driver personas
        from harness.composites import load_composites
        self._benchmark_only = []
        for comp in load_composites():
            if comp.strategy == "driver_repair" and comp.driver and comp.members:
                self.personas[comp.name] = DriverPersona(comp.name, comp.driver, comp.members[0], comp.max_repairs)
            elif comp.strategy in ("cascade", "best_of_n"):
                self._benchmark_only.append((comp.name, comp.strategy))
        self.aliases = {}  # alias -> backing persona name

    def resolve(self, name):
        seen = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return self.personas.get(name)

    def impersonate(self, alias, backing):
        if backing not in self.personas and backing not in self.aliases:
            raise ValueError(f"unknown backing persona: {backing}")
        if alias == backing:
            raise ValueError("alias and backing are the same")
        self.aliases[alias] = backing

    def complete(self, guard, persona_name, prompt, max_tokens=None):
        p = self.resolve(persona_name)
        if p is None:
            raise ValueError(f"unknown persona: {persona_name}")
        out = p.complete(guard, prompt, max_tokens)
        out["persona"] = persona_name  # present under the requested (possibly alias) name
        return out

    def _available(self, p):
        if os.environ.get("TIER_BENCH_MOCK"):
            return True
        from cost_guard import model_available
        if isinstance(p, DriverPersona):
            return model_available(p.driver) and model_available(p.hands)
        return model_available(p.model_id)

    def listing(self):
        out = []
        for name, p in sorted(self.personas.items()):
            if isinstance(p, DriverPersona):
                out.append({"name": name, "kind": "driver",
                            "backing": f"driver={p.driver} · hands={p.hands}",
                            "available": self._available(p),
                            "note": "cheap hands draft, frontier reviews (PASS or fix)"})
            else:
                out.append({"name": name, "kind": "model", "backing": p.model_id,
                            "available": self._available(p), "note": ""})
        for name, strat in self._benchmark_only:
            out.append({"name": name, "kind": "composite", "backing": strat, "available": False,
                        "note": "benchmark-only (needs a task validator); not a live persona"})
        return out
