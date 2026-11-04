from __future__ import annotations

from edgar_sec.domain.forms.families.form_25nse.models import (
    ExchangeFiler,
    Form25NseDocument,
    IssuerAddress,
    RemovalIssuer,
    RemovalSignature,
)


def test_document_model_holds_all_sections() -> None:
    doc = Form25NseDocument(
        schema_version="X0203",
        exchange=ExchangeFiler(cik="0000000001", ccc="xxxxxxxx", entity_name=None),
        issuer=RemovalIssuer(
            cik="0000000002",
            entity_name="Acme Corp",
            file_number="001-00001",
            address=IssuerAddress("1 Main St", None, "Anywhere", "VA", "21212"),
            telephone_number=None,
        ),
        description_class_security="Common Stock",
        rule_provision="17 CFR 240.12d2-2(b)",
        signature=RemovalSignature("Jane Officer", "CEO", "2026-01-15"),
    )
    assert doc.issuer.address is not None
    assert doc.issuer.address.city == "Anywhere"
    assert doc.signature.date == "2026-01-15"
