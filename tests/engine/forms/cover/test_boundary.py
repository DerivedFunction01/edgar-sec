"""Tests for cover boundary detection."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.boundary import (
    RE_TOC_HEADING,
    find_cover_boundary,
    find_cover_start,
)
from edgar_sec.engine.forms.cover.models import (
    BoundaryMethod,
    BoundarySignal,
    CoverBoundaryPolicy,
)
from edgar_sec.engine.forms.plugins.registry import _ANNUAL_SIGNALS

COVER = [
    "UNITED STATES",
    "SECURITIES AND EXCHANGE COMMISSION",
    "Washington, D.C. 20549",
    "",
    "FORM 10-K",
    "",
    "ACME INDUSTRIAL WIDGETS, INC.",
    "(Exact name of registrant as specified in its charter)",
    "",
    "Delaware",
    "(State or other jurisdiction of incorporation)",
    "",
    "Commission File Number: 001-14103",
    "(Exact name of registrant as specified in its charter)",
    "",
    "1234 Widget Parkway, Springfield, IL 62704",
    "(Principal executive offices)",
    "",
    "Trading Symbol(s)",
    "Common Stock, par value $0.01 per share",
    "ACMX",
    "",
    "Indicate by check mark whether the registrant is a shell company.",
    "Emerging growth company",
]

BODY = [
    "",
    "PART I",
    "",
    "ITEM 1. Business",
    "",
    (
        "The Company was founded in 1994 and is a leading provider of "
        "industrial widgets. It operates three manufacturing facilities and "
        "employs approximately 4,200 people worldwide."
    ),
    "",
    "ITEM 1A. Risk Factors",
    "",
    (
        "Investors should note the following risk factors, which could "
        "materially affect the results of the Company. The Company operates "
        "in a competitive industry and its results may differ materially."
    ),
]


def _doc(*extra: list[str]) -> str:
    return "\n".join(COVER + list(extra) + BODY)


def test_no_signals_disables_cover_parsing() -> None:
    boundary = find_cover_boundary(_doc(), signals=())
    assert boundary.method == BoundaryMethod.DISABLED
    assert boundary.end_line is None
    assert boundary.confidence == 0.0


def test_boundary_ends_at_part_heading() -> None:
    text = _doc()
    boundary = find_cover_boundary(text, signals=_ANNUAL_SIGNALS)
    assert boundary.end_line == text.splitlines().index("PART I")
    assert boundary.method == BoundaryMethod.FALLBACK
    assert boundary.continued_cover is False


def test_boundary_records_evidence() -> None:
    boundary = find_cover_boundary(_doc(), signals=_ANNUAL_SIGNALS)
    names = {item.name for item in boundary.evidence}
    assert "part_transition" in names
    assert "part_item_pair" in names
    assert boundary.start_line is not None
    assert boundary.start_evidence


def test_cover_start_finds_cluster() -> None:
    text = "\n".join(COVER)
    start = find_cover_start(text, CoverBoundaryPolicy(signals=_ANNUAL_SIGNALS))
    # The cluster opens at the first identity signal ("SECURITIES AND EXCHANGE
    # COMMISSION"), not at line 0: "UNITED STATES" is a bare fragment with no
    # identity or shape marker, so it is not a cover-cluster member.
    assert start.start_line == text.splitlines().index(
        "SECURITIES AND EXCHANGE COMMISSION"
    )
    assert {item.name for item in start.evidence} == {
        "cover_start_identity",
        "cover_start_shape",
    }


def test_cover_start_disabled_without_identity_signal() -> None:
    start = find_cover_start("\n".join(COVER), CoverBoundaryPolicy(signals=()))
    assert start.start_line is None


def test_empty_document_is_unknown() -> None:
    boundary = find_cover_boundary("", signals=_ANNUAL_SIGNALS)
    assert boundary.end_line is None
    assert boundary.method == BoundaryMethod.UNKNOWN


def test_toc_heading_transition_signal() -> None:
    text = "\n".join([*COVER, "", "TABLE OF CONTENTS", "", *BODY])
    signals = (
        BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
        BoundarySignal.PAGE_MARKERS,
        BoundarySignal.TOC_TRANSITION,
    )
    boundary = find_cover_boundary(text, signals=signals)
    assert boundary.end_line == text.splitlines().index("TABLE OF CONTENTS")
    assert "toc_transition" in {item.name for item in boundary.evidence}


def test_part_fallback_requires_cover_evidence() -> None:
    """A bare PART heading in a document with no cover signals is not a boundary."""
    text = (
        "PART I\n\nITEM 1. Business\n\n"
        "The Company was founded in 1994 and is a leading provider of "
        "industrial widgets. It operates three manufacturing facilities."
    )
    boundary = find_cover_boundary(text, signals=(BoundarySignal.PART_FALLBACK,))
    assert boundary.end_line is None


def test_item_fallback_signal() -> None:
    text = "\n".join([*COVER, "", "ITEM 1. Business", "", *BODY[5:]])
    signals = (
        BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
        BoundarySignal.PAGE_MARKERS,
        BoundarySignal.ITEM_FALLBACK,
    )
    boundary = find_cover_boundary(text, signals=signals)
    assert boundary.end_line == text.splitlines().index("ITEM 1. Business")
    assert "item_transition" in {item.name for item in boundary.evidence}


def test_incorporated_reference_signal() -> None:
    text = "\n".join(
        [
            *COVER,
            "",
            (
                "Part III of this report is incorporated herein by reference "
                "to the Company's Annual Report filed herewith as Exhibit 13."
            ),
            "",
            "PART I",
            "",
            "ITEM 1. Business",
            *BODY[5:],
        ]
    )
    signals = (
        BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
        BoundarySignal.PAGE_MARKERS,
        BoundarySignal.INCORPORATED_REFERENCE,
    )
    boundary = find_cover_boundary(text, signals=signals)
    assert "incorporated_reference" in {item.name for item in boundary.evidence}
    assert boundary.continued_cover is True
    assert boundary.end_line is not None


def test_cover_only_fragment_is_whole_document() -> None:
    text = "\n".join(COVER)
    boundary = find_cover_boundary(text, signals=_ANNUAL_SIGNALS)
    assert boundary.end_line == len(COVER)
    assert "cover_only_fragment" in {item.name for item in boundary.evidence}
    assert boundary.continued_cover is True


def test_toc_heading_regex_forms() -> None:
    assert RE_TOC_HEADING.match("TABLE OF CONTENTS")
    assert RE_TOC_HEADING.match("Table of Contents")
    assert RE_TOC_HEADING.match("INDEX TO EXHIBITS")
    assert RE_TOC_HEADING.match("EXHIBIT INDEX")
    assert not RE_TOC_HEADING.match("TABLE OF CONTENTS AND OTHER")
