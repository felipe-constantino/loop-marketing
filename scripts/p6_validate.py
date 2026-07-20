#!/usr/bin/env python3
"""Validate the P6 security boundary and its sealed dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
P6 = ROOT / "artifacts" / "P6"
SOURCE = ROOT.parent / "loop-marketing"
BASELINE = "3cbf0cf84a038f2cd570883b70988889f037c28e"


def run(command, cwd=ROOT, env=None):
    return subprocess.run(command, cwd=str(cwd), env=env, text=True, capture_output=True, check=False)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_historical_p5(errors):
    manifest_path = ROOT / "artifacts" / "P5" / "integration-manifest.json"
    manifest = load(manifest_path)
    superseded = {
        "candidate/loop-marketing-v2/src/loop_marketing_runtime/__init__.py",
        "candidate/loop-marketing-v2/pyproject.toml",
        "candidate/loop-marketing-v2/setup.py",
    }
    for section in ("source_contracts", "official_artifacts", "runtime_files", "tests", "scripts", "gate_reports"):
        for item in manifest.get(section, []):
            if item["path"] in superseded:
                continue
            path = ROOT / item["path"]
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                errors.append("historical P5 seal drift: %s" % item["path"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = []
    required = [
        P6 / "security-contract.json",
        P6 / "security-fixtures.json",
        P6 / "workstreams" / "security-policy.json",
        P6 / "workstreams" / "threat-model.json",
        CANDIDATE / "src" / "loop_marketing_runtime" / "security.py",
        CANDIDATE / "src" / "loop_marketing_runtime" / "secure_runtime.py",
        CANDIDATE / "src" / "loop_marketing_runtime" / "secure_cli.py",
        CANDIDATE / "src" / "loop_marketing_runtime" / "secure_adapters.py",
        CANDIDATE / "src" / "loop_marketing_runtime" / "observability.py",
        CANDIDATE / "tests" / "test_security.py",
        CANDIDATE / "tests" / "test_secure_runtime.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append("required file missing: %s" % path.relative_to(root))
    for path in [item for item in required if item.suffix == ".json"]:
        try:
            load(path)
        except (OSError, ValueError):
            errors.append("invalid JSON: %s" % path.relative_to(root))

    fixtures = load(P6 / "security-fixtures.json")
    contract = load(P6 / "security-contract.json")
    expected_fixture_codes = {
        "SEC-NEG-001": "ERR_SECURITY_JSON_TYPE",
        "SEC-NEG-002": "ERR_SECURITY_JSON_DEPTH",
        "SEC-NEG-003": "ERR_SECURITY_JSON_NODES",
        "SEC-NEG-004": "ERR_SECURITY_JSON_TOTAL_STRING_SIZE",
        "SEC-NEG-005": "ERR_SECURITY_JSON_INTEGER_SIZE",
        "SEC-NEG-006": "ERR_SECURITY_JSON_DUPLICATE_KEY",
        "SEC-NEG-007": "ERR_SECURITY_INPUT_SIZE",
        "SEC-NEG-008": "ERR_SECURITY_INPUT_PATH",
        "SEC-NEG-009": "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
        "SEC-NEG-010": "ERR_SECURITY_SENSITIVE_INPUT",
        "SEC-NEG-011": "ERR_RUNTIME_INTERNAL",
        "SEC-NEG-012": "ERR_SECURITY_OUTPUT_SIZE",
        "SEC-NEG-013": "ERR_CANONICAL_LIBRARY_DRIFT",
        "SEC-NEG-014": "ERR_PROJECT_PATH_INVALID",
        "SEC-NEG-015": "ERR_SECURITY_PERMISSION_DENIED",
    }
    actual_fixture_codes = {item.get("id"): item.get("expected") for item in fixtures.get("negative_scenarios", [])}
    if actual_fixture_codes != expected_fixture_codes:
        errors.append("security fixture scenario count drift")
    if contract.get("permission_modes", {}).get("external_mutation", {}).get("exposed") is not False:
        errors.append("external mutation surface is not closed")

    verify_historical_p5(errors)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(CANDIDATE / "src"), str(CANDIDATE / "tests")])
    suite = run([sys.executable, "-m", "unittest", "discover", "-s", str(CANDIDATE / "tests"), "-v"], env=env)
    suite_text = suite.stdout + suite.stderr
    match = re.search(r"Ran (\d+) tests", suite_text)
    test_count = int(match.group(1)) if match else 0
    if suite.returncode or test_count < fixtures["expected_minimum_full_suite_tests"]:
        errors.append("full runtime suite failed or fell below the P6 minimum")

    security_suite = run([
        sys.executable, "-m", "unittest", "-v", "test_security", "test_secure_runtime"
    ], env=env)
    security_match = re.search(r"Ran (\d+) tests", security_suite.stdout + security_suite.stderr)
    security_count = int(security_match.group(1)) if security_match else 0
    if security_suite.returncode or security_count < 25:
        errors.append("security-specific suite failed")

    modules = [
        CANDIDATE / "src" / "loop_marketing_runtime" / name
        for name in ("security.py", "secure_runtime.py", "secure_cli.py", "secure_adapters.py", "observability.py")
    ]
    forbidden = re.compile(r"\b(subprocess|socket|urllib|requests|httpx|eval|exec)\b")
    credential_discovery = re.compile(r"(?i)(glob|rglob).*(token|credential|secret)|os\.walk")
    for path in modules:
        body = path.read_text(encoding="utf-8")
        if forbidden.search(body) or credential_discovery.search(body):
            errors.append("forbidden capability in security surface: %s" % path.name)
    secure_body = (modules[1]).read_text(encoding="utf-8")
    if "def orchestrator(" in secure_body or "external_mutation_allowed\"] = True" in secure_body:
        errors.append("secure facade exposes a bypass")
    if "untrusted_tactical_data" not in secure_body or "credential_discovery_allowed\": False" not in secure_body:
        errors.append("prompt execution-policy overlay is incomplete")

    try:
        sys.path.insert(0, str(CANDIDATE / "src"))
        from loop_marketing_runtime.security import sanitize_message
        catalog = load(CANDIDATE / "data" / "tactic-catalog.json")
        sensitive_prompts = []
        total_bytes = 0
        for tactic in catalog["tactics"]:
            prompt = SOURCE / tactic["canonical_path"]
            raw = prompt.read_bytes()
            total_bytes += len(raw)
            text = raw.decode("utf-8")
            if hashlib.sha256(raw).hexdigest() != tactic["canonical_sha256"] or sanitize_message(text) != text:
                sensitive_prompts.append(tactic["tactic_id"])
        if len(catalog["tactics"]) != 100 or sensitive_prompts:
            errors.append("canonical prompt integrity or sensitive-content gate failed")
    except Exception as exc:
        total_bytes = 0
        errors.append("canonical prompt security scan failed: %s" % type(exc).__name__)

    packaged_security_modules = 0
    secure_entrypoint = False
    with tempfile.TemporaryDirectory(prefix="loop-p6-wheel-") as temporary:
        wheel = run([
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--wheel-dir", temporary, str(CANDIDATE),
        ])
        wheels = list(Path(temporary).glob("*.whl"))
        if wheel.returncode or len(wheels) != 1:
            errors.append("P6 wheel build failed")
        else:
            with zipfile.ZipFile(str(wheels[0])) as archive:
                names = archive.namelist()
                entrypoint_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
                entrypoint_text = archive.read(entrypoint_names[0]).decode("utf-8") if len(entrypoint_names) == 1 else ""
            packaged_security_modules = sum(
                any(name.endswith("/%s" % module.name) for name in names) for module in modules
            )
            if packaged_security_modules != 5:
                errors.append("wheel omits a P6 security module")
            secure_entrypoint = "loop-marketing = loop_marketing_runtime.secure_cli:main" in entrypoint_text
            if not secure_entrypoint or "loop_marketing_runtime.cli:main" in entrypoint_text:
                errors.append("wheel does not publish the secure CLI exclusively")

    secure_cli_run = run([
        sys.executable, "-m", "loop_marketing_runtime.secure_cli",
        "--runtime-root", str(CANDIDATE),
        "--library-root", str(SOURCE),
        "--state-root", str(Path(tempfile.gettempdir()) / "loop-p6-cli-state"),
        "resolve", "/projeto-template",
    ], ROOT, env)
    try:
        secure_cli_result = json.loads(secure_cli_run.stdout)
    except ValueError:
        secure_cli_result = {}
    if secure_cli_run.returncode or secure_cli_result.get("result", {}).get("command_id") != "loop.projeto":
        errors.append("secure CLI entry behavior failed")

    source_head = run(["git", "rev-parse", "HEAD"], cwd=SOURCE).stdout.strip()
    source_status = run(["git", "status", "--porcelain"], cwd=SOURCE).stdout.strip()
    if source_head != BASELINE or source_status:
        errors.append("canonical source repository drift")
    if run(["git", "diff", "--check"], cwd=root).returncode:
        errors.append("control worktree whitespace errors")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "counts": {
            "full_suite_tests": test_count,
            "security_tests": security_count,
            "negative_scenarios": len(fixtures.get("negative_scenarios", [])),
            "canonical_prompts": 100,
            "canonical_prompt_bytes": total_bytes,
            "packaged_security_modules": packaged_security_modules
        },
        "secure_entrypoint": secure_entrypoint,
        "source": {"commit": source_head, "clean": not bool(source_status), "preserved": source_head == BASELINE and not source_status}
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
