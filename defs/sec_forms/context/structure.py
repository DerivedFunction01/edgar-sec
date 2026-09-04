"""HTML structure scanner (Phase B).

Builds a deterministic, representation-neutral structure index from a
BeautifulSoup tree in a *single* ``soup.descendants`` walk:

- :class:`HeadingNode` for h1-h6 + b/strong + bold-styled div/span/p +
  short, anchored plain div/span/p headings;
- :class:`BlockNode` for logical blocks (``p``, ``li``, ``caption``,
  validated headings, and leaf div/span blocks);
- :class:`TableNode` for tables, with parent/child relationships preserved
  for nested tables.

The scanner deliberately:

- does not depend on BeautifulSoup ``sourceline``/``sourcepos`` (the
  repository's lxml setup does not populate them reliably — the research
  probe validated this);
- excludes candidates inside tables so TOC rows cannot become body
  headings;
- skips ``script``, ``style``, ``meta``, ``noscript``, comments, and
  ``ix:hidden`` subtrees;
- joins adjacent inline strings so ``<span>T</span>he`` becomes ``The``;
- stores bounded preceding 1-2 blocks and following 1 block per
  :class:`BlockNode` (raw text, no normalization).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, NavigableString

from defs.regex import build_alternation
from defs.sec_forms.context.models import TableNode
from defs.sec_forms.cover.structure import SectionKind, parse_section_heading
from defs.sec_forms.forms.registry import _taxonomy_normalize, get_taxonomy_matcher

__all__ = [
    "SKIP_TAGS",
    "BlockNode",
    "HeadingNode",
    "HtmlStructureIndex",
    "scan_html",
]

SKIP_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "meta",
    "noscript",
    "ix:hidden",
    "ix:header",
)

_HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_STRONG_TAGS: frozenset[str] = frozenset({"b", "strong"})
_BOLD_BRANCHES = build_alternation(["bold", "700", "800", "900"])
_BOLD_STYLE_RE = re.compile(
    rf"font-weight\s*:\s*(?:{_BOLD_BRANCHES})|font-style\s*:\s*italic",
    re.IGNORECASE,
)
_MAX_HEADING_LENGTH = 200
_MAX_BLOCK_LENGTH = 4000
_PRECEDING_BLOCKS = 2
_FOLLOWING_BLOCKS = 1


@dataclass(frozen=True, slots=True)
class HeadingNode:
    """A detected heading inside the structure index."""

    ordinal: int
    locator: str
    text: str
    fingerprint: str
    is_part: bool = False
    is_item: bool = False


@dataclass(frozen=True, slots=True)
class BlockNode:
    """A logical block of body text in document order.

    ``preceding_blocks`` and ``following_blocks`` are bounded raw text
    fragments from nearest neighbor blocks in the same document region.
    Table descendants (``td``/``th``) are excluded so that prose-formatted
    tables do not become preceding paragraphs.
    """

    ordinal: int
    locator: str
    text: str
    fingerprint: str
    preceding_blocks: tuple[str, ...]
    following_blocks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HtmlStructureIndex:
    """One deterministic view over a parsed HTML document.

    All fields are produced by a single ``soup.descendants`` walk; ordinals
    are stable for a given soup and parser. The index is versioned via
    ``schema_version`` and ``scanner_fingerprint`` for provenance.
    """

    document_id: str
    source_sha256: str
    headings: tuple[HeadingNode, ...]
    blocks: tuple[BlockNode, ...]
    tables: tuple[TableNode, ...]
    scanner_fingerprint: str
    schema_version: str = "1"

    def block_for_table(self, table_ordinal: int) -> BlockNode | None:
        """Return the nearest preceding block for a given table ordinal.

        This is a *weak* prior — caller must verify it against the actual
        DOM location of the table.
        """
        for block in self.blocks:
            if block.ordinal <= table_ordinal:
                return block
        return None


def _strip_and_join(node: object) -> str:
    """Return the visible text of ``node`` with inline fragments joined."""
    if isinstance(node, NavigableString):
        return str(node)
    pieces: list[str] = []
    for child in getattr(node, "children", ()):
        if isinstance(child, NavigableString):
            pieces.append(str(child))
        else:
            pieces.append(_strip_and_join(child))
    joined = "".join(pieces)
    return re.sub(r"\s+", " ", joined).strip()


def _is_skip_subtree(node: object) -> bool:
    if isinstance(node, Comment):
        return True
    name = getattr(node, "name", None)
    if name is None:
        return False
    lowered = str(name).lower()
    return lowered in SKIP_TAGS


def _inside_table(node: object) -> bool:
    """True if the node is inside any ``<table>`` ancestor."""
    for parent in getattr(node, "parents", ()):
        if parent is node:
            continue
        name = getattr(parent, "name", None)
        if name in {"table"}:
            return True
    return False


def _is_bold_styled(node: object) -> bool:
    style = node.get("style", "") if hasattr(node, "get") else ""
    return bool(_BOLD_STYLE_RE.search(style or ""))


def _candidate_heading(node: object, family: str | None = None) -> bool:
    if not hasattr(node, "name") or node.name is None:
        return False
    name = str(node.name).lower()
    if name in _HEADING_TAGS:
        return True
    if name in _STRONG_TAGS:
        return True
    if name in {"div", "span", "p"} and _is_bold_styled(node):
        return True
    if name in {"div", "span", "p"}:
        text = _strip_and_join(node)
        if (
            text
            and len(text) <= _MAX_HEADING_LENGTH
            and _looks_heading_like(text, family)
        ):
            return True
    return False


def _looks_heading_like(text: str, family: str | None = None) -> bool:
    lowered = text.casefold().strip()
    if not lowered or len(lowered) > 80:
        return False
    if parse_section_heading(text) is not None:
        return True
    return get_taxonomy_matcher(family).has_any(_taxonomy_normalize(text))


def _classify_heading(text: str) -> tuple[bool, bool]:
    parsed = parse_section_heading(text)
    if parsed is not None and parsed.is_exact_heading:
        return parsed.kind == SectionKind.PART, parsed.kind == SectionKind.ITEM
    return False, False


def _fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _locator(prefix: str, ordinal: int) -> str:
    return f"{prefix}-{ordinal:06d}"


def _iter_visible_descendants(soup: BeautifulSoup) -> Iterable[object]:
    """Yield visible nodes in document order, skipping the excluded subtrees."""
    for node in soup.descendants:
        if _is_skip_subtree(node):
            continue
        if isinstance(node, NavigableString):
            continue
        if _inside_table(node):
            continue
        yield node


def _collect_logical_blocks(
    visible: list[object],
    form_family: str | None = None,
) -> list[tuple[object, str]]:
    """Pick semantic blocks: p, li, caption, validated headings, leaf div/span."""
    blocks: list[tuple[object, str]] = []
    for node in visible:
        name = getattr(node, "name", None)
        if name is None:
            continue
        lowered = str(name).lower()
        text = _strip_and_join(node)
        if not text:
            continue
        if lowered in {"p", "li", "caption"} or _candidate_heading(node, form_family):
            if len(text) > _MAX_BLOCK_LENGTH:
                text = text[:_MAX_BLOCK_LENGTH]
            blocks.append((node, text))
    return blocks


def _collect_tables(soup: BeautifulSoup) -> tuple[TableNode, ...]:
    """Collect all tables in document order, including nested tables.

    Nested tables retain their parent ordinal and depth so the index can
    distinguish prose-formatted outer tables from true data tables.
    """
    tables: list[TableNode] = []
    for ordinal, table in enumerate(soup.find_all("table"), start=1):
        depth = 0
        parent = table.parent
        while parent is not None and getattr(parent, "name", None) is not None:
            if str(parent.name).lower() == "table":
                depth += 1
            parent = parent.parent
        rows = table.find_all("tr")
        cells = table.find_all(["td", "th"])
        parent_ordinal = None
        if depth > 0:
            ancestors = [
                a for a in table.parents if getattr(a, "name", None) == "table"
            ]
            if ancestors:
                outermost = ancestors[-1]
                outer_index = list(soup.find_all("table")).index(outermost)
                parent_ordinal = outer_index + 1
        tables.append(
            TableNode(
                ordinal=ordinal,
                locator=_locator("table", ordinal),
                row_count=len(rows),
                cell_count=len(cells),
                parent_table_ordinal=parent_ordinal,
                depth=depth,
            )
        )
    return tuple(tables)


def scan_html(
    soup: BeautifulSoup,
    *,
    document_id: str = "",
    source_sha256: str = "",
    form_family: str | None = None,
) -> HtmlStructureIndex:
    """Build a deterministic structure index from ``soup``."""
    visible = list(_iter_visible_descendants(soup))
    headings: list[HeadingNode] = []
    heading_ordinal = 0
    for node in visible:
        if not _candidate_heading(node, form_family):
            continue
        text = _strip_and_join(node)
        if not text or len(text) > _MAX_HEADING_LENGTH:
            continue
        heading_ordinal += 1
        is_part, is_item = _classify_heading(text)
        headings.append(
            HeadingNode(
                ordinal=heading_ordinal,
                locator=_locator("heading", heading_ordinal),
                text=text,
                fingerprint=_fingerprint(text),
                is_part=is_part,
                is_item=is_item,
            )
        )

    raw_blocks = _collect_logical_blocks(visible, form_family)
    blocks: list[BlockNode] = []
    for index, (_node, text) in enumerate(raw_blocks, start=1):
        preceding = tuple(
            text for _n, text in raw_blocks[max(0, index - _PRECEDING_BLOCKS) : index]
        )
        following = tuple(
            text for _n, text in raw_blocks[index : index + _FOLLOWING_BLOCKS]
        )
        blocks.append(
            BlockNode(
                ordinal=index,
                locator=_locator("block", index),
                text=text,
                fingerprint=_fingerprint(text),
                preceding_blocks=preceding,
                following_blocks=following,
            )
        )

    tables = _collect_tables(soup)

    scanner_fingerprint = hashlib.sha256(
        b"|".join(
            [f"h{node.ordinal}:{node.fingerprint[:8]}".encode() for node in headings]
        )
        + b"||"
        + b"|".join(
            f"b{node.ordinal}:{node.fingerprint[:8]}".encode() for node in blocks
        )
        + b"||"
        + f"t{len(tables)}".encode()
    ).hexdigest()

    return HtmlStructureIndex(
        document_id=document_id,
        source_sha256=source_sha256,
        headings=tuple(headings),
        blocks=tuple(blocks),
        tables=tables,
        scanner_fingerprint=scanner_fingerprint,
    )
