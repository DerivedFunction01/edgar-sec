"""Unit tests for Form 10-Q evaluator and normalizer."""

from __future__ import annotations

import importlib

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
form_10q_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.form_10q"
)

DocumentLocator = schemas.DocumentLocator
DecisionAction = forms_base.DecisionAction
PreprocessedDocument = forms_base.PreprocessedDocument
Form10QEvaluator = form_10q_mod.Form10QEvaluator
Form10QNormalizer = form_10q_mod.Form10QNormalizer


def test_form_10q_evaluator_basic() -> None:
    evaluator = Form10QEvaluator()
    loc = DocumentLocator(
        "q1", "0000950124-04-000801", "q10k.htm", "https://sec.gov", "10-Q"
    )
    prep = PreprocessedDocument("text", "text", 1, False, "utf-8")
    decision = evaluator.evaluate(prep, loc)
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False


def test_form_10q_normalizer() -> None:
    normalizer = Form10QNormalizer()
    text = "part i\nitem 1. financial statements\nRevenue table.\npart ii\nitem 1. legal proceedings\nNone."
    normalized = normalizer.normalize(text)
    assert normalized == text
