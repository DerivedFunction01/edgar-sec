"""Shared filing vectors for the reflow stage tests.

The reference tree's `defs/tests/test_reflow.py` holds these documents inline in
one 1,013-line module. `AGENTS.md` §6.3 puts shared setup in `conftest.py` at
the narrowest directory that needs it, and the `file-length` scanner caps a test
file at 800 lines, so the documents live here and the tests request them by
name. Nothing here asserts anything: these are inputs, and each test states the
one property it holds them to.
"""

from __future__ import annotations

import pytest

TAGGED_TABLE = "<TABLE>\n<S>     <C>   <C>\nAssets   1,000   900\n</TABLE>"


@pytest.fixture
def justified_prose_with_numbers() -> str:
    return (
        "PART I\nITEM 1. BUSINESS\n\n"
        "Metals  Packaging,  which accounted for  approximately  82% of consolidated  net\n"
        "sales  and  approximately  81% of  consolidated  operating  income  in 1997,\n"
        "employed  approximately  32,000 persons  across  various manufacturing sites."
    )


@pytest.fixture
def financial_narrative() -> str:
    return (
        "      Revenues  for  the  year  ended  December  31,  1998  increased  52.9%  to\n"
        "approximately  $20,224,000  from  approximately  $13,231,000  for the year ended\n"
        "December  31,  1997.   Approximately   5.4%  or  $380,000  of  the  increase  is\n"
        "attributable  to  increased  hours of service  provided  under  existing and new\n"
        "contracts in the State of New York."
    )


@pytest.fixture
def repeated_numeric_columns() -> str:
    return (
        "PART I\nITEM 1. BUSINESS\n\nThe following table summarizes our results:\n\n"
        "Revenue by segment       2024       2023\n"
        "  Automotive             $1,200     $1,100\n"
        "  Industrial              $2,050     $1,980\n"
        "  Total                  $3,250     $3,080\n\n"
        "ITEM 2. PROPERTIES\nOur properties are described below."
    )


@pytest.fixture
def signature_block() -> str:
    return (
        "Signature                     Title                         Date\n\n"
        "/s/Gary L. Westerholm\n"
        "_____________________\n"
        "Gary L. Westerholm       President, Chief Executive\n"
        "                         Officer and Director           January 13, 2004\n\n"
        "/s/John DiMora\n"
        "______________\n"
        "John DiMora                    Director                 January 13, 2004\n\n"
        "John W. Sawarin                Director\n\n"
        "After section"
    )


@pytest.fixture
def wrapped_description_table() -> str:
    return (
        "Description                         2024       2023\n"
        "-----------------------------------  ---------  ---------\n"
        "Government assistance, non-interest\n"
        "bearing, repayable in quarterly\n"
        "payments commencing October 1, 2024       395,778    369,550\n"
        "-----------------------------------  ---------  ---------\n"
        "Following prose begins here.\n"
    )


@pytest.fixture
def structural_section_table() -> str:
    return (
        "Total liabilities             4,868,402    3,856,168\n"
        "                              ----------   ----------\n\n"
        "Commitments and Contingencies (note 15)\n\n"
        "Stockholders' equity (deficit):\n\n"
        "Common stock                       24,818       23,649\n"
        "Additional paid in capital     20,133,739   16,781,788\n"
        "Total stockholders' deficit    (3,252,981)  (2,983,592)\n"
        "                              ------------ ------------\n"
        "Total liabilities and stockholders' deficit\t     $\t1,615,421  $\t872,576\n"
        "                              ============ ============"
    )


@pytest.fixture
def balance_sheet() -> str:
    return (
        "CONSOLIDATED BALANCE SHEETS\n"
        "2004                         2003\n"
        "Cash                         100        90\n"
        "Other assets                 200       180\n"
        "Total assets                 300       270\n\n"
        "LIABILITIES AND STOCKHOLDERS' EQUITY\n\n"
        "Current liabilities           50        45\n"
        "Long-term debt                50        45\n"
        "Total liabilities and stockholders' equity  100  90\n"
        "=======================================  ======\n"
    )


@pytest.fixture
def long_term_debt_schedule() -> str:
    return (
        "PART II\nITEM 8. FINANCIAL STATEMENTS\n\n8.   LONG-TERM DEBT\n\n"
        "Outstanding long-term debt consists of the following at December 31, 1999\n"
        "and 1998:\n"
        "                                                          1999         1998\n"
        "                                                     ------------ ------------\n"
        "Five-year revolving credit agreement                   $ 400,000     $ 35,000\n"
        "Term loan                                                 34,392       34,392\n"
        "364-day credit agreement                                 121,000            -\n"
        "Other                                                          -          128\n"
        "                                                     ------------ ------------\n"
        "                                                         555,392       69,520\n\n"
        "Less current portion of long-term debt                   121,000            -\n"
        "                                                     ------------ ------------\n"
        "Long-term debt                                         $ 434,392     $ 69,520\n"
        "                                                     ============ ============\n\n"
        "On June 5, 1998, in connection with the acquisition of Galileo Canada, the\n"
        "Company incurred $34,392 of debt under a five-year term loan agreement.\n"
    )


@pytest.fixture
def tax_tables_with_prose_between() -> str:
    intro = (
        "The tax effects of temporary differences that give rise to significant portions\n"
        "of the deferred tax assets are presented below:"
    )
    first_table = (
        "2004                                      2003\n"
        "------------------------------------------ ----------\n"
        "Computed tax recovery                    (100)       (90)\n"
        "Tax benefits not recognized                 10          8\n"
        "Total income tax recovery                  (90)       (82)"
    )
    second_table = (
        "2004                                      2003\n"
        "------------------------------------------ ----------\n"
        "Loss carry forwards                      1,000        900\n"
        "Net deferred tax assets                  1,050        940"
    )
    return f"{first_table}\n\n{intro}\n\n{second_table}"


@pytest.fixture
def tariff_page() -> str:
    table = (
        "MONTHLY DISCOUNTS\n"
        "Service                         2024       2023\n"
        "Domestic ASDS                   100%        90%\n"
        "Domestic DDS                     80%        75%\n"
        "Domestic ACCUNET                 60%        55%"
    )
    footer = (
        "AT&T COMMUNICATIONS                              CONTRACT TARIFF NO. 10906\n"
        "Adm. Rates and Tariffs                                  1st Revised Page 9\n"
        "Bridgewater, NJ  08807                             Cancels Original Page 9\n"
        "Issued:  May 21, 1999                             Effective:  May 22, 1999"
    )
    return f"{table}\n\n{footer}"


@pytest.fixture
def lease_intro_then_debt_table() -> str:
    tagged = "<TABLE>\n<S>    <C>\nlease payment 100 90\n</TABLE>"
    intro = (
        "     Future  minimum  lease  payments  under  capital  leases and  noncancelable\n"
        "operating leases at December 31, 1999 are as follows:"
    )
    debt_table = (
        "                                                          1999         1998\n"
        "                                                     ------------ ------------\n"
        "Five-year revolving credit agreement                   $ 400,000     $ 35,000\n"
        "Term loan                                                 34,392       34,392\n"
        "364-day credit agreement                                 121,000            -\n"
        "Other                                                          -          128\n"
        "                                                     ------------ ------------\n"
        "                                                         555,392       69,520"
    )
    return (
        "PART II\nITEM 8. FINANCIAL STATEMENTS\n\n"
        f"{intro}\n{tagged}\n\n"
        "SCHEDULE OF LONG-TERM DEBT\n\n"
        "Outstanding long-term debt consists of the following at December 31, 1999\n"
        "and 1998:\n"
        f"{debt_table}"
    )


@pytest.fixture
def property_schedule() -> str:
    return (
        "2.      PROPERTY AND EQUIPMENT:\n\n"
        "Property and equipment consist of the following at December 31, 1998:\n\n"
        "    Machinery and equipment                                     $465,498\n"
        "    Furniture and fixtures                                       177,904\n"
        "                                                               ---------\n"
        "                                                                $643,402\n"
        "                                                               ========="
    )


@pytest.fixture
def fiscal_period_schedule() -> str:
    return (
        "                            High          Low\n"
        "                            ----          ---\n"
        "Fiscal 1998\n- -----------\n"
        "First  Quarter              3.50          1.50\n"
        "Second Quarter              1.958         1.562\n"
        "Third  Quarter              1.50          1.125\n"
        "Fourth Quarter              1.187          .83\n\n"
        "Fiscal 1999\n- -----------\n"
        "First  Quarter              1.312          .771\n"
    )


@pytest.fixture
def unit_header_schedule() -> str:
    return (
        "             Consolidated Balance Sheets\n"
        "             (in thousands, except per share data)\n\n"
        "                                     2003       2002\n"
        "                                     ----       ----\n"
        "Cash and cash equivalents          $1,200     $1,100\n"
        "Total current assets                4,500      3,900\n"
    )


@pytest.fixture
def explanatory_note() -> str:
    return (
        "FORM 10-K\n\nExplanatory Note\n\n"
        "This amendment does not reflect events occurring after the original filing of\n"
        "the Annual Report on Form 10-K, as previously amended, or modify or update those\n"
        "disclosures as presented in the Form 10-K, as previously amended.\n\n"
        "PART I\n"
    )
