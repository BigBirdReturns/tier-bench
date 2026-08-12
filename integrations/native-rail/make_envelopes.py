#!/usr/bin/env python3
"""Generate the v2 envelope set, positive and negative, from one binding.

Keeping these generated rather than hand-written means every envelope agrees on
the bound revision, and the negative witnesses differ from a valid envelope by
exactly the one property under test.
"""
import copy
import json
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "envelopes-v2")
OUT.mkdir(parents=True, exist_ok=True)

HEAD = "fb47a4cc50e74ac230efe1b063631933a5106a0a"
TREE = "72ceba0bd0d695aa4d8eae953c3c0ebe5a438a4f"
BUNDLE = "estate-fb47a4cc.bundle"
BUNDLE_SHA = "f379b74463c181a829e7893add829fdfc0926cf2516328ef4a89f0858190a5db"
RESOLVER = "estate_authority_resolver.py"
RESOLVER_SHA = "94b5c196b30691e3b6a679606879a89a35bd55e2f630a30448eff746c6fdfe1e"

BASE = {
    "schema": "tier-bench/native-transaction-envelope@2",
    "transaction_id": "PLACEHOLDER",
    "repository": "BigBirdReturns/estate",
    "visibility": "private",
    "base_sha": HEAD,
    "head_sha": HEAD,
    "expected_tree": TREE,
    "coordinate": "BigBirdReturns/estate#78",
    "trust_class": "TRUSTED_PRIVATE",
    "runtime": "python3.11",
    "resource_key": "estate:main:organ-realignment-qualification",
    "allowed_paths": ["repo"],
    "result_schema": "tier-bench/native-transaction-receipt@2",
    "publication_ceiling": "STATUS_ONLY",
    "source_bundle": BUNDLE,
    "source_bundle_sha256": BUNDLE_SHA,
    "phases": [],
}

CANARY_PHASES = [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER, "test_estate_authority_resolver.py"]}},
    {"name": "authority-and-cold-reconstruction-witnesses", "op": "python.unittest",
     "params": {"module": "test_estate_authority_resolver", "verbose": True}},
    {"name": "verify-registry-and-alias-digests", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": RESOLVER_SHA, "args": ["verify"]}},
    {"name": "render-inert-organ-map", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": RESOLVER_SHA,
                "args": ["render", "--out", "organ-map-qualification.html"],
                "allowed_switches": ["--out"]}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
]


def env(txn, phases, **over):
    e = copy.deepcopy(BASE)
    e["transaction_id"] = txn
    e["phases"] = copy.deepcopy(phases)
    e.update(over)
    return e


def write(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")


# ---------------- positive ----------------
write("canary-py311", env("estate-canary-py311-001", CANARY_PHASES))
write("canary-py314", env("estate-canary-py314-001", CANARY_PHASES,
                          runtime="python3.14",
                          resource_key="estate:main:organ-realignment-matrix"))
write("defect", env("estate-defect-001", [
    {"name": "inject-deliberate-defect", "op": "rail.append_byte",
     "params": {"target": "estate_organ_registry.json"}},
    {"name": "verify-registry-and-alias-digests", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": RESOLVER_SHA, "args": ["verify"]}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:defect-probe"))
write("isolation", env("estate-isolation-001", [
    {"name": "assert-worker-has-no-credential", "op": "rail.credential_probe",
     "params": {}},
], resource_key="estate:main:credential-isolation-probe"))
write("collision-holder", env("estate-collision-holder-001", [
    {"name": "hold-resource", "op": "rail.hold_resource", "params": {"seconds": 25}},
], resource_key="estate:main:collision-probe"))
write("collision-contender", env("estate-collision-contender-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
], resource_key="estate:main:collision-probe"))
write("teardown", env("estate-teardown-001", [
    {"name": "spawn-live-descendant", "op": "rail.spawn_descendant",
     "params": {"seconds": 300}, "timeout_seconds": 5},
], resource_key="estate:main:teardown-probe"))
# crash subject: several PURE phases, the last one long enough to be killed
write("crash-pure", env("estate-crash-pure-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
    {"name": "hold-resource", "op": "rail.hold_resource", "params": {"seconds": 30}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:crash-pure-probe"))
# crash subject whose interrupted phase is EFFECTFUL -> recovery must refuse
write("crash-effectful", env("estate-crash-effectful-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
    {"name": "inject-deliberate-defect", "op": "rail.append_byte",
     "params": {"target": "estate_organ_registry.json"}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:crash-effectful-probe"))

# ---------------- negative: must be refused ----------------
NEG = {}


def neg(name, why, mutate):
    e = env(f"neg-{name}", CANARY_PHASES)
    mutate(e)
    NEG[name] = why
    write(f"neg-{name}", e)


def _set(k, v):
    return lambda e: e.__setitem__(k, v)


neg("txn-traversal", "transaction_id containing path traversal",
    _set("transaction_id", "../../../../etc/cron.d/pwn"))
neg("txn-absolute", "absolute transaction_id",
    _set("transaction_id", "/etc/shadow"))
neg("phase-separator", "phase name containing a path separator",
    lambda e: e["phases"][0].__setitem__("name", "../../escape"))
neg("unknown-top-field", "unknown top-level envelope field",
    _set("injected_by_issue_prose", "rm -rf /"))
neg("unknown-phase-field", "unknown phase field",
    lambda e: e["phases"][0].__setitem__("argv", ["sh", "-c", "id"]))
neg("bundle-absolute", "source_bundle given as an absolute native path",
    _set("source_bundle", "/etc/passwd"))
neg("bundle-traversal", "source_bundle escaping the custody root",
    _set("source_bundle", "../../../etc/passwd"))
neg("op-not-admitted", "phase naming an operation outside the registry",
    lambda e: e["phases"][0].__setitem__("op", "sh.dash_c"))
neg("bad-sha-length", "short head_sha", _set("head_sha", "fb47a4cc"))
neg("timeout-ceiling", "timeout above the admitted ceiling",
    lambda e: e["phases"][0].__setitem__("timeout_seconds", 99999))
neg("too-many-phases", "phase graph above the admitted ceiling",
    lambda e: e.__setitem__("phases", [dict(CANARY_PHASES[4], name=f"p{i}")
                                       for i in range(40)]))
neg("untrusted-fork", "fork trust class on the native rail",
    _set("trust_class", "UNTRUSTED_FORK"))
neg("runtime-not-admitted", "runtime outside the pinned set",
    _set("runtime", "/usr/bin/perl"))
neg("empty-phases", "empty phase graph", _set("phases", []))

# refused at execute time rather than submit time
write("exec-neg-script-digest", env("neg-script-digest", [
    {"name": "verify-registry-and-alias-digests", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": "0" * 64, "args": ["verify"]}},
], resource_key="estate:main:negative-probe"))
# two distinct rules, two distinct witnesses: the argument grammar rejects the
# token outright, and the switch rule rejects a well-formed but undeclared flag
write("exec-neg-arg-grammar", env("neg-arg-grammar", [
    {"name": "verify-registry-and-alias-digests", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": RESOLVER_SHA,
                "args": ["verify", "--exec=/bin/sh"]}},
], resource_key="estate:main:negative-probe"))
write("exec-neg-undeclared-switch", env("neg-undeclared-switch", [
    {"name": "verify-registry-and-alias-digests", "op": "python.repo_script",
     "params": {"script": RESOLVER, "script_sha256": RESOLVER_SHA,
                "args": ["verify", "-c"]}},
], resource_key="estate:main:negative-probe"))
write("exec-neg-allowed-path", env("neg-allowed-path", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": ["../../../../etc/passwd"]}},
], resource_key="estate:main:negative-probe"))
write("exec-neg-outside-allowed", env("neg-outside-allowed", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": ["tools/other.py"]}},
], allowed_paths=["docs"], resource_key="estate:main:negative-probe"))

(OUT / "NEGATIVE-INDEX.json").write_text(json.dumps(NEG, indent=2), encoding="utf-8")
print(f"wrote {len(list(OUT.glob('*.json')))} envelopes to {OUT}")
