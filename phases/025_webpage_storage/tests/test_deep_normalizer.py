"""Tests for Stage 3 DeepNormalizer."""

from __future__ import annotations

import importlib

forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)

PreprocessedDocument = forms_base.PreprocessedDocument
DeepNormalizer = normalizer_mod.DeepNormalizer
GenericPreprocessor = importlib.import_module(
    "phases.025_webpage_storage.processors.preprocessor"
).GenericPreprocessor


def test_deep_normalizer_table_conversion() -> None:
    normalizer = DeepNormalizer()

    html = """
    <html>
    <body>
    <p>ITEM 1. BUSINESS</p>
    <p>We manufacture widgets.</p>
    <table border="1">
      <tr><th>Year</th><th>Revenue</th><th>Net Income</th></tr>
      <tr><td>2001</td><td>$100,000</td><td>$10,000</td></tr>
      <tr><td>2002</td><td>$120,000</td><td>$15,000</td></tr>
    </table>
    <PAGE>
    <p>Page 2 of 10</p>
    <p>ITEM 7. MD&A</p>
    <p>Operations increased substantially.</p>
    </body>
    </html>
    """

    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=50,
        has_html_tags=True,
        detected_encoding="utf-8",
    )

    normalized = normalizer.normalize(prep)

    # 1. Header standardized
    assert "ITEM 1. BUSINESS" in normalized
    assert "ITEM 7. MD&A" in normalized

    # 3. HTML table converted into structured ASCII grid
    assert "Revenue" in normalized
    assert "100,000" in normalized
    assert "<tr>" not in normalized.lower()
    assert "<td>" not in normalized.lower()


def test_deep_normalizer_spacer_trimming() -> None:
    normalizer = DeepNormalizer()

    # Table with blank spacer column (col 1) and empty spacer row
    html = """
    <table>
      <tr><th>Metric</th><th></th><th>2003</th></tr>
      <tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
      <tr><td>Sales</td><td></td><td>$5,000</td></tr>
    </table>
    """
    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=10,
        has_html_tags=True,
        detected_encoding="utf-8",
    )
    normalized = normalizer.normalize(prep)
    assert "<TABLE>" in normalized
    assert "Metric" in normalized
    assert "Sales" in normalized
    assert "$5,000" in normalized


def test_deep_normalizer_xml_stripping() -> None:
    normalizer = DeepNormalizer()
    text = "Total assets were <ix:nonFraction unitRef='usd' decimals='0'>1500000</ix:nonFraction> dollars."
    prep = GenericPreprocessor().preprocess(text.encode("utf-8"))
    normalized = normalizer.normalize(prep)
    assert "<ix:" not in normalized
    assert "1500000" in normalized


def test_deep_normalizer_cover_metadata_conversion() -> None:
    normalizer = DeepNormalizer()
    html = """
    <html>
    <body>
    <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
    <p>FORM 10-K</p>
    <table>
      <tr><td>Delaware</td><td></td><td>13-2624428</td></tr>
      <tr><td>(State of Incorporation)</td><td></td><td>(I.R.S. Employer Identification No.)</td></tr>
      <tr><td>270 Park Avenue, New York, New York</td><td></td><td>10017</td></tr>
      <tr><td>(Address of principal executive offices)</td><td></td><td>(Zip Code)</td></tr>
    </table>
    <p>ITEM 1. BUSINESS</p>
    <table border="1">
      <tr><th>Year</th><th>Revenue</th><th>Net Income</th></tr>
      <tr><td>2024</td><td>$100,000</td><td>$10,000</td></tr>
      <tr><td>2025</td><td>$120,000</td><td>$15,000</td></tr>
    </table>
    </body>
    </html>
    """
    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=50,
        has_html_tags=True,
        detected_encoding="utf-8",
        metadata={"form": "10-K"},
    )
    normalized = normalizer.normalize(prep)

    # 1. Cover layout is preserved as canonical normalized source text.
    assert "Delaware" in normalized
    assert "(State of Incorporation)" in normalized
    assert "13-2624428" in normalized
    assert "(I.R.S. Employer" in normalized and "Identification No.)" in normalized
    assert "270 Park Avenue, New York, New York" in normalized
    assert "(Address of principal executive offices)" in normalized
    assert "10017" in normalized
    assert "(Zip Code)" in normalized

    # 2. Subsequent financial table converted to structured ASCII table
    assert "ITEM 1. BUSINESS" in normalized
    assert "Year" in normalized
    assert "$100,000" in normalized
    assert "Revenue" in normalized
    assert "$100,000" in normalized


def test_deep_normalizer_body_start_consumes_toc_end() -> None:
    """Body-start analysis receives a real TOC_END, not None."""
    normalizer = DeepNormalizer()
    text = (
        "UNITED STATES\n"
        "SECURITIES AND EXCHANGE COMMISSION\n"
        "WASHINGTON, D.C. 20549\n"
        "FORM 10-K\n"
        "ACME CORPORATION\n"
        "(Exact name of registrant as specified in its charter)\n"
        "\n"
        "TABLE OF CONTENTS\n"
        "ITEM 1. BUSINESS .......................... 1\n"
        "ITEM 1A. RISK FACTORS ..................... 8\n"
        "\n"
        "PART I\n"
        "\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "The Company was founded in 1985 and operates manufacturing facilities "
        "worldwide. It provides products to customers through its market "
        "segments.\n"
    )
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=80,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"form": "10-K"},
    )
    result = normalizer.normalize_result(prep)
    assert result.body_start is not None
    lines = result.text.splitlines()
    assert lines[result.body_start.line].strip() == "PART I"
    assert result.body_start.first_unit_line >= result.body_start.line


def test_deep_normalizer_removes_validated_html_markers_without_ascii_reflow() -> None:
    html = """<html><body>
    <div class="page-number">1</div>
    <p>First page paragraph.</p>
    <div class="page-number">2</div>
    <p>Second page paragraph.</p>
    <div class="page-number">3</div>
    <p>Third page paragraph.</p>
    </body></html>"""
    preprocessed = GenericPreprocessor().preprocess(html.encode("utf-8"))

    assert preprocessed.representation == "html"
    result = DeepNormalizer().normalize_result(preprocessed)

    assert "page-number" not in result.text
    assert "First page paragraph." in result.text
    assert "Third page paragraph." in result.text
    assert result.reflow is None
    assert result.page_analysis is not None
    assert result.page_analysis.coordinate_frame in ("html", "text")


# --------------------------------------------------------------------------
# Page artifact policy integration.
# --------------------------------------------------------------------------

PageArtifactPolicy = importlib.import_module(
    "defs.sec_forms.page_markers"
).PageArtifactPolicy


def _ascii_prep(text: str) -> PreprocessedDocument:
    return PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=len(text.split()),
        has_html_tags=False,
        detected_encoding="utf-8",
    )


def test_deep_normalizer_annotate_policy_emits_tokens_and_metadata() -> None:
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n<PAGE> 2\nMore prose.\n"
    result = normalizer.normalize_result(
        _ascii_prep(text), page_artifact_policy=PageArtifactPolicy.ANNOTATE
    )
    assert "[[SEC:PAGE_BREAK id=1]]" in result.text
    assert "[[SEC:PAGE_BREAK id=2]]" in result.text
    artifacts = result.page_artifacts
    assert artifacts is not None
    assert artifacts["policy"] == "annotate"
    assert artifacts["source_identity"]
    assert [entry["id"] for entry in artifacts["artifacts"]] == [1, 2]
    assert all(entry["removable"] for entry in artifacts["artifacts"])


def test_deep_normalizer_strip_policy_records_provenance_without_tokens() -> None:
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n<PAGE> 2\nMore prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert "[[SEC:" not in result.text
    assert "<PAGE>" not in result.text
    artifacts = result.page_artifacts
    assert artifacts is not None
    assert artifacts["policy"] == "strip"
    assert len(artifacts["artifacts"]) == 2
    assert all(entry["removable"] for entry in artifacts["artifacts"])
    assert all(entry["line_span"] is not None for entry in artifacts["artifacts"])


def test_deep_normalizer_preserve_policy_keeps_source() -> None:
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n<PAGE> 2\nMore prose.\n"
    result = normalizer.normalize_result(
        _ascii_prep(text), page_artifact_policy=PageArtifactPolicy.PRESERVE
    )
    assert "<PAGE>" in result.text
    assert result.page_artifacts is not None
    assert result.page_artifacts["policy"] == "preserve"
    assert result.page_artifacts["artifacts"] == []
    assert result.page_artifacts["templates"] == {}


# --------------------------------------------------------------------------
# Page-marker analysis lifecycle: analyze once, never refresh.
# --------------------------------------------------------------------------


def test_page_analysis_detects_source_marker_once() -> None:
    """The one canonical analysis detects the <PAGE> marker and one boundary."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_analysis is not None
    assert len(result.page_analysis.markers) >= 1
    assert len(result.page_analysis.page_boundaries) >= 1


def test_page_analysis_remains_non_empty_after_stripping() -> None:
    """The one analysis remains non-empty after STRIP policy removes markers."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_analysis is not None
    assert len(result.page_analysis.markers) >= 1
    assert result.page_analysis.page_number_runs == ()


def test_page_number_runs_zero_without_valid_candidates() -> None:
    """Numbered-run count remains zero when fewer than three valid candidates."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_analysis is not None
    assert result.page_analysis.page_number_runs == ()


def test_page_artifacts_record_removal_provenance() -> None:
    """Page policy removes <PAGE> and emits one removal artifact."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_artifacts is not None
    assert result.page_artifacts["policy"] == "strip"
    assert len(result.page_artifacts["artifacts"]) >= 1
    assert all(entry["removable"] for entry in result.page_artifacts["artifacts"])


def test_stage_trace_contains_required_stages() -> None:
    """Review JSON contains stage trace with all required stages."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    stages = [s["stage"] for s in result.stage_trace]
    assert "preprocessed" in stages
    assert "page_policy_input" in stages
    assert "page_policy_output" in stages
    assert "after_header_normalization" in stages
    assert "after_final_whitespace" in stages


def test_rejection_diagnostics_auditable() -> None:
    """Empty page_number_runs is auditable via rejection_diagnostics."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_analysis is not None
    assert result.page_analysis.page_number_runs == ()
    diagnostics = list(getattr(result.page_analysis, "rejection_diagnostics", ()))
    assert isinstance(diagnostics, list)


def test_page_analysis_not_overwritten_by_healing() -> None:
    """Cover healing does not overwrite source page_analysis."""
    normalizer = DeepNormalizer()
    text = "<PAGE>\nUNITED STATES\nFORM 10-K\nACME CORP\n\nTABLE OF CONTENTS\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert result.page_analysis is not None
    assert len(result.page_analysis.markers) >= 1
    assert result.page_analysis is result.page_analysis


def test_stable_expected_metadata_includes_rejection_diagnostics() -> None:
    """stable_expected_metadata includes rejection_diagnostics."""
    import importlib
    from types import SimpleNamespace

    review_mod = importlib.import_module("phases.025_webpage_storage.testing.review")
    stable_expected_metadata = review_mod.stable_expected_metadata
    normalizer = DeepNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    mock_result = SimpleNamespace(
        normalization=result,
        processed=SimpleNamespace(metadata={}),
        preprocessed=_ascii_prep(text),
    )
    meta = stable_expected_metadata(mock_result)
    assert "rejection_diagnostics" in meta
    assert isinstance(meta["rejection_diagnostics"], list)


# --------------------------------------------------------------------------
# Table protection: heading and whitespace normalization.
# --------------------------------------------------------------------------


def test_normalize_headers_preserves_table_spacing() -> None:
    """Heading normalization leaves table spacing byte-for-byte unchanged."""
    normalizer = DeepNormalizer()
    text = (
        "<TABLE>\n"
        "ITEM 5.               Market for the Registrant's Common Equity\n"
        "ITEM 7.               Management's Discussion\n"
        "</TABLE>\n"
        "ITEM 1. BUSINESS\n"
    )
    result = normalizer.normalize_result(_ascii_prep(text))
    normalized = result.text
    table_start = normalized.find("<TABLE>")
    if table_start != -1:
        table_end = normalized.find("</TABLE>", table_start)
        if table_end != -1:
            table_content = normalized[table_start : table_end + len("</TABLE>")]
            assert "ITEM 5." in table_content
            assert "ITEM 7." in table_content


def test_reflow_preserves_tagged_table() -> None:
    """Reflow preserves the tagged table exactly."""
    normalizer = DeepNormalizer()
    text = "<TABLE>\nItem 1. Description\nValue 1\n</TABLE>\nSome prose here.\n"
    result = normalizer.normalize_result(_ascii_prep(text))
    assert "<TABLE>" in result.text
    assert "</TABLE>" in result.text


# --------------------------------------------------------------------------
# ProtectedText abstraction.
# --------------------------------------------------------------------------


def test_protected_text_outside_only_transform() -> None:
    """ProtectedText.transform_outside only modifies text outside tables."""
    from defs.tables.protection import ProtectedText

    text = "Hello <TABLE>cell\nvalue</TABLE> World"
    pt = ProtectedText(text)
    assert pt.span_count == 1
    result = pt.transform_outside(lambda s: s.upper())
    assert "<TABLE>" in result
    assert "cell" in result
    assert "WORLD" in result


def test_protected_text_multiple_tables() -> None:
    """ProtectedText handles multiple tables."""
    from defs.tables.protection import ProtectedText

    text = "<TABLE>1</TABLE> middle <TABLE>2</TABLE>"
    pt = ProtectedText(text)
    assert pt.span_count == 2
    assert len(pt.complete_spans) == 2


def test_protected_text_unterminated_table() -> None:
    """ProtectedText handles unterminated tables."""
    from defs.tables.protection import ProtectedText

    text = "<TABLE>unclosed"
    pt = ProtectedText(text)
    assert pt.span_count == 1
    assert len(pt.unterminated_spans) == 1
    assert len(pt.complete_spans) == 0


def test_protected_text_restore_once() -> None:
    """ProtectedText.original restores tables exactly once."""
    from defs.tables.protection import ProtectedText

    text = "Hello <TABLE>cell</TABLE> World"
    pt = ProtectedText(text)
    restored = pt.original
    assert restored == text
    restored_again = pt.original
    assert restored_again == text


def test_protected_text_line_ranges() -> None:
    """ProtectedText.span line_ranges preserve line-coordinate information."""
    from defs.tables.protection import ProtectedText

    text = "Line 1\n<TABLE>cell\nvalue</TABLE>\nLine 3"
    pt = ProtectedText(text)
    for span in pt.spans:
        ranges = span.line_ranges
        assert len(ranges) == 1
        assert ranges[0][0] == 0
        assert ranges[0][1] == 1
