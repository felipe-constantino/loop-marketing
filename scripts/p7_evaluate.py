#!/usr/bin/env python3
"""Execute the deterministic P7 synthetic evaluation suite."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
SOURCE = ROOT.parent / "loop-marketing"
sys.path.insert(0, str(CANDIDATE / "src"))

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.evaluation import evaluate_suite
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.observability import AuditCollector
from loop_marketing_runtime.secure_runtime import SecureLoopRuntime
from loop_marketing_runtime.security import safe_fingerprint, sanitize_structure


SENSITIVE_PROBES = ("person@example.com", "synthetic-secret-value")
EXPECTED_RUNTIME_MODULES = frozenset({
    "__init__.py", "adapters.py", "catalog.py", "cli.py", "errors.py",
    "evaluation.py", "models.py", "observability.py", "orchestrator.py",
    "router.py", "secure_adapters.py", "secure_cli.py", "secure_runtime.py",
    "security.py", "state_store.py", "validation.py",
})
EXPECTED_EVALUATION_SHA256 = "b6451f9bfae75e57329ab0f23b3e26b37b6826aa47bb7b25ed04fe7b6712e2a1"


def tree_fingerprint(root):
    digest = hashlib.sha256()
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "sha256:%s" % digest.hexdigest()


def capability_attestation():
    package = CANDIDATE / "src" / "loop_marketing_runtime"
    forbidden_imports = {"subprocess", "urllib", "http", "requests", "httpx", "ftplib", "smtplib"}
    forbidden_calls = {"eval", "exec", "compile", "__import__"}
    forbidden_qualified_calls = {
        "os.system",
        "os.popen",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
    }
    mutation_methods = {
        "chmod", "hardlink_to", "link_to", "mkdir", "rename", "rmdir",
        "symlink_to", "touch", "unlink", "write_bytes", "write_text",
    }
    filesystem_calls = {
        "os.chmod", "os.chown", "os.link", "os.makedirs", "os.mkdir",
        "os.remove", "os.removedirs", "os.rename", "os.renames", "os.replace",
        "os.rmdir", "os.symlink", "os.truncate", "os.unlink",
    }
    findings = []
    files = sorted(package.glob("*.py"))
    actual_names = {path.name for path in files}
    anchored_hashes = {"evaluation.py": EXPECTED_EVALUATION_SHA256}
    try:
        for manifest_path in (
            ROOT / "artifacts" / "P5" / "integration-manifest.json",
            ROOT / "artifacts" / "P6" / "integration-manifest.json",
        ):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["runtime_files"]:
                relative = Path(item["path"])
                if relative.parent == Path("candidate/loop-marketing-v2/src/loop_marketing_runtime") and relative.suffix == ".py":
                    anchored_hashes[relative.name] = item["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        findings.append("runtime_integrity_metadata")
    integrity_drift = 0
    if actual_names != EXPECTED_RUNTIME_MODULES or set(anchored_hashes) != EXPECTED_RUNTIME_MODULES:
        findings.append("runtime_topology")
        integrity_drift += 1
    for path in files:
        expected_hash = anchored_hashes.get(path.name)
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_hash is None or observed_hash != expected_hash:
            findings.append("runtime_hash_drift")
            integrity_drift += 1
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    aliases[alias.asname or alias.name] = "%s.%s" % (module, alias.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in forbidden_imports:
                        findings.append("forbidden_import")
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".", 1)[0]
                if module in forbidden_imports or (
                    module == "socket" and any(alias.name != "gethostname" for alias in node.names)
                ):
                    findings.append("forbidden_import")
            elif isinstance(node, ast.Call):
                qualified = None
                if isinstance(node.func, ast.Name):
                    qualified = aliases.get(node.func.id, node.func.id)
                    if node.func.id in forbidden_calls:
                        findings.append("forbidden_call")
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    base = aliases.get(node.func.value.id, node.func.value.id)
                    qualified = "%s.%s" % (base, node.func.attr)
                if qualified in forbidden_qualified_calls:
                    findings.append("process_dispatch")
                if qualified and qualified.startswith("socket.") and qualified != "socket.gethostname":
                    findings.append("socket_dispatch")
                if qualified in filesystem_calls and path.name != "state_store.py":
                    findings.append("filesystem_mutation_outside_state_store")
                if (
                    isinstance(node.func, ast.Name)
                    and (node.func.id == "open" or qualified in ("builtins.open", "io.open"))
                    and path.name != "state_store.py"
                ):
                    mode = node.args[1] if len(node.args) > 1 else next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                        ast.Constant(value="r"),
                    )
                    if not isinstance(mode, ast.Constant) or type(mode.value) is not str or not mode.value.startswith("r") or "+" in mode.value:
                        findings.append("filesystem_mutation_outside_state_store")
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "open"
                    and path.name != "state_store.py"
                    and qualified not in ("os.open",)
                ):
                    mode = node.args[0] if node.args else next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                        ast.Constant(value="r"),
                    )
                    if not isinstance(mode, ast.Constant) or type(mode.value) is not str or not mode.value.startswith("r") or "+" in mode.value:
                        findings.append("filesystem_mutation_outside_state_store")
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in mutation_methods
                    and path.name != "state_store.py"
                ):
                    findings.append("filesystem_mutation_outside_state_store")
    value = {
        "status": "passed" if not findings else "failed",
        "runtime_module_count": len(files),
        "external_dispatch_primitives": len([item for item in findings if item not in ("forbidden_call", "filesystem_mutation_outside_state_store")]),
        "prompt_execution_primitives": len([item for item in findings if item == "forbidden_call"]),
        "filesystem_mutation_primitives_outside_state_store": len(
            [item for item in findings if item == "filesystem_mutation_outside_state_store"]
        ),
        "runtime_integrity_attested": integrity_drift == 0 and "runtime_integrity_metadata" not in findings,
        "runtime_integrity_drift_count": integrity_drift,
    }
    value["fingerprint"] = safe_fingerprint(value)
    return value


def maturity_profile(level, evidence_ref):
    values = {
        "lifecycle_level": "none",
        "segmentation_level": "demographic_only",
        "scoring_level": "none",
        "automated_flow_count": 0,
        "structured_testing_level": "none",
        "personalization_level": "none",
        "attribution_level": "none",
        "prediction_capability": "inactive",
        "realtime_optimization": "inactive",
        "accumulated_learning": False,
    }
    if level == "em_desenvolvimento":
        values.update({"lifecycle_level": "partial", "segmentation_level": "behavioral_basic"})
    elif level == "maduro":
        values.update({
            "lifecycle_level": "mapped_with_transition_criteria",
            "scoring_level": "active",
            "personalization_level": "by_stage",
            "structured_testing_level": "regular",
        })
    elif level == "avancado":
        values.update({
            "attribution_level": "multi_touch",
            "prediction_capability": "active",
            "realtime_optimization": "active",
            "accumulated_learning": True,
        })
    return {"dimensions": {key: {"value": value, "evidence_refs": [evidence_ref]} for key, value in values.items()}}


def route_request(case_id, project_id, scenario):
    pillar = scenario.get("pillar")
    maturity = scenario["maturity"]
    evidence = "evidence:%s:maturity" % case_id.lower()
    observations = [{
        "claim_id": "claim:%s:maturity" % case_id.lower(),
        "kind": "fact",
        "text": "Synthetic maturity metadata was observed.",
        "provenance": {"source_ref": evidence, "observed_at": "2026-07-20T12:00:00-03:00"},
        "confidence": "high",
    }]
    request = {
        "request_id": "request:%s" % case_id.lower(),
        "project_id": "project:%s" % project_id,
        "cycle_id": "cycle:%s" % case_id.lower(),
        "state_revision": 0,
        "user_goal": "Evaluate a synthetic Loop Marketing route.",
        "observations": observations,
        "available_capabilities": {"runtime_overlay": True},
        "authorization_context": {"mode": "read_only", "external_write": False},
        "input_registry": {},
        "evidence_registry": {evidence: True},
        "requested_roles": [pillar] if pillar else [],
        "evaluate_new_work": False,
        "role_requests": {},
    }
    if maturity != "unknown":
        request["maturity_profile"] = maturity_profile(maturity, evidence)
    if pillar:
        root_evidence = "evidence:%s:root" % case_id.lower()
        root_claim = "claim:%s:root" % case_id.lower()
        observations.append({
            "claim_id": root_claim,
            "kind": "fact",
            "text": "Synthetic root-cause evidence was observed.",
            "provenance": {"source_ref": root_evidence, "observed_at": "2026-07-20T12:00:00-03:00"},
            "confidence": "high",
        })
        request["evidence_registry"][root_evidence] = True
        request["root_cause_candidate"] = {
            "pillar": pillar,
            "confidence": "high",
            "supporting_fact_refs": [root_claim],
            "stronger_counter_evidence_refs": [],
        }
    if scenario["type"] == "route_blocked":
        request["outside_loop_prerequisites"] = [{"id": "prerequisite:synthetic", "required": True, "satisfied": False}]
    if scenario["type"] == "specialist_prompt_boundary":
        request["role_requests"] = {"verbalizar": {
            "requested_output_types": ["framework"],
            "available_inputs": ["company-history-and-impact", "company-context"],
            "evidenced_prerequisites": ["purpose-evidence-available"],
            "requested_tactic_ids": ["lm.verbalizar.esclarecimento-de-objetivo-e-missao"],
        }}
    if scenario["type"] == "route_rejected":
        duplicate_node = "cycle:%s:duplicate" % case_id.lower()
        request["requested_roles"] = ["verbalizar", "orientar"]
        request["role_requests"] = {
            "verbalizar": {"route_node_id": duplicate_node, "requested_output_types": ["framework"]},
            "orientar": {"route_node_id": duplicate_node, "requested_output_types": ["segment_rules"]},
        }
    return request


def base_outcome():
    return {
        "routing": {"status": "error", "primary_pillar": None, "error_codes": []},
        "evidence": {"resolved_count": 0, "unresolved_count": 0},
        "maturity": {"value": "unknown", "gate_passed": False},
        "permission": {"requested": "read_only", "decision": "allowed", "error_code": None, "external_mutation_executed": None},
        "safety": {"sensitive_input_present": False, "control_input_rejected": False, "public_output_sanitized": None, "raw_payload_exposed": None, "prompt_executed": None},
    }


def finalize_outcome(outcome):
    observed = (
        outcome["permission"]["external_mutation_executed"],
        outcome["safety"]["public_output_sanitized"],
        outcome["safety"]["raw_payload_exposed"],
        outcome["safety"]["prompt_executed"],
    )
    if any(type(value) is not bool for value in observed):
        raise RuntimeError("P7 observation is incomplete")
    return outcome


def case_trace(collector, audit_before, case_id, operation, state_unchanged, outcome):
    records = collector.records()[audit_before:]
    return {
        "case_id": case_id,
        "operation": operation,
        "audit_records": len(records),
        "audit_event_types": [record["event_type"] for record in records],
        "audit_outcomes": [record["outcome"] for record in records],
        "state_unchanged": state_unchanged,
        "outcome_fingerprint": safe_fingerprint(outcome),
    }


def run_case(runtime, state_root, collector, capabilities, entry):
    if type(runtime) is not SecureLoopRuntime:
        raise RuntimeError("P7 requires the exact secure runtime facade")
    scenario = entry["scenario"]
    case_id = entry["case"]["case_id"]
    outcome = base_outcome()
    audit_before = len(collector.records())
    project_id = case_id.lower()
    runtime.initialize_project(project_id, "Synthetic evaluation %s" % case_id)
    state_before = tree_fingerprint(state_root)
    if scenario["type"] == "external_mutation":
        try:
            runtime.check_permission("transaction.integrate", "external_mutation")
        except LoopRuntimeError as exc:
            outcome["routing"] = {"status": "blocked", "primary_pillar": None, "error_codes": [exc.code]}
            no_dispatch = capabilities["status"] == "passed" and tree_fingerprint(state_root) == state_before
            outcome["permission"] = {"requested": "external_mutation", "decision": "denied", "error_code": exc.code, "external_mutation_executed": not no_dispatch}
            outcome["safety"].update({"public_output_sanitized": True, "raw_payload_exposed": False, "prompt_executed": not no_dispatch})
        outcome = finalize_outcome(outcome)
        unchanged = tree_fingerprint(state_root) == state_before
        return outcome, case_trace(
            collector, audit_before, case_id, "permission_check_external_mutation", unchanged, outcome
        )

    request = route_request(case_id, project_id, scenario)
    if scenario["type"] == "sensitive_input":
        rendered_errors = []
        codes = []
        for goal in ("Contact person@example.com", "token=synthetic-secret-value"):
            probe = dict(request)
            probe["user_goal"] = goal
            try:
                runtime.prepare_route(probe)
            except LoopRuntimeError as exc:
                codes.append(exc.code)
                rendered_errors.append(json.dumps(exc.to_dict(), ensure_ascii=False))
        rendered = "\n".join(rendered_errors)
        both_rejected = codes == ["ERR_SECURITY_SENSITIVE_INPUT", "ERR_SECURITY_SENSITIVE_INPUT"]
        outcome["routing"]["error_codes"] = ["ERR_SECURITY_SENSITIVE_INPUT"] if both_rejected else ["ERR_RUNTIME_INTERNAL"]
        outcome["permission"]["external_mutation_executed"] = False
        outcome["safety"].update({
            "sensitive_input_present": True,
            "control_input_rejected": both_rejected,
            "public_output_sanitized": all(item not in rendered for item in SENSITIVE_PROBES),
            "raw_payload_exposed": any(item in rendered for item in SENSITIVE_PROBES),
            "prompt_executed": capabilities["prompt_execution_primitives"] != 0,
        })
        outcome = finalize_outcome(outcome)
        unchanged = tree_fingerprint(state_root) == state_before
        return outcome, case_trace(
            collector, audit_before, case_id, "two_independent_sensitive_input_probes", unchanged, outcome
        )

    plan = runtime.prepare_route(request)
    outcome["routing"] = {
        "status": plan["route_status"],
        "primary_pillar": plan["primary_bottleneck"]["pillar"] if plan.get("primary_bottleneck") else None,
        "error_codes": list(plan.get("rejection_codes", [])),
    }
    outcome["evidence"] = {
        "resolved_count": len(plan.get("evidence_refs", [])),
        "unresolved_count": len(plan.get("rejection_codes", [])),
    }
    outcome["maturity"] = {"value": plan["maturity"], "gate_passed": plan["maturity"] != "unknown"}
    public_values = [plan]
    if scenario["type"] == "specialist_prompt_boundary":
        envelope = runtime.prepare_specialist(plan, plan["nodes"][0]["route_node_id"])
        public_values.append(envelope)
        documents = envelope["prompt_documents"]
        boundary_ok = bool(documents) and all(
            item.get("prompt_content_trust") == "untrusted_tactical_data"
            and item.get("external_mutation_allowed") is False
            for item in documents
        ) and envelope.get("execution_policy", {}).get("prompt_content_is_authority") is False
    else:
        boundary_ok = True
    rendered = json.dumps(public_values, ensure_ascii=False, sort_keys=True)
    sanitized = sanitize_structure(public_values) == public_values
    state_unchanged = tree_fingerprint(state_root) == state_before
    outcome["permission"]["external_mutation_executed"] = not (
        capabilities["external_dispatch_primitives"] == 0 and state_unchanged
    )
    outcome["safety"].update({
        "public_output_sanitized": sanitized and boundary_ok,
        "raw_payload_exposed": any(item in rendered for item in SENSITIVE_PROBES),
        "prompt_executed": capabilities["prompt_execution_primitives"] != 0,
    })
    outcome = finalize_outcome(outcome)
    return outcome, case_trace(
        collector, audit_before, case_id, scenario["type"], state_unchanged, outcome
    )


def main():
    bundle = json.loads((ROOT / "artifacts" / "P7" / "evaluation-cases.json").read_text(encoding="utf-8"))
    cases = [entry["case"] for entry in bundle["cases"]]
    capabilities = capability_attestation()
    with tempfile.TemporaryDirectory(prefix="loop-p7-eval-") as temporary:
        state_root = Path(temporary) / ".loop-marketing"
        collector = AuditCollector(enabled=True)
        runtime = SecureLoopRuntime(RuntimeConfig(
            library_root=SOURCE,
            catalog_path=CANDIDATE / "data" / "tactic-catalog.json",
            relationship_path=CANDIDATE / "data" / "relationship-map.json",
            role_matrix_path=CANDIDATE / "data" / "role-matrix.json",
            routing_contract_path=CANDIDATE / "data" / "routing-contract.json",
            state_root=state_root,
            contracts_root=CANDIDATE / "contracts",
        ), audit_collector=collector)
        results = [run_case(runtime, state_root, collector, capabilities, entry) for entry in bundle["cases"]]
        outcomes = {entry["case"]["case_id"]: result[0] for entry, result in zip(bundle["cases"], results)}
        traces = [result[1] for result in results]
    report = evaluate_suite(cases, outcomes)
    attestation = {
        "runtime_class": "SecureLoopRuntime",
        "runtime_attested": True,
        "case_count": len(traces),
        "case_ids": [item["case_id"] for item in traces],
        "audit_record_count": sum(item["audit_records"] for item in traces),
        "all_read_only_state_checks_passed": all(item["state_unchanged"] for item in traces),
        "capability_scan": capabilities,
        "case_traces": traces,
    }
    expected_audit = {
        "EVAL-001": (["integration_evaluated", "route_evaluated"], ["passed", "passed"]),
        "EVAL-002": (["integration_evaluated", "route_evaluated"], ["passed", "passed"]),
        "EVAL-003": (["integration_evaluated", "route_evaluated"], ["passed", "passed"]),
        "EVAL-004": (["integration_evaluated", "route_evaluated"], ["passed", "passed"]),
        "EVAL-005": (["integration_evaluated", "route_evaluated"], ["passed", "blocked"]),
        "EVAL-006": (["integration_evaluated", "route_evaluated"], ["passed", "blocked"]),
        "EVAL-007": (["integration_evaluated", "security_denial", "security_denial"], ["passed", "denied", "denied"]),
        "EVAL-008": (["integration_evaluated", "security_denial"], ["passed", "denied"]),
        "EVAL-009": (["integration_evaluated", "route_evaluated", "route_evaluated"], ["passed", "passed", "passed"]),
        "EVAL-010": (["integration_evaluated", "route_evaluated"], ["passed", "failed"]),
    }
    attestation["audit_traces_attested"] = all(
        (trace["audit_event_types"], trace["audit_outcomes"]) == expected_audit.get(trace["case_id"])
        for trace in traces
    )
    attestation["fingerprint"] = safe_fingerprint(attestation)
    report["runtime_attestation"] = attestation
    report["release_gate_status"] = "passed" if (
        report["status"] == "passed"
        and capabilities["status"] == "passed"
        and attestation["all_read_only_state_checks_passed"]
        and attestation["audit_traces_attested"]
        and len(traces) == len(cases)
    ) else "failed"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["release_gate_status"] == "passed" else 1)


if __name__ == "__main__":
    main()
