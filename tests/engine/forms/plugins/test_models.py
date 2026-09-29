"""Tests for the form plugin contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from edgar_sec.domain.forms.schemas import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.engine.forms.cover.models import BoundarySignal
from edgar_sec.engine.forms.plugins.models import (
    GENERIC_FAMILY,
    FormPlugin,
)


def test_defaults_are_minimal() -> None:
    plugin = FormPlugin(family="S-1")
    assert plugin.cover_schema is None
    assert plugin.boundary_signals == ()
    assert plugin.enable_body_start is True
    assert plugin.transform_content is None
    assert plugin.evaluator is None


def test_plugin_is_immutable() -> None:
    plugin = FormPlugin(family="10-K")
    with pytest.raises(FrozenInstanceError):
        plugin.family = "other"  # type: ignore[misc]


def test_data_and_hooks_are_carried() -> None:
    plugin = FormPlugin(
        family="10-K",
        cover_schema=ANNUAL_CHECKBOX_SCHEMA,
        boundary_signals=(BoundarySignal.PAGE_MARKERS,),
        enable_body_start=False,
        transform_content=lambda text: text.upper(),
        evaluator=lambda text: None,  # type: ignore[arg-type,return-value]
    )
    assert plugin.cover_schema is ANNUAL_CHECKBOX_SCHEMA
    assert plugin.enable_body_start is False
    assert plugin.transform_content is not None
    assert plugin.transform_content("ab") == "AB"
    assert plugin.evaluator is not None


def test_generic_family_constant() -> None:
    assert GENERIC_FAMILY == "GENERIC"
