"""Fast C-native HTML parsing and tree manipulation primitives using selectolax."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from selectolax.parser import HTMLParser, Node


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
    def attributes(self) -> dict[str, str]:
        return {
            str(k).lower(): str(v)
            for k, v in (self._node.attributes or {}).items()
            if k is not None and v is not None
        }

    @property
    def parent(self) -> FastHtmlNode | None:
        p = self._node.parent
        return FastHtmlNode(p) if p is not None else None

    def get(self, attr_name: str, default: str | None = None) -> str | None:
        """Get an attribute by name (case-insensitive)."""
        return self.attributes.get(attr_name.lower(), default)

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        """Extract plain text with optional separator and stripping."""
        raw = self._node.text(separator=separator, strip=strip)
        return raw.strip() if strip else raw

    def get_text(self, separator: str = " ", strip: bool = True) -> str:
        """Compatibility alias for BeautifulSoup get_text."""
        return self.text(separator=separator, strip=strip)

    def css(self, query: str) -> list[FastHtmlNode]:
        """Find matching descendant elements via CSS selector."""
        return [FastHtmlNode(n) for n in self._node.css(query)]

    def css_first(self, query: str) -> FastHtmlNode | None:
        """Find the first matching descendant element via CSS selector."""
        match = self._node.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def find(self, name: str) -> FastHtmlNode | None:
        """Find the first matching descendant tag (compatibility with BeautifulSoup)."""
        return self.css_first(name)

    def find_all(self, tags: str | Iterable[str]) -> list[FastHtmlNode]:
        """Find matching tags by tag name(s)."""
        if isinstance(tags, str):
            selector = tags
        else:
            selector = ", ".join(tags)
        return self.css(selector)

    def find_parent(self, tag_name: str) -> FastHtmlNode | None:
        """Walk ancestors to find the nearest parent with the given tag name."""
        target = tag_name.lower()
        curr = self._node.parent
        while curr is not None:
            if (curr.tag or "").lower() == target:
                return FastHtmlNode(curr)
            curr = curr.parent
        return None

    def iter_children(self) -> Iterator[FastHtmlNode]:
        """Iterate immediate child nodes."""
        for child in self._node.iter(include_text=False):
            if child.tag:
                yield FastHtmlNode(child)

    def unwrap(self) -> None:
        """Remove this element while retaining all its children in place."""
        self._node.unwrap()

    def decompose(self) -> None:
        """Completely remove this element and all its children from the tree."""
        self._node.decompose()


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
        """Find elements matching CSS selector across entire document."""
        return [FastHtmlNode(n) for n in self._tree.css(query)]

    def css_first(self, query: str) -> FastHtmlNode | None:
        """Find first element matching CSS selector across entire document."""
        match = self._tree.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def traverse(self) -> Iterator[FastHtmlNode]:
        """Traverse the entire DOM tree depth-first."""
        root = self._tree.root
        if root is None:
            return
        for node in root.traverse():
            if node.tag:
                yield FastHtmlNode(node)

    def strip_tags(
        self, tags: tuple[str, ...] = ("script", "style", "noscript", "svg")
    ) -> None:
        """Decompose unwanted tags across the tree."""
        selector = ", ".join(tags)
        for node in self._tree.css(selector):
            node.decompose()


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
    "FastHtmlNode",
    "FastHtmlTree",
    "parse_html",
]
