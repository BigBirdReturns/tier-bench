from __future__ import annotations

from pathlib import Path

SYSTEM_RULES = """You are editing a repository file.
Return ONLY the full updated file content for the target file. No explanations. No markdown.
Do not change runtime behavior unless the task explicitly asks for it.
"""

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def render_prompt(template: str, fixture_root: Path, target_relpath: str, baseline: dict | None = None) -> str:
    target_path = fixture_root / target_relpath
    src = _read_text(target_path)

    # Include small, explicit context for multi-file fixtures (all .py except target)
    context_parts: list[str] = []
    for p in sorted(fixture_root.glob("*.py")):
        if p.name == Path(target_relpath).name:
            continue
        context_parts.append(f"=== {p.name} ===\n{_read_text(p)}")

    baseline = baseline or {}
    return template.format(
        target_relpath=target_relpath,
        file_content=src,
        context_files="\n\n".join(context_parts).strip(),
        baseline_rc=baseline.get("rc", ""),
        baseline_stdout=baseline.get("stdout", ""),
        baseline_stderr=baseline.get("stderr", ""),
    )
