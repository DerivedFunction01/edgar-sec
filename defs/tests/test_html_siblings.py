"""Deterministic tests for FastHtmlNode sibling traversal."""

from __future__ import annotations

from defs.text.html import parse_html


def test_find_previous_sibling_skips_text_nodes() -> None:
    tree = parse_html("<div>A<hr/>B</div>")
    hr = tree.css_first("hr")
    assert hr is not None
    assert hr.find_previous_sibling() is None


def test_find_next_sibling_skips_text_nodes() -> None:
    tree = parse_html("<div>A<hr/>B</div>")
    hr = tree.css_first("hr")
    assert hr is not None
    assert hr.find_next_sibling() is None


def test_find_previous_sibling_returns_element_sibling() -> None:
    tree = parse_html("<div><span>A</span><hr/><b>B</b></div>")
    hr = tree.css_first("hr")
    assert hr is not None
    prev = hr.find_previous_sibling()
    assert prev is not None
    assert prev.tag == "span"


def test_find_next_sibling_returns_element_sibling() -> None:
    tree = parse_html("<div><span>A</span><hr/><b>B</b></div>")
    hr = tree.css_first("hr")
    assert hr is not None
    nxt = hr.find_next_sibling()
    assert nxt is not None
    assert nxt.tag == "b"


def test_find_previous_sibling_filters_by_name() -> None:
    tree = parse_html("<div><p>A</p><span>B</span><hr/><b>C</b></div>")
    hr = tree.css_first("hr")
    assert hr is not None
    prev = hr.find_previous_sibling("span")
    assert prev is not None
    assert prev.tag == "span"
    prev_p = hr.find_previous_sibling("p")
    assert prev_p is not None
    assert prev_p.tag == "p"
    assert hr.find_previous_sibling("b") is None


def test_find_next_sibling_filters_by_name() -> None:
    tree = parse_html("<div><b>C</b><hr/><span>B</span><p>A</p></div>")
    hr = tree.css_first("hr")
    assert hr is not None
    nxt = hr.find_next_sibling("span")
    assert nxt is not None
    assert nxt.tag == "span"
    nxt_p = hr.find_next_sibling("p")
    assert nxt_p is not None
    assert nxt_p.tag == "p"
    assert hr.find_next_sibling("b") is None


def test_find_previous_sibling_returns_none_at_boundary() -> None:
    tree = parse_html("<div><hr/>B</div>")
    hr = tree.css_first("hr")
    assert hr is not None
    assert hr.find_previous_sibling() is None


def test_find_next_sibling_returns_none_at_boundary() -> None:
    tree = parse_html("<div>A<hr/></div>")
    hr = tree.css_first("hr")
    assert hr is not None
    assert hr.find_next_sibling() is None


def test_sibling_traversal_skips_multiple_text_nodes() -> None:
    tree = parse_html("<div>  <hr/>  </div>")
    hr = tree.css_first("hr")
    assert hr is not None
    assert hr.find_previous_sibling() is None
    assert hr.find_next_sibling() is None


def test_hr_candidate_path_with_fasthtmlnode() -> None:
    from defs.sec_forms.page_markers import (
        PageMarkerKind,
        analyze_page_markers,
        enrich_html_analysis,
    )

    text = "<html><body><p><hr></p><p>1</p><p><hr></p><p>2</p><p><hr></p><p>3</p></body></html>"
    soup = parse_html(text)
    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "arabic" and [c.value for c in run.candidates] == [1, 2, 3]
        for run in analysis.page_number_runs
    )
    assert all(marker.kind == PageMarkerKind.HTML_NODE for marker in analysis.markers)


def test_hr_candidate_path_skips_empty_parser_wrapper_siblings() -> None:
    text = "<html><body><p><hr /></p><p>1</p><p><hr /></p><p>2</p><p><hr /></p><p>3</p></body></html>"
    soup = parse_html(text)
    from defs.sec_forms.page_markers import analyze_page_markers, enrich_html_analysis

    analysis = enrich_html_analysis(
        analyze_page_markers(text, representation="html"),
        soup,
        source_text=text,
    )
    assert any(
        run.namespace == "arabic"
        and [candidate.value for candidate in run.candidates] == [1, 2, 3]
        for run in analysis.page_number_runs
    )
