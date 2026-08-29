"""Deterministic verifier for the CLAUDE-5 fabric qualification capsule.

Zero-model, zero-network. Three verification levels, each strictly stronger:

  CAPSULE_ONLY_VERIFIED
      (default) The committed capsule alone: required fields present, the
      aggregate evidence root recomputes exactly from the embedded receipt
      manifest under the declared root rule, the summary digest is a member
      of the manifest, and the phase-result table covers the exact declared
      mode denominator.

  RAW_BYTES_VERIFIED
      (--estate-root) Additionally rehashes every raw private evidence file
      against the embedded manifest. Proves the named private files carry the
      expected bytes - and nothing more.

  RAW_SEMANTICS_VERIFIED
      (--estate-root, reached only after RAW_BYTES_VERIFIED) Parses every
      digest-bound raw artifact and RECONSTRUCTS the decision-critical claims
      from raw content alone, then refuses on ANY semantic disagreement with
      the committed capsule even when every raw file digest matches:

        identity     GPU UUIDs and board roles, the port -> UUID pinning of
                     each serve, the phase -> port -> stream binding, the
                     effective per-card core lock under the committed policy
                     rule, and the ollama manifest digest of every served
                     model - all derived from digest-bound raw artifacts, and
                     NEVER from an nvidia-smi ordinal index.
        workload     every primary and secondary sample's token count, against
                     the declared tokens_per_run and against the driver
                     source's own generation constant.
        statistics   every primary and secondary decode and prefill sample,
                     with medians RECOMPUTED (never trusted) and compared to
                     both the receipt summary and the capsule, including the
                     two per-card medians mapped individually to their
                     UUID-bound card roles.
        aggregate    aggregate throughput, scaling, concurrency retention,
                     VRAM allocation, run counts, mode denominator, terminal
                     verdict, claim-boundary structure.

CLAUDE-5 repository closure is supported only at RAW_SEMANTICS_VERIFIED on a
host holding the raw estate tree; a fresh checkout reaches
CAPSULE_ONLY_VERIFIED, which authenticates the committed claims and their
binding but cannot re-derive them.

Exit code 0 = verified at the requested level; 1 = any check failed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CAPSULE = HERE / "CAPSULE.json"

REQUIRED_FIELDS = [
    "schema",
    "claim_id",
    "claim",
    "host",
    "date",
    "qualification_mode_denominator",
    "phase_results",
    "phase_execution",
    "phase_serve_binding",
    "serve_pinning",
    "gpu_identities",
    "model_identities",
    "identity_evidence",
    "summary_receipt_sha256",
    "receipt_manifest_sha256",
    "aggregate_evidence_root_sha256",
    "aggregate_root_rule",
    "claim_boundary",
    "raw_evidence_custody",
]

# Raw artifacts that must be in the manifest denominator for the identity and
# workload semantics to be derivable at all. Absence is a refusal, not a skip.
REQUIRED_IDENTITY_ARTIFACTS = [
    "fabric_qual.py",
    "identity/launch-fabric-serves.ps1",
    "identity/gpu-mode.ps1",
    "identity/gpu-cards.json",
    "identity/gpu-host-OCTO-L01.json",
    "identity/IDENTITY-ATTESTATION.json",
]

# The two source lines that establish the committed core-lock rule inside
# gpu-mode.ps1. Both must be present or the rule is not the one we claim.
LOCK_RULE_ANCHORS = [
    "$eff = $m.coreLock",
    "$eff = [int]$card2.coreLockCapMHz",
]

SERVE_ROW_RE = re.compile(
    r"@\{\s*port\s*=\s*(?P<port>\d+)\s*;\s*"
    r"cuda\s*=\s*(?:'(?P<uuid>[^']*)'|\$null)\s*\}"
)


class VerificationFailure(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def refuse(msg: str) -> None:
    raise VerificationFailure(msg)


def parse_gpu_lines(lines: list[str]) -> dict[int, dict]:
    """Parse 'index, NNN MiB, U %, P W, T' nvidia-smi rows."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        idx = int(parts[0])
        out[idx] = {
            "mib": int(parts[1].split()[0]),
            "util_pct": int(parts[2].split()[0]),
            "power_w": float(parts[3].split()[0]),
            "temp_c": int(parts[4]),
        }
    return out


def median_1dp(values: list[float]) -> float:
    return round(statistics.median(values), 1)


# --------------------------------------------------------------------------
# raw-artifact parsers: every identity fact below is DERIVED, never asserted
# --------------------------------------------------------------------------

def parse_driver_source(source: str) -> dict:
    """Derive the workload constants and the phase -> port/stream dispatch map
    from the digest-bound bench driver's own source text."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        refuse(f"driver source does not parse: {exc}")

    consts: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass

    for name in ("N_PREDICT", "ROUNDS", "PROMPTS"):
        if name not in consts:
            refuse(f"driver source does not define {name}")
    if not isinstance(consts["PROMPTS"], (list, tuple)) or not consts["PROMPTS"]:
        refuse("driver source PROMPTS is not a non-empty sequence")

    phases: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "bench"):
            continue
        if len(node.args) < 3:
            refuse("driver bench() call does not carry (port, model, tag)")
        try:
            port = ast.literal_eval(node.args[0])
            model = ast.literal_eval(node.args[1])
            tag = ast.literal_eval(node.args[2])
        except (ValueError, SyntaxError):
            refuse("driver bench() call arguments are not literals")
        secondary = None
        for kw in node.keywords:
            if kw.arg == "concurrent_with":
                try:
                    secondary = ast.literal_eval(kw.value)
                except (ValueError, SyntaxError):
                    refuse("driver concurrent_with is not a literal")
        if tag in phases:
            refuse(f"driver source dispatches phase {tag!r} more than once")
        phases[tag] = {"primary_port": port, "secondary_port": secondary,
                       "model": model}
    if not phases:
        refuse("driver source contains no bench() dispatch")

    return {
        "n_predict": consts["N_PREDICT"],
        "rounds": consts["ROUNDS"],
        "prompts": len(consts["PROMPTS"]),
        "runs_per_mode": consts["ROUNDS"] * len(consts["PROMPTS"]),
        "declared_uuids": sorted(
            v for k, v in consts.items()
            if k.endswith("_UUID") and isinstance(v, str) and v.startswith("GPU-")),
        "phases": phases,
    }


def parse_serve_pinning(source: str) -> dict[int, str | None]:
    """Derive port -> pinned GPU UUID from the digest-bound serve launcher."""
    rows = list(SERVE_ROW_RE.finditer(source))
    if not rows:
        refuse("serve launcher declares no port/cuda serve table")
    out: dict[int, str | None] = {}
    for m in rows:
        port = int(m.group("port"))
        if port in out:
            refuse(f"serve launcher declares port {port} more than once")
        out[port] = m.group("uuid")  # None for the unpinned fabric serve
    return out


def parse_lock_policy(host: dict, cards: dict, gpu_mode_src: str) -> dict:
    """Derive the effective core lock per GPU UUID under the committed rule
    min(host_mode.coreLock, cards[uuid].coreLockCapMHz)."""
    for anchor in LOCK_RULE_ANCHORS:
        if anchor not in gpu_mode_src:
            refuse(f"core-lock applier does not contain the committed rule "
                   f"anchor {anchor!r}")

    modes = host.get("modes")
    if not isinstance(modes, dict) or not modes:
        refuse("host calibration declares no modes")
    defaults = [name for name, m in modes.items()
                if "DEFAULT" in str(m.get("note", ""))]
    if len(defaults) != 1:
        refuse(f"host calibration must mark exactly one DEFAULT mode, found {defaults}")
    default_mode = defaults[0]

    registry = cards.get("cards")
    if not isinstance(registry, dict) or not registry:
        refuse("card registry declares no cards")

    out = {
        "default_mode": default_mode,
        "mode_core_lock_mhz": modes[default_mode].get("coreLock"),
        "host_validated": bool(host.get("validated")),
        "validated_pair_uuids": sorted(host.get("validatedPairUuids") or []),
        "cards": {},
    }
    for uuid, card in registry.items():
        eff = out["mode_core_lock_mhz"]
        cap = card.get("coreLockCapMHz")
        if eff and cap and int(cap) > 0 and int(cap) < int(eff):
            eff = int(cap)
        out["cards"][uuid] = {
            "label": card.get("label"),
            "core_lock_cap_mhz": cap,
            "effective_core_lock_mhz": eff,
        }
    return out


def manifest_relpath_for_model(name: str) -> str:
    """'qwen3.5:27b' -> 'identity/ollama-manifests/qwen3.5/27b'."""
    if name.count(":") != 1:
        refuse(f"model name {name!r} is not a single '<repo>:<tag>' pair")
    repo, tag = name.split(":")
    if not repo or not tag or "/" in repo or "/" in tag:
        refuse(f"model name {name!r} does not map to a manifest path")
    return f"identity/ollama-manifests/{repo}/{tag}"


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------

def verify_capsule_only(capsule: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in capsule:
            refuse(f"capsule missing required field {field!r}")
    if capsule["schema"] != "estate/fabric-qual-capsule@3":
        refuse(f"unexpected schema {capsule['schema']!r}")

    manifest = capsule["receipt_manifest_sha256"]
    if not manifest or not isinstance(manifest, dict):
        refuse("receipt manifest empty or malformed")
    for name, digest in manifest.items():
        if not isinstance(digest, str) or len(digest) != 64:
            refuse(f"manifest entry {name!r} is not a sha256 hex digest")

    lines = "".join(f"{k} {v}\n" for k, v in sorted(manifest.items()))
    root = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    if root != capsule["aggregate_evidence_root_sha256"]:
        refuse("aggregate evidence root does not recompute from the manifest "
               f"(recomputed {root})")

    if capsule["summary_receipt_sha256"] != manifest.get("QUAL-SUMMARY.json"):
        refuse("summary receipt digest is not the manifest's QUAL-SUMMARY.json entry")

    denom = capsule["qualification_mode_denominator"]
    modes = denom["modes"]
    if denom["modes_total"] != len(modes):
        refuse("mode denominator count does not match the mode list")
    if not isinstance(denom.get("tokens_per_run"), int) or denom["tokens_per_run"] <= 0:
        refuse("mode denominator does not declare a positive tokens_per_run")
    if set(capsule["phase_results"]) != set(modes):
        refuse("phase results do not cover exactly the declared modes")
    if set(capsule["phase_execution"]) != set(modes):
        refuse("phase execution records do not cover exactly the declared modes")
    if set(capsule["phase_serve_binding"]) != set(modes):
        refuse("phase serve bindings do not cover exactly the declared modes")
    receipt_names = {n for n in manifest if n.startswith("receipts/")}
    if len(receipt_names) != len(modes):
        refuse("per-receipt manifest does not carry one receipt per declared mode")

    # every identity claim must name a digest-bound artifact
    for rel in REQUIRED_IDENTITY_ARTIFACTS:
        if rel not in manifest:
            refuse(f"identity artifact {rel!r} is not in the evidence denominator")
    for ident in capsule["gpu_identities"]:
        for key in ("role", "capsule_key", "uuid", "label", "core_lock_mhz"):
            if key not in ident:
                refuse(f"gpu identity missing {key!r}")
    for model in capsule["model_identities"]:
        rel = manifest_relpath_for_model(model["name"])
        if rel not in manifest:
            refuse(f"model manifest {rel!r} is not in the evidence denominator")
        if manifest[rel] != model["ollama_manifest_sha256"]:
            refuse(f"capsule ollama_manifest_sha256 for {model['name']!r} is not the "
                   f"digest bound for {rel!r}")

    boundary = capsule["claim_boundary"]
    if not boundary.get("claims") or not boundary.get("non_claims"):
        refuse("claim boundary must state both claims and non-claims")


def verify_raw_bytes(capsule: dict, estate_root: Path) -> None:
    manifest = capsule["receipt_manifest_sha256"]
    missing, mismatched = [], []
    for name, expected in sorted(manifest.items()):
        p = estate_root / name
        if not p.is_file():
            missing.append(name)
        elif sha256_file(p) != expected:
            mismatched.append(name)
    if missing or mismatched:
        refuse(f"raw custody bytes: missing={missing} mismatched={mismatched}")


def reconstruct_from_estate(estate_root: Path, modes: list[str],
                            model_names: list[str] | None = None) -> dict:
    """Rebuild the decision-critical claims from raw artifact content ONLY."""
    summary = json.loads((estate_root / "QUAL-SUMMARY.json").read_text(encoding="utf-8"))
    driver = parse_driver_source(
        (estate_root / "fabric_qual.py").read_text(encoding="utf-8"))
    pinning = parse_serve_pinning(
        (estate_root / "identity" / "launch-fabric-serves.ps1").read_text(encoding="utf-8"))
    lock = parse_lock_policy(
        json.loads((estate_root / "identity" / "gpu-host-OCTO-L01.json")
                   .read_text(encoding="utf-8")),
        json.loads((estate_root / "identity" / "gpu-cards.json")
                   .read_text(encoding="utf-8")),
        (estate_root / "identity" / "gpu-mode.ps1").read_text(encoding="utf-8"),
    )
    attestation = json.loads(
        (estate_root / "identity" / "IDENTITY-ATTESTATION.json").read_text(encoding="utf-8"))

    model_digests = {}
    for name in (model_names or []):
        p = estate_root / manifest_relpath_for_model(name)
        if not p.is_file():
            refuse(f"model manifest for {name!r} is absent from the raw estate")
        model_digests[name] = sha256_file(p)

    recon: dict = {
        "summary_phase_denominator": sorted(summary.get("phases", {})),
        "terminal_verdict_pass": str(summary.get("verdict", "")).startswith("PASS"),
        "host": summary.get("host"),
        "date": summary.get("date"),
        "driver": driver,
        "serve_pinning": pinning,
        "lock_policy": lock,
        "model_manifest_sha256": model_digests,
        "attestation": attestation,
        "phases": {},
    }

    for mode in modes:
        rp = estate_root / "receipts" / f"{mode}.json"
        r = json.loads(rp.read_text(encoding="utf-8"))
        during = parse_gpu_lines(r["gpu_during"])
        active = sorted(i for i, g in during.items() if g["mib"] > 0)
        excluded = sorted(i for i, g in during.items() if g["mib"] == 0)

        raw = r["raw"]
        phase: dict = {
            "phase_name": r["phase"],
            "model": r["model"],
            "date": str(r["ts"])[:10],
            "runs": len(raw),
            "declared_n": r["primary"]["n"],
            "primary_tokens": [x["tokens"] for x in raw],
            "decode_median": median_1dp([x["decode_tok_s"] for x in raw]),
            "declared_decode_median": r["primary"]["decode_median"],
            "prefill_median": median_1dp([x["prefill_tok_s"] for x in raw]),
            "declared_prefill_median": r["primary"]["prefill_median"],
            "active_devices": active,
            "excluded_devices": excluded,
            "vram_gb_during": {i: round(g["mib"] / 1000, 1) for i, g in during.items()
                               if g["mib"] > 0},
        }
        if "secondary" in r:
            raw2 = r.get("raw_secondary", [])
            phase["secondary_runs"] = len(raw2)
            phase["secondary_tokens"] = [x["tokens"] for x in raw2]
            phase["secondary_decode_median"] = median_1dp(
                [x["decode_tok_s"] for x in raw2]) if raw2 else None
            phase["declared_secondary_decode_median"] = r["secondary"]["decode_median"]
            phase["secondary_prefill_median"] = median_1dp(
                [x["prefill_tok_s"] for x in raw2]) if raw2 else None
            phase["declared_secondary_prefill_median"] = r["secondary"]["prefill_median"]
            phase["aggregate_decode"] = r["aggregate_decode"]
        recon["phases"][mode] = phase
    return recon


def _verify_identity(capsule: dict, recon: dict) -> dict:
    """Bind UUID -> label -> capsule role -> serve port -> receipt stream.

    Returns role_key -> {'uuid', 'port'} so per-card statistics can be mapped
    without ever consulting an nvidia-smi ordinal index.
    """
    lock = recon["lock_policy"]
    pinning = recon["serve_pinning"]
    driver = recon["driver"]
    evidence = capsule["identity_evidence"]

    if lock["default_mode"] != evidence["core_lock_host_mode"]:
        refuse(f"semantic identity: raw default host mode {lock['default_mode']!r} "
               f"!= capsule {evidence['core_lock_host_mode']!r}")
    if not lock["host_validated"]:
        refuse("semantic identity: host calibration is not marked validated")

    claimed_uuids = sorted(g["uuid"] for g in capsule["gpu_identities"])
    if lock["validated_pair_uuids"] != claimed_uuids:
        refuse(f"semantic identity: validated pair {lock['validated_pair_uuids']} "
               f"!= capsule GPU UUIDs {claimed_uuids}")
    if driver["declared_uuids"] != claimed_uuids:
        refuse(f"semantic identity: driver-source UUIDs {driver['declared_uuids']} "
               f"!= capsule GPU UUIDs {claimed_uuids}")

    attested = sorted(
        row.split(",")[1].strip() for row in recon["attestation"]["nvidia_smi_rows"])
    if attested != claimed_uuids:
        refuse(f"semantic identity: attested device UUIDs {attested} "
               f"!= capsule GPU UUIDs {claimed_uuids}")

    # capsule serve_pinning must be exactly the launcher's table
    raw_pin = {str(port): uuid for port, uuid in pinning.items()}
    if raw_pin != {str(k): v for k, v in capsule["serve_pinning"].items()}:
        refuse(f"semantic identity: raw serve pinning {raw_pin} "
               f"!= capsule {capsule['serve_pinning']}")

    roles: dict[str, dict] = {}
    for ident in capsule["gpu_identities"]:
        uuid = ident["uuid"]
        card = lock["cards"].get(uuid)
        if card is None:
            refuse(f"semantic identity: UUID {uuid} is absent from the card registry")
        if card["label"] != ident["label"]:
            refuse(f"semantic identity: registry label {card['label']!r} for {uuid} "
                   f"!= capsule {ident['label']!r}")
        if card["effective_core_lock_mhz"] != ident["core_lock_mhz"]:
            refuse(f"semantic identity: effective core lock "
                   f"{card['effective_core_lock_mhz']} MHz for {ident['label']} "
                   f"!= capsule {ident['core_lock_mhz']} MHz")
        ports = [p for p, u in pinning.items() if u == uuid]
        if len(ports) != 1:
            refuse(f"semantic identity: UUID {uuid} is pinned to {len(ports)} serves")
        roles[ident["capsule_key"]] = {"uuid": uuid, "port": ports[0]}

    for name, digest in recon["model_manifest_sha256"].items():
        claimed = next((m["ollama_manifest_sha256"] for m in capsule["model_identities"]
                        if m["name"] == name), None)
        if claimed is None:
            refuse(f"semantic identity: no capsule model identity for {name!r}")
        if digest != claimed:
            refuse(f"semantic identity: ollama manifest digest for {name!r} is "
                   f"{digest} != capsule {claimed}")
    return roles


def verify_raw_semantics(capsule: dict, recon: dict) -> None:
    """Refuse on ANY disagreement between capsule claims and raw semantics."""
    denom = capsule["qualification_mode_denominator"]
    modes = denom["modes"]
    tokens_per_run = denom["tokens_per_run"]

    if sorted(recon["summary_phase_denominator"]) != sorted(modes):
        refuse("semantic: summary phase denominator "
               f"{recon['summary_phase_denominator']} != capsule modes {sorted(modes)}")
    if not recon["terminal_verdict_pass"]:
        refuse("semantic: raw summary verdict is not a PASS verdict")
    if recon["host"] != capsule["host"]:
        refuse(f"semantic: host {recon['host']!r} != capsule {capsule['host']!r}")
    if recon["date"] != capsule["date"]:
        refuse(f"semantic: date {recon['date']!r} != capsule {capsule['date']!r}")

    roles = _verify_identity(capsule, recon)
    driver = recon["driver"]

    if driver["n_predict"] != tokens_per_run:
        refuse(f"semantic workload: driver N_PREDICT {driver['n_predict']} "
               f"!= capsule tokens_per_run {tokens_per_run}")
    if driver["runs_per_mode"] != denom["runs_per_mode"]:
        refuse(f"semantic workload: driver ROUNDS*PROMPTS {driver['runs_per_mode']} "
               f"!= capsule runs_per_mode {denom['runs_per_mode']}")
    if sorted(driver["phases"]) != sorted(modes):
        refuse(f"semantic workload: driver dispatches {sorted(driver['phases'])} "
               f"!= capsule modes {sorted(modes)}")

    for mode in modes:
        p = recon["phases"][mode]
        claim = capsule["phase_results"][mode]
        execution = capsule["phase_execution"][mode]
        binding = capsule["phase_serve_binding"][mode]
        dispatch = driver["phases"][mode]

        if p["phase_name"] != mode:
            refuse(f"semantic[{mode}]: receipt phase field is {p['phase_name']!r}")
        if p["model"] != claim["model"]:
            refuse(f"semantic[{mode}]: model {p['model']!r} != capsule {claim['model']!r}")
        if dispatch["model"] != claim["model"]:
            refuse(f"semantic[{mode}]: driver dispatches model {dispatch['model']!r} "
                   f"!= capsule {claim['model']!r}")
        if p["date"] != capsule["date"]:
            refuse(f"semantic[{mode}]: receipt date {p['date']} != capsule date")

        if dispatch["primary_port"] != binding["primary_port"] or \
                dispatch["secondary_port"] != binding["secondary_port"]:
            refuse(f"semantic[{mode}]: driver serve binding "
                   f"{dispatch['primary_port']}/{dispatch['secondary_port']} "
                   f"!= capsule {binding['primary_port']}/{binding['secondary_port']}")

        if p["runs"] != denom["runs_per_mode"] or p["declared_n"] != denom["runs_per_mode"]:
            refuse(f"semantic[{mode}]: run count raw={p['runs']} declared={p['declared_n']} "
                   f"!= capsule runs_per_mode {denom['runs_per_mode']}")

        bad = [t for t in p["primary_tokens"] if t != tokens_per_run]
        if bad:
            refuse(f"semantic[{mode}]: primary sample token counts {sorted(set(bad))} "
                   f"!= capsule tokens_per_run {tokens_per_run}")

        if p["decode_median"] != p["declared_decode_median"]:
            refuse(f"semantic[{mode}]: recomputed decode median {p['decode_median']} "
                   f"!= receipt-declared {p['declared_decode_median']}")
        if p["prefill_median"] != p["declared_prefill_median"]:
            refuse(f"semantic[{mode}]: recomputed prefill median {p['prefill_median']} "
                   f"!= receipt-declared {p['declared_prefill_median']}")

        if p["active_devices"] != execution["active_devices"]:
            refuse(f"semantic[{mode}]: active devices {p['active_devices']} "
                   f"!= capsule {execution['active_devices']}")
        if p["excluded_devices"] != execution["excluded_devices"]:
            refuse(f"semantic[{mode}]: excluded devices {p['excluded_devices']} "
                   f"!= capsule {execution['excluded_devices']}")

        if "aggregate_decode_tok_s" in claim:
            if p["secondary_runs"] != denom["runs_per_mode"]:
                refuse(f"semantic[{mode}]: secondary run count {p['secondary_runs']}")
            bad2 = [t for t in p["secondary_tokens"] if t != tokens_per_run]
            if bad2:
                refuse(f"semantic[{mode}]: secondary sample token counts "
                       f"{sorted(set(bad2))} != capsule tokens_per_run {tokens_per_run}")
            if p["secondary_decode_median"] != p["declared_secondary_decode_median"]:
                refuse(f"semantic[{mode}]: recomputed secondary decode median "
                       f"{p['secondary_decode_median']} != receipt-declared "
                       f"{p['declared_secondary_decode_median']}")
            if p["secondary_prefill_median"] != p["declared_secondary_prefill_median"]:
                refuse(f"semantic[{mode}]: recomputed secondary prefill median "
                       f"{p['secondary_prefill_median']} != receipt-declared "
                       f"{p['declared_secondary_prefill_median']}")

            # per-card medians: role -> UUID -> pinned port -> receipt stream.
            # The ordinal nvidia-smi index is never consulted here.
            stream_by_port = {binding["primary_port"]: p["decode_median"],
                              binding["secondary_port"]: p["secondary_decode_median"]}
            for role_key, declared in claim["per_card_medians"].items():
                if role_key not in roles:
                    refuse(f"semantic[{mode}]: per-card median names unknown role "
                           f"{role_key!r}")
                port = roles[role_key]["port"]
                if port not in stream_by_port:
                    refuse(f"semantic[{mode}]: role {role_key!r} is pinned to serve "
                           f":{port}, which this phase did not drive")
                if stream_by_port[port] != declared:
                    refuse(f"semantic[{mode}]: per-card median for {role_key!r} "
                           f"(UUID {roles[role_key]['uuid']}, serve :{port}) is "
                           f"{stream_by_port[port]} != capsule {declared}")

            aggregate = round(p["decode_median"] + p["secondary_decode_median"], 1)
            if aggregate != claim["aggregate_decode_tok_s"] or aggregate != p["aggregate_decode"]:
                refuse(f"semantic[{mode}]: aggregate {aggregate} != capsule "
                       f"{claim['aggregate_decode_tok_s']} / receipt {p['aggregate_decode']}")
            single = capsule["phase_results"]["single-27b-msi"]["decode_tok_s_median"]
            scaling = round(aggregate / single, 2)
            if scaling != claim["scaling_x"]:
                refuse(f"semantic[{mode}]: scaling {scaling} != capsule {claim['scaling_x']}")
            retention = round(min(p["decode_median"], p["secondary_decode_median"])
                              / single * 100, 1)
            if retention != claim["retention_pct"]:
                refuse(f"semantic[{mode}]: concurrency retention {retention} "
                       f"!= capsule {claim['retention_pct']}")
        else:
            if p["decode_median"] != claim["decode_tok_s_median"]:
                refuse(f"semantic[{mode}]: decode median {p['decode_median']} "
                       f"!= capsule {claim['decode_tok_s_median']}")

        if "prefill_tok_s_median" in claim and p["prefill_median"] != claim["prefill_tok_s_median"]:
            refuse(f"semantic[{mode}]: prefill median {p['prefill_median']} "
                   f"!= capsule {claim['prefill_tok_s_median']}")

        if "vram_split_gb" in claim:
            got = [p["vram_gb_during"][i] for i in sorted(p["vram_gb_during"])]
            want = sorted(claim["vram_split_gb"], reverse=True)
            if sorted(got, reverse=True) != want:
                refuse(f"semantic[{mode}]: VRAM allocation {got} != capsule "
                       f"{claim['vram_split_gb']}")


def run(capsule_path: Path, estate_root: Path | None) -> str:
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    verify_capsule_only(capsule)
    level = "CAPSULE_ONLY_VERIFIED"
    print(f"CAPSULE_ONLY_VERIFIED: root {capsule['aggregate_evidence_root_sha256']}")
    if estate_root is not None:
        verify_raw_bytes(capsule, estate_root)
        level = "RAW_BYTES_VERIFIED"
        print(f"RAW_BYTES_VERIFIED: {len(capsule['receipt_manifest_sha256'])} files "
              f"rehash exactly under {estate_root}")
        recon = reconstruct_from_estate(
            estate_root,
            capsule["qualification_mode_denominator"]["modes"],
            [m["name"] for m in capsule["model_identities"]])
        verify_raw_semantics(capsule, recon)
        level = "RAW_SEMANTICS_VERIFIED"
        print("RAW_SEMANTICS_VERIFIED: raw artifact contents support every "
              "decision-critical capsule claim (GPU UUIDs, card roles via serve "
              "pinning, effective core locks, ollama manifest digests, mode "
              "denominator, run counts, per-sample token counts, recomputed "
              "decode/prefill medians for both streams, per-card medians, "
              "aggregate/scaling/retention, VRAM, terminal verdict)")
        print("CLAUDE-5 repository closure: SUPPORTED at this level")
    else:
        print("note: CLAUDE-5 closure support requires RAW_SEMANTICS_VERIFIED "
              "(--estate-root on the custody host)")
    return level


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estate-root", default=None,
                        help="local raw-evidence root (raw bytes + semantics levels)")
    parser.add_argument("--capsule", default=None,
                        help="capsule path override (verification testing)")
    args = parser.parse_args()
    capsule_path = Path(args.capsule) if args.capsule else DEFAULT_CAPSULE
    estate = Path(args.estate_root) if args.estate_root else None
    try:
        run(capsule_path, estate)
    except VerificationFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
