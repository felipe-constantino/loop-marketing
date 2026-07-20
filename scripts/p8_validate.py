#!/usr/bin/env python3
"""Validate the portable internal Loop Marketing skill release."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "release" / "loop-marketing"
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
SOURCE = ROOT.parent / "loop-marketing"
QUICK_VALIDATE = Path("/Users/enorm/.codex/skills/.system/skill-creator/scripts/quick_validate.py")
BASELINE = "3cbf0cf84a038f2cd570883b70988889f037c28e"
AGGREGATE = "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def run(command, cwd=ROOT, env=None): return subprocess.run(command, cwd=str(cwd), env=env, text=True, capture_output=True, check=False)


def wrapper(args, cwd):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = run(
        [sys.executable, str(SKILL / "scripts" / "loop_marketing.py")] + list(args),
        cwd=cwd,
        env=env,
    )
    try: value = json.loads(completed.stdout)
    except ValueError: value = {}
    return completed, value


def main():
    errors = []
    required = [
        SKILL / "SKILL.md",
        SKILL / "agents" / "openai.yaml",
        SKILL / "scripts" / "loop_marketing.py",
        SKILL / "references" / "operating-guide.md",
        SKILL / "references" / "security-model.md",
        SKILL / "references" / "data-contract.md",
        SKILL / "references" / "evaluation-contract.md",
    ]
    for path in required:
        if not path.is_file(): errors.append("required release file missing: %s" % path.relative_to(ROOT))

    p7 = run([sys.executable, str(ROOT / "scripts" / "p7_seal.py"), "verify"])
    try:
        p7_result = json.loads(p7.stdout)
    except ValueError:
        p7_result = {}
    if p7.returncode or p7_result.get("status") != "PASS":
        errors.append("P7 dependency seal failed")

    quick = run([sys.executable, str(QUICK_VALIDATE), str(SKILL)])
    if quick.returncode or "Skill is valid" not in quick.stdout:
        errors.append("official skill validator failed")

    skill_body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    guide_body = (SKILL / "references" / "operating-guide.md").read_text(encoding="utf-8")
    data_body = (SKILL / "references" / "data-contract.md").read_text(encoding="utf-8")
    evaluation_body = (SKILL / "references" / "evaluation-contract.md").read_text(encoding="utf-8")
    documentation_contract = (
        "python3 <skill-root>/scripts/loop_marketing.py" in skill_body
        and "project:<slug>" in guide_body
        and "refinar:data-audit" in guide_body
        and "root_cause_candidate" in data_body
        and "supporting_fact_refs" in data_body
        and "external_mutation_executed" in evaluation_body
        and "runtime_attested: false" in evaluation_body
    )
    if not documentation_contract:
        errors.append("operational documentation contract drift")

    expected_runtime = {
        "__init__.py", "catalog.py", "errors.py", "evaluation.py", "models.py",
        "observability.py", "orchestrator.py", "router.py", "secure_adapters.py",
        "secure_cli.py", "secure_runtime.py", "security.py", "state_store.py", "validation.py",
    }
    release_runtime = SKILL / "scripts" / "runtime" / "loop_marketing_runtime"
    actual_runtime = {path.name for path in release_runtime.glob("*.py")}
    if actual_runtime != expected_runtime:
        errors.append("bundled runtime module surface drift")
    for name in expected_runtime:
        if not (release_runtime / name).is_file() or (release_runtime / name).read_bytes() != (CANDIDATE / "src" / "loop_marketing_runtime" / name).read_bytes():
            errors.append("bundled runtime drift: %s" % name)

    pairs = [
        (SKILL / "references" / "runtime-data" / "data" / name, CANDIDATE / "data" / name)
        for name in ("tactic-catalog.json", "relationship-map.json")
    ] + [
        (SKILL / "references" / "runtime-data" / "contracts" / name, CANDIDATE / "contracts" / name)
        for name in ("state-schema.json", "event-schema.json", "handoff-schema.json")
    ]
    for bundled, source in pairs:
        if not bundled.is_file() or bundled.read_bytes() != source.read_bytes():
            errors.append("bundled contract/data drift: %s" % bundled.name)

    portable_pairs = [
        (
            SKILL / "references" / "runtime-data" / "data" / "role-matrix.json",
            CANDIDATE / "data" / "role-matrix.json",
            ("baseline", "source_repo"),
        ),
        (
            SKILL / "references" / "runtime-data" / "data" / "routing-contract.json",
            CANDIDATE / "data" / "routing-contract.json",
            ("source_baseline", "repo"),
        ),
    ]
    for bundled, source, keys in portable_pairs:
        expected = load(source)
        expected[keys[0]][keys[1]] = "bundled:references/library"
        if not bundled.is_file() or load(bundled) != expected:
            errors.append("portable bundled data drift: %s" % bundled.name)

    catalog = load(SKILL / "references" / "runtime-data" / "data" / "tactic-catalog.json")
    library = SKILL / "references" / "library"
    prompt_records = []
    for tactic in catalog.get("tactics", []):
        path = library / tactic["canonical_path"]
        if not path.is_file() or path.is_symlink() or sha(path) != tactic["canonical_sha256"]:
            errors.append("canonical prompt drift: %s" % tactic.get("tactic_id"))
        else:
            prompt_records.append("%s\0%s" % (tactic["canonical_path"], sha(path)))
    aggregate = hashlib.sha256("\n".join(sorted(prompt_records)).encode("utf-8")).hexdigest()
    library_files = [path for path in (library / "biblioteca").rglob("*") if path.is_file()]
    index_files = [path for path in library_files if path.name == "INDEX.md"]
    if len(catalog.get("tactics", [])) != 100 or len(prompt_records) != 100 or aggregate != AGGREGATE:
        errors.append("100-prompt preservation gate failed")
    if len(library_files) != 104 or len(index_files) != 4:
        errors.append("library navigation file count drift")

    wrapper_body = (SKILL / "scripts" / "loop_marketing.py").read_text(encoding="utf-8")
    if "runtime-root" in wrapper_body or "library-root" in wrapper_body or "external_mutation" in wrapper_body:
        errors.append("wrapper exposes a forbidden root or mutation parameter")
    if (release_runtime / "cli.py").exists() or (release_runtime / "adapters.py").exists():
        errors.append("legacy P5 bypass module is bundled")

    command_results = 0
    e2e_committed = False
    evaluation_passed = False
    sensitive_rejected = False
    with tempfile.TemporaryDirectory(prefix="loop-p8-validate-") as temporary:
        temp = Path(temporary)
        commands = {
            "/loop-planning": "loop.planning", "/loop-planning-agent": "loop.planning",
            "/verbalizar": "loop.verbalizar", "/verbalizar-agent": "loop.verbalizar",
            "/orientar": "loop.orientar", "/orientar-agent": "loop.orientar",
            "/ampliar": "loop.ampliar", "/ampliar-agent": "loop.ampliar",
            "/refinar": "loop.refinar", "/refinar-agent": "loop.refinar",
            "/projeto": "loop.projeto", "/projeto-template": "loop.projeto",
        }
        for invocation, command_id in commands.items():
            completed, value = wrapper(["resolve", invocation], temp)
            if completed.returncode == 0 and value.get("result", {}).get("command_id") == command_id:
                command_results += 1

        sys.path.insert(0, str(CANDIDATE / "src")); sys.path.insert(0, str(CANDIDATE / "tests"))
        from test_orchestrator_e2e import OrchestratorEndToEndTests
        from test_evaluation import passing_case, passing_outcome
        helper = OrchestratorEndToEndTests(methodName="test_real_adapters_resolve_all_commands_without_host_semantic_drift")
        initialized, init_value = wrapper(["init", "e2e", "Packaged E2E"], temp)
        request = helper._request()
        request_path = temp / "request.json"; request_path.write_text(json.dumps(request), encoding="utf-8")
        routed, route_value = wrapper(["route", str(request_path)], temp)
        route_plan = route_value.get("result", {})
        if initialized.returncode == 0 and routed.returncode == 0 and route_plan.get("route_status") == "ready":
            handoff = helper._handoff(route_plan)
            events = helper._events(route_plan)
            envelope_path = temp / "envelope.json"
            envelope_path.write_text(json.dumps({"project_id": "e2e", "route_plan": route_plan, "handoffs": [handoff], "events": events}), encoding="utf-8")
            integrated, integration_value = wrapper(["integrate", str(envelope_path)], temp)
            reread, read_value = wrapper(["read", "e2e"], temp)
            e2e_committed = (
                integrated.returncode == 0 and integration_value.get("result", {}).get("status") == "committed"
                and reread.returncode == 0 and read_value.get("result", {}).get("state_revision") == 1
            )

        evaluation_path = temp / "evaluation.json"
        evaluation_path.write_text(json.dumps({"case": passing_case(), "outcome": passing_outcome()}), encoding="utf-8")
        evaluated, evaluation_value = wrapper(["evaluate", str(evaluation_path)], temp)
        evaluation_passed = (
            evaluated.returncode == 0 and evaluation_value.get("result", {}).get("status") == "passed"
            and evaluation_value.get("result", {}).get("assurance", {}).get("runtime_attested") is False
        )

        wrapper(["init", "sensitive", "Sensitive gate"], temp)
        sensitive = helper._request(); sensitive.update({"project_id": "project:sensitive", "cycle_id": "cycle:sensitive", "user_goal": "token=synthetic-secret-value"})
        sensitive_path = temp / "sensitive.json"; sensitive_path.write_text(json.dumps(sensitive), encoding="utf-8")
        rejected, rejected_value = wrapper(["route", str(sensitive_path)], temp)
        rendered = json.dumps(rejected_value)
        sensitive_rejected = (
            rejected.returncode == 2 and rejected_value.get("error", {}).get("code") == "ERR_SECURITY_SENSITIVE_INPUT"
            and "synthetic-secret-value" not in rendered
        )

    if command_results != 12: errors.append("command compatibility failed")
    if not e2e_committed: errors.append("packaged init-route-integrate-read chain failed")
    if not evaluation_passed: errors.append("packaged evaluator failed")
    if not sensitive_rejected: errors.append("packaged sensitive-input gate failed")

    source_head = run(["git", "rev-parse", "HEAD"], cwd=SOURCE).stdout.strip()
    source_status = run(["git", "status", "--porcelain"], cwd=SOURCE).stdout.strip()
    if source_head != BASELINE or source_status: errors.append("canonical source repository drift")
    if any(SKILL.rglob("__pycache__")) or any(SKILL.rglob("*.pyc")):
        errors.append("release contains generated Python cache")
    local_path_markers = ("/Users/", "/home/", "C:\\Users\\", "C:\\Documents and Settings\\")
    leaked_paths = []
    for path in (item for item in SKILL.rglob("*") if item.is_file()):
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in body for marker in local_path_markers):
            leaked_paths.append(str(path.relative_to(SKILL)))
    if leaked_paths:
        errors.append("release contains local absolute paths")
    if run(["git", "diff", "--check"]).returncode: errors.append("control worktree whitespace errors")

    result = {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "counts": {"canonical_prompts": len(prompt_records), "library_files": len(library_files), "navigation_indexes": len(index_files), "runtime_modules": len(actual_runtime), "command_invocations": command_results},
        "gates": {"p7_dependency_seal": p7_result.get("status") == "PASS", "official_skill_validator": quick.returncode == 0, "documentation_contract": documentation_contract, "portable_path_hygiene": not leaked_paths, "packaged_e2e_committed": e2e_committed, "evaluation_passed": evaluation_passed, "sensitive_input_rejected": sensitive_rejected},
        "source": {"commit": source_head, "clean": not bool(source_status), "preserved": source_head == BASELINE and not source_status}
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__": main()
