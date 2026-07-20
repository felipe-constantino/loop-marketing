"""Dependency-free structural and semantic validation for the P4 contracts.

The validators in this module are deliberately read-only.  They report the
input value unchanged on success and never fill, normalize, or otherwise infer
contract data that was not supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import RuntimeConfig, ValidationResult


_MISSING = object()


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("contract root must be a JSON object: %s" % path)
    return value


def _json_key(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Mapping[str, Any], excluded_field: str) -> str:
    """Return the P4 canonical content hash, excluding its claimed hash field."""

    payload = {key: item for key, item in value.items() if key != excluded_field}
    return hashlib.sha256(_json_key(payload).encode("utf-8")).hexdigest()


class _MiniSchema:
    """JSON Schema subset used by the three sealed, bundled P4 schemas."""

    def __init__(self, root: Dict[str, Any]) -> None:
        self.root = root

    def _resolve(self, reference: str) -> Dict[str, Any]:
        if not reference.startswith("#/"):
            raise ValueError("external JSON Schema references are unsupported")
        node: Any = self.root
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            node = node[part]
        if not isinstance(node, dict):
            raise ValueError("JSON Schema reference does not resolve to an object")
        return node

    @staticmethod
    def _is_type(value: Any, expected: str) -> bool:
        checks = {
            "object": lambda: isinstance(value, dict),
            "array": lambda: isinstance(value, list),
            "string": lambda: isinstance(value, str),
            "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda: isinstance(value, bool),
            "null": lambda: value is None,
        }
        check = checks.get(expected)
        return True if check is None else check()

    def errors(
        self,
        value: Any,
        schema: Optional[Dict[str, Any]] = None,
        path: str = "$",
    ) -> List[Dict[str, str]]:
        schema = self.root if schema is None else schema
        if "$ref" in schema:
            return self.errors(value, self._resolve(schema["$ref"]), path)

        errors: List[Dict[str, str]] = []

        def add(keyword: str, error_path: Optional[str] = None) -> None:
            errors.append({"path": error_path or path, "keyword": keyword})

        if "const" in schema and value != schema["const"]:
            add("const")
        if "enum" in schema and value not in schema["enum"]:
            add("enum")

        declared_type = schema.get("type")
        if declared_type is not None:
            allowed = declared_type if isinstance(declared_type, list) else [declared_type]
            if not any(self._is_type(value, item) for item in allowed):
                add("type")
                return errors

        if "anyOf" in schema:
            branches = [self.errors(value, branch, path) for branch in schema["anyOf"]]
            if all(branch for branch in branches):
                add("anyOf")
        if "oneOf" in schema:
            matches = sum(not self.errors(value, branch, path) for branch in schema["oneOf"])
            if matches != 1:
                add("oneOf")
        for branch in schema.get("allOf", []):
            errors.extend(self.errors(value, branch, path))
        if "if" in schema:
            condition_matches = not self.errors(value, schema["if"], path)
            selected = schema.get("then") if condition_matches else schema.get("else")
            if selected is not None:
                errors.extend(self.errors(value, selected, path))

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for key in schema.get("required", []):
                if key not in value:
                    add("required", "%s.%s" % (path, key))
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        add("additionalProperties", "%s.%s" % (path, key))
            for key, child_schema in properties.items():
                if key in value:
                    errors.extend(self.errors(value[key], child_schema, "%s.%s" % (path, key)))
            if len(value) < schema.get("minProperties", 0):
                add("minProperties")
            if "maxProperties" in schema and len(value) > schema["maxProperties"]:
                add("maxProperties")

        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                add("minItems")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                add("maxItems")
            if schema.get("uniqueItems"):
                try:
                    keys = [_json_key(item) for item in value]
                except (TypeError, ValueError):
                    keys = [repr(item) for item in value]
                if len(set(keys)) != len(keys):
                    add("uniqueItems")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    errors.extend(self.errors(item, item_schema, "%s[%d]" % (path, index)))

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                add("minLength")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                add("maxLength")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                add("pattern")
            if schema.get("format") == "date-time":
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("timezone is required")
                except (TypeError, ValueError):
                    add("date-time")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                add("minimum")
            if "maximum" in schema and value > schema["maximum"]:
                add("maximum")
        return errors


def _violation(code: str, message: str, **details: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _finish(
    value: Any,
    violations: Iterable[Dict[str, Any]],
    precedence: Sequence[str],
) -> ValidationResult:
    """Deduplicate and order all detected violations without modifying input."""

    unique: List[Dict[str, Any]] = []
    seen = set()
    for item in violations:
        marker = _json_key(item)
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    rank = {code: index for index, code in enumerate(precedence)}
    ordered = sorted(
        enumerate(unique),
        key=lambda pair: (rank.get(pair[1]["code"], len(rank)), pair[0]),
    )
    final = tuple(item for _index, item in ordered)
    if not final:
        return ValidationResult.success(value)
    return ValidationResult(ok=False, primary_code=final[0]["code"], violations=final)


_STATE_PRECEDENCE = (
    "ERR_UNKNOWN_SCHEMA_VERSION",
    "LM-COMPAT-PATH-ESCAPE",
    "ERR_STATE_FABRICATION",
)

_EVENT_PRECEDENCE = (
    "ERR_UNKNOWN_SCHEMA_VERSION",
    "LM-EVENT-SCHEMA-INVALID",
    "ERR_STATE_FABRICATION",
    "ERR_STATE_REVISION_STALE",
    "LM-EVENT-HASH-MISMATCH",
    "ERR_BOTTLENECK_OWNER_VIOLATION",
    "ERR_ORCHESTRATOR_AUTHORITY",
    "ERR_OWNER_SCOPE_VIOLATION",
    "ERR_EVENT_TYPE_ROLE_MISMATCH",
    "LM-EVENT-CHAIN-BROKEN",
    "ERR_CLAIM_PROVENANCE_MISSING",
    "ERR_EVIDENCE_REF_UNRESOLVED",
    "ERR_EXPERIMENT_TRANSITION_INVALID",
    "ERR_EXPERIMENT_EVIDENCE_MISSING",
    "ERR_AUTHORITY_REF_UNVERIFIED",
    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
    "LM-EVENT-IDEMPOTENCY-CONFLICT",
)

_TRANSACTION_PRECEDENCE = (
    "ERR_UNKNOWN_SCHEMA_VERSION",
    "LM-EVENT-SCHEMA-INVALID",
    "ERR_STATE_REVISION_STALE",
    "LM-EVENT-CHAIN-BROKEN",
    "LM-EVENT-HASH-MISMATCH",
    "ERR_BOTTLENECK_OWNER_VIOLATION",
    "ERR_ORCHESTRATOR_AUTHORITY",
    "ERR_OWNER_SCOPE_VIOLATION",
    "ERR_EVENT_TYPE_ROLE_MISMATCH",
    "ERR_CLAIM_PROVENANCE_MISSING",
    "ERR_EVIDENCE_REF_UNRESOLVED",
    "ERR_EXPERIMENT_TRANSITION_INVALID",
    "ERR_EXPERIMENT_EVIDENCE_MISSING",
    "ERR_AUTHORITY_REF_UNVERIFIED",
    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
    "LM-EVENT-IDEMPOTENCY-CONFLICT",
)

# Frozen by artifacts/P4/workstreams/handoff.json#validator_contract.
_HANDOFF_PRECEDENCE = (
    "ERR_HANDOFF_FIELD_MISSING",
    "ERR_HANDOFF_STALE_REVISION",
    "ERR_HANDOFF_OWNER_SCOPE",
    "ERR_HANDOFF_SCOPE_BOUNDARY",
    "ERR_OWNER_SCOPE_VIOLATION",
    "ERR_HANDOFF_PROVENANCE",
    "ERR_MATURITY_GATE",
    "ERR_TACTIC_CARDINALITY",
    "ERR_TACTIC_METADATA_MISSING",
    "ERR_CANONICAL_LIBRARY_DRIFT",
    "ERR_SEQUENCE_DEPENDENCY",
    "ERR_PARALLELISM_UNSAFE",
    "ERR_PARALLEL_WRITE_COLLISION",
    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
    "ERR_CROSS_VALIDATION_BLOCKED",
)


class ContractValidator:
    """Validate state, event, transaction, and exact P2 handoff contracts."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config.normalized()
        self.state_schema = _load_json(self.config.contracts_root / "state-schema.json")
        self.event_schema = _load_json(self.config.contracts_root / "event-schema.json")
        self.handoff_schema = _load_json(self.config.contracts_root / "handoff-schema.json")
        self.role_matrix = _load_json(self.config.role_matrix_path)
        self.catalog = _load_json(self.config.catalog_path)
        self._state_struct = _MiniSchema(self.state_schema)
        self._event_struct = _MiniSchema(self.event_schema)
        self._handoff_struct = _MiniSchema(self.handoff_schema)
        event_contract = self.event_schema["x-loop-contract"]
        handoff_contract = self.handoff_schema["x-loop-contract"]
        self._role_events = event_contract["authority_by_role"]
        self._commands = event_contract["command_contract"]
        self._transitions = event_contract["experiment_state_machine"]
        self._domain_owner = handoff_contract["decision_domain_owner"]
        self._catalog_by_id = {
            item["tactic_id"]: item for item in self.catalog.get("tactics", [])
        }

    @staticmethod
    def _context_ref_exists(context: Dict[str, Any], registry_key: str, reference: str) -> bool:
        registry = context.get(registry_key, _MISSING)
        if registry is _MISSING:
            return True
        if isinstance(registry, Mapping):
            return reference in registry
        if isinstance(registry, (set, list, tuple)):
            return reference in registry
        return False

    def validate_state(self, snapshot: Dict[str, Any]) -> ValidationResult:
        violations: List[Dict[str, Any]] = []
        if not isinstance(snapshot, dict):
            return _finish(
                snapshot,
                [_violation("ERR_STATE_FABRICATION", "State snapshot must be an object.")],
                _STATE_PRECEDENCE,
            )
        structural = self._state_struct.errors(snapshot)
        schema_version = snapshot.get("schema_version")
        if schema_version is not None and schema_version != "2.0":
            violations.append(_violation(
                "ERR_UNKNOWN_SCHEMA_VERSION",
                "State schema version is not supported.",
                supplied=schema_version,
                supported="2.0",
            ))
        project_id = snapshot.get("project_id")
        if project_id is not None and (
            not isinstance(project_id, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", project_id) is None
        ):
            violations.append(_violation(
                "LM-COMPAT-PATH-ESCAPE",
                "project_id violates the contained slug contract.",
                project_id=project_id,
            ))
        if structural and not any(item["code"] == "ERR_UNKNOWN_SCHEMA_VERSION" for item in violations):
            violations.append(_violation(
                "ERR_STATE_FABRICATION",
                "State snapshot does not satisfy the sealed P4 schema.",
                schema_errors=structural,
            ))

        if isinstance(project_id, str) and snapshot.get("project_ref") != "project:%s" % project_id:
            violations.append(_violation(
                "LM-COMPAT-PATH-ESCAPE",
                "project_ref is not bound to project_id.",
                project_id=project_id,
                project_ref=snapshot.get("project_ref"),
            ))

        revision = snapshot.get("state_revision")
        derived = snapshot.get("derived_from_revision")
        event_log = snapshot.get("event_log")
        if isinstance(revision, int) and not isinstance(revision, bool) and isinstance(event_log, dict):
            if revision == 0:
                if derived is not None:
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Genesis state cannot claim a prior revision.",
                        derived_from_revision=derived,
                    ))
                nullable_heads = ("head_event_id", "head_event_hash", "head_record_hash")
                if any(event_log.get(key) is not None for key in nullable_heads):
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Genesis state cannot claim committed ledger heads.",
                    ))
                count_keys = ("last_event_sequence", "applied_event_count", "committed_transaction_count")
                if any(event_log.get(key) != 0 for key in count_keys):
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Genesis ledger counters must all be zero.",
                    ))
            elif revision > 0:
                if derived != revision - 1:
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Derived snapshot must name the immediately preceding revision.",
                        state_revision=revision,
                        derived_from_revision=derived,
                    ))
                required_heads = ("head_event_id", "head_event_hash", "head_record_hash")
                if any(event_log.get(key) is None for key in required_heads):
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Non-genesis state requires all ledger heads.",
                    ))
                if event_log.get("committed_transaction_count") != revision:
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "One committed non-duplicate transaction must correspond to one revision.",
                        state_revision=revision,
                        committed_transaction_count=event_log.get("committed_transaction_count"),
                    ))
                if (
                    event_log.get("last_event_sequence") != event_log.get("applied_event_count")
                    or not isinstance(event_log.get("applied_event_count"), int)
                    or event_log.get("applied_event_count") < revision
                ):
                    violations.append(_violation(
                        "ERR_STATE_FABRICATION",
                        "Event counters are inconsistent with the authoritative ledger.",
                    ))
        state = snapshot.get("state")
        if isinstance(state, dict) and state.get("route_status") == "ready" and state.get("accepted_bottleneck_ref") is None:
            violations.append(_violation(
                "ERR_STATE_FABRICATION",
                "A ready route requires one accepted bottleneck reference.",
            ))
        return _finish(snapshot, violations, _STATE_PRECEDENCE)

    def _event_violations(
        self,
        event: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        validate_structure: bool = True,
    ) -> List[Dict[str, Any]]:
        context = context or {}
        violations: List[Dict[str, Any]] = []
        event_definition = self.event_schema["$defs"]["event"]
        structural = self._event_struct.errors(event, event_definition) if validate_structure else []
        version = event.get("schema_version")
        if version is not None and version != "2.0":
            violations.append(_violation(
                "ERR_UNKNOWN_SCHEMA_VERSION",
                "Event schema version is not supported.",
                supplied=version,
                supported="2.0",
            ))
        if structural:
            code = "ERR_STATE_FABRICATION" if not event.get("evidence_refs") else "LM-EVENT-SCHEMA-INVALID"
            violations.append(_violation(
                code,
                "Event does not satisfy the sealed P4 event schema.",
                schema_errors=structural,
            ))

        revision = event.get("state_revision")
        resulting = event.get("resulting_state_revision")
        current = context.get("current_revision", _MISSING)
        if current is not _MISSING and revision != current:
            violations.append(_violation(
                "ERR_STATE_REVISION_STALE",
                "Event was produced against a stale state revision.",
                event_revision=revision,
                current_revision=current,
            ))
        if isinstance(revision, int) and not isinstance(revision, bool) and resulting != revision + 1:
            violations.append(_violation(
                "ERR_STATE_REVISION_STALE",
                "Event resulting revision must be exactly its input revision plus one.",
                event_revision=revision,
                resulting_revision=resulting,
            ))

        claimed_hash = event.get("event_hash")
        if isinstance(claimed_hash, str):
            try:
                actual_hash = canonical_hash(event, "event_hash")
            except (TypeError, ValueError):
                actual_hash = None
            if actual_hash is not None and claimed_hash != actual_hash:
                violations.append(_violation(
                    "LM-EVENT-HASH-MISMATCH",
                    "event_hash does not match canonical event content.",
                    claimed_hash=claimed_hash,
                    actual_hash=actual_hash,
                ))

        role = event.get("actor_role")
        event_type = event.get("event_type")
        if role in self._role_events and event_type not in self._role_events[role]:
            if event_type in ("bottleneck_accepted", "bottleneck_rejected"):
                code = "ERR_BOTTLENECK_OWNER_VIOLATION"
            elif event_type in self._role_events.get("loop_planning", []):
                code = "ERR_ORCHESTRATOR_AUTHORITY"
            elif any(event_type in allowed for allowed in self._role_events.values()):
                code = "ERR_OWNER_SCOPE_VIOLATION"
            else:
                code = "ERR_EVENT_TYPE_ROLE_MISMATCH"
            violations.append(_violation(
                code,
                "actor_role is not authorized for event_type.",
                actor_role=role,
                event_type=event_type,
            ))

        command_id = event.get("command_id")
        command = self._commands.get(command_id)
        if command is not None and command.get("role") != role:
            violations.append(_violation(
                "ERR_OWNER_SCOPE_VIOLATION",
                "command_id and actor_role do not have identical authority.",
                command_id=command_id,
                actor_role=role,
                command_role=command.get("role"),
            ))

        previous_expected = context.get("previous_event_hash", _MISSING)
        if previous_expected is not _MISSING and event.get("previous_event_hash") != previous_expected:
            violations.append(_violation(
                "LM-EVENT-CHAIN-BROKEN",
                "previous_event_hash does not match the verified ledger head.",
                supplied=event.get("previous_event_hash"),
                expected=previous_expected,
            ))

        payload = event.get("payload")
        claims = payload.get("claims", []) if isinstance(payload, dict) else []
        evidence_refs = event.get("evidence_refs")
        event_evidence = set(evidence_refs) if isinstance(evidence_refs, list) else set()
        strict_evidence = context.get("require_evidence_registry") is True
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            provenance = claim.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            if claim.get("kind") == "fact" and not {"source_ref", "observed_at"}.issubset(provenance):
                violations.append(_violation(
                    "ERR_CLAIM_PROVENANCE_MISSING",
                    "A factual claim requires source_ref and observed_at.",
                    claim_index=index,
                    claim_id=claim.get("claim_id"),
                ))
            source_ref = provenance.get("source_ref")
            if claim.get("kind") == "fact" and strict_evidence and isinstance(source_ref, str):
                source_resolved = (
                    "evidence_registry" in context
                    and self._context_ref_exists(context, "evidence_registry", source_ref)
                )
                if not source_resolved or source_ref not in event_evidence:
                    violations.append(_violation(
                        "ERR_EVIDENCE_REF_UNRESOLVED",
                        "A factual claim source must resolve externally and be bound to the event evidence list.",
                        claim_index=index,
                        claim_id=claim.get("claim_id"),
                        source_ref=source_ref,
                        registry_resolved=source_resolved,
                        event_bound=source_ref in event_evidence,
                    ))
            if claim.get("kind") == "hypothesis" and not provenance.get("rationale"):
                violations.append(_violation(
                    "ERR_CLAIM_PROVENANCE_MISSING",
                    "A hypothesis requires an explicit rationale and remains a hypothesis.",
                    claim_index=index,
                    claim_id=claim.get("claim_id"),
                ))

        intrinsic_evidence = {
            claim.get("provenance", {}).get("source_ref")
            for claim in claims
            if isinstance(claim, dict) and isinstance(claim.get("provenance"), dict)
        }
        payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
        evidence_map = payload_data.get("evidence_map", {}) if isinstance(payload_data, dict) else {}
        if isinstance(evidence_map, dict):
            intrinsic_evidence.update(evidence_map.values())
        intrinsic_evidence.discard(None)
        if isinstance(evidence_refs, list):
            for reference in evidence_refs:
                registry_resolved = (
                    "evidence_registry" in context
                    and self._context_ref_exists(context, "evidence_registry", reference)
                )
                if isinstance(reference, str) and (
                    (strict_evidence and not registry_resolved)
                    or (
                        not strict_evidence
                        and event_type not in ("experiment_created_as_proposed", "experiment_transition_evidence_validated")
                        and reference not in intrinsic_evidence
                        and not registry_resolved
                    )
                ):
                    violations.append(_violation(
                        "ERR_EVIDENCE_REF_UNRESOLVED",
                        "Event evidence reference does not resolve in the supplied registry.",
                        evidence_ref=reference,
                    ))

        if event_type in ("experiment_created_as_proposed", "experiment_transition_evidence_validated"):
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            match: Optional[Tuple[str, Dict[str, Any]]] = None
            if isinstance(data, dict):
                for action, transition in self._transitions.items():
                    if transition.get("to") != data.get("to"):
                        continue
                    allowed_from = transition.get("from_any", [transition.get("from")])
                    if data.get("from") in allowed_from:
                        match = (action, transition)
                        break
            if match is None:
                violations.append(_violation(
                    "ERR_EXPERIMENT_TRANSITION_INVALID",
                    "Experiment transition skips, reverses, or leaves the P2 state machine.",
                    from_state=data.get("from") if isinstance(data, dict) else None,
                    to_state=data.get("to") if isinstance(data, dict) else None,
                ))
            else:
                action, transition = match
                required_type = (
                    "experiment_created_as_proposed"
                    if action == "create"
                    else "experiment_transition_evidence_validated"
                )
                if event_type != required_type or data.get("transition_rule_id") != transition.get("rule_id"):
                    violations.append(_violation(
                        "ERR_EXPERIMENT_TRANSITION_INVALID",
                        "Experiment event type or rule ID does not match the transition.",
                        expected_event_type=required_type,
                        expected_rule_id=transition.get("rule_id"),
                    ))
                evidence_map = data.get("evidence_map")
                evidence_map = evidence_map if isinstance(evidence_map, dict) else {}
                required_keys = {item["evidence_key"] for item in transition["required_evidence"]}
                supplied_keys = set(evidence_map)
                referenced_values = set(evidence_map.values())
                event_refs = set(evidence_refs) if isinstance(evidence_refs, list) else set()
                missing = sorted(required_keys - supplied_keys)
                unbound = sorted(value for value in referenced_values if value not in event_refs)
                if missing or unbound:
                    violations.append(_violation(
                        "ERR_EXPERIMENT_EVIDENCE_MISSING",
                        "Experiment transition lacks required, event-bound evidence.",
                        missing_evidence_keys=missing,
                        unbound_evidence_refs=unbound,
                    ))
                authority_ref = data.get("authorization_ref")
                if authority_ref is not None and (
                    "authority_registry" not in context
                    or not self._context_ref_exists(context, "authority_registry", authority_ref)
                ):
                    violations.append(_violation(
                        "ERR_AUTHORITY_REF_UNVERIFIED",
                        "Supplied external authority reference could not be verified.",
                        authority_ref=authority_ref,
                    ))

        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            data = payload["data"]
            authorization_ref = data.get("authorization_ref")
            authority_resolved = (
                authorization_ref is not None
                and "authority_registry" in context
                and self._context_ref_exists(context, "authority_registry", authorization_ref)
            )
            if data.get("external_mutation_requested") is True and not authority_resolved:
                violations.append(_violation(
                    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
                    "A route or analytical role never implies external mutation authority.",
                ))
        return violations

    def validate_event(self, event: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        if not isinstance(event, dict):
            return _finish(
                event,
                [_violation("LM-EVENT-SCHEMA-INVALID", "Event must be an object.")],
                _EVENT_PRECEDENCE,
            )
        violations = self._event_violations(event, context)
        return _finish(event, violations, _EVENT_PRECEDENCE)

    def validate_transaction(self, record: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        if not isinstance(record, dict):
            return _finish(
                record,
                [_violation("LM-EVENT-SCHEMA-INVALID", "Transaction must be an object.")],
                _TRANSACTION_PRECEDENCE,
            )
        context = context or {}
        violations: List[Dict[str, Any]] = []
        structural = self._event_struct.errors(record)
        version = record.get("schema_version")
        if version is not None and version != "2.0":
            violations.append(_violation(
                "ERR_UNKNOWN_SCHEMA_VERSION",
                "Transaction schema version is not supported.",
                supplied=version,
                supported="2.0",
            ))
        if structural:
            violations.append(_violation(
                "LM-EVENT-SCHEMA-INVALID",
                "Transaction does not satisfy the sealed P4 schema.",
                schema_errors=structural,
            ))

        expected = record.get("expected_state_revision")
        resulting = record.get("resulting_state_revision")
        current = context.get("current_revision", expected)
        if expected != current or (
            isinstance(current, int)
            and not isinstance(current, bool)
            and resulting != current + 1
        ):
            violations.append(_violation(
                "ERR_STATE_REVISION_STALE",
                "Transaction must compare-and-swap exactly one revision.",
                expected_state_revision=expected,
                current_revision=current,
                resulting_state_revision=resulting,
            ))

        previous_record = context.get("previous_record_hash", _MISSING)
        if previous_record is not _MISSING and record.get("previous_record_hash") != previous_record:
            violations.append(_violation(
                "LM-EVENT-CHAIN-BROKEN",
                "previous_record_hash does not match the verified record head.",
                supplied=record.get("previous_record_hash"),
                expected=previous_record,
            ))

        claimed_record_hash = record.get("record_hash")
        if isinstance(claimed_record_hash, str):
            try:
                actual_record_hash = canonical_hash(record, "record_hash")
            except (TypeError, ValueError):
                actual_record_hash = None
            if actual_record_hash is not None and claimed_record_hash != actual_record_hash:
                violations.append(_violation(
                    "LM-EVENT-HASH-MISMATCH",
                    "record_hash does not match canonical transaction content.",
                    claimed_hash=claimed_record_hash,
                    actual_hash=actual_record_hash,
                ))

        events = record.get("events")
        if isinstance(events, list) and events:
            event_head = context.get("previous_event_hash", events[0].get("previous_event_hash") if isinstance(events[0], dict) else None)
            last_sequence = context.get(
                "last_event_sequence",
                events[0].get("event_sequence", 1) - 1 if isinstance(events[0], dict) and isinstance(events[0].get("event_sequence"), int) else 0,
            )
            expected_sequence = last_sequence + 1 if isinstance(last_sequence, int) else None
            seen_event_ids = set()
            seen_idempotency = set()
            for index, event in enumerate(events):
                if not isinstance(event, dict):
                    continue
                if event.get("transaction_id") != record.get("transaction_id") or event.get("project_ref") != record.get("project_ref"):
                    violations.append(_violation(
                        "LM-EVENT-SCHEMA-INVALID",
                        "Nested event identity is not bound to its transaction.",
                        event_index=index,
                    ))
                if event.get("state_revision") != expected or event.get("resulting_state_revision") != resulting:
                    violations.append(_violation(
                        "ERR_STATE_REVISION_STALE",
                        "All events in one transaction must share its revisions.",
                        event_index=index,
                    ))
                if expected_sequence is not None and event.get("event_sequence") != expected_sequence:
                    violations.append(_violation(
                        "LM-EVENT-CHAIN-BROKEN",
                        "Event sequence is not contiguous.",
                        event_index=index,
                        expected_sequence=expected_sequence,
                        supplied_sequence=event.get("event_sequence"),
                    ))
                if event.get("previous_event_hash") != event_head:
                    violations.append(_violation(
                        "LM-EVENT-CHAIN-BROKEN",
                        "Nested event does not extend the previous verified event hash.",
                        event_index=index,
                    ))
                event_id = event.get("event_id")
                idempotency_key = event.get("idempotency_key")
                if event_id in seen_event_ids or idempotency_key in seen_idempotency:
                    violations.append(_violation(
                        "LM-EVENT-IDEMPOTENCY-CONFLICT",
                        "A transaction cannot reuse an event or idempotency identifier.",
                        event_index=index,
                    ))
                seen_event_ids.add(event_id)
                seen_idempotency.add(idempotency_key)
                event_context = dict(context)
                event_context.update({"current_revision": expected, "previous_event_hash": event_head})
                violations.extend(self._event_violations(event, event_context, validate_structure=True))
                event_head = event.get("event_hash")
                if expected_sequence is not None:
                    expected_sequence += 1
        return _finish(record, violations, _TRANSACTION_PRECEDENCE)

    def validate_handoff(self, handoff: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        if not isinstance(handoff, dict):
            return _finish(
                handoff,
                [_violation("ERR_HANDOFF_FIELD_MISSING", "Handoff must be an object.")],
                _HANDOFF_PRECEDENCE,
            )
        context = context or {}
        violations: List[Dict[str, Any]] = []
        structural = self._handoff_struct.errors(handoff)
        required_fields = tuple(self.handoff_schema.get("required", ()))
        actual_fields = tuple(handoff)
        missing_fields = [field for field in required_fields if field not in handoff]
        extra_fields = [field for field in actual_fields if field not in required_fields]
        tactic_refs = handoff.get("tactic_refs")
        if isinstance(tactic_refs, list) and len(tactic_refs) > 2:
            violations.append(_violation(
                "ERR_TACTIC_CARDINALITY",
                "A specialist route may select at most two tactics.",
                count=len(tactic_refs),
            ))
        if not handoff.get("evidence_refs") and not handoff.get("assumptions"):
            violations.append(_violation(
                "ERR_HANDOFF_PROVENANCE",
                "Handoff must contain evidence or explicitly marked assumptions.",
            ))
        if missing_fields or extra_fields or len(actual_fields) != 22:
            violations.append(_violation(
                "ERR_HANDOFF_FIELD_MISSING",
                "Handoff must contain exactly the 22 frozen P2 top-level fields.",
                missing_fields=missing_fields,
                extra_fields=extra_fields,
                field_count=len(actual_fields),
            ))
        if structural:
            ignored = []
            for item in structural:
                if item["path"] == "$.tactic_refs" and item["keyword"] == "maxItems":
                    continue
                if (
                    item["path"] in ("$.assumptions", "$.evidence_refs")
                    and item["keyword"] == "minItems"
                    and not handoff.get("evidence_refs")
                    and not handoff.get("assumptions")
                ):
                    continue
                ignored.append(item)
            if ignored:
                violations.append(_violation(
                    "ERR_HANDOFF_FIELD_MISSING",
                    "Handoff does not satisfy the closed P4 field contract.",
                    schema_errors=ignored,
                ))

        revision = handoff.get("state_revision")
        for context_key in ("current_revision", "target_read_revision"):
            if context_key in context and revision != context[context_key]:
                violations.append(_violation(
                    "ERR_HANDOFF_STALE_REVISION",
                    "Handoff revision does not match the immutable target revision.",
                    handoff_revision=revision,
                    context_key=context_key,
                    expected_revision=context[context_key],
                ))
        for key in ("project_ref", "cycle_id"):
            if key in context and handoff.get(key) != context[key]:
                violations.append(_violation(
                    "ERR_HANDOFF_STALE_REVISION",
                    "Handoff identity does not match the target project cycle.",
                    field=key,
                    supplied=handoff.get(key),
                    expected=context[key],
                ))

        from_role = handoff.get("from_role")
        target = handoff.get("to_role")
        if from_role is not None and from_role == target:
            violations.append(_violation(
                "ERR_HANDOFF_OWNER_SCOPE",
                "A role cannot hand off a decision envelope to itself.",
                role=target,
            ))
        owned_domains = {
            domain for domain, owner in self._domain_owner.items() if owner == target
        }
        expected_scope = set(self._domain_owner) - owned_domains
        supplied_scope = handoff.get("scope_boundary_next_does_not_decide")
        if isinstance(supplied_scope, list) and set(supplied_scope) != expected_scope:
            violations.append(_violation(
                "ERR_HANDOFF_SCOPE_BOUNDARY",
                "Scope boundary must be the exact complement of the target role's domains.",
                missing=sorted(expected_scope - set(supplied_scope)),
                unexpected=sorted(set(supplied_scope) - expected_scope),
            ))

        requested = handoff.get("requested_output")
        if isinstance(requested, dict):
            domains = set(requested.get("decision_domains", []))
            if not domains.issubset(owned_domains):
                violations.append(_violation(
                    "ERR_HANDOFF_OWNER_SCOPE",
                    "Requested output asks the target to decide outside its authority.",
                    target_role=target,
                    unauthorized_domains=sorted(domains - owned_domains),
                ))
            events = set(requested.get("proposed_state_events", []))
            allowed_events = set(self._role_events.get(target, []))
            if not events.issubset(allowed_events):
                violations.append(_violation(
                    "ERR_HANDOFF_OWNER_SCOPE",
                    "Requested events exceed the target role's event authority.",
                    target_role=target,
                    unauthorized_events=sorted(events - allowed_events),
                ))
            if "external_execution_authorization" in domains:
                violations.append(_violation(
                    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
                    "External execution authorization is never owned by an analytical role.",
                ))

        input_refs = handoff.get("input_refs")
        if isinstance(input_refs, list):
            for index, item in enumerate(input_refs):
                if not isinstance(item, dict) or not item.get("required"):
                    continue
                if item.get("state_revision") != revision:
                    violations.append(_violation(
                        "ERR_SEQUENCE_DEPENDENCY",
                        "Required input was not validated at the handoff revision.",
                        input_index=index,
                        input_ref=item.get("input_ref"),
                    ))
                if item.get("dependency_status") == "validated" and not self._context_ref_exists(
                    context, "input_registry", item.get("input_ref")
                ):
                    violations.append(_violation(
                        "ERR_SEQUENCE_DEPENDENCY",
                        "Required input does not resolve in the supplied registry.",
                        input_index=index,
                        input_ref=item.get("input_ref"),
                    ))
                if item.get("dependency_status") == "not_applicable" and "not_applicable_decisions" in context:
                    if item.get("input_ref") not in set(context["not_applicable_decisions"]):
                        violations.append(_violation(
                            "ERR_SEQUENCE_DEPENDENCY",
                            "not_applicable input lacks an explicit route decision.",
                            input_ref=item.get("input_ref"),
                        ))

        evidence_claims = set()
        for item in handoff.get("evidence_refs", []) if isinstance(handoff.get("evidence_refs"), list) else []:
            if isinstance(item, dict):
                evidence_claims.update(item.get("claim_refs", []))
                reference = item.get("evidence_id")
                if reference and not self._context_ref_exists(context, "evidence_registry", reference):
                    violations.append(_violation(
                        "ERR_HANDOFF_PROVENANCE",
                        "Handoff evidence does not resolve in the supplied registry.",
                        evidence_ref=reference,
                    ))
        assumption_claims = set()
        for item in handoff.get("assumptions", []) if isinstance(handoff.get("assumptions"), list) else []:
            if isinstance(item, dict):
                assumption_claims.update(item.get("claim_refs", []))
        overlap = sorted(evidence_claims & assumption_claims)
        if overlap:
            violations.append(_violation(
                "ERR_HANDOFF_PROVENANCE",
                "A claim cannot be both evidenced and assumed.",
                claim_refs=overlap,
            ))

        if handoff.get("maturity") == "unknown":
            cross = handoff.get("cross_validation_required")
            required_cross = isinstance(cross, dict) and cross.get("required") is True
            if handoff.get("mode") != "minimo_viavel" or handoff.get("tactic_refs") or not required_cross:
                violations.append(_violation(
                    "ERR_MATURITY_GATE",
                    "Unknown maturity permits only the base minimum-viable method with cross-validation.",
                ))

        maturity_order = {
            "unknown": -1,
            "nascente": 0,
            "em_desenvolvimento": 1,
            "maduro": 2,
            "avancado": 3,
        }
        selected_tactics: List[Dict[str, Any]] = []
        if isinstance(tactic_refs, list):
            for index, tactic_ref in enumerate(tactic_refs):
                if not isinstance(tactic_ref, dict):
                    continue
                tactic_id = tactic_ref.get("tactic_id")
                tactic = self._catalog_by_id.get(tactic_id)
                if tactic is None:
                    violations.append(_violation(
                        "ERR_TACTIC_METADATA_MISSING",
                        "Tactic reference does not resolve in the P3 catalog.",
                        tactic_index=index,
                        tactic_id=tactic_id,
                    ))
                    continue
                selected_tactics.append(tactic)
                if (
                    tactic.get("canonical_path") != tactic_ref.get("canonical_path")
                    or tactic.get("canonical_sha256") != tactic_ref.get("canonical_sha256")
                ):
                    violations.append(_violation(
                        "ERR_CANONICAL_LIBRARY_DRIFT",
                        "Tactic path or hash differs from the immutable P3 catalog.",
                        tactic_id=tactic_id,
                    ))
                if str(tactic.get("pillar", "")).lower() != target:
                    violations.append(_violation(
                        "ERR_TACTIC_METADATA_MISSING",
                        "Tactic belongs to a different specialist pillar.",
                        tactic_id=tactic_id,
                        target_role=target,
                        tactic_pillar=tactic.get("pillar"),
                    ))
                current_maturity = maturity_order.get(handoff.get("maturity"), -1)
                minimum_maturity = maturity_order.get(tactic.get("minimum_maturity"), 99)
                if current_maturity < minimum_maturity:
                    violations.append(_violation(
                        "ERR_MATURITY_GATE",
                        "Tactic exceeds evidenced maturity.",
                        tactic_id=tactic_id,
                        maturity=handoff.get("maturity"),
                        minimum_maturity=tactic.get("minimum_maturity"),
                    ))
                policy = tactic.get("execution_policy", {})
                if policy.get("automatic_selection") == "forbidden":
                    violations.append(_violation(
                        "ERR_MATURITY_GATE",
                        "Tactic execution policy forbids runtime selection.",
                        tactic_id=tactic_id,
                    ))
                reviewed = context.get("planner_reviewed_tactic_ids", _MISSING)
                if (
                    reviewed is not _MISSING
                    and policy.get("automatic_selection") == "planner_review_required"
                    and tactic_id not in set(reviewed)
                ):
                    violations.append(_violation(
                        "ERR_CROSS_VALIDATION_BLOCKED",
                        "Tactic requires an explicit Loop Planning review.",
                        tactic_id=tactic_id,
                    ))

        if len(selected_tactics) == 2:
            output_types = {
                item.get("output_contract", {}).get("output_type") for item in selected_tactics
            }
            dependencies = context.get("tactic_dependencies", [])
            pair = tuple(sorted(item["tactic_id"] for item in selected_tactics))
            normalized_dependencies = {tuple(sorted(item)) for item in dependencies if len(item) == 2}
            if len(output_types) != 2 and pair not in normalized_dependencies:
                violations.append(_violation(
                    "ERR_TACTIC_CARDINALITY",
                    "Two tactics require distinct outputs or an explicit dependency.",
                    tactic_ids=list(pair),
                ))

        bottleneck = handoff.get("bottleneck_ref")
        if isinstance(bottleneck, str) and "unresolved" in bottleneck:
            if not (
                target == "refinar"
                and handoff.get("mode") == "minimo_viavel"
                and handoff.get("maturity") == "unknown"
            ):
                violations.append(_violation(
                    "ERR_HANDOFF_PROVENANCE",
                    "Unresolved bottleneck is valid only for minimum-viable Refinar diagnosis.",
                    bottleneck_ref=bottleneck,
                ))
        if isinstance(bottleneck, str) and "bottleneck_registry" in context:
            record = context["bottleneck_registry"].get(bottleneck) if isinstance(context["bottleneck_registry"], Mapping) else None
            if not isinstance(record, Mapping) or record.get("owner") != "loop_planning":
                violations.append(_violation(
                    "ERR_HANDOFF_PROVENANCE",
                    "Bottleneck reference must resolve to a Loop Planning record.",
                    bottleneck_ref=bottleneck,
                ))

        cross = handoff.get("cross_validation_required")
        if isinstance(cross, dict):
            required = cross.get("required")
            roles = cross.get("roles")
            conflicts = cross.get("conflicts")
            if required is True and not (roles or conflicts):
                violations.append(_violation(
                    "ERR_CROSS_VALIDATION_BLOCKED",
                    "Required cross-validation must name a role or conflict.",
                ))
            if required is False and (roles or conflicts):
                violations.append(_violation(
                    "ERR_CROSS_VALIDATION_BLOCKED",
                    "Non-required cross-validation cannot carry hidden checks.",
                ))

        write_set = requested.get("write_set", []) if isinstance(requested, dict) else []
        parallel_sets = context.get("parallel_write_sets", {})
        if isinstance(parallel_sets, Mapping):
            for sibling, sibling_paths in sorted(parallel_sets.items()):
                collision = sorted(set(write_set) & set(sibling_paths))
                if collision:
                    violations.append(_violation(
                        "ERR_PARALLEL_WRITE_COLLISION",
                        "Parallel handoffs have colliding staged write sets.",
                        sibling=sibling,
                        write_paths=collision,
                    ))
        return _finish(handoff, violations, _HANDOFF_PRECEDENCE)
