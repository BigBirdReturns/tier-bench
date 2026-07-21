from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.desk_harvest import harvested_orchestration  # noqa: E402


def main() -> int:
    value = harvested_orchestration(
        ROOT,
        {
            "arms": {
                "arm_b": {
                    "model_id": "qwen3.5:9b-q4_K_M",
                    "surface": "ollama-local-text-emit",
                }
            }
        },
    )
    lanes = {lane["id"]: lane for lane in value["lanes"]}
    assert lanes["sol"]["role"] == "top driver"
    assert lanes["qwen"]["state"] == "ready"
    assert lanes["spark"]["state"] == "gated"
    assert all(set(lane) == {"id", "label", "role", "state", "detail", "evidence"} for lane in lanes.values())
    assert set(value["custody"]) == {"admission", "anchor", "referee"}
    print("PASS - harvested orchestration exposes roles and only manifest-ready writers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
