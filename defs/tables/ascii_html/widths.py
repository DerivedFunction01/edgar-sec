"""Width budgeting and optimal column width allocation for ASCII table presentation."""

from __future__ import annotations

import re
from collections import defaultdict

from defs.tables.ascii_html.balance import (
    balance_span_widths,
    balanced_wrap_width,
)
from defs.tables.ascii_html.model import (
    DEFAULT_RENDER_BUDGET,
    HorizontalAlign,
    RenderBudget,
    TextLayoutDiagnostic,
)
from defs.tables.tokens import is_numeric_cell

_FOOTNOTE_SUFFIX_RE = re.compile(
    r"\s*(?:\([0-9]{1,2}\)|\([a-zA-Z]{1,2}\)|[*+†‡§u]+)\s*$"
)


def _normalize_header_key(text: str) -> str:
    """Normalize header text for mirror column detection by stripping trailing footnote markers."""
    t = text.strip()
    while True:
        s = _FOOTNOTE_SUFFIX_RE.sub("", t).strip()
        if s == t or not s:
            break
        t = s
    return t.lower()


def compute_column_widths(
    grid_rows: list[list[str]],
    alignments: list[HorizontalAlign],
    span_constraints: list[tuple[int, list[int], str]] | None = None,
    prefix_positions: set[int] | None = None,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
    single_col_rows: list[list[str]] | None = None,
) -> tuple[list[int], list[TextLayoutDiagnostic]]:
    """Compute optimal character column widths adhering to RenderBudget constraints."""
    if not grid_rows or not grid_rows[0]:
        return [], []

    num_cols = len(grid_rows[0])
    num_rows = len(grid_rows)
    prefix_positions = prefix_positions or set()
    diagnostics: list[TextLayoutDiagnostic] = []

    # 1. Measure max natural and unwrapped length per column
    col_natural_lengths = [0] * num_cols
    col_unwrapped_lengths = [0] * num_cols
    col_longest_text = [""] * num_cols
    col_is_numeric = [False] * num_cols
    col_is_prose = [False] * num_cols
    col_min_safe_widths = [0] * num_cols

    multi_span_cells = (
        {
            (r, c)
            for r, span_cols, _ in span_constraints
            if len(span_cols) > 1
            for c in span_cols
        }
        if span_constraints
        else set()
    )

    for c_idx in range(num_cols):
        max_text_len = 0
        max_num_len = 0
        max_unwrapped = 0
        max_word_len = 0
        num_count = 0
        text_count = 0
        word_counts: list[int] = []
        measuring_rows = single_col_rows if single_col_rows is not None else grid_rows
        for r_idx in range(num_rows):
            cell_txt = (
                measuring_rows[r_idx][c_idx]
                if c_idx < len(measuring_rows[r_idx])
                else ""
            )
            stripped = cell_txt.strip()
            if not stripped:
                continue
            if len(stripped) > len(col_longest_text[c_idx]):
                col_longest_text[c_idx] = stripped
            max_unwrapped = max(max_unwrapped, len(stripped))
            words = stripped.split()
            if words:
                word_counts.append(len(words))
            for w in words:
                max_word_len = max(max_word_len, len(w))
            if is_numeric_cell(stripped):
                num_count += 1
                max_num_len = max(max_num_len, len(cell_txt))
            else:
                text_count += 1
                max_text_len = max(max_text_len, len(cell_txt))

        if c_idx == 0:
            is_num = False
        else:
            is_num = num_count > 0 and (
                num_count >= text_count or num_count >= (num_rows * 0.3)
            )
        col_is_numeric[c_idx] = is_num
        col_unwrapped_lengths[c_idx] = max_unwrapped

        body_words = [
            len(measuring_rows[r][c_idx].strip().split())
            for r in range(1, num_rows)
            if c_idx < len(measuring_rows[r]) and measuring_rows[r][c_idx].strip()
        ]
        avg_body_words = (sum(body_words) / len(body_words)) if body_words else 0.0
        max_body_words = max(body_words, default=0)
        is_prose = (not is_num) and (avg_body_words >= 3.5 or max_body_words >= 8)
        col_is_prose[c_idx] = is_prose

        if is_num:
            min_numeric_fit = max(max_num_len, max_word_len, 7)
            header_candidates = [
                measuring_rows[r][c_idx]
                for r in range(min(4, num_rows))
                if (r, c_idx) not in multi_span_cells
                and not is_numeric_cell(measuring_rows[r][c_idx].strip())
                and measuring_rows[r][c_idx].strip()
            ]
            if header_candidates:
                longest_h = max(header_candidates, key=lambda s: len(s.strip())).strip()
                ideal_header_w = balanced_wrap_width(longest_h, max_cap=30)
                tight_header_floor = min(16, balanced_wrap_width(longest_h, max_cap=16))
                min_numeric_fit = max(min_numeric_fit, tight_header_floor)
                col_min_safe_widths[c_idx] = min_numeric_fit
                header_w = max(min_numeric_fit, ideal_header_w)
            else:
                col_min_safe_widths[c_idx] = min_numeric_fit
                header_w = min_numeric_fit
            col_natural_lengths[c_idx] = max(max_num_len, header_w)
        elif is_prose:
            col_natural_lengths[c_idx] = max_text_len
            col_min_safe_widths[c_idx] = max(max_word_len, 38)
        elif c_idx == 0:
            col_natural_lengths[c_idx] = max(max_text_len, max_num_len)
            col_min_safe_widths[c_idx] = max(max_word_len, min(38, max_text_len))
        else:
            col_natural_lengths[c_idx] = max_text_len
            col_min_safe_widths[c_idx] = max(max_word_len, 14)

    # 1b. Mirror column equalization for numeric columns with matching normalized headers
    header_to_num_cols: dict[str, list[int]] = defaultdict(list)
    for c_idx in range(num_cols):
        if col_is_numeric[c_idx] and c_idx not in prefix_positions:
            measuring = single_col_rows if single_col_rows is not None else grid_rows
            h_candidates = [
                measuring[r][c_idx]
                for r in range(min(4, num_rows))
                if (r, c_idx) not in multi_span_cells
                and not is_numeric_cell(measuring[r][c_idx].strip())
                and measuring[r][c_idx].strip()
            ]
            if h_candidates:
                longest_h = max(h_candidates, key=lambda s: len(s.strip())).strip()
                key = _normalize_header_key(longest_h)
                if key and not key.isdigit():
                    header_to_num_cols[key].append(c_idx)

    for key, group in header_to_num_cols.items():
        if len(group) > 1:
            max_nat = max(col_natural_lengths[c] for c in group)
            max_min_safe = max(col_min_safe_widths[c] for c in group)
            for c in group:
                col_natural_lengths[c] = max_nat
                col_min_safe_widths[c] = max_min_safe

    # 2. Assign initial column widths based on budget limits
    widths: list[int] = []
    for c_idx in range(num_cols):
        nat = col_natural_lengths[c_idx]
        is_num = col_is_numeric[c_idx]
        is_prose = col_is_prose[c_idx]
        is_prefix = c_idx in prefix_positions

        if nat == 0:
            widths.append(0)
        elif is_prefix:
            widths.append(min(4, max(1, nat)))
        elif is_num:
            widths.append(max(1, nat))
        elif is_prose:
            widths.append(min(80, max(1, nat)))
        elif c_idx == 0:
            widths.append(min(60, max(1, nat)))
        else:
            widths.append(min(35, max(1, nat)))

    # 3. Expand columns if multi-column spans require additional space
    if span_constraints:
        tier_spans = defaultdict(list)
        for r_idx, span_cols, span_txt in span_constraints:
            tier_spans[r_idx].append((span_cols, span_txt))

        for r_idx, spans in tier_spans.items():
            for span_cols, span_txt in spans:
                valid_span_cols = [c for c in span_cols if c < num_cols]
                if not valid_span_cols or not span_txt:
                    continue

                positive_cols = [c for c in valid_span_cols if widths[c] > 0]
                if not positive_cols:
                    positive_cols = valid_span_cols
                    for c in positive_cols:
                        widths[c] = max(widths[c], 1)

                current_span_w = sum(
                    widths[c] for c in positive_cols
                ) + budget.column_spacing * max(0, len(positive_cols) - 1)

                is_full_table_span = len(positive_cols) >= sum(
                    1 for w in widths if w > 0
                )
                is_bottom_footnote = (r_idx >= max(1, num_rows - 3)) and (
                    len(span_txt) > 60 or is_full_table_span
                )
                is_stub_span = bool(valid_span_cols and valid_span_cols[0] == 0)
                is_prose_span = (
                    r_idx >= 3
                    and (len(span_txt.split()) >= 5 or len(span_txt) >= 40)
                    and not is_full_table_span
                )

                if is_bottom_footnote:
                    # Bottom footnotes/disclaimers wrap across existing table width
                    ideal_span_target = current_span_w
                elif is_stub_span:
                    ideal_span_target = min(
                        len(span_txt), max(58, 30 * len(positive_cols))
                    )
                elif is_prose_span:
                    ideal_span_target = min(len(span_txt), 80)
                elif len(span_txt) <= 24:
                    ideal_span_target = len(span_txt)
                else:
                    ideal_span_target = balanced_wrap_width(span_txt, max_cap=48)

                if ideal_span_target > current_span_w:
                    deficit = ideal_span_target - current_span_w
                    expandable_cols = [
                        c
                        for c in positive_cols
                        if c not in prefix_positions and widths[c] < 80
                    ]
                    content_expandable = [
                        c for c in expandable_cols if col_natural_lengths[c] > 0
                    ]
                    target_expand_cols = content_expandable or expandable_cols
                    if target_expand_cols:
                        add_per_col = (deficit + len(target_expand_cols) - 1) // len(
                            target_expand_cols
                        )
                        for c in target_expand_cols:
                            widths[c] += add_per_col

    # 4. Enforce max table width budget
    active_count = sum(1 for w in widths if w > 0)
    total_col_sep = budget.column_spacing * max(0, active_count - 1)
    total_w = sum(widths) + total_col_sep

    if total_w > budget.max_table_width:
        excess = total_w - budget.max_table_width
        shrinkable_cols = sorted(
            [c for c in range(num_cols) if widths[c] > 0 and c not in prefix_positions],
            key=lambda c: widths[c] - col_min_safe_widths[c],
            reverse=True,
        )

        for c_idx in shrinkable_cols:
            if excess <= 0:
                break
            min_w = col_min_safe_widths[c_idx]
            available_shrink = max(0, widths[c_idx] - min_w)
            shrink_amount = min(excess, available_shrink)
            widths[c_idx] -= shrink_amount
            excess -= shrink_amount

        if excess > 0:
            for c_idx in shrinkable_cols:
                if excess <= 0:
                    break
                available_shrink = max(0, widths[c_idx] - 3)
                shrink_amount = min(excess, available_shrink)
                widths[c_idx] -= shrink_amount
                excess -= shrink_amount

    # 5. Expand prose and text columns if headroom is available
    active_count = sum(1 for w in widths if w > 0)
    total_col_sep = budget.column_spacing * max(0, active_count - 1)
    current_total = sum(widths) + total_col_sep
    headroom = max(0, budget.max_table_width - current_total)

    # First pass: expand prose/description columns towards natural length without forced wrapping
    if headroom > 0:
        for c_idx in range(num_cols):
            if headroom <= 0:
                break
            if (
                widths[c_idx] > 0
                and col_is_prose[c_idx]
                and c_idx not in prefix_positions
            ):
                nat = col_natural_lengths[c_idx]
                if nat > widths[c_idx]:
                    can_expand = min(
                        nat - widths[c_idx], headroom, max(0, 80 - widths[c_idx])
                    )
                    if can_expand > 0:
                        widths[c_idx] += can_expand
                        headroom -= can_expand

    # Second pass: expand row stubs (column 0) if headroom remains
    if headroom > 0 and widths and widths[0] > 0 and widths[0] < col_natural_lengths[0]:
        can_expand = min(col_natural_lengths[0] - widths[0], headroom)
        widths[0] += can_expand
        headroom -= can_expand

    # Third pass: expand other text columns towards natural length
    if headroom > 0:
        for c_idx in range(num_cols):
            if headroom <= 0:
                break
            if (
                widths[c_idx] > 0
                and not col_is_numeric[c_idx]
                and c_idx not in prefix_positions
            ):
                nat = col_natural_lengths[c_idx]
                if nat > widths[c_idx]:
                    can_expand = min(nat - widths[c_idx], headroom)
                    widths[c_idx] += can_expand
                    headroom -= can_expand

    # Fourth pass: expand numeric columns with multi-line headers if headroom remains
    if headroom > 0:
        for c_idx in range(num_cols):
            if headroom <= 0:
                break
            if (
                widths[c_idx] > 0
                and col_is_numeric[c_idx]
                and c_idx not in prefix_positions
            ):
                measuring = (
                    single_col_rows if single_col_rows is not None else grid_rows
                )
                h_candidates = [
                    measuring[r][c_idx]
                    for r in range(min(4, num_rows))
                    if not is_numeric_cell(measuring[r][c_idx].strip())
                    and measuring[r][c_idx].strip()
                ]
                if h_candidates:
                    longest_h = max(h_candidates, key=lambda s: len(s.strip())).strip()
                    target_w = balanced_wrap_width(longest_h, max_cap=32)
                    if target_w > widths[c_idx]:
                        can_expand = min(target_w - widths[c_idx], headroom)
                        widths[c_idx] += can_expand
                        headroom -= can_expand

    if span_constraints:
        balance_span_widths(
            widths,
            span_constraints,
            prefix_positions,
            col_min_safe_widths,
            col_is_numeric,
            budget,
        )

    # 6. Generate diagnostics for cells exceeding column width
    for r_idx in range(num_rows):
        for c_idx in range(num_cols):
            txt = grid_rows[r_idx][c_idx]
            w = widths[c_idx]
            if len(txt) > w:
                diagnostics.append(
                    TextLayoutDiagnostic(
                        row=r_idx,
                        column=c_idx,
                        original_length=len(txt),
                        rendered_lines=(len(txt) + w - 1) // max(1, w),
                        forced_wrap=True,
                    )
                )

    return widths, diagnostics


__all__ = [
    "compute_column_widths",
]
