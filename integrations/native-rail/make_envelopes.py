#!/usr/bin/env python3
"""Generate the v3 envelope set, positive and negative, from one binding.

Keeping these generated rather than hand-written means every envelope agrees on
the bound revision, and the negative witnesses differ from a valid envelope by
exactly the one property under test.

v3: repository work is expressed as `repo.operation` against the accepted
repository-operation manifest. No envelope names a script, a digest, an argv or
a switch.
"""
import copy
import json
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "envelopes-v3")
OUT.mkdir(parents=True, exist_ok=True)

HEAD = "fb47a4cc50e74ac230efe1b063631933a5106a0a"
TREE = "72ceba0bd0d695aa4d8eae953c3c0ebe5a438a4f"
BUNDLE = "estate-fb47a4cc.bundle"
BUNDLE_SHA = "f379b74463c181a829e7893add829fdfc0926cf2516328ef4a89f0858190a5db"
RESOLVER = "estate_authority_resolver.py"
ARTIFACT = "tbrail-crash-artifact.txt"
ARTIFACT_SHA = "af520fc67d79ef399934d25ce3c7337cfd23706b23a7f3cbddc9fbd08d0b21a6"

BASE = {
    "schema": "tier-bench/native-transaction-envelope@3",
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
    "result_schema": "tier-bench/native-transaction-receipt@3",
    "publication_ceiling": "STATUS_ONLY",
    "source_bundle": BUNDLE,
    "source_bundle_sha256": BUNDLE_SHA,
    "phases": [],
}

VERIFY_OP = {"name": "verify-registry-and-alias-digests", "op": "repo.operation",
             "params": {"operation": "estate.authority-verify", "values": {}}}
RENDER_OP = {"name": "render-inert-organ-map", "op": "repo.operation",
             "params": {"operation": "estate.render-organ-map",
                        "values": {"out": "organ-map-qualification.html"}}}

CANARY_PHASES = [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER, "test_estate_authority_resolver.py"]}},
    {"name": "authority-and-cold-reconstruction-witnesses", "op": "python.unittest",
     "params": {"module": "test_estate_authority_resolver", "verbose": True}},
    copy.deepcopy(VERIFY_OP),
    copy.deepcopy(RENDER_OP),
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
    copy.deepcopy(VERIFY_OP),
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:defect-probe"))
write("isolation", env("estate-isolation-001", [
    {"name": "assert-worker-has-no-credential", "op": "rail.credential_probe",
     "params": {}},
], resource_key="estate:main:credential-isolation-probe"))

# ---- leases -------------------------------------------------------------
write("collision-holder", env("estate-collision-holder-001", [
    {"name": "hold-resource", "op": "rail.hold_resource", "params": {"seconds": 25}},
], resource_key="estate:main:collision-probe"))
write("collision-contender", env("estate-collision-contender-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
], resource_key="estate:main:collision-probe"))
# a phase deliberately longer than the lease TTL: a live holder must survive it
write("ttl-holder", env("estate-ttl-holder-001", [
    {"name": "hold-past-lease-ttl", "op": "rail.hold_resource",
     "params": {"seconds": 150}, "timeout_seconds": 300},
], resource_key="estate:main:ttl-probe"))
write("ttl-contender", env("estate-ttl-contender-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
], resource_key="estate:main:ttl-probe"))
# settlement window: the contender must still be refused while the subject is
# publishing its receipt and transitioning to SETTLED
write("settlement-subject", env("estate-settlement-subject-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
], resource_key="estate:main:settlement-probe"))
write("settlement-contender", env("estate-settlement-contender-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
], resource_key="estate:main:settlement-probe"))

write("teardown", env("estate-teardown-001", [
    {"name": "spawn-live-descendant", "op": "rail.spawn_descendant",
     "params": {"seconds": 300}, "timeout_seconds": 5},
], resource_key="estate:main:teardown-probe"))

# ---- crash recovery -----------------------------------------------------
write("crash-pure", env("estate-crash-pure-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
    {"name": "hold-resource", "op": "rail.hold_resource", "params": {"seconds": 30}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:crash-pure-probe"))
write("crash-effectful", env("estate-crash-effectful-001", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": [RESOLVER]}},
    {"name": "inject-deliberate-defect", "op": "rail.append_byte",
     "params": {"target": "estate_organ_registry.json"}},
    {"name": "verify-no-source-mutation", "op": "git.diff_exit_code", "params": {}},
], resource_key="estate:main:crash-effectful-probe"))
# the artifact-producing crash subject: phase 2 can only pass if the state
# phase 0 produced survived the crash
write("crash-artifact", env("estate-crash-artifact-001", [
    {"name": "produce-artifact", "op": "rail.produce_artifact",
     "params": {"target": ARTIFACT, "payload": "artifact-survives-crash"}},
    {"name": "hold-resource", "op": "rail.hold_resource", "params": {"seconds": 30}},
    {"name": "require-artifact", "op": "rail.require_artifact",
     "params": {"target": ARTIFACT, "sha256": ARTIFACT_SHA}},
], resource_key="estate:main:crash-artifact-probe"))

# ---- enforced ceilings --------------------------------------------------
write("burn-output", env("estate-burn-output-001", [
    {"name": "burn-output", "op": "rail.burn_output", "params": {"megabytes": 8},
     "timeout_seconds": 180, "limits": {"max_output_bytes": 262144}},
], resource_key="estate:main:burn-probe"))
write("burn-memory", env("estate-burn-memory-001", [
    {"name": "burn-memory", "op": "rail.burn_memory", "params": {"megabytes": 2048},
     "timeout_seconds": 180, "limits": {"address_space_bytes": 536870912}},
], resource_key="estate:main:burn-probe"))
write("burn-disk", env("estate-burn-disk-001", [
    {"name": "burn-disk", "op": "rail.burn_disk", "params": {"megabytes": 64},
     "timeout_seconds": 180, "limits": {"file_size_bytes": 4194304}},
], resource_key="estate:main:burn-probe"))
write("burn-cpu", env("estate-burn-cpu-001", [
    {"name": "burn-cpu", "op": "rail.burn_cpu", "params": {"seconds": 120},
     "timeout_seconds": 180, "limits": {"cpu_seconds": 3}},
], resource_key="estate:main:burn-probe"))
write("burn-pids", env("estate-burn-pids-001", [
    {"name": "burn-pids", "op": "rail.burn_pids", "params": {"count": 400},
     "timeout_seconds": 120, "limits": {"max_processes": 24}},
], resource_key="estate:main:burn-probe"))

# ---------------- negative: must be refused at submit ----------------
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
neg("limit-above-ceiling", "phase limit above the controller ceiling",
    lambda e: e["phases"][0].__setitem__("limits", {"address_space_bytes": 1 << 40}))
neg("unknown-limit", "unknown resource limit name",
    lambda e: e["phases"][0].__setitem__("limits", {"gpu_seconds": 5}))
neg("legacy-repo-script", "the withdrawn envelope-defined repository script route",
    lambda e: e["phases"][2].__setitem__("op", "python.repo_script"))

# ---------------- negative: refused at execute time ----------------
def exec_neg(name, phases, **over):
    write(f"exec-neg-{name}", env(f"neg-{name}", phases,
                                  resource_key="estate:main:negative-probe", **over))


exec_neg("op-not-in-manifest", [
    {"name": "unadmitted-operation", "op": "repo.operation",
     "params": {"operation": "estate.arbitrary-shell", "values": {}}},
])
exec_neg("undeclared-value", [
    {"name": "undeclared-operation-value", "op": "repo.operation",
     "params": {"operation": "estate.authority-verify",
                "values": {"out": "x.html"}}},
])
exec_neg("switch-value", [
    {"name": "switch-shaped-value", "op": "repo.operation",
     "params": {"operation": "estate.render-organ-map",
                "values": {"out": "--exec=/bin/sh"}}},
])
exec_neg("value-grammar", [
    {"name": "value-outside-declared-grammar", "op": "repo.operation",
     "params": {"operation": "estate.render-organ-map",
                "values": {"out": "pwn.sh"}}},
])
exec_neg("allowed-path", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": ["../../../../etc/passwd"]}},
])
exec_neg("outside-allowed", [
    {"name": "compile-candidate", "op": "python.py_compile",
     "params": {"targets": ["tools/other.py"]}},
], allowed_paths=["docs"])

(OUT / "NEGATIVE-INDEX.json").write_text(json.dumps(NEG, indent=2), encoding="utf-8")
print(f"wrote {len(list(OUT.glob('*.json')))} envelopes to {OUT}")
