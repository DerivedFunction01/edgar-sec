"""Unit tests for the standard item-type table and declaration merge."""

from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.taxonomy.archive import current_table
from edgar_sec.engine.xbrl.taxonomy.item_types import (
    declaration_for,
    is_numeric_item_type,
    item_type_local,
    merge_declarations,
)

_TABLE = {"us-gaap:Revenues": "xbrli:monetaryItemType"}


def test_item_type_local_strips_any_prefix() -> None:
    """Family keying is by local part, whatever prefix the schema used."""
    assert item_type_local("dtr-types:textBlockItemType") == "textBlockItemType"
    assert item_type_local("i:stringItemType") == "stringItemType"
    assert item_type_local(None) is None


def test_is_numeric_item_type_covers_the_numeric_family() -> None:
    """DTR and xbrli numeric types are numeric, whatever their prefix."""
    for item_type in (
        "xbrli:monetaryItemType",
        "xbrli:decimalItemType",
        "xbrli:integerItemType",
        "xbrli:sharesItemType",
        "xbrli:pureItemType",
        "xbrli:positiveIntegerItemType",
        "dtr-types:percentItemType",
        "dtr-types:perShareItemType",
        "srt-types:perUnitItemType",
        "num:volumeItemType",
    ):
        assert is_numeric_item_type(item_type)


def test_is_numeric_item_type_rejects_non_numeric_types() -> None:
    """Identifier, date, and text types are outside the numeric family."""
    for item_type in (
        "dei:centralIndexKeyItemType",
        "dei:employerIdItemType",
        "dei:sequenceNumberItemType",
        "xbrli:gYearItemType",
        "xbrli:normalizedStringItemType",
        "xbrli:stringItemType",
        "dtr-types:textBlockItemType",
        None,
    ):
        assert not is_numeric_item_type(item_type)


def test_merge_declarations_fills_only_missing_types() -> None:
    """Extension declarations win; the table fills gaps underneath."""
    typed = ConceptDeclaration(
        concept_qname="us-gaap:Revenues",
        name="Revenues",
        item_type="xbrli:stringItemType",
    )
    untyped = ConceptDeclaration(concept_qname="us-gaap:Revenues", name="Revenues")
    assert merge_declarations([typed], _TABLE)[0].item_type == "xbrli:stringItemType"
    assert merge_declarations([untyped], _TABLE)[0].item_type == (
        "xbrli:monetaryItemType"
    )


def test_declaration_for_synthesizes_from_table() -> None:
    """A standard qname with no extension declaration resolves from the table."""
    declaration = declaration_for("us-gaap:Revenues", _TABLE)
    assert declaration is not None
    assert declaration.item_type == "xbrli:monetaryItemType"
    assert declaration_for("us-gaap:NotInTable", _TABLE) is None


def test_shipped_table_covers_the_text_population() -> None:
    """The archive's current-vintage table resolves the canonical specimens."""
    table = current_table()
    assert item_type_local(table["us-gaap:Revenues"]) == "monetaryItemType"
    assert (
        item_type_local(table["us-gaap:SignificantAccountingPoliciesTextBlock"])
        == "textBlockItemType"
    )
    assert item_type_local(table["dei:EntityCommonStockSharesOutstanding"]) == (
        "sharesItemType"
    )
