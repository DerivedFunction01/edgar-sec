"""Unit tests for the filing-catalog domain schemas."""

from __future__ import annotations

import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_BASE_COLUMNS,
    PATH_SOURCE_BUNDLE,
    PATH_SOURCE_PRIMARY,
    PROFILE_COLUMNS,
    PROFILE_SCHEMA,
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA

BORROWED_COLUMNS = PROFILE_COLUMNS[:-1]


def test_profile_schema_has_23_columns() -> None:
    assert len(PROFILE_SCHEMA.names) == 23
    assert len(BORROWED_COLUMNS) == 22


@pytest.mark.parametrize("name", BORROWED_COLUMNS)
def test_every_borrowed_column_resolves_in_phase1_schema(name: str) -> None:
    """A Phase 1 rename must fail here, not drift silently downstream."""
    assert name in SUBMISSION_METADATA_SCHEMA.names


@pytest.mark.parametrize("name", BORROWED_COLUMNS)
def test_borrowed_field_types_are_reused_verbatim(name: str) -> None:
    assert (
        PROFILE_SCHEMA.field(name).type == SUBMISSION_METADATA_SCHEMA.field(name).type
    )


def test_profile_schema_appends_only_the_owned_version_column() -> None:
    assert PROFILE_SCHEMA.names[-1] == "profile_schema_version"
    assert PROFILE_SCHEMA.names[:-1] == list(BORROWED_COLUMNS)


def test_target_schema_has_16_columns() -> None:
    assert len(TARGET_SCHEMA.names) == 16
    assert TARGET_SCHEMA.names == list(TARGET_COLUMNS)


def test_target_schema_types() -> None:
    types = {field.name: field.type for field in TARGET_SCHEMA}
    assert str(types["is_amendment"]) == "bool"
    assert str(types["reported_size"]) == "int64"
    assert str(types["occurrence_id"]) == "string"
    assert str(types["document_locator_key"]) == "string"


def test_company_family_is_not_a_profile_column() -> None:
    """Decision D2: clustering is Stage B, so no v1 README claim is ported."""
    assert "company_family" not in PROFILE_SCHEMA.names
    assert "company_family" not in PROFILE_COLUMNS


def test_version_constants_are_present_and_ordered() -> None:
    assert SCHEMA_VERSION == "1.1.0"
    assert TARGET_SCHEMA_VERSION == "1.1.0"
    assert PROFILE_SCHEMA_VERSION == "1.0.0"


def test_path_source_constants() -> None:
    assert PATH_SOURCE_PRIMARY == "primary_document"
    assert PATH_SOURCE_BUNDLE == "submission_bundle"


def test_locator_base_projection_is_the_eight_column_stage_a_shape() -> None:
    """Stage A locator_groups is narrow; Stage B widens it (phase_2.md 3.4)."""
    assert len(LOCATOR_BASE_COLUMNS) == 8
    assert LOCATOR_BASE_COLUMNS[0] == "document_locator_key"
    assert "form_family" not in LOCATOR_BASE_COLUMNS
    assert "era" not in LOCATOR_BASE_COLUMNS


def test_archive_base_is_the_canonical_one() -> None:
    """The catalog fallback and the engine must use one archive base.

    There is exactly one definition, in ``domain.sec_urls``; the catalog imports
    it rather than restating it, so a change to the SEC prefix cannot leave the
    two layers disagreeing.
    """
    from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE as canonical_base

    assert canonical_base == "https://www.sec.gov/Archives/edgar/data"


def test_catalog_archive_url_shape_matches_the_engine() -> None:
    """The SQL fallback must build the URL the Phase 1 engine would build."""
    from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE, archives_url
    from edgar_sec.engine.submissions.helpers import build_archive_url

    engine_url, reason = build_archive_url(
        "0000320193", "0000320193-23-000106", "aapl-20230930.htm"
    )
    assert reason is None
    expected = f"{SEC_ARCHIVE_BASE}/320193/000032019323000106/aapl-20230930.htm"
    assert engine_url == expected
    assert engine_url == archives_url(
        "0000320193", "0000320193-23-000106", "aapl-20230930.htm"
    )
