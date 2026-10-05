"""Form-family plugin registry and its resolution function. 10-K, 10-Q, 8-K, and 20-F
are modelled; everything else resolves to one generic plugin that stages nothing.
Resolution goes through `resolve_alias` and nothing else.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.engine.forms.plugins.base import (
    GENERIC_FAMILY,
    FormPlugin,
    evaluate_generic,
)
from edgar_sec.engine.forms.plugins.evaluators.annual import evaluate_annual
from edgar_sec.engine.forms.plugins.evaluators.current import evaluate_current
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
        evaluator=evaluate_current,
    ),
}

_FALLBACK_PLUGIN = FormPlugin(family=GENERIC_FAMILY, evaluator=evaluate_generic)


def register_plugin(family: str, plugin: FormPlugin) -> None:
    """Register or override a family's plugin, process-globally. There is no
    unregister, so an overriding caller must restore the previous entry itself.
    """
    _PLUGINS[family.strip().upper()] = plugin


def registered_families() -> tuple[str, ...]:
    """Return the registered family keys, sorted, excluding the fallback."""
    return tuple(sorted(_PLUGINS))


def get_plugin(form: str | None) -> FormPlugin:
    """Resolve the plugin for a raw form string. An unmodelled family (`6-K`, an unknown
    form) gets the generic plugin, which stages nothing and always proceeds.
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
