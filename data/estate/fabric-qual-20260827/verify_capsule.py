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
                     effective per-card core lock under the min-rule PROVEN on
                     the applier's executable path (comments, string literals
                     and unreferenced function bodies are erased first), the
                     device attestation bound to its own host, claim, schema,
                     class and device denominator, and the model denominator
                     DERIVED from the driver dispatch and the phase receipts -
                     with the capsule's model identities and the bound ollama
                     manifest artifacts required to equal it exactly. All
                     derived from digest-bound raw artifacts, and NEVER from an
                     nvidia-smi ordinal index.
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
import datetime
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

# The committed core-lock rule, as the property pair the applier must combine
# and the nvidia-smi flag through which the computed value must actually reach
# the device. TEXTUAL PRESENCE IS NOT EVIDENCE: a comment, a string literal, an
# unreferenced function body, or an assignment that is discarded before the
# application all "contain" the rule without executing it. The rule is proven
# structurally on the executable path - see ps_executable_source() and
# parse_lock_rule_ps().
LOCK_RULE_MODE_PROPERTY = "coreLock"
LOCK_RULE_CAP_PROPERTY = "coreLockCapMHz"
LOCK_APPLY_FLAG = "-lgc"

# Attestation binding. The device readback is SUPPLEMENTAL evidence about board
# identity; it is never per-run telemetry, and it is only admissible for the
# host and claim it names.
ATTESTATION_SCHEMA = "estate/fabric-identity-attestation@1"
SUPPLEMENTAL_ATTESTATION_CLASSES = {"POST_RUN_READBACK"}
OLLAMA_MANIFEST_ROOT = "identity/ollama-manifests"

# identity_evidence subkeys the capsule must declare so the attestation can be
# bound to a coordinate rather than merely cited.
REQUIRED_IDENTITY_EVIDENCE_KEYS = [
    "core_lock_host_mode",
    "core_lock_policy_rule",
    "attestation",
    "attestation_schema",
    "attestation_class",
    "attested_device_denominator",
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


# --------------------------------------------------------------------------
# PowerShell executable-path analysis
#
# Everything below exists so the committed core-lock rule is established from
# the code the applier RUNS. Comments, literal string text, and the bodies of
# functions nothing reachable ever calls are erased first; the rule is then
# required to appear as a real assignment chain that survives to the nvidia-smi
# application. Expandable-string subexpressions ("$(...)") are executable and
# are deliberately preserved.
# --------------------------------------------------------------------------

def _blank(chars: list[str], start: int, end: int) -> None:
    for k in range(max(start, 0), min(end, len(chars))):
        if chars[k] != "\n":
            chars[k] = " "


def _keep_interpolations(src: str, chars: list[str], start: int, end: int) -> None:
    """Blank the literal text of an expandable string body, keeping only the
    executable parts: `$( ... )` subexpressions and `$variable` references."""
    i = start
    while i < end:
        c = src[i]
        if c == "`":                       # backtick escape: two literal chars
            _blank(chars, i, min(end, i + 2))
            i += 2
            continue
        if c == "$" and i + 1 < end and src[i + 1] == "(":
            depth, j = 0, i + 1
            while j < end:
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            i = min(j, end)                # kept verbatim
            continue
        if c == "$" and i + 1 < end and (src[i + 1].isalpha() or src[i + 1] in "_{"):
            j = i + 1
            if src[j] == "{":
                while j < end and src[j] != "}":
                    j += 1
                j = min(end, j + 1)
            else:
                while j < end and (src[j].isalnum() or src[j] in "_:."):
                    j += 1
                while j < end and src[j] == "[":
                    depth = 0
                    while j < end:
                        if src[j] == "[":
                            depth += 1
                        elif src[j] == "]":
                            depth -= 1
                            if depth == 0:
                                j += 1
                                break
                        j += 1
            i = j                          # kept verbatim
            continue
        _blank(chars, i, i + 1)
        i += 1


def ps_strip_noncode(src: str) -> str:
    """Erase PowerShell comments and literal string text, preserving offsets."""
    chars = list(src)
    n = len(src)
    i = 0
    while i < n:
        c = src[i]
        if src.startswith("<#", i):
            j = src.find("#>", i + 2)
            j = n if j < 0 else j + 2
            _blank(chars, i, j)
            i = j
            continue
        if c == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            _blank(chars, i, j)
            i = j
            continue
        if c == "@" and i + 1 < n and src[i + 1] in "'\"":
            quote = src[i + 1]
            term = "\n" + quote + "@"
            j = src.find(term, i + 2)
            body_end = n if j < 0 else j + 1
            j = n if j < 0 else j + len(term)
            _blank(chars, i, i + 2)
            if quote == '"':
                _keep_interpolations(src, chars, i + 2, body_end)
            else:
                _blank(chars, i + 2, body_end)
            _blank(chars, body_end, j)
            i = j
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if src[j] == "'":
                    if j + 1 < n and src[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            _blank(chars, i, min(n, j + 1))
            i = min(n, j + 1)
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if src[j] == "`":
                    j += 2
                    continue
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            end = min(n, j)
            _blank(chars, i, i + 1)
            _keep_interpolations(src, chars, i + 1, end)
            _blank(chars, end, min(n, end + 1))
            i = min(n, end + 1)
            continue
        i += 1
    return "".join(chars)


def _match_brace(text: str, open_idx: int) -> int:
    depth = 0
    for j in range(open_idx, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        _blank(chars, start, end)
    return "".join(chars)


def ps_executable_source(src: str) -> str:
    """Reduce a PowerShell script to the statements that can actually run:
    comments and literal string text erased, plus the bodies of every function
    that no reachable code ever names."""
    clean = ps_strip_noncode(src)
    funcs: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(r"(?im)^[ \t]*function[ \t]+([A-Za-z_][\w\-]*)", clean):
        brace = clean.find("{", m.end())
        if brace < 0:
            continue
        end = _match_brace(clean, brace)
        if end < 0:
            continue
        funcs[m.group(1).lower()] = (m.start(), brace + 1, end)
    if not funcs:
        return clean

    all_spans = [(sp[0], sp[2] + 1) for sp in funcs.values()]

    def search_text(exclude: str | None) -> str:
        if exclude is None:
            return _blank_spans(clean, all_spans)
        span = funcs[exclude]
        others = [(sp[0], sp[2] + 1) for name, sp in funcs.items() if name != exclude]
        return _blank_spans(clean, others)[span[1]:span[2]]

    live: set[str] = set()
    frontier = [search_text(None)]
    while frontier:
        text = frontier.pop()
        for name in funcs:
            if name in live:
                continue
            if re.search(r"(?<![\w\-.])" + re.escape(name) + r"(?![\w\-])", text, re.I):
                live.add(name)
                frontier.append(search_text(name))

    dead = [(funcs[n][1], funcs[n][2]) for n in funcs if n not in live]
    return _blank_spans(clean, dead)


_ASSIGN_RE = re.compile(r"^\s*\$(?P<var>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<rhs>.+?)\s*$")
_INDEX_ASSIGN_RE = re.compile(
    r"^\s*\$(?P<map>[A-Za-z_]\w*)\s*\[(?P<idx>[^\]]*)\]\s*=(?!=)\s*(?P<rhs>.+?)\s*$")
_MODE_LOCK_RE = re.compile(
    r"\$(?P<obj>[A-Za-z_]\w*)\s*\.\s*" + LOCK_RULE_MODE_PROPERTY + r"(?![\w])")
_CARD_CAP_RE = re.compile(
    r"\$(?P<obj>[A-Za-z_]\w*)\s*\.\s*" + LOCK_RULE_CAP_PROPERTY + r"(?![\w])")


def _ps_statements(text: str) -> list[dict]:
    """Line-granular statement records carrying brace depth and, for every
    statement, the block opener that introduced its innermost scope."""
    out: list[dict] = []
    openers: list[str] = []
    for lineno, line in enumerate(text.splitlines()):
        out.append({
            "lineno": lineno,
            "text": line,
            "depth": len(openers),
            "opener": openers[-1] if openers else "",
        })
        for ch in line:                    # in order: '{ ... }' on one line nets zero
            if ch == "{":
                openers.append(line)
            elif ch == "}" and openers:
                openers.pop()
    return out


def parse_lock_rule_ps(gpu_mode_src: str) -> dict:
    """Prove the executable applier computes
    min(<mode>.coreLock, <card>.coreLockCapMHz) and applies THAT value.

    Structural requirements, all on the executable path:
      1. a base assignment   $V = $<mode>.coreLock
      2. a strictly-deeper (conditional) override $V = $<card>.coreLockCapMHz
      3. whose innermost enclosing block is guarded by a comparison that only
         takes the cap when the cap is strictly below $V (that IS min())
      4. $V reaches the device: it is stored into a lock map that is applied
         through the nvidia-smi lock flag, and nothing reassigns $V in between.
    """
    exe = ps_executable_source(gpu_mode_src)
    stmts = _ps_statements(exe)

    bases: list[tuple[dict, str, str]] = []       # stmt, var, mode object
    overrides: list[tuple[dict, str, str]] = []   # stmt, var, card object
    assignments: list[tuple[dict, str]] = []      # every $var = ... statement
    stores: list[tuple[dict, str, str]] = []      # stmt, map name, rhs
    for st in stmts:
        m = _ASSIGN_RE.match(st["text"])
        if m:
            assignments.append((st, m.group("var")))
            mode_hit = _MODE_LOCK_RE.search(m.group("rhs"))
            cap_hit = _CARD_CAP_RE.search(m.group("rhs"))
            if cap_hit:
                overrides.append((st, m.group("var"), cap_hit.group("obj")))
            elif mode_hit:
                bases.append((st, m.group("var"), mode_hit.group("obj")))
        mi = _INDEX_ASSIGN_RE.match(st["text"])
        if mi:
            stores.append((st, mi.group("map"), mi.group("rhs")))

    if not bases:
        refuse("core-lock rule: the executable applier never assigns the host "
               f"mode's .{LOCK_RULE_MODE_PROPERTY} as the base lock value")
    if not overrides:
        refuse("core-lock rule: the executable applier never applies the card's "
               f".{LOCK_RULE_CAP_PROPERTY} cap")

    reasons: list[str] = []
    for base_st, var, mode_obj in bases:
        for ovr_st, ovr_var, card_obj in overrides:
            if ovr_var != var:
                continue
            if ovr_st["lineno"] <= base_st["lineno"]:
                reasons.append(f"the .{LOCK_RULE_CAP_PROPERTY} cap for ${var} is "
                               f"applied before the base lock value")
                continue
            if ovr_st["depth"] <= base_st["depth"]:
                reasons.append(f"the .{LOCK_RULE_CAP_PROPERTY} override of ${var} is "
                               "unconditional, so the applier does not compute a minimum")
                continue
            guard = ovr_st["opener"]
            cap = (r"(?:\[[^\]]*\]\s*)?\$" + re.escape(card_obj) + r"\s*\.\s*"
                   + LOCK_RULE_CAP_PROPERTY + r"(?![\w])")
            lt_forms = [
                cap + r"\s*-lt\s*\$" + re.escape(var) + r"(?![\w])",
                r"\$" + re.escape(var) + r"\s*-gt\s*" + cap,
            ]
            if not any(re.search(f, guard) for f in lt_forms):
                reasons.append(
                    f"the conditional that applies ${card_obj}.{LOCK_RULE_CAP_PROPERTY} "
                    f"to ${var} is not guarded by a strict 'cap below current lock' "
                    "comparison, so it is not a minimum")
                continue
            clobber = [a for a in assignments
                       if a[1] == var and base_st["lineno"] < a[0]["lineno"]
                       and a[0]["lineno"] != ovr_st["lineno"]
                       and a[0]["depth"] <= base_st["depth"]]
            for store_st, map_name, rhs in stores:
                if rhs.strip() != f"${var}":
                    continue
                if store_st["lineno"] <= ovr_st["lineno"]:
                    continue
                if any(c[0]["lineno"] < store_st["lineno"] for c in clobber):
                    reasons.append(f"${var} is reassigned between the core-lock "
                                   "computation and its application")
                    continue
                applied = [s for s in stmts
                           if LOCK_APPLY_FLAG in s["text"]
                           and re.search(r"\$" + re.escape(map_name) + r"(?![\w])",
                                         s["text"])]
                if not applied:
                    reasons.append(f"the computed lock is stored into ${map_name} but "
                                   f"${map_name} never reaches an nvidia-smi "
                                   f"{LOCK_APPLY_FLAG} application")
                    continue
                return {
                    "lock_var": var,
                    "mode_object": mode_obj,
                    "card_object": card_obj,
                    "lock_map": map_name,
                    "base_line": base_st["lineno"] + 1,
                    "override_line": ovr_st["lineno"] + 1,
                    "apply_line": applied[0]["lineno"] + 1,
                    "rule": (f"min(${mode_obj}.{LOCK_RULE_MODE_PROPERTY}, "
                             f"${card_obj}.{LOCK_RULE_CAP_PROPERTY})"),
                }
            reasons.append(f"the computed lock ${var} is never stored for "
                           f"{LOCK_APPLY_FLAG} application")

    detail = "; ".join(dict.fromkeys(reasons)) or "no executable min-rule chain"
    refuse(f"core-lock rule: the executable applier does not implement "
           f"min(mode.{LOCK_RULE_MODE_PROPERTY}, card.{LOCK_RULE_CAP_PROPERTY}) - {detail}")


def parse_lock_policy(host: dict, cards: dict, gpu_mode_src: str) -> dict:
    """Derive the effective core lock per GPU UUID under the committed rule
    min(host_mode.coreLock, cards[uuid].coreLockCapMHz), after proving that the
    applier's EXECUTABLE path is that rule."""
    rule = parse_lock_rule_ps(gpu_mode_src)

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
        "executable_rule": rule,
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
    if capsule["schema"] != "estate/fabric-qual-capsule@4":
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

    evidence = capsule["identity_evidence"]
    for key in REQUIRED_IDENTITY_EVIDENCE_KEYS:
        if key not in evidence:
            refuse(f"identity evidence missing required key {key!r}")
    if evidence["attestation_schema"] != ATTESTATION_SCHEMA:
        refuse(f"capsule declares attestation schema "
               f"{evidence['attestation_schema']!r}, not {ATTESTATION_SCHEMA!r}")
    if evidence["attestation_class"] not in SUPPLEMENTAL_ATTESTATION_CLASSES:
        refuse(f"attestation class {evidence['attestation_class']!r} is not a "
               "supplemental class; the device readback must never be declared "
               "as per-run telemetry")
    if evidence["attested_device_denominator"] != len(capsule["gpu_identities"]):
        refuse("attested device denominator "
               f"{evidence['attested_device_denominator']} != the capsule's "
               f"{len(capsule['gpu_identities'])} GPU identities")

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

    recon: dict = {
        "summary_phase_denominator": sorted(summary.get("phases", {})),
        "terminal_verdict_pass": str(summary.get("verdict", "")).startswith("PASS"),
        "host": summary.get("host"),
        "date": summary.get("date"),
        "driver": driver,
        "serve_pinning": pinning,
        "lock_policy": lock,
        "model_manifest_sha256": {},
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

    # The model denominator is DERIVED from the authoritative phase evidence -
    # the driver's own dispatch and every phase receipt - never selected by the
    # capsule. A capsule that drops an identity for a model its phases still
    # run must refuse, and so must one that carries an identity no phase used.
    driver_models = {driver["phases"][m]["model"]
                     for m in modes if m in driver["phases"]}
    receipt_models = {recon["phases"][m]["model"] for m in modes}
    derived = driver_models | receipt_models
    recon["derived_model_names"] = sorted(derived)
    recon["driver_model_names"] = sorted(driver_models)
    recon["receipt_model_names"] = sorted(receipt_models)

    for name in sorted(derived):
        p = estate_root / manifest_relpath_for_model(name)
        if not p.is_file():
            refuse(f"model manifest for {name!r} (dispatched by a phase) is "
                   "absent from the raw estate")
        recon["model_manifest_sha256"][name] = sha256_file(p)
    # capsule-only names are hashed where possible so the set comparison, not a
    # missing file, is what reports an identity no phase ever dispatched
    for name in sorted(set(model_names or []) - derived):
        p = estate_root / manifest_relpath_for_model(name)
        recon["model_manifest_sha256"][name] = sha256_file(p) if p.is_file() else None
    return recon


def _parse_utc(value: object, what: str) -> datetime.datetime:
    if not isinstance(value, str) or not value.strip():
        refuse(f"semantic identity: {what} carries no timestamp")
    try:
        ts = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        refuse(f"semantic identity: {what} timestamp {value!r} is not ISO-8601")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts.astimezone(datetime.timezone.utc)


def _verify_attestation(capsule: dict, recon: dict, claimed_uuids: list[str]) -> None:
    """Bind the device attestation to its identity coordinate.

    The attestation is admissible only for the host, claim, schema, class and
    device denominator it is presented against. An attestation belonging to
    another host - or one that presents itself as per-run telemetry rather than
    a post-run readback - can never support this capsule, however faithfully
    its UUID rows match.
    """
    att = recon["attestation"]
    evidence = capsule["identity_evidence"]

    if att.get("schema") != evidence["attestation_schema"]:
        refuse(f"semantic identity: attestation schema {att.get('schema')!r} "
               f"!= capsule {evidence['attestation_schema']!r}")
    if att.get("host") != capsule["host"]:
        refuse(f"semantic identity: attestation names host {att.get('host')!r}, "
               f"which is not the capsule's host {capsule['host']!r}")
    if att.get("observation_class") != evidence["attestation_class"]:
        refuse(f"semantic identity: attestation class "
               f"{att.get('observation_class')!r} != capsule "
               f"{evidence['attestation_class']!r}")
    if att.get("observation_class") not in SUPPLEMENTAL_ATTESTATION_CLASSES:
        refuse(f"semantic identity: attestation class "
               f"{att.get('observation_class')!r} is not a supplemental class")

    supplements = att.get("supplements")
    if not isinstance(supplements, dict):
        refuse("semantic identity: attestation does not declare the claim it "
               "supplements")
    if supplements.get("capsule_claim_id") != capsule["claim_id"]:
        refuse(f"semantic identity: attestation supplements claim "
               f"{supplements.get('capsule_claim_id')!r} != capsule claim "
               f"{capsule['claim_id']!r}")
    if not str(supplements.get("statement", "")).strip():
        refuse("semantic identity: attestation carries no supplemental statement, "
               "so it does not disclaim being per-run telemetry")

    rows = att.get("nvidia_smi_rows")
    if not isinstance(rows, list) or not rows:
        refuse("semantic identity: attestation carries no device rows")
    if len(rows) != evidence["attested_device_denominator"]:
        refuse(f"semantic identity: attestation reads back {len(rows)} devices "
               f"!= capsule attested denominator "
               f"{evidence['attested_device_denominator']}")
    attested = sorted(row.split(",")[1].strip() for row in rows)
    if len(set(attested)) != len(attested):
        refuse(f"semantic identity: attestation repeats a device UUID {attested}")
    if attested != claimed_uuids:
        refuse(f"semantic identity: attested device UUIDs {attested} "
               f"!= capsule GPU UUIDs {claimed_uuids}")

    observed = _parse_utc(att.get("observed_utc"), "attestation")
    run_date = _parse_utc(capsule["date"], "capsule date")
    if observed < run_date:
        refuse(f"semantic identity: attestation observed at "
               f"{att.get('observed_utc')} precedes the qualification date "
               f"{capsule['date']}, which contradicts its "
               f"{att.get('observation_class')!r} classification")


def _verify_model_denominator(capsule: dict, recon: dict) -> None:
    """Require exact set equality between the models the phases actually
    dispatch, the capsule's model identities, and the bound ollama manifests."""
    derived = set(recon["derived_model_names"])
    if not derived:
        refuse("semantic identity: no phase dispatches a model")

    names = [m["name"] for m in capsule["model_identities"]]
    if len(set(names)) != len(names):
        refuse(f"semantic identity: capsule declares a duplicate model identity "
               f"in {sorted(names)}")

    modes = capsule["qualification_mode_denominator"]["modes"]
    claimed_by_phases = {capsule["phase_results"][mode]["model"] for mode in modes}
    if claimed_by_phases != derived:
        refuse("semantic identity: capsule phase results name models "
               f"{sorted(claimed_by_phases)} != the models the driver and "
               f"receipts dispatch {sorted(derived)}")

    if set(names) != derived:
        missing = sorted(derived - set(names))
        additional = sorted(set(names) - derived)
        refuse("semantic identity: model identity set does not equal the models "
               f"the phases dispatch (missing={missing} additional={additional})")

    manifest = capsule["receipt_manifest_sha256"]
    bound = {rel for rel in manifest if rel.startswith(OLLAMA_MANIFEST_ROOT + "/")}
    expected = {manifest_relpath_for_model(name) for name in derived}
    if bound != expected:
        refuse("semantic identity: bound ollama manifest artifacts "
               f"{sorted(bound)} != the manifests of the dispatched models "
               f"{sorted(expected)}")


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

    _verify_attestation(capsule, recon, claimed_uuids)

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

    _verify_model_denominator(capsule, recon)

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
            # The role denominator is DERIVED: receipt streams -> pinned serve
            # ports -> UUID-bound card roles. Iterating only the entries the
            # capsule supplies would accept an omission as silently as a match.
            driven_roles = {rk for rk, r in roles.items()
                            if r["port"] in stream_by_port}
            declared_roles = set(claim["per_card_medians"])
            if declared_roles != driven_roles:
                refuse(f"semantic[{mode}]: per-card median roles "
                       f"{sorted(declared_roles)} != the UUID-bound roles whose "
                       f"pinned serves this phase drove {sorted(driven_roles)}")
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
            if "per_card_medians" in claim:
                refuse(f"semantic[{mode}]: phase drove a single stream but the "
                       "capsule claims per-card medians for it")
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
