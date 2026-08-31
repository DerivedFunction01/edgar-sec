"""Shared structured heading matching with form-specific grammars."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from defs.regex import build_alternation

HeaderKind = Literal["part", "section", "item"]


@dataclass(frozen=True, slots=True)
class HeaderGrammar:
    """Compiled grammar for one form family's structural headings."""

    part: re.Pattern[str] | None = None
    section: re.Pattern[str] | None = None
    item: re.Pattern[str] | None = None


@dataclass(frozen=True, slots=True)
class HeaderMatch:
    """Structured result for a matched form heading."""

    kind: HeaderKind
    identifier: str
    title: str
    start: int
    end: int


def make_grammar(
    *,
    part_numbers: list[str] | None = None,
    item_numbers: str | None = None,
    section_numbers: str | None = None,
    item_separator: str = r"\s*[\.:\-–—]\s*",
) -> HeaderGrammar:
    """Compile a form grammar once from its allowed identifiers."""
    part = None
    if part_numbers:
        part_alt = build_alternation(part_numbers)
        part = re.compile(
            rf"(?im)^\s*(?P<identifier>part\s+(?:{part_alt}))\s*[\.:\-–—]?\s*$"
        )

    item = None
    if item_numbers:
        item = re.compile(
            rf"(?im)^\s*(?P<identifier>item\s+(?:{item_numbers})[a-z]?)(?:{item_separator})(?P<title>.*?)\s*$"
        )

    section = None
    if section_numbers:
        section = re.compile(
            rf"(?im)^\s*(?P<identifier>section\s+(?:{section_numbers}))\s*[\-–—]\s*(?P<title>[^.\n]+)\s*$"
        )
    return HeaderGrammar(part=part, section=section, item=item)


FORM_10K_GRAMMAR = make_grammar(
    part_numbers=[r"i{1,4}", "iv", "v"], item_numbers=r"1[0-6]?|[1-9]"
)
FORM_10Q_GRAMMAR = make_grammar(part_numbers=[r"i{1,2}", "ii"], item_numbers=r"[1-6]")
FORM_8K_GRAMMAR = make_grammar(
    item_numbers=r"[1-9]\.[0-9]{2}",
    section_numbers=r"[1-9]",
    item_separator=r"(?:[\.:\-–—]\s*|\s+)",
)


def match_header(text: str, grammar: HeaderGrammar) -> HeaderMatch | None:
    """Return the first structured heading match in document order."""
    candidates: list[HeaderMatch] = []
    for kind, pattern in (
        ("part", grammar.part),
        ("section", grammar.section),
        ("item", grammar.item),
    ):
        if pattern is None:
            continue
        match = pattern.search(text)
        if match:
            candidates.append(
                HeaderMatch(
                    kind,
                    match.group("identifier"),
                    match.groupdict().get("title") or "",
                    match.start(),
                    match.end(),
                )
            )
    return (
        min(candidates, key=lambda candidate: candidate.start) if candidates else None
    )


def normalize_headers(text: str, grammar: HeaderGrammar) -> str:
    """Normalize headings using one shared replacement algorithm."""
    normalized = text

    def replace_part(match: re.Match[str]) -> str:
        return f"\n\n{match.group('identifier').upper()}\n"

    def replace_section(match: re.Match[str]) -> str:
        return f"\n\n{match.group(0).strip().upper()}\n"

    def replace_item(match: re.Match[str]) -> str:
        title = match.group("title").strip()
        suffix = f". {title}" if title else "."
        return f"\n\n{match.group('identifier').upper()}{suffix}\n"

    if grammar.part:
        normalized = grammar.part.sub(replace_part, normalized)
    if grammar.section:
        normalized = grammar.section.sub(replace_section, normalized)
    if grammar.item:
        normalized = grammar.item.sub(replace_item, normalized)
    return normalized


__all__ = [
    "FORM_8K_GRAMMAR",
    "FORM_10K_GRAMMAR",
    "FORM_10Q_GRAMMAR",
    "HeaderGrammar",
    "HeaderMatch",
    "make_grammar",
    "match_header",
    "normalize_headers",
]
