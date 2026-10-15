"""Tests for Form 4 section classification and partitioning."""

from edgar_sec.engine.forms.ownership.sections import (
    SectionRole,
    partition_form4_tables,
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


def test_partition_form4_tables_locates_all_sections() -> None:
    sections = partition_form4_tables(SAMPLE_HTML)
    assert sections.boxes_1_to_7 is not None
    assert sections.boxes_1_to_7.role == SectionRole.BOXES_1_TO_7
    assert sections.table_i is not None
    assert sections.table_i.role == SectionRole.TABLE_I
    assert sections.table_ii is not None
    assert sections.table_ii.role == SectionRole.TABLE_II
    assert sections.signatures is not None
    assert sections.signatures.role == SectionRole.SIGNATURES
    assert len(sections.footnotes) == 1


def test_partition_form4_detects_unlabelled_footnotes_via_narrative_terms() -> None:
    html = """<html><body>
    <table><tr><td>(1) Grant of restricted stock units subject to vesting schedule.</td></tr>
    <tr><td>(2) Shares withheld to satisfy tax withholding obligations pursuant to plan.</td></tr></table>
    </body></html>"""
    sections = partition_form4_tables(html)
    assert len(sections.footnotes) == 1
    assert sections.footnotes[0].role == SectionRole.FOOTNOTES


def test_partition_form4_merges_fragmented_boxes_tables() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person*\nJane Doe</td></tr></table>
    <table><tr><td>4. Statement for Month/Day/Year\n12/02/02</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities Acquired</td></tr></table>
    </body></html>"""
    sections = partition_form4_tables(html)
    assert sections.boxes_1_to_7 is not None
    assert len(sections.boxes_1_to_7.resolved_grid.rows) == 2


def test_partition_form4_filters_statutory_page_artifacts_and_merged_box6() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person*\nJane Doe</td></tr></table>
    <table><tr><td>5. If Amendment, Date of Original (Month/Day/Year)</td></tr></table>
    <table><tr><td>6. Relationship of Reporting Person(s) to Issuer\n[X] Officer Vice President</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities Acquired</td></tr></table>
    <table><tr><td>Note:&nbsp;File three copies of this Form, one of which must be manually signed.</td></tr></table>
    <table><tr><td>SEC 1474 (9-02) (Over)</td></tr></table>
    </body></html>"""
    sections = partition_form4_tables(html)
    assert sections.boxes_1_to_7 is not None
    assert len(sections.boxes_1_to_7.resolved_grid.rows) == 3
    assert len(sections.unparsed) == 0
