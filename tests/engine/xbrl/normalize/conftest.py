"""Shared fixtures for the normalize test package."""

from __future__ import annotations

import pytest

from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy


@pytest.fixture(scope="session")
def tax() -> DomainTaxonomy:
    """The production domain taxonomy, loaded once per test session."""
    return load_domain_taxonomy()


@pytest.fixture(scope="session")
def taxonomy(tax: DomainTaxonomy) -> DomainTaxonomy:
    """The session taxonomy under its other call-site name."""
    return tax
