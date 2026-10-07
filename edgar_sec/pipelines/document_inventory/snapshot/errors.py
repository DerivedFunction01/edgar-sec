"""Snapshot publication and query errors."""

from __future__ import annotations


class SnapshotError(RuntimeError):
    """Base for snapshot publication and query failures."""


class BaseSnapshotError(SnapshotError):
    """base_snapshot was invalid, missing, or incompatible."""


class InvalidAccessionError(SnapshotError):
    """An accession reference is malformed."""


class RefusalError(SnapshotError):
    """A staged worker outcome was a refusal; publication is not permitted."""


class ValidationFailedError(SnapshotError):
    """Staged snapshot failed row-count, digest, or referential checks."""


class StaleParentError(SnapshotError):
    """The current snapshot changed after this publication was prepared."""


class SnapshotNotFoundError(SnapshotError):
    """A snapshot id resolves to no published snapshot."""


class NoSnapshotPublishedError(SnapshotError):
    """No snapshot has been published yet; current pointer is absent."""
