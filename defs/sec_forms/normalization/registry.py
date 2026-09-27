"""Form normalization pipeline registry and lookup factory."""

from __future__ import annotations

from defs.sec_forms.families import resolve_alias
from defs.sec_forms.normalization.base import FormNormalizationPipeline
from defs.sec_forms.normalization.pipelines.annual import AnnualPipeline
from defs.sec_forms.normalization.pipelines.current_report import CurrentReportPipeline
from defs.sec_forms.normalization.pipelines.fallback import FallbackPipeline
from defs.sec_forms.normalization.pipelines.quarterly import QuarterlyPipeline

_PIPELINE_REGISTRY: dict[str, FormNormalizationPipeline] = {
    "10-K": AnnualPipeline("10-K"),
    "20-F": AnnualPipeline("20-F"),
    "10-Q": QuarterlyPipeline("10-Q"),
    "8-K": CurrentReportPipeline("8-K"),
}
_FALLBACK_PIPELINE = FallbackPipeline()


def register_pipeline(
    family: str,
    pipeline: FormNormalizationPipeline,
) -> None:
    """Register or override a normalization pipeline for a form family."""
    _PIPELINE_REGISTRY[family.strip().upper()] = pipeline


def get_pipeline(form: str | None) -> FormNormalizationPipeline:
    """Resolve the appropriate FormNormalizationPipeline for a given form type."""
    if not form:
        return _FALLBACK_PIPELINE

    family = resolve_alias(form)
    if family:
        pipeline = _PIPELINE_REGISTRY.get(family.upper())
        if pipeline is not None:
            return pipeline

    raw_form = form.strip().upper()
    return _PIPELINE_REGISTRY.get(raw_form, _FALLBACK_PIPELINE)


__all__ = [
    "get_pipeline",
    "register_pipeline",
]
