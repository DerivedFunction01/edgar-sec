"""Cover cluster start detection and evidence scanning.

The cover *start* is the first line of a connected cover-shaped cluster, not the
first matched label: SEC filings front-load boilerplate, so anchoring on the
first identity hit would start the cover too late and pull a heading into the
body region.
"""

from __future__ import annotations

import re

from edgar_sec.domain.forms.vocabulary import (
    COVER_START_IDENTITY_TERMS,
    COVER_START_SHAPE_TERMS,
)
from edgar_sec.engine.forms.cover.models import (
    BoundaryEvidence,
    BoundarySignal,
    CoverBoundaryPolicy,
    CoverStart,
)
from edgar_sec.foundation.regex.builder import build_alternation

_COVER_START_SEARCH_WINDOW = 60
_COVER_START_CLUSTER_GAP = 5

_RE_COVER_START_IDENTITY = re.compile(
    build_alternation(
        COVER_START_IDENTITY_TERMS, auto_escape=False, never_match_empty=True
    ),
    re.IGNORECASE,
)
_RE_COVER_START_SHAPE = re.compile(
    build_alternation(
        COVER_START_SHAPE_TERMS, auto_escape=True, never_match_empty=True
    ),
    re.IGNORECASE,
)


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _scan_cover_start_cluster(lines: list[str]) -> CoverStart | None:
    """Find a connected cover-shaped cluster in the opening window.

    The cluster requires at least one generic identity signal plus one
    cover-shape signal within a bounded window.
    """
    evidence: list[BoundaryEvidence] = []
    first_identity: int | None = None
    first_shape: int | None = None
    cluster_start: int | None = None
    last_signal = -_COVER_START_CLUSTER_GAP - 1

    for index, line in enumerate(lines[:_COVER_START_SEARCH_WINDOW]):
        is_identity = bool(_RE_COVER_START_IDENTITY.search(line))
        is_shape = bool(_RE_COVER_START_SHAPE.search(line))
        if not (is_identity or is_shape):
            continue
        if index - last_signal > _COVER_START_CLUSTER_GAP:
            if (
                cluster_start is not None
                and first_identity is not None
                and first_shape is not None
            ):
                return CoverStart(
                    start_line=cluster_start,
                    start_offset=_line_offset(lines, cluster_start),
                    evidence=tuple(evidence),
                )
            cluster_start = index
            evidence = []
            first_identity = None
            first_shape = None
        last_signal = index
        if is_identity and first_identity is None:
            first_identity = index
            evidence.append(
                BoundaryEvidence(
                    name="cover_start_identity",
                    strength=0.95,
                    line=index,
                    details="generic cover identity signal",
                )
            )
        if is_shape and first_shape is None:
            first_shape = index
            evidence.append(
                BoundaryEvidence(
                    name="cover_start_shape",
                    strength=0.85,
                    line=index,
                    details="cover-shape field signal",
                )
            )

    if (
        cluster_start is not None
        and first_identity is not None
        and first_shape is not None
    ):
        return CoverStart(
            start_line=cluster_start,
            start_offset=_line_offset(lines, cluster_start),
            evidence=tuple(evidence),
        )
    return None


def find_cover_start(text: str, policy: CoverBoundaryPolicy | None) -> CoverStart:
    """Find the inclusive start of a cover-shaped cluster.

    Returns an unknown start when the ``COVER_IDENTITY_AND_LAYOUT`` signal is
    not enabled, which disables cover parsing entirely.
    """
    if policy is None:
        return CoverStart(start_line=None, start_offset=None)
    if BoundarySignal.COVER_IDENTITY_AND_LAYOUT not in policy.signals:
        return CoverStart(start_line=None, start_offset=None)
    lines = text.splitlines()
    if not lines:
        return CoverStart(start_line=None, start_offset=None)
    result = _scan_cover_start_cluster(lines)
    if result is not None:
        return result
    return CoverStart(start_line=None, start_offset=None)


__all__ = ["CoverStart", "find_cover_start"]
