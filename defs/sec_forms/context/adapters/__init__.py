"""Adapters that build :mod:`defs.sec_forms.context` models from existing
contract types.

These adapters do not introduce new detection logic. They translate the
existing :class:`defs.sec_forms.cover.boundary.CoverBoundary` and
:class:`defs.sec_forms.cover.profiles.CoverProfile` into the representation-
neutral :class:`defs.sec_forms.context.CoverScope`, and lift the existing
:class:`defs.sec_forms.cover.toc.models.TocSpan` into a list of typed
:class:`defs.sec_forms.context.TocReference` entries.
"""

from __future__ import annotations

from .cover_scope import build_cover_scope
from .toc_adapter import (
    TocEntry,
    extract_toc_references,
    lift_toc_span_to_references,
)

__all__ = [
    "TocEntry",
    "build_cover_scope",
    "extract_toc_references",
    "lift_toc_span_to_references",
]
