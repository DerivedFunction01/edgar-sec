"""Regex patterns, constants, and numeral definitions for page marker detection."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.text.patterns import PAGE_NUMBER_CORE

from .models import PageMarkerKind

_RE_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_PAGE_NUMBER = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]*$", re.IGNORECASE
)
_RE_DASHED_NUMBER = re.compile(r"(?im)^[ \t]*-[ \t]*(?P<page>\d+)[ \t]*-[ \t]*$")
_RE_LETTER_NUMBER = re.compile(
    r"(?im)^\s*(?:page\s+)?(?P<prefix>[A-Z])\s*[-–—]\s*(?P<page>\d+)\s*$"
)
_RE_SGML_LINE = re.compile(
    r"(?im)^[ \t]*</?PAGE\b[^>]*>[ \t]*(?P<page>\d+)?[ \t]*"
    r"(?:</?PAGE\b[^>]*>)?[ \t]*$"
)
_RE_SGML_INLINE = re.compile(r"(?i)</?PAGE\b[^>]*>")
_RE_BOUNDARY = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")
_WRAPPERS = build_alternation(["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True)
_RE_DASH_LABEL = re.compile(
    rf"^(?=.*(?:{_WRAPPERS}))(?:{_WRAPPERS}|\s)+"
    rf"(?P<value>\d{{1,4}}|[ivxlcdm]{{1,8}})"
    rf"(?:{_WRAPPERS}|\s)+$",
    re.IGNORECASE,
)
_RE_PIPE_LABEL = re.compile(
    r"^\|\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\|$", re.IGNORECASE
)
_RE_PAREN_LABEL = re.compile(
    r"^\(\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\)$", re.IGNORECASE
)
_RE_SIMPLE_WRAPPED_LABEL = re.compile(
    r"^(?:[|]\s*\d{1,4}\s*[|]|\(\s*\d{1,4}\s*\)|\d{1,4}\.)$"
)
_RE_DOTTED_LABEL = re.compile(r"^(?P<value>\d{1,4})\.$")
_RE_BARE_ARABIC = re.compile(r"^(?P<value>\d{1,4})$")
_RE_BARE_ROMAN = re.compile(r"^(?P<value>[ivxlcdm]{1,8})$", re.IGNORECASE)
_RE_LEADING_NUMBER = re.compile(r"^(?P<value>\d{1,4})\s{1,}\S.*$")
_RE_TRAILING_NUMBER = re.compile(r"^\S.*?\s{2,}(?P<value>\d{1,4})$")
_RE_INLINE_PAGE = re.compile(
    r"^(?P<prefix>.{0,80}?\bpage\s+)(?P<value>\d{1,4})\b(?P<suffix>.{0,80})$",
    re.IGNORECASE,
)
_STRUCTURAL_WORDS = build_alternation(
    ["part", "item", "exhibit", "note"], auto_escape=True
)
_PAGE_MARKER_PATTERNS = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _RE_PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _RE_NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _RE_PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _RE_DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, _RE_LETTER_NUMBER),
    (PageMarkerKind.SGML, _RE_SGML_LINE),
    (PageMarkerKind.SGML, _RE_SGML_INLINE),
)
RE_PAGE_SUFFIX = re.compile(
    rf"(?:\b[A-Z])?[\.\-\s]?{PAGE_NUMBER_CORE}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

_NUMERALS = (
    ("m", 1000),
    ("cm", 900),
    ("d", 500),
    ("cd", 400),
    ("c", 100),
    ("xc", 90),
    ("l", 50),
    ("xl", 40),
    ("x", 10),
    ("ix", 9),
    ("v", 5),
    ("iv", 4),
    ("i", 1),
)

_PAGE_WORDS = build_alternation(
    [
        "page",
        "page-no",
        "page_no",
        "pageno",
        "page-number",
        "page_number",
        "folio",
        "pgbrk",
        "pagebreak",
        "footer",
    ],
    auto_escape=True,
)
_TOC_WORDS = build_alternation(
    ["toc", "contents", "table-of-contents", "table_of_contents", "index"],
    auto_escape=True,
)
_VALUE_RE = re.compile(
    r"^(?:page\s+)?(?P<value>\d{1,4}|[ivxlcdm]{1,8})$|"
    r"^(?:[-–—|·•▪()]\s*)+(?P<wrapped>\d{1,4}|[ivxlcdm]{1,8})"
    r"(?:\s*[-–—|·•▪()])+$",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"^(?P<value>\d{1,4})$")
_HIDDEN_STYLE_VALUES = build_alternation(
    [r"display\s*:\s*none", r"visibility\s*:\s*hidden", "hidden"]
)
_HIDDEN_STYLE_RE = re.compile(rf"(?:{_HIDDEN_STYLE_VALUES})", re.IGNORECASE)
_RE_HIDDEN_TEMPLATE = re.compile(r"(?:^|[\s_-])(?:hidden|template)(?:$|[\s_-])")
_RE_PAGE_SEMANTIC = re.compile(rf"(?:^|[\s_-])(?:{_PAGE_WORDS})(?:$|[\s_-])")
_RE_TOC_SEMANTIC = re.compile(rf"(?:^|[\s_-])(?:{_TOC_WORDS})(?:$|[\s_-])")
_RE_STRUCTURAL_MATCH = re.compile(rf"(?i)^(?:{_STRUCTURAL_WORDS})\b")

# Function words that empirically never appear in captured page header/footer
# text. Derived by probing all 2,202 ASCII fixtures: corpus of captured
# REPEATING_HEADER/REPEATING_FOOTER marker text versus sampled body lines
# (footer document-frequency == 0, body document-frequency >= 25%). Words that
# legitimately occur in footer titles ("the", "of", "for", "to", "no",
# "which", "during", "must") are deliberately excluded. Used to reject
# prose-bearing lookalike tables (footnote tables, comparison tables).
PROSE_GUARD_STOP_WORDS = frozenset(
    [
        "about",
        "above",
        "all",
        "also",
        "any",
        "because",
        "been",
        "being",
        "below",
        "both",
        "can",
        "could",
        "do",
        "does",
        "each",
        "had",
        "has",
        "have",
        "herein",
        "however",
        "is",
        "more",
        "most",
        "only",
        "over",
        "same",
        "should",
        "some",
        "such",
        "than",
        "there",
        "these",
        "this",
        "those",
        "through",
        "until",
        "was",
        "were",
        "when",
        "who",
        "will",
        "would",
    ]
)
_RE_APPENDIX_ROMAN = re.compile(
    r"^(?P<prefix>[A-Za-z])-(?P<value>[ivxlcdm]{1,8})$",
    re.IGNORECASE,
)

_PAGE_BREAK_VALUES = build_alternation(
    ["always", "left", "right", "page"],
    auto_escape=True,
)

# Filing-platform signature vocabulary for the layout-recipe memo. New
# generators discovered by exploratory probes are appended here; the
# alternation is compiled once. Matched against normalized leading HTML
# comments (whitespace collapsed, digits replaced with '#').
RECIPE_PLATFORM_WORDS = build_alternation(
    [
        "workiva",
        "wdesk",
        "webfilings",
        "dfin",
        "donnelley",
        "broadridge",
        "toppan",
        "merrill",
        "pagebreak",
        "rule-page",
        "rule_page",
        "xbrlmaster",
        "converter",
        "field: page",
        "field:rule-page",
    ],
    auto_escape=True,
)
_RECIPE_PLATFORM_RE = re.compile(rf"(?:{RECIPE_PLATFORM_WORDS})", re.IGNORECASE)

# HTML page-hint vocabulary for attribute-based fast-path discovery.
# Attribute values (class/id/name) and CSS property names are normalized by
# lowercasing and stripping every non-alphanumeric character, then replacing
# digit runs with "#" so page_1/page_2/... share one container alias, before
# alias lookup. This collapses spellings such as page-break, page_break,
# "page break", and ct-page-break into one alias without fuzzy per-character
# matching. Roles: break, number, header, footer, container, page_semantic.
_HINT_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")
_HINT_DIGITS_RE = re.compile(r"\d+")
_PAGE_BREAK_PROPERTY_ALIASES = frozenset(
    {"pagebreakbefore", "pagebreakafter", "breakbefore", "breakafter"}
)
_PAGE_BREAK_VALUE_ALIASES = frozenset({"always", "left", "right", "page"})
PAGE_HINT_ROLES: dict[str, tuple[str, ...]] = {
    "pagebreak": ("break",),
    "ctpagebreak": ("break",),
    "pgbrk": ("break",),
    "pgbk": ("break",),
    "pagebreakbefore": ("break",),
    "pagebreakafter": ("break",),
    "breakbefore": ("break",),
    "breakafter": ("break",),
    "dspfpagebreak": ("break",),
    "dspfpagebreakarea": ("break",),
    "lastpagebreak": ("break",),
    "pgnum": ("number",),
    "pagenum": ("number",),
    "pagenumber": ("number",),
    "dspfpagenumber": ("number",),
    "dspfpagenumberarea": ("number",),
    "tocpgnum": ("number",),
    "acipg#": ("number",),
    "pghdr": ("header",),
    "pageheader": ("header",),
    "headercontainer": ("header",),
    "bclheader": ("header",),
    "pgftr": ("footer",),
    "pagefooter": ("footer",),
    "footercontainer": ("footer",),
    "bclfooter": ("footer",),
    "ctheaderfooterpage": ("header", "footer"),
    "page#": ("container",),
    "pagenodecontent": ("container",),
    "eolpage#": ("container",),
}
_RAW_HINT_ATTR_RE = re.compile(
    rf"(?is)\b({build_alternation(['class', 'name', 'id', 'style'])})\s*=\s*"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
_HINT_TOKEN_SPLIT_RE = re.compile(r"[\s;,:]+")


def _normalized_hint_token(token: str) -> str:
    return _HINT_DIGITS_RE.sub("#", _HINT_SEPARATOR_RE.sub("", token.casefold()))


def page_hint_roles(token: str) -> tuple[str, ...]:
    """Resolve one attribute token to its page-hint roles, if any."""

    return PAGE_HINT_ROLES.get(_normalized_hint_token(token), ())


def page_hint_roles_for_attrs(attrs: dict) -> tuple[str, ...]:
    """Single page-hint entry point over one node's attributes.

    Roles combine the alias vocabulary (``PAGE_HINT_ROLES``), the classic
    page-word semantics (``_RE_PAGE_SEMANTIC`` -> ``page_semantic``), and
    value-aware CSS break detection (``page-break-before: always`` -> break,
    ``: avoid`` -> no role). This replaces separate semantic, break, and
    hint lookups for HTML candidate discovery.
    """
    roles: list[str] = []

    def add_token(value: object) -> None:
        if not value:
            return
        tokens = value if isinstance(value, list) else [value]
        for token in tokens:
            for part in _HINT_TOKEN_SPLIT_RE.split(str(token)):
                if not part:
                    continue
                for role in page_hint_roles(part):
                    if role not in roles:
                        roles.append(role)
                if _RE_PAGE_SEMANTIC.search(part) and "page_semantic" not in roles:
                    roles.append("page_semantic")

    for key in ("class", "id", "name", "title", "data-page", "data-page-number"):
        add_token(attrs.get(key))
    for declaration in str(attrs.get("style", "")).split(";"):
        prop, _, value = declaration.partition(":")
        if _normalized_hint_token(prop) in _PAGE_BREAK_PROPERTY_ALIASES:
            normalized_value = _HINT_SEPARATOR_RE.sub("", value.casefold())
            if normalized_value in _PAGE_BREAK_VALUE_ALIASES and "break" not in roles:
                roles.append("break")
    return tuple(roles)


__all__ = [
    "PAGE_HINT_ROLES",
    "PROSE_GUARD_STOP_WORDS",
    "RE_PAGE_SUFFIX",
    "_HIDDEN_STYLE_RE",
    "_HIDDEN_STYLE_VALUES",
    "_NUMERALS",
    "_NUMERIC_RE",
    "_PAGE_MARKER_PATTERNS",
    "_PAGE_WORDS",
    "_RE_APPENDIX_ROMAN",
    "_RE_BARE_ARABIC",
    "_RE_BARE_ROMAN",
    "_RE_BOUNDARY",
    "_RE_DASHED_NUMBER",
    "_RE_DASH_LABEL",
    "_RE_DOTTED_LABEL",
    "_RE_HIDDEN_TEMPLATE",
    "_RE_INLINE_PAGE",
    "_RE_LEADING_NUMBER",
    "_RE_LETTER_NUMBER",
    "_RE_NUMBER_OF_TOTAL",
    "_RE_PAGE_NUMBER",
    "_RE_PAGE_NUMBER_OF_TOTAL",
    "_RE_PAGE_SEMANTIC",
    "_RE_PAREN_LABEL",
    "_RE_PIPE_LABEL",
    "_RE_SGML_INLINE",
    "_RE_SGML_LINE",
    "_RE_SIMPLE_WRAPPED_LABEL",
    "_RE_STRUCTURAL_MATCH",
    "_RE_TOC_SEMANTIC",
    "_RE_TRAILING_NUMBER",
    "_STRUCTURAL_WORDS",
    "_TOC_WORDS",
    "_VALUE_RE",
    "_WRAPPERS",
    "page_hint_roles",
    "page_hint_roles_for_attrs",
]
