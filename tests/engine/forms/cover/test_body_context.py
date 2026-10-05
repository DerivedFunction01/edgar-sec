"""Unit tests for edgar_sec.engine.forms.cover.body_context."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.units import LogicalUnit
from edgar_sec.engine.forms.cover.body_context import (
    collect_cover_vocab,
    compile_body_lexical,
    index_units_by_line,
    is_form_placeholder,
    unit_at,
    unit_context,
    unit_in_toc,
    unit_is_protected,
)
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.foundation.text.evidence import CompiledEvidencePack


def test_compile_body_lexical() -> None:
    profile = get_profile("10-K")
    compiled = compile_body_lexical(profile.body_evidence)
    assert isinstance(compiled, CompiledEvidencePack)
    assert len(compiled.tiers) > 0


def test_collect_cover_vocab() -> None:
    lines = ["UNITED STATES", "SECURITIES AND EXCHANGE COMMISSION", "FORM 10-K"]
    vocab = collect_cover_vocab(lines, 3)
    assert "united" in vocab
    assert "securities" in vocab


def test_unit_indexing_and_lookup() -> None:
    units = [
        LogicalUnit(kind="paragraph", start_line=0, end_line=2, text="Para 1"),
        LogicalUnit(kind="table", start_line=3, end_line=5, text="Table 1"),
    ]
    idx = index_units_by_line(units)
    assert unit_at(idx, 1) == units[0]
    assert unit_at(idx, 4) == units[1]
    assert unit_at(idx, 10) is None


def test_unit_in_toc_and_protected() -> None:
    toc_span = TocSpan(
        start_line=10,
        end_line=20,
        start_offset=0,
        end_offset=0,
        method="test",
        confidence=0.9,
    )
    unit_inside = LogicalUnit(
        kind="paragraph", start_line=12, end_line=15, text="TOC item"
    )
    unit_outside = LogicalUnit(
        kind="paragraph", start_line=21, end_line=25, text="Prose"
    )
    unit_table = LogicalUnit(kind="table", start_line=26, end_line=30, text="Table")

    assert unit_in_toc(unit_inside, toc_span)
    assert not unit_in_toc(unit_outside, toc_span)
    assert unit_is_protected(unit_table)
    assert not unit_is_protected(unit_outside)

    ctx_inside = unit_context(unit_inside, toc_span, frozenset())
    assert not ctx_inside.eligible
    assert ctx_inside.zone == "toc"

    ctx_outside = unit_context(unit_outside, toc_span, frozenset())
    assert ctx_outside.eligible


def test_is_form_placeholder() -> None:
    assert is_form_placeholder("Omitted.")
    assert is_form_placeholder("Not Applicable")
    assert is_form_placeholder("Reserved")
    assert not is_form_placeholder("Item 1. Business")
