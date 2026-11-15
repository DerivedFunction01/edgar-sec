"""Fresh-accession draw — DuckDB over the published extracts.

Universe: filing_targets of the configured catalog snapshot; era
quotas per form, one filing per (cik, fiscal period), seeded order
md5(accession || seed), dashed-accession normalization for all
exclusion comparisons. Outputs: one spec JSON per drawn accession
(labels empty, configured population name) + draw summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.measurement.config import load_config

import duckdb

CONFIG = load_config()
SEED = CONFIG["seed"]
SNAPSHOT = Path(CONFIG["snapshot"]).expanduser()
EXCLUDE_DIRS = [Path(d).expanduser() for d in CONFIG["exclude_dirs"]]
SKIP_NAMES = {"build-summary.json", "finalize-summary.json"}


def main() -> int:
    out_dir = Path(sys.argv[1])
    forms = tuple(sys.argv[2].split(","))
    quotas = json.loads(sys.argv[3])
    population = sys.argv[4]
    specs_dir = out_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    excluded: set[str] = set()
    per_dir: dict[str, int] = {}
    for d in EXCLUDE_DIRS:
        names = {p.stem for p in d.glob("*.json") if p.name not in SKIP_NAMES}
        per_dir[str(d)] = len(names)
        excluded |= names
    con = duckdb.connect()
    targets = str(SNAPSHOT / "filing_targets" / "*.parquet")
    cols = [
        r[0]
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{targets}')"
        ).fetchall()
    ]
    print("filing_targets columns:", cols)
    period_col = next(
        (
            c
            for c in (
                "report_date",
                "period_of_report",
                "fiscal_period_end",
                "period_end",
                "report_period",
            )
            if c in cols
        ),
        None,
    )
    con.execute("CREATE TEMP TABLE excl (accession VARCHAR)")
    con.executemany("INSERT INTO excl VALUES (?)", [(a,) for a in sorted(excluded)])
    date_col = "filing_date" if "filing_date" in cols else "filed_at"
    xbrl_expr = "is_xbrl" if "is_xbrl" in cols else "false"
    cik_col = "source_cik" if "source_cik" in cols else "cik"
    doc_col = "primary_document" if "primary_document" in cols else "primary_doc"
    period_expr = (
        f"CAST({period_col} AS VARCHAR)"
        if period_col
        else "CAST(year(CAST(" + date_col + " AS DATE)) AS VARCHAR)"
    )
    forms_sql = "(" + ", ".join("'%s'" % f for f in forms) + ")"
    sql = f"""
    WITH base AS (
        SELECT CASE WHEN length(replace(CAST(accession AS VARCHAR), '-', '')) = 18
                    THEN substr(replace(CAST(accession AS VARCHAR), '-', ''), 1, 10)
                         || '-' || substr(replace(CAST(accession AS VARCHAR), '-', ''), 11, 2)
                         || '-' || substr(replace(CAST(accession AS VARCHAR), '-', ''), 13, 6)
                    ELSE CAST(accession AS VARCHAR) END AS accession,
               CAST({cik_col} AS VARCHAR) AS cik,
               CAST(form AS VARCHAR) AS form,
               CAST({date_col} AS VARCHAR) AS filing_date,
               CAST({xbrl_expr} AS BOOLEAN) AS is_xbrl,
               CAST({doc_col} AS VARCHAR) AS primary_document,
               {period_expr} AS period_key,
               CASE WHEN year(CAST({date_col} AS DATE)) BETWEEN 2005 AND 2009
                         THEN 'pre2010'
                    WHEN year(CAST({date_col} AS DATE)) BETWEEN 2010 AND 2019
                         THEN 'y2010s'
                    WHEN year(CAST({date_col} AS DATE)) >= 2020
                         THEN 'ixbrl' END AS era
        FROM read_parquet('{targets}')
        WHERE form IN {forms_sql}
    ),
    eligible AS (
        SELECT * FROM base
        WHERE era IS NOT NULL
          AND accession NOT IN (SELECT accession FROM excl)
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY accession
            ORDER BY md5(accession || cik || '{SEED}')) = 1
    ),
    dedup AS (
        SELECT * FROM eligible
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY cik, period_key
            ORDER BY md5(accession || '{SEED}')) = 1
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY era ORDER BY md5(accession || '{SEED}')) AS rn
        FROM dedup
    )
    SELECT accession, cik, form, filing_date, is_xbrl,
           primary_document, era
    FROM ranked
    WHERE (era = 'pre2010' AND rn <= {quotas["pre2010"]})
       OR (era = 'y2010s' AND rn <= {quotas["y2010s"]})
       OR (era = 'ixbrl' AND rn <= {quotas["ixbrl"]})
    ORDER BY era, accession
    """
    rows = con.execute(sql).fetchall()
    drawn: dict[str, int] = {}
    ciks: set[str] = set()
    per_cik: dict[str, int] = {}
    for accession, cik, form, filing_date, is_xbrl, doc, era in rows:
        cik10 = (
            str(cik).lstrip("0").zfill(10) if str(cik).isdigit() else str(cik).zfill(10)
        )
        spec = {
            "accession": accession,
            "cik": cik10,
            "form": form,
            "filing_date": str(filing_date)[:10],
            "era": era,
            "is_xbrl": bool(is_xbrl),
            "filer_category": None,
            "population": population,
            "primary_document": doc,
            "labels": [],
            "source_geometry_count": None,
        }
        (specs_dir / f"{accession}.json").write_text(json.dumps(spec))
        drawn[era] = drawn.get(era, 0) + 1
        ciks.add(cik10)
        per_cik[cik10] = per_cik.get(cik10, 0) + 1
    summary = {
        "seed": SEED,
        "snapshot": "4fb77297c5ead34b",
        "quotas": quotas,
        "drawn": drawn,
        "drawn_total": sum(drawn.values()),
        "distinct_ciks": len(ciks),
        "max_filings_per_cik": max(per_cik.values()) if per_cik else 0,
        "excluded_total": len(excluded),
        "excluded_by_dir": per_dir,
        "period_column": period_col,
        "columns": cols,
    }
    (out_dir / "step6-draw-summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True)
    )
    print(json.dumps(summary, indent=1, sort_keys=True))
    ok = drawn == quotas
    print("QUOTAS EXACT" if ok else "QUOTA SHORTFALL — investigate")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
