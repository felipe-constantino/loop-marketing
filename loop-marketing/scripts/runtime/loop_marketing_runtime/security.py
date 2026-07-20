"""Small, dependency-free security boundary for untrusted runtime data.

This module deliberately treats every string as inert data.  It does not
parse prompts, inspect canonical bodies, access the network or execute input.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from .errors import LoopRuntimeError


_JSON_SCALAR_TYPES = (type(None), bool, int, float, str)
_PERMISSIONS = frozenset(("read_only", "local_state", "external_mutation"))


@dataclass(frozen=True)
class JsonBudgets:
    """Hard limits applied while validating and copying a JSON-like value."""

    max_depth: int = 32
    max_nodes: int = 20_000
    max_string_length: int = 65_536
    max_total_string_utf8_bytes: int = 1_048_576
    max_key_utf8_bytes: int = 256
    max_integer_decimal_digits: int = 128
    max_array_length: int = 2_000
    max_object_length: int = 512

    def __post_init__(self) -> None:
        for field_name in (
            "max_depth",
            "max_nodes",
            "max_string_length",
            "max_total_string_utf8_bytes",
            "max_key_utf8_bytes",
            "max_integer_decimal_digits",
            "max_array_length",
            "max_object_length",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise LoopRuntimeError(
                    "ERR_SECURITY_CONFIG_INVALID",
                    "A JSON security budget is invalid.",
                    details={"budget": field_name},
                )


DEFAULT_JSON_BUDGETS = JsonBudgets()


@dataclass(frozen=True)
class SecurityContext:
    """Out-of-band operation authority created by the secure facade only."""

    operation: str
    effective_mode: str
    request_id: str
    host_id: str = "internal_release"

    @classmethod
    def for_operation(cls, operation: str, effective_mode: str) -> "SecurityContext":
        if type(operation) is not str or type(effective_mode) is not str:
            raise LoopRuntimeError(
                "ERR_SECURITY_CONFIG_INVALID",
                "The security context is invalid.",
            )
        return cls(
            operation=operation,
            effective_mode=effective_mode,
            request_id=uuid.uuid4().hex,
        )


def _json_error(code: str, message: str, **details: Any) -> LoopRuntimeError:
    # Details are intentionally limited to fixed labels and integer counts.
    return LoopRuntimeError(code, message, details=details)


def validate_and_copy_json(
    value: Any,
    budgets: JsonBudgets = DEFAULT_JSON_BUDGETS,
) -> Any:
    """Validate an untrusted JSON-like value and return a defensive copy.

    Only exact stdlib JSON container/scalar types are accepted.  This prevents
    custom ``Mapping``/``Sequence`` implementations, properties and iteration
    hooks from running inside the security boundary.
    """

    if type(budgets) is not JsonBudgets:
        raise _json_error(
            "ERR_SECURITY_CONFIG_INVALID",
            "The JSON security budgets are invalid.",
            budget="budgets",
        )

    node_count = 0
    total_string_utf8_bytes = 0
    active_containers = set()

    def copy_node(node: Any, depth: int) -> Any:
        nonlocal node_count, total_string_utf8_bytes
        if depth > budgets.max_depth:
            raise _json_error(
                "ERR_SECURITY_JSON_DEPTH",
                "JSON nesting exceeds the configured limit.",
                limit=budgets.max_depth,
            )
        node_count += 1
        if node_count > budgets.max_nodes:
            raise _json_error(
                "ERR_SECURITY_JSON_NODES",
                "JSON node count exceeds the configured limit.",
                limit=budgets.max_nodes,
            )

        node_type = type(node)
        if node_type in _JSON_SCALAR_TYPES:
            if node_type is str:
                encoded_size = len(node.encode("utf-8"))
                if len(node) > budgets.max_string_length or encoded_size > budgets.max_string_length:
                    raise _json_error(
                        "ERR_SECURITY_JSON_STRING_SIZE",
                        "A JSON string exceeds the configured limit.",
                        limit=budgets.max_string_length,
                    )
                total_string_utf8_bytes += encoded_size
                if total_string_utf8_bytes > budgets.max_total_string_utf8_bytes:
                    raise _json_error(
                        "ERR_SECURITY_JSON_TOTAL_STRING_SIZE",
                        "Total JSON string bytes exceed the configured limit.",
                        limit=budgets.max_total_string_utf8_bytes,
                    )
                return node
            if node_type is float and not math.isfinite(node):
                raise _json_error(
                    "ERR_SECURITY_JSON_NON_FINITE",
                    "Non-finite JSON numbers are not allowed.",
                )
            if node_type is int and abs(node) >= 10 ** budgets.max_integer_decimal_digits:
                raise _json_error(
                    "ERR_SECURITY_JSON_INTEGER_SIZE",
                    "A JSON integer exceeds the configured decimal-digit limit.",
                    limit=budgets.max_integer_decimal_digits,
                )
            return node

        if node_type not in (list, dict):
            raise _json_error(
                "ERR_SECURITY_JSON_TYPE",
                "Unsupported JSON value type.",
                kind="unsupported",
            )

        identity = id(node)
        if identity in active_containers:
            raise _json_error(
                "ERR_SECURITY_JSON_CYCLE",
                "Cyclic JSON containers are not allowed.",
            )
        active_containers.add(identity)
        try:
            if node_type is list:
                if len(node) > budgets.max_array_length:
                    raise _json_error(
                        "ERR_SECURITY_JSON_ARRAY_SIZE",
                        "A JSON array exceeds the configured limit.",
                        limit=budgets.max_array_length,
                    )
                return [copy_node(item, depth + 1) for item in node]

            if len(node) > budgets.max_object_length:
                raise _json_error(
                    "ERR_SECURITY_JSON_OBJECT_SIZE",
                    "A JSON object exceeds the configured limit.",
                    limit=budgets.max_object_length,
                )
            copied: Dict[str, Any] = {}
            for key, item in node.items():
                if type(key) is not str:
                    raise _json_error(
                        "ERR_SECURITY_JSON_KEY_TYPE",
                        "JSON object keys must be strings.",
                    )
                key_size = len(key.encode("utf-8"))
                if len(key) > budgets.max_string_length:
                    raise _json_error(
                        "ERR_SECURITY_JSON_STRING_SIZE",
                        "A JSON string exceeds the configured limit.",
                        limit=budgets.max_string_length,
                    )
                if key_size > budgets.max_key_utf8_bytes:
                    raise _json_error(
                        "ERR_SECURITY_JSON_KEY_SIZE",
                        "A JSON object key exceeds the configured limit.",
                        limit=budgets.max_key_utf8_bytes,
                    )
                total_string_utf8_bytes += key_size
                if total_string_utf8_bytes > budgets.max_total_string_utf8_bytes:
                    raise _json_error(
                        "ERR_SECURITY_JSON_TOTAL_STRING_SIZE",
                        "Total JSON string bytes exceed the configured limit.",
                        limit=budgets.max_total_string_utf8_bytes,
                    )
                copied[key] = copy_node(item, depth + 1)
            return copied
        finally:
            active_containers.remove(identity)

    try:
        return copy_node(value, 0)
    except RecursionError as exc:
        # Fail closed even if a caller deliberately configures a depth beyond
        # the Python interpreter's recursion capacity.
        raise _json_error(
            "ERR_SECURITY_JSON_DEPTH",
            "JSON nesting exceeds the safe processing limit.",
        ) from exc


_DEFAULT_PERMISSION_POLICY: Mapping[str, FrozenSet[str]] = MappingProxyType(
    {
        "catalog.read": frozenset(("read_only",)),
        "contract.validate": frozenset(("read_only",)),
        "route.resolve": frozenset(("read_only",)),
        "route.prepare": frozenset(("read_only",)),
        "state.read": frozenset(("read_only", "local_state")),
        "state.write": frozenset(("local_state",)),
        "state.lock": frozenset(("local_state",)),
        "telemetry.prepare": frozenset(("read_only",)),
        "telemetry.write": frozenset(("local_state",)),
    }
)


class PermissionGuard:
    """Deny-by-default guard over a closed operation/permission policy."""

    __slots__ = ("_policy",)

    def __init__(
        self,
        policy: Optional[Mapping[str, FrozenSet[str]]] = None,
    ) -> None:
        source = _DEFAULT_PERMISSION_POLICY if policy is None else policy
        if not isinstance(source, Mapping):
            raise LoopRuntimeError(
                "ERR_SECURITY_CONFIG_INVALID",
                "The permission policy is invalid.",
            )
        normalized: Dict[str, FrozenSet[str]] = {}
        for operation, permissions in source.items():
            if type(operation) is not str or not operation:
                raise LoopRuntimeError(
                    "ERR_SECURITY_CONFIG_INVALID",
                    "The permission policy is invalid.",
                )
            try:
                allowed = frozenset(permissions)
            except TypeError as exc:
                raise LoopRuntimeError(
                    "ERR_SECURITY_CONFIG_INVALID",
                    "The permission policy is invalid.",
                ) from exc
            if not allowed or not allowed.issubset(_PERMISSIONS - {"external_mutation"}):
                raise LoopRuntimeError(
                    "ERR_SECURITY_CONFIG_INVALID",
                    "The permission policy is invalid.",
                )
            normalized[operation] = allowed
        self._policy = MappingProxyType(normalized)

    def require(self, operation: str, permission: str) -> None:
        """Allow a declared local/read action or raise a stable safe error."""

        if permission == "external_mutation":
            raise LoopRuntimeError(
                "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
                "External mutation is not authorized by the local runtime.",
            )
        if (
            type(operation) is not str
            or type(permission) is not str
            or permission not in _PERMISSIONS
            or permission not in self._policy.get(operation, frozenset())
        ):
            raise LoopRuntimeError(
                "ERR_SECURITY_PERMISSION_DENIED",
                "The runtime operation is not permitted.",
            )

    def require_context(self, context: SecurityContext) -> None:
        """Validate a trusted, out-of-band context against the closed policy."""

        if type(context) is not SecurityContext or not re.fullmatch(r"[0-9a-f]{32}", context.request_id):
            raise LoopRuntimeError(
                "ERR_SECURITY_CONTEXT_INVALID",
                "The runtime security context is invalid.",
            )
        self.require(context.operation, context.effective_mode)


DEFAULT_PERMISSION_GUARD = PermissionGuard()


def validate_runtime_config(config: Any) -> None:
    """Validate trusted runtime roots before any contract or prompt is read."""

    required = (
        "library_root",
        "catalog_path",
        "relationship_path",
        "role_matrix_path",
        "routing_contract_path",
        "state_root",
        "contracts_root",
    )
    if any(not hasattr(config, field) for field in required):
        raise LoopRuntimeError(
            "ERR_SECURITY_CONFIG_INVALID",
            "The runtime path configuration is incomplete.",
        )

    def path_value(field: str) -> Path:
        value = getattr(config, field)
        if not isinstance(value, (str, os.PathLike)):
            raise LoopRuntimeError(
                "ERR_SECURITY_CONFIG_INVALID",
                "A runtime path has an invalid type.",
                details={"path_class": field},
            )
        return Path(value).expanduser().absolute()

    library_root = path_value("library_root")
    contracts_root = path_value("contracts_root")
    state_root = path_value("state_root")
    data_files = tuple(path_value(field) for field in required[1:5])
    runtime_root = data_files[0].parent.parent

    for path_class, root in (
        ("library_root", library_root),
        ("runtime_root", runtime_root),
        ("contracts_root", contracts_root),
    ):
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A trusted runtime root is unavailable.",
                details={"path_class": path_class, "error_type": type(exc).__name__},
            ) from None
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A trusted runtime root has an invalid file type.",
                details={"path_class": path_class},
            )

    runtime_resolved = runtime_root.resolve()
    if contracts_root.resolve().parent != runtime_resolved:
        raise LoopRuntimeError(
            "ERR_SECURITY_PATH_ESCAPE",
            "The contracts root is outside the trusted runtime root.",
        )
    for file_path in data_files:
        try:
            file_stat = file_path.lstat()
        except OSError as exc:
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A required runtime data file is unavailable.",
                details={"path_class": "runtime_data", "error_type": type(exc).__name__},
            ) from None
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or not stat.S_ISREG(file_stat.st_mode)
            or file_path.resolve().parent != (runtime_resolved / "data")
            or file_stat.st_size > 2_097_152
        ):
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A required runtime data file violates the trusted path policy.",
                details={"path_class": "runtime_data"},
            )

    expected_contracts = ("state-schema.json", "event-schema.json", "handoff-schema.json")
    for name in expected_contracts:
        contract_path = contracts_root / name
        try:
            contract_stat = contract_path.lstat()
        except OSError as exc:
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A required runtime contract is unavailable.",
                details={"path_class": "runtime_contract", "error_type": type(exc).__name__},
            ) from None
        if (
            stat.S_ISLNK(contract_stat.st_mode)
            or not stat.S_ISREG(contract_stat.st_mode)
            or contract_path.resolve().parent != contracts_root.resolve()
            or contract_stat.st_size > 2_097_152
        ):
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_INVALID",
                "A required runtime contract violates the trusted path policy.",
                details={"path_class": "runtime_contract"},
            )

    if state_root.exists() and state_root.is_symlink():
        raise LoopRuntimeError(
            "ERR_SECURITY_PATH_INVALID",
            "The state root cannot be a symlink.",
            details={"path_class": "state_root"},
        )
    state_resolved = state_root.resolve()
    for protected_root in (library_root.resolve(), runtime_resolved):
        if (
            state_resolved == protected_root
            or state_resolved in protected_root.parents
            or protected_root in state_resolved.parents
        ):
            raise LoopRuntimeError(
                "ERR_SECURITY_PATH_OVERLAP",
                "The state root overlaps a protected read-only root.",
            )


def guard_permission(operation: str, permission: str) -> None:
    """Apply the default closed permission policy."""

    DEFAULT_PERMISSION_GUARD.require(operation, permission)


_SECRET_KEYS = frozenset(
    {
        "apikey",
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "bearertoken",
        "clientsecret",
        "credential",
        "credentials",
        "connectionpassword",
        "cookie",
        "password",
        "passwd",
        "privatekey",
        "secret",
        "secretkey",
        "sessiontoken",
        "sessionid",
        "setcookie",
    }
)
_AUTH_KEYS = frozenset(
    {"auth", "authorization", "authorizationheader", "proxyauthorization"}
)
_EMAIL_KEYS = frozenset({"email", "emailaddress", "contactemail"})
_PHONE_KEYS = frozenset({"phone", "phonenumber", "telephone", "mobile", "cellphone"})
_PII_KEYS = frozenset(
    {
        "address",
        "birthdate",
        "cpf",
        "dateofbirth",
        "documentnumber",
        "fullname",
        "homeaddress",
        "ipaddress",
        "nationalid",
        "personname",
        "postalcode",
        "ssn",
        "taxid",
    }
)

_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*"
    r"(?:bearer\s+|basic\s+|token\s+)?[^\s,;]+"
)
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|password|passwd|secret|token|cookie|session[_-]?id)\s*[:=]\s*[^\s,;]+"
)
_KNOWN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"sk-[A-Za-z0-9_-]{16,}|"
    r"AKIA[0-9A-Z]{16}"
    r")(?![A-Za-z0-9])"
)
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\."
    r"[A-Za-z0-9_-]{4,}(?![A-Za-z0-9_-])"
)
_PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_CREDENTIAL_URL_RE = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]{1,128}:[^\s/@]{1,256}@"
)
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(\d{2,3}\)|\d{2,3})"
    r"[ .-]?\d{4,5}[ .-]?\d{4}(?!\w)"
)
_CPF_RE = re.compile(
    r"(?<![A-Za-z0-9])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![A-Za-z0-9])"
)
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:file://)?(?:/Users|/home|/private|/tmp|/var/tmp|"
    r"/var/folders)/[^\s,;]+"
)
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\(?:Users|Documents and Settings)\\|"
    r"\\\\[^\\\s]+\\[^\\\s]+\\)[^\s,;]+"
)


def _normalized_key(key: str) -> str:
    return "".join(character.lower() for character in key if character.isalnum())


def _key_marker(key: str) -> Optional[str]:
    normalized = _normalized_key(key)
    if normalized in _AUTH_KEYS:
        return "<REDACTED:AUTH>"
    if normalized in _SECRET_KEYS or normalized.endswith("secret") or normalized.endswith("token"):
        return "<REDACTED:SECRET>"
    if normalized in _EMAIL_KEYS or normalized.endswith("email"):
        return "<REDACTED:EMAIL>"
    if normalized in _PHONE_KEYS or normalized.endswith("phone"):
        return "<REDACTED:PHONE>"
    if normalized in _PII_KEYS:
        return "<REDACTED:PII>"
    return None


def sanitize_message(message: str) -> str:
    """Redact credentials, contact data and sensitive local paths in text."""

    if type(message) is not str:
        raise _json_error(
            "ERR_SECURITY_JSON_TYPE",
            "A telemetry message must be a string.",
            kind="unsupported",
        )
    result = _AUTH_HEADER_RE.sub(lambda match: "%s: <REDACTED:AUTH>" % match.group(1), message)
    result = _AUTH_SCHEME_RE.sub("<REDACTED:AUTH>", result)
    result = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: "%s=<REDACTED:SECRET>" % match.group(1), result
    )
    result = _KNOWN_TOKEN_RE.sub("<REDACTED:TOKEN>", result)
    result = _JWT_RE.sub("<REDACTED:TOKEN>", result)
    result = _PEM_PRIVATE_KEY_RE.sub("<REDACTED:SECRET>", result)
    result = _CREDENTIAL_URL_RE.sub("<REDACTED:SECRET>", result)
    result = _POSIX_PATH_RE.sub("<REDACTED:PATH>", result)
    result = _WINDOWS_PATH_RE.sub("<REDACTED:PATH>", result)
    result = _EMAIL_RE.sub("<REDACTED:EMAIL>", result)
    result = _PHONE_RE.sub("<REDACTED:PHONE>", result)
    result = _CPF_RE.sub("<REDACTED:PII>", result)
    return result


def sanitize_structure(
    value: Any,
    budgets: JsonBudgets = DEFAULT_JSON_BUDGETS,
) -> Any:
    """Return a validated, redacted copy suitable for telemetry or errors."""

    copied = validate_and_copy_json(value, budgets)

    def sanitize(node: Any) -> Any:
        node_type = type(node)
        if node_type is str:
            return sanitize_message(node)
        if node_type is list:
            return [sanitize(item) for item in node]
        if node_type is dict:
            output: Dict[str, Any] = {}
            for key, item in node.items():
                sanitized_key = sanitize_message(key)
                if sanitized_key != key:
                    sanitized_key = "<REDACTED:KEY>"
                if sanitized_key in output:
                    raise LoopRuntimeError(
                        "ERR_SECURITY_REDACTION_COLLISION",
                        "Redaction produced duplicate object keys.",
                    )
                marker = _key_marker(key)
                output[sanitized_key] = marker if marker is not None else sanitize(item)
            return output
        return node

    return sanitize(copied)


sanitize_for_telemetry = sanitize_structure
sanitize_error_details = sanitize_structure


def safe_fingerprint(value: Any, budgets: JsonBudgets = DEFAULT_JSON_BUDGETS) -> str:
    """Fingerprint only the sanitized canonical form, never a raw value."""

    sanitized = sanitize_structure(value, budgets)
    canonical = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:%s" % hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: Optional[Mapping[str, Any]] = None,
    budgets: JsonBudgets = DEFAULT_JSON_BUDGETS,
) -> LoopRuntimeError:
    """Build a ``LoopRuntimeError`` whose message and details are redacted."""

    if type(code) is not str or re.fullmatch(r"[A-Z][A-Z0-9_-]{2,63}", code) is None:
        raise LoopRuntimeError(
            "ERR_SECURITY_ERROR_CODE",
            "The runtime error code is invalid.",
        )
    if type(retryable) is not bool:
        raise LoopRuntimeError(
            "ERR_SECURITY_CONFIG_INVALID",
            "The runtime error retry policy is invalid.",
        )
    raw_details: Mapping[str, Any] = {} if details is None else details
    safe_details = sanitize_structure(raw_details, budgets)
    if type(safe_details) is not dict:
        raise LoopRuntimeError(
            "ERR_SECURITY_JSON_TYPE",
            "Runtime error details must be a JSON object.",
        )
    encoded = json.dumps(
        {"message": sanitize_message(message), "details": safe_details},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 8_192:
        safe_details = {}
        message = "The runtime rejected the operation safely."
    return LoopRuntimeError(
        code,
        sanitize_message(message),
        retryable=retryable,
        details=safe_details,
    )


__all__: Tuple[str, ...] = (
    "DEFAULT_JSON_BUDGETS",
    "DEFAULT_PERMISSION_GUARD",
    "JsonBudgets",
    "PermissionGuard",
    "SecurityContext",
    "guard_permission",
    "safe_error",
    "safe_fingerprint",
    "sanitize_error_details",
    "sanitize_for_telemetry",
    "sanitize_message",
    "sanitize_structure",
    "validate_runtime_config",
    "validate_and_copy_json",
)
