"""Tests for Form 144 domain models."""

from edgar_sec.domain.forms.families.form144.models import (
    BrokerDetails,
    Form144Document,
    IssuerInformation,
    NoticeSignature,
    ProposedSaleItem,
    ReportingPerson,
    TableISecurityItem,
    TableIISecuritySoldItem,
)


def test_form144_document_defaults():
    issuer = IssuerInformation(cik="0001018724", name="AMAZON.COM, INC.")
    person = ReportingPerson(
        name="Jeffrey P. Bezos", relationships=("Director", "Officer")
    )
    proposed = ProposedSaleItem(
        class_title="Common",
        broker=BrokerDetails(name="Morgan Stanley"),
        units_to_be_sold=15000000,
        aggregate_market_value=4073700000.0,
    )
    doc = Form144Document(
        issuer=issuer,
        reporting_person=person,
        proposed_sale=proposed,
        nothing_to_report_past_3_months=True,
    )
    assert doc.issuer.name == "AMAZON.COM, INC."
    assert doc.reporting_person.name == "Jeffrey P. Bezos"
    assert doc.proposed_sale.units_to_be_sold == 15000000
    assert doc.nothing_to_report_past_3_months is True
    assert doc.securities_to_be_sold == ()
    assert doc.securities_sold_past_3_months == ()


def test_table_items_and_signatures():
    table_i_item = TableISecurityItem(
        class_title="Common",
        acquired_date="07/05/1994",
        nature_of_acquisition="Purchase - Original Issue",
        donor_or_seller_name="Issuer",
        amount_acquired=15000000,
    )
    table_ii_item = TableIISecuritySoldItem(
        seller_name="Seller Name",
        class_title="Common",
        sale_date="05/01/2026",
        amount_sold=1000,
        gross_proceeds=25000.0,
    )
    sig = NoticeSignature(
        notice_date="08/03/2026",
        plan_adoption_dates=("11/14/2025",),
        signature="/s/ Jeffrey P. Bezos",
    )
    assert table_i_item.amount_acquired == 15000000
    assert table_ii_item.gross_proceeds == 25000.0
    assert sig.plan_adoption_dates == ("11/14/2025",)
