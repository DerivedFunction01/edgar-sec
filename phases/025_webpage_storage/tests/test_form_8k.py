"""Unit tests for Form 8-K evaluator and normalizer."""

from __future__ import annotations

import importlib

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
form_8k_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_8k"
)

DocumentLocator = schemas.DocumentLocator
DecisionAction = forms_base.DecisionAction
PreprocessedDocument = forms_base.PreprocessedDocument
Form8KEvaluator = form_8k_mod.Form8KEvaluator
Form8KNormalizer = form_8k_mod.Form8KNormalizer


def test_form_8k_evaluator_basic() -> None:
    evaluator = Form8KEvaluator()
    loc = DocumentLocator(
        "8k1", "0000950124-04-000801", "8k.htm", "https://sec.gov", "8-K"
    )
    prep = PreprocessedDocument("text", "text", 1, False, "utf-8")
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False


def test_form_8k_normalizer_headings() -> None:
    normalizer = Form8KNormalizer()
    text = "section 1 - registrant's business and operations\nitem 1.01 entry into a material definitive agreement\nWe signed an agreement.\nitem 9.01 financial statements and exhibits\nNone."
    normalized = normalizer.normalize_headers(text)

    assert "SECTION 1 - REGISTRANT'S BUSINESS AND OPERATIONS\n" in normalized
    assert "ITEM 1.01. entry into a material definitive agreement\n" in normalized
    assert "ITEM 9.01. financial statements and exhibits\n" in normalized
