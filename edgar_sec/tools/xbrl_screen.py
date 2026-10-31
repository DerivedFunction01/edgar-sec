"""Corpus screen: one term across every SP100 filer, with a dimensional census."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.apps.client.comparison import panel_query
from edgar_sec.apps.client.facts import facts_from_arrow_table
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import calculation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.infra.storage.atomic import atomic_write_json

_RPO = "us-gaap:RevenueRemainingPerformanceObligation"
_TERMS = {"rpo": _RPO, "revenue": "revenue"}
_SPECIMEN_FIRMS = ("HON", "ORCL")


def _sp100_bundles(fixtures_root: Path) -> list[dict[str, Any]]:
    """SP100 cohort rows joined to their fixture bundle folders."""
    cohort = json.loads(
        (fixtures_root / "xbrl" / "sp100_cohort.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (fixtures_root / "xbrl" / "sp100" / "fixture_source_registry.json").read_text(
            encoding="utf-8"
        )
    )
    folder_by_accession = {
        row["cohort_accession"]: row["folder"] for row in registry["bundles"]
    }
    bundles = []
    for row in cohort:
        folder = folder_by_accession.get(row["accession"])
        if folder is None:
            raise ValueError(f"no SP100 bundle for accession {row['accession']}")
        bundles.append(
            {
                "firm": row["firm"],
                "fy": row["fy"],
                "accession": row["accession"],
                "folder": folder,
            }
        )
    return bundles


def _facade(bundle_dir: Path, taxonomy: DomainTaxonomy) -> Xbrl:
    facts = facts_from_arrow_table(pq.read_table(bundle_dir / "facts.parquet"))
    arcs = calculation_arcs_from_arrow_table(
        pq.read_table(bundle_dir / "calculation_arcs.parquet")
    )
    bundle = FilingXbrl(
        accession=AccessionNumber.from_any(facts[0].accession),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, taxonomy)


def _modal_instant(facade: Xbrl) -> str | None:
    counts = Counter(
        fact.instant_date
        for fact in facade.facts
        if not fact.dimensions and fact.instant_date
    )
    return counts.most_common(1)[0][0] if counts else None


def _total_shape(
    facade: Xbrl, taxonomy: DomainTaxonomy, concept: str, instant: str | None
) -> tuple[str, tuple[str, ...]]:
    """How a concept's total is carried at the filer's balance-sheet date.

    Instant facts sit at the date; duration facts end at the date.
    """
    facts = [
        fact
        for fact in facade.facts
        if fact.concept_qname == concept
        and (fact.instant_date == instant or fact.end_date == instant)
    ]
    if not facts:
        return "absent", ()
    if any(not fact.dimensions for fact in facts):
        return "undimensioned", ()
    families = sorted(
        {taxonomy.classify_axis(axis) for fact in facts for axis in fact.dimensions}
    )
    return "dimensioned_only", tuple(families)


def run_screen(
    fixtures_root: Path,
    *,
    policy: str | None = "horizon_totals",
    firms: set[str] | None = None,
) -> dict[str, Any]:
    """Screen RPO and revenue over the SP100 bundles and census the total shapes."""
    taxonomy = load_domain_taxonomy()
    bundles = [
        row
        for row in _sp100_bundles(fixtures_root)
        if firms is None or row["firm"] in firms
    ]
    facades = {
        row["firm"]: _facade(fixtures_root / "xbrl" / "sp100" / row["folder"], taxonomy)
        for row in bundles
    }
    report: dict[str, Any] = {
        "policy": policy,
        "filer_count": len(facades),
        "panels": {},
        "census": {},
        "year_mismatches": [],
        "specimens": {},
    }
    for key, term in _TERMS.items():
        panel = panel_query(facades, term, dimension_policy=policy)
        report["panels"][key] = {
            "term": term,
            "answered": len(panel.rows) - len(panel.missing),
            "missing": list(panel.missing),
            "total": panel.total,
            "rows": [
                {
                    "filer": row.filer,
                    "status": str(row.status),
                    "value": row.value,
                    "candidates": list(row.candidates),
                }
                for row in panel.rows
            ],
        }
    census: dict[str, Counter[str]] = {key: Counter() for key in _TERMS}
    for row in bundles:
        firm = row["firm"]
        facade = facades[firm]
        instant = _modal_instant(facade)
        if instant is not None and int(instant[:4]) != int(row["fy"]):
            report["year_mismatches"].append(
                {"filer": firm, "registry_fy": row["fy"], "modal_instant": instant}
            )
        shape, families = _total_shape(facade, taxonomy, _RPO, instant)
        census["rpo"][shape] += 1
        for family in families:
            census["rpo"][f"dimensioned_only:{family}"] += 1
        revenue = facade.query(
            "revenue",
            fiscal_year=int(instant[:4]) if instant else None,
            dimension_policy=policy,
        )
        revenue_shape = "absent"
        for concept in revenue.candidate_qnames:
            shape, families = _total_shape(facade, taxonomy, concept, instant)
            if shape != "absent":
                revenue_shape = shape
                for family in families:
                    census["revenue"][f"dimensioned_only:{family}"] += 1
                break
        census["revenue"][revenue_shape] += 1
    report["census"] = {key: dict(counts) for key, counts in census.items()}
    for firm in _SPECIMEN_FIRMS:
        if firm in facades:
            report["specimens"][firm] = [
                {
                    "value": fact.value,
                    "instant": fact.instant_date,
                    "dimensions": dict(fact.dimensions),
                }
                for fact in facades[firm].facts
                if fact.concept_qname == _RPO
            ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "tests" / "fixtures",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--policy", default="horizon_totals")
    args = parser.parse_args()
    report = run_screen(args.fixtures, policy=args.policy)
    for key, panel in report["panels"].items():
        print(
            f"{key}: answered {panel['answered']}/{report['filer_count']} "
            f"total {panel['total']:,.0f} missing {panel['missing']}"
        )
    for key, counts in report["census"].items():
        print(f"census {key}: {counts}")
    print(f"year mismatches: {report['year_mismatches']}")
    if args.out is not None:
        atomic_write_json(args.out, report, indent=1)
        print(f"report written to {args.out}")


if __name__ == "__main__":
    main()
