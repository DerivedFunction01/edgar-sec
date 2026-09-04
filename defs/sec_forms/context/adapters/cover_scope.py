"""Adapt a :class:`CoverBoundary` + :class:`CoverProfile` into a typed
:class:`defs.sec_forms.context.CoverScope`.

This module is the Phase-D "cover scope" integration. It deliberately does
not introduce a new cover detector; it only translates the existing
representation-neutral boundary + profile into a single value the table
layer can consume without importing the cover subsystem.
"""

from __future__ import annotations

from defs.sec_forms.context.models import ContextEvidence, CoverScope
from defs.sec_forms.cover.boundary import CoverBoundary
from defs.sec_forms.cover.profiles import CoverProfile

__all__ = ["build_cover_scope"]


def build_cover_scope(
    profile: CoverProfile | None,
    boundary: CoverBoundary | None,
) -> CoverScope:
    """Return a :class:`CoverScope` for a profile + boundary pair.

    A ``None`` profile or a profile with ``boundary is None`` yields an
    inactive cover scope. A ``None`` boundary on a profile that *does* set
    boundary capabilities (annual/quarterly) is still considered "active in
    intent" with the boundary's confidence carried through; callers needing
    strict gating can check ``cover_scope.start_line is not None``.
    """
    if profile is None or profile.boundary is None:
        return CoverScope(
            active=False,
            profile_family=(profile.family if profile is not None else "GENERIC"),
            confidence=0.0,
            evidence=(),
        )

    evidence: tuple[ContextEvidence, ...] = tuple(
        ContextEvidence(
            name=item.name,
            strength=item.strength,
            details=item.details,
            line=item.line,
        )
        for item in (boundary.evidence if boundary is not None else ())
    )
    confidence = boundary.confidence if boundary is not None else 0.0
    return CoverScope(
        active=True,
        profile_family=profile.family,
        confidence=confidence,
        evidence=evidence,
        start_line=boundary.start_line if boundary is not None else None,
        end_line=boundary.end_line if boundary is not None else None,
    )
