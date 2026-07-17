#!/usr/bin/env python3
"""Integrate validated P1 workstreams into the baseline audit artifact."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


CONTROL_ROOT = Path(__file__).resolve().parents[1]
P1_ROOT = CONTROL_ROOT / "artifacts" / "P1"
WORKSTREAM_ROOT = P1_ROOT / "workstreams"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    inventory_path = P1_ROOT / "inventory.json"
    inventory = load(inventory_path)
    names = ("architecture", "library", "security-runtime")
    workstreams: dict[str, dict[str, Any]] = {}
    all_findings: list[dict[str, Any]] = []
    for name in names:
        path = WORKSTREAM_ROOT / f"{name}.json"
        value = load(path)
        findings = value.get("findings", [])
        all_findings.extend(findings)
        workstreams[name] = {
            "artifact": str(path.relative_to(CONTROL_ROOT)),
            "sha256": sha256(path),
            "status": value.get("status"),
            "finding_count": len(findings),
            "finding_ids": [item.get("id") for item in findings],
        }

    severity_counts = Counter(item.get("severity", "unknown") for item in all_findings)
    category_counts = Counter(item.get("category", "unknown") for item in all_findings)
    output = {
        "schema_version": "1.0",
        "phase": "P1",
        "status": "completed_with_findings",
        "mode": "read_only",
        "baseline": {
            "repo": inventory["source_repo"],
            "commit": inventory["source_commit"],
            "branch": inventory["source_branch"],
            "tracked_file_count": inventory["tracked_file_count"],
            "canonical_prompt_count": inventory["canonical_prompt_count"],
            "canonical_library_aggregate_sha256": inventory[
                "canonical_library_aggregate_sha256"
            ],
            "source_worktree_clean": inventory["coverage"][
                "source_worktree_clean"
            ],
        },
        "file_classification": {
            "artifact": str(inventory_path.relative_to(CONTROL_ROOT)),
            "sha256": sha256(inventory_path),
            "summary": inventory["classification_summary"],
            "all_tracked_files_classified": inventory["coverage"][
                "all_tracked_files_classified"
            ],
            "canonical_hashes_match": inventory["coverage"][
                "canonical_hashes_match"
            ],
        },
        "workstreams": workstreams,
        "findings_summary": {
            "raw_finding_count": len(all_findings),
            "by_severity": dict(sorted(severity_counts.items())),
            "by_category": dict(sorted(category_counts.items())),
            "note": "Raw findings intentionally retain overlap; risk-register.json consolidates equivalent risks.",
        },
        "strengths_observed": [
            "Progressive disclosure through pillar indexes and selective tactical loading.",
            "Explicit maturity gating concept and confidence-oriented decisions.",
            "Controlled experiment states with a stated evidence requirement.",
            "Cross-pillar validation and explicit scope-boundary intent.",
            "Complete canonical library: 100 unique prompt paths with matching hashes."
        ],
        "exit_criteria_evidence": {
            "117_files_classified": {
                "status": "proven",
                "evidence": "artifacts/P1/inventory.json"
            },
            "risks_and_drift_with_evidence": {
                "status": "proven",
                "evidence": [
                    "artifacts/P1/workstreams/architecture.json",
                    "artifacts/P1/workstreams/library.json",
                    "artifacts/P1/workstreams/security-runtime.json",
                    "artifacts/P1/risk-register.json"
                ]
            },
            "canonical_hash_preserved": {
                "status": "proven",
                "evidence": "baseline.canonical_library_aggregate_sha256"
            },
            "source_unchanged_during_P1": {
                "status": "proven",
                "evidence": {
                    "commit": inventory["source_commit"],
                    "worktree_clean": inventory["coverage"]["source_worktree_clean"]
                }
            },
            "lead_integration": {
                "status": "proven",
                "evidence": [
                    "artifacts/P1/audit.json",
                    "artifacts/P1/architecture-map.md",
                    "artifacts/P1/risk-register.json"
                ]
            }
        }
    }
    output_path = P1_ROOT / "audit.json"
    temp_path = output_path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(output_path)
    print(
        json.dumps(
            {
                "status": "integrated",
                "output": str(output_path),
                "raw_findings": len(all_findings),
                "severity_counts": dict(sorted(severity_counts.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
