"""Unit tests for XBRL Parquet serialization of linkbases and facts."""

from pathlib import Path
import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.storage.storage import (
    write_calculation_arcs_parquet,
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
