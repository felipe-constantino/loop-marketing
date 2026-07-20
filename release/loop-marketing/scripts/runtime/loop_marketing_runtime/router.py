"""Deterministic, read-only Loop Marketing routing.

The router treats user intent as intent and observations as claims.  Only
provenance-complete facts may set diagnostic signals; no method in this module
writes state or invokes an external system.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .catalog import CatalogLoader
from .errors import LoopRuntimeError, require
from .models import RouteNode, RoutePlan, TacticSelection, ValidationResult


_ROLES = ("loop_planning", "verbalizar", "orientar", "ampliar", "refinar")
_PILLARS = ("verbalizar", "orientar", "ampliar", "refinar")
_CLAIM_KINDS = ("fact", "user_interpretation", "symptom", "hypothesis")
_CONFIDENCE = ("low", "medium", "high")
_MATURITY = ("nascente", "em_desenvolvimento", "maduro", "avancado", "unknown")
_MATURITY_DIMENSIONS = (
    "lifecycle_level",
    "segmentation_level",
    "scoring_level",
    "automated_flow_count",
    "structured_testing_level",
    "personalization_level",
    "attribution_level",
    "prediction_capability",
    "realtime_optimization",
    "accumulated_learning",
)
_SCORING_MODEL: Dict[str, Tuple[Tuple[str, int], ...]] = {
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
_KNOWN_SIGNALS = {signal for rules in _SCORING_MODEL.values() for signal, _weight in rules}
_AUXILIARY_SIGNALS = {
    "message_validated",
    "audience_eligibility_defined",
    "measurable_data_exists",
    "measurement_readiness",
    "failure_locus_unknown",
}
_DEFAULT_OUTPUT = {
    "verbalizar": "message_system",
    "orientar": "segmentation_model",
    "ampliar": "channel_plan",
    "refinar": "analysis",
}


def _as_strings(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(key) for key, included in value.items() if included)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _fact_evidence(provenance: Mapping[str, Any]) -> Tuple[str, ...]:
    values: List[str] = []
    values.extend(_as_strings(provenance.get("evidence_refs")))
    values.extend(_as_strings(provenance.get("evidence_ref")))
    source_ref = provenance.get("source_ref")
    if source_ref:
        values.append(str(source_ref))
    return tuple(dict.fromkeys(values))


class Router:
    """Apply P2 normalization, bottleneck precedence, and safe route ordering."""

    def __init__(self, role_matrix: dict, routing_contract: dict, catalog: CatalogLoader):
        require(isinstance(role_matrix, dict), "ERR_INPUT_REQUIRED", "role_matrix must be an object.")
        require(isinstance(routing_contract, dict), "ERR_INPUT_REQUIRED", "routing_contract must be an object.")
        require(isinstance(catalog, CatalogLoader), "ERR_INPUT_REQUIRED", "catalog must be CatalogLoader.")
        self.role_matrix = copy.deepcopy(role_matrix)
        self.routing_contract = copy.deepcopy(routing_contract)
        self.catalog = catalog
        self._validate_normative_inputs()

    def _validate_normative_inputs(self) -> None:
        enum_roles = self.routing_contract.get("canonical_enums", {}).get("roles")
        require(enum_roles == list(_ROLES), "ERR_INPUT_REQUIRED", "Routing contract canonical roles differ from runtime.")
        roles = self.role_matrix.get("roles")
        require(isinstance(roles, list), "ERR_INPUT_REQUIRED", "Role matrix roles must be an array.")
        role_ids = [item.get("canonical_role_id") for item in roles if isinstance(item, Mapping)]
        require(role_ids == list(_ROLES), "ERR_INPUT_REQUIRED", "Role matrix canonical roles differ from runtime.")

        source_model = (
            self.routing_contract.get("decision_rules", {})
            .get("bottleneck_selection", {})
            .get("scoring_model")
        )
        require(isinstance(source_model, Mapping), "ERR_INPUT_REQUIRED", "Routing scoring model is missing.")
        normalized = {
            pillar: tuple((str(row.get("signal")), int(row.get("weight"))) for row in source_model.get(pillar, ()))
            for pillar in _PILLARS
        }
        require(normalized == _SCORING_MODEL, "ERR_INPUT_REQUIRED", "Runtime scoring model differs from P2 contract.")

    @staticmethod
    def _required_request_fields() -> Tuple[str, ...]:
        return (
            "request_id",
            "project_id",
            "state_revision",
            "user_goal",
            "observations",
            "available_capabilities",
            "authorization_context",
        )

    def normalize_request(self, request: dict) -> dict:
        """Validate the P2 input contract and normalize claims without inference."""

        require(isinstance(request, dict), "ERR_INPUT_REQUIRED", "Route request must be an object.")
        missing = [field for field in self._required_request_fields() if field not in request]
        require(not missing, "ERR_INPUT_REQUIRED", "Required route fields are missing.", fields=missing)
        require(isinstance(request["request_id"], str) and bool(request["request_id"].strip()),
                "ERR_INPUT_REQUIRED", "request_id must be a non-empty string.", field="request_id")
        require(isinstance(request["project_id"], str) and bool(request["project_id"].strip()),
                "ERR_INPUT_REQUIRED", "project_id must be a non-empty string.", field="project_id")
        require(isinstance(request["state_revision"], int) and not isinstance(request["state_revision"], bool)
                and request["state_revision"] >= 0,
                "ERR_INPUT_REQUIRED", "state_revision must be a non-negative integer.", field="state_revision")
        require(isinstance(request["user_goal"], str) and bool(request["user_goal"].strip()),
                "ERR_INPUT_REQUIRED", "user_goal must be a non-empty string.", field="user_goal")
        require(isinstance(request["observations"], list),
                "ERR_INPUT_REQUIRED", "observations must be an array.", field="observations")
        require(isinstance(request["available_capabilities"], (dict, list)),
                "ERR_INPUT_REQUIRED", "available_capabilities must be structured.", field="available_capabilities")
        require(isinstance(request["authorization_context"], dict),
                "ERR_INPUT_REQUIRED", "authorization_context must be an object.", field="authorization_context")

        normalized_claims: List[Dict[str, Any]] = []
        by_kind: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in _CLAIM_KINDS}
        claim_ids: Set[str] = set()
        signal_sources: Dict[str, List[Tuple[bool, str, Tuple[str, ...]]]] = {}
        failure_loci: List[Tuple[str, str, Tuple[str, ...]]] = []

        for index, raw in enumerate(request["observations"]):
            require(isinstance(raw, dict), "ERR_INPUT_REQUIRED", "Every observation must be an object.", index=index)
            required = ("claim_id", "kind", "text", "provenance", "confidence")
            claim_missing = [field for field in required if field not in raw]
            require(not claim_missing, "ERR_INPUT_REQUIRED", "Observation fields are missing.", index=index, fields=claim_missing)
            claim_id = raw["claim_id"]
            kind = raw["kind"]
            text = raw["text"]
            provenance = raw["provenance"]
            confidence = raw["confidence"]
            require(isinstance(claim_id, str) and bool(claim_id.strip()) and claim_id not in claim_ids,
                    "ERR_INPUT_REQUIRED", "claim_id must be non-empty and unique.", index=index, claim_id=claim_id)
            require(kind in _CLAIM_KINDS, "ERR_INPUT_REQUIRED", "Unknown claim kind.", index=index, kind=kind)
            require(isinstance(text, str) and bool(text.strip()),
                    "ERR_INPUT_REQUIRED", "Claim text must be non-empty.", index=index)
            require(isinstance(provenance, dict),
                    "ERR_INPUT_REQUIRED", "Claim provenance must be an object.", index=index)
            require(confidence in _CONFIDENCE, "ERR_INPUT_REQUIRED", "Unknown claim confidence.", index=index)
            if kind == "fact":
                require(bool(provenance.get("source_ref")) and bool(provenance.get("observed_at")),
                        "ERR_CLAIM_PROVENANCE_MISSING", "Fact lacks source_ref or observed_at.",
                        retryable=True, claim_id=claim_id)
            if kind == "hypothesis":
                require(bool(provenance.get("rationale")),
                        "ERR_CLAIM_PROVENANCE_MISSING", "Hypothesis lacks rationale.",
                        retryable=True, claim_id=claim_id)

            claim = copy.deepcopy(raw)
            claim["claim_id"] = claim_id.strip()
            claim["text"] = text.strip()
            claim["evidence_refs"] = list(_fact_evidence(provenance)) if kind == "fact" else []
            claim_ids.add(claim_id)
            normalized_claims.append(claim)
            by_kind[kind].append(claim)

            if kind != "fact":
                continue
            evidence = tuple(claim["evidence_refs"])
            raw_signals: Dict[str, Any] = {}
            if isinstance(raw.get("signals"), Mapping):
                raw_signals.update(raw["signals"])
            signal_name = raw.get("signal", raw.get("signal_id"))
            if signal_name is not None:
                raw_signals[str(signal_name)] = raw.get("value", raw.get("signal_value", True))
            for name, value in raw_signals.items():
                if name not in _KNOWN_SIGNALS and name not in _AUXILIARY_SIGNALS:
                    continue
                if isinstance(value, bool):
                    signal_sources.setdefault(name, []).append((value, claim_id, evidence))
            locus = raw.get("failure_locus")
            if locus in _PILLARS:
                failure_loci.append((str(locus), claim_id, evidence))

        signal_values: Dict[str, Dict[str, Any]] = {}
        for signal in sorted(_KNOWN_SIGNALS.union(_AUXILIARY_SIGNALS)):
            sources = signal_sources.get(signal, [])
            values = {item[0] for item in sources}
            value: Optional[bool] = next(iter(values)) if len(values) == 1 else None
            signal_values[signal] = {
                "value": value,
                "claim_refs": [item[1] for item in sources],
                "evidence_refs": list(dict.fromkeys(ref for item in sources for ref in item[2])),
                "conflict": len(values) > 1,
            }

        normalized = copy.deepcopy(request)
        normalized["observations"] = normalized_claims
        normalized["claims_by_kind"] = by_kind
        normalized["signal_values"] = signal_values
        normalized["failure_loci"] = [
            {"pillar": pillar, "claim_ref": claim_ref, "evidence_refs": list(evidence)}
            for pillar, claim_ref, evidence in failure_loci
        ]
        normalized["normalization_rules"] = ["RTE-NORM-001", "RTE-NORM-002", "RTE-NORM-003"]
        normalized["_loop_runtime_normalized"] = True
        return normalized

    def _normalized(self, request: dict) -> dict:
        return self.normalize_request(request)

    def score_bottlenecks(self, request: dict) -> dict:
        """Score P2 pillar signals; non-facts and unsourced facts never contribute."""

        normalized = self._normalized(request)
        scores: Dict[str, Dict[str, Any]] = {}
        for pillar in _PILLARS:
            confirmed_score = 0
            possible_score = 0
            signals: List[Dict[str, Any]] = []
            for signal, weight in _SCORING_MODEL[pillar]:
                source = normalized["signal_values"][signal]
                value = source["value"]
                if value is True:
                    confirmed_score += weight
                    possible_score += weight
                    state = "true"
                elif value is False:
                    state = "false"
                else:
                    possible_score += weight
                    state = "unknown"
                signals.append({
                    "signal": signal,
                    "weight": weight,
                    "state": state,
                    "claim_refs": list(source["claim_refs"]),
                    "evidence_refs": list(source["evidence_refs"]),
                })
            scores[pillar] = {
                "pillar": pillar,
                "confirmed_score": confirmed_score,
                "possible_score": possible_score,
                "signals": signals,
                "all_signals_known": all(item["state"] != "unknown" for item in signals),
            }
        evidence_refs = list(dict.fromkeys(
            evidence
            for claim in normalized["claims_by_kind"]["fact"]
            for evidence in claim["evidence_refs"]
        ))
        return {
            "pillar_scores": scores,
            "evidence_refs": evidence_refs,
            "signal_values": copy.deepcopy(normalized["signal_values"]),
            "based_on_state_revision": normalized["state_revision"],
        }

    @staticmethod
    def _unresolved_outside_prerequisites(request: Mapping[str, Any]) -> List[Dict[str, Any]]:
        raw = request.get("outside_loop_prerequisites", ())
        result: List[Dict[str, Any]] = []
        if not isinstance(raw, (list, tuple)):
            return result
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            status = item.get("status")
            satisfied = item.get("satisfied", item.get("available"))
            unresolved = not (
                satisfied is True or status in {"satisfied", "resolved", "available"}
            )
            if item.get("required", True) and unresolved:
                result.append(dict(item))
        return result

    @staticmethod
    def _root_cause_candidate(request: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        direct = request.get("root_cause_candidate")
        if isinstance(direct, Mapping):
            return direct
        prior = request.get("prior_diagnosis")
        if isinstance(prior, Mapping) and isinstance(prior.get("root_cause_candidate"), Mapping):
            return prior["root_cause_candidate"]
        return None

    @staticmethod
    def _fact_reference_sets(normalized: Mapping[str, Any]) -> Tuple[Set[str], Set[str]]:
        claim_refs: Set[str] = set()
        evidence_refs: Set[str] = set()
        for fact in normalized["claims_by_kind"]["fact"]:
            claim_refs.add(str(fact["claim_id"]))
            evidence_refs.update(_as_strings(fact.get("evidence_refs")))
        return claim_refs, evidence_refs

    def _select_bottleneck(self, normalized: dict, scores: dict) -> Dict[str, Any]:
        unresolved = self._unresolved_outside_prerequisites(normalized)
        if unresolved:
            return {
                "route_status": "blocked",
                "primary_bottleneck": None,
                "rule_id": "RTE-BOT-001",
                "rejection_codes": ("ERR_OUTSIDE_LOOP_PREREQUISITE",),
                "outside_loop_prerequisites": unresolved,
            }

        fact_claims, fact_evidence = self._fact_reference_sets(normalized)
        candidate = self._root_cause_candidate(normalized)
        if candidate is not None:
            pillar = candidate.get("pillar")
            confidence = candidate.get("confidence")
            support = set(_as_strings(candidate.get("supporting_fact_refs", candidate.get("supporting_evidence_refs"))))
            counters = set(_as_strings(candidate.get("stronger_counter_evidence_refs", candidate.get("counter_evidence_refs"))))
            supported = bool(support.intersection(fact_claims.union(fact_evidence)))
            if pillar in _PILLARS and confidence in {"medium", "high"} and supported and not counters:
                return self._ready_bottleneck(str(pillar), "RTE-BOT-002", sorted(support.intersection(fact_claims.union(fact_evidence))))

        pillar_scores = scores["pillar_scores"]
        for pillar in _PILLARS:
            confirmed = pillar_scores[pillar]["confirmed_score"]
            if confirmed > 0 and all(
                confirmed > pillar_scores[other]["possible_score"] for other in _PILLARS if other != pillar
            ):
                evidence = self._pillar_evidence(pillar_scores[pillar])
                return self._ready_bottleneck(pillar, "RTE-BOT-003", evidence)

        top_score = max(pillar_scores[pillar]["confirmed_score"] for pillar in _PILLARS)
        top = [pillar for pillar in _PILLARS if pillar_scores[pillar]["confirmed_score"] == top_score]
        if top_score > 0 and len(top) == 1 and pillar_scores[top[0]]["all_signals_known"]:
            evidence = self._pillar_evidence(pillar_scores[top[0]])
            return self._ready_bottleneck(top[0], "RTE-BOT-004", evidence)

        measurable = normalized["signal_values"]["measurable_data_exists"]["value"] is True
        failure_unknown = normalized["signal_values"]["failure_locus_unknown"]["value"] is True or not normalized["failure_loci"]
        if top_score > 0 and len(top) > 1 and "refinar" in top and failure_unknown and measurable:
            evidence = list(dict.fromkeys(
                normalized["signal_values"]["measurable_data_exists"]["evidence_refs"]
                + [ref for pillar in top for ref in self._pillar_evidence(pillar_scores[pillar])]
            ))
            return self._ready_bottleneck("refinar", "RTE-BOT-005", evidence)

        measurement_ready = normalized["signal_values"]["measurement_readiness"]["value"]
        unique_loci = {item["pillar"] for item in normalized["failure_loci"]}
        if len(unique_loci) == 1 and unique_loci <= {"verbalizar", "orientar", "ampliar"} and measurement_ready is False:
            pillar = next(iter(unique_loci))
            evidence = list(dict.fromkeys(
                ref for item in normalized["failure_loci"] for ref in item["evidence_refs"]
            ))
            return self._ready_bottleneck(pillar, "RTE-BOT-006", evidence)

        return {
            "route_status": "needs_evidence",
            "primary_bottleneck": None,
            "rule_id": "RTE-BOT-007",
            "rejection_codes": ("ERR_BOTTLENECK_AMBIGUOUS",),
        }

    @staticmethod
    def _derive_maturity(normalized: Mapping[str, Any]) -> str:
        """Recompute P2 maturity from a complete evidence-bound profile.

        A free-form ``maturity`` enum is intentionally ignored. Recorded
        classification reuse needs freshness metadata not present in P5 state,
        so the safe runtime behavior is recomputation or ``unknown``.
        """

        profile = normalized.get("maturity_profile")
        dimensions = profile.get("dimensions") if isinstance(profile, Mapping) else None
        if not isinstance(dimensions, Mapping):
            return "unknown"
        fact_evidence = {
            reference
            for fact in normalized.get("claims_by_kind", {}).get("fact", [])
            for reference in _as_strings(fact.get("evidence_refs"))
        }
        values: Dict[str, Any] = {}
        for dimension in _MATURITY_DIMENSIONS:
            item = dimensions.get(dimension)
            if not isinstance(item, Mapping) or "value" not in item:
                return "unknown"
            references = set(_as_strings(item.get("evidence_refs")))
            if not references or not references.issubset(fact_evidence):
                return "unknown"
            values[dimension] = item["value"]

        if (
            values["attribution_level"] == "multi_touch"
            and values["prediction_capability"] == "active"
            and values["realtime_optimization"] == "active"
            and values["accumulated_learning"] is True
        ):
            return "avancado"
        if (
            values["lifecycle_level"] == "mapped_with_transition_criteria"
            and values["scoring_level"] == "active"
            and values["personalization_level"] in {"by_stage", "predictive"}
            and values["structured_testing_level"] == "regular"
        ):
            return "maduro"
        development_conditions = (
            values["lifecycle_level"] == "partial",
            values["segmentation_level"] in {"behavioral_basic", "behavioral_advanced"},
            values["scoring_level"] == "rudimentary",
            isinstance(values["automated_flow_count"], int)
            and not isinstance(values["automated_flow_count"], bool)
            and values["automated_flow_count"] >= 3,
            values["structured_testing_level"] == "occasional",
        )
        if sum(bool(item) for item in development_conditions) >= 2:
            return "em_desenvolvimento"
        return "nascente"

    @staticmethod
    def _pillar_evidence(score: Mapping[str, Any]) -> List[str]:
        return list(dict.fromkeys(
            ref for signal in score["signals"] if signal["state"] == "true" for ref in signal["evidence_refs"]
        ))

    @staticmethod
    def _ready_bottleneck(pillar: str, rule_id: str, evidence_refs: Sequence[str]) -> Dict[str, Any]:
        return {
            "route_status": "ready",
            "primary_bottleneck": {
                "pillar": pillar,
                "accepted_by": "loop_planning",
                "selection_rule_id": rule_id,
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
            },
            "rule_id": rule_id,
            "rejection_codes": (),
        }

    @staticmethod
    def _role_request(request: Mapping[str, Any], role_id: str) -> Dict[str, Any]:
        value = request.get("role_requests", {})
        if isinstance(value, Mapping) and isinstance(value.get(role_id), Mapping):
            return dict(value[role_id])
        return {}

    @staticmethod
    def _capability(request: Mapping[str, Any], name: str) -> bool:
        capabilities = request.get("available_capabilities")
        if isinstance(capabilities, Mapping):
            value = capabilities.get(name)
            if isinstance(value, Mapping):
                return bool(value.get("available", value.get("enabled", False)))
            return bool(value)
        return name in _as_strings(capabilities)

    def _selection_request(
        self,
        request: Mapping[str, Any],
        role_id: str,
        node_id: str,
        maturity: str,
        requested_output_types: Sequence[str],
    ) -> Dict[str, Any]:
        role_request = self._role_request(request, role_id)
        value: Dict[str, Any] = {
            "route_node_id": node_id,
            "role_id": role_id,
            "maturity": maturity,
            "requested_output_types": list(requested_output_types),
            "need_tags": role_request.get("need_tags", ()),
            "available_inputs": role_request.get("available_inputs", request.get("available_inputs", ())),
            "evidenced_prerequisites": role_request.get(
                "evidenced_prerequisites", request.get("evidenced_prerequisites", ())
            ),
            "active_contraindications": role_request.get(
                "active_contraindications", request.get("active_contraindications", ())
            ),
            "satisfied_handoffs": role_request.get(
                "satisfied_handoffs", request.get("satisfied_handoffs", ())
            ),
            "runtime_overlay_available": role_request.get(
                "runtime_overlay_available", self._capability(request, "runtime_overlay")
            ),
            "planner_reviewed": role_request.get("planner_reviewed", request.get("planner_reviewed", False)),
        }
        for key in (
            "requested_tactic_ids",
            "tactic_ids",
            "candidate_tactic_ids",
            "max_tactics",
            "requested_tactic_count",
            "declared_dependencies",
            "tactic_write_sets",
        ):
            if key in role_request:
                value[key] = role_request[key]
        return value

    def _build_nodes(self, normalized: dict, decision: dict, maturity: str) -> Tuple[RouteNode, ...]:
        revision = normalized["state_revision"]
        cycle_id = str(normalized.get("cycle_id", normalized["request_id"]))
        if decision["route_status"] == "blocked":
            return ()
        if decision["route_status"] == "needs_evidence":
            node_id = "%s:refinar:data-audit" % cycle_id
            selection = self.catalog.select({
                "route_node_id": node_id,
                "role_id": "refinar",
                "maturity": "unknown",
                "requested_output_types": ["analysis"],
            })
            return (RouteNode(
                route_node_id=node_id,
                role_id="refinar",
                objective="Audit available data and define collection requirements without inventing a diagnosis.",
                mode="minimo_viavel",
                state_revision=revision,
                write_set=("state.proposals.refinar.data_gap_plan",),
                requested_output_types=("analysis",),
                selection=selection,
            ),)

        if decision.get("rule_id") == "RTE-BOT-005":
            requested_roles = [
                role for role in _as_strings(normalized.get("requested_roles"))
                if role in {"verbalizar", "orientar", "ampliar"}
            ]
            requested_roles = list(dict.fromkeys(requested_roles))
            refinar_id = "%s:01:refinar-diagnostic" % cycle_id
            planner_id = "%s:02:loop-planning-reroute" % cycle_id
            refinar_selection = self.catalog.select(self._selection_request(
                normalized, "refinar", refinar_id, maturity, ("analysis",)
            ))
            nodes: List[RouteNode] = [
                RouteNode(
                    route_node_id=refinar_id,
                    role_id="refinar",
                    objective="Localize the measurable failure locus before structural work.",
                    mode="minimo_viavel",
                    state_revision=revision,
                    write_set=("state.proposals.refinar.failure_locus",),
                    requested_output_types=("analysis",),
                    selection=refinar_selection,
                ),
                RouteNode(
                    route_node_id=planner_id,
                    role_id="loop_planning",
                    objective="Cross-validate the diagnostic checkpoint and accept the structural reroute.",
                    mode="parcial",
                    state_revision=revision,
                    depends_on=(refinar_id,),
                    write_set=("state.proposals.loop_planning.reroute",),
                    requested_output_types=("route_plan",),
                    selection=None,
                ),
            ]
            for index, role in enumerate(requested_roles, 3):
                role_request = self._role_request(normalized, role)
                node_id = str(role_request.get("route_node_id", "%s:%02d:%s" % (cycle_id, index, role)))
                outputs = _as_strings(role_request.get("requested_output_types")) or (_DEFAULT_OUTPUT[role],)
                selection = self.catalog.select(self._selection_request(
                    normalized, role, node_id, maturity, outputs
                ))
                nodes.append(RouteNode(
                    route_node_id=node_id,
                    role_id=role,
                    objective=str(role_request.get("objective", normalized["user_goal"])),
                    mode=str(role_request.get("mode", "parcial")),
                    state_revision=revision,
                    depends_on=(planner_id,),
                    write_set=tuple(_as_strings(role_request.get("write_set")) or (
                        "state.proposals.%s.%s" % (role, node_id.replace(":", "-")),
                    )),
                    requested_output_types=tuple(outputs),
                    selection=selection,
                ))
            return tuple(nodes)

        primary = decision["primary_bottleneck"]["pillar"]
        requested_roles = [role for role in _as_strings(normalized.get("requested_roles")) if role in _PILLARS]
        if primary not in requested_roles:
            requested_roles.insert(0, primary)
        requested_roles = list(dict.fromkeys(requested_roles))

        message_validated = normalized["signal_values"]["message_validated"]["value"]
        audience_defined = normalized["signal_values"]["audience_eligibility_defined"]["value"]
        if "ampliar" in requested_roles and message_validated is False and "verbalizar" not in requested_roles:
            requested_roles.insert(0, "verbalizar")
        if "ampliar" in requested_roles and audience_defined is False and "orientar" not in requested_roles:
            insert_at = 1 if requested_roles and requested_roles[0] == "verbalizar" else 0
            requested_roles.insert(insert_at, "orientar")

        evaluate_new_work = normalized.get("evaluate_new_work", True)
        if evaluate_new_work and any(role in requested_roles for role in ("verbalizar", "orientar", "ampliar")):
            if "refinar" not in requested_roles:
                requested_roles.append("refinar")

        nodes: List[RouteNode] = []
        role_to_node: Dict[str, str] = {}
        for index, role in enumerate(requested_roles, 1):
            role_request = self._role_request(normalized, role)
            node_id = str(role_request.get("route_node_id", "%s:%02d:%s" % (cycle_id, index, role)))
            role_to_node[role] = node_id

        explicit_dependencies = normalized.get("role_dependencies", {})
        for role in requested_roles:
            role_request = self._role_request(normalized, role)
            dependencies: List[str] = []
            if isinstance(explicit_dependencies, Mapping):
                for producer in _as_strings(explicit_dependencies.get(role)):
                    if producer in role_to_node:
                        dependencies.append(role_to_node[producer])
            if role == "ampliar":
                if message_validated is False and "verbalizar" in role_to_node:
                    dependencies.append(role_to_node["verbalizar"])
                if audience_defined is False and "orientar" in role_to_node:
                    dependencies.append(role_to_node["orientar"])
            if role == "refinar":
                dependencies.extend(
                    role_to_node[producer]
                    for producer in ("verbalizar", "orientar", "ampliar")
                    if producer in role_to_node and role_to_node[producer] != role_to_node[role]
                )
            dependencies = list(dict.fromkeys(dependencies))

            requested_outputs = _as_strings(
                role_request.get("requested_output_types", role_request.get("required_output_types"))
            )
            if not requested_outputs:
                requested_outputs = (_DEFAULT_OUTPUT[role],)
            node_id = role_to_node[role]
            selection = self.catalog.select(self._selection_request(
                normalized, role, node_id, maturity, requested_outputs
            ))
            write_set = _as_strings(role_request.get("write_set")) or (
                "state.proposals.%s.%s" % (role, node_id.replace(":", "-")),
            )
            mode = str(role_request.get("mode", "minimo_viavel" if maturity == "unknown" else normalized.get("mode", "parcial")))
            require(mode in {"completo", "parcial", "minimo_viavel"},
                    "ERR_INPUT_REQUIRED", "Unknown role operation mode.", role_id=role, mode=mode)
            objective = str(role_request.get("objective", normalized["user_goal"]))
            nodes.append(RouteNode(
                route_node_id=node_id,
                role_id=role,
                objective=objective,
                mode=mode,
                state_revision=revision,
                depends_on=tuple(dependencies),
                write_set=tuple(write_set),
                requested_output_types=tuple(requested_outputs),
                selection=selection,
            ))
        return tuple(nodes)

    @staticmethod
    def _parallel_groups(nodes: Sequence[RouteNode]) -> Tuple[Tuple[str, ...], ...]:
        by_id = {node.route_node_id: node for node in nodes}
        remaining = set(by_id)
        completed: Set[str] = set()
        groups: List[Tuple[str, ...]] = []
        while remaining:
            ready = sorted(node_id for node_id in remaining if set(by_id[node_id].depends_on) <= completed)
            if not ready:
                break
            safe: List[str] = []
            roles: Set[str] = set()
            writes: Set[str] = set()
            for node_id in ready:
                node = by_id[node_id]
                node_writes = set(node.write_set)
                if node.role_id in roles or writes.intersection(node_writes):
                    continue
                safe.append(node_id)
                roles.add(node.role_id)
                writes.update(node_writes)
            if len(safe) > 1:
                groups.append(tuple(safe))
            completed.update(ready)
            remaining.difference_update(ready)
        return tuple(groups)

    def plan(self, request: dict) -> RoutePlan:
        """Produce an immutable RoutePlan without state or external writes."""

        normalized = self.normalize_request(request)
        scores = self.score_bottlenecks(normalized)
        decision = self._select_bottleneck(normalized, scores)
        cycle_id = str(normalized.get("cycle_id", normalized["request_id"]))
        primary_bottleneck = copy.deepcopy(decision["primary_bottleneck"])
        if isinstance(primary_bottleneck, dict):
            primary_bottleneck["bottleneck_ref"] = "bottleneck:%s:%s" % (
                cycle_id,
                primary_bottleneck["pillar"],
            )
        maturity = self._derive_maturity(normalized)
        nodes = self._build_nodes(normalized, decision, maturity)
        plan = RoutePlan(
            project_ref=normalized["project_id"],
            cycle_id=cycle_id,
            state_revision=normalized["state_revision"],
            route_status=decision["route_status"],
            maturity=maturity,
            primary_bottleneck=primary_bottleneck,
            nodes=nodes,
            parallel_groups=self._parallel_groups(nodes),
            rejection_codes=tuple(decision["rejection_codes"]),
            evidence_refs=tuple(scores["evidence_refs"]),
        )
        parallel = self.validate_parallelism(plan)
        if not parallel.ok:
            return RoutePlan(
                project_ref=plan.project_ref,
                cycle_id=plan.cycle_id,
                state_revision=plan.state_revision,
                route_status="rejected",
                maturity=plan.maturity,
                primary_bottleneck=None,
                nodes=plan.nodes,
                parallel_groups=plan.parallel_groups,
                rejection_codes=tuple(dict.fromkeys(plan.rejection_codes + tuple(
                    violation["code"] for violation in parallel.violations
                ))),
                evidence_refs=plan.evidence_refs,
            )
        return plan

    def validate_parallelism(self, plan: RoutePlan) -> ValidationResult:
        """Validate immutable revision, ownership, dependencies, and write sets."""

        require(isinstance(plan, RoutePlan), "ERR_INPUT_REQUIRED", "plan must be RoutePlan.")
        violations: List[Dict[str, Any]] = []
        by_id = {node.route_node_id: node for node in plan.nodes}
        if len(by_id) != len(plan.nodes):
            violations.append({
                "code": "ERR_PARALLELISM_UNSAFE",
                "message": "Route node IDs are not unique.",
                "details": {},
            })
        for node in plan.nodes:
            if node.state_revision != plan.state_revision:
                violations.append({
                    "code": "ERR_PARALLELISM_UNSAFE",
                    "message": "Route node reads a different state revision.",
                    "details": {"route_node_id": node.route_node_id},
                })
            unknown_dependencies = sorted(set(node.depends_on).difference(by_id))
            if unknown_dependencies:
                violations.append({
                    "code": "ERR_SEQUENCE_DEPENDENCY",
                    "message": "Route node names an unknown dependency.",
                    "details": {"route_node_id": node.route_node_id, "dependencies": unknown_dependencies},
                })

        ancestors: Dict[str, Set[str]] = {}
        visiting: Set[str] = set()

        def dependencies_of(node_id: str) -> Set[str]:
            if node_id in ancestors:
                return ancestors[node_id]
            if node_id in visiting:
                violations.append({
                    "code": "ERR_SEQUENCE_DEPENDENCY",
                    "message": "Route dependency graph contains a cycle.",
                    "details": {"route_node_id": node_id},
                })
                return set()
            visiting.add(node_id)
            result: Set[str] = set()
            node = by_id.get(node_id)
            if node is not None:
                for dependency in node.depends_on:
                    if dependency in by_id:
                        result.add(dependency)
                        result.update(dependencies_of(dependency))
            visiting.remove(node_id)
            ancestors[node_id] = result
            return result

        for node_id in by_id:
            dependencies_of(node_id)

        for group in plan.parallel_groups:
            group_nodes: List[RouteNode] = []
            for node_id in group:
                if node_id not in by_id:
                    violations.append({
                        "code": "ERR_PARALLELISM_UNSAFE",
                        "message": "Parallel group names an unknown route node.",
                        "details": {"route_node_id": node_id},
                    })
                else:
                    group_nodes.append(by_id[node_id])
            roles: Set[str] = set()
            writes: Dict[str, str] = {}
            group_ids = {node.route_node_id for node in group_nodes}
            for node in group_nodes:
                if node.state_revision != plan.state_revision:
                    violations.append({
                        "code": "ERR_PARALLELISM_UNSAFE",
                        "message": "Parallel nodes do not share the immutable plan revision.",
                        "details": {"route_node_id": node.route_node_id},
                    })
                if node.role_id in roles:
                    violations.append({
                        "code": "ERR_PARALLELISM_UNSAFE",
                        "message": "Parallel nodes share the same decision owner.",
                        "details": {"role_id": node.role_id},
                    })
                roles.add(node.role_id)
                if group_ids.intersection(ancestors.get(node.route_node_id, set())):
                    violations.append({
                        "code": "ERR_PARALLELISM_UNSAFE",
                        "message": "Parallel nodes directly or transitively depend on another node's new output.",
                        "details": {"route_node_id": node.route_node_id},
                    })
                for field in node.write_set:
                    if field in writes:
                        violations.append({
                            "code": "ERR_PARALLEL_WRITE_COLLISION",
                            "message": "Parallel outputs target the same staged state field.",
                            "details": {
                                "write_path": field,
                                "route_node_ids": [writes[field], node.route_node_id],
                            },
                        })
                    else:
                        writes[field] = node.route_node_id

        if violations:
            priority = ("ERR_PARALLEL_WRITE_COLLISION", "ERR_PARALLELISM_UNSAFE", "ERR_SEQUENCE_DEPENDENCY")
            primary = next(code for code in priority if any(item["code"] == code for item in violations))
            return ValidationResult(ok=False, primary_code=primary, violations=tuple(violations))
        return ValidationResult.success(plan)
