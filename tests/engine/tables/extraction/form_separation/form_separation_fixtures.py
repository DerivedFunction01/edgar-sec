"""Shared form-separation fixtures: family specs and evaluators."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.evidence.form.form_separation_evidence import (
    FormSeparationText,
    evaluate_form_separation,
)
from edgar_sec.engine.tables.extraction.specs.form_separation_specs import (
    FORM_SEPARATION_SPECS,
)

SPEC = FORM_SEPARATION_SPECS["related_party"]
EPS_SPEC = FORM_SEPARATION_SPECS["eps_reconciliation"]
INT_SPEC = FORM_SEPARATION_SPECS["intangibles"]


def _eval(table_text: str, caption_stack=()):
    return evaluate_form_separation(FormSeparationText(table_text, caption_stack), SPEC)


def _eval_eps(table_text: str, caption_stack=()):
    return evaluate_form_separation(
        FormSeparationText(table_text, caption_stack), EPS_SPEC
    )


def _eval_int(table_text: str, caption_stack=()):
    return evaluate_form_separation(
        FormSeparationText(table_text, caption_stack), INT_SPEC
    )
