from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    row["timestamp"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
