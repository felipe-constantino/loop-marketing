#!/usr/bin/env python3
"""Seal and verify the complete P4 evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P4 = ROOT / "artifacts" / "P4"
MANIFEST = P4 / "integration-manifest.json"
VALIDATION_REPORT = P4 / "validation-report.json"
REGRESSION_REPORT = P4 / "regression-report.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_json(script: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script} returned non-JSON output: {result.stdout}") from exc


def seal() -> dict:
    validation = run_json("p4_validate.py")
    regression = run_json("p4_regression.py")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dump(VALIDATION_REPORT, {
        "artifact_id": "loop-marketing-p4-validation-report",
        "generated_at": timestamp,
        "command": "python3 scripts/p4_validate.py",
        "result": validation,
    })
    dump(REGRESSION_REPORT, {
        "artifact_id": "loop-marketing-p4-regression-report",
        "generated_at": timestamp,
        "command": "python3 scripts/p4_regression.py",
        "result": regression,
    })
    manifest = load(MANIFEST)
    manifest["status"] = "sealed"
    manifest["sealed_at"] = timestamp
    manifest["gate_reports"] = [
        {"path": str(VALIDATION_REPORT.relative_to(ROOT)), "sha256": sha256_file(VALIDATION_REPORT)},
        {"path": str(REGRESSION_REPORT.relative_to(ROOT)), "sha256": sha256_file(REGRESSION_REPORT)},
    ]
    manifest["gate_summary"] = {
        "validator": validation["status"],
        "fixture_count": validation["counts"]["fixtures"],
        "negative_regression": regression["status"],
        "negative_regression_scenarios": regression["scenario_count"],
        "source_preserved": True,
    }
    dump(MANIFEST, manifest)
    verified = verify()
    return {"status": "SEALED", "sealed_at": timestamp, "verify": verified}


def verify() -> dict:
    manifest = load(MANIFEST)
    errors = []
    if manifest.get("status") != "sealed":
        errors.append("manifest is not sealed")
    for entry in manifest.get("gate_reports", []):
        path = ROOT / entry["path"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            errors.append(f"gate report hash drift: {entry['path']}")
    for path in (VALIDATION_REPORT, REGRESSION_REPORT):
        if not path.is_file() or load(path).get("result", {}).get("status") != "PASS":
            errors.append(f"gate report does not pass: {path.name}")
    if not errors:
        try:
            validation = run_json("p4_validate.py")
            regression = run_json("p4_regression.py")
            if validation["status"] != "PASS" or regression["status"] != "PASS":
                errors.append("live gate did not pass")
        except RuntimeError as exc:
            errors.append(str(exc))
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "gate_report_count": len(manifest.get("gate_reports", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seal", "verify"))
    args = parser.parse_args()
    try:
        result = seal() if args.action == "seal" else verify()
    except RuntimeError as exc:
        result = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("PASS", "SEALED") else 1)


if __name__ == "__main__":
    main()
