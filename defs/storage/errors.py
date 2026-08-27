"""Storage-layer error taxonomy.

All storage errors derive from :class:`StorageError` so callers can catch the
family without knowing which backend raised it.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base class for storage-layer failures."""


class SchemaMismatchError(StorageError):
    """A record or persisted artifact does not match the declared dataset schema."""


class UnsupportedCapability(StorageError):
    """The backend does not implement an optional capability."""

    def __init__(self, capability: str, backend: str = ""):
        self.capability = capability
        self.backend = backend
        super().__init__(
            f"backend {backend or '<unknown>'} does not support {capability}"
        )


class MalformedArtifact(StorageError):
    """A persisted artifact is unreadable or structurally invalid."""
