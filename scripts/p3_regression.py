#!/usr/bin/env python3
"""Deterministic negative regression suite for the P3 workstream validator.

The suite copies the minimum P3 validation topology into temporary directories,
keeps PROJECT.json pointing at the original read-only source repository, and
recreates a pristine sandbox before every mutation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CONTROL_ROOT = Path(__file__).resolve().parents[1]
WORKSTREAM_NAMES = ("verbalizar", "orientar", "ampliar", "refinar")
COPY_PATHS = (
    Path("PROJECT.json"),
    Path("SOURCE_INDEX.json"),
    Path("artifacts/P3/catalog-schema.json"),
    *(Path(f"artifacts/P3/workstreams/{name}.json") for name in WORKSTREAM_NAMES),
    Path("artifacts/P3/workstreams/relation-review.json"),
    Path("scripts/p3_validate.py"),
)


@dataclass(frozen=True)
class Case:
    case_id: str
    name: str
    expected_errors: tuple[str, ...]
    mutate: Callable[[Path], None]
    stage: str = "workstreams"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def workstream_path(root: Path, name: str) -> Path:
    return root / f"artifacts/P3/workstreams/{name}.json"


def find_entry(workstream: dict[str, Any], tactic_id: str) -> dict[str, Any]:
    for entry in workstream.get("entries", []):
        if isinstance(entry, dict) and entry.get("tactic_id") == tactic_id:
            return entry
    raise KeyError(f"missing fixture tactic: {tactic_id}")


def create_sandbox(
    parent: Path, name: str, template_root: Path = CONTROL_ROOT
) -> Path:
    root = parent / name
    if root.exists():
        shutil.rmtree(root)
    for relative in COPY_PATHS:
        source = template_root / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    original_project = load_json(CONTROL_ROOT / "PROJECT.json")
    copied_project = load_json(root / "PROJECT.json")
    if copied_project != original_project:
        raise RuntimeError("sandbox PROJECT.json differs from the control baseline")
    source_repo = Path(copied_project["source"]["repo"])
    if not source_repo.is_absolute() or root == source_repo or root in source_repo.parents:
        raise RuntimeError("sandbox PROJECT.json no longer points to the original source")
    return root


def run_validator(root: Path, stage: str = "workstreams") -> dict[str, Any]:
    command = [sys.executable, str(root / "scripts/p3_validate.py"), stage]
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    try:
        candidate = json.loads(completed.stdout)
        if isinstance(candidate, dict):
            parsed = candidate
        else:
            parse_error = "validator stdout was not a JSON object"
    except json.JSONDecodeError as exc:
        parse_error = f"validator stdout was not valid JSON: {exc}"
    errors = parsed.get("errors", []) if parsed else []
    if not isinstance(errors, list):
        errors = [f"validator returned non-list errors: {errors!r}"]
    return {
        "returncode": completed.returncode,
        "status": parsed.get("status") if parsed else None,
        "stage": parsed.get("stage") if parsed else None,
        "errors": [str(item) for item in errors],
        "stderr": completed.stderr.strip(),
        "parse_error": parse_error,
    }


def mutate_remove_execution_policy(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    data["entries"][0].pop("execution_policy")
    write_json(path, data)


def mutate_remove_entry(root: Path) -> None:
    path = workstream_path(root, "orientar")
    data = load_json(path)
    data["entries"].pop()
    write_json(path, data)


def mutate_reintroduce_icp_segmentation(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    entry = find_entry(data, "lm.verbalizar.perfil-do-cliente-ideal")
    entry["job_tags"] = [*entry["job_tags"], "segment"]
    entry["object_tags"] = [*entry["object_tags"], "segmentation"]
    entry["need_tags"] = [*entry["need_tags"], "segment:segmentation"]
    entry["output_contract"]["output_type"] = "segmentation_model"
    write_json(path, data)


def mutate_automatic_allowed_with_flag(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    entry = find_entry(data, "lm.verbalizar.analisador-de-diferenciacao-de-marcas")
    entry["execution_policy"]["automatic_selection"] = "allowed"
    write_json(path, data)


def mutate_constrained_overlay_false(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    entry = find_entry(data, "lm.verbalizar.analisador-de-diferenciacao-de-marcas")
    if entry["execution_policy"]["execution_mode"] != "sidecar_constrained":
        raise ValueError("overlay fixture is no longer sidecar_constrained")
    entry["execution_policy"]["runtime_overlay_required"] = False
    write_json(path, data)


def mutate_self_confirmed_relation(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    if not data.get("relations"):
        raise ValueError("relation fixture is missing")
    data["relations"][0]["review_status"] = "confirmed"
    write_json(path, data)


def mutate_customer_program_without_pii_guard(root: Path) -> None:
    path = workstream_path(root, "ampliar")
    data = load_json(path)
    entry = find_entry(data, "lm.ampliar.amplificador-de-defesa-do-cliente")
    for requirement in entry["input_requirements"]:
        if requirement.get("sensitivity") == "customer_level_pii":
            requirement["sensitivity"] = "customer_aggregate"
    policy = entry["execution_policy"]
    policy["canonical_scope_conflicts"] = [
        conflict
        for conflict in policy["canonical_scope_conflicts"]
        if conflict.get("conflict_type") != "sensitive_data"
    ]
    policy["excluded_output_sections"] = []
    write_json(path, data)


def mutate_wrong_canonical_hash(root: Path) -> None:
    path = workstream_path(root, "orientar")
    data = load_json(path)
    data["entries"][0]["canonical_sha256"] = "0" * 64
    write_json(path, data)


def mutate_unverified_claim_without_constraint(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    entry = find_entry(data, "lm.verbalizar.analise-de-interruptores-do-setor")
    if "unverified_external_claim" not in entry["quality"]["flags"]:
        raise ValueError("unverified-claim fixture lost its quality flag")
    policy = entry["execution_policy"]
    policy["canonical_scope_conflicts"] = [
        conflict
        for conflict in policy["canonical_scope_conflicts"]
        if conflict.get("conflict_type") != "unverifiable_claim"
    ]
    write_json(path, data)


def mutate_incomplete_prohibited_decisions(root: Path) -> None:
    path = workstream_path(root, "verbalizar")
    data = load_json(path)
    entry = find_entry(data, "lm.verbalizar.esclarecimento-de-objetivo-e-missao")
    entry["execution_policy"]["prohibited_decisions"].pop()
    write_json(path, data)


def mutate_refinar_required_scope_conflict(root: Path) -> None:
    path = workstream_path(root, "refinar")
    data = load_json(path)
    entry = find_entry(data, "lm.refinar.sistema-de-integracao-de-aprendizagem")
    policy = entry["execution_policy"]
    policy["canonical_scope_conflicts"] = [
        conflict
        for conflict in policy["canonical_scope_conflicts"]
        if conflict.get("decision_domain") != "message_and_copy"
    ]
    write_json(path, data)


def mutate_refinar_weak_fallback(root: Path) -> None:
    path = workstream_path(root, "refinar")
    data = load_json(path)
    entry = find_entry(data, "lm.refinar.acelerador-de-velocidade-de-marketing")
    if entry["execution_policy"]["execution_mode"] != "sidecar_constrained":
        raise ValueError("Refinar fallback fixture is no longer sidecar_constrained")
    entry["execution_policy"]["fallback"] = (
        "Retornar TESTAR e data_gap_plan quando a evidência for insuficiente."
    )
    write_json(path, data)


def relation_review_path(root: Path) -> Path:
    return root / "artifacts/P3/workstreams/relation-review.json"


def mutate_relation_missing_decision(root: Path) -> None:
    path = relation_review_path(root)
    data = load_json(path)
    data["decisions"].pop()
    write_json(path, data)


def mutate_relation_nondeterministic_id(root: Path) -> None:
    path = relation_review_path(root)
    data = load_json(path)
    relation = data["relations"][0]
    old_id = relation["relation_id"]
    new_id = "rel-alternative-to-000000000000"
    relation["relation_id"] = new_id
    for decision in data["decisions"]:
        decision["output_relation_ids"] = [
            new_id if relation_id == old_id else relation_id
            for relation_id in decision["output_relation_ids"]
        ]
    data["relations"] = sorted(data["relations"], key=lambda item: item["relation_id"])
    write_json(path, data)


def mutate_relation_status_mismatch(root: Path) -> None:
    path = relation_review_path(root)
    data = load_json(path)
    relation_id = data["relations"][0]["relation_id"]
    data["relations"][0]["review_status"] = "proposed"
    if not any(
        decision.get("decision") == "confirm"
        and relation_id in decision.get("output_relation_ids", [])
        for decision in data["decisions"]
    ):
        raise ValueError("relation status fixture has no confirming decision")
    write_json(path, data)


def mutate_relation_accepted_without_output(root: Path) -> None:
    path = relation_review_path(root)
    data = load_json(path)
    decision = next(
        item
        for item in data["decisions"]
        if item.get("decision") == "confirm" and item.get("output_relation_ids")
    )
    decision["output_relation_ids"] = []
    write_json(path, data)


CASES = (
    Case(
        "NEG-001",
        "missing execution_policy",
        ("execution_policy fields differ from schema",),
        mutate_remove_execution_policy,
    ),
    Case(
        "NEG-002",
        "missing entry breaks pillar and global coverage",
        (
            "workstream must contain exactly 25 entries",
            "workstream catalog coverage mismatch",
        ),
        mutate_remove_entry,
    ),
    Case(
        "NEG-003",
        "Verbalizar ICP re-exposes segmentation ownership",
        ("exposes an Orientar segmentation decision through Verbalizar",),
        mutate_reintroduce_icp_segmentation,
    ),
    Case(
        "NEG-004",
        "automatic selection with review-required quality flag",
        ("allows automatic selection despite review-required flags",),
        mutate_automatic_allowed_with_flag,
    ),
    Case(
        "NEG-005",
        "sidecar constrained without runtime overlay",
        ("constrained mode lacks executable overlay constraints",),
        mutate_constrained_overlay_false,
    ),
    Case(
        "NEG-006",
        "workstream relation self-confirmed before independent replay",
        ("must remain proposed until independent replay",),
        mutate_self_confirmed_relation,
    ),
    Case(
        "NEG-007",
        "customer advocacy program without PII contract or safe-mode exclusion",
        ("under-models canonical customer-level PII without a safe-mode exclusion",),
        mutate_customer_program_without_pii_guard,
    ),
    Case(
        "NEG-008",
        "canonical hash mismatch",
        ("canonical hash differs from source",),
        mutate_wrong_canonical_hash,
    ),
    Case(
        "NEG-009",
        "unverified external claim without unverifiable-claim constraint",
        ("has an unverified claim without a constrained execution rule",),
        mutate_unverified_claim_without_constraint,
    ),
    Case(
        "NEG-010",
        "incomplete prohibited_decisions authority coverage",
        ("prohibited_decisions must cover every non-owner authority domain",),
        mutate_incomplete_prohibited_decisions,
    ),
    Case(
        "NEG-011",
        "Refinar fixture omits a source-proven cross-owner conflict",
        ("misses required Refinar cross-owner conflict domains",),
        mutate_refinar_required_scope_conflict,
    ),
    Case(
        "NEG-012",
        "Refinar constrained fallback omits fail-closed runtime behavior",
        ("constrained Refinar fallback misses do not load",),
        mutate_refinar_weak_fallback,
    ),
    Case(
        "NEG-013",
        "relation review omits one of the 106 input decisions",
        ("relation review replay mismatch",),
        mutate_relation_missing_decision,
        "relations",
    ),
    Case(
        "NEG-014",
        "relation review uses a non-deterministic relation ID",
        ("relation review has non-deterministic relation_id",),
        mutate_relation_nondeterministic_id,
        "relations",
    ),
    Case(
        "NEG-015",
        "confirm decision emits a proposed relation",
        ("outcome differs from output relation status",),
        mutate_relation_status_mismatch,
        "relations",
    ),
    Case(
        "NEG-016",
        "accepted relation input emits no output relation",
        ("accepts input without a relation",),
        mutate_relation_accepted_without_output,
        "relations",
    ),
)


def observed_fragment(errors: list[str], expected: str) -> bool:
    return any(expected in error for error in errors)


def main() -> int:
    details: list[dict[str, Any]] = []
    baseline_detail: dict[str, Any]
    passed = 0
    failed = 0
    with tempfile.TemporaryDirectory(prefix="p3-regression-") as temporary:
        temporary_root = Path(temporary)
        baseline_root = create_sandbox(temporary_root, "baseline")
        baseline_workstreams = run_validator(baseline_root, "workstreams")
        baseline_relations = run_validator(baseline_root, "relations")
        baseline_ok = (
            baseline_workstreams["returncode"] == 0
            and baseline_workstreams["status"] == "valid"
            and baseline_workstreams["stage"] == "workstreams"
            and not baseline_workstreams["errors"]
            and baseline_relations["returncode"] == 0
            and baseline_relations["status"] == "valid"
            and baseline_relations["stage"] == "relations"
            and not baseline_relations["errors"]
        )
        baseline_detail = {
            "status": "passed" if baseline_ok else "failed",
            "workstreams": baseline_workstreams,
            "relations": baseline_relations,
        }
        if baseline_ok:
            for case in CASES:
                case_root = create_sandbox(
                    temporary_root, case.case_id.lower(), baseline_root
                )
                mutation_error: str | None = None
                try:
                    case.mutate(case_root)
                    result = run_validator(case_root, case.stage)
                except (KeyError, ValueError, OSError, TypeError) as exc:
                    mutation_error = f"{type(exc).__name__}: {exc}"
                    result = {
                        "returncode": None,
                        "status": None,
                        "stage": None,
                        "errors": [],
                        "stderr": "",
                        "parse_error": None,
                    }
                matched = {
                    expected: observed_fragment(result["errors"], expected)
                    for expected in case.expected_errors
                }
                case_ok = (
                    mutation_error is None
                    and result["returncode"] not in (None, 0)
                    and result["status"] == "invalid"
                    and all(matched.values())
                )
                if case_ok:
                    passed += 1
                else:
                    failed += 1
                details.append(
                    {
                        "case_id": case.case_id,
                        "name": case.name,
                        "status": "passed" if case_ok else "failed",
                        "expected_errors": list(case.expected_errors),
                        "matched_expected_errors": matched,
                        "observed_errors": result["errors"],
                        "validator_returncode": result["returncode"],
                        "validator_status": result["status"],
                        "validator_stderr": result["stderr"],
                        "validator_parse_error": result["parse_error"],
                        "mutation_error": mutation_error,
                    }
                )
        else:
            failed = len(CASES)
            for case in CASES:
                details.append(
                    {
                        "case_id": case.case_id,
                        "name": case.name,
                        "status": "failed",
                        "expected_errors": list(case.expected_errors),
                        "matched_expected_errors": {
                            expected: False for expected in case.expected_errors
                        },
                        "observed_errors": [],
                        "validator_returncode": None,
                        "validator_status": None,
                        "validator_stderr": "",
                        "validator_parse_error": None,
                        "mutation_error": "baseline workstreams validation failed",
                    }
                )
    success = baseline_detail["status"] == "passed" and passed == len(CASES) and failed == 0
    report = {
        "suite": "p3-negative-regression",
        "status": "passed" if success else "failed",
        "baseline": baseline_detail,
        "total": len(CASES),
        "passed": passed,
        "failed": failed,
        "details": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
