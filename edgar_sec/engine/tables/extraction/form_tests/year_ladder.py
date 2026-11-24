"""Year-ladder form test: a forward ladder of periods with amounts.

Evaluates the ladder parameters declared as registry data
(year_ladder_specs.YEAR_LADDER_SPECS) against one table: step
order, amounts per step, and a total equal to its steps' sum.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.engine.forms.common.values.numbers import clean_numeric
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import (
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_SEARCH_RE,
)
from edgar_sec.foundation.text.date_years import is_year_token

from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.core.text.normalize import collapse_text
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    LADDER_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.form_specs.year_ladder_specs import (
    ANCHOR_AFTER_ASOF,
    ORIENT_COLUMNS,
    ORIENT_ROWS,
    THEREAFTER_REQUIRED,
    TOTAL_CORROBORATE,
    YearLadderSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TOTAL_ROW_RE,
    TypedTable,
    parse_caption_stack,
)

_THEREAFTER = build_alternation(
    ("thereafter", "later years", "remaining", rf"after\s+(?:{YEAR_TOKEN_PATTERN})")
)
_RANGE_SEP = build_alternation(("to", "-", "–", "—"))
_YEARS = build_alternation(("years?", "yrs?"))
_OPEN_PREFIX = build_alternation(("more than", "after", "over", "greater than"))
_FIRST_PREFIX = build_alternation(("less than", "within", "under", "first"))
_THEREAFTER_RE = re.compile(rf"(?:{_THEREAFTER})", re.IGNORECASE)
_ASOF_RE = re.compile(rf"as of\b[^()]*?({YEAR_TOKEN_PATTERN})", re.IGNORECASE)
_BUCKET_CLOSED_RE = re.compile(
    rf"(\d+)\s*(?:{_RANGE_SEP})\s*(\d+)\s*(?:{_YEARS})\b", re.IGNORECASE
)
_BUCKET_OPEN_RE = re.compile(
    rf"(?:{_OPEN_PREFIX})\s+(\d+)\s*(?:{_YEARS})\b", re.IGNORECASE
)
_BUCKET_FIRST_RE = re.compile(
    rf"(?:{_FIRST_PREFIX})\s+(\d+)\s*(?:{_YEARS})\b", re.IGNORECASE
)
_YEAR_RANGE_RE = re.compile(
    rf"({YEAR_TOKEN_PATTERN})\s*(?:{_RANGE_SEP})\s*({YEAR_TOKEN_PATTERN})"
)
_AMOUNT_RESIDUE_RE = re.compile(r"[\d\s,$().%+\-]")


@dataclass(frozen=True, slots=True)
class LadderStep:
    """One ladder step: a year, a year range, or an open final step."""

    kind: str
    start: int
    end: int | None


@dataclass(frozen=True, slots=True)
class YearLadderResult:
    """The ladder verdict for one table under one family's spec."""

    passed: bool
    axis: str | None
    kind: str | None
    steps: tuple[LadderStep, ...]
    thereafter: bool
    total_reconciles: bool | None


_FAILED = YearLadderResult(False, None, None, (), False, None)


def _amount(text: str) -> float | int | None:
    """The amount in a cell, when the cell is nothing but an amount."""
    stripped = text.strip()
    if not stripped or _AMOUNT_RESIDUE_RE.sub("", stripped):
        return None
    return clean_numeric(stripped)


def _is_year_cell(text: str) -> bool:
    """Whether a cell is a bare year label rather than an amount."""
    return is_year_token(text.strip())


def _step_for_label(label: str) -> LadderStep | str | None:
    """Classify one axis label: a step, a total, or neither."""
    text = collapse_text(label)
    if not text:
        return None
    if TOTAL_ROW_RE.match(text):
        return "total"
    if _THEREAFTER_RE.search(text):
        years = YEAR_TOKEN_SEARCH_RE.findall(text)
        start = int(years[-1]) + 1 if years else 0
        return LadderStep("open", start, None)
    bucket_open = _BUCKET_OPEN_RE.search(text)
    if bucket_open:
        return LadderStep("open", int(bucket_open.group(1)), None)
    bucket_closed = _BUCKET_CLOSED_RE.search(text)
    if bucket_closed:
        return LadderStep(
            "range", int(bucket_closed.group(1)), int(bucket_closed.group(2))
        )
    bucket_first = _BUCKET_FIRST_RE.search(text)
    if bucket_first:
        return LadderStep("range", 0, int(bucket_first.group(1)))
    year_range = _YEAR_RANGE_RE.search(text)
    if year_range:
        return LadderStep("range", int(year_range.group(1)), int(year_range.group(2)))
    years = YEAR_TOKEN_SEARCH_RE.findall(text)
    if len(years) == 1:
        year = int(years[0])
        return LadderStep("year", year, year)
    return None


def _split_grid(
    context: TableContext,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], int]:
    """Split a grid into caption lines, body rows, and grid width."""
    rows = context.rows
    caption = parse_caption_stack(rows)
    body = rows[caption.consumed_rows :]
    width = max((len(row) for row in rows), default=0)
    return caption.lines, body, width


def _header_zone(body: tuple[tuple[str, ...], ...]) -> int:
    """Count leading body rows that carry labels, not amounts."""
    count = 0
    for row in body:
        amounts = [
            cell
            for cell in row[1:]
            if _amount(cell) is not None and not _is_year_cell(cell)
        ]
        if amounts:
            break
        count += 1
    return count


def _column_labels(
    body: tuple[tuple[str, ...], ...], header_rows: int, width: int
) -> tuple[str, ...]:
    """The axis label heading each column, joined over the header."""
    labels = []
    for column in range(width):
        parts = [
            collapse_text(body[row][column])
            for row in range(header_rows)
            if column < len(body[row]) and body[row][column].strip()
        ]
        labels.append(" ".join(parts))
    return tuple(labels)


def _asof_year(caption_lines: tuple[str, ...], labels: tuple[str, ...]) -> int | None:
    """The balance-sheet year a table states, when it states one."""
    for text in (*caption_lines, *labels):
        match = _ASOF_RE.search(text)
        if match:
            return int(match.group(1))
    return None


def _reconciles(
    totals: list[float | int | None],
    step_values: list[list[float | int | None]],
    tolerance: float,
) -> bool | None:
    """Whether every complete line's steps sum to its stated total."""
    checked = False
    for index, total in enumerate(totals):
        steps = [
            values[index] if index < len(values) else None for values in step_values
        ]
        if total is None or any(step is None for step in steps):
            continue
        checked = True
        if abs(sum(steps) - total) > tolerance * max(1.0, abs(total)):
            return False
    return True if checked else None


def _judge_steps(
    steps: list[tuple[int, LadderStep]],
    amounts_ok: list[bool],
    spec: YearLadderSpec,
    asof_year: int | None,
) -> tuple[str, tuple[LadderStep, ...], bool] | None:
    """Judge one axis' ordered steps as a year or bucket ladder."""
    ordered = [step for _, step in steps]
    thereafter = bool(ordered and ordered[-1].kind == "open")
    core = ordered[:-1] if thereafter else ordered
    if any(step.kind == "open" for step in core):
        return None
    if not all(ok for _, ok in zip(steps, amounts_ok, strict=True)):
        return None
    if core and all(step.kind == "year" for step in core):
        years = [step.start for step in core]
        if len(years) < spec.min_year_steps:
            return None
        if any(later != earlier + 1 for earlier, later in zip(years, years[1:])):
            return None
        if spec.thereafter == THEREAFTER_REQUIRED and not thereafter:
            return None
        if spec.anchor == ANCHOR_AFTER_ASOF and asof_year is not None:
            if years[0] - asof_year not in (0, 1) or years[-1] <= asof_year:
                return None
        return "year", tuple(ordered), thereafter
    if not spec.bucket_ladder or not core:
        return None
    if any(step.kind not in ("range", "year") for step in core):
        return None
    spans = [(step.start, step.end or step.start) for step in core]
    if len(spans) < spec.min_bucket_steps:
        return None
    if any(later[0] < earlier[1] for earlier, later in zip(spans, spans[1:])):
        return None
    if not thereafter:
        return None
    return "bucket", tuple(ordered), thereafter


def _judge_axis(
    axis: str,
    labelled: list[tuple[int, LadderStep | str | None]],
    amount_at: list[list[float | int | None]],
    spec: YearLadderSpec,
    asof_year: int | None,
) -> YearLadderResult | None:
    """Judge one axis (columns or rows) of one table."""
    steps = [
        (position, item) for position, item in labelled if isinstance(item, LadderStep)
    ]
    totals = [position for position, item in labelled if item == "total"]
    if not steps:
        return None
    step_positions = [position for position, _ in steps]
    amounts_ok = [
        any(value is not None for value in amount_at[position])
        for position in step_positions
    ]
    judged = _judge_steps(steps, amounts_ok, spec, asof_year)
    if judged is None:
        return None
    kind, ordered, thereafter = judged
    total_reconciles: bool | None = None
    if totals and spec.total_mode == TOTAL_CORROBORATE:
        total_position = totals[0]
        if axis == ORIENT_COLUMNS:
            total_reconciles = _reconciles(
                [
                    amount_at[total_position][line]
                    for line in range(len(amount_at[total_position]))
                ],
                [amount_at[position] for position in step_positions],
                spec.tolerance,
            )
        else:
            total_reconciles = _reconciles(
                amount_at[total_position],
                [amount_at[position] for position in step_positions],
                spec.tolerance,
            )
        if total_reconciles is False:
            return None
    return YearLadderResult(True, axis, kind, ordered, thereafter, total_reconciles)


def evaluate_form_test_ladder(
    table: TypedTable, spec: FormTestSpec
) -> YearLadderResult:
    """Stage adapter: evaluate a declared ladder spec over a table."""
    ladder_spec = LADDER_SPECS_BY_TEST_ID.get(spec.test_id)
    if ladder_spec is None:
        return _FAILED
    return evaluate_year_ladder(table.context, ladder_spec)


def evaluate_year_ladder(
    table: TableContext | TypedTable, spec: YearLadderSpec
) -> YearLadderResult:
    """Evaluate one table against one family's year-ladder spec."""
    context = table.context if isinstance(table, TypedTable) else table
    caption_lines, body, width = _split_grid(context)
    if not body or width < 2:
        return _FAILED
    header_rows = _header_zone(body)
    data = body[header_rows:]
    if not data:
        return _FAILED
    asof_year = _asof_year(caption_lines, _column_labels(body, header_rows, width))
    if ORIENT_COLUMNS in spec.orientations and header_rows:
        labels = _column_labels(body, header_rows, width)
        labelled = [
            (column, _step_for_label(labels[column])) for column in range(1, width)
        ]
        amount_at = [
            [_amount(row[column]) if column < len(row) else None for row in data]
            for column in range(width)
        ]
        result = _judge_axis(ORIENT_COLUMNS, labelled, amount_at, spec, asof_year)
        if result is not None:
            return result
    if ORIENT_ROWS in spec.orientations:
        labelled = [
            (index, _step_for_label(row[0] if row else ""))
            for index, row in enumerate(data)
        ]
        amount_at = [[_amount(cell) for cell in row[1:]] for row in data]
        result = _judge_axis(ORIENT_ROWS, labelled, amount_at, spec, asof_year)
        if result is not None:
            return result
    return _FAILED
