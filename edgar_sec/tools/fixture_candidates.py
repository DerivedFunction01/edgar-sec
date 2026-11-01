"""Gather fixture candidates by scoring catalog filings for tagged content.

A JSON config names the screens, sample size, and content floor; the
plan is generated from the filing catalog wherever the run executes.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edgar_sec.domain.sec_urls import archives_url, xbrl_package_url_for
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.runtime.settings.sec import DEFAULT_RATE_LIMIT_RPS
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.fixture_planning import (
    SCREENS,
    SUBSTANTIAL_US_GAAP_FLOOR,
    _screen_from_plan,
    build_plan,
    screen_from_config,
)

ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
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
_INSTANCE_SUFFIXES = ("_lab.xml", "_pre.xml", "_cal.xml", "_def.xml", "_ref.xml")


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
        if (
            lowered.endswith(".xml")
            and lowered != "filingsummary.xml"
            and not lowered.endswith(_INSTANCE_SUFFIXES)
        ):
            return name
    return None


def _score_via_index(
    client: SecHttpClient,
    record: dict[str, Any],
    row: dict[str, Any],
    phrasings: tuple[str, ...],
    floor: int,
) -> None:
    """Score via the filing index: index fetch, instance fetch, counts."""
    names = _index_items(client, record["cik"], record["accession"])
    row["source_path"] = "index"
    row["ex101_present"] = any(
        name.lower().endswith(".xsd") or "_lab.xml" in name.lower() for name in names
    )
    instance = _instance_name(
        names, record["primary_document"], inline=bool(record["is_inline_xbrl"])
    )
    if instance is None:
        return
    nodash = record["accession"].replace("-", "")
    payload = client.get_bytes(f"{ARCHIVES}/{int(record['cik'])}/{nodash}/{instance}")
    extracted = instance != record["primary_document"]
    row.update(
        count_facts(payload, inline=bool(record["is_inline_xbrl"]) and not extracted)
    )
    text = None
    if extracted:
        text = client.get_text(record["archive_url"])
    elif record["is_inline_xbrl"]:
        text = payload.decode("utf-8", "ignore")
    elif (row["us_gaap_facts"] or 0) >= floor:
        text = client.get_text(record["archive_url"])
    if text is not None:
        row["phrasing_checked"] = True
        row["phrasing_matches"] = [p for p in phrasings if p in text]


def _extracted_instance(
    client: SecHttpClient, record: dict[str, Any], row: dict[str, Any]
) -> bytes | None:
    """The filing's extracted instance, fetched by its constructed URL."""
    stem = record["primary_document"].rsplit(".", 1)[0]
    url = archives_url(int(record["cik"]), record["accession"], f"{stem}_htm.xml")
    try:
        payload = client.get_bytes(url)
    except PermanentHttpError as exc:
        if exc.status_code != 404:
            raise
        row["source_path"] = "absent"
        return None
    row["source_path"] = "extracted"
    row["ex101_present"] = True
    return payload


def _package_instance(
    client: SecHttpClient, record: dict[str, Any], row: dict[str, Any]
) -> bytes | None:
    """The filing's standalone instance, read from its generated package."""
    try:
        payload = client.get_bytes(
            xbrl_package_url_for(record["cik"], record["accession"])
        )
    except PermanentHttpError as exc:
        if exc.status_code != 404:
            raise
        row["source_path"] = "absent"
        return None
    row["source_path"] = "package"
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        members = {
            name.rsplit("/", 1)[-1]: name
            for name in package.namelist()
            if not name.endswith("/")
        }
        names = list(members)
        row["ex101_present"] = any(
            name.lower().endswith(".xsd") or "_lab.xml" in name.lower()
            for name in names
        )
        instance = _instance_name(names, record["primary_document"], inline=False)
        if instance is None:
            return None
        return package.read(members[instance])


def _score_index_free(
    client: SecHttpClient,
    record: dict[str, Any],
    row: dict[str, Any],
    phrasings: tuple[str, ...],
) -> None:
    """Score index-free: the constructed extraction for inline filings,
    the generated package for classic ones; a 404 on either vehicle
    scores the candidate as no-instance, marked absent.
    """
    if record["is_inline_xbrl"]:
        payload = _extracted_instance(client, record, row)
    else:
        payload = _package_instance(client, record, row)
    if payload is None:
        return
    row.update(count_facts(payload, inline=False))
    text = client.get_text(record["archive_url"])
    row["phrasing_checked"] = True
    row["phrasing_matches"] = [p for p in phrasings if p in text]


def _score_candidate(
    task: tuple[dict[str, Any], tuple[str, ...], int, str],
) -> dict[str, Any]:
    """Score one candidate via the run's acquisition path."""
    record, phrasings, floor, acquisition = task
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
            "source_path": None,
            "error": None,
        }
    )
    if _CLIENT is None:
        row["error"] = "worker client not initialised"
        return row
    try:
        if acquisition == "index":
            _score_via_index(_CLIENT, record, row, phrasings, floor)
        else:
            _score_index_free(_CLIENT, record, row, phrasings)
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
    acquisition: str = "index-free",
) -> dict[str, Any]:
    """Score the plan's shards, checkpointing each shard as it completes."""
    screen = _screen_from_plan(plan)
    floor = plan.get("floor_us_gaap_facts", SUBSTANTIAL_US_GAAP_FLOOR)
    prefer_seed = plan.get("seed_filer_preference", True)
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
            tasks = [(record, screen.phrasings, floor, acquisition) for record in todo]
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
        build_registry(
            work_dir,
            registry_path,
            screen_name=screen.name,
            floor=floor,
            prefer_seed=prefer_seed,
        )
    return summary


def build_registry(
    work_dir: Path,
    out_path: Path,
    *,
    screen_name: str,
    floor: int = SUBSTANTIAL_US_GAAP_FLOOR,
    prefer_seed: bool = True,
) -> dict[str, Any]:
    """Merge checkpoints into the ranked registry of substantial candidates.

    With seed preference, seed-filer candidates rank first; within a
    tier, higher us-gaap substance ranks first. Counts ride on rows.
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
    if prefer_seed:
        substantial.sort(
            key=lambda r: (not r["seed_filer"], -r["us_gaap_facts"], r["filing_date"])
        )
    else:
        substantial.sort(key=lambda r: (-r["us_gaap_facts"], r["filing_date"]))
    registry = {
        "screen": screen_name,
        "floor_us_gaap_facts": floor,
        "seed_filer_preference": prefer_seed,
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


def load_config(path: Path) -> dict[str, Any]:
    """Load and normalize the gathering config JSON, filling defaults."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    screens = raw.get("screens")
    if not screens:
        raise ValueError("config needs a non-empty screens list")
    for entry in screens:
        screen_from_config(entry)
    outputs = {
        "plan": "gathering-plan-{screen}.json",
        "registry": "fixture-candidates-{screen}.json",
    }
    outputs.update(raw.get("outputs") or {})
    acquisition = raw.get("acquisition", "index-free")
    if acquisition not in ("index-free", "index"):
        raise ValueError(f"acquisition must be package or index: {acquisition!r}")
    return {
        "screens": screens,
        "sample_size": raw.get("sample_size"),
        "floor_us_gaap_facts": raw.get(
            "floor_us_gaap_facts", SUBSTANTIAL_US_GAAP_FLOOR
        ),
        "seed_filer_preference": raw.get("seed_filer_preference", True),
        "acquisition": acquisition,
        "outputs": outputs,
    }


def gather(
    config: dict[str, Any],
    *,
    work_dir: Path,
    out_dir: Path,
    catalog_dir: Path | None = None,
    workers: int,
) -> dict[str, Any]:
    """Run a whole config: plan each screen on the local catalog, then score.

    The plan is generated here, where the run executes, from the
    catalog beside it; only the config travels to the run.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for entry in config["screens"]:
        screen = screen_from_config(entry)
        plan = build_plan(
            screen,
            sample_size=config["sample_size"],
            floor=config["floor_us_gaap_facts"],
            prefer_seed=config["seed_filer_preference"],
            catalog_dir=catalog_dir,
            acquisition=config["acquisition"],
        )
        plan_path = out_dir / config["outputs"]["plan"].replace("{screen}", screen.name)
        atomic_write_json(plan_path, plan)
        registry_path = out_dir / config["outputs"]["registry"].replace(
            "{screen}", screen.name
        )
        summary = run_shards(
            plan,
            work_dir=work_dir,
            registry_path=registry_path,
            workers=workers,
            acquisition=config["acquisition"],
        )
        results[screen.name] = {**summary, "totals": plan["totals"]}
    return results


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
    run.add_argument("--acquisition", choices=("index-free", "index"), default=None)
    reg = sub.add_parser("registry", help="Rebuild the registry from checkpoints.")
    reg.add_argument("--screen", choices=sorted(SCREENS), default="8ka-901a")
    reg.add_argument("--work-dir", type=Path, required=True)
    reg.add_argument("--out", type=Path, required=True)
    reg.add_argument("--floor", type=int, default=SUBSTANTIAL_US_GAAP_FLOOR)
    gat = sub.add_parser("gather", help="Plan and score every screen in a config JSON.")
    gat.add_argument("--config", type=Path, required=True)
    gat.add_argument("--work-dir", type=Path, required=True)
    gat.add_argument("--out-dir", type=Path, required=True)
    gat.add_argument("--catalog-dir", type=Path, default=None)
    gat.add_argument("--workers", type=int, default=derive_resources().workers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: plan, run, registry, and the config-driven gather."""
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
            acquisition=args.acquisition
            or plan.get("screen", {}).get("acquisition", "index-free"),
        )
        print(json.dumps({**summary, "seconds": round(time.time() - started, 1)}))
        return 0
    if args.command == "gather":
        results = gather(
            load_config(args.config),
            work_dir=args.work_dir,
            out_dir=args.out_dir,
            catalog_dir=args.catalog_dir,
            workers=max(1, args.workers),
        )
        print(
            json.dumps({"screens": results, "seconds": round(time.time() - started, 1)})
        )
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
