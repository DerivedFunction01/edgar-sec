"""Census expectations: the scored counts each population must match.

The probe row is loaded from census_probe_expectation.json beside
this module; the remaining rows are adjudicated literals, their
movements cited at the table. benchmark_census.score_census consumes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CensusExpectation:
    """Scored census counts for one population; movement needs adjudication."""

    n: int
    correct: int
    honest: int
    surfaced_conflicts: int


def _load_probe_expectation() -> CensusExpectation:
    """Load the pinned probe census expectation from its data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("census_probe_expectation.json")
        .read_text(encoding="utf-8")
    )
    row = raw["probe"]
    return CensusExpectation(
        n=row["n"],
        correct=row["correct"],
        honest=row["honest"],
        surfaced_conflicts=row["surfaced_conflicts"],
    )


@lru_cache(maxsize=1)
def load_expectations() -> dict[str, CensusExpectation]:
    """Load every census expectation, the probe row included, on first use."""
    # Span adjudications: F5 moved span 127/62/33 -> 130/59/36, and the
    # derivation fix moved span -> 161/28/4; adjudicated in
    # .artifacts/run-logs/2026-11-01-derivation-direction-fix.md.
    return {
        "probe": _load_probe_expectation(),
        # The R/P partner build moved span -> 162/27/3, adjudicated in
        # .artifacts/run-logs/2026-11-09-rp-partner-coverage-impl.md.
        "span": CensusExpectation(n=189, correct=162, honest=27, surfaced_conflicts=3),
        "span-supplement": CensusExpectation(
            n=5, correct=0, honest=5, surfaced_conflicts=0
        ),
        # Followup moved 1438/721/717/192 -> 1706/853/853/221 when Wave D
        # added 8 firms; adjudicated in the WS2 batch log.
        "followup": CensusExpectation(
            n=1706, correct=853, honest=853, surfaced_conflicts=221
        ),
    }


def __getattr__(name: str) -> Any:
    """Serve CENSUS_EXPECTATIONS lazily, so import reads no data file."""
    if name == "CENSUS_EXPECTATIONS":
        return load_expectations()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
