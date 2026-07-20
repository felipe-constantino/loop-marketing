#!/usr/bin/env python3
"""Negative regression suite for P4 contracts using isolated temporary copies."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "p4_validate.py"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_manifest(case_root: Path, relative: str) -> None:
    manifest_path = case_root / "artifacts" / "P4" / "integration-manifest.json"
    manifest = load(manifest_path)
    found = False
    for section in ("source_contracts", "workstreams", "official_artifacts"):
        for entry in manifest[section]:
            if entry["path"] == relative:
                entry["sha256"] = sha256_file(case_root / relative)
                found = True
    if not found:
        raise AssertionError(f"manifest entry not found: {relative}")
    dump(manifest_path, manifest)


def mutate_json(case_root: Path, relative: str, mutator) -> None:
    path = case_root / relative
    value = load(path)
    mutator(value)
    dump(path, value)
    refresh_manifest(case_root, relative)


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    baseline = run_validator(ROOT)
    if baseline.returncode != 0:
        raise SystemExit(f"P4 baseline failed before regression:\n{baseline.stdout}\n{baseline.stderr}")

    scenarios = []

    def scenario(name, expected_text, mutate):
        scenarios.append((name, expected_text, mutate))

    scenario(
        "state_namespace_drift", "canonical state namespace drift",
        lambda root: mutate_json(root, "artifacts/P4/state-schema.json", lambda v: v["x-loop-contract"].update({"namespace": ".claude/"})),
    )
    scenario(
        "state_schema_open", "state/event schema is not closed",
        lambda root: mutate_json(root, "artifacts/P4/state-schema.json", lambda v: v.update({"additionalProperties": True})),
    )
    scenario(
        "state_revision_rule_reverts_to_event", "state revision rule is inconsistent with transaction batches",
        lambda root: mutate_json(root, "artifacts/P4/state-schema.json", lambda v: v["x-loop-contract"].update({"revision_rule": "Each event advances one revision."})),
    )
    scenario(
        "handoff_required_field_removed", "handoff required fields drift from P2",
        lambda root: mutate_json(root, "artifacts/P4/handoff-schema.json", lambda v: v["required"].pop()),
    )
    scenario(
        "handoff_schema_open", "handoff schema is not closed",
        lambda root: mutate_json(root, "artifacts/P4/handoff-schema.json", lambda v: v.update({"additionalProperties": True})),
    )
    scenario(
        "handoff_property_extra", "handoff properties drift from P2",
        lambda root: mutate_json(root, "artifacts/P4/handoff-schema.json", lambda v: v["properties"].update({"hidden_payload": {"type": "object"}})),
    )

    def invent_event(value: dict) -> None:
        value["$defs"]["event"]["properties"]["event_type"]["enum"].append("cycle_closed")
        value["x-loop-contract"]["authority_by_role"]["loop_planning"].append("cycle_closed")
        value["x-loop-contract"]["canonical_event_type_count"] = 34

    scenario(
        "invented_event_authority", "event authority/types drift from the 33 P2 event types",
        lambda root: mutate_json(root, "artifacts/P4/event-schema.json", invent_event),
    )
    scenario(
        "event_authority_owner_swap", "event role authority map drift",
        lambda root: mutate_json(root, "artifacts/P4/event-schema.json", lambda v: v["x-loop-contract"]["authority_by_role"]["verbalizar"].append("maturity_classified")),
    )
    scenario(
        "experiment_transition_removed", "experiment transition rules drift from P2",
        lambda root: mutate_json(root, "artifacts/P4/event-schema.json", lambda v: v["x-loop-contract"]["experiment_state_machine"].pop("invalidate")),
    )

    def drop_negative_fixture(value: dict) -> None:
        value["event_cases"] = [item for item in value["event_cases"] if item["case_id"] != "EVENT-NEG-EXPERIMENT-EVIDENCE"]

    scenario(
        "negative_coverage_removed", "negative fixture coverage missing",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", drop_negative_fixture),
    )

    scenario(
        "transaction_replay_coverage_removed", "transaction replay/idempotency sequence coverage is missing",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", lambda v: v.update({"transaction_sequence_cases": []})),
    )

    def tamper_claimed_replay(value: dict) -> None:
        item = next(case for case in value["transaction_sequence_cases"] if case["case_id"] == "TXSEQ-POS-IDEMPOTENT-REPLAY")
        item["transactions"][1]["events"][0]["payload"]["data"]["maturity"] = "maduro"

    scenario(
        "claimed_hash_cannot_hide_tampered_replay", "TXSEQ-POS-IDEMPOTENT-REPLAY",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", tamper_claimed_replay),
    )

    def tamper_claimed_event_hash(value: dict) -> None:
        item = next(case for case in value["event_sequence_cases"] if case["case_id"] == "SEQ-POS-IDEMPOTENT-REPLAY")
        item["events"][1]["event_hash"] = "f" * 64

    scenario(
        "claimed_event_hash_cannot_bypass_replay", "SEQ-POS-IDEMPOTENT-REPLAY",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", tamper_claimed_event_hash),
    )
    scenario(
        "alias_semantics_drift", "alias drift",
        lambda root: mutate_json(root, "artifacts/P4/event-schema.json", lambda v: v["x-loop-contract"]["command_contract"]["loop.orientar"].update({"legacy_alias": "/orientar-v2-agent"})),
    )

    def tamper_transaction(value: dict) -> None:
        tx = next(item for item in value["transaction_cases"] if item["case_id"] == "TX-POS-SINGLE")
        tx["instance"]["events"][0]["payload"]["data"]["maturity"] = "maduro"

    scenario(
        "accepted_transaction_tampered", "TX-POS-SINGLE",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", tamper_transaction),
    )

    def stale_migration_confirmation(value: dict) -> None:
        item = next(case for case in value["migration_cases"] if case["case_id"] == "MIG-POS-CONFIRMED-PROMOTION")
        item["input"]["confirmation"]["report_sha256"] = "0" * 64

    scenario(
        "migration_confirmation_not_bound", "MIG-POS-CONFIRMED-PROMOTION",
        lambda root: mutate_json(root, "artifacts/P4/compatibility-fixtures.json", stale_migration_confirmation),
    )

    def remove_rollback_marker(case_root: Path) -> None:
        relative = "artifacts/P4/migration-contract.md"
        path = case_root / relative
        text = re.sub("rollback", "reversion", path.read_text(encoding="utf-8"), flags=re.IGNORECASE)
        path.write_text(text, encoding="utf-8")
        refresh_manifest(case_root, relative)

    scenario("migration_rollback_contract_removed", "missing marker: Rollback", remove_rollback_marker)

    def remove_catalog_item(value: dict) -> None:
        value["tactics"].pop()

    scenario(
        "canonical_catalog_incomplete", "P3 catalog no longer contains exactly 100 unique tactics",
        lambda root: mutate_json(root, "artifacts/P3/tactic-catalog.json", remove_catalog_item),
    )

    def drift_domain_owner(value: dict) -> None:
        value["x-loop-contract"]["decision_domain_owner"]["message_and_copy"] = "orientar"

    scenario(
        "handoff_domain_owner_drift", "HO-POS-001",
        lambda root: mutate_json(root, "artifacts/P4/handoff-schema.json", drift_domain_owner),
    )

    def unsealed_change(case_root: Path) -> None:
        path = case_root / "artifacts" / "P4" / "state-event-contract.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nunsealed\n", encoding="utf-8")

    scenario("manifest_detects_unsealed_change", "manifest hash drift", unsealed_change)

    results = []
    with tempfile.TemporaryDirectory(prefix="loop-p4-regression-") as tmp:
        tmp_root = Path(tmp)
        base = tmp_root / "base"
        shutil.copytree(ROOT / "artifacts" / "P2", base / "artifacts" / "P2")
        shutil.copytree(ROOT / "artifacts" / "P3", base / "artifacts" / "P3")
        shutil.copytree(ROOT / "artifacts" / "P4", base / "artifacts" / "P4")
        shutil.copytree(ROOT / "scripts", base / "scripts")
        for index, (name, expected_text, mutate) in enumerate(scenarios, start=1):
            case_root = tmp_root / f"case-{index:02d}"
            shutil.copytree(base, case_root)
            mutate(case_root)
            result = run_validator(case_root)
            combined = result.stdout + result.stderr
            passed = result.returncode != 0 and expected_text in combined
            results.append({"name": name, "status": "PASS" if passed else "FAIL", "expected_text": expected_text})
            if not passed:
                print(json.dumps({"scenario": name, "stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False, indent=2))

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
