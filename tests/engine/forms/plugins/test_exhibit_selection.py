"""Tests for exhibit selection and compilation."""

from dataclasses import replace

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.packs import ex3_1, ex31_i
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    CompiledExhibitPack,
    _compile_pack,
    _get_compiled_pack,
    evaluate_exhibit_body,
    probe_exhibit_header,
)


def test_compile_pack():
    """Verify pack compilation produces compiled patterns."""
    compiled = _compile_pack(ex3_1.PACK)
    assert compiled.pack_id == "ex3_1"
    assert isinstance(compiled, CompiledExhibitPack)
    assert compiled.title_pattern is not None
    assert compiled.primary_pattern is not None


def test_compiled_pack_cache():
    """Cache compiled patterns by pack identity and version."""
    compiled1 = _get_compiled_pack("test_pack", ex3_1.PACK)
    compiled2 = _get_compiled_pack("test_pack", ex3_1.PACK)
    assert compiled1 is compiled2
    newer = _get_compiled_pack("test_pack", replace(ex3_1.PACK, version="v2"))
    assert newer is not compiled1
    assert newer.pack_version == "v2"


def test_probe_exhibit_header():
    """Verify probe detects line-anchored exhibit codes."""
    text = """EXHIBIT 3.1

ARTICLES OF INCORPORATION
This document contains the Articles of Incorporation."""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is not None
    assert match.exhibit_identity.code == "3.1"
    assert match.evidence_tier == "direct_designator"


def test_probe_exhibitsensitive():
    """Verify probe is case-insensitive."""
    text = """exhibit 3.1

Articles of Incorporation"""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is not None
    assert match.exhibit_identity.code == "3.1"


def test_probe_without_code():
    """Verify probe returns None when no exhibit code present."""
    text = """ARTICLES OF INCORPORATION
This document contains the Articles of Incorporation."""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is None


def test_evaluate_source_supported_exhibit_requires_designator_and_title():
    text = "EXHIBIT 3.1\nARTICLES OF INCORPORATION\n"
    result = evaluate_exhibit_body(
        text,
        filing_form="10-K",
        expected_type="EX-3.1",
        expected_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
    )

    assert result is not None
    assert result.disposition == "consistent"
    assert result.evaluator_quality == "source_supported"
    assert result.pack_id == "ex3_1"
    assert result.pack_version == "v1"
    assert [
        text[span.start_char : span.end_char] for span in result.supporting_evidence
    ] == ["3.1", "ARTICLES OF INCORPORATION"]


def test_evaluate_does_not_promote_primary_report_mentions():
    text = "FORM 10-K\nCONTENTS\nExhibit 3.1 Articles of Incorporation\n"
    result = evaluate_exhibit_body(
        text,
        filing_form="10-K",
        expected_type="EX-3.1",
        expected_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
        toc_span=TocSpan(
            start_line=0,
            end_line=3,
            start_offset=0,
            end_offset=len(text),
            method="test",
            confidence=1.0,
        ),
    )

    assert result is not None
    assert result.disposition == "insufficient_evidence"
    assert result.diagnostic_code is None


def test_evaluate_reports_conflicting_designator_as_diagnostic():
    result = evaluate_exhibit_body(
        "EXHIBIT 3.2\nBYLAWS\n",
        filing_form="10-K",
        expected_type="EX-3.1",
        expected_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
    )

    assert result is not None
    assert result.disposition == "possible_role_mismatch"
    assert result.diagnostic_code == "suspected_misfiled_exhibit"
    assert result.observed_identity == ExhibitIdentity("reg_s_k_item_601", "3.2")


def test_evaluate_abstains_for_disabled_authority_and_form():
    assert (
        evaluate_exhibit_body(
            "EXHIBIT 1\nARTICLES OF ASSOCIATION\n",
            filing_form="20-F",
            expected_type="EX-1",
            expected_identity=ExhibitIdentity("form_20f", "1"),
        )
        is None
    )
