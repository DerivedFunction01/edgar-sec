"""Unit and contract tests for edgar_sec.engine.document.html."""

from __future__ import annotations

from edgar_sec.engine.document.html import (
    normalize_html_document,
    parse_html,
)


def test_parse_html_basic() -> None:
    html = """
    <html>
      <head><title>Test</title></head>
      <body>
        <div class="content">
          <h1>Main Title</h1>
          <p>Paragraph with <a href="http://example.com">link</a>.</p>
        </div>
      </body>
    </html>
    """
    tree = parse_html(html)
    assert tree.root is not None
    assert tree.root.tag == "body"

    title_node = tree.find("h1")
    assert title_node is not None
    assert title_node.text() == "Main Title"

    div_node = tree.css_first("div.content")
    assert div_node is not None
    assert div_node.attrs.get("class") == "content"

    p_nodes = tree.find_all("p")
    assert len(p_nodes) == 1
    assert p_nodes[0].text() == "Paragraph with link."


def test_parse_html_strip_tags() -> None:
    html = "<div><script>alert(1);</script><style>p { color: red; }</style><p>Keep this</p></div>"
    tree = parse_html(html)
    tree.strip_tags(("script", "style"))
    assert "alert" not in tree.html
    assert "color: red" not in tree.html
    assert "Keep this" in tree.text()


def test_normalize_html_document() -> None:
    html = "<div><h1>Title</h1><p>First paragraph.</p><p>Second paragraph.</p></div>"
    res = normalize_html_document(html)
    assert "Title\n\nFirst paragraph.\n\nSecond paragraph." in res
