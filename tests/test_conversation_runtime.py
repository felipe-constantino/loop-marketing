from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "loop-marketing"
sys.path.insert(0, str(SKILL_ROOT / "scripts" / "runtime"))

from loop_marketing_runtime.conversation import SPEAKER_LABELS, speaker_header, validate_dialogue_turn
from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.secure_runtime import SecureLoopRuntime


def make_runtime(state_root: Path) -> SecureLoopRuntime:
    data = SKILL_ROOT / "references" / "runtime-data"
    return SecureLoopRuntime(RuntimeConfig(
        library_root=SKILL_ROOT / "references" / "library",
        catalog_path=data / "data" / "tactic-catalog.json",
        relationship_path=data / "data" / "relationship-map.json",
        role_matrix_path=data / "data" / "role-matrix.json",
        routing_contract_path=data / "data" / "routing-contract.json",
        state_root=state_root,
        contracts_root=data / "contracts",
    ))


def route_request() -> dict:
    score_signals = {
        "icp_undefined_or_generic": False,
        "value_proposition_not_differentiated": False,
        "language_differs_from_customer_language": False,
        "message_not_adapted_by_lifecycle": False,
        "segmentation_only_product_plan_or_demographic": True,
        "lifecycle_missing_transition_criteria": False,
        "eligibility_logic_missing": False,
        "churn_or_stagnation_detection_missing": False,
        "same_message_all_channels": False,
        "cross_touchpoint_coordination_missing": False,
        "attribution_last_click_or_missing": False,
        "channels_added_without_reallocation": False,
        "no_performance_diagnosis_by_lifecycle_stage": False,
        "no_structured_tests": False,
        "optimization_only_reactive": False,
        "learning_not_recorded_between_cycles": False,
        "message_validated": True,
        "audience_eligibility_defined": False,
        "measurable_data_exists": True,
        "measurement_readiness": True,
        "failure_locus_unknown": False,
    }
    return {
        "request_id": "request:consent-test",
        "project_id": "project:conversation-test",
        "cycle_id": "cycle:conversation-test-001",
        "state_revision": 0,
        "user_goal": "Revisar a segmentacao antes das reguas.",
        "observations": [{
            "claim_id": "claim:segmentacao-gap",
            "kind": "fact",
            "text": "A segmentacao atual usa somente dados demograficos.",
            "provenance": {
                "source_ref": "artifact:context",
                "observed_at": "2026-07-21T18:00:00-03:00",
                "evidence_refs": ["evidence:context"],
            },
            "confidence": "high",
            "signals": score_signals,
            "failure_locus": "orientar",
        }],
        "available_capabilities": {"runtime_overlay": True},
        "authorization_context": {"mode": "read_only", "external_write": False},
        "requested_roles": ["orientar"],
        "evaluate_new_work": False,
        "root_cause_candidate": {
            "pillar": "orientar",
            "confidence": "high",
            "supporting_fact_refs": ["claim:segmentacao-gap"],
            "stronger_counter_evidence_refs": [],
        },
        "input_registry": {"artifact:context": True},
        "evidence_registry": {"evidence:context": True},
    }


def approved_handoff(route: dict) -> dict:
    node = route["nodes"][0]
    return {
        "handoff_id": "handoff:conversation-test-001",
        "contract_version": "1.1",
        "project_ref": route["project_ref"],
        "cycle_id": route["cycle_id"],
        "state_revision": route["state_revision"],
        "from_role": "loop_planning",
        "to_role": "orientar",
        "created_at": "2026-07-21T18:05:00-03:00",
        "objective": "Revisar e propor a segmentacao do ciclo.",
        "mode": node["mode"],
        "maturity": route["maturity"],
        "bottleneck_ref": route["primary_bottleneck"]["bottleneck_ref"],
        "input_refs": [{
            "input_ref": "artifact:context",
            "input_kind": "artifact",
            "state_revision": route["state_revision"],
            "required": True,
            "dependency_status": "validated",
            "content_sha256": None,
        }],
        "tactic_refs": (node.get("selection") or {}).get("tactic_refs", []),
        "decisions_to_respect": [],
        "scope_boundary_next_does_not_decide": [
            "global_orchestration",
            "message_and_copy",
            "channel_timing_and_cadence",
            "experiment_performance_and_learning",
            "security_privacy_and_data_use",
            "external_execution_authorization",
        ],
        "evidence_refs": [{
            "evidence_id": "evidence:context",
            "source_ref": "artifact:context",
            "observed_at": "2026-07-21T18:00:00-03:00",
            "content_sha256": None,
            "claim_refs": ["claim:temporary-segment"],
        }],
        "assumptions": [],
        "known_gaps": [],
        "requested_output": {
            "output_id": "output:segmentacao",
            "description": "Modelo de segmentacao revisado.",
            "decision_domains": ["lifecycle_segmentation_and_eligibility"],
            "artifact_types": ["segmentacao"],
            "acceptance_criteria": ["Criterios de inclusao e exclusao definidos."],
            "write_set": node["write_set"],
            "proposed_state_events": ["segment_definition_proposed"],
        },
        "cross_validation_required": {
            "required": True,
            "roles": ["loop_planning"],
            "conflicts": [],
        },
        "escalation_conditions": [],
        "user_approval": {
            "approval_ref": "approval:user-001",
            "status": "approved",
            "approved_by": "lead_or_user",
            "approved_at": "2026-07-21T18:04:00-03:00",
            "source_turn_ref": "turn:user-001",
            "scope_summary": "Segmentacao aprovada como escopo para Tailor.",
        },
    }


class DialogueContractTests(unittest.TestCase):
    def test_all_roles_have_exact_visible_headers(self) -> None:
        self.assertEqual(set(SPEAKER_LABELS), {
            "loop_planning", "verbalizar", "orientar", "ampliar", "refinar"
        })
        for role, label in SPEAKER_LABELS.items():
            self.assertEqual(speaker_header(role), f"---\n**{label}**\n---")

    def test_route_proposal_must_pause(self) -> None:
        result = validate_dialogue_turn({
            "conversation_version": "1.0",
            "cycle_id": "cycle:avaliza-001",
            "turn_id": "turn:assistant-001",
            "speaker_role": "loop_planning",
            "speaker_label": "Loop Agent",
            "speaker_header": "---\n**Loop Agent**\n---",
            "turn_kind": "route_proposal",
            "decision_status": "proposed",
            "handoff": {
                "status": "proposed",
                "from_role": "loop_planning",
                "to_role": "orientar",
            },
            "user_approval_ref": None,
            "must_pause": True,
        })
        self.assertTrue(result["valid"])
        self.assertTrue(result["must_pause"])
        self.assertFalse(result["may_start_destination"])

    def test_handoff_cannot_self_approve(self) -> None:
        with self.assertRaises(LoopRuntimeError) as caught:
            validate_dialogue_turn({
                "conversation_version": "1.0",
                "cycle_id": "cycle:avaliza-001",
                "turn_id": "turn:assistant-002",
                "speaker_role": "orientar",
                "speaker_label": "Tailor · Orientar",
                "speaker_header": "---\n**Tailor · Orientar**\n---",
                "turn_kind": "handoff_accepted",
                "decision_status": "draft",
                "handoff": {
                    "status": "approved",
                    "from_role": "loop_planning",
                    "to_role": "orientar",
                },
                "user_approval_ref": None,
                "must_pause": False,
            })
        self.assertEqual(caught.exception.code, "ERR_DIALOGUE_APPROVAL_REQUIRED")

    def test_results_intake_belongs_to_loop_agent(self) -> None:
        with self.assertRaises(LoopRuntimeError) as caught:
            validate_dialogue_turn({
                "conversation_version": "1.0",
                "cycle_id": "cycle:avaliza-002",
                "turn_id": "turn:assistant-results",
                "speaker_role": "refinar",
                "speaker_label": "Evolve · Refinar",
                "speaker_header": "---\n**Evolve · Refinar**\n---",
                "turn_kind": "results_intake",
                "decision_status": "draft",
                "handoff": {"status": "none", "from_role": None, "to_role": None},
                "user_approval_ref": None,
                "must_pause": False,
            })
        self.assertEqual(caught.exception.code, "ERR_DIALOGUE_SPEAKER")

    def test_execution_plan_belongs_to_loop_agent_and_pauses(self) -> None:
        result = validate_dialogue_turn({
            "conversation_version": "1.0",
            "cycle_id": "cycle:avaliza-003",
            "turn_id": "turn:assistant-plan",
            "speaker_role": "loop_planning",
            "speaker_label": "Loop Agent",
            "speaker_header": "---\n**Loop Agent**\n---",
            "turn_kind": "execution_plan",
            "decision_status": "proposed",
            "handoff": {"status": "none", "from_role": None, "to_role": None},
            "user_approval_ref": None,
            "must_pause": True,
        })
        self.assertTrue(result["must_pause"])
        self.assertFalse(result["may_start_destination"])

    def test_cycle_restart_is_only_a_proposal(self) -> None:
        result = validate_dialogue_turn({
            "conversation_version": "1.0",
            "cycle_id": "cycle:avaliza-004",
            "turn_id": "turn:assistant-restart",
            "speaker_role": "loop_planning",
            "speaker_label": "Loop Agent",
            "speaker_header": "---\n**Loop Agent**\n---",
            "turn_kind": "cycle_restart",
            "decision_status": "proposed",
            "handoff": {
                "status": "proposed",
                "from_role": "loop_planning",
                "to_role": "refinar",
            },
            "user_approval_ref": None,
            "must_pause": True,
        })
        self.assertTrue(result["must_pause"])
        self.assertFalse(result["may_start_destination"])


class SpecialistApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = make_runtime(Path(self.temp.name) / ".loop-marketing")
        self.runtime.initialize_project("conversation-test", "Conversation Test")
        self.route = self.runtime.prepare_route(route_request())
        self.node = self.route["nodes"][0]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_approved_handoff_unlocks_only_destination(self) -> None:
        handoff = approved_handoff(self.route)
        envelope = self.runtime.prepare_specialist(
            self.route, self.node["route_node_id"], handoff
        )
        self.assertEqual(envelope["role_contract"]["role_id"], "orientar")
        self.assertEqual(envelope["approved_handoff_id"], handoff["handoff_id"])
        self.assertEqual(envelope["user_approval"]["status"], "approved")

    def test_missing_approval_blocks_specialist(self) -> None:
        handoff = approved_handoff(self.route)
        handoff.pop("user_approval")
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime.prepare_specialist(
                self.route, self.node["route_node_id"], handoff
            )
        self.assertEqual(caught.exception.code, "ERR_USER_APPROVAL_REQUIRED")

    def test_provisional_approval_requires_assumption(self) -> None:
        handoff = approved_handoff(self.route)
        handoff["user_approval"]["status"] = "provisional_approved"
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime.prepare_specialist(
                self.route, self.node["route_node_id"], handoff
            )
        self.assertEqual(caught.exception.code, "ERR_USER_APPROVAL_REQUIRED")

    def test_provisional_approval_requires_risk_and_review_condition(self) -> None:
        handoff = approved_handoff(self.route)
        handoff["user_approval"]["status"] = "provisional_approved"
        handoff["assumptions"] = [{
            "assumption_id": "assumption:temporary-segment",
            "claim_refs": ["claim:temporary-segment"],
            "statement": "Usar temporariamente a segmentacao atual.",
            "rationale": "Ainda falta a fonte discriminante.",
            "confidence": "medium",
        }]
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime.prepare_specialist(
                self.route, self.node["route_node_id"], handoff
            )
        self.assertEqual(caught.exception.code, "ERR_USER_APPROVAL_REQUIRED")

    def test_complete_provisional_approval_unlocks_destination(self) -> None:
        handoff = approved_handoff(self.route)
        handoff["user_approval"].update({
            "status": "provisional_approved",
            "risk_summary": "O tamanho dos segmentos pode mudar apos reconciliacao.",
            "review_condition": "Revalidar antes de publicar qualquer regua.",
        })
        handoff["assumptions"] = [{
            "assumption_id": "assumption:temporary-segment",
            "claim_refs": ["claim:segmentacao-gap"],
            "statement": "Usar temporariamente a segmentacao atual.",
            "rationale": "Permite desenvolver a proposta sem publicar a regua.",
            "confidence": "medium",
        }]
        envelope = self.runtime.prepare_specialist(
            self.route, self.node["route_node_id"], handoff
        )
        self.assertEqual(envelope["user_approval"]["status"], "provisional_approved")

    def test_wrong_destination_is_rejected(self) -> None:
        handoff = approved_handoff(self.route)
        handoff["to_role"] = "verbalizar"
        with self.assertRaises(LoopRuntimeError) as caught:
            self.runtime.prepare_specialist(
                self.route, self.node["route_node_id"], handoff
            )
        self.assertIn(caught.exception.code, {
            "ERR_HANDOFF_SCOPE_BOUNDARY", "ERR_HANDOFF_OWNER_SCOPE", "ERR_SEQUENCE_DEPENDENCY"
        })


class PackageContractTests(unittest.TestCase):
    def test_claude_frontmatter_and_required_resources(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---", 2)[1]
        description = next(
            line.split(":", 1)[1].strip()
            for line in frontmatter.splitlines()
            if line.startswith("description:")
        )
        self.assertLessEqual(len(description), 200)
        for relative in (
            "scripts/loop_marketing.py",
            "references/conversation-contract.md",
            "references/operating-guide.md",
            "references/data-contract.md",
        ):
            self.assertTrue((SKILL_ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
