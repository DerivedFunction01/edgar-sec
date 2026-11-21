from __future__ import annotations

import re

from edgar_sec.engine.forms.ownership.sections import ClassifiedSection

_FOOTNOTE_ENTRY_RE = re.compile(
    r"^\s*(?:[\(\[]\s*(\d{1,3})\s*[\)\]]|(\d{1,3})\.)\s*(.+)",
    re.MULTILINE,
)
_FOOTNOTE_PREFIX_CHARS = frozenset("([0123456789*")


def parse_footnotes(sections: list[ClassifiedSection]) -> dict[str, str]:
    footnotes: dict[str, str] = {}
    for section in sections:
        for row in section.resolved_grid.rows:
            for cell in row:
                if not cell:
                    continue
                for line in cell.splitlines():
                    stripped = line.lstrip()
                    if not stripped or stripped[0] not in _FOOTNOTE_PREFIX_CHARS:
                        continue
                    match = _FOOTNOTE_ENTRY_RE.match(stripped)
                    if match:
                        footnote_id = match.group(1) or match.group(2)
                        text = match.group(3).strip()
                        if footnote_id and text:
                            footnotes[footnote_id] = text
    return footnotes


__all__ = ["parse_footnotes"]
