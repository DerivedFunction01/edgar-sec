"""Unit tests for Form 4 domain models."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.families.ownership.models import (
    FilingPeriod,
    Form4Metadata,
    Issuer,
    ReportingOwner,
)


def test_domain_models_instantiation_and_defaults() -> None:
    owner = ReportingOwner(name="John Doe", is_officer=True)
    assert owner.name == "John Doe"
    assert owner.is_officer is True
    assert owner.is_director is False

    issuer = Issuer(name="Acme Corp", trading_symbol="ACM")
    assert issuer.name == "Acme Corp"
    assert issuer.trading_symbol == "ACM"

    period = FilingPeriod(period_of_report="June 2003")
    assert period.period_of_report == "June 2003"
    assert period.is_amendment is False

    meta = Form4Metadata(issuer=issuer, reporting_owner=owner, period=period)
    assert meta.issuer.name == "Acme Corp"
    assert meta.reporting_owner.name == "John Doe"
    assert meta.signature_name is None


def test_domain_models_immutability() -> None:
    issuer = Issuer(name="Acme Corp")
    with pytest.raises(AttributeError):
        issuer.name = "New Corp"  # type: ignore[misc]
