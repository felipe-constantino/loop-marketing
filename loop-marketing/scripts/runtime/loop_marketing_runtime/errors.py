"""Structured, secret-safe runtime errors."""

from __future__ import annotations

from typing import Any, Dict, Optional


class LoopRuntimeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


def require(condition: bool, code: str, message: str, *, retryable: bool = False, **details: Any) -> None:
    if not condition:
        raise LoopRuntimeError(code, message, retryable=retryable, details=details)
