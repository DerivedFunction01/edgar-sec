"""Contract tests for the TOC span data models."""

from __future__ import annotations

import dataclasses

import pytest

from edgar_sec.engine.forms.cover.toc.models import TocEvidence, TocSpan


def test_evidence_rows_default_to_no_line_or_details() -> None:
    assert TocEvidence(name="toc_heading").line is None
    assert TocEvidence(name="toc_heading").details == ""


def test_span_is_exact_by_default_and_carries_both_frames() -> None:
    span = TocSpan(
        start_line=2,
        end_line=6,
        start_offset=20,
        end_offset=60,
        method="heading_rows",
        confidence=0.92,
    )

    assert span.approximate is False
    assert span.evidence == ()
    assert (span.start_offset, span.end_offset) == (20, 60)


def test_span_is_frozen() -> None:
    span = TocSpan(
        start_line=0,
        end_line=1,
        start_offset=0,
        end_offset=5,
        method="aligned_rows",
        confidence=0.7,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.start_line = 4  # type: ignore[misc]
