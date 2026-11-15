"""Labor capture: schema-led prose-to-table conversion.

The shape is employee group x contract x union, named in prose
per group; linkage terms find the span, fields bind inside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import RE_DATE_OR_YEAR

PROV_LABOR_CAPTURE = "labor-capture:prose_conversion"

LINKAGE_TERMS = (
    "collective bargaining",
    "bargaining agreement",
    "bargaining unit",
    "labor agreement",
    "labour agreement",
    "union contract",
    "represented by a union",
    "represented by unions",
    "covered by a collective",
)
UNION_ACRONYMS = (
    "UAW",
    "IBEW",
    "USW",
    "SEIU",
    "UFCW",
    "IAM",
    "CWA",
    "AFSCME",
    "AFL-CIO",
    "UNITE",
    "LIUNA",
    "IBT",
    "OPEIU",
    "RWDSU",
)
_TERM_KEYWORDS = ("expir", "ratifi", "effective", "renew", "through", "until")
_NEGATION_RE = re.compile(
    build_alternation(
        (
            rf"none of (?:{build_alternation(('our', 'the'), auto_escape=True)})"
            rf" employees (?:{build_alternation(('are', 'is'), auto_escape=True)})",
            "no employees are",
            "not represented by",
            "are not members of",
            r"no .*collective bargaining unit",
        )
    ),
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    rf"(?:{build_alternation(('approximately', 'about', 'nearly'), auto_escape=True)})?"
    r"\s*([\d,]+)\s+"
    rf"({build_alternation(('full-time', 'part-time'), auto_escape=True)}\s+)?"
    rf"({build_alternation(('employees', 'associates', 'workers', 'team members'), auto_escape=True)})",
    re.IGNORECASE,
)
_LOCAL_RE = re.compile(
    build_alternation(
        (
            r"\b(?P<acr>[A-Z]{2,6})\s+Local\s+(?P<num1>\d+)\b",
            r"\bLocal\s+(?P<num2>\d+)\b",
            rf"\b(?P<name>(?:{build_alternation(('International', 'United', 'National', 'American'), auto_escape=True)})\s+"
            rf"(?:[A-Z][a-z]+\s+){{0,3}}?"
            rf"{build_alternation(('Workers', 'Brotherhood', 'Union', 'Association', 'Federation', 'Guild'), auto_escape=True)})\b",
        )
    )
)
_ACRONYM_RE = re.compile(
    rf"\b(?:{build_alternation(UNION_ACRONYMS, auto_escape=True)})\b"
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class LaborRow:
    """One bound row of the labor schema; text-valued by design."""

    employee_group: str | None
    employee_count: int | None
    union: str | None
    contract_terms: tuple[str, ...]
    negated: bool
    span: str
    provenance: str = PROV_LABOR_CAPTURE


def _sentences(prose: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(prose or "") if part.strip()]


def _union_in(span: str) -> str | None:
    match = _LOCAL_RE.search(span)
    if match is not None:
        if match.group("acr"):
            return f"{match.group('acr')} Local {match.group('num1')}"
        if match.group("num2"):
            return f"Local {match.group('num2')}"
        return match.group("name")
    acronym = _ACRONYM_RE.search(span)
    return acronym.group(0) if acronym is not None else None


def _contract_terms(span: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in RE_DATE_OR_YEAR.finditer(span):
        start = max(0, match.start() - 60)
        lead = span[start : match.start()].lower()
        if any(keyword in lead for keyword in _TERM_KEYWORDS):
            terms.append(span[start : match.end()].strip(" ,;"))
    return tuple(dict.fromkeys(terms))


def _bind(span: str) -> LaborRow:
    negated = _NEGATION_RE.search(span) is not None
    count = None
    group = None
    match = _COUNT_RE.search(span)
    if match is not None:
        count = int(match.group(1).replace(",", ""))
        group = (match.group(2) or "").strip() + match.group(3)
    elif "employees" in span.lower():
        group = "employees"
    return LaborRow(
        employee_group=group,
        employee_count=count,
        union=None if negated else _union_in(span),
        contract_terms=() if negated else _contract_terms(span),
        negated=negated,
        span=span,
    )


def _field_evidence(sentence: str) -> bool:
    return (
        RE_DATE_OR_YEAR.search(sentence) is not None
        or _COUNT_RE.search(sentence) is not None
        or _union_in(sentence) is not None
        or any(keyword in sentence.lower() for keyword in _TERM_KEYWORDS)
    )


def capture_labor(prose: str) -> tuple[LaborRow, ...]:
    """Bind labor rows from prose; linkage terms are the generator.

    A span is a linked sentence plus its field-carrying followers;
    schedule-header terms bind inside a span, never generate one.
    """
    sentences = _sentences(prose)
    rows: list[LaborRow] = []
    seen: set[str] = set()
    index = 0
    while index < len(sentences):
        sentence = sentences[index]
        lowered = sentence.lower()
        linked = any(term in lowered for term in LINKAGE_TERMS)
        negated = _NEGATION_RE.search(sentence) is not None
        index += 1
        if not linked and not negated:
            continue
        parts = [sentence]
        while (
            index < len(sentences)
            and len(parts) < 3
            and not any(term in sentences[index].lower() for term in LINKAGE_TERMS)
            and _field_evidence(sentences[index])
        ):
            parts.append(sentences[index])
            index += 1
        span = " ".join(parts)
        key = " ".join(span.lower().split())
        if key in seen:
            continue
        seen.add(key)
        rows.append(_bind(span))
    return tuple(rows)


def capture_from_context(context: TableContext) -> tuple[LaborRow, ...]:
    """Capture labor rows from a context's surrounding prose."""
    prose = " ".join(
        part for part in (context.prose_before, context.prose_after) if part
    )
    return capture_labor(prose)
