"""Structural allowlist renderer for inert index-page previews."""

from __future__ import annotations

import html

from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html

_DROP_SUBTREES = frozenset(
    {
        "applet",
        "audio",
        "base",
        "button",
        "canvas",
        "embed",
        "form",
        "frame",
        "frameset",
        "iframe",
        "img",
        "input",
        "link",
        "math",
        "meta",
        "noscript",
        "object",
        "portal",
        "script",
        "select",
        "source",
        "style",
        "svg",
        "template",
        "textarea",
        "track",
        "video",
        "xmp",
    }
)
_ALLOWED_TAGS = frozenset(
    {
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)
_VOID_TAGS = frozenset({"br", "hr"})
_CSP = "default-src 'none'; img-src 'none'; style-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; sandbox"


def _children(node: FastHtmlNode, parts: list[str]) -> None:
    child = node.raw_node.child
    while child is not None:
        tag = child.tag or ""
        if tag == "-text":
            parts.append(html.escape(child.text(deep=False), quote=True))
        elif tag not in {"-comment", "-doctype"}:
            _render_node(FastHtmlNode(child), parts)
        child = child.next


def _render_node(node: FastHtmlNode, parts: list[str]) -> None:
    tag = node.tag
    if tag in _DROP_SUBTREES or tag in {"head", "title"}:
        return
    if tag in {"html", "body", "a"}:
        _children(node, parts)
        return
    if tag not in _ALLOWED_TAGS:
        _children(node, parts)
        return
    parts.append(f"<{tag}>")
    _children(node, parts)
    if tag not in _VOID_TAGS:
        parts.append(f"</{tag}>")


def render_inert(source: bytes) -> str:
    tree = parse_html(source)
    parts = [
        "<!doctype html><html><head>",
        '<meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(_CSP, quote=True)}">',
        "<title>Index page review</title></head><body>",
    ]
    if tree.root is not None:
        _render_node(tree.root, parts)
    parts.append("</body></html>")
    return "".join(parts)
