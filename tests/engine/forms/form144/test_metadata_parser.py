"""Tests for Form 144 signatures and remarks parsing."""

from edgar_sec.engine.forms.form144.metadata_parser import (
    parse_remarks,
    parse_signatures,
)
from edgar_sec.engine.forms.form144.sections import partition_form144_tables


def test_parse_signatures_and_plan_adoption_date():
    html = """
    <table><tr><td>DATE OF NOTICE: May 10, 2022 /s/ Jane Doe
        DATE OF PLAN ADOPTION: 12/01/2021</td></tr></table>
    """
    sections = partition_form144_tables(html)
    signature = parse_signatures(sections.signatures, full_text=html)
    assert signature.signature == "/s/ Jane Doe"
    assert signature.notice_date == "2022-05-10"
    assert signature.plan_adoption_dates == ("2021-12-01",)


def test_signature_block_with_footer_is_not_discarded_as_instructions():
    html = """
    <table><tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr></table>
    <table><tr><td>May 12, 2015 /s/ Michael L Snider DATE OF NOTICE
        The notice shall be signed by the person for whose account the securities are to be sold.</td></tr></table>
    """
    sections = partition_form144_tables(html)
    signature = parse_signatures(sections.signatures, full_text=html)
    assert signature.signature == "/s/ Michael L Snider"


def test_parse_signer_from_full_text_when_signature_table_is_empty():
    html = """
    <table><tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr></table>
    <table><tr><td>05/10/2022 DATE OF NOTICE</td><td>(SIGNATURE)</td></tr></table>
    <p>By: /s/ Moritz Sell</p>
    """
    sections = partition_form144_tables(html)
    assert sections.signatures
    signature = parse_signatures(sections.signatures, full_text=html)
    assert signature.signature == "/s/ Moritz Sell"


def test_parse_signatures_recovers_from_fallback_section():
    from edgar_sec.engine.forms.form144.sections import (
        ClassifiedSection,
        SectionRole,
    )
    from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid

    fallback = ClassifiedSection(
        role=SectionRole.UNPARSED,
        table_index=0,
        raw_node=None,
        resolved_grid=ResolvedGrid(
            rows=(("/s/ Dana Roe", "DATE OF NOTICE", "March 3, 2021"),),
            column_alignments=(),
            column_widths=(),
        ),
    )
    signature = parse_signatures(None, fallback_sections=(fallback,))
    assert signature.signature == "/s/ Dana Roe"
    assert signature.notice_date == "2021-03-03"


def test_parse_remarks():
    html = """
    <table><tr><td>Remarks: Delivery under an equity compensation plan.</td></tr></table>
    """
    sections = partition_form144_tables(html)
    parsed = parse_remarks(sections.remarks)
    assert parsed == "Delivery under an equity compensation plan."
