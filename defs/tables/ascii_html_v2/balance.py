"""Sibling span width balancing and header segment sizing heuristics."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from defs.tables.ascii_html_v2.text import wrap_cell_text

if TYPE_CHECKING:
    from defs.tables.ascii_html_v2.model import RenderBudget


def split_wide_hyphenated(text: str, width: int) -> str:
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


def header_minimum_width(text: str) -> int:
    """Return the longest natural header segment that should not be chopped."""
    words = text.split()
    lengths = [len(part) for word in words for part in word.split("-") if part]
    return max(lengths, default=1)


def preferred_header_width(text: str) -> int:
    """Find a modest width that fits short headers on 1 line and keeps longer headers to at most two lines."""
    text_len = len(text.strip())
    if text_len <= 14:
        return text_len
    minimum = header_minimum_width(text)
    for width in range(minimum, 25):
        if len(wrap_cell_text(text, width)) <= 2:
            return width
    return min(24, max(minimum, (text_len + 1) // 2))


def balanced_wrap_width(text: str, max_cap: int = 52) -> int:
    """Compute optimal character width that produces visually even, balanced wrapped lines."""
    text_len = len(text.strip())
    if text_len <= 30:
        return text_len

    min_w = header_minimum_width(text)
    if text_len <= max_cap:
        return text_len

    # Try 2-line balanced wrapping
    half_len = (text_len + 1) // 2
    best_w = max_cap
    min_diff = 999
    for w in range(max(min_w, half_len - 5), min(max_cap + 1, text_len)):
        lines = wrap_cell_text(text, w)
        if len(lines) == 2:
            diff = abs(len(lines[0].strip()) - len(lines[1].strip()))
            if diff < min_diff:
                min_diff = diff
                best_w = max(len(lines[0].strip()), len(lines[1].strip()))
            if diff <= 6:
                return max(len(lines[0].strip()), len(lines[1].strip()))

    # Try 3-line balanced wrapping if text is long
    if text_len > 70:
        third_len = (text_len + 2) // 3
        for w in range(max(min_w, third_len - 3), min(max_cap, half_len)):
            lines = wrap_cell_text(text, w)
            if len(lines) <= 3:
                line_lens = [len(l.strip()) for l in lines if l.strip()]
                diff = max(line_lens) - min(line_lens)
                if diff < min_diff:
                    min_diff = diff
                    best_w = max(line_lens)

    return min(max_cap, max(min_w, best_w))


def balance_span_widths(
    widths: list[int],
    span_constraints: list[tuple[int, list[int], str]],
    prefix_positions: set[int],
    col_min_safe_widths: list[int],
    col_is_numeric: list[bool],
    budget: RenderBudget,
) -> None:
    """Redistribute width among same-tier spans without increasing table width."""
    header_columns = {
        c for _, span_cols, _ in span_constraints for c in span_cols if c < len(widths)
    }

    for _, span_cols, text in span_constraints:
        origin = next((c for c in span_cols if c < len(widths)), None)
        if origin is None or not text.strip() or widths[origin] > 0:
            continue
        donors = [c for c in range(len(widths)) if c not in header_columns]
        donors.sort(
            key=lambda c: (
                widths[c]
                - (
                    col_min_safe_widths[c]
                    if col_is_numeric[c]
                    else (38 if c == 0 else 1)
                )
            ),
            reverse=True,
        )
        for donor in donors:
            floor = (
                col_min_safe_widths[donor]
                if col_is_numeric[donor]
                else (38 if donor == 0 else 1)
            )
            if widths[donor] > floor:
                widths[donor] -= 1
                widths[origin] = 1
                break

    tiers: dict[tuple[int, int], list[tuple[list[int], str]]] = defaultdict(list)
    for row_idx, span_cols, text in span_constraints:
        if len(span_cols) > 1 and text.strip():
            tiers[(row_idx, len(span_cols))].append((span_cols, text))

    repeated_band_count = max((len(spans) for spans in tiers.values()), default=0)
    if repeated_band_count >= 3 and widths and widths[0] > 38:
        widths[0] = 38

    for spans in tiers.values():
        if len(spans) < 2:
            continue

        # Do not balance if spans are asymmetric (e.g. compact key/item label vs prose description)
        word_counts = [len(text.split()) for _, text in spans]
        text_lens = [len(text.strip()) for _, text in spans]
        if (
            max(word_counts) >= 5
            and min(word_counts) <= 2
            and max(text_lens) >= 30
            and min(text_lens) <= 12
        ):
            continue

        block_sums = [
            sum(widths[c] for c in cols if c < len(widths)) for cols, _ in spans
        ]
        total = sum(block_sums)
        minimums = [
            max(
                header_minimum_width(text),
                sum(
                    min(widths[c], col_min_safe_widths[c])
                    for c in span_cols
                    if c < len(widths) and c in prefix_positions
                ),
            )
            for span_cols, text in spans
        ]
        if total < sum(minimums):
            continue

        target = max(minimums)
        target = max(target, total // len(spans))
        desired = [max(target, minimum) for minimum in minimums]
        while sum(desired) > total:
            reducible = [i for i, value in enumerate(desired) if value > minimums[i]]
            if not reducible:
                break
            idx = max(reducible, key=lambda i: desired[i])
            desired[idx] -= 1
        desired_by_index = desired

        donors = [
            i for i, current in enumerate(block_sums) if current > desired_by_index[i]
        ]
        receivers = [
            i for i, current in enumerate(block_sums) if current < desired_by_index[i]
        ]

        for receiver in receivers:
            need = desired_by_index[receiver] - block_sums[receiver]
            while need > 0 and donors:
                donor = max(donors, key=lambda i: block_sums[i] - desired_by_index[i])
                available = block_sums[donor] - desired_by_index[donor]
                if available <= 0:
                    donors.remove(donor)
                    continue
                amount = min(need, available)
                donor_cols = [c for c in spans[donor][0] if c not in prefix_positions]
                donor_cols.sort(
                    key=lambda c: widths[c] - col_min_safe_widths[c], reverse=True
                )
                receiver_cols = [
                    c for c in spans[receiver][0] if c not in prefix_positions
                ]
                if not receiver_cols:
                    receiver_cols = spans[receiver][0]
                receiver_cols.sort(key=lambda c: widths[c], reverse=True)
                if not donor_cols or not receiver_cols:
                    donors.remove(donor)
                    continue

                remaining = amount
                for col in donor_cols:
                    floor = col_min_safe_widths[col] if col_is_numeric[col] else 1
                    movable = max(0, widths[col] - floor)
                    moved = min(remaining, movable)
                    widths[col] -= moved
                    remaining -= moved
                    if remaining == 0:
                        break
                moved = amount - remaining
                if moved == 0:
                    donors.remove(donor)
                    continue
                widths[receiver_cols[0]] += moved
                block_sums[donor] -= moved
                block_sums[receiver] += moved
                need -= moved

        visible = sum(width > 0 for width in widths)
        excess = (
            sum(widths)
            + budget.column_spacing * max(0, visible - 1)
            - budget.max_table_width
        )
        if excess > 0:
            for col in sorted(
                range(len(widths)), key=lambda c: widths[c], reverse=True
            ):
                if excess <= 0 or col in prefix_positions:
                    continue
                floor = col_min_safe_widths[col] if col_is_numeric[col] else 1
                moved = min(excess, max(0, widths[col] - floor))
                widths[col] -= moved
                excess -= moved

    header_requests: list[tuple[list[int], int]] = []
    for _, span_cols, text in span_constraints:
        block_cols = [c for c in span_cols if c < len(widths)]
        visible_cols = [c for c in block_cols if widths[c] > 0]
        block_width = sum(
            widths[c] for c in visible_cols
        ) + budget.column_spacing * max(0, len(visible_cols) - 1)
        deficit = header_minimum_width(text) - block_width
        if deficit <= 0:
            continue

        receiver_cols = [c for c in block_cols if c not in prefix_positions]
        if not receiver_cols:
            receiver_cols = block_cols
        receiver_cols.sort(key=lambda c: widths[c], reverse=True)
        donors = [c for c in range(len(widths)) if c not in header_columns]
        donors.sort(
            key=lambda c: (
                widths[c]
                - (
                    col_min_safe_widths[c]
                    if col_is_numeric[c]
                    else (38 if c == 0 else 1)
                )
            ),
            reverse=True,
        )

        for donor in donors:
            if deficit <= 0:
                break
            floor = (
                col_min_safe_widths[donor]
                if col_is_numeric[donor]
                else (38 if donor == 0 else 1)
            )
            movable = max(0, widths[donor] - floor)
            moved = min(deficit, movable)
            widths[donor] -= moved
            if receiver_cols:
                widths[receiver_cols[0]] += moved
            deficit -= moved

    for _, span_cols, text in span_constraints:
        block_cols = [c for c in span_cols if c < len(widths)]
        receiver_cols = [c for c in block_cols if c not in prefix_positions]
        if not receiver_cols:
            receiver_cols = block_cols
        receiver_cols.sort(key=lambda c: widths[c], reverse=True)
        if not receiver_cols:
            continue
        visible_cols = [c for c in block_cols if widths[c] > 0]
        current = sum(widths[c] for c in visible_cols) + budget.column_spacing * max(
            0, len(visible_cols) - 1
        )
        preferred = preferred_header_width(text)
        need = max(0, preferred - current)
        if need <= 0:
            continue
        header_requests.append((receiver_cols, need))

    while header_requests:
        visible = sum(width > 0 for width in widths)
        available = budget.max_table_width - (
            sum(widths) + budget.column_spacing * max(0, visible - 1)
        )
        if available <= 0:
            break
        request_idx = max(
            range(len(header_requests)), key=lambda i: header_requests[i][1]
        )
        receiver_cols, need = header_requests[request_idx]
        widths[receiver_cols[0]] += 1
        if need <= 1:
            header_requests.pop(request_idx)
        else:
            header_requests[request_idx] = (receiver_cols, need - 1)


__all__ = [
    "balance_span_widths",
    "balanced_wrap_width",
    "header_minimum_width",
    "preferred_header_width",
    "split_wide_hyphenated",
]
