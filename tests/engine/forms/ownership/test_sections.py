"""Tests for Section 16 ownership section classification and partitioning."""

from edgar_sec.engine.forms.ownership.sections import (
    SectionRole,
    partition_ownership_tables,
)

SAMPLE_HTML = """
<html><body>
<table><tr><td>FORM 4 [ ] Check this box if no longer subject to Section 16</td></tr></table>
<table><tr>
  <td>1. Name and Address of Reporting Person* Doe, Jane (Last) (First)</td>
  <td>2. Issuer Name and Ticker Symbol ACME CORP ACM</td>
  <td>4. Statement for June 2001</td>
  <td>6. Relationship Director [X] Officer</td>
</tr></table>
<table><tr><td>Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr><td>1. Title of Security</td><td>2. Transaction Date</td><td>3. Transaction Code</td><td>4. Securities Acquired/Disposed</td></tr>
  <tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>1,000 | A | $10.00</td></tr>
</table>
<table><tr><td>Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr><td>1. Title of Derivative Security</td><td>2. Exercise Price</td><td>3. Trans Date</td></tr>
  <tr><td>Stock Option</td><td>$15.00</td><td>06/01/2001</td></tr>
</table>
<table><tr><td>** Signature of Reporting Person Date\nJane Doe\n06-02-2001</td></tr></table>
<table><tr><td>FOOTNOTE Descriptions (1) Test footnote</td></tr></table>
</body></html>
"""


def test_partition_ownership_tables_locates_all_sections() -> None:
    sections = partition_ownership_tables(SAMPLE_HTML)
    assert sections.boxes_1_to_7 is not None
    assert sections.boxes_1_to_7.role == SectionRole.BOXES_1_TO_7
    assert sections.table_i is not None
    assert sections.table_i.role == SectionRole.TABLE_I
    assert sections.table_ii is not None
    assert sections.table_ii.role == SectionRole.TABLE_II
    assert sections.signatures is not None
    assert sections.signatures.role == SectionRole.SIGNATURES
    assert len(sections.footnotes) == 1


def test_partition_ownership_detects_unlabelled_footnotes_via_narrative_terms() -> None:
    html = """<html><body>
    <table><tr><td>(1) Grant of restricted stock units subject to vesting schedule.</td></tr>
    <tr><td>(2) Shares withheld to satisfy tax withholding obligations pursuant to plan.</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert len(sections.footnotes) == 1
    assert sections.footnotes[0].role == SectionRole.FOOTNOTES


def test_partition_ownership_merges_fragmented_boxes_tables() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person*\nJane Doe</td></tr></table>
    <table><tr><td>4. Statement for Month/Day/Year\n12/02/02</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities Acquired</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.boxes_1_to_7 is not None
    assert len(sections.boxes_1_to_7.resolved_grid.rows) == 2


def test_partition_ownership_filters_statutory_page_artifacts_and_merged_box6() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person*\nJane Doe</td></tr></table>
    <table><tr><td>5. If Amendment, Date of Original (Month/Day/Year)</td></tr></table>
    <table><tr><td>6. Relationship of Reporting Person(s) to Issuer\n[X] Officer Vice President</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities Acquired</td></tr></table>
    <table><tr><td>Note:&nbsp;File three copies of this Form, one of which must be manually signed.</td></tr></table>
    <table><tr><td>SEC 1474 (9-02) (Over)</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.boxes_1_to_7 is not None
    assert len(sections.boxes_1_to_7.resolved_grid.rows) == 3
    assert len(sections.unparsed) == 0


def test_partition_ownership_classifies_repeated_form_header_after_tables() -> None:
    html = """<html><body>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table><tr><td>1. Title of Security</td><td>2. Transaction Date</td></tr>
    <tr><td>Common Stock</td><td>06/01/2001</td></tr></table>
    <table><tr><td>OMB APPROVAL</td><td>OMB Number: 3235-0287</td></tr></table>
    <table><tr><td>o Check this box if no longer subject to Section 16.</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.table_i is not None
    assert sections.unparsed == []


def test_partition_ownership_classifies_sec_masthead_and_short_checkbox() -> None:
    html = """<html><body>
    <table><tr><td>UNITED STATES SECURITIES AND EXCHANGE COMMISSION Washington, DC 20549 FORM 4</td></tr></table>
    <table><tr><td>Check box if no longer subject to Section 16. Form 4 obligations may continue.</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table><tr><td>1. Title of Security</td><td>2. Transaction Date</td></tr>
    <tr><td>Common Stock</td><td>06/01/2001</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.table_i is not None
    assert sections.unparsed == []


def test_partition_ownership_classifies_form3_and_form5_headers() -> None:
    html = """<html><body>
    <table><tr><td>UNITED STATES SECURITIES AND EXCHANGE COMMISSION Washington, D.C. 20549 FORM 3</td></tr></table>
    <table><tr><td>INITIAL STATEMENT OF BENEFICIAL OWNERSHIP OF SECURITIES Filed pursuant to...</td></tr></table>
    <table><tr><td>Form 5 continuation statement Ticker: XYZ</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities Beneficially Owned</td></tr></table>
    <table><tr><td>Common Stock</td><td>100</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.table_i is not None
    assert sections.unparsed == []


def test_partition_ownership_merges_split_signature_and_notary_tables() -> None:
    html = """<html><body>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table><tr><td>1. Title of Security</td><td>2. Transaction Date</td></tr>
    <tr><td>Common Stock</td><td>06/01/2001</td></tr></table>
    <table><tr><td>/s/ Neil W. Klusmann Signature</td></tr></table>
    <table><tr><td>Neil W. Klusmann Print Name</td></tr></table>
    <table><tr><td>STATE OF MONTANA ) COUNTY OF YELLOWSTONE )<br>(SEAL) /s/ Amy Anderson Notary Public</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.signatures is not None
    assert len(sections.signatures.resolved_grid.rows) == 3
    assert sections.unparsed == []


def test_partition_ownership_classifies_institutional_signatures_and_table_i_rows() -> (
    None
):
    html = """<html><body>
    <table><tr><td>* Includes Shares Acquired Under Dividend Reinvestment</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    <table><tr><td>1. Title of Security</td><td>2. Date</td><td>3. Code</td><td>4. Amount</td><td>5. Owned</td><td>6. Form</td><td>7. Nature</td></tr></table>
    <table><tr><td>Common Stock</td><td>12/03/02</td><td>S</td><td>6,200</td><td>64,000</td><td>D</td><td>Direct</td></tr></table>
    <table><tr><td>Willow Creek Capital Management<br>By: Aaron H. Braun President</td></tr></table>
    <table><tr><td>Aaron H. Braun</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert len(sections.footnotes) == 1
    assert sections.table_i is not None
    assert len(sections.table_i.resolved_grid.rows) == 2
    assert sections.signatures is not None
    assert len(sections.signatures.resolved_grid.rows) == 2
    assert sections.unparsed == []


def test_partition_ownership_classifies_holding_only_table_i_and_stacked_boxes() -> (
    None
):
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person Doe, Jane</td></tr></table>
    <table>
      <tr><td>5.</td><td>Amount of Securities Beneficially Owned at End of Month = 152,600.</td></tr>
      <tr><td>6.</td><td>Ownership Form -- (D).</td></tr>
    </table>
    <table><tr><td>Jane Doe, September 30, 2002</td></tr></table>
    <table><tr><td>Director 10% Owner Officer (give title below) Other (specify below)</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    assert sections.boxes_1_to_7 is not None
    assert sections.table_i is not None
    assert sections.unparsed == []
