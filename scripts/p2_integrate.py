#!/usr/bin/env python3
"""Integrate reviewed P2 workstreams into the official machine-readable contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
P2 = ROOT / "artifacts" / "P2"
WORKSTREAMS = P2 / "workstreams"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def integrate_roles(source_path: Path) -> dict[str, Any]:
    source = load(source_path)
    compatibility_path = WORKSTREAMS / "compatibility.json"
    compatibility = load(compatibility_path)
    command_by_role = {
        "loop_planning": "loop.planning",
        "verbalizar": "loop.verbalizar",
        "orientar": "loop.orientar",
        "ampliar": "loop.ampliar",
        "refinar": "loop.refinar",
    }
    command_contracts = {
        item["command_id"]: item
        for item in compatibility["command_compatibility"]["commands"]
    }
    tactic_field = {
        "name": "tactic_refs",
        "required": True,
        "constraint": "Array; pode ser vazio. Cada tatica selecionada registra ID, path, sha256 e motivo sem copiar o prompt."
    }
    fields = list(source["mandatory_handoff_contract"]["fields"])
    input_index = next(
        index for index, item in enumerate(fields) if item["name"] == "input_refs"
    )
    fields.insert(input_index + 1, tactic_field)
    handoff_contract = dict(source["mandatory_handoff_contract"])
    handoff_contract["fields"] = fields
    for item in handoff_contract["fields"]:
        if item["name"] == "mode":
            item["constraint"] = "completo, parcial ou minimo_viavel."

    roles: list[dict[str, Any]] = []
    for role in source["roles"]:
        normalized = dict(role)
        command = command_contracts[command_by_role[role["canonical_role_id"]]]
        normalized["command_contract"] = {
            "command_id": command["command_id"],
            "canonical_invocation": command["canonical_invocation"],
            "backward_compatible_aliases": command["backward_compatible_aliases"],
        }
        normalized["aliases"] = sorted(
            set(
                role.get("aliases", [])
                + [
                    command["canonical_name"],
                    command["canonical_invocation"],
                    *command["backward_compatible_aliases"],
                ]
            )
        )
        mandatory = list(role["mandatory_handoff_fields"])
        mandatory.insert(mandatory.index("input_refs") + 1, "tactic_refs")
        normalized["mandatory_handoff_fields"] = mandatory
        if role["canonical_role_id"] == "ampliar":
            normalized["outputs"] = [
                "channel_role_and_feasibility_classification_with_evidence"
                if item == "channel_classification_with_evidence"
                else item
                for item in role["outputs"]
            ]
            normalized["semantic_boundaries"] = {
                "channel_role_and_feasibility_classification_with_evidence": "Classifica papel, fit, capacidade e restricoes do canal como primario, secundario ou evitar; nao classifica performance como ESCALAR, OTIMIZAR, PARAR ou TESTAR.",
                "performance_action_classification": "Pertence exclusivamente a Refinar."
            }
        roles.append(normalized)
    unresolved = [
        item
        for item in source["unresolved_questions"]
        if item["id"] != "RA-Q002"
    ]
    return {
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "phase": "P2",
        "status": "integrated",
        "source_workstream": {
            "path": str(source_path.relative_to(ROOT)),
            "sha256": digest(source_path),
        },
        "compatibility_workstream": {
            "path": str(compatibility_path.relative_to(ROOT)),
            "sha256": digest(compatibility_path),
        },
        "baseline": source["baseline"],
        "authority_invariants": source["authority_invariants"],
        "decision_ownership": source["canonical_authority_map"],
        "authority_resolutions": source["authority_resolutions"],
        "roles": roles,
        "handoff_contract": handoff_contract,
        "temporal_authority_model": source["temporal_authority_model"],
        "state_event_authority": source["state_event_authority"],
        "library_preservation": source["library_preservation"],
        "resolved_during_integration": [
            {
                "question_id": "RA-Q002",
                "resolution": "routing-contract.json decision_rules.refinar_benchmark_intervals defines complete, inclusive and precedence-ordered intervals."
            }
        ],
        "deferred_questions": unresolved,
    }


def integrate_routing(source_path: Path) -> dict[str, Any]:
    source = load(source_path)
    role_source = load(WORKSTREAMS / "role-authority.json")
    required_handoff_fields = [
        item["name"] for item in role_source["mandatory_handoff_contract"]["fields"]
    ]
    required_handoff_fields.insert(
        required_handoff_fields.index("input_refs") + 1, "tactic_refs"
    )
    handoff_validation = source["decision_rules"]["handoff_validation"]
    handoff_validation["required_fields"] = required_handoff_fields
    handoff_validation["validation_rules"][0]["rule"] = (
        "Every canonical handoff field MUST be present. tactic_refs, assumptions and known_gaps are arrays and may be empty; evidence_refs may be empty only when assumptions is non-empty and every unsupported claim remains a hypothesis."
    )
    handoff_validation["canonical_contract_source"] = "role-matrix.json#handoff_contract"
    source["canonical_enums"]["maturity"] = [
        "nascente", "em_desenvolvimento", "maduro", "avancado", "unknown"
    ]
    maturity = source["decision_rules"]["maturity_gating"]
    maturity["required_classification_dimensions"] = [
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
    ]
    maturity["unknown_policy"] = (
        "If any required classification dimension is unknown and the known values do not already prove a higher row, aggregate maturity is unknown; missing data MUST NOT be coerced to nascente."
    )
    decision_table = maturity["decision_table"]
    decision_table[-1] = {
        "order": 4,
        "classification": "unknown",
        "when": "one or more required_classification_dimensions are unknown after evaluating rows 1 through 3",
    }
    decision_table.append(
        {
            "order": 5,
            "classification": "nascente",
            "when": "all required_classification_dimensions are evidenced and none of rows 1 through 3 match",
        }
    )
    maturity["tactic_gate_rules"].append(
        {
            "id": "RTE-MAT-005",
            "kind": "decision_rule",
            "rule": "Aggregate maturity unknown blocks tactic selection and falls back to the specialist base method until the missing dimensions are evidenced.",
            "on_failure": "ERR_MATURITY_GATE",
        }
    )
    tactic_selection = source["decision_rules"]["tactic_selection"]
    tactic_selection["selection_unit"] = (
        "One specialist route node identified by route_node_id. A repeated specialist in the same loop cycle is a new node with its own declared objective and dependencies."
    )
    tactic_selection["cardinality_rules"][-1]["when"] = (
        "more than two tactics are requested for one specialist route_node"
    )
    for item in source["rejection_codes"]:
        if item["code"] == "ERR_TACTIC_CARDINALITY":
            item["meaning"] = "more than two tactics were selected for one specialist route_node"
            item["remedy"] = "retain at most two eligible complementary tactics or decompose the objective into another route node"

    benchmark = source["decision_rules"]["refinar_benchmark_intervals"]
    benchmark["normalization"]["requirements"].extend(
        [
            "the ratio classifier accepts only a non-negative metric domain",
            "for higher_is_better, observed_value MUST be >= 0 and benchmark_value MUST be > 0",
            "for lower_is_better, observed_value MUST be > 0 and benchmark_value MUST be >= 0",
            "a negative value or an unsupported zero denominator requires a predeclared metric-specific transformation or direct threshold; without it classify TESTAR and do not calculate performance_index",
        ]
    )
    benchmark["classification_precedence"][0]["when_any"].append(
        "observed or benchmark values fall outside the declared non-negative ratio domain and no predeclared metric-specific transformation or direct threshold exists"
    )

    source["unresolved_questions"] = [
        item for item in source["unresolved_questions"] if item["id"] != "UQ-002"
    ]
    source["resolved_questions"] = [
        {
            "id": "UQ-002",
            "resolution": "cancelled and invalidated are canonical v2 terminal dispositions; invalidated may supersede completed by append-only evidence without rewriting history.",
            "resolved_in": ["canonical_enums.experiment_state", "decision_rules.experiment_state_machine"],
        }
    ]
    source["product_version"] = "2.0.0"
    source["status"] = "integrated"
    source["source_workstream"] = {
        "path": str(source_path.relative_to(ROOT)),
        "sha256": digest(source_path),
    }
    source["lead_resolutions"] = {
        "UQ-001": "Deferred to P3; fail closed to the specialist base method until complete tactic metadata exists.",
        "UQ-003": "Deferred to P7; TESTAR is mandatory when statistical sufficiency cannot be proven by a predeclared method.",
        "UQ-004": "Deferred to P7; conservative maturity gates remain proposed and must be replay-evaluated before release.",
        "UQ-005": "Deferred to P4; staged outputs and one compare-and-swap integration remain the safe contract."
    }
    return source


def main() -> int:
    role_source = WORKSTREAMS / "role-authority.json"
    routing_source = WORKSTREAMS / "routing-rules.json"
    role_output = P2 / "role-matrix.json"
    routing_output = P2 / "routing-contract.json"
    write(role_output, integrate_roles(role_source))
    write(routing_output, integrate_routing(routing_source))
    manifest_output = P2 / "integration-manifest.json"
    official_paths = [
        P2 / "canonical-spec.md",
        role_output,
        routing_output,
        P2 / "compatibility-policy.md",
    ]
    workstream_paths = [
        WORKSTREAMS / "role-authority.json",
        WORKSTREAMS / "routing-rules.json",
        WORKSTREAMS / "compatibility.json",
    ]
    script_paths = [Path(__file__).resolve(), ROOT / "scripts/p2_validate.py"]
    write(
        manifest_output,
        {
            "schema_version": "1.0",
            "product_version": "2.0.0",
            "phase": "P2",
            "status": "integrated",
            "official_artifacts": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                }
                for path in official_paths
            ],
            "workstream_evidence": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": digest(path),
                }
                for path in workstream_paths
            ],
            "integration_scripts": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": digest(path),
                }
                for path in script_paths
            ],
        },
    )
    print(
        json.dumps(
            {
                "status": "integrated",
                "outputs": [
                    str(role_output.relative_to(ROOT)),
                    str(routing_output.relative_to(ROOT)),
                    str(manifest_output.relative_to(ROOT)),
                ],
                "roles": 5,
                "routing_error_codes": len(
                    load(routing_output)["rejection_codes"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
