"""Shared document builders for the page-marker policy suites."""

from __future__ import annotations

NO_TOC = {"toc_lines": frozenset({-1})}


def _paged(
    pages: int, header: str = "", footer: str = "", label: str = "<PAGE>"
) -> str:
    lines: list[str] = []
    for index in range(1, pages + 1):
        lines.append(label)
        if header:
            lines.append(header)
        lines.append(f"Body {index}")
        if footer:
            lines.append(footer)
    return "\n".join(lines)
