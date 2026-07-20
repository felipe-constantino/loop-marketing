"""Security-enforcing facade for every operation exposed by the internal release."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .errors import LoopRuntimeError
from .models import RuntimeConfig
from .observability import AuditCollector
from .orchestrator import LoopOrchestrator
from .security import (
    DEFAULT_JSON_BUDGETS,
    JsonBudgets,
    PermissionGuard,
    SecurityContext,
    safe_error,
    safe_fingerprint,
    sanitize_structure,
    validate_and_copy_json,
    validate_runtime_config,
)


_RELEASE_POLICY = {
    "command.resolve": frozenset(("read_only",)),
    "permission.check": frozenset(("read_only",)),
    "project.initialize": frozenset(("local_state",)),
    "project.read": frozenset(("read_only", "local_state")),
    "route.prepare": frozenset(("read_only",)),
    "specialist.prepare": frozenset(("read_only",)),
    "handoff.validate": frozenset(("read_only",)),
    "transaction.integrate": frozenset(("local_state",)),
}


class SecureLoopRuntime:
    """Expose the complete local workflow through one closed, secret-safe facade."""

    def __init__(
        self,
        config: RuntimeConfig,
        budgets: JsonBudgets = DEFAULT_JSON_BUDGETS,
        audit_collector: Optional[AuditCollector] = None,
    ) -> None:
        validate_runtime_config(config)
        self._budgets = budgets
        self._permissions = PermissionGuard(_RELEASE_POLICY)
        self._audit = AuditCollector() if audit_collector is None else audit_collector
        if type(self._audit) is not AuditCollector:
            raise LoopRuntimeError(
                "ERR_AUDIT_CONFIG",
                "The runtime audit collector is invalid.",
            )
        self._library_root = Path(config.library_root).expanduser().absolute()
        self._orchestrator = LoopOrchestrator(config)

    def _safe_call(self, operation: str, permission: str, function: Callable[[], Any]) -> Any:
        try:
            context = SecurityContext.for_operation(operation, permission)
            self._permissions.require_context(context)
            result = self._output(function())
            self._emit_audit(operation, permission, result=result)
            return result
        except LoopRuntimeError as exc:
            self._emit_audit(operation, permission, error=exc)
            raise safe_error(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                details=exc.details,
                budgets=self._budgets,
            ) from None
        except Exception as exc:
            self._emit_audit(operation, permission, error=exc)
            raise safe_error(
                "ERR_RUNTIME_INTERNAL",
                "The secure runtime could not complete the operation.",
                budgets=self._budgets,
            ) from None

    def _emit_audit(
        self,
        operation: str,
        permission: str,
        *,
        result: Any = None,
        error: Optional[BaseException] = None,
    ) -> None:
        if not self._audit.enabled:
            return
        mapping = {
            "command.resolve": ("permission_evaluated", "security", "permission"),
            "permission.check": ("permission_evaluated", "security", "permission"),
            "project.initialize": ("integration_evaluated", "integration", "aggregate"),
            "project.read": ("integration_evaluated", "integration", "aggregate"),
            "route.prepare": ("route_evaluated", "router", "routing"),
            "specialist.prepare": ("route_evaluated", "specialist", "routing"),
            "handoff.validate": ("handoff_evaluated", "handoff", "evidence"),
            "transaction.integrate": ("integration_evaluated", "integration", "aggregate"),
        }
        event_type, component, audit_operation = mapping.get(
            operation, ("permission_evaluated", "security", "permission")
        )
        if error is not None:
            code = getattr(error, "code", "ERR_RUNTIME_INTERNAL")
            security_denial = str(code).startswith("ERR_SECURITY") or str(code).startswith("ERR_EXTERNAL")
            self._audit.emit(
                "security_denial" if security_denial else event_type,
                "denied" if security_denial else "error",
                dimensions={
                    "component": "security" if security_denial else component,
                    "operation": "safety" if security_denial else audit_operation,
                    "permission": permission,
                    "error_family": "safety" if security_denial else "internal",
                },
                metrics={"violation_count": 1},
            )
            return
        outcome = "passed"
        if type(result) is dict:
            status = result.get("route_status", result.get("status"))
            if status in ("needs_evidence", "blocked"):
                outcome = "blocked"
            elif status in ("rejected", "failed") or result.get("ok") is False:
                outcome = "failed"
        item_count = len(result) if type(result) in (dict, list) else 1
        self._audit.emit(
            event_type,
            outcome,
            dimensions={
                "component": component,
                "operation": audit_operation,
                "permission": permission,
                "error_family": "none",
            },
            metrics={"item_count": item_count, "violation_count": 0},
        )

    def _output(self, value: Any) -> Any:
        copied = validate_and_copy_json(value, self._budgets)
        sanitized = sanitize_structure(copied, self._budgets)
        if sanitized != copied:
            raise safe_error(
                "ERR_SECURITY_SENSITIVE_OUTPUT",
                "The runtime blocked a sensitive value from the public output.",
                budgets=self._budgets,
            )
        encoded = json.dumps(
            copied,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 2_097_152:
            raise safe_error(
                "ERR_SECURITY_OUTPUT_SIZE",
                "The runtime output exceeds the configured byte limit.",
                details={"limit": 2_097_152},
                budgets=self._budgets,
            )
        return copied

    def _reverify_prompt(self, document: Mapping[str, Any]) -> None:
        relative = document.get("canonical_path")
        expected_hash = document.get("canonical_sha256")
        expected_body = document.get("prompt_body")
        if type(relative) is not str or type(expected_hash) is not str or type(expected_body) is not str:
            raise LoopRuntimeError(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "Selected canonical prompt metadata is incomplete.",
            )
        path = self._library_root.joinpath(*Path(relative).parts)
        root = self._library_root.resolve()
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_ESCAPE",
                "A selected prompt path escapes the trusted library root.",
            )
        try:
            path.resolve().relative_to(root)
        except ValueError:
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_ESCAPE",
                "A selected prompt path escapes the trusted library root.",
            ) from None
        current = root
        for part in Path(relative).parts:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except OSError:
                raise LoopRuntimeError(
                    "ERR_CANONICAL_LIBRARY_DRIFT",
                    "A selected canonical prompt is unavailable.",
                ) from None
            if stat.S_ISLNK(mode):
                raise LoopRuntimeError(
                    "ERR_SECURITY_PATH_INVALID",
                    "A selected canonical prompt path contains a symlink.",
                )
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > 262_144:
                raise LoopRuntimeError(
                    "ERR_SECURITY_PROMPT_SIZE",
                    "A selected prompt violates the trusted file policy.",
                )
            chunks = []
            remaining = 262_145
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
        try:
            body = raw.decode("utf-8")
        except UnicodeError:
            raise LoopRuntimeError(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "A selected canonical prompt is not valid UTF-8.",
            ) from None
        if hashlib.sha256(raw).hexdigest() != expected_hash or body != expected_body:
            raise LoopRuntimeError(
                "ERR_CANONICAL_LIBRARY_DRIFT",
                "A selected canonical prompt failed descriptor verification.",
            )

    def _input(self, value: Any, label: str, operation: str, permission: str) -> Any:
        try:
            copied = validate_and_copy_json(value, self._budgets)
            sanitized = sanitize_structure(copied, self._budgets)
            if sanitized != copied:
                raise safe_error(
                    "ERR_SECURITY_SENSITIVE_INPUT",
                    "Sensitive values are not accepted in runtime control payloads.",
                    retryable=True,
                    details={
                        "input": label,
                        "sanitized_fingerprint": safe_fingerprint(sanitized, self._budgets),
                    },
                    budgets=self._budgets,
                )
            return copied
        except LoopRuntimeError as exc:
            self._emit_audit(operation, permission, error=exc)
            raise safe_error(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                details=exc.details,
                budgets=self._budgets,
            ) from None

    def resolve_command(self, invocation: str) -> Dict[str, Any]:
        value = self._input({"invocation": invocation}, "command", "command.resolve", "read_only")
        return self._safe_call(
            "command.resolve",
            "read_only",
            lambda: self._orchestrator.resolve_command(value["invocation"]).to_dict(),
        )

    def check_permission(self, operation: str, requested_mode: str) -> Dict[str, Any]:
        """Evaluate a permission request without exposing an execution callback."""

        value = self._input(
            {"operation": operation, "requested_mode": requested_mode},
            "permission_request",
            "permission.check",
            "read_only",
        )

        def check() -> Dict[str, Any]:
            self._permissions.require(value["operation"], value["requested_mode"])
            return {
                "operation": value["operation"],
                "requested_mode": value["requested_mode"],
                "decision": "allowed",
                "external_mutation_executed": False,
            }

        return self._safe_call("permission.check", "read_only", check)

    def initialize_project(self, project_id: str, display_name: str) -> Dict[str, Any]:
        value = self._input(
            {"project_id": project_id, "display_name": display_name},
            "project",
            "project.initialize",
            "local_state",
        )
        return self._safe_call(
            "project.initialize",
            "local_state",
            lambda: self._orchestrator.store.initialize_project(
                value["project_id"], value["display_name"]
            ),
        )

    def read_project(self, project_id: str) -> Dict[str, Any]:
        value = self._input({"project_id": project_id}, "project", "project.read", "read_only")
        return self._safe_call(
            "project.read",
            "read_only",
            lambda: self._orchestrator.store.replay(value["project_id"]),
        )

    def prepare_route(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        value = self._input(request, "route_request", "route.prepare", "read_only")
        return self._safe_call(
            "route.prepare",
            "read_only",
            lambda: self._orchestrator.prepare_route(value),
        )

    def prepare_specialist(
        self,
        route_plan: Mapping[str, Any],
        route_node_id: str,
    ) -> Dict[str, Any]:
        value = self._input(
            {"route_plan": route_plan, "route_node_id": route_node_id},
            "specialist_request",
            "specialist.prepare",
            "read_only",
        )
        envelope = self._safe_call(
            "specialist.prepare",
            "read_only",
            lambda: self._orchestrator.prepare_specialist(
                value["route_plan"], value["route_node_id"]
            ),
        )
        prompt_total = 0
        for document in envelope.get("prompt_documents", []):
            self._reverify_prompt(document)
            body = document.get("prompt_body", "")
            body_size = len(body.encode("utf-8")) if type(body) is str else 0
            if body_size > 262_144:
                raise safe_error(
                    "ERR_SECURITY_PROMPT_SIZE",
                    "A selected prompt exceeds the configured byte limit.",
                    details={"limit": 262_144},
                    budgets=self._budgets,
                )
            prompt_total += body_size
            document["prompt_content_trust"] = "untrusted_tactical_data"
            document["external_mutation_allowed"] = False
        if prompt_total > 524_288:
            raise safe_error(
                "ERR_SECURITY_PROMPT_TOTAL_SIZE",
                "Selected prompts exceed the configured total byte limit.",
                details={"limit": 524_288},
                budgets=self._budgets,
            )
        envelope["execution_policy"] = {
            "prompt_content_is_authority": False,
            "credential_discovery_allowed": False,
            "external_mutation_allowed": False,
            "state_write_allowed": False,
        }
        return self._output(envelope)

    def validate_handoffs(
        self,
        route_plan: Mapping[str, Any],
        handoffs: Any,
    ) -> Dict[str, Any]:
        value = self._input(
            {"route_plan": route_plan, "handoffs": handoffs},
            "handoff_validation",
            "handoff.validate",
            "read_only",
        )
        return self._safe_call(
            "handoff.validate",
            "read_only",
            lambda: self._orchestrator.validate_staged_outputs(
                value["route_plan"], value["handoffs"]
            ),
        )

    def integrate(self, envelope: Mapping[str, Any]) -> Dict[str, Any]:
        """Validate handoffs, build one batch and commit it in the same process."""

        value = self._input(envelope, "integration_envelope", "transaction.integrate", "local_state")

        def operation() -> Dict[str, Any]:
            required = {"project_id", "route_plan", "handoffs", "events"}
            if set(value) != required:
                raise LoopRuntimeError(
                    "ERR_INPUT_REQUIRED",
                    "Integration envelope fields do not match the closed contract.",
                    retryable=True,
                    details={"required_fields": sorted(required)},
                )
            validation = self._orchestrator.validate_staged_outputs(
                value["route_plan"], value["handoffs"]
            )
            if not validation.get("ok"):
                return {
                    "status": "rejected",
                    "validation": sanitize_structure(validation, self._budgets),
                }
            transaction = self._orchestrator.build_transaction(
                value["route_plan"], value["events"]
            )
            committed = self._orchestrator.commit_transaction(
                value["project_id"], transaction
            )
            return {
                "status": committed["status"],
                "state_revision": committed["state_revision"],
                "transaction_id": transaction["transaction_id"],
                "record_hash": transaction["record_hash"],
                "validated_handoff_ids": validation["validated_handoff_ids"],
                "snapshot": committed["snapshot"],
            }

        return self._safe_call("transaction.integrate", "local_state", operation)


__all__ = ("SecureLoopRuntime",)
