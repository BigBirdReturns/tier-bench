from pathlib import Path

EXPECTED = b"DESK_DRIVER_LOOP_LIVE\n"
PROOF = Path(__file__).resolve().parents[1] / "experiments" / "desk_driver_live_smoke" / "proof.txt"


def main() -> int:
    try:
        actual = PROOF.read_bytes()
    except FileNotFoundError:
        raise SystemExit(f"missing sentinel file: {PROOF}")
    if actual != EXPECTED:
        raise SystemExit(f"sentinel bytes differ: expected {EXPECTED!r}, got {actual!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
