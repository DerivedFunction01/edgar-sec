"""Tests for filing-resolution acquisition records.

Records live in the domain layer and must stay free of transport, engine, and
pipeline machinery; fixtures are supplied as plain bytes and locators.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.document.acquisition import (
    AcquisitionSource,
    AcquisitionSourceKind,
    BundleFetchResult,
    DocumentReference,
    FilingResolutionOutcome,
    FilingResolutionResult,
    SubmissionDocument,
    unresolved_resolution,
)
from edgar_sec.domain.document.models import (
    AccessionNumber,
    DocumentLocator,
    FilingOccurrence,
)
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import Cik


LOCATOR = DocumentLocator.from_parts(
    "0000320193-02-000123",
    "ex21.txt",
    archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/ex21.txt",
    form="10-K",
    source_cik="0000320193",
)

DESCRIPTOR = SubmissionDocument(
    document_path="ex21.txt",
    content_route=DocumentRoute.TEXT,
    sequence=1,
    doc_type="EX-21",
    description="LIST OF SUBSIDIARIES",
)

SOURCE = AcquisitionSource(
    kind=AcquisitionSourceKind.FIXTURE, reference="fixture://ex21.txt"
)

PRIMARY_LOCATOR = DocumentLocator.from_parts(
    "0000320193-02-000123",
    "a10k.htm",
    archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
    form="10-K",
    source_cik="0000320193",
    document_type="10-K",
)

OCCURRENCE = FilingOccurrence(
    occurrence_id="occ-1",
    source_cik=Cik.from_raw("0000320193"),
    accession=LOCATOR.accession,
    document_path="ex21.txt",
    form="10-K",
    filing_date="2002-05-15",
    report_date=None,
    doc_id=LOCATOR.document_locator_key,
)


def test_bundle_fetch_result_invariants() -> None:
    """An ok result requires a payload; a failure requires an error and no payload."""
    BundleFetchResult(status="ok", payload=b"bundle", source=SOURCE)
    BundleFetchResult(status="ok", payload=b"bundle")
    BundleFetchResult(status="missing", payload=None, error="not found")
    BundleFetchResult(status="failed", payload=None, error="connection refused")

    with pytest.raises(ValueError, match="ok bundle result must carry a payload"):
        BundleFetchResult(status="ok")

    with pytest.raises(
        ValueError, match="unsuccessful bundle result carries no payload"
    ):
        BundleFetchResult(status="missing", payload=b"leaked")

    with pytest.raises(
        ValueError, match="unsuccessful bundle result must name an error"
    ):
        BundleFetchResult(status="failed")


def test_document_reference_is_role_neutral() -> None:
    """A reference carries identity, headers, body, and provenance, no role fields."""
    ref = DocumentReference(
        locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit", source=SOURCE
    )
    assert ref.locator.document_locator_key == LOCATOR.document_locator_key
    assert ref.descriptor.doc_type == "EX-21"
    assert ref.payload == b"exhibit"
    assert ref.source is SOURCE

    ref_no_source = DocumentReference(
        locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit"
    )
    assert ref_no_source.source is None


def test_resolution_outcome_values_are_exhaustive() -> None:
    """Every outcome is a unique, stable string."""
    assert tuple(FilingResolutionOutcome)[:-2] == (
        "not_candidate",
        "bundle_unavailable",
        "non_sgml_bundle",
        "malformed_sgml",
        "requested_not_in_bundle",
        "no_matching_primary",
        "ambiguous_headers",
    )
    assert FilingResolutionOutcome.REQUESTED_IS_PRIMARY.value == "requested_is_primary"
    assert FilingResolutionOutcome.PRIMARY_RECOVERED.value == "primary_recovered"


def test_resolution_result_unresolved_shapes() -> None:
    """Every unresolved outcome keeps only the requested reference."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    for outcome in tuple(FilingResolutionOutcome)[:-2]:
        result = FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            outcome=outcome,
        )
        assert result.outcome is outcome
        assert result.primary is None
        assert result.exhibit is None
        assert result.requested is ref


def test_resolution_result_requested_is_primary_shape() -> None:
    """REQUESTED_IS_PRIMARY carries primary is requested and no exhibit."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    result = FilingResolutionResult(
        requested=ref,
        requested_occurrences=(OCCURRENCE,),
        primary=ref,
        outcome=FilingResolutionOutcome.REQUESTED_IS_PRIMARY,
    )
    assert result.primary is ref
    assert result.exhibit is None
    assert (
        result.primary.locator.document_locator_key == ref.locator.document_locator_key
    )


def test_resolution_result_primary_recovered_shape() -> None:
    """PRIMARY_RECOVERED keeps requested/exhibit, distinct primary, same accession."""
    requested = DocumentReference(
        locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit", source=SOURCE
    )
    primary = DocumentReference(
        locator=PRIMARY_LOCATOR,
        descriptor=DESCRIPTOR,
        payload=b"primary",
        source=SOURCE,
    )
    result = FilingResolutionResult(
        requested=requested,
        requested_occurrences=(OCCURRENCE,),
        primary=primary,
        exhibit=requested,
        outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
    )
    assert result.primary is primary
    assert result.exhibit is requested
    assert result.requested is requested
    assert result.primary.locator.accession == requested.locator.accession
    assert (
        result.primary.locator.document_locator_key
        != requested.locator.document_locator_key
    )
    assert (
        len(
            {
                result.requested.locator.document_locator_key,
                result.primary.locator.document_locator_key,
            }
        )
        == 2
    )


def test_resolution_result_rejects_invalid_shapes() -> None:
    """Construction enforces the valid shapes strictly."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")

    with pytest.raises(ValueError, match="unresolved outcome carries neither"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=ref,
            outcome=FilingResolutionOutcome.NOT_CANDIDATE,
        )

    with pytest.raises(ValueError, match="REQUESTED_IS_PRIMARY requires"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=DocumentReference(
                locator=PRIMARY_LOCATOR, descriptor=DESCRIPTOR, payload=b"x"
            ),
            outcome=FilingResolutionOutcome.REQUESTED_IS_PRIMARY,
        )

    with pytest.raises(ValueError, match="REQUESTED_IS_PRIMARY carries no exhibit"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=ref,
            exhibit=ref,
            outcome=FilingResolutionOutcome.REQUESTED_IS_PRIMARY,
        )

    with pytest.raises(ValueError, match="PRIMARY_RECOVERED requires"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=DocumentReference(
                locator=PRIMARY_LOCATOR, descriptor=DESCRIPTOR, payload=b"x"
            ),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )

    with pytest.raises(ValueError, match="PRIMARY_RECOVERED requires"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=ref,
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )

    primary_diff_accession = DocumentReference(
        locator=DocumentLocator.from_parts(
            "0000789019-02-000001", "a10k.htm", document_type="10-K"
        ),
        descriptor=DESCRIPTOR,
        payload=b"x",
    )
    with pytest.raises(ValueError, match="same accession"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=primary_diff_accession,
            exhibit=ref,
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )

    with pytest.raises(ValueError, match="distinct locator key"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=ref,
            exhibit=ref,
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )


def test_unresolved_resolution_helper() -> None:
    """The helper builds every unresolved outcome without boilerplate."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    result = unresolved_resolution(
        ref, (OCCURRENCE,), FilingResolutionOutcome.BUNDLE_UNAVAILABLE
    )
    assert (
        result.primary is None
        and result.exhibit is None
        and result.outcome is FilingResolutionOutcome.BUNDLE_UNAVAILABLE
    )

    with pytest.raises(ValueError, match="use the full constructor"):
        unresolved_resolution(
            ref, (OCCURRENCE,), FilingResolutionOutcome.PRIMARY_RECOVERED
        )


def test_bundle_fetch_result_adapts_fetch_result_provenance() -> None:
    """A caller can fold an existing FetchResult into a BundleFetchResult."""
    from edgar_sec.domain.document.acquisition import (
        FetchResult,
        AcquisitionFailure,
        direct_acquisition,
    )

    acquired = direct_acquisition(LOCATOR, b"bundle envelope")
    fetch = FetchResult(
        locator=LOCATOR,
        status="ok",
        acquired=acquired,
        source_payload=b"bundle envelope",
    )
    bundle = BundleFetchResult(
        status=fetch.status,
        payload=fetch.source_payload,
        source=None,  # provenance folded in where available
    )
    assert bundle.status == "ok"
    assert bundle.payload == b"bundle envelope"
    assert bundle.source is None

    failure = FetchResult(
        locator=LOCATOR, status="missing", acquired=None, error="gone"
    )
    assert failure.source_payload is None
    assert (
        BundleFetchResult(
            status=failure.status, payload=failure.source_payload, error=failure.error
        ).error
        == "gone"
    )

    missing = FetchResult(
        locator=LOCATOR, status="missing", acquired=None, error="absent"
    )
    assert (
        BundleFetchResult(
            status=missing.status, payload=missing.source_payload, error=missing.error
        ).payload
        is None
    )
