"""Tests for presumed-coordinate defaults loading and validation."""

import json
from pathlib import Path
import pytest

from edgar_sec.engine.xbrl.taxonomy.defaults import load_default_coordinates
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _write_defaults_taxonomy(
    tmp_path: Path, defaults: list[dict], payable_groups: list[str] | None = None
) -> Path:
    """Write a minimal taxonomy dir whose only variable file is the defaults."""
    heads = [
        {
            "head_id": "H_LIABILITY",
            "head_symbol": "LIABILITY",
            "economic_class": "STOCK",
            "statement_type": "BalanceSheet",
            "normal_balance": "CREDIT",
            "is_dual_role_primitive": 0,
            "description": "Liabilities",
            "recognition_book": "B_BALANCE_SHEET",
            "flow_stock": "STOCK",
            "timing_horizon": "INSTANT",
        }
    ]
    mods = [
        {
            "modifier_id": mid,
            "category": "MATURITY_HORIZON",
            "keywords": [],
            "description": mid,
            "sibling_groups": [group],
        }
        for mid, group in (
            ("M_CURRENT", "MATURITY_HORIZON"),
            ("M_NONCURRENT", "MATURITY_HORIZON"),
        )
    ]
    mods += [
        {
            "modifier_id": mid,
            "category": "IDENTITY",
            "keywords": [],
            "description": mid,
        }
        for mid in ("M_ACCOUNTS_PAYABLE", "M_REALIZED")
    ]
    if payable_groups is not None:
        for mod in mods:
            if mod["modifier_id"] == "M_ACCOUNTS_PAYABLE":
                mod["sibling_groups"] = payable_groups
    lexicon = [
        {
            "phrase": ["Accounts", "Payable"],
            "claim": "head",
            "head": "H_LIABILITY",
            "claim_class": "PRIMARY",
            "carriage": ["M_ACCOUNTS_PAYABLE"],
        }
    ]
    (tmp_path / "prime_heads.json").write_text(json.dumps(heads))
    (tmp_path / "subatomic_modifiers.json").write_text(json.dumps(mods))
    (tmp_path / "token_lexicon.json").write_text(json.dumps(lexicon))
    (tmp_path / "default_coordinates.json").write_text(json.dumps(defaults))
    return tmp_path


def _default_entry(**overrides) -> dict:
    """One valid default-coordinate record, with field overrides applied."""
    entry = {
        "head": "H_LIABILITY",
        "identity_modifiers": ["M_ACCOUNTS_PAYABLE"],
        "axis": "MATURITY_HORIZON",
        "presumed_modifier": "M_CURRENT",
        "rationale": "Usually current.",
        "attestation_class": "corpus",
    }
    entry.update(overrides)
    return entry


def test_default_coordinates_load_from_real_taxonomy() -> None:
    """The shipped defaults table loads with the accounts-payable entry."""
    taxonomy = load_domain_taxonomy()
    assert len(taxonomy.default_coordinates) == 1
    entry = taxonomy.default_coordinates[0]
    assert entry.signature == ("H_LIABILITY", frozenset({"M_ACCOUNTS_PAYABLE"}))
    assert entry.axis == "MATURITY_HORIZON"
    assert entry.presumed_modifier == "M_CURRENT"
    assert entry.attestation_class == "corpus"


def test_load_default_coordinates_roundtrip(tmp_path: Path) -> None:
    """The standalone loader parses records into DefaultCoordinate tuples."""
    path = tmp_path / "default_coordinates.json"
    path.write_text(json.dumps([_default_entry()]))
    loaded = load_default_coordinates(path)
    assert len(loaded) == 1
    assert loaded[0].identity_modifiers == ("M_ACCOUNTS_PAYABLE",)


def test_default_coordinate_validation_rejects_bad_records(tmp_path: Path) -> None:
    """Unknown heads/modifiers, axis mismatches, and duplicates are hard errors."""
    bad_records = [
        _default_entry(head="H_NOPE"),
        _default_entry(presumed_modifier="M_NOPE"),
        _default_entry(axis="EPS_BASIS"),
        _default_entry(identity_modifiers=["M_NOPE"]),
        _default_entry(identity_modifiers=["M_CURRENT"]),
        _default_entry(identity_modifiers=["M_REALIZED"]),
    ]
    for record in bad_records:
        folder = _write_defaults_taxonomy(tmp_path, [record])
        with pytest.raises(ValueError):
            load_domain_taxonomy(folder)
    folder = _write_defaults_taxonomy(tmp_path, [_default_entry(), _default_entry()])
    with pytest.raises(ValueError):
        load_domain_taxonomy(folder)


def test_default_coordinate_validation_accepts_valid_record(tmp_path: Path) -> None:
    """A well-formed record survives taxonomy loading unchanged."""
    folder = _write_defaults_taxonomy(tmp_path, [_default_entry()])
    taxonomy = load_domain_taxonomy(folder)
    assert len(taxonomy.default_coordinates) == 1


def test_identity_declaring_a_different_axis_is_legal(tmp_path: Path) -> None:
    """Multi-membership: an identity in another axis does not block a default."""
    folder = _write_defaults_taxonomy(
        tmp_path, [_default_entry()], payable_groups=["STOCK_CLASS"]
    )
    taxonomy = load_domain_taxonomy(folder)
    assert len(taxonomy.default_coordinates) == 1
