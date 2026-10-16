"""Load committed offline filing artifacts as solver inputs."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from tests.support import fixture_path


def load_seed_facts(folder: str) -> tuple[XbrlFact, ...]:
    rows = pq.read_table(fixture_path(f"xbrl/seed/{folder}/facts.parquet")).to_pylist()
    return tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=row["numeric_value"]
            if row["numeric_value"] is not None
            else row["text_value"],
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in rows
    )


def load_seed_calculation_arcs(folder: str) -> tuple[CalculationArc, ...]:
    rows = pq.read_table(
        fixture_path(f"xbrl/seed/{folder}/calculation_arcs.parquet")
    ).to_pylist()
    return tuple(
        CalculationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            weight=row["weight"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in rows
    )
