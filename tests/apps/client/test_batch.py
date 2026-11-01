"""Batch streaming contract: bounded lifetimes, per-filing failures."""

from __future__ import annotations

import gc
import os
import statistics
import time
import weakref
from pathlib import Path

import psutil

from edgar_sec.apps.client.batch import FilingOutcome, stream_filing_outcomes
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from tests.support import bundle_dir, load_fixture


def _length_or_raise(unit: str) -> int:
    """The unit's length, except one unit that always fails."""
    if unit == "bad":
        raise ValueError("boom")
    return len(unit)


def _length_or_crash(unit: str) -> int:
    """The unit's length, except one unit that kills its worker process."""
    if unit == "crash":
        os._exit(42)
    time.sleep(0.3)
    return len(unit)


def test_sequential_outcomes_carry_values_and_named_errors() -> None:
    """Sequential outcomes arrive in order; a failure is named, not raised."""
    outcomes = list(
        stream_filing_outcomes(["aa", "bad", "cccc"], _length_or_raise, workers=1)
    )
    assert [outcome.unit for outcome in outcomes] == ["aa", "bad", "cccc"]
    assert [outcome.value for outcome in outcomes] == [2, None, 4]
    assert outcomes[1].error == "ValueError: boom"
    assert [outcome.ok for outcome in outcomes] == [True, False, True]


def test_pool_outcomes_equal_sequential_outcomes() -> None:
    """The pool changes lifetimes only: per-unit results are unchanged."""
    units = ["aa", "bad", "cccc", "d", "ee", "fff", "gg", "hhhhh"]

    def by_unit(outcomes: list[FilingOutcome[str, int]]) -> dict[str, tuple]:
        return {o.unit: (o.value, o.error) for o in outcomes}

    sequential = by_unit(
        list(stream_filing_outcomes(units, _length_or_raise, workers=1))
    )
    pooled = by_unit(list(stream_filing_outcomes(units, _length_or_raise, workers=2)))
    assert pooled == sequential


def test_worker_crash_fails_its_window_not_the_run() -> None:
    """A worker's death errors its in-flight filings; the run completes."""
    units = ["crash"] + [f"u{i}" for i in range(7)]
    outcomes = {
        o.unit: o for o in stream_filing_outcomes(units, _length_or_crash, workers=2)
    }
    assert set(outcomes) == set(units)
    assert outcomes["crash"].error is not None
    assert outcomes["crash"].error.startswith("BrokenProcessPool")
    assert all(outcomes[f"u{i}"].ok for i in range(4, 7))


_TAXONOMY: DomainTaxonomy | None = None
_LIVE_FACADES: weakref.WeakSet[Xbrl] = weakref.WeakSet()
_PROBE = {"built": 0, "peak": 0}


def _taxonomy() -> DomainTaxonomy:
    """This process's taxonomy, loaded once for the probe runs."""
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = load_domain_taxonomy()
    return _TAXONOMY


def _probe_filing(unit: str) -> tuple[int, int]:
    """Build one bundle's facade and report its size, holding nothing."""
    facade = Xbrl.from_bundle(Path(unit), _taxonomy())
    _LIVE_FACADES.add(facade)
    _PROBE["built"] += 1
    _PROBE["peak"] = max(_PROBE["peak"], len(_LIVE_FACADES))
    return len(facade.facts), len(facade.facts.records)


def test_streaming_seed_run_never_accumulates_facades() -> None:
    """49 seed filings stream through one worker; live facades stay at one."""
    _PROBE.update(built=0, peak=0)
    sources = load_fixture("xbrl/seed/fixture_source_registry.json")["bundles"]
    units = [str(bundle_dir(source["folder"])) for source in sources]
    assert len(units) == 49
    rss = []
    seen = 0
    for outcome in stream_filing_outcomes(units, _probe_filing, workers=1):
        assert outcome.ok
        seen += 1
        rss.append(psutil.Process().memory_info().rss)
    gc.collect()
    assert seen == 49
    assert _PROBE == {"built": 49, "peak": 1}
    assert len(_LIVE_FACADES) == 0
    warm = rss[8:]
    growth = statistics.median(warm[-12:]) - statistics.median(warm[:12])
    assert growth <= 64 * 1024 * 1024
