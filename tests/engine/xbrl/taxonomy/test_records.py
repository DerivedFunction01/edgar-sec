"""Tests for declared movement valence data and its lookup."""

import pytest

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.engine.xbrl.taxonomy.records import load_valences


def _taxonomy() -> DomainTaxonomy:
    paths = resolve_xbrl_paths()
    return DomainTaxonomy(
        prime_heads=(),
        subatomic_modifiers=(),
        valences=load_valences(paths.default_valence_path),
    )


def test_valence_records_are_signed_units_without_duplicates() -> None:
    """Every record carries a unit sign and a unique scope/role/side key."""
    records = _taxonomy().valences
    assert records
    keys = [(r.scope, r.role, r.side) for r in records]
    assert len(keys) == len(set(keys))
    assert all(r.sign in (-1.0, 1.0) for r in records)
    assert {r.scope for r in records} == {
        "level3",
        "pension",
        "equity",
        "debt_total",
        "cash_change_including_fx",
    }


def test_movement_sign_side_specific_beats_generic() -> None:
    """Level-3 gains flip on a liability balance and not on an asset."""
    taxonomy = _taxonomy()
    assert taxonomy.movement_sign("level3", "gains_earnings", "liability") == -1.0
    assert taxonomy.movement_sign("level3", "gains_earnings", "asset") == 1.0
    assert taxonomy.movement_sign("level3", "sales") == -1.0


def test_movement_sign_pension_and_equity_roles() -> None:
    """Pension negatives are side-scoped; equity signs are role-only."""
    taxonomy = _taxonomy()
    assert taxonomy.movement_sign("pension", "benefits_paid", "assets") == -1.0
    assert taxonomy.movement_sign("pension", "service_cost", "obligation") == 1.0
    assert taxonomy.movement_sign("pension", "actuarial", "obligation") == -1.0
    assert taxonomy.movement_sign("equity", "dividends") == -1.0
    assert taxonomy.movement_sign("equity", "issuance") == 1.0


def test_movement_sign_undeclared_role_raises() -> None:
    """An undeclared role is a data gap, never a silent positive."""
    taxonomy = _taxonomy()
    with pytest.raises(KeyError):
        taxonomy.movement_sign("pension", "actuarial", "assets")
    with pytest.raises(KeyError):
        taxonomy.movement_sign("equity", "no_such_role")


def test_composition_scopes_declare_their_roles_in_order() -> None:
    """The two fallback identities are declared as composition scopes."""
    taxonomy = _taxonomy()
    assert taxonomy.composition_roles("debt_total") == ("current", "noncurrent")
    assert taxonomy.composition_roles("cash_change_including_fx") == (
        "change_excluding_fx",
        "fx_effect",
    )
    assert taxonomy.movement_sign("debt_total", "current") == 1.0
    assert taxonomy.composition_roles("no_such_scope") == ()
