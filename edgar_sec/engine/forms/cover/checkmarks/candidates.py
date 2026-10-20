"""Geometry and text candidate extraction for cover checkbox inference."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cache

from edgar_sec.domain.forms.common.checkmarks import (
    CHECKMARK_MARK_RE,
    is_fill_in_mark_token,
    is_unchecked_mark_token,
)
from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import (
    REPORT_PERIOD_GROUP,
    STATUTORY_BINARY_GROUP,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.engine.forms.cover.checkmarks.frames import (
    build_masked_offset_translator,
)
from edgar_sec.engine.forms.cover.checkmarks.models import CheckboxCandidate
from edgar_sec.engine.forms.cover.checkmarks.yes_no_pairs import YES_NO_WORD_RE
from edgar_sec.engine.forms.cover.models import CoverBoundary
from edgar_sec.engine.forms.common.mark_association import (
    MarkLabelRelation,
    SpanPosition,
    relation_between,
    select_unique_nearest,
)
from edgar_sec.engine.tables.protection.tags import mask_tagged_tables
from edgar_sec.foundation.text.dates import parse_date
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE


def _compile_label_pattern(phrase: str) -> re.Pattern[str]:
    """Compile a cover-label phrase with bounded whitespace and flexible hyphenation."""
    escaped = re.escape(phrase)
    pattern = escaped.replace(r"\ ", r"[ \t]{1,6}")
    pattern = pattern.replace(r"\-", r"[ \t]*-[ \t]*")
    pattern = pattern.replace(r"\(", r"[ \t]*\([ \t]*").replace(r"\)", r"[ \t]*\)")
    left_b = r"\b" if phrase[0].isalnum() else ""
    right_b = r"\b" if phrase[-1].isalnum() else ""
    return re.compile(rf"{left_b}{pattern}{right_b}", re.IGNORECASE)


@cache
def _label_patterns(
    labels: tuple[CheckboxLabelSpec, ...],
) -> tuple[tuple[str, str, str, re.Pattern[str]], ...]:
    return tuple(
        (label.key, phrase, label.group, _compile_label_pattern(phrase))
        for label in labels
        for phrase in label.phrases
    )


def _labels_for_schema(
    schema: CoverCheckboxSchema | None,
) -> tuple[CheckboxLabelSpec, ...]:
    return (
        schema.labels
        if schema is not None and schema.labels
        else COMMON_CHECKBOX_LABELS
    )


_NEWLINE_RE = re.compile(r"\n")


def _orientation(mark: SpanPosition, label: SpanPosition) -> str:
    relation = relation_between(mark, label)
    return {
        MarkLabelRelation.LEFT: "left_of_label",
        MarkLabelRelation.RIGHT: "right_of_label",
        MarkLabelRelation.ABOVE: "above_label",
        MarkLabelRelation.BELOW: "below_label",
        MarkLabelRelation.SAME_CELL: "same_cell",
        MarkLabelRelation.SAME_LINE: "same_line",
        MarkLabelRelation.UNRESOLVED: "unresolved",
    }[relation]


def _span_position(
    row: int,
    column: int | None,
    line: int,
    span: tuple[int, int],
    source_text: str | None = None,
) -> SpanPosition:
    if source_text is not None:
        line = source_text.count("\n", 0, span[0])
    return SpanPosition(row, column, line, span[0], span[1])


@dataclass(frozen=True, slots=True)
class CoverLineSignals:
    """Cached lexical signals used by line-level cover extraction."""

    labels: tuple[tuple[str, str, int, int, str], ...]
    marks: tuple[re.Match[str], ...]
    answers: tuple[re.Match[str], ...]
    date_present: bool
    dash_only: bool


def _label_matches(
    text: str,
    patterns: tuple[tuple[str, str, str, re.Pattern[str]], ...],
) -> list[tuple[str, str, int, int, str]]:
    matches: list[tuple[str, str, int, int, str]] = []
    for key, phrase, group, pattern in patterns:
        for match in pattern.finditer(text):
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


def _line_signals(
    text: str,
    label_patterns: tuple[tuple[str, str, str, re.Pattern[str]], ...],
) -> CoverLineSignals:
    answers = tuple(YES_NO_WORD_RE.finditer(text))
    marks = tuple(_mark_matches(text, answers=answers))
    return CoverLineSignals(
        labels=tuple(_label_matches(text, label_patterns)),
        marks=marks,
        answers=answers,
        date_present=_date_present(text),
        dash_only=bool(RE_SEPARATOR_LINE.fullmatch(text)),
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
                orientation=_orientation(
                    _span_position(
                        row_index,
                        column,
                        0,
                        (marks[0].start(), marks[0].end()),
                        text,
                    ),
                    _span_position(
                        row_index,
                        column,
                        0,
                        (answer.start(), answer.end()),
                        text,
                    ),
                ),
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
                        orientation=_orientation(
                            _span_position(
                                line_index,
                                None,
                                0,
                                (mark.start(), mark.end()),
                            ),
                            _span_position(
                                line_index,
                                None,
                                0,
                                (answer.start(), answer.end()),
                            ),
                        ),
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
    schema: CoverCheckboxSchema | None = None,
) -> tuple[CheckboxCandidate, ...]:
    """Extract semantic candidates from logical table rows and cell geometry."""
    label_patterns = _label_patterns(_labels_for_schema(schema))
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
            labels = (
                ()
                if text.lstrip().startswith("(")
                else _label_matches(text, label_patterns)
            )
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
        cell_texts = {column: text for column, text, _, _ in cells}
        for label_idx, (label_column, (key, phrase, start, end, group)) in enumerate(
            labels
        ):
            label_position = _span_position(
                row_index,
                label_column,
                0,
                (start, end),
                cell_texts[label_column],
            )
            same_cell = [
                (column, match) for column, match in marks if column == label_column
            ]
            if same_cell:
                selected = select_unique_nearest(
                    label_position,
                    same_cell,
                    position_of=lambda item: _span_position(
                        row_index,
                        item[0],
                        0,
                        (item[1].start(), item[1].end()),
                        cell_texts[item[0]],
                    ),
                )
                related = [selected] if selected is not None else []
            elif all_right or all_left:
                related = [marks[label_idx]]
            else:
                available = [m for m in marks if id(m[1]) not in used_marks]
                if not available:
                    available = marks
                selected = select_unique_nearest(
                    label_position,
                    available,
                    position_of=lambda item: _span_position(
                        row_index,
                        item[0],
                        0,
                        (item[1].start(), item[1].end()),
                        cell_texts[item[0]],
                    ),
                )
                related = [selected] if selected is not None else []
            for mark_column, mark in related:
                used_marks.add(id(mark))
                orientation = _orientation(
                    _span_position(
                        row_index,
                        mark_column,
                        0,
                        (mark.start(), mark.end()),
                        cell_texts[mark_column],
                    ),
                    label_position,
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
                if item[2]
            ]
            unused_options = [
                option
                for option in label_options
                if (option[0], option[1][0]) not in used_vertical_labels
            ]
            target = _span_position(
                row_index,
                column,
                0,
                (marks_in_cell[0].start(), marks_in_cell[0].end()),
                cell_text,
            )
            selected = select_unique_nearest(
                target,
                unused_options or label_options,
                position_of=lambda option: _span_position(
                    option[0],
                    option[1][0],
                    0,
                    (option[1][2][0][2], option[1][2][0][3]),
                    option[1][1],
                ),
            )
            if selected is None:
                continue
            other_row, (label_column, label_text, found, _) = selected
            used_vertical_labels.add((other_row, label_column))
            key, phrase, start, end, group = found[0]
            for mark in marks_in_cell:
                orientation = _orientation(
                    _span_position(
                        row_index,
                        column,
                        0,
                        (mark.start(), mark.end()),
                        cell_text,
                    ),
                    _span_position(
                        other_row, label_column, 0, (start, end), label_text
                    ),
                )
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
    schema: CoverCheckboxSchema | None = None,
    table_geometries: Sequence[object] = (),
) -> tuple[CheckboxCandidate, ...]:
    """Extract candidates from the bounded cover and retained table grids."""
    entry = get_family_entry(family)
    schema = schema or (entry.cover_checkbox_schema if entry is not None else None)
    label_patterns = _label_patterns(_labels_for_schema(schema))
    if boundary.end_line is None:
        return ()
    candidates: list[CheckboxCandidate] = []
    masked, table_spans = mask_tagged_tables(text)
    # A continued-cover region can give an approximate late start; the end line is
    # the reliable fence, so scan from the document start rather than skip headers.
    start_line = 0
    # One indexed scan replaces repeated prefix counts for table placement.
    text_line_starts = [0]
    text_line_starts.extend(match.end() for match in _NEWLINE_RE.finditer(text))

    def _text_line_at(offset: int) -> int:
        return bisect_right(text_line_starts, offset) - 1

    for table_index, geometry in enumerate(table_geometries):
        if table_index >= len(table_spans):
            break
        table_line = _text_line_at(table_spans[table_index].start)
        if table_line >= boundary.end_line:
            break
        if table_line < start_line:
            continue
        candidates.extend(
            extract_table_candidates(
                geometry,
                table_index=table_index,
                schema=schema,
            )
        )

    # Spans are reported in the unmasked frame, because the rewrite slices the
    # original text with them; masked sentinels would shift every offset after a
    # table. Line extraction skips table interiors, then translates back.
    lines = masked.splitlines(keepends=True)
    masked_line_offsets: list[int] = []
    offset = 0
    for raw_line in lines:
        masked_line_offsets.append(offset)
        offset += len(raw_line)

    masked_to_original = build_masked_offset_translator(masked, table_spans)
    # One indexed scan replaces per-line prefix counts.
    masked_line_starts = [0]
    masked_line_starts.extend(
        offset + len(raw_line) for offset, raw_line in zip(masked_line_offsets, lines)
    )

    # Extraction stops at the boundary but the nearby-line fallback reads past it,
    # so signals are computed lazily and memoized.
    line_signals: dict[int, CoverLineSignals] = {}

    def _signals_for(index: int) -> CoverLineSignals:
        signals = line_signals.get(index)
        if signals is None:
            signals = _line_signals(lines[index].rstrip("\r\n"), label_patterns)
            line_signals[index] = signals
        return signals

    unmasked_line_starts: list[int] | None = None

    def _unmasked_line_at(offset: int) -> int:
        nonlocal unmasked_line_starts
        if unmasked_line_starts is None:
            unmasked_line_starts = [0]
            unmasked_line_starts.extend(
                match.end() for match in _NEWLINE_RE.finditer(text)
            )
        return bisect_right(unmasked_line_starts, offset) - 1

    for line_index, raw_line in enumerate(lines):
        line_offset = masked_line_offsets[line_index]
        unmasked_index = _unmasked_line_at(masked_to_original(line_offset))
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
                signals=_signals_for(line_index),
            )
        )
        signals = _signals_for(line_index)
        labels = signals.labels
        if not labels:
            continue
        all_line_marks = signals.marks
        used_line_marks: set[int] = set()
        for label_index, (key, phrase, start, end, group) in enumerate(labels):
            line_marks = all_line_marks
            if group == REPORT_PERIOD_GROUP:
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
                selected = select_unique_nearest(
                    _span_position(line_index, None, 0, (start, end)),
                    [mark for mark in line_marks if id(mark) not in used_line_marks],
                    position_of=lambda mark: _span_position(
                        line_index, None, 0, (mark.start(), mark.end())
                    ),
                )
                mark_refs = [(line_index, selected)] if selected is not None else []
            else:
                mark_refs = []
            used_line_marks.update(id(mark) for _, mark in mark_refs)
            if not mark_refs:
                if group == REPORT_PERIOD_GROUP:
                    continue
                nearby_marks = [
                    (nearby_index, mark)
                    for nearby_index in range(
                        max(0, line_index - 2),
                        min(len(lines), line_index + 3),
                    )
                    if nearby_index != line_index
                    for mark in _signals_for(nearby_index).marks
                ]
                selected = select_unique_nearest(
                    _span_position(line_index, None, 0, (start, end)),
                    nearby_marks,
                    position_of=lambda item: _span_position(
                        item[0], None, 0, (item[1].start(), item[1].end())
                    ),
                )
                if selected is not None:
                    mark_refs.append(selected)
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
                        orientation=_orientation(
                            _span_position(
                                mark_line, None, 0, (mark.start(), mark.end())
                            ),
                            _span_position(line_index, None, 0, (start, end)),
                        ),
                        mark_span=(mark_start, mark_end),
                        answer_matches=_signals_for(mark_line).answers,
                        date_valid=signals.date_present,
                    )
                )
    return tuple(candidates)


__all__ = [
    "extract_cover_candidates",
    "extract_table_candidates",
]
