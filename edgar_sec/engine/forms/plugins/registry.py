"""Form plugin registry: the single lookup from a raw form string to its plugin.

Seeded with the modeled families (10-K, 10-Q, 8-K). Evaluator hooks are bound
lazily so importing the registry never pulls in evaluator modules, which keeps
the engine import graph acyclic and import cost flat.
"""

from __future__ import annotations

from importlib import import_module

from edgar_sec.domain.forms.families import form_family, resolve_alias
from edgar_sec.domain.forms.schemas import (
    ANNUAL_CHECKBOX_SCHEMA,
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.engine.forms.cover.models import BoundarySignal
from edgar_sec.engine.forms.plugins.annual_rules import ANNUAL_PHRASE_RULES
from edgar_sec.engine.forms.plugins.common_rules import COMMON_PHRASE_RULES
from edgar_sec.engine.forms.plugins.models import (
    GENERIC_FAMILY,
    Evaluator,
    FormPlugin,
)

_ANNUAL_SIGNALS: tuple[BoundarySignal, ...] = (
    BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
    BoundarySignal.PAGE_MARKERS,
    BoundarySignal.INCORPORATED_REFERENCE,
    BoundarySignal.TOC_TRANSITION,
    BoundarySignal.PART_FALLBACK,
    BoundarySignal.ITEM_FALLBACK,
    BoundarySignal.BODY_PROSE_FALLBACK,
)

_QUARTERLY_SIGNALS: tuple[BoundarySignal, ...] = (
    BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
    BoundarySignal.PAGE_MARKERS,
    BoundarySignal.PART_FALLBACK,
    BoundarySignal.ITEM_FALLBACK,
    BoundarySignal.BODY_PROSE_FALLBACK,
)

_CURRENT_REPORT_SIGNALS: tuple[BoundarySignal, ...] = (
    BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
    BoundarySignal.PAGE_MARKERS,
)


def _lazy_evaluator(module_name: str, attribute: str) -> Evaluator:
    """Bind an evaluator hook on first call, keeping imports off the hot path."""

    def _hook(text: str):
        module = import_module(module_name)
        return getattr(module, attribute)(text)

    return _hook


def _default_plugin() -> FormPlugin:
    return FormPlugin(family=GENERIC_FAMILY, enable_body_start=False)


_PLUGINS: dict[str, FormPlugin] = {
    "10-K": FormPlugin(
        family="10-K",
        cover_schema=ANNUAL_CHECKBOX_SCHEMA,
        boundary_signals=_ANNUAL_SIGNALS,
        enable_body_start=True,
        evaluator=_lazy_evaluator(
            "edgar_sec.engine.forms.evaluators.annual", "evaluate_annual"
        ),
        healing_rules=tuple(ANNUAL_PHRASE_RULES),
    ),
    "20-F": FormPlugin(
        family="20-F",
        cover_schema=ANNUAL_CHECKBOX_SCHEMA,
        boundary_signals=_ANNUAL_SIGNALS,
        enable_body_start=True,
        evaluator=_lazy_evaluator(
            "edgar_sec.engine.forms.evaluators.annual", "evaluate_annual"
        ),
        healing_rules=tuple(ANNUAL_PHRASE_RULES),
    ),
    "10-Q": FormPlugin(
        family="10-Q",
        cover_schema=QUARTERLY_CHECKBOX_SCHEMA,
        boundary_signals=_QUARTERLY_SIGNALS,
        enable_body_start=True,
        evaluator=_lazy_evaluator(
            "edgar_sec.engine.forms.evaluators.quarterly", "evaluate_quarterly"
        ),
        healing_rules=tuple(COMMON_PHRASE_RULES),
    ),
    "8-K": FormPlugin(
        family="8-K",
        cover_schema=None,
        boundary_signals=_CURRENT_REPORT_SIGNALS,
        enable_body_start=False,
        evaluator=_lazy_evaluator(
            "edgar_sec.engine.forms.evaluators.current_report",
            "evaluate_current_report",
        ),
    ),
}


def register_plugin(family: str, plugin: FormPlugin) -> None:
    """Register or override the plugin for a form family."""
    key = family.strip().upper()
    if not key:
        raise ValueError("form family must be a non-empty string")
    _PLUGINS[key] = plugin


def get_plugin(form: str | None) -> FormPlugin:
    """Resolve the plugin for a raw form string, falling back to the generic one.

    Resolution order: exact alias, then the suffix-stripped form, then an exact
    match on the raw uppercased string. The middle step is what makes a
    ``register_plugin``-ed family reachable by its amendment forms
    (``S-4/A`` -> ``S-4``), which the alias table cannot know about.

    Anything unmodeled gets the generic plugin rather than raising, so a new
    SEC form type degrades to no cover handling.
    """
    if not form:
        return _default_plugin()
    family = resolve_alias(form)
    if family:
        plugin = _PLUGINS.get(family.upper())
        if plugin is not None:
            return plugin
    stripped = form_family(form).upper()
    plugin = _PLUGINS.get(stripped)
    if plugin is not None:
        return plugin
    return _PLUGINS.get(form.strip().upper(), _default_plugin())


def registered_families() -> tuple[str, ...]:
    """Return the form families that currently have a modeled plugin."""
    return tuple(sorted(_PLUGINS))


__all__ = [
    "get_plugin",
    "register_plugin",
    "registered_families",
]
