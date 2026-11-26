"""Measure-set evaluator for the form-test stage.

A filed form is a set of named measures, carried as columns or as
rows; the test counts the spec's priced groups present in the
table's stub, header and caption text, orientation-free."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.specs.measure_set_specs import (
    MEASURE_SET_SPECS_BY_TEST_ID,
    MeasureSetSpec,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.text.date_patterns import (
    MONTH_PATTERN,
    NUMERIC_DATE_RE,
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_SEARCH_RE,
)


@dataclass(frozen=True, slots=True)
class MeasureSetResult:
    """One measure-set evaluation: admission, evaluability, why."""

    admitted: bool
    evaluable: bool
    detail: str


def _texts(table: TypedTable) -> list[str]:
    """The match universe: row labels, header cells and joins, titles."""
    texts = [normalize_text(row.label) for row in table.rows if row.label]
    texts.extend(normalize_text(title) for title in table.caption.titles)
    for row in table.context.rows:
        if len(row) > 1 and not normalize_text(row[0]):
            cell = normalize_text(row[1])
            if cell:
                texts.append(cell)
    start = table.caption.consumed_rows
    zone = table.context.rows[start : start + table.header_rows + 2]
    width = max((len(row) for row in zone), default=0)
    for row in zone:
        texts.extend(normalize_text(cell) for cell in row if cell)
    for column in range(width):
        joined = " ".join(
            normalize_text(row[column])
            for row in zone
            if column < len(row) and normalize_text(row[column])
        )
        if joined:
            texts.append(joined)
    texts.extend(_head_year_variants(texts))
    return [text for text in texts if text]


_MONTH_DAY_BOOKEND_RE = re.compile(
    rf"^(?:gross\s+|net\s+)?balances?,?\s+(?:as\s+of\s+)?"
    rf"(?:{MONTH_PATTERN})\s*\d{{1,2}},?$"
)


def _head_year_variants(texts: list[str]) -> list[str]:
    """Dated forms of month-day bookend stubs, years from the texts.

    A balance stub carrying a month and day but no year is dated when
    the table's own head zone carries the year (at most four appended).
    """
    years: list[str] = []
    for text in texts:
        for year in YEAR_TOKEN_SEARCH_RE.findall(text):
            if year not in years:
                years.append(year)
    if not years:
        return []
    return [
        f"{text} {year}"
        for text in texts
        if _MONTH_DAY_BOOKEND_RE.match(text)
        for year in years[:4]
    ]


def _present(texts: list[str], phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for text in texts for phrase in phrases)


def _build_dated_bookend_re() -> re.Pattern[str]:
    """Compose the dated-bookend recognizer from the dates home."""
    md = rf"(?:{MONTH_PATTERN})\s*\d{{1,2}},? (?:{YEAR_TOKEN_PATTERN})"
    df = rf"\d{{1,2}} (?:{MONTH_PATTERN}),? (?:{YEAR_TOKEN_PATTERN})"
    mdy = rf"(?:{MONTH_PATTERN})\s*\d{{1,2}},?"
    qual = (
        "(?:"
        + "|".join(
            (
                r"\s*\([^()]*\)",
                r"\s*[-–—]\s*[a-z]+",
                r"\s*,\s*as\s+[a-z]+(?:\s+[a-z]+)?",
            )
        )
        + ")?"
    )
    connector = "(?:" + "|".join((r"at\s+", r"as at\s+", r"as of\s+")) + ")?"
    prefixes = (
        rf"balances?,?\s+{connector}",
        rf"balances?,?\s*[-–—]\s*",
        rf"totals?,?\s+(?:at\s+|as of\s+)?",
        rf"net\s+balances?,?\s+(?:at\s+|as of\s+)?",
        rf"goodwill\s+balances?,?\s+(?:at\s+|as of\s+)?",
        r"as of\s+",
        r"at\s+",
        rf"goodwill,?\s+(?:at\s+|as of\s+)?",
        rf"goodwill\s*[-–—]\s*",
        rf"goodwill\s*(?:\(\s*(?:gross|net)\s*\)|,?\s+(?:gross|net),?)"
        rf"\s+(?:at\s+|as of\s+)?",
        rf"accumulated impairment(?:\s+losses)?\s+(?:at\s+|as of\s+)?",
        rf"net carrying value,?\s+(?:at\s+|as of\s+)?",
        rf"carrying amount,?\s+(?:at\s+|as of\s+)?",
        rf"carrying value,?\s+(?:at\s+|as of\s+)?",
    )
    prefix = "(?:" + "|".join(prefixes) + ")?"
    core = "(?:" + "|".join((md, NUMERIC_DATE_RE.pattern, df, mdy)) + ")"
    year_end = (
        rf"(?:goodwill,?\s+(?:(?:gross|net),?\s*)?)?"
        rf"as of year[-\s]end (?:{YEAR_TOKEN_PATTERN})"
    )
    balance_year_end = rf"balances?,?\s+as of year[-\s]end (?:{YEAR_TOKEN_PATTERN})"
    year_first_year_end = (
        rf"balances?,?\s+as of (?:{YEAR_TOKEN_PATTERN})\s+year[-\s]end{qual}"
    )
    alts = (
        rf"{prefix}{core}{qual}",
        rf"{prefix}{md}{qual}\s+and\s+.+",
        rf"balances?,?\s+(?:{YEAR_TOKEN_PATTERN}){qual}",
        year_end,
        balance_year_end,
        year_first_year_end,
    )
    return re.compile("^(?:" + "|".join(alts) + ")$")


_DATED_BOOKEND_RE = _build_dated_bookend_re()


def _splits(
    table: TypedTable,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """Split the match universe: row labels, titles, zone, head,
    and the head rows' stub (first-cell) texts."""
    row_texts = [normalize_text(row.label) for row in table.rows if row.label]
    title_texts = [normalize_text(title) for title in table.caption.titles]
    start = table.caption.consumed_rows
    zone = table.context.rows[start : start + table.header_rows + 2]
    zone_texts: list[str] = []
    width = max((len(row) for row in zone), default=0)
    for row in zone:
        zone_texts.extend(normalize_text(cell) for cell in row if cell)
    for column in range(width):
        joined = " ".join(
            normalize_text(row[column])
            for row in zone
            if column < len(row) and normalize_text(row[column])
        )
        if joined:
            zone_texts.append(joined)
    head = table.context.rows[start : start + table.header_rows]
    head_texts = [normalize_text(cell) for row in head for cell in row if cell]
    head_stub_texts = [
        normalize_text(row[0]) for row in head if row and normalize_text(row[0])
    ]
    return (
        [text for text in row_texts if text],
        [text for text in title_texts if text],
        [text for text in zone_texts if text],
        [text for text in head_texts if text],
        head_stub_texts,
    )


def _qualified_dated(
    dated: set[str],
    row_texts: list[str],
    zone_texts: list[str],
    params: MeasureSetSpec,
    head_stub_texts: list[str] | None = None,
) -> set[str]:
    """The qualified dated set: stub-position texts (row labels
    or head stub cells), balance/subject-worded texts, and zone
    texts with a worded sibling (SEP4')."""
    worded = {t for t in dated if "balance" in t or "goodwill" in t}
    rows = set(row_texts) | set(head_stub_texts or ())
    zone = set(zone_texts)
    return {t for t in dated if t in rows or t in worded or (worded and t in zone)}


def _head_pair(head_texts: list[str], params: MeasureSetSpec) -> bool:
    """Transposed pair: two dated head cells plus a movement
    group among the header cells (HEAD')."""
    dated = {t for t in head_texts if _DATED_BOOKEND_RE.match(t)}
    if len(dated) < 2:
        return False
    bookends = set(params.date_bookend_groups)
    return any(
        _present(head_texts, group)
        for index, group in enumerate(params.groups)
        if index not in bookends
    )


def _subject_in_walk_position(
    title_texts: list[str],
    head_texts: list[str],
    row_texts: list[str],
    params: MeasureSetSpec,
) -> bool:
    """Walk-subject binding: subject in the titles, in the head
    cells, or in at least two distinct rows (SUBJ2'')."""
    if any(_present([t], params.subject_terms) for t in title_texts):
        return True
    if any(_present(head_texts, (term,)) for term in params.subject_terms):
        return True
    carriers = {t for t in row_texts if _present([t], params.subject_terms)}
    return len(carriers) >= 2


def _groups_admitted(present: list[bool], params: MeasureSetSpec) -> bool:
    """True when the hit vector clears min_groups and required."""
    return sum(present) >= params.min_groups and all(
        present[i] for i in params.required_groups
    )


def _dated_hits(
    present: list[bool], dated: set[str], params: MeasureSetSpec
) -> list[bool]:
    """Fold a dated-text set into the hit vector (the dated rule)."""
    hits = list(present)
    if dated:
        hits[params.date_bookend_groups[0]] = True
        if len(dated) >= 2:
            for index in params.date_bookend_groups:
                hits[index] = True
    return hits


def _dated_verdict(
    table: TypedTable,
    texts: list[str],
    present: list[bool],
    params: MeasureSetSpec,
) -> tuple[list[bool], bool]:
    """Dated-bookend composition: qualified dated set first, the
    transposed head-pair arm as its alternative, then the
    walk-subject binding over the admitted hits."""
    row_texts, title_texts, zone_texts, head_texts, head_stub_texts = _splits(table)
    dated = {t for t in texts if _DATED_BOOKEND_RE.match(t)}
    admitted = dated
    if params.dated_bookend_qualified:
        admitted = _qualified_dated(
            dated, row_texts, zone_texts, params, head_stub_texts
        )
    hits = _dated_hits(present, admitted, params)
    if (
        params.dated_bookend_qualified
        and not _groups_admitted(hits, params)
        and _head_pair(head_texts, params)
    ):
        hits = _dated_hits(present, dated, params)
    unbound = (
        params.subject_position_bound
        and _groups_admitted(hits, params)
        and not _subject_in_walk_position(title_texts, head_texts, row_texts, params)
    )
    return hits, unbound


def evaluate_measure_set(table: TypedTable, spec: FormTestSpec) -> MeasureSetResult:
    """Evaluate one table against one measure-set spec."""
    params = MEASURE_SET_SPECS_BY_TEST_ID[spec.test_id]
    texts = _texts(table)
    if not texts:
        return MeasureSetResult(False, False, "no stub or header text")
    refused = next(
        (term for term in params.refused_terms if _present(texts, (term,))),
        None,
    )
    if refused is not None:
        return MeasureSetResult(False, True, f"refused term present: {refused}")
    prose_tail = ""
    if params.subject_prose_tail_chars:
        prose_tail = (table.context.prose_before or "")[
            -params.subject_prose_tail_chars :
        ].lower()
    missing = next(
        (
            term
            for term in params.subject_terms
            if not _present(texts, (term,)) and term not in prose_tail
        ),
        None,
    )
    if missing is not None:
        return MeasureSetResult(False, True, f"subject absent: {missing}")
    present = [_present(texts, group) for group in params.groups]
    unbound = False
    if params.date_bookend_groups:
        present, unbound = _dated_verdict(table, texts, present, params)
    if unbound and any(term in prose_tail for term in params.subject_terms):
        unbound = False
    hits = sum(present)
    missing_required = next((i for i in params.required_groups if not present[i]), None)
    admitted = hits >= params.min_groups and missing_required is None and not unbound
    detail = (
        f"{hits} of {len(params.groups)} measure groups present"
        f" (needs {params.min_groups})"
    )
    if missing_required is not None:
        detail += f"; required group {missing_required} absent"
    if unbound:
        detail += "; subject not in walk position"
    return MeasureSetResult(admitted, True, detail)


def group_presence(table: TypedTable, test_id: str) -> tuple[bool, ...]:
    """The spec's raw per-group presence over the table's texts.

    Raw: before any dated-bookend folding — the presence vector
    the measure-set admission itself starts from."""
    params = MEASURE_SET_SPECS_BY_TEST_ID[test_id]
    texts = _texts(table)
    return tuple(_present(texts, group) for group in params.groups)
