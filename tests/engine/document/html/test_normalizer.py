"""Unit and contract tests for edgar_sec.engine.document.html.normalizer.

Projection is where byte-exactness is won or lost: tables must survive it
unchanged, and every rule here either protects a table or reshapes prose.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.normalizer import (
    decompose_html_structures,
    normalize_html_document,
)

TAGGED_TABLE = (
    "<TABLE><TR><TD>  A  </TD><TD>\tB\t</TD></TR>\n"
    "<TR><TD>Widgets</TD><TD>$1,000</TD></TR>\n"
    "  ragged   spacing  </TABLE>"
)


def test_empty_input() -> None:
    assert decompose_html_structures("") == ""


def test_paragraphs_become_blank_line_separated() -> None:
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    assert decompose_html_structures(html) == "First paragraph.\n\nSecond paragraph."


def test_headings_and_containers_become_lines() -> None:
    html = "<div><h1>Title</h1><p>First</p><h2>Sub</h2></div>"
    result = decompose_html_structures(html)
    assert "Title" in result
    assert "Sub" in result
    assert result.count("\n") >= 2


def test_inline_tags_do_not_introduce_breaks() -> None:
    html = "<p>a <b>bold</b> and <i>italic</i> word</p>"
    assert decompose_html_structures(html) == "a bold and italic word"


def test_double_br_inside_a_paragraph_collapses_to_a_space() -> None:
    """Deliberate, not an accident of the passes.

    A `<br><br>` run becomes a blank line at the break stage, and the later
    source-line-wrap pass collapses that blank line back to a space. Only a
    break pair sitting *between* block tags survives as a paragraph break.
    """
    assert decompose_html_structures("<p>para one<br><br>para two</p>") == (
        "para one para two"
    )


def test_break_pair_between_blocks_becomes_a_paragraph_break() -> None:
    assert decompose_html_structures("<p>a</p><p>b<br><br>c</p>") == "a\n\nb c"


def test_single_br_becomes_a_space() -> None:
    assert decompose_html_structures("<p>one<br>two</p>") == "one two"


def test_entities_are_unescaped() -> None:
    assert decompose_html_structures("<p>a &amp; b</p>") == "a & b"


def test_comments_and_declarations_are_removed() -> None:
    html = "<!DOCTYPE html><!-- hidden --><p>body</p>"
    assert decompose_html_structures(html) == "body"


def test_nested_divs_unroll() -> None:
    html = "<div><div><div><p>deep</p></div></div></div>"
    assert decompose_html_structures(html) == "deep"


def test_table_bytes_survive_projection_exactly() -> None:
    html = f"before\n{TAGGED_TABLE}\nafter"
    result = decompose_html_structures(html)
    assert TAGGED_TABLE in result


def test_table_entity_content_is_not_unescaped() -> None:
    """The table is masked before unescaping, so its bytes stay untouched."""
    html = "<p>" + TAGGED_TABLE.replace("Widgets", "Wid&amp;gets") + "</p>"
    result = decompose_html_structures(html)
    assert "Wid&amp;gets" in result


def test_prose_around_an_embedded_table_is_kept_on_one_line() -> None:
    html = f"<p>Intro prose {TAGGED_TABLE} trailing prose</p>"
    result = decompose_html_structures(html)
    assert "Intro prose" in result
    assert "trailing prose" in result
    assert TAGGED_TABLE in result


def test_definition_list_bullets_fuse_into_their_description() -> None:
    html = "<dl><dt>&bull;</dt><dd>first item</dd></dl>"
    result = decompose_html_structures(html)
    assert "first item" in result
    assert "\u2022 first item" in result or "• first item" in result


def test_source_line_wraps_collapse_to_spaces() -> None:
    assert decompose_html_structures("<p>one\ntwo</p>") == "one two"


def test_excessive_blank_runs_collapse() -> None:
    result = decompose_html_structures("<p>a</p>\n\n\n\n\n<p>b</p>")
    assert result == "a\n\nb"


def test_raw_newlines_between_adjacent_tables_stay_separate() -> None:
    """Collapsing the separator would fuse two tables onto one line."""
    html = f"{TAGGED_TABLE}\n{TAGGED_TABLE}"
    result = decompose_html_structures(html)
    lines = [line for line in result.split("\n") if line.strip()]
    assert len(lines) >= 2


def test_list_items_become_one_line_each() -> None:
    html = "<ul><li>one</li><li>two</li><li>three</li></ul>"
    lines = [line for line in decompose_html_structures(html).split("\n") if line]
    assert lines == ["one", "two", "three"]


def test_output_is_stripped() -> None:
    assert decompose_html_structures("   <p>body</p>   ") == "body"


def test_malformed_markup_does_not_raise() -> None:
    for html in ("<p>unclosed", "<<>>", "</p></div>", "<p>a</p", ""):
        assert isinstance(decompose_html_structures(html), str)


def _table_html(rows: int = 3) -> str:
    body = "".join(f"<tr><td>Item {i}</td><td>{i * 100}</td></tr>" for i in range(rows))
    return f'<table border="1"><tr><th>Label</th><th>Amount</th></tr>{body}</table>'


def test_normalize_html_document_projects_paragraphs() -> None:
    html = "<html><body><h1>Title</h1><p>First.</p><p>Second.</p></body></html>"
    result = normalize_html_document(html)
    assert "Title" in result
    assert "First." in result
    assert "Second." in result


def test_normalized_html_text_behaves_as_a_string() -> None:
    result = normalize_html_document("<p>body</p>")
    assert isinstance(result, str)
    assert result == "body"
    assert result.strip() == "body"
    assert result.upper() == "BODY"


def test_normalized_html_text_on_empty_input() -> None:
    result = normalize_html_document("")
    assert str(result) == ""
    assert result.table_geometries == ()


def test_normalize_html_document_renders_a_table_to_ascii() -> None:
    result = normalize_html_document(_table_html())
    assert "<TABLE>" in result
    assert "</TABLE>" in result
    assert "Item 0" in result
    assert "<td>" not in result


def test_normalize_html_document_reports_geometry_per_rendered_table() -> None:
    result = normalize_html_document(_table_html())
    assert len(result.table_geometries) == 1
    geometry = result.table_geometries[0]
    assert geometry.table_index == 0
    assert geometry.render_result.confidence > 0.0


def test_geometry_indexes_match_the_tables_in_the_document() -> None:
    result = normalize_html_document(
        _table_html() + "<p>gap</p>" + _table_html() + "<p>gap</p>" + _table_html()
    )
    assert len(result.table_geometries) == 3
    assert [g.table_index for g in result.table_geometries] == [0, 1, 2]


def test_adjacent_tables_fuse_into_one_geometry() -> None:
    """A layout that splits one table across several `<table>` tags is one table.

    Filing generators emit exactly this. Refusing to fuse would render three
    separate fragments and split every row, so the geometry reports one table —
    which is why a geometry count is not a `<table>` tag count.
    """
    result = normalize_html_document(_table_html() + _table_html() + _table_html())
    assert len(result.table_geometries) == 1
    assert result.table_geometries[0].table_index == 0


def test_document_without_tables_reports_no_geometry() -> None:
    result = normalize_html_document("<p>no tables here</p>")
    assert result.table_geometries == ()


def test_normalize_html_document_unwraps_a_false_table() -> None:
    """A one-cell layout grid is prose, not a table, so it produces no geometry."""
    html = "<table><tr><td><p>Single narrative cell</p></td></tr></table>"
    result = normalize_html_document(html)
    assert "<TABLE>" not in result
    assert "Single narrative cell" in result


def test_injected_cleanup_replaces_the_default_policy() -> None:
    seen: list[str] = []

    def _cleanup(text: str) -> str:
        seen.append(text)
        return text.replace("SECRET", "REDACTED")

    result = normalize_html_document("<p>SECRET value</p>", cleanup_tables=_cleanup)
    assert seen
    assert "REDACTED" in result


def test_hybrid_pre_payload_survives_projection() -> None:
    html = "<html><body><pre>MONOSPACE  COLUMN</pre><p>prose</p></body></html>"
    result = normalize_html_document(html)
    assert "MONOSPACE" in result


def test_normalized_html_text_repr_names_its_geometry() -> None:
    result = normalize_html_document(_table_html())
    assert "NormalizedHtmlText" in repr(result)
    assert "table_geometries" in repr(result)
