"""End-to-end P5 runtime tests across every integration boundary."""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_marketing_runtime.adapters import HostAdapter
from loop_marketing_runtime.cli import run as cli_run
from loop_marketing_runtime import cli
from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.orchestrator import LoopOrchestrator
from loop_marketing_runtime.validation import canonical_hash


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = PACKAGE_ROOT.parents[1]
SOURCE_ROOT = CONTROL_ROOT.parent / "loop-marketing"

SCORING_MODEL = {
    "verbalizar": (
        "icp_undefined_or_generic",
        "value_proposition_not_differentiated",
        "language_differs_from_customer_language",
        "message_not_adapted_by_lifecycle",
    ),
    "orientar": (
        "segmentation_only_product_plan_or_demographic",
        "lifecycle_missing_transition_criteria",
        "eligibility_logic_missing",
        "churn_or_stagnation_detection_missing",
    ),
    "ampliar": (
        "same_message_all_channels",
        "cross_touchpoint_coordination_missing",
        "attribution_last_click_or_missing",
        "channels_added_without_reallocation",
    ),
    "refinar": (
        "no_performance_diagnosis_by_lifecycle_stage",
        "no_structured_tests",
        "optimization_only_reactive",
        "learning_not_recorded_between_cycles",
    ),
}


class OrchestratorEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temp.name) / ".loop-marketing"
        config = RuntimeConfig(
            library_root=SOURCE_ROOT,
            catalog_path=PACKAGE_ROOT / "data" / "tactic-catalog.json",
            relationship_path=PACKAGE_ROOT / "data" / "relationship-map.json",
            role_matrix_path=PACKAGE_ROOT / "data" / "role-matrix.json",
            routing_contract_path=PACKAGE_ROOT / "data" / "routing-contract.json",
            state_root=self.state_root,
            contracts_root=PACKAGE_ROOT / "contracts",
        )
        self.orchestrator = LoopOrchestrator(config)
        self.orchestrator.store.initialize_project("e2e", "Loop Marketing E2E")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _observations():
        observations = []
        for pillar, signals in SCORING_MODEL.items():
            observations.append({
                "claim_id": "claim:%s" % pillar,
                "kind": "fact",
                "text": "Observed diagnostic signals for %s." % pillar,
                "provenance": {
                    "source_ref": "evidence:%s" % pillar,
                    "observed_at": "2026-07-19T10:00:00-03:00",
                },
                "confidence": "high",
                "signals": {
                    signal: pillar == "verbalizar" and signal == "icp_undefined_or_generic"
                    for signal in signals
                },
            })
        observations.append({
            "claim_id": "claim:maturity-profile",
            "kind": "fact",
            "text": "Maturity dimensions were observed in the referenced assessment.",
            "provenance": {
                "source_ref": "evidence:maturity-profile",
                "observed_at": "2026-07-19T10:00:00-03:00",
            },
            "confidence": "high",
        })
        return observations

    @staticmethod
    def _maturity_profile():
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
        return {
            "dimensions": {
                key: {"value": value, "evidence_refs": ["evidence:maturity-profile"]}
                for key, value in values.items()
            }
        }

    def _request(self):
        return {
            "request_id": "request:e2e",
            "project_id": "project:e2e",
            "cycle_id": "cycle:e2e",
            "state_revision": 0,
            "user_goal": "Produce an evidence-bound message framework.",
            "observations": self._observations(),
            "available_capabilities": {"runtime_overlay": True},
            "authorization_context": {"mode": "read_only", "external_write": False},
            "input_registry": {"artifact:brief-001": True},
            "evidence_registry": {"evidence:diagnostic-001": True},
            "maturity": "em_desenvolvimento",
            "maturity_profile": self._maturity_profile(),
            "requested_roles": ["verbalizar"],
            "evaluate_new_work": False,
            "role_requests": {
                "verbalizar": {
                    "requested_output_types": ["framework"],
                    "need_tags": ["synthesize:brand"],
                    "available_inputs": ["company-history-and-impact", "company-context"],
                    "evidenced_prerequisites": ["purpose-evidence-available"],
                    "requested_tactic_ids": [
                        "lm.verbalizar.esclarecimento-de-objetivo-e-missao"
                    ],
                }
            },
        }

    def _handoff(self, route_plan):
        fixtures = json.loads(
            (CONTROL_ROOT / "artifacts" / "P4" / "compatibility-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = copy.deepcopy(next(
            item["instance"] for item in fixtures["handoff_cases"]
            if item["case_id"] == "HO-POS-001"
        ))
        node = route_plan["nodes"][0]
        handoff.update({
            "handoff_id": "handoff:e2e:verbalizar",
            "project_ref": route_plan["project_ref"],
            "cycle_id": route_plan["cycle_id"],
            "state_revision": route_plan["state_revision"],
            "maturity": route_plan["maturity"],
            "bottleneck_ref": route_plan["primary_bottleneck"]["bottleneck_ref"],
            "tactic_refs": copy.deepcopy(node["selection"]["tactic_refs"]),
        })
        handoff["input_refs"][0]["state_revision"] = route_plan["state_revision"]
        handoff["requested_output"]["write_set"] = list(node["write_set"])
        return handoff

    @staticmethod
    def _events(route_plan):
        bottleneck_ref = route_plan["primary_bottleneck"]["bottleneck_ref"]

        def event(event_type, data):
            return {
                "event_type": event_type,
                "actor_role": "loop_planning",
                "effect": "integration",
                "evidence_refs": ["evidence:verbalizar"],
                "payload": {
                    "payload_version": "1.0",
                    "claims": [{
                        "claim_id": "claim:e2e:%s" % event_type,
                        "kind": "fact",
                        "text": "Evidence validated for the E2E integration.",
                        "provenance": {
                            "source_ref": "evidence:verbalizar",
                            "observed_at": "2026-07-19T10:00:00-03:00",
                        },
                        "confidence": "high",
                    }],
                    "data": data,
                },
            }

        return [
            event("maturity_classified", {"maturity": route_plan["maturity"]}),
            event("bottleneck_accepted", {"bottleneck_ref": bottleneck_ref}),
        ]

    def test_real_adapters_resolve_all_commands_without_host_semantic_drift(self):
        invocations = (
            "/loop-planning", "/loop-planning-agent", "/verbalizar", "/verbalizar-agent",
            "/orientar", "/orientar-agent", "/ampliar", "/ampliar-agent",
            "/refinar", "/refinar-agent", "/projeto", "/projeto-template",
        )
        for invocation in invocations:
            baseline = HostAdapter(self.orchestrator, "generic").resolve(invocation).to_dict()
            for host in ("claude", "codex"):
                with self.subTest(invocation=invocation, host=host):
                    self.assertEqual(baseline, HostAdapter(self.orchestrator, host).resolve(invocation).to_dict())
        cli_result = cli_run([
            "--runtime-root", str(PACKAGE_ROOT),
            "--library-root", str(SOURCE_ROOT),
            "--state-root", str(self.state_root),
            "resolve", "/projeto-template",
        ])
        self.assertEqual("loop.projeto", cli_result["command_id"])
        self.assertEqual("/projeto", cli_result["canonical_invocation"])
        output = io.StringIO()
        with mock.patch.object(cli, "run", side_effect=KeyError("secret-bearing-internal")), mock.patch("sys.stdout", output):
            self.assertEqual(2, cli.main([]))
        failure = json.loads(output.getvalue())
        self.assertEqual("ERR_RUNTIME_INTERNAL", failure["error"]["code"])
        self.assertNotIn("secret-bearing-internal", output.getvalue())

    def test_route_specialist_and_handoff_are_read_only_and_contract_bound(self):
        ledger = self.state_root / "state" / "projects" / "e2e" / "events.jsonl"
        before = ledger.read_bytes()
        planning = HostAdapter(self.orchestrator, "generic").invoke_read_only(
            "/loop-planning-agent",
            self._request(),
        )
        route_plan = planning["result"]
        self.assertEqual("ready", route_plan["route_status"])
        self.assertEqual("verbalizar", route_plan["primary_bottleneck"]["pillar"])
        self.assertTrue(route_plan["primary_bottleneck"]["bottleneck_ref"].startswith("bottleneck:cycle:e2e:"))
        self.assertEqual(1, len(route_plan["nodes"]))

        node = route_plan["nodes"][0]
        specialist = HostAdapter(self.orchestrator, "codex").invoke_read_only(
            "/verbalizar-agent",
            {"route_plan": route_plan, "route_node_id": node["route_node_id"]},
        )
        self.assertEqual(1, len(specialist["result"]["prompt_documents"]))
        self.assertTrue(specialist["result"]["prompt_documents"][0]["prompt_body"].strip())
        self.assertEqual(before, ledger.read_bytes())

        with self.assertRaises(LoopRuntimeError) as wrong_role:
            HostAdapter(self.orchestrator, "generic").invoke_read_only(
                "/orientar",
                {"route_plan": route_plan, "route_node_id": node["route_node_id"]},
            )
        self.assertEqual("ERR_OWNER_SCOPE_VIOLATION", wrong_role.exception.code)

        tampered_plan = copy.deepcopy(route_plan)
        tampered_plan["nodes"][0]["objective"] = "Bypass the canonical router."
        with self.assertRaises(LoopRuntimeError) as route_drift:
            self.orchestrator.prepare_specialist(
                tampered_plan,
                tampered_plan["nodes"][0]["route_node_id"],
            )
        self.assertEqual("ERR_RUNTIME_CONTRACT_DRIFT", route_drift.exception.code)
        self.assertEqual(before, ledger.read_bytes())

        handoff = self._handoff(route_plan)
        empty = self.orchestrator.validate_staged_outputs(route_plan, [])
        self.assertFalse(empty["ok"])
        self.assertEqual("ERR_SEQUENCE_DEPENDENCY", empty["primary_code"])
        validated = self.orchestrator.validate_staged_outputs(route_plan, [handoff])
        self.assertTrue(validated["ok"], validated)
        self.assertEqual([handoff["handoff_id"]], validated["validated_handoff_ids"])

        drifted = copy.deepcopy(handoff)
        drifted["tactic_refs"] = []
        drifted["bottleneck_ref"] = "bottleneck:other"
        rejected = self.orchestrator.validate_staged_outputs(route_plan, [drifted])
        self.assertFalse(rejected["ok"])
        codes = {item["code"] for item in rejected["violations"]}
        self.assertIn("ERR_TACTIC_METADATA_MISSING", codes)
        self.assertIn("ERR_HANDOFF_PROVENANCE", codes)
        self.assertEqual(before, ledger.read_bytes())

    def test_route_to_multi_event_commit_exact_replay_and_stale_rejection(self):
        stale_request = self._request()
        stale_request["state_revision"] = 99
        with self.assertRaises(LoopRuntimeError) as stale_route:
            self.orchestrator.prepare_route(stale_request)
        self.assertEqual("ERR_STATE_REVISION_STALE", stale_route.exception.code)
        route_plan = self.orchestrator.prepare_route(self._request())
        with self.assertRaises(LoopRuntimeError) as blocked:
            self.orchestrator.build_transaction(route_plan, self._events(route_plan))
        self.assertEqual("ERR_CROSS_VALIDATION_BLOCKED", blocked.exception.code)
        handoff = self._handoff(route_plan)
        self.assertTrue(self.orchestrator.validate_staged_outputs(route_plan, [handoff])["ok"])
        external_events = self._events(route_plan)
        external_events[0]["payload"]["data"]["external_mutation_requested"] = True
        with self.assertRaises(LoopRuntimeError) as external:
            self.orchestrator.build_transaction(route_plan, external_events)
        self.assertEqual("ERR_EXTERNAL_MUTATION_UNAUTHORIZED", external.exception.code)

        unknown_evidence = self._events(route_plan)
        unknown_evidence[0]["evidence_refs"] = ["evidence:unresolved"]
        unknown_evidence[0]["payload"]["claims"][0]["provenance"]["source_ref"] = "evidence:unresolved"
        with self.assertRaises(LoopRuntimeError) as unresolved:
            self.orchestrator.build_transaction(route_plan, unknown_evidence)
        self.assertEqual("ERR_EVIDENCE_REF_UNRESOLVED", unresolved.exception.code)
        claim_source_drift = self._events(route_plan)
        claim_source_drift[0]["payload"]["claims"][0]["provenance"]["source_ref"] = "evidence:unresolved-claim"
        with self.assertRaises(LoopRuntimeError) as unresolved_claim:
            self.orchestrator.build_transaction(route_plan, claim_source_drift)
        self.assertEqual("ERR_EVIDENCE_REF_UNRESOLVED", unresolved_claim.exception.code)
        mismatched_maturity = self._events(route_plan)
        mismatched_maturity[0]["payload"]["data"]["maturity"] = "avancado"
        with self.assertRaises(LoopRuntimeError) as maturity:
            self.orchestrator.build_transaction(route_plan, mismatched_maturity)
        self.assertEqual("ERR_MATURITY_GATE", maturity.exception.code)
        transaction = self.orchestrator.build_transaction(route_plan, self._events(route_plan))
        self.assertEqual(2, len(transaction["events"]))
        self.assertEqual({0}, {item["state_revision"] for item in transaction["events"]})
        self.assertEqual({1}, {item["resulting_state_revision"] for item in transaction["events"]})

        committed = self.orchestrator.commit_transaction("e2e", transaction)
        self.assertEqual("committed", committed["status"])
        self.assertEqual(1, committed["state_revision"])
        self.assertEqual("em_desenvolvimento", committed["snapshot"]["state"]["maturity"])
        self.assertEqual(
            route_plan["primary_bottleneck"]["bottleneck_ref"],
            committed["snapshot"]["state"]["accepted_bottleneck_ref"],
        )
        ledger = self.state_root / "state" / "projects" / "e2e" / "events.jsonl"
        committed_bytes = ledger.read_bytes()

        replayed = self.orchestrator.commit_transaction("e2e", transaction)
        self.assertEqual("noop", replayed["status"])
        self.assertEqual(committed_bytes, ledger.read_bytes())
        self.assertEqual(committed["snapshot"], self.orchestrator.store.replay("e2e"))
        restarted = LoopOrchestrator(self.orchestrator.config)
        self.assertEqual("noop", restarted.commit_transaction("e2e", transaction)["status"])
        self.assertEqual(committed_bytes, ledger.read_bytes())

        tampered = copy.deepcopy(transaction)
        tampered["events"][0]["payload"]["data"]["maturity"] = "avancado"
        tampered["events"][0]["event_hash"] = canonical_hash(tampered["events"][0], "event_hash")
        tampered["events"][1]["previous_event_hash"] = tampered["events"][0]["event_hash"]
        tampered["events"][1]["event_hash"] = canonical_hash(tampered["events"][1], "event_hash")
        tampered["record_hash"] = canonical_hash(tampered, "record_hash")
        with self.assertRaises(LoopRuntimeError) as conflict:
            self.orchestrator.commit_transaction("e2e", tampered)
        self.assertEqual("ERR_CROSS_VALIDATION_BLOCKED", conflict.exception.code)
        self.assertEqual(committed_bytes, ledger.read_bytes())

        with self.assertRaises(LoopRuntimeError) as stale:
            self.orchestrator.build_transaction(route_plan, self._events(route_plan))
        self.assertEqual("ERR_STATE_REVISION_STALE", stale.exception.code)
        self.assertEqual(committed_bytes, ledger.read_bytes())


if __name__ == "__main__":
    unittest.main()
