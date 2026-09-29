"""High-throughput HTML document parsing and tree extraction via selectolax.

Uses selectolax (Modest C engine) for sub-millisecond DOM traversal, tag unrolling,
and whitespace normalization while preserving table sentinels and symbolic font glyphs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

from selectolax.parser import HTMLParser, Node

from edgar_sec.engine.document.html_cleaner import (
    BLOCK_TAGS,
    clean_html_for_parsing,
    decompose_html_structures,
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

    @property
    def contents(self) -> list[FastHtmlNode]:
        return [
            FastHtmlNode(child)
            for child in self._node.iter(include_text=True)
            if child is not None
        ]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FastHtmlNode):
            return self._node == other._node
        return False

    def __hash__(self) -> int:
        return hash(self._node)

    def get(self, attr_name: str, default: str | None = None) -> str | None:
        return self.attributes.get(attr_name.lower(), default)

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        """Extract plain text with block-aware separator and stripping."""
        chunks: list[str] = []

        def _walk(n: Node) -> None:
            for child in n.iter(include_text=True):
                tag = child.tag
                if tag == "-text":
                    chunks.append(child.text(deep=False))
                elif tag == "br":
                    chunks.append(separator)
                elif tag in BLOCK_TAGS:
                    if (
                        separator
                        and chunks
                        and not chunks[-1].endswith((" ", "\n", "\t", "\xa0"))
                    ):
                        chunks.append(separator)
                    _walk(child)
                    if (
                        separator
                        and chunks
                        and not chunks[-1].endswith((" ", "\n", "\t", "\xa0"))
                    ):
                        chunks.append(separator)
                else:
                    child_txt = child.text(deep=True)
                    if (
                        child_txt.startswith("(")
                        and chunks
                        and chunks[-1]
                        and (chunks[-1][-1].isalnum() or chunks[-1][-1] in "%$")
                    ):
                        chunks.append(" ")
                    _walk(child)

        _walk(self._node)
        raw = "".join(chunks)
        return raw.strip() if strip else raw

    def get_text(self, separator: str = " ", strip: bool = True) -> str:
        return self.text(separator=separator, strip=strip)

    def css(self, query: str) -> list[FastHtmlNode]:
        return [FastHtmlNode(n) for n in self._node.css(query)]

    def css_first(self, query: str) -> FastHtmlNode | None:
        match = self._node.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def find(self, name: str | Iterable[str]) -> FastHtmlNode | None:
        selector = name if isinstance(name, str) else ", ".join(name)
        return self.css_first(selector)

    def find_all(
        self,
        tags: str | Iterable[str] | bool = True,
        *,
        recursive: bool = True,
    ) -> list[FastHtmlNode]:
        if not recursive:
            if tags is True:
                return [
                    FastHtmlNode(n)
                    for n in self._node.iter(include_text=False)
                    if n.tag
                ]
            tag_set = (
                {tags.lower()} if isinstance(tags, str) else {t.lower() for t in tags}
            )
            return [
                FastHtmlNode(n)
                for n in self._node.iter(include_text=False)
                if (n.tag or "").lower() in tag_set
            ]
        if tags is True:
            return [FastHtmlNode(n) for n in self._node.traverse() if n.tag]
        selector = tags if isinstance(tags, str) else ", ".join(tags)
        return self.css(selector)

    def find_parent(self, tag_name: str) -> FastHtmlNode | None:
        target = tag_name.lower()
        curr = self._node.parent
        while curr is not None:
            if (curr.tag or "").lower() == target:
                return FastHtmlNode(curr)
            curr = curr.parent
        return None

    def iter_children(self) -> Iterator[FastHtmlNode]:
        for child in self._node.iter(include_text=False):
            if child.tag:
                yield FastHtmlNode(child)

    def find_previous_sibling(self, name: str | None = None) -> FastHtmlNode | None:
        target = name.lower() if name is not None else None
        curr = self._node.prev
        while curr is not None:
            if curr.tag != "-text" and (target is None or curr.tag == target):
                return FastHtmlNode(curr)
            curr = curr.prev
        return None

    def find_next_sibling(self, name: str | None = None) -> FastHtmlNode | None:
        target = name.lower() if name is not None else None
        curr = self._node.next
        while curr is not None:
            if curr.tag != "-text" and (target is None or curr.tag == target):
                return FastHtmlNode(curr)
            curr = curr.next
        return None

    def unwrap(self) -> None:
        self._node.unwrap()

    def decompose(self) -> None:
        self._node.decompose()

    @property
    def html(self) -> str:
        return self._node.html or ""

    def insert_before_html(self, html: str) -> None:
        self._node.insert_before(html)

    def replace_with_html(self, html: str) -> None:
        if hasattr(self._node, "replace_with"):
            self._node.replace_with(html)
        else:
            self.insert_before_html(html)
            self._node.decompose()

    def remove(self) -> None:
        self._node.remove()

    def replace_with(self, content: str | FastHtmlNode) -> None:
        html_str = content if isinstance(content, str) else content.raw_node.html
        self.replace_with_html(html_str)


class FastHtmlTree:
    """Wrapper around a parsed selectolax HTML document tree."""

    __slots__ = ("_tree",)

    def __init__(self, tree: HTMLParser) -> None:
        self._tree = tree

    @property
    def root(self) -> FastHtmlNode | None:
        body = self._tree.body or self._tree.root
        return FastHtmlNode(body) if body is not None else None

    @property
    def contents(self) -> list[FastHtmlNode]:
        if self._tree.root is not None:
            doc = self._tree.root.parent
            if doc is not None:
                return [
                    FastHtmlNode(child)
                    for child in doc.iter(include_text=True)
                    if child is not None
                ]
            return [FastHtmlNode(self._tree.root)]
        return []

    def css(self, query: str) -> list[FastHtmlNode]:
        return [FastHtmlNode(n) for n in self._tree.css(query)]

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        return self.root.text(separator=separator, strip=strip) if self.root else ""

    def get_text(self, separator: str = " ", strip: bool = True) -> str:
        return self.text(separator=separator, strip=strip)

    def css_first(self, query: str) -> FastHtmlNode | None:
        match = self._tree.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def find(self, name: str) -> FastHtmlNode | None:
        return self.css_first(name)

    def find_all(self, tags: str | Iterable[str] | bool = True) -> list[FastHtmlNode]:
        if tags is True:
            return list(self.traverse())
        selector = tags if isinstance(tags, str) else ", ".join(tags)
        return self.css(selector)

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


class NormalizedHtmlText(str):
    """String result of HTML normalization with retained table geometry metadata."""

    def __new__(cls, text: str, table_geometries: tuple = ()):
        instance = super().__new__(cls, text)
        instance._table_geometries = tuple(table_geometries)
        return instance

    @property
    def table_geometries(self) -> tuple:
        return self._table_geometries

    def __repr__(self) -> str:
        return (
            f"NormalizedHtmlText({super().__repr__()!r}, "
            f"table_geometries={self._table_geometries!r})"
        )


def normalize_html_document(
    html: str,
    *,
    cleanup_tables: Callable[[str], str] | None = None,
) -> NormalizedHtmlText:
    """Render an HTML document into normalized text without tree text extraction."""
    if not html:
        return NormalizedHtmlText("", ())

    cleaned = clean_html_for_parsing(html)
    rendered = cleanup_tables(cleaned) if cleanup_tables else cleaned
    normalized = decompose_html_structures(rendered)
    return NormalizedHtmlText(normalized, ())


__all__ = [
    "FastHtmlNode",
    "FastHtmlTree",
    "NormalizedHtmlText",
    "normalize_html_document",
    "parse_html",
]
