"""Tests for the frame-to-atom coordinate resolver."""

from __future__ import annotations

import pytest

from edgar_sec.engine.xbrl.frame_coordinates import resolve_frame_coordinate
from edgar_sec.engine.xbrl.solve.concept_table import build_concept_table
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


def test_instant_frame_lands_on_the_concept_table_coordinate(
    taxonomy: DomainTaxonomy,
) -> None:
    resolved = resolve_frame_coordinate("us-gaap", "Assets", domain_taxonomy=taxonomy)
    assert resolved is not None
    assert resolved.qname == "us-gaap:Assets"
    assert resolved.declaration.period_type == "instant"
    table = build_concept_table(
        taxonomy, (resolved.qname,), declarations=(resolved.declaration,)
    )
    assert resolved.atom == table.record(resolved.qname).atom
    assert resolved.atom.head == "H_ASSET"


def test_duration_frame_lands_on_its_coordinate(taxonomy: DomainTaxonomy) -> None:
    resolved = resolve_frame_coordinate("us-gaap", "Revenues", domain_taxonomy=taxonomy)
    assert resolved is not None
    assert resolved.declaration.period_type == "duration"
    assert resolved.qname == "us-gaap:Revenues"


def test_unarchived_taxonomy_resolves_to_absence() -> None:
    assert resolve_frame_coordinate("no-such-taxonomy", "Assets") is None


def test_undeclared_tag_resolves_to_absence(taxonomy: DomainTaxonomy) -> None:
    assert (
        resolve_frame_coordinate(
            "us-gaap", "NoSuchFrameTagXYZ", domain_taxonomy=taxonomy
        )
        is None
    )
