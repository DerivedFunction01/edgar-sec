"""The label-shape vocabulary and the records detection is stated in."""

from __future__ import annotations

import re

from edgar_sec.engine.document.page_markers.models import (
    PAGE_HINT_ROLES,
    PAGE_MARKER_PATTERNS,
    PROSE_GUARD_STOP_WORDS,
    RE_BOUNDARY_TOKEN,
    RE_PAGE_VALUE,
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerTerminalState,
    TemplateEvidence,
)


def test_page_marker_kind_names_the_shapes_the_analysis_reports() -> None:
    assert PageMarkerKind.SGML == "sgml"
    assert PageMarkerKind.LETTER_NUMBER == "letter_number"
    assert PageMarkerKind.REPEATING_FOOTER == "repeating_footer"


def test_marker_patterns_are_ordered_most_specific_first() -> None:
    kinds = [kind for kind, _pattern in PAGE_MARKER_PATTERNS]
    assert kinds[0] == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
    assert kinds.index(PageMarkerKind.NUMBER_OF_TOTAL) < kinds.index(
        PageMarkerKind.PAGE_NUMBER
    )
    assert kinds.index(PageMarkerKind.PAGE_NUMBER) < kinds.index(
        PageMarkerKind.LETTER_NUMBER
    )


def test_page_marker_patterns_extract_page_and_count() -> None:
    matched = {
        kind: pattern.search("Page 4 of 12").groupdict()
        for kind, pattern in PAGE_MARKER_PATTERNS
        if pattern.search("Page 4 of 12")
    }
    assert matched[PageMarkerKind.PAGE_NUMBER_OF_TOTAL] == {
        "page": "4",
        "count": "12",
    }


def test_boundary_token_matches_both_bracketing_conventions() -> None:
    assert RE_BOUNDARY_TOKEN.match("(PAGE)") is not None
    assert RE_BOUNDARY_TOKEN.match("[PAGE]") is not None
    assert RE_BOUNDARY_TOKEN.match("PAGE 4") is None


def test_page_value_matches_arabic_and_roman_but_not_a_bare_word() -> None:
    assert RE_PAGE_VALUE.fullmatch("4") is not None
    assert RE_PAGE_VALUE.fullmatch("xiv") is not None
    assert RE_PAGE_VALUE.fullmatch("hello") is None


def test_prose_guard_words_exclude_words_that_really_appear_in_footers() -> None:
    assert "was" in PROSE_GUARD_STOP_WORDS
    assert "however" in PROSE_GUARD_STOP_WORDS
    assert "the" not in PROSE_GUARD_STOP_WORDS
    assert "of" not in PROSE_GUARD_STOP_WORDS


def test_page_hint_roles_name_the_break_subset_the_projection_uses() -> None:
    from edgar_sec.engine.document.html.breaks import PAGE_BREAK_HINT_TOKENS

    assert PAGE_BREAK_HINT_TOKENS
    for token in PAGE_BREAK_HINT_TOKENS:
        assert PAGE_HINT_ROLES[token] == ("break",)


def test_page_hint_roles_collapse_digit_runs_to_one_alias() -> None:
    assert PAGE_HINT_ROLES["page#"] == ("container",)
    assert PAGE_HINT_ROLES["acipg#"] == ("number",)
    assert PAGE_HINT_ROLES["ctheaderfooterpage"] == ("header", "footer")


def test_policy_and_terminal_states_are_string_enums() -> None:
    assert PageArtifactPolicy.STRIP == "strip"
    assert PageMarkerAction.REMOVE == "remove"
    assert PageMarkerAction.PRESERVE == "preserve"
    assert PageMarkerTerminalState.UNRESOLVED == "unresolved"


def test_analysis_defaults_report_a_documented_empty_frame() -> None:
    analysis = PageMarkerAnalysis((), (), ())
    assert analysis.coordinate_frame == "text"
    assert analysis.terminal_state is PageMarkerTerminalState.NONE
    assert analysis.source_text == ""


def test_decision_carries_its_marker_action_reason_and_evidence() -> None:
    marker = PageMarker(0, 6, "<PAGE>", PageMarkerKind.SGML, start_line=0, end_line=0)
    decision = PageMarkerDecision(
        marker, PageMarkerAction.REMOVE, "sgml_page_tag", 1.0, ("firm_pattern",)
    )
    assert decision.marker is marker
    assert decision.evidence == ("firm_pattern",)


def test_break_artifact_records_provenance_rather_than_payload() -> None:
    artifact = PageBreakArtifact(
        page_number=7,
        namespace="arabic",
        source="bare_number",
        coordinate_frame="text",
        source_identity="src-1",
        start=10,
        end=11,
        removable=True,
    )
    assert artifact.template_id is None
    assert artifact.node_path == ()


def test_template_evidence_defaults_to_preserved_and_unknown_role() -> None:
    evidence = TemplateEvidence("header", 0, "acme corp", 3, 1.0, "repeating_header")
    assert evidence.role == "unknown"
    assert evidence.retention == "preserve"
    assert evidence.lines == ()


def test_every_marker_pattern_compiles_under_the_ignored_case_flag() -> None:
    for _kind, pattern in PAGE_MARKER_PATTERNS:
        assert isinstance(pattern, re.Pattern)
