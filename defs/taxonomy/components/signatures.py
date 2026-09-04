"""Canonical signature block and officer title concepts."""

from __future__ import annotations

import re

from defs.regex import build_alternation

SIGNATURE_MARKERS: tuple[str, ...] = (
    "/s/",
    "/ s /",
    "by:",
    "title:",
    "date:",
    "signature",
    "signatures",
    "pursuant to the requirements",
)

OFFICER_TITLES: tuple[str, ...] = (
    "chief executive officer",
    "chief financial officer",
    "principal executive officer",
    "principal financial officer",
    "principal accounting officer",
    "president",
    "vice president",
    "executive vice president",
    "senior vice president",
    "treasurer",
    "secretary",
    "director",
    "co-founder",
    "chair of the board",
    "chairman of the board",
    "chairperson",
)

# Words too generic to act as title evidence on their own.
_OFFICER_HINT_STOPWORDS: frozenset[str] = frozenset(
    {"and", "the", "of", "board", "executive", "senior", "lead", "independent"}
)

# Distinctive stem words extracted once from OFFICER_TITLES so the hint
# pattern can never drift from the canonical vocabulary: adding a title to
# OFFICER_TITLES automatically extends the hint.
_OFFICER_HINT_STEMS: tuple[str, ...] = tuple(
    sorted(
        {
            word
            for title in OFFICER_TITLES
            for word in title.split()
            if word not in _OFFICER_HINT_STOPWORDS and len(word) > 3
        },
        key=len,
        reverse=True,
    )
)

# Broad title-evidence hint composed from the canonical vocabulary. This is a
# fuzzy signal for signer-vs-title disambiguation inside a confirmed signature
# block, not a validator: full titles vary (``Chief Compliance Officer``,
# ``Controller``) while the stem vocabulary stays stable.
OFFICER_TITLE_HINT_RE = re.compile(
    rf"\b(?:{build_alternation(_OFFICER_HINT_STEMS)})",
    re.IGNORECASE,
)
