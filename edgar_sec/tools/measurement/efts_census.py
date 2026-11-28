"""EFTS paced-draw census: year-sharded totals + stratified specimens.

The R1 census form as a measurement command: EFTS population totals
and pools by year shard, a first/middle/last sample per year, then a
paced specimen leg (cooldown, block probe, single size-scored fetch).
"""

from __future__ import annotations

import html as _html
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from edgar_sec.domain.sec_urls import archives_url, efts_search_url, index_json_url_for
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.measurement.config import load_config, workdir

HEADING_RE = re.compile(r"item\s+3\.?\s+legal\s+proceedings", re.I)
END_RES = tuple(
    re.compile(p, re.I)
    for p in (r"item\s+4\.?\s+", r"item\s+5\.?\s+", r"part\s+iii\b")
)
RAW_END_RES = tuple(
    re.compile(p) for p in (r"item\s+4", r"item\s+5", r"part\s+iii")
)
SPAN_RE = re.compile(r"legal\s+proceedings", re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
HREF_RE = re.compile(r'href="([^"]+\.html?)"', re.I)
STUB_OPENER_RE = re.compile(r"\s*(none|not applicable|n/a|omitted)\b")
XREF_RE = re.compile(
    r"(see|described in|set forth in|included in)"
    r"\s+(note|item\s+8|part\s+iii|the notes)"
)
SEGMENT_CAP_CHARS = 120_000
SPAN_CAP_CHARS = 3_000_000
SNIPPET_CHARS = 100
STUB_MAX_CHARS = 200
STUB_OPENER_MAX_CHARS = 450
XREF_MAX_CHARS = 1200


class ProbeExhausted(Exception):
    """The block probe never reached Archives inside its backoffs."""


class CensusClient(Protocol):
    """The transport seam: JSON and byte fetches by URL."""

    def get_json(self, url: str) -> dict[str, Any]:
        """Fetch one URL as parsed JSON."""
        ...

    def get_bytes(self, url: str) -> bytes:
        """Fetch one URL as raw bytes."""
        ...


@dataclass(frozen=True)
class CensusConfig:
    """One census step's parameters; pacing rides here, not literals."""

    phrase: str
    broad_phrase: str
    forms: tuple[str, ...]
    start_year: int
    end_year: int
    end_date: str
    prefix: str
    pool_size: int
    cooldown_s: float
    pace_s: float
    totals_pace_s: float
    probe_backoffs_s: tuple[float, ...]

    @classmethod
    def from_config(cls, config: dict) -> CensusConfig:
        """Build the typed config from the step's config JSON mapping."""
        return cls(
            phrase=config["phrase"],
            broad_phrase=config["broad_phrase"],
            forms=tuple(config["forms"]),
            start_year=int(config["start_year"]),
            end_year=int(config["end_year"]),
            end_date=config["end_date"],
            prefix=config["prefix"],
            pool_size=int(config["pool_size"]),
            cooldown_s=float(config["cooldown_s"]),
            pace_s=float(config["pace_s"]),
            totals_pace_s=float(config["totals_pace_s"]),
            probe_backoffs_s=tuple(
                float(s) for s in config["probe_backoffs_s"]
            ),
        )


def efts_url(
    phrase: str, form: str, startdt: str, enddt: str, offset: int, size: int
) -> str:
    """The EFTS search-index URL for one phrase/form/date-shard page."""
    params = {
        "q": f'"{phrase}"',
        "dateRange": "custom",
        "startdt": startdt,
        "enddt": enddt,
        "from": offset,
        "size": size,
        "forms": form,
    }
    return efts_search_url() + "?" + urlencode(params)


def _efts_total(
    client: CensusClient, phrase: str, form: str, startdt: str, enddt: str
) -> int | None:
    payload = client.get_json(efts_url(phrase, form, startdt, enddt, 0, 100))
    return (payload.get("hits", {}).get("total", {}) or {}).get("value")


def totals_leg(
    client: CensusClient,
    cfg: CensusConfig,
    sleep: Callable[[float], None],
) -> tuple[dict[int, list[int | None]], int | None]:
    """Year-sharded phrase totals per form, plus the broad-phrase total."""
    year_totals: dict[int, list[int | None]] = {}
    for year in range(cfg.start_year, cfg.end_year + 1):
        startdt, enddt = f"{year}-01-01", f"{year}-12-31"
        row: list[int | None] = []
        for form in cfg.forms:
            try:
                row.append(_efts_total(client, cfg.phrase, form, startdt, enddt))
            except Exception:
                row.append(None)
        year_totals[year] = row
        sleep(cfg.totals_pace_s)
    try:
        broad = _efts_total(
            client,
            cfg.broad_phrase,
            cfg.forms[0],
            f"{cfg.start_year}-01-01",
            cfg.end_date,
        )
    except Exception:
        broad = None
    return year_totals, broad


def pools_leg(
    client: CensusClient,
    cfg: CensusConfig,
    sleep: Callable[[float], None],
) -> dict[int, list[dict]]:
    """Per-year pools: the first pool page of hits per form, accession-sorted."""
    pool_by_year: dict[int, list[dict]] = {}
    for year in range(cfg.start_year, cfg.end_year + 1):
        startdt, enddt = f"{year}-01-01", f"{year}-12-31"
        accs: dict[str, dict] = {}
        for form in cfg.forms:
            try:
                payload = client.get_json(
                    efts_url(cfg.phrase, form, startdt, enddt, 0, cfg.pool_size)
                )
            except Exception:
                continue
            for hit in payload.get("hits", {}).get("hits", []):
                src = hit.get("_source") or {}
                accession = src.get("adsh")
                if accession and accession not in accs:
                    accs[accession] = {
                        "accession": accession,
                        "cik": str((src.get("ciks") or [""])[0]).lstrip("0")
                        or "0",
                        "form": src.get("form"),
                        "date": src.get("file_date"),
                    }
            sleep(cfg.totals_pace_s)
        pool_by_year[year] = sorted(accs.values(), key=lambda r: r["accession"])
    return pool_by_year


def draw_sample(pool_by_year: dict[int, list[dict]]) -> list[dict]:
    """The stratified sample: first, middle, and last accession per year."""
    sample: list[dict] = []
    for year, accs in pool_by_year.items():
        if not accs:
            continue
        idx = (
            [0, len(accs) // 2, len(accs) - 1]
            if len(accs) >= 3
            else list(range(len(accs)))
        )
        for i in sorted(set(idx)):
            record = dict(accs[i])
            record["pool_year"] = year
            sample.append(record)
    return sample


def strip_text(raw: str) -> str:
    """Document text with markup, scripts, and styles stripped out."""
    text = SCRIPT_STYLE_RE.sub(" ", raw)
    text = TAG_RE.sub("\n", text)
    return WS_RE.sub(" ", _html.unescape(text))


def classify_segment(segment: str) -> str:
    """The section disposition class for one extracted segment."""
    low = segment.lower()
    chars = len(segment)
    if chars < STUB_MAX_CHARS or (
        chars < STUB_OPENER_MAX_CHARS and STUB_OPENER_RE.match(low)
    ):
        return "none-or-na-stub"
    if "incorporated by reference" in low:
        return "incorporated-by-reference"
    if chars < XREF_MAX_CHARS and XREF_RE.search(low):
        return "cross-reference-short"
    return "substantive-prose"


def extract_segment(text: str) -> tuple[str, bool, int] | None:
    """The longest heading segment, its cap flag, and the heading count."""
    heads = [m.start() for m in HEADING_RE.finditer(text)]
    if not heads:
        return None
    best: tuple[str, bool] | None = None
    for hpos in heads:
        end = len(text)
        first = END_RES[0].search(text, hpos + 10)
        if first:
            end = first.start()
        else:
            for pattern in END_RES[1:]:
                match = pattern.search(text, hpos + 200)
                if match:
                    end = min(end, match.start())
        segment = text[hpos : min(end, hpos + SEGMENT_CAP_CHARS)]
        if best is None or len(segment) > len(best[0]):
            best = (segment, end - hpos > SEGMENT_CAP_CHARS)
    assert best is not None
    return best[0], best[1], len(heads)


def count_tables(raw: str) -> int:
    """Table tags in the raw span after the last heading-phrase match."""
    rawl = raw.lower()
    rheads = [m.start() for m in SPAN_RE.finditer(rawl)]
    if not rheads:
        return -1
    start = rheads[-1]
    mend = None
    for pattern in RAW_END_RES:
        match = pattern.search(rawl, start + 10)
        if match:
            mend = start + 10 + match.start()
            break
    span = rawl[start : mend if mend else start + SPAN_CAP_CHARS]
    return span.count("<table")


def list_docs(
    client: CensusClient, cik: str, accession: str
) -> list[tuple[str, int]]:
    """Candidate documents (name, size): index.json, else the listing page."""
    try:
        index = client.get_json(index_json_url_for(accession, cik))
        items = index.get("directory", {}).get("item", [])
        out: list[tuple[str, int]] = []
        for item in items:
            if item["name"].lower().endswith((".htm", ".html")):
                try:
                    size = int(item.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                out.append((item["name"], size))
        if out:
            return out
    except Exception:
        pass
    try:
        page = client.get_bytes(archives_url(cik, accession, "")).decode(
            "utf-8", "replace"
        )
        return [(name, 0) for name in sorted(set(HREF_RE.findall(page)))]
    except Exception:
        return []


def _doc_score(name_size: tuple[str, int]) -> float:
    name, size = name_size
    low = name.lower()
    score = size / 1e6
    if "10-k" in low or "10k" in low:
        score += 2
    if low.startswith("ex") or "-ex" in low or "_ex" in low:
        score -= 3
    return score


def measure_specimen(client: CensusClient, record: dict) -> dict:
    """One sampled filing's section measurement, or its error record."""
    line = {
        "accession": record["accession"],
        "cik": record["cik"],
        "form": record["form"],
        "date": record["date"],
        "pool_year": record["pool_year"],
    }
    try:
        candidates = list_docs(client, record["cik"], record["accession"])
        if not candidates:
            line["err"] = "no-doc-listing"
            return line
        doc = sorted(candidates, key=_doc_score, reverse=True)[0][0]
        raw = client.get_bytes(
            archives_url(record["cik"], record["accession"], doc)
        ).decode("utf-8", "replace")
        text = strip_text(raw)
        line["doc"] = doc
        line["doc_chars"] = len(text)
        found = extract_segment(text)
        if found is None:
            line["headings"] = 0
            line["class"] = "heading-not-found"
            line["chars"] = 0
            line["tables"] = 0
            return line
        segment, capped, headings = found
        line["headings"] = headings
        line["chars"] = len(segment)
        line["capped"] = capped
        line["tables"] = count_tables(raw)
        line["class"] = classify_segment(segment)
        line["snippet"] = segment[:SNIPPET_CHARS].replace("\n", " ")
    except Exception as exc:
        line["err"] = f"{type(exc).__name__}: {exc}"
    return line


def probe(
    client: CensusClient,
    cfg: CensusConfig,
    sample: list[dict],
    sleep: Callable[[float], None],
) -> bool:
    """Gate the specimen leg on one known Archives fetch, with backoff."""
    if not sample:
        return True
    record = sample[min(5, len(sample) - 1)]
    url = index_json_url_for(record["accession"], record["cik"])
    for wait_s in (0.0, *cfg.probe_backoffs_s):
        if wait_s:
            sleep(wait_s)
        try:
            client.get_bytes(url)
            return True
        except Exception:
            continue
    return False


def specimen_leg(
    client: CensusClient,
    cfg: CensusConfig,
    sample: list[dict],
    sleep: Callable[[float], None],
) -> list[dict]:
    """Cooldown, probe, then the paced measurement of every specimen."""
    sleep(cfg.cooldown_s)
    if not probe(client, cfg, sample, sleep):
        raise ProbeExhausted("archives probe exhausted its backoffs")
    results: list[dict] = []
    for record in sample:
        results.append(measure_specimen(client, record))
        sleep(cfg.pace_s)
    return results


def summarize(
    year_totals: dict[int, list[int | None]],
    broad: int | None,
    pool_by_year: dict[int, list[dict]],
    forms: tuple[str, ...],
    results: list[dict],
) -> dict:
    """The census summary in the R1 fires' recorded shape."""
    classes = Counter(r.get("class", "fetch-error") for r in results)
    substantive = sorted(
        r["chars"] for r in results if r.get("class") == "substantive-prose"
    )
    measured = [r for r in results if r.get("class")]
    return {
        "year_totals_q1": {
            str(year): row for year, row in year_totals.items()
        },
        "year_totals_q1_sums": {
            form: sum(
                row[i]
                for row in year_totals.values()
                if isinstance(row[i], int)
            )
            for i, form in enumerate(forms)
        },
        "broad_phrase_10k_total_capped": broad,
        "pool_sizes_by_year": {
            str(year): len(pool) for year, pool in pool_by_year.items()
        },
        "sample_n": len(results),
        "class_counts": dict(classes),
        "measured_n": len(measured),
        "table_bearing_sections": sum(
            1 for r in results if (r.get("tables") or 0) > 0
        ),
        "substantive_median_chars": (
            substantive[len(substantive) // 2] if substantive else None
        ),
        "substantive_minmax": (
            [substantive[0], substantive[-1]] if substantive else None
        ),
        "capped_segments": sum(1 for r in results if r.get("capped")),
        "fetch_errors": sum(1 for r in results if "err" in r),
    }


def run_census(
    client: CensusClient,
    cfg: CensusConfig,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Run all legs and return the summary plus the specimen records."""
    year_totals, broad = totals_leg(client, cfg, sleep)
    pool_by_year = pools_leg(client, cfg, sleep)
    sample = draw_sample(pool_by_year)
    results = specimen_leg(client, cfg, sample, sleep)
    summary = summarize(year_totals, broad, pool_by_year, cfg.forms, results)
    return {"summary": summary, "specimens": results, "sample": sample}


def main() -> int:
    """Command entry: --config step JSON, outputs under its workdir."""
    config = load_config()
    cfg = CensusConfig.from_config(config)
    out_dir = workdir(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = SecHttpClient()
    try:
        result = run_census(client, cfg)
    except ProbeExhausted:
        print("PROBE EXHAUSTED -- egress to Archives still blocked")
        return 3
    atomic_write_json(
        out_dir / f"{cfg.prefix}-efts-census-summary.json",
        result["summary"],
        canonical=False,
        indent=1,
    )
    atomic_write_json(
        out_dir / f"{cfg.prefix}-efts-census-specimens.json",
        result["specimens"],
        canonical=False,
        indent=1,
    )
    print(json.dumps(result["summary"], indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
