"""JSON CLI exposing only the security-enforcing internal-release facade."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import sysconfig
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .errors import LoopRuntimeError
from .models import RuntimeConfig
from .secure_runtime import SecureLoopRuntime
from .security import safe_error


MAX_RAW_INPUT_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 2_097_152


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise LoopRuntimeError(
                "ERR_SECURITY_JSON_DUPLICATE_KEY",
                "Duplicate JSON object keys are not allowed.",
                retryable=True,
            )
        value[key] = item
    return value


def _read_input_bytes(path: str) -> bytes:
    if path == "-":
        buffer = getattr(sys.stdin, "buffer", None)
        raw = buffer.read(MAX_RAW_INPUT_BYTES + 1) if buffer is not None else sys.stdin.read(MAX_RAW_INPUT_BYTES + 1).encode("utf-8")
    else:
        input_path = Path(path)
        try:
            path_stat = input_path.lstat()
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                raise LoopRuntimeError(
                    "ERR_SECURITY_INPUT_PATH",
                    "The JSON input path must be a regular non-symlink file.",
                    retryable=True,
                )
            if path_stat.st_size > MAX_RAW_INPUT_BYTES:
                raise LoopRuntimeError(
                    "ERR_SECURITY_INPUT_SIZE",
                    "The JSON input exceeds the configured byte limit.",
                    retryable=True,
                    details={"limit": MAX_RAW_INPUT_BYTES},
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(str(input_path), flags)
            try:
                opened_stat = os.fstat(descriptor)
                if not stat.S_ISREG(opened_stat.st_mode):
                    raise LoopRuntimeError(
                        "ERR_SECURITY_INPUT_PATH",
                        "The JSON input path must be a regular file.",
                        retryable=True,
                    )
                raw = os.read(descriptor, MAX_RAW_INPUT_BYTES + 1)
            finally:
                os.close(descriptor)
        except LoopRuntimeError:
            raise
        except OSError:
            raise LoopRuntimeError(
                "ERR_SECURITY_INPUT_PATH",
                "The JSON input file could not be read safely.",
                retryable=True,
            ) from None
    if len(raw) > MAX_RAW_INPUT_BYTES:
        raise LoopRuntimeError(
            "ERR_SECURITY_INPUT_SIZE",
            "The JSON input exceeds the configured byte limit.",
            retryable=True,
            details={"limit": MAX_RAW_INPUT_BYTES},
        )
    return raw


def _read_json(path: str) -> Dict[str, Any]:
    try:
        text = _read_input_bytes(path).decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except LoopRuntimeError:
        raise
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise LoopRuntimeError(
            "ERR_SECURITY_JSON_PARSE",
            "The JSON input is not valid canonical UTF-8 JSON.",
            retryable=True,
        ) from None
    if not isinstance(value, dict):
        raise LoopRuntimeError(
            "ERR_INPUT_REQUIRED",
            "The JSON input must be an object.",
            retryable=True,
        )
    return value


def _parser() -> argparse.ArgumentParser:
    source_root = Path(__file__).resolve().parents[2]
    installed_root = Path(sysconfig.get_path("data")) / "share" / "loop-marketing-runtime"
    package_root = source_root if (source_root / "data" / "tactic-catalog.json").is_file() else installed_root
    parser = argparse.ArgumentParser(prog="loop-marketing-secure")
    parser.add_argument("--runtime-root", default=str(package_root))
    parser.add_argument("--library-root", required=True)
    parser.add_argument("--state-root", default=".loop-marketing")
    operations = parser.add_subparsers(dest="operation", required=True)
    init = operations.add_parser("init")
    init.add_argument("project_id")
    init.add_argument("display_name")
    resolve = operations.add_parser("resolve")
    resolve.add_argument("invocation")
    read = operations.add_parser("read")
    read.add_argument("project_id")
    route = operations.add_parser("route")
    route.add_argument("request")
    specialist = operations.add_parser("specialist")
    specialist.add_argument("route_plan")
    specialist.add_argument("route_node_id")
    specialist.add_argument("approved_handoff")
    integrate = operations.add_parser("integrate")
    integrate.add_argument("envelope")
    return parser


def _runtime(args: argparse.Namespace) -> SecureLoopRuntime:
    root = Path(args.runtime_root)
    return SecureLoopRuntime(RuntimeConfig(
        library_root=Path(args.library_root),
        catalog_path=root / "data" / "tactic-catalog.json",
        relationship_path=root / "data" / "relationship-map.json",
        role_matrix_path=root / "data" / "role-matrix.json",
        routing_contract_path=root / "data" / "routing-contract.json",
        state_root=Path(args.state_root),
        contracts_root=root / "contracts",
    ))


def run(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    args = _parser().parse_args(argv)
    runtime = _runtime(args)
    if args.operation == "init":
        return runtime.initialize_project(args.project_id, args.display_name)
    if args.operation == "resolve":
        return runtime.resolve_command(args.invocation)
    if args.operation == "read":
        return runtime.read_project(args.project_id)
    if args.operation == "route":
        return runtime.prepare_route(_read_json(args.request))
    if args.operation == "specialist":
        return runtime.prepare_specialist(
            _read_json(args.route_plan),
            args.route_node_id,
            _read_json(args.approved_handoff),
        )
    if args.operation == "integrate":
        return runtime.integrate(_read_json(args.envelope))
    raise LoopRuntimeError("ERR_RUNTIME_INTERNAL", "Unsupported secure CLI operation.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = run(argv)
    except LoopRuntimeError as exc:
        error = safe_error(
            exc.code,
            exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )
        _print_bounded({"ok": False, "error": error.to_dict()})
        return 2
    except Exception as exc:
        error = safe_error(
            "ERR_RUNTIME_INTERNAL",
            "The secure CLI could not complete the operation.",
        )
        _print_bounded({"ok": False, "error": error.to_dict()})
        return 2
    try:
        within_limit = _print_bounded({"ok": True, "result": result})
    except LoopRuntimeError as exc:
        error = safe_error(exc.code, exc.message, details=exc.details)
        _print_bounded({"ok": False, "error": error.to_dict()})
        return 2
    return 0 if within_limit else 2


def _print_bounded(value: Dict[str, Any]) -> bool:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    within_limit = True
    if len(rendered.encode("utf-8")) > MAX_OUTPUT_BYTES:
        within_limit = False
        rendered = json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "ERR_SECURITY_OUTPUT_SIZE",
                    "message": "The runtime output exceeds the configured byte limit.",
                    "retryable": False,
                    "details": {"limit": MAX_OUTPUT_BYTES},
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    print(rendered)
    return within_limit


if __name__ == "__main__":
    raise SystemExit(main())
