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


def test_form_10k_normalizer_headings() -> None:
    normalizer = Form10KNormalizer()
    text = "part i\nitem 1. business\nWe sell software.\npart ii\nitem 7. md&a\nRevenue grew."
    normalized = normalizer.normalize_headers(text)

    assert "PART I\n" in normalized
    assert "ITEM 1. business\n" in normalized
    assert "PART II\n" in normalized
    assert "ITEM 7. md&a\n" in normalized
