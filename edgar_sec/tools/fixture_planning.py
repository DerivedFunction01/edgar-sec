"""Fixture-gathering plan generation: screens over the filing catalog.

A screen filters the catalog to a candidate population; the plan
samples, shards, and prices it before any network work runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import form_family
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.settings.sec import DEFAULT_RATE_LIMIT_RPS
from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list

REPO = Path(__file__).resolve().parents[2]
SEED_COHORT = REPO / "tests" / "fixtures" / "xbrl" / "seed_cohort.json"

# Only filings at or above this us-gaap fact count enter the registry;
# every scored row keeps its counts, so picks can re-threshold from the
# checkpoint files without re-gathering.
SUBSTANTIAL_US_GAAP_FLOOR = 200
SHARD_MAX_CANDIDATES = 400
YEAR_BANDS = ((2011, 2014), (2015, 2018), (2019, 2022), (2023, 2026))


@dataclass(frozen=True, slots=True)
class Screen:
    """One gathering screen: a catalog filter plus phrasing evidence.

    A null form set resolves to the amendment forms of the item's
    carrier families; require_xbrl keeps only XBRL-flagged filings.
    """

    name: str
    required_item: str
    phrasings: tuple[str, ...]
    year_start: int
    year_end: int
    forms: tuple[str, ...] | None = None
    require_xbrl: bool = False


SCREENS = {
    "8ka-901a": Screen(
        name="8ka-901a",
        required_item="9.01",
        phrasings=(
            "Item 9.01(a)",
            "Rule 3-05",
            "financial statements required by Item 9.01",
        ),
        year_start=2011,
        year_end=2026,
    ),
}


def _catalog_parts(catalog_dir: Path | None = None) -> list[Path]:
    """Parquet parts of the filing catalog, defaulting to the local snapshot.

    An explicit directory may hold parts directly, under parts/, or
    in the snapshot layout (*/parts/*.parquet).
    """
    if catalog_dir is not None:
        parts = (
            sorted(catalog_dir.glob("*.parquet"))
            or sorted(catalog_dir.glob("parts/*.parquet"))
            or sorted(catalog_dir.glob("*/parts/*.parquet"))
        )
        if not parts:
            raise FileNotFoundError(f"no catalog parquet parts under {catalog_dir}")
        return parts
    snapshots = resolve_paths().artifacts_root / "metadata" / "snapshots"
    parts = sorted(snapshots.glob("*/parts/*.parquet"))
    if not parts:
        raise FileNotFoundError(f"no catalog snapshot parts under {snapshots}")
    return parts


def _seed_ciks() -> set[str]:
    """Zero-padded CIKs of the 49-firm seed corpus."""
    rows = json.loads(SEED_COHORT.read_text(encoding="utf-8"))
    return {str(row["cik"]).zfill(10) for row in rows}


def _band_label(year: int) -> str:
    for start, end in YEAR_BANDS:
        if start <= year <= end:
            return f"{start}-{end}"
    return "out-of-range"


# XBRL-package presence measured 2026-11-01 per band on a mixed seed
# and non-seed sample of the flagged pool (17/17, 7/60, 60/60, 60/60);
# the record is .artifacts/run-logs/2026-11-01-xbrl-package-presence.md.
PACKAGE_PRESENCE_BY_BAND = {
    "2011-2014": 1.0,
    "2015-2018": 7 / 60,
    "2019-2022": 1.0,
    "2023-2026": 1.0,
}


def _population(
    screen: Screen, catalog_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Screen candidates from the catalog, ordered for deterministic shards.

    A screen naming forms keeps exactly those; otherwise the form set
    is the amendment forms of the item's carrier families.
    """
    parts = [str(p) for p in _catalog_parts(catalog_dir)]
    seeds = _seed_ciks()
    xbrl_clause = "AND f.is_xbrl" if screen.require_xbrl else ""
    sql = f"""
        SELECT cik, identity.name AS filer, f.accession_number AS accession,
               f.form AS form, f.filing_date AS filing_date,
               f.report_date AS period, f.is_xbrl AS is_xbrl,
               f.is_inline_xbrl AS is_inline_xbrl,
               f.primary_document AS primary_document,
               f.archive_url AS archive_url
        FROM (SELECT cik, identity, unnest(filings) AS f
              FROM read_parquet({sql_path_list(parts)}))
        WHERE list_contains(f.items, {sql_literal(screen.required_item)})
          AND year(f.filing_date::DATE) BETWEEN {screen.year_start}
              AND {screen.year_end}
          {xbrl_clause}
    """
    with connect() as con:
        rows = con.execute(sql).fetchall()
        cols = [d[0] for d in con.description]
    records = [dict(zip(cols, row, strict=True)) for row in rows]
    if screen.forms is not None:
        amendments = set(screen.forms)
    else:
        families = {form_family(record["form"]) for record in records}
        amendments = {f"{family}/A" for family in families}
    out = []
    for record in records:
        if record["form"] not in amendments:
            continue
        record["seed_filer"] = record["cik"] in seeds
        record["screen"] = screen.name
        out.append(record)
    out.sort(key=lambda r: (r["cik"], r["filing_date"]))
    return out


def _catalog_context(catalog_dir: Path | None = None) -> dict[str, Any]:
    """Whole-catalog totals, so a screen's cost is visible against all of it."""
    parts = [str(p) for p in _catalog_parts(catalog_dir)]
    flat = f"(SELECT unnest(filings) AS f FROM read_parquet({sql_path_list(parts)}))"
    with connect() as con:
        ciks = con.execute(
            f"SELECT count(*) FROM read_parquet({sql_path_list(parts)})"
        ).fetchone()[0]
        total, in_window, xbrl, first, last = con.execute(
            f"""SELECT count(*),
                  sum(CASE WHEN year(f.filing_date::DATE) BETWEEN 2011 AND 2026
                           THEN 1 ELSE 0 END),
                  sum(CASE WHEN year(f.filing_date::DATE) BETWEEN 2011 AND 2026
                           AND f.is_xbrl THEN 1 ELSE 0 END),
                  min(f.filing_date), max(f.filing_date)
                FROM {flat}"""
        ).fetchone()
    return {
        "ciks": ciks,
        "filings_total": total,
        "filings_2011_2026": in_window,
        "xbrl_filings_2011_2026": xbrl,
        "filing_date_min": first,
        "filing_date_max": last,
        "generic_xbrl_scoring_requests": 2 * xbrl,
        "generic_xbrl_scoring_hours_at_cap": round(
            2 * xbrl / DEFAULT_RATE_LIMIT_RPS / 3600, 1
        ),
    }


def _shards(screen: Screen, population: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shard the population by year band, then CIK-ordered candidate blocks."""
    by_band: dict[str, list[dict[str, Any]]] = {}
    for record in population:
        by_band.setdefault(_band_label(int(record["filing_date"][:4])), []).append(
            record
        )
    shards = []
    for band in sorted(by_band):
        rows = by_band[band]
        for index in range(0, len(rows), SHARD_MAX_CANDIDATES):
            block = rows[index : index + SHARD_MAX_CANDIDATES]
            xbrl = sum(1 for r in block if r["is_xbrl"])
            inline = sum(1 for r in block if r["is_inline_xbrl"])
            requests = len(block) + xbrl
            shards.append(
                {
                    "shard_id": f"{screen.name}/{band}/{index // SHARD_MAX_CANDIDATES:02d}",
                    "band": band,
                    "candidates": len(block),
                    "xbrl_flagged": xbrl,
                    "inline_flagged": inline,
                    "package_presence": PACKAGE_PRESENCE_BY_BAND[band],
                    "seed_candidates": sum(1 for r in block if r["seed_filer"]),
                    "estimated_requests": requests,
                    "estimated_seconds_at_cap": round(
                        requests / DEFAULT_RATE_LIMIT_RPS, 1
                    ),
                    "rows": block,
                }
            )
    return shards


def _sample(
    population: list[dict[str, Any]], sample_size: int | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """A deterministic even-stride sample spanning the ordered population."""
    if sample_size is None or sample_size >= len(population):
        return population, None
    if sample_size < 1:
        raise ValueError("sample_size must be a positive integer or null")
    stride = len(population) / sample_size
    taken = [population[int(i * stride)] for i in range(sample_size)]
    return taken, {
        "requested": sample_size,
        "population": len(population),
        "taken": len(taken),
    }


def build_plan(
    screen: Screen,
    *,
    sample_size: int | None = None,
    floor: int = SUBSTANTIAL_US_GAAP_FLOOR,
    prefer_seed: bool = True,
    catalog_dir: Path | None = None,
    acquisition: str = "index-free",
) -> dict[str, Any]:
    """The execution plan for one screen, generated from the catalog."""
    population = _population(screen, catalog_dir)
    planned, sample = _sample(population, sample_size)
    shards = _shards(screen, planned)
    return {
        "screen": {
            "name": screen.name,
            "forms": sorted({record["form"] for record in population}),
            "required_item": screen.required_item,
            "phrasings": list(screen.phrasings),
            "years": [screen.year_start, screen.year_end],
            "require_xbrl": screen.require_xbrl,
            "acquisition": acquisition,
        },
        "floor_us_gaap_facts": floor,
        "seed_filer_preference": prefer_seed,
        "sample": sample,
        "rate_cap_rps": DEFAULT_RATE_LIMIT_RPS,
        "catalog": _catalog_context(catalog_dir),
        "totals": {
            "population": len(population),
            "candidates": len(planned),
            "shards": len(shards),
            "estimated_requests": sum(s["estimated_requests"] for s in shards),
            "estimated_seconds_at_cap": round(
                sum(s["estimated_requests"] for s in shards) / DEFAULT_RATE_LIMIT_RPS,
                1,
            ),
        },
        "shards": shards,
    }


def _screen_from_plan(plan: dict[str, Any]) -> Screen:
    """The screen a plan was generated for, rebuilt from the plan itself."""
    block = plan["screen"]
    return Screen(
        name=block["name"],
        required_item=block["required_item"],
        phrasings=tuple(block["phrasings"]),
        year_start=block["years"][0],
        year_end=block["years"][1],
        require_xbrl=bool(block.get("require_xbrl", False)),
    )


def screen_from_config(entry: dict[str, Any]) -> Screen:
    """One config screen entry as a Screen; years default to 2011-2026."""
    if "name" not in entry or "required_item" not in entry:
        raise ValueError("each config screen needs a name and a required_item")
    years = entry.get("years") or [2011, 2026]
    forms = entry.get("forms")
    return Screen(
        name=entry["name"],
        required_item=entry["required_item"],
        phrasings=tuple(entry.get("phrasings") or ()),
        year_start=int(years[0]),
        year_end=int(years[1]),
        forms=tuple(forms) if forms else None,
        require_xbrl=bool(entry.get("require_xbrl", False)),
    )


__all__ = [
    "SCREENS",
    "SUBSTANTIAL_US_GAAP_FLOOR",
    "Screen",
    "build_plan",
    "screen_from_config",
]
