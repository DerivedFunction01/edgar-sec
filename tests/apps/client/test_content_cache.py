"""Tests pinning the byte-bounded content cache: accounting, eviction, admission."""

from __future__ import annotations

import threading
import time

import pytest

from edgar_sec.apps.client.content_cache import ContentCache, estimate_retained_bytes
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)


def _build(value: object, weight: int):
    return lambda: (value, weight)


def test_budget_must_be_positive() -> None:
    """Verify a zero budget is refused rather than silently unbounded."""
    with pytest.raises(ValueError):
        ContentCache(0)
    with pytest.raises(ValueError):
        ContentCache(100, max_item_fraction=0)
    with pytest.raises(ValueError):
        ContentCache(100, text_share=1.5)


def test_byte_accounting_and_stats() -> None:
    """Verify admitted weights sum exactly into the reported byte counters."""
    cache = ContentCache(2_000)
    assert cache.get_or_build(("sections", "a"), _build("A", 300)) == "A"
    assert cache.get_or_build(("notes", "a"), _build("N", 200)) == "N"
    stats = cache.stats()["ram"]
    assert stats["current_bytes"] == 500
    assert stats["entries"] == 2
    assert stats["budget_bytes"] == 2_000
    assert stats["misses"] == 2
    assert cache.get(("sections", "a")) == "A"
    assert cache.get(("sections", "missing")) is None
    stats = cache.stats()["ram"]
    assert stats["hits"] == 1
    assert stats["misses"] == 3


def test_lru_eviction_order_across_kinds() -> None:
    """Verify the least recently used entry goes first, whatever its kind."""
    cache = ContentCache(300)
    for acc in ("a", "b", "c"):
        cache.get_or_build(("sections", acc), _build(acc.upper(), 75))
    assert cache.get(("sections", "a")) == "A"
    cache.get_or_build(("notes", "d"), _build("D", 75))
    cache.get_or_build(("notes", "e"), _build("E", 75))
    assert ("sections", "b") not in cache
    assert ("sections", "a") in cache
    assert ("sections", "c") in cache
    assert ("notes", "d") in cache
    assert ("notes", "e") in cache
    assert cache.stats()["ram"]["evictions"] == 1
    assert cache.stats()["ram"]["current_bytes"] == 300


def test_oversize_item_is_served_but_never_retained() -> None:
    """Verify an entry over the admission cap bypasses instead of flushing."""
    cache = ContentCache(400)
    cache.get_or_build(("sections", "small"), _build("S", 100))
    big = cache.get_or_build(("sections", "big"), _build("B", 101))
    assert big == "B"
    assert ("sections", "big") not in cache
    assert ("sections", "small") in cache
    assert cache.stats()["ram"]["bypassed_oversize"] == 1
    assert cache.stats()["ram"]["current_bytes"] == 100


def test_nonpositive_weight_is_never_retained() -> None:
    """Verify weightless builds (empty text, empty body) leave no entry."""
    cache = ContentCache(400)
    assert cache.get_or_build(("text", "a"), _build("", 0)) == ""
    assert len(cache) == 0
    assert cache.stats()["ram"]["bypassed_oversize"] == 0


def test_hit_never_rebuilds_or_reweighs() -> None:
    """Verify a hit returns the first build and keeps its original weight."""
    cache = ContentCache(400)
    assert cache.get_or_build(("text", "a"), _build("x", 40)) == "x"
    assert cache.get_or_build(("text", "a"), _build("y", 99)) == "x"
    assert cache.stats()["ram"]["text_bytes"] == 40
    assert cache.stats()["ram"]["current_bytes"] == 40
    assert len(cache) == 1


def test_concurrent_miss_builds_once() -> None:
    """Verify racing builders for one key derive a single value."""
    cache = ContentCache(10_000)
    builds: list[object] = []

    def builder() -> tuple[object, int]:
        time.sleep(0.05)
        value = object()
        builds.append(value)
        return value, 10

    results: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                cache.get_or_build(("sections", "a"), builder)
            )
        )
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(builds) == 1
    assert all(result is builds[0] for result in results)


def test_text_share_caps_text_and_protects_parsed_entries() -> None:
    """Verify text stays within its share and never flushes parsed entries."""
    cache = ContentCache(800, text_share=0.125)
    cache.get_or_build(("sections", "a"), _build("S", 200))
    cache.get_or_build(("text", "a"), _build("ta", 60))
    cache.get_or_build(("text", "b"), _build("tb", 60))
    assert cache.stats()["ram"]["text_bytes"] == 60
    assert ("text", "a") not in cache
    assert ("sections", "a") in cache
    assert cache.get_or_build(("text", "c"), _build("tc", 150)) == "tc"
    assert ("text", "c") not in cache
    assert cache.stats()["ram"]["bypassed_oversize"] == 1


def test_text_yields_when_parsed_entries_fill_the_budget() -> None:
    """Verify text is refused, not parked over parsed entries, at a full budget."""
    cache = ContentCache(200, text_share=0.5)
    cache.get_or_build(("sections", "a"), _build("S", 50))
    cache.get_or_build(("sections", "b"), _build("T", 50))
    cache.get_or_build(("notes", "a"), _build("N", 50))
    cache.get_or_build(("notes", "b"), _build("M", 40))
    assert cache.get_or_build(("text", "a"), _build("ta", 50)) == "ta"
    assert ("text", "a") not in cache
    assert cache.stats()["ram"]["current_bytes"] == 190
    assert len(cache) == 4


def test_clear_resets_entries_and_counters() -> None:
    """Verify clear drops every entry and zeroes the statistics."""
    cache = ContentCache(400)
    cache.get_or_build(("sections", "a"), _build("S", 100))
    cache.get(("sections", "a"))
    cache.clear()
    assert len(cache) == 0
    stats = cache.stats()["ram"]
    assert stats["current_bytes"] == 0
    assert stats["hits"] == 0
    assert stats["entries"] == 0


def _sequence(section_count: int) -> SectionSequence:
    sections = tuple(
        ResolvedSection(
            item_identifier=f"ITEM {index}",
            start_line=index * 10,
            end_line=index * 10 + 5,
            title=f"Title {index}",
            raw_heading=f"ITEM {index}. TITLE {index}",
            kind=CandidateKind.STANDARD,
            confidence=1.0,
        )
        for index in range(section_count)
    )
    return SectionSequence(sections=sections, family="10-K")


def test_estimate_grows_with_sequence_size() -> None:
    """Verify the estimator is positive, deterministic, and size-sensitive."""
    small = estimate_retained_bytes(_sequence(2))
    large = estimate_retained_bytes(_sequence(20))
    assert 0 < small < large
    assert estimate_retained_bytes(_sequence(2)) == small


def test_estimate_counts_shared_nodes_once() -> None:
    """Verify objects referenced twice (index cache and tuple) are weighed once."""
    note = ResolvedNote(
        note_number=1,
        note_label="1",
        start_line=0,
        end_line=5,
        title="Policies",
        raw_heading="Note 1. Policies",
        confidence=1.0,
    )
    seq = NotesSequence(notes=(note,))
    assert estimate_retained_bytes(seq) < 2 * estimate_retained_bytes(note) + 200


def _str_codecs() -> dict:
    return {
        "sections": (
            lambda v: v.encode("utf-8"),
            lambda b: b.decode("utf-8"),
            lambda v: "src",
        )
    }


def test_stats_report_no_disk_tier_when_unconfigured() -> None:
    """Verify a RAM-only cache reports a null disk block."""
    assert ContentCache(400).stats()["disk"] is None


def test_oversize_item_spills_to_disk_and_reserves_without_recompute(
    tmp_path: Path,
) -> None:
    """Verify a RAM-refused derivation is disk-resident and never rebuilt."""
    cache = ContentCache(
        400,
        disk_dir=tmp_path / "disk",
        disk_budget_bytes=100_000,
        codecs=_str_codecs(),
    )
    builds: list[int] = []

    def builder() -> tuple[str, int]:
        builds.append(1)
        return "x" * 300, 300

    assert cache.get_or_build(("sections", "a"), builder) == "x" * 300
    assert len(cache) == 0
    assert cache.stats()["disk"]["entries"] == 1
    assert cache.get_or_build(("sections", "a"), builder) == "x" * 300
    assert len(builds) == 1
    assert len(cache) == 0
    assert cache.stats()["disk"]["hits"] == 1


def test_ram_eviction_falls_back_to_disk_not_recompute(tmp_path: Path) -> None:
    """Verify an evicted derivation is re-served from disk, builder untouched."""
    cache = ContentCache(
        300,
        disk_dir=tmp_path / "disk",
        disk_budget_bytes=100_000,
        codecs=_str_codecs(),
    )
    builds: dict[str, int] = {}

    def make(acc: str):
        def builder() -> tuple[str, int]:
            builds[acc] = builds.get(acc, 0) + 1
            return acc.upper() * 25, 75

        return builder

    for acc in ("a", "b", "c", "d"):
        cache.get_or_build(("sections", acc), make(acc))
    cache.get_or_build(("sections", "e"), make("e"))
    assert ("sections", "a") not in cache
    assert cache.stats()["disk"]["entries"] >= 1
    assert cache.get_or_build(("sections", "a"), make("a")) == "A" * 25
    assert builds["a"] == 1
    assert cache.stats()["disk"]["hits"] >= 1


def test_disk_tier_evicts_coldest_under_its_own_budget(tmp_path: Path) -> None:
    """Verify disk LRU eviction keeps the tier within its byte budget."""
    cache = ContentCache(
        400,
        disk_dir=tmp_path / "disk",
        disk_budget_bytes=250,
        codecs=_str_codecs(),
    )
    builds: dict[str, int] = {}

    def make(acc: str, char: str):
        def builder() -> tuple[str, int]:
            builds[acc] = builds.get(acc, 0) + 1
            return char * 100, 300

        return builder

    cache.get_or_build(("sections", "k1"), make("k1", "1"))
    cache.get_or_build(("sections", "k2"), make("k2", "2"))
    assert cache.get_or_build(("sections", "k1"), make("k1", "1")) == "1" * 100
    cache.get_or_build(("sections", "k3"), make("k3", "3"))
    disk = cache.stats()["disk"]
    assert disk["current_bytes"] <= 250
    assert disk["evictions"] >= 1
    assert cache.get_or_build(("sections", "k2"), make("k2", "2")) == "2" * 100
    assert builds["k2"] == 2
    assert cache.get_or_build(("sections", "k3"), make("k3", "3")) == "3" * 100
    assert builds["k3"] == 1
