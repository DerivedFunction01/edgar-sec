"""Unit tests for XBRL Parquet serialization of linkbases and facts."""

from pathlib import Path
import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    DefinitionArc,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.storage.storage import (
    calculation_arcs_from_arrow_table,
    declarations_from_arrow_table,
    definition_arcs_from_arrow_table,
    presentation_arcs_from_arrow_table,
    read_declarations_parquet,
    write_calculation_arcs_parquet,
    write_declarations_parquet,
    write_definition_arcs_parquet,
    write_facts_parquet,
    write_presentation_arcs_parquet,
)


def test_write_calculation_and_presentation_parquet(tmp_path: Path) -> None:
    """Verify writing calculation and presentation arcs to Parquet."""
    calc_arcs = [
        CalculationArc(
            parent_qname="us-gaap:GrossProfit",
            child_qname="us-gaap:Revenues",
            weight=1.0,
            order=1.0,
            role_uri="http://msft/role/Income",
        )
    ]
    calc_path = tmp_path / "calc.parquet"
    assert write_calculation_arcs_parquet(calc_arcs, calc_path) == 1
    assert calc_path.is_file()

    table = pq.read_table(calc_path)
    assert table.num_rows == 1
    assert table.column("parent_qname")[0].as_py() == "us-gaap:GrossProfit"
    assert table.column("weight")[0].as_py() == 1.0

    pres_arcs = [
        PresentationArc(
            parent_qname="us-gaap:Abstract",
            child_qname="us-gaap:GrossProfit",
            order=1.0,
            role_uri="http://msft/role/Income",
        )
    ]
    pres_path = tmp_path / "pres.parquet"
    assert write_presentation_arcs_parquet(pres_arcs, pres_path) == 1
    assert pres_path.is_file()


def test_arc_tables_roundtrip_through_converters(tmp_path: Path) -> None:
    """Verify arc converters rebuild the exact arcs the writers stored."""
    calc_arcs = (
        CalculationArc("us-gaap:GrossProfit", "us-gaap:Revenues", 1.0, 1.0, "r1"),
        CalculationArc("us-gaap:GrossProfit", "us-gaap:CostOfRevenue", -1.0, 2.0, "r1"),
    )
    calc_path = tmp_path / "calc.parquet"
    write_calculation_arcs_parquet(list(calc_arcs), calc_path)
    assert calculation_arcs_from_arrow_table(pq.read_table(calc_path)) == calc_arcs

    pres_arcs = (
        PresentationArc("us-gaap:Abstract", "us-gaap:GrossProfit", 1.0, "r1"),
        PresentationArc("us-gaap:Abstract", "us-gaap:GrossProfit", 9.0, "r1"),
    )
    pres_path = tmp_path / "pres.parquet"
    write_presentation_arcs_parquet(list(pres_arcs), pres_path)
    assert presentation_arcs_from_arrow_table(pq.read_table(pres_path)) == pres_arcs


def test_definition_arcs_parquet_roundtrip(tmp_path: Path) -> None:
    """Definition arcs survive the Parquet roundtrip, nulls included."""
    arcs = (
        DefinitionArc(
            parent_qname="us-gaap:EquityComponentDomain",
            child_qname="us-gaap:CommonStockMember",
            arcrole="http://xbrl.org/int/dim/arcrole/domain-member",
            order=1.0,
            role_uri="http://msft/role/Equity",
            usable=False,
            closed=True,
            context_element="segment",
        ),
        DefinitionArc(
            parent_qname="us-gaap:StatementEquityComponentsAxis",
            child_qname="us-gaap:EquityComponentDomain",
            arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain",
        ),
    )
    path = tmp_path / "definition_arcs.parquet"
    assert write_definition_arcs_parquet(list(arcs), path) == 2
    assert definition_arcs_from_arrow_table(pq.read_table(path)) == arcs


def test_write_facts_parquet(tmp_path: Path) -> None:
    """Verify writing XBRL facts with dimensional slices to Parquet."""
    facts = [
        XbrlFact(
            accession=AccessionNumber("0000950170-24-087843"),
            concept_qname="us-gaap:Revenues",
            value=245122000000.0,
            unit="USD",
            decimals=-6,
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
            dimensions={"srt:ProductOrServiceAxis": "msft:CloudMember"},
            context_id="c-1",
        )
    ]
    facts_path = tmp_path / "facts.parquet"
    assert write_facts_parquet(facts, facts_path) == 1
    assert facts_path.is_file()

    table = pq.read_table(facts_path)
    assert table.num_rows == 1
    assert table.column("numeric_value")[0].as_py() == 245122000000.0
    assert "CloudMember" in table.column("dimensions_json")[0].as_py()


def test_write_declarations_parquet_roundtrip(tmp_path: Path) -> None:
    """Declarations survive the Parquet roundtrip, item type included."""
    declarations = [
        ConceptDeclaration(
            concept_qname="msft:CloudMember",
            name="CloudMember",
            period_type="duration",
            substitution_group="xbrli:item",
            item_type="xbrli:stringItemType",
        ),
        ConceptDeclaration(concept_qname="us-gaap:Revenues", name="Revenues"),
    ]
    path = tmp_path / "declarations.parquet"
    assert write_declarations_parquet(declarations, path) == 2
    loaded = declarations_from_arrow_table(read_declarations_parquet(path))
    assert loaded == tuple(declarations)


def test_bundle_declarations_merge_archive_rows(tmp_path: Path) -> None:
    """A bundle read supplies referenced archive rows under its own rows."""
    import json

    (tmp_path / "namespaces.json").write_text(
        json.dumps(
            {
                "us-gaap": "http://fasb.org/us-gaap/2024",
                "ex": "http://example.com/20241231",
            }
        ),
        encoding="utf-8",
    )
    own = [
        ConceptDeclaration(
            concept_qname="us-gaap:Assets",
            name="Assets",
            item_type="ex:bundleItemType",
        ),
        ConceptDeclaration(
            concept_qname="ex:Custom",
            name="Custom",
            period_type="duration",
            substitution_group="xbrli:item",
            item_type="xbrli:stringItemType",
        ),
    ]
    write_declarations_parquet(own, tmp_path / "declarations.parquet")
    facts = [
        XbrlFact(
            accession=AccessionNumber("0000950170-24-087843"),
            concept_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            value=1.0,
            unit="USD",
            decimals=0,
            period_type="instant",
            instant_date="2024-06-30",
            dimensions={},
            context_id="c-1",
        )
    ]
    write_facts_parquet(facts, tmp_path / "facts.parquet")
    loaded = declarations_from_arrow_table(
        read_declarations_parquet(tmp_path / "declarations.parquet")
    )
    by_qname = {item.concept_qname: item for item in loaded}
    assert by_qname["us-gaap:Assets"].item_type == "ex:bundleItemType"
    supplied = by_qname["us-gaap:CashAndCashEquivalentsAtCarryingValue"]
    assert supplied.period_type == "instant"
    assert supplied.item_type == "xbrli:monetaryItemType"
    assert by_qname["ex:Custom"].period_type == "duration"
    assert len(loaded) == 3
