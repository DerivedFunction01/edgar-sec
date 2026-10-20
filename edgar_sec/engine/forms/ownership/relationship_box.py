"""Relationship box extraction for Section 16 ownership forms.

The box becomes an ordered token stream of marks, role labels, and free text.
The filer layout varies, so only the relative order of the tokens carries
meaning.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.forms.common.checkmarks import (
    CHECKMARK_MARK_RE,
    mark_token_state,
)
from edgar_sec.engine.forms.common.entities import NON_OWNER_JURISDICTION_RE
from edgar_sec.engine.forms.common.mark_association import (
    SpanPosition,
    select_unique_nearest,
)
from edgar_sec.engine.forms.common.marks import canonicalize_filled_marks
from edgar_sec.engine.forms.ownership.patterns import is_ownership_boilerplate
from edgar_sec.foundation.regex.builder import build_alternation

ROLE_KEYS = ("director", "officer", "ten_percent", "other")
_BARE_ROLE_LABELS = ("officer", "other")

_STRICT_LABEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("director", re.compile(r"(?<![\w])Director(?![\w])")),
    ("ten_percent", re.compile(r"(?<![\w])10\s*%\s*Owner(?![\w])", re.IGNORECASE)),
    ("officer", re.compile(r"(?<![\w])Officer\s*\(\s*give", re.IGNORECASE)),
    ("other", re.compile(r"(?<![\w])Other\s*\(\s*specify", re.IGNORECASE)),
)
_BROAD_LABEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("director", re.compile(r"(?<![\w])Director(?![\w])", re.IGNORECASE)),
    ("ten_percent", re.compile(r"(?<![\w])10\s*%\s*Owner(?![\w])", re.IGNORECASE)),
    ("officer", re.compile(r"(?<![\w])Officer(?![\w/])", re.IGNORECASE)),
    ("other", re.compile(r"(?<![\w])Other(?![\w/])", re.IGNORECASE)),
)
_BOX_HEADER_RE = re.compile(r"^\s*[1-9]\s*\.(?!\d)")
_BOX_NUMBER_RE = re.compile(r"^\s*([1-9])\s*[\.\)]")
_FILL_RUN_RE = re.compile(r"^_{1,8}")
_RELATIONSHIP_HEADER_RE = re.compile(r"relationship\s+of\s+reporting", re.IGNORECASE)
_BOX_TERMINATOR_RE = re.compile(
    r"(?:\b[1-9]\s*[\.\)]\s*)?individual\s+or\s+joint", re.IGNORECASE
)
_VALUE_REJECT_TERMS = (
    "check all applicable",
    "title below",
    "specify below",
    "form filed by",
)
_SLOT_LABEL_RE = re.compile(
    r"^\s*(?:"
    + build_alternation(
        (
            r"officer\s*/\s*other\s+description",
            r"officer\s*/\s*other",
            r"description",
            r"\(\s*title\s*\)",
            r"\(\s*specify\s*\)",
        ),
        auto_escape=False,
    )
    + r")\s*[:\-]?\s*",
    re.IGNORECASE,
)
_LABEL_DESCRIPTIVE_PHRASES = (
    r"give\s+title\s+below",
    r"specify\s+(?:title\s+)?below",
    r"officer\s*/\s*other(?:\s+description)?",
    r"description",
    r"below",
)
_DESCRIPTIVE_ALT = build_alternation(_LABEL_DESCRIPTIVE_PHRASES, auto_escape=False)
_DESCRIPTIVE_TAIL_RE = re.compile(
    rf"^[\s\(\[,]*(?:{_DESCRIPTIVE_ALT})[\s\)\],:]*",
    re.IGNORECASE,
)


class TokenKind(StrEnum):
    """The kinds of token the relationship box yields."""

    MARK = "mark"
    LABEL = "label"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class Token:
    """One ordered element of the relationship box."""

    kind: TokenKind
    row: int
    column: int
    line: int
    offset: int
    end: int
    key: str | None = None
    checked: bool = False
    text: str = ""

    @property
    def position(self) -> tuple[int, int, int, int]:
        return (self.row, self.column, self.line, self.offset)


@dataclass(frozen=True, slots=True)
class RelationshipBox:
    """The resolved relationship box: which roles are checked and what it names."""

    roles: dict[str, bool]
    officer_title: str | None
    other_text: str | None


def _checked_marks(text: str) -> list[re.Match[str]]:
    return [
        match
        for match in CHECKMARK_MARK_RE.finditer(text)
        if mark_token_state(match.group(0).strip(), allow_bare=True) == "checked"
    ]


def _all_marks(text: str) -> list[re.Match[str]]:
    return [
        match
        for match in CHECKMARK_MARK_RE.finditer(text)
        if mark_token_state(match.group(0).strip(), allow_bare=True) is not None
    ]


def _strip_leading_slots(text: str) -> str:
    """Remove leading mark tokens and fill runs so a label can be recognized."""
    stripped = text.strip()
    while stripped:
        match = CHECKMARK_MARK_RE.match(stripped)
        if match and match.end():
            stripped = stripped[match.end() :].lstrip()
            continue
        fill = _FILL_RUN_RE.match(stripped)
        if fill:
            stripped = stripped[fill.end() :].lstrip()
            continue
        break
    return stripped


def _bare_role_key(stripped: str) -> str | None:
    """Return the role key when a cell holds only the bare role word."""
    lowered = stripped.strip().lower()
    return lowered if lowered in _BARE_ROLE_LABELS else None


def _label_matches(
    text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    for key, pattern in patterns:
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), key))
    return sorted(matches)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _is_collapsed(text: str) -> bool:
    """Report whether one cell holds several role labels and their marks."""
    if not _checked_marks(text):
        return False
    keys = {key for _, _, key in _label_matches(text, _BROAD_LABEL_PATTERNS)}
    return len(keys) >= 2


def _label_patterns_for(text: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Choose the label vocabulary that fits how the cell is written."""
    if _is_collapsed(text):
        return _BROAD_LABEL_PATTERNS
    return _STRICT_LABEL_PATTERNS


def _is_label_cell(text: str) -> bool:
    """Report whether a cell holds a role label rather than a value."""
    stripped = _strip_leading_slots(text)
    if not stripped:
        return False
    if any(pattern.match(stripped) for _, pattern in _STRICT_LABEL_PATTERNS):
        return True
    if _bare_role_key(stripped) is not None:
        return True
    return _is_collapsed(text) and bool(_label_matches(stripped, _BROAD_LABEL_PATTERNS))


def _cell_tokens(row: int, column: int, text: str) -> list[Token]:
    """Tokenize one cell into marks, labels, and free text in reading order."""
    stripped = _strip_leading_slots(text)
    patterns = _label_patterns_for(text)
    labels = _label_matches(text, patterns) if stripped else []
    bare = _bare_role_key(stripped) if not labels else None
    if bare is not None:
        start = text.lower().find(bare)
        labels = [(start, start + len(bare), bare)]
    marks = _all_marks(text)
    if not labels:
        if marks:
            return _mark_tokens(row, column, text, marks)
        if not stripped:
            return []
        return [
            Token(
                kind=TokenKind.TEXT,
                row=row,
                column=column,
                line=0,
                offset=0,
                end=len(text),
                text=text.strip(),
            )
        ]
    if (
        not _is_collapsed(text)
        and bare is None
        and not any(pattern.match(stripped) for _, pattern in _STRICT_LABEL_PATTERNS)
    ):
        return [
            Token(
                kind=TokenKind.TEXT,
                row=row,
                column=column,
                line=0,
                offset=0,
                end=len(text),
                text=text.strip(),
            )
        ]
    events: list[tuple[int, int, Token]] = []
    for start, end, key in labels:
        events.append(
            (
                start,
                end,
                Token(
                    kind=TokenKind.LABEL,
                    row=row,
                    column=column,
                    line=_line_of(text, start),
                    offset=start,
                    end=end,
                    key=key,
                    text=text[start:end],
                ),
            )
        )
    for token in _mark_tokens(row, column, text, marks):
        events.append((token.offset, token.end, token))
    events.sort(key=lambda item: (item[0], item[1]))
    return [token for _, _, token in events]


def _mark_tokens(
    row: int, column: int, text: str, marks: Sequence[re.Match[str]]
) -> list[Token]:
    """Build one mark token per recognized mark slot in a cell."""
    return [
        Token(
            kind=TokenKind.MARK,
            row=row,
            column=column,
            line=_line_of(text, match.start()),
            offset=match.start(),
            end=match.end(),
            checked=mark_token_state(match.group(0).strip(), allow_bare=True)
            == "checked",
            text=match.group(0),
        )
        for match in marks
    ]


def _truncate_at_next_box(text: str) -> str:
    """Cut a cell at the next numbered box so later boxes do not join this one."""
    match = _BOX_TERMINATOR_RE.search(text)
    if match is None:
        return text
    line_start = text.rfind("\n", 0, match.start()) + 1
    if not text[line_start : match.start()].strip():
        return text[:line_start]
    return text[: match.start()]


def _labels_precede(text: str, offset: int) -> bool:
    """Report whether role labels appear before an offset in the same cell."""
    labels = _label_matches(text, _BROAD_LABEL_PATTERNS)
    return bool(labels) and labels[0][0] < offset


def _is_terminator_row(cells: Sequence[str]) -> bool:
    """Report whether a row opens the box that follows the relationship box."""
    if any(_label_matches(cell, _BROAD_LABEL_PATTERNS) for cell in cells):
        return False
    for cell in cells:
        text = cell.strip()
        if not text:
            continue
        terminator = _BOX_TERMINATOR_RE.search(text)
        if terminator is not None and not _labels_precede(text, terminator.start()):
            return True
        match = _BOX_NUMBER_RE.match(text)
        if match and int(match.group(1)) >= 7:
            return True
    return False


def _block_bounds(rows: Sequence[Sequence[str]]) -> tuple[int, int] | None:
    """Locate the rows holding the relationship box, from its header to the next box."""
    header = -1
    for index, row in enumerate(rows):
        if _RELATIONSHIP_HEADER_RE.search(" ".join(row)):
            header = index
            break
    if header < 0:
        return None
    end = len(rows)
    for index in range(header + 1, len(rows)):
        if _is_terminator_row(rows[index]):
            end = index
            break
    return (header, end)


def _tokenize(rows: Sequence[Sequence[str]], start: int, end: int) -> list[Token]:
    tokens: list[Token] = []
    for index in range(start, end):
        for column, cell in enumerate(rows[index]):
            text = _truncate_at_next_box(canonicalize_filled_marks(cell))
            if not text.strip():
                continue
            tokens.extend(_cell_tokens(index, column, text))
    return tokens


def _bind_roles(
    tokens: Sequence[Token],
) -> tuple[dict[str, bool], list[tuple[int, bool]]]:
    """Bind each role label to the nearest unbound mark in the token order."""
    roles = {key: False for key in ROLE_KEYS}
    bound: list[tuple[int, bool]] = []
    used: set[int] = set()
    scope_start = 0
    for index, token in enumerate(tokens):
        if token.kind is not TokenKind.LABEL:
            continue
        mark = _nearest_mark(tokens, index, scope_start, used)
        scope_start = index + 1
        if mark is None:
            continue
        used.add(mark)
        checked = bool(token.key and tokens[mark].checked)
        if checked:
            roles[token.key] = True
        bound.append((index, checked))
    return roles, bound


def _value_anchor(tokens: Sequence[Token], bound: Sequence[tuple[int, bool]]) -> int:
    """Choose the label whose slot holds the value the filer wrote."""
    if not bound:
        return -1
    other = [
        index for index, checked in bound if checked and tokens[index].key == "other"
    ]
    if other:
        return other[-1]
    checked = [index for index, is_checked in bound if is_checked]
    if checked:
        return checked[-1]
    return bound[-1][0]


def _nearest_mark(
    tokens: Sequence[Token], index: int, scope_start: int, used: set[int]
) -> int | None:
    """Select a unique nearest mark in the reading-order interval before a label."""
    candidates = [
        candidate
        for candidate in range(scope_start, index)
        if tokens[candidate].kind is TokenKind.MARK and candidate not in used
    ]
    selected = select_unique_nearest(
        _token_position(tokens[index]),
        candidates,
        position_of=lambda candidate: _token_position(tokens[candidate]),
    )
    return selected


def _token_position(token: Token) -> SpanPosition:
    return SpanPosition(token.row, token.column, token.line, token.offset, token.end)


def _is_value_text(text: str) -> bool:
    stripped = " ".join(text.split())
    if not stripped or len(stripped) > 120:
        return False
    lowered = stripped.lower()
    if any(term in lowered for term in _VALUE_REJECT_TERMS):
        return False
    if is_ownership_boilerplate(stripped):
        return False
    if NON_OWNER_JURISDICTION_RE.match(stripped):
        return False
    if _BOX_HEADER_RE.match(stripped):
        return False
    if _checked_marks(stripped):
        return False
    return True


def _clean_value(text: str) -> str | None:
    stripped = _SLOT_LABEL_RE.sub("", " ".join(text.split())).strip()
    stripped = _strip_descriptive_tail(stripped)
    return stripped if _is_value_text(stripped) else None


def _strip_descriptive_tail(text: str) -> str:
    """Remove the label wording that a wrapped slot label leaves in front."""
    for _ in range(3):
        stripped = _DESCRIPTIVE_TAIL_RE.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def _line_tail(text: str, offset: int) -> str:
    """Return the rest of the line that follows an offset."""
    end = text.find("\n", offset)
    return text[offset:] if end < 0 else text[offset:end]


def _is_label_boundary(text: str, end: int) -> bool:
    """Report whether a role label ends the label region of a collapsed cell."""
    tail = _line_tail(text, end)
    return not tail.strip() or bool(_DESCRIPTIVE_TAIL_RE.match(tail))


def _label_region_end(text: str) -> int | None:
    """Find where the role-label region ends inside a collapsed cell."""
    boundary: int | None = None
    for _, end, _ in _label_matches(text, _BROAD_LABEL_PATTERNS):
        if _is_label_boundary(text, end):
            boundary = end
    return boundary


def _collapsed_value(rows: Sequence[Sequence[str]], anchor: Token) -> str | None:
    """Read the value slot out of a cell that holds the whole relationship box."""
    cell = rows[anchor.row][anchor.column]
    text = _truncate_at_next_box(canonicalize_filled_marks(cell))
    region_end = _label_region_end(text)
    if region_end is not None:
        value = _clean_value(text[region_end:])
        if value:
            return value
    mark_lines = {_line_of(text, match.start()) for match in _all_marks(text)}
    if mark_lines:
        lines = text.split("\n")
        for line in lines[max(mark_lines) + 1 :]:
            value = _clean_value(line)
            if value:
                return value
    return None


def _free_text(
    rows: Sequence[Sequence[str]],
    tokens: Sequence[Token],
    bound: Sequence[tuple[int, bool]],
    end: int,
) -> str | None:
    """Find the value slot that follows the bound role labels inside the box."""
    if not tokens:
        return None
    anchor_index = _value_anchor(tokens, bound)
    if anchor_index < 0:
        labels = [
            index for index, token in enumerate(tokens) if token.kind is TokenKind.LABEL
        ]
        if not labels:
            return None
        anchor_index = labels[-1]
    anchor = tokens[anchor_index]
    anchor_cell = rows[anchor.row][anchor.column]
    if _is_collapsed(_truncate_at_next_box(canonicalize_filled_marks(anchor_cell))):
        value = _collapsed_value(rows, anchor)
        if value:
            return value
    remainder = _cell_remainder(rows, anchor)
    value = _clean_value(remainder) if remainder else None
    if value:
        return value
    columns = [
        token.column
        for token in tokens
        if token.kind in (TokenKind.LABEL, TokenKind.MARK)
    ]
    for index in range(anchor.row, end):
        row = rows[index]
        tolerance = max(2, len(row) // 8)
        for column, cell in enumerate(row):
            if index == anchor.row and column <= anchor.column:
                continue
            text = _truncate_at_next_box(canonicalize_filled_marks(cell))
            if not text.strip():
                continue
            if columns and not any(
                abs(column - label_column) <= tolerance for label_column in columns
            ):
                continue
            if _is_label_cell(text) or _checked_marks(text):
                continue
            value = _clean_value(text)
            if value:
                return value
    return None


def _cell_remainder(rows: Sequence[Sequence[str]], token: Token) -> str:
    """Return the text that follows a label inside the same cell."""
    cell = rows[token.row][token.column]
    text = _truncate_at_next_box(canonicalize_filled_marks(cell))
    if not _is_collapsed(text):
        close = text.find(")", token.end)
        if close >= 0:
            return text[close + 1 :]
    cut = text.find("\n", token.end)
    return text[cut + 1 :] if cut >= 0 else ""


def parse_relationship_box(rows: Sequence[Sequence[str]]) -> RelationshipBox | None:
    """Resolve the relationship box roles and its free-text slot."""
    bounds = _block_bounds(rows)
    if bounds is None:
        return None
    start, end = bounds
    tokens = _tokenize(rows, start, end)
    if not any(token.kind is TokenKind.LABEL for token in tokens):
        return None
    roles, bound = _bind_roles(tokens)
    value = _free_text(rows, tokens, bound, end)
    if roles["other"]:
        return RelationshipBox(roles=roles, officer_title=None, other_text=value)
    return RelationshipBox(roles=roles, officer_title=value, other_text=None)


__all__ = [
    "ROLE_KEYS",
    "RelationshipBox",
    "Token",
    "TokenKind",
    "parse_relationship_box",
]
