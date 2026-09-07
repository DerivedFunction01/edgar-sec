from __future__ import annotations

from defs.text.html import normalize_html_document


def test_normalize_html_document_preserves_paragraph_unity() -> None:
    html = "<p>This is a <span>single</span> paragraph.</p>"

    assert normalize_html_document(html) == "This is a single paragraph."


def test_normalize_html_document_keeps_false_table_stage_explicit() -> None:
    calls: list[str] = []

    def cleanup(text: str) -> str:
        calls.append(text)
        return text

    assert normalize_html_document("<p>One</p><p>Two</p>", cleanup_tables=cleanup) == (
        "One\n\nTwo"
    )
    assert calls == ["<html><head></head><body><p>One</p><p>Two</p></body></html>"]


def test_normalize_html_document_preserves_rendered_table_tags() -> None:
    html = "<table><tr><th>Metric</th><th>Value</th></tr><tr><td>Sales</td><td>5</td></tr></table>"

    normalized = normalize_html_document(html)

    assert normalized.startswith("<TABLE>\n")
    assert normalized.endswith("\n</TABLE>")
    assert "Metric" in normalized
    assert "Sales" in normalized


def test_normalize_html_document_preserves_literal_sgml_table_in_pre() -> None:
    html = "<html><body><pre><TABLE>\n<S>Revenue <C>100\n</TABLE></pre></body></html>"

    normalized = normalize_html_document(html)

    assert normalized == "<TABLE>\n<S>Revenue <C>100\n</TABLE>"


def test_normalize_html_document_renders_html_table_in_pre() -> None:
    html = "<html><body><pre><table><tr><td>Revenue</td><td>100</td></tr></table></pre></body></html>"

    normalized = normalize_html_document(html)

    assert normalized.startswith("<TABLE>\n")
    assert "Revenue" in normalized
    assert "100" in normalized
