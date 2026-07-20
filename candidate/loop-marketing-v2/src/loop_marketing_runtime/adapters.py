"""Host-neutral, read-only adapters for the frozen P5 command surface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, Tuple

from .errors import LoopRuntimeError
from .models import CommandResolution

if TYPE_CHECKING:
    from .orchestrator import LoopOrchestrator


_HOSTS = frozenset(("generic", "claude", "codex"))

# This closed table is intentionally independent of host presentation layers.
_COMMANDS: Dict[str, Tuple[str, str, str]] = {
    "/loop-planning": ("loop.planning", "/loop-planning", "loop_planning"),
    "/loop-planning-agent": ("loop.planning", "/loop-planning", "loop_planning"),
    "/verbalizar": ("loop.verbalizar", "/verbalizar", "verbalizar"),
    "/verbalizar-agent": ("loop.verbalizar", "/verbalizar", "verbalizar"),
    "/orientar": ("loop.orientar", "/orientar", "orientar"),
    "/orientar-agent": ("loop.orientar", "/orientar", "orientar"),
    "/ampliar": ("loop.ampliar", "/ampliar", "ampliar"),
    "/ampliar-agent": ("loop.ampliar", "/ampliar", "ampliar"),
    "/refinar": ("loop.refinar", "/refinar", "refinar"),
    "/refinar-agent": ("loop.refinar", "/refinar", "refinar"),
    "/projeto": ("loop.projeto", "/projeto", "loop_planning"),
    "/projeto-template": ("loop.projeto", "/projeto", "loop_planning"),
}


def _serializable_copy(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise LoopRuntimeError(
            "ERR_INPUT_REQUIRED",
            "%s must be JSON serializable." % label,
            retryable=True,
            details={"label": label, "reason": str(exc)},
        )


class HostAdapter:
    """Expose identical local, read-only orchestration on supported hosts."""

    def __init__(self, orchestrator: LoopOrchestrator, host_id: str) -> None:
        if host_id not in _HOSTS:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Unknown host adapter.",
                retryable=False,
                details={"host_id": host_id, "accepted": sorted(_HOSTS)},
            )
        if orchestrator is None or not callable(getattr(orchestrator, "resolve_command", None)):
            raise LoopRuntimeError(
                "ERR_RUNTIME_CONTRACT_DRIFT",
                "Host adapter requires a LoopOrchestrator-compatible object.",
                retryable=False,
            )
        self._orchestrator = orchestrator
        self._host_id = host_id

    def resolve(self, invocation: str) -> CommandResolution:
        expected = _COMMANDS.get(invocation)
        if expected is None:
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Unknown Loop Marketing command invocation.",
                retryable=True,
                details={"invocation": invocation, "accepted": sorted(_COMMANDS)},
            )
        resolved = self._orchestrator.resolve_command(invocation)
        actual = (
            getattr(resolved, "command_id", None),
            getattr(resolved, "canonical_invocation", None),
            getattr(resolved, "role_id", None),
        )
        if actual != expected or getattr(resolved, "invoked_as", None) != invocation:
            raise LoopRuntimeError(
                "ERR_RUNTIME_CONTRACT_DRIFT",
                "Orchestrator command resolution drifted from the sealed P5 table.",
                retryable=False,
                details={"invocation": invocation, "expected": list(expected), "actual": list(actual)},
            )
        return CommandResolution(
            command_id=expected[0],
            canonical_invocation=expected[1],
            invoked_as=invocation,
            role_id=expected[2],
        )

    def build_envelope(self, invocation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise LoopRuntimeError(
                "ERR_INPUT_REQUIRED",
                "Adapter payload must be a JSON object.",
                retryable=True,
                details={"payload_type": type(payload).__name__},
            )
        resolution = self.resolve(invocation)
        copied_payload = _serializable_copy(payload, "payload")
        config = getattr(self._orchestrator, "config", None)
        state_root = getattr(config, "state_root", None)
        if state_root is None:
            raise LoopRuntimeError(
                "ERR_RUNTIME_CONTRACT_DRIFT",
                "Orchestrator does not expose the canonical state root.",
                retryable=False,
            )
        operation = (
            "prepare_route"
            if resolution.command_id in ("loop.planning", "loop.projeto")
            else "prepare_specialist"
        )
        envelope = {
            "envelope_version": "1.0",
            "command": resolution.to_dict(),
            "operation": operation,
            "state": {
                "namespace": ".loop-marketing/",
                "root": str(state_root),
                "read_only": True,
            },
            "payload": copied_payload,
            "read_only": True,
            "external_write_authorized": False,
        }
        # Round-trip before returning so no host object can leak into the envelope.
        return _serializable_copy(envelope, "envelope")

    def invoke_read_only(self, invocation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        envelope = self.build_envelope(invocation, payload)
        command_id = envelope["command"]["command_id"]
        if command_id in ("loop.planning", "loop.projeto"):
            prepare_route = getattr(self._orchestrator, "prepare_route", None)
            if not callable(prepare_route):
                raise LoopRuntimeError(
                    "ERR_RUNTIME_CONTRACT_DRIFT",
                    "Orchestrator does not implement prepare_route.",
                    retryable=False,
                )
            result = prepare_route(envelope["payload"])
        else:
            specialist = getattr(self._orchestrator, "prepare_specialist", None)
            route_plan = envelope["payload"].get("route_plan")
            route_node_id = envelope["payload"].get("route_node_id")
            if not callable(specialist):
                raise LoopRuntimeError(
                    "ERR_RUNTIME_CONTRACT_DRIFT",
                    "Orchestrator does not implement prepare_specialist.",
                    retryable=False,
                )
            if not isinstance(route_plan, dict) or not isinstance(route_node_id, str) or not route_node_id:
                raise LoopRuntimeError(
                    "ERR_INPUT_REQUIRED",
                    "Specialist invocation requires route_plan and route_node_id.",
                    retryable=True,
                    details={"command_id": command_id},
                )
            matching_nodes = [
                item for item in route_plan.get("nodes", [])
                if isinstance(item, dict) and item.get("route_node_id") == route_node_id
            ]
            if len(matching_nodes) != 1 or matching_nodes[0].get("role_id") != envelope["command"]["role_id"]:
                raise LoopRuntimeError(
                    "ERR_OWNER_SCOPE_VIOLATION",
                    "Specialist command role must own the selected route node.",
                    retryable=False,
                    details={"command_id": command_id, "route_node_id": route_node_id},
                )
            result = specialist(route_plan, route_node_id)
        response = dict(envelope)
        response["result"] = _serializable_copy(result, "orchestrator result")
        return _serializable_copy(response, "adapter response")
