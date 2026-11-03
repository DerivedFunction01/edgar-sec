"""Tests for Form N-PORT document models."""

from edgar_sec.domain.forms.families.form_nport.models import (
    FormNPortDocument,
    NPortInvestment,
)


def test_nport_investment_defaults() -> None:
    """Optional investment fields default to None."""
    row = NPortInvestment(name="ACME CORP", title="ACME COMMON", cusip="001000000")
    assert row.isin is None
    assert row.value_usd is None
    assert row.payoff_profile is None


def test_nport_document_holdings() -> None:
    """Document carries registrant metadata and the investments tuple."""
    row = NPortInvestment(
        name="ACME CORP",
        title="ACME COMMON",
        cusip="001000000",
        value_usd="1250.50",
        percent_value="0.25",
    )
    doc = FormNPortDocument(
        submission_type="NPORT-P",
        registrant_name="ACME FUND",
        investments=(row,),
        registrant_cik="0000123456",
        net_assets="500000.00",
    )
    assert doc.investments == (row,)
    assert doc.registrant_cik == "0000123456"
    assert doc.net_assets == "500000.00"
