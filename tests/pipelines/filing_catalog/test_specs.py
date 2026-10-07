"""Tests for filing catalog relation specifications."""

from edgar_sec.pipelines.filing_catalog.specs import (
    CATALOG_RELATION_SPECS,
    COMPANY_PROFILES_SPEC,
    FILING_TARGETS_SPEC,
)


def test_catalog_relation_specs_contract():
    assert len(CATALOG_RELATION_SPECS) == 2
    assert FILING_TARGETS_SPEC.name == "filing_targets"
    assert FILING_TARGETS_SPEC.primary_key == ("occurrence_id",)
    assert FILING_TARGETS_SPEC.merge_strategy == "append"

    assert COMPANY_PROFILES_SPEC.name == "company_profiles"
    assert COMPANY_PROFILES_SPEC.primary_key == ("cik",)
    assert COMPANY_PROFILES_SPEC.merge_strategy == "upsert"
