"""Deterministic, privacy-safe observability for the local runtime.

Audit records are deliberately metadata-only.  This module has no file sink,
network sink, clock, random source, or API that accepts raw payloads/prompts.
Telemetry is disabled by default and, when enabled, remains in memory.
"""

from __future__ import annotations

import copy
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import LoopRuntimeError
from .security import safe_fingerprint, validate_and_copy_json


AUDIT_SCHEMA_VERSION = "1.0"

_EVENT_TYPES = frozenset(
    (
        "route_evaluated",
        "handoff_evaluated",
        "integration_evaluated",
        "permission_evaluated",
        "security_denial",
        "evaluation_completed",
    )
)
_OUTCOMES = frozenset(("passed", "failed", "blocked", "denied", "error"))
_EVENT_OUTCOMES = MappingProxyType(
    {
        "route_evaluated": frozenset(("passed", "failed", "blocked", "error")),
        "handoff_evaluated": frozenset(("passed", "failed", "blocked", "error")),
        "integration_evaluated": frozenset(("passed", "failed", "blocked", "error")),
        "permission_evaluated": frozenset(("passed", "denied", "error")),
        "security_denial": frozenset(("denied",)),
        "evaluation_completed": frozenset(("passed", "failed", "error")),
    }
)
_DIMENSION_VALUES = MappingProxyType(
    {
        "component": frozenset(
            ("router", "specialist", "handoff", "integration", "security", "evaluator")
        ),
        "operation": frozenset(
            ("routing", "evidence", "maturity", "permission", "safety", "aggregate")
        ),
        "pillar": frozenset(
            ("none", "loop_planning", "verbalizar", "orientar", "ampliar", "refinar")
        ),
        "maturity": frozenset(
            ("none", "unknown", "nascente", "em_desenvolvimento", "maduro", "avancado")
        ),
        "permission": frozenset(("none", "read_only", "local_state", "external_mutation")),
        "duration_bucket": frozenset(("not_measured", "under_10ms", "under_100ms", "under_1s", "over_1s")),
        "error_family": frozenset(
            ("none", "input", "contract", "evidence", "maturity", "permission", "safety", "state", "internal")
        ),
    }
)
_METRIC_KEYS = frozenset(("item_count", "violation_count"))


def _invalid(message: str = "Audit metadata does not match the closed contract.") -> LoopRuntimeError:
    return LoopRuntimeError("ERR_AUDIT_CONTRACT", message)


def _validate_dimensions(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    copied = validate_and_copy_json(value)
    if type(copied) is not dict:
        raise _invalid()
    output: Dict[str, Any] = {}
    for key in sorted(copied):
        item = copied[key]
        if (
            key not in _DIMENSION_VALUES
            or type(item) is not str
            or item not in _DIMENSION_VALUES[key]
        ):
            raise _invalid()
        output[key] = item
    return output


def _validate_metrics(value: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    if value is None:
        return {}
    copied = validate_and_copy_json(value)
    if type(copied) is not dict or not set(copied).issubset(_METRIC_KEYS):
        raise _invalid()
    output: Dict[str, int] = {}
    for key in sorted(copied):
        item = copied[key]
        if type(item) is not int or item < 0 or item > 1_000_000:
            raise _invalid()
        output[key] = item
    return output


def build_audit_record(
    event_type: str,
    outcome: str,
    *,
    dimensions: Optional[Mapping[str, Any]] = None,
    metrics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one deterministic record from a strict metadata allowlist."""

    if type(event_type) is not str or event_type not in _EVENT_TYPES:
        raise _invalid()
    if type(outcome) is not str or outcome not in _OUTCOMES:
        raise _invalid()
    if outcome not in _EVENT_OUTCOMES[event_type]:
        raise _invalid()
    validated_dimensions = _validate_dimensions(dimensions)
    validated_metrics = _validate_metrics(metrics)
    if event_type == "security_denial":
        if validated_dimensions.get("component") != "security" or validated_dimensions.get("error_family") in (None, "none"):
            raise _invalid()
        if validated_metrics.get("violation_count", 0) < 1:
            raise _invalid()
    if validated_dimensions.get("permission") == "external_mutation" and outcome != "denied":
        raise _invalid()
    record: Dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_type": event_type,
        "outcome": outcome,
        "dimensions": validated_dimensions,
        "metrics": validated_metrics,
    }
    record["record_fingerprint"] = safe_fingerprint(record)
    return record


class AuditCollector:
    """Optional in-memory audit collector; persistence is never enabled."""

    __slots__ = ("_enabled", "_records")

    def __init__(self, enabled: bool = False) -> None:
        if type(enabled) is not bool:
            raise LoopRuntimeError(
                "ERR_AUDIT_CONFIG",
                "Audit collection configuration is invalid.",
            )
        self._enabled = enabled
        self._records = []  # type: list[Dict[str, Any]]

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def persistence_enabled(self) -> bool:
        return False

    def emit(
        self,
        event_type: str,
        outcome: str,
        *,
        dimensions: Optional[Mapping[str, Any]] = None,
        metrics: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._enabled:
            return None
        record = build_audit_record(
            event_type,
            outcome,
            dimensions=dimensions,
            metrics=metrics,
        )
        self._records.append(copy.deepcopy(record))
        return copy.deepcopy(record)

    def records(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._records))

    def clear(self) -> None:
        self._records.clear()


__all__ = (
    "AUDIT_SCHEMA_VERSION",
    "AuditCollector",
    "build_audit_record",
)
