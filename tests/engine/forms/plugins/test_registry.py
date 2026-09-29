"""Tests for the form plugin registry."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.schemas import (
    ANNUAL_CHECKBOX_SCHEMA,
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.engine.forms.plugins.models import GENERIC_FAMILY, FormPlugin
from edgar_sec.engine.forms.plugins.registry import (
    get_plugin,
    register_plugin,
    registered_families,
)


@pytest.mark.parametrize("family", ["10-K", "10-Q", "8-K"])
def test_seeded_families_are_registered(family: str) -> None:
    assert family in registered_families()
    assert get_plugin(family).family == family


def test_seeded_families_include_the_annual_foreign_form() -> None:
    """20-F is the annual foreign-private-issuer form and must be registered.

    The registry previously declared this plugin with ``family="20-K"``, a
    family string the solver's annual branches never test for, so every 20-F
    filing silently fell off the annual path while the annual evaluator was
    still bound to it. The plugin's family and its seeded key must agree, and
    both must be a family the solver recognises as annual.
    """
    assert "20-F" in registered_families()


@pytest.mark.parametrize(
    ("form", "expected_family"), [("20-F", "20-F"), ("20-F/A", "20-F")]
)
def test_20_f_resolves_to_a_family_the_solver_treats_as_annual(
    form: str, expected_family: str
) -> None:
    plugin = get_plugin(form)
    assert plugin.family == expected_family
    assert plugin.family in {"10-K", "20-F"}


def test_no_seeded_plugin_declares_a_family_it_is_not_keyed_under() -> None:
    """A plugin whose family differs from its key falls off every family branch.

    This is the general form of the 20-F defect: the registry is keyed by
    family, so a mismatched ``family=`` field can only be a typo — and here the
    typo is exactly what disconnected the plugin from the solver's family
    tests.
    """
    from edgar_sec.engine.forms.plugins.registry import _PLUGINS

    for key, plugin in _PLUGINS.items():
        assert plugin.family == key, (
            f"plugin keyed {key!r} declares family {plugin.family!r}"
        )


def test_annual_and_quarterly_carry_cover_schemas() -> None:
    assert get_plugin("10-K").cover_schema is ANNUAL_CHECKBOX_SCHEMA
    assert get_plugin("10-Q").cover_schema is QUARTERLY_CHECKBOX_SCHEMA
    assert get_plugin("8-K").cover_schema is None


def test_20_f_shares_the_annual_profile() -> None:
    assert get_plugin("20-F").cover_schema is ANNUAL_CHECKBOX_SCHEMA


def test_body_start_toggle_matches_form_shape() -> None:
    assert get_plugin("10-K").enable_body_start is True
    assert get_plugin("10-Q").enable_body_start is True
    assert get_plugin("8-K").enable_body_start is False


def test_unmodeled_form_falls_back_to_generic() -> None:
    plugin = get_plugin("S-1")
    assert plugin.family == GENERIC_FAMILY
    assert plugin.cover_schema is None
    assert plugin.boundary_signals == ()
    assert plugin.evaluator is None


def test_empty_form_falls_back_to_generic() -> None:
    assert get_plugin(None).family == GENERIC_FAMILY
    assert get_plugin("").family == GENERIC_FAMILY


def test_register_plugin_overrides_a_family() -> None:
    sentinel = FormPlugin(family="S-4", enable_body_start=False)
    register_plugin("S-4", sentinel)
    assert get_plugin("S-4") is sentinel
    assert get_plugin("S-4/A") is sentinel


def test_register_plugin_rejects_empty_family() -> None:
    with pytest.raises(ValueError):
        register_plugin("  ", FormPlugin(family="X"))


def test_boundary_signals_are_declared_per_family() -> None:
    annual = {s.value for s in get_plugin("10-K").boundary_signals}
    current = {s.value for s in get_plugin("8-K").boundary_signals}
    assert "toc_transition" in annual
    assert "toc_transition" not in current
