"""Frames lookups: SEC cross-company aggregates for one concept and period.

This is a cross-check surface only: values are SEC aggregates served with
their frame identity as provenance, never as per-filing facts. The join to
parsed per-filing facts exists only as the comparison below.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from edgar_sec.domain.sec_urls import frames_url
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted

__all__ = [
    "FrameComparison",
    "FrameComparisonRow",
    "FrameIdentity",
    "FrameResult",
    "FrameRow",
    "compare_frame_to_parsed",
    "fetch_frame",
]


@dataclass(frozen=True, slots=True)
class FrameIdentity:
    """The frame a result came from: its concept, unit, and period shape."""

    taxonomy: str
    tag: str
    unit: str
    period: str

    @property
    def is_instant(self) -> bool:
        """True for an instant period (the trailing ``I`` shape)."""
        return self.period[-1:] == "I"


@dataclass(frozen=True, slots=True)
class FrameRow:
    """One filer's SEC aggregate value in a frame, with frame provenance."""

    cik: int
    entity_name: str
    value: int | float
    end: str
    frame: FrameIdentity


@dataclass(frozen=True, slots=True)
class FrameResult:
    """One frame's aggregate rows; empty when the frame is absent."""

    frame: FrameIdentity
    label: str
    rows: tuple[FrameRow, ...]


def fetch_frame(
    taxonomy: str,
    tag: str,
    unit: str,
    period: str,
    *,
    client: SecHttpClient,
) -> FrameResult:
    """Fetch one frame's aggregate rows; empty when the frame is absent."""
    identity = FrameIdentity(taxonomy=taxonomy, tag=tag, unit=unit, period=period)
    url = frames_url(taxonomy, tag, unit, period)
    try:
        payload = client.get_json(url)
    except (PermanentHttpError, RetryExhausted):
        return FrameResult(frame=identity, label="", rows=())
    if not isinstance(payload, dict):
        return FrameResult(frame=identity, label="", rows=())
    data = payload.get("data")
    if not isinstance(data, list):
        return FrameResult(frame=identity, label="", rows=())
    rows: list[FrameRow] = []
    for point in data:
        if not isinstance(point, dict):
            continue
        value = point.get("val")
        cik = point.get("cik")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not isinstance(cik, int) or isinstance(cik, bool):
            continue
        rows.append(
            FrameRow(
                cik=cik,
                entity_name=str(point.get("entityName", "")),
                value=value,
                end=str(point.get("end", "")),
                frame=identity,
            )
        )
    return FrameResult(
        frame=identity,
        label=str(payload.get("label", "")),
        rows=tuple(rows),
    )


AGREE = "agree"
DIVERGE = "diverge"
FRAME_ONLY = "frame_only"
PARSED_ONLY = "parsed_only"


@dataclass(frozen=True, slots=True)
class FrameComparisonRow:
    """One CIK's cross-check outcome between the frame and parsed facts."""

    cik: int
    outcome: str
    frame_value: int | float | None
    parsed_value: float | None


@dataclass(frozen=True, slots=True)
class FrameComparison:
    """A frame cross-checked against parsed per-filing values, by CIK."""

    frame: FrameIdentity
    rows: tuple[FrameComparisonRow, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Outcome counts over the compared CIK set."""
        counts = {AGREE: 0, DIVERGE: 0, FRAME_ONLY: 0, PARSED_ONLY: 0}
        for row in self.rows:
            counts[row.outcome] += 1
        return counts

    @property
    def agreement_rate(self) -> float | None:
        """Agreements over CIKs present on both sides; None when disjoint."""
        counts = self.counts
        both = counts[AGREE] + counts[DIVERGE]
        if both == 0:
            return None
        return counts[AGREE] / both


def compare_frame_to_parsed(
    result: FrameResult,
    parsed_by_cik: Mapping[int, float | None],
) -> FrameComparison:
    """Compare frame aggregates with parsed per-filing values, CIK by CIK.

    A parsed value of None (or a missing CIK) is an absence, not a zero:
    the row is frame-only, never a divergence.
    """
    rows: list[FrameComparisonRow] = []
    frame_ciks: set[int] = set()
    for row in result.rows:
        frame_ciks.add(row.cik)
        parsed = parsed_by_cik.get(row.cik)
        if parsed is None:
            outcome = FRAME_ONLY
        elif float(row.value) == float(parsed):
            outcome = AGREE
        else:
            outcome = DIVERGE
        rows.append(
            FrameComparisonRow(
                cik=row.cik,
                outcome=outcome,
                frame_value=row.value,
                parsed_value=parsed,
            )
        )
    for cik in sorted(set(parsed_by_cik) - frame_ciks):
        parsed = parsed_by_cik[cik]
        if parsed is None:
            continue
        rows.append(
            FrameComparisonRow(
                cik=cik,
                outcome=PARSED_ONLY,
                frame_value=None,
                parsed_value=parsed,
            )
        )
    return FrameComparison(frame=result.frame, rows=tuple(rows))
