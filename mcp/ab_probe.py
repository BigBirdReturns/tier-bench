#!/usr/bin/env python3
"""
A/B probe — run a batch of prompts through two personas and compare output
tokens, cost, and (optionally) blind-judged quality. Built for the experiment:
give someone a frontier key, run the frontier ALONE vs a driver-composite that
only lets the frontier REVIEW, and measure how many frontier output tokens the
orchestration saves while quality holds.

    export ANTHROPIC_API_KEY=sk-ant-...            # whatever your personas need
    python3 mcp/ab_probe.py \
        --a claude-fable-5 \
        --b driver:fable+haiku \
        --judge claude-sonnet-4-5 \
        --prompts my_prompts.txt \
        --out results.jsonl

Then send results.jsonl back — it aggregates into the same pipeline the site
renders. No key? TIER_BENCH_MOCK=1 runs the whole thing on a fake backend
(costs/tokens illustrative, not a measurement).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personas  # noqa: E402

DEFAULT_PROMPTS = [
    "Write a Python function that parses an ISO-8601 duration string into seconds, with docstring and edge-case handling.",
    "Refactor a 60-line god function that mixes validation, DB access, and formatting into clean units. Describe the split and give the code.",
    "Explain the tradeoffs between optimistic and pessimistic locking for a booking system, then recommend one and name what would change your mind.",
    "Given a failing test that asserts slugify('a--b') == 'a-b', find and fix the bug in a slugify implementation you write.",
]


def _focus_out_tok(result, model):
    """Output tokens attributable to `model` in this result (across its trace)."""
    return sum(s.get("out_tok", 0) for s in result.get("trace", []) if s.get("model") == model)


def main():
    ap = argparse.ArgumentParser(description="A/B two personas on a batch of prompts; compare tokens, cost, quality.")
    ap.add_argument("--a", required=True, help="persona A (e.g. the frontier alone: claude-fable-5)")
    ap.add_argument("--b", required=True, help="persona B (e.g. a composite: driver:fable+haiku)")
    ap.add_argument("--judge", help="optional persona to blind-judge which answer is better")
    ap.add_argument("--prompts", help="file with one prompt per line (defaults to a built-in set)")
    ap.add_argument("--out", default="ab_probe_results.jsonl", help="where to write the per-prompt records")
    ap.add_argument("--max-tokens", type=int, default=None)
    args = ap.parse_args()

    prompts = ([l.strip() for l in Path(args.prompts).read_text(encoding="utf-8").splitlines() if l.strip()]
               if args.prompts else DEFAULT_PROMPTS)

    reg = personas.Registry()
    guard = personas.make_guard()
    if reg.resolve(args.a) is None or reg.resolve(args.b) is None:
        sys.exit(f"unknown persona (see list_personas). a={args.a} b={args.b}")

    # The shared "frontier" whose token burn we're comparing: B's driver if B is
    # a composite, else A's model.
    bp = reg.resolve(args.b)
    focus = bp.driver if isinstance(bp, personas.DriverPersona) else reg.resolve(args.a).model_id

    rows = []
    tot = {"a_out": 0, "b_out": 0, "a_focus": 0, "b_focus": 0, "a_cost": 0.0, "b_cost": 0.0, "b_wins": 0, "judged": 0}
    print(f"\nfocus model (frontier under test): {focus}\n" + "=" * 78)
    for i, prompt in enumerate(prompts, 1):
        ra = reg.complete(guard, args.a, prompt, args.max_tokens)
        rb = reg.complete(guard, args.b, prompt, args.max_tokens)
        a_focus, b_focus = _focus_out_tok(ra, focus), _focus_out_tok(rb, focus)

        winner = None
        if args.judge:
            from server import _blind_order  # reuse the blind ordering
            (lr, ln), (rr, rn) = _blind_order(ra, args.a, rb, args.b)
            jmsg = ("Two assistants answered the same request. Reply with exactly LEFT or RIGHT — "
                    f"whichever is better.\n\nREQUEST:\n{prompt}\n\nLEFT:\n{lr['content']}\n\nRIGHT:\n{rr['content']}")
            jr = reg.complete(guard, args.judge, jmsg, args.max_tokens)
            side = "right" if (jr["content"] or "").strip().upper().startswith("RIGHT") else "left"
            winner = rn if side == "right" else ln
            tot["judged"] += 1
            if winner == args.b:
                tot["b_wins"] += 1

        tot["a_out"] += ra["output_tokens"]; tot["b_out"] += rb["output_tokens"]
        tot["a_focus"] += a_focus; tot["b_focus"] += b_focus
        tot["a_cost"] += ra["cost"]; tot["b_cost"] += rb["cost"]

        print(f"[{i}] {prompt[:56]!r}")
        print(f"    A {args.a:24s} out={ra['output_tokens']:5d}  {focus}={a_focus:5d}  ${ra['cost']:.4f}")
        print(f"    B {args.b:24s} out={rb['output_tokens']:5d}  {focus}={b_focus:5d}  ${rb['cost']:.4f}"
              + (f"   winner={winner}" if winner else ""))
        rows.append({"prompt": prompt, "focus_model": focus,
                     "a": {"persona": args.a, "output_tokens": ra["output_tokens"], "focus_out_tok": a_focus,
                           "cost": ra["cost"], "final_model": ra["final_model"], "trace": ra["trace"]},
                     "b": {"persona": args.b, "output_tokens": rb["output_tokens"], "focus_out_tok": b_focus,
                           "cost": rb["cost"], "final_model": rb["final_model"], "trace": rb["trace"]},
                     "judge": args.judge, "winner": winner})

    Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def pct(new, old):
        return f"{(1 - new / old) * 100:+.0f}%" if old else "n/a"

    print("=" * 78)
    print(f"{focus} OUTPUT TOKENS   A(alone)={tot['a_focus']}  B(orchestrated)={tot['b_focus']}  "
          f"=> {pct(tot['b_focus'], tot['a_focus'])} frontier generation")
    print(f"TOTAL COST           A=${tot['a_cost']:.4f}  B=${tot['b_cost']:.4f}  => {pct(tot['b_cost'], tot['a_cost'])} cost")
    if tot["judged"]:
        print(f"BLIND QUALITY        B won {tot['b_wins']}/{tot['judged']} (judge={args.judge})")
    print(f"\nwrote {len(rows)} rows to {args.out} — send it back to fold into the aggregate.")


if __name__ == "__main__":
    main()
