#!/usr/bin/env python3
"""Validate P4 schemas, semantic contracts, fixtures, and source preservation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


BASELINE_COMMIT = "3cbf0cf84a038f2cd570883b70988889f037c28e"
LIBRARY_HASH = "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"
SOURCE = Path("/Users/enorm/Documents/Claude/loop-marketing")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: dict, excluded: str) -> str:
    payload = {key: val for key, val in value.items() if key != excluded}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class MiniSchema:
    """Dependency-free validator for the JSON Schema subset used by P4."""

    def __init__(self, root: dict):
        self.root = root

    def resolve(self, ref: str) -> dict:
        if not ref.startswith("#/"):
            raise ValueError(f"external ref unsupported: {ref}")
        node: Any = self.root
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def errors(self, value: Any, schema: dict | None = None, path: str = "$") -> list[str]:
        schema = self.root if schema is None else schema
        if "$ref" in schema:
            return self.errors(value, self.resolve(schema["$ref"]), path)
        errors: list[str] = []
        if "const" in schema and value != schema["const"]:
            errors.append(f"{path}: const")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: enum")
        schema_type = schema.get("type")
        if schema_type:
            allowed = schema_type if isinstance(schema_type, list) else [schema_type]
            type_ok = any(self._is_type(value, item) for item in allowed)
            if not type_ok:
                return errors + [f"{path}: type {schema_type}"]
        if "anyOf" in schema:
            branches = [self.errors(value, branch, path) for branch in schema["anyOf"]]
            if all(branch for branch in branches):
                errors.append(f"{path}: anyOf")
        if "oneOf" in schema:
            matches = sum(not self.errors(value, branch, path) for branch in schema["oneOf"])
            if matches != 1:
                errors.append(f"{path}: oneOf")
        for branch in schema.get("allOf", []):
            errors.extend(self.errors(value, branch, path))
        if "if" in schema:
            condition_matches = not self.errors(value, schema["if"], path)
            selected = schema.get("then") if condition_matches else schema.get("else")
            if selected:
                errors.extend(self.errors(value, selected, path))
        if isinstance(value, dict):
            required = schema.get("required", [])
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key}: required")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key}: additionalProperty")
            for key, child in properties.items():
                if key in value:
                    errors.extend(self.errors(value[key], child, f"{path}.{key}"))
            if len(value) < schema.get("minProperties", 0):
                errors.append(f"{path}: minProperties")
            if "maxProperties" in schema and len(value) > schema["maxProperties"]:
                errors.append(f"{path}: maxProperties")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                errors.append(f"{path}: minItems")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append(f"{path}: maxItems")
            if schema.get("uniqueItems") and len({json_key(item) for item in value}) != len(value):
                errors.append(f"{path}: uniqueItems")
            if "items" in schema:
                for index, item in enumerate(value):
                    errors.extend(self.errors(item, schema["items"], f"{path}[{index}]"))
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                errors.append(f"{path}: minLength")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(f"{path}: maxLength")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                errors.append(f"{path}: pattern")
            if schema.get("format") == "date-time":
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    errors.append(f"{path}: date-time")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{path}: minimum")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{path}: maximum")
        return errors

    @staticmethod
    def _is_type(value: Any, expected: str) -> bool:
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(expected, True)


class P4Validator:
    def __init__(self, root: Path):
        self.root = root
        self.p2 = root / "artifacts" / "P2"
        self.p3 = root / "artifacts" / "P3"
        self.p4 = root / "artifacts" / "P4"
        self.errors: list[str] = []
        self.role_matrix = load(self.p2 / "role-matrix.json")
        self.routing = load(self.p2 / "routing-contract.json")
        self.catalog = load(self.p3 / "tactic-catalog.json")
        self.state_schema = load(self.p4 / "state-schema.json")
        self.event_schema = load(self.p4 / "event-schema.json")
        self.handoff_schema = load(self.p4 / "handoff-schema.json")
        self.fixtures = load(self.p4 / "compatibility-fixtures.json")
        self.manifest = load(self.p4 / "integration-manifest.json")
        self.state_struct = MiniSchema(self.state_schema)
        self.event_struct = MiniSchema(self.event_schema)
        self.handoff_struct = MiniSchema(self.handoff_schema)
        self.authority = {r["canonical_role_id"]: r["owns"] for r in self.role_matrix["roles"]}
        self.role_events = {r["canonical_role_id"]: r["allowed_state_events"] for r in self.role_matrix["roles"]}
        self.event_types = sorted({item for values in self.role_events.values() for item in values})
        self.catalog_by_id = {item["tactic_id"]: item for item in self.catalog["tactics"]}
        self.domain_owner = self.handoff_schema["x-loop-contract"]["decision_domain_owner"]
        self.commands = self.event_schema["x-loop-contract"]["command_contract"]
        self.transitions = self.event_schema["x-loop-contract"]["experiment_state_machine"]

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def contracts(self) -> None:
        expected_fields = [item["name"] for item in self.role_matrix["handoff_contract"]["fields"]]
        if len(expected_fields) != 22 or self.handoff_schema.get("required") != expected_fields:
            self.fail("handoff required fields drift from P2")
        if list(self.handoff_schema.get("properties", {})) != expected_fields:
            self.fail("handoff properties drift from P2")
        if self.handoff_schema.get("additionalProperties") is not False:
            self.fail("handoff schema is not closed")
        if self.handoff_schema.get("minProperties") != 22 or self.handoff_schema.get("maxProperties") != 22:
            self.fail("handoff schema does not enforce exactly 22 top-level fields")
        schema_events = sorted(self.event_schema["$defs"]["event"]["properties"]["event_type"]["enum"])
        if schema_events != self.event_types or len(schema_events) != 33:
            self.fail("event authority/types drift from the 33 P2 event types")
        if self.event_schema["x-loop-contract"]["authority_by_role"] != self.role_events:
            self.fail("event role authority map drift")
        if any(item in schema_events for item in ("cycle_closed", "legacy.imported", "recovery", "rollback")):
            self.fail("P4 invented a domain event authority")
        p2_states = self.routing["canonical_enums"]["experiment_state"]
        if p2_states != ["proposed", "approved", "instrumented", "running", "completed", "cancelled", "invalidated"]:
            self.fail("P2 experiment state anchor drift")
        p2_rules = self.routing["decision_rules"]["experiment_state_machine"]
        if len(self.transitions) != 7 or {v["rule_id"] for v in self.transitions.values()} != {
            p2_rules["creation_rule"]["id"], *(item["id"] for item in p2_rules["transitions"])
        }:
            self.fail("experiment transition rules drift from P2")
        if self.state_schema.get("x-loop-contract", {}).get("namespace") != ".loop-marketing/":
            self.fail("canonical state namespace drift")
        revision_rule = self.state_schema.get("x-loop-contract", {}).get("revision_rule", "")
        if "transaction" not in revision_rule or "one or more events" not in revision_rule:
            self.fail("state revision rule is inconsistent with transaction batches")
        if self.state_schema.get("additionalProperties") is not False or self.event_schema.get("additionalProperties") is not False:
            self.fail("state/event schema is not closed")
        required_docs = {
            "state-event-contract.md": ["compare-and-swap", "fsync", "ponto de commit", "quarantine", "33 tipos"],
            "migration-contract.md": ["Dry-run", "Backup", "Rollback", "copy-and-verify", "100 prompts"],
        }
        for name, markers in required_docs.items():
            text = (self.p4 / name).read_text(encoding="utf-8").lower()
            for marker in markers:
                if marker.lower() not in text:
                    self.fail(f"{name} missing marker: {marker}")
        if not self.fixtures.get("transaction_sequence_cases"):
            self.fail("transaction replay/idempotency sequence coverage is missing")
        event_sequence_ids = {item["case_id"] for item in self.fixtures.get("event_sequence_cases", [])}
        if "SEQ-NEG-TAMPERED-CLAIMED-EVENT-HASH" not in event_sequence_ids:
            self.fail("tampered event replay with stale claimed hash coverage is missing")
        tx_sequence_ids = {item["case_id"] for item in self.fixtures.get("transaction_sequence_cases", [])}
        if "TXSEQ-NEG-TAMPERED-CLAIMED-REPLAY" not in tx_sequence_ids:
            self.fail("tampered replay with stale claimed hash coverage is missing")
        promoted = next((item for item in self.fixtures["migration_cases"] if item["case_id"] == "MIG-POS-CONFIRMED-PROMOTION"), None)
        required_confirmation = {
            "migration_id", "report_sha256", "source_inventory_sha256",
            "destination_precondition_sha256", "migrator_version", "project_id", "operation", "confirmed_at",
        }
        if promoted is None or not required_confirmation.issubset((promoted["input"].get("confirmation") or {})):
            self.fail("migration confirmation is not bound to the dry-run contract")

    def state_code(self, value: dict) -> str | None:
        structural = self.state_struct.errors(value)
        if structural:
            if "project_id" in value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", str(value["project_id"])):
                return "LM-COMPAT-PATH-ESCAPE"
            return "ERR_STATE_FABRICATION"
        project_id = value["project_id"]
        if value["project_ref"] != f"project:{project_id}":
            return "LM-COMPAT-PATH-ESCAPE"
        rev = value["state_revision"]
        log = value["event_log"]
        if rev == 0:
            if value["derived_from_revision"] is not None:
                return "ERR_STATE_FABRICATION"
            if any(log[key] is not None for key in ("head_event_id", "head_event_hash", "head_record_hash")):
                return "ERR_STATE_FABRICATION"
            if any(log[key] != 0 for key in ("last_event_sequence", "applied_event_count", "committed_transaction_count")):
                return "ERR_STATE_FABRICATION"
        else:
            if value["derived_from_revision"] != rev - 1:
                return "ERR_STATE_FABRICATION"
            if any(log[key] is None for key in ("head_event_id", "head_event_hash", "head_record_hash")):
                return "ERR_STATE_FABRICATION"
            if log["committed_transaction_count"] != rev:
                return "ERR_STATE_FABRICATION"
            if log["last_event_sequence"] != log["applied_event_count"] or log["applied_event_count"] < rev:
                return "ERR_STATE_FABRICATION"
        state = value["state"]
        if state["route_status"] == "ready" and state["accepted_bottleneck_ref"] is None:
            return "ERR_STATE_FABRICATION"
        return None

    def event_code(self, value: dict, context: dict | None = None, skip_chain: bool = False) -> str | None:
        structural = self.event_struct.errors(value, self.event_schema["$defs"]["event"])
        if structural:
            if not value.get("evidence_refs"):
                return "ERR_STATE_FABRICATION"
            return "LM-EVENT-SCHEMA-INVALID"
        context = context or {}
        if value["state_revision"] != context.get("current_revision", value["state_revision"]):
            return "ERR_STATE_REVISION_STALE"
        if value["resulting_state_revision"] != value["state_revision"] + 1:
            return "ERR_STATE_REVISION_STALE"
        expected = canonical_hash(value, "event_hash")
        if value["event_hash"] != expected:
            return "LM-EVENT-HASH-MISMATCH"
        role = value["actor_role"]
        if value["event_type"] not in self.role_events[role]:
            if value["event_type"] in ("bottleneck_accepted", "bottleneck_rejected"):
                return "ERR_BOTTLENECK_OWNER_VIOLATION"
            if value["event_type"] in self.role_events["loop_planning"]:
                return "ERR_ORCHESTRATOR_AUTHORITY"
            return "ERR_OWNER_SCOPE_VIOLATION"
        command = self.commands[value["command_id"]]
        if command["role"] != role:
            return "ERR_OWNER_SCOPE_VIOLATION"
        if not skip_chain and value["previous_event_hash"] != context.get("previous_event_hash", value["previous_event_hash"]):
            return "LM-EVENT-CHAIN-BROKEN"
        for claim in value["payload"]["claims"]:
            provenance = claim["provenance"]
            if claim["kind"] == "fact" and not {"source_ref", "observed_at"}.issubset(provenance):
                return "ERR_CLAIM_PROVENANCE_MISSING"
            if claim["kind"] == "hypothesis" and not provenance.get("rationale"):
                return "ERR_CLAIM_PROVENANCE_MISSING"
        if value["event_type"] in ("experiment_created_as_proposed", "experiment_transition_evidence_validated"):
            data = value["payload"]["data"]
            match = None
            for action, transition in self.transitions.items():
                if transition["to"] != data.get("to"):
                    continue
                allowed_from = transition.get("from_any", [transition.get("from")])
                if data.get("from") in allowed_from:
                    match = (action, transition)
                    break
            if match is None:
                return "ERR_EXPERIMENT_TRANSITION_INVALID"
            action, transition = match
            expected_type = "experiment_created_as_proposed" if action == "create" else "experiment_transition_evidence_validated"
            if value["event_type"] != expected_type or data.get("transition_rule_id") != transition["rule_id"]:
                return "ERR_EXPERIMENT_TRANSITION_INVALID"
            needed = {item["evidence_key"] for item in transition["required_evidence"]}
            supplied = set(data.get("evidence_map", {}))
            if not needed.issubset(supplied) or not set(data.get("evidence_map", {}).values()).issubset(value["evidence_refs"]):
                return "ERR_EXPERIMENT_EVIDENCE_MISSING"
        return None

    def transaction_code(self, value: dict, context: dict | None = None) -> str | None:
        if self.event_struct.errors(value):
            return "LM-EVENT-SCHEMA-INVALID"
        context = context or {}
        current = context.get("current_revision", value["expected_state_revision"])
        if value["expected_state_revision"] != current or value["resulting_state_revision"] != current + 1:
            return "ERR_STATE_REVISION_STALE"
        if value["previous_record_hash"] != context.get("previous_record_hash", value["previous_record_hash"]):
            return "LM-EVENT-CHAIN-BROKEN"
        if value["record_hash"] != canonical_hash(value, "record_hash"):
            return "LM-EVENT-HASH-MISMATCH"
        event_head = context.get("previous_event_hash", value["events"][0]["previous_event_hash"])
        expected_sequence = context.get("last_event_sequence", value["events"][0]["event_sequence"] - 1) + 1
        event_ids: set[str] = set()
        idem: set[str] = set()
        for item in value["events"]:
            if item["transaction_id"] != value["transaction_id"] or item["project_ref"] != value["project_ref"]:
                return "LM-EVENT-SCHEMA-INVALID"
            if item["state_revision"] != current or item["resulting_state_revision"] != current + 1:
                return "ERR_STATE_REVISION_STALE"
            if item["event_sequence"] != expected_sequence or item["previous_event_hash"] != event_head:
                return "LM-EVENT-CHAIN-BROKEN"
            if item["event_id"] in event_ids or item["idempotency_key"] in idem:
                return "LM-EVENT-IDEMPOTENCY-CONFLICT"
            code = self.event_code(item, {"current_revision": current, "previous_event_hash": event_head})
            if code:
                return code
            event_ids.add(item["event_id"])
            idem.add(item["idempotency_key"])
            event_head = item["event_hash"]
            expected_sequence += 1
        return None

    def sequence_code(self, sequence: dict) -> tuple[str, str | None]:
        current = sequence["initial_revision"]
        previous_hash = "GENESIS"
        seen_events: dict[str, str] = {}
        seen_idem: dict[str, str] = {}
        noops = 0
        for item in sequence["events"]:
            fingerprint = canonical_hash(item, "event_hash")
            old_event = seen_events.get(item["event_id"])
            old_idem = seen_idem.get(item["idempotency_key"])
            if old_event is not None or old_idem is not None:
                if old_event == fingerprint and old_idem == fingerprint and item["event_hash"] == fingerprint:
                    noops += 1
                    continue
                return "reject", "LM-EVENT-IDEMPOTENCY-CONFLICT"
            code = self.event_code(item, {"current_revision": current, "previous_event_hash": previous_hash})
            if code:
                return "reject", code
            seen_events[item["event_id"]] = fingerprint
            seen_idem[item["idempotency_key"]] = fingerprint
            current += 1
            previous_hash = item["event_hash"]
        return ("accept_with_noop" if noops else "accept"), None

    def transaction_sequence_code(self, sequence: dict) -> tuple[str, str | None]:
        current = sequence["initial_revision"]
        previous_record = sequence["initial_record_hash"]
        previous_event = sequence["initial_event_hash"]
        last_sequence = sequence["initial_event_sequence"]
        transactions: dict[str, str] = {}
        transaction_idem: dict[str, str] = {}
        event_ids: set[str] = set()
        event_idem: set[str] = set()
        noops = 0
        for record in sequence["transactions"]:
            fingerprint = canonical_hash(record, "record_hash")
            old_tx = transactions.get(record["transaction_id"])
            old_idem = transaction_idem.get(record["idempotency_key"])
            if old_tx is not None or old_idem is not None:
                if old_tx == fingerprint and old_idem == fingerprint and record["record_hash"] == fingerprint:
                    noops += 1
                    continue
                return "reject", "LM-EVENT-IDEMPOTENCY-CONFLICT"
            if any(item["event_id"] in event_ids or item["idempotency_key"] in event_idem for item in record["events"]):
                return "reject", "LM-EVENT-IDEMPOTENCY-CONFLICT"
            code = self.transaction_code(record, {
                "current_revision": current,
                "previous_record_hash": previous_record,
                "previous_event_hash": previous_event,
                "last_event_sequence": last_sequence,
            })
            if code:
                return "reject", code
            transactions[record["transaction_id"]] = fingerprint
            transaction_idem[record["idempotency_key"]] = fingerprint
            for item in record["events"]:
                event_ids.add(item["event_id"])
                event_idem.add(item["idempotency_key"])
            current += 1
            previous_record = record["record_hash"]
            previous_event = record["events"][-1]["event_hash"]
            last_sequence = record["events"][-1]["event_sequence"]
        return ("accept_with_noop" if noops else "accept"), None

    def handoff_code(self, value: dict, context: dict | None = None) -> str | None:
        structural = self.handoff_struct.errors(value)
        if structural:
            if len(value.get("tactic_refs", [])) > 2:
                return "ERR_TACTIC_CARDINALITY"
            if not value.get("evidence_refs") and not value.get("assumptions"):
                return "ERR_HANDOFF_PROVENANCE"
            return "ERR_HANDOFF_FIELD_MISSING"
        context = context or {}
        if value["state_revision"] != context.get("current_revision", value["state_revision"]):
            return "ERR_HANDOFF_STALE_REVISION"
        if value["from_role"] == value["to_role"]:
            return "ERR_HANDOFF_OWNER_SCOPE"
        target = value["to_role"]
        owned_domains = {domain for domain, owner in self.domain_owner.items() if owner == target}
        expected_scope = set(self.domain_owner) - owned_domains
        if set(value["scope_boundary_next_does_not_decide"]) != expected_scope:
            return "ERR_HANDOFF_SCOPE_BOUNDARY"
        output = value["requested_output"]
        if not set(output["decision_domains"]).issubset(owned_domains):
            return "ERR_HANDOFF_OWNER_SCOPE"
        if not set(output["proposed_state_events"]).issubset(self.role_events[target]):
            return "ERR_HANDOFF_OWNER_SCOPE"
        if "external_execution_authorization" in output["decision_domains"]:
            return "ERR_EXTERNAL_MUTATION_UNAUTHORIZED"
        for input_ref in value["input_refs"]:
            if input_ref["required"] and input_ref["state_revision"] != value["state_revision"]:
                return "ERR_SEQUENCE_DEPENDENCY"
        if not value["evidence_refs"] and not value["assumptions"]:
            return "ERR_HANDOFF_PROVENANCE"
        evidence_claims = {claim for evidence in value["evidence_refs"] for claim in evidence["claim_refs"]}
        assumption_claims = {claim for item in value["assumptions"] for claim in item["claim_refs"]}
        if evidence_claims & assumption_claims:
            return "ERR_HANDOFF_PROVENANCE"
        if value["maturity"] == "unknown":
            if value["mode"] != "minimo_viavel" or value["tactic_refs"] or not value["cross_validation_required"]["required"]:
                return "ERR_MATURITY_GATE"
        for tactic_ref in value["tactic_refs"]:
            tactic = self.catalog_by_id.get(tactic_ref["tactic_id"])
            if tactic is None:
                return "ERR_TACTIC_METADATA_MISSING"
            if tactic["canonical_path"] != tactic_ref["canonical_path"] or tactic["canonical_sha256"] != tactic_ref["canonical_sha256"]:
                return "ERR_CANONICAL_LIBRARY_DRIFT"
            if tactic["pillar"].lower() != target:
                return "ERR_TACTIC_METADATA_MISSING"
            policy = tactic["execution_policy"]
            if policy["automatic_selection"] == "forbidden":
                return "ERR_MATURITY_GATE"
        bottleneck = value["bottleneck_ref"]
        if "unresolved" in bottleneck and not (
            target == "refinar" and value["mode"] == "minimo_viavel" and value["maturity"] == "unknown"
        ):
            return "ERR_HANDOFF_PROVENANCE"
        cross = value["cross_validation_required"]
        if cross["required"] and not (cross["roles"] or cross["conflicts"]):
            return "ERR_CROSS_VALIDATION_BLOCKED"
        if not cross["required"] and (cross["roles"] or cross["conflicts"]):
            return "ERR_CROSS_VALIDATION_BLOCKED"
        return None

    @staticmethod
    def migration_result(case_input: dict) -> tuple[str, str | None]:
        rollback = case_input.get("rollback")
        if rollback and rollback.get("requested"):
            if not rollback.get("destination_hashes_match") or rollback.get("post_import_events", 0) > 0:
                return "rollback_blocked", "LM-ROLLBACK-DESTINATION-DRIFT"
            return "rolled_back", None
        canonical = case_input.get("canonical_v2")
        if canonical and canonical.get("present") and canonical.get("valid"):
            return "report_only", None
        if case_input.get("path_contained") is False:
            return "blocked", "LM-COMPAT-PATH-ESCAPE"
        sources = list(case_input.get("legacy_sources", []))
        explicit = case_input.get("explicit_path", False)
        recognized = []
        for item in sources:
            namespace = item["namespace"]
            automatic = namespace in (".claude/loop-marketing/", ".Codex/loop-marketing/")
            if automatic or explicit:
                recognized.append(item)
        if not recognized:
            return "ignored", None
        if any(str(item.get("schema_version", "0")).split(".")[0].isdigit() and int(str(item["schema_version"]).split(".")[0]) > 2 for item in recognized):
            return "blocked", "LM-COMPAT-FUTURE-SCHEMA"
        if case_input.get("secret_detected"):
            return "blocked", "LM-COMPAT-SECRET-DETECTED"
        hashes = {item["content_hash"] for item in recognized}
        if len(recognized) > 1 and len(hashes) > 1:
            return "blocked", "LM-COMPAT-NAMESPACE-CONFLICT"
        if not case_input.get("promotion_requested"):
            return "dry_run_ready", None
        dry_run = case_input.get("dry_run") or {}
        confirmation = case_input.get("confirmation")
        if confirmation is None:
            return "blocked", "LM-COMPAT-CONFIRMATION-REQUIRED"
        bound_fields = (
            "migration_id", "report_sha256", "source_inventory_sha256",
            "destination_precondition_sha256", "migrator_version", "project_id",
        )
        if confirmation.get("operation") != "promote" or any(
            confirmation.get(field) != dry_run.get(field) for field in bound_fields
        ):
            return "blocked", "LM-COMPAT-CONFIRMATION-STALE"
        if not confirmation.get("confirmed_at"):
            return "blocked", "LM-COMPAT-CONFIRMATION-STALE"
        try:
            datetime.fromisoformat(str(confirmation["confirmed_at"]).replace("Z", "+00:00"))
        except ValueError:
            return "blocked", "LM-COMPAT-CONFIRMATION-STALE"
        for field in ("report_sha256", "source_inventory_sha256", "destination_precondition_sha256"):
            if re.fullmatch(r"[a-f0-9]{64}", str(dry_run.get(field, ""))) is None:
                return "blocked", "LM-COMPAT-CONFIRMATION-STALE"
        if case_input.get("current_source_inventory_sha256") != dry_run.get("source_inventory_sha256"):
            return "blocked", "LM-COMPAT-SOURCE-DRIFT"
        if case_input.get("current_destination_precondition_sha256") != dry_run.get("destination_precondition_sha256"):
            return "blocked", "LM-COMPAT-CONFIRMATION-STALE"
        if not case_input.get("backup_valid", False) or not case_input.get("staging_valid", False):
            return "aborted_cleanly", "LM-MIGRATION-VALIDATION-FAILED"
        return "promoted", None

    def fixture_group(self, name: str, evaluator) -> None:
        for item in self.fixtures[name]:
            code = evaluator(item["instance"], item.get("context"))
            actual = "accept" if code is None else "reject"
            if actual != item["expected"]:
                self.fail(f"{item['case_id']}: expected {item['expected']}, got {actual} ({code})")
            if actual == "reject" and code != item.get("expected_code"):
                self.fail(f"{item['case_id']}: expected code {item.get('expected_code')}, got {code}")

    def fixtures_gate(self) -> None:
        self.fixture_group("state_cases", lambda value, _context: self.state_code(value))
        self.fixture_group("event_cases", self.event_code)
        self.fixture_group("transaction_cases", self.transaction_code)
        self.fixture_group("handoff_cases", self.handoff_code)
        for item in self.fixtures["event_sequence_cases"]:
            outcome, code = self.sequence_code(item)
            if outcome != item["expected"] or code != item.get("expected_code"):
                self.fail(f"{item['case_id']}: expected {item['expected']}/{item.get('expected_code')}, got {outcome}/{code}")
        for item in self.fixtures["transaction_sequence_cases"]:
            outcome, code = self.transaction_sequence_code(item)
            if outcome != item["expected"] or code != item.get("expected_code"):
                self.fail(f"{item['case_id']}: expected {item['expected']}/{item.get('expected_code')}, got {outcome}/{code}")
        for item in self.fixtures["migration_cases"]:
            outcome, code = self.migration_result(item["input"])
            if outcome != item["expected"] or code != item.get("expected_code"):
                self.fail(f"{item['case_id']}: expected {item['expected']}/{item.get('expected_code')}, got {outcome}/{code}")
        invocation_map = {}
        for command_id, data in self.commands.items():
            invocation_map[data["canonical"]] = (command_id, data["role"])
            invocation_map[data["legacy_alias"]] = (command_id, data["role"])
        for item in self.fixtures["alias_cases"]:
            actual = invocation_map.get(item["invocation"])
            expected = (item["expected_command_id"], item["expected_role"])
            if actual != expected:
                self.fail(f"{item['case_id']}: alias drift")
        categories = {
            "state_negative_codes": self.fixtures["state_cases"],
            "event_negative_codes": self.fixtures["event_cases"] + self.fixtures["event_sequence_cases"],
            "transaction_negative_codes": self.fixtures["transaction_cases"] + self.fixtures["transaction_sequence_cases"],
            "handoff_negative_codes": self.fixtures["handoff_cases"],
            "migration_negative_codes": self.fixtures["migration_cases"],
        }
        for key, cases in categories.items():
            present = {item.get("expected_code") for item in cases if item.get("expected_code")}
            required = set(self.fixtures["coverage_requirements"][key])
            if not required.issubset(present):
                self.fail(f"negative fixture coverage missing for {key}: {sorted(required - present)}")

    def preservation(self) -> None:
        if len(self.catalog_by_id) != 100 or len(self.catalog["tactics"]) != 100:
            self.fail("P3 catalog no longer contains exactly 100 unique tactics")
            return
        if not SOURCE.exists():
            self.fail("canonical source repository missing")
            return
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True, capture_output=True, check=True).stdout.strip()
        status = subprocess.run(["git", "status", "--short"], cwd=SOURCE, text=True, capture_output=True, check=True).stdout.strip()
        if head != BASELINE_COMMIT:
            self.fail(f"canonical source commit drift: {head}")
        if status:
            self.fail("canonical source worktree is not clean")
        seen_paths = set()
        aggregate_records = []
        for item in sorted(self.catalog["tactics"], key=lambda row: row["canonical_path"]):
            rel = item["canonical_path"]
            path = SOURCE / rel
            if rel in seen_paths or not path.is_file():
                self.fail(f"canonical prompt missing/duplicate: {rel}")
                continue
            seen_paths.add(rel)
            actual = sha256_file(path)
            if actual != item["canonical_sha256"]:
                self.fail(f"canonical prompt hash drift: {rel}")
            aggregate_records.append(f"{rel}\0{actual}")
        aggregate = hashlib.sha256("\n".join(aggregate_records).encode("utf-8")).hexdigest()
        if aggregate != LIBRARY_HASH:
            self.fail(f"canonical library aggregate drift: {aggregate}")
        if self.manifest["baseline"] != {
            "source_commit": BASELINE_COMMIT,
            "canonical_prompt_count": 100,
            "aggregate_sha256": LIBRARY_HASH,
        }:
            self.fail("P4 baseline manifest drift")

    def manifest_gate(self) -> None:
        sections = ["source_contracts", "workstreams", "official_artifacts", "scripts"]
        if "gate_reports" in self.manifest:
            sections.append("gate_reports")
        for section in sections:
            for entry in self.manifest[section]:
                path = self.root / entry["path"]
                if not path.is_file() or sha256_file(path) != entry["sha256"]:
                    self.fail(f"manifest hash drift: {entry['path']}")
        workstream_expectations = {
            "state-events.json": ("verdict", "conditionally_ready_for_p4_integration_review"),
            "handoff.json": ("verdict", "ready_for_lead_integration"),
            "migration.json": ("verdict", "PASS"),
        }
        for name, (section, expected) in workstream_expectations.items():
            data = load(self.p4 / "workstreams" / name)
            verdict = data[section]
            actual = verdict.get("result", verdict.get("status"))
            if actual != expected:
                self.fail(f"unexpected workstream verdict: {name}={actual}")

    def run(self) -> dict:
        self.contracts()
        self.fixtures_gate()
        self.preservation()
        self.manifest_gate()
        return {
            "status": "PASS" if not self.errors else "FAIL",
            "error_count": len(self.errors),
            "errors": self.errors,
            "counts": {
                "canonical_event_types": len(self.event_types),
                "handoff_fields": len(self.handoff_schema["required"]),
                "canonical_prompts": len(self.catalog_by_id),
                "fixtures": sum(
                    len(self.fixtures[key]) for key in (
                        "state_cases", "event_cases", "event_sequence_cases", "transaction_cases", "transaction_sequence_cases",
                        "handoff_cases", "migration_cases", "alias_cases",
                    )
                ),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = P4Validator(args.root.resolve()).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
