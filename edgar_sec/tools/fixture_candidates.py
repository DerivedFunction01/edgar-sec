"""Gather fixture candidates by scoring catalog filings for tagged content.

Plans shards from the filing catalog, scores each candidate's EX-101
payload by taxonomy, and writes a ranked candidate registry.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import form_family
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.runtime.settings.sec import DEFAULT_RATE_LIMIT_RPS
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list

REPO = Path(__file__).resolve().parents[2]
SEED_COHORT = REPO / "tests" / "fixtures" / "xbrl" / "seed_cohort.json"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# Only filings at or above this us-gaap fact count enter the registry;
# every scored row keeps its counts, so picks can re-threshold from the
# checkpoint files without re-gathering.
SUBSTANTIAL_US_GAAP_FLOOR = 200
SHARD_MAX_CANDIDATES = 400
YEAR_BANDS = ((2011, 2014), (2015, 2018), (2019, 2022), (2023, 2026))
_NON_FACT_PREFIXES = frozenset({"ix", "link", "xbrli", "xbrldi", "xlink", "xml", "xsi"})

_IX_FACT = re.compile(
    rb"<ix:non(?:Numeric|Fraction)\b([^>]*)>(.*?)</ix:non(?:Numeric|Fraction)>",
    re.DOTALL,
)
_IX_NAME = re.compile(rb'\bname="([^"]+)"')
_XML_FACT = re.compile(
    rb"<([A-Za-z][A-Za-z0-9_.-]*:[A-Za-z][A-Za-z0-9_.-]*)\b([^>]*)>(.*?)</\1>",
    re.DOTALL,
)
_IX_NIL = re.compile(rb"<ix:non(?:Numeric|Fraction)\b([^>]*)/>")
_XML_NIL = re.compile(rb"<([A-Za-z][A-Za-z0-9_.-]*:[A-Za-z][A-Za-z0-9_.-]*)\b([^>]*)/>")
_CONTEXT_REF = re.compile(rb'\bcontextRef="([^"]+)"')
_UNIT_REF = re.compile(rb'\bunitRef="([^"]+)"')
_DECIMALS = re.compile(rb'\bdecimals="([^"]+)"')
_INSTANCE_SUFFIXES = ("_lab.xml", "_pre.xml", "_cal.xml", "_def.xml")


@dataclass(frozen=True, slots=True)
class Screen:
    """One gathering screen: a catalog filter plus phrasing evidence.

    The form set is resolved from the catalog, never named here: the
    amendment forms of whichever families carry the required item.
    """

    name: str
    required_item: str
    phrasings: tuple[str, ...]
    year_start: int
    year_end: int


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


def _catalog_parts() -> list[Path]:
    """Parquet parts of the current metadata snapshot (the filing catalog)."""
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


def _population(screen: Screen) -> list[dict[str, Any]]:
    """Screen candidates from the catalog, ordered for deterministic shards.

    The form set is resolved from the item's carriers, never named here.
    """
    parts = [str(p) for p in _catalog_parts()]
    seeds = _seed_ciks()
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
    """
    with connect() as con:
        rows = con.execute(sql).fetchall()
        cols = [d[0] for d in con.description]
    records = [dict(zip(cols, row, strict=True)) for row in rows]
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


def _catalog_context() -> dict[str, Any]:
    """Whole-catalog totals, so a screen's cost is visible against all of it."""
    parts = [str(p) for p in _catalog_parts()]
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
            requests = len(block) + xbrl + inline
            shards.append(
                {
                    "shard_id": f"{screen.name}/{band}/{index // SHARD_MAX_CANDIDATES:02d}",
                    "band": band,
                    "candidates": len(block),
                    "xbrl_flagged": xbrl,
                    "inline_flagged": inline,
                    "seed_candidates": sum(1 for r in block if r["seed_filer"]),
                    "estimated_requests": requests,
                    "estimated_seconds_at_cap": round(
                        requests / DEFAULT_RATE_LIMIT_RPS, 1
                    ),
                    "rows": block,
                }
            )
    return shards


def build_plan(screen: Screen) -> dict[str, Any]:
    """The execution plan for one screen, generated from the catalog."""
    population = _population(screen)
    shards = _shards(screen, population)
    return {
        "screen": {
            "name": screen.name,
            "forms": sorted({record["form"] for record in population}),
            "required_item": screen.required_item,
            "phrasings": list(screen.phrasings),
            "years": [screen.year_start, screen.year_end],
        },
        "floor_us_gaap_facts": SUBSTANTIAL_US_GAAP_FLOOR,
        "rate_cap_rps": DEFAULT_RATE_LIMIT_RPS,
        "catalog": _catalog_context(),
        "totals": {
            "candidates": len(population),
            "shards": len(shards),
            "estimated_requests": sum(s["estimated_requests"] for s in shards),
            "estimated_seconds_at_cap": round(
                sum(s["estimated_requests"] for s in shards) / DEFAULT_RATE_LIMIT_RPS,
                1,
            ),
        },
        "shards": shards,
    }


def _fact_key(attrs: bytes, value: bytes) -> tuple[bytes, ...]:
    """Dedup identity of one fact: context, unit, decimals, and value."""

    def grab(pattern: re.Pattern[bytes]) -> bytes:
        match = pattern.search(attrs)
        return match.group(1) if match else b""

    return (grab(_CONTEXT_REF), grab(_UNIT_REF), grab(_DECIMALS), value.strip())


def count_facts(payload: bytes, *, inline: bool) -> dict[str, Any]:
    """Count distinct tagged facts by taxonomy prefix in one instance.

    A fact tagged identically in two documents of one filing is one
    fact; structural prefixes are not facts.
    """
    seen: set[tuple[bytes, ...]] = set()
    counts: dict[str, int] = {}
    if inline:
        inline_rows = [
            *_IX_FACT.findall(payload),
            *((attrs, b"") for attrs in _IX_NIL.findall(payload)),
        ]
        for attrs, value in inline_rows:
            name = _IX_NAME.search(attrs)
            if name is None:
                continue
            qname = name.group(1)
            key = (qname, *_fact_key(attrs, value))
            if key in seen:
                continue
            seen.add(key)
            prefix = qname.split(b":", 1)[0].decode("ascii", "replace")
            counts[prefix] = counts.get(prefix, 0) + 1
    else:
        xml_rows = [
            *_XML_FACT.findall(payload),
            *((qname, attrs, b"") for qname, attrs in _XML_NIL.findall(payload)),
        ]
        for qname, attrs, value in xml_rows:
            prefix = qname.split(b":", 1)[0].decode("ascii", "replace")
            if prefix in _NON_FACT_PREFIXES:
                continue
            key = (qname, *_fact_key(attrs, value))
            if key in seen:
                continue
            seen.add(key)
            counts[prefix] = counts.get(prefix, 0) + 1
    return {
        "total_facts": sum(counts.values()),
        "us_gaap_facts": counts.get("us-gaap", 0),
        "dei_facts": counts.get("dei", 0),
        "by_prefix": counts,
    }


_CLIENT: SecHttpClient | None = None


def _worker_init(workers: int) -> None:
    """Per-worker client; per-worker rate shares sum to the global cap."""
    global _CLIENT
    user_agent = get_env("SEC_USER_AGENT")
    if not user_agent:
        raise ValueError("SEC_USER_AGENT must be set in the process environment")
    limiter = RateLimiter(min_interval_s=workers / DEFAULT_RATE_LIMIT_RPS)
    _CLIENT = SecHttpClient(user_agent=user_agent, rate_limiter=limiter)


def _index_items(client: SecHttpClient, cik: str, accession: str) -> list[str]:
    """Filing-index file names for one accession (one request)."""
    nodash = accession.replace("-", "")
    payload = client.get_json(f"{ARCHIVES}/{int(cik)}/{nodash}/index.json")
    return [item["name"] for item in payload["directory"]["item"]]


def _instance_name(names: list[str], primary: str, *, inline: bool) -> str | None:
    """The instance document among a filing's index files, when present.

    For inline filings that is EDGAR's extracted instance, which
    aggregates every inline document in the filing, not just the cover.
    """
    if inline:
        stem = primary.rsplit(".", 1)[0]
        for suffix in ("_htm.xml", "_html.xml"):
            if stem + suffix in names:
                return stem + suffix
        return primary
    for name in names:
        lowered = name.lower()
        if lowered.endswith(".xml") and not lowered.endswith(_INSTANCE_SUFFIXES):
            return name
    return None


def _score_candidate(task: tuple[dict[str, Any], tuple[str, ...]]) -> dict[str, Any]:
    """Score one candidate: index fetch, instance fetch, fact counts."""
    record, phrasings = task
    row = {
        key: record[key]
        for key in (
            "cik",
            "filer",
            "accession",
            "form",
            "filing_date",
            "period",
            "seed_filer",
            "screen",
        )
    }
    row.update(
        {
            "ex101_present": False,
            "total_facts": None,
            "us_gaap_facts": None,
            "dei_facts": None,
            "phrasing_matches": [],
            "phrasing_checked": False,
            "error": None,
        }
    )
    if _CLIENT is None:
        row["error"] = "worker client not initialised"
        return row
    try:
        names = _index_items(_CLIENT, record["cik"], record["accession"])
        row["ex101_present"] = any(
            name.lower().endswith(".xsd") or "_lab.xml" in name.lower()
            for name in names
        )
        instance = _instance_name(
            names, record["primary_document"], inline=bool(record["is_inline_xbrl"])
        )
        if instance is None:
            return row
        nodash = record["accession"].replace("-", "")
        payload = _CLIENT.get_bytes(
            f"{ARCHIVES}/{int(record['cik'])}/{nodash}/{instance}"
        )
        extracted = instance != record["primary_document"]
        row.update(
            count_facts(
                payload, inline=bool(record["is_inline_xbrl"]) and not extracted
            )
        )
        text = None
        if extracted:
            text = _CLIENT.get_text(record["archive_url"])
        elif record["is_inline_xbrl"]:
            text = payload.decode("utf-8", "ignore")
        elif (row["us_gaap_facts"] or 0) >= SUBSTANTIAL_US_GAAP_FLOOR:
            text = _CLIENT.get_text(record["archive_url"])
        if text is not None:
            row["phrasing_checked"] = True
            row["phrasing_matches"] = [p for p in phrasings if p in text]
    except Exception as exc:  # noqa: BLE001 - a failed candidate is a row, not a stop
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def _checkpoint_path(work_dir: Path, shard_id: str) -> Path:
    return work_dir / "checkpoints" / (shard_id.replace("/", "__") + ".jsonl")


def _scored_accessions(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["accession"])
    return done


def run_shards(
    plan: dict[str, Any],
    *,
    work_dir: Path,
    registry_path: Path,
    workers: int,
    shard_ids: set[str] | None = None,
    accessions: set[str] | None = None,
) -> dict[str, Any]:
    """Score the plan's shards, checkpointing each shard as it completes."""
    screen = SCREENS[plan["screen"]["name"]]
    summary = {"shards_completed": 0, "candidates_scored": 0}
    for shard in plan["shards"]:
        if shard_ids is not None and shard["shard_id"] not in shard_ids:
            continue
        path = _checkpoint_path(work_dir, shard["shard_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        done = _scored_accessions(path)
        todo = [
            record
            for record in shard["rows"]
            if record["accession"] not in done
            and (accessions is None or record["accession"] in accessions)
        ]
        if todo:
            tasks = [(record, screen.phrasings) for record in todo]
            with (
                path.open("a", encoding="utf-8") as sink,
                ProcessPoolExecutor(
                    max_workers=workers, initializer=_worker_init, initargs=(workers,)
                ) as pool,
            ):
                for row in pool.map(_score_candidate, tasks):
                    sink.write(json.dumps(row) + "\n")
                    sink.flush()
                    summary["candidates_scored"] += 1
        summary["shards_completed"] += 1
        build_registry(work_dir, registry_path, screen_name=screen.name)
    return summary


def build_registry(
    work_dir: Path,
    out_path: Path,
    *,
    screen_name: str,
    floor: int = SUBSTANTIAL_US_GAAP_FLOOR,
) -> dict[str, Any]:
    """Merge checkpoints into the ranked registry of substantial candidates.

    Seed-filer candidates rank first; within a tier, higher us-gaap
    substance ranks first. Counts ride on every row for re-thresholding.
    """
    rows: dict[str, dict[str, Any]] = {}
    checkpoint_dir = work_dir / "checkpoints"
    if checkpoint_dir.is_dir():
        for path in sorted(checkpoint_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    rows[row["accession"]] = row
    substantial = [
        row
        for row in rows.values()
        if row.get("us_gaap_facts") is not None
        and row["us_gaap_facts"] >= floor
        and row["screen"] == screen_name
    ]
    substantial.sort(
        key=lambda r: (not r["seed_filer"], -r["us_gaap_facts"], r["filing_date"])
    )
    registry = {
        "screen": screen_name,
        "floor_us_gaap_facts": floor,
        "scored_candidates": len(rows),
        "candidates": [
            {
                key: row[key]
                for key in (
                    "cik",
                    "filer",
                    "accession",
                    "form",
                    "filing_date",
                    "period",
                    "seed_filer",
                    "screen",
                    "ex101_present",
                    "total_facts",
                    "us_gaap_facts",
                    "dei_facts",
                    "phrasing_matches",
                )
            }
            for row in substantial
        ],
    }
    atomic_write_json(out_path, registry)
    return registry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixture_candidates")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Generate the execution plan from the catalog.")
    plan.add_argument("--screen", choices=sorted(SCREENS), default="8ka-901a")
    plan.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run", help="Execute plan shards with checkpointing.")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--work-dir", type=Path, required=True)
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--workers", type=int, default=derive_resources().workers)
    run.add_argument("--shards", nargs="*", default=None)
    run.add_argument("--accessions", nargs="*", default=None)
    reg = sub.add_parser("registry", help="Rebuild the registry from checkpoints.")
    reg.add_argument("--screen", choices=sorted(SCREENS), default="8ka-901a")
    reg.add_argument("--work-dir", type=Path, required=True)
    reg.add_argument("--out", type=Path, required=True)
    reg.add_argument("--floor", type=int, default=SUBSTANTIAL_US_GAAP_FLOOR)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: plan from the catalog, run shards, rebuild registry."""
    args = _build_parser().parse_args(argv)
    started = time.time()
    if args.command == "plan":
        plan = build_plan(SCREENS[args.screen])
        atomic_write_json(args.out, plan)
        print(
            json.dumps(
                {
                    "screen": args.screen,
                    "candidates": plan["totals"]["candidates"],
                    "shards": plan["totals"]["shards"],
                    "estimated_requests": plan["totals"]["estimated_requests"],
                    "estimated_seconds_at_cap": plan["totals"][
                        "estimated_seconds_at_cap"
                    ],
                    "seconds": round(time.time() - started, 1),
                }
            )
        )
        return 0
    if args.command == "run":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        summary = run_shards(
            plan,
            work_dir=args.work_dir,
            registry_path=args.registry,
            workers=max(1, args.workers),
            shard_ids=set(args.shards) if args.shards else None,
            accessions=set(args.accessions) if args.accessions else None,
        )
        print(json.dumps({**summary, "seconds": round(time.time() - started, 1)}))
        return 0
    registry = build_registry(
        args.work_dir, args.out, screen_name=args.screen, floor=args.floor
    )
    print(
        json.dumps(
            {
                "screen": args.screen,
                "scored": registry["scored_candidates"],
                "substantial": len(registry["candidates"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
