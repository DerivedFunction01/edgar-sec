"""Materialize Phase 2 catalog snapshots from a finalized Phase 1 artifact."""

from __future__ import annotations

from ..schemas import (
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from .engine import (
    FALLBACK_POLICY_VERSION,
    materialize,
)

__all__ = [
    "FALLBACK_POLICY_VERSION",
    "PROFILE_COLUMNS",
    "PROFILE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "materialize",
]
