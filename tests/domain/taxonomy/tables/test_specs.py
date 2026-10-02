"""Unit tests for table taxonomy specifications and models."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.tables.families import FAMILY_SPECS
from edgar_sec.domain.taxonomy.tables.shapes import ShapeConstraint
from edgar_sec.domain.taxonomy.tables.specs import (
    RepairPolicy,
    TableScope,
    build_ngram_tier,
)


def test_shape_constraint_defaults_and_effective_max_rows() -> None:
    constraint = ShapeConstraint(min_rows=2, max_rows=10, max_rows_scoped=30)
    assert constraint.effective_max_rows(is_authorized_scope=False) == 10
    assert constraint.effective_max_rows(is_authorized_scope=True) == 30

    unscoped = ShapeConstraint(min_rows=2, max_rows=10)
    assert unscoped.effective_max_rows(is_authorized_scope=True) == 10


def test_table_scope_coercion() -> None:
    assert TableScope.from_string("cover") is TableScope.COVER
    assert TableScope.from_string("toc") is TableScope.TOC
    assert TableScope.from_string("body") is TableScope.BODY
    assert TableScope.from_string("UNKNOWN") is TableScope.BODY
    assert TableScope.from_string(None) is TableScope.BODY
    assert TableScope.from_string(TableScope.COVER) is TableScope.COVER

    assert TableScope.COVER.allows_cover_templates is True
    assert TableScope.BODY.allows_cover_templates is False
    assert TableScope.TOC.allows_body_templates is False
    assert TableScope.BODY.allows_body_templates is True


def test_build_ngram_tier_filters_unigrams() -> None:
    tier = build_ngram_tier(
        "test_tier",
        ("single", "multi token phrase", "another phrase"),
        priority=10,
        value=2,
    )
    assert tier is not None
    assert "single" not in tier.terms
    assert "multi token phrase" in tier.terms
    assert "another phrase" in tier.terms

    empty_tier = build_ngram_tier("empty", ("single", "word"), priority=5, value=1)
    assert empty_tier is None


def test_family_specs_registry_integrity() -> None:
    assert len(FAMILY_SPECS) == 22
    for name, spec in FAMILY_SPECS.items():
        assert spec.name == name
        assert spec.shape.min_rows >= 1
        assert spec.shape.min_cols >= 1
        assert spec.evidence_pack is not None
        assert isinstance(spec.repair_policy, RepairPolicy)
