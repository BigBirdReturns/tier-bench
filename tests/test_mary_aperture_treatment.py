from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.mary_aperture_treatment import (  # noqa: E402
    canonical_bytes,
    run_treatment,
    sha256_json,
)

FIXTURES = ROOT / "labs" / "mary-aperture-treatment" / "fixtures"
PLAN = FIXTURES / "plan.json"
VERDICT = FIXTURES / "verdict.json"
RESPONSE = FIXTURES / "response.json"
SEALED_RECEIPT = ROOT / "labs" / "mary-aperture-treatment" / "SANITIZED-TREATMENT-RECEIPT.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resign(plan: dict, verdict: dict, response: dict) -> tuple[dict, dict, dict]:
    plan = copy.deepcopy(plan)
    verdict = copy.deepcopy(verdict)
    response = copy.deepcopy(response)
    plan["plan_sha256"] = sha256_json({k: v for k, v in plan.items() if k != "plan_sha256"})
    verdict["plan"] = copy.deepcopy(plan)
    verdict["verdict_sha256"] = sha256_json(
        {k: v for k, v in verdict.items() if k != "verdict_sha256"}
    )
    response["plan_sha256"] = plan["plan_sha256"]
    for result in response["owned_results"]:
        result["response_sha256"] = sha256_json(
            {k: v for k, v in result.items() if k != "response_sha256"}
        )
    response["response_sha256"] = sha256_json(
        {k: v for k, v in response.items() if k != "response_sha256"}
    )
    return plan, verdict, response


class MaryApertureTreatmentTests(unittest.TestCase):
    def run_packet(self, plan: dict, verdict: dict, response: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            verdict_path = root / "verdict.json"
            response_path = root / "response.json"
            write(plan_path, plan)
            write(verdict_path, verdict)
            write(response_path, response)
            return run_treatment(
                plan_path=plan_path,
                verdict_path=verdict_path,
                response_path=response_path,
            )

    def test_sanitized_packet_passes_and_matches_sealed_receipt(self) -> None:
        result = run_treatment(
            plan_path=PLAN,
            verdict_path=VERDICT,
            response_path=RESPONSE,
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["observations"]["owned_clause_count"], 5)
        self.assertEqual(result["observations"]["unowned_clause_count"], 2)
        self.assertEqual(result["observations"]["machine_session_count"], 4)
        self.assertEqual(result["observations"]["machine_query_count"], 5)
        self.assertFalse(result["observations"]["internet_used"])
        self.assertFalse(result["observations"]["frontier_model_used"])
        self.assertFalse(result["observations"]["mutation_attempted"])
        self.assertFalse(result["authority"]["model_may_decide_ownership"])
        self.assertEqual(result, load(SEALED_RECEIPT))

    def test_cli_emits_byte_identical_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "receipt.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tier_runner.mary_aperture_treatment",
                    "--plan",
                    str(PLAN),
                    "--verdict",
                    str(VERDICT),
                    "--response",
                    str(RESPONSE),
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(out.read_bytes(), SEALED_RECEIPT.read_bytes())

    def test_plan_byte_mutation_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            shutil.copy2(PLAN, plan)
            text = plan.read_text(encoding="utf-8").replace(
                "candidate_only", "fabricated", 1
            )
            plan.write_text(text, encoding="utf-8")
            result = run_treatment(
                plan_path=plan,
                verdict_path=VERDICT,
                response_path=RESPONSE,
            )
            self.assertEqual(result["status"], "refused")
            self.assertIn("candidate_only", result["reason"])

    def test_model_selected_ownership_refuses_even_when_resigned(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        plan["ownership_decider"] = "frontier_model"
        for clause in plan["clauses"]:
            clause["ownership_decider"] = "frontier_model"
        plan["model_used_for_ownership"] = True
        plan, verdict, response = resign(plan, verdict, response)
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("deterministic_registry", result["reason"])

    def test_missing_covering_cartridge_refuses_even_when_resigned(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        plan["clauses"][0]["covering_cartridge_ids"] = []
        plan, verdict, response = resign(plan, verdict, response)
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("requires a covering cartridge", result["reason"])

    def test_authority_widening_refuses_even_when_resigned(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        response["authority"] = "execute"
        plan, verdict, response = resign(plan, verdict, response)
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("response authority", result["reason"])

    def test_provider_free_packet_refuses_internet_route(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        clause = plan["clauses"][0]
        clause_id = clause["clause_id"]
        clause["route"] = "internet"
        plan["summary"]["by_route"]["tier_desk"].remove(clause_id)
        plan["summary"]["by_route"]["internet"] = [clause_id]
        plan["summary"]["internet_required"] = True
        response["owned_results"][0]["route"] = "internet"
        response["summary"]["internet_used"] = True
        plan, verdict, response = resign(plan, verdict, response)
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("provider-free", result["reason"])

    def test_response_plan_cross_binding_refuses(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        response["plan_sha256"] = "0" * 64
        response["response_sha256"] = sha256_json(
            {k: v for k, v in response.items() if k != "response_sha256"}
        )
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("not bound", result["reason"])

    def test_missing_evidence_refuses(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        response["owned_results"][0]["evidence"] = []
        plan, verdict, response = resign(plan, verdict, response)
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("at least one evidence reference", result["reason"])

    def test_duplicate_json_key_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            plan_path.write_text(
                '{"schema":"mary/operator-aperture-plan@1","schema":"duplicate"}\n',
                encoding="utf-8",
            )
            result = run_treatment(
                plan_path=plan_path,
                verdict_path=VERDICT,
                response_path=RESPONSE,
            )
            self.assertEqual(result["status"], "refused")
            self.assertIn("duplicate JSON key", result["reason"])

    def test_forbidden_aggregate_score_refuses(self) -> None:
        plan, verdict, response = load(PLAN), load(VERDICT), load(RESPONSE)
        response["aggregate_score"] = 1.0
        response["response_sha256"] = sha256_json(
            {k: v for k, v in response.items() if k != "response_sha256"}
        )
        result = self.run_packet(plan, verdict, response)
        self.assertEqual(result["status"], "refused")
        self.assertIn("forbidden aggregate", result["reason"])

    def test_canonical_bytes_end_with_one_lf(self) -> None:
        encoded = canonical_bytes({"b": 2, "a": 1})
        self.assertEqual(encoded, b'{"a":1,"b":2}\n')


if __name__ == "__main__":
    unittest.main()
