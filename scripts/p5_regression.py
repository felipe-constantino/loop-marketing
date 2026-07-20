#!/usr/bin/env python3
"""Run independent negative P5 regression scenarios by contract boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate" / "loop-marketing-v2"

SCENARIOS = [
    ("catalog_hash_drift", "test_catalog_router.CatalogTests.test_hash_drift_rejects_progressive_loading"),
    ("catalog_three_tactics", "test_catalog_router.CatalogTests.test_zero_one_two_and_rejected_three_cardinality"),
    ("unknown_maturity_tactic_request", "test_catalog_router.CatalogTests.test_unknown_maturity_falls_back_to_base_method"),
    ("unsourced_fact", "test_catalog_router.RouterTests.test_unsourced_fact_and_unrationalized_hypothesis_reject"),
    ("outside_loop_prerequisite", "test_catalog_router.RouterTests.test_outside_loop_prerequisite_has_highest_precedence"),
    ("parallel_write_collision", "test_catalog_router.RouterTests.test_parallel_write_collision_and_revision_mismatch_reject"),
    ("handoff_route_binding", "test_orchestrator_e2e.OrchestratorEndToEndTests.test_route_specialist_and_handoff_are_read_only_and_contract_bound"),
    ("closed_handoff_extension", "test_validation_adapters.ContractValidatorTests.test_schema_subset_rejects_closed_object_extensions"),
    ("unauthorized_event", "test_validation_adapters.ContractValidatorTests.test_event_hash_revision_and_authority_fail_closed_independently"),
    ("experiment_evidence_registry_bypass", "test_validation_adapters.ContractValidatorTests.test_strict_registry_binds_experiment_evidence_and_fact_sources"),
    ("fact_source_event_binding_bypass", "test_validation_adapters.ContractValidatorTests.test_strict_registry_binds_experiment_evidence_and_fact_sources"),
    ("tampered_nested_event", "test_validation_adapters.ContractValidatorTests.test_transaction_detects_nested_event_tamper_even_with_rehashed_record"),
    ("stale_cas", "test_state_store.ProjectStateStoreTests.test_stale_revision_or_head_is_rejected_before_write"),
    ("partial_batch_retry", "test_state_store.ProjectStateStoreTests.test_partial_batch_retry_is_idempotency_conflict"),
    ("tampered_exact_replay", "test_state_store.ProjectStateStoreTests.test_tampered_replay_with_stale_claimed_hash_is_conflict"),
    ("symlink_state_boundary", "test_state_store.ProjectStateStoreTests.test_symlink_state_root_is_rejected_before_any_write"),
    ("abandoned_process_lock", "test_state_store.ProjectStateStoreTests.test_abandoned_process_lock_is_proven_reported_and_recovered"),
    ("crash_before_commit", "test_state_store.ProjectStateStoreTests.test_simulated_crash_before_commit_point_preserves_old_ledger"),
    ("crash_after_commit", "test_state_store.ProjectStateStoreTests.test_simulated_crash_after_commit_point_rebuilds_stale_snapshot"),
]


def run(command, cwd, env=None):
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    baseline = run([sys.executable, str(ROOT / "scripts" / "p5_validate.py")], ROOT)
    try:
        baseline_json = json.loads(baseline.stdout)
    except json.JSONDecodeError:
        baseline_json = {"status": "FAIL"}
    if baseline.returncode != 0 or baseline_json.get("status") != "PASS":
        print(json.dumps({
            "status": "FAIL",
            "baseline": "FAIL",
            "errors": ["P5 baseline validation failed before negative regression"],
        }, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(CANDIDATE / "src"),
        str(CANDIDATE / "tests"),
    ])
    results = []
    for name, test_name in SCENARIOS:
        completed = run([sys.executable, "-m", "unittest", "-q", test_name], ROOT, env)
        results.append({
            "scenario": name,
            "test": test_name,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
        })
    failed = [item for item in results if item["status"] != "PASS"]
    output = {
        "status": "PASS" if not failed else "FAIL",
        "baseline": "PASS",
        "scenario_count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
