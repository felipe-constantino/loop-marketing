#!/usr/bin/env python3
"""Build the deterministic read-only source inventory for P1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


CONTROL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = CONTROL_ROOT / "PROJECT.json"
SOURCE_INDEX_PATH = CONTROL_ROOT / "SOURCE_INDEX.json"
OUTPUT_PATH = CONTROL_ROOT / "artifacts" / "P1" / "inventory.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(path: Path) -> tuple[str, str | None]:
    parts = path.parts
    if str(path) == ".gitignore":
        return "repository_config", None
    if len(parts) == 1:
        if path.name in {"SKILL.md", "CLAUDE.md", "AGENTS.md"}:
            return "runtime_instruction", None
        return "product_documentation", None
    if parts[0] == "commands":
        if path.name == "projeto-template.md":
            return "project_memory_template", None
        return "agent_command", None
    if parts[0] == "biblioteca":
        pillar = parts[1]
        if path.name == "INDEX.md":
            return "tactical_index", pillar
        return "canonical_tactical_prompt", pillar
    return "other", None


def main() -> int:
    project = read_json(PROJECT_PATH)
    source_index = read_json(SOURCE_INDEX_PATH)
    repo = Path(project["source"]["repo"]).resolve()
    tracked_paths = [
        Path(line)
        for line in run_git(repo, "ls-files").splitlines()
        if line.strip()
    ]
    canonical_hashes = {
        item["path"]: item["sha256"]
        for item in source_index["canonical_prompts"]
    }
    files: list[dict[str, Any]] = []
    for relative in tracked_paths:
        absolute = repo / relative
        category, pillar = classify(relative)
        raw = absolute.read_bytes()
        entry = {
            "path": str(relative),
            "category": category,
            "pillar": pillar,
            "bytes": len(raw),
            "lines": len(raw.splitlines()),
            "sha256": sha256_file(absolute),
        }
        if category == "canonical_tactical_prompt":
            entry["matches_source_index"] = (
                canonical_hashes.get(str(relative)) == entry["sha256"]
            )
        files.append(entry)

    category_counts = Counter(item["category"] for item in files)
    pillar_counts = Counter(
        item["pillar"] for item in files if item["pillar"] is not None
    )
    errors: list[str] = []
    if len(files) != project["source"]["file_count_at_baseline"]:
        errors.append(
            f"tracked file count {len(files)} differs from baseline {project['source']['file_count_at_baseline']}"
        )
    tactical = [
        item for item in files if item["category"] == "canonical_tactical_prompt"
    ]
    if len(tactical) != project["source"]["canonical_prompt_count"]:
        errors.append("canonical prompt count differs from baseline")
    mismatches = [
        item["path"] for item in tactical if not item["matches_source_index"]
    ]
    if mismatches:
        errors.append(f"canonical prompt hash mismatches: {mismatches}")
    if run_git(repo, "status", "--porcelain"):
        errors.append("source worktree is not clean during read-only P1")

    output = {
        "schema_version": "1.0",
        "phase": "P1",
        "mode": "read_only",
        "source_repo": str(repo),
        "source_commit": run_git(repo, "rev-parse", "HEAD"),
        "source_branch": run_git(repo, "branch", "--show-current"),
        "tracked_file_count": len(files),
        "canonical_prompt_count": len(tactical),
        "canonical_library_aggregate_sha256": source_index[
            "canonical_library_aggregate_sha256"
        ],
        "classification_summary": {
            "by_category": dict(sorted(category_counts.items())),
            "by_pillar_including_indexes": dict(sorted(pillar_counts.items())),
        },
        "coverage": {
            "all_tracked_files_classified": not any(
                item["category"] == "other" for item in files
            ),
            "canonical_hashes_match": not mismatches,
            "source_worktree_clean": not bool(
                run_git(repo, "status", "--porcelain")
            ),
        },
        "files": files,
        "errors": errors,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT_PATH.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(OUTPUT_PATH)
    print(
        json.dumps(
            {
                "status": "valid" if not errors else "invalid",
                "output": str(OUTPUT_PATH),
                "tracked_file_count": len(files),
                "canonical_prompt_count": len(tactical),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
