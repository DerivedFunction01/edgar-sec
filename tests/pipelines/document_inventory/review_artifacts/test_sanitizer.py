from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.pipelines.document_inventory.review_artifacts.sanitizer import (
    render_inert,
)


def test_preview_preserves_tables_and_removes_active_content() -> None:
    source = b"""<html><head><title>private title</title></head><body>
      <p onclick="run()">Visible <a href="javascript:alert(1)">document</a></p>
      <table><thead><tr><th>Document</th></tr></thead><tbody>
      <tr><td>exhibit.txt</td></tr></tbody></table>
      <script>script-secret</script><style>style-secret</style>
      <iframe src="https://example.test/track">frame-secret</iframe>
      <svg onload="run()"><text>svg-secret</text></svg>
      <form action="https://example.test"><input value="private"></form>
      <img src="https://example.test/pixel.png" alt="image-secret">
    </body></html>"""

    rendered = render_inert(source)
    assert "Visible" in rendered and "document" in rendered
    assert "Document" in rendered and "exhibit.txt" in rendered
    assert "<table>" in rendered and "<th>" in rendered and "<tr>" in rendered
    for unsafe in (
        "onclick",
        "javascript:",
        "https://example.test",
        "script-secret",
        "style-secret",
        "frame-secret",
        "svg-secret",
        "private title",
        "image-secret",
        "action=",
        "src=",
    ):
        assert unsafe not in rendered
    assert "Content-Security-Policy" in rendered
    tree = parse_html(rendered)
    tags = {node.tag for node in tree.find_all()}
    assert not tags & {"script", "style", "iframe", "svg", "form", "img", "input"}


def test_malformed_input_is_rebuilt_without_attributes() -> None:
    rendered = render_inert(b"<TABLE onclick=x><TR><TD>text</TABLE><SCRIPT>bad")
    assert "<table>" in rendered and "<td>text" in rendered
    assert "onclick" not in rendered and "bad" not in rendered
