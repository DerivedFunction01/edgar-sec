"""Walk-kind form-test parameters, keyed by test_id."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WalkSpec:
    """Walk-kind parameters for one test, keyed by test_id below.
    column_headers selects value columns (empty means all of them);
    a pass needs min_columns columns closed over >= min_movements."""

    min_movements: int = 1
    min_columns: int = 1
    column_headers: tuple[str, ...] = ()


# Walk-kind parameters, keyed by test_id (the per-kind table).
WALK_SPECS_BY_TEST_ID: dict[str, WalkSpec] = {
    "aoci_beginning_ending_walk": WalkSpec(),
    "comprehensive_income_boundary_walk": WalkSpec(),
    "stock_comp_activity_walk": WalkSpec(),
    "eps_numerator_denominator_walk": WalkSpec(min_columns=2),
}
