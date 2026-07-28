"""Executable estate laboratory runtime."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .adapters import AdapterRefused, execute_adapter
from .canonical import canonical_json_bytes, sha256_hex, stable_id, write_json
from .errors import AuthorityRefused, ProjectionMismatch, RouteRefused, ScenarioError
from .model import (
    EstateManifest,
    RouteDecision,
    ScenarioOutcome,
    ScenarioSpec,
    SemanticAction,
    StepOutcome,
)
from .probes import adapter_status_from_environment, discover_repositories, run_probes
from .reducer import (
    causal_debrief,
    desired_output,
    reduce_action,
    semantic_event,
    validate_authority,
)
from .report import render_html, render_markdown
from .routing import choose_route


def _matches_subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _matches_subset(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(_matches_subset(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _route_evaluations(decision: RouteDecision) -> list[dict[str, Any]]:
    return [
        {
            "route_id": evaluation.route_id,
            "eligible": evaluation.eligible,
            "score": evaluation.score,
            "refusal_reasons": list(evaluation.refusal_reasons),
            "metrics": asdict(evaluation.metrics),
        }
        for evaluation in decision.evaluations
    ]


def _step_dict(step: StepOutcome) -> dict[str, Any]:
    return asdict(step)


class EstateLab:
    """Run deterministic route, equivalence, fault, and repository probes."""

    def __init__(
        self,
        manifest: EstateManifest,
        *,
        workspace: Path | None = None,
        execution_mode: str = "synthetic",
        probe_profile: str = "none",
    ) -> None:
        if execution_mode not in {"synthetic", "live"}:
            raise ValueError("execution_mode must be synthetic or live")
        self.manifest = manifest
        self.workspace = workspace
        self.execution_mode = execution_mode
        self.probe_profile = probe_profile
        self.repositories = discover_repositories(manifest, workspace)
        self.probe_results, self.probe_logs = run_probes(
            manifest,
            self.repositories,
            profile=probe_profile,
        )
        self.adapter_status = adapter_status_from_environment(
            manifest,
            self.repositories,
            self.probe_results,
            execution_mode=execution_mode,
        )
        self.manifest_id = stable_id("manifest1", manifest.raw, 32)

    def _execute_step(
        self,
        *,
        scenario_id: str,
        run_id: str,
        state: dict[str, Any],
        action: SemanticAction,
        sequence: int,
        applied_event_ids: set[str],
        evidence: dict[str, list[dict[str, Any]]],
        candidate_route_ids: Iterable[str] | None = None,
        forced_route_id: str | None = None,
        unavailable_route_ids: Iterable[str] = (),
        fault: str | None = None,
        epoch_override: int | None = None,
    ) -> tuple[dict[str, Any], StepOutcome]:
        before_hash = sha256_hex(state)
        route_id_for_failure = forced_route_id or "unselected"
        try:
            candidates = (forced_route_id,) if forced_route_id else tuple(candidate_route_ids or action.route_ids)
            decision = choose_route(
                self.manifest,
                action_id=action.semantic_id,
                required_role=action.required_role,
                required_mandate=action.required_mandate,
                candidate_route_ids=candidates or None,
                constraints=action.route_query,
                unavailable_route_ids=unavailable_route_ids,
                adapter_status=self.adapter_status,
            )
            route = self.manifest.routes[decision.route_id]
            route_id_for_failure = route.route_id
            validate_authority(state, action, route, epoch_override=epoch_override)

            event = semantic_event(
                run_id=run_id,
                sequence=sequence,
                route_id=route.route_id,
                action=action,
                state_before_hash=before_hash,
            )
            event_id = event["event_id"]
            if event_id in applied_event_ids:
                outcome = StepOutcome(
                    step_id=action.step_id,
                    route_id=route.route_id,
                    outcome="duplicate",
                    reason="event_already_applied",
                    event_id=event_id,
                    state_before_hash=before_hash,
                    state_after_hash=before_hash,
                    output_hash=None,
                    debrief_hash=None,
                    route_score=decision.score,
                    details={"route_evaluations": _route_evaluations(decision)},
                )
                evidence["route_decisions"].append(
                    {
                        "step_id": action.step_id,
                        "selected_route_id": decision.route_id,
                        "score": decision.score,
                        "evaluations": _route_evaluations(decision),
                        "duplicate": True,
                    }
                )
                return state, outcome

            source_adapter = self.manifest.adapters[route.source_adapter]
            target_adapter = self.manifest.adapters[route.target_adapter]
            source_response = execute_adapter(
                source_adapter,
                phase="source",
                event=event,
                repository=self.repositories.get(source_adapter.organ_id),
                execution_mode=self.execution_mode,
                fault="adapter_semantic_mutation" if fault == "adapter_semantic_mutation" else None,
            )
            target_response = execute_adapter(
                target_adapter,
                phase="target",
                event=event,
                repository=self.repositories.get(target_adapter.organ_id),
                execution_mode=self.execution_mode,
                fault="target_refusal" if fault == "target_refusal" else None,
            )

            next_state, before_value, after_value = reduce_action(state, action)
            output = desired_output(
                scenario_id=scenario_id,
                action=action,
                before=before_value,
                after=after_value,
            )
            expected_output_hash = sha256_hex(output)
            if fault == "projection_mutation":
                output = copy.deepcopy(output)
                output.setdefault("channels", {})["injected_corruption"] = True
            actual_output_hash = sha256_hex(output)
            if actual_output_hash != expected_output_hash:
                raise ProjectionMismatch(
                    f"expected {expected_output_hash}, got {actual_output_hash}"
                )

            debrief = causal_debrief(
                scenario_id=scenario_id,
                action=action,
                before=before_value,
                after=after_value,
            )
            after_hash = sha256_hex(next_state)
            if "after" in action.expected and after_value != action.expected["after"]:
                raise ScenarioError(
                    f"step {action.step_id} expected after={action.expected['after']!r}, got {after_value!r}"
                )
            if "state_subset" in action.expected and not _matches_subset(
                next_state,
                action.expected["state_subset"],
            ):
                raise ScenarioError(f"step {action.step_id} state subset did not match")

            applied_event_ids.add(event_id)
            evidence["events"].append(event)
            evidence["adapter_responses"].extend([source_response, target_response])
            evidence["outputs"].append(output)
            evidence["debriefs"].append(debrief)
            evidence["route_decisions"].append(
                {
                    "step_id": action.step_id,
                    "selected_route_id": decision.route_id,
                    "score": decision.score,
                    "evaluations": _route_evaluations(decision),
                }
            )
            outcome = StepOutcome(
                step_id=action.step_id,
                route_id=route.route_id,
                outcome="committed",
                reason=None,
                event_id=event_id,
                state_before_hash=before_hash,
                state_after_hash=after_hash,
                output_hash=actual_output_hash,
                debrief_hash=sha256_hex(debrief),
                route_score=decision.score,
                details={
                    "route_evaluations": _route_evaluations(decision),
                    "source_response_id": source_response.get("response_id"),
                    "target_response_id": target_response.get("response_id"),
                    "before": before_value,
                    "after": after_value,
                },
            )
            return next_state, outcome
        except RouteRefused as exc:
            return state, StepOutcome(
                step_id=action.step_id,
                route_id=route_id_for_failure,
                outcome="refused",
                reason=exc.reason,
                event_id=None,
                state_before_hash=before_hash,
                state_after_hash=before_hash,
                output_hash=None,
                debrief_hash=None,
                route_score=None,
                details=exc.details,
            )
        except AuthorityRefused as exc:
            return state, StepOutcome(
                step_id=action.step_id,
                route_id=route_id_for_failure,
                outcome="refused",
                reason=exc.reason,
                event_id=None,
                state_before_hash=before_hash,
                state_after_hash=before_hash,
                output_hash=None,
                debrief_hash=None,
                route_score=None,
                details=exc.details,
            )
        except AdapterRefused as exc:
            return state, StepOutcome(
                step_id=action.step_id,
                route_id=route_id_for_failure,
                outcome="faulted",
                reason=exc.reason,
                event_id=None,
                state_before_hash=before_hash,
                state_after_hash=before_hash,
                output_hash=None,
                debrief_hash=None,
                route_score=None,
                details=exc.details,
            )
        except ProjectionMismatch as exc:
            return state, StepOutcome(
                step_id=action.step_id,
                route_id=route_id_for_failure,
                outcome="faulted",
                reason="projection_digest_mismatch",
                event_id=None,
                state_before_hash=before_hash,
                state_after_hash=before_hash,
                output_hash=None,
                debrief_hash=None,
                route_score=None,
                details={"message": str(exc)},
            )
        except ScenarioError as exc:
            return state, StepOutcome(
                step_id=action.step_id,
                route_id=route_id_for_failure,
                outcome="faulted",
                reason="scenario_assertion_failed",
                event_id=None,
                state_before_hash=before_hash,
                state_after_hash=before_hash,
                output_hash=None,
                debrief_hash=None,
                route_score=None,
                details={"message": str(exc)},
            )

    def _run_routing_trials(self, scenario: ScenarioSpec) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        failures: list[str] = []
        for trial in scenario.routing_trials:
            try:
                decision = choose_route(
                    self.manifest,
                    action_id=trial.action_prefix,
                    required_role=str(trial.constraints.get("required_role", "engineering")),
                    required_mandate=str(
                        trial.constraints.get("required_mandate", "ship.engineering.control")
                    ),
                    candidate_route_ids=trial.candidate_route_ids or None,
                    constraints={
                        key: value
                        for key, value in trial.constraints.items()
                        if key not in {"required_role", "required_mandate"}
                    },
                    unavailable_route_ids=trial.unavailable_route_ids,
                    adapter_status=self.adapter_status,
                )
                actual = f"selected:{decision.route_id}"
                expected = (
                    f"selected:{trial.expected_route_id}"
                    if trial.expected_outcome == "selected"
                    else "refused"
                )
                passed = trial.expected_outcome == "selected" and decision.route_id == trial.expected_route_id
                records.append(
                    {
                        "trial_id": trial.trial_id,
                        "actual": actual,
                        "expected": expected,
                        "passed": passed,
                        "selected_route_id": decision.route_id,
                        "score": decision.score,
                        "evaluations": _route_evaluations(decision),
                    }
                )
            except RouteRefused as exc:
                actual = f"refused:{exc.reason}"
                expected = (
                    f"selected:{trial.expected_route_id}"
                    if trial.expected_outcome == "selected"
                    else "refused"
                )
                passed = trial.expected_outcome == "refused"
                records.append(
                    {
                        "trial_id": trial.trial_id,
                        "actual": actual,
                        "expected": expected,
                        "passed": passed,
                        "selected_route_id": None,
                        "score": None,
                        "evaluations": exc.details.get("evaluations", []),
                    }
                )
            if not records[-1]["passed"]:
                failures.append(
                    f"routing trial {trial.trial_id} expected {records[-1]['expected']} "
                    f"but observed {records[-1]['actual']}"
                )
        return records, failures

    @staticmethod
    def _outcome_code(outcome: StepOutcome) -> str:
        if outcome.outcome in {"committed", "duplicate"}:
            return outcome.outcome
        return f"{outcome.outcome}:{outcome.reason}"

    def _run_fault_trials(
        self,
        scenario: ScenarioSpec,
        *,
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        failures: list[str] = []
        action_by_id = {action.step_id: action for action in scenario.actions}

        for index, trial in enumerate(scenario.fault_trials, start=1):
            action = action_by_id.get(str(trial.parameters.get("step_id"))) or scenario.actions[0]
            evidence = {
                "events": [],
                "adapter_responses": [],
                "outputs": [],
                "debriefs": [],
                "route_decisions": [],
            }
            state = copy.deepcopy(scenario.initial_state)
            applied: set[str] = set()
            actual: str
            details: dict[str, Any] = {}

            setup_failed = False
            setup_records: list[dict[str, Any]] = []
            setup_ids = trial.parameters.get("setup_step_ids", [])
            if setup_ids:
                if not isinstance(setup_ids, list):
                    actual = "faulted:invalid_setup_step_ids"
                    setup_failed = True
                else:
                    for setup_sequence, setup_id in enumerate(setup_ids, start=1):
                        setup_action = action_by_id.get(str(setup_id))
                        if setup_action is None:
                            actual = "faulted:unknown_setup_step"
                            setup_failed = True
                            setup_records.append({"step_id": str(setup_id), "reason": "unknown_setup_step"})
                            break
                        state, setup_outcome = self._execute_step(
                            scenario_id=scenario.scenario_id,
                            run_id=f"{run_id}-fault-{index}-setup",
                            state=state,
                            action=setup_action,
                            sequence=setup_sequence,
                            applied_event_ids=applied,
                            evidence=evidence,
                            forced_route_id=setup_action.route_ids[0] if setup_action.route_ids else None,
                        )
                        setup_records.append(_step_dict(setup_outcome))
                        if setup_outcome.outcome != "committed":
                            actual = f"faulted:setup_{setup_outcome.reason or setup_outcome.outcome}"
                            setup_failed = True
                            break

            if setup_failed:
                details = {"setup": setup_records}
            elif trial.fault == "route_unavailable":
                candidates_raw = trial.parameters.get("candidate_route_ids", list(action.route_ids))
                if not isinstance(candidates_raw, list):
                    candidates_raw = list(action.route_ids)
                try:
                    decision = choose_route(
                        self.manifest,
                        action_id=action.semantic_id,
                        required_role=action.required_role,
                        required_mandate=action.required_mandate,
                        candidate_route_ids=tuple(str(item) for item in candidates_raw),
                        constraints=action.route_query,
                        unavailable_route_ids=(trial.route_id,) if trial.route_id else (),
                        adapter_status=self.adapter_status,
                    )
                    actual = f"selected:{decision.route_id}"
                    details["evaluations"] = _route_evaluations(decision)
                except RouteRefused as exc:
                    actual = f"refused:{exc.reason}"
                    details.update(exc.details)
            elif trial.fault == "duplicate_event":
                route_id = trial.route_id or action.route_ids[0]
                state, first = self._execute_step(
                    scenario_id=scenario.scenario_id,
                    run_id=f"{run_id}-fault-{index}",
                    state=state,
                    action=action,
                    sequence=1,
                    applied_event_ids=applied,
                    evidence=evidence,
                    forced_route_id=route_id,
                )
                state, second = self._execute_step(
                    scenario_id=scenario.scenario_id,
                    run_id=f"{run_id}-fault-{index}",
                    state=state,
                    action=action,
                    sequence=1,
                    applied_event_ids=applied,
                    evidence=evidence,
                    forced_route_id=route_id,
                )
                actual = self._outcome_code(second)
                details = {
                    "first": _step_dict(first),
                    "second": _step_dict(second),
                    "state_hash": sha256_hex(state),
                }
            else:
                route_id = trial.route_id or (action.route_ids[0] if action.route_ids else None)
                trial_action = action
                epoch_override = None
                injected_fault = trial.fault
                if trial.fault == "stale_epoch":
                    epoch_override = action.authority.ownership_epoch + int(
                        trial.parameters.get("delta", 1)
                    )
                    injected_fault = None
                elif trial.fault == "authority_role_mismatch":
                    trial_action = replace(
                        action,
                        authority=replace(action.authority, role="unauthorized-role"),
                    )
                    injected_fault = None
                state, outcome = self._execute_step(
                    scenario_id=scenario.scenario_id,
                    run_id=f"{run_id}-fault-{index}",
                    state=state,
                    action=trial_action,
                    sequence=1,
                    applied_event_ids=applied,
                    evidence=evidence,
                    forced_route_id=route_id,
                    fault=injected_fault,
                    epoch_override=epoch_override,
                )
                actual = self._outcome_code(outcome)
                details = _step_dict(outcome)

            if setup_records:
                details = dict(details)
                details["setup"] = setup_records

            expected = trial.expected_outcome
            if ":" in expected:
                passed = actual == expected
            else:
                passed = actual == expected or actual.startswith(expected + ":")
            record = {
                "trial_id": trial.trial_id,
                "fault": trial.fault,
                "actual": actual,
                "expected": expected,
                "passed": passed,
                "details": details,
            }
            records.append(record)
            if not passed:
                failures.append(
                    f"fault trial {trial.trial_id} expected {expected} but observed {actual}"
                )
        return records, failures

    def run_scenario(
        self,
        scenario: ScenarioSpec,
        *,
        output_root: Path | None = None,
    ) -> ScenarioOutcome:
        scenario_digest = sha256_hex(scenario.raw)
        run_id = stable_id(
            "labrun1",
            {
                "manifest_id": self.manifest_id,
                "scenario_digest": scenario_digest,
                "execution_mode": self.execution_mode,
                "adapter_status": self.adapter_status,
            },
            32,
        )
        evidence: dict[str, list[dict[str, Any]]] = {
            "events": [],
            "adapter_responses": [],
            "outputs": [],
            "debriefs": [],
            "route_decisions": [],
        }
        steps: list[StepOutcome] = []
        failures: list[str] = []
        equivalence: dict[str, Any] = {}

        routing_trials, routing_failures = self._run_routing_trials(scenario)
        failures.extend(routing_failures)

        if scenario.kind == "equivalence":
            action = scenario.actions[0]
            fingerprints: dict[str, dict[str, Any]] = {}
            final_states: dict[str, dict[str, Any]] = {}
            for route_id in scenario.equivalence_route_ids:
                variant_state = copy.deepcopy(scenario.initial_state)
                variant_applied: set[str] = set()
                variant_action = replace(action, step_id=f"{action.step_id}@{route_id}")
                variant_state, outcome = self._execute_step(
                    scenario_id=scenario.scenario_id,
                    run_id=run_id,
                    state=variant_state,
                    action=variant_action,
                    sequence=1,
                    applied_event_ids=variant_applied,
                    evidence=evidence,
                    forced_route_id=route_id,
                )
                steps.append(outcome)
                final_states[route_id] = variant_state
                fingerprints[route_id] = {
                    "outcome": outcome.outcome,
                    "state_hash": outcome.state_after_hash,
                    "output_hash": outcome.output_hash,
                    "debrief_hash": outcome.debrief_hash,
                }
                if outcome.outcome != "committed":
                    failures.append(
                        f"equivalence route {route_id} did not commit: {outcome.reason}"
                    )
                if scenario.expected_final_state and not _matches_subset(
                    variant_state,
                    scenario.expected_final_state,
                ):
                    failures.append(
                        f"equivalence route {route_id} did not reach the expected final state"
                    )

            state_hashes = {item["state_hash"] for item in fingerprints.values()}
            output_hashes = {item["output_hash"] for item in fingerprints.values()}
            debrief_hashes = {item["debrief_hash"] for item in fingerprints.values()}
            equivalence = {
                "fingerprints": fingerprints,
                "state_hashes_equal": len(state_hashes) == 1,
                "output_hashes_equal": len(output_hashes) == 1,
                "debrief_hashes_equal": len(debrief_hashes) == 1,
            }
            for key in ("state_hashes_equal", "output_hashes_equal", "debrief_hashes_equal"):
                if not equivalence[key]:
                    failures.append(f"equivalence gate failed: {key}")
            final_state_hash = sha256_hex(
                {route_id: sha256_hex(state) for route_id, state in sorted(final_states.items())}
            )
        else:
            state = copy.deepcopy(scenario.initial_state)
            applied_event_ids: set[str] = set()
            for sequence, action in enumerate(scenario.actions, start=1):
                state, outcome = self._execute_step(
                    scenario_id=scenario.scenario_id,
                    run_id=run_id,
                    state=state,
                    action=action,
                    sequence=sequence,
                    applied_event_ids=applied_event_ids,
                    evidence=evidence,
                    candidate_route_ids=action.route_ids or None,
                )
                steps.append(outcome)
                if outcome.outcome not in {"committed", "duplicate"}:
                    failures.append(
                        f"sequence step {action.step_id} did not commit: {outcome.reason}"
                    )
                    break
            if scenario.expected_final_state and not _matches_subset(state, scenario.expected_final_state):
                failures.append("sequence did not reach the expected final state")
            final_state_hash = sha256_hex(state)

        fault_trials, fault_failures = self._run_fault_trials(scenario, run_id=run_id)
        failures.extend(fault_failures)

        status = "passed" if not failures else "failed"
        control_question = (
            scenario.invariants[-1]
            if scenario.invariants
            else "Can every admitted route reproduce the same governed state and receipts?"
        )
        run_record = {
            "format": "axm-estate-lab-run/1",
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "manifest_id": self.manifest_id,
            "scenario_digest": scenario_digest,
            "scenario": {
                "id": scenario.scenario_id,
                "title": scenario.title,
                "kind": scenario.kind,
                "objective": scenario.objective,
            },
            "execution_mode": self.execution_mode,
            "probe_profile": self.probe_profile,
            "status": status,
            "final_state_hash": final_state_hash,
            "adapter_status": dict(sorted(self.adapter_status.items())),
            "repository_discovery": {
                organ_id: {
                    "present": path is not None,
                    "local_name": path.name if path is not None else None,
                }
                for organ_id, path in sorted(self.repositories.items())
            },
            "probes": [asdict(result) for result in self.probe_results],
            "steps": [_step_dict(step) for step in steps],
            "routing_trials": routing_trials,
            "fault_trials": fault_trials,
            "equivalence": equivalence,
            "failures": failures,
            "invariants": list(scenario.invariants),
            "control_question": control_question,
            "evidence_counts": {key: len(value) for key, value in evidence.items()},
        }

        receipt_dir: Path | None = None
        if output_root is not None:
            receipt_dir = output_root.expanduser().resolve() / scenario.scenario_id / run_id
            self._write_receipts(receipt_dir, scenario, run_record, evidence)

        return ScenarioOutcome(
            scenario_id=scenario.scenario_id,
            status=status,
            kind=scenario.kind,
            run_id=run_id,
            manifest_id=self.manifest_id,
            scenario_digest=scenario_digest,
            final_state_hash=final_state_hash,
            steps=tuple(steps),
            routing_trials=tuple(routing_trials),
            fault_trials=tuple(fault_trials),
            equivalence=equivalence,
            failures=tuple(failures),
            receipt_dir=receipt_dir,
        )

    def _write_receipts(
        self,
        receipt_dir: Path,
        scenario: ScenarioSpec,
        run_record: dict[str, Any],
        evidence: dict[str, list[dict[str, Any]]],
    ) -> None:
        receipt_dir.mkdir(parents=True, exist_ok=True)
        write_json(receipt_dir / "manifest.snapshot.json", self.manifest.raw)
        write_json(receipt_dir / "scenario.snapshot.json", scenario.raw)
        write_json(receipt_dir / "run.json", run_record)
        for name in ("adapter_responses", "outputs", "debriefs", "route_decisions"):
            write_json(receipt_dir / f"{name}.json", evidence[name])
        events_path = receipt_dir / "events.jsonl"
        events_path.write_text(
            "".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for event in evidence["events"]
            ),
            encoding="utf-8",
            newline="\n",
        )
        logs_dir = receipt_dir / "probe-logs"
        for key, log in sorted(self.probe_logs.items()):
            safe = key.replace(":", "__").replace("/", "_")
            write_json(logs_dir / f"{safe}.json", log)
        (receipt_dir / "SUMMARY.md").write_text(
            render_markdown(run_record), encoding="utf-8", newline="\n"
        )
        (receipt_dir / "report.html").write_text(
            render_html(run_record), encoding="utf-8", newline="\n"
        )

        checksum_lines: list[str] = []
        for path in sorted(receipt_dir.rglob("*")):
            if not path.is_file() or path.name == "CHECKSUMS.sha256":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {path.relative_to(receipt_dir).as_posix()}")
        (receipt_dir / "CHECKSUMS.sha256").write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )
