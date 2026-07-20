"""Shared immutable models for P5 modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RuntimeConfig:
    library_root: Path
    catalog_path: Path
    relationship_path: Path
    role_matrix_path: Path
    routing_contract_path: Path
    state_root: Path
    contracts_root: Path

    def normalized(self) -> "RuntimeConfig":
        return RuntimeConfig(**{
            key: Path(value).expanduser().resolve()
            for key, value in asdict(self).items()
        })


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    primary_code: Optional[str] = None
    violations: Tuple[Dict[str, Any], ...] = ()
    value: Any = None

    @classmethod
    def success(cls, value: Any = None) -> "ValidationResult":
        return cls(ok=True, value=value)

    @classmethod
    def failure(cls, code: str, message: str, **details: Any) -> "ValidationResult":
        violation = {"code": code, "message": message, "details": details}
        return cls(ok=False, primary_code=code, violations=(violation,))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "primary_code": self.primary_code,
            "violations": list(self.violations),
            "value": self.value,
        }


@dataclass(frozen=True)
class CommandResolution:
    command_id: str
    canonical_invocation: str
    invoked_as: str
    role_id: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TacticRef:
    tactic_id: str
    canonical_path: str
    canonical_sha256: str
    selection_reason: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TacticSelection:
    route_node_id: str
    role_id: str
    tactic_refs: Tuple[TacticRef, ...] = ()
    ranking_trace: Tuple[Dict[str, Any], ...] = ()
    base_method: bool = True
    requires_planner_review: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_node_id": self.route_node_id,
            "role_id": self.role_id,
            "tactic_refs": [item.to_dict() for item in self.tactic_refs],
            "ranking_trace": list(self.ranking_trace),
            "base_method": self.base_method,
            "requires_planner_review": self.requires_planner_review,
        }


@dataclass(frozen=True)
class RouteNode:
    route_node_id: str
    role_id: str
    objective: str
    mode: str
    state_revision: int
    depends_on: Tuple[str, ...] = ()
    write_set: Tuple[str, ...] = ()
    requested_output_types: Tuple[str, ...] = ()
    selection: Optional[TacticSelection] = None

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["selection"] = self.selection.to_dict() if self.selection else None
        return value


@dataclass(frozen=True)
class RoutePlan:
    project_ref: str
    cycle_id: str
    state_revision: int
    route_status: str
    maturity: str
    primary_bottleneck: Optional[Dict[str, Any]]
    nodes: Tuple[RouteNode, ...] = ()
    parallel_groups: Tuple[Tuple[str, ...], ...] = ()
    rejection_codes: Tuple[str, ...] = ()
    evidence_refs: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_ref": self.project_ref,
            "cycle_id": self.cycle_id,
            "state_revision": self.state_revision,
            "route_status": self.route_status,
            "maturity": self.maturity,
            "primary_bottleneck": self.primary_bottleneck,
            "nodes": [node.to_dict() for node in self.nodes],
            "parallel_groups": [list(group) for group in self.parallel_groups],
            "rejection_codes": list(self.rejection_codes),
            "evidence_refs": list(self.evidence_refs),
        }
