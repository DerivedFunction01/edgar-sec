"""Typed exception classes for acquisition snapshot publication and lifecycle."""

from __future__ import annotations


class SnapshotError(ValueError):
    pass


class PublicationGateError(SnapshotError):
    pass


class RunNotPublishableError(SnapshotError):
    pass


class ReferentialIntegrityError(SnapshotError):
    pass


class SnapshotCleanupError(SnapshotError):
    pass


__all__ = [
    "PublicationGateError",
    "ReferentialIntegrityError",
    "RunNotPublishableError",
    "SnapshotCleanupError",
    "SnapshotError",
]
