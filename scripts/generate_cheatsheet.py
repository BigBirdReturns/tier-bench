"""
Generate an HTML cheatsheet from models.json and (optionally) benchmark results.

Usage:
    python scripts/generate_cheatsheet.py
    python scripts/generate_cheatsheet.py --results harness_results.jsonl
    python scripts/generate_cheatsheet.py --out docs/cheatsheet.html

Reads: models.json (required), harness_results.jsonl (optional)
Writes: cheatsheet.html (or --out path)

DOCTRINE: tier_ceiling in models.json is a HYPOTHESIS, not a fact -- someone typed
a guess when they added the model. This page must never let a guess pass for a
measurement. Every ceiling rendered here is tagged either "measured" (backed by
>=1 benchmark row hitting the pass-rate bar) or "hypothesis -- unverified" (nothing
backs it yet). See harness/metrics.py for the cost_per_success math this mirrors.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

TIER_LABELS = {
    "T0": "Clerical — format, lint, rename",
    "T1": "Junior — implement from spec",
    "T2": "Mid — debug, integrate",
    "T3": "Senior — review, refactor",
    "T4": "Staff — plan, decompose",
    "T5": "Principal — architecture",
}
TIER_ORDER = list(TIER_LABELS)  # dict preserves insertion order T0..T5

# A tier only counts as "cleared" at 2/3 pass rate -- one lucky attempt out of
# one isn't evidence, and this is the same bar a human would want before trusting
# a junior with the next tier up.
CEILING_PASS_NUM = 2
CEILING_PASS_DEN = 3


def esc(s) -> str:
    """Escape anything interpolated from models.json / results before it hits the page --
    both files are user-editable registry/log data, not trusted markup."""
    return html.escape(str(s), quote=True)


def load_models(path: Path) -> dict:
    raw = json.loads(path.read_text())
    return raw.get("models", {})


def load_results(path: Path) -> dict:
    """Parse harness_results.jsonl into {model: {tier: {attempts, successes, total_cost}}}."""
    stats: dict[str, dict[str, dict]] = {}
    if not path.exists():
        return stats
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        model = row.get("model", "?")
        tier = row.get("tier", "?")
        if model not in stats:
            stats[model] = {}
        if tier not in stats[model]:
            stats[model][tier] = {"attempts": 0, "successes": 0, "total_cost": 0.0}
        s = stats[model][tier]
        s["attempts"] += 1
        if row.get("pass") is True:
            s["successes"] += 1
        cost = row.get("actual_cost")
        if isinstance(cost, (int, float)):
            s["total_cost"] += cost
    return stats


def success_rate(s: dict) -> float:
    return s["successes"] / s["attempts"] if s.get("attempts") else 0.0


def cost_per_success(s: dict):
    """avg_cost/success_rate, mirroring harness/metrics.py::ModelTierStats.cost_per_success.
    Returns None (render as "—") when there are zero successes -- dividing by a zero
    success rate isn't "expensive", it's undefined, and pretending otherwise hides a
    model that has never once earned its cost."""
    if not s.get("attempts") or not s.get("successes"):
        return None
    avg_cost = s["total_cost"] / s["attempts"]
    return avg_cost / success_rate(s)


def fmt_cost(v) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "$0"
    return f"${v:.4f}" if v < 1 else f"${v:.2f}"


def measured_ceiling(model_stats: dict):
    """Highest tier where this model has >=1 attempt and a success_rate that clears
    2/3. Walk tiers top-down: a model that clears T3 but was never tried at T2 still
    gets credited for T3 -- the ceiling is about the highest verified bar, not an
    unbroken staircase. Multiplication (successes*3 >= attempts*2) instead of a float
    division dodges 2/3 landing on 0.6666666...7 and missing its own threshold."""
    for tier in reversed(TIER_ORDER):
        s = model_stats.get(tier)
        if s and s["attempts"] > 0 and s["successes"] * CEILING_PASS_DEN >= s["attempts"] * CEILING_PASS_NUM:
            return tier, s["successes"], s["attempts"]
    return None, 0, 0


def ceiling_cell(hyp_tier, model_stats: dict) -> str:
    """Renders the one thing this whole rewrite exists to fix: a tier_ceiling can
    only ever be shown as either a green measured chip (with the pass rate that
    earned it) or a grey hypothesis chip (an admitted guess) -- never a bare bold
    string that looks like a fact."""
    tier, succ, att = measured_ceiling(model_stats)
    if tier is not None:
        rate = succ / att
        cell = f'<span class="chip c-green">{esc(tier)} measured — {rate:.0%} ({succ}/{att})</span>'
        if hyp_tier in TIER_ORDER and hyp_tier != tier:
            # The registry's guess and the measured floor disagree -- surface it instead
            # of quietly letting the green chip imply the guess was right.
            cell += f'<div class="small muted">registry guessed {esc(hyp_tier)}</div>'
        return cell
    label = esc(hyp_tier) if hyp_tier in TIER_ORDER else "?"
    return f'<span class="chip c-grey">{label} · hypothesis — unverified</span>'


def rate_chip(succ: int, att: int) -> str:
    rate = succ / att if att else 0.0
    cls = "c-green" if rate >= CEILING_PASS_NUM / CEILING_PASS_DEN else ("c-yellow" if rate > 0 else "c-red")
    return f'<span class="chip {cls}">{rate:.0%} ({succ}/{att})</span>'


def generate_html(models: dict, results: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    has_results = bool(results)

    # Sort registry rows by total sticker cost, same as before -- cheapest first is
    # the useful default when you're scanning for "what could replace what I pay for".
    sorted_models = sorted(models.items(), key=lambda x: x[1].get("input_per_1M", 0) + x[1].get("output_per_1M", 0))

    measured_count = sum(1 for name in models if measured_ceiling(results.get(name, {}))[0] is not None)
    total_count = len(models)

    # Registry table: pricing + the one ceiling chip. No per-tier pass columns here --
    # those live in the cost-per-success section below so the real metric isn't a
    # side column bolted onto a pricing table.
    model_rows = []
    for name, info in sorted_models:
        inp = info.get("input_per_1M", 0)
        out = info.get("output_per_1M", 0)
        provider = info.get("provider", "?")
        hyp_tier = info.get("tier_ceiling", "?")
        total = inp + out
        is_local = total == 0

        cost_cell = "FREE (local)" if is_local else f"${inp:.2f} / ${out:.2f}"
        total_cell = "—" if is_local else f"${total:.2f}"

        model_rows.append(f"""
      <tr>
        <td><strong>{esc(name)}</strong></td>
        <td>{esc(provider)}</td>
        <td>{cost_cell}</td>
        <td>{total_cell}</td>
        <td>{ceiling_cell(hyp_tier, results.get(name, {}))}</td>
      </tr>""")

    tier_rows = "".join(
        f"<tr><td><code>{esc(t)}</code></td><td>{esc(label)}</td></tr>\n"
        for t, label in TIER_LABELS.items()
    )

    # Cost-per-success section: one table per tier that actually has data, over every
    # model/composite that appears in results -- including strategies like
    # "cascade:x>y" that have no models.json entry and therefore no hypothesis at all.
    cost_section = ""
    if has_results:
        all_names = sorted(set(models) | set(results))
        unregistered = sorted(set(results) - set(models))
        tier_tables = []
        for tier in TIER_ORDER:
            rows = []
            for name in all_names:
                s = results.get(name, {}).get(tier)
                if s and s["attempts"] > 0:
                    rows.append((name, s))
            if not rows:
                continue
            # Cheapest-per-success first; models with zero successes (cps=None) sort
            # last -- they haven't earned a place ahead of anything that actually works.
            rows.sort(key=lambda r: (cost_per_success(r[1]) is None, cost_per_success(r[1]) or 0.0))
            body = ""
            for name, s in rows:
                avg = s["total_cost"] / s["attempts"] if s["attempts"] else 0.0
                unreg_tag = ' <span class="chip c-grey">not in registry</span>' if name in unregistered else ""
                body += f"""
      <tr>
        <td>{esc(name)}{unreg_tag}</td>
        <td>{rate_chip(s["successes"], s["attempts"])}</td>
        <td>{fmt_cost(avg)}</td>
        <td><strong>{fmt_cost(cost_per_success(s))}</strong></td>
      </tr>"""
            tier_tables.append(f"""
    <h3><code>{esc(tier)}</code> — {esc(TIER_LABELS.get(tier, ""))}</h3>
    <div class="tblwrap"><table>
      <tr><th>model / composite</th><th>success rate</th><th>avg cost / attempt</th><th>cost per success</th></tr>
      {body}
    </table></div>""")

        unreg_note = ""
        if unregistered:
            names = ", ".join(f"<code>{esc(n)}</code>" for n in unregistered)
            unreg_note = f"""
    <p class="small muted">{names} — {"appears" if len(unregistered) == 1 else "appear"} in the results file but
    {"has" if len(unregistered) == 1 else "have"} no <code>models.json</code> entry (composites/strategies aren't
    priced as a single sticker price). Real cost is whatever the underlying calls summed to.</p>"""

        cost_section = f"""
<section id="cost-per-success">
  <div class="wrap">
    <div class="kicker">The real metric</div>
    <h2>Cost per success, by tier</h2>
    <p class="lede">Sticker price tells you what a token costs. This tells you what a <em>passing task</em> costs —
    <code>cost_per_success = avg_cost / success_rate</code>, same formula the harness itself computes
    (<code>harness/metrics.py</code>). "—" means zero successes: no amount of cheapness makes that a bargain.</p>
    {"".join(tier_tables)}
    {unreg_note}
  </div>
</section>"""

    # Honest banner: the whole reason this file was rewritten. No results = a blunt
    # callout, not a footnote. With results = an honest fraction, not a victory lap.
    if has_results:
        banner_text = (
            f"<b>{measured_count} of {total_count}</b> model-tier ceilings are measured; "
            "the rest are unverified hypotheses."
        )
    else:
        banner_text = (
            "Nothing on this page is measured yet. Every ceiling below is the registry's guess. "
            "Run <code>python orchestrator.py --benchmark all</code> to replace guesses with numbers."
        )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tier Bench — Model Routing Cheatsheet</title>
<style>
  :root{{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2129; --line:#2d333b;
    --ink:#e6edf3; --ink2:#9da7b3; --muted:#6e7a87;
    --green:#3fb950; --yellow:#d29922; --red:#f85149; --blue:#58a6ff;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
  .wrap{{max-width:960px;margin:0 auto;padding:0 20px}}
  a{{color:var(--blue);text-decoration:none}} a:hover{{text-decoration:underline}}
  code,pre{{font-family:var(--mono)}}
  code{{background:var(--panel2);padding:1px 6px;border-radius:4px;font-size:.9em}}
  pre{{background:var(--panel);border:1px solid var(--line);border-radius:8px;
      padding:14px 16px;overflow-x:auto;font-size:13.5px;line-height:1.55;margin:14px 0}}
  pre code{{background:none;padding:0}}
  h1{{font-size:1.9rem;line-height:1.2;margin:0 0 6px}}
  h2{{font-size:1.3rem;margin:0 0 6px;letter-spacing:-.01em}}
  h3{{font-size:1.02rem;margin:20px 0 6px}}
  section{{padding:32px 0;border-top:1px solid var(--line)}}
  section:first-of-type{{border-top:none;padding-top:36px}}
  .kicker{{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}}
  .lede{{color:var(--ink2);font-size:1.02rem;max-width:52em;margin-bottom:4px}}
  .meta{{color:var(--muted);font-size:.85rem;margin-bottom:18px}}
  .muted{{color:var(--muted)}} .small{{font-size:.86rem}}
  table{{border-collapse:collapse;width:100%;font-size:.88rem}}
  .tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:14px 0}}
  th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}
  th{{background:var(--panel);font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2);white-space:nowrap}}
  tr:last-child td{{border-bottom:none}}
  .chip{{display:inline-block;font-family:var(--mono);font-size:11.5px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}}
  .c-green{{color:var(--green);border-color:color-mix(in srgb,var(--green) 45%,transparent)}}
  .c-yellow{{color:var(--yellow);border-color:color-mix(in srgb,var(--yellow) 45%,transparent)}}
  .c-red{{color:var(--red);border-color:color-mix(in srgb,var(--red) 45%,transparent)}}
  .c-grey{{color:var(--muted)}}
  .callout{{border-left:3px solid var(--yellow);background:var(--panel);padding:14px 18px;border-radius:0 8px 8px 0;margin:16px 0;color:var(--ink2);font-size:.98rem}}
  .callout b{{color:var(--ink)}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:14px}}
</style>
</head>
<body>

<section>
  <div class="wrap">
    <div class="kicker"><a href="index.html">&larr; Tier Bench</a></div>
    <h1>Model Routing Cheatsheet</h1>
    <p class="meta">Generated {now} from models.json{" + harness_results.jsonl" if has_results else ""}</p>
    <div class="callout">{banner_text}</div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="kicker">Reference</div>
    <h2>Tier definitions</h2>
    <div class="tblwrap"><table>
      <tr><th>Tier</th><th>Description</th></tr>
      {tier_rows}
    </table></div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="kicker">Registry ({len(models)} models)</div>
    <h2>Pricing &amp; claimed ceiling</h2>
    <p class="lede">Sorted by total sticker cost per 1M tokens (input + output). The Ceiling column is tagged —
    green means a benchmark row backs it, grey means it's still the registry author's guess.</p>
    <div class="tblwrap"><table>
      <tr>
        <th>Model</th>
        <th>Provider</th>
        <th>Cost (in / out)</th>
        <th>Total $/1M</th>
        <th>Ceiling</th>
      </tr>
      {"".join(model_rows)}
    </table></div>
  </div>
</section>
{cost_section}
<section>
  <div class="wrap">
    <div class="kicker">Extend it</div>
    <h2>Adding a model</h2>
    <div class="card">
      <p>Edit <code>models.json</code> and add an entry:</p>
      <pre><code>"my-cool-model": {{
  "provider": "ollama",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T1"
}}</code></pre>
      <p>For HuggingFace models via Ollama: <code>ollama pull hf.co/username/model</code></p>
      <p>For any OpenAI-compatible endpoint (LMStudio, vLLM, etc.):</p>
      <pre><code>"my-vllm-model": {{
  "provider": "openai-compat",
  "base_url": "http://localhost:8000/v1",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T2"
}}</code></pre>
      <p>The <code>tier_ceiling</code> you write is a hypothesis, nothing more. Then:</p>
      <pre><code>python orchestrator.py --benchmark T0
python scripts/generate_cheatsheet.py --results harness_results.jsonl</code></pre>
      <p class="small muted">Re-running the generator is what turns the grey chip into a green one — or proves the
      guess wrong, which is the point.</p>
    </div>
  </div>
</section>

</body>
</html>"""
    return html_out


def main():
    ap = argparse.ArgumentParser(description="Generate cost-to-task HTML cheatsheet")
    ap.add_argument("--models", default="models.json", help="Path to models.json")
    ap.add_argument("--results", default=None, help="Path to harness_results.jsonl (optional)")
    ap.add_argument("--out", default="cheatsheet.html", help="Output HTML path")
    args = ap.parse_args()

    models = load_models(Path(args.models))
    results = load_results(Path(args.results)) if args.results else {}

    html_out = generate_html(models, results)
    Path(args.out).write_text(html_out, encoding="utf-8")
    print(f"✓ Generated {args.out} ({len(models)} models" +
          (f", {sum(sum(t['attempts'] for t in m.values()) for m in results.values())} benchmark runs" if results else "") +
          ")")


if __name__ == "__main__":
    main()
