"""Cross-form census summaries, grouped and scored by filing block."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from edgar_sec.engine.xbrl.review.benchmark import CensusScore, _ADVERSE_CLASSES


def block_key(form: str, taxonomy: str, period_shape: str) -> str:
    """Return the census block key for one form/taxonomy/period shape."""
    return f"{form}|{taxonomy}|{period_shape}"


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


CROSS_FORM_EXPECTATIONS: dict[str, CrossFormExpectation] = {
    "10-K|us-gaap|annual": CrossFormExpectation(
        form="10-K",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "10-K/A|us-gaap|annual": CrossFormExpectation(
        form="10-K/A",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "10-Q|us-gaap|quarterly": CrossFormExpectation(
        form="10-Q",
        taxonomy="us-gaap",
        period_shape="quarterly",
        posture="measured",
        n=3,
        correct=0,
        honest=0,
        surfaced_conflicts=0,
        adverse={"refused": 2, "wrong-value": 1},
        replay_mismatches=3,
    ),
    "10-Q|us-gaap|ytd": CrossFormExpectation(
        form="10-Q",
        taxonomy="us-gaap",
        period_shape="ytd",
        posture="measured",
        n=8,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
        adverse={"refused": 4, "unfaithful non-answer": 2, "wrong-value": 1},
        replay_mismatches=7,
    ),
    "10-Q/A|us-gaap|ytd": CrossFormExpectation(
        form="10-Q/A",
        taxonomy="us-gaap",
        period_shape="ytd",
        posture="measured",
        n=1,
        correct=0,
        honest=0,
        surfaced_conflicts=0,
        adverse={"refused": 1},
        replay_mismatches=1,
    ),
    "11-K|us-gaap-ebp|annual": CrossFormExpectation(
        form="11-K",
        taxonomy="us-gaap-ebp",
        period_shape="annual",
        posture="absence",
        n=2,
        correct=0,
        honest=2,
        surfaced_conflicts=0,
    ),
    "424B2|ffd|quarterly": CrossFormExpectation(
        form="424B2",
        taxonomy="ffd",
        period_shape="quarterly",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
    "6-K|ifrs-full|ytd": CrossFormExpectation(
        form="6-K",
        taxonomy="ifrs-full",
        period_shape="ytd",
        posture="measured",
        n=1,
        correct=0,
        honest=0,
        surfaced_conflicts=0,
        adverse={"unfaithful non-answer": 1},
        replay_mismatches=1,
    ),
    "6-K|us-gaap|ytd": CrossFormExpectation(
        form="6-K",
        taxonomy="us-gaap",
        period_shape="ytd",
        posture="measured",
        n=1,
        correct=0,
        honest=0,
        surfaced_conflicts=0,
        adverse={"refused": 1},
        replay_mismatches=1,
    ),
    "8-K|dei|quarterly": CrossFormExpectation(
        form="8-K",
        taxonomy="dei",
        period_shape="quarterly",
        posture="absence",
        n=6,
        correct=0,
        honest=6,
        surfaced_conflicts=0,
    ),
    "8-K|us-gaap|annual": CrossFormExpectation(
        form="8-K",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "8-K/A|us-gaap|annual": CrossFormExpectation(
        form="8-K/A",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=2,
        correct=1,
        honest=0,
        surfaced_conflicts=1,
        adverse={"wrong-value": 1},
        replay_mismatches=1,
    ),
    "DEF 14A|ecd|annual": CrossFormExpectation(
        form="DEF 14A",
        taxonomy="ecd",
        period_shape="annual",
        posture="absence",
        n=2,
        correct=0,
        honest=2,
        surfaced_conflicts=0,
    ),
    "F-1|us-gaap|annual": CrossFormExpectation(
        form="F-1",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "N-CSR|cef|annual": CrossFormExpectation(
        form="N-CSR",
        taxonomy="cef",
        period_shape="annual",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
    "N-CSR|oef|quarterly": CrossFormExpectation(
        form="N-CSR",
        taxonomy="oef",
        period_shape="quarterly",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
    "N-CSRS|cef|ytd": CrossFormExpectation(
        form="N-CSRS",
        taxonomy="cef",
        period_shape="ytd",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
    "N-CSRS|oef|ytd": CrossFormExpectation(
        form="N-CSRS",
        taxonomy="oef",
        period_shape="ytd",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
    "S-1|us-gaap|annual": CrossFormExpectation(
        form="S-1",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "S-4|us-gaap|annual": CrossFormExpectation(
        form="S-4",
        taxonomy="us-gaap",
        period_shape="annual",
        posture="measured",
        n=1,
        correct=1,
        honest=0,
        surfaced_conflicts=0,
    ),
    "SD|rxp|annual": CrossFormExpectation(
        form="SD",
        taxonomy="rxp",
        period_shape="annual",
        posture="absence",
        n=1,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
    ),
}


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
                name: counts[name] for name in counts if name in _ADVERSE_CLASSES
            },
            "replay_mismatches": sum(1 for e in evs if e["replay_mismatch"]),
        }
    return {"blocks": blocks}


def score_cross_form(
    summary: dict[str, Any],
    expectations: dict[str, CrossFormExpectation] = CROSS_FORM_EXPECTATIONS,
) -> CensusScore:
    """Score a cross-form summary; any unadjudicated movement fails."""
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
