"""HTML parsing, traversal, and mutation.

Covers the surface the cleaning and table passes need.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html

SAMPLE = """
<html>
  <head><title>Test</title></head>
  <body>
    <div class="content">
      <h1>Main Title</h1>
      <p>Paragraph with <a href="http://example.com">link</a>.</p>
      <table><tr><td>A</td><td>B</td></tr></table>
    </div>
  </body>
</html>
"""


def test_parse_html_basic() -> None:
    tree = parse_html(SAMPLE)
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


def test_parse_html_accepts_bytes() -> None:
    tree = parse_html(SAMPLE.encode("utf-8"))
    assert tree.css_first("h1") is not None


def test_parse_html_replaces_undecodable_bytes() -> None:
    tree = parse_html(b"<p>caf\xff</p>")
    assert tree.text().startswith("caf")


def test_node_text_separates_blocks_and_breaks() -> None:
    tree = parse_html("<div><p>one</p><p>two</p></div>")
    assert tree.text() == "one two"


def test_node_text_separates_paren_after_alphanumeric() -> None:
    """A parenthesised element following prose gets a separator, not a fusion."""
    tree = parse_html("<p>value<span>(1)</span> and more</p>")
    assert tree.text() == "value (1) and more"


def test_node_text_leaves_paren_fused_inside_a_text_node() -> None:
    tree = parse_html("<p>value(1)</p>")
    assert tree.text() == "value(1)"


def test_node_text_strip_can_be_disabled() -> None:
    tree = parse_html("<p>  spaced  </p>")
    node = tree.find("p")
    assert node is not None
    assert node.text(strip=False).startswith(" ")
    assert node.text(strip=True) == "spaced"


def test_node_attributes_are_lowercased_and_never_none() -> None:
    tree = parse_html('<table><tr><td COLSPAN="2" align="right">v</td></tr></table>')
    node = tree.css_first("td")
    assert node is not None
    assert node.attributes["colspan"] == "2"
    assert node.get("ALIGN") == "right"
    assert node.get("missing", "fallback") == "fallback"


def test_node_parent_and_find_parent() -> None:
    tree = parse_html("<div><table><tr><td>cell</td></tr></table></div>")
    cell = tree.css_first("td")
    assert cell is not None
    assert cell.parent is not None
    assert cell.parent.tag == "tr"
    assert cell.find_parent("table") is not None
    assert cell.find_parent("nonexistent") is None


def test_node_css_and_find_all() -> None:
    tree = parse_html("<ul><li>a</li><li>b</li></ul>")
    node = tree.css_first("ul")
    assert node is not None
    assert len(node.css("li")) == 2
    assert len(node.find_all("li")) == 2
    assert len(node.find_all()) >= 2


def test_node_siblings_skip_text_nodes() -> None:
    tree = parse_html("<p>one</p>text<p>two</p>")
    first = tree.find_all("p")[0]
    assert first.find_next_sibling() is not None
    assert first.find_next_sibling().text() == "two"
    assert first.find_previous_sibling() is None


def test_node_sibling_blocks_climb_ancestors() -> None:
    html = "<div><p>label</p></div><div><hr></div><div><p>after</p></div>"
    tree = parse_html(html)
    hr = tree.css_first("hr")
    assert hr is not None
    previous = hr.previous_sibling_blocks()
    assert previous
    assert previous[0].text() == "label"


def test_node_iter_children_yields_elements_only() -> None:
    tree = parse_html("<div>text<span>a</span>more</div>")
    div = tree.css_first("div")
    assert div is not None
    tags = [child.tag for child in div.iter_children()]
    assert tags == ["span"]


def test_node_mutation_unwrap_keeps_children() -> None:
    tree = parse_html("<div><span>keep</span></div>")
    span = tree.css_first("span")
    assert span is not None
    span.unwrap()
    assert tree.css_first("span") is None
    assert "keep" in tree.html


def test_node_mutation_decompose_removes_children() -> None:
    tree = parse_html("<div><span>gone</span></div>")
    span = tree.css_first("span")
    assert span is not None
    span.decompose()
    assert "gone" not in tree.html


def test_node_replace_with_html() -> None:
    tree = parse_html("<div><span>old</span></div>")
    span = tree.css_first("span")
    assert span is not None
    span.replace_with_html("<b>new</b>")
    assert "new" in tree.html
    assert "old" not in tree.html


def test_tree_strip_tags() -> None:
    html = "<div><script>alert(1);</script><style>p { color: red; }</style><p>Keep this</p></div>"
    tree = parse_html(html)
    tree.strip_tags(("script", "style"))
    assert "alert" not in tree.html
    assert "color: red" not in tree.html
    assert "Keep this" in tree.text()


def test_tree_strip_tags_handles_namespaced_names() -> None:
    tree = parse_html("<div><ix:header>meta</ix:header><p>body</p></div>")
    tree.strip_tags(("ix:header",))
    assert "meta" not in tree.html
    assert "body" in tree.html


def test_tree_traverse_visits_every_element() -> None:
    tree = parse_html(SAMPLE)
    tags = {node.tag for node in tree.traverse()}
    assert {"html", "body", "div", "h1", "p", "a", "table", "tr", "td"} <= tags


def test_tree_html_and_str_round_trip() -> None:
    tree = parse_html("<p>text</p>")
    assert str(tree) == tree.html
    assert "<p>text</p>" in tree.html


def test_node_equality_is_by_wrapped_node_not_wrapper_identity() -> None:
    tree = parse_html("<p><span>x</span></p>")
    first = tree.css_first("span")
    second = tree.css_first("span")
    assert first is not None and second is not None
    assert first == second
    assert first != "span"
    assert isinstance(first, FastHtmlNode)
