"""Tests for the exhibit probe module."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity, EvidenceSpan
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    probe_exhibit_header,
)


def test_10_1_exhibit_probe():
    """Probe finds EXHIBIT 10.1 at line start."""
    lines = ("", "EXHIBIT 10.1 MATERIAL CONTRACT", "Some text")
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is not None
    assert result.exhibit_identity.code == "10.1"
    assert result.line_number == 1


def test_ex_99_1_exhibit_probe():
    """Probe finds EX-99.1 at line start."""
    lines = ("", "EX-99.1 CERTIFICATION", "Some text")
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is not None
    assert result.exhibit_identity.code == "99.1"


def test_101_exhibit_probe():
    """Probe finds EXHIBIT 101 at line start."""
    lines = ("", "EXHIBIT 101", "Some text")
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is not None
    assert result.exhibit_identity.code == "101"


def test_no_mid_sentence_exhibit():
    """Probe rejects mid-sentence exhibit mentions."""
    lines = (
        "This document discusses",
        "pursuant to exhibit 10.1 of the prior filing",
        "more text",
    )
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is None


def test_case_insensitivity():
    """Probe is case-insensitive."""
    lines = ("", "exhibit 10.1", "Some text")
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is not None
    assert result.exhibit_identity.code == "10.1"


def test_toc_shielding():
    """Probe ignores matches inside TOC."""
    lines = ("", "EXHIBIT 10.1", "Some text")
    toc_span = TocSpan(
        start_line=0,
        end_line=100,
        start_offset=0,
        end_offset=1000,
        method="test",
        confidence=1.0,
    )
    result = probe_exhibit_header(
        text="\n".join(lines),
        lines=lines,
        toc_span=toc_span,
    )
    assert result is None


def test_non_existent_exhibit_code():
    """Probe rejects empty code."""
    lines = ("", "EXHIBIT", "Some text")
    result = probe_exhibit_header(text="\n".join(lines), lines=lines)
    assert result is None
