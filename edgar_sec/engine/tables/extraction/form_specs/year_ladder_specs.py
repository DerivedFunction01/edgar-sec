"""Year-ladder form-test parameters, keyed by family."""

from __future__ import annotations

from dataclasses import dataclass


ORIENT_COLUMNS = "columns"
ORIENT_ROWS = "rows"
THEREAFTER_REQUIRED = "required"
THEREAFTER_PREFERRED = "preferred"
THEREAFTER_NONE = "none"
TOTAL_CORROBORATE = "corroborate"
TOTAL_IGNORE = "ignore"
ANCHOR_AFTER_ASOF = "after_asof_when_present"
ANCHOR_NONE = "none"


@dataclass(frozen=True, slots=True)
class YearLadderSpec:
    """Year-ladder form-test parameters, declared as registry data."""

    orientations: tuple[str, ...]
    min_year_steps: int
    thereafter: str = THEREAFTER_PREFERRED
    bucket_ladder: bool = False
    min_bucket_steps: int = 0
    total_mode: str = TOTAL_CORROBORATE
    anchor: str = ANCHOR_AFTER_ASOF
    tolerance: float = 0.02


# Year-ladder class specs, keyed by family: the one literal
# home of the ladder kind's parameters.
YEAR_LADDER_SPECS: dict[str, YearLadderSpec] = {
    "debt_maturity": YearLadderSpec(
        orientations=(ORIENT_COLUMNS, ORIENT_ROWS),
        min_year_steps=4,
        thereafter=THEREAFTER_PREFERRED,
        bucket_ladder=False,
        total_mode=TOTAL_CORROBORATE,
        anchor=ANCHOR_AFTER_ASOF,
    ),
    "commitments_contingencies": YearLadderSpec(
        orientations=(ORIENT_COLUMNS, ORIENT_ROWS),
        min_year_steps=3,
        thereafter=THEREAFTER_PREFERRED,
        bucket_ladder=True,
        min_bucket_steps=3,
        total_mode=TOTAL_CORROBORATE,
        anchor=ANCHOR_AFTER_ASOF,
    ),
}
