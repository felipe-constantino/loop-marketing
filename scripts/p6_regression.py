#!/usr/bin/env python3
"""Run the closed P6 security regression matrix."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"
SCENARIOS = [
    ("hostile_json_types_and_budgets", "test_security.JsonBoundaryTests.test_rejects_non_json_values_without_invoking_custom_protocols"),
    ("depth_nodes_and_numeric_limits", "test_security.JsonBoundaryTests.test_rejects_non_finite_numbers_cycles_and_every_budget"),
    ("permission_deny_default", "test_security.PermissionGuardTests.test_default_policy_allows_only_declared_local_and_read_operations"),
    ("external_mutation_hard_deny", "test_security.PermissionGuardTests.test_external_mutation_is_unconditionally_denied"),
    ("recursive_redaction", "test_security.SanitizationTests.test_key_and_pattern_redaction_in_nested_telemetry"),
    ("redaction_idempotence", "test_security.SanitizationTests.test_message_redaction_is_deterministic_and_idempotent"),
    ("safe_error", "test_security.SanitizationTests.test_safe_error_never_exposes_secret_in_message_or_details"),
    ("concurrent_determinism", "test_security.SanitizationTests.test_thread_safety_and_determinism_under_shared_input"),
    ("sensitive_payload_reject", "test_secure_runtime.SecureRuntimeTests.test_sensitive_control_payload_is_rejected_without_echo"),
    ("read_only_no_repair", "test_secure_runtime.SecureRuntimeTests.test_resolve_initialize_and_read_use_closed_permissions"),
    ("no_orchestrator_bypass", "test_secure_runtime.SecureRuntimeTests.test_wrapped_orchestrator_is_not_publicly_exposed"),
    ("strict_cli_input", "test_secure_runtime.SecureRuntimeTests.test_cli_parser_rejects_duplicates_oversize_and_symlinks"),
    ("bounded_cli_output", "test_secure_runtime.SecureRuntimeTests.test_cli_stdin_remains_open_and_output_is_bounded"),
    ("safe_unknown_failure", "test_secure_runtime.SecureRuntimeTests.test_secure_cli_unknown_failure_has_no_trace_or_secret"),
    ("canonical_prompt_hash_drift", "test_catalog_router.CatalogTests.test_hash_drift_rejects_progressive_loading"),
    ("state_symlink_boundary", "test_state_store.ProjectStateStoreTests.test_symlink_state_root_is_rejected_before_any_write")
]


def main():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(CANDIDATE / "src"), str(CANDIDATE / "tests")])
    results = []
    for scenario, test in SCENARIOS:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "-q", test],
            cwd=str(ROOT), env=env, text=True, capture_output=True, check=False,
        )
        results.append({"scenario": scenario, "test": test, "status": "PASS" if completed.returncode == 0 else "FAIL"})
    failed = [item for item in results if item["status"] != "PASS"]
    output = {"status": "PASS" if not failed else "FAIL", "scenario_count": len(results), "passed": len(results) - len(failed), "failed": len(failed), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
