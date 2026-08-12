#!/bin/bash
# Native rail v3 reproduction path. Run on the admitted controller host.
#
#   ./run_proofs.sh emit
#   ./run_proofs.sh qualify <fresh-root> <accepted-profile-sha256>
#   ./run_proofs.sh collect <fresh-root>
#
# `emit` produces the runner profile that must then be committed and reviewed as
# an accepted artifact. `qualify` runs the full cold qualification from a fresh
# controller root; it refuses a root that already holds a database, lease,
# workspace, receipt or checkpoint. The accepted profile digest is an EXTERNAL
# input: read it from the committed profile and quote it in the review packet.
set -u

RAIL="$(cd "$(dirname "$0")" && pwd)"
PROFILE="$RAIL/RUNNER-PROFILE.$(hostname).json"
BUNDLE="${TBRAIL_SOURCE_BUNDLE:-$HOME/.tbrail/source/estate-fb47a4cc.bundle}"

case "${1:-}" in
  emit)
    cd "$RAIL" || exit 1
    TBRAIL_HOME=$(mktemp -d) python3 tbrail.py profile-emit "$PROFILE" || exit 1
    sha256sum "$PROFILE"
    ;;
  qualify)
    ROOT="${2:?fresh controller root required}"
    SHA="${3:?accepted runner-profile sha256 required}"
    cd "$RAIL" || exit 1
    python3 cold_qualify.py "$ROOT" "$BUNDLE" "$SHA"
    echo "COLD_QUALIFY_EXIT=$?"
    ;;
  collect)
    ROOT="${2:?controller root required}"
    python3 - "$ROOT" <<'PYEOF'
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
data = json.loads((root / "COLD-QUALIFICATION.json").read_text())
print(data["verdict"])
print(f"{data['total'] - data['failed']}/{data['total']} properties passed")
for r in data["results"]:
    print(("PASS " if r["pass"] else "FAIL ") + r["property"])
PYEOF
    ;;
  *)
    echo "usage: run_proofs.sh emit | qualify <root> <sha256> | collect <root>"
    exit 2
    ;;
esac
