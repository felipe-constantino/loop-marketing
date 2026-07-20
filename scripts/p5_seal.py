#!/usr/bin/env python3
"""Seal and verify the complete P5 runtime evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
P5 = ROOT / "artifacts" / "P5"
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
MANIFEST = P5 / "integration-manifest.json"
VALIDATION_REPORT = P5 / "validation-report.json"
REGRESSION_REPORT = P5 / "regression-report.json"
INDEPENDENT_AUDIT = P5 / "final-independent-audit.json"


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(relative: str) -> Dict[str, str]:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError("required seal file missing: %s" % relative)
    return {"path": relative, "sha256": sha256_file(path)}


def entries(paths: Iterable[str]) -> List[Dict[str, str]]:
    return [entry(path) for path in sorted(paths)]


def run_json(script: str) -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("%s failed\n%s\n%s" % (script, completed.stdout, completed.stderr))
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("%s did not return JSON" % script) from exc


def build_manifest(timestamp: str, validation: Dict[str, Any], regression: Dict[str, Any]) -> Dict[str, Any]:
    source_contract_paths = [
        "artifacts/P2/role-matrix.json",
        "artifacts/P2/routing-contract.json",
        "artifacts/P2/compatibility-policy.md",
        "artifacts/P3/tactic-catalog.json",
        "artifacts/P3/relationship-map.json",
        "artifacts/P4/state-schema.json",
        "artifacts/P4/event-schema.json",
        "artifacts/P4/handoff-schema.json",
        "artifacts/P4/state-event-contract.md",
    ]
    runtime_paths = [
        str(path.relative_to(ROOT))
        for base in (
            CANDIDATE / "src" / "loop_marketing_runtime",
            CANDIDATE / "data",
            CANDIDATE / "contracts",
            CANDIDATE / "adapters",
        )
        for path in base.glob("**/*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    runtime_paths.append(str((CANDIDATE / "pyproject.toml").relative_to(ROOT)))
    runtime_paths.append(str((CANDIDATE / "setup.py").relative_to(ROOT)))
    test_paths = [
        str(path.relative_to(ROOT))
        for path in (CANDIDATE / "tests").glob("test_*.py")
    ]
    gate_reports = [
        entry(str(VALIDATION_REPORT.relative_to(ROOT))),
        entry(str(REGRESSION_REPORT.relative_to(ROOT))),
    ]
    audit_status = "NOT_RUN"
    if INDEPENDENT_AUDIT.is_file():
        audit = load(INDEPENDENT_AUDIT)
        audit_status = audit.get("verdict", audit.get("status", "UNKNOWN"))
        gate_reports.append(entry(str(INDEPENDENT_AUDIT.relative_to(ROOT))))
    return {
        "artifact_id": "loop-marketing-p5-integration-manifest",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "sealed",
        "sealed_at": timestamp,
        "source_contracts": entries(source_contract_paths),
        "official_artifacts": entries([
            "artifacts/P5/runtime-contract.json",
            "artifacts/P5/runtime-fixtures.json",
        ]),
        "runtime_files": entries(runtime_paths),
        "tests": entries(test_paths),
        "scripts": entries([
            "scripts/p5_validate.py",
            "scripts/p5_regression.py",
            "scripts/p5_seal.py",
        ]),
        "gate_reports": gate_reports,
        "gate_summary": {
            "validator": validation["status"],
            "tests": validation["counts"]["tests"],
            "negative_regression": regression["status"],
            "negative_regression_scenarios": regression["scenario_count"],
            "independent_audit": audit_status,
            "source_preserved": validation["source"]["preserved"],
        },
        "contract_counts": {
            "canonical_prompts": validation["counts"]["canonical_tactics"],
            "confirmed_relations": validation["counts"]["confirmed_relations"],
            "command_invocations": validation["counts"]["command_invocations"],
            "handoff_top_level_fields": validation["counts"]["handoff_top_level_fields"],
            "runtime_tests": validation["counts"]["tests"],
        },
        "invariants": [
            "the original 100-prompt library remains immutable and bodies load only after selection",
            "zero tactics is valid, one is default and two require a proven combination",
            "only provenance-complete facts can set bottleneck scoring signals",
            "only Loop Planning accepts the primary bottleneck, route order and transaction integration",
            "handoffs contain exactly 22 fields and bind to the selected route node, tactic metadata and bottleneck",
            "one transaction with one or more events advances exactly one state revision",
            "the ledger is authoritative for mutable state and immutable identity survives cache rebuild",
            "exact replay is a noop while identifier reuse with different canonical content is rejected",
            "generic, Claude and Codex profiles share one command and state contract with no external-write surface"
        ],
        "baseline": {
            "source_repository": "/Users/enorm/Documents/Claude/loop-marketing",
            "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
            "canonical_prompt_count": 100,
            "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"
        }
    }


def verify(run_live: bool = True) -> Dict[str, Any]:
    errors = []
    if not MANIFEST.is_file():
        return {"status": "FAIL", "errors": ["manifest is missing"], "gate_report_count": 0}
    manifest = load(MANIFEST)
    if manifest.get("status") != "sealed":
        errors.append("manifest is not sealed")
    for section in ("source_contracts", "official_artifacts", "runtime_files", "tests", "scripts", "gate_reports"):
        for item in manifest.get(section, []):
            path = ROOT / item["path"]
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                errors.append("manifest hash drift: %s" % item["path"])
    for report in (VALIDATION_REPORT, REGRESSION_REPORT):
        if not report.is_file() or load(report).get("result", {}).get("status") != "PASS":
            errors.append("gate report does not pass: %s" % report.name)
    if INDEPENDENT_AUDIT.is_file():
        audit = load(INDEPENDENT_AUDIT)
        if audit.get("verdict", audit.get("status")) != "PASS" or audit.get("blockers"):
            errors.append("independent audit does not pass")
    else:
        errors.append("independent audit is missing")
    if run_live and not errors:
        try:
            if run_json("p5_validate.py").get("status") != "PASS":
                errors.append("live validator failed")
            if run_json("p5_regression.py").get("status") != "PASS":
                errors.append("live negative regression failed")
        except RuntimeError as exc:
            errors.append(str(exc))
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "gate_report_count": len(manifest.get("gate_reports", [])),
    }


def seal() -> Dict[str, Any]:
    if not INDEPENDENT_AUDIT.is_file():
        raise RuntimeError("independent audit must exist before sealing P5")
    audit = load(INDEPENDENT_AUDIT)
    if audit.get("verdict", audit.get("status")) != "PASS" or audit.get("blockers"):
        raise RuntimeError("independent audit must pass without blockers before sealing P5")
    validation = run_json("p5_validate.py")
    regression = run_json("p5_regression.py")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dump(VALIDATION_REPORT, {
        "artifact_id": "loop-marketing-p5-validation-report",
        "generated_at": timestamp,
        "command": "python3 scripts/p5_validate.py",
        "result": validation,
    })
    dump(REGRESSION_REPORT, {
        "artifact_id": "loop-marketing-p5-regression-report",
        "generated_at": timestamp,
        "command": "python3 scripts/p5_regression.py",
        "result": regression,
    })
    dump(MANIFEST, build_manifest(timestamp, validation, regression))
    return {"status": "SEALED", "sealed_at": timestamp, "verify": verify(run_live=True)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seal", "verify"))
    args = parser.parse_args()
    try:
        result = seal() if args.action == "seal" else verify(run_live=True)
    except RuntimeError as exc:
        result = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("PASS", "SEALED") and result.get("verify", {"status": "PASS"})["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
