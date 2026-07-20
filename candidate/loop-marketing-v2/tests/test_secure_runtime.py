"""Integration tests for the only facade exposed by the internal release."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.observability import AuditCollector
from loop_marketing_runtime.secure_runtime import SecureLoopRuntime
from loop_marketing_runtime.secure_adapters import SecureHostAdapter
from loop_marketing_runtime import secure_cli


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = PACKAGE_ROOT.parents[1]
SOURCE_ROOT = CONTROL_ROOT.parent / "loop-marketing"


class SecureRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temporary.name) / ".loop-marketing"
        self.config = RuntimeConfig(
            library_root=SOURCE_ROOT,
            catalog_path=PACKAGE_ROOT / "data" / "tactic-catalog.json",
            relationship_path=PACKAGE_ROOT / "data" / "relationship-map.json",
            role_matrix_path=PACKAGE_ROOT / "data" / "role-matrix.json",
            routing_contract_path=PACKAGE_ROOT / "data" / "routing-contract.json",
            state_root=self.state_root,
            contracts_root=PACKAGE_ROOT / "contracts",
        )
        self.runtime = SecureLoopRuntime(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_resolve_initialize_and_read_use_closed_permissions(self) -> None:
        resolved = self.runtime.resolve_command("/loop-planning-agent")
        self.assertEqual("loop.planning", resolved["command_id"])
        created = self.runtime.initialize_project("secure", "Secure project")
        self.assertEqual(0, created["state_revision"])
        loaded = self.runtime.read_project("secure")
        self.assertEqual(created, loaded)

        derived_cache = self.state_root / "state" / "projects" / "secure" / "project.json"
        derived_cache.unlink()
        self.assertEqual(created, self.runtime.read_project("secure"))
        self.assertFalse(derived_cache.exists(), "read_only replay must not repair derived state")

    def test_sensitive_control_payload_is_rejected_without_echo(self) -> None:
        request = {
            "request_id": "request:secret",
            "project_id": "project:missing",
            "state_revision": 0,
            "user_goal": "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456",
            "observations": [],
            "available_capabilities": {},
            "authorization_context": {},
        }
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime.prepare_route(request)
        self.assertEqual("ERR_SECURITY_SENSITIVE_INPUT", caught.exception.code)
        rendered = json.dumps(caught.exception.to_dict())
        self.assertNotIn("ghp_", rendered)
        self.assertNotIn("Bearer", rendered)
        request["user_goal"] = "token=synthetic-secret-value"
        with self.assertRaises(LoopRuntimeError) as token_only:
            self.runtime.prepare_route(request)
        self.assertEqual("ERR_SECURITY_SENSITIVE_INPUT", token_only.exception.code)
        self.assertNotIn("synthetic-secret-value", json.dumps(token_only.exception.to_dict()))

    def test_external_mutation_permission_is_not_present(self) -> None:
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime._permissions.require("transaction.integrate", "external_mutation")
        self.assertEqual("ERR_EXTERNAL_MUTATION_UNAUTHORIZED", caught.exception.code)
        with self.assertRaises(LoopRuntimeError) as facade_denial:
            self.runtime.check_permission("transaction.integrate", "external_mutation")
        self.assertEqual("ERR_EXTERNAL_MUTATION_UNAUTHORIZED", facade_denial.exception.code)

    def test_runtime_observability_is_connected_and_metadata_only(self) -> None:
        collector = AuditCollector(enabled=True)
        runtime = SecureLoopRuntime(self.config, audit_collector=collector)
        runtime.resolve_command("/verbalizar")
        with self.assertRaises(LoopRuntimeError):
            runtime.check_permission("transaction.integrate", "external_mutation")
        records = collector.records()
        self.assertEqual(2, len(records))
        self.assertEqual("permission_evaluated", records[0]["event_type"])
        self.assertEqual("security_denial", records[1]["event_type"])
        self.assertEqual("denied", records[1]["outcome"])
        rendered = json.dumps(records)
        self.assertNotIn("payload", rendered)
        self.assertNotIn("prompt", rendered)
        self.assertNotIn("transaction.integrate", rendered)

    def test_sensitive_input_denials_emit_metadata_only_audit_records(self) -> None:
        collector = AuditCollector(enabled=True)
        runtime = SecureLoopRuntime(self.config, audit_collector=collector)
        request = {
            "request_id": "request:audit-sensitive",
            "project_id": "project:missing",
            "state_revision": 0,
            "user_goal": "token=synthetic-secret-value",
            "observations": [],
            "available_capabilities": {},
            "authorization_context": {},
        }
        with self.assertRaises(LoopRuntimeError):
            runtime.prepare_route(request)
        records = collector.records()
        self.assertEqual(1, len(records))
        self.assertEqual("security_denial", records[0]["event_type"])
        self.assertEqual("denied", records[0]["outcome"])
        rendered = json.dumps(records)
        self.assertNotIn("synthetic-secret-value", rendered)
        self.assertNotIn("user_goal", rendered)

    def test_secure_host_adapter_accepts_only_secure_facade(self) -> None:
        adapter = SecureHostAdapter(self.runtime, "codex")
        self.assertEqual("loop.verbalizar", adapter.resolve("/verbalizar-agent")["command_id"])
        with self.assertRaises(LoopRuntimeError) as caught:
            SecureHostAdapter(self.runtime._orchestrator, "codex")
        self.assertEqual("ERR_SECURITY_CONTEXT_INVALID", caught.exception.code)
        self.assertFalse(hasattr(adapter, "invoke_external"))
        self.assertFalse(hasattr(adapter, "invoke_local_state"))

    def test_wrapped_orchestrator_is_not_publicly_exposed(self) -> None:
        self.assertFalse(hasattr(type(self.runtime), "orchestrator"))

    def test_sensitive_runtime_output_is_rejected_before_return(self) -> None:
        resolution = mock.Mock()
        resolution.to_dict.return_value = {"value": "person@example.com"}
        with mock.patch.object(self.runtime._orchestrator, "resolve_command", return_value=resolution):
            with self.assertRaises(LoopRuntimeError) as caught:
                self.runtime.resolve_command("/verbalizar")
        self.assertEqual("ERR_SECURITY_SENSITIVE_OUTPUT", caught.exception.code)
        self.assertNotIn("person@example.com", json.dumps(caught.exception.to_dict()))

    def test_actual_specialist_prompt_is_descriptor_verified_and_subordinate(self) -> None:
        self.runtime.initialize_project("prompt", "Prompt boundary")
        maturity_evidence = "evidence:prompt:maturity"
        root_evidence = "evidence:prompt:root"
        values = {
            "lifecycle_level": "partial",
            "segmentation_level": "behavioral_basic",
            "scoring_level": "none",
            "automated_flow_count": 0,
            "structured_testing_level": "none",
            "personalization_level": "none",
            "attribution_level": "none",
            "prediction_capability": "inactive",
            "realtime_optimization": "inactive",
            "accumulated_learning": False,
        }
        request = {
            "request_id": "request:prompt",
            "project_id": "project:prompt",
            "cycle_id": "cycle:prompt",
            "state_revision": 0,
            "user_goal": "Prepare a message framework.",
            "observations": [
                {"claim_id": "claim:prompt:maturity", "kind": "fact", "text": "Synthetic maturity evidence.", "provenance": {"source_ref": maturity_evidence, "observed_at": "2026-07-20T12:00:00-03:00"}, "confidence": "high"},
                {"claim_id": "claim:prompt:root", "kind": "fact", "text": "Synthetic root evidence.", "provenance": {"source_ref": root_evidence, "observed_at": "2026-07-20T12:00:00-03:00"}, "confidence": "high"},
            ],
            "available_capabilities": {"runtime_overlay": True},
            "authorization_context": {"mode": "read_only", "external_write": False},
            "evidence_registry": {maturity_evidence: True, root_evidence: True},
            "maturity_profile": {"dimensions": {key: {"value": value, "evidence_refs": [maturity_evidence]} for key, value in values.items()}},
            "root_cause_candidate": {"pillar": "verbalizar", "confidence": "high", "supporting_fact_refs": ["claim:prompt:root"], "stronger_counter_evidence_refs": []},
            "requested_roles": ["verbalizar"],
            "evaluate_new_work": False,
            "role_requests": {"verbalizar": {"requested_output_types": ["framework"], "available_inputs": ["company-history-and-impact", "company-context"], "evidenced_prerequisites": ["purpose-evidence-available"], "requested_tactic_ids": ["lm.verbalizar.esclarecimento-de-objetivo-e-missao"]}},
        }
        plan = self.runtime.prepare_route(request)
        opened = []
        original_open = Path.open

        def tracked_open(path, *args, **kwargs):
            opened.append(str(path))
            return original_open(path, *args, **kwargs)

        with mock.patch("pathlib.Path.open", tracked_open):
            envelope = self.runtime.prepare_specialist(plan, plan["nodes"][0]["route_node_id"])
        self.assertEqual(1, len(envelope["prompt_documents"]))
        self.assertEqual("untrusted_tactical_data", envelope["prompt_documents"][0]["prompt_content_trust"])
        self.assertFalse(envelope["execution_policy"]["prompt_content_is_authority"])
        self.assertFalse(envelope["execution_policy"]["credential_discovery_allowed"])
        self.assertTrue(opened)
        self.assertFalse(any(Path(item).name.lower() in {".env", "token.txt", "credentials.md"} for item in opened))

    def test_cli_parser_rejects_duplicates_oversize_and_symlinks(self) -> None:
        duplicate = Path(self.temporary.name) / "duplicate.json"
        duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
        with self.assertRaises(LoopRuntimeError) as caught:
            secure_cli._read_json(str(duplicate))
        self.assertEqual("ERR_SECURITY_JSON_DUPLICATE_KEY", caught.exception.code)

        oversized = Path(self.temporary.name) / "oversized.json"
        oversized.write_bytes(b" " * (secure_cli.MAX_RAW_INPUT_BYTES + 1))
        with self.assertRaises(LoopRuntimeError) as caught:
            secure_cli._read_json(str(oversized))
        self.assertEqual("ERR_SECURITY_INPUT_SIZE", caught.exception.code)

        target = Path(self.temporary.name) / "target.json"
        target.write_text("{}", encoding="utf-8")
        link = Path(self.temporary.name) / "link.json"
        link.symlink_to(target)
        with self.assertRaises(LoopRuntimeError) as caught:
            secure_cli._read_json(str(link))
        self.assertEqual("ERR_SECURITY_INPUT_PATH", caught.exception.code)

    def test_cli_stdin_remains_open_and_output_is_bounded(self) -> None:
        stream = io.StringIO("{}")
        with mock.patch("sys.stdin", stream):
            self.assertEqual({}, secure_cli._read_json("-"))
        self.assertFalse(stream.closed)

        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertFalse(secure_cli._print_bounded({"value": "x" * secure_cli.MAX_OUTPUT_BYTES}))
        value = json.loads(output.getvalue())
        self.assertEqual("ERR_SECURITY_OUTPUT_SIZE", value["error"]["code"])

    def test_secure_cli_unknown_failure_has_no_trace_or_secret(self) -> None:
        output = io.StringIO()
        with mock.patch.object(secure_cli, "run", side_effect=KeyError("person@example.com secret=abc123456789")), mock.patch("sys.stdout", output):
            self.assertEqual(2, secure_cli.main([]))
        result = output.getvalue()
        self.assertNotIn("person@example.com", result)
        self.assertNotIn("abc123456789", result)
        self.assertNotIn("Traceback", result)
        self.assertEqual("ERR_RUNTIME_INTERNAL", json.loads(result)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
