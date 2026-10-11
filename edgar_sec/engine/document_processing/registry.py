"""Handler registry for document processing.

This module binds handler IDs to actual callable implementations at runtime.
It is separate from the capability metadata in capabilities.py.
"""

from __future__ import annotations

from typing import Callable, Any, TypeVar

T = TypeVar("T")

# Runtime registry - maps handler_id to callable
_HANDLERS: dict[str, Callable[..., Any]] = {}


def register(handler_id: str, version: str) -> Callable[[T], T]:
    """Decorator to register a handler function."""

    def decorator(func: T) -> T:
        _HANDLERS[handler_id] = func
        return func

    return decorator


def get_handler(handler_id: str) -> Callable[..., Any] | None:
    """Get a handler by ID."""
    return _HANDLERS.get(handler_id)


def has_handler(handler_id: str) -> bool:
    """Check if a handler is registered."""
    return handler_id in _HANDLERS


def list_handlers() -> list[str]:
    """List all registered handler IDs."""
    return list(_HANDLERS.keys())


def clear() -> None:
    """Clear all registered handlers. For testing only."""
    _HANDLERS.clear()


__all__ = [
    "clear",
    "get_handler",
    "has_handler",
    "list_handlers",
    "register",
]
