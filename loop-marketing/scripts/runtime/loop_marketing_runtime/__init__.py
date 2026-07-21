"""Loop Marketing v2.1 host-neutral runtime."""

from .errors import LoopRuntimeError
from .secure_adapters import SecureHostAdapter
from .secure_runtime import SecureLoopRuntime
from .models import (
    CommandResolution,
    RouteNode,
    RoutePlan,
    RuntimeConfig,
    TacticRef,
    TacticSelection,
    ValidationResult,
)

__all__ = [
    "CommandResolution",
    "LoopRuntimeError",
    "RouteNode",
    "RoutePlan",
    "RuntimeConfig",
    "TacticRef",
    "TacticSelection",
    "ValidationResult",
    "SecureHostAdapter",
    "SecureLoopRuntime",
]

__version__ = "2.1.0"
