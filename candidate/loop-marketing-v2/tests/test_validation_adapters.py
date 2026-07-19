"""Contract and host-adapter tests for the P5 validation workstream."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = CONTROL_ROOT.parent / "loop-marketing"
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from loop_marketing_runtime.adapters import HostAdapter  # noqa: E402
from loop_marketing_runtime.errors import LoopRuntimeError  # noqa: E402
from loop_marketing_runtime.models import CommandResolution, RuntimeConfig  # noqa: E402
from loop_marketing_runtime.validation import ContractValidator, canonical_hash  # noqa: E402


def runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        library_root=SOURCE_ROOT,
        catalog_path=PACKAGE_ROOT / "data" / "tactic-catalog.json",
        relationship_path=PACKAGE_ROOT / "data" / "relationship-map.json",
        role_matrix_path=PACKAGE_ROOT / "data" / "role-matrix.json",
        routing_contract_path=PACKAGE_ROOT / "data" / "routing-contract.json",
        state_root=PACKAGE_ROOT / ".loop-marketing" / "state",
        contracts_root=PACKAGE_ROOT / "contracts",
    )


class ContractValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = ContractValidator(runtime_config())
        cls.fixtures = json.loads(
            (CONTROL_ROOT / "artifacts" / "P4" / "compatibility-fixtures.json").read_text(
                encoding="utf-8"
            )
        )

    def _fixture(self, group: str, case_id: str):
        return next(item for item in self.fixtures[group] if item["case_id"] == case_id)

    def test_all_bundled_p4_state_event_transaction_and_handoff_cases(self) -> None:
        evaluators = {
            "state_cases": lambda instance, _context: self.validator.validate_state(instance),
            "event_cases": self.validator.validate_event,
            "transaction_cases": self.validator.validate_transaction,
            "handoff_cases": self.validator.validate_handoff,
        }
        for group, evaluator in evaluators.items():
            for case in self.fixtures[group]:
                with self.subTest(group=group, case=case["case_id"]):
                    result = evaluator(case["instance"], case.get("context", {}))
                    self.assertEqual(result.ok, case["expected"] == "accept")
                    self.assertEqual(result.primary_code, case.get("expected_code"))

    def test_schema_subset_rejects_closed_object_extensions(self) -> None:
        event_case = self._fixture("event_cases", "EVENT-POS-BASIC")
        event = copy.deepcopy(event_case["instance"])
        event["host_only_field"] = "claude"
        event["event_hash"] = canonical_hash(event, "event_hash")
        result = self.validator.validate_event(event, event_case["context"])
        self.assertFalse(result.ok)
        self.assertEqual(result.primary_code, "LM-EVENT-SCHEMA-INVALID")
        schema_errors = result.violations[0]["details"]["schema_errors"]
        self.assertIn({"path": "$.host_only_field", "keyword": "additionalProperties"}, schema_errors)

        handoff_case = self._fixture("handoff_cases", "HO-POS-001")
        handoff = copy.deepcopy(handoff_case["instance"])
        handoff["repair_hint"] = "infer-me"
        result = self.validator.validate_handoff(handoff, handoff_case["context"])
        self.assertFalse(result.ok)
        self.assertEqual(result.primary_code, "ERR_HANDOFF_FIELD_MISSING")

    def test_event_hash_revision_and_authority_fail_closed_independently(self) -> None:
        case = self._fixture("event_cases", "EVENT-POS-BASIC")

        tampered = copy.deepcopy(case["instance"])
        tampered["payload"]["data"]["maturity"] = "avancado"
        result = self.validator.validate_event(tampered, case["context"])
        self.assertEqual(result.primary_code, "LM-EVENT-HASH-MISMATCH")

        stale = copy.deepcopy(case["instance"])
        stale["state_revision"] = 7
        stale["resulting_state_revision"] = 8
        stale["event_hash"] = canonical_hash(stale, "event_hash")
        result = self.validator.validate_event(stale, case["context"])
        self.assertEqual(result.primary_code, "ERR_STATE_REVISION_STALE")

        unauthorized = copy.deepcopy(case["instance"])
        unauthorized["actor_role"] = "verbalizar"
        unauthorized["command_id"] = "loop.verbalizar"
        unauthorized["event_type"] = "bottleneck_accepted"
        unauthorized["event_hash"] = canonical_hash(unauthorized, "event_hash")
        result = self.validator.validate_event(unauthorized, case["context"])
        self.assertEqual(result.primary_code, "ERR_BOTTLENECK_OWNER_VIOLATION")

        unresolved = copy.deepcopy(case["instance"])
        unresolved["evidence_refs"] = ["evidence:does-not-exist"]
        unresolved["event_hash"] = canonical_hash(unresolved, "event_hash")
        result = self.validator.validate_event(unresolved, case["context"])
        self.assertEqual(result.primary_code, "ERR_EVIDENCE_REF_UNRESOLVED")

        external = copy.deepcopy(case["instance"])
        external["payload"]["data"].update({
            "external_mutation_requested": True,
            "authorization_ref": "authority:does-not-exist",
        })
        external["event_hash"] = canonical_hash(external, "event_hash")
        result = self.validator.validate_event(external, case["context"])
        self.assertEqual(result.primary_code, "ERR_EXTERNAL_MUTATION_UNAUTHORIZED")

    def test_strict_registry_binds_experiment_evidence_and_fact_sources(self) -> None:
        experiment = self._fixture("event_cases", "EVENT-POS-EXPERIMENT")
        strict_experiment = dict(experiment["context"])
        strict_experiment.update({
            "require_evidence_registry": True,
            "evidence_registry": {"evidence:diagnostic-001": True},
        })
        result = self.validator.validate_event(experiment["instance"], strict_experiment)
        self.assertFalse(result.ok)
        self.assertEqual(result.primary_code, "ERR_EVIDENCE_REF_UNRESOLVED")

        basic = self._fixture("event_cases", "EVENT-POS-BASIC")
        event = copy.deepcopy(basic["instance"])
        event_ref = event["evidence_refs"][0]
        event["payload"]["claims"][0]["provenance"]["source_ref"] = "evidence:fake-claim-source"
        event["event_hash"] = canonical_hash(event, "event_hash")
        result = self.validator.validate_event(event, {
            **basic["context"],
            "require_evidence_registry": True,
            "evidence_registry": {
                event_ref: True,
                "evidence:fake-claim-source": True,
            },
        })
        self.assertFalse(result.ok)
        self.assertEqual(result.primary_code, "ERR_EVIDENCE_REF_UNRESOLVED")
        binding = next(
            item for item in result.violations
            if item["code"] == "ERR_EVIDENCE_REF_UNRESOLVED"
            and item["details"].get("source_ref") == "evidence:fake-claim-source"
        )
        self.assertTrue(binding["details"]["registry_resolved"])
        self.assertFalse(binding["details"]["event_bound"])

    def test_transaction_detects_nested_event_tamper_even_with_rehashed_record(self) -> None:
        case = self._fixture("transaction_cases", "TX-POS-SINGLE")
        record = copy.deepcopy(case["instance"])
        record["events"][0]["payload"]["data"]["maturity"] = "avancado"
        record["record_hash"] = canonical_hash(record, "record_hash")
        result = self.validator.validate_transaction(record, case["context"])
        self.assertFalse(result.ok)
        self.assertEqual(result.primary_code, "LM-EVENT-HASH-MISMATCH")

    def test_handoff_exact_scope_and_deterministic_multi_error_precedence(self) -> None:
        case = self._fixture("handoff_cases", "HO-POS-001")
        handoff = copy.deepcopy(case["instance"])
        handoff["unexpected"] = True
        handoff["state_revision"] += 1
        handoff["scope_boundary_next_does_not_decide"] = []
        handoff["requested_output"]["decision_domains"] = [
            "external_execution_authorization"
        ]
        result = self.validator.validate_handoff(handoff, case["context"])
        self.assertFalse(result.ok)
        codes = [item["code"] for item in result.violations]
        self.assertEqual(result.primary_code, "ERR_HANDOFF_FIELD_MISSING")
        self.assertLess(codes.index("ERR_HANDOFF_STALE_REVISION"), codes.index("ERR_HANDOFF_OWNER_SCOPE"))
        self.assertLess(codes.index("ERR_HANDOFF_OWNER_SCOPE"), codes.index("ERR_HANDOFF_SCOPE_BOUNDARY"))
        self.assertLess(codes.index("ERR_HANDOFF_SCOPE_BOUNDARY"), codes.index("ERR_EXTERNAL_MUTATION_UNAUTHORIZED"))

    def test_validation_never_repairs_or_mutates_input(self) -> None:
        case = self._fixture("handoff_cases", "HO-NEG-MISSING")
        value = copy.deepcopy(case["instance"])
        before = copy.deepcopy(value)
        result = self.validator.validate_handoff(value, case["context"])
        self.assertFalse(result.ok)
        self.assertEqual(value, before)
        self.assertIsNone(result.value)


class _FakeOrchestrator:
    _MAP = {
        "/loop-planning": ("loop.planning", "/loop-planning", "loop_planning"),
        "/loop-planning-agent": ("loop.planning", "/loop-planning", "loop_planning"),
        "/verbalizar": ("loop.verbalizar", "/verbalizar", "verbalizar"),
        "/verbalizar-agent": ("loop.verbalizar", "/verbalizar", "verbalizar"),
        "/orientar": ("loop.orientar", "/orientar", "orientar"),
        "/orientar-agent": ("loop.orientar", "/orientar", "orientar"),
        "/ampliar": ("loop.ampliar", "/ampliar", "ampliar"),
        "/ampliar-agent": ("loop.ampliar", "/ampliar", "ampliar"),
        "/refinar": ("loop.refinar", "/refinar", "refinar"),
        "/refinar-agent": ("loop.refinar", "/refinar", "refinar"),
        "/projeto": ("loop.projeto", "/projeto", "loop_planning"),
        "/projeto-template": ("loop.projeto", "/projeto", "loop_planning"),
    }

    def __init__(self) -> None:
        self.config = SimpleNamespace(state_root=PACKAGE_ROOT / ".loop-marketing" / "state")
        self.calls = []

    def resolve_command(self, invocation: str) -> CommandResolution:
        command_id, canonical, role = self._MAP[invocation]
        return CommandResolution(command_id, canonical, invocation, role)

    def prepare_route(self, request):
        self.calls.append(("prepare_route", request))
        return {"prepared": "route", "read_only": True}

    def prepare_specialist(self, route_plan, route_node_id):
        self.calls.append(("prepare_specialist", route_plan, route_node_id))
        return {"prepared": route_node_id, "read_only": True}


class HostAdapterTests(unittest.TestCase):
    PAIRS = (
        ("/loop-planning", "/loop-planning-agent", "loop.planning", "loop_planning"),
        ("/verbalizar", "/verbalizar-agent", "loop.verbalizar", "verbalizar"),
        ("/orientar", "/orientar-agent", "loop.orientar", "orientar"),
        ("/ampliar", "/ampliar-agent", "loop.ampliar", "ampliar"),
        ("/refinar", "/refinar-agent", "loop.refinar", "refinar"),
        ("/projeto", "/projeto-template", "loop.projeto", "loop_planning"),
    )

    def test_six_canonical_and_six_legacy_invocations_are_semantically_identical(self) -> None:
        adapter = HostAdapter(_FakeOrchestrator(), "generic")
        for canonical, legacy, command_id, role in self.PAIRS:
            with self.subTest(command_id=command_id):
                canonical_result = adapter.resolve(canonical)
                legacy_result = adapter.resolve(legacy)
                self.assertEqual(canonical_result.command_id, command_id)
                self.assertEqual(legacy_result.command_id, command_id)
                self.assertEqual(canonical_result.role_id, role)
                self.assertEqual(legacy_result.role_id, role)
                self.assertEqual(canonical_result.canonical_invocation, canonical)
                self.assertEqual(legacy_result.canonical_invocation, canonical)

    def test_generic_claude_and_codex_envelopes_are_byte_semantically_equal(self) -> None:
        payload = {"project_ref": "project:example", "claims": []}
        envelopes = [
            HostAdapter(_FakeOrchestrator(), host).build_envelope("/loop-planning", payload)
            for host in ("generic", "claude", "codex")
        ]
        self.assertEqual(envelopes[0], envelopes[1])
        self.assertEqual(envelopes[1], envelopes[2])
        self.assertTrue(envelopes[0]["read_only"])
        self.assertFalse(envelopes[0]["external_write_authorized"])
        json.dumps(envelopes[0], allow_nan=False)

    def test_alias_only_changes_invoked_as_presentation(self) -> None:
        adapter = HostAdapter(_FakeOrchestrator(), "claude")
        canonical = adapter.build_envelope("/orientar", {})
        legacy = adapter.build_envelope("/orientar-agent", {})
        legacy["command"]["invoked_as"] = canonical["command"]["invoked_as"]
        self.assertEqual(canonical, legacy)

    def test_unknown_host_and_host_specific_namespaces_are_rejected(self) -> None:
        with self.assertRaises(LoopRuntimeError) as caught:
            HostAdapter(_FakeOrchestrator(), "vscode")
        self.assertEqual(caught.exception.code, "ERR_INPUT_REQUIRED")
        adapter = HostAdapter(_FakeOrchestrator(), "codex")
        for invocation in ("codex:/orientar", "/codex/orientar", "/ORIENTAR", " /orientar"):
            with self.subTest(invocation=invocation), self.assertRaises(LoopRuntimeError) as caught:
                adapter.resolve(invocation)
            self.assertEqual(caught.exception.code, "ERR_INPUT_REQUIRED")

    def test_invoke_read_only_routes_planner_and_specialist_without_write_surface(self) -> None:
        orchestrator = _FakeOrchestrator()
        adapter = HostAdapter(orchestrator, "generic")
        planning = adapter.invoke_read_only("/loop-planning", {"project_ref": "project:example"})
        self.assertEqual(planning["result"]["prepared"], "route")
        specialist = adapter.invoke_read_only(
            "/verbalizar-agent",
            {
                "route_plan": {
                    "state_revision": 3,
                    "nodes": [{"route_node_id": "node:message", "role_id": "verbalizar"}],
                },
                "route_node_id": "node:message",
            },
        )
        self.assertEqual(specialist["result"]["prepared"], "node:message")
        public_callables = {
            name for name in dir(adapter)
            if not name.startswith("_") and callable(getattr(adapter, name))
        }
        self.assertEqual(public_callables, {"resolve", "build_envelope", "invoke_read_only"})

    def test_payload_is_copied_and_non_serializable_values_fail_closed(self) -> None:
        adapter = HostAdapter(_FakeOrchestrator(), "codex")
        payload = {"nested": {"value": 1}}
        envelope = adapter.build_envelope("/projeto", payload)
        payload["nested"]["value"] = 2
        self.assertEqual(envelope["payload"]["nested"]["value"], 1)
        with self.assertRaises(LoopRuntimeError) as caught:
            adapter.build_envelope("/projeto", {"bad": object()})
        self.assertEqual(caught.exception.code, "ERR_INPUT_REQUIRED")


class SourcePreservationTests(unittest.TestCase):
    def test_canonical_source_repository_remains_clean(self) -> None:
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(SOURCE_ROOT),
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
