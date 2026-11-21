from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

_EXHIBIT_PREFIX = build_alternation(("dex", "exhibit", "ex"), auto_escape=True)
_EXHIBIT_EXTENSION = build_alternation(("txt", "htm", "html"), auto_escape=True)
_STATUTORY_NUMBER = build_alternation(
    (r"[1-9]", r"[1-9]\d", r"10[0-5]"), auto_escape=False
)
PRIMARY_EXHIBIT_FILENAME_PATTERN = (
    rf"^(?:{_EXHIBIT_PREFIX})[-_]?{_STATUTORY_NUMBER}"
    rf"(?:[-._][a-z0-9]+)?\.(?:{_EXHIBIT_EXTENSION})$"
)
_PRIMARY_EXHIBIT_FILENAME = re.compile(PRIMARY_EXHIBIT_FILENAME_PATTERN, re.IGNORECASE)


def is_primary_exhibit_filename(filename: str | None) -> bool:
    if not filename:
        return False
    return _PRIMARY_EXHIBIT_FILENAME.fullmatch(filename.strip()) is not None


__all__ = ["PRIMARY_EXHIBIT_FILENAME_PATTERN", "is_primary_exhibit_filename"]
