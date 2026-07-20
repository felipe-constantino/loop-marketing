#!/usr/bin/env python3
"""Seal and verify the P6 security evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P6 = ROOT / "artifacts" / "P6"
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
MANIFEST = P6 / "integration-manifest.json"
AUDIT = P6 / "final-independent-audit.json"
VALIDATION = P6 / "validation-report.json"
REGRESSION = P6 / "regression-report.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(relative):
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError("required seal file missing: %s" % relative)
    return {"path": relative, "sha256": sha(path)}


def run_json(script):
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError("%s failed: %s" % (script, completed.stdout[-1000:]))
    return json.loads(completed.stdout)


def build_manifest(timestamp, validation, regression):
    official = [
        "artifacts/P6/security-contract.json",
        "artifacts/P6/security-fixtures.json",
        "artifacts/P6/workstreams/security-policy.json",
        "artifacts/P6/workstreams/threat-model.json",
    ]
    runtime = [
        "candidate/loop-marketing-v2/pyproject.toml",
        "candidate/loop-marketing-v2/setup.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/__init__.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/security.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/secure_runtime.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/secure_cli.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/secure_adapters.py",
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/observability.py",
    ]
    tests = [
        "candidate/loop-marketing-v2/tests/test_security.py",
        "candidate/loop-marketing-v2/tests/test_secure_runtime.py",
        "candidate/loop-marketing-v2/tests/test_observability.py",
    ]
    scripts = ["scripts/p6_validate.py", "scripts/p6_regression.py", "scripts/p6_seal.py"]
    reports = [
        "artifacts/P6/validation-report.json",
        "artifacts/P6/regression-report.json",
        "artifacts/P6/final-independent-audit.json",
    ]
    return {
        "artifact_id": "loop-marketing-p6-integration-manifest",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "sealed",
        "sealed_at": timestamp,
        "scope": "technical_security_and_operational_permissions",
        "official_artifacts": [entry(path) for path in official],
        "runtime_files": [entry(path) for path in runtime],
        "tests": [entry(path) for path in tests],
        "scripts": [entry(path) for path in scripts],
        "gate_reports": [entry(path) for path in reports],
        "gate_summary": {
            "validator": validation["status"],
            "full_suite_tests": validation["counts"]["full_suite_tests"],
            "security_tests": validation["counts"]["security_tests"],
            "negative_regression": regression["status"],
            "negative_scenarios": regression["scenario_count"],
            "independent_audit": load(AUDIT).get("verdict"),
            "source_preserved": validation["source"]["preserved"],
        },
        "invariants": [
            "all untrusted control JSON is budgeted and defensively copied",
            "secrets, sensitive PII and local paths are rejected or deterministically redacted",
            "read_only operations do not repair or persist local state",
            "local_state writes remain confined to the canonical state store",
            "external mutation is unconditionally denied and absent from the release surface",
            "canonical prompt bodies are hash verified, byte bounded and labeled untrusted tactical data",
            "prompt content cannot authorize tools, credential discovery, state writes or external mutation",
            "the 100-prompt canonical source remains clean at its sealed commit"
        ],
        "baseline": {
            "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
            "canonical_prompt_count": 100,
            "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"
        }
    }


def verify(live=True):
    errors = []
    if not MANIFEST.is_file():
        return {"status": "FAIL", "errors": ["manifest is missing"]}
    try:
        manifest = load(MANIFEST)
        validation_result = load(VALIDATION)["result"]
        regression_result = load(REGRESSION)["result"]
        expected = build_manifest(manifest.get("sealed_at"), validation_result, regression_result)
        if manifest != expected:
            errors.append("manifest structure, topology or hashes drifted")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        manifest = {}
        errors.append("manifest or gate report is malformed")
    for report in (VALIDATION, REGRESSION):
        if not report.is_file() or load(report).get("result", {}).get("status") != "PASS":
            errors.append("gate report failed: %s" % report.name)
    audit = load(AUDIT) if AUDIT.is_file() else {}
    if audit.get("verdict") != "PASS" or audit.get("blockers"):
        errors.append("independent audit is missing or failed")
    if live and not errors:
        try:
            if run_json("p6_validate.py")["status"] != "PASS":
                errors.append("live validation failed")
            if run_json("p6_regression.py")["status"] != "PASS":
                errors.append("live regression failed")
        except (RuntimeError, ValueError, KeyError) as exc:
            errors.append("live gate error: %s" % type(exc).__name__)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def seal():
    audit = load(AUDIT) if AUDIT.is_file() else {}
    if audit.get("verdict") != "PASS" or audit.get("blockers"):
        raise RuntimeError("independent P6 audit must pass without blockers")
    validation = run_json("p6_validate.py")
    regression = run_json("p6_regression.py")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dump(VALIDATION, {"artifact_id": "loop-marketing-p6-validation-report", "generated_at": timestamp, "command": "python3 scripts/p6_validate.py", "result": validation})
    dump(REGRESSION, {"artifact_id": "loop-marketing-p6-regression-report", "generated_at": timestamp, "command": "python3 scripts/p6_regression.py", "result": regression})
    dump(MANIFEST, build_manifest(timestamp, validation, regression))
    return {"status": "SEALED", "sealed_at": timestamp, "verify": verify(live=True)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seal", "verify"))
    args = parser.parse_args()
    try:
        result = seal() if args.action == "seal" else verify(live=True)
    except RuntimeError as exc:
        result = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result["status"] in ("PASS", "SEALED") and result.get("verify", {"status": "PASS"})["status"] == "PASS"
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
