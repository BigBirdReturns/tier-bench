#!/usr/bin/env python3
"""
Harvest every token. Reconcile against the bill. Trust no number that doesn't.

"Use all the buffalo": every model call — regardless of account, tier, or effort
— appends one row here with its full economy. The ledger is append-only and
git-tracked (the blanket *.jsonl ignore is negated for experiments/**), so a run
cannot silently lose telemetry the way the earlier results.jsonl drop did.

The guarantee is `reconcile()`: the sum of per-call cost/tokens in the ledger
must match what the provider billed the account, within tolerance. If it does
not, a call went unlogged — a buffalo escaped — and NO downstream conclusion
(the breadth map, an escalation decision) may be trusted until it does. That is
the difference between "we measured the model" and "we think we did."

    from experiments.breadth.ledger import log_call, load, reconcile
    log_call("runs.jsonl", account="acct-B", model="claude-fable-5", tier="max",
             task_id="t06_select", phase="baseline", effort="xhigh",
             input_tokens=25383, output_tokens=1841, cost_usd=0.6346, outcome="pass")
    rows = load("runs.jsonl")
    print(reconcile(rows, billed_usd=0.63))   # from the account's usage dashboard
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Fields every call carries. Missing token/cost fields are 0.0, never dropped —
# a blank is a logged blank, not a silent gap.
_NUM = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
        "cost_usd", "latency_ms")


@dataclass
class Call:
    ts: str                      # RFC3339; caller stamps it (kept out of the logic for determinism)
    account: str                 # which billing account — escalation lives per account
    model: str                   # e.g. claude-haiku-4-5 / claude-fable-5
    tier: str                    # cheap | mid | frontier | max  (your billing rung)
    task_id: str
    phase: str                   # baseline | harness | probe | verify
    outcome: str                 # pass | fail | partial | error
    effort: str = ""             # low..max (Claude Code effort / reasoning tier)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    trial: int = 0               # which repeat (ceilings need K trials, not one)
    note: str = ""
    extra: dict = field(default_factory=dict)


def log_call(path: str | Path, **kw) -> Call:
    """Append one call to the ledger and return it. Unknown keys go to `extra`."""
    known = {f for f in Call.__dataclass_fields__}  # noqa
    extra = {k: kw.pop(k) for k in list(kw) if k not in known}
    call = Call(extra=extra, **kw)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(call), sort_keys=True) + "\n")
    return call


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def totals(rows: list[dict]) -> dict:
    """Roll up tokens + cost, overall and per (account, model, tier)."""
    overall = {k: 0.0 for k in _NUM}
    overall["calls"] = 0
    by: dict[tuple, dict] = {}
    for r in rows:
        overall["calls"] += 1
        for k in _NUM:
            overall[k] += float(r.get(k, 0) or 0)
        key = (r.get("account", ""), r.get("model", ""), r.get("tier", ""))
        cell = by.setdefault(key, {k: 0.0 for k in _NUM} | {"calls": 0})
        cell["calls"] += 1
        for k in _NUM:
            cell[k] += float(r.get(k, 0) or 0)
    return {"overall": overall, "by_account_model_tier": {"/".join(k): v for k, v in sorted(by.items())}}


def reconcile(rows: list[dict], billed_usd: float, account: Optional[str] = None,
              tol: float = 0.02) -> dict:
    """Ledger cost vs the account's billed cost. `ok` is False when a buffalo escaped.

    tol is fractional (0.02 = 2%). Provider rounding and unlogged system overhead
    live inside a small tolerance; anything past it means calls went unrecorded."""
    sel = [r for r in rows if account is None or r.get("account") == account]
    ledger_usd = round(sum(float(r.get("cost_usd", 0) or 0) for r in sel), 6)
    drift = round(ledger_usd - billed_usd, 6)
    frac = abs(drift) / billed_usd if billed_usd else (0.0 if ledger_usd == 0 else 1.0)
    return {
        "account": account or "*",
        "calls": len(sel),
        "ledger_usd": ledger_usd,
        "billed_usd": round(billed_usd, 6),
        "drift_usd": drift,
        "drift_frac": round(frac, 4),
        "tolerance": tol,
        "ok": frac <= tol,
        "verdict": "reconciled" if frac <= tol else
                   f"UNRECONCILED — {abs(drift):.4f} USD unaccounted ({frac*100:.1f}%); a call went unlogged",
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Roll up / reconcile a token ledger.")
    ap.add_argument("ledger")
    ap.add_argument("--billed", type=float, help="account-billed USD to reconcile against")
    ap.add_argument("--account", default=None)
    a = ap.parse_args()
    rows = load(a.ledger)
    print(json.dumps(totals(rows), indent=2))
    if a.billed is not None:
        print(json.dumps(reconcile(rows, a.billed, a.account), indent=2))
