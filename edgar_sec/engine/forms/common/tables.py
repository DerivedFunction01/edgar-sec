"""Tabular grid partitioning for SEC forms into header, data, and instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.domain.forms.common.entities import (
    INSTRUCTION_SIGNATURE_PHRASES,
    TABULAR_STOPWORDS,
)
from edgar_sec.engine.forms.common.entities import BARE_BOX_NUM_RE, STATE_ZIP_RE
from edgar_sec.engine.tables.ascii_html.converter import ResolvedGrid
from edgar_sec.foundation.regex.builder import build_alternation

_STOPWORDS_SET = frozenset(TABULAR_STOPWORDS)
_IGNORE_MARKERS = frozenset({"(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)"})
_CONJUNCTIONS = ("and", "or", "&", "/")
_CONJUNCTION_ALT = build_alternation(_CONJUNCTIONS, auto_escape=True)
_CONJUNCTION_LABEL_RE = re.compile(rf"^\s*(?:{_CONJUNCTION_ALT})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GridPartition:
    """Segmented rows and header index from a table grid."""

    header_index: int | None
    data_rows: tuple[tuple[str, ...], ...]
    instruction_rows: tuple[tuple[str, ...], ...]


def is_instruction_row(row_text: str) -> bool:
    """Detect whether a row is instructional prose or statutory boilerplate."""
    lower = row_text.lower()
    if any(phrase in lower for phrase in INSTRUCTION_SIGNATURE_PHRASES):
        return True
    tokens = [w for w in lower.split() if w.isalpha()]
    if len(tokens) >= 10:
        stop_count = sum(1 for w in tokens if w in _STOPWORDS_SET)
        if stop_count >= 7 and (stop_count / len(tokens)) >= 0.35:
            return True
    return False


def partition_grid_rows(
    grid: ResolvedGrid,
    header_keywords: set[str] | frozenset[str],
    *,
    min_header_score: int = 6,
) -> GridPartition:
    """Partition table rows into header, clean data rows, and instruction rows."""
    header_idx: int | None = None
    data_rows: list[tuple[str, ...]] = []
    instruction_rows: list[tuple[str, ...]] = []

    for idx, row in enumerate(grid.rows):
        row_str = " ".join(c.strip() for c in row if c.strip())
        if not row_str:
            continue
        lower = row_str.lower().replace("(", " ").replace(")", " ")
        tokens = set(lower.split())
        h_score = len(tokens & header_keywords)

        if h_score >= min_header_score and header_idx is None:
            header_idx = idx
            continue

        if is_instruction_row(row_str):
            instruction_rows.append(row)
            continue

        if header_idx is not None:
            data_rows.append(row)

    return GridPartition(
        header_index=header_idx,
        data_rows=tuple(data_rows),
        instruction_rows=tuple(instruction_rows),
    )


def clean_field_candidate(text: str, excluded: tuple[str, ...] = ()) -> str | None:
    """Normalize and validate extracted cell text candidate."""
    value = text.strip(" \t\r\n:;,-")
    lower = value.lower()
    if (
        len(value) < 2
        or BARE_BOX_NUM_RE.match(value)
        or lower in _IGNORE_MARKERS
        or any(term in lower for term in excluded)
    ):
        return None
    return value


def extract_labeled_field(
    grid: ResolvedGrid,
    labels: tuple[str, ...],
    *,
    excluded: tuple[str, ...] = (),
    lookahead_cols: int = 1,
    lookdown_rows: int = 3,
) -> str | None:
    """Resolve field value from 2D coordinates: inline tail, right cell, or row below."""
    for row_idx, row in enumerate(grid.rows):
        for col_idx, cell in enumerate(row):
            c_clean = cell.strip()
            if not c_clean:
                continue
            lines = [line.strip() for line in cell.splitlines() if line.strip()]
            for line_idx, line in enumerate(lines):
                lower = line.lower()
                matched = next((lbl for lbl in labels if lbl in lower), None)
                if matched is None:
                    continue
                raw_tail = line[lower.find(matched) + len(matched) :]
                if _CONJUNCTION_LABEL_RE.match(raw_tail):
                    continue
                tail = raw_tail
                if ")" in tail:
                    tail = tail[tail.rfind(")") + 1 :]
                val = clean_field_candidate(tail, excluded)
                if val:
                    return val
                value_lines: list[str] = []
                for candidate in lines[line_idx + 1 :]:
                    if candidate.lower().strip(" .:;") in {
                        "are to be sold",
                        "is to be sold",
                    }:
                        continue
                    c_val = clean_field_candidate(candidate, excluded)
                    if not c_val:
                        break
                    value_lines.append(c_val)
                if value_lines:
                    return " ".join(value_lines)

            c_lower = c_clean.lower()
            if any(lbl in c_lower for lbl in labels):
                if lookahead_cols >= 1 and col_idx + 1 < len(row):
                    val = clean_field_candidate(row[col_idx + 1], excluded)
                    if val and not any(lbl in val.lower() for lbl in labels):
                        return val
                if lookdown_rows >= 1:
                    for d in range(1, min(lookdown_rows + 1, len(grid.rows) - row_idx)):
                        target_row = grid.rows[row_idx + d]
                        if not any(c.strip() for c in target_row):
                            continue
                        prop_idx = min(
                            len(target_row) - 1,
                            max(
                                0,
                                round(
                                    (col_idx + 0.5) / max(1, len(row)) * len(target_row)
                                    - 0.5
                                ),
                            ),
                        )
                        prop_val = clean_field_candidate(target_row[prop_idx], excluded)
                        if prop_val and not any(
                            lbl in prop_val.lower() for lbl in labels
                        ):
                            marker = prop_val.replace(" ", "").lower()
                            if marker not in _IGNORE_MARKERS and not (
                                len(marker) == 4
                                and marker[0].isdigit()
                                and marker[1] == "("
                                and marker[2] in "abcdefg"
                                and marker[3] == ")"
                            ):
                                return prop_val

                        for candidate in target_row:
                            val = clean_field_candidate(candidate, excluded)
                            if not val or any(lbl in val.lower() for lbl in labels):
                                continue
                            marker = val.replace(" ", "").lower()
                            if marker in _IGNORE_MARKERS or (
                                len(marker) == 4
                                and marker[0].isdigit()
                                and marker[1] == "("
                                and marker[2] in "abcdefg"
                                and marker[3] == ")"
                            ):
                                continue
                            return val
    return None


def parse_address_parts(
    text: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Split full address text into street, city, state, and postal code."""
    match = STATE_ZIP_RE.search(text)
    if not match:
        return text.strip() or None, None, None, None
    prefix = text[: match.start()].strip().rstrip(",")
    pieces = [piece.strip() for piece in prefix.split(",") if piece.strip()]
    city = pieces.pop() if len(pieces) > 1 else None
    street = ", ".join(pieces) if pieces else prefix or None
    return street, city, match.group(1), match.group(2)


def address_from_column_headers(
    labels: tuple[str, ...], values: tuple[str, ...]
) -> tuple[str | None, str | None, str | None, str | None] | None:
    """Extract address components aligned under street, city, state, zip headers."""
    terms = ("street", "city", "state", "zip")
    indexes: list[int] = []
    for term in terms:
        matches = [i for i, cell in enumerate(labels) if term in cell.lower()]
        if len(matches) != 1:
            return None
        indexes.append(matches[0])
    if len(set(indexes)) != len(indexes) or any(i >= len(values) for i in indexes):
        return None
    res = tuple(values[i].strip() or None for i in indexes)
    return res[0], res[1], res[2], res[3]


def address_from_inline_cells(
    row: tuple[str, ...],
) -> tuple[str | None, str | None, str | None, str | None] | None:
    """Extract address parts embedded with inline sub-labels across cells."""
    fields: dict[str, str] = {}
    terms = ("street", "city", "state", "zip code")
    for term in terms:
        for cell in row:
            lines = [line.strip() for line in cell.splitlines() if line.strip()]
            for line_idx, line in enumerate(lines):
                lower = line.lower()
                if term not in lower or sum(c in lower for c in terms) > 1:
                    continue
                tail = line[lower.find(term) + len(term) :]
                val = clean_field_candidate(tail, terms)
                if val:
                    fields[term] = val
                    break
                if line_idx + 1 < len(lines):
                    val = clean_field_candidate(lines[line_idx + 1], terms)
                    if val:
                        fields[term] = val
                        break
            if term in fields:
                break
    if not fields:
        return None
    state_zip = STATE_ZIP_RE.search(" ".join(row))
    state = fields.get("state")
    zip_code = fields.get("zip code")
    if state_zip:
        state = state or state_zip.group(1)
        zip_code = zip_code or state_zip.group(2)
    return fields.get("street"), fields.get("city"), state, zip_code


_EMPTY_CONTINUATION_WORDS: frozenset[str] = frozenset(
    {"none", "n/a", "no reported", "not applicable", "nil", "0"}
)


def is_trailing_signature_table(text: str, row_count: int) -> bool:
    """Classify whether a short trailing table represents a signature continuation."""
    return len(text.strip()) < 100 and row_count <= 2


def is_single_cell_empty_table(
    rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]],
) -> bool:
    """Detect whether a table contains only empty / negative placeholder entries."""
    clean_cells = [
        cell.strip().lower()
        for row in rows
        for cell in row
        if cell.strip() and not cell.strip().lower().startswith("remarks")
    ]
    return bool(clean_cells) and all(
        c in _EMPTY_CONTINUATION_WORDS for c in clean_cells
    )


__all__ = [
    "GridPartition",
    "address_from_column_headers",
    "address_from_inline_cells",
    "clean_field_candidate",
    "extract_labeled_field",
    "is_instruction_row",
    "is_single_cell_empty_table",
    "is_trailing_signature_table",
    "parse_address_parts",
    "partition_grid_rows",
]
