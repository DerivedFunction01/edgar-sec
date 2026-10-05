"""Tests for the filing-resolution resolver call path.

The resolver consumes a `DocumentReference`, unchanged co-filer occurrences, and a
typed `BundleFetchResult`; it is pure, in-memory, and side-effect-free.
"""

from __future__ import annotations

from pathlib import Path

import shutil
import pytest

from edgar_sec.domain.document.acquisition import (
    AcquisitionSource,
    AcquisitionSourceKind,
    BundleFetchResult,
    DocumentReference,
    FilingResolutionOutcome,
    SubmissionDocument,
)
from edgar_sec.domain.document.models import (
    AccessionNumber,
    DocumentLocator,
    FilingOccurrence,
)
from edgar_sec.domain.document.route import DocumentRoute, content_route
from edgar_sec.domain.identity import Cik
from edgar_sec.engine.document.unpacking.unpacker import has_sgml_documents
from edgar_sec.pipelines.document_storage.candidates import candidate_for
from edgar_sec.pipelines.document_storage.resolution import resolve_candidate_filing
from tests.support import fixture_path, load_document_storage_fixture

ACCESSION = "0000320193-02-000123"

BUNDLE_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019302000123/0000320193-02-000123.txt"

OCCURRENCE = FilingOccurrence(
    occurrence_id="occ-1",
    source_cik=Cik.from_raw("0000320193"),
    accession=AccessionNumber(ACCESSION),
    document_path="ex21.txt",
    form="10-K",
    filing_date="2002-05-15",
    report_date=None,
    doc_id="occ-1",  # wrong, covered below
)

PRIMARY_FORM_OCCURRENCE = FilingOccurrence(
    occurrence_id="occ-1",
    source_cik=Cik.from_raw("0000320193"),
    accession=AccessionNumber(ACCESSION),
    document_path="a10k.htm",
    form="10-K",
    filing_date="2002-05-15",
    report_date=None,
    doc_id="occ-1",
)


def _requested_ref(
    locator: DocumentLocator, source: AcquisitionSource | None = None
) -> DocumentReference:
    return DocumentReference(
        locator=locator,
        descriptor=SubmissionDocument(
            document_path=locator.document_path,
            content_route=content_route(locator.document_path),
            sequence=None,
            doc_type=None,
            description=None,
        ),
        payload=b"initial exhibit",
        source=source,
    )


def test_primary_recovered_from_exhibit_position_one() -> None:
    """The form-matched primary is the lowest accepted sequence, not position one."""
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    occurrences = [
        [OCCURRENCE],
    ]
    bundle_fetch = BundleFetchResult(
        status="ok",
        payload=bundle,
        source=AcquisitionSource(
            kind=AcquisitionSourceKind.FIXTURE, reference=BUNDLE_URL
        ),
    )
    result = resolve_candidate_filing(
        _requested_ref(requested, bundle_fetch.source),
        [OCCURRENCE],
        bundle_fetch,
    )
    assert result.outcome is FilingResolutionOutcome.PRIMARY_RECOVERED
    assert result.exhibit is result.requested
    assert result.primary is not result.requested
    assert result.primary.locator.document_path == "a10k.htm"
    assert result.primary.descriptor.doc_type == "10-K"
    assert result.primary.locator.accession == result.requested.locator.accession
    assert (
        result.primary.locator.document_locator_key
        != result.requested.locator.document_locator_key
    )
    assert (
        result.primary.locator.document_locator_key.startswith("sha256_")
        or len(result.primary.locator.document_locator_key) == 64
    )
    assert b"ANNUAL REPORT BODY" in result.primary.payload
    assert b"EXHIBIT TWENTY ONE BODY" in result.requested.payload
    assert (
        b"<SEC-DOCUMENT>" not in result.requested.payload
        and b"<SEC-DOCUMENT>" not in result.primary.payload
    )


def test_primary_is_the_requested_document() -> None:
    """When the first accepted match is the requested document, it is its own primary."""
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "a10k.htm",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    bundle_fetch = BundleFetchResult(
        status="ok",
        payload=bundle,
        source=AcquisitionSource(
            kind=AcquisitionSourceKind.FIXTURE, reference=BUNDLE_URL
        ),
    )
    result = resolve_candidate_filing(
        _requested_ref(requested, bundle_fetch.source),
        [PRIMARY_FORM_OCCURRENCE],
        bundle_fetch,
    )
    assert result.outcome is FilingResolutionOutcome.REQUESTED_IS_PRIMARY
    assert result.primary is result.requested
    assert result.exhibit is None
    assert b"ANNUAL REPORT BODY" in result.primary.payload


def test_not_candidate_skips_bundle_inspection() -> None:
    """OUT_OF_WINDOW and window-eligible verdicts keep the bundle untouched."""
    requested = DocumentLocator.from_parts(
        "0000320193-02-000123",
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    out_of_window = [
        FilingOccurrence(
            occurrence_id="occ-2",
            source_cik=Cik.from_raw("0000320193"),
            accession=AccessionNumber(ACCESSION),
            document_path="ex21.txt",
            form="10-K",
            filing_date="2012-05-15",
            report_date=None,
            doc_id=requested.document_locator_key,
        ),
    ]
    result = resolve_candidate_filing(
        _requested_ref(requested),
        out_of_window,
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.NOT_CANDIDATE
    assert result.primary is None and result.exhibit is None

    eligible = [
        FilingOccurrence(
            occurrence_id="occ-3",
            source_cik=Cik.from_raw("0000320193"),
            accession=AccessionNumber(ACCESSION),
            document_path="ex21.txt",
            form="10-K",
            filing_date="2001-05-15",
            report_date=None,
            doc_id=requested.document_locator_key,
        ),
    ]
    result = resolve_candidate_filing(
        _requested_ref(
            DocumentLocator.from_parts(
                ACCESSION,
                "report.htm",
                archive_url=BUNDLE_URL,
                form="10-K",
                source_cik="0000320193",
            )
        ),
        eligible,
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.NOT_CANDIDATE


def test_bundle_unavailable_when_missing_or_failed() -> None:
    """No payload in the typed result is BUNDLE_UNAVAILABLE, not an exception."""
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result_missing = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="missing", payload=None, error="not found"),
    )
    assert result_missing.outcome is FilingResolutionOutcome.BUNDLE_UNAVAILABLE

    result_failed = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="failed", payload=None, error="timeout"),
    )
    assert result_failed.outcome is FilingResolutionOutcome.BUNDLE_UNAVAILABLE


def test_non_sgml_bundle_does_not_pass_the_sgml_gate() -> None:
    """An HTML bundle is a normal outcome; the resolver never parses it as SGML."""
    bundle = load_document_storage_fixture("html_bundle.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.NON_SGML_BUNDLE
    assert result.primary is None and result.exhibit is None


def test_malformed_sgml_reports_structure_not_an_exception() -> None:
    """Nested and unbalanced delimiters are typed outcomes, not errors."""
    nested = load_document_storage_fixture("nested_delimiters.sgm")
    unbalanced = load_document_storage_fixture("unbalanced_delimiters.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    for name, bundle in (("nested", nested), ("unbalanced", unbalanced)):
        result = resolve_candidate_filing(
            _requested_ref(requested),
            [OCCURRENCE],
            BundleFetchResult(status="ok", payload=bundle),
        )
        assert result.outcome is FilingResolutionOutcome.MALFORMED_SGML, name
        assert result.primary is None and result.exhibit is None


def test_requested_not_in_bundle_when_no_basename_matches() -> None:
    """The requested document is retained but its filename is not in the envelope."""
    bundle = load_document_storage_fixture("missing_requested.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.REQUESTED_NOT_IN_BUNDLE
    assert result.primary is None and result.exhibit is None
    # The originally acquired body is preserved when the bundle does not name it.
    assert result.requested.payload == b"initial exhibit"


def test_no_matching_primary_when_form_type_is_absent() -> None:
    """Absent accepted types are no match, never a fallback to a sibling."""
    bundle = load_document_storage_fixture("no_matching_type.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.NO_MATCHING_PRIMARY
    assert result.primary is None and result.exhibit is None


def test_ambiguous_headers_on_duplicate_requested_basename() -> None:
    """A filename appearing twice is ambiguous even when a primary exists."""
    bundle = load_document_storage_fixture("duplicate_requested.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.AMBIGUOUS_HEADERS
    assert result.primary is None and result.exhibit is None


def test_ambiguous_headers_on_invalid_primary_sequence() -> None:
    """A matching type without a positive sequence is ambiguous, never skipped."""
    bundle = load_document_storage_fixture("invalid_sequence.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.AMBIGUOUS_HEADERS
    assert result.primary is None


def test_ambiguous_headers_on_tied_earliest_sequence() -> None:
    """A tie for the lowest accepted sequence is not broken by envelope order."""
    bundle = load_document_storage_fixture("tied_sequence.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.AMBIGUOUS_HEADERS
    assert result.primary is None


def test_base_form_is_accepted_as_primary_when_form_is_amendment() -> None:
    """The canonical family and its /A token are both accepted; the 10-K is the primary."""
    bundle = load_document_storage_fixture("amendment_alias.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K/A",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(requested),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.outcome is FilingResolutionOutcome.PRIMARY_RECOVERED
    assert result.primary.locator.document_path == "a10k.htm"
    assert result.primary.descriptor.doc_type == "10-K"
    assert result.primary.locator.accession == result.requested.locator.accession
    assert (
        result.primary.locator.document_locator_key
        != result.requested.locator.document_locator_key
    )


def test_occurrence_group_is_unchanged() -> None:
    """The resolver never mutates or retargets the co-filer group."""
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    original = [
        FilingOccurrence(
            occurrence_id="occ-1",
            source_cik=Cik.from_raw("0000320193"),
            accession=AccessionNumber(ACCESSION),
            document_path="ex21.txt",
            form="10-K",
            filing_date="2002-05-15",
            report_date=None,
            doc_id="occ-1",
        ),
        FilingOccurrence(
            occurrence_id="occ-2",
            source_cik=Cik.from_raw("0000789019"),
            accession=AccessionNumber(ACCESSION),
            document_path="ex21.txt",
            form="10-K",
            filing_date="2002-05-15",
            report_date=None,
            doc_id="occ-2",
        ),
    ]
    before = [
        (r.source_cik.to_10digit(), r.accession, r.filing_date, r.doc_id)
        for r in original
    ]
    result = resolve_candidate_filing(
        _requested_ref(
            DocumentLocator.from_parts(
                ACCESSION,
                "ex21.txt",
                archive_url=BUNDLE_URL,
                form="10-K",
                source_cik="0000320193",
            )
        ),
        original,
        BundleFetchResult(status="ok", payload=bundle),
    )
    after = [
        (r.source_cik.to_10digit(), r.accession, r.filing_date, r.doc_id)
        for r in original
    ]
    assert before == after
    assert len(result.requested_occurrences) == 2
    assert [r.occurrence_id for r in result.requested_occurrences] == ["occ-1", "occ-2"]
    assert len(result.requested_occurrences) == 2


def test_recovered_primary_key_is_recomputed_from_accession_and_filename() -> None:
    """The primary identity comes from its own basename, not the request's."""
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    locator = DocumentLocator.from_parts(
        ACCESSION,
        "ex21.txt",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    result = resolve_candidate_filing(
        _requested_ref(locator),
        [OCCURRENCE],
        BundleFetchResult(status="ok", payload=bundle),
    )
    assert result.primary is not None
    expected_key = __import__(
        "edgar_sec.domain.document.models", fromlist=["derive_document_locator_key"]
    ).derive_document_locator_key(ACCESSION.replace("-", ""), "a10k.htm")
    assert result.primary.locator.document_locator_key == expected_key
    assert result.primary.locator.accession == locator.accession
    assert result.primary.locator.form == locator.form
    assert result.primary.locator.source_cik == locator.source_cik
    assert result.primary.locator.document_type == "10-K"


def test_archive_url_falls_back_when_source_lacks_scheme() -> None:
    """A non-URL source reference yields no archive_url; the locator URL is used when valid."""
    bundle = load_document_storage_fixture("exhibit_primary.sgm")
    requested = DocumentLocator.from_parts(
        ACCESSION,
        "a10k.htm",
        archive_url=BUNDLE_URL,
        form="10-K",
        source_cik="0000320193",
    )
    fixture_source = AcquisitionSource(
        kind=AcquisitionSourceKind.FIXTURE, reference="fixture://a10k.htm"
    )
    bundle_fetch = BundleFetchResult(status="ok", payload=bundle, source=fixture_source)
    result = resolve_candidate_filing(
        _requested_ref(requested, bundle_fetch.source),
        [PRIMARY_FORM_OCCURRENCE],
        bundle_fetch,
    )
    assert (
        result.primary is result.requested
        and result.outcome is FilingResolutionOutcome.REQUESTED_IS_PRIMARY
    )
    assert result.primary.locator.archive_url == BUNDLE_URL


def test_catalog_plan_integration() -> None:
    """The ex21 candidate from an era plan yields PRIMARY_RECOVERED with its group intact."""
    from edgar_sec.pipelines.document_storage.catalog_plan import CatalogPlan
    from edgar_sec.pipelines.document_storage.work_order import ChunkInput

    source = fixture_path("catalog/sample_submission_metadata.parquet")
    destination = source.parent / "era_resolution_metadata.parquet"
    destination.unlink(missing_ok=True)
    stale = destination.parent / "manifest.json"
    stale.unlink(missing_ok=True)
    artifacts = destination.parent / "art"
    try:
        from tests.support import era_submission_metadata

        destination = era_submission_metadata(destination)

        artifacts = destination.parent / "art"
        artifacts.mkdir(parents=True, exist_ok=True)
        meta_path = destination.parent / "manifest.json"
        if not meta_path.exists():
            import json
            from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
            from edgar_sec.pipelines.filing_catalog.planner import plan

            manifest = materialize(str(destination), artifacts)
            plan(str(manifest["catalog_id"]), artifacts)
            meta_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        plan_dir = None
        for d in (artifacts / "filing_catalog" / "plans").iterdir():
            if d.is_dir() and (d / "plan.json").exists():
                plan_dir = d
                break
        assert plan_dir is not None, "plan directory not found under artifacts"
        catalog_plan = CatalogPlan(str(plan_dir), chunk_size=8)
        target_locator = None
        target_occurrences: list[FilingOccurrence] = []
        for chunk in catalog_plan.iter_chunks():
            for loc in chunk.locators:
                if loc.document_path == "ex21.txt" and loc.accession.raw == ACCESSION:
                    target_locator = loc
                    target_occurrences = [
                        o for o in chunk.occurrences if o.accession.raw == ACCESSION
                    ]
                    break
            if target_locator:
                break
        assert target_locator is not None, "ex21 locator not found in plan"
        assert len(target_occurrences) >= 2, "expect the two co-filers"

        bundle = load_document_storage_fixture("exhibit_primary.sgm")
        assert has_sgml_documents(bundle)
        request = _requested_ref(
            target_locator,
            AcquisitionSource(kind=AcquisitionSourceKind.FIXTURE, reference=str(b"")),
        )
        occurrences_before = list(target_occurrences)
        result = resolve_candidate_filing(
            request, occurrences_before, BundleFetchResult(status="ok", payload=bundle)
        )
        assert result.outcome is FilingResolutionOutcome.PRIMARY_RECOVERED
        assert result.exhibit is result.requested
        assert result.primary.locator.document_path == "a10k.htm"
        assert [r.occurrence_id for r in occurrences_before] == [
            r.occurrence_id for r in target_occurrences
        ]

    finally:
        if destination.exists():
            destination.unlink()
        stale.unlink(missing_ok=True)
        if artifacts.exists():
            shutil.rmtree(artifacts, ignore_errors=True)
