"""Contract tests for cover boundary detection."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import BodyEvidencePack
from edgar_sec.engine.forms.cover.boundary.detector import (
    find_cover_boundary,
    find_cover_boundary_for_profile,
)
from edgar_sec.engine.forms.cover.models import (
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundaryPolicy,
)

COVER_HEAD = (
    "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
    "Washington, D.C. 20549\n"
    "Commission File Number 001-12345\n"
    "Precise name of registrant as specified in Section 10(b)\n"
    "FORM 10-K\n"
)
ANNUAL_REFERENCE = (
    COVER_HEAD
    + "The following documents are incorporated by reference into this report.\n"
    "Item 1. Business\n"
    "Item 1A. Risk Factors\n"
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "The company manufactures precision instruments worldwide.\n"
)
TOC_COVER = (
    COVER_HEAD + "TABLE OF CONTENTS\n"
    "PART I ........................................ 1\n"
    "ITEM 1. BUSINESS ............................. 1\n"
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "We are an enterprise software company.\n"
)
BODY = BodyEvidencePack(semantic_headings=("risk factors", "properties"))
COVER_EVIDENCE = type(
    "Cover",
    (),
    {
        "labels": ("table of contents", "part i", "item 1"),
        "identity_terms": ("securities and exchange commission", "form 10-k"),
        "shape_terms": ("washington, d.c. 20549", "commission file number"),
        "cover_end_terms": (
            "documents incorporated by reference",
            "the following documents are incorporated by reference",
        ),
    },
)()


def _policy(*signals: BoundarySignal) -> CoverBoundaryPolicy:
    return CoverBoundaryPolicy(signals=signals)


_ALL = _policy(*BoundarySignal)


def test_an_absent_policy_disables_cover_parsing() -> None:
    boundary = find_cover_boundary(BoundaryInput(text=ANNUAL_REFERENCE), None)

    assert boundary.method is BoundaryMethod.DISABLED
    assert boundary.end_line is None
    assert boundary.confidence == 0.0


def test_an_empty_document_has_an_unknown_boundary() -> None:
    boundary = find_cover_boundary("", _ALL)

    assert boundary.method is BoundaryMethod.UNKNOWN
    assert boundary.end_line is None


def test_an_incorporated_reference_block_ends_the_cover_at_its_transition() -> None:
    boundary = find_cover_boundary(
        ANNUAL_REFERENCE,
        _ALL,
        cover_evidence=COVER_EVIDENCE,
        body_evidence=BODY,
    )
    lines = ANNUAL_REFERENCE.splitlines()

    assert boundary.method is BoundaryMethod.STRUCTURAL
    assert boundary.end_line == 7
    assert lines[boundary.end_line] == "Item 1A. Risk Factors"
    names = {item.name for item in boundary.evidence}
    assert "incorporated_reference" in names
    assert "incorporated_reference_transition" in names
    assert boundary.confidence == 0.96


def test_a_toc_span_ends_the_cover_without_backward_confirmation() -> None:
    boundary = find_cover_boundary(TOC_COVER, _ALL, body_evidence=BODY)
    lines = TOC_COVER.splitlines()

    assert boundary.method is BoundaryMethod.STRUCTURAL
    assert lines[boundary.end_line] == "TABLE OF CONTENTS"
    assert any(item.name == "toc_start_stops_cover_scan" for item in boundary.evidence)


def test_a_proxy_reference_disclosure_never_ends_the_cover() -> None:
    text = (
        COVER_HEAD + "Portions of Item 1 are incorporated by reference here.\nPART I\n"
    )

    boundary = find_cover_boundary(text, _ALL, body_evidence=BODY)

    assert boundary.method is not BoundaryMethod.PHRASE


def test_the_signal_ladder_gates_every_fallback() -> None:
    text = COVER_HEAD + "PART I\nITEM 1. BUSINESS\nThe company operates worldwide.\n"

    assert find_cover_boundary(text, _ALL, body_evidence=BODY).method is (
        BoundaryMethod.FALLBACK
    )
    assert (
        find_cover_boundary(
            text,
            _policy(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PART_FALLBACK,
            ),
            body_evidence=BODY,
        ).method
        is BoundaryMethod.FALLBACK
    )


def test_a_disabled_signal_is_never_consulted() -> None:
    text = COVER_HEAD + "PART I\nITEM 1. BUSINESS\n"

    boundary = find_cover_boundary(
        text, _policy(BoundarySignal.PAGE_MARKERS), body_evidence=BODY
    )

    assert boundary.method is BoundaryMethod.UNKNOWN


def test_a_cover_only_fragment_is_reported_as_a_continued_cover() -> None:
    text = COVER_HEAD + "Securities registered pursuant to Section 12(b) of the Act\n"

    boundary = find_cover_boundary(text, _ALL, body_evidence=BODY)

    assert boundary.continued_cover is True
    assert boundary.end_line == len(text.splitlines())
    assert any(item.name == "cover_only_fragment" for item in boundary.evidence)


def test_boundaries_are_approximate_and_carry_the_cover_start() -> None:
    boundary = find_cover_boundary(ANNUAL_REFERENCE, _ALL, body_evidence=BODY)

    assert boundary.approximate is True
    assert boundary.start_line is not None
    assert boundary.start_offset is not None
    assert boundary.start_evidence


def test_a_plain_string_is_accepted_in_place_of_a_boundary_input() -> None:
    boundary = find_cover_boundary(
        ANNUAL_REFERENCE,
        _ALL,
        cover_evidence=COVER_EVIDENCE,
        body_evidence=BODY,
    )

    assert boundary.end_line == 7


def test_the_profile_entry_point_reads_the_profile_policy_and_packs() -> None:
    class _Profile:
        boundary = _policy(*BoundarySignal)
        cover_evidence = COVER_EVIDENCE
        body_evidence = BODY

    boundary = find_cover_boundary_for_profile(ANNUAL_REFERENCE, _Profile())

    assert boundary.end_line == 7
    assert boundary.method is BoundaryMethod.STRUCTURAL


def test_the_profile_entry_point_of_a_profile_without_a_policy_is_disabled() -> None:
    class _Profile:
        boundary = None
        cover_evidence = None
        body_evidence = None

    boundary = find_cover_boundary_for_profile(ANNUAL_REFERENCE, _Profile())

    assert boundary.method is BoundaryMethod.DISABLED
