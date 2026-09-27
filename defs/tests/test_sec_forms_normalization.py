"""Unit tests for defs.sec_forms.normalization engine, pipelines, and evaluators."""

from __future__ import annotations

from defs.sec_documents import DocumentPreprocessor
from defs.sec_documents.models import PreprocessedDocument
from defs.sec_forms.forms.annual.evaluator import AnnualEvaluator
from defs.sec_forms.forms.current_report.evaluator import CurrentReportEvaluator
from defs.sec_forms.forms.evaluator import DecisionAction, get_evaluator
from defs.sec_forms.forms.quarterly.evaluator import QuarterlyEvaluator
from defs.sec_forms.normalization import (
    DocumentNormalizer,
    get_pipeline,
    normalize_document,
)
from defs.sec_forms.normalization.pipelines.annual import AnnualPipeline
from defs.sec_forms.normalization.pipelines.current_report import CurrentReportPipeline
from defs.sec_forms.normalization.pipelines.quarterly import QuarterlyPipeline
from defs.sec_forms.page_markers import PageArtifactPolicy


def _ascii_prep(text: str, form: str | None = None) -> PreprocessedDocument:
    metadata = {}
    if form:
        metadata["form"] = form
    return PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=len(text.split()),
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata=metadata,
        representation="ascii",
    )


def test_registry_resolution() -> None:
    assert isinstance(get_pipeline("10-K"), AnnualPipeline)
    assert isinstance(get_pipeline("10-K405"), AnnualPipeline)
    assert isinstance(get_pipeline("10-KSB"), AnnualPipeline)
    assert isinstance(get_pipeline("20-F"), AnnualPipeline)
    assert isinstance(get_pipeline("10-Q"), QuarterlyPipeline)
    assert isinstance(get_pipeline("10-QSB"), QuarterlyPipeline)
    assert isinstance(get_pipeline("8-K"), CurrentReportPipeline)
    assert isinstance(get_pipeline("8-K12B"), CurrentReportPipeline)


def test_annual_normalization_html() -> None:
    html = """
    <html>
    <body>
    <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
    <p>FORM 10-K</p>
    <p>ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)</p>
    <p>For the fiscal year ended December 31, 2020</p>
    <p>Commission File Number: 001-12345</p>
    <p>ACME WIDGETS CORP</p>
    <table border="1">
      <tr><th>Year</th><th>Revenue</th></tr>
      <tr><td>2020</td><td>$100,000</td></tr>
    </table>
    <p>ITEM 1. BUSINESS</p>
    <p>We manufacture widgets worldwide.</p>
    <p>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</p>
    <p>Operations increased substantially.</p>
    </body>
    </html>
    """
    prep = DocumentPreprocessor().preprocess(
        html.encode("utf-8"), metadata={"form": "10-K"}
    )
    result = normalize_document(prep)
    assert "ITEM 1. BUSINESS" in result.text
    assert "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS" in result.text
    assert result.cover_boundary is not None
    assert "<tr>" not in result.text.lower()
    assert "$100,000" in result.text


def test_annual_normalization_pre_wrapped_ascii() -> None:
    html = """
    <html>
    <body>
    <pre>
    ITEM 1. BUSINESS
    We build software.

    ITEM 7. MD&A
    Revenues grew strongly.
    </pre>
    </body>
    </html>
    """
    prep = DocumentPreprocessor().preprocess(
        html.encode("utf-8"), metadata={"form": "10-K"}
    )
    assert prep.representation in ("ascii", "ascii_pre")
    result = normalize_document(prep)
    assert "ITEM 1. BUSINESS" in result.text
    assert "ITEM 7. MD&A" in result.text


def test_quarterly_normalization_ascii() -> None:
    text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 10-Q\n"
        "QUARTERLY REPORT PURSUANT TO SECTION 13 OR 15(d)\n"
        "For the quarterly period ended March 31, 2021\n"
        "Commission File Number: 001-12345\n"
        "PART I. FINANCIAL INFORMATION\n"
        "ITEM 1. FINANCIAL STATEMENTS\n"
        "Revenue was $10 million.\n"
    )
    prep = _ascii_prep(text, form="10-Q")
    normalizer = DocumentNormalizer()
    norm_result = normalizer.normalize_result(prep)
    assert "PART I. FINANCIAL INFORMATION" in norm_result.text
    assert "ITEM 1. FINANCIAL STATEMENTS" in norm_result.text


def test_evaluator_factory() -> None:
    assert isinstance(get_evaluator("10-K"), AnnualEvaluator)
    assert isinstance(get_evaluator("10-Q"), QuarterlyEvaluator)
    assert isinstance(get_evaluator("8-K"), CurrentReportEvaluator)

    # 10-K exhibit 13 delegation evaluation
    evaluator = get_evaluator("10-K")
    prep = PreprocessedDocument(
        raw_text="Item 7 is incorporated by reference to Exhibit 13 filed herewith.",
        cleaned_text="Item 7 is incorporated by reference to Exhibit 13 filed herewith.",
        word_count=12,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"filing_year": 2005},
        representation="ascii",
    )
    decision = evaluator.evaluate(prep)
    assert decision.action == DecisionAction.REFETCH_SUB_DOC
    assert decision.is_stub is True
    assert decision.target_exhibit == "EX-13"


def test_page_artifact_policies() -> None:
    normalizer = DocumentNormalizer()
    text = "<PAGE>\nITEM 1. BUSINESS\nSome prose.\n<PAGE> 2\nMore prose.\n"

    # Annotate policy
    annotate_res = normalizer.normalize_result(
        _ascii_prep(text, "10-K"), page_artifact_policy=PageArtifactPolicy.ANNOTATE
    )
    assert "[[SEC:PAGE_BREAK id=1]]" in annotate_res.text
    assert annotate_res.page_artifacts is not None
    assert annotate_res.page_artifacts["policy"] == "annotate"

    # Strip policy
    strip_res = normalizer.normalize_result(
        _ascii_prep(text, "10-K"), page_artifact_policy=PageArtifactPolicy.STRIP
    )
    assert "[[SEC:" not in strip_res.text
    assert "<PAGE>" not in strip_res.text
    assert strip_res.page_artifacts is not None
    assert strip_res.page_artifacts["policy"] == "strip"


def test_stage_trace() -> None:
    normalizer = DocumentNormalizer()
    text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 10-K\n"
        "ITEM 1. BUSINESS\nProse.\n"
    )
    result = normalizer.normalize_result(_ascii_prep(text, "10-K"))
    assert len(result.stage_trace) >= 3
    stage_names = [s["stage"] for s in result.stage_trace]
    assert "preprocessed" in stage_names
    assert "page_policy_output" in stage_names
    assert "after_final_whitespace" in stage_names


def test_tag_untagged_tables_opt_in() -> None:
    raw_ascii = (
        "FORM 10-K\n\n"
        "ANNUAL REPORT PURSUANT TO SECTION 13\n\n"
        "Registrant: Example Corp\n\n"
        "TABLE OF CONTENTS\n\n"
        "PART I\n"
        "ITEM 1. BUSINESS\n\n"
        "We are an enterprise software company founded in 1998 that sells "
        "products across multiple market segments today.\n\n"
        "2. PROPERTY AND EQUIPMENT:\n\n"
        "Property and equipment consist of the following at December 31, 1998:\n\n"
        "    Machinery and equipment                                     $465,498\n"
        "    Furniture and fixtures                                       177,904\n"
        "                                                               ---------\n"
        "                                                                $643,402\n"
        "                                                               =========\n\n"
        "Continuing prose.\n"
    )
    prep = DocumentPreprocessor().preprocess(
        raw_ascii.encode("utf-8"), metadata={"form": "10-K"}
    )
    default_res = DocumentNormalizer().normalize_result(prep)
    assert "<TABLE>" not in default_res.text
    assert "$643,402" in default_res.text

    tagged_res = DocumentNormalizer(tag_untagged_tables=True).normalize_result(prep)
    assert "<TABLE>" in tagged_res.text
    assert "</TABLE>" in tagged_res.text
