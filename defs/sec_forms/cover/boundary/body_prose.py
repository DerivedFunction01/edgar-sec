"""Body prose detection logic for cover boundary."""

from __future__ import annotations

from defs.sec_forms.cover.body_search import (
    _is_toc_like_line,
    _score_body_paragraph,
)


def _find_body_prose_line(
    lines: list[str],
    start_line: int,
    search_limit: int,
    rules: object,
) -> int | None:
    """First logical unit with decisive body-lexical evidence (score >= 2).

    Accumulates consecutive prose lines into bounded paragraphs so wrapped
    text reaches the lexical gate, skipping tagged tables and TOC-like lines.
    """
    buffer: list[str] = []
    buffer_start: int | None = None
    in_table = False

    def score_and_check() -> int | None:
        nonlocal buffer, buffer_start
        if not buffer or buffer_start is None:
            return None
        paragraph = " ".join(line for line in buffer if line)
        if len(paragraph.split()) < 8:
            return None
        score = _score_body_paragraph(paragraph, rules.lexical)
        if score.score >= 2:
            return buffer_start
        return None

    for index in range(max(0, start_line), min(search_limit, len(lines))):
        stripped = lines[index].strip()
        upper = stripped.upper()
        if "<TABLE" in upper:
            in_table = True
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
            continue
        if "</TABLE" in upper:
            in_table = False
            continue
        if in_table or _is_toc_like_line(stripped):
            continue
        if not stripped:
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
            continue
        if not buffer:
            buffer_start = index
        buffer.append(stripped)
        if len(" ".join(buffer).split()) >= 160:
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
    return _return_with_heading(result=score_and_check(), lines=lines, rules=rules)


def _return_with_heading(
    result: int | None, lines: list[str], rules: object
) -> int | None:
    """Walk a scored prose start back over preceding body-semantic headings."""
    from defs.sec_forms.cover.body_search import _is_toc_like_line

    if result is None:
        return None
    position = result
    for back in range(result - 1, max(0, result - 5) - 1, -1):
        line = lines[back].strip()
        if not line:
            continue
        if len(line) > 70:
            break
        if not rules.body_semantic.search(line):
            break
        if _is_toc_like_line(line):
            break
        position = back
    return position
