"""Unit tests for Form 10-K evaluator and normalizer."""

from __future__ import annotations

import importlib

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
form_10k_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_10k"
)

DocumentLocator = schemas.DocumentLocator
DecisionAction = forms_base.DecisionAction
PreprocessedDocument = forms_base.PreprocessedDocument
Form10KEvaluator = form_10k_mod.Form10KEvaluator
Form10KNormalizer = form_10k_mod.Form10KNormalizer


def test_form_10k_evaluator_basic() -> None:
    evaluator = Form10KEvaluator()
    loc = DocumentLocator(
        "k1", "0000950124-04-000801", "k82532e10vk.htm", "https://sec.gov", "10-K"
    )
    prep = PreprocessedDocument("text", "text", 1, False, "utf-8")
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False


def test_form_10k_evaluator_post_2011_bypass() -> None:
    evaluator = Form10KEvaluator()
    loc = DocumentLocator(
        "k1", "0000950124-15-000801", "k82532e10vk.htm", "https://sec.gov", "10-K"
    )
    text = "Information is incorporated by reference to Exhibit 13 filed herewith."
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=10,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"filing_year": 2015},
    )
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False
    assert decision.category == "post_2011_xbrl_full"


def test_form_10k_evaluator_exhibit_13_delegation() -> None:
    evaluator = Form10KEvaluator()
    loc = DocumentLocator(
        "k1", "0000950124-05-000801", "k82532e10vk.htm", "https://sec.gov", "10-K"
    )
    text = (
        "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS\n"
        "The information required by this item is incorporated by reference to Exhibit 13.01.\n"
        "ITEM 8. FINANCIAL STATEMENTS\n"
        "Refer to Exhibit 13 for financial tables."
    )
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=25,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"filing_year": 2005},
    )
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.REFETCH_SUB_DOC
    assert decision.is_stub is True
    assert decision.target_exhibit == "EX-13"
    assert decision.category == "exhibit_13_delegation"
    assert "char_span" in decision.metadata
    assert "line_number" in decision.metadata
    assert decision.metadata["line_number"] == 2
    assert "Exhibit 13" in decision.metadata["snippet"]


def test_form_10k_evaluator_index_only_no_delegation() -> None:
    evaluator = Form10KEvaluator()
    loc = DocumentLocator(
        "k1", "0000950124-05-000801", "k82532e10vk.htm", "https://sec.gov", "10-K"
    )
    text = (
        "ITEM 15. EXHIBITS AND FINANCIAL STATEMENT SCHEDULES\n"
        "(a) The following exhibits are filed as part of this report:\n"
        "Exhibit 10.1 Material Contract\n"
        "Exhibit 13 Annual Report\n"
        "Exhibit 21 Subsidiaries"
    )
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=30,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"filing_year": 2005},
    )
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False
    assert decision.category == "exhibit_index_only"


def test_form_10k_normalizer_headings() -> None:
    normalizer = Form10KNormalizer()
    text = "part i\nitem 1. business\nWe sell software.\npart ii\nitem 7. md&a\nRevenue grew."
    normalized = normalizer.normalize_headers(text)

    assert "PART I\n" in normalized
    assert "ITEM 1. business\n" in normalized
    assert "PART II\n" in normalized
    assert "ITEM 7. md&a\n" in normalized
