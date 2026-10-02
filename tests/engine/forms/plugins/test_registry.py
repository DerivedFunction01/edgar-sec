"""Contract tests for form-family plugin resolution and registration."""

from __future__ import annotations

import pytest

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
from edgar_sec.engine.forms.plugins.registry import (
    _PLUGINS,
    get_plugin,
    register_plugin,
    registered_families,
)


@pytest.fixture
def restored_registry():
    """Restore the process-global plugin table around an overriding test."""
    saved = dict(_PLUGINS)
    try:
        yield
    finally:
        _PLUGINS.clear()
        _PLUGINS.update(saved)


def test_annual_family_enables_both_gated_stages() -> None:
    plugin = get_plugin("10-K")
    assert plugin.family == "10-K"
    assert plugin.enable_toc is True
    assert plugin.enable_body_start is True
    assert plugin.evaluator is evaluate_annual


def test_twenty_f_is_annual_for_normalization_and_generic_for_triage() -> None:
    """v1's ``get_evaluator`` had no 20-F branch.

    ``AnnualEvaluator``'s own docstring claims 20-F, but ``get_evaluator``
    compared the resolved family against ``10-K``, ``10-Q``, and ``8-K`` only,
    so a 20-F filing was normalized as annual and triaged as generic: an
    Exhibit 13 delegation in a foreign annual report was never detected as a
    stub. Preserved here so stored behaviour does not change under the port.
    """
    plugin = get_plugin("20-F")
    assert plugin.family == "20-F"
    assert plugin.enable_toc is True
    assert plugin.enable_body_start is True
    assert plugin.evaluator is evaluate_generic
    assert plugin.evaluator(
        "is incorporated by reference into Exhibit 13."
    ).category == ("standard_full")


def test_quarterly_resolves_a_body_root_but_cuts_no_toc() -> None:
    plugin = get_plugin("10-Q")
    assert plugin.family == "10-Q"
    assert plugin.enable_toc is False
    assert plugin.enable_body_start is True
    assert plugin.evaluator is evaluate_quarterly


def test_current_report_gates_both_stages_off() -> None:
    plugin = get_plugin("8-K")
    assert plugin.family == "8-K"
    assert plugin.enable_toc is False
    assert plugin.enable_body_start is False
    assert plugin.evaluator is evaluate_current_report


@pytest.mark.parametrize(
    "form",
    ["10-K/A", "10-K405", "10-K405/A", "10-KSB", "10-KT", "10KSB40", "  10-k  "],
)
def test_every_annual_alias_resolves_to_the_annual_plugin(form: str) -> None:
    plugin = get_plugin(form)
    assert plugin.family == "10-K"
    assert plugin.enable_toc is True


@pytest.mark.parametrize("form", ["10-Q/A", "10-QSB", "10-QT", "10QSB"])
def test_every_quarterly_alias_resolves_to_the_quarterly_plugin(form: str) -> None:
    assert get_plugin(form).family == "10-Q"


@pytest.mark.parametrize("form", ["8-K/A", "8-K12B", "8-K12G3", "8-K15D5"])
def test_every_current_report_alias_resolves_to_the_8k_plugin(form: str) -> None:
    assert get_plugin(form).family == "8-K"


def test_an_amendment_and_its_original_resolve_to_one_plugin() -> None:
    """``10-K405`` contains ``10-K`` as a substring and must not be tested as one."""
    assert get_plugin("10-K405") is get_plugin("10-K")
    assert get_plugin("10-Q/A") is get_plugin("10-Q")
    assert get_plugin("10-K405") is not get_plugin("10-Q")


def test_unmodelled_families_and_unknown_forms_get_the_generic_plugin() -> None:
    for form in (None, "", "   ", "6-K", "6-K/A", "S-1", "DEF 14A", "424B5", "/A"):
        assert get_plugin(form).family == GENERIC_FAMILY
        assert get_plugin(form).evaluator is evaluate_generic


def test_the_generic_plugin_is_one_shared_instance() -> None:
    assert get_plugin(None) is get_plugin("S-1")


def test_resolution_returns_the_same_instance_every_time() -> None:
    assert get_plugin("10-K") is get_plugin("10-K")
    assert get_plugin("10-K") is not get_plugin("20-F")


def test_registered_families_lists_the_seeded_families_only() -> None:
    assert registered_families() == ("10-K", "10-Q", "20-F", "8-K")


def test_register_plugin_overrides_a_family_process_globally(
    restored_registry: None,
) -> None:
    replacement = FormPlugin(family="10-K", enable_toc=True)
    register_plugin("10-k", replacement)
    assert get_plugin("10-K") is replacement
    assert get_plugin("10-K405") is replacement
    assert registered_families() == ("10-K", "10-Q", "20-F", "8-K")


def test_register_plugin_keys_are_stripped_and_upper_cased(
    restored_registry: None,
) -> None:
    replacement = FormPlugin(family="S-1")
    register_plugin("  s-1  ", replacement)
    assert "S-1" in registered_families()
    assert get_plugin("S-1") is replacement


def test_register_plugin_cannot_override_a_shadowed_alias_key(
    restored_registry: None,
) -> None:
    """v1's second lookup is unreachable for any form that resolves to a family.

    ``10-K405`` resolves to ``10-K``, so the seeded entry answers before the
    raw-string table is consulted and an override registered under the alias is
    dead. Preserved from v1 and pinned here so a caller does not adopt it.
    """
    replacement = FormPlugin(family="10-K", enable_toc=False)
    register_plugin("10-K405", replacement)
    assert get_plugin("10-K405") is get_plugin("10-K")
    assert get_plugin("10-K405").enable_toc is True


def test_register_plugin_registers_a_form_the_alias_table_does_not_know(
    restored_registry: None,
) -> None:
    """The raw-string lookup matches the whole input, not a collapsed form.

    ``s-1/A`` collapses to ``S-1`` under the alias table but is not itself a
    registry key, so a plugin registered for a form the alias table does not
    know answers only that literal spelling.
    """
    replacement = FormPlugin(family="S-1")
    register_plugin("S-1", replacement)
    assert get_plugin("S-1") is replacement
    assert get_plugin("s-1") is replacement
    assert get_plugin("s-1/A").family == GENERIC_FAMILY


def test_a_registered_plugin_may_carry_no_evaluator(
    restored_registry: None,
) -> None:
    register_plugin("40-F", FormPlugin(family="40-F"))
    plugin = get_plugin("40-F")
    assert plugin.evaluator is None
    assert plugin.enable_toc is False
