"""Content and rule line shapes no furniture route may claim.
One home for the line predicates the candidate, template, and policy routes share: a content
line is document content even when it repeats, and a rule line is table structure, not text.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE

_CONTENT_SHAPE_RE = re.compile(
    build_alternation(
        (
            r"/s/",
            r"\bcusip\b",
            r"\bisin\b",
            r"\)\s*ss:",
            r"^\s*by\s*:",
            r"^\s*name\s*:",
            r"^\s*title\s*:",
            r"^\s*schedule\s+of\s+investments\b",
            r"^\s*state\s+of\s+.*\)\s*$",
            r"^\s*county\s+of\s+.*\)\s*$",
            r"^\s*the\s+commonwealth\s+of\s+.*\)\s*$",
            r"\bfinancial\s+statements?\b",
            r"\bbalance\s+sheets?\b",
            r"\bstatements?\s+of\b",
            r"^\s*see\s+accompanying\s+notes\b",
            r"^\s*see\s+notes\s+to\b",
        ),
        auto_escape=False,
    ),
    re.IGNORECASE,
)


def is_content_line(text: str) -> bool:
    """Whether a line carries document content no furniture route may claim.
    Signature, jurat, schedule- and statement-title, and identifier lines are cover content even when they repeat at an anchor.
    """
    return bool(_CONTENT_SHAPE_RE.search(text))


#: Em- and en-dash rule runs: the separator border RE_SEPARATOR_LINE's ASCII class misses.
_DASH_RULE_RE = re.compile(r"^[—–]{2,}(?:\s+[—–]{2,})*$")
#: A single rule run over the wider rule-character set, asterisks and the horizontal bar included.
_RULE_ONLY_RE = re.compile(r"^[-_=—–―*]{3,}$")


def is_rule_line(text: str) -> bool:
    """Whether a line is only a rule: separator runs and nothing else.
    A rule line is table structure, so it is neither a furniture observation nor table content.
    """
    stripped = text.strip()
    return bool(
        RE_SEPARATOR_LINE.fullmatch(stripped)
        or _DASH_RULE_RE.fullmatch(stripped)
        or _RULE_ONLY_RE.fullmatch(stripped)
    )


__all__ = [
    "is_content_line",
    "is_rule_line",
]
