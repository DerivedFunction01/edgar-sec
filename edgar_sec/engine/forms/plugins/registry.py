"""Form-family plugin registry and its resolution function.

Four primary families are modelled (10-K, 10-Q, 8-K, 20-F) and everything else
resolves to one generic plugin. Per-family pipeline flags gate stages: an annual
report cuts out its table of contents and resolves a body root, a quarterly
report resolves a body root without TOC cut, and an 8-K gets neither.

Resolution goes through `resolve_alias` and nothing else. The alias table is the
single canonical authority that maps form variants (e.g. 10KSB, 10-K/A) to their
underlying family key.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.engine.forms.plugins.base import (
    GENERIC_FAMILY,
    FormPlugin,
    evaluate_generic,
)
from edgar_sec.engine.forms.plugins.evaluators.annual import evaluate_annual
from edgar_sec.engine.forms.plugins.evaluators.current_report import (
    evaluate_current_report,
)
from edgar_sec.engine.forms.plugins.evaluators.quarterly import evaluate_quarterly

_PLUGINS: dict[str, FormPlugin] = {
    "10-K": FormPlugin(
        family="10-K",
        enable_toc=True,
        enable_body_start=True,
        evaluator=evaluate_annual,
    ),
    "20-F": FormPlugin(
        family="20-F",
        enable_toc=True,
        enable_body_start=True,
        evaluator=evaluate_generic,
    ),
    "10-Q": FormPlugin(
        family="10-Q",
        enable_body_start=True,
        evaluator=evaluate_quarterly,
    ),
    "8-K": FormPlugin(
        family="8-K",
        evaluator=evaluate_current_report,
    ),
}

_FALLBACK_PLUGIN = FormPlugin(family=GENERIC_FAMILY, evaluator=evaluate_generic)


def register_plugin(family: str, plugin: FormPlugin) -> None:
    """Register or override the plugin for a family, process-globally.

    The table is module state, so the effect outlives the call and is visible to
    every thread and every later resolution; there is no unregister, and a test
    that overrides a family has to restore the previous entry itself. The key is
    stripped and upper-cased so registration is spelled the way callers pass
    form strings.

    An override registered for a raw form string that resolves to a seeded family
    is shadowed and has no effect: resolution consults the family first and
    returns before the raw-string table is read.
    """
    _PLUGINS[family.strip().upper()] = plugin


def registered_families() -> tuple[str, ...]:
    """Return the registered family keys, sorted, excluding the fallback."""
    return tuple(sorted(_PLUGINS))


def get_plugin(form: str | None) -> FormPlugin:
    """Resolve the plugin for a raw form string.

    A form string that resolves to no modelled family — an unknown form, or a
    modelled family with no pipeline of its own such as ``6-K`` — gets the
    generic plugin, which stages nothing and always proceeds.
    """
    if not form:
        return _FALLBACK_PLUGIN

    family = resolve_alias(form)
    if family is not None:
        plugin = _PLUGINS.get(family.upper())
        if plugin is not None:
            return plugin

    return _PLUGINS.get(form.strip().upper(), _FALLBACK_PLUGIN)


__all__ = [
    "get_plugin",
    "register_plugin",
    "registered_families",
]
