"""Form router and evaluator dispatcher."""

from __future__ import annotations

from collections.abc import Mapping

from ..core.schemas import DocumentLocator
from .forms.base import FormEvaluator, PreprocessedDocument, RefetchDecision
from .forms.form_8k import Form8KEvaluator
from .forms.form_10k import Form10KEvaluator
from .forms.form_10q import Form10QEvaluator
from .forms.form_generic import GenericFormEvaluator


class FormRouter:
    """Stage 2 form router directing preprocessed documents to form-specific evaluators."""

    def __init__(
        self,
        evaluators: Mapping[str, FormEvaluator] | None = None,
        default_evaluator: FormEvaluator | None = None,
    ) -> None:
        self._evaluators: dict[str, FormEvaluator] = dict(evaluators or {})
        self._default_evaluator = default_evaluator or GenericFormEvaluator()

        if not self._evaluators:
            self._register_default_evaluators()

    def _register_default_evaluators(self) -> None:
        k10 = Form10KEvaluator()
        q10 = Form10QEvaluator()
        k8 = Form8KEvaluator()

        # 10-K family
        for f in (
            "10-K",
            "10-K/A",
            "10-K405",
            "10-K405/A",
            "10-KSB",
            "10-KSB/A",
            "10KSB",
            "10KSB40",
            "10-KT",
            "10-KT/A",
        ):
            self._evaluators[f.upper()] = k10

        # 10-Q family
        for f in (
            "10-Q",
            "10-Q/A",
            "10-QSB",
            "10-QSB/A",
            "10QSB",
            "10-QT",
            "10-QT/A",
        ):
            self._evaluators[f.upper()] = q10

        # 8-K family
        for f in ("8-K", "8-K/A", "8-K12B", "8-K12G3", "8-K15D5"):
            self._evaluators[f.upper()] = k8

    def get_evaluator(self, form: str | None) -> FormEvaluator:
        """Resolve the appropriate FormEvaluator for a given form type."""
        if not form:
            return self._default_evaluator
        normalized_form = form.strip().upper()
        return self._evaluators.get(normalized_form, self._default_evaluator)

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Route preprocessed document to its form evaluator and emit a RefetchDecision."""
        evaluator = self.get_evaluator(locator.form)
        return evaluator.evaluate(preprocessed, locator)
