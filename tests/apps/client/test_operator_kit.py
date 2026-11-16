"""Pins for the shared operator-kit template members: the register factory,
the lazy SPECS getattr, the key-value result (selection's fixed hints), the
field helper, and the token/accession spellings.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace

import pytest

from edgar_sec.apps.client.operator_kit import (
    accession_text,
    help_field,
    key_value_result,
    make_module_getattr,
    make_register,
    split_tokens,
)


def test_help_field_carries_default_and_help() -> None:
    @dataclass
    class _Args:
        mode: str = help_field("standard", "how much to show")

    args = _Args()
    assert args.mode == "standard"
    fields_by_name = {f.name: f for f in _Args.__dataclass_fields__.values()}
    assert fields_by_name["mode"].metadata["help"] == "how much to show"


def test_split_tokens_splits_commas_and_spaces() -> None:
    assert split_tokens("a,b c,,d") == ("a", "b", "c", "d")
    assert split_tokens("") == ()


def test_accession_text_spellings() -> None:
    assert accession_text("0000123-26-000001") == "0000123-26-000001"
    filing = SimpleNamespace(accession=SimpleNamespace(value="0000999-26-000002"))
    assert accession_text(filing) == "0000999-26-000002"
    assert accession_text(SimpleNamespace(accession="0000111-26-000003")) == (
        "0000111-26-000003"
    )


def test_key_value_result_shape() -> None:
    result = key_value_result("Title", {"k": 1}, (("a", "1"), ("b", "2")))
    assert result.kind == "key_value"
    assert result.title == "Title"
    assert result.data == {"k": 1}
    assert result.total == 2
    assert result.shown == 2
    assert [(row.label, row.value) for row in result.components] == [
        ("a", "1"),
        ("b", "2"),
    ]


def test_key_value_result_selection_hints_pin() -> None:
    bound = partial(key_value_result, hints=("vars", "peek"))
    result = bound("Seeded set x", {}, (("a", "1"),))
    assert result.hints == ("vars", "peek")
    assert result.total == 1


def test_make_register_fills_and_returns_the_registry() -> None:
    specs = (SimpleNamespace(id="one"), SimpleNamespace(id="two"))
    register = make_register(lambda: specs)
    registry: dict = {}
    returned = register(registry)
    assert returned is registry
    assert registry == {"one": specs[0], "two": specs[1]}


def test_make_module_getattr_serves_specs_and_names_the_module() -> None:
    getattr_ = make_module_getattr(lambda: ("spec",), "some.module")
    assert getattr_("SPECS") == ("spec",)
    with pytest.raises(AttributeError) as excinfo:
        getattr_("OTHER")
    assert "'some.module'" in str(excinfo.value)
    assert "'OTHER'" in str(excinfo.value)
