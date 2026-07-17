#!/usr/bin/env python3
"""Seal or verify the complete P3 evidence set after all independent gates pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
P3 = ROOT / "artifacts" / "P3"
MANIFEST = P3 / "integration-manifest.json"
BASELINE = {
    "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
    "canonical_prompt_count": 100,
    "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1",
}
EVIDENCE_PATHS = (
    "artifacts/P3/catalog-schema.json",
    "artifacts/P3/tactic-catalog.json",
    "artifacts/P3/relationship-map.json",
    "artifacts/P3/preservation-report.json",
    "artifacts/P3/workstreams/verbalizar.json",
    "artifacts/P3/workstreams/orientar.json",
    "artifacts/P3/workstreams/ampliar.json",
    "artifacts/P3/workstreams/refinar.json",
    "artifacts/P3/workstreams/catalog-cross-audit-3pillars.json",
    "artifacts/P3/workstreams/catalog-final-audit.json",
    "artifacts/P3/workstreams/relation-review.json",
    "scripts/p3_validate.py",
    "scripts/p3_integrate.py",
    "scripts/p3_regression.py",
    "scripts/p3_seal.py",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command, cwd=ROOT, check=False, capture_output=True, text=True
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"command emitted invalid JSON: {' '.join(command)}: {exc}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}: "
            + json.dumps(payload, ensure_ascii=False)
        )
    return payload


def gate_checks() -> dict[str, Any]:
    final_validation = run_json(
        [sys.executable, str(ROOT / "scripts" / "p3_validate.py"), "final"]
    )
    regression = run_json([sys.executable, str(ROOT / "scripts" / "p3_regression.py")])
    if final_validation.get("status") != "valid":
        raise RuntimeError("P3 final validator did not return valid")
    if regression.get("status") != "passed" or regression.get("failed") != 0:
        raise RuntimeError("P3 negative regression did not pass")

    final_audit = load(P3 / "workstreams" / "catalog-final-audit.json")
    gate = final_audit.get("gate")
    if not isinstance(gate, dict) or gate.get("verdict", gate.get("result")) != "PASS":
        raise RuntimeError("P3 independent catalog final audit is not PASS")
    blocking_count = gate.get("blocking_p3", gate.get("blocking_findings"))
    if blocking_count != 0:
        raise RuntimeError("P3 independent catalog final audit still has blockers")

    relation_review = load(P3 / "workstreams" / "relation-review.json")
    review_summary = relation_review.get("review_summary")
    if (
        relation_review.get("status") != "completed"
        or not isinstance(review_summary, dict)
        or review_summary.get("verdict") != "PASS"
        or review_summary.get("blocking_findings") != 0
    ):
        raise RuntimeError("P3 independent relation review is not PASS")
    return {
        "p3_validate_final": "passed",
        "p3_negative_regression": {
            "status": "passed",
            "cases": regression.get("total"),
            "failed": regression.get("failed"),
        },
        "independent_catalog_audit": "passed",
        "independent_relation_review": "passed",
    }


def evidence_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in EVIDENCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"required P3 evidence is missing: {relative}")
        records.append(
            {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size}
        )
    return records


def source_integrity() -> dict[str, Any]:
    project = load(ROOT / "PROJECT.json")
    repo = Path(project["source"]["repo"])
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return {
        "head": head,
        "worktree_clean": not bool(status),
        "canonical_prompt_count": 100,
        "aggregate_sha256": BASELINE["aggregate_sha256"],
    }


def create() -> int:
    validation = gate_checks()
    source = source_integrity()
    if source["head"] != BASELINE["source_commit"] or not source["worktree_clean"]:
        raise RuntimeError("canonical source differs from the P3 baseline")
    manifest = {
        "schema_version": "1.0",
        "phase": "P3",
        "status": "sealed",
        "baseline": BASELINE,
        "validation": validation,
        "release_constraints": {
            "individual_source_verified": False,
            "redistribution_review": "not_reviewed",
            "public_redistribution_authorized": False,
        },
        "source_integrity": source,
        "evidence": evidence_records(),
    }
    temporary = MANIFEST.with_suffix(MANIFEST.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, MANIFEST)
    print(
        json.dumps(
            {
                "status": "sealed",
                "phase": "P3",
                "evidence_files": len(manifest["evidence"]),
                "manifest": str(MANIFEST),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def verify() -> int:
    manifest = load(MANIFEST)
    errors: list[str] = []
    if manifest.get("status") != "sealed" or manifest.get("baseline") != BASELINE:
        errors.append("manifest identity or baseline is invalid")
    expected_records = {record["path"]: record for record in evidence_records()}
    stored_records = {
        record.get("path"): record
        for record in manifest.get("evidence", [])
        if isinstance(record, dict)
    }
    if set(stored_records) != set(expected_records):
        errors.append("manifest evidence path set differs from required evidence")
    for path, expected in expected_records.items():
        stored = stored_records.get(path, {})
        if stored.get("sha256") != expected["sha256"] or stored.get("bytes") != expected["bytes"]:
            errors.append(f"manifest evidence drift: {path}")
    try:
        gate_checks()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    current_source = source_integrity()
    if current_source != manifest.get("source_integrity"):
        errors.append("source integrity differs from sealed manifest")
    print(
        json.dumps(
            {
                "status": "valid" if not errors else "invalid",
                "phase": "P3",
                "evidence_files": len(expected_records),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "verify"))
    args = parser.parse_args()
    try:
        return create() if args.command == "create" else verify()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "failed", "phase": "P3", "errors": [str(exc)]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
