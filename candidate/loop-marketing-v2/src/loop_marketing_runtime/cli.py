"""Small host-neutral JSON CLI for the staged P5 runtime."""

from __future__ import annotations

import argparse
import json
import sys
import sysconfig
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .errors import LoopRuntimeError
from .models import RuntimeConfig
from .orchestrator import LoopOrchestrator


def _read_json(path: str) -> Dict[str, Any]:
    if path == "-":
        value = json.load(sys.stdin)
    else:
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    if not isinstance(value, dict):
        raise LoopRuntimeError(
            "ERR_INPUT_REQUIRED",
            "The JSON input must be an object.",
            retryable=True,
            details={"path": path},
        )
    return value


def _runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    runtime_root = Path(args.runtime_root)
    return RuntimeConfig(
        library_root=Path(args.library_root),
        catalog_path=runtime_root / "data" / "tactic-catalog.json",
        relationship_path=runtime_root / "data" / "relationship-map.json",
        role_matrix_path=runtime_root / "data" / "role-matrix.json",
        routing_contract_path=runtime_root / "data" / "routing-contract.json",
        state_root=Path(args.state_root),
        contracts_root=runtime_root / "contracts",
    )


def _parser() -> argparse.ArgumentParser:
    source_root = Path(__file__).resolve().parents[2]
    installed_root = Path(sysconfig.get_path("data")) / "share" / "loop-marketing-runtime"
    package_root = source_root if (source_root / "data" / "tactic-catalog.json").is_file() else installed_root
    parser = argparse.ArgumentParser(prog="loop-marketing")
    parser.add_argument("--runtime-root", default=str(package_root))
    parser.add_argument("--library-root", default=".")
    parser.add_argument("--state-root", default=".loop-marketing")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    resolve = subparsers.add_parser("resolve", help="Resolve a canonical command or alias.")
    resolve.add_argument("invocation")

    route = subparsers.add_parser("route", help="Prepare a read-only route from JSON.")
    route.add_argument("request", help="JSON file or '-' for stdin.")

    specialist = subparsers.add_parser(
        "specialist",
        help="Prepare one read-only specialist envelope from a route plan.",
    )
    specialist.add_argument("route_plan", help="JSON file or '-' for stdin.")
    specialist.add_argument("route_node_id")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    args = _parser().parse_args(argv)
    orchestrator = LoopOrchestrator(_runtime_config(args))
    if args.operation == "resolve":
        return orchestrator.resolve_command(args.invocation).to_dict()
    if args.operation == "route":
        return orchestrator.prepare_route(_read_json(args.request))
    if args.operation == "specialist":
        return orchestrator.prepare_specialist(
            _read_json(args.route_plan),
            args.route_node_id,
        )
    raise LoopRuntimeError("ERR_RUNTIME_INTERNAL", "Unsupported CLI operation.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = run(argv)
    except LoopRuntimeError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False, sort_keys=True))
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = LoopRuntimeError(
            "ERR_INPUT_REQUIRED",
            "The CLI input could not be read.",
            retryable=True,
            details={"error_type": type(exc).__name__},
        )
        print(json.dumps({"ok": False, "error": error.to_dict()}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception:
        error = LoopRuntimeError(
            "ERR_RUNTIME_INTERNAL",
            "The runtime could not complete the operation safely.",
            retryable=False,
            details={},
        )
        print(json.dumps({"ok": False, "error": error.to_dict()}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
