#!/usr/bin/env python3
"""Qualify two exact OSS glTF suppliers behind one AXM capability contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from verify_asset import AssetError, canonical_bytes, semantic_report

HERE = Path(__file__).resolve().parent
MAX_JSON_BYTES = 2_000_000


class QualificationError(RuntimeError):
    pass


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise QualificationError(f"JSON source is absent or oversized: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qualification_identity(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "qualificationId"}
    return "supplierqual1_" + hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def executable(name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    path = HERE / "node_modules" / ".bin" / f"{name}{suffix}"
    if not path.is_file():
        raise QualificationError(f"supplier executable is absent: {path}")
    return path


def network_wrapper() -> list[str]:
    raw = os.environ.get("AXM_SUPPLIER_NETWORK_WRAPPER", "").strip()
    if not raw:
        if os.environ.get("AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE") == "1":
            raise QualificationError("network quarantine is required but no wrapper is configured")
        return []
    return shlex.split(raw)


def parse_time_metrics(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8").strip().split()
    if len(raw) != 2:
        raise QualificationError(f"unexpected /usr/bin/time output: {path}")
    return {"elapsedSeconds": float(raw[0]), "peakRssKiB": int(raw[1])}


def run_command(
    command: list[str],
    cwd: Path,
    log_path: Path,
    metrics_path: Path,
    wrapper: list[str],
) -> dict[str, Any]:
    if os.name == "nt":
        timed = wrapper + command
    else:
        timed = ["/usr/bin/time", "-f", "%e %M", "-o", str(metrics_path)] + wrapper + command
    env = os.environ.copy()
    for key in [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"
    ]:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    started = time.monotonic()
    process = subprocess.run(
        [str(item) for item in timed],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    wall = time.monotonic() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "$ " + " ".join(shlex.quote(str(item)) for item in command) + "\n" + process.stdout,
        encoding="utf-8",
    )
    if process.returncode:
        raise QualificationError(
            f"supplier command failed with {process.returncode}: {' '.join(command)}\n{process.stdout[-2000:]}"
        )
    if os.name == "nt":
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        metrics = {"elapsedSeconds": round(wall, 6), "peakRssKiB": int(usage.ru_maxrss)}
    else:
        metrics = parse_time_metrics(metrics_path)
        metrics["wallSecondsObserved"] = round(wall, 6)
    return metrics


def package_metadata(package: str, lock: dict[str, Any]) -> dict[str, Any]:
    key = "node_modules/" + package
    lock_row = (lock.get("packages") or {}).get(key)
    if not isinstance(lock_row, dict):
        raise QualificationError(f"package lock has no exact package row: {package}")
    package_json = load_json(HERE / key / "package.json")
    repository = package_json.get("repository")
    if isinstance(repository, dict):
        repository = repository.get("url")
    return {
        "package": package,
        "version": lock_row.get("version"),
        "integrity": lock_row.get("integrity"),
        "resolved": lock_row.get("resolved"),
        "license": package_json.get("license"),
        "repository": repository,
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("format") != "axm-supplier-pilot/1":
        raise QualificationError("unsupported supplier manifest format")
    providers = manifest.get("providers")
    if not isinstance(providers, list) or len(providers) != 2:
        raise QualificationError("the first pilot requires exactly two providers")
    ids = [provider.get("id") for provider in providers]
    if len(set(ids)) != len(ids) or not all(isinstance(item, str) for item in ids):
        raise QualificationError("provider IDs must be unique strings")
    authority = manifest.get("authority")
    if not isinstance(authority, dict) or set(authority) != {
        "domainCapability", "supplierSelection", "actionOutcome", "campaignMutation",
        "evidenceAcceptance", "estateScheduling"
    }:
        raise QualificationError("manifest authority membrane is incomplete")
    if any(authority[key] != "none" for key in authority if key != "supplierSelection"):
        raise QualificationError("Supplier Foundry manifest attempts to acquire authority")
    if authority["supplierSelection"] != "measurement recommendation only":
        raise QualificationError("supplier selection must remain a measurement recommendation")


def gltf_transform_pipeline(
    source: Path,
    output: Path,
    work: Path,
    log: Path,
    wrapper: list[str],
) -> dict[str, Any]:
    tool = executable("gltf-transform")
    stage = work / "deduplicated.glb"
    first_log = work / "dedup.log"
    second_log = work / "prune.log"
    first = run_command(
        [str(tool), "dedup", str(source), str(stage)],
        work,
        first_log,
        work / "dedup.time",
        wrapper,
    )
    second = run_command(
        [str(tool), "prune", str(stage), str(output)],
        work,
        second_log,
        work / "prune.time",
        wrapper,
    )
    log.write_text(first_log.read_text(encoding="utf-8") + "\n" + second_log.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "elapsedSeconds": round(first["elapsedSeconds"] + second["elapsedSeconds"], 6),
        "peakRssKiB": max(first["peakRssKiB"], second["peakRssKiB"]),
        "steps": [first, second],
    }


def gltfpack_pipeline(
    source: Path,
    output: Path,
    work: Path,
    log: Path,
    wrapper: list[str],
) -> dict[str, Any]:
    tool = executable("gltfpack")
    return run_command(
        [str(tool), "-i", str(source), "-o", str(output), "-kn", "-km", "-ke"],
        work,
        log,
        work / "gltfpack.time",
        wrapper,
    )


def qualify_provider(
    provider: dict[str, Any],
    package: dict[str, Any],
    source: Path,
    source_semantic: dict[str, Any],
    root: Path,
    wrapper: list[str],
    pipeline: Callable[[Path, Path, Path, Path, list[str]], dict[str, Any]],
    budgets: dict[str, Any],
) -> dict[str, Any]:
    provider_id = provider["id"]
    slug = provider_id.replace(".", "-")
    runs: list[dict[str, Any]] = []
    for number in (1, 2):
        work = root / "work" / slug / f"run-{number}"
        work.mkdir(parents=True, exist_ok=True)
        output = work / "output.glb"
        log = work / "execution.log"
        metrics = pipeline(source, output, work, log, wrapper)
        semantic = semantic_report(output)
        record = {
            "number": number,
            "output": output,
            "outputSha256": sha256_file(output),
            "outputBytes": output.stat().st_size,
            "semantic": semantic,
            "metrics": metrics,
            "log": log,
            "logSha256": sha256_file(log),
        }
        runs.append(record)

    first, second = runs
    if budgets.get("requireRawDeterminism") and first["outputSha256"] != second["outputSha256"]:
        raise QualificationError(f"{provider_id} produced different bytes across identical runs")
    if budgets.get("requireSemanticEquivalence"):
        for run in runs:
            if run["semantic"]["semanticDigest"] != source_semantic["semanticDigest"]:
                raise QualificationError(f"{provider_id} changed bounded asset semantics")
    maximum_seconds = float(budgets.get("maximumExecutionSecondsPerProvider", 60))
    if any(run["metrics"]["elapsedSeconds"] > maximum_seconds for run in runs):
        raise QualificationError(f"{provider_id} exceeded the execution budget")
    maximum_bytes = int(budgets.get("maximumOutputBytes", 1_048_576))
    if first["outputBytes"] > maximum_bytes:
        raise QualificationError(f"{provider_id} exceeded the output budget")
    if budgets.get("requireOutputNoLargerThanSource") and first["outputBytes"] > source.stat().st_size:
        raise QualificationError(f"{provider_id} output is larger than the source fixture")
    accepted_licenses = set(provider.get("licensePolicy") or [])
    if package.get("license") not in accepted_licenses:
        raise QualificationError(
            f"{provider_id} license {package.get('license')!r} is outside {sorted(accepted_licenses)}"
        )
    if package.get("version") != provider.get("version"):
        raise QualificationError(f"{provider_id} installed version differs from manifest")
    if not package.get("integrity"):
        raise QualificationError(f"{provider_id} has no package-lock integrity")

    return {
        "id": provider_id,
        "status": "pass",
        "package": package,
        "pipeline": provider.get("pipeline"),
        "runOneSha256": first["outputSha256"],
        "runTwoSha256": second["outputSha256"],
        "outputBytes": first["outputBytes"],
        "semanticDigest": first["semantic"]["semanticDigest"],
        "elapsedSeconds": first["metrics"]["elapsedSeconds"],
        "peakRssKiB": first["metrics"]["peakRssKiB"],
        "runOne": first,
        "runTwo": second,
    }


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def prepare_bundle(
    output_root: Path,
    manifest_path: Path,
    lock_path: Path,
    source_path: Path,
    source_semantic: dict[str, Any],
    provider_results: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    bundle = output_root / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "source").mkdir(parents=True)
    (bundle / "products").mkdir(parents=True)
    (bundle / "selected").mkdir(parents=True)
    (bundle / "logs").mkdir(parents=True)
    (bundle / "custody").mkdir(parents=True)
    (bundle / "tools").mkdir(parents=True)

    shutil.copy2(manifest_path, bundle / "manifest.json")
    shutil.copy2(lock_path, bundle / "custody" / "package-lock.json")
    shutil.copy2(HERE / "package.json", bundle / "custody" / "package.json")
    shutil.copy2(source_path, bundle / "source" / "two-triangles.gltf")
    shutil.copy2(HERE / "verify_asset.py", bundle / "tools" / "verify_asset.py")
    shutil.copy2(HERE / "verify_bundle.py", bundle / "tools" / "verify_bundle.py")

    providers: list[dict[str, Any]] = []
    for result in provider_results:
        slug = result["id"].replace(".", "-")
        product = bundle / "products" / f"{slug}.glb"
        log = bundle / "logs" / f"{slug}.log"
        shutil.copy2(result["runOne"]["output"], product)
        shutil.copy2(result["runOne"]["log"], log)
        providers.append(
            {
                "id": result["id"],
                "status": "pass",
                "package": result["package"],
                "pipeline": result["pipeline"],
                "productPath": relative(bundle, product),
                "outputSha256": result["runOneSha256"],
                "runOneSha256": result["runOneSha256"],
                "runTwoSha256": result["runTwoSha256"],
                "outputBytes": result["outputBytes"],
                "semanticDigest": result["semanticDigest"],
                "elapsedSeconds": result["elapsedSeconds"],
                "peakRssKiB": result["peakRssKiB"],
                "logPath": relative(bundle, log),
                "logSha256": sha256_file(log),
            }
        )

    winner = min(providers, key=lambda row: (row["outputBytes"], row["elapsedSeconds"], row["id"]))
    selected = bundle / "selected" / "asset.glb"
    shutil.copy2(bundle / winner["productPath"], selected)
    source = bundle / "source" / "two-triangles.gltf"
    lock = bundle / "custody" / "package-lock.json"
    receipt: dict[str, Any] = {
        "format": "axm-supplier-qualification/1",
        "status": "pass",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pilotId": manifest["id"],
        "organId": (manifest.get("organ") or {}).get("id"),
        "capability": (manifest.get("capability") or {}).get("id"),
        "authority": manifest.get("authority"),
        "source": {
            "path": relative(bundle, source),
            "sha256": sha256_file(source),
            "bytes": source.stat().st_size,
            "semanticDigest": source_semantic["semanticDigest"],
            "semantic": source_semantic,
        },
        "acquisition": {
            "packageLockPath": relative(bundle, lock),
            "packageLockSha256": sha256_file(lock),
            "node": platform.node(),
            "nodeVersion": subprocess.run(["node", "--version"], text=True, capture_output=True, check=True).stdout.strip(),
            "pythonVersion": platform.python_version(),
            "platform": platform.platform(),
        },
        "executionIsolation": {
            "networkWrapper": network_wrapper(),
            "proxyEnvironmentRemoved": True,
            "jobScopedWorkingDirectories": True,
            "remoteRuntimeReferences": False,
        },
        "providers": providers,
        "selection": {
            "policy": (manifest.get("capability") or {}).get("policy"),
            "providerId": winner["id"],
            "productPath": relative(bundle, selected),
            "sha256": sha256_file(selected),
            "outputBytes": selected.stat().st_size,
            "status": "measurement recommendation only",
        },
        "fallback": {
            "id": (manifest.get("fallback") or {}).get("id"),
            "path": relative(bundle, source),
            "sha256": sha256_file(source),
            "semanticDigest": source_semantic["semanticDigest"],
            "behavior": (manifest.get("fallback") or {}).get("behavior"),
        },
        "ripOut": {
            "status": "pending",
            "requirement": "Delete supplier runtime and verify the bundle using only bundled stdlib tools.",
        },
        "limits": manifest.get("limits"),
    }
    receipt["qualificationId"] = qualification_identity(receipt)
    (bundle / "qualification.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "supplier_manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_root = args.output.resolve()
    try:
        manifest_path = args.manifest.resolve()
        manifest = load_json(manifest_path)
        validate_manifest(manifest)
        lock_path = HERE / "package-lock.json"
        lock = load_json(lock_path)
        source_path = (HERE / manifest["fixture"]).resolve()
        source_semantic = semantic_report(source_path)
        wrapper = network_wrapper()
        packages = {provider["id"]: package_metadata(provider["package"], lock) for provider in manifest["providers"]}
        output_root.mkdir(parents=True, exist_ok=True)
        pipelines: dict[str, Callable[[Path, Path, Path, Path, list[str]], dict[str, Any]]] = {
            "oss.gltf-transform.cli": gltf_transform_pipeline,
            "oss.gltfpack": gltfpack_pipeline,
        }
        results = []
        for provider in manifest["providers"]:
            pipeline = pipelines.get(provider["id"])
            if pipeline is None:
                raise QualificationError(f"no bounded adapter for {provider['id']}")
            results.append(
                qualify_provider(
                    provider,
                    packages[provider["id"]],
                    source_path,
                    source_semantic,
                    output_root,
                    wrapper,
                    pipeline,
                    manifest["budgets"],
                )
            )
        receipt = prepare_bundle(
            output_root,
            manifest_path,
            lock_path,
            source_path,
            source_semantic,
            results,
            manifest,
        )
    except (QualificationError, AssetError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "qualificationId": receipt["qualificationId"],
                "selectedProvider": receipt["selection"]["providerId"],
                "ripOut": receipt["ripOut"]["status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
