"""Cover cluster start detection and evidence scanning."""

from __future__ import annotations

from defs.sec_forms.cover.models import (
    BoundaryEvidence,
    BoundaryInput,
    CoverBoundaryPolicy,
    CoverStart,
)
from defs.sec_forms.cover.rules import CompiledCoverRules, compile_cover_rules

_COVER_START_SEARCH_WINDOW = 60
_COVER_START_CLUSTER_GAP = 5


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _scan_cover_start_cluster(
    lines: list[str],
    *,
    enabled: bool,
    rules: CompiledCoverRules,
) -> CoverStart | None:
    """Find a connected cover-shaped cluster in the opening window.

    The cluster requires at least one generic identity signal plus one
    cover-shape signal within a bounded window. The start is the first line
    of the connected cluster, not the first matched label.
    """
    if not enabled:
        return None

    from defs.sec_forms.cover.boundary import BoundaryEvidence

    evidence: list[BoundaryEvidence] = []
    first_identity: int | None = None
    first_shape: int | None = None
    cluster_start = None
    last_signal = -_COVER_START_CLUSTER_GAP - 1

    for index, line in enumerate(lines[:_COVER_START_SEARCH_WINDOW]):
        is_identity = bool(rules.cover_start_identity.search(line))
        is_shape = bool(rules.cover_start_shape.search(line))
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


def find_cover_start(
    boundary_input: BoundaryInput | str,
    policy: CoverBoundaryPolicy | None,
    *,
    cover_evidence: object | None = None,
    body_evidence: object | None = None,
) -> CoverStart:
    """Find the inclusive start of a cover-shaped cluster.

    Returns a ``CoverStart`` with ``start_line`` set to the first line of the
    connected cover-shaped cluster. Requires the ``COVER_IDENTITY_AND_LAYOUT``
    signal to be enabled; otherwise returns an unknown start.
    """
    if policy is None:
        return CoverStart(start_line=None, start_offset=None)

    from defs.sec_forms.cover.boundary import BoundarySignal

    rules = compile_cover_rules(cover_evidence, body_evidence)

    text = boundary_input if isinstance(boundary_input, str) else boundary_input.text
    lines = text.splitlines()
    if not lines:
        return CoverStart(start_line=None, start_offset=None)

    result = _scan_cover_start_cluster(
        lines,
        enabled=BoundarySignal.COVER_IDENTITY_AND_LAYOUT in policy.signals,
        rules=rules,
    )
    return (
        result if result is not None else CoverStart(start_line=None, start_offset=None)
    )


__all__ = ["CoverStart", "_scan_cover_start_cluster", "find_cover_start"]
