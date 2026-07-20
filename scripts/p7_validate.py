#!/usr/bin/env python3
"""Validate P7 evaluations, observability and red-team evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
P7 = ROOT / "artifacts" / "P7"
SOURCE = ROOT.parent / "loop-marketing"
BASELINE = "3cbf0cf84a038f2cd570883b70988889f037c28e"


def run(command, env=None, cwd=ROOT):
    return subprocess.run(command, cwd=str(cwd), env=env, text=True, capture_output=True, check=False)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_seal(path, sections, errors):
    if not path.is_file():
        errors.append("dependency seal missing: %s" % path.name)
        return
    try:
        manifest = load(path)
    except (OSError, ValueError):
        errors.append("dependency seal is malformed: %s" % path.name)
        return
    expected_counts = {
        "official_artifacts": 4,
        "runtime_files": 8,
        "tests": 3,
        "scripts": 3,
        "gate_reports": 3,
    }
    if (
        manifest.get("artifact_id") != "loop-marketing-p6-integration-manifest"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("product_version") != "2.0.0"
        or manifest.get("status") != "sealed"
        or manifest.get("baseline", {}).get("source_commit") != BASELINE
        or manifest.get("gate_summary", {}).get("validator") != "PASS"
        or manifest.get("gate_summary", {}).get("negative_regression") != "PASS"
        or manifest.get("gate_summary", {}).get("independent_audit") != "PASS"
        or manifest.get("gate_summary", {}).get("source_preserved") is not True
    ):
        errors.append("dependency seal metadata is incomplete or failed")
    for section in sections:
        items = manifest.get(section)
        if type(items) is not list or len(items) != expected_counts[section]:
            errors.append("dependency seal topology drift: %s" % section)
            continue
        paths = []
        for item in items:
            if (
                type(item) is not dict
                or set(item) != {"path", "sha256"}
                or type(item.get("path")) is not str
                or type(item.get("sha256")) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            ):
                errors.append("dependency seal entry malformed: %s" % section)
                continue
            paths.append(item["path"])
            target = ROOT / item["path"]
            if not target.is_file() or sha(target) != item["sha256"]:
                errors.append("dependency seal drift: %s" % item["path"])
        if len(paths) != len(set(paths)):
            errors.append("dependency seal duplicates: %s" % section)


def main():
    errors = []
    required = [
        P7 / "evaluation-contract.json",
        P7 / "evaluation-cases.json",
        P7 / "workstreams" / "evaluation-design.json",
        P7 / "workstreams" / "observability-design.json",
        CANDIDATE / "src" / "loop_marketing_runtime" / "evaluation.py",
        CANDIDATE / "src" / "loop_marketing_runtime" / "observability.py",
        CANDIDATE / "tests" / "test_evaluation.py",
        CANDIDATE / "tests" / "test_observability.py",
        ROOT / "scripts" / "p7_evaluate.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append("required file missing: %s" % path.relative_to(ROOT))
    for path in [item for item in required if item.suffix == ".json"]:
        try:
            load(path)
        except (OSError, ValueError):
            errors.append("invalid JSON: %s" % path.relative_to(ROOT))

    verify_seal(
        ROOT / "artifacts" / "P6" / "integration-manifest.json",
        ("official_artifacts", "runtime_files", "tests", "scripts", "gate_reports"),
        errors,
    )
    p6_verify = run([sys.executable, str(ROOT / "scripts" / "p6_seal.py"), "verify"])
    try:
        p6_verify_result = json.loads(p6_verify.stdout)
    except ValueError:
        p6_verify_result = {}
    if p6_verify.returncode or p6_verify_result.get("status") != "PASS":
        errors.append("live P6 dependency verification failed")

    cases = load(P7 / "evaluation-cases.json").get("cases", [])
    case_ids = [item.get("case", {}).get("case_id") for item in cases]
    scenario_types = {item.get("scenario", {}).get("type") for item in cases}
    pillars = {item.get("scenario", {}).get("pillar") for item in cases}
    maturities = {item.get("scenario", {}).get("maturity") for item in cases}
    if len(cases) != 10 or len(case_ids) != len(set(case_ids)):
        errors.append("evaluation case count or IDs drift")
    if not {"route_ready", "route_needs_evidence", "route_blocked", "route_rejected", "sensitive_input", "external_mutation", "specialist_prompt_boundary"}.issubset(scenario_types):
        errors.append("evaluation scenario coverage incomplete")
    if not {"verbalizar", "orientar", "ampliar", "refinar"}.issubset(pillars):
        errors.append("pillar coverage incomplete")
    if not {"unknown", "nascente", "em_desenvolvimento", "maduro", "avancado"}.issubset(maturities):
        errors.append("maturity coverage incomplete")

    first = run([sys.executable, str(ROOT / "scripts" / "p7_evaluate.py")])
    second = run([sys.executable, str(ROOT / "scripts" / "p7_evaluate.py")])
    try:
        evaluation = json.loads(first.stdout)
        deterministic = first.stdout == second.stdout
    except ValueError:
        evaluation = {}
        deterministic = False
    if first.returncode or second.returncode or evaluation.get("status") != "passed" or not deterministic:
        errors.append("end-to-end evaluation failed or is nondeterministic")
    if evaluation.get("summary") != {"case_count": 10, "passed": 10, "failed": 0}:
        errors.append("evaluation summary drift")
    attestation = evaluation.get("runtime_attestation", {})
    if (
        evaluation.get("release_gate_status") != "passed"
        or attestation.get("runtime_attested") is not True
        or attestation.get("case_count") != 10
        or attestation.get("all_read_only_state_checks_passed") is not True
        or attestation.get("audit_traces_attested") is not True
        or attestation.get("capability_scan", {}).get("status") != "passed"
        or attestation.get("capability_scan", {}).get("runtime_integrity_attested") is not True
        or attestation.get("capability_scan", {}).get("runtime_integrity_drift_count") != 0
    ):
        errors.append("runtime attestation is absent or failed")
    sensitive_markers = ("person@example.com", "synthetic-secret-value", "prompt_body", "/Users/")
    if any(marker in first.stdout for marker in sensitive_markers):
        errors.append("evaluation report leaked forbidden content")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(CANDIDATE / "src"), str(CANDIDATE / "tests")])
    suite = run([sys.executable, "-m", "unittest", "discover", "-s", str(CANDIDATE / "tests"), "-v"], env=env)
    match = re.search(r"Ran (\d+) tests", suite.stdout + suite.stderr)
    test_count = int(match.group(1)) if match else 0
    if suite.returncode or test_count < 82:
        errors.append("full suite failed or fell below P7 minimum")

    p7_suite = run([sys.executable, "-m", "unittest", "-v", "test_evaluation", "test_observability"], env=env)
    match = re.search(r"Ran (\d+) tests", p7_suite.stdout + p7_suite.stderr)
    p7_test_count = int(match.group(1)) if match else 0
    if p7_suite.returncode or p7_test_count < 13:
        errors.append("P7 unit suite failed")

    for name in ("evaluation.py", "observability.py"):
        path = CANDIDATE / "src" / "loop_marketing_runtime" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }.union({
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        })
        if imports.intersection({"subprocess", "socket", "urllib", "requests", "httpx"}):
            errors.append("forbidden sink in %s" % name)
    obs_body = (CANDIDATE / "src" / "loop_marketing_runtime" / "observability.py").read_text(encoding="utf-8")
    if "def __init__(self, enabled: bool = False)" not in obs_body or "return False" not in obs_body:
        errors.append("observability default or persistence boundary drift")

    source_head = run(["git", "rev-parse", "HEAD"], cwd=SOURCE).stdout.strip()
    source_status = run(["git", "status", "--porcelain"], cwd=SOURCE).stdout.strip()
    if source_head != BASELINE or source_status:
        errors.append("canonical source repository drift")
    if run(["git", "diff", "--check"]).returncode:
        errors.append("control worktree whitespace errors")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "counts": {"evaluation_cases": len(cases), "evaluation_passed": evaluation.get("summary", {}).get("passed", 0), "p7_tests": p7_test_count, "full_suite_tests": test_count, "pillars": 4, "maturity_states": 5},
        "deterministic": deterministic,
        "source": {"commit": source_head, "clean": not bool(source_status), "preserved": source_head == BASELINE and not source_status}
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
