"""Filter vocabulary shared by deterministic planning and selection policy.

This module holds only vocabulary and pure normalization: the default
suffix set and the suffix normalizer. It is Layer 1 because two
different layers need to agree on it --

* ``pipelines.filing_catalog.planner`` for deterministic planning, and
* ``engine.selection.policy.SelectionPolicy`` for Stage B selection.

Stage A originally kept this vocabulary in ``pipelines/filing_catalog/filters.py``
alongside the two SQL builders. Stage B could not reuse it: the layer graph is
acyclic downward-only, so Layer 3 (``engine``) may not import Layer 4
(``pipelines``). Rather than restate the suffix vocabulary in the selection
policy -- two closed sets that must never disagree -- the vocabulary moved down
here, and the SQL builders moved down with it to
``infra.storage.duckdb_catalog``.

v1 built its suffix predicate by interpolating both the column name and each
suffix straight into a SQL string literal, and ``normalize_suffixes`` only
lower-cased and de-dotted, so a suffix containing a quote could terminate the
literal. v2 rejects any suffix outside a conservative allowlist up front, which
fails loudly at the call site instead of producing malformed or injected SQL.

``DateSelection`` is the same kind of shared vocabulary: a union of tagged date
clauses that deterministic planning, the selection policy, and both SQL
compilers must agree about. It lives here for the same reason the suffix
vocabulary does -- two layers need one answer, and the lower layer cannot
import the higher one.

The grammar is deliberately small and total: every term either parses to a
clause or raises naming the offending token. Nothing is guessed. ``2023Q1`` is an
absolute quarter, ``@Q1[2023..2023]`` is the recurring quarter of 2023, and a bare
``Q1`` is an error rather than a guess at either one.
"""

from __future__ import annotations

import re
from calendar import monthrange
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from edgar_sec.foundation.text.dates import is_valid_year, parse_year_token

# Suffixes are user input arriving from a CLI flag or a policy document. Real SEC
# document names use letters, digits, and dots (``0001.htm`` is a real stub
# suffix), so the allowlist covers exactly that and rejects everything quote- or
# comment-shaped.
_SUFFIX_RE = re.compile(r"^[a-z0-9][a-z0-9.]*$")

DEFAULT_DOCUMENT_SUFFIXES: tuple[str, ...] = ()

# Recurring periods are calendar months and quarters of ``report_date``. The
# granularity names are part of the persisted policy document.
GRANULARITY_MONTH = "month"
GRANULARITY_QUARTER = "quarter"
RECURRING_GRANULARITIES = (GRANULARITY_MONTH, GRANULARITY_QUARTER)

QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}

_CLAUSE_ABSOLUTE = "absolute"
_CLAUSE_RECURRING = "recurring"

# Separators, kept as module constants so the grammar has exactly one spelling.
_RANGE_SEPARATOR = ".."
_RECUR_PREFIX = "@"
_RECUR_BRACKET_OPEN = "["
_RECUR_BRACKET_CLOSE = "]"
_QUARTER_MARKER = "Q"
_MONTH_MARKER = "M"
_QUARTER_ATOM_MARKER = "Q"

# One calendar day, the adjacency step for absolute intervals. Year spans use 1.
_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True, order=True)
class AbsoluteDateClause:
    """One continuous inclusive interval on ``report_date``.

    ``None`` on either bound means the interval is open at that end. An open
    bound is never resolved against a catalog's latest date: an open bound means
    "every year the catalog holds", which is a statement about the reader's
    intent rather than about today's data.
    """

    start_date: date | None
    end_date: date | None

    def __post_init__(self) -> None:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError(
                f"date interval starts after it ends: {self.iso_start}..{self.iso_end}"
            )

    @property
    def iso_start(self) -> str | None:
        return self.start_date.isoformat() if self.start_date else None

    @property
    def iso_end(self) -> str | None:
        return self.end_date.isoformat() if self.end_date else None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": _CLAUSE_ABSOLUTE,
            "start_date": self.iso_start,
            "end_date": self.iso_end,
        }


@dataclass(frozen=True, slots=True, order=True)
class RecurringDateClause:
    """Selected calendar months or quarters, repeated over an inclusive year range.

    ``@Q1[2011..2015]`` keeps Q1 of 2011 through 2015 and drops the rest of each
    year; ``@Q1`` keeps Q1 of every year present. The two are different
    selections and the grammar keeps them apart.
    """

    granularity: str
    values: tuple[int, ...]
    start_year: int | None
    end_year: int | None

    def __post_init__(self) -> None:
        if self.granularity not in RECURRING_GRANULARITIES:
            raise ValueError(
                f"recurring granularity must be one of "
                f"{', '.join(RECURRING_GRANULARITIES)}; got {self.granularity!r}"
            )
        if not self.values:
            raise ValueError("a recurring clause must name at least one period")
        limit = 12 if self.granularity == GRANULARITY_MONTH else 4
        for value in self.values:
            if not 1 <= value <= limit:
                raise ValueError(
                    f"{self.granularity} value {value} is outside 1..{limit}"
                )
        for year in (self.start_year, self.end_year):
            if year is not None and not is_valid_year(year):
                raise ValueError(f"year {year} is outside the valid range")
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.start_year > self.end_year
        ):
            raise ValueError(
                f"recurring year range starts after it ends: "
                f"{self.start_year}..{self.end_year}"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": _CLAUSE_RECURRING,
            "granularity": self.granularity,
            "values": list(self.values),
            "start_year": self.start_year,
            "end_year": self.end_year,
        }


# One clause of either kind. Callers that persist or compare a selection need the
# distinction; callers that only filter do not.
DateClause = AbsoluteDateClause | RecurringDateClause
DateSelection = tuple[DateClause, ...]


def _end_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _parse_year_atom(token: str, source: str) -> int:
    year = parse_year_token(token)
    if year is None:
        raise ValueError(f"invalid year {source!r}")
    return year


def _absolute_atom(token: str) -> tuple[date, date]:
    """Expand one absolute atom into the inclusive interval it names.

    Precision is carried by the token's own shape. The caller picks which edge
    of that interval a position needs: ``2005Q3`` yields ``2005-07-01`` and
    ``2008-03-31``, so the same atom supplies a start edge or an end edge
    depending on which side of ``..`` it sits.
    """
    source = token.strip()
    if not source:
        raise ValueError("empty date term")

    if _QUARTER_ATOM_MARKER in source:
        year_text, _, quarter_text = source.partition(_QUARTER_ATOM_MARKER)
        year = _parse_year_atom(year_text, source)
        if len(quarter_text) != 1 or quarter_text not in "1234":
            raise ValueError(
                f"invalid quarter in {source!r}; expected a year followed by Q1-Q4"
            )
        quarter = int(quarter_text)
        first_month, last_month = QUARTER_MONTHS[quarter]
        start = date(year, first_month, 1)
        end = _end_of_month(year, last_month)
    else:
        parts = source.split("-")
        if len(parts) == 1:
            year = _parse_year_atom(parts[0], source)
            start, end = date(year, 1, 1), date(year, 12, 31)
        elif len(parts) == 2:
            year = _parse_year_atom(parts[0], source)
            month = _month_number(parts[1], source)
            start, end = date(year, month, 1), _end_of_month(year, month)
        elif len(parts) == 3:
            year = _parse_year_atom(parts[0], source)
            month = _month_number(parts[1], source)
            day_text = parts[2]
            if not day_text.isdigit():
                raise ValueError(f"invalid day in {source!r}")
            day = int(day_text)
            try:
                start = end = date(year, month, day)
            except ValueError as exc:
                raise ValueError(f"invalid calendar date {source!r}: {exc}") from None
        else:
            raise ValueError(
                f"invalid date term {source!r}; expected YYYY, YYYYMQ, YYYY-MM, "
                "or YYYY-MM-DD"
            )

    return start, end


def _month_number(token: str, source: str) -> int:
    if not token.isdigit():
        raise ValueError(f"invalid month in {source!r}")
    month = int(token)
    if not 1 <= month <= 12:
        raise ValueError(f"month {token} in {source!r} is outside 1..12")
    return month


def _parse_absolute(token: str) -> AbsoluteDateClause:
    parts = token.split(_RANGE_SEPARATOR)
    if len(parts) == 1:
        start, end = _absolute_atom(parts[0])
        return AbsoluteDateClause(start_date=start, end_date=end)
    if len(parts) != 2:
        raise ValueError(f"invalid date range {token!r}")
    left, right = parts
    if not left and not right:
        raise ValueError(
            "a date range needs at least one endpoint; '..' on its own is the "
            "empty selection, which is written as an empty value"
        )
    start = _absolute_atom(left)[0] if left else None
    end = _absolute_atom(right)[1] if right else None
    return AbsoluteDateClause(start_date=start, end_date=end)


def _parse_recurring(token: str) -> RecurringDateClause:
    body = token[len(_RECUR_PREFIX) :]
    bracket = body.find(_RECUR_BRACKET_OPEN)
    if bracket < 0:
        if _RECUR_BRACKET_CLOSE in body:
            raise ValueError(f"unbalanced year range in {token!r}")
        period_text, year_text = body, ""
    else:
        if not body.endswith(_RECUR_BRACKET_CLOSE):
            raise ValueError(f"unbalanced year range in {token!r}")
        period_text = body[:bracket]
        year_text = body[bracket + 1 : -1]

    granularity, values = _parse_periods(period_text, token)

    start_year: int | None = None
    end_year: int | None = None
    if year_text != "":
        bounds = year_text.split(_RANGE_SEPARATOR)
        if len(bounds) != 2:
            raise ValueError(f"year range in {token!r} must be written as [YEAR..YEAR]")
        if bounds[0]:
            start_year = _parse_year_atom(bounds[0].strip(), token)
        if bounds[1]:
            end_year = _parse_year_atom(bounds[1].strip(), token)
        if start_year is None and end_year is None and year_text.strip() != "":
            raise ValueError(f"empty year range in {token!r}")
    return RecurringDateClause(
        granularity=granularity,
        values=values,
        start_year=start_year,
        end_year=end_year,
    )


def _parse_periods(period_text: str, source: str) -> tuple[str, tuple[int, ...]]:
    marker = period_text[:1]
    digits = period_text[1:]
    if marker == _QUARTER_MARKER:
        if len(digits) != 1 or digits not in "1234":
            raise ValueError(
                f"invalid recurring quarter in {source!r}; expected @Q1 through @Q4"
            )
        return GRANULARITY_QUARTER, (int(digits),)
    if marker == _MONTH_MARKER:
        if not 1 <= len(digits) <= 2 or not digits.isdigit():
            raise ValueError(
                f"invalid recurring month in {source!r}; expected @M01 through @M12"
            )
        month = int(digits)
        if not 1 <= month <= 12:
            raise ValueError(f"recurring month in {source!r} is outside 1..12")
        return GRANULARITY_MONTH, (month,)
    raise ValueError(
        f"invalid recurring period in {source!r}; expected @Q1-@Q4 or @M01-@M12"
    )


def _shift(value: Any, step: Any) -> Any:
    """Return ``value + step``, saturating at the domain's upper bound.

    ``date.max + timedelta(days=1)`` raises, and a caller may legitimately build
    a clause ending at the last representable day.
    """
    try:
        return value + step
    except OverflowError:
        return value


def _overlaps_or_touches(end: Any, next_start: Any, step: Any) -> bool:
    """Return whether two sorted intervals share a point or abut.

    An open end swallows whatever follows it, so it always merges. Adjacency
    counts: ``2024-12-31`` and ``2025-01-01`` describe one contiguous interval,
    and merging them keeps ``2024-12-31..2025-01-01`` out of a persisted
    selection where it would read as two overlapping windows.
    ``step`` is the domain's granularity -- a day for dates, ``1`` for year spans.
    """
    if end is None or next_start is None:
        return True
    return next_start <= _shift(end, step)


def _interval_sort_key(
    item: tuple[Any, Any],
) -> tuple[tuple[bool, Any], tuple[bool, Any]]:
    """Sort key placing an open bound ahead of every closed one.

    The flag is compared before the value, so an open bound sorts first without
    needing a sentinel that would have to be typed per domain.
    """
    start, end = item
    return (start is not None, start), (end is not None, end)


def _merge_intervals(
    intervals: Sequence[tuple[Any, Any]],
    step: Any,
) -> tuple[tuple[Any, Any], ...]:
    """Merge overlapping and abutting intervals into a minimal disjoint set."""
    if not intervals:
        return ()
    ordered = sorted(intervals, key=_interval_sort_key)
    merged: list[tuple[Any, Any]] = []
    current_start, current_end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if _overlaps_or_touches(current_end, next_start, step):
            # An open end wins the union: dropping it would silently turn
            # ``..2007`` plus ``2008..`` into a bounded interval that no longer
            # describes what the caller asked for.
            if next_end is None:
                current_end = None
            elif current_end is not None and next_end > current_end:
                current_end = next_end
            continue
        merged.append((current_start, current_end))
        current_start, current_end = next_start, next_end
    merged.append((current_start, current_end))
    return tuple(merged)


def _merge_absolute(
    clauses: Iterable[AbsoluteDateClause],
) -> tuple[AbsoluteDateClause, ...]:
    """Merge absolute intervals, dropping any that cover every date.

    ``..2007`` plus ``2008..`` is every date, and the one canonical way to write
    that is the empty selection: a clause with both bounds open would have to be
    spelled ``..``, which the grammar rejects as ambiguous with "no selection".
    Collapsing it also keeps the missing-date rule honest -- an input that asks
    for every date must not start excluding rows whose ``report_date`` is
    unreadable.
    """
    merged = _merge_intervals([(c.start_date, c.end_date) for c in clauses], _DAY)
    return tuple(
        AbsoluteDateClause(start, end)
        for start, end in merged
        if start is not None or end is not None
    )


def _covers_year(
    interval: tuple[int | None, int | None],
    segment: tuple[int | None, int | None],
) -> bool:
    """Return whether one year interval spans a whole year segment."""
    start, end = interval
    segment_start, segment_end = segment
    if start is not None and (segment_start is None or start > segment_start):
        return False
    return not (end is not None and (segment_end is None or end < segment_end))


def _year_segments(
    intervals: Sequence[tuple[int | None, int | None]],
) -> tuple[tuple[int | None, int | None], ...]:
    """Split the timeline into segments no interval boundary falls inside.

    Cutting at every boundary makes the segments a function of the intervals
    alone, which is what makes the decomposition canonical: two spellings of the
    same recurring selection reduce to the same intervals first, and therefore to
    the same segments.
    """
    boundaries: set[int] = set()
    for start, end in intervals:
        if start is not None:
            boundaries.add(start)
        if end is not None:
            boundaries.add(end + 1)
    if not boundaries:
        return ((None, None),)
    ordered = sorted(boundaries)
    segments: list[tuple[int | None, int | None]] = [(None, ordered[0] - 1)]
    segments.extend(
        (year, ordered[index + 1] - 1 if index + 1 < len(ordered) else None)
        for index, year in enumerate(ordered)
    )
    return tuple(segments)


def _merge_recurring(
    clauses: Iterable[RecurringDateClause],
) -> tuple[RecurringDateClause, ...]:
    """Collapse recurring clauses to one clause per year segment.

    Each granularity is reduced twice. First per period value, so overlapping and
    abutting spans for the same period become one span; then across the
    timeline, so periods whose spans abut can share a clause. Reducing per value
    before slicing matters: ``@Q1,@Q2[2011..2015]`` keeps Q1 in every year and
    Q2 only in 2011-2015, and a rule that merged the two values' spans first
    would widen it to Q2 in every year.
    """
    grouped: dict[str, list[tuple[int, tuple[int | None, int | None]]]] = {}
    for clause in clauses:
        grouped.setdefault(clause.granularity, []).extend(
            (value, (clause.start_year, clause.end_year)) for value in clause.values
        )

    merged: list[RecurringDateClause] = []
    for granularity in sorted(grouped):
        per_value: dict[int, list[tuple[int | None, int | None]]] = {}
        for value, span in grouped[granularity]:
            per_value.setdefault(value, []).append(span)
        per_value = {
            value: list(_merge_intervals(spans, 1))
            for value, spans in per_value.items()
        }
        segments = _year_segments(
            [span for spans in per_value.values() for span in spans]
        )
        labelled: list[tuple[tuple[int | None, int | None], tuple[int, ...]]] = []
        for segment in segments:
            values = tuple(
                sorted(
                    value
                    for value, spans in per_value.items()
                    if any(_covers_year(span, segment) for span in spans)
                )
            )
            if not values:
                continue
            if (
                labelled
                and labelled[-1][1] == values
                and labelled[-1][0][1] is not None
                and labelled[-1][0][1] + 1 == segment[0]
            ):
                previous, _ = labelled[-1]
                labelled[-1] = ((previous[0], segment[1]), values)
                continue
            labelled.append((segment, values))
        merged.extend(
            RecurringDateClause(
                granularity=granularity,
                values=values,
                start_year=segment[0],
                end_year=segment[1],
            )
            for segment, values in labelled
        )
    return tuple(merged)


def normalize_date_selection(clauses: Iterable[DateClause]) -> DateSelection:
    """Return the canonical form of a selection.

    Canonical means two selections that select the same dates have the same
    value, because that value is what a plan identity and a policy fingerprint
    hash. Absolute intervals are merged and sorted; recurring clauses are
    collapsed to one clause per granularity and year span with their periods
    collected. Absolute clauses come first, then recurring clauses.
    """
    absolute: list[AbsoluteDateClause] = []
    recurring: list[RecurringDateClause] = []
    for clause in clauses:
        if isinstance(clause, RecurringDateClause):
            recurring.append(clause)
        elif isinstance(clause, AbsoluteDateClause):
            absolute.append(clause)
        else:
            raise ValueError(f"unknown date clause type: {type(clause).__name__}")
    return _merge_absolute(absolute) + _merge_recurring(recurring)


def parse_date_selection(value: str) -> DateSelection:
    """Parse the ``--dates`` grammar into a canonical selection.

    The grammar is a comma-separated union; each element is an absolute
    interval, an absolute atom, or a recurring period. An empty value selects
    every date, which is a distinct answer from a nonempty selection: a
    nonempty selection excludes rows whose ``report_date`` is missing or
    unparseable, because the predicate cannot place them.
    """
    if not isinstance(value, str):
        raise ValueError(f"date selection must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return ()

    clauses: list[DateClause] = []
    for raw in text.split(","):
        token = raw.strip()
        if not token:
            raise ValueError(f"empty date term in {value!r}")
        if token.startswith(_RECUR_PREFIX):
            clauses.append(_parse_recurring(token))
        elif _QUARTER_ATOM_MARKER in token:
            clauses.append(_parse_absolute(token))
        else:
            clauses.append(_parse_absolute(token))
    return normalize_date_selection(clauses)


def date_selection_to_json(selection: DateSelection) -> list[dict[str, Any]]:
    """Return the persisted form of a selection, ready for canonical JSON."""
    return [clause.to_json() for clause in selection]


def date_selection_from_json(payload: Sequence[Any]) -> DateSelection:
    """Rebuild a selection from its persisted form, then re-canonicalize.

    Re-normalizing matters because a policy document is hand-editable: a draft
    listing overlapping spans must fingerprint as the same selection the parser
    would have produced, or an unchanged policy would get a new identity.
    """
    clauses: list[DateClause] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError(f"date clause must be an object, got {entry!r}")
        kind = entry.get("kind")
        if kind == _CLAUSE_ABSOLUTE:
            clauses.append(
                AbsoluteDateClause(
                    start_date=_json_date(entry.get("start_date"), "start_date"),
                    end_date=_json_date(entry.get("end_date"), "end_date"),
                )
            )
        elif kind == _CLAUSE_RECURRING:
            granularity = entry.get("granularity")
            values = entry.get("values")
            if not isinstance(values, list) or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in values
            ):
                raise ValueError(
                    f"recurring clause values must be a list of integers; got {values!r}"
                )
            clauses.append(
                RecurringDateClause(
                    granularity=str(granularity),
                    values=tuple(sorted(set(values))),
                    start_year=_json_year(entry.get("start_year"), "start_year"),
                    end_year=_json_year(entry.get("end_year"), "end_year"),
                )
            )
        else:
            raise ValueError(
                f"date clause kind must be 'absolute' or 'recurring'; got {kind!r}"
            )
    return normalize_date_selection(clauses)


def _json_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} is not an ISO date: {value!r}") from None


def _json_year(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer year, got {value!r}")
    return value


def format_date_selection(selection: DateSelection) -> str:
    """Render a selection in the ``--dates`` grammar, for reports and prompts."""
    terms: list[str] = []
    for clause in selection:
        if isinstance(clause, RecurringDateClause):
            if clause.granularity == GRANULARITY_MONTH:
                periods = ",".join(f"@M{value:02d}" for value in clause.values)
            else:
                periods = ",".join(f"@Q{value}" for value in clause.values)
            span = ""
            if clause.start_year is not None or clause.end_year is not None:
                low = "" if clause.start_year is None else str(clause.start_year)
                high = "" if clause.end_year is None else str(clause.end_year)
                span = (
                    f"{_RECUR_BRACKET_OPEN}{low}{_RANGE_SEPARATOR}{high}"
                    f"{_RECUR_BRACKET_CLOSE}"
                )
            terms.append(f"{periods}{span}")
            continue
        start = clause.iso_start or ""
        end = clause.iso_end or ""
        terms.append(f"{start}{_RANGE_SEPARATOR}{end}")
    return ",".join(terms)


def normalize_suffixes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Lower-case, de-dot, de-duplicate, and validate document suffixes.

    Order is preserved because a plan's recorded suffix list participates in
    the plan identity hash; de-duplication keeps that hash stable when a caller
    repeats a suffix.
    """
    normalized: list[str] = []
    for suffix in values:
        if not isinstance(suffix, str):
            raise ValueError(f"suffix must be a string, got {type(suffix).__name__}")
        token = suffix.strip().lower().lstrip(".")
        if not token:
            continue
        if not _SUFFIX_RE.match(token):
            raise ValueError(
                f"invalid document suffix {suffix!r}; expected letters, digits, "
                "or dots only"
            )
        if token not in normalized:
            normalized.append(token)
    return tuple(normalized)


__all__ = [
    "DEFAULT_DOCUMENT_SUFFIXES",
    "GRANULARITY_MONTH",
    "GRANULARITY_QUARTER",
    "QUARTER_MONTHS",
    "RECURRING_GRANULARITIES",
    "AbsoluteDateClause",
    "DateClause",
    "DateSelection",
    "RecurringDateClause",
    "date_selection_from_json",
    "date_selection_to_json",
    "format_date_selection",
    "normalize_date_selection",
    "normalize_suffixes",
    "parse_date_selection",
]
