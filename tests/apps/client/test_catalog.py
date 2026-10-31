"""Presentation catalog: roles, derived categories, titles, and lookup."""

from __future__ import annotations

import pyarrow.parquet as pq

from edgar_sec.apps.client.catalog import _segment_word
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import presentation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support import bundle_dir

_MSFT = "msft_2024_10k"
_JPM = "jpm_2024_10k"
_AFRM = "afrm_2024_10k"
_MSFT_ROLE = "http://www.microsoft.com/20240630/taxonomy/role"
_INCOME_URI = f"{_MSFT_ROLE}/Role_StatementINCOMESTATEMENTS"
_EQUITY_DETAIL_URI = (
    f"{_MSFT_ROLE}/Role_DisclosureStockholdersEquityAdditionalInformationDetail"
)


def _facade(folder: str, *, presentation: bool = True) -> Xbrl:
    pres_arcs = ()
    if presentation:
        table = pq.read_table(bundle_dir(folder) / "presentation_arcs.parquet")
        pres_arcs = presentation_arcs_from_arrow_table(table)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(
            calculation_arcs=load_seed_calculation_arcs(folder),
            presentation_arcs=pres_arcs,
        ),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_msft_catalog_lists_all_presentation_roles() -> None:
    """MSFT 2024 files 119 presentation roles; the catalog lists each once."""
    frame = _facade(_MSFT).statements.list_available()
    assert len(frame) == 119
    assert list(frame.columns) == ["title", "category", "concept_count", "role"]
    assert frame["role"].is_unique


# Edgartools reports 7 statements / 72 disclosures for this filing; the
# one-role difference is the equity detail role pinned below.
def test_msft_category_split_from_derivation() -> None:
    """Derived split: 6 statements, 1 document, 39 notes, 73 disclosures."""
    statements = _facade(_MSFT).statements
    counts = {
        category: len(statements.by_category(category))
        for category in ("statement", "document", "note", "disclosure")
    }
    assert counts == {"statement": 6, "document": 1, "note": 39, "disclosure": 73}


# The role's root seeds the Equity slice, so the family is recorded; the
# filer's own Detail suffix decides the category.
def test_msft_detail_role_on_equity_abstract_is_disclosure() -> None:
    """A Detail role rooting on the equity abstract stays a disclosure."""
    entry = _facade(_MSFT).statements.get(_EQUITY_DETAIL_URI)
    assert entry is not None
    assert entry.category == "disclosure"
    assert entry.family == "Equity"
    assert entry.title == "Stockholders Equity Additional Information Detail"


def test_msft_statement_entry_carries_family_roots_and_tree() -> None:
    """A statement entry carries its slice family, roots, and role arcs."""
    entry = _facade(_MSFT).statements.get(_INCOME_URI)
    assert entry is not None
    assert entry.title == "Income Statements"
    assert entry.category == "statement"
    assert entry.family == "IncomeStatement"
    assert entry.roots == ("us-gaap:IncomeStatementAbstract",)
    assert entry.concept_count == 24
    assert entry.concepts == tuple(sorted(set(entry.concepts)))
    assert len(entry.concepts) == entry.concept_count
    assert entry.arcs
    assert all(arc.role_uri == _INCOME_URI for arc in entry.arcs)
    assert "us-gaap:NetIncomeLoss" in entry.concepts


def test_msft_statement_titles() -> None:
    """Statement titles humanize from the role URI tails."""
    statements = _facade(_MSFT).statements
    assert {entry.title for entry in statements.by_category("statement")} == {
        "Income Statements",
        "Comprehensive Income Statements",
        "Balance Sheets",
        "Balance Sheets Parenthetical",
        "Cash Flows Statements",
        "Stockholders Equity Statements",
    }
    document = statements.by_category("document")
    assert [entry.title for entry in document] == ["Document and Entity Information"]
    assert document[0].family == "Cover"


def test_get_resolves_uri_exact_title_and_casefolded_title() -> None:
    """get resolves a role URI, an exact title, then a casefolded title."""
    statements = _facade(_MSFT).statements
    by_uri = statements.get(_INCOME_URI)
    assert by_uri is not None
    assert statements.get("Income Statements") is by_uri
    assert statements.get("income statements") is by_uri
    assert statements.get("No Such Role") is None


def test_search_matches_every_term_token_in_title() -> None:
    """Search returns titles carrying all of the term's tokens."""
    statements = _facade(_MSFT).statements
    hits = statements.search("long term debt")
    assert [entry.title for entry in hits] == [
        "Disclosure Components of Long Term Debt Detail",
        "Disclosure Components of Long Term Debt Parenthetical Detail",
        "Maturities of Long Term Debt Including Current Portion Detail",
    ]
    assert statements.search("debt")
    assert statements.search("zanzibar") == ()
    assert statements.search("") == ()


def test_by_category_partitions_the_catalog() -> None:
    """The four categories are disjoint and cover every role."""
    statements = _facade(_MSFT).statements
    groups = [
        statements.by_category(category)
        for category in ("statement", "document", "note", "disclosure")
    ]
    roles = [entry.role_uri for group in groups for entry in group]
    assert len(roles) == len(set(roles)) == 119
    assert statements.by_category("other") == ()


def test_jpm_catalog_split_and_titles() -> None:
    """JPM 2024: 235 roles; statements resolve by slice and URI alike."""
    statements = _facade(_JPM).statements
    assert len(statements.list_available()) == 235
    counts = {
        category: len(statements.by_category(category))
        for category in ("statement", "document", "note", "disclosure")
    }
    assert counts == {"statement": 7, "document": 1, "note": 71, "disclosure": 156}
    assert {entry.title for entry in statements.by_category("statement")} == {
        "Consolidated Statements of Income",
        "Consolidated Statements of Comprehensive Income",
        "Consolidated Balance Sheets",
        "Consolidated Balance Sheets Parenthetical",
        "Consolidated Statements of Changes in Stockholders Equity",
        "Consolidated Statements of Changes in Stockholders Equity Parenthetical",
        "Consolidated Statements of Cash Flows",
    }
    assert any(
        entry.title == "Long Term Debt" for entry in statements.search("long term debt")
    )
    balance_sheet = statements.get("Consolidated Balance Sheets")
    assert balance_sheet is not None
    assert balance_sheet.family == "BalanceSheet"
    assert balance_sheet.concept_count == 43


def test_catalog_is_empty_without_presentation_arcs() -> None:
    """A lookup-built facade (no presentation arcs) catalogs nothing."""
    statements = _facade(_MSFT, presentation=False).statements
    frame = statements.list_available()
    assert frame.empty
    assert list(frame.columns) == ["title", "category", "concept_count", "role"]
    assert statements.get(_INCOME_URI) is None
    assert statements.search("debt") == ()
    assert statements.by_category("statement") == ()


_WORDS = frozenset(
    {
        "balance",
        "sheet",
        "long",
        "term",
        "changes",
        "in",
        "of",
        "with",
        "and",
        "statement",
    }
)
_ATTESTED = frozenset({"statement", "document", "components", "comp", "aoci"})


def test_segment_word_splits_merged_compounds() -> None:
    """Merged tokens split on lexicon/stop words, plurals included."""
    assert _segment_word("balancessheets", _WORDS, _ATTESTED) == [
        "balances",
        "sheets",
    ]
    assert _segment_word("statementsof", _WORDS, _ATTESTED) == [
        "statements",
        "of",
    ]
    assert _segment_word("longterm", _WORDS, _ATTESTED) == ["long", "term"]
    assert _segment_word("changesin", _WORDS, _ATTESTED) == ["changes", "in"]


def test_segment_word_refuses_false_covers() -> None:
    """Attested junk pieces and all-stop covers never split a word."""
    assert _segment_word("components", _WORDS, _ATTESTED) is None
    assert _segment_word("within", _WORDS, _ATTESTED) is None
    assert _segment_word("aoci", _WORDS, _ATTESTED, whole_ok=True) is None


def test_afrm_components_title_is_not_split() -> None:
    """AFRM's Balance Sheet Components role keeps its real word."""
    statements = _facade(_AFRM).statements
    titles = set(statements.list_available()["title"])
    assert "Balance Sheet Components" in titles
