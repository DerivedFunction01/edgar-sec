"""Geometry and text candidate extraction for cover checkbox inference."""

from __future__ import annotations

import re
from collections.abc import Sequence

from defs.regex import build_alternation
from defs.sec_forms.cover.checkmark_models import CheckboxCandidate
from defs.sec_forms.cover.models import CoverBoundary
from defs.tables.protection import mask_tagged_tables
from defs.taxonomy.components.cover import (
    FILER_ACCELERATED,
    FILER_EMERGING_GROWTH,
    FILER_LARGE_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
    FILER_STATUS_GROUP,
    REPORT_ANNUAL,
    REPORT_PERIOD_GROUP,
    REPORT_QUARTERLY,
    REPORT_TRANSITION,
    STAT_COMPLIANT_12_MONTHS,
    STAT_EGC_TRANSITION_OPTOUT,
    STAT_ERROR_CORRECTION,
    STAT_RECOVERY_ANALYSIS,
    STAT_SHELL,
    STAT_SOX_404B,
    STAT_VOLUNTARY,
    STAT_WKSI,
    STATUTORY_BINARY_GROUP,
)
from defs.text.dates import parse_date

_MARK_TOKENS = (
    "[X]",
    "[x]",
    "[ ]",
    "(X)",
    "(x)",
    "☒",
    "☑",
    "☐",
    "□",
    "✓",
    "✔",
    "✘",
    "●",
    "■",
    "▪",
    "•",
    "*",
    "+",
    "-",
    "x",
    "X",
    "o",
    "O",
    "þ",
    "ý",
    "r",
    "R",
)
_MARK_RE = re.compile(
    rf"(?<!\w)(?:{build_alternation(_MARK_TOKENS, auto_escape=True)})(?!\w)"
)
_LABELS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (REPORT_ANNUAL, ("annual report", "annual report pursuant"), REPORT_PERIOD_GROUP),
    (
        REPORT_QUARTERLY,
        ("quarterly report", "quarterly report pursuant"),
        REPORT_PERIOD_GROUP,
    ),
    (
        REPORT_TRANSITION,
        ("transition report", "transition report pursuant"),
        REPORT_PERIOD_GROUP,
    ),
    (
        FILER_LARGE_ACCELERATED,
        ("large accelerated filer",),
        FILER_STATUS_GROUP,
    ),
    (FILER_ACCELERATED, ("accelerated filer",), FILER_STATUS_GROUP),
    (
        FILER_NON_ACCELERATED,
        ("non-accelerated filer", "non accelerated filer"),
        FILER_STATUS_GROUP,
    ),
    (
        FILER_SMALLER_REPORTING,
        ("smaller reporting company",),
        FILER_STATUS_GROUP,
    ),
    (FILER_EMERGING_GROWTH, ("emerging growth company",), FILER_STATUS_GROUP),
    (
        STAT_WKSI,
        ("well-known seasoned issuer", "well known seasoned issuer"),
        STATUTORY_BINARY_GROUP,
    ),
    (STAT_SHELL, ("shell company",), STATUTORY_BINARY_GROUP),
    (
        STAT_VOLUNTARY,
        ("voluntary filer", "not required to file reports"),
        STATUTORY_BINARY_GROUP,
    ),
    (
        STAT_COMPLIANT_12_MONTHS,
        (
            "preceding 12 months",
            "preceding twelve months",
            "has filed all reports required",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    (
        STAT_SOX_404B,
        ("404(b)", "auditor attestation", "independent auditor"),
        STATUTORY_BINARY_GROUP,
    ),
    (
        STAT_EGC_TRANSITION_OPTOUT,
        ("extended transition", "transition period for complying"),
        STATUTORY_BINARY_GROUP,
    ),
    (
        STAT_ERROR_CORRECTION,
        ("error correction", "error corrections"),
        STATUTORY_BINARY_GROUP,
    ),
    (STAT_RECOVERY_ANALYSIS, ("recovery analysis",), STATUTORY_BINARY_GROUP),
)


def _label_matches(text: str) -> list[tuple[str, str, int, int, str]]:
    matches: list[tuple[str, str, int, int, str]] = []
    for key, phrases, group in _LABELS:
        for phrase in phrases:
            for match in re.finditer(re.escape(phrase), text, re.IGNORECASE):
                matches.append((key, phrase, match.start(), match.end(), group))
    matches.sort(key=lambda item: (item[2], -(item[3] - item[2])))
    accepted: list[tuple[str, str, int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for match in matches:
        if any(match[2] < end and match[3] > start for start, end in occupied):
            continue
        accepted.append(match)
        occupied.append((match[2], match[3]))
    return accepted


def _mark_matches(text: str, *, allow_asterisk: bool = False) -> list[re.Match[str]]:
    matches = list(_MARK_RE.finditer(text))
    if allow_asterisk:
        return matches
    return [
        match
        for match in matches
        if match.group(0) != "*" or re.search(r"\b(?:yes|no)\b", text, re.IGNORECASE)
    ]


def _answer_for_mark(text: str, start: int, end: int) -> str | None:
    nearby = [
        (abs(match.start() - end), match.group(1).lower())
        for match in re.finditer(r"\b(yes|no)\b", text, re.IGNORECASE)
        if start - 32 <= match.start() <= end + 32
    ]
    return min(nearby)[1] if nearby else None


def _date_present(text: str) -> bool:
    return parse_date(text) is not None


def _yes_no_candidates(
    cells: Sequence[
        tuple[int, str, list[tuple[str, str, int, int, str]], list[re.Match[str]]]
    ],
    *,
    table_index: int,
    row_index: int,
) -> list[CheckboxCandidate]:
    """Extract a binary pair from a table row containing only Yes/No answers."""
    if any(found for _, _, found, _ in cells):
        return []
    entries: list[tuple[str, int, int, re.Match[str]]] = []
    for _, text, _, marks in cells:
        answers = list(re.finditer(r"\b(yes|no)\b", text, re.IGNORECASE))
        if len(answers) != 1 or len(marks) != 1:
            continue
        entries.append(
            (
                answers[0].group(1).lower(),
                answers[0].start(),
                answers[0].end(),
                marks[0],
            )
        )
    if {answer for answer, _, _, _ in entries} != {"yes", "no"}:
        return []
    question_key = f"table_yes_no:{table_index}:{row_index}"
    candidates: list[CheckboxCandidate] = []
    for column, text, _, marks in cells:
        answers = list(re.finditer(r"\b(yes|no)\b", text, re.IGNORECASE))
        if len(answers) != 1 or len(marks) != 1:
            continue
        answer = answers[0]
        candidates.append(
            _candidate_from_match(
                key=question_key,
                group=STATUTORY_BINARY_GROUP,
                token=marks[0],
                label=(answer.group(0), answer.start(), answer.end()),
                row_text=text,
                source_region=f"table-{table_index}/row-{row_index}/column-{column}",
                row=row_index,
                column=column,
                orientation="same_cell",
                mark_span=(marks[0].start(), marks[0].end()),
            )
        )
    return candidates


def _candidate_from_match(
    *,
    key: str,
    group: str,
    token: re.Match[str],
    label: tuple[str, int, int],
    row_text: str,
    source_region: str,
    row: int | None = None,
    column: int | None = None,
    orientation: str = "",
    mark_span: tuple[int, int] | None = None,
) -> CheckboxCandidate:
    label_text, label_start, label_end = label
    answer = _answer_for_mark(row_text, token.start(), token.end())
    return CheckboxCandidate(
        semantic_key=key,
        source_token=token.group(0),
        group=group,
        answer=answer,
        question_key=key if answer is not None else None,
        source_region=source_region,
        row=row,
        column=column,
        orientation=orientation,
        date_valid=_date_present(row_text),
        label_span=(label_start, label_end),
        mark_span=mark_span or (token.start(), token.end()),
        label_text=label_text,
    )


def extract_table_candidates(
    geometry: object,
    *,
    table_index: int,
) -> tuple[CheckboxCandidate, ...]:
    """Extract semantic candidates from logical table rows and cell geometry."""
    rows = tuple(getattr(geometry, "rows", ()))
    candidates: list[CheckboxCandidate] = []
    row_cells: list[
        list[tuple[int, str, list[tuple[str, str, int, int, str]], list[re.Match[str]]]]
    ] = []
    for row in rows:
        cells = list(row)
        row_data = []
        for column, cell in enumerate(cells):
            text = str(cell)
            labels = () if text.lstrip().startswith("(") else _label_matches(text)
            row_data.append(
                (column, text, list(labels), _mark_matches(text, allow_asterisk=True))
            )
        row_cells.append(row_data)

    used_vertical_labels: set[tuple[int, int]] = set()
    for row_index, cells in enumerate(row_cells):
        row_text = " ".join(cell[1] for cell in cells)
        labels = [(column, item) for column, _, found, _ in cells for item in found]
        marks = [(column, match) for column, _, _, found in cells for match in found]
        yes_no = _yes_no_candidates(cells, table_index=table_index, row_index=row_index)
        if yes_no:
            candidates.extend(yes_no)
            continue
        for label_column, (key, phrase, start, end, group) in labels:
            same_cell = [
                (column, match) for column, match in marks if column == label_column
            ]
            related = (
                same_cell
                or sorted(
                    marks,
                    key=lambda item: abs(item[0] - label_column),
                )[:1]
            )
            for mark_column, mark in related:
                orientation = (
                    "left_of_label"
                    if mark_column < label_column
                    else "right_of_label"
                    if mark_column > label_column
                    else "same_cell"
                )
                candidates.append(
                    _candidate_from_match(
                        key=key,
                        group=group,
                        token=mark,
                        label=(phrase, start, end),
                        row_text=row_text,
                        source_region=f"table-{table_index}/row-{row_index}/column-{mark_column}",
                        row=row_index,
                        column=mark_column,
                        orientation=orientation,
                        mark_span=(mark.start(), mark.end()),
                    )
                )
        if labels:
            continue
        for column, cell_text, _, marks_in_cell in cells:
            if not marks_in_cell:
                continue
            label_rows = []
            for other_row in (row_index - 1, row_index + 1):
                if not 0 <= other_row < len(row_cells):
                    continue
                label_cells = [item for item in row_cells[other_row] if item[2]]
                if label_cells:
                    label_rows.append((other_row, label_cells))
            if not label_rows:
                continue
            label_options = [
                (other_row, item)
                for other_row, label_cells in label_rows
                for item in label_cells
            ]
            unused_options = [
                option
                for option in label_options
                if (option[0], option[1][0]) not in used_vertical_labels
            ]
            other_row, (label_column, _, found, _) = min(
                unused_options or label_options,
                key=lambda item: abs(item[0] - row_index) + abs(item[1][0] - column),
            )
            used_vertical_labels.add((other_row, label_column))
            key, phrase, start, end, group = found[0]
            orientation = "above_label" if row_index < other_row else "below_label"
            for mark in marks_in_cell:
                candidates.append(
                    _candidate_from_match(
                        key=key,
                        group=group,
                        token=mark,
                        label=(phrase, start, end),
                        row_text=f"{cell_text} {row_cells[other_row][label_column][1]}",
                        source_region=f"table-{table_index}/row-{row_index}/column-{column}",
                        row=row_index,
                        column=column,
                        orientation=orientation,
                        mark_span=(mark.start(), mark.end()),
                    )
                )
    return tuple(candidates)


def extract_cover_candidates(
    text: str,
    boundary: CoverBoundary,
    *,
    family: str,
    table_geometries: Sequence[object] = (),
) -> tuple[CheckboxCandidate, ...]:
    """Extract candidates from the bounded cover and retained table grids."""
    del family
    if boundary.end_line is None:
        return ()
    candidates: list[CheckboxCandidate] = []
    _, table_spans = mask_tagged_tables(text)
    table_line_numbers = tuple(text.count("\n", 0, span.start) for span in table_spans)
    for table_index, geometry in enumerate(table_geometries):
        if table_index >= len(table_line_numbers):
            continue
        table_line = table_line_numbers[table_index]
        if table_line < (boundary.start_line or 0) or table_line >= boundary.end_line:
            continue
        candidates.extend(extract_table_candidates(geometry, table_index=table_index))

    masked, _ = mask_tagged_tables(text)
    lines = masked.splitlines(keepends=True)
    line_offsets: list[int] = []
    offset = 0
    for raw_line in lines:
        line_offsets.append(offset)
        offset += len(raw_line)
    for line_index, raw_line in enumerate(lines[: boundary.end_line]):
        line = raw_line.rstrip("\r\n")
        if line_index < (boundary.start_line or 0):
            continue
        labels = _label_matches(line)
        if not labels:
            continue
        line_marks = _mark_matches(line)
        for label_index, (key, phrase, start, end, group) in enumerate(labels):
            if len(labels) == len(line_marks):
                mark_refs = [(line_index, line_marks[label_index])]
            elif len(labels) == 1:
                mark_refs = [(line_index, mark) for mark in line_marks]
            elif line_marks:
                mark_refs = [
                    (
                        line_index,
                        min(line_marks, key=lambda mark: abs(mark.start() - start)),
                    )
                ]
            else:
                mark_refs = []
            if not mark_refs:
                for nearby_index in range(
                    max(boundary.start_line or 0, line_index - 2),
                    min(boundary.end_line, line_index + 3),
                ):
                    if nearby_index == line_index:
                        continue
                    mark_refs.extend(
                        (nearby_index, mark)
                        for mark in _mark_matches(lines[nearby_index].rstrip("\r\n"))
                    )
            row_text = " ".join(
                [line]
                + [
                    lines[nearby_index].rstrip("\r\n")
                    for nearby_index, _ in mark_refs
                    if nearby_index != line_index
                ]
            )
            for mark_line, mark in mark_refs:
                candidates.append(
                    _candidate_from_match(
                        key=key,
                        group=group,
                        token=mark,
                        label=(phrase, start, end),
                        row_text=row_text or line,
                        source_region=f"line-{mark_line}-mark-{line_offsets[mark_line] + mark.start()}",
                        row=line_index,
                        orientation=(
                            "above_label"
                            if mark_line < line_index
                            else "below_label"
                            if mark_line > line_index
                            else "left_of_label"
                            if mark.start() < start
                            else "right_of_label"
                        ),
                        mark_span=(
                            line_offsets[mark_line] + mark.start(),
                            line_offsets[mark_line] + mark.end(),
                        ),
                    )
                )
    return tuple(candidates)


__all__ = [
    "extract_cover_candidates",
    "extract_table_candidates",
]
