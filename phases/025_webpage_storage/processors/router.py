"""Form router for evaluator and normalizer dispatch."""

from __future__ import annotations

from collections.abc import Mapping

from defs.sec_forms import FORM_FAMILY_ALIASES

from ..core.schemas import DocumentLocator
from .forms.base import (
    FormEvaluator,
    FormNormalizer,
    PreprocessedDocument,
    RefetchDecision,
)
from .forms.form_8k import Form8KEvaluator, Form8KNormalizer
from .forms.form_10k import Form10KEvaluator, Form10KNormalizer
from .forms.form_10q import Form10QEvaluator, Form10QNormalizer
from .forms.form_generic import GenericFormEvaluator, GenericFormNormalizer


def _register_family(
    evaluators: dict[str, FormEvaluator],
    normalizers: dict[str, FormNormalizer],
    family: str,
    evaluator: FormEvaluator,
    normalizer: FormNormalizer,
) -> None:
    for alias in FORM_FAMILY_ALIASES.get(family, ()):
        evaluators.setdefault(alias.upper(), evaluator)
        normalizers.setdefault(alias.upper(), normalizer)


class FormRouter:
    """Stage 2 form router directing preprocessed documents to form-specific evaluators and normalizers."""

    def __init__(
        self,
        evaluators: Mapping[str, FormEvaluator] | None = None,
        default_evaluator: FormEvaluator | None = None,
        normalizers: Mapping[str, FormNormalizer] | None = None,
        default_normalizer: FormNormalizer | None = None,
    ) -> None:
        self._evaluators: dict[str, FormEvaluator] = dict(evaluators or {})
        self._default_evaluator = default_evaluator or GenericFormEvaluator()
        self._normalizers: dict[str, FormNormalizer] = dict(normalizers or {})
        self._default_normalizer = default_normalizer or GenericFormNormalizer()

        if not self._evaluators or not self._normalizers:
            self._register_defaults()

    def _register_defaults(self) -> None:
        k10_eval, k10_norm = Form10KEvaluator(), Form10KNormalizer()
        q10_eval, q10_norm = Form10QEvaluator(), Form10QNormalizer()
        k8_eval, k8_norm = Form8KEvaluator(), Form8KNormalizer()

        # 10-K family
        _register_family(
            self._evaluators, self._normalizers, "10-K", k10_eval, k10_norm
        )

        # 10-Q family
        _register_family(
            self._evaluators, self._normalizers, "10-Q", q10_eval, q10_norm
        )

        # 8-K family
        _register_family(self._evaluators, self._normalizers, "8-K", k8_eval, k8_norm)

    def get_evaluator(self, form: str | None) -> FormEvaluator:
        """Resolve the appropriate FormEvaluator for a given form type."""
        if not form:
            return self._default_evaluator
        return self._evaluators.get(form.strip().upper(), self._default_evaluator)

    def get_normalizer(self, form: str | None) -> FormNormalizer:
        """Resolve the appropriate FormNormalizer for a given form type."""
        if not form:
            return self._default_normalizer
        return self._normalizers.get(form.strip().upper(), self._default_normalizer)

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Route preprocessed document to its form evaluator and emit a RefetchDecision."""
        evaluator = self.get_evaluator(locator.form)
        return evaluator.evaluate(preprocessed, locator)


__all__ = ["FormRouter"]
