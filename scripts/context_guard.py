#!/usr/bin/env python3
"""Create and validate the durable context snapshot for Loop Marketing v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


CONTROL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = CONTROL_ROOT / "PROJECT.json"
CHECKPOINT_PATH = CONTROL_ROOT / "CHECKPOINT.md"
DECISIONS_PATH = CONTROL_ROOT / "DECISIONS.jsonl"
WORKLOG_PATH = CONTROL_ROOT / "WORKLOG.jsonl"
INDEX_PATH = CONTROL_ROOT / "SOURCE_INDEX.json"
CONTROL_INDEX_PATH = CONTROL_ROOT / "CONTEXT_INDEX.json"
PROTOCOL_PATH = CONTROL_ROOT / "CONTEXT_PROTOCOL.md"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def validate_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name}:{line_number} is not an object")
            entry_id = value.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                raise ValueError(f"{path.name}:{line_number} has no valid id")
            if entry_id in ids:
                raise ValueError(f"{path.name}:{line_number} repeats id {entry_id}")
            ids.add(entry_id)
            entries.append(value)
    return entries


def validate_log_semantics(
    entries: list[dict[str, Any]],
    *,
    prefix: str,
    required_fields: set[str],
    allowed_statuses: set[str],
) -> list[str]:
    errors: list[str] = []
    numbers: list[int] = []
    for line_number, entry in enumerate(entries, start=1):
        missing = sorted(required_fields - entry.keys())
        if missing:
            errors.append(f"{prefix} log entry {line_number} misses fields: {missing}")
        entry_id = entry.get("id", "")
        match = re.fullmatch(rf"{prefix}-(\d{{4}})", str(entry_id))
        if not match:
            errors.append(f"invalid {prefix} id: {entry_id}")
        else:
            numbers.append(int(match.group(1)))
        if entry.get("status") not in allowed_statuses:
            errors.append(f"invalid status in {entry_id}: {entry.get('status')}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("date", ""))):
            errors.append(f"invalid date in {entry_id}")
        evidence = entry.get("evidence")
        if evidence in (None, [], {}):
            errors.append(f"missing evidence in {entry_id}")
    if numbers != list(range(1, len(numbers) + 1)):
        errors.append(f"{prefix} ids are not consecutive from 0001")
    return errors


def validate_project_semantics(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "project_id",
        "checkpoint_id",
        "status",
        "objective",
        "source",
        "constraints",
        "execution_model",
        "phases",
        "acceptance_criteria",
    }
    missing = sorted(required - project.keys())
    if missing:
        errors.append(f"PROJECT.json misses fields: {missing}")
    if project.get("project_id") != "loop-marketing-v2":
        errors.append("unexpected project_id")
    if not re.fullmatch(r"CP-\d{4}", str(project.get("checkpoint_id", ""))):
        errors.append("invalid checkpoint_id")
    phase_statuses = {"pending", "in_progress", "completed", "blocked"}
    phase_ids: set[str] = set()
    for phase in project.get("phases", []):
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or phase_id in phase_ids:
            errors.append(f"invalid or duplicate phase id: {phase_id}")
        phase_ids.add(phase_id)
        if phase.get("status") not in phase_statuses:
            errors.append(f"invalid phase status in {phase_id}")
    p1 = next((phase for phase in project.get("phases", []) if phase.get("id") == "P1"), None)
    if not p1 or not p1.get("deliverables") or not p1.get("exit_criteria"):
        errors.append("P1 must define deliverables and exit_criteria")
    return errors


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(repo: Path) -> list[Path]:
    return sorted(
        path
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    )


def canonical_prompts(repo: Path) -> list[Path]:
    library = repo / "biblioteca"
    return sorted(
        path
        for path in library.glob("*/*.md")
        if path.name != "INDEX.md"
    )


def build_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    repo = Path(project["source"]["repo"]).resolve()
    prompts = canonical_prompts(repo)
    prompt_entries = [
        {
            "path": str(path.relative_to(repo)),
            "sha256": sha256_file(path),
        }
        for path in prompts
    ]
    aggregate_payload = "\n".join(
        f"{entry['path']}\0{entry['sha256']}" for entry in prompt_entries
    ).encode("utf-8")
    all_files = source_files(repo)
    status_lines = run_git(repo, "status", "--porcelain").splitlines()
    critical_names = {
        "SKILL.md",
        "CLAUDE.md",
        "AGENTS.md",
        "README.md",
        "LEIAME.md",
        "SOBRE.md",
    }
    critical_files = [
        {
            "path": str(path.relative_to(repo)),
            "sha256": sha256_file(path),
        }
        for path in all_files
        if (
            path.name in critical_names
            or path.parent.name == "commands"
            or (path.name == "INDEX.md" and path.parent.parent.name == "biblioteca")
        )
    ]
    return {
        "schema_version": "1.0",
        "repo": str(repo),
        "branch": run_git(repo, "branch", "--show-current"),
        "commit": run_git(repo, "rev-parse", "HEAD"),
        "worktree_clean": not status_lines,
        "changed_paths": status_lines,
        "total_source_files": len(all_files),
        "canonical_prompt_count": len(prompt_entries),
        "canonical_library_aggregate_sha256": hashlib.sha256(
            aggregate_payload
        ).hexdigest(),
        "canonical_prompts": prompt_entries,
        "critical_files": critical_files,
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def nonempty_line_hashes(path: Path) -> list[str]:
    hashes: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.strip():
                hashes.append(hashlib.sha256(line.encode("utf-8")).hexdigest())
    return hashes


def build_control_index(project: dict[str, Any]) -> dict[str, Any]:
    core_paths = (
        PROJECT_PATH,
        CHECKPOINT_PATH,
        PROTOCOL_PATH,
        INDEX_PATH,
        Path(__file__).resolve(),
    )
    return {
        "schema_version": "1.0",
        "checkpoint_id": project["checkpoint_id"],
        "core_files": [
            {
                "path": str(path.relative_to(CONTROL_ROOT)),
                "sha256": sha256_file(path),
            }
            for path in core_paths
        ],
        "append_only_logs": {
            path.name: {
                "line_count": len(nonempty_line_hashes(path)),
                "line_sha256": nonempty_line_hashes(path),
            }
            for path in (DECISIONS_PATH, WORKLOG_PATH)
        },
    }


def snapshot() -> int:
    project = read_json(PROJECT_PATH)
    value = build_snapshot(project)
    write_json_atomic(INDEX_PATH, value)
    print(
        json.dumps(
            {
                "status": "snapshot_written",
                "index": str(INDEX_PATH),
                "commit": value["commit"],
                "worktree_clean": value["worktree_clean"],
                "canonical_prompt_count": value["canonical_prompt_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def seal() -> int:
    try:
        project = read_json(PROJECT_PATH)
        current = build_control_index(project)
        errors: list[str] = []
        if CONTROL_INDEX_PATH.exists():
            previous = read_json(CONTROL_INDEX_PATH)
            for name, old_log in previous.get("append_only_logs", {}).items():
                new_hashes = current["append_only_logs"].get(name, {}).get(
                    "line_sha256", []
                )
                old_hashes = old_log.get("line_sha256", [])
                if new_hashes[: len(old_hashes)] != old_hashes:
                    errors.append(f"append-only history changed for {name}")
        else:
            errors.append("CONTEXT_INDEX.json is missing; restore it from Git instead of resealing")
        if errors:
            print(json.dumps({"status": "seal_rejected", "errors": errors}, ensure_ascii=False, indent=2))
            return 1
        write_json_atomic(CONTROL_INDEX_PATH, current)
        print(
            json.dumps(
                {
                    "status": "sealed",
                    "checkpoint_id": current["checkpoint_id"],
                    "decision_entries": current["append_only_logs"][DECISIONS_PATH.name]["line_count"],
                    "worklog_entries": current["append_only_logs"][WORKLOG_PATH.name]["line_count"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "seal_rejected", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


def validate() -> int:
    errors: list[str] = []
    try:
        project = read_json(PROJECT_PATH)
        stored = read_json(INDEX_PATH)
        decisions = validate_jsonl(DECISIONS_PATH)
        worklog = validate_jsonl(WORKLOG_PATH)
        errors.extend(validate_project_semantics(project))
        errors.extend(
            validate_log_semantics(
                decisions,
                prefix="D",
                required_fields={"id", "date", "status", "decision", "rationale", "evidence", "supersedes"},
                allowed_statuses={"active", "superseded", "revoked"},
            )
        )
        errors.extend(
            validate_log_semantics(
                worklog,
                prefix="E",
                required_fields={"id", "date", "type", "status", "summary", "evidence"},
                allowed_statuses={"in_progress", "completed", "failed", "blocked"},
            )
        )
        current = build_snapshot(project)
        control_stored = read_json(CONTROL_INDEX_PATH)
        control_current = build_control_index(project)
        checkpoint = CHECKPOINT_PATH.read_text(encoding="utf-8")

        checkpoint_id = project.get("checkpoint_id")
        checkpoint_first_line = checkpoint.splitlines()[0] if checkpoint else ""
        if not isinstance(checkpoint_id, str) or checkpoint_first_line != f"# Checkpoint {checkpoint_id}":
            errors.append("CHECKPOINT.md header does not exactly match PROJECT.json checkpoint_id")

        expected_count = project["source"]["canonical_prompt_count"]
        if current["canonical_prompt_count"] != expected_count:
            errors.append(
                f"canonical prompt count is {current['canonical_prompt_count']}, expected {expected_count}"
            )

        expected_library_hash = project["source"]["baseline_library_aggregate_sha256"]
        if current["canonical_library_aggregate_sha256"] != expected_library_hash:
            errors.append("canonical library differs from the anchored baseline hash")

        for field in (
            "commit",
            "branch",
            "worktree_clean",
            "changed_paths",
            "total_source_files",
            "canonical_prompt_count",
            "canonical_library_aggregate_sha256",
            "canonical_prompts",
            "critical_files",
        ):
            if current.get(field) != stored.get(field):
                errors.append(f"source snapshot is stale for field: {field}")

        if control_current != control_stored:
            errors.append("control artifacts differ from CONTEXT_INDEX.json; run seal after authorized updates")

        summary = {
            "status": "valid" if not errors else "invalid",
            "checkpoint_id": checkpoint_id,
            "decision_entries": len(decisions),
            "worklog_entries": len(worklog),
            "canonical_prompt_count": current["canonical_prompt_count"],
            "source_commit": current["commit"],
            "source_worktree_clean": current["worktree_clean"],
            "errors": errors,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("snapshot", "seal", "validate"))
    args = parser.parse_args()
    if args.command == "snapshot":
        return snapshot()
    if args.command == "seal":
        return seal()
    return validate()


if __name__ == "__main__":
    sys.exit(main())
