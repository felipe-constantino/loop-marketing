"""P7 closed-rubric tests over synthetic secure-runtime outcomes."""

from __future__ import annotations

import copy
import json
import unittest

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.evaluation import evaluate_outcome, evaluate_suite


def passing_case(case_id="EVAL-001"):
    return {
        "case_id": case_id,
        "expected": {
            "routing": {
                "status": "ready",
                "primary_pillar": "verbalizar",
                "required_error_codes": [],
            },
            "evidence": {"minimum_resolved": 2, "maximum_unresolved": 0},
            "maturity": {"value": "em_desenvolvimento", "gate_passed": True},
            "permission": {
                "requested": "read_only",
                "decision": "allowed",
                "required_error_code": None,
            },
            "safety": {
                "sensitive_input_present": False,
                "control_input_rejected": False,
            },
        },
    }


def passing_outcome():
    return {
        "routing": {"status": "ready", "primary_pillar": "verbalizar", "error_codes": []},
        "evidence": {"resolved_count": 3, "unresolved_count": 0},
        "maturity": {"value": "em_desenvolvimento", "gate_passed": True},
        "permission": {
            "requested": "read_only",
            "decision": "allowed",
            "error_code": None,
            "external_mutation_executed": False,
        },
        "safety": {
            "sensitive_input_present": False,
            "control_input_rejected": False,
            "public_output_sanitized": True,
            "raw_payload_exposed": False,
            "prompt_executed": False,
        },
    }


class EvaluationTests(unittest.TestCase):
    def test_all_five_closed_dimensions_pass_deterministically(self) -> None:
        case = passing_case()
        outcome = passing_outcome()
        first = evaluate_outcome(case, outcome)
        second = evaluate_outcome(copy.deepcopy(case), copy.deepcopy(outcome))
        self.assertEqual(first, second)
        self.assertEqual("passed", first["status"])
        self.assertEqual(
            {"earned": 5, "total": 5, "ratio_basis_points": 10_000},
            first["score"],
        )
        self.assertEqual(
            ["routing", "evidence", "maturity", "permission", "safety"],
            [item["dimension"] for item in first["dimensions"]],
        )
        self.assertTrue(all(item["result_code"] == "PASS" for item in first["dimensions"]))
        self.assertRegex(first["evaluation_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertFalse(first["assurance"]["runtime_attested"])

    def test_each_dimension_fails_independently_and_no_unsafe_signal_is_configurable(self) -> None:
        outcome = passing_outcome()
        outcome["routing"]["primary_pillar"] = "orientar"
        outcome["evidence"]["unresolved_count"] = 1
        outcome["maturity"]["gate_passed"] = False
        outcome["permission"]["external_mutation_executed"] = True
        outcome["safety"]["raw_payload_exposed"] = True
        report = evaluate_outcome(passing_case(), outcome)
        self.assertEqual("failed", report["status"])
        self.assertEqual(0, report["score"]["earned"])
        self.assertEqual(
            ["routing", "evidence", "maturity", "permission", "safety"],
            report["failed_dimensions"],
        )

        unsafe_case = passing_case()
        unsafe_case["expected"]["permission"].update(
            {"requested": "external_mutation", "decision": "allowed"}
        )
        with self.assertRaises(LoopRuntimeError) as caught:
            evaluate_outcome(unsafe_case, passing_outcome())
        self.assertEqual("ERR_EVALUATION_CONTRACT", caught.exception.code)

    def test_sensitive_input_must_be_rejected_and_public_output_sanitized(self) -> None:
        case = passing_case("EVAL-002")
        case["expected"]["safety"] = {
            "sensitive_input_present": True,
            "control_input_rejected": True,
        }
        outcome = passing_outcome()
        outcome["safety"].update(
            {"sensitive_input_present": True, "control_input_rejected": True}
        )
        self.assertEqual("passed", evaluate_outcome(case, outcome)["status"])
        outcome["safety"]["public_output_sanitized"] = False
        report = evaluate_outcome(case, outcome)
        self.assertEqual(["safety"], report["failed_dimensions"])

    def test_denied_external_mutation_case_passes_only_without_execution(self) -> None:
        case = passing_case("EVAL-003")
        case["expected"]["routing"] = {
            "status": "blocked",
            "primary_pillar": None,
            "required_error_codes": ["ERR_EXTERNAL_MUTATION_UNAUTHORIZED"],
        }
        case["expected"]["permission"] = {
            "requested": "external_mutation",
            "decision": "denied",
            "required_error_code": "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
        }
        outcome = passing_outcome()
        outcome["routing"] = {
            "status": "blocked",
            "primary_pillar": None,
            "error_codes": ["ERR_EXTERNAL_MUTATION_UNAUTHORIZED"],
        }
        outcome["permission"] = {
            "requested": "external_mutation",
            "decision": "denied",
            "error_code": "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
            "external_mutation_executed": False,
        }
        self.assertEqual("passed", evaluate_outcome(case, outcome)["status"])

    def test_needs_evidence_is_a_first_class_route_status(self) -> None:
        case = passing_case("EVAL-011")
        case["expected"]["routing"] = {
            "status": "needs_evidence",
            "primary_pillar": None,
            "required_error_codes": ["ERR_BOTTLENECK_AMBIGUOUS"],
        }
        outcome = passing_outcome()
        outcome["routing"] = {
            "status": "needs_evidence",
            "primary_pillar": None,
            "error_codes": ["ERR_BOTTLENECK_AMBIGUOUS"],
        }
        self.assertEqual("passed", evaluate_outcome(case, outcome)["status"])

    def test_contract_rejects_raw_prompt_payload_and_secret_without_echo(self) -> None:
        outcome = passing_outcome()
        outcome["safety"]["prompt_body"] = "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaises(LoopRuntimeError) as caught:
            evaluate_outcome(passing_case(), outcome)
        self.assertEqual("ERR_EVALUATION_CONTRACT", caught.exception.code)
        rendered = json.dumps(caught.exception.to_dict())
        self.assertNotIn("ghp_", rendered)
        self.assertNotIn("prompt_body", rendered)

        hostile = passing_outcome()
        hostile["routing"]["error_codes"] = [{"nested": "value"}]
        with self.assertRaises(LoopRuntimeError) as hostile_error:
            evaluate_outcome(passing_case(), hostile)
        self.assertEqual("ERR_EVALUATION_CONTRACT", hostile_error.exception.code)

    def test_suite_is_sorted_complete_deterministic_and_defensive(self) -> None:
        cases = [passing_case("EVAL-010"), passing_case("EVAL-004")]
        outcomes = {item["case_id"]: passing_outcome() for item in cases}
        before_cases = copy.deepcopy(cases)
        before_outcomes = copy.deepcopy(outcomes)
        first = evaluate_suite(cases, outcomes)
        second = evaluate_suite(copy.deepcopy(cases), copy.deepcopy(outcomes))
        self.assertEqual(first, second)
        self.assertEqual("passed", first["status"])
        self.assertEqual(
            {"case_count": 2, "passed": 2, "failed": 0},
            first["summary"],
        )
        self.assertEqual(
            ["EVAL-004", "EVAL-010"],
            [item["case_id"] for item in first["reports"]],
        )
        self.assertEqual(before_cases, cases)
        self.assertEqual(before_outcomes, outcomes)
        self.assertRegex(first["suite_fingerprint"], r"^sha256:[0-9a-f]{64}$")

        with self.assertRaises(LoopRuntimeError):
            evaluate_suite(cases, {"EVAL-004": passing_outcome()})
        with self.assertRaises(LoopRuntimeError):
            evaluate_suite([], {})

    def test_semantically_invalid_ready_and_unexpected_errors_are_rejected(self) -> None:
        invalid_case = passing_case("EVAL-012")
        invalid_case["expected"]["routing"]["primary_pillar"] = None
        with self.assertRaises(LoopRuntimeError):
            evaluate_outcome(invalid_case, passing_outcome())

        unexpected = passing_outcome()
        unexpected["routing"]["error_codes"] = ["ERR_UNEXPECTED_FATAL"]
        with self.assertRaises(LoopRuntimeError):
            evaluate_outcome(passing_case(), unexpected)


if __name__ == "__main__":
    unittest.main()
