"""Equivalence defaults: presumption and declared sibling-group data."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_pair,
    presumed_atom,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.equivalence_support import _atom, _defaults


def test_via_default_rule_overrides_the_presumed_classification() -> None:
    """A default-mediated NEAR reports via_default, not its presumed rule."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    ranked = rank_equivalents(
        "firm-x:AccountsPayable",
        target,
        (
            ("firm-a:AccountsPayableCurrent", _atom("us-gaap:AccountsPayableCurrent")),
            (
                "firm-b:AccruedLiabilitiesCurrent",
                _atom("us-gaap:AccruedLiabilitiesCurrent"),
            ),
        ),
        defaults,
    )
    rules = {item.qname: item.rule for item in ranked}
    assert rules == {
        "firm-a:AccountsPayableCurrent": "single_modifier_difference",
        "firm-b:AccruedLiabilitiesCurrent": "via_default",
    }
    assert ranked[-1].via_default is True


def test_declared_sibling_groups_reproduce_default_outcomes() -> None:
    """The solver default is the taxonomy declaration itself, not a copy."""
    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
    from edgar_sec.engine.xbrl.solve.equivalence import _resolve_groups
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import load_sibling_groups

    declared = load_sibling_groups(resolve_xbrl_paths().default_sibling_groups_path)
    assert _resolve_groups(None) == declared

    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    candidates = (
        ("firm-a:AccountsPayableCurrent", _atom("us-gaap:AccountsPayableCurrent")),
        (
            "firm-b:AccruedLiabilitiesCurrent",
            _atom("us-gaap:AccruedLiabilitiesCurrent"),
        ),
        ("firm-c:AccountsPayableLongTerm", _atom("us-gaap:AccountsPayableLongTerm")),
    )
    by_default = rank_equivalents(
        "firm-x:AccountsPayable", target, candidates, defaults
    )
    by_declared = rank_equivalents(
        "firm-x:AccountsPayable", target, candidates, defaults, sibling_groups=declared
    )
    assert by_declared == by_default
    assert presumed_atom(target, defaults, sibling_groups=declared) == presumed_atom(
        target, defaults
    )

    afs = _atom(
        "us-gaap:DebtSecuritiesAvailableForSaleMaturityAfter10YearsWeightedAverageYield"
    )
    htm = _atom(
        "us-gaap:DebtSecuritiesHeldToMaturityMaturityAfter10YearsWeightedAverageYield"
    )
    swapped = rank_equivalents(
        "firm-x:Afs", afs, (("firm-a:Htm", htm),), sibling_groups=declared
    )
    assert swapped[0].tier == NEAR and swapped[0].rule == "sibling_swap"


def test_sibling_group_matches_subatomic_data() -> None:
    """Def memberships and the declared groups table agree."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

    paths = resolve_xbrl_paths()
    defs = json.loads(paths.default_subatomic_modifiers_path.read_text())
    table = json.loads(paths.default_sibling_groups_path.read_text())
    declared = {
        (d["modifier_id"], group) for d in defs for group in d.get("sibling_groups", ())
    }
    tabled = {(member, g["group"]) for g in table for member in g["members"]}
    assert declared == tabled


def test_default_coordinates_match_subatomic_data() -> None:
    """Default entries mirror the data: the axis is among the def's groups."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

    defs = json.loads(resolve_xbrl_paths().default_subatomic_modifiers_path.read_text())
    by_id = {d["modifier_id"]: d for d in defs}
    tax = load_domain_taxonomy()
    signatures = set()
    axes = set()
    for entry in tax.default_coordinates:
        assert entry.axis in by_id[entry.presumed_modifier].get("sibling_groups", [])
        group_members = {
            d["modifier_id"] for d in defs if entry.axis in d.get("sibling_groups", [])
        }
        assert len(group_members) >= 2
        assert entry.signature not in signatures
        signatures.add(entry.signature)
        axes.add(entry.axis)
    assert axes == {"MATURITY_HORIZON"}


def _defaults():
    """The shipped defaults table, loaded through the domain taxonomy."""
    return load_domain_taxonomy().default_coordinates


def test_presumed_atom_applies_only_to_a_silent_signature() -> None:
    """Presumption fires on the bare identity and nowhere else."""
    defaults = _defaults()
    bare = _atom("us-gaap:AccountsPayable")
    assert presumed_atom(bare, defaults).modifiers == {
        "M_ACCOUNTS_PAYABLE",
        "M_CURRENT",
    }
    for stated in (
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableNoncurrent",
        "us-gaap:AccountsPayableCurrentAndNoncurrent",
    ):
        atom = _atom(stated)
        assert presumed_atom(atom, defaults) == atom
    compound = _atom("us-gaap:AccountsPayableAndOtherAccruedLiabilities")
    assert presumed_atom(compound, defaults) == compound
    debt = Atom("H_LIABILITY", frozenset({"M_DEBT"}))
    assert presumed_atom(debt, defaults) == debt


def test_bare_payable_ranks_current_first_and_long_term_after() -> None:
    """For a bare AP target the presumed-current match leads the near set."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    candidates = (
        ("firm-a:AccountsPayableLongTerm", _atom("firm-a:AccountsPayableLongTerm")),
        ("firm-b:AccountsPayableCurrent", _atom("firm-b:AccountsPayableCurrent")),
        ("firm-c:AccountsPayable", _atom("firm-c:AccountsPayable")),
    )
    ranked = rank_equivalents("firm-x:AccountsPayable", target, candidates, defaults)
    assert [item.qname for item in ranked] == [
        "firm-c:AccountsPayable",
        "firm-b:AccountsPayableCurrent",
        "firm-a:AccountsPayableLongTerm",
    ]
    assert [item.tier for item in ranked] == [EXACT, NEAR, NEAR]
    assert not any(item.via_default for item in ranked)
    assert ranked[1].modifier_distance == 0
    assert ranked[2].modifier_distance == 2


def test_default_mediated_match_is_flagged_and_ranked_last() -> None:
    """Bare AP reaches accrued-current only under presumption: via_default."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    current = _atom("us-gaap:AccountsPayableCurrent")
    assert classify_pair(target, accrued) == UNRELATED
    ranked = rank_equivalents(
        "firm-x:AccountsPayable",
        target,
        (
            ("firm-a:AccruedLiabilitiesCurrent", accrued),
            ("firm-b:AccountsPayableCurrent", current),
        ),
        defaults,
    )
    assert [item.qname for item in ranked] == [
        "firm-b:AccountsPayableCurrent",
        "firm-a:AccruedLiabilitiesCurrent",
    ]
    assert ranked[0].via_default is False
    assert ranked[1].tier == NEAR and ranked[1].via_default is True


def test_explicit_horizon_swap_is_never_default_mediated() -> None:
    """LongTerm vs Current is an evidenced sibling swap, defaults or not."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayableLongTerm")
    candidate = _atom("us-gaap:AccountsPayableCurrent")
    ranked = rank_equivalents(
        "firm-x:AccountsPayableLongTerm",
        target,
        (("firm-a:AccountsPayableCurrent", candidate),),
        defaults,
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].via_default is False


def test_anticipated_noncurrent_payable_is_exact_and_default_proof() -> None:
    """The unattested LiabilitiesLongTerm name: exact kin, default-proof."""
    defaults = _defaults()
    anticipated = _atom("us-gaap:AccountsPayableLiabilitiesLongTerm")
    assert (
        classify_pair(anticipated, _atom("us-gaap:AccountsPayableNoncurrent")) == EXACT
    )
    assert classify_pair(anticipated, _atom("us-gaap:AccountsPayableLongTerm")) == EXACT
    assert presumed_atom(anticipated, defaults) == anticipated
    bare = _atom("us-gaap:AccountsPayable")
    assert classify_pair(anticipated, bare) == NEAR
    ranked = rank_equivalents(
        "us-gaap:AccountsPayableLiabilitiesLongTerm",
        anticipated,
        (
            ("firm-a:AccountsPayable", bare),
            ("firm-b:AccountsPayableCurrent", _atom("firm-b:AccountsPayableCurrent")),
        ),
        defaults,
    )
    assert [item.tier for item in ranked] == [NEAR, NEAR]
    assert not any(item.via_default for item in ranked)


def test_identity_without_default_stays_equidistant() -> None:
    """Bare debt has no default: both horizon portions rank at distance one."""
    defaults = _defaults()
    target = Atom("H_LIABILITY", frozenset({"M_DEBT"}))
    candidates = (
        ("firm-a:DebtCurrent", Atom("H_LIABILITY", frozenset({"M_DEBT", "M_CURRENT"}))),
        (
            "firm-b:DebtNoncurrent",
            Atom("H_LIABILITY", frozenset({"M_DEBT", "M_NONCURRENT"})),
        ),
    )
    ranked = rank_equivalents("firm-x:Debt", target, candidates, defaults)
    assert [item.tier for item in ranked] == [NEAR, NEAR]
    assert [item.modifier_distance for item in ranked] == [1, 1]
    assert not any(item.via_default for item in ranked)


def test_dual_horizon_names_suppress_defaults_and_are_not_swaps() -> None:
    """Dual-horizon atoms are explicit evidence against each single sibling."""
    defaults = _defaults()
    dual = _atom("us-gaap:AccountsPayableCurrentAndNoncurrent")
    assert presumed_atom(dual, defaults) == dual
    for sibling in (
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableNoncurrent",
    ):
        assert classify_pair(dual, _atom(sibling)) == NEAR
    portion = _atom("us-gaap:LongTermDebtCurrent")
    assert presumed_atom(portion, defaults) == portion
    assert classify_pair(portion, _atom("us-gaap:DebtCurrent")) == NEAR
