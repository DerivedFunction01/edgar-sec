"""Capture pins, stamps, reuse, and replay of product fixtures."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.pipelines.table_classification.fixture_store.capture import (
    capture_results,
)
from edgar_sec.pipelines.table_classification.fixture_store.discovery import (
    discover_fixtures,
)
from edgar_sec.pipelines.table_classification.fixture_store.models import (
    FixtureStoreError,
    PlanPin,
    ProductStamps,
)
from edgar_sec.pipelines.table_classification.fixture_store.reader import (
    list_fixture_cases,
    read_case_products,
    validate_stamps,
)
from tests.pipelines.table_classification.fixture_store.test_products import _result

_PIN = PlanPin(
    plan_format_version="1.0.0",
    plan_id="tcplan-" + sha256(b"plan").hexdigest()[:16],
    registry_state="sha256:" + sha256(b"registry").hexdigest(),
    source_snapshot_id="snapshot-1",
)
_STAMPS = ProductStamps(
    normalize_version="normalize-1", renderer_version="r1", page_policy="annotate"
)


def _capture(root: Path, stamps: ProductStamps = _STAMPS, pin: PlanPin = _PIN):
    return capture_results(
        root, "fx1", pin, (("0000000000-00-000000", "primary", _result(), stamps),)
    )


def test_capture_and_replay(tmp_path: Path) -> None:
    outcome = _capture(tmp_path)
    assert outcome.cases_added == 1
    cases = list_fixture_cases(tmp_path, "fx1")
    assert len(cases) == 1
    assert cases[0].stamps == _STAMPS
    stamps, rebuilt = read_case_products(tmp_path, "fx1", cases[0].key.case_id)
    assert stamps == _STAMPS
    live = _result()
    assert rebuilt.text == live.text
    assert len(rebuilt.table_geometries) == len(live.table_geometries)


def test_capture_reuses_identical_products(tmp_path: Path) -> None:
    _capture(tmp_path)
    outcome = _capture(tmp_path)
    assert outcome.cases_added == 0
    assert outcome.cases_reused == 1


def test_capture_refuses_a_different_pin(tmp_path: Path) -> None:
    _capture(tmp_path)
    other = PlanPin(
        plan_format_version="1.0.0",
        plan_id="tcplan-" + sha256(b"other").hexdigest()[:16],
        registry_state="sha256:" + sha256(b"registry").hexdigest(),
        source_snapshot_id="snapshot-1",
    )
    with pytest.raises(FixtureStoreError):
        _capture(tmp_path, pin=other)


def test_capture_refuses_different_stamps(tmp_path: Path) -> None:
    _capture(tmp_path)
    other = ProductStamps(
        normalize_version="normalize-2", renderer_version="r1", page_policy="annotate"
    )
    with pytest.raises(FixtureStoreError):
        _capture(tmp_path, stamps=other)


def test_validate_stamps_rejects_a_stale_consumer(tmp_path: Path) -> None:
    _capture(tmp_path)
    assert validate_stamps(tmp_path, "fx1", _STAMPS) == _STAMPS
    stale = ProductStamps(
        normalize_version="normalize-9", renderer_version="r9", page_policy="strip"
    )
    with pytest.raises(FixtureStoreError):
        validate_stamps(tmp_path, "fx1", stale)


def test_discovery_reports_pin_and_stamps(tmp_path: Path) -> None:
    _capture(tmp_path)
    found = discover_fixtures(tmp_path)
    assert len(found) == 1
    assert found[0].plan_pin == _PIN
    assert found[0].stamps == _STAMPS
    assert found[0].case_count == 1


def test_policy_stamp_matches_the_capture_policy() -> None:
    result = normalize_document(
        b"<html><body><p>FORM 10-K</p></body></html>",
        form="10-K",
        document_path="acme.htm",
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    assert result.text
