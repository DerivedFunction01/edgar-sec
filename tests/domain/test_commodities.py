from __future__ import annotations

from types import MappingProxyType

import pytest

from edgar_sec.domain.commodities import (
    ALL_LEAVES,
    CLASSES,
    CLASS_GROUPS,
    GENERAL_VOCABULARY,
    GROUP_PARENT,
    LEAF_GROUPS,
    LEAVES_BY_CLASS,
    PARKED_LEAVES,
)


def test_taxonomy_shape() -> None:
    # The eight agreed classes plus seafood, seated per adoption D1.
    assert CLASSES == (
        "energy",
        "metals",
        "crops",
        "chemicals",
        "livestock",
        "forestry",
        "construction",
        "environmental",
        "seafood",
    )
    assert set(CLASS_GROUPS) == set(CLASSES)
    assert LEAVES_BY_CLASS.keys() == CLASS_GROUPS.keys()
    # Every class's groups and leaves are tuples, never bare strings.
    assert all(isinstance(gs, tuple) for gs in CLASS_GROUPS.values())
    assert all(isinstance(ls, tuple) for ls in LEAVES_BY_CLASS.values())
    # The pre-port catch-all and the old2 generation's names seat no
    # class (D2/D4).
    assert "general" not in CLASSES
    assert "textiles" not in CLASSES
    assert "agriculture" not in CLASSES
    groups = {g for gs in CLASS_GROUPS.values() for g in gs} | set(GROUP_PARENT)
    # A leaf seats in a group, or directly in a class (uranium seats
    # in energy itself in the XBRL graph).
    assert set(LEAF_GROUPS.values()) <= groups | set(CLASSES)
    assert set(GROUP_PARENT.values()) <= groups | set(CLASSES)


def test_leaf_vocabulary_reconciles_with_the_attestation() -> None:
    # 356 leaves were sampled: 206 active by class, 3 general words,
    # 147 parked. Every leaf sits in exactly one place.
    by_class = [leaf for leaves in LEAVES_BY_CLASS.values() for leaf in leaves]
    assert len(by_class) == len(set(by_class)) == 206
    assert len(ALL_LEAVES) == 209
    assert len(PARKED_LEAVES) == 147
    assert not (set(PARKED_LEAVES) & ALL_LEAVES)
    assert GENERAL_VOCABULARY == ("commodity", "raw materials", "textiles")
    assert set(GENERAL_VOCABULARY) <= ALL_LEAVES


def test_parked_leaves_carry_counts_not_verdicts() -> None:
    for parked in PARKED_LEAVES.values():
        assert set(parked) == {"documents", "firms", "category"}
        assert parked["documents"] >= 0
        assert parked["category"] is None or parked["category"] in CLASSES
    # The unattested seafood exotica are parked, not silently dropped
    # and not silently kept as vocabulary.
    assert PARKED_LEAVES["plaice"] == {
        "documents": 1,
        "firms": 1,
        "category": "seafood",
    }
    assert "plaice" not in ALL_LEAVES
    assert PARKED_LEAVES["anchov"]["documents"] == 0
    assert PARKED_LEAVES["abalone"] == {
        "documents": 47,
        "firms": 11,
        "category": "seafood",
    }


def test_no_prior_codes_are_imported() -> None:
    # D7: pre-port CP means commodity price; the XBRL risk vocabulary
    # maps CP to credit. Full names only, so no code can be imported.
    names = set(CLASSES) | {g for gs in CLASS_GROUPS.values() for g in gs}
    assert "cp" not in names
    assert "cm" not in names
    assert all(len(name) > 2 for name in names)


def test_vocabulary_is_immutable() -> None:
    assert isinstance(LEAVES_BY_CLASS, MappingProxyType)
    assert isinstance(PARKED_LEAVES, MappingProxyType)
    with pytest.raises(TypeError):
        LEAVES_BY_CLASS["energy"] = ()  # type: ignore[index]
