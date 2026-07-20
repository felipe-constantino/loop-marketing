#!/usr/bin/env python3
"""Validate P1 workstreams and final audit deliverables."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


CONTROL_ROOT = Path(__file__).resolve().parents[1]
P1_ROOT = CONTROL_ROOT / "artifacts" / "P1"
WORKSTREAM_ROOT = P1_ROOT / "workstreams"
INVENTORY_PATH = P1_ROOT / "inventory.json"
PROJECT_PATH = CONTROL_ROOT / "PROJECT.json"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def require_fields(
    value: dict[str, Any], fields: set[str], label: str, errors: list[str]
) -> None:
    missing = sorted(fields - value.keys())
    if missing:
        errors.append(f"{label} misses fields: {missing}")


def validate_finding_evidence(
    findings: Any, label: str, source_repo: Path, errors: list[str]
) -> None:
    if not isinstance(findings, list):
        errors.append(f"{label} findings must be a list")
        return
    ids: set[str] = set()
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            errors.append(f"{label} finding {index} is not an object")
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            errors.append(f"{label} finding {index} has no id")
        elif finding_id in ids:
            errors.append(f"{label} repeats finding id {finding_id}")
        ids.add(str(finding_id))
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{label} finding {finding_id} has no evidence")
            continue
        for item in evidence:
            if not isinstance(item, dict) or not item.get("path"):
                errors.append(f"{label} finding {finding_id} has invalid evidence")
                continue
            if "command" in item:
                if not isinstance(item["command"], str) or not item["command"].strip():
                    errors.append(f"{label} finding {finding_id} has an empty command")
                continue
            if "line_start" not in item:
                errors.append(
                    f"{label} finding {finding_id} evidence lacks line_start or command"
                )
                continue
            candidate = source_repo / str(item["path"])
            if not candidate.is_file():
                errors.append(
                    f"{label} finding {finding_id} references missing path {item['path']}"
                )
                continue
            line_start = item.get("line_start")
            line_end = item.get("line_end", line_start)
            line_count = len(candidate.read_bytes().splitlines())
            if (
                not isinstance(line_start, int)
                or not isinstance(line_end, int)
                or line_start < 1
                or line_end < line_start
                or line_end > line_count
            ):
                errors.append(
                    f"{label} finding {finding_id} has invalid line range for {item['path']}"
                )


def validate_workstreams(errors: list[str]) -> None:
    project = load_object(PROJECT_PATH)
    source_repo = Path(project["source"]["repo"])
    inventory = load_object(INVENTORY_PATH)
    if inventory.get("tracked_file_count") != 117:
        errors.append("inventory must classify 117 tracked files")
    if inventory.get("canonical_prompt_count") != 100:
        errors.append("inventory must contain 100 canonical prompts")
    coverage = inventory.get("coverage", {})
    if not all(coverage.get(key) for key in (
        "all_tracked_files_classified",
        "canonical_hashes_match",
        "source_worktree_clean",
    )):
        errors.append("inventory coverage is incomplete")

    architecture = load_object(WORKSTREAM_ROOT / "architecture.json")
    require_fields(
        architecture,
        {
            "workstream",
            "status",
            "files_reviewed",
            "file_classification",
            "findings",
            "dependency_graph",
            "role_matrix_observed",
            "version_drift",
            "duplications",
            "unresolved",
        },
        "architecture",
        errors,
    )
    validate_finding_evidence(
        architecture.get("findings"), "architecture", source_repo, errors
    )

    library = load_object(WORKSTREAM_ROOT / "library.json")
    require_fields(
        library,
        {
            "workstream",
            "status",
            "canonical_prompt_count",
            "aggregate_hash_observed",
            "indexes_reviewed",
            "prompts",
            "findings",
            "coverage",
            "unresolved",
        },
        "library",
        errors,
    )
    prompts = library.get("prompts", [])
    if not isinstance(prompts, list) or len(prompts) != 100:
        errors.append("library workstream must contain exactly 100 prompts")
    else:
        required_prompt_fields = {
            "path",
            "sha256",
            "pillar",
            "inferred_function",
            "maturity_marker",
            "input_signals",
            "output_family",
            "translation_risk",
            "duplicate_candidates",
        }
        for index, prompt in enumerate(prompts, start=1):
            if not isinstance(prompt, dict):
                errors.append(f"library prompt {index} is not an object")
                continue
            missing = sorted(required_prompt_fields - prompt.keys())
            if missing:
                errors.append(f"library prompt {index} misses fields: {missing}")
        observed = {item.get("path"): item.get("sha256") for item in prompts}
        canonical = {
            item["path"]: item["sha256"]
            for item in inventory["files"]
            if item["category"] == "canonical_tactical_prompt"
        }
        if observed != canonical:
            errors.append("library workstream paths or hashes differ from inventory")
        pillar_counts: dict[str, int] = {}
        for item in prompts:
            pillar = str(item.get("pillar"))
            pillar_counts[pillar] = pillar_counts.get(pillar, 0) + 1
        if pillar_counts != {"Ampliar": 25, "Orientar": 25, "Refinar": 25, "Verbalizar": 25}:
            errors.append(f"library pillar distribution is invalid: {pillar_counts}")
    validate_finding_evidence(library.get("findings"), "library", source_repo, errors)

    security = load_object(WORKSTREAM_ROOT / "security-runtime.json")
    require_fields(
        security,
        {
            "workstream",
            "status",
            "files_reviewed",
            "capabilities_observed",
            "missing_runtime_components",
            "findings",
            "security_threats",
            "state_management_risks",
            "packaging_gaps",
            "testability_gaps",
            "safe_migration_constraints",
            "unresolved",
        },
        "security-runtime",
        errors,
    )
    validate_finding_evidence(
        security.get("findings"), "security-runtime", source_repo, errors
    )


def validate_finals(errors: list[str]) -> None:
    audit = load_object(P1_ROOT / "audit.json")
    require_fields(
        audit,
        {
            "schema_version",
            "phase",
            "status",
            "baseline",
            "file_classification",
            "workstreams",
            "findings_summary",
            "exit_criteria_evidence",
        },
        "audit.json",
        errors,
    )
    baseline = audit.get("baseline", {})
    if baseline.get("tracked_file_count") != 117:
        errors.append("audit baseline must prove 117 files")
    if baseline.get("canonical_prompt_count") != 100:
        errors.append("audit baseline must prove 100 prompts")
    project = load_object(PROJECT_PATH)
    if baseline.get("commit") != project["source"]["baseline_commit"]:
        errors.append("audit baseline commit differs from project baseline")
    if (
        baseline.get("canonical_library_aggregate_sha256")
        != project["source"]["baseline_library_aggregate_sha256"]
    ):
        errors.append("audit canonical hash differs from project baseline")
    exit_evidence = audit.get("exit_criteria_evidence", {})
    if not isinstance(exit_evidence, dict) or not exit_evidence:
        errors.append("audit has no exit criteria evidence")
    elif any(
        not isinstance(item, dict) or item.get("status") != "proven"
        for item in exit_evidence.values()
    ):
        errors.append("not all P1 exit criteria are proven")

    risk_register = load_object(P1_ROOT / "risk-register.json")
    require_fields(
        risk_register,
        {"schema_version", "phase", "status", "severity_scale", "risks", "summary"},
        "risk-register.json",
        errors,
    )
    risks = risk_register.get("risks")
    if not isinstance(risks, list) or not risks:
        errors.append("risk register must contain prioritized risks")
    else:
        ids: set[str] = set()
        for risk in risks:
            required = {
                "id",
                "severity",
                "category",
                "title",
                "evidence",
                "impact",
                "treatment",
                "target_phase",
                "status",
            }
            if not isinstance(risk, dict) or not required.issubset(risk):
                errors.append("risk register contains an incomplete risk")
                continue
            if risk["id"] in ids:
                errors.append(f"risk register repeats id {risk['id']}")
            ids.add(risk["id"])
        validate_finding_evidence(risks, "risk-register", Path(audit["baseline"]["repo"]), errors)

        summary = risk_register.get("summary", {})
        observed_by_severity: dict[str, int] = {}
        observed_by_phase: dict[str, int] = {}
        for risk in risks:
            if not isinstance(risk, dict):
                continue
            severity = str(risk.get("severity"))
            phase = str(risk.get("target_phase"))
            observed_by_severity[severity] = observed_by_severity.get(severity, 0) + 1
            observed_by_phase[phase] = observed_by_phase.get(phase, 0) + 1
        if summary.get("total") != len(risks):
            errors.append("risk summary total differs from risks")
        if summary.get("by_severity") != observed_by_severity:
            errors.append("risk summary by_severity differs from risks")
        if summary.get("by_target_phase") != observed_by_phase:
            errors.append("risk summary by_target_phase differs from risks")

    architecture_map = (P1_ROOT / "architecture-map.md").read_text(encoding="utf-8")
    for heading in (
        "# Mapa da arquitetura atual",
        "## Baseline",
        "## Fluxo observado",
        "## Fronteiras observadas",
        "## Lacunas para a v2",
    ):
        if heading not in architecture_map:
            errors.append(f"architecture-map.md misses heading: {heading}")


def validate_source(errors: list[str]) -> None:
    project = load_object(PROJECT_PATH)
    repo = Path(project["source"]["repo"])
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != project["source"]["baseline_commit"]:
        errors.append("source HEAD moved during read-only P1")
    if status:
        errors.append("source worktree changed during read-only P1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("workstreams", "final"))
    args = parser.parse_args()
    errors: list[str] = []
    try:
        validate_source(errors)
        validate_workstreams(errors)
        if args.stage == "final":
            validate_finals(errors)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        errors.append(str(exc))
    print(
        json.dumps(
            {"status": "valid" if not errors else "invalid", "stage": args.stage, "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
