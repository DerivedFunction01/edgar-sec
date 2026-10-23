"""Load committed offline filing artifacts as solver inputs."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry
from tests.support import fixture_path, load_fixture


def load_seed_cohort() -> tuple[CohortEntry, ...]:
    registry = load_fixture("xbrl/seed_cohort.json")
    sources = load_fixture("xbrl/seed/fixture_source_registry.json")["bundles"]
    folder_by_accession = {s["cohort_accession"]: s["folder"] for s in sources}
    seed_root = fixture_path("xbrl/seed")
    entries = []
    for item in registry:
        folder = folder_by_accession.get(item["accession"])
        if folder is None:
            raise ValueError(f"seed bundle for accession {item['accession']}")
        facts_path = seed_root / folder / "facts.parquet"
        accessions = set(
            pq.read_table(facts_path, columns=["accession"]).column(0).to_pylist()
        )
        if len(accessions) != 1:
            raise ValueError(f"seed bundle for {item['firm']}: {accessions}")
        entries.append(
            CohortEntry(
                accession=accessions.pop(),
                facts_path=facts_path,
                firm=item["firm"],
            )
        )
    return tuple(entries)


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
