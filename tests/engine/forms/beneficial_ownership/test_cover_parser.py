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
