#!/usr/bin/env python3
"""Validate P2 workstreams, official contracts and the immutable source baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
P2 = ROOT / "artifacts" / "P2"
WORKSTREAMS = P2 / "workstreams"
PROJECT_PATH = ROOT / "PROJECT.json"
SOURCE_INDEX_PATH = ROOT / "SOURCE_INDEX.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from dicts(item)


def require_fields(
    value: dict[str, Any], fields: set[str], label: str, errors: list[str]
) -> None:
    missing = sorted(fields - value.keys())
    if missing:
        errors.append(f"{label} misses fields: {missing}")


def validate_source(errors: list[str]) -> tuple[Path, dict[str, Any]]:
    project = load(PROJECT_PATH)
    index = load(SOURCE_INDEX_PATH)
    repo = Path(project["source"]["repo"])
    if run_git(repo, "rev-parse", "HEAD") != project["source"]["baseline_commit"]:
        errors.append("source HEAD differs from the read-only baseline")
    if run_git(repo, "status", "--porcelain"):
        errors.append("source worktree changed during P2")
    tracked = run_git(repo, "ls-files").splitlines()
    if len(tracked) != project["source"]["file_count_at_baseline"]:
        errors.append("source tracked-file count differs from baseline")

    prompts = index.get("canonical_prompts", [])
    if not isinstance(prompts, list) or len(prompts) != 100:
        errors.append("SOURCE_INDEX must contain exactly 100 prompts")
        return repo, index
    observed_records: list[str] = []
    seen: set[str] = set()
    for item in prompts:
        path = str(item.get("path"))
        expected = item.get("sha256")
        candidate = repo / path
        if path in seen:
            errors.append(f"duplicate canonical prompt path: {path}")
        seen.add(path)
        if not candidate.is_file():
            errors.append(f"missing canonical prompt: {path}")
            continue
        actual = sha256(candidate)
        if actual != expected:
            errors.append(f"canonical prompt hash changed: {path}")
        observed_records.append(f"{path}\0{actual}")
    aggregate = hashlib.sha256(
        "\n".join(sorted(observed_records)).encode("utf-8")
    ).hexdigest()
    expected_aggregate = project["source"]["baseline_library_aggregate_sha256"]
    if aggregate != expected_aggregate:
        errors.append("canonical prompt aggregate differs from baseline")
    if index.get("canonical_library_aggregate_sha256") != expected_aggregate:
        errors.append("SOURCE_INDEX aggregate differs from PROJECT baseline")
    return repo, index


def validate_evidence(value: Any, label: str, repo: Path, errors: list[str]) -> None:
    for item in dicts(value):
        if "line_start" not in item:
            continue
        path = item.get("path")
        line_start = item.get("line_start")
        line_end = item.get("line_end", line_start)
        if not isinstance(path, str) or not path:
            errors.append(f"{label} has line evidence without a path")
            continue
        control_candidate = ROOT / path
        candidate = control_candidate if control_candidate.is_file() else repo / path
        if not candidate.is_file():
            errors.append(f"{label} references missing source path {path}")
            continue
        line_count = len(candidate.read_bytes().splitlines())
        if (
            not isinstance(line_start, int)
            or not isinstance(line_end, int)
            or line_start < 1
            or line_end < line_start
            or line_end > line_count
        ):
            errors.append(f"{label} has invalid source range {path}:{line_start}-{line_end}")


def p1_ids() -> tuple[set[str], set[str]]:
    risk_ids = {
        item["id"] for item in load(ROOT / "artifacts/P1/risk-register.json")["risks"]
    }
    finding_ids: set[str] = set()
    for name in ("architecture", "library", "security-runtime"):
        value = load(ROOT / f"artifacts/P1/workstreams/{name}.json")
        finding_ids.update(item["id"] for item in value["findings"])
    return risk_ids, finding_ids


def validate_refs(value: Any, label: str, errors: list[str]) -> None:
    known_risks, known_findings = p1_ids()
    all_strings = set(strings(value))
    observed_risks = {
        token
        for text in all_strings
        for token in re.findall(r"P1-R\d{3}", text)
    }
    observed_findings = {
        token
        for text in all_strings
        for token in re.findall(r"(?:ARCH|LIB-F|SR)-\d{3}", text)
    }
    unknown_risks = sorted(observed_risks - known_risks)
    unknown_findings = sorted(observed_findings - known_findings)
    if unknown_risks:
        errors.append(f"{label} references unknown P1 risks: {unknown_risks}")
    if unknown_findings:
        errors.append(f"{label} references unknown P1 findings: {unknown_findings}")


def validate_workstreams(repo: Path, index: dict[str, Any], errors: list[str]) -> None:
    role = load(WORKSTREAMS / "role-authority.json")
    require_fields(
        role,
        {
            "workstream", "status", "canonical_authority_map", "roles",
            "mandatory_handoff_contract", "internal_consistency_checks",
            "authority_resolutions", "library_preservation",
        },
        "role-authority workstream",
        errors,
    )
    if {item.get("canonical_role_id") for item in role.get("roles", [])} != {
        "loop_planning", "verbalizar", "orientar", "ampliar", "refinar"
    }:
        errors.append("role workstream must define the five canonical roles")
    if any(item.get("result") != "pass" for item in role.get("internal_consistency_checks", [])):
        errors.append("role workstream has a failed consistency check")

    routing = load(WORKSTREAMS / "routing-rules.json")
    require_fields(
        routing,
        {
            "artifact_id", "status", "canonical_enums", "input_contract",
            "normalized_diagnosis_contract", "decision_rules", "rejection_codes",
            "invariants", "examples", "hypotheses", "traceability",
        },
        "routing workstream",
        errors,
    )
    codes = [item.get("code") for item in routing.get("rejection_codes", [])]
    if len(codes) < 30 or len(codes) != len(set(codes)):
        errors.append("routing workstream must define at least 30 unique rejection codes")
    referenced_codes = {
        token
        for text in strings(routing)
        for token in re.findall(r"ERR_[A-Z0-9_]+", text)
    }
    if referenced_codes - set(codes):
        errors.append(f"routing references undefined errors: {sorted(referenced_codes - set(codes))}")
    rule_ids = {
        str(item["id"])
        for item in dicts(routing.get("decision_rules"))
        if isinstance(item.get("id"), str)
    }
    referenced_rules = {
        token
        for text in strings(routing.get("examples"))
        for token in re.findall(r"RTE-[A-Z]+-\d{3}", text)
    }
    if referenced_rules - rule_ids:
        errors.append(f"routing examples reference undefined rules: {sorted(referenced_rules - rule_ids)}")

    compatibility = load(WORKSTREAMS / "compatibility.json")
    require_fields(
        compatibility,
        {
            "canonical_identity", "host_neutral_state_namespace",
            "command_compatibility", "discovery_and_migration",
            "compatibility_matrix", "invariants", "acceptance_scenarios",
            "canonical_prompt_preservation", "unresolved_questions",
        },
        "compatibility workstream",
        errors,
    )
    preservation = compatibility.get("canonical_prompt_preservation", {})
    expected_prompts = {
        item["path"]: item["sha256"] for item in index["canonical_prompts"]
    }
    observed_prompts = {
        item.get("path"): item.get("sha256") for item in preservation.get("entries", [])
    }
    if observed_prompts != expected_prompts:
        errors.append("compatibility prompt manifest differs from SOURCE_INDEX")
    if preservation.get("aggregate_sha256") != index.get("canonical_library_aggregate_sha256"):
        errors.append("compatibility aggregate hash differs from SOURCE_INDEX")
    if len(compatibility.get("compatibility_matrix", [])) < 12:
        errors.append("compatibility matrix has insufficient scenario coverage")
    if len(compatibility.get("acceptance_scenarios", [])) < 18:
        errors.append("compatibility workstream has insufficient acceptance scenarios")

    for label, value in (
        ("role-authority", role),
        ("routing", routing),
        ("compatibility", compatibility),
    ):
        validate_evidence(value, label, repo, errors)
        validate_refs(value, label, errors)


def validate_markdown(path: Path, headings: list[str], label: str, errors: list[str]) -> str:
    text = path.read_text(encoding="utf-8")
    for heading in headings:
        if heading not in text:
            errors.append(f"{label} misses heading: {heading}")
    return text


def validate_finals(errors: list[str]) -> None:
    role = load(P2 / "role-matrix.json")
    routing = load(P2 / "routing-contract.json")
    for label, value in (("role-matrix", role), ("routing-contract", routing)):
        if value.get("product_version") != "2.0.0" or value.get("status") != "integrated":
            errors.append(f"{label} has wrong product version or status")
        source = value.get("source_workstream", {})
        source_path = ROOT / str(source.get("path"))
        if not source_path.is_file() or source.get("sha256") != sha256(source_path):
            errors.append(f"{label} is not anchored to its current workstream")
    compatibility_source = role.get("compatibility_workstream", {})
    compatibility_source_path = ROOT / str(compatibility_source.get("path"))
    if (
        not compatibility_source_path.is_file()
        or compatibility_source.get("sha256") != sha256(compatibility_source_path)
    ):
        errors.append("role-matrix is not anchored to the compatibility workstream")

    roles = role.get("roles", [])
    role_ids = [item.get("canonical_role_id") for item in roles]
    expected_roles = ["loop_planning", "verbalizar", "orientar", "ampliar", "refinar"]
    if role_ids != expected_roles:
        errors.append(f"role-matrix roles differ from canonical order: {role_ids}")
    ownership = role.get("decision_ownership", {})
    required_owners = {
        "global_bottleneck_and_role_sequence": "loop_planning",
        "message_value_proposition_voice_tone_and_cta": "verbalizar",
        "lifecycle_stages_segments_eligibility_and_lifecycle_events": "orientar",
        "operational_timing_frequency_contact_pressure_and_cross_channel_cadence": "ampliar",
        "performance_diagnosis_experiment_contract_success_metric_and_learning": "refinar",
    }
    for domain, owner in required_owners.items():
        if ownership.get(domain) != owner:
            errors.append(f"canonical owner mismatch for {domain}")
    handoff_names = {
        item.get("name") for item in role.get("handoff_contract", {}).get("fields", [])
    }
    required_handoff = {
        "handoff_id", "project_ref", "cycle_id", "state_revision", "from_role",
        "to_role", "objective", "bottleneck_ref", "decisions_to_respect",
        "scope_boundary_next_does_not_decide", "evidence_refs", "assumptions",
        "known_gaps", "requested_output", "escalation_conditions",
    }
    required_handoff.add("tactic_refs")
    if not required_handoff.issubset(handoff_names) or len(handoff_names) != 22:
        errors.append("role-matrix handoff contract is incomplete")
    expected_commands = {
        "loop_planning": ("loop.planning", "/loop-planning", ["/loop-planning-agent"]),
        "verbalizar": ("loop.verbalizar", "/verbalizar", ["/verbalizar-agent"]),
        "orientar": ("loop.orientar", "/orientar", ["/orientar-agent"]),
        "ampliar": ("loop.ampliar", "/ampliar", ["/ampliar-agent"]),
        "refinar": ("loop.refinar", "/refinar", ["/refinar-agent"]),
    }
    for item in roles:
        command = item.get("command_contract", {})
        expected = expected_commands.get(item.get("canonical_role_id"))
        if expected != (
            command.get("command_id"),
            command.get("canonical_invocation"),
            command.get("backward_compatible_aliases"),
        ):
            errors.append(f"role command mismatch for {item.get('canonical_role_id')}")
    ampliar = next((item for item in roles if item.get("canonical_role_id") == "ampliar"), {})
    if "channel_classification_with_evidence" in ampliar.get("outputs", []):
        errors.append("Ampliar output still collides semantically with Refinar performance classification")
    if (
        "channel_role_and_feasibility_classification_with_evidence"
        not in ampliar.get("outputs", [])
        or ampliar.get("semantic_boundaries", {}).get("performance_action_classification")
        != "Pertence exclusivamente a Refinar."
    ):
        errors.append("Ampliar channel classification boundary is not explicit")

    enums = routing.get("canonical_enums", {})
    if enums.get("roles") != expected_roles:
        errors.append("routing roles differ from role-matrix")
    if enums.get("maturity") != [
        "nascente", "em_desenvolvimento", "maduro", "avancado", "unknown"
    ]:
        errors.append("routing maturity enum does not preserve unknown")
    routing_handoff = set(
        routing.get("decision_rules", {})
        .get("handoff_validation", {})
        .get("required_fields", [])
    )
    if routing_handoff != handoff_names:
        errors.append("routing and role-matrix handoff field sets differ")
    expected_states = [
        "proposed", "approved", "instrumented", "running", "completed",
        "cancelled", "invalidated",
    ]
    if enums.get("experiment_state") != expected_states:
        errors.append("routing experiment states are incomplete or reordered")
    rules = routing.get("decision_rules", {})
    cardinality = {
        str(item.get("result_count"))
        for item in rules.get("tactic_selection", {}).get("cardinality_rules", [])
    }
    if cardinality != {"0", "1", "2", "reject"}:
        errors.append(f"tactic selection cardinality is incomplete: {cardinality}")
    tactic_selection = rules.get("tactic_selection", {})
    if "route_node_id" not in tactic_selection.get("selection_unit", ""):
        errors.append("tactic selection unit is not a canonical route node")
    if any(
        "route_node" not in str(item.get("when", ""))
        for item in tactic_selection.get("cardinality_rules", [])
        if str(item.get("result_count")) == "reject"
    ):
        errors.append("tactic hard cap is not expressed per route node")
    maturity_rules = rules.get("maturity_gating", {})
    maturity_rows = maturity_rules.get("decision_table", [])
    if not any(item.get("classification") == "unknown" for item in maturity_rows):
        errors.append("maturity table has no unknown result")
    if not any(
        item.get("classification") == "nascente"
        and "all required_classification_dimensions are evidenced" in item.get("when", "")
        for item in maturity_rows
    ):
        errors.append("nascente still acts as a fallback for missing maturity data")
    intervals = rules.get("refinar_benchmark_intervals", {}).get("classification_precedence", [])
    interval_text = set(strings(intervals))
    for expected in (
        "0.00 <= performance_index < 0.50",
        "0.50 <= performance_index < 0.60",
        "0.60 <= performance_index <= 1.00",
        "performance_index > 1.00",
    ):
        if expected not in interval_text:
            errors.append(f"Refinar classification misses interval: {expected}")
    if not any(
        item.get("interval") == "0.50 <= performance_index < 0.60"
        and item.get("classification") == "OTIMIZAR"
        for item in intervals
    ):
        errors.append("Refinar 50-to-60 percent gap is not deterministically resolved")
    normalization_requirements = set(
        rules.get("refinar_benchmark_intervals", {})
        .get("normalization", {})
        .get("requirements", [])
    )
    if not any("non-negative metric domain" in item for item in normalization_requirements):
        errors.append("Refinar ratio classifier does not reject unsupported negative domains")
    testar_row = next(
        (item for item in intervals if item.get("order") == 1 and item.get("classification") == "TESTAR"),
        {},
    )
    if not any("outside the declared non-negative ratio domain" in item for item in testar_row.get("when_any", [])):
        errors.append("negative or unsupported zero benchmark inputs have no deterministic result")
    if len(routing.get("rejection_codes", [])) < 30:
        errors.append("official routing contract has fewer than 30 errors")
    unresolved_ids = {item.get("id") for item in routing.get("unresolved_questions", [])}
    if set(routing.get("lead_resolutions", {})) != unresolved_ids:
        errors.append("routing unresolved questions lack lead dispositions")
    if "UQ-002" in unresolved_ids or not any(
        item.get("id") == "UQ-002" for item in routing.get("resolved_questions", [])
    ):
        errors.append("resolved experiment-state question still appears unresolved")

    spec = validate_markdown(
        P2 / "canonical-spec.md",
        [
            "# Especificação canônica — Loop Marketing v2.0",
            "## 2. Camadas canônicas",
            "## 3. Invariantes normativos",
            "## 5. Mapeamento metodológico",
            "## 7. Autoridade de decisão",
            "## 9. Handoff mínimo",
            "## 13. Compatibilidade",
        ],
        "canonical-spec.md",
        errors,
    )
    policy = validate_markdown(
        P2 / "compatibility-policy.md",
        [
            "# Política de compatibilidade — Loop Marketing v2",
            "## 2. Identidade canônica",
            "## 3. Comandos e aliases",
            "## 4. Layout canônico de estado",
            "## 7. Importação v1.x",
            "## 8. Conflitos",
            "## 9. Rollback",
            "## 12. Cenários de aceite",
        ],
        "compatibility-policy.md",
        errors,
    )
    for token in ("proposed", "approved", "instrumented", "running", "completed", "cancelled", "invalidated"):
        if token not in spec:
            errors.append(f"canonical spec misses experiment state {token}")
    for invocation in (
        "/loop-planning", "/verbalizar", "/orientar", "/ampliar", "/refinar", "/projeto"
    ):
        if invocation not in policy:
            errors.append(f"compatibility policy misses canonical command {invocation}")
    if ".loop-marketing/state/" not in policy or ".loop-marketing/" not in spec:
        errors.append("host-neutral state namespace is inconsistent")

    manifest = load(P2 / "integration-manifest.json")
    if manifest.get("status") != "integrated" or manifest.get("product_version") != "2.0.0":
        errors.append("P2 integration manifest has wrong status or version")
    required_officials = {
        "artifacts/P2/canonical-spec.md",
        "artifacts/P2/role-matrix.json",
        "artifacts/P2/routing-contract.json",
        "artifacts/P2/compatibility-policy.md",
    }
    observed_officials: set[str] = set()
    for item in manifest.get("official_artifacts", []):
        path = str(item.get("path"))
        candidate = ROOT / path
        observed_officials.add(path)
        if (
            not candidate.is_file()
            or item.get("sha256") != sha256(candidate)
            or item.get("bytes") != candidate.stat().st_size
        ):
            errors.append(f"P2 manifest has stale official artifact: {path}")
    if observed_officials != required_officials:
        errors.append("P2 manifest official artifact set is incomplete")
    for section in ("workstream_evidence", "integration_scripts"):
        for item in manifest.get(section, []):
            path = str(item.get("path"))
            candidate = ROOT / path
            if not candidate.is_file() or item.get("sha256") != sha256(candidate):
                errors.append(f"P2 manifest has stale {section} entry: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("workstreams", "final"))
    args = parser.parse_args()
    errors: list[str] = []
    try:
        repo, index = validate_source(errors)
        validate_workstreams(repo, index, errors)
        if args.stage == "final":
            validate_finals(errors)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        errors.append(str(exc))
    print(
        json.dumps(
            {
                "status": "valid" if not errors else "invalid",
                "stage": args.stage,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
