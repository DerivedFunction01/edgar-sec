"""Admission evidence: the Step 7 core-signal reads.

J1 for debt_maturity (prose subject and ladder, plus the
total-reconciliation leg) and JOINT for commitments
(heading subject and disjunctive subform), over one table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import YEAR_TOKEN_RE, YEAR_TOKEN_SEARCH_RE

from .normalize import normalize_text
from .typed_rows import TOTAL_ROW_RE, TypedTable
from .validation import values_close

DEBT_TEST_ID = "debt_maturity_j1_admission"
JOINT_TEST_ID = "commitments_joint_admission"

_PROSE_TAIL = 700
_D1_SUBJECT_A = re.compile(
    r"(matur|principal (payments|amounts|repayments)|"
    r"repayments of (debt|principal)|amounts? due)"
)
_D1_SUBJECT_B = re.compile(
    build_alternation(
        ["debt", "borrow", "notes payable", "mortgage", "obligation", "advances"],
        auto_escape=True,
    )
)
_BUCKET_KEYS = (
    "less than 1 year",
    "1 year or less",
    "or less",
    "but less than",
    "1-3 years",
    "2-3 years",
    "3-5 years",
    "4-5 years",
    "more than 5 years",
    "5 years or more",
    "or more",
    "thereafter",
    "and beyond",
)
_BUCKET_LABEL_RE = re.compile(
    r"(less than|more than|thereafter|and beyond|"
    r"\d+\s*(?:-|to)\s*\d+\s*years?|within \d+|after \d+|"
    r"over \d+|greater than)"
)
_NUM_RE = re.compile(r"^\(?-?[\d]+(\.\d+)?\)?$")
_HEAD_COMMITMENT = re.compile(r"commitment")
_HEAD_CONTRACTUAL = re.compile(r"contractual obligation")
_PERIOD_RE = re.compile(r"payments due by (year|period)")
_CREDIT_PHRASES = (
    "commitments to extend credit",
    "standby letters of credit",
    "contract amounts represent credit risk",
    "unused lines of credit",
    "commitments to extend",
)
_PURCHASE_TABLE_PHRASES = (
    "purchase commitment",
    "purchase obligations",
    "manufacturing commitments",
)


@dataclass(frozen=True, slots=True)
class AdmissionOutcome:
    """One admission signal's legs over one table."""

    family: str
    test_id: str
    passed: bool
    evaluable: bool
    detail: str
    recon: bool | None = None


def _prose_tail(table: TypedTable) -> str:
    return normalize_text((table.context.prose_before or "")[-_PROSE_TAIL:])


def _heading_text(table: TypedTable) -> str:
    caption = " ".join(table.context.caption_stack)
    return normalize_text(f"{caption} {_prose_tail(table)}")


def _grid_text(table: TypedTable) -> str:
    return normalize_text(
        " ".join(cell for row in table.context.rows for cell in row if cell.strip())
    )


def _ladder(grid: str) -> bool:
    """The priced ladder leg: years, thereafter form, or buckets."""
    years = sorted({int(m.group(0)) for m in YEAR_TOKEN_SEARCH_RE.finditer(grid)})
    consec = 0
    if years:
        run = 1
        best = 1
        for a, b in zip(years, years[1:], strict=False):
            run = run + 1 if b == a + 1 else 1
            best = max(best, run)
        consec = best
    buckets = sum(1 for key in _BUCKET_KEYS if key in grid)
    return (
        consec >= 3
        or len(years) >= 3
        or (("thereafter" in grid or "and beyond" in grid) and len(years) >= 2)
        or buckets >= 2
    )


def _amount(cell: str) -> float | None:
    """The amount in a raw grid cell, when it is nothing else."""
    s = cell.strip().replace("$", "").replace(",", "").replace(" ", "")
    if s in ("", "-", "—") or not _NUM_RE.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        value = float(s.strip("()"))
    except ValueError:
        return None
    return -value if neg else value


def _recon_rows(rows: tuple[tuple[str, ...], ...]) -> bool:
    """Row axis: ladder-labelled rows sum to a total row."""
    ladder_idx = []
    total_idx = []
    for i, cells in enumerate(rows):
        label = normalize_text(cells[0]) if cells else ""
        if TOTAL_ROW_RE.match(label):
            total_idx.append(i)
        elif YEAR_TOKEN_SEARCH_RE.search(label) or _BUCKET_LABEL_RE.search(label):
            ladder_idx.append(i)
    if not total_idx or len(ladder_idx) < 2:
        return False
    width = max(len(c) for c in rows)
    for j in range(1, width):
        steps = []
        for i in ladder_idx:
            if j < len(rows[i]):
                value = _amount(rows[i][j])
                if value is not None and not (
                    j == 1 and YEAR_TOKEN_RE.match(rows[i][j].strip())
                ):
                    steps.append(value)
        if len(steps) < 2:
            continue
        for i in total_idx:
            if j < len(rows[i]):
                total = _amount(rows[i][j])
                if total is not None and values_close(sum(steps), total):
                    return True
    return False


def _recon_cols(rows: tuple[tuple[str, ...], ...]) -> bool:
    """Column axis: year-headed step columns sum to a total column."""
    if len(rows) < 2:
        return False
    width = max(len(c) for c in rows)
    total_cols = []
    step_cols = []
    for j in range(1, width):
        header = normalize_text(
            " ".join(r[j] for r in rows[:3] if j < len(r) and r[j].strip())
        )
        if "total" in header:
            total_cols.append(j)
        elif YEAR_TOKEN_SEARCH_RE.search(header):
            step_cols.append(j)
    if not total_cols or len(step_cols) < 2:
        return False
    for total_j in total_cols:
        checked = 0
        contradicted = False
        for cells in rows:
            total = _amount(cells[total_j]) if total_j < len(cells) else None
            steps = [_amount(cells[j]) if j < len(cells) else None for j in step_cols]
            if total is None or any(s is None for s in steps):
                continue
            checked += 1
            if not values_close(sum(steps), total):
                contradicted = True
                break
        if checked >= 1 and not contradicted:
            return True
    return False


def ladder_reconciles(table: TypedTable) -> bool:
    """Whether the table's ladder steps sum to its stated total."""
    rows = tuple(tuple(str(c) for c in row) for row in table.context.rows)
    if not rows:
        return False
    return _recon_rows(rows) or _recon_cols(rows)


def evaluate_debt_admission(table: TypedTable) -> AdmissionOutcome:
    """J1 for debt_maturity: prose subject and ladder, jointly."""
    prose = _prose_tail(table)
    grid = _grid_text(table)
    subject = bool(_D1_SUBJECT_A.search(prose)) and bool(_D1_SUBJECT_B.search(prose))
    ladder = _ladder(grid)
    passed = subject and ladder
    recon = ladder_reconciles(table) if ladder else False
    legs = f"subject={subject} ladder={ladder} recon={recon}"
    return AdmissionOutcome(
        "debt_maturity",
        DEBT_TEST_ID,
        passed,
        True,
        f"J1 {legs}",
        recon,
    )


def evaluate_commitments_joint(table: TypedTable) -> AdmissionOutcome:
    """JOINT for commitments: heading subject and subform."""
    head = _heading_text(table)
    grid = _grid_text(table)
    head_hit = bool(_HEAD_COMMITMENT.search(head)) or bool(
        _HEAD_CONTRACTUAL.search(head)
    )
    buckets = sum(1 for key in _BUCKET_KEYS if key in grid)
    period = buckets >= 2 or bool(_PERIOD_RE.search(grid))
    credit = any(phrase in grid for phrase in _CREDIT_PHRASES)
    unfunded = (
        "unfunded" in grid
        or "unfunded" in head
        or "unused commitments" in head
        or "commitments to extend financing" in head
    )
    purchase = (
        any(phrase in grid for phrase in _PURCHASE_TABLE_PHRASES)
        or "purchase commitments" in head
    )
    subform = period or credit or unfunded or purchase
    passed = head_hit and subform
    legs = (
        f"head={head_hit} period={period} credit={credit} "
        f"unfunded={unfunded} purchase={purchase}"
    )
    return AdmissionOutcome(
        "commitments_contingencies",
        JOINT_TEST_ID,
        passed,
        True,
        f"JOINT {legs}",
    )


EVALUATORS = {
    DEBT_TEST_ID: evaluate_debt_admission,
    JOINT_TEST_ID: evaluate_commitments_joint,
}


def apply_admissions(
    outcomes,
    claims,
    scores,
    vetoed,
    *,
    floor,
    score_type,
    evidence_type,
):
    """Seat the priced reads' claims on one geometry.
    J1 seats only residually; JOINT wherever unclaimed.
    Returns (seated families, scores)."""
    admission: list[str] = []
    for outcome in outcomes:
        if outcome.test_id not in (DEBT_TEST_ID, JOINT_TEST_ID):
            continue
        if not outcome.passed or outcome.family in vetoed:
            continue
        if outcome.family in claims:
            continue
        if outcome.test_id == DEBT_TEST_ID and claims:
            continue
        family = outcome.family
        claims.append(family)
        admission.append(family)
        existing = scores.get(family)
        if existing is None:
            scores = dict(scores)
            scores[family] = score_type(
                family,
                floor,
                {"admission": floor},
                (evidence_type("admission", outcome.detail, floor),),
            )
        elif existing.total < floor:
            lift = floor - existing.total
            channels = dict(existing.by_channel)
            channels["admission"] = channels.get("admission", 0.0) + lift
            scores = dict(scores)
            scores[family] = score_type(
                existing.family,
                floor,
                channels,
                existing.evidence + (evidence_type("admission", outcome.detail, lift),),
            )
    return admission, scores
