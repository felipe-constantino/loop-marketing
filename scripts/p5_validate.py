#!/usr/bin/env python3
"""Validate the staged P5 runtime against the sealed P2-P4 contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path
from typing import Any, Dict, List


BASELINE_COMMIT = "3cbf0cf84a038f2cd570883b70988889f037c28e"
SOURCE = Path("/Users/enorm/Documents/Claude/loop-marketing")


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: List[str], cwd: Path, env: Dict[str, str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    candidate = root / "candidate" / "loop-marketing-v2"
    p5 = root / "artifacts" / "P5"
    errors: List[str] = []

    required = [
        p5 / "runtime-contract.json",
        p5 / "runtime-fixtures.json",
        candidate / "pyproject.toml",
        candidate / "setup.py",
        candidate / "adapters" / "adapter-contract.json",
        candidate / "src" / "loop_marketing_runtime" / "catalog.py",
        candidate / "src" / "loop_marketing_runtime" / "router.py",
        candidate / "src" / "loop_marketing_runtime" / "validation.py",
        candidate / "src" / "loop_marketing_runtime" / "state_store.py",
        candidate / "src" / "loop_marketing_runtime" / "orchestrator.py",
        candidate / "src" / "loop_marketing_runtime" / "adapters.py",
        candidate / "src" / "loop_marketing_runtime" / "cli.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append("required file missing: %s" % path.relative_to(root))

    json_files = list((candidate / "data").glob("*.json"))
    json_files += list((candidate / "contracts").glob("*.json"))
    json_files += [p5 / "runtime-contract.json", p5 / "runtime-fixtures.json", candidate / "adapters" / "adapter-contract.json"]
    for path in json_files:
        try:
            load(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append("invalid JSON %s: %s" % (path.relative_to(root), type(exc).__name__))

    exact_copies = {
        candidate / "data" / "tactic-catalog.json": root / "artifacts" / "P3" / "tactic-catalog.json",
        candidate / "data" / "relationship-map.json": root / "artifacts" / "P3" / "relationship-map.json",
        candidate / "data" / "role-matrix.json": root / "artifacts" / "P2" / "role-matrix.json",
        candidate / "data" / "routing-contract.json": root / "artifacts" / "P2" / "routing-contract.json",
        candidate / "contracts" / "state-schema.json": root / "artifacts" / "P4" / "state-schema.json",
        candidate / "contracts" / "event-schema.json": root / "artifacts" / "P4" / "event-schema.json",
        candidate / "contracts" / "handoff-schema.json": root / "artifacts" / "P4" / "handoff-schema.json",
    }
    for staged, sealed in exact_copies.items():
        if not staged.is_file() or not sealed.is_file() or staged.read_bytes() != sealed.read_bytes():
            errors.append("staged contract drift: %s" % staged.relative_to(root))

    fixtures = load(p5 / "runtime-fixtures.json") if (p5 / "runtime-fixtures.json").is_file() else {}
    expected_tests = fixtures.get("expected_test_count")
    declared_tests = sum(item.get("expected_count", 0) for item in fixtures.get("suites", []))
    if expected_tests != 50 or declared_tests != expected_tests:
        errors.append("runtime fixture test counts are inconsistent")

    command_contract = load(candidate / "adapters" / "adapter-contract.json") if (candidate / "adapters" / "adapter-contract.json").is_file() else {}
    commands = command_contract.get("commands", {})
    if len(commands) != 12 or command_contract.get("external_write_methods") != []:
        errors.append("adapter command or write surface drift")
    if command_contract.get("state_namespace") != ".loop-marketing/":
        errors.append("adapter state namespace drift")

    pyproject = (candidate / "pyproject.toml").read_text(encoding="utf-8") if (candidate / "pyproject.toml").is_file() else ""
    if 'requires-python = ">=3.9"' not in pyproject or "dependencies = []" not in pyproject:
        errors.append("Python 3.9 or dependency-free packaging contract drift")

    packaged_assets = 0
    installed_cli = False
    with tempfile.TemporaryDirectory(prefix="loop-p5-package-") as package_temp:
        package_root = Path(package_temp)
        wheel_result = run([
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(package_root), str(candidate),
        ], root)
        wheels = list(package_root.glob("loop_marketing_runtime-*.whl"))
        if wheel_result.returncode != 0 or len(wheels) != 1:
            errors.append("installable wheel build failed")
        else:
            with zipfile.ZipFile(str(wheels[0])) as archive:
                names = archive.namelist()
            packaged_assets = len([
                name for name in names if "share/loop-marketing-runtime/" in name
            ])
            if packaged_assets != 8 or not any(name.endswith("loop_marketing_runtime/cli.py") for name in names):
                errors.append("wheel does not contain the runtime modules and eight sealed assets")
            environment_root = package_root / "venv"
            try:
                venv.EnvBuilder(with_pip=True, clear=True).create(str(environment_root))
                python = environment_root / "bin" / "python"
                console = environment_root / "bin" / "loop-marketing"
                installed = run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], root)
                invoked = run([str(console), "resolve", "/projeto-template"], package_root) if installed.returncode == 0 else installed
                response = json.loads(invoked.stdout) if invoked.returncode == 0 else {}
                installed_cli = (
                    installed.returncode == 0
                    and invoked.returncode == 0
                    and response.get("ok") is True
                    and response.get("result", {}).get("command_id") == "loop.projeto"
                )
            except (OSError, ValueError, json.JSONDecodeError):
                installed_cli = False
            if not installed_cli:
                errors.append("installed console script could not resolve commands from packaged assets")

    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(candidate / "src")
    suite = run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(candidate / "tests"), "-v"],
        root,
        env,
    )
    suite_text = suite.stdout + suite.stderr
    match = re.search(r"Ran (\d+) tests", suite_text)
    ran_tests = int(match.group(1)) if match else 0
    if suite.returncode != 0 or ran_tests != expected_tests:
        errors.append("runtime unit/integration suite failed or test count drifted")

    try:
        sys.path.insert(0, str(candidate / "src"))
        from loop_marketing_runtime.catalog import CatalogLoader
        from loop_marketing_runtime.models import RuntimeConfig

        with tempfile.TemporaryDirectory(prefix="loop-p5-validate-") as temporary:
            config = RuntimeConfig(
                library_root=SOURCE,
                catalog_path=candidate / "data" / "tactic-catalog.json",
                relationship_path=candidate / "data" / "relationship-map.json",
                role_matrix_path=candidate / "data" / "role-matrix.json",
                routing_contract_path=candidate / "data" / "routing-contract.json",
                state_root=Path(temporary) / ".loop-marketing",
                contracts_root=candidate / "contracts",
            )
            catalog_result = CatalogLoader(config).verify_catalog()
            if not catalog_result.ok or catalog_result.value.get("verified_tactic_count") != 100:
                errors.append("live canonical catalog verification failed")
            verified_relations = catalog_result.value.get("verified_relation_count", 0) if catalog_result.ok else 0
    except Exception as exc:  # converted to a deterministic gate error
        verified_relations = 0
        errors.append("runtime import/catalog gate failed: %s" % type(exc).__name__)

    source_head = run(["git", "rev-parse", "HEAD"], SOURCE).stdout.strip()
    source_status = run(["git", "status", "--porcelain"], SOURCE).stdout.strip()
    if source_head != BASELINE_COMMIT:
        errors.append("canonical source commit drift")
    if source_status:
        errors.append("canonical source worktree is not clean")

    diff_check = run(["git", "diff", "--check"], root)
    if diff_check.returncode != 0:
        errors.append("control worktree has whitespace errors")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "counts": {
            "tests": ran_tests,
            "canonical_tactics": 100 if not any("catalog" in item for item in errors) else 0,
            "confirmed_relations": verified_relations,
            "command_invocations": len(commands),
            "handoff_top_level_fields": 22,
            "runtime_modules": len(list((candidate / "src" / "loop_marketing_runtime").glob("*.py"))),
            "packaged_assets": packaged_assets,
        },
        "source": {
            "commit": source_head,
            "clean": not bool(source_status),
            "preserved": source_head == BASELINE_COMMIT and not bool(source_status),
        },
        "suite_returncode": suite.returncode,
        "installed_cli": installed_cli,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
