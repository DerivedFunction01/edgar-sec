"""Tests for cover matrix parsing."""

from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.models import EvidenceState
from edgar_sec.engine.forms.beneficial_ownership.cover_parser import (
    extract_reporting_person_covers,
    parse_reporting_person_matrix,
)

_SAMPLE_MATRIX = """
1. NAMES OF REPORTING PERSONS
   S.S. OR I.R.S. IDENTIFICATION NO. OF ABOVE PERSON
   Acme Holdings LLC
2. CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP
   (a) [ ]
   (b) [X]
3. SEC USE ONLY
4. SOURCE OF FUNDS
   WC; OO
5. CHECK BOX IF DISCLOSURE OF LEGAL PROCEEDINGS IS REQUIRED PURSUANT TO ITEMS 2(d) OR 2(e)
   [ ]
6. CITIZENSHIP OR PLACE OF ORGANIZATION
   Delaware, USA
<TABLE>
------------  -------  ------------------------
 NUMBER OF          7  SOLE VOTING POWER
   SHARES              1,500,000
------------  -------  ------------------------
BENEFICIALLY        8  SHARED VOTING POWER
  OWNED BY             0
------------  -------  ------------------------
    EACH            9  SOLE DISPOSITIVE POWER
 REPORTING             1,500,000
------------  -------  ------------------------
PERSON WITH        10  SHARED DISPOSITIVE POWER
                       0
------------  -------  ------------------------
</TABLE>
11. AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON
    1,500,000
12. CHECK BOX IF THE AGGREGATE AMOUNT IN ROW (11) EXCLUDES CERTAIN SHARES
    [ ]
13. PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11)
    7.5%
14. TYPE OF REPORTING PERSON
    OO
    *Footnote explaining director shares.
"""

_SAMPLE_13G_MATRIX = """
1. NAMES OF REPORTING PERSONS
   Beacon Capital LLC
2. CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP
   (a) [ ]
   (b) [ ]
3. SEC USE ONLY
4. CITIZENSHIP OR PLACE OF ORGANIZATION
   New York
5. SOLE VOTING POWER
   850,000
6. SHARED VOTING POWER
   0
7. SOLE DISPOSITIVE POWER
   850,000
8. SHARED DISPOSITIVE POWER
   0
9. AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON
   850,000
10. CHECK BOX IF THE AGGREGATE AMOUNT IN ROW (9) EXCLUDES CERTAIN SHARES
   [ ]
11. PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (9)
   5.2%
12. TYPE OF REPORTING PERSON
   IA
"""


def test_parse_reporting_person_matrix_extracts_all_slots() -> None:
    person = parse_reporting_person_matrix(_SAMPLE_MATRIX, family="13D")
    item1 = person.first_item(1)
    assert item1 is not None and item1.value == "Acme Holdings LLC"
    item2 = person.first_item(2)
    assert item2 is not None and item2.value == "(a) [ ] (b) [X]"
    item4 = person.first_item(4)
    assert item4 is not None and item4.value == "WC; OO"
    item5 = person.first_item(5)
    assert item5 is not None and item5.state is EvidenceState.UNCHECKED
    item6 = person.first_item(6)
    assert item6 is not None and item6.value == "Delaware, USA"
    item7 = person.first_item(7)
    assert item7 is not None and item7.value == "1,500,000"
    item8 = person.first_item(8)
    assert item8 is not None and item8.value == "0"
    item9 = person.first_item(9)
    assert item9 is not None and item9.value == "1,500,000"
    item10 = person.first_item(10)
    assert item10 is not None and item10.value == "0"
    item11 = person.first_item(11)
    assert item11 is not None and item11.value == "1,500,000"
    item12 = person.first_item(12)
    assert item12 is not None and item12.state is EvidenceState.UNCHECKED
    item13 = person.first_item(13)
    assert item13 is not None and item13.value == "7.5%"
    item14 = person.first_item(14)
    assert item14 is not None and item14.value == "OO"
    assert person.comment_content == "*Footnote explaining director shares."


def test_parse_reporting_person_matrix_13g_extracts_twelve_slots() -> None:
    person = parse_reporting_person_matrix(_SAMPLE_13G_MATRIX, family="13G")
    assert person.first_item("reportingPersonName").value == "Beacon Capital LLC"
    assert person.first_item("citizenshipOrOrganization").value == "New York"
    assert person.first_item(4).value == "New York"
    assert person.first_item("soleVotingPower").value == "850,000"
    assert person.first_item(5).value == "850,000"
    assert person.first_item("aggregateAmountOwned").value == "850,000"
    assert person.first_item(9).value == "850,000"
    assert person.first_item("percentOfClass").value == "5.2%"
    assert person.first_item(11).value == "5.2%"
    assert person.first_item("typeOfReportingPerson").value == "IA"
    assert person.first_item(12).value == "IA"


def test_extract_reporting_person_covers_finds_multiple_filers() -> None:
    text = f"{_SAMPLE_MATRIX}\n{_SAMPLE_MATRIX}"
    people = extract_reporting_person_covers(text)
    assert len(people) == 2
    assert people[0].first_item(1).value == "Acme Holdings LLC"
    assert people[1].first_item(1).value == "Acme Holdings LLC"


def test_cover_parser_accepts_check_if_wording_without_box() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person.
Beacon LLC
11. Aggregate Amount Beneficially Owned by Each Reporting Person: 20,924,055
12. Check if the Aggregate Amount in Row (11) Excludes Certain Shares (See Instructions): [ ]
13. Percent of Class Represented by Amount in Row (11): Approximately 100%
14. Type of Reporting Person: OO (Limited Liability Company)""",
        family="13D",
    )

    assert person.first_item("aggregateAmountOwned").value == "20,924,055"
    assert (
        person.first_item("isAggregateExcludeShares").state is EvidenceState.UNCHECKED
    )
    assert person.first_item("percentOfClass").value == "Approximately 100%"
    assert person.first_item("reportingPersonName").value == "Beacon LLC"


def test_cover_parser_keeps_long_names_and_discards_repeated_labels() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons
Thirsty Brook 2010 Irrevocable Trust
Names of Reporting Persons Thirsty Brook 2010 Irrevocable Trust
2. Check the Appropriate Box if a Member of a Group
(a) [ ]
3. SEC Use Only""",
        family="13D",
    )

    assert (
        person.first_item("reportingPersonName").value
        == "Thirsty Brook 2010 Irrevocable Trust"
    )


def test_cover_parser_strips_slash_prefixed_irs_label() -> None:
    person = parse_reporting_person_matrix(
        "1. Name of Reporting Person / I.R.S. Identification Nos. of Above Persons "
        "(entities only): Beacon LLC 2. Check the Appropriate Box if a Member of a Group: [ ]"
    )

    assert person.first_item("reportingPersonName").value == "Beacon LLC"


def test_cover_parser_removes_irs_label_after_name() -> None:
    person = parse_reporting_person_matrix(
        "1. Name of Reporting Person Sagard Capital Partners, L.P. "
        "I.R.S. Identification No. of Above Person (Entities Only): 20-3332164 "
        "2. Check the Appropriate Box if a Member of a Group: [ ]"
    )

    assert person.first_item("reportingPersonName").value == (
        "Sagard Capital Partners, L.P."
    )


def test_cover_parser_keeps_name_after_leading_irs_label() -> None:
    person = parse_reporting_person_matrix(
        "1. Name of Reporting Person OR I.R.S. Identification No. of Above Person: "
        "Tencent Holdings Limited 2. Check the Appropriate Box if a Member of a Group: [ ]"
    )

    assert person.first_item("reportingPersonName").value == "Tencent Holdings Limited"


def test_cover_parser_removes_underlines_and_narrative_tail() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital Partners LLC
11. Aggregate Amount Beneficially Owned by Each Reporting Person
20,000
____________________
Item 3. Source and Amount of Funds or Other Consideration
This Schedule 13D has been filed for the purpose of ...""",
        family="13D",
    )

    assert person.first_item("aggregateAmountOwned").value == "20,000"


def test_cover_parser_stops_at_wrapped_power_labels_with_interleaved_values() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
6. Citizenship or Place of Organization
Kentucky
Number of Shares 7. Sole Voting 2
Beneficially Owned Power 9
by Each Reporting 0
Person With 8. Shared 0
Voting
Power
9. Sole 2
Dispositive 9
Power 0
10. Shared 0
Dispositive
Power
11. Aggregate Amount Beneficially Owned
2,900
""",
        family="13D",
    )

    assert person.first_item("citizenshipOrOrganization").value == "Kentucky"
    assert person.first_item("soleVotingPower").value == "2 9 0"
    assert person.first_item("sharedVotingPower").value == "0"
    assert person.first_item("soleDispositivePower").value == "2 9 0"
    assert person.first_item("sharedDispositivePower").value == "0"


def test_cover_parser_cleans_irs_prefix_and_preserves_multiple_type_codes() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of reporting persons
I.R.S. identification nos. of above persons (entities only)
Gabelli Funds, LLC I.D. No. 13-4044523
2. Check the appropriate box if a member of a group
(a) [ ]
6. Citizenship or place of organization
New York
7. Sole voting power
459,600 (Item 5)
8. Shared voting power
None Person : With
9. Sole dispositive power
459,600 (Item 5)
:10 Shared dispositive power
None
11. Aggregate amount beneficially owned by each reporting person
459,600 (Item 5)
12. Check if the aggregate amount in row (11) excludes certain shares
[ ]
13. Percent of class represented by amount in row (11)
2.64%
14. Type of reporting person (SEE INSTRUCTIONS)
IA, CO
====""",
        family="13D",
    )

    assert person.first_item("reportingPersonName").value == "Gabelli Funds, LLC"
    assert person.first_item("sharedVotingPower").value == "None"
    assert person.first_item("soleDispositivePower").value == "459,600 (Item 5)"
    assert person.first_item("sharedDispositivePower").value == "None"
    assert person.first_item("typeOfReportingPerson").value == "IA, CO"
    assert person.comment_content is None


def test_cover_parser_normalizes_bare_checkbox_marks_and_repeated_row_numbers() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
2. Check the appropriate box if a member of a group
(a) X (b) [ ]
5. Check box if disclosure of legal proceedings is required
X
7. Sole Voting Power
7 900,000
8. Shared Voting Power
0
9. Sole Dispositive Power
9 PERSON 900,000 WITH
10. Shared Dispositive Power
0
11. Aggregate Amount Beneficially Owned
900,000
12. Check if the aggregate amount in row (11) excludes certain shares
X
13. Percent of class
5%
14. Type of reporting person
IN""",
        family="13D",
    )

    assert person.first_item("memberOfGroup").value == "(a) [X] (b) [ ]"
    assert person.first_item("legalProceedings").state is EvidenceState.CHECKED
    assert person.first_item("soleVotingPower").value == "900,000"
    assert person.first_item("sharedVotingPower").value == "0"
    assert person.first_item("soleDispositivePower").value == "900,000"
    assert person.first_item("isAggregateExcludeShares").state is EvidenceState.CHECKED
    assert person.first_item("aggregateAmountOwned").value == "900,000"


def test_cover_parser_reads_the_shared_checkbox_vocabulary() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
2. Check the appropriate box if a member of a group
(a) ☒ (b) ☐
5. Check box if disclosure of legal proceedings is required
✓
12. Check if the aggregate amount in row (11) excludes certain shares
___X___
13. Percent of class
5%
14. Type of reporting person
IN""",
        family="13D",
    )

    assert person.first_item("memberOfGroup").value == "(a) [X] (b) [ ]"
    assert person.first_item("legalProceedings").state is EvidenceState.CHECKED
    assert person.first_item("isAggregateExcludeShares").state is EvidenceState.CHECKED


def test_cover_parser_leaves_an_unfilled_slot_blank() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
2. Check the appropriate box if a member of a group
(a) ______ (b) ______
5. Check box if disclosure of legal proceedings is required
_______
12. Check if the aggregate amount in row (11) excludes certain shares
_______
13. Percent of class
5%
14. Type of reporting person
IN""",
        family="13D",
    )

    assert person.first_item("memberOfGroup").value == "(a) (b)"
    assert person.first_item("legalProceedings").state is EvidenceState.BLANK
    assert person.first_item("isAggregateExcludeShares").state is EvidenceState.BLANK


def test_cover_parser_removes_cross_column_power_text_from_citizenship() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
6. Citizenship or place of organization
USA Shares Voting Power Beneficially 943,762 Owned by Each 8. Shared Reporting Voting Power Person With 120,090
7. Sole Voting Power
7 943,762
8. Shared Voting Power
None : With :
9. Sole Dispositive Power
9 943,762
10. Shared Dispositive Power
0
11. Aggregate Amount Beneficially Owned
BY EACH PERSON 943,762
13. Percent of class
7.5%
14. Type of reporting person
CO""",
        family="13D",
    )

    assert person.first_item("citizenshipOrOrganization").value == "USA"
    assert person.first_item("sharedVotingPower").value == "None"
    assert person.first_item("soleDispositivePower").value == "943,762"
    assert person.first_item("aggregateAmountOwned").value == "943,762"


def test_cover_parser_removes_type_row_number_and_instruction_footer() -> None:
    person = parse_reporting_person_matrix(
        """1. Name of Reporting Person
Beacon Capital LLC
14. Type of reporting person
* 14 OO *SEE INSTRUCTIONS BEFORE FILLING OUT 13D""",
        family="13D",
    )

    assert person.first_item("typeOfReportingPerson").value == "OO"
    assert person.comment_content is None


def test_cover_parser_handles_wasatch_item_header_format() -> None:
    person = parse_reporting_person_matrix(
        """Item 1: Reporting Person: Wasatch Advisors, Inc. 87-0319391
Item 2: Check Box If Member of Group: Not Applicable
Item 3: SEC Use
Item 4: Place of Organization: Utah
Item 5: Sole Voting Power: 909,435
Item 6: Shared Voting Power: 0
Item 7: Sole Dispositive Power: 909,435
Item 8: Shared Dispositive Power: 0
Item 9: Aggregate Amount Owned: 909,435
Item 10: Check Box If Aggregate Amount Excludes Certain Shares: N/A
Item 11: Percent of Class Owned: 6.2%
Item 12: Type of Reporting Person: IA""",
        family="13G",
    )

    assert (
        person.first_item("reportingPersonName").value
        == "Wasatch Advisors, Inc. 87-0319391"
    )
    assert person.first_item("citizenshipOrOrganization").value == "Utah"
    assert person.first_item("soleVotingPower").value == "909,435"
    assert person.first_item("sharedVotingPower").value == "0"
    assert person.first_item("soleDispositivePower").value == "909,435"
    assert person.first_item("sharedDispositivePower").value == "0"
    assert person.first_item("aggregateAmountOwned").value == "909,435"
    assert person.first_item("percentOfClass").value == "6.2%"
    assert person.first_item("typeOfReportingPerson").value == "IA"


def test_cover_parser_handles_fmr_bare_item_format() -> None:
    person = parse_reporting_person_matrix(
        """Item 1:    Reporting Person - FMR Corp.
Item 4:    Commonwealth of Massachusetts
Item 5:    1,129,889
Item 6:    0
Item 7:    11,924,554
Item 8:    0
Item 9:    11,924,554
Item 11:   8.118%
Item 12:       HC""",
        family="13G",
    )

    assert person.first_item("reportingPersonName").value == "FMR Corp."
    assert (
        person.first_item("citizenshipOrOrganization").value
        == "Commonwealth of Massachusetts"
    )
    assert person.first_item("soleVotingPower").value == "1,129,889"
    assert person.first_item("sharedVotingPower").value == "0"
    assert person.first_item("soleDispositivePower").value == "11,924,554"
    assert person.first_item("sharedDispositivePower").value == "0"
    assert person.first_item("aggregateAmountOwned").value == "11,924,554"
    assert person.first_item("percentOfClass").value == "8.118%"
    assert person.first_item("typeOfReportingPerson").value == "HC"


def test_cover_parser_handles_type_of_person_reporting() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons: James R. Moffett
6. Citizenship: United States
11. Aggregate Amount Beneficially Owned: 2,672,712
13. Percent of Class: 9.9%
14. Type of Person Reporting: IN""",
        family="13D",
    )
    assert person.first_item("percentOfClass").value == "9.9%"
    assert person.first_item("typeOfReportingPerson").value == "IN"


def test_cover_parser_handles_person_prefix_on_next_line() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons: Jennison Associates LLC
9. Aggregate Amount Beneficially Owned by Each Reporting
Person: 9,135,000 shares
11. Percent of Class: 16.47%
12. Type of Reporting Person: IA""",
        family="13G",
    )
    assert person.first_item("aggregateAmountOwned").value == "9,135,000 shares"
    assert person.first_item("percentOfClass").value == "16.47%"


def test_cover_parser_handles_line_citation_in_percent_of_class() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons: Test Filer LLC
9. Aggregate Amount: 500,000
11. Percent of Class Represented by Line 9: 6.5%
12. Type of Reporting Person: IA""",
        family="13G",
    )
    assert person.first_item("percentOfClass").value == "6.5%"


def test_cover_parser_handles_aggregated_amount_and_group_variant() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons: State Street Corporation
2. Check the Appropriate Box if the Member of a Group: (a) [ ] (b) [X]
9. Aggregated Amount Beneficially Owned: 2,859,610
11. Percent of Class: 7.5%
12. Type of Reporting Person: HC""",
        family="13G",
    )
    assert person.first_item("reportingPersonName").value == "State Street Corporation"
    assert person.first_item("memberOfGroup").value == "(a) [ ] (b) [X]"
    assert person.first_item("aggregateAmountOwned").value == "2,859,610"
    assert person.first_item("percentOfClass").value == "7.5%"


def test_cover_parser_handles_barclays_aggregate_vanguard_line_and_html_tags() -> None:
    person = parse_reporting_person_matrix(
        """1. Names of Reporting Persons: The Vanguard Group - 23-1945930
2. CHECK THE APPROPRIATE [LINE] IF A MEMBER OF A GROUP: A. B. [X]
(9) Aggregate: 1,234,567
11) Percent of Class: <P><B>Approx. 11.6%</B></P>
12. Type of Reporting Person: IA""",
        family="13G",
    )
    assert (
        person.first_item("reportingPersonName").value
        == "The Vanguard Group - 23-1945930"
    )
    assert person.first_item("aggregateAmountOwned").value == "1,234,567"
    assert person.first_item("percentOfClass").value == "11.6%"


def test_cover_parser_strips_group_checkbox_bleed_and_interleaved_irs_labels() -> None:
    """Verify Box 2 checkboxes and interleaved IRS headers are stripped from names."""
    matrix1 = """1. Names of Reporting Persons:
Glazer Capital, LLC 2 CHECK THE APPROPRIATE BOX IF A MEMBER OF A (a) [ ] GROUP (b) [ ]
4. Citizenship: Delaware
9. Aggregate Amount: 2,181,000
11. Percent of Class: 9.93%
12. Type: IA"""
    p1 = parse_reporting_person_matrix(matrix1, family="13G")
    assert p1.first_item("reportingPersonName").value == "Glazer Capital, LLC"

    matrix2 = """1. Names of Reporting Persons:
Welsh, Carson, Ander-
I.R.S. Identification son & Stowe IX, L.P.
No. of Above Person (Entities Only)
2) Check the Appropriate Box (a) [ ] if a Member of a Group (b) [X]
4. Citizenship: Delaware
9. Aggregate Amount: 500,000
11. Percent of Class: 5.0%"""
    p2 = parse_reporting_person_matrix(matrix2, family="13G")
    assert (
        p2.first_item("reportingPersonName").value
        == "Welsh, Carson, Anderson & Stowe IX, L.P."
    )
    assert p2.first_item("memberOfGroup").value == "b"

    matrix3 = """1. NAMES OF REPORTING PERSONS
    I.R.S. IDENTIFICATION NOS. (ENTITIES ONLY)
BBR Partners, LLC
2. CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP
(a) [ ]
(b) [X]
4. CITIZENSHIP: Delaware
9. AGGREGATE AMOUNT: 1,658,466
11. PERCENT OF CLASS: 5.53%
12. TYPE: IA"""
    p3 = parse_reporting_person_matrix(matrix3, family="13G")
    assert p3.first_item("reportingPersonName").value == "BBR Partners, LLC"
    assert p3.first_item("memberOfGroup").value == "(a) [ ] (b) [X]"

    matrix4 = """1) NAME AND I.R.S. IDENTIFICATION NO. OF REPORTING PERSON
Prudential Financial, Inc. 22-3703799
2.) MEMBER OF A GROUP: (a) N/A (b) N/A
4) PLACE OF ORGANIZATION: New Jersey
9) AGGREGATE AMOUNT: 1,000,000
11) PERCENT OF CLASS: 5.1%
12) TYPE OF REPORTING PERSON: HC"""
    p4 = parse_reporting_person_matrix(matrix4, family="13G")
    assert (
        p4.first_item("reportingPersonName").value
        == "Prudential Financial, Inc. 22-3703799"
    )

    matrix5 = """1       I.R.S. IDENTIFICATION NO. OF ABOVE PERSONS (ENTITIES ONLY)
Farallon Capital Partners, L.P.
2  CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP (a) [ ] (b) [ ]
4  CITIZENSHIP OR PLACE OF ORGANIZATION: California
9  AGGREGATE AMOUNT: 2,000,000
11 PERCENT OF CLASS: 6.0%
12 TYPE OF REPORTING PERSON: PN"""
    p5 = parse_reporting_person_matrix(matrix5, family="13G")
    assert (
        p5.first_item("reportingPersonName").value == "Farallon Capital Partners, L.P."
    )
