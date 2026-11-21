"""Equivalence barriers: typed-coordinate barriers and filing-local rungs."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_ladder_pair,
    classify_pair,
    coordinate_diff,
    presumed_atom,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.concepts.equivalence_support import (
    _atom,
    _defaults,
    _presumed_ladder,
    _typed_atom,
)


def test_text_barrier_kills_a_false_exact() -> None:
    """Typed text vs a bare numeric atom: UNRELATED where untyped was NEAR."""
    text = _typed_atom(
        "all:CapitalStructureDisclosureTextBlock", "dtr-types:textBlockItemType"
    )
    numeric = _atom("adm:Biodieseltaxcredit")
    assert text == Atom("H_UNKNOWN", frozenset({"M_TEXT_NODE"}))
    assert numeric == Atom("H_UNKNOWN")
    assert (
        classify_pair(_atom("all:CapitalStructureDisclosureTextBlock"), numeric) == NEAR
    )
    assert classify_pair(text, numeric) == UNRELATED
    assert classify_pair(numeric, text) == UNRELATED


def test_text_barrier_rule_shapes() -> None:
    """One-modifier difference and subsumption shapes both hit the barrier."""
    text = Atom("H_DISCLOSURE", frozenset({"M_TEXT_NODE"}))
    bare = Atom("H_DISCLOSURE")
    assert classify_pair(text, bare) == UNRELATED
    wider_text = Atom("H_DISCLOSURE", frozenset({"M_TEXT_NODE", "M_SEGMENT"}))
    assert wider_text.is_a(bare)
    assert classify_pair(wider_text, bare) == UNRELATED


def test_percent_barrier_rule_shapes() -> None:
    """One-modifier difference and subsumption shapes both hit the barrier."""
    typed = Atom("H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER", "M_PERCENT_TYPED"}))
    bare = Atom("H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER"}))
    assert classify_pair(typed, bare) == UNRELATED
    assert classify_pair(bare, typed) == UNRELATED
    wider_typed = Atom(
        "H_REVENUE",
        frozenset({"M_CONTRACT_CUSTOMER", "M_PERCENT_TYPED", "M_TAX"}),
    )
    assert wider_typed.is_a(bare)
    assert classify_pair(wider_typed, bare) == UNRELATED
    result = classify_ladder_pair(bare, typed)
    assert result.tier == UNRELATED and result.rule == "percent_barrier"


def test_percent_pairs_classify_by_the_ordinary_rules() -> None:
    """Percent↔percent: the coordinate cancels; the lattice still applies."""
    hon = _typed_atom(
        "hon:RevenueFromContractWithCustomerPercentage", "dtr-types1:percentItemType"
    )
    assert "M_PERCENT_TYPED" in hon.modifiers
    base = Atom("H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER", "M_PERCENT_TYPED"}))
    wider = Atom(
        "H_REVENUE",
        frozenset({"M_CONTRACT_CUSTOMER", "M_PERCENT_TYPED", "M_TAX"}),
    )
    assert classify_pair(base, wider) == NEAR


def test_name_claimed_percent_alone_raises_no_barrier() -> None:
    """The barrier reads the typed coordinate, never the name-claimed one."""
    monetary = Atom("H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER"}))
    named = Atom("H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER", "M_PERCENT"}))
    assert classify_pair(monetary, named) == NEAR


def test_text_pairs_classify_by_the_ordinary_rules() -> None:
    """Text↔text: the coordinate cancels; renamed policy notes still match."""
    pld = _typed_atom(
        "pld:NoncontrollingInterestsPolicyTextBlock", "dtr-types:textBlockItemType"
    )
    tsla = _typed_atom(
        "tsla:NoncontrollingInterestsPolicyTextBlock", "dtr-types1:textBlockItemType"
    )
    assert "M_TEXT_NODE" in pld.modifiers and "M_TEXT_NODE" in tsla.modifiers
    assert classify_pair(pld, tsla) == EXACT
    cycle = _typed_atom(
        "ba:OperatingCyclePolicyTextBlock", "dtr-types1:textBlockItemType"
    )
    structure = _typed_atom(
        "all:CapitalStructureDisclosureTextBlock", "dtr-types:textBlockItemType"
    )
    assert classify_pair(cycle, structure) == NEAR


def test_text_coordinate_never_enters_presumption() -> None:
    """No default signature names the coordinate; presumption leaves it alone."""
    tax = load_domain_taxonomy()
    for entry in tax.default_coordinates:
        assert "M_TEXT_NODE" not in entry.identity_modifiers
        assert entry.presumed_modifier != "M_TEXT_NODE"
    groups = tuple(tax.sibling_groups) or None
    for entry in tax.default_coordinates:
        text_atom = Atom(
            entry.head, frozenset(entry.identity_modifiers) | {"M_TEXT_NODE"}
        )
        assert presumed_atom(text_atom, tax.default_coordinates, groups) == text_atom


def _presumed_ladder(atom: Atom, derived: str | None, placement: str | None) -> Atom:
    """Full ladder composition: filing-local rung, then the global default."""
    from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
        presumed_atom_filing_local,
    )

    return presumed_atom(
        presumed_atom_filing_local(atom, derived, placement), _defaults()
    )


def test_filing_local_silent_placement_keeps_default() -> None:
    """AP regression, silent placement: presumption is exactly today's."""
    bare = _atom("us-gaap:AccountsPayable")
    assert _presumed_ladder(bare, None, None) == presumed_atom(bare, _defaults())
    assert _presumed_ladder(bare, None, None).modifiers == {
        "M_ACCOUNTS_PAYABLE",
        "M_CURRENT",
    }
    target = _atom("us-gaap:AccruedLiabilitiesCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        target,
        (("firm-a:AccountsPayable", bare),),
        _defaults(),
        placement_horizons={"firm-a:AccountsPayable": None},
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].rule == "via_default"
    assert ranked[0].via_default and not ranked[0].via_filing_local
    assert ranked[0].modifier_distance == 2


def test_filing_local_speaks_current_flags_provenance() -> None:
    """AP regression, placement current: same verdict, via_filing_local."""
    bare = _atom("us-gaap:AccountsPayable")
    target = _atom("us-gaap:AccruedLiabilitiesCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        target,
        (("firm-a:AccountsPayable", bare),),
        _defaults(),
        placement_horizons={"firm-a:AccountsPayable": "M_CURRENT"},
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].rule == "via_filing_local"
    assert ranked[0].via_filing_local and not ranked[0].via_default
    assert ranked[0].modifier_distance == 2


def test_filing_local_speaks_noncurrent_outranks_default() -> None:
    """AP regression, placement noncurrent: the default is outranked."""
    bare = _atom("us-gaap:AccountsPayable")
    assert _presumed_ladder(bare, None, "M_NONCURRENT").modifiers == {
        "M_ACCOUNTS_PAYABLE",
        "M_NONCURRENT",
    }
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        accrued,
        (("firm-a:AccountsPayable", bare),),
        _defaults(),
        placement_horizons={"firm-a:AccountsPayable": "M_NONCURRENT"},
    )
    assert ranked == ()
    noncurrent = _atom("us-gaap:AccountsPayableNoncurrent")
    ranked = rank_equivalents(
        "firm-x:AccountsPayableNoncurrent",
        noncurrent,
        (
            ("firm-a:AccountsPayable", bare),
            ("firm-b:AccountsPayable", bare),
        ),
        _defaults(),
        placement_horizons={
            "firm-a:AccountsPayable": "M_NONCURRENT",
            "firm-b:AccountsPayable": None,
        },
    )
    assert [item.qname for item in ranked] == [
        "firm-a:AccountsPayable",
        "firm-b:AccountsPayable",
    ]
    assert [item.modifier_distance for item in ranked] == [0, 2]
    assert all(item.tier == NEAR for item in ranked)


def test_filing_local_name_speaks_evidence_not_consulted() -> None:
    """AP regression, name speaks: contradictory placement changes nothing."""
    from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
        presumed_atom_filing_local,
    )

    for stated, contradictory in (
        ("us-gaap:AccountsPayableCurrent", "M_NONCURRENT"),
        ("us-gaap:AccountsPayableNoncurrent", "M_CURRENT"),
        ("us-gaap:AccountsPayableCurrentAndNoncurrent", "M_CURRENT"),
    ):
        atom = _atom(stated)
        assert presumed_atom_filing_local(atom, None, contradictory) == atom
    current = _atom("us-gaap:AccountsPayableCurrent")
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        accrued,
        (("firm-a:AccountsPayableCurrent", current),),
        _defaults(),
        placement_horizons={"firm-a:AccountsPayableCurrent": "M_NONCURRENT"},
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"
    assert not ranked[0].via_default and not ranked[0].via_filing_local


def test_filing_local_derived_horizon_outranks_placement() -> None:
    """Derived rung stands: placement neither overrides nor mediates."""
    from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
        presumed_atom_filing_local,
    )

    bare = _atom("us-gaap:AccountsPayable")
    assert presumed_atom_filing_local(bare, "M_CURRENT", "M_NONCURRENT") == bare
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        accrued,
        (("firm-a:AccountsPayable", bare),),
        _defaults(),
        derived_horizons={"firm-a:AccountsPayable": "M_CURRENT"},
        placement_horizons={"firm-a:AccountsPayable": "M_NONCURRENT"},
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"
    assert not ranked[0].via_default and not ranked[0].via_filing_local
    assert ranked[0].modifier_distance == 2


def test_filing_local_sort_order_is_ladder_order() -> None:
    """Evidenced NEAR, then filing-local NEAR, then default-mediated NEAR."""
    target = _atom("us-gaap:AccruedLiabilitiesCurrent")
    bare = _atom("us-gaap:AccountsPayable")
    current = _atom("us-gaap:AccountsPayableCurrent")
    ranked = rank_equivalents(
        "firm-x:AccruedLiabilitiesCurrent",
        target,
        (
            ("firm-c:AccountsPayable", bare),
            ("firm-a:AccountsPayableCurrent", current),
            ("firm-b:AccountsPayable", bare),
        ),
        _defaults(),
        placement_horizons={"firm-b:AccountsPayable": "M_CURRENT"},
    )
    assert [item.qname for item in ranked] == [
        "firm-a:AccountsPayableCurrent",
        "firm-b:AccountsPayable",
        "firm-c:AccountsPayable",
    ]
    assert [item.rule for item in ranked] == [
        "sibling_swap",
        "via_filing_local",
        "via_default",
    ]


def test_coordinate_diff_reports_modifier_sides() -> None:
    """Diff lists each side's own modifiers, sorted, with no swap named."""
    target = Atom("H_REVENUE")
    candidate = Atom("H_REVENUE", frozenset({"M_TAX", "M_CONTRACT_CUSTOMER"}))
    diff = coordinate_diff(target, candidate, "subsumption")
    assert diff.target_only == ()
    assert diff.candidate_only == ("M_CONTRACT_CUSTOMER", "M_TAX")
    assert diff.swapped is None


def test_coordinate_diff_names_sibling_swap_pair() -> None:
    """Only the sibling_swap rule names a swapped (target, candidate) pair."""
    target = Atom("H_ASSET", frozenset({"M_CURRENT"}))
    candidate = Atom("H_ASSET", frozenset({"M_NONCURRENT"}))
    diff = coordinate_diff(target, candidate, "sibling_swap")
    assert diff.target_only == ("M_CURRENT",)
    assert diff.candidate_only == ("M_NONCURRENT",)
    assert diff.swapped == ("M_CURRENT", "M_NONCURRENT")
    assert coordinate_diff(target, candidate, "subsumption").swapped is None
