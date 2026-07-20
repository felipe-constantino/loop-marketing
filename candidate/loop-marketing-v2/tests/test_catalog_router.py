"""P5 catalog and router contract tests (Python 3.9 stdlib only)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loop_marketing_runtime.catalog import CatalogLoader
from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.models import RouteNode, RoutePlan, RuntimeConfig
from loop_marketing_runtime.router import Router


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[2]
CANONICAL_ROOT = WORKSPACE_ROOT / "loop-marketing"


def runtime_config(
    *,
    library_root: Path = CANONICAL_ROOT,
    catalog_path: Path = PROJECT_ROOT / "data" / "tactic-catalog.json",
    relationship_path: Path = PROJECT_ROOT / "data" / "relationship-map.json",
) -> RuntimeConfig:
    return RuntimeConfig(
        library_root=library_root,
        catalog_path=catalog_path,
        relationship_path=relationship_path,
        role_matrix_path=PROJECT_ROOT / "data" / "role-matrix.json",
        routing_contract_path=PROJECT_ROOT / "data" / "routing-contract.json",
        state_root=PROJECT_ROOT / ".loop-marketing",
        contracts_root=PROJECT_ROOT / "contracts",
    )


def json_data(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def selected_safe_verbalizar(loader: CatalogLoader):
    return loader.select({
        "route_node_id": "node:verbalizar:safe",
        "role_id": "verbalizar",
        "maturity": "nascente",
        "requested_output_types": ["framework"],
        "need_tags": ["synthesize:brand"],
        "available_inputs": ["company-history-and-impact", "company-context"],
        "evidenced_prerequisites": ["purpose-evidence-available"],
        "requested_tactic_ids": ["lm.verbalizar.esclarecimento-de-objetivo-e-missao"],
    })


def mandatory_handoff_ids(loader: CatalogLoader, *tactic_ids: str):
    wanted = set(tactic_ids)
    return [
        handoff["handoff_id"]
        for role in ("verbalizar", "orientar", "ampliar", "refinar")
        for tactic in loader.metadata_for_role(role)
        if tactic["tactic_id"] in wanted
        for handoff in tactic["execution_policy"].get("mandatory_handoffs", [])
        if handoff.get("required") is True
    ]


def fact(claim_id: str, signals=None, **extra):
    value = {
        "claim_id": claim_id,
        "kind": "fact",
        "text": "Observed fact %s" % claim_id,
        "provenance": {
            "source_ref": "source:%s" % claim_id,
            "observed_at": "2026-07-17T12:00:00-03:00",
        },
        "confidence": "high",
    }
    if signals is not None:
        value["signals"] = signals
    value.update(extra)
    return value


def development_maturity_profile():
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
            key: {"value": value, "evidence_refs": ["source:maturity-profile"]}
            for key, value in values.items()
        }
    }


def base_request(observations=None, **updates):
    routed_observations = list(observations or [])
    routed_observations.append(fact("maturity-profile"))
    value = {
        "request_id": "request:router-test",
        "project_id": "project:router-test",
        "cycle_id": "cycle:router-test",
        "state_revision": 7,
        "user_goal": "Produce a read-only routed proposal.",
        "observations": routed_observations,
        "available_capabilities": {"runtime_overlay": True},
        "authorization_context": {"mode": "read_only", "external_write": False},
        "maturity": "em_desenvolvimento",
        "maturity_profile": development_maturity_profile(),
        "evaluate_new_work": False,
    }
    value.update(updates)
    if updates.get("maturity") == "unknown" and "maturity_profile" not in updates:
        value.pop("maturity_profile", None)
    return value


def complete_signal_facts(primary: str, *, score_signal: str, auxiliary=None):
    observations = []
    for pillar, rules in RouterScoringModel.items():
        values = {signal: signal == score_signal and pillar == primary for signal, _weight in rules}
        observations.append(fact("signals-%s" % pillar, values))
    if auxiliary:
        observations.append(fact("auxiliary", auxiliary))
    return observations


RouterScoringModel = {
    "verbalizar": (
        ("icp_undefined_or_generic", 3),
        ("value_proposition_not_differentiated", 3),
        ("language_differs_from_customer_language", 2),
        ("message_not_adapted_by_lifecycle", 2),
    ),
    "orientar": (
        ("segmentation_only_product_plan_or_demographic", 3),
        ("lifecycle_missing_transition_criteria", 3),
        ("eligibility_logic_missing", 2),
        ("churn_or_stagnation_detection_missing", 2),
    ),
    "ampliar": (
        ("same_message_all_channels", 3),
        ("cross_touchpoint_coordination_missing", 3),
        ("attribution_last_click_or_missing", 2),
        ("channels_added_without_reallocation", 2),
    ),
    "refinar": (
        ("no_performance_diagnosis_by_lifecycle_stage", 3),
        ("no_structured_tests", 3),
        ("optimization_only_reactive", 2),
        ("learning_not_recorded_between_cycles", 2),
    ),
}


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = CatalogLoader(runtime_config())

    def test_verify_all_100_ids_paths_and_hashes(self):
        result = self.loader.verify_catalog()
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(100, result.value["verified_tactic_count"])
        self.assertEqual(91, result.value["verified_relation_count"])
        self.assertEqual(
            {"verbalizar": 25, "orientar": 25, "ampliar": 25, "refinar": 25},
            {role: len(self.loader.metadata_for_role(role)) for role in ("verbalizar", "orientar", "ampliar", "refinar")},
        )

    def test_metadata_and_selection_read_no_prompt_bodies_then_load_one(self):
        canonical = CANONICAL_ROOT.resolve()
        original_open = Path.open
        body_reads = []

        def recording_open(path, *args, **kwargs):
            resolved = path.resolve()
            try:
                resolved.relative_to(canonical)
            except ValueError:
                pass
            else:
                body_reads.append(resolved)
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", recording_open):
            metadata = self.loader.metadata_for_role("verbalizar")
            selection = selected_safe_verbalizar(self.loader)
            self.assertEqual([], body_reads)
            self.assertEqual(25, len(metadata))
            loaded = self.loader.load_selected(selection)

        self.assertEqual(1, len(body_reads))
        self.assertEqual(1, len(loaded))
        self.assertIn("prompt_body", loaded[0])
        self.assertTrue(loaded[0]["prompt_body"].strip())

    def test_unknown_maturity_falls_back_to_base_method(self):
        selection = self.loader.select({
            "route_node_id": "node:unknown",
            "role_id": "verbalizar",
            "maturity": "unknown",
            "requested_tactic_ids": ["lm.verbalizar.esclarecimento-de-objetivo-e-missao"],
        })
        self.assertTrue(selection.base_method)
        self.assertEqual((), selection.tactic_refs)
        self.assertEqual("RTE-MAT-005", selection.ranking_trace[0]["rule"])

    def test_execution_policy_overlay_and_prerequisite_gates_fail_closed(self):
        request = {
            "route_node_id": "node:sidecar",
            "role_id": "verbalizar",
            "maturity": "nascente",
            "requested_tactic_ids": ["lm.verbalizar.criador-de-perfil-de-personalidade-da-marca"],
            "requested_output_types": ["framework"],
            "available_inputs": ["brand-communication-sample", "brand-context"],
            "evidenced_prerequisites": ["authentic-communication-exists", "sensitive-content-redacted"],
            "satisfied_handoffs": mandatory_handoff_ids(
                self.loader, "lm.verbalizar.criador-de-perfil-de-personalidade-da-marca"
            ),
        }
        without_overlay = self.loader.select(request)
        self.assertTrue(without_overlay.base_method)
        self.assertIn("runtime_overlay_unavailable", without_overlay.ranking_trace[0]["gate_reasons"])

        request["runtime_overlay_available"] = True
        selected = self.loader.select(request)
        self.assertFalse(selected.base_method)
        self.assertTrue(selected.requires_planner_review)

        request["planner_reviewed"] = True
        reviewed = self.loader.select(request)
        self.assertFalse(reviewed.requires_planner_review)
        self.assertEqual(1, len(self.loader.load_selected(reviewed)))

        request["evidenced_prerequisites"] = ["authentic-communication-exists"]
        missing_prerequisite = self.loader.select(request)
        self.assertTrue(missing_prerequisite.base_method)
        self.assertIn("prerequisites_missing", missing_prerequisite.ranking_trace[0]["gate_reasons"])

    def test_ranking_exact_output_then_need_tags_then_id(self):
        common_inputs = [
            "test-opportunity",
            "baseline-and-metric-contract",
            "instrumentation-sample-capability",
            "prior-experiments",
        ]
        common_prerequisites = [
            "testable-hypothesis",
            "valid-control-and-assignment",
            "predeclared-sample-duration-decision",
        ]
        selection = self.loader.select({
            "route_node_id": "node:rank",
            "role_id": "refinar",
            "maturity": "maduro",
            "requested_output_types": ["experiment_design"],
            "need_tags": ["validate:learning"],
            "available_inputs": common_inputs,
            "evidenced_prerequisites": common_prerequisites,
            "candidate_tactic_ids": [
                "lm.refinar.estrategista-de-teste-multi-variate",
                "lm.refinar.mecanismo-de-experimentacao-rapida",
            ],
            "max_tactics": 1,
        })
        self.assertEqual(
            "lm.refinar.mecanismo-de-experimentacao-rapida",
            selection.tactic_refs[0].tactic_id,
        )

        tie = self.loader.select({
            "route_node_id": "node:rank-tie",
            "role_id": "refinar",
            "maturity": "maduro",
            "requested_output_types": ["experiment_design"],
            "available_inputs": common_inputs,
            "evidenced_prerequisites": common_prerequisites,
            "candidate_tactic_ids": [
                "lm.refinar.estrategista-de-teste-multi-variate",
                "lm.refinar.mecanismo-de-experimentacao-rapida",
            ],
            "max_tactics": 1,
        })
        self.assertEqual(
            "lm.refinar.estrategista-de-teste-multi-variate",
            tie.tactic_refs[0].tactic_id,
        )

    def test_zero_one_two_and_rejected_three_cardinality(self):
        zero = self.loader.select({
            "route_node_id": "node:zero",
            "role_id": "verbalizar",
            "maturity": "nascente",
            "requested_output_types": ["does_not_exist"],
        })
        self.assertTrue(zero.base_method)
        self.assertEqual((), zero.tactic_refs)

        one = selected_safe_verbalizar(self.loader)
        self.assertEqual(1, len(one.tactic_refs))

        common_inputs = [
            "test-opportunity",
            "baseline-and-metric-contract",
            "instrumentation-sample-capability",
            "prior-experiments",
        ]
        common_prerequisites = [
            "testable-hypothesis",
            "valid-control-and-assignment",
            "predeclared-sample-duration-decision",
        ]
        first = "lm.refinar.designer-de-estrutura-de-teste-sistematica"
        second = "lm.refinar.coordenador-de-testes-entre-canais"
        two = self.loader.select({
            "route_node_id": "node:two",
            "role_id": "refinar",
            "maturity": "maduro",
            "requested_output_types": ["experiment_design"],
            "need_tags": ["design:test-portfolio", "coordinate:experiment"],
            "available_inputs": common_inputs,
            "evidenced_prerequisites": common_prerequisites,
            "runtime_overlay_available": True,
            "satisfied_handoffs": mandatory_handoff_ids(self.loader, first, second),
            "requested_tactic_ids": [first, second],
            "max_tactics": 2,
            "declared_dependencies": {first: [second]},
            "tactic_write_sets": {first: ["state.test.design"], second: ["state.test.coordination"]},
        })
        self.assertEqual(2, len(two.tactic_refs))

        with self.assertRaises(LoopRuntimeError) as raised:
            self.loader.select({
                "route_node_id": "node:three",
                "role_id": "refinar",
                "maturity": "maduro",
                "requested_tactic_ids": [first, second, "lm.refinar.estrategista-de-teste-multi-variate"],
            })
        self.assertEqual("ERR_TACTIC_CARDINALITY", raised.exception.code)

    def test_confirmed_relations_are_normative_and_proposed_are_audit_only(self):
        confirmed = self.loader._confirmed_relations(
            "lm.refinar.designer-de-estrutura-de-teste-sistematica",
            "lm.refinar.coordenador-de-testes-entre-canais",
        )
        self.assertTrue(any(item["relation_type"] == "complements" for item in confirmed))

        relationship = json_data(PROJECT_ROOT / "data" / "relationship-map.json")
        relationship["relations"].append({
            "relation_id": "rel-proposed-test-only",
            "relation_type": "collides_with",
            "from_tactic_id": "lm.verbalizar.esclarecimento-de-objetivo-e-missao",
            "to_tactic_id": "lm.verbalizar.criador-de-perfil-de-personalidade-da-marca",
            "directional": False,
            "rationale": "Test-only proposed relation.",
            "routing_effect": "never_auto_co_select",
            "confidence": "low",
            "review_status": "proposed",
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relationships.json"
            path.write_text(json.dumps(relationship), encoding="utf-8")
            loader = CatalogLoader(runtime_config(relationship_path=path))
            self.assertEqual([], loader._confirmed_relations(
                "lm.verbalizar.esclarecimento-de-objetivo-e-missao",
                "lm.verbalizar.criador-de-perfil-de-personalidade-da-marca",
            ))

    def test_hash_drift_rejects_progressive_loading(self):
        selection = selected_safe_verbalizar(self.loader)
        ref = selection.tactic_refs[0]
        tampered = type(ref)(ref.tactic_id, ref.canonical_path, "0" * 64, ref.selection_reason)
        selection = type(selection)(
            route_node_id=selection.route_node_id,
            role_id=selection.role_id,
            tactic_refs=(tampered,),
            ranking_trace=selection.ranking_trace,
            base_method=False,
        )
        with self.assertRaises(LoopRuntimeError) as raised:
            self.loader.load_selected(selection)
        self.assertEqual("ERR_CANONICAL_LIBRARY_DRIFT", raised.exception.code)

        catalog = json_data(PROJECT_ROOT / "data" / "tactic-catalog.json")
        catalog["baseline"]["source_commit"] = "0" * 40
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            anchored = CatalogLoader(runtime_config(catalog_path=catalog_path))
            result = anchored.verify_catalog()
        self.assertFalse(result.ok)
        self.assertEqual("ERR_CANONICAL_LIBRARY_DRIFT", result.primary_code)


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = CatalogLoader(runtime_config())
        cls.role_matrix = json_data(PROJECT_ROOT / "data" / "role-matrix.json")
        cls.routing_contract = json_data(PROJECT_ROOT / "data" / "routing-contract.json")
        cls.router = Router(cls.role_matrix, cls.routing_contract, cls.loader)

    def test_only_sourced_facts_score(self):
        observations = [
            fact("scored", {"icp_undefined_or_generic": True}),
            {
                "claim_id": "interpretation",
                "kind": "user_interpretation",
                "text": "I think there is no structured testing.",
                "provenance": {},
                "confidence": "medium",
                "signals": {"no_structured_tests": True},
            },
        ]
        scores = self.router.score_bottlenecks(base_request(observations))
        self.assertEqual(3, scores["pillar_scores"]["verbalizar"]["confirmed_score"])
        self.assertEqual(0, scores["pillar_scores"]["refinar"]["confirmed_score"])
        refinar_signal = next(
            item for item in scores["pillar_scores"]["refinar"]["signals"]
            if item["signal"] == "no_structured_tests"
        )
        self.assertEqual("unknown", refinar_signal["state"])

    def test_unsourced_fact_and_unrationalized_hypothesis_reject(self):
        request = base_request([{
            "claim_id": "bad-fact",
            "kind": "fact",
            "text": "Unsupported fact.",
            "provenance": {},
            "confidence": "high",
        }])
        with self.assertRaises(LoopRuntimeError) as raised:
            self.router.normalize_request(request)
        self.assertEqual("ERR_CLAIM_PROVENANCE_MISSING", raised.exception.code)

        request["observations"][0].update({"kind": "hypothesis", "confidence": "low"})
        with self.assertRaises(LoopRuntimeError) as raised:
            self.router.normalize_request(request)
        self.assertEqual("ERR_CLAIM_PROVENANCE_MISSING", raised.exception.code)

    def test_exact_bottleneck_precedence_root_cause_then_dominance(self):
        observations = complete_signal_facts("verbalizar", score_signal="icp_undefined_or_generic")
        observations.append(fact("root-support"))
        request = base_request(
            observations,
            root_cause_candidate={
                "pillar": "orientar",
                "confidence": "medium",
                "supporting_fact_refs": ["root-support"],
                "counter_evidence_refs": [],
            },
        )
        plan = self.router.plan(request)
        self.assertEqual("ready", plan.route_status)
        self.assertEqual("orientar", plan.primary_bottleneck["pillar"])
        self.assertEqual("RTE-BOT-002", plan.primary_bottleneck["selection_rule_id"])

        request.pop("root_cause_candidate")
        plan = self.router.plan(request)
        self.assertEqual("verbalizar", plan.primary_bottleneck["pillar"])
        self.assertEqual("RTE-BOT-003", plan.primary_bottleneck["selection_rule_id"])

        untrusted = self.router.plan(base_request(
            observations,
            maturity="avancado",
            maturity_profile={},
            requested_roles=["verbalizar"],
        ))
        self.assertEqual("unknown", untrusted.maturity)
        self.assertTrue(untrusted.nodes[0].selection.base_method)

    def test_outside_loop_prerequisite_has_highest_precedence(self):
        request = base_request(
            complete_signal_facts("verbalizar", score_signal="icp_undefined_or_generic"),
            outside_loop_prerequisites=[{
                "prerequisite_id": "instrumentation",
                "required": True,
                "status": "missing",
            }],
        )
        plan = self.router.plan(request)
        self.assertEqual("blocked", plan.route_status)
        self.assertIsNone(plan.primary_bottleneck)
        self.assertEqual(("ERR_OUTSIDE_LOOP_PREREQUISITE",), plan.rejection_codes)
        self.assertEqual((), plan.nodes)

    def test_tied_or_insufficient_evidence_needs_evidence_and_refinar_minimum(self):
        observations = []
        for pillar, rules in RouterScoringModel.items():
            values = {signal: False for signal, _weight in rules}
            if pillar in {"verbalizar", "refinar"}:
                values[rules[0][0]] = True
            observations.append(fact("tie-%s" % pillar, values))
        plan = self.router.plan(base_request(observations, maturity="unknown"))
        self.assertEqual("needs_evidence", plan.route_status)
        self.assertIsNone(plan.primary_bottleneck)
        self.assertIn("ERR_BOTTLENECK_AMBIGUOUS", plan.rejection_codes)
        self.assertEqual(1, len(plan.nodes))
        self.assertEqual("refinar", plan.nodes[0].role_id)
        self.assertEqual("minimo_viavel", plan.nodes[0].mode)
        self.assertTrue(plan.nodes[0].selection.base_method)
        self.assertEqual(plan.state_revision, plan.nodes[0].state_revision)

    def test_refinar_tie_checkpoint_precedes_planner_and_structural_reroute(self):
        observations = []
        for pillar, rules in RouterScoringModel.items():
            values = {signal: False for signal, _weight in rules}
            if pillar in {"verbalizar", "refinar"}:
                values[rules[0][0]] = True
            observations.append(fact("measurable-tie-%s" % pillar, values))
        observations.append(fact(
            "measurable-data",
            {"measurable_data_exists": True, "failure_locus_unknown": True},
        ))
        plan = self.router.plan(base_request(
            observations,
            requested_roles=["verbalizar"],
        ))
        self.assertEqual("ready", plan.route_status)
        self.assertEqual("RTE-BOT-005", plan.primary_bottleneck["selection_rule_id"])
        self.assertEqual(["refinar", "loop_planning", "verbalizar"], [node.role_id for node in plan.nodes])
        self.assertEqual((plan.nodes[0].route_node_id,), plan.nodes[1].depends_on)
        self.assertEqual((plan.nodes[1].route_node_id,), plan.nodes[2].depends_on)
        self.assertEqual({plan.state_revision}, {node.state_revision for node in plan.nodes})

    def test_sequence_and_parallel_wave_preserve_revision(self):
        observations = complete_signal_facts(
            "ampliar",
            score_signal="same_message_all_channels",
            auxiliary={"message_validated": False, "audience_eligibility_defined": False},
        )
        request = base_request(
            observations,
            requested_roles=["ampliar"],
            evaluate_new_work=True,
        )
        plan = self.router.plan(request)
        self.assertEqual("ready", plan.route_status)
        by_role = {node.role_id: node for node in plan.nodes}
        self.assertEqual({"verbalizar", "orientar", "ampliar", "refinar"}, set(by_role))
        self.assertEqual({plan.state_revision}, {node.state_revision for node in plan.nodes})
        self.assertEqual(
            {by_role["verbalizar"].route_node_id, by_role["orientar"].route_node_id},
            set(by_role["ampliar"].depends_on),
        )
        self.assertEqual(
            {by_role["verbalizar"].route_node_id, by_role["orientar"].route_node_id, by_role["ampliar"].route_node_id},
            set(by_role["refinar"].depends_on),
        )
        self.assertIn(
            (by_role["verbalizar"].route_node_id, by_role["orientar"].route_node_id),
            plan.parallel_groups,
        )
        self.assertTrue(self.router.validate_parallelism(plan).ok)

    def test_parallel_write_collision_and_revision_mismatch_reject(self):
        first = RouteNode(
            route_node_id="node:first",
            role_id="verbalizar",
            objective="First proposal.",
            mode="parcial",
            state_revision=7,
            write_set=("state.proposals.shared",),
        )
        second = RouteNode(
            route_node_id="node:second",
            role_id="orientar",
            objective="Second proposal.",
            mode="parcial",
            state_revision=7,
            write_set=("state.proposals.shared",),
        )
        plan = RoutePlan(
            project_ref="project:test",
            cycle_id="cycle:test",
            state_revision=7,
            route_status="ready",
            maturity="em_desenvolvimento",
            primary_bottleneck={"pillar": "verbalizar"},
            nodes=(first, second),
            parallel_groups=(("node:first", "node:second"),),
        )
        result = self.router.validate_parallelism(plan)
        self.assertFalse(result.ok)
        self.assertEqual("ERR_PARALLEL_WRITE_COLLISION", result.primary_code)

        stale = RouteNode(
            route_node_id="node:stale",
            role_id="orientar",
            objective="Stale proposal.",
            mode="parcial",
            state_revision=8,
            write_set=("state.proposals.orientar",),
        )
        stale_plan = RoutePlan(
            project_ref=plan.project_ref,
            cycle_id=plan.cycle_id,
            state_revision=7,
            route_status="ready",
            maturity=plan.maturity,
            primary_bottleneck=plan.primary_bottleneck,
            nodes=(first, stale),
            parallel_groups=(("node:first", "node:stale"),),
        )
        result = self.router.validate_parallelism(stale_plan)
        self.assertFalse(result.ok)
        self.assertEqual("ERR_PARALLELISM_UNSAFE", result.primary_code)


if __name__ == "__main__":
    unittest.main()
