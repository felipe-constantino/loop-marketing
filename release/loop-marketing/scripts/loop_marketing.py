#!/usr/bin/env python3
"""Closed internal-release wrapper for the bundled Loop Marketing runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = SKILL_ROOT / "scripts" / "runtime"
RESOURCE_ROOT = SKILL_ROOT / "references" / "runtime-data"
LIBRARY_ROOT = SKILL_ROOT / "references" / "library"
sys.path.insert(0, str(RUNTIME_SOURCE))

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.evaluation import evaluate_outcome, evaluate_suite
from loop_marketing_runtime.models import RuntimeConfig
from loop_marketing_runtime.secure_cli import _print_bounded, _read_json
from loop_marketing_runtime.secure_runtime import SecureLoopRuntime
from loop_marketing_runtime.security import safe_error


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="loop-marketing", description="Loop Marketing v2.0 internal release")
    operations = value.add_subparsers(dest="operation", required=True)
    init = operations.add_parser("init", help="Initialize isolated local project state")
    init.add_argument("project_id")
    init.add_argument("display_name")
    read = operations.add_parser("read", help="Replay project state without repair")
    read.add_argument("project_id")
    route = operations.add_parser("route", help="Prepare a deterministic route from JSON")
    route.add_argument("request")
    specialist = operations.add_parser("specialist", help="Prepare one route-bound specialist envelope")
    specialist.add_argument("route_plan")
    specialist.add_argument("route_node_id")
    integrate = operations.add_parser("integrate", help="Validate and atomically commit local state")
    integrate.add_argument("envelope")
    evaluate = operations.add_parser("evaluate", help="Evaluate normalized metadata without state writes")
    evaluate.add_argument("case")
    resolve = operations.add_parser("resolve", help="Check canonical and legacy command compatibility")
    resolve.add_argument("invocation")
    return value


def runtime() -> SecureLoopRuntime:
    return SecureLoopRuntime(RuntimeConfig(
        library_root=LIBRARY_ROOT,
        catalog_path=RESOURCE_ROOT / "data" / "tactic-catalog.json",
        relationship_path=RESOURCE_ROOT / "data" / "relationship-map.json",
        role_matrix_path=RESOURCE_ROOT / "data" / "role-matrix.json",
        routing_contract_path=RESOURCE_ROOT / "data" / "routing-contract.json",
        state_root=Path.cwd() / ".loop-marketing",
        contracts_root=RESOURCE_ROOT / "contracts",
    ))


def run(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    args = parser().parse_args(argv)
    if args.operation == "evaluate":
        value = _read_json(args.case)
        if set(value) == {"case", "outcome"}:
            return evaluate_outcome(value["case"], value["outcome"])
        if set(value) == {"cases", "outcomes"}:
            return evaluate_suite(value["cases"], value["outcomes"])
        raise LoopRuntimeError(
            "ERR_EVALUATION_CONTRACT",
            "Evaluation input must contain case/outcome or cases/outcomes.",
            retryable=True,
        )
    engine = runtime()
    if args.operation == "init":
        return engine.initialize_project(args.project_id, args.display_name)
    if args.operation == "read":
        return engine.read_project(args.project_id)
    if args.operation == "route":
        return engine.prepare_route(_read_json(args.request))
    if args.operation == "specialist":
        return engine.prepare_specialist(_read_json(args.route_plan), args.route_node_id)
    if args.operation == "integrate":
        return engine.integrate(_read_json(args.envelope))
    if args.operation == "resolve":
        return engine.resolve_command(args.invocation)
    raise LoopRuntimeError("ERR_RUNTIME_INTERNAL", "Unsupported Loop Marketing operation.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = run(argv)
    except LoopRuntimeError as exc:
        error = safe_error(exc.code, exc.message, retryable=exc.retryable, details=exc.details)
        _print_bounded({"ok": False, "error": error.to_dict()})
        return 2
    except SystemExit:
        raise
    except Exception:
        error = safe_error("ERR_RUNTIME_INTERNAL", "The Loop Marketing wrapper could not complete the operation.")
        _print_bounded({"ok": False, "error": error.to_dict()})
        return 2
    return 0 if _print_bounded({"ok": True, "result": result}) else 2


if __name__ == "__main__":
    raise SystemExit(main())
