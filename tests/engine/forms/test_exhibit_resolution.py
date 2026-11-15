"""Exhibit resolution: registry links, candidacy, delegation."""

from __future__ import annotations

from edgar_sec.engine.forms.exhibit_resolution import (
    ExhibitCandidateInput,
    delegation_judgement,
    linked_exhibit_families,
    resolve_exhibits,
)

_EX13_BODY = """EXHIBIT 13
ANNUAL REPORT TO SECURITY HOLDERS
ACME CORPORATION
Consolidated statements of income and balance sheets follow.
"""


def test_annual_links_name_statement_families() -> None:
    linked = linked_exhibit_families("B")
    assert set(linked) == {"EX-13"}
    assert "income_statement" in linked["EX-13"]
    assert "balance_sheet" in linked["EX-13"]


def test_quarterly_stratum_has_no_ex13_links() -> None:
    assert linked_exhibit_families("D") == {}
    resolved = resolve_exhibits(
        (ExhibitCandidateInput("EX-13", "ex13.htm", _EX13_BODY),),
        stratum="D",
        filing_form="10-Q",
    )
    assert resolved == ()


def test_metadata_candidacy_without_body() -> None:
    resolved = resolve_exhibits(
        (
            ExhibitCandidateInput("EX-13.1", "ex13.htm"),
            ExhibitCandidateInput("EX-99.1", "ex99.htm"),
            ExhibitCandidateInput("GRAPHIC", "logo.jpg"),
        ),
        stratum="B",
        filing_form="10-K",
    )
    assert len(resolved) == 1
    entry = resolved[0]
    assert entry.document_name == "ex13.htm"
    assert entry.code == "13"
    assert entry.body_disposition is None
    assert entry.body_confirmed is False


def test_body_confirmation_on_flagged_candidate() -> None:
    resolved = resolve_exhibits(
        (ExhibitCandidateInput("EX-13", "ex13.htm", _EX13_BODY),),
        stratum="B",
        filing_form="10-K",
    )
    assert len(resolved) == 1
    assert resolved[0].body_disposition == "consistent"
    assert resolved[0].body_confirmed is True


def test_delegation_stub_vs_index_only() -> None:
    stub = delegation_judgement(
        "The financial statements are set forth in Exhibit 13 to this report."
    )
    assert stub is not None
    assert stub.is_stub is True
    assert stub.exhibit_index_only is False
    assert stub.anchors == 1

    index_only = delegation_judgement(
        "Exhibit 13 is listed in the exhibit index at the end of this report "
        "alongside the other exhibits required by Item 601 of Regulation S-K "
        "and the certifications of the principal executive officer."
    )
    assert index_only is not None
    assert index_only.is_stub is False
    assert index_only.exhibit_index_only is True

    assert delegation_judgement("no exhibits mentioned here") is None
    assert delegation_judgement(None) is None
