"""Tests for Form D domain models."""

from edgar_sec.domain.forms.families.form_d.models import (
    FormDDocument,
    IssuerAddress,
    OfferingSalesAmounts,
    PrimaryIssuer,
    RelatedPerson,
    Signatory,
)


def test_form_d_document_construction() -> None:
    """Validate construction of FormDDocument model."""
    addr = IssuerAddress("123 Main St", None, "New York", "NY", "NEW YORK", "10001")
    issuer = PrimaryIssuer(
        "0001234567", "Acme Inc.", addr, "555-1234", "DE", "Corporation", "2020"
    )
    rp = RelatedPerson("John", None, "Doe", addr, ("Director",), None)
    amounts = OfferingSalesAmounts(1000000.0, 500000.0, 500000.0, False)
    sig = Signatory("Acme Inc.", "/s/ John Doe", "John Doe", "CEO", "2021-01-01")
    doc = FormDDocument(
        "X0101", "D", "LIVE", issuer, (rp,), amounts, (sig,), "Other", ("06b",)
    )
    assert doc.primary_issuer.entity_name == "Acme Inc."
    assert doc.offering_amounts.total_remaining == 500000.0
    assert len(doc.signatures) == 1
