"""TOC residue consumption logic."""

from __future__ import annotations

from defs.sec_forms.cover.structure import is_continuation_prose
from defs.sec_forms.page_markers import is_page_marker_line
from defs.text.tokens import BULLET_MARKERS

from .analysis import is_anachronistic_late_item, is_toc_row, normalize_for_matching
from .patterns import _RE_WEAK_HEADING, RE_TOC_HEADING, RE_TOC_ITEM, RE_TOC_LEADER


def consume_toc_residue(
    lines: list[str],
    start_index: int,
    limit: int,
    derived_taxonomy: dict | None = None,
    page_marker_lines: set[int] | None = None,
) -> int:
    """Advance past trailing TOC residue until substantive body prose begins."""
    curr = start_index
    late_item_re = derived_taxonomy.get("late_item_re") if derived_taxonomy else None
    norm_late_names = (
        derived_taxonomy.get("norm_late_names", ()) if derived_taxonomy else ()
    )
    norm_early_names = (
        derived_taxonomy.get("norm_early_names", ()) if derived_taxonomy else ()
    )

    while curr < limit:
        line = lines[curr].strip()
        if not line or line.startswith(("+---", "====")):
            curr += 1
            continue

        clean_line = line.strip("|+").strip()
        if not clean_line:
            curr += 1
            continue

        if curr in (page_marker_lines or set()) or is_page_marker_line(clean_line):
            curr += 1
            continue

        norm_line = normalize_for_matching(clean_line)

        if line.startswith(("*", "Note:", "NOTE:")):
            curr += 1
            continue

        if len(clean_line) > 200:
            break

        if (
            any(name in norm_line for name in norm_early_names)
            and curr + 1 < limit
            and is_continuation_prose(lines[curr + 1])
        ):
            break

        if (
            clean_line.upper() in ("PART I", "PART 1") or RE_TOC_ITEM.match(clean_line)
        ) and (
            curr + 1 < limit
            and not (
                is_toc_row(lines[curr + 1]) or RE_TOC_LEADER.search(lines[curr + 1])
            )
        ):
            break

        if RE_TOC_HEADING.match(clean_line) or _RE_WEAK_HEADING.match(clean_line):
            curr += 1
            continue

        if is_toc_row(clean_line) or RE_TOC_LEADER.search(clean_line):
            curr += 1
            continue

        if is_anachronistic_late_item(clean_line, late_item_re, norm_late_names):
            curr += 1
            continue

        if clean_line in BULLET_MARKERS or (
            clean_line.isdigit() and len(clean_line) <= 4
        ):
            curr += 1
            continue

        break

    return curr


__all__ = ["consume_toc_residue"]
