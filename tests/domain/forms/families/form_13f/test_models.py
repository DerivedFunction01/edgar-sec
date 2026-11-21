"""Tests for Form 13F document models."""

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
    ManagerAddress,
)


def test_info_table_row_defaults() -> None:
    """Optional row fields default to None."""
    row = InfoTableRow(
        name_of_issuer="ACME CORP",
        title_of_class="COM",
        cusip="001000000",
        value=1250,
        shares_or_principal=100,
        amount_type="SH",
        investment_discretion="SOLE",
        voting_sole=100,
        voting_shared=0,
        voting_none=0,
    )
    assert row.figi is None
    assert row.put_call is None
    assert row.other_managers is None
    assert row.value == 1250


def test_form13f_document_holdings() -> None:
    """Document carries cover metadata and the holdings tuple."""
    address = ManagerAddress("1 Main St", None, "Boston", "MA", "02110")
    doc = Form13FDocument(
        submission_type="13F-HR",
        manager_name="ACME ADVISORS",
        holdings=(),
        crd_number="123456",
        sec_file_number="801-12345",
        manager_address=address,
        table_entry_total=0,
        table_value_total=0,
    )
    assert doc.crd_number == "123456"
    assert doc.sec_file_number == "801-12345"
    assert doc.manager_address is address
    assert doc.is_amendment is False
