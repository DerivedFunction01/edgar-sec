"""Combined operations separator evidence (TEST_COMBINED_OPERATIONS_SEPARATOR).
The claim-local cascade over one table at the form-test stage,
and the set-level J1 / A1-corekeep pass over a filing's complete
candidate sets, ranked by the facts the stage stamps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.combined_operations_separator_specs import (
    COMBINED_OPERATIONS_SEPARATOR_SPECS,
    CORE_GROUP_INDICES,
    JOINT_MEASURE_SET_TEST_ID,
    MEASURE_SET_TEST_ID,
    CombinedOperationsSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome,
)
from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.measure_set import (
    evaluate_measure_set,
    group_presence,
)
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_COMBINED_OPERATIONS_SEPARATOR,
    TEST_MEASURE_SET,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable
from edgar_sec.foundation.text.dates import STRICT_YEAR_TOKEN_PATTERN

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.competition import (
        CompetitionResult,
    )

FAMILY = "combined_operations_ci"
PRIMARIES = ("combined_operations_ci", "income_statement", "comprehensive_income")

# The sibling primaries' core tests, as stamped on every geometry:
# core for a sibling is its own core test passing (Rulings 11-13).
SIBLING_CORE_TEST_IDS = {
    "income_statement": "revenue_to_net_income_descent",
    "comprehensive_income": "comprehensive_income_boundary_walk",
}

_YEAR_RE = re.compile(STRICT_YEAR_TOKEN_PATTERN)
_FACTS_RE = re.compile(r"core=([01]) rank=([0-2])")
_HEADER_ZONE_ROWS = 6

_MEASURE_SET_FORM_SPEC = FormTestSpec(
    FAMILY, TEST_MEASURE_SET, MEASURE_SET_TEST_ID, 0.0
)
_JOINT_FORM_SPEC = FormTestSpec(
    FAMILY, TEST_MEASURE_SET, JOINT_MEASURE_SET_TEST_ID, 0.0
)


@dataclass(frozen=True, slots=True)
class CombinedOperationsSeparatorVerdict:
    """The separator's read over one table."""

    fired: bool
    fired_legs: tuple[str, ...]
    core_satisfied: bool
    form_rank: int
    evaluable: bool
    detail: str


def _year_columns(table: TypedTable) -> int:
    """Distinct year-carrying columns through the first wide year row."""
    zone = table.context.rows[:_HEADER_ZONE_ROWS]
    first_wide = None
    for index, row in enumerate(zone):
        years = set()
        for cell in row:
            years.update(_YEAR_RE.findall(cell or ""))
        if len(years) >= 2:
            first_wide = index
            break
    if first_wide is None:
        return 0
    columns = set()
    for row in zone[: first_wide + 1]:
        for column, cell in enumerate(row):
            if _YEAR_RE.search(cell or ""):
                columns.add(column)
    return len(columns)


def evaluate_combined_operations_separator(
    table: TypedTable, spec: CombinedOperationsSeparatorSpec
) -> CombinedOperationsSeparatorVerdict:
    """Evaluate the claim-local cascade legs over one table."""
    present = group_presence(table, MEASURE_SET_TEST_ID)
    measure_passed = evaluate_measure_set(table, _MEASURE_SET_FORM_SPEC).admitted
    joint_passed = evaluate_measure_set(table, _JOINT_FORM_SPEC).admitted
    core_satisfied = all(present[index] for index in CORE_GROUP_INDICES) or joint_passed
    form_rank = 2 if measure_passed else 1 if joint_passed else 0
    n_rows = len(table.rows)
    evaluable = n_rows > 0 or any(present)
    if not evaluable:
        return CombinedOperationsSeparatorVerdict(
            False, (), core_satisfied, form_rank, False, "coci separator unevaluable"
        )
    valued = sum(1 for row in table.rows if any(v is not None for v in row.values))
    numeric_share = round(valued / n_rows, 4) if n_rows else 0.0
    legs = []
    if n_rows <= spec.max_rows:
        legs.append("S1_rows")
    if numeric_share < spec.numeric_share_bound:
        legs.append("S2_numshare")
    if _year_columns(table) >= spec.min_year_columns:
        legs.append("S3_span")
    if not core_satisfied:
        legs.append("C1_core")
    facts = f"core={1 if core_satisfied else 0} rank={form_rank}"
    if legs:
        detail = f"coci separator fired: {'+'.join(legs)} {facts}"
    else:
        detail = f"coci separator clear {facts}"
    return CombinedOperationsSeparatorVerdict(
        bool(legs), tuple(legs), core_satisfied, form_rank, True, detail
    )


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_combined_operations_separator(table, spec):
    """Stage adapter: evaluate the separator over a table."""
    return evaluate_combined_operations_separator(
        table, COMBINED_OPERATIONS_SEPARATOR_SPECS[spec.family]
    )


def failing_combined_operations_separator_outcome(form_tests):
    """The stamped separator outcome failing this family's gate.

    Delegates to the homed outcome reader in core_form_evidence."""
    return failing_core_form_outcome(
        form_tests, FAMILY, TEST_COMBINED_OPERATIONS_SEPARATOR
    )


def separator_facts(form_tests) -> tuple[bool, int] | None:
    """The (core_satisfied, form_rank) facts the stage stamped."""
    for outcome in form_tests:
        if (
            outcome.family == FAMILY
            and outcome.kind == TEST_COMBINED_OPERATIONS_SEPARATOR
        ):
            match = _FACTS_RE.search(outcome.detail)
            if match is None:
                return None
            return match.group(1) == "1", int(match.group(2))
    return None


# ---------------- set-level pass (J1 joint assignment, A1 corekeep) ----------------


def _test_passed(form_tests, test_id: str) -> bool:
    return any(outcome.test_id == test_id and outcome.passed for outcome in form_tests)


def _core_satisfied(geometry, family: str) -> bool:
    """Core satisfaction for one primary on one geometry."""
    if family == FAMILY:
        facts = separator_facts(geometry.form_tests)
        return facts[0] if facts is not None else False
    return _test_passed(geometry.form_tests, SIBLING_CORE_TEST_IDS[family])


def _rank_key(geometry, result: CompetitionResult, family: str):
    """The priced rank: core first, form rank for this family, score."""
    score = result.scores[family].total if family in result.scores else 0.0
    facts = separator_facts(geometry.form_tests)
    form_rank = facts[1] if family == FAMILY and facts is not None else 0
    return (_core_satisfied(geometry, family), form_rank, score)


def _refuse(result: CompetitionResult, family: str, note: str) -> CompetitionResult:
    """Drop one family's claim, stamping the act on its score."""
    from edgar_sec.engine.tables.extraction.competition import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    scores = dict(result.scores)
    score = scores.get(family)
    if score is not None:
        scores[family] = FamilyScore(
            family,
            score.total,
            dict(score.by_channel),
            score.evidence + (ClaimEvidence("gate", note, 0.0),),
        )
    return CompetitionResult(
        claims=tuple(f for f in result.claims if f != family),
        contested=tuple(f for f in result.contested if f != family),
        scores=scores,
        foreign_explained=result.foreign_explained,
        groups=result.groups,
    )


def apply_combined_operations_assignment(geometries, results):
    """J1 joint assignment across the primaries, then A1 corekeep.

    J1: a geometry claimed by two or more primaries seats only the
    top-ranked one. A1: a filing's non-core candidates for this
    family are pruned to their best one; core candidates all stand.
    X1 require-tie carries no act: refuted as a gate in every frame,
    it is corroboration only and this stage never reads it."""
    results = list(results)
    for index, geometry in enumerate(geometries):
        result = results[index]
        claimed = [family for family in PRIMARIES if family in result.claims]
        if len(claimed) < 2:
            continue
        winner = max(claimed, key=lambda f: _rank_key(geometry, result, f))
        for family in claimed:
            if family != winner:
                result = _refuse(result, family, f"joint assignment: {winner} seated")
        results[index] = result
    claimed = [i for i, r in enumerate(results) if FAMILY in r.claims]
    if len(claimed) > 1:
        core = {i for i in claimed if _core_satisfied(geometries[i], FAMILY)}
        rest = [i for i in claimed if i not in core]
        if rest:
            keep = max(rest, key=lambda i: _rank_key(geometries[i], results[i], FAMILY))
            for i in rest:
                if i != keep:
                    results[i] = _refuse(
                        results[i],
                        FAMILY,
                        "corekeep adjudication: core candidates stand",
                    )
    return results
