#!/usr/bin/env python3
"""Seal and verify the P7 evaluation evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P7 = ROOT / "artifacts" / "P7"
MANIFEST = P7 / "integration-manifest.json"
AUDIT = P7 / "red-team-report.json"
REPORT = P7 / "evaluation-report.json"
VALIDATION = P7 / "validation-report.json"
GROUPS = {
    "official_artifacts": ["artifacts/P7/evaluation-contract.json", "artifacts/P7/evaluation-cases.json", "artifacts/P7/workstreams/evaluation-design.json", "artifacts/P7/workstreams/observability-design.json"],
    "runtime_files": ["candidate/loop-marketing-v2/src/loop_marketing_runtime/evaluation.py", "candidate/loop-marketing-v2/src/loop_marketing_runtime/observability.py"],
    "tests": ["candidate/loop-marketing-v2/tests/test_evaluation.py", "candidate/loop-marketing-v2/tests/test_observability.py"],
    "scripts": ["scripts/p7_evaluate.py", "scripts/p7_validate.py", "scripts/p7_seal.py"],
    "gate_reports": ["artifacts/P7/evaluation-report.json", "artifacts/P7/validation-report.json", "artifacts/P7/red-team-report.json"],
}
INVARIANTS = [
    "the rubric is closed and requires five of five dimensions",
    "all four pillars and all maturity states are covered",
    "needs_evidence is evaluated as a first-class route state",
    "sensitive input and external mutation are denied in executed cases",
    "observability is allowlist-only, in-memory and disabled by default",
    "reports contain no raw payload, prompt body, PII, credential or path",
]


def load(path): return json.loads(path.read_text(encoding="utf-8"))
def dump(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def entry(relative):
    path = ROOT / relative
    if not path.is_file(): raise RuntimeError("missing: %s" % relative)
    return {"path": relative, "sha256": sha(path)}
def run_json(script):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    if result.returncode: raise RuntimeError("%s failed" % script)
    return json.loads(result.stdout)


def build_manifest(timestamp, evaluation, validation, audit):
    return {
        "artifact_id": "loop-marketing-p7-integration-manifest",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "sealed",
        "sealed_at": timestamp,
        **{key: [entry(path) for path in paths] for key, paths in GROUPS.items()},
        "gate_summary": {
            "evaluation": evaluation["status"],
            "release_gate": evaluation["release_gate_status"],
            "runtime_attestation": evaluation["runtime_attestation"]["runtime_attested"],
            "audit_traces_attested": evaluation["runtime_attestation"]["audit_traces_attested"],
            "capability_scan": evaluation["runtime_attestation"]["capability_scan"]["status"],
            "cases": evaluation["summary"]["case_count"],
            "passed": evaluation["summary"]["passed"],
            "validator": validation["status"],
            "red_team": audit["verdict"],
            "source_preserved": validation["source"]["preserved"],
        },
        "invariants": INVARIANTS,
    }


def verify(live=True):
    errors = []
    if not MANIFEST.is_file(): return {"status": "FAIL", "errors": ["manifest is missing"]}
    try:
        manifest = load(MANIFEST)
        audit = load(AUDIT)
        evaluation = load(REPORT)
        validation = load(VALIDATION)["result"]
        expected = build_manifest(manifest.get("sealed_at"), evaluation, validation, audit)
        if manifest != expected:
            errors.append("manifest structure, topology or hashes drifted")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        audit = {}
        evaluation = {}
        validation = {}
        errors.append("manifest or gate report is malformed")
    if audit.get("verdict") != "PASS" or audit.get("blockers"): errors.append("red team did not pass")
    if evaluation.get("status") != "passed" or evaluation.get("release_gate_status") != "passed": errors.append("evaluation report failed")
    if validation.get("status") != "PASS": errors.append("validation report failed")
    if live and not errors:
        if run_json("p7_validate.py")["status"] != "PASS": errors.append("live validation failed")
        live_evaluation = run_json("p7_evaluate.py")
        if live_evaluation["status"] != "passed" or live_evaluation.get("release_gate_status") != "passed": errors.append("live evaluation failed")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def seal():
    audit = load(AUDIT) if AUDIT.is_file() else {}
    if audit.get("verdict") != "PASS" or audit.get("blockers"): raise RuntimeError("red team must pass without blockers")
    evaluation = run_json("p7_evaluate.py")
    validation = run_json("p7_validate.py")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dump(REPORT, evaluation)
    dump(VALIDATION, {"artifact_id": "loop-marketing-p7-validation-report", "generated_at": timestamp, "command": "python3 scripts/p7_validate.py", "result": validation})
    dump(MANIFEST, build_manifest(timestamp, evaluation, validation, audit))
    return {"status": "SEALED", "sealed_at": timestamp, "verify": verify(live=True)}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("seal", "verify")); args = parser.parse_args()
    try: result = seal() if args.action == "seal" else verify(live=True)
    except (RuntimeError, ValueError, KeyError) as exc: result = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result["status"] in ("PASS", "SEALED") and result.get("verify", {"status": "PASS"})["status"] == "PASS"
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__": main()
