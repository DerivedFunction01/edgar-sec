"""Shared SEC cover-page concept registries, extraction primitives, and profiles."""

from __future__ import annotations

from defs.sec_forms.cover.extractors import (
    extract_candidate_ein,
    extract_commission_file_number,
    extract_fiscal_period,
)
from defs.sec_forms.cover.vocabulary import COVER_BOUNDARY_PHRASES, COVER_LABELS

__all__ = [
    "COVER_BOUNDARY_PHRASES",
    "COVER_LABELS",
    "COVER_PROFILES",
    "CoverProfile",
    "extract_candidate_ein",
    "extract_commission_file_number",
    "extract_fiscal_period",
    "get_profile",
]


def __getattr__(name: str):
    # Profile construction touches ``defs.tables`` (typed scope), which in turn
    # imports ``defs.sec_forms.patterns``. Loading it lazily here avoids a
    # circular import during ``defs.sec_forms`` package initialization.
    if name in {"COVER_PROFILES", "CoverProfile", "get_profile"}:
        from defs.sec_forms.cover import profiles as _profiles

        value = getattr(_profiles, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
