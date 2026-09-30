"""High-throughput HTML document parsing and tree extraction via selectolax.

Uses selectolax for sub-millisecond DOM traversal, tag unrolling,
and sanitized HTML rendering required by document review artifacts.
"""

from __future__ import annotations

from collections.abc import Iterator

from selectolax.parser import HTMLParser, Node

BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "table",
        "tr",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "hr",
    }
)


class FastHtmlNode:
    """Wrapper around a selectolax HTML DOM node providing standardized access."""

    __slots__ = ("_node",)

    def __init__(self, node: Node) -> None:
        self._node = node

    @property
    def raw_node(self) -> Node:
        return self._node

    @property
    def tag(self) -> str:
        return (self._node.tag or "").lower()

    @property
    def name(self) -> str:
        return self.tag

    @property
    def attributes(self) -> dict[str, str]:
        raw = self._node.attributes
        if not raw:
            return {}
        return {
            str(k).lower(): str(v)
            for k, v in raw.items()
            if k is not None and v is not None
        }

    @property
    def attrs(self) -> dict[str, str]:
        return self.attributes

    @property
    def parent(self) -> FastHtmlNode | None:
        p = self._node.parent
        return FastHtmlNode(p) if p is not None else None

    def unwrap(self) -> None:
        self._node.unwrap()

    def decompose(self) -> None:
        self._node.decompose()

    @property
    def html(self) -> str:
        return self._node.html or ""

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        raw = self._node.text(deep=True) or ""
        return raw.strip() if strip else raw


class FastHtmlTree:
    """Wrapper around a parsed selectolax HTML document tree."""

    __slots__ = ("_tree",)

    def __init__(self, tree: HTMLParser) -> None:
        self._tree = tree

    @property
    def root(self) -> FastHtmlNode | None:
        body = self._tree.body or self._tree.root
        return FastHtmlNode(body) if body is not None else None

    def css(self, query: str) -> list[FastHtmlNode]:
        return [FastHtmlNode(n) for n in self._tree.css(query)]

    def css_first(self, query: str) -> FastHtmlNode | None:
        match = self._tree.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def traverse(self) -> Iterator[FastHtmlNode]:
        root = self._tree.root
        if root is None:
            return
        for node in root.traverse():
            if node.tag:
                yield FastHtmlNode(node)

    def strip_tags(
        self, tags: tuple[str, ...] = ("script", "style", "noscript", "svg")
    ) -> None:
        css_tags: list[str] = []
        custom_tags: set[str] = set()
        for t in tags:
            if ":" in t:
                custom_tags.add(t.lower())
            else:
                css_tags.append(t)
        if css_tags:
            for node in self._tree.css(", ".join(css_tags)):
                node.decompose()
        if custom_tags:
            for node in self.traverse():
                if node.tag in custom_tags:
                    node.decompose()

    @property
    def html(self) -> str:
        return self._tree.html or ""

    def __str__(self) -> str:
        return self.html


def parse_html(html_content: str | bytes) -> FastHtmlTree:
    """Parse HTML content into a fast C-native FastHtmlTree."""
    text = (
        html_content.decode("utf-8", errors="replace")
        if isinstance(html_content, (bytes, bytearray, memoryview))
        else html_content
    )
    tree = HTMLParser(text)
    return FastHtmlTree(tree)


__all__ = [
    "BLOCK_TAGS",
    "FastHtmlNode",
    "FastHtmlTree",
    "parse_html",
]
