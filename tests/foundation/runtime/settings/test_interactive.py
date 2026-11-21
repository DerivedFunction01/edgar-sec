"""Interactive pick-list settings: one validated page-size spec, registered once."""

from __future__ import annotations

import pytest

from edgar_sec.foundation.runtime.settings import (
    collect_specs,
    environment_name,
    resolve_settings,
)
from edgar_sec.foundation.runtime.settings.interactive import (
    DEFAULT_PAGE_SIZE,
    get_interactive_specs,
)
from edgar_sec.foundation.runtime.settings.validators import validate_positive_int


def _spec():
    return get_interactive_specs()["interactive"]["page_size"]


def test_the_page_size_default_is_fifteen() -> None:
    assert DEFAULT_PAGE_SIZE == 15


def test_the_page_size_spec_is_typed_and_validated() -> None:
    spec = _spec()
    assert spec.value_type is int
    assert spec.default == DEFAULT_PAGE_SIZE
    assert spec.validate is validate_positive_int
    with pytest.raises(ValueError, match="must be >= 1"):
        spec.validate(0)


def test_the_page_size_spec_is_addressable_from_every_source() -> None:
    spec = _spec()
    assert spec.env and spec.config and spec.cli
    assert environment_name("interactive.page_size") == "INTERACTIVE_PAGE_SIZE"


def test_the_page_size_spec_is_registered() -> None:
    assert collect_specs()["interactive.page_size"].default == DEFAULT_PAGE_SIZE


def test_the_page_size_resolves_through_the_registry() -> None:
    assert resolve_settings(env={})["interactive.page_size"] == DEFAULT_PAGE_SIZE
    env = resolve_settings(env={"INTERACTIVE_PAGE_SIZE": "7"})
    assert env["interactive.page_size"] == 7
    cli = resolve_settings(env={}, cli_overrides={"interactive.page_size": 9})
    assert cli["interactive.page_size"] == 9


def test_the_split_leaves_graph_limit_dag_scoped() -> None:
    specs = collect_specs()
    assert "dag.graph_limit" in specs
    assert "dag.page_size" not in specs
