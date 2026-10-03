"""Canonical HTML tag classifications for parsing, traversal, and decomposition.
These sets are the single definition of what a "block" is; changing one changes both text
extraction and whitespace output, so every use site imports rather than duplicates it.
"""

from __future__ import annotations

# Blocks that represent distinct paragraphs or headings; delimited with \n\n.
PARAGRAPH_TAGS: frozenset[str] = frozenset(
    {"p", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
)

# Structural container blocks; delimited with a single \n.
CONTAINER_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "address",
        "article",
        "aside",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "noscript",
        "ol",
        "section",
        "ul",
    }
)

# Table and preformatted blocks. Treated as blocks, but their interior layout
# is owned by the table and hybrid pipelines, never by prose projection.
TABLE_AND_PRE_TAGS: frozenset[str] = frozenset(
    {"table", "tbody", "thead", "tfoot", "tr", "td", "th", "pre"}
)

# Every block tag combined.
BLOCK_TAGS: frozenset[str] = PARAGRAPH_TAGS | CONTAINER_BLOCK_TAGS | TABLE_AND_PRE_TAGS

# Strictly inline formatting elements: removed without inserting a line break.
INLINE_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "b",
        "big",
        "center",
        "cite",
        "code",
        "del",
        "em",
        "font",
        "i",
        "ins",
        "q",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "u",
    }
)

__all__ = [
    "BLOCK_TAGS",
    "CONTAINER_BLOCK_TAGS",
    "INLINE_TAGS",
    "PARAGRAPH_TAGS",
    "TABLE_AND_PRE_TAGS",
]
