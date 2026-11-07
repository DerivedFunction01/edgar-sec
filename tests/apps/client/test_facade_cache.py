"""Tests pinning the bounded LRU facade cache and its capacity derivation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from edgar_sec.apps.client.facade import (
    Edgar,
    FacadeCache,
    derive_content_cache_budget,
    derive_content_disk_budget,
    derive_facade_capacity,
)
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
from edgar_sec.engine.xbrl.storage.storage import (
    declarations_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.foundation.runtime.resources import MEBIBYTE, RuntimeResourceProfile
from tests.engine.xbrl.solve.conftest import load_seed_cohort

_FIRMS = ("MSFT", "AAPL", "JPM")


def _profile(worker_memory_mib: int) -> RuntimeResourceProfile:
    return RuntimeResourceProfile(
        cpu_cores=2,
        workers=1,
        threads=1,
        memory_limit="512MiB",
        temp_directory="/tmp",
        available_memory_bytes=worker_memory_mib * 1024 * 1024,
        worker_memory_mib=worker_memory_mib,
        worker_memory_safety=0.9,
    )


def test_capacity_derives_from_the_worker_memory_share() -> None:
    """Verify capacity is the worker share divided by per-facade retained bytes."""
    assert derive_facade_capacity(_profile(512)) == 74
    assert derive_facade_capacity(_profile(1024)) > derive_facade_capacity(
        _profile(512)
    )
    assert derive_facade_capacity(_profile(4)) == 1


def test_capacity_must_be_positive() -> None:
    """Verify a zero capacity is refused rather than silently unbounded."""
    with pytest.raises(ValueError):
        FacadeCache(capacity=0)


def test_hit_returns_the_identical_facade() -> None:
    """Verify a hit returns the same object and never rebuilds."""
    cache = FacadeCache(capacity=2)
    builds: list[object] = []

    def builder() -> object:
        facade = object()
        builds.append(facade)
        return facade

    key = ("0000320193", "0000320193-23-000106")
    first = cache.get_or_build(key, builder)
    assert cache.get_or_build(key, builder) is first
    assert builds == [first]


def test_eviction_drops_the_least_recently_used() -> None:
    """Verify touching a key protects it; the untouched elder is dropped whole."""
    cache = FacadeCache(capacity=2)
    first = cache.get_or_build(("1", "a"), object)
    elder = cache.get_or_build(("1", "b"), object)
    assert cache.get_or_build(("1", "a"), object) is first
    newest = cache.get_or_build(("1", "c"), object)
    assert ("1", "b") not in cache
    assert cache.get_or_build(("1", "a"), object) is first
    assert cache.get_or_build(("1", "c"), object) is newest
    assert len(cache) == 2
    assert cache.get_or_build(("1", "b"), object) is not elder


def test_concurrent_miss_builds_once() -> None:
    """Verify racing builders for one key construct a single facade."""
    cache = FacadeCache(capacity=4)
    builds: list[object] = []

    def builder() -> object:
        time.sleep(0.05)
        facade = object()
        builds.append(facade)
        return facade

    results: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(cache.get_or_build(("1", "a"), builder))
        )
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(builds) == 1
    assert all(result is builds[0] for result in results)


def test_unrelated_key_builds_do_not_convoy() -> None:
    """Verify one key's slow build does not block another key's build."""
    cache = FacadeCache(capacity=4)
    started = threading.Event()
    release = threading.Event()

    def slow_builder() -> object:
        started.set()
        release.wait(timeout=5)
        return object()

    results: list[object] = []
    thread = threading.Thread(
        target=lambda: results.append(cache.get_or_build(("1", "a"), slow_builder))
    )
    thread.start()
    assert started.wait(timeout=5)
    before = time.monotonic()
    other = cache.get_or_build(("1", "b"), object)
    assert time.monotonic() - before < 2
    assert other is not None
    release.set()
    thread.join(timeout=5)
    assert len(results) == 1


def _aggregate(accession: str, cik: int = 320193) -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=Cik(cik),
        ciks=(Cik(cik),),
        form="10-K",
        filing_date="2024-11-01",
    )


def _stub_parse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    parses: list[str] = []

    def fake_parse(filing: FilingAggregate) -> FilingXbrl:
        parses.append(filing.accession.value)
        return FilingXbrl(
            accession=filing.accession,
            cik=filing.primary_cik,
            facts=(),
            linkbases=LinkbaseBundle(),
        )

    monkeypatch.setattr(
        "edgar_sec.engine.xbrl.parsing.filing_parser.parse_filing_xbrl", fake_parse
    )
    return parses


def test_edgar_xbrl_revisit_is_a_cache_hit(monkeypatch, tmp_path) -> None:
    """Verify Edgar.xbrl parses once per (cik, accession) and reuses the object."""
    parses = _stub_parse(monkeypatch)
    edgar = Edgar(artifacts_root=tmp_path)
    first = edgar.xbrl(_aggregate("0000320193-24-000123"))
    assert edgar.xbrl(_aggregate("0000320193-24-000123")) is first
    assert parses == ["0000320193-24-000123"]
    assert edgar.xbrl(_aggregate("0000320193-24-000124")) is not first
    assert len(edgar.facade_cache) == 2


def test_edgar_xbrl_capacity_one_evicts(monkeypatch, tmp_path) -> None:
    """Verify a capacity-1 Edgar drops the prior facade, which then re-parses."""
    parses = _stub_parse(monkeypatch)
    edgar = Edgar(artifacts_root=tmp_path, facade_capacity=1)
    first = edgar.xbrl(_aggregate("0000320193-24-000123"))
    edgar.xbrl(_aggregate("0000320193-24-000124"))
    assert len(edgar.facade_cache) == 1
    assert edgar.xbrl(_aggregate("0000320193-24-000123")) is not first
    assert parses.count("0000320193-24-000123") == 2


@pytest.fixture(scope="module")
def cohort() -> tuple:
    """Concept table over three seed filings, as the cohort tests build."""
    taxonomy = load_domain_taxonomy()
    entries = tuple(e for e in load_seed_cohort() if e.firm in _FIRMS)
    merged: dict[str, object] = {}
    for entry in entries:
        path = entry.facts_path.parent / "declarations.parquet"
        if path.exists():
            for decl in declarations_from_arrow_table(read_declarations_parquet(path)):
                merged[decl.concept_qname] = decl
    table = build_cohort_table(taxonomy, entries, declarations=tuple(merged.values()))
    return taxonomy, entries, table


def test_cache_holds_real_facades_by_key(cohort) -> None:
    """Verify real cohort facades hit identically and evict by key."""
    _taxonomy, entries, table = cohort
    by_firm = {entry.firm: entry for entry in entries}
    cache = FacadeCache(capacity=2)

    def build(firm: str) -> Xbrl:
        entry = by_firm[firm]
        return Xbrl.from_cohort(table, entries, entry.accession)

    keys = {firm: (firm, by_firm[firm].accession) for firm in _FIRMS}
    msft = cache.get_or_build(keys["MSFT"], lambda: build("MSFT"))
    aapl = cache.get_or_build(keys["AAPL"], lambda: build("AAPL"))
    assert cache.get_or_build(keys["MSFT"], lambda: build("MSFT")) is msft
    jpm = cache.get_or_build(keys["JPM"], lambda: build("JPM"))
    assert keys["AAPL"] not in cache
    assert cache.get_or_build(keys["MSFT"], lambda: build("MSFT")) is msft
    assert cache.get_or_build(keys["AAPL"], lambda: build("AAPL")) is not aapl
    cached_hits = [
        (hit.qname, hit.tier, hit.rule) for hit in jpm.search("revenue").hits
    ]
    fresh_hits = [
        (hit.qname, hit.tier, hit.rule) for hit in build("JPM").search("revenue").hits
    ]
    assert cached_hits == fresh_hits


def test_content_cache_budget_derives_from_the_worker_memory_share() -> None:
    """Verify the content budget is the settings fraction of one worker share."""
    assert derive_content_cache_budget(_profile(512)) == 512 * MEBIBYTE // 4
    assert derive_content_cache_budget(_profile(1024)) == 2 * (512 * MEBIBYTE // 4)
    assert derive_content_cache_budget(_profile(1024)) > derive_content_cache_budget(
        _profile(128)
    )


def _sample_filing(tmp_path: Path) -> FilingAggregate:
    text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "The business overview.\n"
        "ITEM 1A. RISK FACTORS\n"
        "General risks.\n"
        "PART II\n"
        "ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA\n"
        "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS\n"
        "Note 1. Summary of Significant Accounting Policies\n"
        "Accounting details.\n"
        "Note 2. Revenue Recognition\n"
        "Revenue details.\n"
    )
    path = tmp_path / "10k_primary.txt"
    path.write_text(text, encoding="utf-8")
    cik = Cik.from_raw(320193)
    return FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=cik,
        ciks=(cik,),
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        primary_document_path="10k_primary.txt",
        primary_storage_path=path,
    )


def _count_detections(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from edgar_sec.engine.forms.sections.items import detector

    real = detector.detect_section_sequence
    calls: list[int] = []

    def counting(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(detector, "detect_section_sequence", counting)
    return calls


def test_edgar_sections_and_notes_revisits_are_content_cache_hits(
    monkeypatch, tmp_path
) -> None:
    """Verify revisits return the identical sequence and detect only once."""
    calls = _count_detections(monkeypatch)
    edgar = Edgar(artifacts_root=tmp_path)
    filing = _sample_filing(tmp_path)
    first = edgar.sections(filing)
    assert len(first.sections) > 0
    assert edgar.sections(filing) is first
    assert len(calls) == 1
    notes = edgar.notes(filing)
    assert len(notes.notes) == 2
    assert edgar.notes(filing) is notes
    stats = edgar.content_cache.stats()
    assert stats["ram"]["current_bytes"] > 0
    assert stats["ram"]["budget_bytes"] == derive_content_cache_budget()


def test_edgar_tiny_ram_budget_serves_sequences_from_disk(
    monkeypatch, tmp_path
) -> None:
    """Verify RAM-refused derivations are re-served from disk, not recomputed."""
    calls = _count_detections(monkeypatch)
    edgar = Edgar(artifacts_root=tmp_path, content_cache_budget=64)
    filing = _sample_filing(tmp_path)
    first = edgar.sections(filing)
    second = edgar.sections(filing)
    assert first == second
    assert len(first.sections) > 0
    assert len(calls) == 1
    assert len(edgar.content_cache) == 0
    stats = edgar.content_cache.stats()
    assert stats["ram"]["bypassed_oversize"] >= 1
    assert stats["disk"]["entries"] >= 1
    assert stats["disk"]["hits"] >= 1


def test_edgar_clear_cache_empties_the_content_cache(tmp_path) -> None:
    """Verify clear_cache drops retained text and sequences with the rest."""
    edgar = Edgar(artifacts_root=tmp_path)
    edgar.sections(_sample_filing(tmp_path))
    assert len(edgar.content_cache) >= 1
    edgar.clear_cache(scope="documents")
    assert len(edgar.content_cache) == 0
    spilled = Edgar(artifacts_root=tmp_path, content_cache_budget=64)
    spilled.sections(_sample_filing(tmp_path))
    assert spilled.content_cache.stats()["disk"]["entries"] >= 1
    spilled.clear_cache(scope="documents")
    assert spilled.content_cache.stats()["disk"]["entries"] == 0


def test_cache_stats_extends_response_stats_with_the_content_cache(
    tmp_path,
) -> None:
    """Verify the response stats keep their shape and gain a content block."""
    from edgar_sec.infra.sec_http.client import SecHttpClient

    edgar = Edgar(
        artifacts_root=tmp_path,
        sec_client=SecHttpClient(cache_dir=tmp_path / "http_cache"),
    )
    stats = edgar.cache_stats()
    assert stats is not None
    assert stats["content_cache"]["ram"]["budget_bytes"] == (
        derive_content_cache_budget()
    )
    assert stats["content_cache"]["ram"]["current_bytes"] == 0
    assert stats["content_cache"]["disk"]["budget_bytes"] == (
        derive_content_disk_budget()
    )
    edgar.sections(_sample_filing(tmp_path))
    stats = edgar.cache_stats()
    assert stats is not None
    assert stats["content_cache"]["ram"]["current_bytes"] > 0
