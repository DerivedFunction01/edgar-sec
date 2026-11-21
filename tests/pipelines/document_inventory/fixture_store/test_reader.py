from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.fixture_store.discovery import (
    discover_index_fixtures,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    IndexFixtureError,
)
from edgar_sec.pipelines.document_inventory.fixture_store.reader import (
    list_fixture,
    open_index_fixture,
    replay_index_page,
)
from edgar_sec.pipelines.document_inventory.paths import inventory_paths

from .conftest import contribution, make_cohort


def _captured(tmp_path: Path, broker_for, body: bytes = b"<html>page</html>"):
    accession = "0000123456-12-000001"
    url = "https://www.sec.gov/Archives/edgar/data/123456/index.html"
    cohort = make_cohort(accession, "123456789", "source-a", url)
    fixture = inventory_paths(tmp_path).index_fixture_paths("fixture")
    create_index_fixture(fixture, fixture_id="fixture")
    capture_index_pages(
        cohort,
        fixture_id="fixture",
        paths=fixture,
        broker=broker_for({url: body}).broker,
        contribution=contribution(cohort),
    )
    return fixture, accession, url


def test_replay_returns_exact_decompressed_body(tmp_path: Path, broker_for) -> None:
    body = b"<html>" + b"x" * 8192 + b"</html>"
    paths, accession, url = _captured(tmp_path, broker_for, body)
    with open_index_fixture(paths) as reader:
        case = reader.list_cases(AccessionNumber(accession))[0]
        page = reader.replay(case.accession, case.key)
        assert page.body == body
        assert page.byte_size == len(body)
        assert page.key.request_url == url
        assert page.key.response_sha256 == sha256_bytes(body)
        assert page.accession == AccessionNumber(accession)


def test_case_iteration_is_bounded_and_deterministic(
    tmp_path: Path, broker_for
) -> None:
    paths, accession, _ = _captured(tmp_path, broker_for)
    with open_index_fixture(paths) as reader:
        cases = tuple(reader.iter_cases(batch_size=1))
        assert len(cases) == 1
        assert cases[0].accession == AccessionNumber(accession)
        assert reader.list_cases(accession) == cases
        with pytest.raises(ValueError, match="use iter_cases"):
            reader.list_cases()


def test_missing_manifest_refuses_replay(tmp_path: Path, broker_for) -> None:
    paths, accession, _ = _captured(tmp_path, broker_for)
    with open_index_fixture(paths) as reader:
        key = reader.list_cases(accession)[0].key
    paths.manifest_path.unlink()
    with pytest.raises(IndexFixtureError, match="manifest missing"):
        replay_index_page(paths, accession, key)


@pytest.mark.parametrize("schema_version", [True, 2.0])
def test_non_integer_schema_version_refuses_before_database_validation(
    tmp_path: Path, broker_for, schema_version: bool | float
) -> None:
    paths, _, _ = _captured(tmp_path, broker_for)
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    manifest["details"]["store_schema_version"] = schema_version
    paths.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IndexFixtureError, match="schema_version must be an integer"):
        with open_index_fixture(paths):
            pass


def test_tampered_selected_body_fails_digest_check(tmp_path: Path, broker_for) -> None:
    paths, accession, _ = _captured(tmp_path, broker_for)
    with open_index_fixture(paths) as reader:
        case = reader.list_cases(accession)[0]
    with sqlite3.connect(paths.storage_path) as connection:
        connection.execute(
            "UPDATE index_responses SET compressed_body = ?",
            (b"not-a-compressed-page",),
        )
    with pytest.raises(IndexFixtureError, match="cannot be decompressed"):
        replay_index_page(paths, accession, case.key)


def test_discovery_uses_inventory_paths_and_skips_damaged_manifests(
    tmp_path: Path, broker_for
) -> None:
    paths, _, _ = _captured(tmp_path, broker_for)
    summary = discover_index_fixtures(inventory_paths(tmp_path).fixtures_root)
    assert [item["fixture_id"] for item in summary] == ["fixture"]
    damaged = inventory_paths(tmp_path).fixture_root("damaged")
    damaged.mkdir(parents=True)
    (damaged / "manifest.json").write_text("not-json", encoding="utf-8")
    assert len(discover_index_fixtures(inventory_paths(tmp_path).fixtures_root)) == 1


def test_list_reports_fixture_counts(tmp_path: Path, broker_for) -> None:
    paths, _, _ = _captured(tmp_path, broker_for)
    summary = list_fixture(paths)
    assert summary.database_integrity_ok is True
    assert (
        summary.page_count == summary.accession_count == summary.membership_count == 1
    )
    assert summary.state == "complete"
