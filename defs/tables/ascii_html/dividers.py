"""Divider formatting, affix gap healing, and template matching for ASCII tables."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.tables.ascii_html.model import BorderStyle, RenderBudget
from defs.tables.tokens import (
    CLOSING_DELIMITERS,
    PREFIX_SYMBOLS,
    is_numeric_cell,
    is_prefix_token,
    is_suffix_token,
)

if TYPE_CHECKING:
    from defs.tables.ascii_html.blocks import RenderBlock
    from defs.tables.ascii_html.model import SourceCell


def repair_rendered_affix_columns(lines: list[str]) -> None:
    """Restore missing divider marks at rendered prefix/suffix columns only."""
    currency_prefixes = PREFIX_SYMBOLS - {"(", "-"}
    prefix_pattern = re.compile(
        rf"[{re.escape(''.join(sorted(currency_prefixes)))}]\s*(?=\d)"
    )
    affix_columns: set[int] = set()
    affix_line_indices: set[int] = set()
    for line_idx, line in enumerate(lines):
        for match in prefix_pattern.finditer(line):
            affix_columns.add(match.start())
            affix_line_indices.add(line_idx)

    if not affix_columns:
        return

    for idx, line in enumerate(lines):
        if not line or not set(line) <= {"-", "=", " "} or not set(line) & {"-", "="}:
            continue
        if not any(abs(idx - affix_idx) <= 3 for affix_idx in affix_line_indices):
            continue
        chars = list(line)
        for column in affix_columns:
            if column >= len(chars) or chars[column] not in " -=":
                continue
            left = column > 0 and chars[column - 1] in "-="
            right = column + 1 < len(chars) and chars[column + 1] in "-="
            if left and right:
                chars[column] = "=" if chars[column + 1] == "=" else "-"
        lines[idx] = "".join(chars)


def heal_divider_lines_from_templates(lines: list[str]) -> None:
    """Heal fragmented divider lines using equal-width superset divider templates in the same table."""
    divider_indices = [
        idx
        for idx, line in enumerate(lines)
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    if len(divider_indices) < 2:
        return

    for target_idx in divider_indices:
        target = lines[target_idx]
        target_len = len(target)
        candidate_refs = [
            lines[idx]
            for idx in divider_indices
            if idx != target_idx and len(lines[idx]) == target_len
        ]
        candidate_refs.sort(
            key=lambda ref: ref.count("-") + ref.count("="),
            reverse=True,
        )

        for reference in candidate_refs:
            conflicting = any(
                t in "-=" and r not in "-=" for t, r in zip(target, reference)
            )
            if conflicting:
                continue

            added_positions = [
                pos
                for pos, (t, r) in enumerate(zip(target, reference))
                if t == " " and r in "-="
            ]
            if not added_positions:
                continue

            runs: list[list[int]] = [[added_positions[0]]]
            for pos in added_positions[1:]:
                if pos == runs[-1][-1] + 1:
                    runs[-1].append(pos)
                else:
                    runs.append([pos])

            if not all(len(run) <= 3 for run in runs):
                continue

            target_stroke_matches = list(re.finditer(r"[-=]+", target))
            target_run_lengths = [len(m.group(0)) for m in target_stroke_matches]
            # Check if any gap bridges to an isolated short run (<= 3 chars, e.g. affix/footnote columns)
            has_short_fragment = any(rl <= 3 for rl in target_run_lengths)

            if has_short_fragment:
                fill_char = "=" if target.count("=") > target.count("-") else "-"
                chars = list(target)
                for pos in added_positions:
                    chars[pos] = fill_char
                target = "".join(chars)
                lines[target_idx] = target
                break


def prune_unanchored_divider_fragments(lines: list[str]) -> None:
    """Prune phantom divider fragments in columns where no text rows have content."""
    non_divider_lines = [
        line
        for line in lines
        if line
        and line not in ("<TABLE>", "</TABLE>")
        and not (set(line) <= {"-", "=", " "} and set(line) & {"-", "="})
    ]
    if not non_divider_lines:
        return

    for idx, line in enumerate(lines):
        if not line or not (set(line) <= {"-", "=", " "} and set(line) & {"-", "="}):
            continue

        chars = list(line)
        for m in re.finditer(r"[-=]+", line):
            start, end = m.span()
            length = end - start
            if length <= 3:
                has_anchor = any(
                    len(nd_line) > start
                    and any(
                        nd_line[p] != " " for p in range(start, min(end, len(nd_line)))
                    )
                    for nd_line in non_divider_lines
                )
                if not has_anchor:
                    for p in range(start, end):
                        chars[p] = " "
        lines[idx] = "".join(chars).rstrip()


def format_top_divider(
    row_0_blocks: list[tuple[SourceCell | None, list[int], int]],
    row_top_borders: dict[int, dict[int, BorderStyle]],
    col_sep: str,
) -> str | None:
    """Format the top border above row 0 adhering to row 0 merged blocks."""
    if 0 not in row_top_borders:
        return None

    top_div_parts: list[str] = []
    has_any_top = False
    for _, span_cols, block_w in row_0_blocks:
        b_style: BorderStyle | None = None
        for c in span_cols:
            s = row_top_borders[0].get(c)
            if s is not None and s != BorderStyle.NONE:
                if s == BorderStyle.DOUBLE:
                    b_style = BorderStyle.DOUBLE
                elif b_style is None:
                    b_style = s
        if b_style is not None and b_style != BorderStyle.NONE:
            char = "=" if b_style == BorderStyle.DOUBLE else "-"
            top_div_parts.append(char * block_w)
            has_any_top = True
        else:
            top_div_parts.append(" " * block_w)

    return col_sep.join(top_div_parts).rstrip() if has_any_top else None


def format_row_divider(
    blocks: list[RenderBlock],
    r_idx: int,
    header_row_count: int,
    header_divider_style: BorderStyle,
    row_bot_borders: dict[int, dict[int, BorderStyle]],
    row_top_borders: dict[int, dict[int, BorderStyle]],
    budget: RenderBudget,
    col_sep: str,
    prefix_positions: set[int],
    suffix_positions: set[int],
    table_has_affix_token: bool,
    is_affix_footnote_token_fn=None,
) -> str | None:
    """Format the bottom divider below a given row."""
    is_header_bottom = header_row_count > 0 and r_idx == header_row_count - 1
    r_bot = row_bot_borders.get(r_idx, {})
    next_top = row_top_borders.get(r_idx + 1, {})

    has_divider = is_header_bottom or bool(r_bot) or bool(next_top)
    if not has_divider:
        return None

    block_styles: list[tuple[int, BorderStyle | None]] = []
    for b_info in blocks:
        b_style: BorderStyle | None = None
        for c in b_info.span_cols:
            s = r_bot.get(c) or next_top.get(c)
            if s is not None and s != BorderStyle.NONE:
                if s == BorderStyle.DOUBLE:
                    b_style = BorderStyle.DOUBLE
                elif b_style is None:
                    b_style = s

        if is_header_bottom and b_style is None and b_info.text.strip():
            b_style = header_divider_style

        block_styles.append((b_info.width, b_style))

    div_chunks: list[str] = []
    has_any_char = False
    for b_pos, (b_w, b_s) in enumerate(block_styles):
        b_info = blocks[b_pos]
        block_token = b_info.text.strip()
        is_affix_only = (
            bool(b_info.span_cols)
            and all(
                c in prefix_positions or c in suffix_positions for c in b_info.span_cols
            )
            and block_token not in CLOSING_DELIMITERS
        )
        is_fn = (
            is_affix_footnote_token_fn(block_token)
            if is_affix_footnote_token_fn
            else False
        )
        is_affix_token_flag = bool(
            block_token
            and (
                is_prefix_token(block_token)
                or (
                    is_suffix_token(block_token)
                    and block_token not in CLOSING_DELIMITERS
                )
                or is_fn
            )
        )
        is_affix_only = is_affix_only or is_affix_token_flag
        is_affix_gap = (
            table_has_affix_token
            and len(b_info.span_cols) == 1
            and not b_info.text.strip()
            and b_pos > 0
            and is_numeric_cell(blocks[b_pos - 1].text.strip())
            and (
                b_pos + 1 == len(blocks)
                or is_numeric_cell(blocks[b_pos + 1].text.strip())
            )
        )
        if b_s is not None and b_s != BorderStyle.NONE:
            char = "=" if b_s == BorderStyle.DOUBLE else "-"
            if (is_affix_only or is_affix_gap) and b_pos > 0 and div_chunks:
                div_chunks.append(char * (budget.column_spacing + b_w))
            else:
                if b_pos > 0:
                    div_chunks.append(col_sep)
                div_chunks.append(char * b_w)
            has_any_char = True
        else:
            if b_pos > 0:
                div_chunks.append(col_sep)
            div_chunks.append(" " * b_w)

    return "".join(div_chunks).rstrip() if has_any_char else None


__all__ = [
    "format_row_divider",
    "format_top_divider",
    "heal_divider_lines_from_templates",
    "prune_unanchored_divider_fragments",
    "repair_rendered_affix_columns",
]
