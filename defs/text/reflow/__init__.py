"""Conservative ASCII prose reflow and untagged-table tagging.

This is the Stage-4 span/action engine for plain-text (non-HTML) filings. It
classifies each blank-line-delimited block and renders the canonical output
from exact decisions:

- ``UNWRAP``: join ordinary hard-wrapped prose lines with single spaces.
- ``PRESERVE``: emit the original span unchanged, no tags.
- ``TAG_AND_PRESERVE``: emit the original span unchanged between uppercase
  ``<TABLE>``/``</TABLE>`` markers.

Safety bias is deliberate: a missed unwrap leaves prose hard-wrapped, but a
collapsed table corrupts financial data. Ambiguous blocks therefore always
resolve to ``PRESERVE``. Existing tagged ``<TABLE>`` blocks are masked before
analysis via ``defs.tables.protection`` and restored byte-for-byte; they are
never reclassified or reflowed.

All operations are deterministic and line-based. Decisions carry half-open
line ranges in the coordinate frame of the text passed in.
"""

from __future__ import annotations

from .engine import reflow_ascii
from .types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowResult,
    SpanDecision,
)

__all__ = [
    "ACTION_PRESERVE",
    "ACTION_TAG_AND_PRESERVE",
    "ACTION_UNWRAP",
    "ReflowResult",
    "SpanDecision",
    "reflow_ascii",
]
