"""Cross-form census summaries, grouped and scored by filing block."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.review.benchmark_census import CensusScore, _ADVERSE_CLASSES


def block_key(form: str, taxonomy: str, period_shape: str) -> str:
    """Return the census block key for one form/taxonomy/period shape."""
    return f"{form}|{taxonomy}|{period_shape}"


# A pooled original+amendment answer drawn from the wrong population is
# adverse in the cross-form census only; per-filing populations never mix.
_CROSS_FORM_ADVERSE = _ADVERSE_CLASSES | {"mixed-population"}


@dataclass(frozen=True, slots=True)
class CrossFormExpectation:
    """Scored cross-form counts for one block; movement needs adjudication."""

    form: str
    taxonomy: str
    period_shape: str
    posture: str
    n: int
    correct: int
    honest: int
    surfaced_conflicts: int
    adverse: dict[str, int] = field(default_factory=dict)
    replay_mismatches: int = 0


@lru_cache(maxsize=1)
def _load_expectations() -> dict[str, CrossFormExpectation]:
    """Load the pinned cross-form expectation blocks from their data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("cross_form_expectations.json")
        .read_text(encoding="utf-8")
    )
    return {key: CrossFormExpectation(**row) for key, row in sorted(raw.items())}


@dataclass(frozen=True, slots=True)
class FactExpectation:
    """Pinned fact-matrix counts for one form/taxonomy/shape row."""

    form: str
    taxonomy: str
    period_shape: str
    filings: int
    facts: int
    numeric_facts: int
    dimensioned_numeric: int
    quarantined_facts: int


@lru_cache(maxsize=1)
def _load_fact_expectations() -> dict[str, FactExpectation]:
    """Load the pinned fact-matrix rows from their data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("cross_form_fact_expectations.json")
        .read_text(encoding="utf-8")
    )
    return {key: FactExpectation(**row) for key, row in sorted(raw.items())}


def score_fact_matrix(
    summary: dict[str, Any],
    expectations: dict[str, FactExpectation] | None = None,
) -> CensusScore:
    """Score the fact matrix; any unadjudicated movement fails."""
    if expectations is None:
        expectations = _load_fact_expectations()
    failures: list[str] = []
    matrix = summary.get("fact_matrix", {})
    for key, expected in expectations.items():
        row = matrix.get(key)
        if row is None:
            failures.append(f"fact {key}: row missing from fact matrix")
            continue
        for field in (
            "filings",
            "facts",
            "numeric_facts",
            "dimensioned_numeric",
            "quarantined_facts",
        ):
            if row[field] != getattr(expected, field):
                failures.append(
                    f"fact {key}: {field} {row[field]} "
                    f"!= expected {getattr(expected, field)}"
                )
    return CensusScore(passed=not failures, failures=tuple(failures))


@dataclass(frozen=True, slots=True)
class K1Expectation:
    """Pinned dimensioned-only (K1) mass for one form/taxonomy block."""

    form: str
    taxonomy: str
    filings: int
    k1_facts: int
    no_calc_role: int
    in_calc_arcs: int
    per_share: int
    schedule: int
    breakdown_served: int
    calc_component: int
    orphan: int


@lru_cache(maxsize=1)
def _load_k1_expectations() -> dict[str, K1Expectation]:
    """Load the pinned K1 blocks from their data file."""
    raw = json.loads(
        Path(__file__).with_name("k1_expectations.json").read_text(encoding="utf-8")
    )
    return {key: K1Expectation(**row) for key, row in sorted(raw.items())}


_K1_FIELDS = (
    "filings",
    "k1_facts",
    "no_calc_role",
    "in_calc_arcs",
    "per_share",
    "schedule",
    "breakdown_served",
    "calc_component",
    "orphan",
)

_K1_DISPOSITIONS = (
    "per_share",
    "schedule",
    "breakdown_served",
    "calc_component",
    "orphan",
)


def score_k1(
    summary: dict[str, Any],
    expectations: dict[str, K1Expectation] | None = None,
) -> CensusScore:
    """Score the K1 census; mass moves only by adjudicated reclassification."""
    if expectations is None:
        expectations = _load_k1_expectations()
    failures: list[str] = []
    blocks = summary.get("k1_blocks", {})
    for key, expected in expectations.items():
        row = blocks.get(key)
        if row is None:
            failures.append(f"k1 {key}: block missing from K1 census")
            continue
        for name in _K1_FIELDS:
            if row[name] != getattr(expected, name):
                failures.append(
                    f"k1 {key}: {name} {row[name]} != expected {getattr(expected, name)}"
                )
        if sum(row[name] for name in _K1_DISPOSITIONS) != row["k1_facts"]:
            failures.append(f"k1 {key}: dispositions do not sum to k1_facts")
        if row["no_calc_role"] + row["in_calc_arcs"] != row["k1_facts"]:
            failures.append(f"k1 {key}: calc-role split does not sum to k1_facts")
    return CensusScore(passed=not failures, failures=tuple(failures))


@dataclass(frozen=True, slots=True)
class DeiPresenceExpectation:
    """Pinned dei period/fiscal metadata presence for one form family."""

    form: str
    filings: int
    present: dict[str, int] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _load_dei_presence_expectations() -> dict[str, DeiPresenceExpectation]:
    """Load the pinned dei presence rows from their data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("dei_presence_expectations.json")
        .read_text(encoding="utf-8")
    )
    return {key: DeiPresenceExpectation(**row) for key, row in sorted(raw.items())}


def score_dei_presence(
    summary: dict[str, Any],
    expectations: dict[str, DeiPresenceExpectation] | None = None,
) -> CensusScore:
    """Score dei metadata presence per form family; movement fails."""
    if expectations is None:
        expectations = _load_dei_presence_expectations()
    failures: list[str] = []
    presence = summary.get("dei_presence", {})
    for form, expected in expectations.items():
        row = presence.get(form)
        if row is None:
            failures.append(f"dei {form}: family missing from census")
            continue
        if row["filings"] != expected.filings:
            failures.append(
                f"dei {form}: filings {row['filings']} != expected {expected.filings}"
            )
        if row["present"] != expected.present:
            failures.append(
                f"dei {form}: presence {row['present']} != expected {expected.present}"
            )
    return CensusScore(passed=not failures, failures=tuple(failures))


def summarize_cross_form(evaluations: list[dict]) -> dict:
    """Aggregate cross-form evaluations into the scored summary shape."""
    grouped: dict[str, list[dict]] = {}
    for ev in evaluations:
        if ev.get("population") != "cross-form":
            continue
        key = block_key(ev["form"], ev["taxonomy"], ev["period_shape"])
        grouped.setdefault(key, []).append(ev)
    blocks: dict[str, dict] = {}
    for key, evs in grouped.items():
        first = evs[0]
        counts = Counter(e["classification"] for e in evs)
        blocks[key] = {
            "form": first["form"],
            "taxonomy": first["taxonomy"],
            "period_shape": first["period_shape"],
            "n": len(evs),
            "solved": counts.get("correct", 0),
            "honest": counts.get("honest-faithful", 0),
            "conflict": sum(1 for e in evs if e["facade"]["status"] == "CONFLICT"),
            "quarantined_facts": sum(e.get("quarantined_facts", 0) for e in evs),
            "adverse": {
                name: counts[name] for name in counts if name in _CROSS_FORM_ADVERSE
            },
            "replay_mismatches": sum(1 for e in evs if e["replay_mismatch"]),
        }
    return {"blocks": blocks}


def score_cross_form(
    summary: dict[str, Any],
    expectations: dict[str, CrossFormExpectation] | None = None,
) -> CensusScore:
    """Score a cross-form summary; any unadjudicated movement fails."""
    if expectations is None:
        expectations = _load_expectations()
    failures: list[str] = []
    blocks = summary.get("blocks", {})
    for key, expected in expectations.items():
        block = blocks.get(key)
        if block is None:
            failures.append(f"{key}: block missing from summary")
            continue
        if block["n"] != expected.n:
            failures.append(f"{key}: n {block['n']} != expected {expected.n}")
        if block["adverse"] != expected.adverse:
            failures.append(
                f"{key}: adverse {block['adverse']} != expected {expected.adverse}"
            )
        if block["solved"] != expected.correct:
            failures.append(
                f"{key}: correct {block['solved']} != expected {expected.correct}"
            )
        if block["honest"] != expected.honest:
            failures.append(
                f"{key}: honest-faithful {block['honest']} "
                f"!= expected {expected.honest}"
            )
        if block["replay_mismatches"] != expected.replay_mismatches:
            failures.append(
                f"{key}: replay_mismatches {block['replay_mismatches']} "
                f"!= expected {expected.replay_mismatches}"
            )
        if block["conflict"] != expected.surfaced_conflicts:
            failures.append(
                f"{key}: surfaced_conflicts {block['conflict']} "
                f"!= expected {expected.surfaced_conflicts}"
            )
        if expected.posture == "absence" and block["solved"] != 0:
            failures.append(f"{key}: absence solved {block['solved']} != 0")
    return CensusScore(passed=not failures, failures=tuple(failures))


_LAZY_EXPECTATIONS = {
    "CROSS_FORM_EXPECTATIONS": _load_expectations,
    "FACT_EXPECTATIONS": _load_fact_expectations,
    "K1_EXPECTATIONS": _load_k1_expectations,
    "DEI_PRESENCE_EXPECTATIONS": _load_dei_presence_expectations,
}


def __getattr__(name: str) -> Any:
    """Serve the expectation constants lazily, so import reads no data file."""
    loader = _LAZY_EXPECTATIONS.get(name)
    if loader is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return loader()
