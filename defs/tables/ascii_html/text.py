"""Text layout engine, word wrapping, discrete indentation normalization, and formatting."""

from __future__ import annotations

import re
import textwrap
from typing import Any

from defs.tables.ascii_html.model import HorizontalAlign
from defs.text.syntax.tokens import BULLET_MARKER_RE
from defs.text.syntax.unicode import NORMALIZE_TO_SPACE, STRIP_ZERO_WIDTH

# Single-pass character translation table
_NORMALIZE_TRANS = str.maketrans(
    {ch: " " for ch in NORMALIZE_TO_SPACE} | {ch: None for ch in STRIP_ZERO_WIDTH}
)
_SENTENCE_END_RE = re.compile(r"[:.!?\)]\s*$")
_RE_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_RE_DOTS = re.compile(r"\.{4,}")


def _collapse_non_structural_newlines(text: str) -> str:
    """Collapse soft wrapping newlines while preserving paragraphs and bullet/sentence breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = _RE_PARAGRAPH_SPLIT.split(text.strip())
    out_paragraphs: list[str] = []

    for p in paragraphs:
        lines = p.split("\n")
        curr_line: list[str] = []
        p_lines: list[str] = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if not curr_line:
                curr_line.append(line_str)
            else:
                prev = curr_line[-1]
                first_word = line_str.split()[0]
                is_bullet = bool(BULLET_MARKER_RE.match(first_word))
                is_sentence_end = bool(_SENTENCE_END_RE.search(prev))
                is_capital = line_str[0].isupper() or line_str[0].isdigit()
                if is_bullet or (is_sentence_end and is_capital):
                    p_lines.append(" ".join(" ".join(curr_line).split()))
                    curr_line = [line_str]
                else:
                    curr_line.append(line_str)
        if curr_line:
            p_lines.append(" ".join(" ".join(curr_line).split()))
        if p_lines:
            out_paragraphs.append("\n".join(p_lines))

    return "\n".join(out_paragraphs)


def normalize_cell_whitespace(text: str, *, preserve_newlines: bool = False) -> str:
    """Normalize cell text whitespace, dots, and soft wrapping newlines."""
    text = text.translate(_NORMALIZE_TRANS)
    text = _RE_DOTS.sub("...", text)
    if not preserve_newlines:
        text = _collapse_non_structural_newlines(text)
    return text


def _split_wide_hyphenated(text: str, width: int) -> str:
    """Split hyphenated long words to fit within available cell width."""
    if width < 4:
        return text
    tokens = text.split()
    prepared: list[str] = []
    for token in tokens:
        if len(token) > width and "-" in token:
            parts = token.split("-")
            current = parts[0]
            for part in parts[1:]:
                candidate = current + "-" + part
                if len(candidate) <= width:
                    current = candidate
                else:
                    prepared.append(current + "-")
                    current = part
            if current:
                prepared.append(current)
        else:
            prepared.append(token)
    return " ".join(prepared)


def _normalize_wrap_whitespace(text: str) -> str:
    """Make source whitespace consistently breakable for direct wrap callers."""
    return text.translate(_NORMALIZE_TRANS)


def wrap_cell_text(text: str, width: int) -> list[str]:
    """Wrap cell text at word boundaries into lines fitting the column width."""
    text = _normalize_wrap_whitespace(text)
    if not text:
        return [""]
    if len(text) <= width and "\n" not in text:
        return [text]

    # Preserve explicit newlines if present
    raw_lines = text.split("\n")
    wrapped_lines: list[str] = []

    for line in raw_lines:
        if not line:
            wrapped_lines.append("")
            continue
        lstripped = line.lstrip(" ")
        indent_len = len(line) - len(lstripped)
        indent_str = " " * indent_len if indent_len > 0 else ""
        content = lstripped.rstrip()
        if not content:
            wrapped_lines.append(indent_str)
            continue

        prepared = _split_wide_hyphenated(content, max(4, width))
        chunks = textwrap.wrap(
            prepared,
            width=max(4, width),
            initial_indent=indent_str,
            subsequent_indent=indent_str,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(chunks if chunks else [""])

    return wrapped_lines if wrapped_lines else [""]


def format_cell_line(
    text: str, width: int, align: HorizontalAlign = HorizontalAlign.LEFT
) -> str:
    """Format and pad a single line of text to exact column width with alignment."""
    if align == HorizontalAlign.RIGHT:
        txt = text.strip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.rjust(width)
    elif align == HorizontalAlign.CENTER:
        txt = text.strip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.center(width)
    else:  # LEFT or JUSTIFY or AUTO
        # Preserve leading indentation for left alignment
        txt = text.rstrip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.ljust(width)


def normalize_grid_indents(
    raw_grid: list[list[str]],
    single_col_grid: list[list[str]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Normalize effective column visual indentation to discrete 2-space tiers."""
    if not raw_grid or not raw_grid[0]:
        return raw_grid, single_col_grid

    num_cols = len(raw_grid[0])
    num_rows = len(raw_grid)

    new_raw = [list(r) for r in raw_grid]
    new_single = [list(r) for r in single_col_grid]

    for c in range(num_cols):
        indents: list[int] = []
        for r in range(num_rows):
            txt = new_single[r][c] if c < len(new_single[r]) else ""
            if txt.strip():
                leading = len(txt) - len(txt.lstrip(" "))
                indents.append(leading)

        if not indents:
            continue

        unique = sorted(set(indents))
        if len(unique) <= 1:
            if unique[0] > 0:
                for r in range(num_rows):
                    if c < len(new_raw[r]) and new_raw[r][c].strip():
                        new_raw[r][c] = new_raw[r][c].lstrip(" ")
                    if c < len(new_single[r]) and new_single[r][c].strip():
                        new_single[r][c] = new_single[r][c].lstrip(" ")
            continue

        mapping = {u: min(8, rank * 2) for rank, u in enumerate(unique)}

        for r in range(num_rows):
            for target_grid in (new_raw, new_single):
                if c < len(target_grid[r]):
                    txt = target_grid[r][c]
                    if txt.strip():
                        leading = len(txt) - len(txt.lstrip(" "))
                        content = txt.lstrip(" ")
                        new_indent = mapping.get(leading, min(8, leading))
                        target_grid[r][c] = (" " * new_indent) + content

    return new_raw, new_single


def __getattr__(name: str) -> Any:
    if name == "compute_column_widths":
        from defs.tables.ascii_html.widths import compute_column_widths

        return compute_column_widths
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "format_cell_line",
    "normalize_grid_indents",
    "wrap_cell_text",
]
