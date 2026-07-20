#!/usr/bin/env python3
"""Generate the canonical P4 contracts and deterministic compatibility fixtures."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P2 = ROOT / "artifacts" / "P2"
P3 = ROOT / "artifacts" / "P3"
OUT = ROOT / "artifacts" / "P4"

SCHEMA_VERSION = "2.0"
HANDOFF_VERSION = "1.0"
BASELINE_COMMIT = "3cbf0cf84a038f2cd570883b70988889f037c28e"
LIBRARY_HASH = "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"
ROLES = ["loop_planning", "verbalizar", "orientar", "ampliar", "refinar"]
MATURITY = ["nascente", "em_desenvolvimento", "maduro", "avancado", "unknown"]
MODES = ["completo", "parcial", "minimo_viavel"]
ROUTE_STATUS = ["ready", "needs_evidence", "blocked", "rejected"]
EXPERIMENT_STATES = [
    "proposed", "approved", "instrumented", "running", "completed",
    "cancelled", "invalidated",
]

DECISION_DOMAIN_OWNER = {
    "global_orchestration": "loop_planning",
    "message_and_copy": "verbalizar",
    "lifecycle_segmentation_and_eligibility": "orientar",
    "channel_timing_and_cadence": "ampliar",
    "experiment_performance_and_learning": "refinar",
    "security_privacy_and_data_use": "security_review",
    "external_execution_authorization": "authorized_operator",
}
ROLE_PRIMARY_EVENT = {
    "loop_planning": "maturity_classified",
    "verbalizar": "message_decision_proposed",
    "orientar": "lifecycle_model_proposed",
    "ampliar": "channel_plan_proposed",
    "refinar": "performance_diagnosis_recorded",
}

COMMANDS = {
    "loop.planning": {"canonical": "/loop-planning", "legacy_alias": "/loop-planning-agent", "role": "loop_planning"},
    "loop.verbalizar": {"canonical": "/verbalizar", "legacy_alias": "/verbalizar-agent", "role": "verbalizar"},
    "loop.orientar": {"canonical": "/orientar", "legacy_alias": "/orientar-agent", "role": "orientar"},
    "loop.ampliar": {"canonical": "/ampliar", "legacy_alias": "/ampliar-agent", "role": "ampliar"},
    "loop.refinar": {"canonical": "/refinar", "legacy_alias": "/refinar-agent", "role": "refinar"},
    "loop.projeto": {"canonical": "/projeto", "legacy_alias": "/projeto-template", "role": "loop_planning"},
}

EXPERIMENT_TRANSITIONS = {
    "create": {
        "from": None,
        "to": "proposed",
        "rule_id": "RTE-EXP-001",
        "evidence": [
            ("hypothesis", "hypothesis with specific change and measurable expected result"),
            ("isolated_variable_or_multivariate_design", "one isolated variable or explicit multivariate design"),
            ("control_definition", "control definition"),
            ("success_metric_and_target", "numeric success metric and target set before launch"),
            ("minimum_sample_rule", "minimum sample rule"),
            ("duration_and_early_stop_rule", "minimum duration and early-stop rule"),
            ("post_test_thresholds", "post-test decision thresholds"),
            ("owner_and_created_at", "owner and creation timestamp"),
        ],
    },
    "approve": {
        "from": "proposed", "to": "approved", "rule_id": "RTE-EXP-002",
        "evidence": [
            ("approval_event_id", "approval event ID"),
            ("approver_identity", "approver identity"),
            ("approved_scope", "approved scope"),
            ("approval_timestamp", "approval timestamp"),
        ],
    },
    "instrument": {
        "from": "approved", "to": "instrumented", "rule_id": "RTE-EXP-003",
        "evidence": [
            ("instrumentation_record_id", "instrumentation record ID"),
            ("event_or_metric_schema", "event or metric schema"),
            ("assignment_mechanism", "assignment mechanism"),
            ("qa_result", "QA result"),
            ("sample_plan", "sample plan"),
        ],
    },
    "launch": {
        "from": "instrumented", "to": "running", "rule_id": "RTE-EXP-004",
        "evidence": [
            ("launch_event_id", "launch event ID"),
            ("confirmed_start_timestamp", "confirmed start timestamp"),
            ("live_treatment_and_control_ids", "live treatment and control identifiers"),
            ("audience_allocation", "audience allocation"),
        ],
    },
    "complete": {
        "from": "running", "to": "completed", "rule_id": "RTE-EXP-005",
        "evidence": [
            ("completion_event_id", "completion event ID"),
            ("observation_window_or_early_stop", "observation window or predeclared early-stop trigger"),
            ("result_dataset_ref", "result dataset reference"),
            ("actual_sample", "actual sample"),
            ("metric_result", "metric result"),
            ("quality_checks", "quality checks"),
        ],
    },
    "cancel": {
        "from_any": ["proposed", "approved", "instrumented", "running"],
        "to": "cancelled", "rule_id": "RTE-EXP-006",
        "evidence": [
            ("cancellation_event_id", "cancellation event ID"),
            ("actor", "actor"),
            ("reason", "reason"),
            ("timestamp", "timestamp"),
            ("collected_data_impact", "impact on already collected data"),
        ],
    },
    "invalidate": {
        "from_any": ["instrumented", "running", "completed"],
        "to": "invalidated", "rule_id": "RTE-EXP-007",
        "evidence": [
            ("invalidation_event_id", "invalidation event ID"),
            ("integrity_defect", "integrity defect"),
            ("affected_data", "affected data"),
            ("actor", "actor"),
            ("timestamp", "timestamp"),
            ("remediation_or_replacement_ref", "remediation or replacement experiment reference"),
        ],
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(value: dict, excluded: tuple[str, ...] = ()) -> str:
    payload = {key: val for key, val in value.items() if key not in excluded}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def defs() -> dict:
    return {
        "nonEmptyString": {"type": "string", "minLength": 1, "maxLength": 4096},
        "shortText": {"type": "string", "minLength": 1, "maxLength": 512},
        "reference": {
            "type": "string", "minLength": 1, "maxLength": 512,
            "pattern": "^[^\\u0000-\\u001f\\u007f]+$",
        },
        "projectId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,62}$"},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "dateTime": {"type": "string", "format": "date-time"},
        "role": {"type": "string", "enum": ROLES},
        "maturity": {"type": "string", "enum": MATURITY},
        "mode": {"type": "string", "enum": MODES},
        "referenceArray": {
            "type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/reference"},
        },
    }


def role_contracts(role_matrix: dict) -> tuple[dict, dict, list[str]]:
    authority = {}
    events = {}
    ownership = []
    for role in role_matrix["roles"]:
        role_id = role["canonical_role_id"]
        authority[role_id] = list(role["owns"])
        events[role_id] = list(role["allowed_state_events"])
        ownership.extend(role["owns"])
    return authority, events, sorted(set(ownership))


def build_state_schema() -> dict:
    common = defs()
    common.update({
        "nullableReference": {"anyOf": [{"$ref": "#/$defs/reference"}, {"type": "null"}]},
        "eventLogHead": {
            "type": "object", "additionalProperties": False,
            "required": [
                "path", "head_event_id", "head_event_hash", "head_record_hash",
                "last_event_sequence", "applied_event_count", "committed_transaction_count",
            ],
            "properties": {
                "path": {"const": "events.jsonl"},
                "head_event_id": {"$ref": "#/$defs/nullableReference"},
                "head_event_hash": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                "head_record_hash": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                "last_event_sequence": {"type": "integer", "minimum": 0},
                "applied_event_count": {"type": "integer", "minimum": 0},
                "committed_transaction_count": {"type": "integer", "minimum": 0},
            },
        },
        "projectState": {
            "type": "object", "additionalProperties": False,
            "required": [
                "active_cycle_id", "maturity", "route_status", "accepted_bottleneck_ref",
                "decision_refs", "handoff_refs", "experiment_refs", "learning_refs",
                "known_gap_refs", "legacy_import_refs", "canonical_library",
            ],
            "properties": {
                "active_cycle_id": {"$ref": "#/$defs/nullableReference"},
                "maturity": {"$ref": "#/$defs/maturity"},
                "route_status": {"type": "string", "enum": ROUTE_STATUS},
                "accepted_bottleneck_ref": {"$ref": "#/$defs/nullableReference"},
                "decision_refs": {"$ref": "#/$defs/referenceArray"},
                "handoff_refs": {"$ref": "#/$defs/referenceArray"},
                "experiment_refs": {"$ref": "#/$defs/referenceArray"},
                "learning_refs": {"$ref": "#/$defs/referenceArray"},
                "known_gap_refs": {"$ref": "#/$defs/referenceArray"},
                "legacy_import_refs": {"$ref": "#/$defs/referenceArray"},
                "canonical_library": {
                    "type": "object", "additionalProperties": False,
                    "required": ["baseline_commit", "aggregate_sha256", "prompt_count"],
                    "properties": {
                        "baseline_commit": {"const": BASELINE_COMMIT},
                        "aggregate_sha256": {"const": LIBRARY_HASH},
                        "prompt_count": {"const": 100},
                    },
                },
            },
        },
    })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://loop-marketing.local/schemas/state-2.0.json",
        "title": "Loop Marketing v2 project state snapshot",
        "description": "Derived snapshot; the append-only event ledger is authoritative.",
        "type": "object", "additionalProperties": False,
        "required": [
            "schema_version", "artifact_type", "project_id", "project_ref", "display_name",
            "state_revision", "derived_from_revision", "created_at", "updated_at", "event_log", "state",
        ],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "artifact_type": {"const": "loop_marketing_project_state"},
            "project_id": {"$ref": "#/$defs/projectId"},
            "project_ref": {"$ref": "#/$defs/reference"},
            "display_name": {"type": "string", "minLength": 1, "maxLength": 200},
            "state_revision": {"type": "integer", "minimum": 0},
            "derived_from_revision": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
            "created_at": {"$ref": "#/$defs/dateTime"},
            "updated_at": {"$ref": "#/$defs/dateTime"},
            "event_log": {"$ref": "#/$defs/eventLogHead"},
            "state": {"$ref": "#/$defs/projectState"},
        },
        "$defs": common,
        "x-loop-contract": {
            "namespace": ".loop-marketing/",
            "canonical_path": ".loop-marketing/state/projects/<project_id>/snapshots/latest.json",
            "source_of_truth": ".loop-marketing/state/projects/<project_id>/events.jsonl",
            "concurrency": "optimistic_compare_and_swap_on_state_revision",
            "revision_rule": "Each committed non-duplicate transaction advances exactly one revision; its one or more events share the same expected and resulting revisions.",
            "recovery_rule": "Rebuild a missing or stale snapshot from the verified event ledger; never infer a forward state from prose.",
        },
    }


def build_event_schema(event_authority: dict) -> dict:
    event_types = sorted({event for values in event_authority.values() for event in values})
    common = defs()
    common.update({
        "chainHead": {"anyOf": [{"const": "GENESIS"}, {"$ref": "#/$defs/sha256"}]},
        "claim": {
            "type": "object", "additionalProperties": False,
            "required": ["claim_id", "kind", "text", "provenance", "confidence"],
            "properties": {
                "claim_id": {"$ref": "#/$defs/reference"},
                "kind": {"type": "string", "enum": ["fact", "user_interpretation", "symptom", "hypothesis"]},
                "text": {"$ref": "#/$defs/nonEmptyString"},
                "provenance": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "source_ref": {"$ref": "#/$defs/reference"},
                        "observed_at": {"$ref": "#/$defs/dateTime"},
                        "rationale": {"$ref": "#/$defs/nonEmptyString"},
                    },
                },
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
        "payload": {
            "type": "object", "additionalProperties": False,
            "required": ["payload_version", "claims", "data"],
            "properties": {
                "payload_version": {"const": "1.0"},
                "claims": {"type": "array", "items": {"$ref": "#/$defs/claim"}},
                "data": {"type": "object"},
            },
        },
        "event": {
            "type": "object", "additionalProperties": False,
            "required": [
                "schema_version", "event_id", "event_type", "project_ref", "cycle_id",
                "actor_role", "command_id", "occurred_at", "state_revision",
                "resulting_state_revision", "event_sequence", "transaction_id", "effect",
                "idempotency_key", "previous_event_hash", "event_hash", "evidence_refs", "payload",
            ],
            "properties": {
                "schema_version": {"const": SCHEMA_VERSION},
                "event_id": {"type": "string", "pattern": "^evt_[a-z0-9][a-z0-9_-]{2,127}$"},
                "event_type": {"type": "string", "enum": event_types},
                "project_ref": {"$ref": "#/$defs/reference"},
                "cycle_id": {"$ref": "#/$defs/reference"},
                "actor_role": {"$ref": "#/$defs/role"},
                "command_id": {"type": "string", "enum": sorted(COMMANDS)},
                "occurred_at": {"$ref": "#/$defs/dateTime"},
                "state_revision": {"type": "integer", "minimum": 0},
                "resulting_state_revision": {"type": "integer", "minimum": 1},
                "event_sequence": {"type": "integer", "minimum": 1},
                "transaction_id": {"type": "string", "pattern": "^tx_[a-z0-9][a-z0-9_-]{2,127}$"},
                "effect": {"type": "string", "enum": ["observation", "proposal", "transition_validation", "integration"]},
                "idempotency_key": {"type": "string", "pattern": "^idem_[a-z0-9][a-z0-9_-]{2,127}$"},
                "previous_event_hash": {"$ref": "#/$defs/chainHead"},
                "event_hash": {"$ref": "#/$defs/sha256"},
                "evidence_refs": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"$ref": "#/$defs/reference"},
                },
                "payload": {"$ref": "#/$defs/payload"},
            },
        },
    })
    transition_extension = {}
    for name, transition in EXPERIMENT_TRANSITIONS.items():
        item = {key: copy.deepcopy(value) for key, value in transition.items() if key != "evidence"}
        item["required_evidence"] = [
            {"evidence_key": key, "description": description}
            for key, description in transition["evidence"]
        ]
        transition_extension[name] = item
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://loop-marketing.local/schemas/event-2.0.json",
        "title": "Loop Marketing v2 append-only event transaction record",
        "type": "object", "additionalProperties": False,
        "required": [
            "schema_version", "record_type", "transaction_id", "project_ref",
            "expected_state_revision", "resulting_state_revision", "committed_at",
            "integrated_by_role", "reducer_version", "idempotency_key",
            "previous_record_hash", "record_hash", "events",
        ],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "record_type": {"const": "event_transaction"},
            "transaction_id": {"type": "string", "pattern": "^tx_[a-z0-9][a-z0-9_-]{2,127}$"},
            "project_ref": {"$ref": "#/$defs/reference"},
            "expected_state_revision": {"type": "integer", "minimum": 0},
            "resulting_state_revision": {"type": "integer", "minimum": 1},
            "committed_at": {"$ref": "#/$defs/dateTime"},
            "integrated_by_role": {"const": "loop_planning"},
            "reducer_version": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"},
            "idempotency_key": {"type": "string", "pattern": "^idem_[a-z0-9][a-z0-9_-]{2,127}$"},
            "previous_record_hash": {"$ref": "#/$defs/chainHead"},
            "record_hash": {"$ref": "#/$defs/sha256"},
            "events": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"$ref": "#/$defs/event"},
            },
        },
        "$defs": common,
        "x-loop-contract": {
            "canonical_path": ".loop-marketing/state/projects/<project_id>/events.jsonl",
            "authority_by_role": event_authority,
            "command_contract": COMMANDS,
            "canonical_event_type_count": len(event_types),
            "hash_canonicalization": "RFC 8785 JSON; exclude event_hash for event hashes and record_hash for transaction hashes.",
            "revision_rule": "One committed transaction advances one state revision; all nested events share the expected and resulting revisions.",
            "audit_records_outside_domain_authority": ["legacy.imported", "recovery", "rollback"],
            "idempotency": {
                "same_transaction_or_event_identifiers_and_content": "noop",
                "same_identifier_with_different_content": "reject",
                "partial_batch_retry": "reject",
            },
            "experiment_state_machine": transition_extension,
        },
    }


def build_handoff_schema(handoff_fields: list[str], ownership_fields: list[str]) -> dict:
    common = defs()
    common.update({
        "ownershipField": {"type": "string", "enum": ownership_fields},
        "tacticRef": {
            "type": "object", "additionalProperties": False,
            "required": ["tactic_id", "canonical_path", "canonical_sha256", "selection_reason", "route_node_id"],
            "properties": {
                "tactic_id": {"type": "string", "pattern": "^lm\\.(verbalizar|orientar|ampliar|refinar)\\.[a-z0-9][a-z0-9-]*$"},
                "canonical_path": {"type": "string", "pattern": "^biblioteca/(Verbalizar|Orientar|Ampliar|Refinar)/[^/]+\\.md$"},
                "canonical_sha256": {"$ref": "#/$defs/sha256"},
                "selection_reason": {"$ref": "#/$defs/nonEmptyString"},
                "route_node_id": {"$ref": "#/$defs/reference"},
            },
        },
        "decisionRef": {
            "type": "object", "additionalProperties": False,
            "required": ["decision_ref", "owner_role", "decision_field"],
            "properties": {
                "decision_ref": {"$ref": "#/$defs/reference"},
                "owner_role": {"$ref": "#/$defs/role"},
                "decision_field": {"$ref": "#/$defs/ownershipField"},
            },
        },
        "assumption": {
            "type": "object", "additionalProperties": False,
            "required": ["assumption_id", "claim", "rationale", "confidence"],
            "properties": {
                "assumption_id": {"$ref": "#/$defs/reference"},
                "claim": {"$ref": "#/$defs/nonEmptyString"},
                "rationale": {"$ref": "#/$defs/nonEmptyString"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
        "knownGap": {
            "type": "object", "additionalProperties": False,
            "required": ["gap_id", "description", "impact"],
            "properties": {
                "gap_id": {"$ref": "#/$defs/reference"},
                "description": {"$ref": "#/$defs/nonEmptyString"},
                "impact": {"$ref": "#/$defs/nonEmptyString"},
            },
        },
        "requestedOutput": {
            "type": "object", "additionalProperties": False,
            "required": ["output_id", "description", "owner_role", "decision_fields"],
            "properties": {
                "output_id": {"$ref": "#/$defs/reference"},
                "description": {"$ref": "#/$defs/nonEmptyString"},
                "owner_role": {"$ref": "#/$defs/role"},
                "decision_fields": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"$ref": "#/$defs/ownershipField"},
                },
            },
        },
        "crossValidation": {
            "type": "object", "additionalProperties": False,
            "required": ["required", "role_refs", "conflict_refs", "reason"],
            "properties": {
                "required": {"type": "boolean"},
                "role_refs": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/role"}},
                "conflict_refs": {"$ref": "#/$defs/referenceArray"},
                "reason": {"anyOf": [{"$ref": "#/$defs/nonEmptyString"}, {"type": "null"}]},
            },
        },
        "escalation": {
            "type": "object", "additionalProperties": False,
            "required": ["condition_id", "condition", "route_to", "blocking"],
            "properties": {
                "condition_id": {"$ref": "#/$defs/reference"},
                "condition": {"$ref": "#/$defs/nonEmptyString"},
                "route_to": {"$ref": "#/$defs/reference"},
                "blocking": {"type": "boolean"},
            },
        },
    })
    props = {
        "handoff_id": {"type": "string", "pattern": "^handoff_[a-z0-9][a-z0-9_-]{2,127}$"},
        "contract_version": {"const": HANDOFF_VERSION},
        "project_ref": {"$ref": "#/$defs/reference"},
        "cycle_id": {"$ref": "#/$defs/reference"},
        "state_revision": {"type": "integer", "minimum": 0},
        "from_role": {"$ref": "#/$defs/role"},
        "to_role": {"$ref": "#/$defs/role"},
        "created_at": {"$ref": "#/$defs/dateTime"},
        "objective": {"$ref": "#/$defs/nonEmptyString"},
        "mode": {"$ref": "#/$defs/mode"},
        "maturity": {"$ref": "#/$defs/maturity"},
        "bottleneck_ref": {"anyOf": [{"$ref": "#/$defs/reference"}, {"type": "null"}]},
        "input_refs": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"$ref": "#/$defs/reference"}},
        "tactic_refs": {"type": "array", "maxItems": 2, "uniqueItems": True, "items": {"$ref": "#/$defs/tacticRef"}},
        "decisions_to_respect": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/decisionRef"}},
        "scope_boundary_next_does_not_decide": {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"$ref": "#/$defs/ownershipField"},
        },
        "evidence_refs": {"$ref": "#/$defs/referenceArray"},
        "assumptions": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/assumption"}},
        "known_gaps": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/knownGap"}},
        "requested_output": {"$ref": "#/$defs/requestedOutput"},
        "cross_validation_required": {"$ref": "#/$defs/crossValidation"},
        "escalation_conditions": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/escalation"}},
    }
    assert list(props) == handoff_fields
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://loop-marketing.local/schemas/handoff-1.0.json",
        "title": "Loop Marketing canonical 22-field handoff",
        "type": "object", "additionalProperties": False,
        "required": handoff_fields,
        "properties": props,
        "$defs": common,
        "x-loop-contract": {
            "canonical_source": "artifacts/P2/role-matrix.json#handoff_contract",
            "field_count": 22,
            "semantic_rejection_codes": [
                "ERR_HANDOFF_FIELD_MISSING", "ERR_HANDOFF_STALE_REVISION",
                "ERR_HANDOFF_SCOPE_BOUNDARY", "ERR_HANDOFF_OWNER_SCOPE",
                "ERR_HANDOFF_PROVENANCE", "ERR_SEQUENCE_DEPENDENCY",
                "ERR_TACTIC_CARDINALITY", "ERR_CANONICAL_LIBRARY_DRIFT",
            ],
        },
    }


def integrate_handoff_schema(proposal: dict, handoff_fields: list[str]) -> dict:
    """Integrate the independently reviewed proposal and close P4 decisions."""
    schema = copy.deepcopy(proposal)
    if schema.get("required") != handoff_fields:
        raise ValueError("Handoff proposal does not preserve canonical P2 field order")
    if list(schema.get("properties", {})) != handoff_fields:
        raise ValueError("Handoff proposal properties differ from canonical P2 fields")
    schema["minProperties"] = 22
    schema["maxProperties"] = 22
    domains = schema["$defs"]["decisionDomain"]["enum"]
    for domain in DECISION_DOMAIN_OWNER:
        if domain not in domains:
            domains.append(domain)
    schema["$defs"]["decisionDomain"]["enum"] = list(DECISION_DOMAIN_OWNER)
    schema["x-loop-contract"] = {
        "canonical_source": "artifacts/P2/role-matrix.json#handoff_contract",
        "field_count": 22,
        "decision_domain_owner": DECISION_DOMAIN_OWNER,
        "scope_boundary_rule": "Exact set complement of the target role's owned decision domains; security and external execution always remain outside canonical analytical roles.",
        "unresolved_bottleneck_rule": "Use a resolvable loop_planning unresolved-bottleneck record; null and specialist observations are invalid.",
        "semantic_rejection_codes": [
            "ERR_HANDOFF_FIELD_MISSING", "ERR_HANDOFF_STALE_REVISION",
            "ERR_HANDOFF_SCOPE_BOUNDARY", "ERR_HANDOFF_OWNER_SCOPE",
            "ERR_HANDOFF_PROVENANCE", "ERR_SEQUENCE_DEPENDENCY",
            "ERR_MATURITY_GATE", "ERR_TACTIC_METADATA_MISSING",
            "ERR_TACTIC_CARDINALITY", "ERR_PARALLELISM_UNSAFE",
            "ERR_PARALLEL_WRITE_COLLISION", "ERR_OWNER_SCOPE_VIOLATION",
            "ERR_EXTERNAL_MUTATION_UNAUTHORIZED", "ERR_CROSS_VALIDATION_BLOCKED",
        ],
    }
    return schema


def base_state(revision: int = 0) -> dict:
    has_events = revision > 0
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "loop_marketing_project_state",
        "project_id": "projeto-exemplo",
        "project_ref": "project:projeto-exemplo",
        "display_name": "Projeto Exemplo",
        "state_revision": revision,
        "derived_from_revision": revision - 1 if has_events else None,
        "created_at": "2026-07-17T09:00:00-03:00",
        "updated_at": "2026-07-17T09:00:00-03:00",
        "event_log": {
            "path": "events.jsonl",
            "head_event_id": "evt_seed_001" if has_events else None,
            "head_event_hash": "a" * 64 if has_events else None,
            "head_record_hash": "b" * 64 if has_events else None,
            "last_event_sequence": revision if has_events else 0,
            "applied_event_count": revision,
            "committed_transaction_count": revision,
        },
        "state": {
            "active_cycle_id": "cycle:001" if has_events else None,
            "maturity": "unknown",
            "route_status": "needs_evidence",
            "accepted_bottleneck_ref": None,
            "decision_refs": [],
            "handoff_refs": [],
            "experiment_refs": [],
            "learning_refs": [],
            "known_gap_refs": [],
            "legacy_import_refs": [],
            "canonical_library": {
                "baseline_commit": BASELINE_COMMIT,
                "aggregate_sha256": LIBRARY_HASH,
                "prompt_count": 100,
            },
        },
    }


def fact_claim() -> dict:
    return {
        "claim_id": "claim:001",
        "kind": "fact",
        "text": "O diagnóstico possui evidência referenciada.",
        "provenance": {
            "source_ref": "evidence:diagnostic-001",
            "observed_at": "2026-07-17T09:55:00-03:00",
        },
        "confidence": "high",
    }


def event(
    event_id: str = "evt_maturity_001",
    event_type: str = "maturity_classified",
    actor_role: str = "loop_planning",
    command_id: str = "loop.planning",
    revision: int = 0,
    previous_hash: str = "GENESIS",
    data: dict | None = None,
    evidence_refs: list[str] | None = None,
    idempotency_key: str | None = None,
    event_sequence: int | None = None,
    transaction_id: str | None = None,
    effect: str = "integration",
) -> dict:
    value = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "project_ref": "project:projeto-exemplo",
        "cycle_id": "cycle:001",
        "actor_role": actor_role,
        "command_id": command_id,
        "occurred_at": "2026-07-17T10:00:00-03:00",
        "state_revision": revision,
        "resulting_state_revision": revision + 1,
        "event_sequence": event_sequence or revision + 1,
        "transaction_id": transaction_id or f"tx_{event_id[4:]}",
        "effect": effect,
        "idempotency_key": idempotency_key or f"idem_{event_id[4:]}",
        "previous_event_hash": previous_hash,
        "event_hash": "0" * 64,
        "evidence_refs": evidence_refs or ["evidence:diagnostic-001"],
        "payload": {
            "payload_version": "1.0",
            "claims": [fact_claim()],
            "data": data or {"maturity": "em_desenvolvimento"},
        },
    }
    value["event_hash"] = canonical_hash(value, ("event_hash",))
    return value


def transition_event(action: str, revision: int = 1, previous_hash: str = "GENESIS") -> dict:
    transition = EXPERIMENT_TRANSITIONS[action]
    evidence_map = {
        key: f"evidence:experiment-{action}-{key}"
        for key, _description in transition["evidence"]
    }
    data = {
        "experiment_id": "experiment:exp-001",
        "from": transition.get("from", transition.get("from_any", [None])[0]),
        "to": transition["to"],
        "transition_rule_id": transition["rule_id"],
        "evidence_map": evidence_map,
    }
    return event(
        event_id=f"evt_experiment_{action}_001",
        event_type="experiment_created_as_proposed" if action == "create" else "experiment_transition_evidence_validated",
        actor_role="refinar",
        command_id="loop.refinar",
        revision=revision,
        previous_hash=previous_hash,
        data=data,
        evidence_refs=list(evidence_map.values()),
        effect="transition_validation",
    )


def transaction(
    events: list[dict],
    transaction_id: str,
    expected_revision: int,
    previous_record_hash: str = "GENESIS",
    idempotency_key: str | None = None,
) -> dict:
    event_head = events[0]["previous_event_hash"]
    for item in events:
        item["transaction_id"] = transaction_id
        item["state_revision"] = expected_revision
        item["resulting_state_revision"] = expected_revision + 1
        item["previous_event_hash"] = event_head
        item["event_hash"] = canonical_hash(item, ("event_hash",))
        event_head = item["event_hash"]
    value = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "event_transaction",
        "transaction_id": transaction_id,
        "project_ref": events[0]["project_ref"],
        "expected_state_revision": expected_revision,
        "resulting_state_revision": expected_revision + 1,
        "committed_at": "2026-07-17T10:00:01-03:00",
        "integrated_by_role": "loop_planning",
        "reducer_version": "2.0.0",
        "idempotency_key": idempotency_key or f"idem_{transaction_id[3:]}",
        "previous_record_hash": previous_record_hash,
        "record_hash": "0" * 64,
        "events": events,
    }
    value["record_hash"] = canonical_hash(value, ("record_hash",))
    return value


def owned_domains_for(role: str) -> list[str]:
    return [domain for domain, owner in DECISION_DOMAIN_OWNER.items() if owner == role]


def scope_for(role: str) -> list[str]:
    owned = set(owned_domains_for(role))
    return [domain for domain in DECISION_DOMAIN_OWNER if domain not in owned]


def catalog_tactic(catalog: dict, role: str) -> dict:
    pillar = role.capitalize()
    tactic = next(item for item in catalog["tactics"] if item["pillar"] == pillar)
    return {
        "tactic_id": tactic["tactic_id"],
        "canonical_path": tactic["canonical_path"],
        "canonical_sha256": tactic["canonical_sha256"],
        "selection_reason": "A tática cobre a necessidade do route node e respeita o gate de maturidade.",
    }


def base_handoff(authority: dict, catalog: dict, to_role: str = "verbalizar", revision: int = 1) -> dict:
    decision_domain = owned_domains_for(to_role)[0]
    return {
        "handoff_id": f"handoff:{to_role}:001",
        "contract_version": HANDOFF_VERSION,
        "project_ref": "project:projeto-exemplo",
        "cycle_id": "cycle:001",
        "state_revision": revision,
        "from_role": "loop_planning" if to_role != "loop_planning" else "refinar",
        "to_role": to_role,
        "created_at": "2026-07-17T10:05:00-03:00",
        "objective": "Produzir o próximo contrato de domínio dentro da autoridade do receptor.",
        "mode": "parcial",
        "maturity": "em_desenvolvimento",
        "bottleneck_ref": "bottleneck:001",
        "input_refs": [{
            "input_ref": "artifact:brief-001",
            "input_kind": "artifact",
            "state_revision": revision,
            "required": True,
            "dependency_status": "validated",
            "content_sha256": "a" * 64,
        }],
        "tactic_refs": [] if to_role == "loop_planning" else [catalog_tactic(catalog, to_role)],
        "decisions_to_respect": [],
        "scope_boundary_next_does_not_decide": scope_for(to_role),
        "evidence_refs": [{
            "evidence_id": "evidence:diagnostic-001",
            "source_ref": "artifact:diagnostic-001",
            "observed_at": "2026-07-17T09:55:00-03:00",
            "content_sha256": "c" * 64,
            "claim_refs": ["claim:001"],
        }],
        "assumptions": [],
        "known_gaps": [],
        "requested_output": {
            "output_id": f"output:{to_role}:001",
            "description": "Registrar uma decisão pertencente ao domínio do receptor.",
            "decision_domains": [decision_domain],
            "artifact_types": ["domain-contract"],
            "acceptance_criteria": ["A saída respeita owner, evidência e revisão do estado."],
            "write_set": [f"state.outputs.{to_role}"],
            "proposed_state_events": [ROLE_PRIMARY_EVENT[to_role]],
        },
        "cross_validation_required": {
            "required": False,
            "roles": [],
            "conflicts": [],
        },
        "escalation_conditions": [
            {
                "condition_id": "escalation:stale-revision",
                "when": "A revisão do estado mudou antes da integração.",
                "target": "loop_planning",
                "action": "Reidratar e regenerar ou revalidar o handoff completo.",
                "blocking": True,
                "rejection_code": "ERR_HANDOFF_STALE_REVISION",
            }
        ],
    }


def case(case_id: str, expected: str, instance: dict, expected_code: str | None = None, context: dict | None = None) -> dict:
    result = {"case_id": case_id, "expected": expected, "instance": instance}
    if expected_code:
        result["expected_code"] = expected_code
    if context:
        result["context"] = context
    return result


def build_fixtures(authority: dict, catalog: dict) -> dict:
    state_ok = base_state(0)
    state_bad_revision = base_state(2)
    state_bad_revision["derived_from_revision"] = 0
    state_bad_count = base_state(2)
    state_bad_count["event_log"]["applied_event_count"] = 1
    state_path_escape = base_state(0)
    state_path_escape["project_id"] = "../escape"

    evt_ok = event()
    evt_bad_authority = event(
        event_id="evt_wrong_owner_001", event_type="bottleneck_accepted",
        actor_role="verbalizar", command_id="loop.verbalizar",
    )
    evt_stale = event(event_id="evt_stale_001", revision=1, previous_hash="a" * 64)
    evt_hash = copy.deepcopy(evt_ok)
    evt_hash["payload"]["data"]["maturity"] = "maduro"
    evt_no_evidence = event(event_id="evt_no_evidence_001")
    evt_no_evidence["evidence_refs"] = []
    evt_no_evidence["event_hash"] = canonical_hash(evt_no_evidence, ("event_hash",))
    evt_bad_claim = event(event_id="evt_bad_claim_001")
    evt_bad_claim["payload"]["claims"][0]["provenance"] = {}
    evt_bad_claim["event_hash"] = canonical_hash(evt_bad_claim, ("event_hash",))

    exp_ok = transition_event("approve")
    exp_skip = transition_event("approve")
    exp_skip["event_id"] = "evt_experiment_skip_001"
    exp_skip["idempotency_key"] = "idem_experiment_skip_001"
    exp_skip["payload"]["data"]["from"] = "proposed"
    exp_skip["payload"]["data"]["to"] = "running"
    exp_skip["event_hash"] = canonical_hash(exp_skip, ("event_hash",))
    exp_missing = transition_event("instrument")
    exp_missing["event_id"] = "evt_experiment_missing_001"
    exp_missing["idempotency_key"] = "idem_experiment_missing_001"
    exp_missing["payload"]["data"]["evidence_map"].pop("qa_result")
    exp_missing["event_hash"] = canonical_hash(exp_missing, ("event_hash",))

    first = event(event_id="evt_chain_001", idempotency_key="idem_chain_001")
    second = event(
        event_id="evt_chain_002", event_type="pillar_scores_recorded", revision=1,
        previous_hash=first["event_hash"], idempotency_key="idem_chain_002",
        data={"pillar_score_refs": ["score:001"]},
    )
    idem_conflict = copy.deepcopy(first)
    idem_conflict["event_id"] = "evt_chain_conflict_001"
    idem_conflict["payload"]["data"]["maturity"] = "maduro"
    idem_conflict["event_hash"] = canonical_hash(idem_conflict, ("event_hash",))
    broken_chain = copy.deepcopy(second)
    broken_chain["event_id"] = "evt_chain_broken_001"
    broken_chain["idempotency_key"] = "idem_chain_broken_001"
    broken_chain["previous_event_hash"] = "b" * 64
    broken_chain["event_hash"] = canonical_hash(broken_chain, ("event_hash",))
    event_hash_only_replay = copy.deepcopy(first)
    event_hash_only_replay["event_hash"] = "f" * 64

    tx_single = transaction(
        [event(event_id="evt_tx_single_001", event_sequence=1)],
        "tx_single_001", 0,
    )
    tx_batch = transaction(
        [
            event(event_id="evt_tx_batch_001", event_sequence=1),
            event(
                event_id="evt_tx_batch_002", event_type="pillar_scores_recorded",
                event_sequence=2, data={"pillar_score_refs": ["score:001"]},
            ),
        ],
        "tx_batch_001", 0,
    )
    tx_stale = copy.deepcopy(tx_single)
    tx_hash = copy.deepcopy(tx_single)
    tx_hash["events"][0]["payload"]["data"]["maturity"] = "maduro"
    tx_mixed_revision = copy.deepcopy(tx_batch)
    tx_mixed_revision["events"][1]["state_revision"] = 1
    tx_mixed_revision["events"][1]["event_hash"] = canonical_hash(tx_mixed_revision["events"][1], ("event_hash",))
    tx_mixed_revision["record_hash"] = canonical_hash(tx_mixed_revision, ("record_hash",))

    tx_chain_second = transaction(
        [event(
            event_id="evt_tx_chain_002", event_type="pillar_scores_recorded",
            revision=1, event_sequence=2,
            previous_hash=tx_single["events"][-1]["event_hash"],
            data={"pillar_score_refs": ["score:002"]},
        )],
        "tx_chain_002", 1, previous_record_hash=tx_single["record_hash"],
    )
    tx_content_collision = copy.deepcopy(tx_single)
    tx_content_collision["events"][0]["payload"]["data"]["maturity"] = "maduro"
    tx_content_collision["events"][0]["event_hash"] = canonical_hash(tx_content_collision["events"][0], ("event_hash",))
    tx_content_collision["record_hash"] = canonical_hash(tx_content_collision, ("record_hash",))
    tx_tampered_claimed_replay = copy.deepcopy(tx_single)
    tx_tampered_claimed_replay["events"][0]["payload"]["data"]["maturity"] = "maduro"
    tx_idempotency_collision = copy.deepcopy(tx_single)
    tx_idempotency_collision["transaction_id"] = "tx_idempotency_collision_001"
    tx_idempotency_collision["events"][0]["transaction_id"] = "tx_idempotency_collision_001"
    tx_idempotency_collision["events"][0]["event_hash"] = canonical_hash(tx_idempotency_collision["events"][0], ("event_hash",))
    tx_idempotency_collision["record_hash"] = canonical_hash(tx_idempotency_collision, ("record_hash",))
    tx_partial_retry = copy.deepcopy(tx_batch)
    tx_partial_retry["events"] = tx_partial_retry["events"][:1]
    tx_partial_retry["record_hash"] = canonical_hash(tx_partial_retry, ("record_hash",))
    tx_broken_record_chain = copy.deepcopy(tx_chain_second)
    tx_broken_record_chain["transaction_id"] = "tx_broken_record_chain_001"
    tx_broken_record_chain["idempotency_key"] = "idem_broken_record_chain_001"
    tx_broken_record_chain["previous_record_hash"] = "f" * 64
    tx_broken_record_chain["events"][0]["transaction_id"] = "tx_broken_record_chain_001"
    tx_broken_record_chain["events"][0]["event_hash"] = canonical_hash(tx_broken_record_chain["events"][0], ("event_hash",))
    tx_broken_record_chain["record_hash"] = canonical_hash(tx_broken_record_chain, ("record_hash",))

    handoff_ok = base_handoff(authority, catalog, "verbalizar")
    handoff_cases = [
        case("HO-POS-001", "accept", handoff_ok, context={"current_revision": 1}),
    ]
    for role in ROLES:
        handoff_cases.append(case(
            f"HO-POS-ROLE-{role.upper()}", "accept", base_handoff(authority, catalog, role),
            context={"current_revision": 1},
        ))
    missing = copy.deepcopy(handoff_ok)
    missing.pop("known_gaps")
    handoff_cases.append(case("HO-NEG-MISSING", "reject", missing, "ERR_HANDOFF_FIELD_MISSING", {"current_revision": 1}))
    extra = copy.deepcopy(handoff_ok)
    extra["role_specific_payload"] = {}
    handoff_cases.append(case("HO-NEG-EXTRA", "reject", extra, "ERR_HANDOFF_FIELD_MISSING", {"current_revision": 1}))
    stale = copy.deepcopy(handoff_ok)
    handoff_cases.append(case("HO-NEG-STALE", "reject", stale, "ERR_HANDOFF_STALE_REVISION", {"current_revision": 2}))
    scope = copy.deepcopy(handoff_ok)
    scope["scope_boundary_next_does_not_decide"].pop()
    handoff_cases.append(case("HO-NEG-SCOPE", "reject", scope, "ERR_HANDOFF_SCOPE_BOUNDARY", {"current_revision": 1}))
    owner = copy.deepcopy(handoff_ok)
    owner["requested_output"]["decision_domains"] = ["lifecycle_segmentation_and_eligibility"]
    handoff_cases.append(case("HO-NEG-OWNER", "reject", owner, "ERR_HANDOFF_OWNER_SCOPE", {"current_revision": 1}))
    provenance = copy.deepcopy(handoff_ok)
    provenance["evidence_refs"] = []
    handoff_cases.append(case("HO-NEG-PROVENANCE", "reject", provenance, "ERR_HANDOFF_PROVENANCE", {"current_revision": 1}))
    tactics = copy.deepcopy(handoff_ok)
    tactics["tactic_refs"] = [copy.deepcopy(tactics["tactic_refs"][0]) for _ in range(3)]
    for index, item in enumerate(tactics["tactic_refs"]):
        item["tactic_id"] = item["tactic_id"] + f"-invalid-{index}"
    handoff_cases.append(case("HO-NEG-TACTIC-CARDINALITY", "reject", tactics, "ERR_TACTIC_CARDINALITY", {"current_revision": 1}))
    tactic_drift = copy.deepcopy(handoff_ok)
    tactic_drift["tactic_refs"][0]["canonical_sha256"] = "f" * 64
    handoff_cases.append(case("HO-NEG-TACTIC-DRIFT", "reject", tactic_drift, "ERR_CANONICAL_LIBRARY_DRIFT", {"current_revision": 1}))
    null_bottleneck = base_handoff(authority, catalog, "refinar")
    null_bottleneck["bottleneck_ref"] = "bottleneck:unresolved-001"
    null_bottleneck["mode"] = "minimo_viavel"
    null_bottleneck["maturity"] = "unknown"
    null_bottleneck["tactic_refs"] = []
    null_bottleneck["cross_validation_required"] = {
        "required": True, "roles": ["loop_planning"], "conflicts": [],
    }
    handoff_cases.append(case("HO-POS-NEEDS-EVIDENCE", "accept", null_bottleneck, context={"current_revision": 1}))
    bad_null = copy.deepcopy(handoff_ok)
    bad_null["bottleneck_ref"] = None
    handoff_cases.append(case("HO-NEG-NULL-BOTTLENECK", "reject", bad_null, "ERR_HANDOFF_FIELD_MISSING", {"current_revision": 1}))

    dry_run = {
        "migration_id": "migration:mig-001",
        "report_sha256": "9" * 64,
        "source_inventory_sha256": "8" * 64,
        "destination_precondition_sha256": "7" * 64,
        "migrator_version": "2.0.0",
        "project_id": "projeto-exemplo",
    }
    confirmation = {
        "migration_id": dry_run["migration_id"],
        "report_sha256": dry_run["report_sha256"],
        "source_inventory_sha256": dry_run["source_inventory_sha256"],
        "destination_precondition_sha256": dry_run["destination_precondition_sha256"],
        "migrator_version": dry_run["migrator_version"],
        "project_id": dry_run["project_id"],
        "operation": "promote",
        "confirmed_at": "2026-07-17T10:15:00-03:00",
    }

    def mig_input(sources: list[dict], **overrides) -> dict:
        value = {
            "legacy_sources": sources,
            "canonical_v2": None,
            "explicit_path": False,
            "dry_run": copy.deepcopy(dry_run),
            "confirmation": None,
            "promotion_requested": False,
            "current_source_inventory_sha256": dry_run["source_inventory_sha256"],
            "current_destination_precondition_sha256": dry_run["destination_precondition_sha256"],
        }
        value.update(overrides)
        return value

    migration_cases = [
        {"case_id": "MIG-POS-CLAUDE-ONLY", "expected": "dry_run_ready", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "a" * 64, "schema_version": "1.2"}])},
        {"case_id": "MIG-POS-CODEX-DRIFT-ONLY", "expected": "dry_run_ready", "input": mig_input([{"namespace": ".Codex/loop-marketing/", "content_hash": "b" * 64, "schema_version": "1.2"}])},
        {"case_id": "MIG-POS-IDENTICAL-NAMESPACES", "expected": "dry_run_ready", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "c" * 64, "schema_version": "1.2"}, {"namespace": ".Codex/loop-marketing/", "content_hash": "c" * 64, "schema_version": "1.2"}])},
        {"case_id": "MIG-NEG-DIVERGENT-NAMESPACES", "expected": "blocked", "expected_code": "LM-COMPAT-NAMESPACE-CONFLICT", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "d" * 64, "schema_version": "1.2"}, {"namespace": ".Codex/loop-marketing/", "content_hash": "e" * 64, "schema_version": "1.2"}])},
        {"case_id": "MIG-POS-V2-WINS", "expected": "report_only", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "f" * 64, "schema_version": "1.2"}], canonical_v2={"present": True, "valid": True}, promotion_requested=True, confirmation=copy.deepcopy(confirmation))},
        {"case_id": "MIG-NEG-PATH-ESCAPE", "expected": "blocked", "expected_code": "LM-COMPAT-PATH-ESCAPE", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "1" * 64, "schema_version": "1.2"}], path_contained=False)},
        {"case_id": "MIG-NEG-FUTURE-SCHEMA", "expected": "blocked", "expected_code": "LM-COMPAT-FUTURE-SCHEMA", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "2" * 64, "schema_version": "9.0"}])},
        {"case_id": "MIG-NEG-SECRET", "expected": "blocked", "expected_code": "LM-COMPAT-SECRET-DETECTED", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "3" * 64, "schema_version": "1.2"}], secret_detected=True)},
        {"case_id": "MIG-NEG-CONFIRMATION-REQUIRED", "expected": "blocked", "expected_code": "LM-COMPAT-CONFIRMATION-REQUIRED", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "4" * 64, "schema_version": "1.2"}], promotion_requested=True)},
        {"case_id": "MIG-NEG-CONFIRMATION-STALE", "expected": "blocked", "expected_code": "LM-COMPAT-CONFIRMATION-STALE", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "4" * 64, "schema_version": "1.2"}], promotion_requested=True, confirmation={**copy.deepcopy(confirmation), "report_sha256": "0" * 64})},
        {"case_id": "MIG-NEG-CONFIRMATION-TIMESTAMP-MISSING", "expected": "blocked", "expected_code": "LM-COMPAT-CONFIRMATION-STALE", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "4" * 64, "schema_version": "1.2"}], promotion_requested=True, confirmation={key: value for key, value in copy.deepcopy(confirmation).items() if key != "confirmed_at"})},
        {"case_id": "MIG-NEG-SOURCE-DRIFT", "expected": "blocked", "expected_code": "LM-COMPAT-SOURCE-DRIFT", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "4" * 64, "schema_version": "1.2"}], promotion_requested=True, confirmation=copy.deepcopy(confirmation), current_source_inventory_sha256="6" * 64)},
        {"case_id": "MIG-POS-CONFIRMED-PROMOTION", "expected": "promoted", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "4" * 64, "schema_version": "1.2"}], promotion_requested=True, confirmation=copy.deepcopy(confirmation), backup_valid=True, staging_valid=True)},
        {"case_id": "MIG-NEG-PRECOMMIT-FAILURE", "expected": "aborted_cleanly", "expected_code": "LM-MIGRATION-VALIDATION-FAILED", "input": mig_input([{"namespace": ".claude/loop-marketing/", "content_hash": "5" * 64, "schema_version": "1.2"}], promotion_requested=True, confirmation=copy.deepcopy(confirmation), backup_valid=True, staging_valid=False)},
        {"case_id": "MIG-NEG-ROLLBACK-DRIFT", "expected": "rollback_blocked", "expected_code": "LM-ROLLBACK-DESTINATION-DRIFT", "input": {"legacy_sources": [], "canonical_v2": {"present": True, "valid": True}, "rollback": {"requested": True, "destination_hashes_match": False, "post_import_events": 1}}},
        {"case_id": "MIG-POS-ROLLBACK", "expected": "rolled_back", "input": {"legacy_sources": [], "canonical_v2": {"present": True, "valid": True}, "rollback": {"requested": True, "destination_hashes_match": True, "post_import_events": 0}}},
        {"case_id": "MIG-NEG-EXPLICIT-ONLY-SOURCE", "expected": "ignored", "input": mig_input([{"namespace": ".codex/loop-marketing/", "content_hash": "6" * 64, "schema_version": "1.2"}])},
        {"case_id": "MIG-POS-EXPLICIT-ONLY-SOURCE", "expected": "dry_run_ready", "input": mig_input([{"namespace": ".codex/loop-marketing/", "content_hash": "6" * 64, "schema_version": "1.2"}], explicit_path=True)},
    ]

    alias_cases = []
    for command_id, data in COMMANDS.items():
        alias_cases.extend([
            {"case_id": f"ALIAS-{command_id}-CANONICAL", "invocation": data["canonical"], "expected_command_id": command_id, "expected_role": data["role"]},
            {"case_id": f"ALIAS-{command_id}-LEGACY", "invocation": data["legacy_alias"], "expected_command_id": command_id, "expected_role": data["role"]},
        ])

    return {
        "artifact_id": "loop-marketing-p4-compatibility-fixtures",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "source_contracts": {
            "role_matrix": "artifacts/P2/role-matrix.json",
            "routing_contract": "artifacts/P2/routing-contract.json",
            "compatibility_policy": "artifacts/P2/compatibility-policy.md",
            "tactic_catalog": "artifacts/P3/tactic-catalog.json",
        },
        "state_cases": [
            case("STATE-POS-INITIAL", "accept", state_ok),
            case("STATE-NEG-DERIVATION", "reject", state_bad_revision, "ERR_STATE_FABRICATION"),
            case("STATE-NEG-COUNT", "reject", state_bad_count, "ERR_STATE_FABRICATION"),
            case("STATE-NEG-PATH", "reject", state_path_escape, "LM-COMPAT-PATH-ESCAPE"),
        ],
        "event_cases": [
            case("EVENT-POS-BASIC", "accept", evt_ok, context={"current_revision": 0}),
            case("EVENT-NEG-AUTHORITY", "reject", evt_bad_authority, "ERR_BOTTLENECK_OWNER_VIOLATION", {"current_revision": 0}),
            case("EVENT-NEG-STALE", "reject", evt_stale, "ERR_STATE_REVISION_STALE", {"current_revision": 2}),
            case("EVENT-NEG-HASH", "reject", evt_hash, "LM-EVENT-HASH-MISMATCH", {"current_revision": 0}),
            case("EVENT-NEG-EVIDENCE", "reject", evt_no_evidence, "ERR_STATE_FABRICATION", {"current_revision": 0}),
            case("EVENT-NEG-PROVENANCE", "reject", evt_bad_claim, "ERR_CLAIM_PROVENANCE_MISSING", {"current_revision": 0}),
            case("EVENT-POS-EXPERIMENT", "accept", exp_ok, context={"current_revision": 1}),
            case("EVENT-NEG-EXPERIMENT-SKIP", "reject", exp_skip, "ERR_EXPERIMENT_TRANSITION_INVALID", {"current_revision": 1}),
            case("EVENT-NEG-EXPERIMENT-EVIDENCE", "reject", exp_missing, "ERR_EXPERIMENT_EVIDENCE_MISSING", {"current_revision": 1}),
        ],
        "event_sequence_cases": [
            {"case_id": "SEQ-POS-CHAIN", "expected": "accept", "initial_revision": 0, "events": [first, second]},
            {"case_id": "SEQ-POS-IDEMPOTENT-REPLAY", "expected": "accept_with_noop", "initial_revision": 0, "events": [first, copy.deepcopy(first)]},
            {"case_id": "SEQ-NEG-TAMPERED-CLAIMED-EVENT-HASH", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "events": [first, event_hash_only_replay]},
            {"case_id": "SEQ-NEG-IDEMPOTENCY-COLLISION", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "events": [first, idem_conflict]},
            {"case_id": "SEQ-NEG-BROKEN-CHAIN", "expected": "reject", "expected_code": "LM-EVENT-CHAIN-BROKEN", "initial_revision": 0, "events": [first, broken_chain]},
        ],
        "transaction_cases": [
            case("TX-POS-SINGLE", "accept", tx_single, context={"current_revision": 0, "previous_record_hash": "GENESIS"}),
            case("TX-POS-BATCH", "accept", tx_batch, context={"current_revision": 0, "previous_record_hash": "GENESIS"}),
            case("TX-NEG-STALE", "reject", tx_stale, "ERR_STATE_REVISION_STALE", {"current_revision": 1, "previous_record_hash": "GENESIS"}),
            case("TX-NEG-RECORD-HASH", "reject", tx_hash, "LM-EVENT-HASH-MISMATCH", {"current_revision": 0, "previous_record_hash": "GENESIS"}),
            case("TX-NEG-MIXED-REVISION", "reject", tx_mixed_revision, "ERR_STATE_REVISION_STALE", {"current_revision": 0, "previous_record_hash": "GENESIS"}),
        ],
        "transaction_sequence_cases": [
            {"case_id": "TXSEQ-POS-CHAIN", "expected": "accept", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, tx_chain_second]},
            {"case_id": "TXSEQ-POS-IDEMPOTENT-REPLAY", "expected": "accept_with_noop", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, copy.deepcopy(tx_single)]},
            {"case_id": "TXSEQ-NEG-TRANSACTION-ID-COLLISION", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, tx_content_collision]},
            {"case_id": "TXSEQ-NEG-TAMPERED-CLAIMED-REPLAY", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, tx_tampered_claimed_replay]},
            {"case_id": "TXSEQ-NEG-IDEMPOTENCY-KEY-COLLISION", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, tx_idempotency_collision]},
            {"case_id": "TXSEQ-NEG-PARTIAL-BATCH-RETRY", "expected": "reject", "expected_code": "LM-EVENT-IDEMPOTENCY-CONFLICT", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_batch, tx_partial_retry]},
            {"case_id": "TXSEQ-NEG-BROKEN-RECORD-CHAIN", "expected": "reject", "expected_code": "LM-EVENT-CHAIN-BROKEN", "initial_revision": 0, "initial_record_hash": "GENESIS", "initial_event_hash": "GENESIS", "initial_event_sequence": 0, "transactions": [tx_single, tx_broken_record_chain]},
        ],
        "handoff_cases": handoff_cases,
        "migration_cases": migration_cases,
        "alias_cases": alias_cases,
        "coverage_requirements": {
            "state_negative_codes": ["ERR_STATE_FABRICATION", "LM-COMPAT-PATH-ESCAPE"],
            "event_negative_codes": [
                "ERR_BOTTLENECK_OWNER_VIOLATION", "ERR_STATE_REVISION_STALE",
                "LM-EVENT-HASH-MISMATCH", "ERR_STATE_FABRICATION",
                "ERR_CLAIM_PROVENANCE_MISSING", "ERR_EXPERIMENT_TRANSITION_INVALID",
                "ERR_EXPERIMENT_EVIDENCE_MISSING", "LM-EVENT-IDEMPOTENCY-CONFLICT",
                "LM-EVENT-CHAIN-BROKEN",
            ],
            "transaction_negative_codes": [
                "ERR_STATE_REVISION_STALE", "LM-EVENT-HASH-MISMATCH",
                "LM-EVENT-IDEMPOTENCY-CONFLICT", "LM-EVENT-CHAIN-BROKEN",
            ],
            "handoff_negative_codes": [
                "ERR_HANDOFF_FIELD_MISSING", "ERR_HANDOFF_STALE_REVISION",
                "ERR_HANDOFF_SCOPE_BOUNDARY", "ERR_HANDOFF_OWNER_SCOPE",
                "ERR_HANDOFF_PROVENANCE", "ERR_TACTIC_CARDINALITY",
                "ERR_CANONICAL_LIBRARY_DRIFT",
            ],
            "migration_negative_codes": [
                "LM-COMPAT-NAMESPACE-CONFLICT", "LM-COMPAT-PATH-ESCAPE",
                "LM-COMPAT-FUTURE-SCHEMA", "LM-COMPAT-SECRET-DETECTED",
                "LM-COMPAT-CONFIRMATION-REQUIRED", "LM-COMPAT-CONFIRMATION-STALE",
                "LM-COMPAT-SOURCE-DRIFT",
                "LM-MIGRATION-VALIDATION-FAILED", "LM-ROLLBACK-DESTINATION-DRIFT",
            ],
        },
    }


def build_state_event_contract() -> str:
    return f"""# Contrato de estado e eventos — Loop Marketing v2

Status: integrado em P4  
Produto: `2.0.0`  
Schema de estado/evento: `{SCHEMA_VERSION}`

## 1. Autoridade e fonte de verdade

O ledger append-only `.loop-marketing/state/projects/<project_id>/events.jsonl` é a fonte de verdade. `snapshots/latest.json` é uma projeção derivada e descartável. Prosa, reinício do agente, reexecução de comando ou estado de conversa nunca avançam a revisão.

Cada linha do ledger é uma transação comprometida com um ou mais eventos. Todos os eventos do batch carregam a mesma revisão lida em `state_revision` e a mesma revisão pretendida em `resulting_state_revision`. Uma transação nova avança exatamente uma revisão. O snapshot registra a revisão aplicada e `derived_from_revision`; revisão zero não possui transação anterior.

## 2. Compare-and-swap e exclusão por projeto

1. Resolver o caminho real e provar contenção em `.loop-marketing/state/projects/`.
2. Ler e validar ledger e snapshot; se o snapshot estiver atrás, reconstruí-lo antes de aceitar escrita.
3. Comparar a revisão informada com a revisão do head do ledger. Divergência retorna `ERR_STATE_REVISION_STALE` sem escrita.
4. Adquirir lock exclusivo por projeto, reler o head e repetir a comparação.
5. Validar schema, autoridade, evidência, handoffs referenciados, write sets e transições de experimento antes de integrar o batch.
6. Calcular idempotência, hash canônico e encadeamento antes de preparar qualquer arquivo.

O lock reduz colisões, mas não substitui o compare-and-swap. A decisão é baseada na revisão relida após o lock.

## 3. Commit recuperável

1. Criar arquivos temporários no mesmo filesystem do projeto.
2. Materializar o ledger completo anterior mais uma única linha de transação JSON terminada por newline; o prefixo anterior deve permanecer byte-for-byte.
3. Materializar o snapshot derivado e um registro de transação `prepared` com hashes pré/pós.
4. Fazer `fsync` dos arquivos temporários.
5. Renomear atomicamente o novo ledger sobre `events.jsonl`; este rename é o ponto de commit.
6. Fazer `fsync` do diretório do projeto.
7. Renomear atomicamente o snapshot e fazer `fsync` dos diretórios envolvidos.
8. Marcar a transação `committed` sem reescrever o evento.

Falha antes do passo 5 não muda o estado. Falha entre os passos 5 e 7 deixa o ledger à frente; a recuperação valida o hash-chain e reconstrói o snapshot. Um snapshot à frente do ledger é inválido e retorna `ERR_STATE_FABRICATION`.

## 4. Hash-chain e idempotência

`event_hash` e `record_hash` usam SHA-256 sobre JSON canônico RFC 8785, excluindo respectivamente o próprio `event_hash` e `record_hash`. O primeiro head usa `GENESIS`; os seguintes apontam para o hash anterior. A transação possui hash-chain próprio e os eventos preservam ordem e chain dentro e entre batches.

- Mesmos IDs/chaves de transação e eventos com o mesmo conteúdo canônico: replay idempotente do batch inteiro, `noop`, sem nova revisão.
- Mesmo identificador com conteúdo diferente: `LM-EVENT-IDEMPOTENCY-CONFLICT`.
- Retry parcial de batch: rejeitado.
- Hash inválido: `LM-EVENT-HASH-MISMATCH`.
- Encadeamento inválido: `LM-EVENT-CHAIN-BROKEN`.

## 5. Evidência, autoridade e experimentos

O mapa `x-loop-contract.authority_by_role` de `event-schema.json` reproduz exatamente os 33 tipos autorizados de P2. Especialistas não aceitam gargalo, sequência ou fechamento de ciclo; roteamento nunca eleva autorização externa. `cycle_closed`, recovery, rollback e `legacy.imported` não ganham autoridade de domínio nesta fase: vivem em relatórios de auditoria/transação até contrato explícito posterior.

Eventos exigem ao menos uma referência de evidência. Fatos exigem `source_ref` e `observed_at`; hipóteses exigem `rationale`. A máquina de experimento em `event-schema.json` reproduz `RTE-EXP-001` a `RTE-EXP-007`. Não há salto, reversão ou avanço por narrativa. Aprovação e lançamento são apenas registrados por Refinar após validar referências do ator externo; isso não concede a Refinar autoridade de aprovação ou execução.

## 6. Recuperação e quarentena

Na inicialização, validar schema, newline final, unicidade, idempotência, revisões, hashes e autoridade. Cauda parcial ou arquivo conflitante é copiado para `.loop-marketing/quarantine/` e bloqueia escrita automática. A recuperação pode reconstruir snapshots a partir do último ledger integralmente válido, mas nunca apaga o material em quarentena nem inventa a transição faltante.
"""


def build_migration_contract() -> str:
    alias_rows = "\n".join(
        f"| `{command_id}` | `{data['canonical']}` | `{data['legacy_alias']}` | `{data['role']}` |"
        for command_id, data in COMMANDS.items()
    )
    return f"""# Contrato de migração e compatibilidade — Loop Marketing v2

Status: integrado em P4  
Produto: `2.0.0`  
Migração: `copy-and-verify`, local, confirmada e reversível

## 1. Limites

P4 define e testa o contrato; não executa migração real. A origem v1.x é sempre read-only. Markdown legado é dado não confiável: não instrui ferramentas, não autoriza escrita externa e não pode elevar fatos, decisões ou experimentos sem evidência.

## 2. Descoberta

1. Seleção explícita de projeto ou caminho canônico v2 válido.
2. `.loop-marketing/state/active-project.json`, se schema, contenção e alvo forem válidos.
3. Um único projeto v2 válido, somente como sugestão.
4. `.claude/loop-marketing/` e `.Codex/loop-marketing/`, somente para inventário/dry-run.
5. `.codex/loop-marketing/` e `.claude/projects/` apenas por caminho explícito.

Um v2 válido nunca é sobrescrito por legado. Caminhos reais e symlinks devem permanecer contidos nas raízes declaradas. `project_id` segue `^[a-z0-9][a-z0-9-]{{0,62}}$`; `display_name` nunca participa do caminho.

## 3. Dry-run obrigatório

O relatório de dry-run contém: `migration_id`, versão do migrador, origens e proveniência, inventário com hashes/tamanhos sem segredos, parser/version, mapeamento de campos, anexos preservados, perdas conhecidas, lacunas, conflitos, redactions, `project_id` proposto, arquivos a criar, hashes previstos, validações e plano de rollback.

Dry-run não grava estado canônico. Promoção exige um confirmation record, nunca booleano, vinculado exatamente a `migration_id`, `report_sha256`, `source_inventory_sha256`, `destination_precondition_sha256`, `migrator_version`, `project_id`, operação e timestamp. Qualquer mudança nesses campos, nas origens ou no destino invalida a confirmação e exige novo dry-run (`LM-COMPAT-CONFIRMATION-STALE` ou `LM-COMPAT-SOURCE-DRIFT`). Pedido de promoção sem o record retorna `LM-COMPAT-CONFIRMATION-REQUIRED`.

## 4. Conflitos e conteúdo sensível

- Namespaces byte a byte idênticos formam um candidato com múltiplas proveniências.
- Subconjunto ou divergência é apresentado; nenhuma origem vence por recência.
- Divergência de decisão, gargalo, experimento ou projeto ativo retorna `LM-COMPAT-NAMESPACE-CONFLICT`.
- Path escape, schema futuro, credencial, active pointer ausente e colisão de IDs usam os códigos `LM-COMPAT-*` de P2.
- Até P6 estabelecer política de redaction autorizada, credencial detectada bloqueia promoção (`LM-COMPAT-SECRET-DETECTED`) e nunca aparece em relatório/log.

Texto sem campo v2 correspondente vira anexo legado referenciado ou lacuna; nunca é descartado nem convertido silenciosamente em decisão aceita.

## 5. Backup, staging e promoção

Antes da promoção, criar pacote de rollback local com inventário/hash das origens, dry-run confirmado, versão do migrador, manifest e hashes dos arquivos v2 previstos, estado anterior do destino e resultados de validação.

Construir o destino em staging no mesmo filesystem. Validar schemas, contenção, IDs, contagens, hashes, referências aos 100 prompts e replay completo dos eventos. Fazer `fsync`; promover por rename atômico somente se o destino canônico ainda corresponder ao estado observado no dry-run. Registrar `legacy.imported` como audit record no relatório/transação de migração, com origens, hashes, parser e versão; P4 não o promove a evento de domínio nem inventa um owner. A origem permanece intocada.

Falha anterior ao rename remove apenas staging identificado pela transação e deixa o namespace canônico ausente/inalterado. Falha posterior ao commit usa o ledger para reconstruir snapshot; nunca repete importação sem checar idempotência.

## 6. Rollback

Rollback verifica o manifest, os hashes atuais e a inexistência de eventos posteriores à importação. Remove somente arquivos criados pela transação. Se houver drift ou novos eventos, retorna `LM-ROLLBACK-DESTINATION-DRIFT` e exige plano manual. Origem e pacote de evidência nunca são apagados.

## 7. Comandos e aliases

| `command_id` | Canônico | Alias v1.x | Papel |
|---|---|---|---|
{alias_rows}

Nome canônico e alias resolvem para o mesmo `command_id`, papel, estado e autorização. Eventos guardam `command_id`, nunca o texto invocado. Os aliases permanecem durante toda a série `2.x`.

## 8. Preservação da biblioteca

A migração referencia exatamente 100 prompts pelo path/hash do catálogo P3 e pelo hash agregado `{LIBRARY_HASH}`. Não renomeia, mescla, corrige ou remove prompts. Proveniência editorial e revisão de redistribuição continuam sidecar e não são promovidas por migração.

## 9. Operações externas

Importação só cria estado local em `.loop-marketing/` após confirmação. Não envia mensagens, altera CRM, publica campanha, configura canal, faz push ou chama integração externa. Roteamento e aliases não equivalem a autorização operacional.
"""


def main() -> None:
    role_matrix = load_json(P2 / "role-matrix.json")
    routing = load_json(P2 / "routing-contract.json")
    catalog = load_json(P3 / "tactic-catalog.json")
    authority, event_authority, ownership_fields = role_contracts(role_matrix)
    handoff_fields = [item["name"] for item in role_matrix["handoff_contract"]["fields"]]
    assert len(handoff_fields) == 22 and len(set(handoff_fields)) == 22
    assert routing["canonical_enums"]["experiment_state"] == EXPERIMENT_STATES

    workstreams = OUT / "workstreams"
    required_workstreams = [workstreams / name for name in ("state-events.json", "handoff.json", "migration.json")]
    missing = [str(path.relative_to(ROOT)) for path in required_workstreams if not path.exists()]
    if missing:
        raise SystemExit(f"P4 workstreams ausentes: {', '.join(missing)}")

    state_schema = build_state_schema()
    event_schema = build_event_schema(event_authority)
    handoff_workstream = load_json(workstreams / "handoff.json")
    handoff_schema = integrate_handoff_schema(handoff_workstream["schema_proposal"], handoff_fields)
    fixtures = build_fixtures(authority, catalog)

    outputs = {
        OUT / "state-schema.json": state_schema,
        OUT / "event-schema.json": event_schema,
        OUT / "handoff-schema.json": handoff_schema,
        OUT / "compatibility-fixtures.json": fixtures,
    }
    for path, value in outputs.items():
        dump(path, value)
    (OUT / "state-event-contract.md").write_text(build_state_event_contract(), encoding="utf-8")
    (OUT / "migration-contract.md").write_text(build_migration_contract(), encoding="utf-8")

    official_paths = [
        OUT / "state-schema.json", OUT / "event-schema.json", OUT / "handoff-schema.json",
        OUT / "state-event-contract.md", OUT / "migration-contract.md",
        OUT / "compatibility-fixtures.json",
    ]
    source_paths = [
        P2 / "role-matrix.json", P2 / "routing-contract.json", P2 / "compatibility-policy.md",
        P3 / "catalog-schema.json", P3 / "tactic-catalog.json", P3 / "preservation-report.json",
    ]
    script_paths = [
        ROOT / "scripts" / "p4_integrate.py",
        ROOT / "scripts" / "p4_validate.py",
        ROOT / "scripts" / "p4_regression.py",
        ROOT / "scripts" / "p4_seal.py",
    ]
    missing_scripts = [str(path.relative_to(ROOT)) for path in script_paths if not path.is_file()]
    if missing_scripts:
        raise SystemExit(f"P4 scripts ausentes: {', '.join(missing_scripts)}")
    manifest = {
        "artifact_id": "loop-marketing-p4-integration-manifest",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "integrated_pending_independent_gate",
        "source_contracts": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in source_paths
        ],
        "workstreams": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in required_workstreams
        ],
        "official_artifacts": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in official_paths
        ],
        "scripts": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in script_paths
        ],
        "contract_counts": {
            "handoff_top_level_fields": 22,
            "roles": len(ROLES),
            "commands": len(COMMANDS),
            "experiment_states": len(EXPERIMENT_STATES),
            "experiment_transition_rules": len(EXPERIMENT_TRANSITIONS),
            "canonical_prompts": 100,
            "state_cases": len(fixtures["state_cases"]),
            "event_cases": len(fixtures["event_cases"]),
            "event_sequence_cases": len(fixtures["event_sequence_cases"]),
            "transaction_cases": len(fixtures["transaction_cases"]),
            "transaction_sequence_cases": len(fixtures["transaction_sequence_cases"]),
            "handoff_cases": len(fixtures["handoff_cases"]),
            "migration_cases": len(fixtures["migration_cases"]),
            "alias_cases": len(fixtures["alias_cases"]),
        },
        "invariants": [
            "canonical namespace is .loop-marketing/ and host-neutral",
            "event ledger is append-only and authoritative; snapshots are derived",
            "new events advance exactly one revision after optimistic compare-and-swap",
            "replays are idempotent only when canonical content is identical",
            "handoff has exactly the 22 P2 fields and no top-level extension",
            "experiment transitions preserve RTE-EXP-001 through RTE-EXP-007",
            "migration is copy-and-verify with dry-run, confirmation, backup and rollback",
            "all 100 canonical prompts remain referenced by path/hash and unmodified",
        ],
        "baseline": {
            "source_commit": BASELINE_COMMIT,
            "canonical_prompt_count": 100,
            "aggregate_sha256": LIBRARY_HASH,
        },
    }
    dump(OUT / "integration-manifest.json", manifest)
    print(json.dumps({"status": "generated", "files": len(official_paths) + 1}, ensure_ascii=False))


if __name__ == "__main__":
    main()
