from __future__ import annotations

import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from edgar_sec.domain.document_inventory.models import (
    InventoryEntry,
    ParsedIndexPage,
    ParserDiagnostics,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    FixturePlanPin,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.plan_capture import (
    capture_fixture_plan,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_cases,
    read_fixture_lazy_index,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_planning.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
)
from edgar_sec.foundation.serialization import canonical_hash
from tests.pipelines.document_acquisition.plan_projection.plan_fixture import (
    write_plan_bundle,
)

_ACCESSION = "0000000001-24-000001"
_COMPACT = _ACCESSION.replace("-", "")
_ROOT_URL = f"https://www.sec.gov/Archives/edgar/data/1/{_COMPACT}/"


class _Transport:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse

        self.calls.append(url)
        body = self.responses[url]
        if len(body) > max_response_bytes:
            return StreamFailure("response_too_large", False, None, "too large")
        validate_redirect(url)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return StreamedResponse(
            200,
            url,
            url,
            hashlib.sha256(body).hexdigest(),
            len(body),
            "text/html",
            None,
            destination,
        )


def _write_fixture_plan(
    paths, *, lazy: bool, target_count: int = 1, bundle: bool = False
):
    catalog_only = lazy
    identity = {
        "bundle_schema_version": target_plan_bundle_schema_version(),
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
        "matcher_version": target_plan_matcher_version(),
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "c" * 64,
        "catalog_plan_id": "catalog-fixture",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": None if catalog_only else "snapshot-fixture",
        "inventory_snapshot_digest": None if catalog_only else "b" * 64,
    }
    plan_id = f"dplan_{canonical_hash(identity)[:32]}"
    plan_root = paths.target_plan_dir(plan_id)
    plan_root.mkdir(parents=True)
    targets = []
    for index in range(target_count):
        request_id = f"primary:primary:{index}"
        target = {
            "target_id": "",
            "accession": _ACCESSION,
            "form": "10-K",
            "filing_date": "2024-01-01",
            "request_id": request_id,
            "target_role": "primary",
            "target_type": "primary",
            "optional": False,
            "inventory_entry_id": None if catalog_only else f"entry-{index}",
            "status": "matched",
            "status_reason": None,
            "source_origin": "catalog_direct" if catalog_only else "inventory_index",
            "retrieval_mode": "bundle_sequence" if bundle else "direct_url",
            "target_url": (
                f"{_ROOT_URL}{_ACCESSION}.txt"
                if lazy or bundle
                else f"{_ROOT_URL}report.htm"
            ),
            "sequence": 1 if lazy or bundle else None,
            "byte_size": None,
            "availability_evidence": "catalog_direct" if catalog_only else "index_html",
            "catalog_direct_selection": (
                "exact_form_with_lazy_index" if lazy else None
            ),
        }
        target["target_id"] = canonical_hash(
            [
                plan_id,
                target["accession"],
                request_id,
                target["inventory_entry_id"],
                "matched",
            ]
        )
        targets.append(target)
    manifest = write_plan_bundle(plan_root, plan_id, identity, targets)
    pin = FixturePlanPin(plan_id, manifest["plan_digest"], TARGET_SCHEMA_VERSION)
    return create_fixture("fixture-plan", pin, paths=paths), pin


def test_fixture_fill_fetches_plan_body_without_acquisition_run(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=False)
    body = b"<html><body>offline parser input</body></html>"
    url = f"{_ROOT_URL}report.htm"
    transport = _Transport({url: body})

    result = capture_fixture_plan(
        "fixture-plan", paths=paths, max_body_bytes=1024, transport=transport
    )

    cases = list(list_fixture_cases(paths, fixture_id="fixture-plan"))
    assert result.captured_cases == 1
    assert result.failed_targets == 0
    assert result.skipped_targets == 0
    assert transport.calls == [url]
    assert cases[0].selection_source == "inventory_index"
    assert cases[0].body_sha256 == hashlib.sha256(body).hexdigest()
    assert cases[0].index_sha256 is None


def test_fixture_fill_extracts_the_pinned_bundle_sequence(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=False, bundle=True)
    selected = b"<html>selected child</html>"
    source = (
        b"<DOCUMENT>\n<TYPE>EX-10.1\n<SEQUENCE>1\n<FILENAME>report.htm\n<TEXT>"
        + selected
        + b"</TEXT>\n</DOCUMENT>\n"
    )
    url = f"{_ROOT_URL}{_ACCESSION}.txt"
    transport = _Transport({url: source})

    result = capture_fixture_plan(
        "fixture-plan", paths=paths, max_body_bytes=1024, transport=transport
    )

    case = next(list_fixture_cases(paths, fixture_id="fixture-plan"))
    assert result.captured_cases == 1
    assert case.retrieval_mode == "bundle_sequence"
    assert case.selected_filename == "report.htm"
    assert case.body_sha256 == hashlib.sha256(selected).hexdigest()


def test_concurrent_fixture_fills_are_serialized_before_network_access(
    tmp_path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=False)
    url = f"{_ROOT_URL}report.htm"
    started = Event()
    release = Event()

    class _BlockingTransport(_Transport):
        def stream_to_file(self, *args, **kwargs):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("blocking fixture test timed out")
            return super().stream_to_file(*args, **kwargs)

    first_transport = _BlockingTransport({url: b"<html>body</html>"})
    second_transport = _Transport({url: b"<html>body</html>"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            capture_fixture_plan,
            "fixture-plan",
            paths=paths,
            max_body_bytes=1024,
            transport=first_transport,
        )
        assert started.wait(timeout=5)
        try:
            with pytest.raises(FixtureOperationError, match="already in progress"):
                capture_fixture_plan(
                    "fixture-plan",
                    paths=paths,
                    max_body_bytes=1024,
                    transport=second_transport,
                )
        finally:
            release.set()
        result = first.result(timeout=5)

    assert result.captured_cases == 1
    assert len(list(list_fixture_cases(paths, fixture_id="fixture-plan"))) == 1
    assert second_transport.calls == []


def test_lazy_index_is_fetched_and_cached_once_per_fixture(tmp_path, monkeypatch):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=True, target_count=2)
    index_url = f"{_ROOT_URL}{_ACCESSION}-index.html"
    body_url = f"{_ROOT_URL}report.htm"
    index_body = b"<html>cached filing index</html>"
    body = b"<html>selected filing body</html>"
    transport = _Transport({index_url: index_body, body_url: body})
    entry = InventoryEntry(
        entry_id="entry-form",
        accession=AccessionNumber(_ACCESSION),
        table_kind="document_format",
        row_ordinal=1,
        sequence=1,
        document_type="10-K",
        document_label="10-K",
        description="Annual report",
        filename="report.htm",
        href="report.htm",
        archive_url=body_url,
        byte_size=len(body),
    )

    def parse_index(page):
        return ParsedIndexPage(
            page.accession,
            page.source_url,
            hashlib.sha256(page.response_bytes).hexdigest(),
            (entry,),
            f"{_ROOT_URL}{_ACCESSION}.txt",
            len(index_body),
            None,
            ParserDiagnostics((), 0),
        )

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.fixture_store.plan_capture.parse_html_index",
        parse_index,
    )

    result = capture_fixture_plan(
        "fixture-plan", paths=paths, max_body_bytes=1024, transport=transport
    )

    cases = list(list_fixture_cases(paths, fixture_id="fixture-plan"))
    cached = read_fixture_lazy_index(paths, "fixture-plan", _ACCESSION)
    assert result.captured_cases == 2
    assert result.fetched_lazy_indexes == 1
    assert result.reused_lazy_indexes == 1
    assert Counter(transport.calls) == Counter({index_url: 1, body_url: 2})
    assert all(case.selection_source == "fixture_lazy_index" for case in cases)
    assert all(case.index_sha256 == cached.body_sha256 for case in cases)
    assert cached.body == index_body
    assert list_fixture_summaries(paths)[0].lazy_index_count == 1


def test_lazy_index_bundle_must_match_the_selected_form(tmp_path, monkeypatch):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=True)
    index_url = f"{_ROOT_URL}{_ACCESSION}-index.html"
    bundle_url = f"{_ROOT_URL}{_ACCESSION}.txt"
    index_body = b"<html>index</html>"
    bundle_body = (
        b"<DOCUMENT>\n<TYPE>EX-10.1\n<SEQUENCE>1\n<FILENAME>report.htm\n"
        b"<TEXT>not the planned form</TEXT>\n</DOCUMENT>\n"
    )
    transport = _Transport({index_url: index_body, bundle_url: bundle_body})
    entry = InventoryEntry(
        entry_id="bundle-form",
        accession=AccessionNumber(_ACCESSION),
        table_kind="document_format",
        row_ordinal=1,
        sequence=1,
        document_type="10-K",
        document_label="10-K",
        description="Annual report",
        filename="report.htm",
        href=None,
        archive_url=None,
        byte_size=None,
    )

    def parse_index(page):
        return ParsedIndexPage(
            page.accession,
            page.source_url,
            hashlib.sha256(page.response_bytes).hexdigest(),
            (entry,),
            bundle_url,
            len(index_body),
            None,
            ParserDiagnostics((), 0),
        )

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.fixture_store.plan_capture.parse_html_index",
        parse_index,
    )

    result = capture_fixture_plan(
        "fixture-plan", paths=paths, max_body_bytes=1024, transport=transport
    )

    assert result.captured_cases == 0
    assert result.failed_targets == 1
    assert result.failure_counts == {"source_mismatch": 1}
    assert list(list_fixture_cases(paths, fixture_id="fixture-plan")) == []
    assert read_fixture_lazy_index(paths, "fixture-plan", _ACCESSION).body == index_body


def test_fixture_fill_rejects_oversized_response(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _write_fixture_plan(paths, lazy=False)
    url = f"{_ROOT_URL}report.htm"
    transport = _Transport({url: b"larger than limit"})

    result = capture_fixture_plan(
        "fixture-plan", paths=paths, max_body_bytes=4, transport=transport
    )

    assert result.captured_cases == 0
    assert result.failed_targets == 1
    assert result.failure_counts == {"response_too_large": 1}
    assert list(list_fixture_cases(paths, fixture_id="fixture-plan")) == []
