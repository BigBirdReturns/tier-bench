from __future__ import annotations

from pathlib import Path

def _canon_dir(root: Path) -> Path:
    d = root / "tasks" / "_canonical"
    d.mkdir(parents=True, exist_ok=True)
    return d

def canonical_path(task_id: str, root: Path) -> Path:
    return _canon_dir(root) / f"{task_id}.py"

def load_canonical(task_id: str, root: Path) -> str | None:
    p = canonical_path(task_id, root)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")

def save_canonical(task_id: str, root: Path, content: str) -> None:
    p = canonical_path(task_id, root)
    p.write_text(content, encoding="utf-8")

def compare_to_canonical(task_id: str, root: Path, content: str) -> bool | None:
    canon = load_canonical(task_id, root)
    if canon is None:
        return None
    return canon == content
