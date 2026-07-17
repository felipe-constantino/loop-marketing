#!/usr/bin/env python3
"""Validate the P3 sidecar catalog without modifying canonical prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
P3 = ROOT / "artifacts" / "P3"
WORKSTREAMS = P3 / "workstreams"
SCHEMA_PATH = P3 / "catalog-schema.json"
PROJECT_PATH = ROOT / "PROJECT.json"
SOURCE_INDEX_PATH = ROOT / "SOURCE_INDEX.json"

PILLARS = {
    "Verbalizar": {
        "file": "verbalizar.json",
        "stage": "Express",
        "role": "verbalizar",
        "id_prefix": "lm.verbalizar.",
    },
    "Orientar": {
        "file": "orientar.json",
        "stage": "Tailor",
        "role": "orientar",
        "id_prefix": "lm.orientar.",
    },
    "Ampliar": {
        "file": "ampliar.json",
        "stage": "Amplify",
        "role": "ampliar",
        "id_prefix": "lm.ampliar.",
    },
    "Refinar": {
        "file": "refinar.json",
        "stage": "Evolve",
        "role": "refinar",
        "id_prefix": "lm.refinar.",
    },
}

ROLE_DOMAIN = {
    "verbalizar": "message_and_copy",
    "orientar": "lifecycle_segmentation_and_eligibility",
    "ampliar": "channel_timing_and_cadence",
    "refinar": "experiment_performance_and_learning",
}
DOMAIN_AUTHORITY = {
    "global_orchestration": "loop_planning",
    "message_and_copy": "verbalizar",
    "lifecycle_segmentation_and_eligibility": "orientar",
    "channel_timing_and_cadence": "ampliar",
    "experiment_performance_and_learning": "refinar",
    "security_privacy_and_data_use": "security_review",
    "external_execution_authorization": "authorized_operator",
}

REFINAR_SCOPE_FIXTURES = {
    "lm.refinar.sistema-de-integracao-de-aprendizagem": {
        "domains": {
            "message_and_copy", "lifecycle_segmentation_and_eligibility",
            "channel_timing_and_cadence", "external_execution_authorization",
        },
        "ranges": [(125, 136), (171, 182)],
    },
    "lm.refinar.analisador-de-desempenho-de-coorte": {
        "domains": {
            "message_and_copy", "lifecycle_segmentation_and_eligibility",
            "channel_timing_and_cadence", "external_execution_authorization",
        },
        "ranges": [(104, 107), (121, 155), (155, 165)],
    },
    "lm.refinar.interprete-de-analises-da-jornada-do-cliente": {
        "domains": {
            "global_orchestration", "message_and_copy",
            "lifecycle_segmentation_and_eligibility", "channel_timing_and_cadence",
            "external_execution_authorization",
        },
        "ranges": [(63, 98), (118, 138), (173, 195)],
    },
    "lm.refinar.coordenador-de-testes-entre-canais": {
        "domains": {"channel_timing_and_cadence", "external_execution_authorization"},
        "ranges": [(102, 119), (122, 141)],
    },
    "lm.refinar.otimizador-de-atribuicao-de-marketing": {
        "domains": {
            "message_and_copy", "lifecycle_segmentation_and_eligibility",
            "channel_timing_and_cadence", "external_execution_authorization",
        },
        "ranges": [(5, 9), (89, 90), (102, 124), (142, 170)],
    },
    "lm.refinar.modelador-de-combinacao-de-marketing": {
        "domains": {
            "global_orchestration", "message_and_copy",
            "lifecycle_segmentation_and_eligibility", "channel_timing_and_cadence",
            "external_execution_authorization",
        },
        "ranges": [(50, 52), (77, 105), (126, 128), (136, 162), (170, 173)],
    },
    "lm.refinar.calculadora-de-otimizacao": {
        "domains": {
            "global_orchestration", "channel_timing_and_cadence",
            "external_execution_authorization",
        },
        "ranges": [(123, 127), (162, 185)],
    },
    "lm.refinar.gerador-de-relatorios-de-otimizacao-continua": {
        "domains": {
            "message_and_copy", "channel_timing_and_cadence",
            "external_execution_authorization",
        },
        "ranges": [(45, 50), (89, 93)],
    },
    "lm.refinar.resultados-previsiveis-da-campanha-antes-do-lancamento": {
        "domains": {
            "message_and_copy", "lifecycle_segmentation_and_eligibility",
            "channel_timing_and_cadence", "external_execution_authorization",
        },
        "ranges": [(36, 42), (50, 56), (117, 117)],
    },
    "lm.refinar.construtor-de-estrutura-de-experimentacao-rapida": {
        "domains": {
            "message_and_copy", "lifecycle_segmentation_and_eligibility",
            "channel_timing_and_cadence", "external_execution_authorization",
        },
        "ranges": [(24, 24), (32, 44), (69, 69)],
    },
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def require_fields(
    value: dict[str, Any], fields: set[str], label: str, errors: list[str]
) -> None:
    missing = sorted(fields - value.keys())
    if missing:
        errors.append(f"{label} misses fields: {missing}")


def validate_source(errors: list[str]) -> tuple[Path, dict[str, dict[str, Any]], str]:
    project = load(PROJECT_PATH)
    index = load(SOURCE_INDEX_PATH)
    repo = Path(project["source"]["repo"])
    expected_commit = project["source"]["baseline_commit"]
    if run_git(repo, "rev-parse", "HEAD") != expected_commit:
        errors.append("source HEAD differs from baseline during P3")
    if run_git(repo, "status", "--porcelain"):
        errors.append("source worktree changed during P3")
    if len(run_git(repo, "ls-files").splitlines()) != 117:
        errors.append("source no longer has 117 tracked files")
    prompts = index.get("canonical_prompts", [])
    if not isinstance(prompts, list) or len(prompts) != 100:
        errors.append("SOURCE_INDEX must contain exactly 100 canonical prompts")
        return repo, {}, ""
    source_map: dict[str, dict[str, Any]] = {}
    records: list[str] = []
    for item in prompts:
        path = str(item.get("path"))
        candidate = repo / path
        if path in source_map:
            errors.append(f"SOURCE_INDEX repeats canonical path {path}")
        if not candidate.is_file():
            errors.append(f"canonical source file is missing: {path}")
            continue
        actual = sha256(candidate)
        if actual != item.get("sha256"):
            errors.append(f"canonical source hash changed: {path}")
        source_map[path] = {
            "sha256": actual,
            "line_count": len(candidate.read_bytes().splitlines()),
        }
        records.append(f"{path}\0{actual}")
    aggregate = hashlib.sha256("\n".join(sorted(records)).encode()).hexdigest()
    expected_aggregate = project["source"]["baseline_library_aggregate_sha256"]
    if aggregate != expected_aggregate:
        errors.append("canonical library aggregate changed during P3")
    return repo, source_map, aggregate


def schema_values(schema: dict[str, Any], definition: str, field: str = "enum") -> set[str]:
    return set(schema["$defs"][definition][field])


def validate_schema(schema: dict[str, Any], errors: list[str]) -> None:
    required_defs = {
        "tactic", "tacticCatalog", "relation", "relationshipMap", "baseline",
        "jobTag", "objectTag", "quality", "provenance", "executionPolicy",
        "canonicalScopeConflict", "mandatoryHandoff", "decisionDomain",
    }
    missing = sorted(required_defs - schema.get("$defs", {}).keys())
    if missing:
        errors.append(f"catalog schema misses definitions: {missing}")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("catalog schema must use JSON Schema 2020-12")
    for definition in ("jobTag", "objectTag"):
        values = schema.get("$defs", {}).get(definition, {}).get("enum", [])
        if not values or len(values) != len(set(values)):
            errors.append(f"schema enum {definition} is empty or duplicated")
    tactic_required = set(schema.get("$defs", {}).get("tactic", {}).get("required", []))
    tactic_properties = set(schema.get("$defs", {}).get("tactic", {}).get("properties", {}))
    if tactic_required != tactic_properties:
        errors.append("every tactic property must be required in P3 v1")


def validate_input_requirements(
    value: Any, label: str, schema: dict[str, Any], errors: list[str]
) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} input_requirements must be non-empty")
        return
    input_schema = schema["$defs"]["inputRequirement"]
    required = set(input_schema["required"])
    allowed = set(input_schema["properties"])
    evidence_allowed = set(input_schema["properties"]["evidence_types"]["items"]["enum"])
    sensitivity_allowed = set(input_schema["properties"]["sensitivity"]["enum"])
    ids: set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors.append(f"{label} input {index} is not an object")
            continue
        if set(item) != allowed or not required.issubset(item):
            errors.append(f"{label} input {index} fields differ from schema")
        input_id = item.get("input_id")
        if not nonempty(input_id) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(input_id)):
            errors.append(f"{label} input {index} has invalid input_id")
        if input_id in ids:
            errors.append(f"{label} repeats input_id {input_id}")
        ids.add(str(input_id))
        if not nonempty(item.get("description")) or not isinstance(item.get("required"), bool):
            errors.append(f"{label} input {input_id} has invalid description/required")
        evidence = item.get("evidence_types")
        if not isinstance(evidence, list) or not evidence or len(evidence) != len(set(evidence)) or not set(evidence).issubset(evidence_allowed):
            errors.append(f"{label} input {input_id} has invalid evidence_types")
        if item.get("sensitivity") not in sensitivity_allowed:
            errors.append(f"{label} input {input_id} has invalid sensitivity")


def validate_execution_policy(
    entry: dict[str, Any],
    meta: dict[str, str],
    source_record: dict[str, Any],
    schema: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    policy = entry.get("execution_policy")
    policy_schema = schema["$defs"]["executionPolicy"]
    policy_fields = set(policy_schema["properties"])
    if not isinstance(policy, dict) or set(policy) != policy_fields:
        errors.append(f"{label} execution_policy fields differ from schema")
        return
    mode = policy.get("execution_mode")
    automatic = policy.get("automatic_selection")
    if mode not in {"canonical_safe", "sidecar_constrained", "base_method_only"}:
        errors.append(f"{label} has invalid execution mode")
    if automatic not in {"allowed", "planner_review_required", "forbidden"}:
        errors.append(f"{label} has invalid automatic selection policy")
    owner_domain = ROLE_DOMAIN[meta["role"]]
    if policy.get("owner_domain") != owner_domain:
        errors.append(f"{label} execution owner domain differs from P2 authority")
    if not isinstance(policy.get("runtime_overlay_required"), bool):
        errors.append(f"{label} runtime_overlay_required must be boolean")

    output = entry.get("output_contract")
    required_sections = set(output.get("required_sections", [])) if isinstance(output, dict) else set()
    allowed_sections = policy.get("allowed_output_sections")
    excluded_sections = policy.get("excluded_output_sections")
    if not isinstance(allowed_sections, list) or len(allowed_sections) != len(set(allowed_sections)):
        errors.append(f"{label} has invalid allowed_output_sections")
        allowed_sections = []
    if not isinstance(excluded_sections, list) or len(excluded_sections) != len(set(excluded_sections)):
        errors.append(f"{label} has invalid excluded_output_sections")
        excluded_sections = []
    if set(allowed_sections) & set(excluded_sections):
        errors.append(f"{label} allowed and excluded output sections overlap")
    if mode == "base_method_only":
        if allowed_sections:
            errors.append(f"{label} base_method_only cannot expose canonical output sections")
    elif set(allowed_sections) != required_sections:
        errors.append(f"{label} allowed output sections must equal the sidecar output contract")

    prohibited = policy.get("prohibited_decisions")
    domain_allowed = set(DOMAIN_AUTHORITY)
    if (
        not isinstance(prohibited, list)
        or not prohibited
        or len(prohibited) != len(set(prohibited))
        or not set(prohibited).issubset(domain_allowed)
    ):
        errors.append(f"{label} has invalid prohibited_decisions")
        prohibited = []
    if owner_domain in prohibited:
        errors.append(f"{label} prohibits its own P2 decision domain")
    expected_prohibited = domain_allowed - {owner_domain}
    if set(prohibited) != expected_prohibited:
        errors.append(
            f"{label} prohibited_decisions must cover every non-owner authority domain"
        )

    conflicts = policy.get("canonical_scope_conflicts")
    conflict_fields = set(schema["$defs"]["canonicalScopeConflict"]["properties"])
    conflict_ids: set[str] = set()
    conflict_domains: set[str] = set()
    if not isinstance(conflicts, list):
        errors.append(f"{label} canonical_scope_conflicts must be a list")
        conflicts = []
    for index, conflict in enumerate(conflicts, 1):
        if not isinstance(conflict, dict) or set(conflict) != conflict_fields:
            errors.append(f"{label} scope conflict {index} fields differ from schema")
            continue
        conflict_id = conflict.get("conflict_id")
        if not isinstance(conflict_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", conflict_id) or conflict_id in conflict_ids:
            errors.append(f"{label} scope conflict {index} has invalid conflict_id")
        conflict_ids.add(str(conflict_id))
        if conflict.get("conflict_type") not in {
            "owner_boundary", "sensitive_data", "external_execution",
            "editorial_integrity", "unverifiable_claim",
        }:
            errors.append(f"{label} scope conflict {conflict_id} has invalid type")
        start = conflict.get("source_line_start")
        end = conflict.get("source_line_end")
        if (
            not isinstance(start, int) or not isinstance(end, int)
            or start < 1 or end < start or end > source_record["line_count"]
        ):
            errors.append(f"{label} scope conflict {conflict_id} has invalid source lines")
        domain = conflict.get("decision_domain")
        authority = conflict.get("destination_authority")
        if domain not in DOMAIN_AUTHORITY or DOMAIN_AUTHORITY.get(str(domain)) != authority:
            errors.append(f"{label} scope conflict {conflict_id} has invalid authority mapping")
        else:
            conflict_domains.add(str(domain))
        if domain not in prohibited:
            errors.append(f"{label} scope conflict {conflict_id} is not prohibited by policy")
        if not nonempty(conflict.get("canonical_request")) or not nonempty(conflict.get("safe_handling")):
            errors.append(f"{label} scope conflict {conflict_id} has empty evidence or handling")

    handoffs = policy.get("mandatory_handoffs")
    handoff_fields = set(schema["$defs"]["mandatoryHandoff"]["properties"])
    handoff_ids: set[str] = set()
    handoff_domains: set[str] = set()
    if not isinstance(handoffs, list):
        errors.append(f"{label} mandatory_handoffs must be a list")
        handoffs = []
    for index, handoff in enumerate(handoffs, 1):
        if not isinstance(handoff, dict) or set(handoff) != handoff_fields:
            errors.append(f"{label} handoff {index} fields differ from schema")
            continue
        handoff_id = handoff.get("handoff_id")
        if not isinstance(handoff_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", handoff_id) or handoff_id in handoff_ids:
            errors.append(f"{label} handoff {index} has invalid handoff_id")
        handoff_ids.add(str(handoff_id))
        domain = handoff.get("decision_domain")
        target = handoff.get("target_authority")
        if domain not in DOMAIN_AUTHORITY or DOMAIN_AUTHORITY.get(str(domain)) != target:
            errors.append(f"{label} handoff {handoff_id} has invalid authority mapping")
        else:
            handoff_domains.add(str(domain))
        if handoff.get("required") is not True:
            errors.append(f"{label} handoff {handoff_id} must be required")
        if not nonempty(handoff.get("trigger")) or not nonempty(handoff.get("requested_output")):
            errors.append(f"{label} handoff {handoff_id} has empty trigger or output")
    if not conflict_domains.issubset(handoff_domains):
        errors.append(f"{label} scope conflicts do not all have mandatory authority handoffs")

    if mode == "canonical_safe":
        if conflicts or excluded_sections or policy.get("runtime_overlay_required") is not False:
            errors.append(f"{label} canonical_safe has conflicts, exclusions, or overlay")
    elif mode == "sidecar_constrained":
        if policy.get("runtime_overlay_required") is not True or not (conflicts or excluded_sections):
            errors.append(f"{label} constrained mode lacks executable overlay constraints")
        if automatic == "allowed":
            errors.append(f"{label} constrained mode cannot be selected automatically")
    elif mode == "base_method_only":
        if automatic != "forbidden" or policy.get("runtime_overlay_required") is not False:
            errors.append(f"{label} base_method_only must forbid selection and skip overlay")
    quality = entry.get("quality")
    if (
        isinstance(quality, dict)
        and quality.get("semantic_review_status") == "needs_editorial_review"
        and automatic == "allowed"
    ):
        errors.append(f"{label} needs editorial review but allows automatic selection")
    flags = set(quality.get("flags", [])) if isinstance(quality, dict) else set()
    automatic_review_flags = {
        "ambiguous_instruction", "pii_sensitive", "security_sensitive",
        "unverified_external_claim",
    }
    if automatic == "allowed" and flags & automatic_review_flags:
        errors.append(
            f"{label} allows automatic selection despite review-required flags "
            f"{sorted(flags & automatic_review_flags)}"
        )
    if "unverified_external_claim" in flags:
        has_claim_constraint = any(
            isinstance(conflict, dict)
            and conflict.get("conflict_type") == "unverifiable_claim"
            for conflict in conflicts
        )
        if mode == "canonical_safe" or not has_claim_constraint:
            errors.append(f"{label} has an unverified claim without a constrained execution rule")
    if not nonempty(policy.get("fallback")):
        errors.append(f"{label} execution policy has empty fallback")


def validate_authority_fixtures(
    entry: dict[str, Any], label: str, errors: list[str]
) -> None:
    tactic_id = entry.get("tactic_id")
    jobs = set(entry.get("job_tags", []))
    objects = set(entry.get("object_tags", []))
    needs = set(entry.get("need_tags", []))
    output = entry.get("output_contract", {})
    output_type = output.get("output_type") if isinstance(output, dict) else None
    sections = set(output.get("required_sections", [])) if isinstance(output, dict) else set()
    policy = entry.get("execution_policy", {})

    if tactic_id == "lm.verbalizar.perfil-do-cliente-ideal" and (
        "segment" in jobs
        or "segmentation" in objects
        or "segment:segmentation" in needs
        or output_type == "segmentation_model"
    ):
        errors.append(f"{label} exposes an Orientar segmentation decision through Verbalizar")
    if tactic_id == "lm.verbalizar.mapeador-da-jornada-do-cliente" and (
        "map:customer-journey" in needs or output_type == "journey_map"
    ):
        errors.append(f"{label} exposes lifecycle journey ownership through Verbalizar")
    if tactic_id == "lm.orientar.personalizacao-orientada-por-comentarios" and (
        "optimize" in jobs
        or "optimization" in objects
        or "optimize:optimization" in needs
        or output_type == "learning_system"
        or "learning-loop" in sections
    ):
        errors.append(f"{label} exposes a Refinar learning decision through Orientar")
    if tactic_id == "lm.ampliar.otimizador-de-atribuicao-cruzada-de-canal" and (
        "design:attribution" in needs or output_type != "brief"
    ):
        errors.append(f"{label} exposes attribution model design through Ampliar")

    customer_programs = {
        "lm.ampliar.amplificador-de-defesa-do-cliente",
        "lm.ampliar.mecanismo-de-referencias-do-cliente",
        "lm.ampliar.multiplicador-de-conteudo-gerado-pelo-usuario",
    }
    if tactic_id in customer_programs:
        sensitivities = {
            requirement.get("sensitivity")
            for requirement in entry.get("input_requirements", [])
            if isinstance(requirement, dict)
        }
        if "customer_level_pii" not in sensitivities:
            conflicts = policy.get("canonical_scope_conflicts", []) if isinstance(policy, dict) else []
            has_sensitive_exclusion = any(
                isinstance(conflict, dict)
                and conflict.get("conflict_type") == "sensitive_data"
                and conflict.get("decision_domain") == "security_privacy_and_data_use"
                for conflict in conflicts
            )
            if (
                policy.get("execution_mode") not in {"sidecar_constrained", "base_method_only"}
                or not has_sensitive_exclusion
                or not policy.get("excluded_output_sections")
            ):
                errors.append(f"{label} under-models canonical customer-level PII without a safe-mode exclusion")
        for section in sections:
            if (
                ("eligibility" in section or "suppression" in section)
                and "reference" not in section
                and "accepted" not in section
            ):
                errors.append(f"{label} owns eligibility semantics instead of consuming a reference")

    refinar_fixture = REFINAR_SCOPE_FIXTURES.get(str(tactic_id))
    if refinar_fixture is not None:
        conflicts = policy.get("canonical_scope_conflicts", []) if isinstance(policy, dict) else []
        declared_domains = {
            conflict.get("decision_domain")
            for conflict in conflicts
            if isinstance(conflict, dict)
        }
        missing_domains = sorted(refinar_fixture["domains"] - declared_domains)
        if missing_domains:
            errors.append(
                f"{label} misses required Refinar cross-owner conflict domains {missing_domains}"
            )
        for expected_start, expected_end in refinar_fixture["ranges"]:
            covered = any(
                isinstance(conflict, dict)
                and isinstance(conflict.get("source_line_start"), int)
                and isinstance(conflict.get("source_line_end"), int)
                and conflict["source_line_start"] <= expected_end
                and conflict["source_line_end"] >= expected_start
                for conflict in conflicts
            )
            if not covered:
                errors.append(
                    f"{label} misses required Refinar source conflict range "
                    f"{expected_start}-{expected_end}"
                )
        if tactic_id == "lm.refinar.sistema-de-integracao-de-aprendizagem" and (
            policy.get("execution_mode") != "sidecar_constrained"
            or policy.get("automatic_selection") != "planner_review_required"
            or policy.get("runtime_overlay_required") is not True
        ):
            errors.append(f"{label} learning integration body must be sidecar constrained")

    if entry.get("pillar") == "Refinar" and policy.get("execution_mode") == "sidecar_constrained":
        fallback = str(policy.get("fallback", "")).lower()
        phrase_groups = {
            "overlay": ("overlay",),
            "planner review": ("planner review", "revisão do planner", "revisao do planner"),
            "do not load": ("não carregar", "nao carregar"),
            "do not execute": ("não executar", "nao executar"),
            "base method": ("método-base", "metodo-base", "método base", "metodo base"),
            "TESTAR": ("testar",),
            "data_gap_plan": ("data_gap_plan",),
            "pending handoff": ("handoff pendente", "pending handoff"),
        }
        for phrase_name, alternatives in phrase_groups.items():
            if not any(alternative in fallback for alternative in alternatives):
                errors.append(f"{label} constrained Refinar fallback misses {phrase_name}")


def validate_entry(
    entry: Any,
    pillar: str,
    meta: dict[str, str],
    source_map: dict[str, dict[str, Any]],
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(entry, dict):
        errors.append(f"{pillar} catalog entry is not an object")
        return
    tactic_schema = schema["$defs"]["tactic"]
    required = set(tactic_schema["required"])
    allowed = set(tactic_schema["properties"])
    tactic_id = str(entry.get("tactic_id"))
    label = tactic_id if tactic_id != "None" else f"{pillar} unknown tactic"
    if set(entry) != allowed or not required.issubset(entry):
        errors.append(f"{label} fields differ from tactic schema")
    path = entry.get("canonical_path")
    if not isinstance(path, str) or path not in source_map:
        errors.append(f"{label} references a non-canonical path: {path}")
        return
    expected_id = meta["id_prefix"] + Path(path).stem
    if tactic_id != expected_id:
        errors.append(f"{path} tactic_id must be {expected_id}")
    if entry.get("canonical_sha256") != source_map[path]["sha256"]:
        errors.append(f"{label} canonical hash differs from source")
    if entry.get("canonical_immutable") is not True:
        errors.append(f"{label} must be canonical_immutable")
    if entry.get("pillar") != pillar or entry.get("methodology_stage") != meta["stage"]:
        errors.append(f"{label} has wrong pillar or methodology stage")
    for field in ("display_name", "summary", "maturity_rationale"):
        if not nonempty(entry.get(field)):
            errors.append(f"{label} has empty {field}")
    aliases = entry.get("aliases")
    if not isinstance(aliases, list) or len(aliases) != len(set(aliases)) or not all(nonempty(item) for item in aliases):
        errors.append(f"{label} aliases must be unique non-empty strings")

    job_allowed = schema_values(schema, "jobTag")
    object_allowed = schema_values(schema, "objectTag")
    jobs = entry.get("job_tags")
    objects = entry.get("object_tags")
    if not isinstance(jobs, list) or not jobs or len(jobs) != len(set(jobs)) or not set(jobs).issubset(job_allowed):
        errors.append(f"{label} has invalid job_tags")
        jobs = []
    if not isinstance(objects, list) or not objects or len(objects) != len(set(objects)) or not set(objects).issubset(object_allowed):
        errors.append(f"{label} has invalid object_tags")
        objects = []
    need_tags = entry.get("need_tags")
    if not isinstance(need_tags, list) or not need_tags or len(need_tags) != len(set(need_tags)):
        errors.append(f"{label} has invalid need_tags")
    else:
        for need in need_tags:
            parts = str(need).split(":")
            if len(parts) != 2 or parts[0] not in jobs or parts[1] not in objects:
                errors.append(f"{label} need_tag is not backed by its tags: {need}")

    validate_input_requirements(entry.get("input_requirements"), label, schema, errors)
    output = entry.get("output_contract")
    output_schema = schema["$defs"]["outputContract"]
    if not isinstance(output, dict) or set(output) != set(output_schema["properties"]):
        errors.append(f"{label} output_contract fields differ from schema")
    else:
        if output.get("output_type") not in set(output_schema["properties"]["output_type"]["enum"]):
            errors.append(f"{label} has invalid output_type")
        sections = output.get("required_sections")
        if not isinstance(sections, list) or not sections or len(sections) != len(set(sections)) or not all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(item)) for item in sections):
            errors.append(f"{label} has invalid required_sections")
        if output.get("decision_owner") != meta["role"]:
            errors.append(f"{label} output owner must be {meta['role']}")
        if not nonempty(output.get("description")):
            errors.append(f"{label} has empty output description")

    validate_execution_policy(entry, meta, source_map[path], schema, label, errors)

    if entry.get("minimum_maturity") not in schema_values(schema, "maturity"):
        errors.append(f"{label} has invalid minimum_maturity")
    prerequisites = entry.get("prerequisites")
    if not isinstance(prerequisites, list):
        errors.append(f"{label} prerequisites must be a list")
    else:
        prereq_ids: set[str] = set()
        for item in prerequisites:
            if not isinstance(item, dict) or set(item) != {"prerequisite_id", "description", "required"}:
                errors.append(f"{label} has invalid prerequisite")
                continue
            prereq_id = item.get("prerequisite_id")
            if prereq_id in prereq_ids:
                errors.append(f"{label} repeats prerequisite {prereq_id}")
            prereq_ids.add(str(prereq_id))
            if not nonempty(prereq_id) or not nonempty(item.get("description")) or not isinstance(item.get("required"), bool):
                errors.append(f"{label} has malformed prerequisite {prereq_id}")
    for field in ("contraindications", "use_when", "do_not_use_when"):
        value = entry.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"{label} {field} must be non-empty")
    for item in entry.get("contraindications", []) if isinstance(entry.get("contraindications"), list) else []:
        if not isinstance(item, dict) or set(item) != {"condition", "reason", "fallback"} or not all(nonempty(item.get(field)) for field in ("condition", "reason", "fallback")):
            errors.append(f"{label} has malformed contraindication")
    if not all(nonempty(item) for field in ("use_when", "do_not_use_when") for item in (entry.get(field) if isinstance(entry.get(field), list) else [])):
        errors.append(f"{label} use/do-not-use entries must be non-empty")
    if entry.get("selection_confidence") not in schema_values(schema, "confidence"):
        errors.append(f"{label} has invalid selection_confidence")

    quality = entry.get("quality")
    quality_schema = schema["$defs"]["quality"]
    if not isinstance(quality, dict) or set(quality) != set(quality_schema["properties"]):
        errors.append(f"{label} quality fields differ from schema")
    else:
        status = quality.get("semantic_review_status")
        flags = quality.get("flags")
        flag_allowed = set(quality_schema["properties"]["flags"]["items"]["enum"])
        if status not in set(quality_schema["properties"]["semantic_review_status"]["enum"]):
            errors.append(f"{label} has invalid semantic review status")
        if quality.get("translation_risk") not in {"low", "medium", "high"}:
            errors.append(f"{label} has invalid translation risk")
        if not isinstance(flags, list) or not flags or len(flags) != len(set(flags)) or not set(flags).issubset(flag_allowed):
            errors.append(f"{label} has invalid quality flags")
        elif "none" in flags and len(flags) != 1:
            errors.append(f"{label} quality flag none cannot coexist")
        elif status == "reviewed_no_blocking_issue" and flags != ["none"]:
            errors.append(f"{label} no-issue status must use only the none flag")
        elif status != "reviewed_no_blocking_issue" and flags == ["none"]:
            errors.append(f"{label} flagged review status cannot use none")
        if not nonempty(quality.get("assessment_note")):
            errors.append(f"{label} has empty quality assessment note")

    provenance = entry.get("provenance")
    expected_provenance = {
        "baseline_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
        "collection_origin": "user_reported_hubspot_loop_marketing_prompt_library",
        "collection_reference": "https://www.hubspot.com/loop-marketing",
        "individual_source_verified": False,
        "redistribution_review": "not_reviewed",
    }
    if provenance != expected_provenance:
        errors.append(f"{label} provenance differs from the conservative P3 contract")
    review = entry.get("review_evidence")
    if not isinstance(review, dict) or set(review) != {"reviewed_full_source", "source_line_count", "review_notes"}:
        errors.append(f"{label} review_evidence fields differ from schema")
    else:
        if review.get("reviewed_full_source") is not True:
            errors.append(f"{label} was not reviewed in full")
        if review.get("source_line_count") != source_map[path]["line_count"]:
            errors.append(f"{label} source line count differs from canonical file")
        if not nonempty(review.get("review_notes")):
            errors.append(f"{label} has empty review notes")
    sensitivities = {
        item.get("sensitivity")
        for item in entry.get("input_requirements", [])
        if isinstance(item, dict)
    }
    if "customer_level_pii" in sensitivities and isinstance(quality, dict) and "pii_sensitive" not in quality.get("flags", []):
        errors.append(f"{label} consumes customer-level PII without pii_sensitive flag")
    validate_authority_fixtures(entry, label, errors)


def validate_relations(
    relations: Any,
    valid_ids: set[str],
    label: str,
    schema: dict[str, Any],
    errors: list[str],
    within_ids: set[str] | None = None,
) -> None:
    if not isinstance(relations, list):
        errors.append(f"{label} relations must be a list")
        return
    relation_schema = schema["$defs"]["relation"]
    required = set(relation_schema["required"])
    allowed = set(relation_schema["properties"])
    types = set(relation_schema["properties"]["relation_type"]["enum"])
    effects = set(relation_schema["properties"]["routing_effect"]["enum"])
    ids: set[str] = set()
    semantic_keys: set[tuple[str, str, str]] = set()
    for index, item in enumerate(relations, 1):
        if not isinstance(item, dict):
            errors.append(f"{label} relation {index} is not an object")
            continue
        if set(item) != allowed or not required.issubset(item):
            errors.append(f"{label} relation {index} fields differ from schema")
        relation_id = item.get("relation_id")
        if not isinstance(relation_id, str) or not re.fullmatch(r"rel-[a-z0-9][a-z0-9-]*", relation_id):
            errors.append(f"{label} relation {index} has invalid relation_id")
        if relation_id in ids:
            errors.append(f"{label} repeats relation_id {relation_id}")
        ids.add(str(relation_id))
        relation_type = item.get("relation_type")
        source = item.get("from_tactic_id")
        target = item.get("to_tactic_id")
        if relation_type not in types or item.get("routing_effect") not in effects:
            errors.append(f"{label} relation {relation_id} has invalid type/effect")
        if source not in valid_ids or target not in valid_ids or source == target:
            errors.append(f"{label} relation {relation_id} has invalid target or self-link")
        if within_ids is not None and (source not in within_ids or target not in within_ids):
            errors.append(f"{label} relation {relation_id} must remain within assigned pillar")
        directional = item.get("directional")
        if relation_type == "depends_on":
            if directional is not True or item.get("routing_effect") != "require_order":
                errors.append(f"{label} dependency {relation_id} must be directional require_order")
            semantic_key = (str(relation_type), str(source), str(target))
        else:
            if directional is not False:
                errors.append(f"{label} symmetric relation {relation_id} must set directional=false")
            if isinstance(source, str) and isinstance(target, str) and source >= target:
                errors.append(f"{label} symmetric relation {relation_id} must use lexical endpoint order")
            semantic_key = (str(relation_type), *sorted((str(source), str(target))))
        if semantic_key in semantic_keys:
            errors.append(f"{label} duplicates semantic relation {semantic_key}")
        semantic_keys.add(semantic_key)
        if not nonempty(item.get("rationale")):
            errors.append(f"{label} relation {relation_id} has empty rationale")
        if item.get("confidence") not in {"low", "medium", "high"}:
            errors.append(f"{label} relation {relation_id} has invalid confidence")
        if item.get("review_status") not in {"proposed", "confirmed"}:
            errors.append(f"{label} relation {relation_id} has invalid review status")


def validate_workstreams(
    schema: dict[str, Any], source_map: dict[str, dict[str, Any]], errors: list[str],
    selected_pillar: str | None = None,
) -> None:
    all_source_ids = {
        "lm." + path.split("/")[1].lower() + "." + Path(path).stem
        for path in source_map
    }
    observed_paths: set[str] = set()
    observed_ids: set[str] = set()
    expected_baseline = {
        "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
        "canonical_prompt_count": 100,
        "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1",
    }
    for pillar, meta in PILLARS.items():
        if selected_pillar is not None and pillar != selected_pillar:
            continue
        path = WORKSTREAMS / meta["file"]
        value = load(path)
        top_fields = {
            "workstream", "status", "pillar", "methodology_stage", "baseline",
            "entries", "relations", "cross_pillar_relation_candidates",
            "review_summary", "unresolved_questions",
        }
        require_fields(value, top_fields, f"{pillar} workstream", errors)
        if set(value) != top_fields:
            errors.append(f"{pillar} workstream top-level fields differ from contract")
        if value.get("workstream") != f"pillar_catalog_{pillar.lower()}":
            errors.append(f"{pillar} workstream has invalid workstream name")
        if value.get("status") != "completed":
            errors.append(f"{pillar} workstream is not completed")
        if value.get("baseline") != expected_baseline:
            errors.append(f"{pillar} workstream baseline differs from source contract")
        if value.get("pillar") != pillar or value.get("methodology_stage") != meta["stage"]:
            errors.append(f"{pillar} workstream identity is invalid")
        entries = value.get("entries")
        if not isinstance(entries, list):
            errors.append(f"{pillar} workstream must contain exactly 25 entries")
            continue
        if len(entries) != 25:
            errors.append(f"{pillar} workstream must contain exactly 25 entries")
        pillar_paths: set[str] = set()
        pillar_ids: set[str] = set()
        for entry in entries:
            validate_entry(entry, pillar, meta, source_map, schema, errors)
            if isinstance(entry, dict):
                tactic_path = entry.get("canonical_path")
                tactic_id = entry.get("tactic_id")
                if tactic_path in pillar_paths or tactic_path in observed_paths:
                    errors.append(f"catalog workstreams repeat path {tactic_path}")
                if tactic_id in pillar_ids or tactic_id in observed_ids:
                    errors.append(f"catalog workstreams repeat tactic_id {tactic_id}")
                pillar_paths.add(str(tactic_path))
                pillar_ids.add(str(tactic_id))
                observed_paths.add(str(tactic_path))
                observed_ids.add(str(tactic_id))
        validate_relations(
            value.get("relations"), all_source_ids, f"{pillar} workstream",
            schema, errors, within_ids=pillar_ids,
        )
        if isinstance(value.get("relations"), list):
            for relation in value["relations"]:
                if isinstance(relation, dict) and relation.get("review_status") != "proposed":
                    errors.append(
                        f"{pillar} workstream relation {relation.get('relation_id')} "
                        "must remain proposed until independent replay"
                    )
        candidates = value.get("cross_pillar_relation_candidates")
        if not isinstance(candidates, list):
            errors.append(f"{pillar} cross-pillar candidates must be a list")
        else:
            candidate_ids: set[str] = set()
            allowed_candidate_fields = {
                "candidate_id", "from_tactic_id", "from_tactic_ids",
                "candidate_relation_type", "target_pillar", "target_tactic_id",
                "target_tactic_ids", "target_capability", "rationale", "boundary",
                "review_status",
            }
            relation_types = set(
                schema["$defs"]["relation"]["properties"]["relation_type"]["enum"]
            )
            for index, candidate in enumerate(candidates, 1):
                candidate_label = f"{pillar} cross-pillar candidate {index}"
                if not isinstance(candidate, dict):
                    errors.append(f"{candidate_label} is not an object")
                    continue
                if not set(candidate).issubset(allowed_candidate_fields):
                    errors.append(f"{candidate_label} has unsupported fields")
                candidate_id = candidate.get("candidate_id")
                if not isinstance(candidate_id, str) or not re.fullmatch(
                    r"xrel-[a-z0-9][a-z0-9-]*", candidate_id
                ):
                    errors.append(f"{candidate_label} has invalid candidate_id")
                if candidate_id in candidate_ids:
                    errors.append(f"{pillar} repeats cross-pillar candidate {candidate_id}")
                candidate_ids.add(str(candidate_id))
                single_source = candidate.get("from_tactic_id")
                multiple_sources = candidate.get("from_tactic_ids")
                if (single_source is None) == (multiple_sources is None):
                    errors.append(f"{candidate_label} must define one source form")
                    source_ids: list[Any] = []
                elif single_source is not None:
                    source_ids = [single_source]
                else:
                    source_ids = multiple_sources if isinstance(multiple_sources, list) else []
                    if not source_ids or len(source_ids) != len(set(source_ids)):
                        errors.append(f"{candidate_label} has invalid from_tactic_ids")
                if any(source_id not in pillar_ids for source_id in source_ids):
                    errors.append(f"{candidate_label} source is outside assigned pillar")
                target_pillar = candidate.get("target_pillar")
                if target_pillar not in PILLARS or target_pillar == pillar:
                    errors.append(f"{candidate_label} has invalid target_pillar")
                target_forms = [
                    candidate.get("target_tactic_id") is not None,
                    candidate.get("target_tactic_ids") is not None,
                    candidate.get("target_capability") is not None,
                ]
                if sum(target_forms) != 1:
                    errors.append(f"{candidate_label} must define one target form")
                target_ids: list[Any] = []
                if candidate.get("target_tactic_id") is not None:
                    target_ids = [candidate.get("target_tactic_id")]
                elif candidate.get("target_tactic_ids") is not None:
                    raw_target_ids = candidate.get("target_tactic_ids")
                    target_ids = raw_target_ids if isinstance(raw_target_ids, list) else []
                    if not target_ids or len(target_ids) != len(set(target_ids)):
                        errors.append(f"{candidate_label} has invalid target_tactic_ids")
                elif not nonempty(candidate.get("target_capability")):
                    errors.append(f"{candidate_label} has invalid target_capability")
                target_prefix = (
                    PILLARS.get(str(target_pillar), {}).get("id_prefix")
                    if target_pillar in PILLARS else None
                )
                if any(
                    target_id not in all_source_ids
                    or not str(target_id).startswith(str(target_prefix))
                    for target_id in target_ids
                ):
                    errors.append(f"{candidate_label} has invalid target tactic")
                if candidate.get("candidate_relation_type") not in relation_types:
                    errors.append(f"{candidate_label} has invalid relation type")
                if not nonempty(candidate.get("rationale")) or not nonempty(candidate.get("boundary")):
                    errors.append(f"{candidate_label} has empty rationale or boundary")
                if candidate.get("review_status") != "needs_cross_pillar_review":
                    errors.append(f"{candidate_label} has invalid review_status")
        if not isinstance(value.get("review_summary"), dict) or not value.get("review_summary"):
            errors.append(f"{pillar} review_summary must be a non-empty object")
        unresolved = value.get("unresolved_questions")
        if not isinstance(unresolved, list):
            errors.append(f"{pillar} unresolved_questions must be a list")
        else:
            question_ids: set[str] = set()
            for index, question in enumerate(unresolved, 1):
                if not isinstance(question, dict) or set(question) != {
                    "id", "question", "blocking", "owner", "safe_default"
                }:
                    errors.append(f"{pillar} unresolved question {index} is malformed")
                    continue
                question_id = question.get("id")
                if not nonempty(question_id) or question_id in question_ids:
                    errors.append(f"{pillar} unresolved question {index} has invalid id")
                question_ids.add(str(question_id))
                if not isinstance(question.get("blocking"), bool) or not all(
                    nonempty(question.get(field))
                    for field in ("question", "owner", "safe_default")
                ):
                    errors.append(f"{pillar} unresolved question {question_id} is invalid")
        expected_pillar_paths = {
            source_path
            for source_path in source_map
            if source_path.startswith(f"biblioteca/{pillar}/")
        }
        if pillar_paths != expected_pillar_paths:
            missing = sorted(expected_pillar_paths - pillar_paths)
            extra = sorted(pillar_paths - expected_pillar_paths)
            errors.append(
                f"{pillar} coverage mismatch missing={missing} extra={extra}"
            )
    if selected_pillar is None and observed_paths != set(source_map):
        missing = sorted(set(source_map) - observed_paths)
        extra = sorted(observed_paths - set(source_map))
        errors.append(f"workstream catalog coverage mismatch missing={missing} extra={extra}")
    if selected_pillar is None and observed_ids != all_source_ids:
        errors.append("workstream tactic IDs differ from deterministic source IDs")


def canonical_relation_id(relation: dict[str, Any]) -> str:
    semantic_key = "|".join(
        str(relation.get(field))
        for field in ("relation_type", "from_tactic_id", "to_tactic_id")
    )
    digest = hashlib.sha256(semantic_key.encode("utf-8")).hexdigest()[:12]
    relation_type = str(relation.get("relation_type", "unknown")).replace("_", "-")
    return f"rel-{relation_type}-{digest}"


def validate_relation_review(
    schema: dict[str, Any], source_map: dict[str, dict[str, Any]], errors: list[str]
) -> None:
    review_path = WORKSTREAMS / "relation-review.json"
    review = load(review_path)
    top_fields = {
        "workstream", "status", "baseline", "input_summary", "relations",
        "decisions", "review_summary", "unresolved_questions",
    }
    if set(review) != top_fields:
        errors.append("relation review top-level fields differ from contract")
    if review.get("workstream") != "p3_relation_review" or review.get("status") != "completed":
        errors.append("relation review identity or status is invalid")
    expected_baseline = {
        "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
        "canonical_prompt_count": 100,
        "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1",
    }
    if review.get("baseline") != expected_baseline:
        errors.append("relation review baseline differs from source contract")

    all_ids = {
        "lm." + path.split("/")[1].lower() + "." + Path(path).stem
        for path in source_map
    }
    expected_inputs: dict[str, dict[str, str]] = {}
    intra_count = 0
    cross_count = 0
    for pillar, meta in PILLARS.items():
        workstream = load(WORKSTREAMS / meta["file"])
        for relation in workstream.get("relations", []):
            if not isinstance(relation, dict):
                continue
            input_ref = f"intra:{pillar}:{relation.get('relation_id')}"
            if input_ref in expected_inputs:
                errors.append(f"relation review input ref collides: {input_ref}")
            expected_inputs[input_ref] = {"kind": "intrapillar_relation", "pillar": pillar}
            intra_count += 1
        for candidate in workstream.get("cross_pillar_relation_candidates", []):
            if not isinstance(candidate, dict):
                continue
            input_ref = f"cross:{pillar}:{candidate.get('candidate_id')}"
            if input_ref in expected_inputs:
                errors.append(f"relation review input ref collides: {input_ref}")
            expected_inputs[input_ref] = {"kind": "cross_pillar_candidate", "pillar": pillar}
            cross_count += 1
    expected_summary = {
        "pillar_workstreams": 4,
        "catalog_entries": 100,
        "intrapillar_relations_reviewed": intra_count,
        "cross_pillar_candidates_reviewed": cross_count,
        "total_inputs_replayed": intra_count + cross_count,
    }
    if review.get("input_summary") != expected_summary:
        errors.append("relation review input summary does not prove full replay")

    relations = review.get("relations")
    validate_relations(relations, all_ids, "relation review", schema, errors)
    relation_map = {
        relation.get("relation_id"): relation
        for relation in relations if isinstance(relation, dict)
    } if isinstance(relations, list) else {}
    if isinstance(relations, list) and [
        item.get("relation_id") for item in relations if isinstance(item, dict)
    ] != sorted(relation_map):
        errors.append("relation review relations must be sorted by canonical relation_id")
    for relation_id, relation in relation_map.items():
        if relation_id != canonical_relation_id(relation):
            errors.append(f"relation review has non-deterministic relation_id {relation_id}")

    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        errors.append("relation review decisions must be a list")
        decisions = []
    observed_inputs: set[str] = set()
    referenced_relations: set[str] = set()
    decision_fields = {
        "input_ref", "input_kind", "source_pillar", "decision",
        "output_relation_ids", "rationale", "evidence_refs",
        "owner_boundary_check", "cardinality_check",
    }
    for index, decision in enumerate(decisions, 1):
        label = f"relation review decision {index}"
        if not isinstance(decision, dict) or set(decision) != decision_fields:
            errors.append(f"{label} fields differ from contract")
            continue
        input_ref = decision.get("input_ref")
        expected = expected_inputs.get(str(input_ref))
        if expected is None:
            errors.append(f"{label} references an unknown input {input_ref}")
            continue
        if input_ref in observed_inputs:
            errors.append(f"relation review repeats input {input_ref}")
        observed_inputs.add(str(input_ref))
        if decision.get("input_kind") != expected["kind"] or decision.get("source_pillar") != expected["pillar"]:
            errors.append(f"{label} input identity differs from workstream")
        outcome = decision.get("decision")
        if outcome not in {"confirm", "retain_proposed", "reject"}:
            errors.append(f"{label} has invalid decision")
        output_ids = decision.get("output_relation_ids")
        if not isinstance(output_ids, list) or len(output_ids) != len(set(output_ids)):
            errors.append(f"{label} has invalid output_relation_ids")
            output_ids = []
        if outcome == "reject" and output_ids:
            errors.append(f"{label} rejects input but emits relations")
        if outcome != "reject" and not output_ids:
            errors.append(f"{label} accepts input without a relation")
        for relation_id in output_ids:
            relation = relation_map.get(relation_id)
            if relation is None:
                errors.append(f"{label} references unknown output relation {relation_id}")
                continue
            expected_status = "confirmed" if outcome == "confirm" else "proposed"
            if relation.get("review_status") != expected_status:
                errors.append(f"{label} outcome differs from output relation status")
            referenced_relations.add(str(relation_id))
        evidence_refs = decision.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs or not all(nonempty(item) for item in evidence_refs):
            errors.append(f"{label} must cite non-empty evidence_refs")
        if not nonempty(decision.get("rationale")):
            errors.append(f"{label} has empty rationale")
        if decision.get("owner_boundary_check") not in {"pass", "fail"}:
            errors.append(f"{label} has invalid owner boundary check")
        if decision.get("cardinality_check") not in {"pass", "fail"}:
            errors.append(f"{label} has invalid cardinality check")
        if outcome != "reject" and (
            decision.get("owner_boundary_check") != "pass"
            or decision.get("cardinality_check") != "pass"
        ):
            errors.append(f"{label} accepts a relation that failed a safety check")
    if observed_inputs != set(expected_inputs):
        missing = sorted(set(expected_inputs) - observed_inputs)
        extra = sorted(observed_inputs - set(expected_inputs))
        errors.append(f"relation review replay mismatch missing={missing} extra={extra}")
    if referenced_relations != set(relation_map):
        errors.append("relation review contains orphan or unreferenced relations")

    summary = review.get("review_summary")
    if not isinstance(summary, dict) or summary.get("verdict") != "PASS":
        errors.append("relation review verdict is not PASS")
    elif summary.get("blocking_findings") != 0:
        errors.append("relation review still has blocking findings")
    unresolved = review.get("unresolved_questions")
    if not isinstance(unresolved, list):
        errors.append("relation review unresolved_questions must be a list")


def validate_finals(
    schema: dict[str, Any], source_map: dict[str, dict[str, Any]], aggregate: str,
    errors: list[str],
) -> None:
    catalog = load(P3 / "tactic-catalog.json")
    require_fields(
        catalog,
        {"artifact_type", "schema_version", "product_version", "catalog_version", "status", "baseline", "tactics"},
        "tactic-catalog.json",
        errors,
    )
    if catalog.get("artifact_type") != "tactic_catalog" or catalog.get("status") != "integrated":
        errors.append("official tactic catalog has invalid type or status")
    expected_catalog_fields = set(schema["$defs"]["tacticCatalog"]["properties"])
    if set(catalog) != expected_catalog_fields:
        errors.append("official tactic catalog top-level fields differ from schema")
    if (
        catalog.get("schema_version") != "1.0"
        or catalog.get("product_version") != "2.0.0"
        or catalog.get("catalog_version") != "1.0.0"
    ):
        errors.append("official tactic catalog version constants are invalid")
    tactics = catalog.get("tactics")
    if not isinstance(tactics, list) or len(tactics) != 100:
        errors.append("official tactic catalog must contain exactly 100 entries")
        tactics = []
    observed_paths: set[str] = set()
    observed_ids: set[str] = set()
    for entry in tactics:
        if not isinstance(entry, dict):
            errors.append("official catalog contains a non-object entry")
            continue
        pillar = entry.get("pillar")
        meta = PILLARS.get(str(pillar))
        if meta is None:
            errors.append(f"official entry has invalid pillar {pillar}")
            continue
        validate_entry(entry, str(pillar), meta, source_map, schema, errors)
        path = str(entry.get("canonical_path"))
        tactic_id = str(entry.get("tactic_id"))
        if path in observed_paths or tactic_id in observed_ids:
            errors.append(f"official catalog duplicates {path} or {tactic_id}")
        observed_paths.add(path)
        observed_ids.add(tactic_id)
    if observed_paths != set(source_map):
        errors.append("official catalog paths differ from canonical source set")
    if [item.get("canonical_path") for item in tactics if isinstance(item, dict)] != sorted(observed_paths):
        errors.append("official catalog must be sorted by canonical_path")
    baseline = catalog.get("baseline", {})
    if baseline != {
        "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
        "canonical_prompt_count": 100,
        "aggregate_sha256": aggregate,
    }:
        errors.append("official catalog baseline differs from source replay")

    relationship_map = load(P3 / "relationship-map.json")
    if relationship_map.get("artifact_type") != "relationship_map" or relationship_map.get("status") != "integrated":
        errors.append("official relationship map has invalid type or status")
    expected_relationship_fields = set(
        schema["$defs"]["relationshipMap"]["properties"]
    )
    if set(relationship_map) != expected_relationship_fields:
        errors.append("official relationship map top-level fields differ from schema")
    if relationship_map.get("schema_version") != "1.0" or relationship_map.get("product_version") != "2.0.0":
        errors.append("official relationship map version constants are invalid")
    expected_routing_policy = {
        "normative_review_status": "confirmed",
        "proposed_relation_effect": "audit_only",
        "dependency_failure": "reject_route_node",
        "collision_effect": "block_automatic_co_selection",
        "cardinality_guard": "relations_do_not_override_zero_one_or_two_tactics_per_route_node",
    }
    if relationship_map.get("routing_policy") != expected_routing_policy:
        errors.append("official relationship map has invalid routing policy")
    relation_values = relationship_map.get("relations")
    relation_values = relation_values if isinstance(relation_values, list) else []
    relation_status_counts = Counter(
        item.get("review_status") for item in relation_values if isinstance(item, dict)
    )
    relation_review = relationship_map.get("review_evidence")
    if not isinstance(relation_review, dict):
        errors.append("official relationship map misses review evidence")
    else:
        expected_review_constants = {
            "reviewer": "independent_relation_reviewer",
            "review_artifact": "artifacts/P3/workstreams/relation-review.json",
            "all_candidates_replayed": True,
            "evidence_basis": [
                "canonical_prompt_bodies",
                "p2_role_authority",
                "p2_routing_contract",
                "p3_tactic_metadata",
            ],
        }
        for field, expected in expected_review_constants.items():
            if relation_review.get(field) != expected:
                errors.append(f"official relationship review has invalid {field}")
        if relation_review.get("confirmed_relation_count") != relation_status_counts.get("confirmed", 0):
            errors.append("confirmed relation count differs from relationship map")
        if relation_review.get("proposed_relation_count") != relation_status_counts.get("proposed", 0):
            errors.append("proposed relation count differs from relationship map")
        if not isinstance(relation_review.get("rejected_candidate_count"), int) or relation_review.get("rejected_candidate_count") < 0:
            errors.append("relationship review has invalid rejected candidate count")
    validate_relations(
        relationship_map.get("relations"), observed_ids, "relationship-map.json",
        schema, errors,
    )

    report = load(P3 / "preservation-report.json")
    require_fields(
        report,
        {
            "schema_version", "phase", "status", "baseline", "catalog_coverage",
            "metadata_coverage", "relationship_summary", "quality_summary",
            "provenance_summary", "source_integrity", "validation",
        },
        "preservation-report.json",
        errors,
    )
    if report.get("status") != "proven" or report.get("catalog_coverage", {}).get("entries") != 100:
        errors.append("preservation report does not prove 100-entry coverage")
    if report.get("source_integrity", {}).get("aggregate_sha256") != aggregate:
        errors.append("preservation report aggregate differs from source")
    if report.get("source_integrity", {}).get("worktree_clean") is not True:
        errors.append("preservation report does not prove a clean source")
    pillar_counts = Counter(item.get("pillar") for item in tactics if isinstance(item, dict))
    if dict(pillar_counts) != {pillar: 25 for pillar in PILLARS}:
        errors.append(f"official catalog pillar distribution is invalid: {dict(pillar_counts)}")
    coverage = report.get("catalog_coverage", {})
    if coverage.get("unique_paths") != 100 or coverage.get("unique_tactic_ids") != 100:
        errors.append("preservation report does not prove unique catalog coverage")
    if coverage.get("by_pillar") != dict(sorted(pillar_counts.items())):
        errors.append("preservation report pillar counts differ from official catalog")
    metadata = report.get("metadata_coverage", {})
    for field in (
        "entries_with_all_required_fields", "entries_reviewed_full_source",
        "entries_with_input_requirements", "entries_with_output_contract",
        "entries_with_execution_policy",
        "entries_with_maturity_rationale", "entries_with_contraindications",
    ):
        if metadata.get(field) != 100:
            errors.append(f"preservation report metadata coverage is incomplete for {field}")
    expected_maturity = dict(sorted(Counter(
        item.get("minimum_maturity") for item in tactics if isinstance(item, dict)
    ).items()))
    if metadata.get("minimum_maturity_distribution") != expected_maturity:
        errors.append("preservation report maturity distribution differs from catalog")
    expected_execution_modes = dict(sorted(Counter(
        item.get("execution_policy", {}).get("execution_mode")
        for item in tactics if isinstance(item, dict)
    ).items()))
    if metadata.get("execution_mode_distribution") != expected_execution_modes:
        errors.append("preservation report execution mode distribution differs from catalog")
    expected_automatic_selection = dict(sorted(Counter(
        item.get("execution_policy", {}).get("automatic_selection")
        for item in tactics if isinstance(item, dict)
    ).items()))
    if metadata.get("automatic_selection_distribution") != expected_automatic_selection:
        errors.append("preservation report automatic selection distribution differs from catalog")
    expected_conflicts = sum(
        len(item.get("execution_policy", {}).get("canonical_scope_conflicts", []))
        for item in tactics if isinstance(item, dict)
    )
    expected_handoffs = sum(
        len(item.get("execution_policy", {}).get("mandatory_handoffs", []))
        for item in tactics if isinstance(item, dict)
    )
    if metadata.get("canonical_scope_conflict_count") != expected_conflicts:
        errors.append("preservation report scope conflict count differs from catalog")
    if metadata.get("mandatory_handoff_count") != expected_handoffs:
        errors.append("preservation report mandatory handoff count differs from catalog")
    relationship_summary = report.get("relationship_summary", {})
    if relationship_summary.get("total_relations") != len(relation_values):
        errors.append("preservation report relation count differs from relationship map")
    if relationship_summary.get("runtime_uses_only_confirmed") is not True:
        errors.append("preservation report does not preserve confirmed-only runtime policy")
    if relationship_summary.get("replayed_inputs") != len(load(WORKSTREAMS / "relation-review.json").get("decisions", [])):
        errors.append("preservation report replay count differs from relation review")
    quality_summary = report.get("quality_summary", {})
    expected_quality_status = dict(sorted(Counter(
        item.get("quality", {}).get("semantic_review_status")
        for item in tactics if isinstance(item, dict)
    ).items()))
    if quality_summary.get("semantic_review_status") != expected_quality_status:
        errors.append("preservation report quality distribution differs from catalog")
    if quality_summary.get("flags_are_review_metadata_not_source_rewrites") is not True:
        errors.append("preservation report does not constrain quality flags to metadata")
    provenance_summary = report.get("provenance_summary", {})
    if (
        provenance_summary.get("entries_with_conservative_provenance") != 100
        or provenance_summary.get("individual_source_verified") is not False
        or provenance_summary.get("redistribution_review") != "not_reviewed"
        or provenance_summary.get("redistribution_authorized_by_p3") is not False
    ):
        errors.append("preservation report overstates provenance or redistribution authority")
    integrity = report.get("source_integrity", {})
    if (
        integrity.get("head") != baseline.get("source_commit")
        or integrity.get("tracked_file_count") != 117
        or integrity.get("canonical_prompt_count") != 100
        or integrity.get("canonical_files_modified_by_p3") != 0
    ):
        errors.append("preservation report source integrity fields are invalid")
    validation = report.get("validation", {})
    for field in ("schema", "workstreams", "relation_review", "integration_invariants"):
        if validation.get(field) != "passed":
            errors.append(f"preservation report validation status is not passed for {field}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=("schema", "workstream", "workstreams", "relations", "final"),
    )
    parser.add_argument("--pillar", choices=tuple(PILLARS))
    args = parser.parse_args()
    errors: list[str] = []
    try:
        schema = load(SCHEMA_PATH)
        validate_schema(schema, errors)
        _, source_map, aggregate = validate_source(errors)
        if args.stage == "workstream":
            if args.pillar is None:
                errors.append("--pillar is required for the workstream stage")
            else:
                validate_workstreams(schema, source_map, errors, selected_pillar=args.pillar)
        if args.stage in {"workstreams", "final"}:
            validate_workstreams(schema, source_map, errors)
        if args.stage in {"relations", "final"}:
            validate_relation_review(schema, source_map, errors)
        if args.stage == "final":
            validate_finals(schema, source_map, aggregate, errors)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        errors.append(str(exc))
    print(
        json.dumps(
            {"status": "valid" if not errors else "invalid", "stage": args.stage, "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
