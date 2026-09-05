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
    def name(self) -> str:
        return self.tag

    @property
    def attributes(self) -> dict[str, str]:
        return {
            str(k).lower(): str(v)
            for k, v in (self._node.attributes or {}).items()
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
        """List immediate child nodes as FastHtmlNode wrappers."""
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
        """Get an attribute by name (case-insensitive)."""
        return self.attributes.get(attr_name.lower(), default)

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        """Extract plain text with block-aware separator and stripping."""
        block_tags = {
            "address",
            "article",
            "aside",
            "blockquote",
            "canvas",
            "dd",
            "div",
            "dl",
            "dt",
            "fieldset",
            "figcaption",
            "figure",
            "footer",
            "form",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hr",
            "li",
            "main",
            "nav",
            "noscript",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "tfoot",
            "ul",
            "video",
            "br",
            "tr",
            "td",
            "th",
        }
        chunks: list[str] = []

        def _walk(n: Node) -> None:
            for child in n.iter(include_text=True):
                tag = child.tag
                if tag == "-text":
                    chunks.append(child.text(deep=False))
                elif tag == "br":
                    chunks.append(separator)
                elif tag in block_tags:
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
        """Compatibility alias for BeautifulSoup get_text."""
        return self.text(separator=separator, strip=strip)

    def css(self, query: str) -> list[FastHtmlNode]:
        """Find matching descendant elements via CSS selector."""
        return [FastHtmlNode(n) for n in self._node.css(query)]

    def css_first(self, query: str) -> FastHtmlNode | None:
        """Find the first matching descendant element via CSS selector."""
        match = self._node.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def find(self, name: str | Iterable[str]) -> FastHtmlNode | None:
        """Find the first matching descendant tag (compatibility with BeautifulSoup)."""
        if isinstance(name, str):
            selector = name
        else:
            selector = ", ".join(name)
        return self.css_first(selector)

    def find_all(
        self,
        tags: str | Iterable[str] | bool = True,
        *,
        recursive: bool = True,
    ) -> list[FastHtmlNode]:
        """Find matching tags by tag name(s) or all tags if True."""
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

    @property
    def html(self) -> str:
        """Get the HTML markup for this node and its children."""
        return self._node.html or ""

    def replace_with_html(self, html: str) -> None:
        """Replace this node with new HTML content."""
        if hasattr(self._node, "replace_with"):
            self._node.replace_with(html)
        else:
            self._node.insert_before(html)
            self._node.decompose()

    def replace_with(self, content: str | FastHtmlNode) -> None:
        """Replace this node with new string or FastHtmlNode (BeautifulSoup compatibility)."""
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
        """Root child contents."""
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
        """Find elements matching CSS selector across entire document."""
        return [FastHtmlNode(n) for n in self._tree.css(query)]

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        """Extract plain text for entire document."""
        return self.root.text(separator=separator, strip=strip) if self.root else ""

    def get_text(self, separator: str = " ", strip: bool = True) -> str:
        """Compatibility alias for BeautifulSoup get_text."""
        return self.text(separator=separator, strip=strip)

    def css_first(self, query: str) -> FastHtmlNode | None:
        """Find first element matching CSS selector across entire document."""
        match = self._tree.css_first(query)
        return FastHtmlNode(match) if match is not None else None

    def find(self, name: str) -> FastHtmlNode | None:
        """Find the first matching descendant tag."""
        return self.css_first(name)

    def find_all(self, tags: str | Iterable[str] | bool = True) -> list[FastHtmlNode]:
        """Find matching descendant tags or all tags if True."""
        if tags is True:
            return list(self.traverse())
        if isinstance(tags, str):
            selector = tags
        else:
            selector = ", ".join(tags)
        return self.css(selector)

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
        """Get the HTML markup for the entire document tree."""
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
    "FastHtmlNode",
    "FastHtmlTree",
    "parse_html",
]
