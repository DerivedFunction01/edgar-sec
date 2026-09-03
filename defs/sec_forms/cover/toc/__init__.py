"""Table of contents span detection package.

Re-exports the full public API so existing imports from
``defs.sec_forms.cover.toc`` continue to work unchanged after the module
was split into this package.
"""

from __future__ import annotations

from defs.sec_forms.page_markers import RE_PAGE_SUFFIX

from .analysis import (
    is_anachronistic_late_item,
    is_toc_row,
    normalize_for_matching,
    score_block_toc_density,
)
from .finder import find_toc_span
from .models import TocEvidence, TocSpan
from .patterns import (
    RE_TOC_HEADING,
    RE_TOC_ITEM,
    RE_TOC_LEADER,
    RE_TOC_PART_TEXT,
    WEAK_TOC_HEADINGS,
)
from .residue import consume_toc_residue

__all__ = [
    "RE_PAGE_SUFFIX",
    "RE_TOC_HEADING",
    "RE_TOC_ITEM",
    "RE_TOC_LEADER",
    "RE_TOC_PART_TEXT",
    "WEAK_TOC_HEADINGS",
    "TocEvidence",
    "TocSpan",
    "consume_toc_residue",
    "find_toc_span",
    "is_anachronistic_late_item",
    "is_toc_row",
    "normalize_for_matching",
    "score_block_toc_density",
]
