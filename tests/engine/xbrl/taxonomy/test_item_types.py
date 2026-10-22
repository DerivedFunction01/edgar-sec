"""Unit tests for the standard item-type table and declaration merge."""

import json
from pathlib import Path

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.taxonomy.item_types import (
    declaration_for,
    item_type_local,
    load_standard_item_types,
    merge_declarations,
)

_TABLE = {"us-gaap:Revenues": "xbrli:monetaryItemType"}


def test_load_standard_item_types_roundtrip(tmp_path: Path) -> None:
    """The loader reads the qname -> item-type JSON table."""
    path = tmp_path / "types.json"
    path.write_text(json.dumps(_TABLE), encoding="utf-8")
    assert load_standard_item_types(path) == _TABLE


def test_item_type_local_strips_any_prefix() -> None:
    """Family keying is by local part, whatever prefix the schema used."""
    assert item_type_local("dtr-types:textBlockItemType") == "textBlockItemType"
    assert item_type_local("i:stringItemType") == "stringItemType"
    assert item_type_local(None) is None


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
    """The shipped table resolves the canonical text and numeric specimens."""
    table = load_standard_item_types(
        resolve_xbrl_paths().default_standard_item_types_path
    )
    assert item_type_local(table["us-gaap:Revenues"]) == "monetaryItemType"
    assert (
        item_type_local(table["us-gaap:SignificantAccountingPoliciesTextBlock"])
        == "textBlockItemType"
    )
    assert item_type_local(table["dei:EntityCommonStockSharesOutstanding"]) == (
        "sharesItemType"
    )
