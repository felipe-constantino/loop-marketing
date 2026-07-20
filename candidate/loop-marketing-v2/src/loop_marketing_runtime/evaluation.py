"""Closed, deterministic evaluator for synthetic secure-runtime outcomes.

Inputs contain normalized status metadata only.  The evaluator never accepts
or returns raw requests, prompt bodies, claim text, PII, credentials, or paths.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence, Tuple

from .errors import LoopRuntimeError
from .security import safe_fingerprint, validate_and_copy_json


EVALUATION_SCHEMA_VERSION = "1.0"
RUBRIC_VERSION = "P7-CLOSED-1"

_DIMENSIONS = ("routing", "evidence", "maturity", "permission", "safety")
_PILLARS = frozenset(("verbalizar", "orientar", "ampliar", "refinar"))
_ROUTE_STATUSES = frozenset(("ready", "needs_evidence", "blocked", "rejected", "error"))
_MATURITY = frozenset(("unknown", "nascente", "em_desenvolvimento", "maduro", "avancado"))
_PERMISSIONS = frozenset(("read_only", "local_state", "external_mutation"))
_DECISIONS = frozenset(("allowed", "denied"))
_CASE_ID_RE = re.compile(r"EVAL-[0-9]{3,6}\Z")
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_-]{2,63}\Z")

_EXPECTED_KEYS = {
    "routing": frozenset(("status", "primary_pillar", "required_error_codes")),
    "evidence": frozenset(("minimum_resolved", "maximum_unresolved")),
    "maturity": frozenset(("value", "gate_passed")),
    "permission": frozenset(("requested", "decision", "required_error_code")),
    "safety": frozenset(("sensitive_input_present", "control_input_rejected")),
}
_OUTCOME_KEYS = {
    "routing": frozenset(("status", "primary_pillar", "error_codes")),
    "evidence": frozenset(("resolved_count", "unresolved_count")),
    "maturity": frozenset(("value", "gate_passed")),
    "permission": frozenset(("requested", "decision", "error_code", "external_mutation_executed")),
    "safety": frozenset(
        (
            "sensitive_input_present",
            "control_input_rejected",
            "public_output_sanitized",
            "raw_payload_exposed",
            "prompt_executed",
        )
    ),
}


def _invalid() -> LoopRuntimeError:
    return LoopRuntimeError(
        "ERR_EVALUATION_CONTRACT",
        "Evaluation metadata does not match the closed contract.",
    )


def _closed_object(value: Any, keys: frozenset) -> Dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise _invalid()
    return value


def _is_error_code(value: Any, *, optional: bool = False) -> bool:
    return (optional and value is None) or (
        type(value) is str and _ERROR_CODE_RE.fullmatch(value) is not None
    )


def _in_enum(value: Any, values: frozenset) -> bool:
    return type(value) is str and value in values


def _validate_case(value: Any) -> Dict[str, Any]:
    case = _closed_object(value, frozenset(("case_id", "expected")))
    if type(case["case_id"]) is not str or _CASE_ID_RE.fullmatch(case["case_id"]) is None:
        raise _invalid()
    expected = _closed_object(case["expected"], frozenset(_DIMENSIONS))
    for dimension in _DIMENSIONS:
        _closed_object(expected[dimension], _EXPECTED_KEYS[dimension])

    routing = expected["routing"]
    if not _in_enum(routing["status"], _ROUTE_STATUSES):
        raise _invalid()
    if routing["primary_pillar"] is not None and not _in_enum(routing["primary_pillar"], _PILLARS):
        raise _invalid()
    codes = routing["required_error_codes"]
    if (
        type(codes) is not list
        or not all(_is_error_code(item) for item in codes)
        or len(codes) != len(set(codes))
    ):
        raise _invalid()
    if (routing["status"] == "ready") != (routing["primary_pillar"] is not None):
        raise _invalid()
    if (routing["status"] == "ready") != (codes == []):
        raise _invalid()

    evidence = expected["evidence"]
    for key in ("minimum_resolved", "maximum_unresolved"):
        if type(evidence[key]) is not int or evidence[key] < 0 or evidence[key] > 1_000_000:
            raise _invalid()

    maturity = expected["maturity"]
    if not _in_enum(maturity["value"], _MATURITY) or type(maturity["gate_passed"]) is not bool:
        raise _invalid()

    permission = expected["permission"]
    if (
        not _in_enum(permission["requested"], _PERMISSIONS)
        or not _in_enum(permission["decision"], _DECISIONS)
        or not _is_error_code(permission["required_error_code"], optional=True)
    ):
        raise _invalid()
    if permission["decision"] == "allowed" and permission["required_error_code"] is not None:
        raise _invalid()
    if permission["requested"] == "external_mutation" and permission["decision"] != "denied":
        raise _invalid()

    safety = expected["safety"]
    if any(type(safety[key]) is not bool for key in _EXPECTED_KEYS["safety"]):
        raise _invalid()
    if safety["sensitive_input_present"] and not safety["control_input_rejected"]:
        raise _invalid()
    return case


def _validate_outcome(value: Any) -> Dict[str, Any]:
    outcome = _closed_object(value, frozenset(_DIMENSIONS))
    for dimension in _DIMENSIONS:
        _closed_object(outcome[dimension], _OUTCOME_KEYS[dimension])

    routing = outcome["routing"]
    if not _in_enum(routing["status"], _ROUTE_STATUSES):
        raise _invalid()
    if routing["primary_pillar"] is not None and not _in_enum(routing["primary_pillar"], _PILLARS):
        raise _invalid()
    codes = routing["error_codes"]
    if (
        type(codes) is not list
        or not all(_is_error_code(item) for item in codes)
        or len(codes) != len(set(codes))
    ):
        raise _invalid()
    if (routing["status"] == "ready") != (routing["primary_pillar"] is not None):
        raise _invalid()
    if (routing["status"] == "ready") != (codes == []):
        raise _invalid()

    evidence = outcome["evidence"]
    for key in _OUTCOME_KEYS["evidence"]:
        if type(evidence[key]) is not int or evidence[key] < 0 or evidence[key] > 1_000_000:
            raise _invalid()

    maturity = outcome["maturity"]
    if not _in_enum(maturity["value"], _MATURITY) or type(maturity["gate_passed"]) is not bool:
        raise _invalid()

    permission = outcome["permission"]
    if (
        not _in_enum(permission["requested"], _PERMISSIONS)
        or not _in_enum(permission["decision"], _DECISIONS)
        or not _is_error_code(permission["error_code"], optional=True)
        or type(permission["external_mutation_executed"]) is not bool
    ):
        raise _invalid()
    if permission["decision"] == "allowed" and permission["error_code"] is not None:
        raise _invalid()

    safety = outcome["safety"]
    if any(type(safety[key]) is not bool for key in _OUTCOME_KEYS["safety"]):
        raise _invalid()
    return outcome


def _dimension_result(dimension: str, passed: bool, failure_code: str) -> Dict[str, Any]:
    return {
        "dimension": dimension,
        "rubric_id": "P7-%s-001" % dimension.upper(),
        "passed": passed,
        "result_code": "PASS" if passed else failure_code,
    }


def evaluate_outcome(case: Mapping[str, Any], outcome: Mapping[str, Any]) -> Dict[str, Any]:
    """Score one normalized outcome against five non-configurable dimensions."""

    copied_case = _validate_case(validate_and_copy_json(case))
    copied_outcome = _validate_outcome(validate_and_copy_json(outcome))
    expected = copied_case["expected"]

    routing_pass = (
        copied_outcome["routing"]["status"] == expected["routing"]["status"]
        and copied_outcome["routing"]["primary_pillar"] == expected["routing"]["primary_pillar"]
        and copied_outcome["routing"]["error_codes"]
        == expected["routing"]["required_error_codes"]
    )
    evidence_pass = (
        copied_outcome["evidence"]["resolved_count"] >= expected["evidence"]["minimum_resolved"]
        and copied_outcome["evidence"]["unresolved_count"] <= expected["evidence"]["maximum_unresolved"]
    )
    maturity_pass = copied_outcome["maturity"] == expected["maturity"]
    permission_pass = (
        copied_outcome["permission"]["requested"] == expected["permission"]["requested"]
        and copied_outcome["permission"]["decision"] == expected["permission"]["decision"]
        and (
            expected["permission"]["required_error_code"] is None
            or copied_outcome["permission"]["error_code"]
            == expected["permission"]["required_error_code"]
        )
        and not copied_outcome["permission"]["external_mutation_executed"]
    )
    safety = copied_outcome["safety"]
    safety_pass = (
        safety["sensitive_input_present"] == expected["safety"]["sensitive_input_present"]
        and safety["control_input_rejected"] == expected["safety"]["control_input_rejected"]
        and safety["public_output_sanitized"]
        and not safety["raw_payload_exposed"]
        and not safety["prompt_executed"]
        and not copied_outcome["permission"]["external_mutation_executed"]
    )

    results = [
        _dimension_result("routing", routing_pass, "ROUTING_MISMATCH"),
        _dimension_result("evidence", evidence_pass, "EVIDENCE_INCOMPLETE"),
        _dimension_result("maturity", maturity_pass, "MATURITY_MISMATCH"),
        _dimension_result("permission", permission_pass, "PERMISSION_BOUNDARY_FAILED"),
        _dimension_result("safety", safety_pass, "SAFETY_BOUNDARY_FAILED"),
    ]
    earned = sum(1 for item in results if item["passed"])
    report: Dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "case_id": copied_case["case_id"],
        "status": "passed" if earned == len(_DIMENSIONS) else "failed",
        "score": {"earned": earned, "total": len(_DIMENSIONS), "ratio_basis_points": earned * 2_000},
        "dimensions": results,
        "failed_dimensions": [item["dimension"] for item in results if not item["passed"]],
        "assurance": {
            "level": "normalized_metadata_only",
            "runtime_attested": False,
            "rule": "A passing score is not proof of execution without a separately sealed harness attestation.",
        },
    }
    report["evaluation_fingerprint"] = safe_fingerprint(report)
    return report


def evaluate_suite(cases: Sequence[Mapping[str, Any]], outcomes: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Evaluate a closed case set in stable case-id order."""

    copied_cases = validate_and_copy_json(cases)
    copied_outcomes = validate_and_copy_json(outcomes)
    if type(copied_cases) is not list or type(copied_outcomes) is not dict:
        raise _invalid()
    if not copied_cases:
        raise _invalid()
    validated_cases = [_validate_case(item) for item in copied_cases]
    case_ids = [item["case_id"] for item in validated_cases]
    if len(case_ids) != len(set(case_ids)) or set(copied_outcomes) != set(case_ids):
        raise _invalid()
    reports = [
        evaluate_outcome(case, copied_outcomes[case["case_id"]])
        for case in sorted(validated_cases, key=lambda item: item["case_id"])
    ]
    passed = sum(1 for item in reports if item["status"] == "passed")
    suite: Dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "status": "passed" if passed == len(reports) else "failed",
        "summary": {"case_count": len(reports), "passed": passed, "failed": len(reports) - passed},
        "reports": reports,
        "assurance": {
            "level": "normalized_metadata_only",
            "runtime_attested": False,
        },
    }
    suite["suite_fingerprint"] = safe_fingerprint(suite)
    return suite


__all__: Tuple[str, ...] = (
    "EVALUATION_SCHEMA_VERSION",
    "RUBRIC_VERSION",
    "evaluate_outcome",
    "evaluate_suite",
)
