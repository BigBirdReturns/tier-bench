"""Human-readable Estate Lab reports derived from run receipts."""

from __future__ import annotations

import html
from typing import Any


def render_markdown(run: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Estate Lab run: {run['scenario']['title']}")
    lines.append("")
    lines.append(f"- Status: **{run['status'].upper()}**")
    lines.append(f"- Run: `{run['run_id']}`")
    lines.append(f"- Manifest: `{run['manifest_id']}`")
    lines.append(f"- Scenario: `{run['scenario']['id']}`")
    lines.append(f"- Execution mode: `{run['execution_mode']}`")
    lines.append(f"- Final state: `{run['final_state_hash']}`")
    lines.append("")
    lines.append("## Route and action outcomes")
    lines.append("")
    lines.append("| Step | Route | Outcome | Reason | State after |")
    lines.append("|---|---|---|---|---|")
    for step in run.get("steps", []):
        reason = step.get("reason") or ""
        lines.append(
            f"| `{step['step_id']}` | `{step['route_id']}` | `{step['outcome']}` | "
            f"{reason} | `{step['state_after_hash'][:16]}` |"
        )

    lines.append("")
    lines.append("## Routing trials")
    lines.append("")
    if run.get("routing_trials"):
        lines.append("| Trial | Result | Expected | Pass |")
        lines.append("|---|---|---|---|")
        for trial in run["routing_trials"]:
            lines.append(
                f"| `{trial['trial_id']}` | `{trial['actual']}` | `{trial['expected']}` | "
                f"{'yes' if trial['passed'] else 'no'} |"
            )
    else:
        lines.append("No routing trials were declared.")

    lines.append("")
    lines.append("## Fault trials")
    lines.append("")
    if run.get("fault_trials"):
        lines.append("| Trial | Fault | Actual | Expected | Pass |")
        lines.append("|---|---|---|---|---|")
        for trial in run["fault_trials"]:
            lines.append(
                f"| `{trial['trial_id']}` | `{trial['fault']}` | `{trial['actual']}` | "
                f"`{trial['expected']}` | {'yes' if trial['passed'] else 'no'} |"
            )
    else:
        lines.append("No fault trials were declared.")

    if run.get("equivalence"):
        lines.append("")
        lines.append("## Cross-adapter equivalence")
        lines.append("")
        eq = run["equivalence"]
        lines.append(f"State hashes equal: **{eq.get('state_hashes_equal', False)}**")
        lines.append("")
        lines.append(f"Output hashes equal: **{eq.get('output_hashes_equal', False)}**")
        lines.append("")
        lines.append(f"Debrief hashes equal: **{eq.get('debrief_hashes_equal', False)}**")

    lines.append("")
    lines.append("## Repository probes")
    lines.append("")
    probes = run.get("probes", [])
    if probes:
        lines.append("| Organ | Probe | Status | Exit | Evidence |")
        lines.append("|---|---|---|---|---|")
        for probe in probes:
            lines.append(
                f"| `{probe['organ_id']}` | `{probe['probe_id']}` | `{probe['status']}` | "
                f"{probe.get('exit_code', '')} | `{probe['evidence_class']}` |"
            )
    else:
        lines.append("Repository probes were not run for this receipt.")

    if run.get("failures"):
        lines.append("")
        lines.append("## Failures")
        lines.append("")
        for failure in run["failures"]:
            lines.append(f"- {failure}")

    lines.append("")
    lines.append("## Control question")
    lines.append("")
    lines.append(run["control_question"])
    lines.append("")
    return "\n".join(lines)


def render_html(run: dict[str, Any]) -> str:
    status = html.escape(run["status"])
    title = html.escape(run["scenario"]["title"])
    route_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(step['step_id'])}</code></td>"
        f"<td><code>{html.escape(step['route_id'])}</code></td>"
        f"<td>{html.escape(step['outcome'])}</td>"
        f"<td>{html.escape(step.get('reason') or '')}</td>"
        f"<td><code>{html.escape(step['state_after_hash'][:16])}</code></td>"
        "</tr>"
        for step in run.get("steps", [])
    )
    routing_cards = "".join(
        f"<article class='card {'pass' if trial['passed'] else 'fail'}'>"
        f"<h3>{html.escape(trial['trial_id'])}</h3>"
        f"<p>Actual <code>{html.escape(trial['actual'])}</code></p>"
        f"<p>Expected <code>{html.escape(trial['expected'])}</code></p>"
        "</article>"
        for trial in run.get("routing_trials", [])
    )
    fault_cards = "".join(
        f"<article class='card {'pass' if trial['passed'] else 'fail'}'>"
        f"<h3>{html.escape(trial['trial_id'])}</h3>"
        f"<p>{html.escape(trial['fault'])}</p>"
        f"<p><code>{html.escape(trial['actual'])}</code></p>"
        "</article>"
        for trial in run.get("fault_trials", [])
    )
    failures = "".join(f"<li>{html.escape(item)}</li>" for item in run.get("failures", []))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · AXM Estate Lab</title>
<style>
:root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
body {{ margin: 0; background: Canvas; color: CanvasText; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
header {{ border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent); padding-bottom: 24px; }}
h1 {{ margin: 0 0 8px; font-size: clamp(2rem, 6vw, 4.8rem); letter-spacing: -0.045em; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.pill {{ border: 1px solid currentColor; border-radius: 999px; padding: 5px 10px; font-size: .86rem; }}
section {{ margin-top: 34px; }}
table {{ width: 100%; border-collapse: collapse; overflow: auto; display: block; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid color-mix(in srgb, CanvasText 16%, transparent); text-align: left; white-space: nowrap; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.card {{ border: 1px solid color-mix(in srgb, CanvasText 18%, transparent); border-radius: 14px; padding: 14px; }}
.card.pass {{ border-inline-start: 5px solid #238636; }}
.card.fail {{ border-inline-start: 5px solid #d1242f; }}
code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .9em; }}
.control {{ font-size: 1.18rem; line-height: 1.55; max-width: 72ch; }}
</style>
</head>
<body>
<main>
<header>
<p>AXM Estate Lab</p>
<h1>{title}</h1>
<div class="meta">
<span class="pill">status: {status}</span>
<span class="pill">run: {html.escape(run['run_id'])}</span>
<span class="pill">mode: {html.escape(run['execution_mode'])}</span>
</div>
</header>
<section><h2>Route and action outcomes</h2>
<table><thead><tr><th>Step</th><th>Route</th><th>Outcome</th><th>Reason</th><th>State</th></tr></thead><tbody>{route_rows}</tbody></table>
</section>
<section><h2>Routing trials</h2><div class="grid">{routing_cards or '<p>No routing trials.</p>'}</div></section>
<section><h2>Fault trials</h2><div class="grid">{fault_cards or '<p>No fault trials.</p>'}</div></section>
<section><h2>Failures</h2><ul>{failures or '<li>None.</li>'}</ul></section>
<section><h2>Control question</h2><p class="control">{html.escape(run['control_question'])}</p></section>
</main>
</body>
</html>
"""
