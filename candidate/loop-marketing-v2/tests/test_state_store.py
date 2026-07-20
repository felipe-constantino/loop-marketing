from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.state_store import GENESIS, ProjectStateStore
from loop_marketing_runtime.validation import ContractValidator


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def canonical_hash(value: Dict[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim() -> Dict[str, Any]:
    return {
        "claim_id": "claim:test",
        "kind": "fact",
        "text": "The test observation is backed by local evidence.",
        "provenance": {
            "source_ref": "evidence:test",
            "observed_at": "2026-07-17T10:00:00Z",
        },
        "confidence": "high",
    }


class FaultingStateStore(ProjectStateStore):
    def __init__(self, *args: Any, fail_stage: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_stage = fail_stage

    def _fault_hook(self, stage: str) -> None:
        if stage == self.fail_stage:
            raise OSError("simulated crash at %s" % stage)


class ProjectStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.config = RuntimeConfig(
            library_root=PACKAGE_ROOT,
            catalog_path=PACKAGE_ROOT / "data" / "tactic-catalog.json",
            relationship_path=PACKAGE_ROOT / "data" / "relationship-map.json",
            role_matrix_path=PACKAGE_ROOT / "data" / "role-matrix.json",
            routing_contract_path=PACKAGE_ROOT / "data" / "routing-contract.json",
            state_root=self.temp_root / ".loop-marketing",
            contracts_root=PACKAGE_ROOT / "contracts",
        )
        self.validator = ContractValidator(self.config)
        self.store = ProjectStateStore(self.config, self.validator)
        self.project_id = "project-one"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def initialize(self, store: Optional[ProjectStateStore] = None) -> Dict[str, Any]:
        return (store or self.store).initialize_project(self.project_id, "Project One")

    def make_record(
        self,
        snapshot: Dict[str, Any],
        suffix: str,
        event_specs: Sequence[Tuple[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        revision = snapshot["state_revision"]
        transaction_id = "tx_%s" % suffix
        previous_event_hash = snapshot["event_log"]["head_event_hash"] or GENESIS
        sequence = snapshot["event_log"]["last_event_sequence"]
        events = []
        for index, (event_type, data) in enumerate(event_specs, 1):
            sequence += 1
            event = {
                "schema_version": "2.0",
                "event_id": "evt_%s_%d" % (suffix, index),
                "event_type": event_type,
                "project_ref": "project:%s" % self.project_id,
                "cycle_id": "cycle:test",
                "actor_role": "loop_planning",
                "command_id": "loop.planning",
                "occurred_at": "2026-07-17T10:00:%02dZ" % index,
                "state_revision": revision,
                "resulting_state_revision": revision + 1,
                "event_sequence": sequence,
                "transaction_id": transaction_id,
                "effect": "integration",
                "idempotency_key": "idem_event_%s_%d" % (suffix, index),
                "previous_event_hash": previous_event_hash,
                "event_hash": "0" * 64,
                "evidence_refs": ["evidence:test"],
                "payload": {
                    "payload_version": "1.0",
                    "claims": [claim()],
                    "data": data,
                },
            }
            event["event_hash"] = canonical_hash(event, "event_hash")
            previous_event_hash = event["event_hash"]
            events.append(event)
        record = {
            "schema_version": "2.0",
            "record_type": "event_transaction",
            "transaction_id": transaction_id,
            "project_ref": "project:%s" % self.project_id,
            "expected_state_revision": revision,
            "resulting_state_revision": revision + 1,
            "committed_at": "2026-07-17T10:01:00Z",
            "integrated_by_role": "loop_planning",
            "reducer_version": "2.0.0",
            "idempotency_key": "idem_transaction_%s" % suffix,
            "previous_record_hash": snapshot["event_log"]["head_record_hash"] or GENESIS,
            "record_hash": "0" * 64,
            "events": events,
        }
        record["record_hash"] = canonical_hash(record, "record_hash")
        return record

    def commit_record(
        self,
        store: ProjectStateStore,
        snapshot: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        return store.commit(
            self.project_id,
            record,
            snapshot["state_revision"],
            snapshot["event_log"]["head_event_hash"] or GENESIS,
        )

    def assert_error(self, code: str, callable_: Any, *args: Any, **kwargs: Any) -> LoopRuntimeError:
        with self.assertRaises(LoopRuntimeError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_initialize_creates_canonical_genesis_and_secure_modes(self) -> None:
        snapshot = self.initialize()
        self.assertEqual(snapshot["state_revision"], 0)
        self.assertIsNone(snapshot["derived_from_revision"])
        self.assertEqual(snapshot["project_ref"], "project:project-one")
        self.assertEqual(snapshot["state"]["maturity"], "unknown")
        self.assertEqual(snapshot["event_log"]["committed_transaction_count"], 0)
        self.assertEqual(self.store.load(self.project_id), snapshot)

        project = self.config.state_root / "state" / "projects" / self.project_id
        for directory in (
            self.config.state_root,
            self.config.state_root / "state",
            self.config.state_root / "state" / "projects",
            project,
            project / "snapshots",
        ):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for file_path in (
            project / "events.jsonl",
            project / "identity.json",
            project / "project.json",
            project / "snapshots" / "latest.json",
        ):
            self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)

    def test_single_and_multi_event_commits_advance_one_revision_per_batch(self) -> None:
        genesis = self.initialize()
        first = self.make_record(genesis, "single_001", [("maturity_classified", {"maturity": "maduro"})])
        result_one = self.commit_record(self.store, genesis, first)
        self.assertEqual(result_one["status"], "committed")
        self.assertEqual(result_one["state_revision"], 1)
        prefix = (self.config.state_root / "state" / "projects" / self.project_id / "events.jsonl").read_bytes()

        revision_one = self.store.load(self.project_id)
        second = self.make_record(
            revision_one,
            "batch_002",
            [
                ("pillar_scores_recorded", {"pillar_score_refs": ["score:one"]}),
                ("route_plan_issued", {"route_status": "needs_evidence"}),
            ],
        )
        result_two = self.commit_record(self.store, revision_one, second)
        self.assertEqual(result_two["state_revision"], 2)
        loaded = self.store.load(self.project_id)
        self.assertEqual(loaded["state_revision"], 2)
        self.assertEqual(loaded["event_log"]["applied_event_count"], 3)
        self.assertEqual(loaded["event_log"]["last_event_sequence"], 3)
        self.assertEqual(loaded["event_log"]["committed_transaction_count"], 2)
        ledger = (self.config.state_root / "state" / "projects" / self.project_id / "events.jsonl").read_bytes()
        self.assertTrue(ledger.startswith(prefix))
        self.assertEqual(len(ledger.splitlines()), 2)

    def test_exact_replay_is_noop_without_new_ledger_bytes(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "replay_001", [("maturity_classified", {"maturity": "maduro"})])
        committed = self.commit_record(self.store, genesis, record)
        ledger = self.config.state_root / "state" / "projects" / self.project_id / "events.jsonl"
        before = ledger.read_bytes()
        replayed = self.commit_record(self.store, genesis, copy.deepcopy(record))
        self.assertEqual(replayed["status"], "noop")
        self.assertEqual(replayed["transaction_id"], committed["transaction_id"])
        self.assertEqual(replayed["state_revision"], 1)
        self.assertEqual(ledger.read_bytes(), before)

    def test_tampered_replay_with_stale_claimed_hash_is_conflict(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "tamper_001", [("maturity_classified", {"maturity": "maduro"})])
        self.commit_record(self.store, genesis, record)
        tampered = copy.deepcopy(record)
        tampered["events"][0]["payload"]["data"]["maturity"] = "nascente"
        self.assert_error(
            "LM-EVENT-IDEMPOTENCY-CONFLICT",
            self.commit_record,
            self.store,
            genesis,
            tampered,
        )

    def test_partial_batch_retry_is_idempotency_conflict(self) -> None:
        genesis = self.initialize()
        batch = self.make_record(
            genesis,
            "partial_001",
            [
                ("maturity_classified", {"maturity": "maduro"}),
                ("pillar_scores_recorded", {"pillar_score_refs": ["score:one"]}),
            ],
        )
        self.commit_record(self.store, genesis, batch)
        current = self.store.load(self.project_id)
        retry = self.make_record(
            current,
            "partial_002",
            [("maturity_classified", {"maturity": "maduro"})],
        )
        retry["events"][0]["event_id"] = batch["events"][0]["event_id"]
        retry["events"][0]["idempotency_key"] = batch["events"][0]["idempotency_key"]
        retry["events"][0]["event_hash"] = canonical_hash(retry["events"][0], "event_hash")
        retry["record_hash"] = canonical_hash(retry, "record_hash")
        self.assert_error(
            "LM-EVENT-IDEMPOTENCY-CONFLICT",
            self.commit_record,
            self.store,
            current,
            retry,
        )

    def test_stale_revision_or_head_is_rejected_before_write(self) -> None:
        genesis = self.initialize()
        first = self.make_record(genesis, "cas_001", [("maturity_classified", {"maturity": "maduro"})])
        self.commit_record(self.store, genesis, first)
        current = self.store.load(self.project_id)
        second = self.make_record(current, "cas_002", [("pillar_scores_recorded", {"pillar_score_refs": ["score:two"]})])
        ledger = self.config.state_root / "state" / "projects" / self.project_id / "events.jsonl"
        before = ledger.read_bytes()
        self.assert_error("ERR_STATE_REVISION_STALE", self.store.commit, self.project_id, second, 0, GENESIS)
        self.assert_error("ERR_STATE_REVISION_STALE", self.store.commit, self.project_id, second, 1, "0" * 64)
        self.assertEqual(ledger.read_bytes(), before)

    def test_broken_event_chain_is_rejected(self) -> None:
        genesis = self.initialize()
        first = self.make_record(genesis, "chain_001", [("maturity_classified", {"maturity": "maduro"})])
        self.commit_record(self.store, genesis, first)
        current = self.store.load(self.project_id)
        broken = self.make_record(current, "chain_002", [("pillar_scores_recorded", {"pillar_score_refs": ["score:two"]})])
        broken["events"][0]["previous_event_hash"] = "0" * 64
        broken["events"][0]["event_hash"] = canonical_hash(broken["events"][0], "event_hash")
        broken["record_hash"] = canonical_hash(broken, "record_hash")
        self.assert_error(
            "LM-EVENT-CHAIN-BROKEN",
            self.commit_record,
            self.store,
            current,
            broken,
        )

    def test_live_lock_contention_does_not_remove_foreign_lock(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "lock_001", [("maturity_classified", {"maturity": "maduro"})])
        project_dir = self.config.state_root / "state" / "projects" / self.project_id
        lock_id = self.store._acquire_lock(self.project_id, project_dir, 0)
        try:
            lock_path = project_dir / ".write.lock"
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
            self.assert_error("ERR_LOCK_HELD", self.commit_record, self.store, genesis, record)
            self.assertTrue(lock_path.exists())
            self.assertEqual(json.loads(lock_path.read_text())["lock_id"], lock_id)
        finally:
            self.store._release_lock(project_dir, lock_id)

    def test_abandoned_process_lock_is_proven_reported_and_recovered(self) -> None:
        genesis = self.initialize()
        child = r'''
import sys
from pathlib import Path
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.state_store import ProjectStateStore
from loop_marketing_runtime.validation import ContractValidator
package = Path(sys.argv[1])
state_root = Path(sys.argv[2])
config = RuntimeConfig(
    library_root=package,
    catalog_path=package / "data" / "tactic-catalog.json",
    relationship_path=package / "data" / "relationship-map.json",
    role_matrix_path=package / "data" / "role-matrix.json",
    routing_contract_path=package / "data" / "routing-contract.json",
    state_root=state_root,
    contracts_root=package / "contracts",
)
store = ProjectStateStore(config, ContractValidator(config))
project_dir = state_root / "state" / "projects" / "project-one"
store._acquire_lock("project-one", project_dir, 0)
'''
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-c", child, str(PACKAGE_ROOT), str(self.config.state_root)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        report = self.store.inspect_recovery(self.project_id)
        self.assertEqual("stale_lock_recovery_required", report["status"])
        self.assertEqual("proven_dead_same_host", report["lock_status"])
        self.assertFalse(report["writable"])

        record = self.make_record(genesis, "abandoned_lock", [("maturity_classified", {"maturity": "maduro"})])
        committed = self.commit_record(self.store, genesis, record)
        self.assertEqual("committed", committed["status"])
        project_dir = self.config.state_root / "state" / "projects" / self.project_id
        self.assertFalse((project_dir / ".write.lock").exists())
        recovery_reports = list(project_dir.glob("lock-recovery-*.json"))
        self.assertEqual(1, len(recovery_reports))
        self.assertEqual("stale_lock_recovered", json.loads(recovery_reports[0].read_text())["status"])

    def test_simulated_crash_before_commit_point_preserves_old_ledger(self) -> None:
        store = FaultingStateStore(self.config, self.validator, fail_stage="before_ledger_commit")
        genesis = self.initialize(store)
        record = self.make_record(genesis, "crash_before", [("maturity_classified", {"maturity": "maduro"})])
        error = self.assert_error("ERR_ATOMIC_COMMIT_FAILED", self.commit_record, store, genesis, record)
        self.assertFalse(error.details["ledger_committed"])
        ledger = self.config.state_root / "state" / "projects" / self.project_id / "events.jsonl"
        self.assertEqual(ledger.read_bytes(), b"")
        store.fail_stage = None
        self.assertEqual(store.load(self.project_id)["state_revision"], 0)
        self.assertEqual(list(ledger.parent.glob(".*.tmp.*")), [])

    def test_simulated_crash_after_commit_point_rebuilds_stale_snapshot(self) -> None:
        store = FaultingStateStore(self.config, self.validator, fail_stage="after_ledger_commit")
        genesis = self.initialize(store)
        record = self.make_record(genesis, "crash_after", [("maturity_classified", {"maturity": "maduro"})])
        error = self.assert_error("ERR_ATOMIC_COMMIT_FAILED", self.commit_record, store, genesis, record)
        self.assertTrue(error.details["ledger_committed"])
        latest = self.config.state_root / "state" / "projects" / self.project_id / "snapshots" / "latest.json"
        self.assertEqual(json.loads(latest.read_text())["state_revision"], 0)
        store.fail_stage = None
        recovered = store.load(self.project_id)
        self.assertEqual(recovered["state_revision"], 1)
        self.assertEqual(json.loads(latest.read_text())["state_revision"], 1)

    def test_explicit_stale_snapshot_is_rebuilt_from_ledger(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "rebuild_001", [("maturity_classified", {"maturity": "maduro"})])
        self.commit_record(self.store, genesis, record)
        latest = self.config.state_root / "state" / "projects" / self.project_id / "snapshots" / "latest.json"
        latest.write_text(json.dumps(genesis) + "\n", encoding="utf-8")
        os.chmod(str(latest), 0o600)
        rebuilt = self.store.load(self.project_id)
        self.assertEqual(rebuilt["state_revision"], 1)
        self.assertEqual(rebuilt["state"]["maturity"], "maduro")
        self.assertEqual(json.loads(latest.read_text()), rebuilt)

    def test_missing_derived_caches_rebuild_exact_identity_and_state(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "identity_001", [("maturity_classified", {"maturity": "maduro"})])
        committed = self.commit_record(self.store, genesis, record)["snapshot"]
        project_dir = self.config.state_root / "state" / "projects" / self.project_id
        (project_dir / "project.json").unlink()
        (project_dir / "snapshots" / "latest.json").unlink()
        rebuilt = self.store.load(self.project_id)
        self.assertEqual(committed, rebuilt)
        self.assertEqual("Project One", rebuilt["display_name"])
        self.assertEqual(genesis["created_at"], rebuilt["created_at"])

    def test_snapshot_ahead_of_ledger_is_rejected_as_fabrication(self) -> None:
        genesis = self.initialize()
        project_dir = self.config.state_root / "state" / "projects" / self.project_id
        ahead = copy.deepcopy(genesis)
        ahead["state_revision"] = 1
        latest = project_dir / "snapshots" / "latest.json"
        latest.write_text(json.dumps(ahead) + "\n", encoding="utf-8")
        os.chmod(str(latest), 0o600)
        self.assert_error("ERR_STATE_FABRICATION", self.store.load, self.project_id)
        record = self.make_record(genesis, "ahead_001", [("maturity_classified", {"maturity": "maduro"})])
        self.assert_error(
            "ERR_STATE_FABRICATION",
            self.commit_record,
            self.store,
            genesis,
            record,
        )

    def test_invalid_project_and_symlink_component_are_rejected(self) -> None:
        self.assert_error("ERR_PROJECT_PATH_INVALID", self.store.initialize_project, "../escape", "Escape")
        self.initialize()
        projects = self.config.state_root / "state" / "projects"
        outside = self.temp_root / "outside"
        outside.mkdir()
        marker = outside / "marker.txt"
        marker.write_text("untouched", encoding="utf-8")
        link = projects / "linked-project"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available on this platform")
        self.assert_error("ERR_PROJECT_PATH_INVALID", self.store.initialize_project, "linked-project", "Linked")
        self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")

    def test_symlink_state_root_is_rejected_before_any_write(self) -> None:
        outside = self.temp_root / "outside-state"
        outside.mkdir()
        linked = self.temp_root / "linked-state"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available on this platform")
        linked_config = RuntimeConfig(
            library_root=self.config.library_root,
            catalog_path=self.config.catalog_path,
            relationship_path=self.config.relationship_path,
            role_matrix_path=self.config.role_matrix_path,
            routing_contract_path=self.config.routing_contract_path,
            state_root=linked,
            contracts_root=self.config.contracts_root,
        )
        linked_store = ProjectStateStore(linked_config, self.validator)
        self.assert_error("ERR_PROJECT_PATH_INVALID", linked_store.initialize_project, "linked", "Linked")
        self.assertEqual([], list(outside.iterdir()))

    def test_corrupt_ledger_is_quarantined_and_project_becomes_read_only(self) -> None:
        genesis = self.initialize()
        record = self.make_record(genesis, "corrupt_001", [("maturity_classified", {"maturity": "maduro"})])
        self.commit_record(self.store, genesis, record)
        project_dir = self.config.state_root / "state" / "projects" / self.project_id
        ledger = project_dir / "events.jsonl"
        with ledger.open("ab") as handle:
            handle.write(b'{"partial":')
            handle.flush()
            os.fsync(handle.fileno())
        report = self.store.inspect_recovery(self.project_id)
        self.assertEqual(report["status"], "degraded_read_only")
        self.assertFalse(report["writable"])
        self.assertEqual(report["primary_code"], "LM-EVENT-CHAIN-BROKEN")
        self.assertTrue((self.config.state_root / report["quarantine_paths"][0]).is_file())
        self.assertTrue((project_dir / "recovery-status.json").is_file())
        self.assert_error("ERR_RECOVERY_REQUIRED", self.store.load, self.project_id)


if __name__ == "__main__":
    unittest.main()
