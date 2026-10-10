"""Typed results and errors for acquisition fixture storage."""

from __future__ import annotations

from dataclasses import dataclass


class FixtureStoreError(RuntimeError):
    """A fixture is missing, corrupt, incompatible, or conflicts with immutable evidence."""


@dataclass(frozen=True, slots=True)
class ResponseBodyRef:
    response_sha256: str
    byte_size: int
    stored_sha256: str
    stored_byte_size: int
    reused: bool
