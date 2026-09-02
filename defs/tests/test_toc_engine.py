"""Contract tests for the upgraded ItemDefinition taxonomies, TOC engine, and 4-zone Document Topology."""

from __future__ import annotations

from defs.sec_forms.cover.boundary import (
    CoverBoundaryPolicy,
    resolve_document_topology,
)
from defs.sec_forms.cover.models import BoundarySignal
from defs.sec_forms.cover.toc import find_toc_span, normalize_for_matching
from defs.sec_forms.forms.annual.taxonomy import (
    FORM_10K_DERIVED,
    FORM_10K_ITEMS,
    FORM_20F_DERIVED,
    FORM_20F_ITEMS,
)
from defs.sec_forms.forms.quarterly.taxonomy import FORM_10Q_DERIVED, FORM_10Q_ITEMS


def test_item_definition_taxonomies_have_early_flags():
    """Verify that form taxonomies correctly tag early items vs late items."""
    # 10-K: Item 1, 1A, 1B, 1C, 2, 3, 4 are early
    early_10k = [d.item for d in FORM_10K_ITEMS if d.early]
    assert "ITEM 1" in early_10k
    assert "ITEM 1A" in early_10k
    assert "ITEM 2" in early_10k
    assert "ITEM 8" not in early_10k
    assert "ITEM 15" not in early_10k

    # 20-F: Items 1-5 are early
    early_20f = [d.item for d in FORM_20F_ITEMS if d.early]
    assert "ITEM 1" in early_20f
    assert "ITEM 4" in early_20f
    assert "ITEM 5" in early_20f
    assert "ITEM 8" not in early_20f

    # 10-Q: Items 1-4 of Part I are early
    early_10q = [d.item for d in FORM_10Q_ITEMS if d.early]
    assert "ITEM 1" in early_10q
    assert "ITEM 2" in early_10q


def test_edge_case_1_incorporated_reference_in_cover_not_toc():
    """Edge Case 1: Proxy reference mentioning Part III (Items 10-14) on cover is not a TOC."""
    doc = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)
COMMISSION FILE NUMBER 001-12345
ACME CORPORATION
EXACT NAME OF REGISTRANT AS SPECIFIED IN ITS CHARTER
State or other jurisdiction: Delaware
IRS Employer Identification No.: 12-3456789
Address of principal executive offices: 100 Main St, New York, NY 10001
Registrant's telephone number: 212-555-0100
Securities registered pursuant to Section 12(b):
Title of each class: Common Stock
Trading Symbol: ACM
Name of each exchange on which registered: NYSE
Indicate by check mark if the registrant is a well-known seasoned issuer: [X] Yes [ ] No
Large accelerated filer [X] Accelerated filer [ ] Non-accelerated filer [ ]
Aggregate market value of voting and non-voting common equity: $500,000,000
Number of shares of common stock outstanding: 50,000,000

DOCUMENTS INCORPORATED BY REFERENCE
Portions of the definitive Proxy Statement for the 2025 Annual Meeting of Stockholders
are incorporated by reference into Part III (Items 10, 11, 12, 13, and 14) of this Form 10-K.

PART I

ITEM 1. BUSINESS
The Company was founded in 1990 and manufactures precision aerospace components.
We operate across three primary commercial segments.
"""
    # Verify find_toc_span returns None on the cover section
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is None

    # Verify resolve_document_topology sets clean 4-zone boundaries
    topo = resolve_document_topology(
        doc,
        policy=CoverBoundaryPolicy(signals=(BoundarySignal.COVER_IDENTITY_AND_LAYOUT,)),
        cover_evidence=("FORM 10-K", "ANNUAL REPORT"),
        body_evidence=("ITEM 1", "BUSINESS"),
        derived_taxonomy=FORM_10K_DERIVED,
    )
    assert topo.toc_start is None
    assert topo.toc_end is None
    assert topo.cover_start == 0
    assert topo.cover_end is not None
    assert topo.body_start is not None
    assert topo.body_start >= topo.cover_end


def test_edge_case_2_merged_multi_item_headings():
    """Edge Case 2: Merged multi-item headings (e.g. ITEMS 1 AND 2. BUSINESS AND PROPERTIES)."""
    line = "ITEMS 1 AND 2. BUSINESS AND PROPERTIES"
    from defs.sec_forms.cover.toc import RE_TOC_ITEM

    assert RE_TOC_ITEM.match(line)
    line2 = "ITEMS 1, 1A, AND 1B. BUSINESS, RISK FACTORS, AND UNRESOLVED STAFF COMMENTS"
    # Matches normalized item search
    assert RE_TOC_ITEM.match(line2)
    assert "items 1" in normalize_for_matching(line2)
    assert "1a" in normalize_for_matching(line2)


def test_edge_case_3_zero_prose_stubs():
    """Edge Case 3: 'Not Applicable' / 'None' stubs transition cleanly without requiring long prose."""
    doc = """PART I

ITEM 1. BUSINESS
The company manufactures widgets.

ITEM 1A. RISK FACTORS
Not applicable.

ITEM 1B. UNRESOLVED STAFF COMMENTS
None.

ITEM 2. PROPERTIES
Our principal executive offices are located in Chicago.
"""
    # TOC engine should not flag this as TOC
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is None


def test_edge_case_4_toc_keyword_density_without_header_or_dots():
    """Edge Case 4: High keyword density (hits >= 3) detects TOC even without dot leaders or header."""
    doc = """ACME CORP
FORM 10-K 2024

Item 1 Business Item 1A Risk Factors Item 2 Properties Item 8 Financial Statements Item 15 Exhibits

PART I

ITEM 1. BUSINESS
The Company is a leading manufacturer of robotics hardware.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.method == "density_score"
    assert toc.start_line == 3


def test_edge_case_5_temporal_anachronism_late_item_in_opening():
    """Edge Case 5: Late item (Item 8 Financial Statements) on line 15 triggers TOC detection."""
    doc = """ACME CORP 2024
ANNUAL REPORT

Item 8. Financial Statements and Supplementary Data
Item 15. Exhibits and Financial Statement Schedules

PART I

ITEM 1. BUSINESS
The Company operates in two segments.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 3


def test_edge_case_6_multi_page_toc_continuity():
    """Edge Case 6: Multi-page Table of Contents with continuation header is consumed completely."""
    doc = """TABLE OF CONTENTS
PART I
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 15
Item 2. Properties ...................................... 30

TABLE OF CONTENTS (Continued)
PART II
Item 5. Market for Common Equity ........................ 35
Item 7. Management's Discussion ......................... 40
Item 8. Financial Statements ............................ 60

PART I

ITEM 1. BUSINESS
The Company was incorporated in 2005.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    # The TOC should consume past the continued section
    lines = doc.splitlines()
    assert (
        "ITEM 1. BUSINESS" in lines[toc.end_line + 1] or "PART I" in lines[toc.end_line]
    )


def test_edge_case_7_form_20f_decimal_letter_subsections():
    """Edge Case 7: Form 20-F decimal and letter subsections are recognized."""
    doc = """FORM 20-F ANNUAL REPORT

TABLE OF CONTENTS
Item 1. Identity of Directors ........................... 1
Item 3. Key Information ................................. 5
Item 4. Information on the Company ...................... 12
Item 5. Operating and Financial Review .................. 25
Item 8. Financial Information ........................... 45

PART I

ITEM 4. INFORMATION ON THE COMPANY
A. History and Development of the Company
The Company is an international telecommunications provider.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_20F_DERIVED)
    assert toc is not None
    assert toc.start_line == 2


def test_edge_case_8_form_10q_topology():
    """Edge Case 8: Form 10-Q 4-zone topology resolution."""
    doc = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-Q
QUARTERLY REPORT PURSUANT TO SECTION 13 OR 15(d)
COMMISSION FILE NUMBER 001-99999
BETA CORP
(Exact name of registrant as specified in its charter)

PART I - FINANCIAL INFORMATION

ITEM 1. FINANCIAL STATEMENTS
Condensed Consolidated Balance Sheets as of June 30, 2024.
"""
    topo = resolve_document_topology(
        doc,
        policy=CoverBoundaryPolicy(signals=(BoundarySignal.COVER_IDENTITY_AND_LAYOUT,)),
        cover_evidence=("FORM 10-Q", "QUARTERLY REPORT"),
        body_evidence=("ITEM 1", "FINANCIAL STATEMENTS"),
        derived_taxonomy=FORM_10Q_DERIVED,
    )
    assert topo.cover_start == 0
    assert topo.toc_start is None
    assert topo.body_start is not None
    assert topo.body_start >= topo.cover_end


def test_adversarial_toc_in_untagged_ascii_box_table():
    """Adversarial: TOC enclosed in untagged ASCII box lines (+---+)."""
    doc = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K

+-------------------------------------------------------------+
|                     TABLE OF CONTENTS                       |
+-------------------------------------------------------------+
| Part I                                                      |
|   Item 1. Business ...................................... 1 |
|   Item 1A. Risk Factors ................................. 8 |
|   Item 2. Properties .................................... 15|
| Part II                                                     |
|   Item 7. MD&A .......................................... 20|
|   Item 8. Financial Statements .......................... 35|
+-------------------------------------------------------------+

PART I

ITEM 1. BUSINESS
The Company is an AI research lab building autonomous systems.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line <= 4
    assert toc.end_line <= 17


def test_adversarial_cover_with_heavy_item_checkboxes_not_toc():
    """Adversarial: Cover page listing numerous items and checkboxes is not a TOC."""
    doc = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)
COMMISSION FILE NUMBER 001-54321
GAMMA ENTERPRISES INC
Delaware | IRS 99-8877665
Indicate by check mark which items are included in this report:
[X] Item 1.01 Entry into Material Agreement
[X] Item 2.01 Acquisition
[X] Item 5.02 Departure of Directors
[ ] Part I Items 1, 1A, 2, 3
[ ] Part II Items 5, 7, 8
Securities registered pursuant to Section 12(b):
Common Stock $0.001 par value

PART I

ITEM 1. BUSINESS
Gamma Enterprises develops renewable energy storage platforms.
"""
    # TOC span search should return None because these are checkboxes, not TOC rows
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is None

    topo = resolve_document_topology(
        doc,
        policy=CoverBoundaryPolicy(signals=(BoundarySignal.COVER_IDENTITY_AND_LAYOUT,)),
        cover_evidence=("FORM 10-K", "ANNUAL REPORT"),
        body_evidence=("ITEM 1", "BUSINESS"),
        derived_taxonomy=FORM_10K_DERIVED,
    )
    assert topo.toc_start is None
    assert topo.body_start is not None


def test_adversarial_merged_roman_numeral_and_item_headings():
    """Adversarial: Combined 'ITEMS 1, 2, 3, AND 4 OF PART I'."""
    line = "ITEMS 1, 2, 3 AND 4 OF PART I. BUSINESS, PROPERTIES, LEGAL PROCEEDINGS"
    from defs.sec_forms.cover.toc import RE_TOC_ITEM

    assert RE_TOC_ITEM.match(line)


def test_adversarial_toc_with_trailing_part1_footnote():
    """Adversarial: A footnote at the bottom of the TOC mentioning Part I/Item 1."""
    doc = """TABLE OF CONTENTS
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 5
Item 8. Financial Statements ............................ 20
* Information required by Part I, Item 1 is incorporated in part from our Proxy Statement.

PART I

ITEM 1. BUSINESS
The Company was founded in 2012.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    lines = doc.splitlines()
    assert (
        "PART I" in lines[toc.end_line] or "ITEM 1. BUSINESS" in lines[toc.end_line + 1]
    )


def test_adversarial_zero_prose_incorporation_shell():
    """Adversarial: Filing where every item is an incorporation one-liner."""
    doc = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K
ACME CORP

PART I

ITEM 1. BUSINESS
The information required by this item is incorporated by reference to Exhibit 13.

ITEM 1A. RISK FACTORS
Incorporated by reference to Exhibit 13.

ITEM 2. PROPERTIES
Incorporated by reference to Exhibit 13.
"""
    topo = resolve_document_topology(
        doc,
        policy=CoverBoundaryPolicy(signals=(BoundarySignal.COVER_IDENTITY_AND_LAYOUT,)),
        cover_evidence=("FORM 10-K",),
        body_evidence=("ITEM 1", "BUSINESS"),
        derived_taxonomy=FORM_10K_DERIVED,
    )
    assert topo.body_start is not None
    assert topo.body_start >= 4


def test_adversarial_roman_numeral_toc_page_numbers():
    """Adversarial: TOC using lowercase roman numerals for page numbers (i, ii, iii, iv)."""
    doc = """TABLE OF CONTENTS
Item 1. Business ........................................ i
Item 1A. Risk Factors ................................... iii
Item 2. Properties ...................................... iv
Item 8. Financial Statements ............................ xii

PART I

ITEM 1. BUSINESS
The Company operates a global logistics network.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    assert toc.end_line >= 4


def test_adversarial_filing_starting_directly_at_item1_body():
    """Adversarial: Filing with no cover page, beginning directly at Item 1."""
    doc = """PART I

ITEM 1. BUSINESS
The Company provides cloud computing infrastructure and operates
manufacturing facilities throughout North America and Europe.
"""

    # Use body_evidence_pack with body terms for BoW scoring
    class SimpleEvidence:
        body_terms = (
            "company",
            "provides",
            "business",
            "operations",
            "operates",
            "manufactures",
            "facilities",
        )
        body_verbs = ("provides", "operates", "manufactures")
        body_ngrams = ("cloud computing",)
        cover_terms = ()

    topo = resolve_document_topology(
        doc,
        policy=CoverBoundaryPolicy(signals=(BoundarySignal.COVER_IDENTITY_AND_LAYOUT,)),
        cover_evidence=(),
        body_evidence_pack=SimpleEvidence(),
        derived_taxonomy=FORM_10K_DERIVED,
    )
    assert topo.toc_start is None
    assert topo.body_start is not None


def test_adversarial_split_toc_sgml_page_marker():
    """Adversarial: Multi-page TOC split by an SGML <PAGE> marker between pages."""
    doc = """\
TABLE OF CONTENTS
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 8
Item 2. Properties ...................................... 15
<PAGE>
Item 5. Market for Common Equity ........................ 35
Item 7. Management's Discussion ......................... 40
Item 8. Financial Statements ............................ 60

PART I

ITEM 1. BUSINESS
The Company manufactures precision optics.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    # Must bridge across the <PAGE> and consume the second half of the TOC
    lines = doc.splitlines()
    assert toc.end_line >= 8, f"TOC ended at line {toc.end_line}, expected >= 8"
    assert (
        "PART I" in lines[toc.end_line] or "ITEM 1. BUSINESS" in lines[toc.end_line + 1]
    )


def test_adversarial_split_toc_dashed_page_number():
    """Adversarial: Multi-page TOC split by a dashed page number ( -2- )."""
    doc = """\
TABLE OF CONTENTS
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 8
  -2-
Item 2. Properties ...................................... 15
Item 5. Market for Common Equity ........................ 35
Item 8. Financial Statements ............................ 60

PART I

ITEM 1. BUSINESS
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    assert toc.end_line >= 6


def test_adversarial_split_toc_page_n_of_m():
    """Adversarial: Multi-page TOC split by a 'Page 1 of 2' marker."""
    doc = """\
TABLE OF CONTENTS
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 8
Page 1 of 2
Item 7. Management's Discussion ......................... 40
Item 8. Financial Statements ............................ 60

PART I

ITEM 1. BUSINESS
The Company was incorporated in Delaware.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    assert toc.end_line >= 5


def test_adversarial_split_toc_plain_page_n():
    """Adversarial: Multi-page TOC split by a standalone 'Page 2' marker."""
    doc = """\
TABLE OF CONTENTS
Item 1. Business ........................................ 1
Item 1A. Risk Factors ................................... 8
Page 2
Item 5. Market for Common Equity ........................ 35
Item 8. Financial Statements ............................ 60

PART I

ITEM 1. BUSINESS
Annual Report contents begin here.
"""
    toc = find_toc_span(doc, start_line=0, derived_taxonomy=FORM_10K_DERIVED)
    assert toc is not None
    assert toc.start_line == 0
    assert toc.end_line >= 5
