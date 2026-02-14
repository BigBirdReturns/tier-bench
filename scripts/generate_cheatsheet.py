"""
Generate an HTML cheatsheet from models.json and (optionally) benchmark results.

Usage:
    python scripts/generate_cheatsheet.py
    python scripts/generate_cheatsheet.py --results harness_results.jsonl
    python scripts/generate_cheatsheet.py --out docs/cheatsheet.html

Reads: models.json (required), harness_results.jsonl (optional)
Writes: cheatsheet.html (or --out path)
"""
from __future__ import annotations

import argparse
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


def generate_html(models: dict, results: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    has_results = bool(results)

    # Sort models by total cost
    sorted_models = sorted(models.items(), key=lambda x: x[1].get("input_per_1M", 0) + x[1].get("output_per_1M", 0))

    # Build model rows
    model_rows = []
    for name, info in sorted_models:
        inp = info.get("input_per_1M", 0)
        out = info.get("output_per_1M", 0)
        provider = info.get("provider", "?")
        ceiling = info.get("tier_ceiling", "?")
        total = inp + out
        is_local = (total == 0)

        cost_cell = "FREE (local)" if is_local else f"${inp:.2f} / ${out:.2f}"
        total_cell = "—" if is_local else f"${total:.2f}"

        # Benchmark results if available
        result_cells = ""
        if has_results:
            for tier_name in ["T0", "T1", "T2", "T3"]:
                r = results.get(name, {}).get(tier_name)
                if r and r["attempts"] > 0:
                    rate = r["successes"] / r["attempts"]
                    color = "#4ade80" if rate >= 0.8 else "#fbbf24" if rate >= 0.5 else "#f87171"
                    result_cells += f'<td style="color:{color};font-weight:bold">{rate:.0%} ({r["successes"]}/{r["attempts"]})</td>'
                else:
                    result_cells += '<td style="color:#666">—</td>'

        model_rows.append(f"""
        <tr>
          <td><strong>{name}</strong></td>
          <td>{provider}</td>
          <td>{cost_cell}</td>
          <td>{total_cell}</td>
          <td><strong>{ceiling}</strong></td>
          {result_cells}
        </tr>""")

    result_headers = ""
    if has_results:
        result_headers = '<th>T0 Pass</th><th>T1 Pass</th><th>T2 Pass</th><th>T3 Pass</th>'

    tier_rows = ""
    for tier_name, label in TIER_LABELS.items():
        tier_rows += f"<tr><td><strong>{tier_name}</strong></td><td>{label}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tier Bench — Model Routing Cheatsheet</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0d1117; color: #c9d1d9; padding: 24px; line-height: 1.5; }}
  h1 {{ color: #58a6ff; margin-bottom: 4px; font-size: 1.5rem; }}
  .meta {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 24px; }}
  h2 {{ color: #79c0ff; margin: 24px 0 12px; font-size: 1.1rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 0.85rem; }}
  th {{ background: #161b22; color: #58a6ff; text-align: left; padding: 8px 12px;
       border-bottom: 2px solid #30363d; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #21262d; }}
  tr:hover {{ background: #161b22; }}
  .free {{ color: #4ade80; font-weight: bold; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
             padding: 16px; margin-bottom: 20px; }}
  .note {{ color: #8b949e; font-size: 0.8rem; font-style: italic; }}
  .add-model {{ background: #1f2937; border: 1px dashed #30363d; border-radius: 8px;
               padding: 16px; margin-top: 20px; }}
  code {{ background: #1f2937; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; }}
  pre {{ background: #1f2937; padding: 12px; border-radius: 6px; overflow-x: auto;
        font-size: 0.8rem; margin: 8px 0; }}
  @media print {{ body {{ background: white; color: black; }}
                  th {{ background: #f0f0f0; color: #333; }} }}
</style>
</head>
<body>

<h1>Model Routing Cheatsheet</h1>
<p class="meta">Generated {now} from models.json{'&nbsp;+&nbsp;harness_results.jsonl' if has_results else ''}</p>

<div class="section">
<h2>Tier Definitions</h2>
<table>
<tr><th>Tier</th><th>Description</th></tr>
{tier_rows}
</table>
</div>

<div class="section">
<h2>Model Registry ({len(models)} models)</h2>
<p class="note">Sorted by total cost. Costs are per 1M tokens (input / output).</p>
<table>
<tr>
  <th>Model</th>
  <th>Provider</th>
  <th>Cost (in / out)</th>
  <th>Total $/1M</th>
  <th>Ceiling</th>
  {result_headers}
</tr>
{''.join(model_rows)}
</table>
</div>

{'<div class="section"><h2>Benchmark Results</h2><p class="note">Pass rates from harness_results.jsonl. Green ≥80%, yellow ≥50%, red &lt;50%.</p></div>' if has_results else '<div class="section"><h2>Benchmark Results</h2><p>No benchmark data yet. The model registry above shows pricing and tier ceilings. Clone the repo and run the benchmark to add empirical pass rates.</p></div>'}

<div class="add-model">
<h2>Adding a Model</h2>
<p>Edit <code>models.json</code> and add an entry:</p>
<pre>
"my-cool-model": {{
  "provider": "ollama",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T1"
}}
</pre>
<p>For HuggingFace models via Ollama: <code>ollama pull hf.co/username/model</code></p>
<p>For any OpenAI-compatible endpoint (LMStudio, vLLM, etc.):</p>
<pre>
"my-vllm-model": {{
  "provider": "openai-compat",
  "base_url": "http://localhost:8000/v1",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T2"
}}
</pre>
<p>Then: <code>python orchestrator.py --benchmark T0</code> to test it, and <code>python scripts/generate_cheatsheet.py --results harness_results.jsonl</code> to update this page.</p>
</div>

</body>
</html>"""
    return html


def main():
    ap = argparse.ArgumentParser(description="Generate cost-to-task HTML cheatsheet")
    ap.add_argument("--models", default="models.json", help="Path to models.json")
    ap.add_argument("--results", default=None, help="Path to harness_results.jsonl (optional)")
    ap.add_argument("--out", default="cheatsheet.html", help="Output HTML path")
    args = ap.parse_args()

    models = load_models(Path(args.models))
    results = load_results(Path(args.results)) if args.results else {}

    html = generate_html(models, results)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"✓ Generated {args.out} ({len(models)} models" +
          (f", {sum(sum(t['attempts'] for t in m.values()) for m in results.values())} benchmark runs" if results else "") +
          ")")


if __name__ == "__main__":
    main()
