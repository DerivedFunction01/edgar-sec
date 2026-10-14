"""Unit tests for Atom sub-atomic coordinates and subsumption lattice algebra."""

from edgar_sec.engine.xbrl.atoms import (
    Atom,
    prune_specialized,
    prune_subsumed,
)


def test_atom_normalization_and_equality() -> None:
    """Verify case normalization, head prefixing, and set equality."""
    a1 = Atom("revenue", frozenset(["m_sales_goods", "v_net"]))
    a2 = Atom("H_REVENUE", frozenset(["M_SALES_GOODS", "V_NET"]))
    assert a1 == a2
    assert a1.head == "H_REVENUE"
    assert a1.modifiers == frozenset({"M_SALES_GOODS", "V_NET"})


def test_atom_is_a_and_subsumption_lattice() -> None:
    """Verify subset lattice ordering: more modifiers implies subtype."""
    general_rev = Atom("H_REVENUE")
    real_estate_rev = Atom("H_REVENUE", frozenset(["M_REAL_ESTATE"]))
    real_estate_rev_net = Atom("H_REVENUE", frozenset(["M_REAL_ESTATE", "V_NET"]))

    assert real_estate_rev.is_a(general_rev)
    assert real_estate_rev_net.is_a(real_estate_rev)
    assert real_estate_rev_net.is_a(general_rev)

    assert not general_rev.is_a(real_estate_rev)
    assert general_rev.subsumes(real_estate_rev)
    assert general_rev.subsumes(real_estate_rev_net)

    opex = Atom("H_EXPENSE", frozenset(["M_OPERATING"]))
    assert not real_estate_rev.is_a(opex)


def test_atom_meet_and_join() -> None:
    """Verify greatest lower bound (meet) and least upper bound (join)."""
    rd = Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_RD"]))
    sga = Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_SGA"]))

    meet_atom = rd.meet(sga)
    assert meet_atom == Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_RD", "M_SGA"]))

    join_atom = rd.join(sga)
    assert join_atom == Atom("H_EXPENSE", frozenset(["M_OPERATING"]))


def test_prune_subsumed_and_specialized() -> None:
    """Verify antichain filtering keeping only specific or general atoms."""
    parent = Atom("H_EXPENSE", frozenset(["M_OPERATING"]))
    rd = Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_RD"]))
    sga = Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_SGA"]))

    specific_only = prune_subsumed([parent, rd, sga])
    assert specific_only == [rd, sga]

    general_only = prune_specialized([parent, rd, sga])
    assert general_only == [parent]
