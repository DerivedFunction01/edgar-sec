"""Series/class command: the refresh drive over a fake HTTP client."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.domain.browse_urls import browse_series_url
from edgar_sec.pipelines.metadata_sync.commands.series_class import (
    MF_TICKER_URL,
    cmd_series_class_refresh,
    read_series_class_reconciliation,
    read_series_class_status,
    refresh_series_class,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.series_class import (
    read_tickered_rows,
    reconcile_series_class,
    series_class_tip,
)
from tests.support import fixture_path


class _FakeHttp:
    """Serves the MF payload and per-URL pages; named URLs raise instead."""

    def __init__(
        self,
        mf_payload: bytes,
        pages: dict[str, bytes] | None = None,
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self._mf_payload = mf_payload
        self._pages = pages or {}
        self._failing = failing
        self.requested: list[str] = []

    def get_bytes(
        self,
        url: str,
        content_kind: str = "bytes",
        *,
        force_refresh: bool = False,
        mutable: bool = False,
    ) -> bytes:
        self.requested.append(url)
        if url in self._failing:
            raise RuntimeError(f"fetch failed: {url}")
        if url == MF_TICKER_URL:
            return self._mf_payload
        if url in self._pages:
            return self._pages[url]
        raise RuntimeError(f"unexpected URL: {url}")


def _mf_payload(*rows: list) -> bytes:
    return json.dumps(
        {"fields": ["cik", "seriesId", "classId", "symbol"], "data": rows}
    ).encode()


def _specimen_page() -> bytes:
    return fixture_path("browse_edgar_series_0000002663.html").read_bytes()


def _drive_http() -> _FakeHttp:
    payload = _mf_payload(
        [2663, "S000008702", "C000023718", "IVMXX"],
        [9999, "S000000099", "C000000099", "ZZZ"],
    )
    return _FakeHttp(
        payload,
        pages={browse_series_url(2663): _specimen_page()},
        failing=frozenset({browse_series_url(9999)}),
    )


def test_refresh_accounts_every_cik_and_publishes(tmp_path: Path) -> None:
    outcome = refresh_series_class(artifacts_root=tmp_path, http=_drive_http())

    assert outcome.population == 2
    assert outcome.parsed_ingested == 1
    assert outcome.fetch_failures == 1
    assert outcome.parse_failures == 0
    assert outcome.unrecognized == 0
    assert outcome.failure_samples == (("0000009999", "fetch_failure"),)
    assert outcome.publish.published is True
    assert outcome.tip_after is not None
    paths = resolve_metadata_paths(tmp_path)
    assert series_class_tip(paths) == outcome.tip_after
    assert len(read_tickered_rows(paths)) == 2
    counts = outcome.reconciliation
    assert counts.classes_in_both == 1
    assert counts.classes_browse_only == 3
    assert counts.classes_file_only == 1
    assert counts.symbol_agreements == 1
    assert counts.symbol_disagreements == 0


def test_repeat_refresh_publishes_no_new_snapshot(tmp_path: Path) -> None:
    first = refresh_series_class(artifacts_root=tmp_path, http=_drive_http())
    second = refresh_series_class(artifacts_root=tmp_path, http=_drive_http())

    assert second.publish.published is False
    assert second.publish.snapshot_id is None
    assert second.tip_after == first.tip_after


def test_ciks_option_scopes_the_drive(tmp_path: Path) -> None:
    http = _drive_http()

    outcome = refresh_series_class(artifacts_root=tmp_path, ciks=("2663",), http=http)

    assert outcome.population == 1
    assert outcome.parsed_ingested == 1
    assert browse_series_url(9999) not in http.requested


def test_unrecognized_and_parse_failure_are_accounted(tmp_path: Path) -> None:
    payload = _mf_payload(
        [2663, "S000008702", "C000023718", "IVMXX"],
        [3521, "S000000001", "C000000001", "AAA"],
    )
    specimen = _specimen_page()
    drifted = specimen.replace(b"Items 1 - 5", b"Items 1 - 9")
    assert drifted != specimen
    http = _FakeHttp(
        payload,
        pages={
            browse_series_url(2663): drifted,
            browse_series_url(3521): fixture_path(
                "browse_edgar_company_0000003521.html"
            ).read_bytes(),
        },
    )

    outcome = refresh_series_class(artifacts_root=tmp_path, http=http)

    assert outcome.population == 2
    assert outcome.parsed_ingested == 0
    assert outcome.parse_failures == 1
    assert outcome.unrecognized == 1
    assert dict(outcome.failure_samples) == {
        "0000002663": "parse_failure",
        "0000003521": "unrecognized",
    }


def test_status_and_reconciliation_readers(tmp_path: Path) -> None:
    empty = read_series_class_status(artifacts_root=tmp_path)
    assert empty.tip is None
    assert empty.tickered_rows == 0
    assert empty.browse_class_rows == 0

    refresh_series_class(artifacts_root=tmp_path, http=_drive_http())

    status = read_series_class_status(artifacts_root=tmp_path)
    assert status.tip is not None
    assert status.tickered_rows == 2
    assert status.browse_class_rows == 4
    assert status.browse_series_rows == 1
    paths = resolve_metadata_paths(tmp_path)
    assert read_series_class_reconciliation(
        artifacts_root=tmp_path
    ) == reconcile_series_class(paths)


def test_cmd_series_class_refresh_renders_and_returns_zero(
    tmp_path: Path,
) -> None:
    result = cmd_series_class_refresh(artifacts_root=tmp_path, http=_drive_http())

    assert result == 0
    paths = resolve_metadata_paths(tmp_path)
    assert series_class_tip(paths) is not None
