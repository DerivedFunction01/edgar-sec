"""Geometry and text candidate extraction for cover checkbox inference."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from defs.sec_forms.cover.checkmark.frames import build_masked_offset_translator
from defs.sec_forms.cover.checkmark.models import CheckboxCandidate
from defs.sec_forms.cover.checkmark.yes_no_pairs import YES_NO_WORD_RE
from defs.sec_forms.cover.models import CoverBoundary
from defs.sec_forms.vocabulary import (
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
from defs.tables.protection import mask_tagged_tables
from defs.text.checkmarks import (
    CHECKMARK_MARK_RE,
    is_fill_in_mark_token,
    is_unchecked_mark_token,
)
from defs.text.dates import parse_date
from defs.text.patterns import RE_SEPARATOR_LINE

_RE_DASH_ONLY_LINE = RE_SEPARATOR_LINE

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


_LABEL_RE_PATTERNS: list[tuple[str, str, int, int, str, re.Pattern[str]]] = []
for _key, _phrases, _group in _LABELS:
    for _phrase in _phrases:
        _LABEL_RE_PATTERNS.append(
            (_key, _phrase, 0, 0, _group, re.compile(re.escape(_phrase), re.IGNORECASE))
        )


@dataclass(frozen=True, slots=True)
class CoverLineSignals:
    """Cached lexical signals used by line-level cover extraction."""

    labels: tuple[tuple[str, str, int, int, str], ...]
    marks: tuple[re.Match[str], ...]
    answers: tuple[re.Match[str], ...]
    date_present: bool
    dash_only: bool


def _label_matches(text: str) -> list[tuple[str, str, int, int, str]]:
    matches: list[tuple[str, str, int, int, str]] = []
    for _key, _phrase, _a, _b, _group, _re in _LABEL_RE_PATTERNS:
        for match in _re.finditer(text):
            matches.append((_key, _phrase, match.start(), match.end(), _group))
    matches.sort(key=lambda item: (item[2], -(item[3] - item[2])))
    accepted: list[tuple[str, str, int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for match in matches:
        if any(match[2] < end and match[3] > start for start, end in occupied):
            continue
        accepted.append(match)
        occupied.append((match[2], match[3]))
    return accepted


def _mark_matches(
    text: str,
    *,
    answers: Sequence[re.Match[str]] = (),
) -> list[re.Match[str]]:
    del answers
    return list(CHECKMARK_MARK_RE.finditer(text))


def _answer_for_mark(
    start: int,
    end: int,
    answers: Sequence[re.Match[str]],
) -> str | None:
    nearby = [
        (abs(match.start() - end), match.group("answer").lower())
        for match in answers
        if start - 32 <= match.start() <= end + 32
    ]
    return min(nearby)[1] if nearby else None


def _date_present(text: str) -> bool:
    return parse_date(text) is not None


def _line_signals(text: str) -> CoverLineSignals:
    answers = tuple(YES_NO_WORD_RE.finditer(text))
    marks = tuple(_mark_matches(text, answers=answers))
    return CoverLineSignals(
        labels=tuple(_label_matches(text)),
        marks=marks,
        answers=answers,
        date_present=_date_present(text),
        dash_only=bool(_RE_DASH_ONLY_LINE.fullmatch(text)),
    )


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
        answers = list(YES_NO_WORD_RE.finditer(text))
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
        answers = list(YES_NO_WORD_RE.finditer(text))
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
    answer_matches: Sequence[re.Match[str]] | None = None,
    date_valid: bool | None = None,
) -> CheckboxCandidate:
    label_text, label_start, label_end = label
    answers = (
        tuple(answer_matches)
        if answer_matches is not None
        else tuple(YES_NO_WORD_RE.finditer(row_text))
    )
    answer = _answer_for_mark(token.start(), token.end(), answers)
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
        date_valid=_date_present(row_text) if date_valid is None else date_valid,
        label_span=(label_start, label_end),
        mark_span=mark_span or (token.start(), token.end()),
        label_text=label_text,
    )


def _line_yes_no_candidates(
    line: str,
    *,
    line_index: int,
    line_offset: int,
    signals: CoverLineSignals | None = None,
) -> list[CheckboxCandidate]:
    """Extract one explicit Yes/No pair from an ASCII cover line."""

    signals = signals or _line_signals(line)
    answers = signals.answers
    if len(answers) < 2 or len(answers) % 2:
        return []
    marks = signals.marks
    if len(marks) != len(answers):
        return []
    candidates: list[CheckboxCandidate] = []
    for pair_index in range(0, len(answers), 2):
        pair_answers = answers[pair_index : pair_index + 2]
        if {answer.group("answer").lower() for answer in pair_answers} != {
            "yes",
            "no",
        }:
            return []
        question_key = f"line_yes_no:{line_index}:{pair_index // 2}"
        for answer, mark in zip(
            pair_answers, marks[pair_index : pair_index + 2], strict=True
        ):
            candidates.append(
                replace(
                    _candidate_from_match(
                        key=question_key,
                        group=STATUTORY_BINARY_GROUP,
                        token=mark,
                        label=(answer.group(0), answer.start(), answer.end()),
                        row_text=line,
                        source_region=(
                            f"line-{line_index}-mark-{line_offset + mark.start()}"
                        ),
                        row=line_index,
                        orientation="same_line",
                        mark_span=(
                            line_offset + mark.start(),
                            line_offset + mark.end(),
                        ),
                        answer_matches=pair_answers,
                        date_valid=signals.date_present,
                    ),
                    answer=answer.group("answer").lower(),
                    question_key=question_key,
                    state=(
                        "unchecked" if is_unchecked_mark_token(mark.group(0)) else None
                    ),
                )
            )
    return candidates


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
            row_data.append((column, text, list(labels), _mark_matches(text)))
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
        used_marks: set[int] = set()
        all_right = len(labels) == len(marks) > 1 and all(
            marks[i][0] > labels[i][0] for i in range(len(labels))
        )
        all_left = len(labels) == len(marks) > 1 and all(
            marks[i][0] < labels[i][0] for i in range(len(labels))
        )
        for label_idx, (label_column, (key, phrase, start, end, group)) in enumerate(
            labels
        ):
            same_cell = [
                (column, match) for column, match in marks if column == label_column
            ]
            if same_cell:
                related = same_cell
            elif all_right or all_left:
                related = [marks[label_idx]]
            else:
                available = [m for m in marks if id(m[1]) not in used_marks]
                if not available:
                    available = marks
                related = sorted(
                    available,
                    key=lambda item: abs(item[0] - label_column),
                )[:1]
            for mark_column, mark in related:
                used_marks.add(id(mark))
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
    masked, table_spans = mask_tagged_tables(text)
    # ASCII cover boundaries can have an approximate late start line when the
    # detector identifies a continued-cover region.  The end line is the
    # reliable cover/body fence; scanning from the document start prevents
    # valid report-period checkboxes near the cover header from being skipped.
    start_line = 0
    for table_index, geometry in enumerate(table_geometries):
        if table_index >= len(table_spans):
            break
        table_line = text.count("\n", 0, table_spans[table_index].start)
        if table_line >= boundary.end_line:
            break
        if table_line < start_line:
            continue
        candidates.extend(extract_table_candidates(geometry, table_index=table_index))

    # Candidate marks and spans must be reported in the unmasked document
    # frame: apply_cover_checkmark_decisions slices the original text with
    # them. Masked-table sentinels would shift every offset after a table.
    # Line extraction still skips table interiors via the sentinel text, then
    # each masked offset is translated back through the table spans.
    lines = masked.splitlines(keepends=True)
    masked_line_offsets: list[int] = []
    offset = 0
    for raw_line in lines:
        masked_line_offsets.append(offset)
        offset += len(raw_line)

    masked_to_original = build_masked_offset_translator(masked, table_spans)
    line_signals = {
        index: _line_signals(raw_line.rstrip("\r\n"))
        for index, raw_line in enumerate(lines)
    }

    for line_index, raw_line in enumerate(lines):
        line_offset = masked_line_offsets[line_index]
        unmasked_index = text.count("\n", 0, masked_to_original(line_offset))
        if unmasked_index >= boundary.end_line:
            break
        if unmasked_index < start_line:
            continue
        line = raw_line.rstrip("\r\n")
        candidates.extend(
            _line_yes_no_candidates(
                line,
                line_index=line_index,
                line_offset=masked_to_original(line_offset),
                signals=line_signals[line_index],
            )
        )
        signals = line_signals[line_index]
        labels = signals.labels
        if not labels:
            continue
        all_line_marks = signals.marks
        for label_index, (key, phrase, start, end, group) in enumerate(labels):
            line_marks = all_line_marks
            if key in {REPORT_TRANSITION, REPORT_ANNUAL, REPORT_QUARTERLY}:
                line_marks = [
                    mark
                    for mark in all_line_marks
                    if not is_fill_in_mark_token(mark.group(0))
                ]
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
                if key in {REPORT_TRANSITION, REPORT_ANNUAL, REPORT_QUARTERLY}:
                    continue
                for nearby_index in range(
                    max(0, line_index - 2),
                    min(len(lines), line_index + 3),
                ):
                    if nearby_index == line_index:
                        continue
                    mark_refs.extend(
                        (nearby_index, mark)
                        for mark in line_signals[nearby_index].marks
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
                mark_start = masked_to_original(
                    masked_line_offsets[mark_line] + mark.start()
                )
                mark_end = masked_to_original(
                    masked_line_offsets[mark_line] + mark.end()
                )
                candidates.append(
                    _candidate_from_match(
                        key=key,
                        group=group,
                        token=mark,
                        label=(phrase, start, end),
                        row_text=row_text or line,
                        source_region=f"line-{mark_line}-mark-{mark_start}",
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
                        mark_span=(mark_start, mark_end),
                        answer_matches=line_signals[mark_line].answers,
                        date_valid=signals.date_present,
                    )
                )
    return tuple(candidates)


__all__ = [
    "extract_cover_candidates",
    "extract_table_candidates",
]
