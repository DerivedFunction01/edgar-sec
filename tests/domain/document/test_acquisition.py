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
    DocumentPathSource,
    FilingOccurrence,
    derive_occurrence_id,
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
    document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
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
        "requested_is_primary",
        "primary_recovered",
    )
    assert FilingResolutionOutcome.REQUESTED_IS_PRIMARY.value == "requested_is_primary"
    assert FilingResolutionOutcome.PRIMARY_RECOVERED.value == "primary_recovered"


def test_resolution_result_unresolved_shapes() -> None:
    """Every unresolved outcome keeps only the requested reference and no projection."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    unresolved = (
        FilingResolutionOutcome.NOT_CANDIDATE,
        FilingResolutionOutcome.BUNDLE_UNAVAILABLE,
        FilingResolutionOutcome.NON_SGML_BUNDLE,
        FilingResolutionOutcome.MALFORMED_SGML,
        FilingResolutionOutcome.REQUESTED_NOT_IN_BUNDLE,
        FilingResolutionOutcome.NO_MATCHING_PRIMARY,
        FilingResolutionOutcome.AMBIGUOUS_HEADERS,
    )
    for outcome in unresolved:
        result = FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            outcome=outcome,
            primary_occurrences=(),
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
    primary_occurrence = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            OCCURRENCE.source_cik.to_10digit(),
            str(requested.locator.accession),
            primary.locator.document_path,
        ),
        source_cik=OCCURRENCE.source_cik,
        accession=primary.locator.accession,
        document_path=primary.locator.document_path,
        form=OCCURRENCE.form,
        filing_date=OCCURRENCE.filing_date,
        report_date=OCCURRENCE.report_date,
        doc_id=primary.locator.document_locator_key,
    )
    result = FilingResolutionResult(
        requested=requested,
        requested_occurrences=(OCCURRENCE,),
        primary=primary,
        exhibit=requested,
        primary_occurrences=(primary_occurrence,),
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
        primary_occurrence = FilingOccurrence(
            occurrence_id=derive_occurrence_id(
                OCCURRENCE.source_cik.to_10digit(),
                str(PRIMARY_LOCATOR.accession),
                "a10k.htm",
            ),
            source_cik=OCCURRENCE.source_cik,
            accession=PRIMARY_LOCATOR.accession,
            document_path="a10k.htm",
            form=OCCURRENCE.form,
            filing_date=OCCURRENCE.filing_date,
            report_date=OCCURRENCE.report_date,
            doc_id=PRIMARY_LOCATOR.document_locator_key,
        )
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=DocumentReference(
                locator=PRIMARY_LOCATOR, descriptor=DESCRIPTOR, payload=b"x"
            ),
            primary_occurrences=(primary_occurrence,),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )

    with pytest.raises(ValueError, match="PRIMARY_RECOVERED requires"):
        primary_occurrence = FilingOccurrence(
            occurrence_id=derive_occurrence_id(
                OCCURRENCE.source_cik.to_10digit(),
                str(ref.locator.accession),
                "ex21.txt",
            ),
            source_cik=OCCURRENCE.source_cik,
            accession=ref.locator.accession,
            document_path="ex21.txt",
            form=OCCURRENCE.form,
            filing_date=OCCURRENCE.filing_date,
            report_date=OCCURRENCE.report_date,
            doc_id=ref.locator.document_locator_key,
        )
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=ref,
            primary_occurrences=(primary_occurrence,),
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


def test_missing_source_cik_is_unresolved_without_projection() -> None:
    """A requested occurrence lacking source_cik yields MISSING_SOURCE_CIK."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    missing_cik_occurrence = FilingOccurrence(
        occurrence_id="occ-1",
        source_cik=None,  # type: ignore[arg-type]
        accession=OCCURRENCE.accession,
        document_path=OCCURRENCE.document_path,
        form=OCCURRENCE.form,
        filing_date=OCCURRENCE.filing_date,
        report_date=OCCURRENCE.report_date,
        doc_id=OCCURRENCE.doc_id,
    )
    result = FilingResolutionResult(
        requested=ref,
        requested_occurrences=(missing_cik_occurrence,),
        outcome=FilingResolutionOutcome.MISSING_SOURCE_CIK,
        primary_occurrences=(),
    )
    assert result.primary is None and result.exhibit is None
    assert result.requested is ref
    assert result.primary_occurrences == ()
    assert result.requested_occurrences == (missing_cik_occurrence,)


def test_duplicate_source_cik_is_unresolved_without_projection() -> None:
    """Repeating source_cik values yield DUPLICATE_SOURCE_CIK."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    result = FilingResolutionResult(
        requested=ref,
        requested_occurrences=(OCCURRENCE, OCCURRENCE),
        outcome=FilingResolutionOutcome.DUPLICATE_SOURCE_CIK,
        primary_occurrences=(),
    )
    assert result.primary is None and result.exhibit is None
    assert result.primary_occurrences == ()


def _primary_ref_for(locator: DocumentLocator) -> DocumentReference:
    return DocumentReference(
        locator=locator,
        descriptor=DESCRIPTOR,
        payload=b"primary",
        source=SOURCE,
    )


def test_missing_source_cik_rejected_as_projection() -> None:
    """A missing source_cik in a source row is refused even with a projection."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    bad_row = FilingOccurrence(
        occurrence_id="occ-1",
        source_cik=None,  # type: ignore[arg-type]
        accession=OCCURRENCE.accession,
        document_path="ex21.txt",
        form=OCCURRENCE.form,
        filing_date=OCCURRENCE.filing_date,
        report_date=OCCURRENCE.report_date,
        doc_id=LOCATOR.document_locator_key,
    )
    primary_occurrence = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            "0000320193", str(LOCATOR.accession), "a10k.htm"
        ),
        source_cik=Cik.from_raw("0000320193"),
        accession=LOCATOR.accession,
        document_path="a10k.htm",
        form="10-K",
        filing_date="2002-05-15",
        report_date=None,
        doc_id=PRIMARY_LOCATOR.document_locator_key,
    )
    with pytest.raises(ValueError, match="must not retarget identity"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(bad_row,),
            primary=_primary_ref_for(PRIMARY_LOCATOR),
            exhibit=ref,
            primary_occurrences=(primary_occurrence,),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )


def test_duplicate_source_cik_rejected_as_projection() -> None:
    """A CIK duplicated in the projection is refused."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    cik_1 = Cik.from_raw("0000320193")
    cik_2 = Cik.from_raw("0000789019")
    requested = (
        FilingOccurrence(
            occurrence_id="occ-1",
            source_cik=cik_1,
            accession=LOCATOR.accession,
            document_path="ex21.txt",
            form="10-K",
            filing_date="2002-05-15",
            report_date=None,
            doc_id=LOCATOR.document_locator_key,
        ),
        FilingOccurrence(
            occurrence_id="occ-2",
            source_cik=cik_2,
            accession=LOCATOR.accession,
            document_path="ex21.txt",
            form="10-K",
            filing_date="2002-05-15",
            report_date=None,
            doc_id=LOCATOR.document_locator_key,
        ),
    )
    primary_occurrence = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            "0000320193", str(LOCATOR.accession), "a10k.htm"
        ),
        source_cik=cik_1,
        accession=LOCATOR.accession,
        document_path="a10k.htm",
        form="10-K",
        filing_date="2002-05-15",
        report_date=None,
        doc_id=PRIMARY_LOCATOR.document_locator_key,
    )
    with pytest.raises(ValueError, match="must derive distinct occurrence ids"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=requested,
            primary=_primary_ref_for(PRIMARY_LOCATOR),
            exhibit=ref,
            primary_occurrences=(primary_occurrence, primary_occurrence),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )


def test_primary_recovered_projection_invariants() -> None:
    """A PRIMARY_RECOVERED projection is complete, unique, and deterministic."""
    cik_1 = Cik.from_raw("0000320193")
    cik_2 = Cik.from_raw("0000789019")
    requested_occurrence_1 = FilingOccurrence(
        occurrence_id="occ-1",
        source_cik=cik_1,
        accession=LOCATOR.accession,
        document_path="ex21.txt",
        form="10-K",
        filing_date="2002-05-15",
        report_date=None,
        doc_id=LOCATOR.document_locator_key,
    )
    requested_occurrence_2 = FilingOccurrence(
        occurrence_id="occ-2",
        source_cik=cik_2,
        accession=LOCATOR.accession,
        document_path="ex21.txt",
        form="10-K",
        filing_date="2002-05-15",
        report_date="2002-04-30",
        doc_id=LOCATOR.document_locator_key,
    )
    primary_occurrence_1 = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            cik_1.to_10digit(), str(LOCATOR.accession), "a10k.htm"
        ),
        source_cik=cik_1,
        accession=LOCATOR.accession,
        document_path="a10k.htm",
        form="10-K",
        filing_date="2002-05-15",
        report_date=None,
        doc_id=PRIMARY_LOCATOR.document_locator_key,
    )
    primary_occurrence_2 = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            cik_2.to_10digit(), str(LOCATOR.accession), "a10k.htm"
        ),
        source_cik=cik_2,
        accession=LOCATOR.accession,
        document_path="a10k.htm",
        form="10-K",
        filing_date="2002-05-15",
        report_date="2002-04-30",
        doc_id=PRIMARY_LOCATOR.document_locator_key,
    )
    primary_locator = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "a10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
        form="10-K",
        source_cik="0000320193",
        document_type="10-K",
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    primary = _primary_ref_for(primary_locator)
    requested_ref = DocumentReference(
        locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit", source=SOURCE
    )
    result = FilingResolutionResult(
        requested=requested_ref,
        requested_occurrences=(requested_occurrence_1, requested_occurrence_2),
        primary=primary,
        exhibit=requested_ref,
        primary_occurrences=(primary_occurrence_1, primary_occurrence_2),
        outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
    )
    assert result.primary is primary
    assert result.exhibit is requested_ref
    assert result.requested is requested_ref
    assert len(result.primary_occurrences) == 2
    assert result.primary_occurrences[0] is not result.primary_occurrences[1]
    assert (
        result.primary.locator.document_path_source
        is DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE
    )
    assert result.primary.locator.document_path == "a10k.htm"
    assert result.primary.locator.accession == requested_occurrence_1.accession
    assert (
        result.primary.locator.document_locator_key
        != result.requested.locator.document_locator_key
    )
    for requested, projected in zip(
        result.requested_occurrences, result.primary_occurrences
    ):
        assert projected.source_cik is requested.source_cik
        assert projected.accession == requested.accession
        assert projected.form == requested.form
        assert projected.filing_date == requested.filing_date
        assert projected.report_date == requested.report_date
        assert projected.doc_id == result.primary.locator.document_locator_key
    ids = [r.occurrence_id for r in result.primary_occurrences]
    assert len(set(ids)) == len(ids)


def test_primary_recovered_projection_fails_on_retargeting() -> None:
    """A projection that retargets identity is refused."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    bad_occurrence = FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            "0000320193", "0000789019-02-000001", "a10k.htm"
        ),
        source_cik=Cik.from_raw("0000789019"),
        accession=AccessionNumber("0000789019-02-000001"),
        document_path="a10k.htm",
        form="10-K",
        filing_date="2002-05-15",
        report_date=None,
        doc_id=PRIMARY_LOCATOR.document_locator_key,
    )
    primary_locator = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "a10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
        form="10-K",
        source_cik="0000320193",
        document_type="10-K",
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    with pytest.raises(ValueError, match="must not retarget identity"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=_primary_ref_for(primary_locator),
            exhibit=ref,
            primary_occurrences=(bad_occurrence,),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )


def test_primary_recovered_projection_fails_on_metadata_mismatch() -> None:
    """A projection with mismatched inherited metadata is refused."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    primary_locator = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "a10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
        form="10-K",
        source_cik="0000320193",
        document_type="10-K",
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    primary_ref = _primary_ref_for(primary_locator)
    for bad_form, bad_filing, bad_report in (
        ("10-Q", None, None),
        ("10-K", "2002-06-01", None),
        ("10-K", "2002-05-15", "2002-05-16"),
    ):
        bad_occurrence = FilingOccurrence(
            occurrence_id=derive_occurrence_id(
                "0000320193", str(LOCATOR.accession), "a10k.htm"
            ),
            source_cik=OCCURRENCE.source_cik,
            accession=LOCATOR.accession,
            document_path="a10k.htm",
            form=bad_form,
            filing_date=bad_filing,
            report_date=bad_report,
            doc_id=PRIMARY_LOCATOR.document_locator_key,
        )
        with pytest.raises(ValueError, match="must inherit the source metadata"):
            FilingResolutionResult(
                requested=ref,
                requested_occurrences=(OCCURRENCE,),
                primary=primary_ref,
                exhibit=ref,
                primary_occurrences=(bad_occurrence,),
                outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
            )


def test_primary_recovered_projection_fails_on_wrong_doc_id() -> None:
    """A projection keyed on the wrong locator is refused."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    primary_locator = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "a10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
        form="10-K",
        source_cik="0000320193",
        document_type="10-K",
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    # Compute the correct occurrence id, then hand-write a wrong doc_id.
    correct_id = derive_occurrence_id("0000320193", str(LOCATOR.accession), "a10k.htm")
    bad_occurrence = FilingOccurrence(
        occurrence_id=correct_id,
        source_cik=OCCURRENCE.source_cik,
        accession=LOCATOR.accession,
        document_path="a10k.htm",
        form=OCCURRENCE.form,
        filing_date=OCCURRENCE.filing_date,
        report_date=OCCURRENCE.report_date,
        doc_id="not-the-primary-key",
    )
    with pytest.raises(ValueError, match="must key on the primary locator"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=_primary_ref_for(primary_locator),
            exhibit=ref,
            primary_occurrences=(bad_occurrence,),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )


def test_primary_recovered_requires_recovered_path_provenance() -> None:
    """A primary without recovered-bundle provenance is refused."""
    ref = DocumentReference(locator=LOCATOR, descriptor=DESCRIPTOR, payload=b"exhibit")
    primary_locator = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "a10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/a10k.htm",
        form="10-K",
        source_cik="0000320193",
        document_type="10-K",
        document_path_source=DocumentPathSource.PRIMARY_DOCUMENT,
    )
    with pytest.raises(ValueError, match="record recovered-bundle provenance"):
        FilingResolutionResult(
            requested=ref,
            requested_occurrences=(OCCURRENCE,),
            primary=_primary_ref_for(primary_locator),
            exhibit=ref,
            primary_occurrences=(
                FilingOccurrence(
                    occurrence_id=derive_occurrence_id(
                        "0000320193", str(LOCATOR.accession), "a10k.htm"
                    ),
                    source_cik=OCCURRENCE.source_cik,
                    accession=LOCATOR.accession,
                    document_path="a10k.htm",
                    form=OCCURRENCE.form,
                    filing_date=OCCURRENCE.filing_date,
                    report_date=OCCURRENCE.report_date,
                    doc_id=primary_locator.document_locator_key,
                ),
            ),
            outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
        )
