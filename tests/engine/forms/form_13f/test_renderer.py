"""Tests for the Form 13F canonical XML renderer."""

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
)
from edgar_sec.engine.document_processing.capabilities import has_capability
from edgar_sec.engine.document_processing.registry import DEFAULT_HANDLER_REGISTRY
from edgar_sec.engine.forms.form_13f.renderer import (
    build_form_13f_xml,
    render_form_13f_to_xml,
)
from edgar_sec.engine.forms.form_13f.xml_parser import parse_form_13f_xml

_NATIVE_SUBMISSION = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><submissionType>13F-NT</submissionType></headerData>
</edgarSubmission>
"""

_ROW = InfoTableRow(
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


def test_render_native_submission_passthrough() -> None:
    """Native spec XML passes through byte-identical."""
    output = render_form_13f_to_xml(_NATIVE_SUBMISSION)
    assert output.content == _NATIVE_SUBMISSION


def test_build_information_table_round_trip() -> None:
    """A holdings-only document renders and re-parses to the same rows."""
    doc = Form13FDocument(submission_type="", manager_name="", holdings=(_ROW,))
    output = build_form_13f_xml(doc)
    reparsed = parse_form_13f_xml(output.content)
    assert reparsed.holdings == (_ROW,)


def test_build_submission_with_holdings_round_trip() -> None:
    """Cover plus holdings (text-era shape) renders one canonical document."""
    doc = Form13FDocument(
        submission_type="13F-HR",
        manager_name="ACME ADVISORS",
        holdings=(_ROW,),
        period_of_report="December 31, 2001",
        report_type="13F HOLDINGS REPORT",
        table_entry_total=1,
        table_value_total=1250,
    )
    output = build_form_13f_xml(doc)
    reparsed = parse_form_13f_xml(output.content, normalize_values=False)
    assert reparsed.manager_name == "ACME ADVISORS"
    assert reparsed.table_entry_total == 1
    assert reparsed.holdings == (_ROW,)
    second = build_form_13f_xml(doc)
    assert second.content == output.content


def test_registry_and_capability_registered() -> None:
    """The 13F handler is registered for the family with its capability."""
    assert has_capability("form_13f_to_xml")
    registration = DEFAULT_HANDLER_REGISTRY.get("form_13f_to_xml", "render_to_xml")
    assert registration is not None
    assert registration.family == "13f"
