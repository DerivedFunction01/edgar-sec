"""Tests for resolving non-primary intents against a parsed index page."""

from __future__ import annotations

import pytest

from edgar_sec.domain.document_inventory.models import IndexPageInput
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.enumeration import (
    TargetIntent,
    enumerate_index_targets,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from tests.support import fixture_path

_ACCESSION = AccessionNumber.from_any("0001234567-24-000042")
_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/"
    "000123456724000042/0001234567-24-000042-index.html"
)


def _page():
    outcome = parse_html_index(
        IndexPageInput(
            _ACCESSION,
            _INDEX_URL,
            fixture_path("document_planning_index_page.html").read_bytes(),
        )
    )
    assert outcome.__class__.__name__ == "ParsedIndexPage"
    return outcome


def _intent(role: str, doc_type: str, *, optional: bool = True) -> TargetIntent:
    return TargetIntent(
        role=role,
        type=doc_type,
        optional=optional,
        request_id=f"{role}:{doc_type}",
    )


def test_concrete_exhibit_and_data_file_resolve() -> None:
    resolutions = enumerate_index_targets(
        _page(),
        (_intent("exhibit", "EX-99.1"), _intent("data_file", "EX-101.SCH")),
    )
    by_id = {item.request_id: item for item in resolutions}
    exhibit = by_id["exhibit:EX-99.1"]
    assert exhibit.status == "matched"
    assert exhibit.filename == "ex991.htm"
    assert exhibit.document_type == "EX-99.1"
    assert exhibit.sequence == 2
    assert exhibit.target_url is not None
    assert exhibit.target_url.endswith("/ex991.htm")
    data_file = by_id["data_file:EX-101.SCH"]
    assert data_file.status == "matched"
    assert data_file.filename == "ex101.xsd"


def test_pattern_intent_resolves_with_concrete_document_type() -> None:
    (resolution,) = enumerate_index_targets(_page(), (_intent("exhibit", "EX-*"),))
    assert resolution.status == "matched"
    assert resolution.type == "EX-*"
    assert resolution.document_type == "EX-99.1"


def test_absent_type_is_not_filed_or_required_missing() -> None:
    optional, required = enumerate_index_targets(
        _page(),
        (
            _intent("exhibit", "EX-99.2"),
            _intent("exhibit", "EX-99.3", optional=False),
        ),
    )
    assert optional.status == "not_filed"
    assert optional.status_reason == "no_matching_entry"
    assert required.status == "required_missing"


def test_primary_intent_is_refused() -> None:
    with pytest.raises(ValueError, match="non-primary"):
        enumerate_index_targets(_page(), (_intent("primary", "primary"),))
