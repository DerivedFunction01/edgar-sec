"""Tests for fixture-backed review artifact generation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import DocumentLocator, RawDocumentBlob
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.paths import REVIEW_MANIFEST_NAME
from edgar_sec.pipelines.document_storage.review_artifacts import (
    ReviewArtifactError,
    ReviewCase,
    bounded_analysis,
    render_review_run,
    run_review_case,
    sanitized_source_html,
    select_review_cases,
    write_review_artifacts,
)

ASCII_SOURCE = (
    b"UNITED STATES\n"
    b"SECURITIES AND EXCHANGE COMMISSION\n"
    b"\n"
    b"FORM 10-K\n"
    b"\n"
    b"Item 1. Business\n"
    b"\n"
    b"We do things.\n"
)
HTML_SOURCE = (
    b"<html><head><script>evil()</script><style>a{}</style></head>"
    b'<body><a href="http://x/" onclick="steal()">link</a>'
    b"<table><tr><td>1</td></tr></table></body></html>"
)
#: Non-ASCII bytes that must survive a review run that stores the payload verbatim.
PDF_SOURCE = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
PAPER_SOURCE = (
    b"<SEC-DOCUMENT>\n<TEXT>\nThis document was generated as part of a paper "
    b"submission.\n</TEXT>\n</SEC-DOCUMENT>\n"
)
WRAPPED_SOURCE = (
    b"The registrant agrees to report on a\nfiscal year basis, as amended.\n"
)


def _paths(root: Path) -> ProjectPaths:
    return ProjectPaths(root, root / ".artifacts", root / "uploads")


def _seed(
    paths: ProjectPaths,
    fixture_id: str = "fix-review",
    forms: dict[str, str] | None = None,
) -> dict[str, DocumentLocator]:
    """Write a fixture directly, so tests never reach the network."""
    locators = {
        "alpha.txt": DocumentLocator.from_parts(
            "0001234567-11-000001", "alpha.txt", form="10-K"
        ),
        "beta.htm": DocumentLocator.from_parts(
            "0001234567-11-000002", "beta.htm", form="10-K"
        ),
        "gamma.htm": DocumentLocator.from_parts(
            "0001234567-11-000003", "gamma.htm", form="10-K"
        ),
    }
    payloads = {
        "alpha.txt": ASCII_SOURCE,
        "beta.htm": HTML_SOURCE,
        "gamma.htm": HTML_SOURCE,
    }
    from edgar_sec.domain.document.models import RawDocumentBlob

    with FixtureStore(paths.fixture_db_path(fixture_id)) as store:
        store.put_many(
            [
                (locators[name].document_locator_key, payload)
                for name, payload in payloads.items()
            ]
        )
        store.put_documents(
            [
                RawDocumentBlob(
                    doc_id=locators[name].document_locator_key,
                    accession=str(locators[name].accession),
                    document_path=name,
                    byte_size=len(payload),
                    mime_type="text/html" if name.endswith(".htm") else "text/plain",
                    raw_payload_sha256=__import__("hashlib")
                    .sha256(payload)
                    .hexdigest(),
                )
                for name, payload in payloads.items()
            ],
            forms or {},
        )
    (paths.fixture_manifest_path(fixture_id)).parent.mkdir(parents=True, exist_ok=True)
    paths.fixture_manifest_path(fixture_id).write_text(
        json.dumps({"fixture_id": fixture_id, "forms": ["10-K"]}), encoding="utf-8"
    )
    return locators


def test_selection_is_ordered_and_limitable(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths)
    selection = select_review_cases(paths, "fix-review")
    assert not selection.failures
    cases = selection.cases
    assert [case.document.document_path for case in cases] == [
        "alpha.txt",
        "beta.htm",
        "gamma.htm",
    ]
    # A limit takes the first N of a stable order, or two runs would drift apart.
    limited = select_review_cases(paths, "fix-review", limit=2).cases
    assert [case.document.doc_id for case in limited] == [
        case.document.doc_id for case in cases[:2]
    ]


def test_selection_matches_document_id_or_path_suffix(tmp_path: Path) -> None:
    """A reviewer knows the filename long before they know the digest."""
    paths = _paths(tmp_path)
    locators = _seed(paths)
    by_suffix = select_review_cases(paths, "fix-review", ids=["BETA.HTM"]).cases
    assert [case.document.doc_id for case in by_suffix] == [
        locators["beta.htm"].document_locator_key
    ]
    by_id = select_review_cases(
        paths, "fix-review", ids=[locators["gamma.htm"].document_locator_key]
    ).cases
    assert [case.document.document_path for case in by_id] == ["gamma.htm"]


def test_selection_filters_by_extension(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths)
    cases = select_review_cases(paths, "fix-review", extensions=["htm"]).cases
    assert [case.document.document_path for case in cases] == ["beta.htm", "gamma.htm"]


def test_form_falls_back_to_the_manifest_when_not_recorded(tmp_path: Path) -> None:
    """The form selects the processing plugin, so a guess must be visible."""
    paths = _paths(tmp_path)
    _seed(paths, forms={})
    case = select_review_cases(paths, "fix-review", ids=["alpha.txt"]).cases[0]
    assert case.form == "10-K"
    assert case.form_source == "manifest"


def test_per_document_form_is_preferred_over_the_manifest(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    locators = _seed(paths)
    with FixtureStore(paths.fixture_db_path("fix-review")) as store:
        store.put_documents(
            [],
            {locators["alpha.txt"].document_locator_key: "10-Q"},
        )
    case = select_review_cases(paths, "fix-review", ids=["alpha.txt"]).cases[0]
    assert (case.form, case.form_source) == ("10-Q", "document")


def test_selection_refuses_a_fixture_without_document_metadata(tmp_path: Path) -> None:
    """The failure has to name the repair, not just report an empty selection."""
    paths = _paths(tmp_path)
    _seed(paths)
    with sqlite3.connect(paths.fixture_db_path("fix-review")) as connection:
        connection.execute("DROP TABLE document_blobs")
        connection.commit()
    with pytest.raises(ReviewArtifactError, match="documents fill"):
        select_review_cases(paths, "fix-review")


def test_corrupt_payload_skips_one_document_instead_of_the_run(
    tmp_path: Path,
) -> None:
    """One corrupt document must not withhold review of the rest."""
    paths = _paths(tmp_path)
    _seed(paths)
    with sqlite3.connect(paths.fixture_db_path("fix-review")) as connection:
        connection.execute(
            "UPDATE document_blobs SET raw_payload_sha256 = ? WHERE document_path = 'alpha.txt'",
            ("f" * 64,),
        )
        connection.commit()
    selection = select_review_cases(paths, "fix-review")
    assert [case.document.document_path for case in selection.cases] == [
        "beta.htm",
        "gamma.htm",
    ]
    assert len(selection.failures) == 1
    assert "hash mismatch" in selection.failures[0]


def test_render_writes_one_case_per_document(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths)
    output = tmp_path / "run-a"
    result = render_review_run(paths, "fix-review", output, workers=1)
    assert result.rendered == result.selected == 3
    assert not result.failures
    assert result.manifest_path == output / REVIEW_MANIFEST_NAME

    manifest = [
        json.loads(line)
        for line in result.manifest_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["document_id"] for entry in manifest] == sorted(
        entry["document_id"] for entry in manifest
    )
    for entry in manifest:
        case_dir = output / "cases" / entry["document_id"]
        assert (case_dir / f"{entry['document_id']}.txt").is_file()
        assert (case_dir / f"{entry['document_id']}.analysis.json").is_file()
        # Source separates "the normalizer dropped it" from "never there".
        source = case_dir / f"{entry['document_id']}.source.txt"
        assert source.is_file()
        assert entry["fixture_id"] == "fix-review"


def test_source_bytes_are_written_verbatim(tmp_path: Path) -> None:
    """The source file is the fetched bytes, not a re-encoding of them."""
    paths = _paths(tmp_path)
    locators = _seed(paths)
    output = tmp_path / "run-a"
    render_review_run(paths, "fix-review", output, ids=["alpha.txt"], workers=1)
    document_id = locators["alpha.txt"].document_locator_key
    written = (
        output / "cases" / document_id / f"{document_id}.source.txt"
    ).read_bytes()
    assert written == ASCII_SOURCE


def test_html_view_is_written_only_for_html_documents(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    locators = _seed(paths)
    output = tmp_path / "run-a"
    render_review_run(paths, "fix-review", output, workers=1)
    html_id = locators["beta.htm"].document_locator_key
    ascii_id = locators["alpha.txt"].document_locator_key
    assert (output / "cases" / html_id / f"{html_id}.html").is_file()
    assert not (output / "cases" / ascii_id / f"{ascii_id}.html").exists()


def test_sanitized_html_drops_script_style_and_unsafe_attributes() -> None:
    rendered = sanitized_source_html(HTML_SOURCE.decode())
    assert "evil()" not in rendered
    assert "a{}" not in rendered
    assert "onclick" not in rendered
    assert 'href="http://x/"' not in rendered
    # The document body survives, which is the point of rendering it at all.
    assert "link" in rendered
    assert "Item" not in rendered  # never present; guards against over-stripping


def test_render_refuses_a_non_empty_output_directory(tmp_path: Path) -> None:
    """Two runs sharing an output root cannot be compared, so this is refused."""
    paths = _paths(tmp_path)
    _seed(paths)
    output = tmp_path / "run-a"
    render_review_run(paths, "fix-review", output, workers=1)
    with pytest.raises(ReviewArtifactError, match="already contains artifacts"):
        render_review_run(paths, "fix-review", output, workers=1)


def test_render_reports_an_empty_selection(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed(paths)
    with pytest.raises(ReviewArtifactError, match="no reviewable documents"):
        render_review_run(paths, "fix-review", tmp_path / "empty", ids=["absent.htm"])


def test_one_failing_document_does_not_end_the_run(tmp_path: Path) -> None:
    """A single bad filing is a result to report, not a reason to lose the rest."""
    paths = _paths(tmp_path)
    locators = _seed(paths)
    alpha = locators["alpha.txt"].document_locator_key
    with sqlite3.connect(paths.fixture_db_path("fix-review")) as connection:
        connection.execute("DELETE FROM fixture_payloads WHERE doc_id = ?", (alpha,))
        connection.commit()
    result = render_review_run(paths, "fix-review", tmp_path / "run-a", workers=1)
    assert result.failures
    assert result.rendered == 2
    assert result.selected == 3


# --- route parity with the worker ------------------------------------------


def _binary_case(document_path: str) -> ReviewCase:
    return ReviewCase(
        document=RawDocumentBlob(
            doc_id="doc-pdf",
            accession="0001234567-11-000001",
            document_path=document_path,
            byte_size=len(PDF_SOURCE),
            mime_type="application/pdf",
            raw_payload_sha256=hashlib.sha256(PDF_SOURCE).hexdigest(),
        ),
        form="8-K",
        form_source="fixture",
        payload=PDF_SOURCE,
    )


def test_review_defers_a_binary_document(tmp_path: Path) -> None:
    """Review must reach the same outcome the worker does, or it verifies nothing."""
    result = run_review_case(_binary_case("chart.pdf"))

    assert result.normalization is None
    assert result.text == ""


def test_review_analysis_records_why_a_document_was_deferred() -> None:
    analysis = bounded_analysis(None)

    assert analysis == {"normalization": "deferred", "reason": "binary document"}


def test_review_manifest_reports_raw_for_a_deferred_document(tmp_path: Path) -> None:
    entry = write_review_artifacts(
        run_review_case(_binary_case("chart.pdf")), tmp_path / "run", "fix-x"
    )

    assert entry["representation"] == "raw"


def test_review_writes_binary_bytes_verbatim(tmp_path: Path) -> None:
    """A lost byte must stay distinguishable from a byte that was never there."""
    result = run_review_case(_binary_case("chart.pdf"))
    write_review_artifacts(result, tmp_path / "run", "fix-x")

    assert (tmp_path / "run" / "doc-pdf.source.txt").read_bytes() == PDF_SOURCE
    assert (tmp_path / "run" / "doc-pdf.txt").read_text() == "\n"


def _rendered_case() -> ReviewCase:
    return ReviewCase(
        document=RawDocumentBlob(
            doc_id="doc-rendered",
            accession="0001234567-11-000001",
            document_path="xslF345X02/edgar.xml",
            byte_size=len(HTML_SOURCE),
            mime_type="text/html",
            raw_payload_sha256=hashlib.sha256(HTML_SOURCE).hexdigest(),
        ),
        form="4",
        form_source="fixture",
        payload=HTML_SOURCE,
    )


def test_review_gives_a_rendered_document_a_browser_view(tmp_path: Path) -> None:
    """A rendering is served as HTML, so a suffix-only test withheld the view."""
    write_review_artifacts(run_review_case(_rendered_case()), tmp_path / "run", "fix-x")

    assert (tmp_path / "run" / "doc-rendered.html").is_file()


def test_review_withholds_a_browser_view_from_a_text_document(tmp_path: Path) -> None:
    case = ReviewCase(
        document=RawDocumentBlob(
            doc_id="doc-txt",
            accession="0001234567-11-000001",
            document_path="alpha.txt",
            byte_size=len(ASCII_SOURCE),
            mime_type="text/plain",
            raw_payload_sha256=hashlib.sha256(ASCII_SOURCE).hexdigest(),
        ),
        form="10-K",
        form_source="fixture",
        payload=ASCII_SOURCE,
    )
    write_review_artifacts(run_review_case(case), tmp_path / "run", "fix-x")

    assert not (tmp_path / "run" / "doc-txt.html").exists()


def test_review_routes_a_paper_stub_like_the_worker() -> None:
    """Without the path, review ran six stages where the worker runs one."""
    case = ReviewCase(
        document=RawDocumentBlob(
            doc_id="doc-paper",
            accession="0001234567-11-000001",
            document_path="9999999997-25-001505.paper",
            byte_size=len(PAPER_SOURCE),
            mime_type="text/plain",
            raw_payload_sha256=hashlib.sha256(PAPER_SOURCE).hexdigest(),
        ),
        form="REGDEX",
        form_source="fixture",
        payload=PAPER_SOURCE,
    )

    result = run_review_case(case)

    assert result.normalization is not None
    assert [record.stage for record in result.normalization.stage_trace] == ["unpacked"]


def test_review_reflows_a_no_cover_text_document_like_the_worker() -> None:
    case = ReviewCase(
        document=RawDocumentBlob(
            doc_id="doc-txt",
            accession="0001234567-11-000001",
            document_path="note.txt",
            byte_size=len(WRAPPED_SOURCE),
            mime_type="text/plain",
            raw_payload_sha256=hashlib.sha256(WRAPPED_SOURCE).hexdigest(),
        ),
        form="REGDEX",
        form_source="fixture",
        payload=WRAPPED_SOURCE,
    )

    result = run_review_case(case)

    assert result.normalization is not None
    assert result.normalization.reflow is not None
    assert len(result.text.splitlines()) == 1
