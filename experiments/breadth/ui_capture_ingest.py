#!/usr/bin/env python3
"""Ingest raw ChatGPT UI capture packets into auditable breadth-sweep evidence."""
from __future__ import annotations

import argparse, ast, hashlib, json, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from experiments.breadth.ledger import log_call

TASK_GRADERS = {
    "task01_parse_duration": REPO / "experiments/tier-uplift/task01_parse_duration/hidden_tests.py",
    "task02_wildcard": REPO / "experiments/tier-uplift/task02_wildcard/hidden_oracle.py",
    "task06_select": REPO / "experiments/tier-uplift/task06_select/grader.py",
}
FUNCTION_NAMES = {"task01_parse_duration": "parse_duration", "task02_wildcard": "wildcard_match"}


def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def derive_label(pkt: dict[str, Any]) -> str:
    return pkt.get("selected_model_label") or f"{pkt.get('model_family','')} / {pkt.get('intelligence','')}"


def extract_json_candidate_lines(task_id: str, raw: str, packet: dict[str, Any] | None) -> tuple[str, str | None] | None:
    """Extract transport JSON outputs without treating JSON text as Python.

    The UI raw output remains the exact JSON string for provenance and raw hashing;
    only the candidate is reconstructed from candidate_lines by joining with newlines
    and appending one final newline.
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "candidate_lines" not in obj:
        return None
    expected = {"model_family", "intelligence", "trial", "task", "candidate_lines"}
    if set(obj) != expected:
        return "malformed_no_candidate", None
    if obj.get("task") != "task02_wildcard" or task_id != "task02_wildcard":
        return "malformed_no_candidate", None
    if obj.get("model_family") != "GPT-5.5" or obj.get("trial") != 2:
        return "malformed_no_candidate", None
    if obj.get("intelligence") not in {"Instant", "Medium", "High"}:
        return "malformed_no_candidate", None
    if packet is not None:
        if obj.get("model_family") != packet.get("model_family"):
            return "malformed_no_candidate", None
        if obj.get("intelligence") != packet.get("intelligence"):
            return "malformed_no_candidate", None
        if obj.get("trial") != packet.get("trial"):
            return "malformed_no_candidate", None
    lines = obj.get("candidate_lines")
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        return "malformed_no_candidate", None
    return "json_candidate_lines", "\n".join(lines) + "\n"


def classify_and_extract(task_id: str, raw: str, packet: dict[str, Any] | None = None) -> tuple[str, str | None]:
    raw = raw or ""
    if not raw.strip():
        return "malformed_no_candidate", None
    json_candidate = extract_json_candidate_lines(task_id, raw, packet)
    if json_candidate is not None:
        return json_candidate
    if task_id in FUNCTION_NAMES:
        fn = FUNCTION_NAMES[task_id]
        if re.match(rf"^\s*def\s+{re.escape(fn)}\s*\(", raw) and "```" not in raw:
            return "raw_function_only", raw.strip() + "\n"
        m = re.search(r"```(?:python)?\s*(.*?)```", raw, re.S | re.I)
        if m and f"def {fn}" in m.group(1):
            return "extractor_needed_markdown_fence", m.group(1).strip() + "\n"
        idx = raw.find(f"def {fn}")
        if idx >= 0:
            return "extractor_needed_prose", raw[idx:].strip() + "\n"
        return "malformed_no_candidate", None
    if task_id == "task06_select":
        pat = r"items\s*=\s*(\[[\s\S]*?\])\s*;?\s*k\s*=\s*(-?\d+)"
        m = re.fullmatch(r"\s*" + pat + r"\s*", raw)
        status = "counterexample_exact" if m else "counterexample_extracted"
        if not m:
            m = re.search(pat, raw)
        if not m:
            return "malformed_no_candidate", None
        candidate = f"items={m.group(1)}; k={m.group(2)}"
        try:
            items = ast.literal_eval(m.group(1)); k = int(m.group(2))
            if not isinstance(items, list) or not isinstance(k, int):
                return "malformed_no_candidate", None
        except Exception:
            return "malformed_no_candidate", None
        return status, candidate
    return "malformed_no_candidate", None


def grade(task_id: str, candidate: str) -> tuple[str, str, str | None]:
    if task_id in ("task01_parse_duration", "task02_wildcard"):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "candidate.py"; cp.write_text(candidate, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TASK_GRADERS[task_id]), str(cp)], cwd=REPO, text=True, capture_output=True, timeout=30)
        out = (proc.stdout + proc.stderr).strip()
        m = re.search(r"SCORE\s+(\d+)/(\d+)", out)
        if not m:
            return "error", out or "NO SCORE", None
        score = f"SCORE {m.group(1)}/{m.group(2)}"
        return ("pass" if m.group(1) == m.group(2) else "fail"), score, out
    if task_id == "task06_select":
        proc = subprocess.run([sys.executable, str(TASK_GRADERS[task_id]), "--check", candidate], cwd=REPO, text=True, capture_output=True, timeout=30)
        out = (proc.stdout + proc.stderr).strip()
        ok = "COUNTEREXAMPLE: True" in out
        return ("pass" if ok else "fail"), ("COUNTEREXAMPLE: True" if ok else "COUNTEREXAMPLE: False"), out
    return "error", "UNKNOWN TASK", None


def matrix_key_trial(trial: Any) -> str:
    return str(int(trial or 0))


def add_matrix(matrix: dict, row: dict) -> None:
    e = row.get("extra", {})
    task = row["task_id"]; fam = e.get("selected_model_family", ""); intel = e.get("selected_intelligence", ""); trial = matrix_key_trial(row.get("trial"))
    availability = "not_exposed_in_ui" if e.get("quota_status") == "not_exposed_in_ui" else ("blocked" if row["outcome"] == "blocked" else "available")
    matrix.setdefault(task, {}).setdefault(fam, {}).setdefault(intel, {})[trial] = {
        "availability": availability, "semantic_outcome": row["outcome"], "score": e.get("score"),
        "format_compliance": e.get("format_compliance"), "visible_thought_seconds": e.get("visible_thought_seconds"),
        "prompt_sha256": e.get("prompt_sha256"), "raw_output_sha256": e.get("raw_output_sha256"),
        "candidate_sha256": e.get("candidate_sha256"), "note": row.get("note", ""),
    }


def process_packet(pkt: dict[str, Any], ledger: Path) -> tuple[dict, dict]:
    fam, intel, label = pkt.get("model_family", ""), pkt.get("intelligence", ""), derive_label(pkt)
    prompt, raw = pkt.get("prompt_text", "") or "", pkt.get("raw_output", "") or ""
    task_id, phase = pkt.get("task_id", ""), pkt.get("phase", "solo")
    quota = pkt.get("quota_status", "") or ""
    prompt_hash, raw_hash = sha256_text(prompt), sha256_text(raw)
    candidate_hash = None; score = None; grade_output = None
    if phase == "availability" or quota == "not_exposed_in_ui":
        outcome, fmt, candidate = "blocked", "malformed_no_candidate", None
        note = "UI selector cell unavailable: not_exposed_in_ui"
    else:
        fmt, candidate = classify_and_extract(task_id, raw, pkt)
        if candidate is None:
            outcome, note = "error", "malformed_no_candidate; hidden grader not run"
        else:
            candidate_hash = sha256_text(candidate)
            outcome, score, grade_output = grade(task_id, candidate)
            note = score
    extra = {
        "surface": "chatgpt_ui_subscription", "selected_model_family": fam, "selected_intelligence": intel,
        "selected_model_label": label, "telemetry_class": "subscription_surface", "token_accounting": "unavailable",
        "cost_accounting": pkt.get("cost_accounting") or ("subscription_quota" if quota else "unavailable"),
        "quota_status": quota, "prompt_sha256": prompt_hash, "raw_output_sha256": raw_hash,
        "candidate_sha256": candidate_hash, "capture_id": pkt.get("capture_id"), "format_compliance": fmt,
        "extraction_status": "extracted" if candidate_hash else "none", "visible_thought_seconds": pkt.get("visible_thought_seconds"),
        "screenshot_sha256": pkt.get("screenshot_sha256"), "score": score, "grade_output": grade_output,
    }
    call = log_call(ledger, ts=datetime.now(timezone.utc).isoformat(), account="chatgpt_subscription", model=label,
                    tier="subscription", task_id=task_id, phase=phase, outcome=outcome, effort=intel,
                    input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.0,
                    latency_ms=0.0, trial=int(pkt.get("trial") or 0), note=note, **extra)
    row = json.loads(json.dumps(call, default=lambda o: o.__dict__))
    norm = dict(pkt); norm.update(extra); norm["outcome"] = outcome; norm["note"] = note
    return row, norm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("captures"); ap.add_argument("--ledger", default="experiments/breadth/run/subscription_ledger.jsonl")
    ap.add_argument("--normalized-out"); ap.add_argument("--matrix-out")
    a = ap.parse_args(); matrix = {}; norms = []
    with open(a.captures, encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            row, norm = process_packet(json.loads(line), Path(a.ledger)); add_matrix(matrix, row); norms.append(norm)
    if a.normalized_out:
        Path(a.normalized_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.normalized_out).write_text("".join(json.dumps(n, sort_keys=True)+"\n" for n in norms), encoding="utf-8")
    if a.matrix_out:
        Path(a.matrix_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.matrix_out).write_text(json.dumps(matrix, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"captures": len(norms), "ledger": a.ledger}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
