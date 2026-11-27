"""Census summary aggregation and expectation scoring for XBRL review."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.review.census_expectations import (
    CensusExpectation,
    load_expectations,
)


def summarize_census(evaluations: list[dict]) -> dict:
    """Aggregate evaluations into the scored summary shape, per population."""
    by_pop: dict[str, list[dict]] = {}
    for ev in evaluations:
        by_pop.setdefault(ev["population"], []).append(ev)
    summary: dict = {"populations": {}}
    for pop, evs in by_pop.items():
        summary["populations"][pop] = {
            "n": len(evs),
            "classification": dict(Counter(e["classification"] for e in evs)),
            "replay_mismatches": sum(1 for e in evs if e["replay_mismatch"]),
            "surfaced_conflicts": [
                {
                    "firm": e["firm"],
                    "term": e["term"],
                    "mode": e["mode"],
                    "precision_duplicate": e.get("conflict_precision_duplicate"),
                }
                for e in evs
                if e["facade"]["status"] == "CONFLICT"
            ],
            "derived_artefacts": [
                {"firm": e["firm"], "term": e["term"], "mode": e["mode"]}
                for e in evs
                if e["facade"]["status"] == "DERIVED"
                and not e.get("derived_in_faithful_tier", True)
            ],
            "derived_faithful_no_reported": [
                {
                    "firm": e["firm"],
                    "term": e["term"],
                    "mode": e["mode"],
                    "value": e["facade"]["value"],
                }
                for e in evs
                if e["facade"]["status"] == "DERIVED"
                and e.get("derived_in_faithful_tier")
                and e.get("derived_has_reported_fact") is False
            ],
            "textblock_answer_evaluations": sum(
                1 for e in evs if e.get("textblock_candidates")
            ),
            "near_promotions": sum(1 for e in evs if e.get("near_promotion")),
            "near_guard_violations": [
                {"firm": e["firm"], "term": e["term"], "mode": e["mode"]}
                for e in evs
                if e.get("near_guard_violation")
            ],
            "shadowed_conflicts": {
                "total": sum(
                    1 for e in evs if e.get("shadowed_conflict_in_tiers") is not None
                ),
                "in_faithful_tiers": sum(
                    1 for e in evs if e.get("shadowed_conflict_in_tiers")
                ),
                "by_facade_status": dict(
                    Counter(
                        e["facade"]["status"]
                        for e in evs
                        if e.get("shadowed_conflict_in_tiers") is not None
                    )
                ),
            },
            "loose_revenue": [
                {
                    "firm": e["firm"],
                    "mode": e["mode"],
                    "status": e["facade"]["status"],
                    "value": e["facade"]["value"],
                    "bare_components": e.get("bare_revenue_components"),
                }
                for e in evs
                if e["term"] == "revenue"
            ],
        }
    return summary


@dataclass(frozen=True, slots=True)
class CensusScore:
    """Gate outcome for a census summary against scored expectations."""

    passed: bool
    failures: tuple[str, ...]


_ADVERSE_CLASSES = frozenset(
    {"wrong-span", "wrong-value", "refused", "unfaithful non-answer"}
)


def score_census(
    summary: dict[str, Any],
    expectations: dict[str, CensusExpectation] | None = None,
) -> CensusScore:
    """Score a census summary; any unadjudicated movement fails the gate."""
    if expectations is None:
        expectations = load_expectations()
    failures: list[str] = []
    populations = summary.get("populations", {})
    for name, expected in expectations.items():
        pop = populations.get(name)
        if pop is None:
            failures.append(f"{name}: population missing from summary")
            continue
        if pop["n"] != expected.n:
            failures.append(f"{name}: n {pop['n']} != expected {expected.n}")
        counts = pop["classification"]
        adverse = {key: counts[key] for key in counts if key in _ADVERSE_CLASSES}
        if adverse:
            failures.append(f"{name}: adverse classifications {adverse}")
        correct = counts.get("correct", 0)
        honest = counts.get("honest-faithful", 0)
        if correct != expected.correct:
            failures.append(f"{name}: correct {correct} != expected {expected.correct}")
        if honest != expected.honest:
            failures.append(
                f"{name}: honest-faithful {honest} != expected {expected.honest}"
            )
        if pop["replay_mismatches"] != 0:
            failures.append(
                f"{name}: replay_mismatches {pop['replay_mismatches']} != 0"
            )
        surfaced = len(pop["surfaced_conflicts"])
        if surfaced != expected.surfaced_conflicts:
            failures.append(
                f"{name}: surfaced_conflicts {surfaced} "
                f"!= expected {expected.surfaced_conflicts}"
            )
        if pop["derived_artefacts"]:
            failures.append(f"{name}: derived artefacts {pop['derived_artefacts']}")
        if pop["near_guard_violations"]:
            failures.append(
                f"{name}: near guard violations {pop['near_guard_violations']}"
            )
        if pop["textblock_answer_evaluations"] != 0:
            failures.append(
                f"{name}: textblock answers {pop['textblock_answer_evaluations']} != 0"
            )
    return CensusScore(passed=not failures, failures=tuple(failures))
