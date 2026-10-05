"""Tests for the pre-2005 exhibit-candidate gate."""

from __future__ import annotations

from datetime import date

import pytest

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.pipelines.document_storage.candidates import (
    CANDIDATE_WINDOW_END,
    CANDIDATE_WINDOW_START,
    RE_STATUTORY_EXHIBIT_FILENAME,
    CandidateIntent,
    candidate_decision,
    candidate_for,
    occurrence_filing_date,
    primary_form_token_pattern,
)

#: The 2001 sample from roadmap/design.md: Sequence 1 is ``ex21.txt``.
ERA_ACCESSION = "0000890923-01-000002"
MODERN_ACCESSION = "0001234567-11-000001"


def _locator(
    document_path: str, form: str = "10-K", accession: str = ERA_ACCESSION
) -> DocumentLocator:
    return DocumentLocator.from_parts(
        accession,
        document_path,
        archive_url=f"https://www.sec.gov/x/{document_path}",
        form=form,
        source_cik="890923",
    )


def _occurrence(
    locator: DocumentLocator, filing_date: str, occurrence_id: str = "occ-1"
) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id=occurrence_id,
        source_cik=Cik.from_raw("890923"),
        accession=locator.accession,
        document_path=locator.document_path,
        form="10-K",
        filing_date=filing_date,
        report_date=None,
        doc_id=locator.document_locator_key,
    )


# --- the temporal gate -----------------------------------------------------


def test_window_bounds_the_candidate_gate() -> None:
    assert (CANDIDATE_WINDOW_START, CANDIDATE_WINDOW_END) == (
        date(2000, 1, 1),
        date(2005, 1, 1),
    )


@pytest.mark.parametrize("filing_date", ["2000-01-01", "2004-12-31"])
def test_window_edges_are_inside(filing_date: str) -> None:
    decision = candidate_decision(_locator("ex21.txt"), date.fromisoformat(filing_date))
    assert decision.is_bundle_candidate is True


@pytest.mark.parametrize("filing_date", ["1999-12-31", "2005-01-01", "2011-02-15"])
def test_dates_outside_the_window_are_not_eligible(filing_date: str) -> None:
    decision = candidate_decision(_locator("ex21.txt"), date.fromisoformat(filing_date))
    assert decision.window_eligible is False
    assert decision.intent is CandidateIntent.OUT_OF_WINDOW
    assert decision.reason == "outside_window"


def test_an_unknown_date_produces_no_candidate() -> None:
    decision = candidate_decision(_locator("ex21.txt"), None)
    assert decision.window_eligible is False
    assert decision.reason == "no_filing_date"


# --- the occurrence filing date --------------------------------------------


def test_agreeing_occurrence_dates_yield_one_date() -> None:
    locator = _locator("ex21.txt")
    dates = [
        occurrence_filing_date([_occurrence(locator, "2001-03-01")]),
        occurrence_filing_date(
            [
                _occurrence(locator, "2001-03-01", "occ-1"),
                _occurrence(locator, "03/01/2001", "occ-2"),
            ]
        ),
    ]
    assert dates == [date(2001, 3, 1), date(2001, 3, 1)]


@pytest.mark.parametrize("filing_date", ["", "   ", "not-a-date", "2001-13-45", "2001"])
def test_missing_or_malformed_dates_fail_closed(filing_date: str) -> None:
    locator = _locator("ex21.txt")
    assert occurrence_filing_date([_occurrence(locator, filing_date)]) is None


def test_conflicting_co_filer_dates_fail_closed() -> None:
    locator = _locator("ex21.txt")
    occurrences = [
        _occurrence(locator, "2001-03-01", "occ-1"),
        _occurrence(locator, "2002-03-01", "occ-2"),
    ]
    assert occurrence_filing_date(occurrences) is None


def test_one_malformed_co_filer_date_fails_the_whole_locator() -> None:
    locator = _locator("ex21.txt")
    occurrences = [
        _occurrence(locator, "2001-03-01", "occ-1"),
        _occurrence(locator, "", "occ-2"),
    ]
    assert occurrence_filing_date(occurrences) is None


def test_the_accession_year_is_never_a_substitute() -> None:
    """A 2001 accession must not rescue an occurrence with no usable date."""
    locator = _locator("ex21.txt", accession=ERA_ACCESSION)
    filing_date, decision = candidate_for(locator, [_occurrence(locator, "unknown")])
    assert filing_date is None
    assert decision.intent is CandidateIntent.OUT_OF_WINDOW


def test_a_locator_with_no_occurrences_has_no_candidate_date() -> None:
    assert occurrence_filing_date([]) is None


# --- the statutory filename grammar ----------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "ex21.txt",
        "ex-10.1.htm",
        "exhibit99.htm",
        "dex101.htm",
        "ex-3_1.txt",
        "EX99-1.htm",
    ],
)
def test_statutory_exhibit_names_are_recognized(name: str) -> None:
    assert RE_STATUTORY_EXHIBIT_FILENAME.match(name) is not None


@pytest.mark.parametrize(
    "name",
    [
        "exxon10k.htm",
        "exp.txt",
        "ex.txt",
        "EXAS",
        "EXPO",
        "acme-10k.htm",
        "form10k.txt",
        "ex10k.htm",
        "ex-10k.htm",
        "exhibit106.htm",
    ],
)
def test_ticker_company_and_form_names_are_rejected(name: str) -> None:
    assert RE_STATUTORY_EXHIBIT_FILENAME.match(name) is None


def test_a_statutory_exhibit_numbered_beyond_item_601_is_rejected() -> None:
    assert RE_STATUTORY_EXHIBIT_FILENAME.match("ex106.htm") is None
    assert RE_STATUTORY_EXHIBIT_FILENAME.match("ex105.htm") is not None


def test_only_the_basename_participates_in_exhibit_recognition() -> None:
    """A rendered path's directory is routing, not filename grammar."""
    candidate = candidate_decision(_locator("xslF345X02/ex21.txt"), date(2001, 3, 1))
    rendered = candidate_decision(_locator("xslF345X02/exxon.htm"), date(2001, 3, 1))
    assert candidate.is_bundle_candidate is True
    assert rendered.is_bundle_candidate is False


# --- the dynamic primary-form token ----------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "form10k.txt",
        "tenksb.htm",
        "ex-10k.htm",
        "annualreport.htm",
        "quarterlyreport.htm",
    ],
)
def test_primary_form_tokens_are_recognized(name: str) -> None:
    assert primary_form_token_pattern("10-K").search(name) is not None


@pytest.mark.parametrize(
    "name", ["exhibit99.htm", "bylaws.txt", "carat2001-1post8k.txt"]
)
def test_ordinary_names_carry_no_form_token(name: str) -> None:
    assert primary_form_token_pattern("10-K").search(name) is None


@pytest.mark.parametrize(
    ("form", "name"),
    [
        ("10-K", "annualreport.htm"),
        ("20-F", "annualreport.htm"),
        ("10-Q", "quarterlyreport.htm"),
        ("8-K", "currentreport.htm"),
        ("6-K", "currentreport.htm"),
    ],
)
def test_a_family_contributes_its_own_context_token(form: str, name: str) -> None:
    assert primary_form_token_pattern(form).search(name) is not None


def test_an_unresolved_form_still_matches_the_context_tokens() -> None:
    assert primary_form_token_pattern(None).search("form10q.txt") is not None


def test_the_form_token_pattern_is_memoized_per_family() -> None:
    assert primary_form_token_pattern("10-K") is primary_form_token_pattern("10-K/A")
    assert primary_form_token_pattern("10-K") is not primary_form_token_pattern("10-Q")


# --- the combined decision -------------------------------------------------


def test_a_form_token_inside_a_statutory_name_is_rejected() -> None:
    decision = candidate_decision(_locator("exhibit10-k.htm"), date(2001, 3, 1))
    assert decision.window_eligible is True
    assert decision.reason == "primary_form_token"


def test_a_window_eligible_name_that_is_not_statutory_is_not_a_candidate() -> None:
    """A non-exhibit name carrying the form token is named like the primary form."""
    decision = candidate_decision(_locator("exxon10k.htm"), date(2001, 3, 1))
    assert decision.window_eligible is True
    assert decision.is_bundle_candidate is False
    assert decision.reason == "primary_form_token"


def test_the_verified_inversion_sample_is_a_candidate() -> None:
    """The 2001 10-K sample: Sequence 1 named ``ex21.txt``."""
    locator = _locator("ex21.txt")
    filing_date, decision = candidate_for(locator, [_occurrence(locator, "2001-03-01")])
    assert filing_date == date(2001, 3, 1)
    assert decision.intent is CandidateIntent.BUNDLE_CANDIDATE
    assert decision.reason == "statutory_exhibit"


def test_a_modern_filing_is_never_a_candidate() -> None:
    locator = _locator("ex99-1.htm", accession=MODERN_ACCESSION)
    _filing_date, decision = candidate_for(
        locator, [_occurrence(locator, "2011-02-15")]
    )
    assert decision.window_eligible is False
