"""Deterministic tests for the CART0 Select/Compose bridge; zero model calls."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.cart0_anchor import (  # noqa: E402
    AnchorError,
    ab_demo,
    build,
    rehydrate,
    resurface,
    verify,
)


def run(argv: list[str], cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def fixture(root: Path) -> tuple[Path, Path, Path]:
    repo = root / "repo"
    repo.mkdir()
    run(["git", "init", "--initial-branch=main"], repo)
    run(["git", "config", "user.name", "CART0 Test"], repo)
    run(["git", "config", "user.email", "cart0@example.invalid"], repo)
    (repo / "STATE.md").write_text(
        "Objective and constraints live here.\nSecond source line.\n", encoding="utf-8"
    )
    run(["git", "add", "STATE.md"], repo)
    run(["git", "commit", "-m", "state"], repo)
    spec = {
        "schema": "tier-bench/cart0-anchor-spec@0",
        "anchor_id": "test-anchor",
        "objective": "Continue without repeating full context.",
        "interpretation": "Proposal-only Select/Compose projection.",
        "constraints": ["Never mint a scientific claim."],
        "position": {
            "principal": "test",
            "role": "driver",
            "lane": "driver",
            "branch": "main",
            "state": "proposal",
        },
        "authorized_transition": "Run deterministic bridge tests.",
        "authority": "Local test fixture.",
        "resurface_at": ["implementation_start", "handoff"],
        "evidence_paths": ["STATE.md"],
    }
    catalog = {
        "schema": "tier-bench/cart0-card-catalog@0",
        "catalog_id": "test-compiled-projection",
        "cards": [{
            "card_id": "000.100.TEST",
            "revision": 1,
            "summary": "The current objective and constraints are source-bound.",
            "token_budget": 128,
            "sources": [{"path": "STATE.md", "start_line": 1, "end_line": 2}],
            "supersedes": None,
            "freshness": "git-head-bound",
            "authority": "test-authority",
            "review_status": "proposal-unreviewed",
            "select_at": ["implementation_start", "handoff"],
        }],
    }
    spec_path = root / "spec.json"
    catalog_path = root / "catalog.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    return repo, spec_path, catalog_path


def test_build_verify_resurface_rehydrate_and_ab(root: Path) -> None:
    repo, spec, catalog = fixture(root)
    bundle = root / "bundle"
    receipt = build(repo, spec, catalog, bundle, "implementation_start", 256)
    assert receipt["scientific_claim_minted"] is False
    assert receipt["anchor_metrics"]["approx_tokens_bytes_div_4"] <= 256
    assert receipt["cards"][0]["review_status"] == "proposal-unreviewed"
    verify(repo, bundle)
    prompt = resurface(
        repo, bundle, "implementation_start", "Implement the bounded prototype.", None
    )
    assert b"SELECTED CARDS" in prompt
    evidence = rehydrate(repo, bundle, "000.100.TEST", None)
    assert b"Objective and constraints live here." in evidence
    result = ab_demo(
        repo,
        spec,
        catalog,
        root / "ab",
        "implementation_start",
        "Implement the bounded prototype.",
        256,
    )
    assert result["model_calls"] == 0
    assert result["utf8_bytes_saved"] == (
        result["A_full_context"]["utf8_bytes"]
        - result["B_anchor_plus_selected_cards"]["utf8_bytes"]
    )
    assert all(probe["refused"] for probe in result["failure_probes"])
    assert (root / "ab" / "raw_output_A_full_context_prompt.txt").is_file()
    assert (root / "ab" / "raw_output_B_catalog_prompt.txt").is_file()
    cli = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "cart0_anchor.py"),
            "verify",
            "--repo",
            str(repo),
            "--bundle",
            str(bundle),
        ],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0, cli.stderr
    assert '"schema": "tier-bench/cart0-anchor-receipt@1"' in cli.stdout


def test_stale_head_boundary_and_lookup_miss_refuse(root: Path) -> None:
    repo, spec, catalog = fixture(root)
    bundle = root / "bundle"
    build(repo, spec, catalog, bundle, "implementation_start", 256)
    try:
        resurface(repo, bundle, "handoff", "Do work.", None)
    except AnchorError as exc:
        assert "does not match bundle boundary" in str(exc)
    else:
        raise AssertionError("wrong boundary was accepted")
    try:
        rehydrate(repo, bundle, "999.999.MISSING", None)
    except AnchorError as exc:
        assert "retrieval miss" in str(exc)
    else:
        raise AssertionError("missing card was accepted")
    (repo / "new.txt").write_text("new head\n", encoding="utf-8")
    run(["git", "add", "new.txt"], repo)
    run(["git", "commit", "-m", "move head"], repo)
    try:
        verify(repo, bundle)
    except AnchorError as exc:
        assert "HEAD changed" in str(exc)
    else:
        raise AssertionError("stale bundle was accepted")


def test_unsafe_path_and_revision_gap_refuse(root: Path) -> None:
    repo, spec_path, catalog_path = fixture(root)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["evidence_paths"] = ["../secret.txt"]
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    try:
        build(repo, spec_path, catalog_path, root / "bundle", "implementation_start", 256)
    except AnchorError as exc:
        assert "canonical safe path" in str(exc)
    else:
        raise AssertionError("traversal path was accepted")
    second = root / "second"
    second.mkdir()
    _, clean_spec, catalog_path = fixture(second)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["cards"][0]["revision"] = 2
    catalog["cards"][0]["supersedes"] = {"card_id": "000.100.TEST", "revision": 1}
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    try:
        build(second / "repo", clean_spec, catalog_path, root / "gap", "implementation_start", 256)
    except AnchorError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("revision gap was accepted")


def main() -> int:
    tests = [
        test_build_verify_resurface_rehydrate_and_ab,
        test_stale_head_boundary_and_lookup_miss_refuse,
        test_unsafe_path_and_revision_gap_refuse,
    ]
    parent = Path(tempfile.mkdtemp(prefix="cart0-anchor-tests-"))
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    print(f"OK - {len(tests)}/{len(tests)} CART0 bridge tests passed; zero model calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
