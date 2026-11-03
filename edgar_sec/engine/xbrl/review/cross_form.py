"""Cross-form census summaries, grouped and scored by filing block."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
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


def _load_expectations() -> dict[str, CrossFormExpectation]:
    """Load the pinned cross-form expectation blocks from their data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("cross_form_expectations.json")
        .read_text(encoding="utf-8")
    )
    return {key: CrossFormExpectation(**row) for key, row in sorted(raw.items())}


CROSS_FORM_EXPECTATIONS: dict[str, CrossFormExpectation] = _load_expectations()


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
