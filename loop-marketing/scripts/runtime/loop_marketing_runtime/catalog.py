"""Immutable tactic catalog verification and metadata-only selection.

The catalog and relationship documents are sidecars.  Canonical prompt bodies are
opened only by :meth:`verify_catalog` (integrity audit) or
:meth:`load_selected` (progressive, post-selection loading).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .errors import LoopRuntimeError, require
from .models import RuntimeConfig, TacticRef, TacticSelection, ValidationResult


_ROLE_TO_PILLAR = {
    "verbalizar": "Verbalizar",
    "orientar": "Orientar",
    "ampliar": "Ampliar",
    "refinar": "Refinar",
}
_MATURITY_RANK = {
    "nascente": 0,
    "em_desenvolvimento": 1,
    "maduro": 2,
    "avancado": 3,
}
_REQUIRED_METADATA = {
    "tactic_id",
    "canonical_path",
    "canonical_sha256",
    "pillar",
    "need_tags",
    "input_requirements",
    "output_contract",
    "minimum_maturity",
    "prerequisites",
    "contraindications",
    "execution_policy",
}
_BLOCKING_RELATION_TYPES = {"alternative_to", "collides_with", "overlaps"}
_BASELINE_COMMIT = "3cbf0cf84a038f2cd570883b70988889f037c28e"
_BASELINE_AGGREGATE = "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"


def _json_document(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LoopRuntimeError(
            "ERR_TACTIC_METADATA_MISSING",
            "Tactic sidecar could not be read as JSON.",
            retryable=True,
            details={"path": str(path), "error_type": type(exc).__name__},
        ) from exc
    require(isinstance(value, dict), "ERR_TACTIC_METADATA_MISSING", "Tactic sidecar must be a JSON object.")
    return value


def _strings(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(key) for key, present in value.items() if present)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _present_ids(value: Any) -> Set[str]:
    if value is None:
        return set()
    if isinstance(value, Mapping):
        result: Set[str] = set()
        for key, item in value.items():
            if isinstance(item, Mapping):
                present = item.get("evidenced", item.get("available", item.get("satisfied", False)))
            else:
                present = bool(item)
            if present:
                result.add(str(key))
        return result
    return set(_strings(value))


class CatalogLoader:
    """Load P3 metadata, select deterministically, and verify canonical bytes."""

    def __init__(self, config: RuntimeConfig):
        self.config = config.normalized()
        self._catalog = _json_document(self.config.catalog_path)
        self._relationship_map = _json_document(self.config.relationship_path)
        tactics = self._catalog.get("tactics")
        relations = self._relationship_map.get("relations")
        require(isinstance(tactics, list), "ERR_TACTIC_METADATA_MISSING", "Catalog tactics must be an array.")
        require(isinstance(relations, list), "ERR_TACTIC_METADATA_MISSING", "Relationship map relations must be an array.")
        self._tactics: Tuple[Dict[str, Any], ...] = tuple(
            item for item in tactics if isinstance(item, dict)
        )
        self._relations: Tuple[Dict[str, Any], ...] = tuple(
            item for item in relations if isinstance(item, dict)
        )
        self._by_id: Dict[str, Dict[str, Any]] = {
            str(item.get("tactic_id")): item for item in self._tactics if item.get("tactic_id")
        }

    def _canonical_file(self, canonical_path: str) -> Path:
        require(bool(canonical_path), "ERR_CANONICAL_LIBRARY_DRIFT", "Canonical path is empty.")
        root = self.config.library_root.resolve()
        candidate = (root / canonical_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise LoopRuntimeError(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Canonical path escapes the injected library root.",
                details={"canonical_path": canonical_path},
            ) from exc
        return candidate

    @staticmethod
    def _violation(code: str, message: str, **details: Any) -> Dict[str, Any]:
        return {"code": code, "message": message, "details": details}

    def verify_catalog(self) -> ValidationResult:
        """Verify the exact 100-entry ID/path/hash baseline against library_root."""

        violations: List[Dict[str, Any]] = []
        baseline = self._catalog.get("baseline")
        expected_count = baseline.get("canonical_prompt_count") if isinstance(baseline, dict) else None
        if expected_count != 100 or len(self._tactics) != 100:
            violations.append(self._violation(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Canonical catalog must contain exactly 100 tactics.",
                baseline_count=expected_count,
                actual_count=len(self._tactics),
            ))
        if not isinstance(baseline, dict) or baseline.get("source_commit") != _BASELINE_COMMIT:
            violations.append(self._violation(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Catalog source commit differs from the embedded immutable baseline.",
            ))
        metadata_records = [
            "%s\0%s" % (item.get("canonical_path"), item.get("canonical_sha256"))
            for item in self._tactics
        ]
        metadata_aggregate = hashlib.sha256("\n".join(sorted(metadata_records)).encode("utf-8")).hexdigest()
        if (
            not isinstance(baseline, dict)
            or baseline.get("aggregate_sha256") != _BASELINE_AGGREGATE
            or metadata_aggregate != _BASELINE_AGGREGATE
        ):
            violations.append(self._violation(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Catalog path/hash aggregate differs from the embedded immutable baseline.",
                actual_aggregate=metadata_aggregate,
            ))

        ids = [item.get("tactic_id") for item in self._tactics]
        paths = [item.get("canonical_path") for item in self._tactics]
        if len(ids) != len(set(ids)) or any(not isinstance(item, str) or not item for item in ids):
            violations.append(self._violation(
                "ERR_CANONICAL_LIBRARY_DRIFT", "Canonical tactic IDs must be non-empty and unique."
            ))
        if len(paths) != len(set(paths)) or any(not isinstance(item, str) or not item for item in paths):
            violations.append(self._violation(
                "ERR_CANONICAL_LIBRARY_DRIFT", "Canonical tactic paths must be non-empty and unique."
            ))

        for tactic in sorted(self._tactics, key=lambda item: str(item.get("tactic_id", ""))):
            tactic_id = str(tactic.get("tactic_id", ""))
            missing = sorted(_REQUIRED_METADATA.difference(tactic))
            if missing:
                violations.append(self._violation(
                    "ERR_TACTIC_METADATA_MISSING",
                    "Tactic metadata is incomplete.",
                    tactic_id=tactic_id,
                    missing=missing,
                ))
                continue
            canonical_path = tactic.get("canonical_path")
            expected_hash = tactic.get("canonical_sha256")
            if not isinstance(canonical_path, str) or not isinstance(expected_hash, str):
                violations.append(self._violation(
                    "ERR_CANONICAL_LIBRARY_DRIFT", "Canonical path or SHA-256 has an invalid type.", tactic_id=tactic_id
                ))
                continue
            try:
                prompt_path = self._canonical_file(canonical_path)
                if not prompt_path.is_file() or prompt_path.is_symlink():
                    raise OSError("missing, non-file, or symlink")
                with prompt_path.open("rb") as stream:
                    actual_hash = hashlib.sha256(stream.read()).hexdigest()
            except (OSError, LoopRuntimeError) as exc:
                violations.append(self._violation(
                    "ERR_CANONICAL_LIBRARY_DRIFT",
                    "Canonical prompt is unavailable at the anchored path.",
                    tactic_id=tactic_id,
                    canonical_path=canonical_path,
                    error_type=type(exc).__name__,
                ))
                continue
            if actual_hash != expected_hash:
                violations.append(self._violation(
                    "ERR_CANONICAL_LIBRARY_DRIFT",
                    "Canonical prompt hash differs from the catalog anchor.",
                    tactic_id=tactic_id,
                    canonical_path=canonical_path,
                    expected_sha256=expected_hash,
                    actual_sha256=actual_hash,
                ))

        confirmed = [item for item in self._relations if item.get("review_status") == "confirmed"]
        for relation in sorted(confirmed, key=lambda item: str(item.get("relation_id", ""))):
            endpoints = (relation.get("from_tactic_id"), relation.get("to_tactic_id"))
            if any(endpoint not in self._by_id for endpoint in endpoints):
                violations.append(self._violation(
                    "ERR_TACTIC_METADATA_MISSING",
                    "Confirmed relationship references a tactic outside the catalog.",
                    relation_id=relation.get("relation_id"),
                    endpoints=list(endpoints),
                ))

        if violations:
            primary = violations[0]["code"]
            return ValidationResult(ok=False, primary_code=primary, violations=tuple(violations))
        return ValidationResult.success({
            "verified_tactic_count": len(self._tactics),
            "verified_relation_count": len(confirmed),
        })

    def metadata_for_role(self, role_id: str) -> List[Dict[str, Any]]:
        """Return detached sidecar metadata without opening any prompt body."""

        require(role_id in _ROLE_TO_PILLAR, "ERR_TACTIC_METADATA_MISSING", "Unknown specialist role.", role_id=role_id)
        pillar = _ROLE_TO_PILLAR[role_id]
        return [
            copy.deepcopy(item)
            for item in sorted(self._tactics, key=lambda value: str(value.get("tactic_id", "")))
            if item.get("pillar") == pillar
        ]

    def _confirmed_relations(self, first_id: str, second_id: Optional[str] = None) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for relation in self._relations:
            if relation.get("review_status") != "confirmed":
                continue
            left = relation.get("from_tactic_id")
            right = relation.get("to_tactic_id")
            if second_id is None:
                if first_id in (left, right):
                    matches.append(relation)
            elif {first_id, second_id} == {left, right}:
                matches.append(relation)
        return matches

    def _metadata_complete(self, tactic: Mapping[str, Any]) -> bool:
        if _REQUIRED_METADATA.difference(tactic):
            return False
        output = tactic.get("output_contract")
        policy = tactic.get("execution_policy")
        return (
            isinstance(output, Mapping)
            and isinstance(output.get("output_type"), str)
            and isinstance(policy, Mapping)
            and isinstance(tactic.get("need_tags"), list)
            and isinstance(tactic.get("input_requirements"), list)
            and isinstance(tactic.get("prerequisites"), list)
            and isinstance(tactic.get("contraindications"), list)
            and tactic.get("minimum_maturity") in _MATURITY_RANK
        )

    @staticmethod
    def _active_contraindications(request: Mapping[str, Any], tactic_id: str) -> Set[str]:
        value = request.get("active_contraindications", request.get("contraindication_flags", ()))
        if isinstance(value, Mapping):
            selected = value.get(tactic_id, value.get("*", ()))
        else:
            selected = value
        return {item.casefold().strip() for item in _strings(selected)}

    @staticmethod
    def _tactic_write_sets(request: Mapping[str, Any], tactic_id: str) -> Set[str]:
        value = request.get("tactic_write_sets", {})
        if isinstance(value, Mapping):
            return set(_strings(value.get(tactic_id, ())))
        return set()

    def _pair_allowed(
        self,
        first: Mapping[str, Any],
        second: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> Tuple[bool, str]:
        first_id = str(first["tactic_id"])
        second_id = str(second["tactic_id"])
        relations = self._confirmed_relations(first_id, second_id)
        for relation in relations:
            if (
                relation.get("relation_type") in _BLOCKING_RELATION_TYPES
                and relation.get("routing_effect") != "allow_together"
            ):
                return False, "confirmed_relation_blocks_co_selection"

        dependencies = request.get("declared_dependencies", {})
        dependent = False
        if isinstance(dependencies, Mapping):
            dependent = (
                second_id in _strings(dependencies.get(first_id))
                or first_id in _strings(dependencies.get(second_id))
            )
        outputs_distinct = first["output_contract"]["output_type"] != second["output_contract"]["output_type"]
        confirmed_complement = any(
            relation.get("relation_type") == "complements" and relation.get("routing_effect") == "allow_together"
            for relation in relations
        )
        if not (outputs_distinct or dependent):
            return False, "pair_has_no_distinct_output_or_dependency"

        first_writes = self._tactic_write_sets(request, first_id)
        second_writes = self._tactic_write_sets(request, second_id)
        if not first_writes or not second_writes:
            return False, "pair_write_sets_not_declared"
        if first_writes.intersection(second_writes):
            return False, "pair_write_sets_collide"
        if confirmed_complement:
            return True, "confirmed_complement_with_disjoint_writes"
        if dependent:
            return True, "declared_dependency_with_disjoint_writes"
        return True, "distinct_outputs_with_disjoint_writes"

    def select(self, request: Dict[str, Any]) -> TacticSelection:
        """Select zero, one, or two tactics using the exact P2 ranking order."""

        require(isinstance(request, dict), "ERR_INPUT_REQUIRED", "Selection request must be an object.")
        route_node_id = str(request.get("route_node_id", "")).strip()
        role_id = str(request.get("role_id", "")).strip()
        require(bool(route_node_id), "ERR_INPUT_REQUIRED", "route_node_id is required.", field="route_node_id")
        require(role_id in _ROLE_TO_PILLAR, "ERR_INPUT_REQUIRED", "Canonical specialist role_id is required.", field="role_id")

        explicit_ids = _strings(request.get("requested_tactic_ids", request.get("tactic_ids")))
        candidate_ids = _strings(request.get("candidate_tactic_ids"))
        requested_limit = request.get("max_tactics", request.get("requested_tactic_count"))
        if requested_limit is not None:
            require(isinstance(requested_limit, int) and not isinstance(requested_limit, bool),
                    "ERR_TACTIC_CARDINALITY", "Requested tactic count must be an integer.")
        if len(explicit_ids) > 2 or (requested_limit is not None and requested_limit > 2):
            raise LoopRuntimeError(
                "ERR_TACTIC_CARDINALITY",
                "A specialist route node may select at most two tactics.",
                retryable=True,
                details={"requested_count": max(len(explicit_ids), requested_limit or 0)},
            )

        maturity = str(request.get("maturity", "unknown"))
        if maturity == "unknown":
            return TacticSelection(
                route_node_id=route_node_id,
                role_id=role_id,
                ranking_trace=({"rule": "RTE-MAT-005", "result": "base_method", "reason": "unknown_maturity"},),
                base_method=True,
            )
        require(maturity in _MATURITY_RANK, "ERR_MATURITY_GATE", "Unknown maturity enum.", maturity=maturity)

        requested_outputs = set(_strings(request.get("requested_output_types", request.get("required_output_types"))))
        need_tags = set(_strings(request.get("need_tags", request.get("required_need_tags"))))
        available_inputs = _present_ids(request.get("available_inputs"))
        evidenced_prerequisites = _present_ids(
            request.get("evidenced_prerequisites", request.get("satisfied_prerequisites"))
        )
        satisfied_handoffs = _present_ids(
            request.get("satisfied_handoffs", request.get("validated_handoffs"))
        )
        overlay_available = bool(request.get("runtime_overlay_available", request.get("sidecar_overlay_available", False)))
        planner_reviewed = bool(request.get("planner_reviewed", False))
        filter_set = set(explicit_ids or candidate_ids)
        traces: List[Dict[str, Any]] = []
        eligible: List[Tuple[Tuple[Any, ...], Dict[str, Any], Dict[str, Any]]] = []

        for tactic in self.metadata_for_role(role_id):
            tactic_id = str(tactic.get("tactic_id", ""))
            if filter_set and tactic_id not in filter_set:
                continue
            reasons: List[str] = []
            if not self._metadata_complete(tactic):
                reasons.append("metadata_incomplete")
            minimum = tactic.get("minimum_maturity")
            if minimum not in _MATURITY_RANK or _MATURITY_RANK[maturity] < _MATURITY_RANK.get(str(minimum), 99):
                reasons.append("maturity_gate")

            requirements = tactic.get("input_requirements") if isinstance(tactic.get("input_requirements"), list) else []
            required_inputs = {
                str(item.get("input_id")) for item in requirements
                if isinstance(item, Mapping) and item.get("required") is True and item.get("input_id")
            }
            optional_inputs = {
                str(item.get("input_id")) for item in requirements
                if isinstance(item, Mapping) and item.get("required") is False and item.get("input_id")
            }
            missing_required = sorted(required_inputs.difference(available_inputs))
            if missing_required:
                reasons.append("required_inputs_missing")

            prerequisites = tactic.get("prerequisites") if isinstance(tactic.get("prerequisites"), list) else []
            required_prerequisites = {
                str(item.get("prerequisite_id")) for item in prerequisites
                if isinstance(item, Mapping) and item.get("required") is True and item.get("prerequisite_id")
            }
            missing_prerequisites = sorted(required_prerequisites.difference(evidenced_prerequisites))
            if missing_prerequisites:
                reasons.append("prerequisites_missing")

            active = self._active_contraindications(request, tactic_id)
            declared_conditions = {
                str(item.get("condition", "")).casefold().strip()
                for item in tactic.get("contraindications", []) if isinstance(item, Mapping)
            }
            if active.intersection(declared_conditions):
                reasons.append("contraindication_active")

            policy = tactic.get("execution_policy") if isinstance(tactic.get("execution_policy"), Mapping) else {}
            execution_mode = policy.get("execution_mode")
            automatic_selection = policy.get("automatic_selection")
            if execution_mode == "base_method_only" or automatic_selection == "forbidden":
                reasons.append("execution_policy_forbids_tactic")
            if policy.get("runtime_overlay_required") is True and not overlay_available:
                reasons.append("runtime_overlay_unavailable")
            required_handoffs = {
                str(item.get("handoff_id")) for item in policy.get("mandatory_handoffs", [])
                if isinstance(item, Mapping) and item.get("required") is True and item.get("handoff_id")
            }
            missing_handoffs = sorted(required_handoffs.difference(satisfied_handoffs))
            if missing_handoffs:
                reasons.append("mandatory_handoffs_missing")

            output_type = tactic.get("output_contract", {}).get("output_type")
            exact_output = bool(requested_outputs and output_type in requested_outputs)
            matched_need_count = len(need_tags.intersection(set(_strings(tactic.get("need_tags")))))
            if not filter_set and requested_outputs and not exact_output and matched_need_count == 0:
                reasons.append("no_output_or_need_match")
            if not filter_set and not requested_outputs and need_tags and matched_need_count == 0:
                reasons.append("no_need_match")

            collision_count = sum(
                1 for relation in self._confirmed_relations(tactic_id)
                if relation.get("relation_type") in _BLOCKING_RELATION_TYPES
                and relation.get("routing_effect") != "allow_together"
            )
            optional_gaps = len(optional_inputs.difference(available_inputs))
            trace = {
                "tactic_id": tactic_id,
                "eligible": not reasons,
                "exact_output_match": exact_output,
                "need_tag_matches": matched_need_count,
                "optional_input_gaps": optional_gaps,
                "confirmed_collision_count": collision_count,
                "gate_reasons": reasons,
                "missing_required_inputs": missing_required,
                "missing_prerequisites": missing_prerequisites,
                "missing_mandatory_handoffs": missing_handoffs,
            }
            traces.append(trace)
            if not reasons:
                rank = (-int(exact_output), -matched_need_count, optional_gaps, collision_count, tactic_id)
                eligible.append((rank, tactic, trace))

        eligible.sort(key=lambda item: item[0])
        traces.sort(key=lambda item: item["tactic_id"])
        if not eligible:
            return TacticSelection(
                route_node_id=route_node_id,
                role_id=role_id,
                ranking_trace=tuple(traces),
                base_method=True,
            )

        desired = len(explicit_ids) if explicit_ids else (
            requested_limit if requested_limit is not None else (2 if len(requested_outputs) >= 2 else 1)
        )
        if desired <= 0:
            return TacticSelection(
                route_node_id=route_node_id,
                role_id=role_id,
                ranking_trace=tuple(traces),
                base_method=True,
            )
        first = eligible[0][1]
        selected = [first]
        pair_reason: Optional[str] = None
        if desired == 2:
            for _rank, candidate, _trace in eligible[1:]:
                allowed, reason = self._pair_allowed(first, candidate, request)
                if allowed:
                    selected.append(candidate)
                    pair_reason = reason
                    break
            if len(selected) != 2:
                raise LoopRuntimeError(
                    "ERR_TACTIC_CARDINALITY",
                    "Two tactics were requested but no fail-closed eligible pair exists.",
                    retryable=True,
                    details={"first_tactic_id": first["tactic_id"]},
                )

        planner_review = False
        tactic_refs: List[TacticRef] = []
        for index, tactic in enumerate(selected):
            policy = tactic["execution_policy"]
            planner_review = planner_review or (
                policy.get("automatic_selection") == "planner_review_required" and not planner_reviewed
            )
            reason = "selected_by_P2_rank_exact_output_need_tags_optional_gaps_collisions_id"
            if index == 1 and pair_reason:
                reason += ":" + pair_reason
            tactic_refs.append(TacticRef(
                tactic_id=tactic["tactic_id"],
                canonical_path=tactic["canonical_path"],
                canonical_sha256=tactic["canonical_sha256"],
                selection_reason=reason,
            ))
        return TacticSelection(
            route_node_id=route_node_id,
            role_id=role_id,
            tactic_refs=tuple(tactic_refs),
            ranking_trace=tuple(traces),
            base_method=False,
            requires_planner_review=planner_review,
        )

    def load_selected(self, selection: TacticSelection) -> List[Dict[str, Any]]:
        """Read and return only selected bodies after ID/path/hash verification."""

        require(isinstance(selection, TacticSelection), "ERR_INPUT_REQUIRED", "selection must be TacticSelection.")
        require(len(selection.tactic_refs) <= 2, "ERR_TACTIC_CARDINALITY", "Selection exceeds two tactics.")
        require(selection.role_id in _ROLE_TO_PILLAR, "ERR_TACTIC_METADATA_MISSING", "Unknown selection role.")
        require(not selection.requires_planner_review,
                "ERR_CROSS_VALIDATION_BLOCKED", "Planner review is required before prompt-body loading.", retryable=True)
        expected_pillar = _ROLE_TO_PILLAR[selection.role_id]
        loaded: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for reference in selection.tactic_refs:
            require(reference.tactic_id not in seen, "ERR_TACTIC_CARDINALITY", "Duplicate selected tactic.")
            seen.add(reference.tactic_id)
            tactic = self._by_id.get(reference.tactic_id)
            require(tactic is not None, "ERR_TACTIC_METADATA_MISSING", "Selected tactic is absent from catalog.", tactic_id=reference.tactic_id)
            require(tactic.get("pillar") == expected_pillar,
                    "ERR_OWNER_SCOPE_VIOLATION", "Selected tactic belongs to a different role.", tactic_id=reference.tactic_id)
            require(
                tactic.get("canonical_path") == reference.canonical_path
                and tactic.get("canonical_sha256") == reference.canonical_sha256,
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Selected tactic reference differs from catalog metadata.",
                tactic_id=reference.tactic_id,
            )
            prompt_path = self._canonical_file(reference.canonical_path)
            try:
                if not prompt_path.is_file() or prompt_path.is_symlink():
                    raise OSError("missing, non-file, or symlink")
                with prompt_path.open("rb") as stream:
                    body_bytes = stream.read()
                actual_hash = hashlib.sha256(body_bytes).hexdigest()
                body = body_bytes.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise LoopRuntimeError(
                    "ERR_CANONICAL_LIBRARY_DRIFT",
                    "Selected canonical prompt cannot be loaded safely.",
                    details={"tactic_id": reference.tactic_id, "error_type": type(exc).__name__},
                ) from exc
            require(actual_hash == reference.canonical_sha256,
                    "ERR_CANONICAL_LIBRARY_DRIFT", "Selected canonical prompt hash mismatch.",
                    tactic_id=reference.tactic_id, expected_sha256=reference.canonical_sha256, actual_sha256=actual_hash)
            value = copy.deepcopy(tactic)
            value["prompt_body"] = body
            loaded.append(value)
        return loaded
