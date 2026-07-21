"""Host-neutral adapter over the security-enforcing runtime facade only."""

from __future__ import annotations

from typing import Any, Dict

from .errors import LoopRuntimeError
from .secure_runtime import SecureLoopRuntime
from .security import validate_and_copy_json


_HOSTS = frozenset(("generic", "claude", "codex"))
_PLANNING_COMMANDS = frozenset(("loop.planning", "loop.projeto"))


class SecureHostAdapter:
    """Expose read-only host dispatch without access to the core orchestrator."""

    __slots__ = ("_runtime", "_host_id")

    def __init__(self, runtime: SecureLoopRuntime, host_id: str) -> None:
        if type(runtime) is not SecureLoopRuntime:
            raise LoopRuntimeError(
                "ERR_SECURITY_CONTEXT_INVALID",
                "The host adapter requires the secure runtime facade.",
            )
        if type(host_id) is not str or host_id not in _HOSTS:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Unknown secure host adapter.",
                retryable=True,
            )
        self._runtime = runtime
        self._host_id = host_id

    def resolve(self, invocation: str) -> Dict[str, Any]:
        return self._runtime.resolve_command(invocation)

    def invoke_read_only(self, invocation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        copied = validate_and_copy_json(payload)
        if type(copied) is not dict:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "The secure adapter payload must be an object.",
                retryable=True,
            )
        resolution = self._runtime.resolve_command(invocation)
        if resolution["command_id"] in _PLANNING_COMMANDS:
            result = self._runtime.prepare_route(copied)
        else:
            if set(copied) != {"route_plan", "route_node_id", "approved_handoff"}:
                raise LoopRuntimeError(
                    "ERR_INPUT_REQUIRED",
                    "A specialist adapter request has invalid fields.",
                    retryable=True,
                )
            matching = [
                item for item in copied["route_plan"].get("nodes", [])
                if item.get("route_node_id") == copied["route_node_id"]
            ] if type(copied.get("route_plan")) is dict else []
            if len(matching) != 1 or matching[0].get("role_id") != resolution["role_id"]:
                raise LoopRuntimeError(
                    "ERR_OWNER_SCOPE_VIOLATION",
                    "The specialist command does not own the selected route node.",
                )
            result = self._runtime.prepare_specialist(
                copied["route_plan"],
                copied["route_node_id"],
                copied["approved_handoff"],
            )
        return {
            "envelope_version": "2.0",
            "host_id": self._host_id,
            "command": resolution,
            "permission": "read_only",
            "external_mutation_allowed": False,
            "result": result,
        }


__all__ = ("SecureHostAdapter",)
