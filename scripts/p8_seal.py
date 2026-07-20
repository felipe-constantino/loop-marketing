#!/usr/bin/env python3
"""Build, seal and verify the deterministic internal Loop Marketing skill archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "release" / "loop-marketing"
ARCHIVE = ROOT / "release" / "loop-marketing-internal-v2.0.0.tar.gz"
P8 = ROOT / "artifacts" / "P8"
MANIFEST = P8 / "release-manifest.json"
AUDIT = P8 / "final-release-audit.json"
VALIDATION = P8 / "validation-report.json"
FORWARD = P8 / "forward-test-report.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def skill_files():
    return sorted(
        path for path in SKILL.rglob("*")
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def run_json(script):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode:
        raise RuntimeError("%s failed" % script)
    return json.loads(completed.stdout)


def build_archive(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for path in skill_files():
                    relative = path.relative_to(SKILL)
                    info = bundle.gettarinfo(str(path), arcname=str(Path("loop-marketing") / relative))
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    info.mode = 0o755 if relative == Path("scripts/loop_marketing.py") else 0o644
                    with path.open("rb") as handle:
                        bundle.addfile(info, handle)
    os.replace(temporary, destination)


def build_manifest(timestamp, validation, forward, audit):
    files = [entry(path) for path in skill_files()]
    contents = "\n".join("%s\0%s" % (item["path"], item["sha256"]) for item in files)
    prompt_files = [item for item in files if "/references/library/biblioteca/" in item["path"] and not item["path"].endswith("/INDEX.md")]
    return {
        "artifact_id": "loop-marketing-p8-release-manifest",
        "schema_version": "1.0",
        "product_version": "2.0.0",
        "status": "sealed",
        "sealed_at": timestamp,
        "distribution": "internal_restricted",
        "skill_root": "release/loop-marketing",
        "skill_files": files,
        "skill_contents_sha256": hashlib.sha256(contents.encode("utf-8")).hexdigest(),
        "archive": entry(ARCHIVE),
        "release_scripts": [entry(ROOT / "scripts" / name) for name in ("p8_validate.py", "p8_seal.py")],
        "gate_reports": [entry(VALIDATION), entry(FORWARD), entry(AUDIT)],
        "gate_summary": {
            "validator": validation["status"],
            "forward_tests": forward["verdict"],
            "final_audit": audit["verdict"],
            "p7_dependency_seal": validation["gates"]["p7_dependency_seal"],
            "official_skill_validator": validation["gates"]["official_skill_validator"],
            "documentation_contract": validation["gates"]["documentation_contract"],
            "portable_path_hygiene": validation["gates"]["portable_path_hygiene"],
            "packaged_e2e_committed": validation["gates"]["packaged_e2e_committed"],
            "evaluation_passed": validation["gates"]["evaluation_passed"],
            "sensitive_input_rejected": validation["gates"]["sensitive_input_rejected"],
            "source_preserved": validation["source"]["preserved"],
        },
        "counts": {
            "skill_files": len(files),
            "canonical_prompts": len(prompt_files),
            "library_files": validation["counts"]["library_files"],
            "runtime_modules": validation["counts"]["runtime_modules"],
            "command_invocations": validation["counts"]["command_invocations"],
        },
        "baseline": {
            "source_commit": "3cbf0cf84a038f2cd570883b70988889f037c28e",
            "canonical_prompt_count": 100,
            "aggregate_sha256": "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1",
        },
    }


def archive_members():
    with tarfile.open(ARCHIVE, mode="r:gz") as bundle:
        members = bundle.getmembers()
        if any(not member.isfile() or member.issym() or member.islnk() for member in members):
            raise RuntimeError("archive contains a non-regular member")
        return sorted(member.name for member in members)


def verify(live=True):
    errors = []
    if not MANIFEST.is_file() or not ARCHIVE.is_file():
        return {"status": "FAIL", "errors": ["release manifest or archive is missing"]}
    try:
        manifest = load(MANIFEST)
        validation = load(VALIDATION)["result"]
        forward = load(FORWARD)
        audit = load(AUDIT)
        expected = build_manifest(manifest.get("sealed_at"), validation, forward, audit)
        if manifest != expected:
            errors.append("release manifest structure, topology or hashes drifted")
        expected_members = sorted(str(Path("loop-marketing") / path.relative_to(SKILL)) for path in skill_files())
        if archive_members() != expected_members:
            errors.append("archive member topology drifted")
        with tempfile.TemporaryDirectory(prefix="loop-p8-repro-") as temporary:
            reproduced = Path(temporary) / ARCHIVE.name
            build_archive(reproduced)
            if reproduced.read_bytes() != ARCHIVE.read_bytes():
                errors.append("archive is not reproducible")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, tarfile.TarError):
        errors.append("release manifest, archive or gate report is malformed")
        audit = {}
        forward = {}
        validation = {}
    if audit.get("verdict") != "PASS" or audit.get("blockers"):
        errors.append("final release audit did not pass")
    if validation.get("status") != "PASS":
        errors.append("release validation report failed")
    if forward.get("verdict") != "PASS" or forward.get("blockers"):
        errors.append("forward tests did not pass")
    if live and not errors:
        try:
            if run_json("p8_validate.py")["status"] != "PASS":
                errors.append("live release validation failed")
        except (RuntimeError, ValueError, KeyError):
            errors.append("live release gate failed")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def seal():
    audit = load(AUDIT) if AUDIT.is_file() else {}
    forward = load(FORWARD) if FORWARD.is_file() else {}
    if audit.get("verdict") != "PASS" or audit.get("blockers"):
        raise RuntimeError("final release audit must pass without blockers")
    if forward.get("verdict") != "PASS" or forward.get("blockers"):
        raise RuntimeError("forward tests must pass without blockers")
    validation = run_json("p8_validate.py")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dump(VALIDATION, {
        "artifact_id": "loop-marketing-p8-validation-report",
        "generated_at": timestamp,
        "command": "python3 scripts/p8_validate.py",
        "result": validation,
    })
    build_archive(ARCHIVE)
    dump(MANIFEST, build_manifest(timestamp, validation, forward, audit))
    return {"status": "SEALED", "sealed_at": timestamp, "verify": verify(live=True)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seal", "verify"))
    args = parser.parse_args()
    try:
        result = seal() if args.action == "seal" else verify(live=True)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result["status"] in ("PASS", "SEALED") and result.get("verify", {"status": "PASS"})["status"] == "PASS"
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
