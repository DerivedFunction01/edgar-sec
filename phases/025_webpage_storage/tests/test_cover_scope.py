"""Contract tests for representation-aware cover routing and capability gating."""

from __future__ import annotations

import importlib

forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
shared_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.shared.hybrid_cover"
)
router_mod = importlib.import_module("phases.025_webpage_storage.processors.router")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)

PreprocessedDocument = forms_base.PreprocessedDocument
HybridCoverPreprocessor = shared_mod.HybridCoverPreprocessor
FormRouter = router_mod.FormRouter
DeepNormalizer = normalizer_mod.DeepNormalizer


def _prep(
    html: str, *, has_html_tags: bool = True, form: str | None = "10-K"
) -> PreprocessedDocument:
    return PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=len(html.split()),
        has_html_tags=has_html_tags,
        detected_encoding="utf-8",
        metadata={"form": form} if form else {},
    )


def test_router_resolves_20f_and_6k_aliases() -> None:
    router = FormRouter()
    assert router.get_evaluator("20-F") is not None
    assert router.get_evaluator("6-K") is not None
    assert router.get_normalizer("20-F") is not None
    assert router.get_normalizer("6-K") is not None


def test_router_uses_generic_for_unknown_forms() -> None:
    router = FormRouter()
    form_generic_mod = importlib.import_module(
        "phases.025_webpage_storage.processors.forms.form_generic"
    )
    GenericFormEvaluator = form_generic_mod.GenericFormEvaluator
    GenericFormNormalizer = form_generic_mod.GenericFormNormalizer

    assert isinstance(router.get_evaluator("S-1"), GenericFormEvaluator)
    assert isinstance(router.get_normalizer("FORM 3"), GenericFormNormalizer)
    assert isinstance(router.get_evaluator(None), GenericFormEvaluator)


def test_no_cover_profile_disables_cover_templates() -> None:
    html_doc = """
    <html>
      <body>
        <table>
          <tr>
            <td>Large accelerated filer</td>
            <td>&#9746;</td>
            <td>Accelerated filer</td>
            <td>&#9744;</td>
          </tr>
        </table>
      </body>
    </html>
    """

    from defs.sec_forms.cover import get_profile

    preprocessor = HybridCoverPreprocessor(get_profile("8-K"))
    result = preprocessor.preprocess(html_doc)
    assert result.matched is False
    assert result.template is None
    assert result.reason == "no_cover_profile_or_evidence"
    # Checkbox canonicalization is document-wide and still applies.
    assert "[X]" in result.html
    assert "[ ]" in result.html


def test_quarterly_profile_excludes_annual_healing() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES</p>
        <p>SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-Q</p>
        <p>For the quarterly period ended July 31, 2024</p>
        <p>Documents incorporated by reference: Portions of Part III.</p>
        <p>Item 1. Financial Statements</p>
      </body>
    </html>
    """

    from defs.sec_forms.cover import get_profile

    preprocessor = HybridCoverPreprocessor(get_profile("10-Q"))
    result = preprocessor.preprocess(html_doc)
    text = result.html
    # Quarterly boundary excludes the annual-only anchor, so body content is
    # preserved as-is rather than being treated as a cover region end.
    assert "Documents incorporated by reference: Portions of Part III." in text
    assert "Item 1. Financial Statements" in text


def test_pure_xml_does_not_enter_html_cover_pass() -> None:
    normalizer = DeepNormalizer()
    xml_text = "<root><ix:nonFraction>1500000</ix:nonFraction></root>"
    prep = _prep(xml_text, has_html_tags=False, form="10-K")
    normalized = normalizer.normalize(prep)
    assert "<ix:" not in normalized
    assert "1500000" in normalized


def test_html_body_without_cover_evidence_is_not_matched() -> None:
    normalizer = DeepNormalizer()
    html = """
    <html>
      <body>
        <p>Item 1. Business</p>
        <p>We manufacture widgets.</p>
        <table border="1">
          <tr><th>Year</th><th>Revenue</th></tr>
          <tr><td>2024</td><td>$100</td></tr>
        </table>
      </body>
    </html>
    """
    prep = _prep(html, form="8-K")
    normalized = normalizer.normalize(prep)
    assert "Item 1. Business" in normalized
    assert "Revenue" in normalized
    assert "<tr>" not in normalized.lower()


def test_annual_cover_profile_matches_existing_behavior() -> None:
    html_doc = """
    <html>
      <body>
        <div>
          UNITED STATES<br>
          SECURITIES AND EXCHANGE COMMISSION<br>
          WASHINGTON, D.C. 20549<br>
          FORM 10-K<br>
          For the fiscal<br>
          year ended December 31, 2024<br>
          Commission file<br>
          number 001-13665<br>
          JARDEN CORPORATION<br>
          (Exact name of registrant as specified in its charter)<br>
          <table>
            <tr>
              <td>Delaware</td>
              <td>35-1828377</td>
            </tr>
            <tr>
              <td>(State or other jurisdiction of incorporation or organization)</td>
              <td>(I.R.S. Employer Identification No.)</td>
            </tr>
          </table>
        </div>
      </body>
    </html>
    """

    from defs.sec_forms.cover import get_profile

    preprocessor = HybridCoverPreprocessor(get_profile("10-K"))
    result = preprocessor.preprocess(html_doc, company_name="Jarden Corporation")
    assert result.matched is True
    text = result.html
    assert "UNITED STATES SECURITIES AND EXCHANGE COMMISSION" in text
    assert "For the fiscal year ended December 31, 2024" in text
    assert "Commission file number 001-13665" in text
    assert (
        "Delaware\n(State or other jurisdiction of incorporation or organization)"
        in text
    )
    assert "35-1828377\n(I.R.S. Employer Identification No.)" in text
