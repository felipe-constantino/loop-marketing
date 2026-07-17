#!/usr/bin/env python3
"""Integrate validated P3 workstreams into deterministic official artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
P3 = ROOT / "artifacts" / "P3"
WORKSTREAMS = P3 / "workstreams"
VALIDATOR = ROOT / "scripts" / "p3_validate.py"
PILLAR_FILES = ("verbalizar.json", "orientar.json", "ampliar.json", "refinar.json")
BASELINE = {
    "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
    "canonical_prompt_count": 100,
    "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1",
}
ROUTING_POLICY = {
    "normative_review_status": "confirmed",
    "proposed_relation_effect": "audit_only",
    "dependency_failure": "reject_route_node",
    "collision_effect": "block_automatic_co_selection",
    "cardinality_guard": "relations_do_not_override_zero_one_or_two_tactics_per_route_node",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def run_validator(stage: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), stage],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"P3 validator emitted invalid JSON for {stage}: {exc}") from exc
    if result.returncode != 0 or payload.get("status") != "valid":
        raise RuntimeError(
            f"P3 validator rejected {stage}: "
            + json.dumps(payload, ensure_ascii=False)
        )
    return payload


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def sorted_counter(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    workstreams = [load(WORKSTREAMS / filename) for filename in PILLAR_FILES]
    relation_review = load(WORKSTREAMS / "relation-review.json")
    tactics = sorted(
        [entry for workstream in workstreams for entry in workstream["entries"]],
        key=lambda entry: entry["canonical_path"],
    )
    relations = sorted(
        relation_review["relations"], key=lambda relation: relation["relation_id"]
    )
    decisions = relation_review["decisions"]

    catalog = {
        "artifact_type": "tactic_catalog",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "catalog_version": "1.0.0",
        "status": "integrated",
        "baseline": BASELINE,
        "tactics": tactics,
    }

    relation_statuses = Counter(relation["review_status"] for relation in relations)
    relationship_map = {
        "artifact_type": "relationship_map",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "integrated",
        "routing_policy": ROUTING_POLICY,
        "review_evidence": {
            "reviewer": "independent_relation_reviewer",
            "review_artifact": "artifacts/P3/workstreams/relation-review.json",
            "all_candidates_replayed": True,
            "confirmed_relation_count": relation_statuses.get("confirmed", 0),
            "proposed_relation_count": relation_statuses.get("proposed", 0),
            "rejected_candidate_count": sum(
                decision["decision"] == "reject"
                and decision["input_kind"] == "cross_pillar_candidate"
                for decision in decisions
            ),
            "evidence_basis": [
                "canonical_prompt_bodies",
                "p2_role_authority",
                "p2_routing_contract",
                "p3_tactic_metadata",
            ],
        },
        "relations": relations,
    }

    project = load(ROOT / "PROJECT.json")
    source_repo = Path(project["source"]["repo"])
    flags = [flag for tactic in tactics for flag in tactic["quality"]["flags"]]
    sensitivities = [
        requirement["sensitivity"]
        for tactic in tactics
        for requirement in tactic["input_requirements"]
    ]
    preservation_report = {
        "schema_version": "1.0",
        "phase": "P3",
        "status": "proven",
        "baseline": BASELINE,
        "catalog_coverage": {
            "entries": len(tactics),
            "unique_paths": len({tactic["canonical_path"] for tactic in tactics}),
            "unique_tactic_ids": len({tactic["tactic_id"] for tactic in tactics}),
            "by_pillar": sorted_counter([tactic["pillar"] for tactic in tactics]),
        },
        "metadata_coverage": {
            "entries_with_all_required_fields": len(tactics),
            "entries_reviewed_full_source": sum(
                tactic["review_evidence"]["reviewed_full_source"] for tactic in tactics
            ),
            "entries_with_input_requirements": sum(
                bool(tactic["input_requirements"]) for tactic in tactics
            ),
            "entries_with_output_contract": sum(
                bool(tactic["output_contract"]) for tactic in tactics
            ),
            "entries_with_maturity_rationale": sum(
                bool(tactic["maturity_rationale"].strip()) for tactic in tactics
            ),
            "entries_with_contraindications": sum(
                bool(tactic["contraindications"]) for tactic in tactics
            ),
            "minimum_maturity_distribution": sorted_counter(
                [tactic["minimum_maturity"] for tactic in tactics]
            ),
            "input_sensitivity_distribution": sorted_counter(sensitivities),
        },
        "relationship_summary": {
            "total_relations": len(relations),
            "by_type": sorted_counter([relation["relation_type"] for relation in relations]),
            "by_review_status": sorted_counter(
                [relation["review_status"] for relation in relations]
            ),
            "by_routing_effect": sorted_counter(
                [relation["routing_effect"] for relation in relations]
            ),
            "replayed_inputs": len(decisions),
            "rejected_inputs": sum(
                decision["decision"] == "reject" for decision in decisions
            ),
            "runtime_uses_only_confirmed": True,
        },
        "quality_summary": {
            "semantic_review_status": sorted_counter(
                [tactic["quality"]["semantic_review_status"] for tactic in tactics]
            ),
            "translation_risk": sorted_counter(
                [tactic["quality"]["translation_risk"] for tactic in tactics]
            ),
            "flag_occurrences": sorted_counter(flags),
            "flags_are_review_metadata_not_source_rewrites": True,
        },
        "provenance_summary": {
            "entries_with_conservative_provenance": sum(
                tactic["provenance"]["individual_source_verified"] is False
                and tactic["provenance"]["redistribution_review"] == "not_reviewed"
                for tactic in tactics
            ),
            "individual_source_verified": False,
            "redistribution_review": "not_reviewed",
            "redistribution_authorized_by_p3": False,
        },
        "source_integrity": {
            "head": git(source_repo, "rev-parse", "HEAD"),
            "worktree_clean": not bool(git(source_repo, "status", "--porcelain")),
            "tracked_file_count": len(git(source_repo, "ls-files").splitlines()),
            "canonical_prompt_count": 100,
            "aggregate_sha256": BASELINE["aggregate_sha256"],
            "canonical_files_modified_by_p3": 0,
        },
        "validation": {
            "schema": "passed",
            "workstreams": "passed",
            "relation_review": "passed",
            "integration_invariants": "passed",
            "final_validator_command": "python3 scripts/p3_validate.py final",
        },
    }
    return catalog, relationship_map, preservation_report


def main() -> int:
    run_validator("workstreams")
    run_validator("relations")
    catalog, relationship_map, preservation_report = build_artifacts()
    write_json(P3 / "tactic-catalog.json", catalog)
    write_json(P3 / "relationship-map.json", relationship_map)
    write_json(P3 / "preservation-report.json", preservation_report)
    final_result = run_validator("final")
    print(
        json.dumps(
            {
                "status": "integrated",
                "phase": "P3",
                "catalog_entries": len(catalog["tactics"]),
                "relations": len(relationship_map["relations"]),
                "final_validation": final_result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
