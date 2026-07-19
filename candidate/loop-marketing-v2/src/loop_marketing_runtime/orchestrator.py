"""Host-neutral orchestration over the frozen P2-P4 contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .catalog import CatalogLoader
from .errors import LoopRuntimeError, require
from .models import CommandResolution, RoutePlan, RuntimeConfig, TacticRef, TacticSelection
from .router import Router
from .state_store import ProjectStateStore
from .validation import ContractValidator


def _load_json(path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _canonical_hash(value: Mapping[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LoopOrchestrator:
    """Coordinates read-only preparation and serialized local-state integration."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config.normalized()
        self.role_matrix = _load_json(self.config.role_matrix_path)
        self.routing_contract = _load_json(self.config.routing_contract_path)
        self.catalog = CatalogLoader(self.config)
        self.validator = ContractValidator(self.config)
        self.router = Router(self.role_matrix, self.routing_contract, self.catalog)
        self.store = ProjectStateStore(self.config, self.validator)
        self._commands = self._build_command_index()
        self._role_by_command = {
            resolution.command_id: resolution.role_id
            for resolution in self._commands.values()
        }
        self._validated_routes: Dict[str, Dict[str, Any]] = {}
        self._validated_receipts: Dict[str, Dict[str, Any]] = {}
        self._built_transactions: Dict[str, Dict[str, Any]] = {}

    def _build_command_index(self) -> Dict[str, CommandResolution]:
        index: Dict[str, CommandResolution] = {}
        for role in self.role_matrix["roles"]:
            contract = role["command_contract"]
            command_id = contract["command_id"]
            canonical = contract["canonical_invocation"]
            invocations = [canonical] + list(contract["backward_compatible_aliases"])
            for invocation in invocations:
                require(
                    invocation not in index,
                    "ERR_RUNTIME_CONTRACT_DRIFT",
                    "Duplicate command invocation in the canonical role matrix.",
                    invocation=invocation,
                )
                index[invocation] = CommandResolution(
                    command_id=command_id,
                    canonical_invocation=canonical,
                    invoked_as=invocation,
                    role_id=role["canonical_role_id"],
                )
        project = CommandResolution(
            command_id="loop.projeto",
            canonical_invocation="/projeto",
            invoked_as="/projeto",
            role_id="loop_planning",
        )
        index["/projeto"] = project
        index["/projeto-template"] = CommandResolution(
            command_id=project.command_id,
            canonical_invocation=project.canonical_invocation,
            invoked_as="/projeto-template",
            role_id=project.role_id,
        )
        require(len(index) == 12, "ERR_RUNTIME_CONTRACT_DRIFT", "Expected six canonical commands and six aliases.")
        return index

    def resolve_command(self, invocation: str) -> CommandResolution:
        resolution = self._commands.get(invocation)
        if resolution is None:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Unknown Loop Marketing command invocation.",
                retryable=True,
                details={"invocation": invocation, "accepted": sorted(self._commands)},
            )
        return resolution

    def prepare_route(self, request: Dict[str, Any]) -> Dict[str, Any]:
        project_ref = request.get("project_id") if isinstance(request, dict) else None
        require(
            isinstance(project_ref, str) and project_ref.startswith("project:"),
            "ERR_INPUT_REQUIRED",
            "Route request project_id must be a project reference.",
        )
        project_id = project_ref.split(":", 1)[1]
        snapshot = self.store.replay(project_id)
        require(
            request.get("state_revision") == snapshot["state_revision"],
            "ERR_STATE_REVISION_STALE",
            "Route request does not match the authoritative ledger revision.",
            retryable=True,
            requested_revision=request.get("state_revision"),
            current_revision=snapshot["state_revision"],
        )
        plan = self.router.plan(request)
        value = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan)
        try:
            value = json.loads(json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ))
            value["routing_input"] = json.loads(json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ))
        except (TypeError, ValueError) as exc:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Route request must be JSON serializable.",
                retryable=True,
                details={"error_type": type(exc).__name__},
            ) from exc
        value["read_only"] = True
        value["external_write_authorized"] = False
        value["route_plan_hash"] = _canonical_hash(value, "route_plan_hash")
        return value

    def _assert_route_plan(self, route_plan: Dict[str, Any]) -> None:
        require(isinstance(route_plan, dict), "ERR_INPUT_REQUIRED", "route_plan must be an object.")
        supplied_hash = route_plan.get("route_plan_hash")
        require(
            isinstance(supplied_hash, str) and supplied_hash == _canonical_hash(route_plan, "route_plan_hash"),
            "ERR_RUNTIME_CONTRACT_DRIFT",
            "Route plan content does not match its canonical hash.",
        )
        routing_input = route_plan.get("routing_input")
        require(
            isinstance(routing_input, dict),
            "ERR_RUNTIME_CONTRACT_DRIFT",
            "Route plan lacks its deterministic routing input.",
        )
        expected = self.prepare_route(routing_input)
        require(
            expected == route_plan,
            "ERR_RUNTIME_CONTRACT_DRIFT",
            "Route plan was not reproduced by the canonical router.",
        )

    @staticmethod
    def _selection_from_dict(value: Dict[str, Any]) -> TacticSelection:
        refs = tuple(TacticRef(**item) for item in value.get("tactic_refs", []))
        return TacticSelection(
            route_node_id=value["route_node_id"],
            role_id=value["role_id"],
            tactic_refs=refs,
            ranking_trace=tuple(value.get("ranking_trace", [])),
            base_method=value.get("base_method", not refs),
            requires_planner_review=value.get("requires_planner_review", False),
        )

    def prepare_specialist(self, route_plan: Dict[str, Any], route_node_id: str) -> Dict[str, Any]:
        self._assert_route_plan(route_plan)
        nodes = {item["route_node_id"]: item for item in route_plan.get("nodes", [])}
        require(route_node_id in nodes, "ERR_INPUT_REQUIRED", "Unknown route_node_id.", route_node_id=route_node_id)
        node = nodes[route_node_id]
        require(
            node["state_revision"] == route_plan["state_revision"],
            "ERR_STATE_REVISION_STALE",
            "Route node does not preserve the immutable plan revision.",
            retryable=True,
        )
        selection_value = node.get("selection") or {
            "route_node_id": route_node_id,
            "role_id": node["role_id"],
            "tactic_refs": [],
            "ranking_trace": [],
            "base_method": True,
            "requires_planner_review": False,
        }
        selection = self._selection_from_dict(selection_value)
        prompt_documents = self.catalog.load_selected(selection)
        role = next(item for item in self.role_matrix["roles"] if item["canonical_role_id"] == node["role_id"])
        return {
            "envelope_version": "1.0",
            "project_ref": route_plan["project_ref"],
            "cycle_id": route_plan["cycle_id"],
            "state_revision": route_plan["state_revision"],
            "route_node": node,
            "role_contract": {
                "role_id": role["canonical_role_id"],
                "purpose": role["purpose"],
                "owns": role["owns"],
                "does_not_own": role["does_not_own"],
                "required_inputs": role["required_inputs"],
                "outputs": role["outputs"],
            },
            "handoff_required_fields": [item["name"] for item in self.role_matrix["handoff_contract"]["fields"]],
            "prompt_documents": prompt_documents,
            "read_only": True,
            "external_write_authorized": False,
        }

    def validate_staged_outputs(self, route_plan: Dict[str, Any], handoffs: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._assert_route_plan(route_plan)
        require(isinstance(handoffs, list), "ERR_INPUT_REQUIRED", "handoffs must be an array.")
        nodes = {item["route_node_id"]: item for item in route_plan.get("nodes", [])}
        violations: List[Dict[str, Any]] = []
        handoff_ids = set()
        node_by_handoff: Dict[str, str] = {}
        primary = route_plan.get("primary_bottleneck")
        bottleneck_ref = primary.get("bottleneck_ref") if isinstance(primary, dict) else None
        routing_input = route_plan.get("routing_input", {})
        input_registry = routing_input.get("input_registry", {})
        evidence_registry = routing_input.get("evidence_registry", {})
        if isinstance(evidence_registry, dict):
            evidence_registry = dict(evidence_registry)
        elif isinstance(evidence_registry, (list, tuple, set)):
            evidence_registry = {item: True for item in evidence_registry}
        else:
            evidence_registry = {}
        for reference in route_plan.get("evidence_refs", []):
            evidence_registry[reference] = True
        tactic_dependencies = []
        relations = _load_json(self.config.relationship_path).get("relations", [])
        for relation in relations:
            if (
                relation.get("review_status") == "confirmed"
                and relation.get("routing_effect") == "allow_together"
            ):
                tactic_dependencies.append([
                    relation["from_tactic_id"],
                    relation["to_tactic_id"],
                ])
        for handoff in handoffs:
            handoff_id = handoff.get("handoff_id")
            if handoff_id in handoff_ids:
                violations.append({
                    "code": "ERR_HANDOFF_FIELD_MISSING",
                    "message": "Staged handoff IDs must be unique.",
                    "details": {"handoff_id": handoff_id},
                })
            handoff_ids.add(handoff_id)
            context = {
                "current_revision": route_plan["state_revision"],
                "target_read_revision": route_plan["state_revision"],
                "project_ref": route_plan["project_ref"],
                "cycle_id": route_plan["cycle_id"],
                "tactic_dependencies": tactic_dependencies,
                "input_registry": input_registry,
                "evidence_registry": evidence_registry,
            }
            if bottleneck_ref:
                context["bottleneck_registry"] = {
                    bottleneck_ref: {"owner": "loop_planning"}
                }
            result = self.validator.validate_handoff(handoff, context)
            if not result.ok:
                violations.extend(result.violations)
            candidates = [
                (node_id, node)
                for node_id, node in nodes.items()
                if node.get("role_id") == handoff.get("to_role")
            ]
            requested = handoff.get("requested_output")
            handoff_writes = set(requested.get("write_set", [])) if isinstance(requested, dict) else set()
            exact_writes = [
                (node_id, node) for node_id, node in candidates
                if set(node.get("write_set", [])) == handoff_writes
            ]
            if len(exact_writes) == 1:
                node_id, node = exact_writes[0]
                node_by_handoff[handoff_id] = node_id
                selected = (node.get("selection") or {}).get("tactic_refs", [])
                selected_refs = [
                    (item.get("tactic_id"), item.get("canonical_path"), item.get("canonical_sha256"))
                    for item in selected
                ]
                handoff_refs = [
                    (item.get("tactic_id"), item.get("canonical_path"), item.get("canonical_sha256"))
                    for item in handoff.get("tactic_refs", [])
                    if isinstance(item, dict)
                ]
                if selected_refs != handoff_refs:
                    violations.append({
                        "code": "ERR_TACTIC_METADATA_MISSING",
                        "message": "Handoff tactics must exactly match its route-node selection.",
                        "details": {"handoff_id": handoff_id, "route_node_id": node_id},
                    })
            else:
                violations.append({
                    "code": "ERR_SEQUENCE_DEPENDENCY",
                    "message": "Handoff must resolve to exactly one route node by role and write set.",
                    "details": {
                        "handoff_id": handoff_id,
                        "candidate_route_node_ids": [item[0] for item in candidates],
                    },
                })
            if bottleneck_ref and handoff.get("bottleneck_ref") != bottleneck_ref:
                violations.append({
                    "code": "ERR_HANDOFF_PROVENANCE",
                    "message": "Handoff bottleneck_ref must match the accepted route bottleneck.",
                    "details": {
                        "handoff_id": handoff_id,
                        "expected": bottleneck_ref,
                        "supplied": handoff.get("bottleneck_ref"),
                    },
                })

        required_node_ids = {
            node_id for node_id, node in nodes.items()
            if node.get("role_id") != "loop_planning"
        }
        supplied_node_ids = set(node_by_handoff.values())
        if supplied_node_ids != required_node_ids:
            violations.append({
                "code": "ERR_SEQUENCE_DEPENDENCY",
                "message": "Every specialist route node requires exactly one validated handoff.",
                "details": {
                    "missing_route_node_ids": sorted(required_node_ids - supplied_node_ids),
                    "unexpected_route_node_ids": sorted(supplied_node_ids - required_node_ids),
                },
            })

        handoffs_by_node = {node_id: handoff_id for handoff_id, node_id in node_by_handoff.items()}
        handoff_by_id = {item.get("handoff_id"): item for item in handoffs}
        for group in route_plan.get("parallel_groups", []):
            writes: Dict[str, str] = {}
            for node_id in group:
                handoff_id = handoffs_by_node.get(node_id)
                handoff = handoff_by_id.get(handoff_id)
                requested = handoff.get("requested_output") if isinstance(handoff, dict) else None
                for target in requested.get("write_set", []) if isinstance(requested, dict) else []:
                    prior = writes.get(target)
                    if prior is not None:
                        violations.append({
                            "code": "ERR_PARALLEL_WRITE_COLLISION",
                            "message": "Parallel staged handoffs share a write-set path.",
                            "details": {"write_path": target, "handoff_ids": [prior, handoff_id]},
                        })
                    writes[target] = handoff_id
        if violations:
            return {"ok": False, "primary_code": violations[0]["code"], "violations": violations}
        handoff_hashes = sorted(_canonical_hash(item, "__no_excluded_field__") for item in handoffs)
        receipt_payload = {
            "route_plan_hash": route_plan["route_plan_hash"],
            "handoff_hashes": handoff_hashes,
            "state_revision": route_plan["state_revision"],
        }
        validation_receipt = "validation:" + hashlib.sha256(
            json.dumps(receipt_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        resolved_evidence = dict(evidence_registry)
        for handoff in handoffs:
            for item in handoff.get("evidence_refs", []):
                if isinstance(item, dict) and item.get("evidence_id"):
                    resolved_evidence[item["evidence_id"]] = True
        record = {
            "validation_receipt": validation_receipt,
            "route_plan_hash": route_plan["route_plan_hash"],
            "project_ref": route_plan["project_ref"],
            "state_revision": route_plan["state_revision"],
            "handoff_ids": [item["handoff_id"] for item in handoffs],
            "evidence_registry": resolved_evidence,
            "allowed_specialist_events": sorted({
                event_type
                for handoff in handoffs
                for event_type in handoff.get("requested_output", {}).get("proposed_state_events", [])
            }),
        }
        self._validated_routes[route_plan["route_plan_hash"]] = record
        self._validated_receipts[validation_receipt] = record
        return {
            "ok": True,
            "primary_code": None,
            "violations": [],
            "validated_handoff_ids": [item["handoff_id"] for item in handoffs],
            "state_revision": route_plan["state_revision"],
            "validation_receipt": validation_receipt,
        }

    def build_transaction(self, route_plan: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._assert_route_plan(route_plan)
        validation = self._validated_routes.get(route_plan["route_plan_hash"])
        require(
            validation is not None,
            "ERR_CROSS_VALIDATION_BLOCKED",
            "Route outputs must pass closed handoff validation before transaction construction.",
        )
        require(events, "ERR_INPUT_REQUIRED", "At least one staged event is required.")
        project_ref = route_plan["project_ref"]
        require(project_ref.startswith("project:"), "ERR_INPUT_REQUIRED", "Invalid project_ref.")
        project_id = project_ref.split(":", 1)[1]
        snapshot = self.store.load(project_id)
        revision = snapshot["state_revision"]
        require(
            revision == route_plan["state_revision"],
            "ERR_STATE_REVISION_STALE",
            "Route plan is stale relative to the project ledger.",
            retryable=True,
            plan_revision=route_plan["state_revision"],
            current_revision=revision,
        )
        transaction_id = "tx_" + uuid.uuid4().hex
        previous_event_hash = snapshot["event_log"]["head_event_hash"] or "GENESIS"
        event_sequence = snapshot["event_log"]["last_event_sequence"]
        built_events = []
        for staged in events:
            event_sequence += 1
            role_id = staged["actor_role"]
            command_id = staged.get("command_id") or next(
                command for command, owner in self._role_by_command.items() if owner == role_id and command != "loop.projeto"
            )
            try:
                payload = json.loads(json.dumps(
                    staged["payload"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise LoopRuntimeError(
                    "ERR_INPUT_REQUIRED",
                    "Staged event payload must be a JSON object.",
                    retryable=True,
                    details={"error_type": type(exc).__name__},
                ) from exc
            require(isinstance(payload, dict) and isinstance(payload.get("data"), dict),
                    "LM-EVENT-SCHEMA-INVALID", "Staged event payload.data must be an object.")
            require(
                payload["data"].get("external_mutation_requested") is not True,
                "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
                "P5 transactions cannot request an external platform mutation.",
            )
            payload["data"]["integration_validation_receipt"] = validation["validation_receipt"]
            if staged["event_type"] == "maturity_classified":
                require(
                    payload["data"].get("maturity") == route_plan["maturity"],
                    "ERR_MATURITY_GATE",
                    "A maturity event must match the route classification validated at this revision.",
                )
            if staged["event_type"] == "bottleneck_accepted":
                require(
                    isinstance(route_plan.get("primary_bottleneck"), dict)
                    and payload["data"].get("bottleneck_ref") == route_plan["primary_bottleneck"].get("bottleneck_ref"),
                    "ERR_BOTTLENECK_OWNER_VIOLATION",
                    "A bottleneck event must match the accepted route bottleneck.",
                )
            if staged["event_type"] == "route_plan_issued":
                require(
                    payload["data"].get("route_status") == route_plan["route_status"],
                    "ERR_ORCHESTRATOR_AUTHORITY",
                    "A route event must match the validated route status.",
                )
            if staged["actor_role"] != "loop_planning":
                require(
                    staged["event_type"] in validation["allowed_specialist_events"],
                    "ERR_OWNER_SCOPE_VIOLATION",
                    "Specialist event was not proposed by a validated handoff.",
                )
            item = {
                "schema_version": "2.0",
                "event_id": staged.get("event_id") or "evt_" + uuid.uuid4().hex,
                "event_type": staged["event_type"],
                "project_ref": project_ref,
                "cycle_id": route_plan["cycle_id"],
                "actor_role": role_id,
                "command_id": command_id,
                "occurred_at": staged.get("occurred_at") or _now(),
                "state_revision": revision,
                "resulting_state_revision": revision + 1,
                "event_sequence": event_sequence,
                "transaction_id": transaction_id,
                "effect": staged.get("effect", "proposal"),
                "idempotency_key": staged.get("idempotency_key") or "idem_" + uuid.uuid4().hex,
                "previous_event_hash": previous_event_hash,
                "event_hash": "0" * 64,
                "evidence_refs": list(staged["evidence_refs"]),
                "payload": payload,
            }
            item["event_hash"] = _canonical_hash(item, "event_hash")
            previous_event_hash = item["event_hash"]
            built_events.append(item)
        record = {
            "schema_version": "2.0",
            "record_type": "event_transaction",
            "transaction_id": transaction_id,
            "project_ref": project_ref,
            "expected_state_revision": revision,
            "resulting_state_revision": revision + 1,
            "committed_at": _now(),
            "integrated_by_role": "loop_planning",
            "reducer_version": "2.0.0",
            "idempotency_key": "idem_" + uuid.uuid4().hex,
            "previous_record_hash": snapshot["event_log"]["head_record_hash"] or "GENESIS",
            "record_hash": "0" * 64,
            "events": built_events,
        }
        record["record_hash"] = _canonical_hash(record, "record_hash")
        result = self.validator.validate_transaction(record, {
            "current_revision": revision,
            "previous_record_hash": record["previous_record_hash"],
            "previous_event_hash": built_events[0]["previous_event_hash"],
            "last_event_sequence": snapshot["event_log"]["last_event_sequence"],
            "evidence_registry": validation["evidence_registry"],
            "authority_registry": {},
            "require_evidence_registry": True,
        })
        if not result.ok:
            raise LoopRuntimeError(
                result.primary_code or "ERR_RUNTIME_CONTRACT_DRIFT",
                "Transaction failed the P4 contract.",
                details={"violations": list(result.violations)},
            )
        self._built_transactions[record["record_hash"]] = {
            "validation_receipt": validation["validation_receipt"],
            "project_ref": project_ref,
            "expected_state_revision": revision,
            "transaction_id": transaction_id,
        }
        return record

    def commit_transaction(self, project_id: str, transaction: Dict[str, Any]) -> Dict[str, Any]:
        claimed_record_hash = transaction.get("record_hash") if isinstance(transaction, dict) else None
        require(
            isinstance(claimed_record_hash, str)
            and claimed_record_hash == _canonical_hash(transaction, "record_hash"),
            "ERR_CROSS_VALIDATION_BLOCKED",
            "Transaction content changed after canonical construction.",
        )
        receipts = {
            item.get("payload", {}).get("data", {}).get("integration_validation_receipt")
            for item in transaction.get("events", [])
            if isinstance(item, dict)
        }
        require(
            len(receipts) == 1 and None not in receipts,
            "ERR_CROSS_VALIDATION_BLOCKED",
            "Every transaction event must carry one shared integration validation receipt.",
        )
        built = self._built_transactions.get(claimed_record_hash)
        receipt = next(iter(receipts))
        if built is None and receipt not in self._validated_receipts:
            if self.store.is_exact_replay(project_id, transaction):
                first_event = transaction["events"][0]
                return self.store.commit(
                    project_id,
                    transaction,
                    transaction["expected_state_revision"],
                    first_event["previous_event_hash"],
                )
        require(
            built is not None
            and built["project_ref"] == "project:%s" % project_id
            and built["expected_state_revision"] == transaction.get("expected_state_revision")
            and built["transaction_id"] == transaction.get("transaction_id"),
            "ERR_CROSS_VALIDATION_BLOCKED",
            "Transaction was not built and approved by this orchestrator.",
        )
        validation = self._validated_receipts.get(receipt)
        require(
            validation is not None
            and built["validation_receipt"] == receipt
            and validation["project_ref"] == "project:%s" % project_id
            and validation["state_revision"] == transaction.get("expected_state_revision"),
            "ERR_CROSS_VALIDATION_BLOCKED",
            "Transaction receipt is unknown or does not match the project revision.",
        )
        first_event = transaction["events"][0]
        return self.store.commit(
            project_id,
            transaction,
            transaction["expected_state_revision"],
            first_event["previous_event_hash"],
        )
