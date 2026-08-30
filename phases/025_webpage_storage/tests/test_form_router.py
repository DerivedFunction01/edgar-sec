"""Tests for Stage 2 FormRouter."""

from __future__ import annotations

import importlib

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
form_8k_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_8k"
)
form_10k_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_10k"
)
form_10q_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_10q"
)
form_generic_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_generic"
)
router_mod = importlib.import_module("phases.025_webpage_storage.processors.router")

DocumentLocator = schemas.DocumentLocator
DecisionAction = forms_base.DecisionAction
PreprocessedDocument = forms_base.PreprocessedDocument
Form8KEvaluator = form_8k_mod.Form8KEvaluator
Form10KEvaluator = form_10k_mod.Form10KEvaluator
Form10QEvaluator = form_10q_mod.Form10QEvaluator
GenericFormEvaluator = form_generic_mod.GenericFormEvaluator
FormRouter = router_mod.FormRouter


def test_form_router_resolution() -> None:
    router = FormRouter()

    # 10-K variations
    assert isinstance(router.get_evaluator("10-K"), Form10KEvaluator)
    assert isinstance(router.get_evaluator("10-K405"), Form10KEvaluator)
    assert isinstance(router.get_evaluator("10-KSB"), Form10KEvaluator)
    assert isinstance(router.get_evaluator("10-KT/A"), Form10KEvaluator)

    # 10-Q variations
    assert isinstance(router.get_evaluator("10-Q"), Form10QEvaluator)
    assert isinstance(router.get_evaluator("10-QSB"), Form10QEvaluator)

    # 8-K variations
    assert isinstance(router.get_evaluator("8-K"), Form8KEvaluator)
    assert isinstance(router.get_evaluator("8-K12B"), Form8KEvaluator)

    # Generic fallback
    assert isinstance(router.get_evaluator("20-F"), GenericFormEvaluator)
    assert isinstance(router.get_evaluator("11-K"), GenericFormEvaluator)
    assert isinstance(router.get_evaluator(None), GenericFormEvaluator)


def test_form_router_evaluate_default_proceed() -> None:
    router = FormRouter()
    loc = DocumentLocator(
        locator_key="k1",
        accession="0000950124-04-000801",
        document_path="k82532e10vk.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/55067/000095012404000801/k82532e10vk.htm",
        form="10-K",
    )
    prep = PreprocessedDocument(
        raw_text="Item 1. Business",
        cleaned_text="Item 1. Business",
        word_count=3,
        has_html_tags=False,
        detected_encoding="utf-8",
    )

    decision = router.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False


def test_form_router_post_2011_temporal_bypass() -> None:
    router = FormRouter()
    loc = DocumentLocator(
        locator_key="k2015",
        accession="0001193125-15-000001",
        document_path="form10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/12345/000119312515000001/form10k.htm",
        form="10-K",
    )
    prep = PreprocessedDocument(
        raw_text="<p>Form 10-K for FY 2014 filed in 2015</p>",
        cleaned_text="Form 10-K for FY 2014 filed in 2015",
        word_count=10,
        has_html_tags=True,
        detected_encoding="utf-8",
        metadata={"filing_year": 2015},
    )

    decision = router.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "post_2011_xbrl_full"


def test_form_router_size_ceiling_bypass() -> None:
    router = FormRouter()
    loc = DocumentLocator(
        locator_key="klarge",
        accession="0000950124-04-000801",
        document_path="k82532e10vk.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/55067/000095012404000801/k82532e10vk.htm",
        form="10-K",
    )
    # Large 1.5MB HTML payload
    big_html = (
        "<html><body>"
        + ("<p>Substantive accounting note disclosure.</p>\n" * 25000)
        + "</body></html>"
    )
    prep = PreprocessedDocument(
        raw_text=big_html,
        cleaned_text=big_html,
        word_count=100000,
        has_html_tags=True,
        detected_encoding="utf-8",
        metadata={"filing_year": 2004},
    )

    decision = router.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "size_ceiling_full"
