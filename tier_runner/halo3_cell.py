"""CLI for the HALO3 Cell Zero home-lab qualification floor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .halo3_cell_common import Halo3Error, hash_json, load_json, write_json
from .halo3_cell_plan import (
    compile_plan,
    compile_proof_matrix,
    observation_templates,
    render_proof_markdown,
    verify_plan,
    verify_proof_matrix,
)
from .halo3_cell_schema import validate_fingerprint_contract, validate_lab


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierhalo3",
        description=(
            "Compile the HALO3 Cell Zero home lab into an exact model-fingerprint matrix, "
            "physical proof stages, subtraction tests, and unmeasured observation templates."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    def sources(command: argparse.ArgumentParser) -> None:
        command.add_argument("--lab", type=Path, required=True)
        command.add_argument("--fingerprint", type=Path, required=True)

    validate = commands.add_parser("validate")
    sources(validate)

    plan = commands.add_parser("plan")
    sources(plan)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    sources(verify)
    verify.add_argument("--plan", type=Path, required=True)

    templates = commands.add_parser("templates")
    templates.add_argument("--plan", type=Path, required=True)
    templates.add_argument("--out", type=Path)

    proof = commands.add_parser("proof-matrix")
    sources(proof)
    proof.add_argument("--out-json", type=Path)
    proof.add_argument("--out-markdown", type=Path)

    proof_verify = commands.add_parser("verify-proof-matrix")
    sources(proof_verify)
    proof_verify.add_argument("--matrix", type=Path, required=True)
    return root


def _sources(args: argparse.Namespace) -> tuple[object, object]:
    return load_json(args.lab), load_json(args.fingerprint)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            raw_lab, raw_fingerprint = _sources(args)
            fingerprint = validate_fingerprint_contract(raw_fingerprint)
            lab = validate_lab(raw_lab, fingerprint)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "lab_id": lab["id"],
                        "lab_sha256": hash_json(lab),
                        "fingerprint_contract_id": fingerprint["id"],
                        "fingerprint_contract_sha256": hash_json(fingerprint),
                        "models": len(lab["models"]),
                        "nodes": len(lab["nodes"]),
                        "stages": len(lab["stages"]),
                        "claims": len(lab["claims"]),
                        "faults": len(lab["faults"]),
                        "fingerprint_families": len(fingerprint["families"]),
                        "physical_qualification": False,
                        "production_claim": False,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "plan":
            raw_lab, raw_fingerprint = _sources(args)
            write_json(args.out, compile_plan(raw_lab, raw_fingerprint))
            return 0

        if args.command == "verify":
            raw_lab, raw_fingerprint = _sources(args)
            errors = verify_plan(raw_lab, raw_fingerprint, load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))

        if args.command == "templates":
            write_json(args.out, observation_templates(load_json(args.plan)))
            return 0

        if args.command == "proof-matrix":
            raw_lab, raw_fingerprint = _sources(args)
            matrix = compile_proof_matrix(raw_lab, raw_fingerprint)
            write_json(args.out_json, matrix)
            markdown = render_proof_markdown(matrix)
            if args.out_markdown is None:
                print(markdown, end="")
            else:
                args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.out_markdown.with_suffix(args.out_markdown.suffix + ".tmp")
                temporary.write_bytes(markdown.encode("utf-8"))
                temporary.replace(args.out_markdown)
            return 0

        if args.command == "verify-proof-matrix":
            raw_lab, raw_fingerprint = _sources(args)
            errors = verify_proof_matrix(
                raw_lab,
                raw_fingerprint,
                load_json(args.matrix),
            )
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
    except (Halo3Error, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierhalo3: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
