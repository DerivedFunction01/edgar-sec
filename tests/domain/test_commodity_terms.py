from __future__ import annotations

from edgar_sec.domain.commodity_terms import (
    COMMERCIAL_PHRASE_PATTERNS,
    COMMERCIAL_TERMS,
    COMMODITY_HEADER_PHRASE,
    CONTEXT_TERMS,
    ENERGY_PATTERN_PARTS,
    EXCHANGE_VENUE_PATTERNS,
    METALS_PATTERN_PARTS,
    NPNS_PATTERNS,
    NPNS_PHRASES,
    PHYSICAL_COMMERCIAL_TERM_PATTERNS,
    UNITS,
    UNITS_LOOSE,
    UNITS_STRICT,
)


def test_units_merge() -> None:
    assert len(UNITS_STRICT) == 30
    assert len(UNITS_LOOSE) == 42
    assert UNITS == UNITS_STRICT + UNITS_LOOSE
    assert not (set(UNITS_STRICT) & set(UNITS_LOOSE))
    assert len({unit.lower() for unit in UNITS}) == len(UNITS)
    # Pre-port live spellings win over old2 case variants.
    assert "mmbtu" in UNITS_STRICT
    assert "MMBtu" not in UNITS
    # The old2 disjoint additions are homed.
    assert "megawatt-hour" in UNITS_STRICT
    assert "barrels per day" in UNITS_STRICT
    assert "metric tons" in UNITS_STRICT
    assert {"bu", "lb", "oz", "head"} <= set(UNITS_LOOSE)


def test_npns_primitives() -> None:
    assert len(NPNS_PATTERNS) == 5
    # The physical-forward construction the gate port dropped is
    # restored in the plain-phrase set.
    assert "physical forward contracts" in NPNS_PHRASES
    assert "physical delivery agreements" in NPNS_PHRASES
    # The phrases the derivatives gate already carried survive.
    assert {
        "normal purchases and normal sales",
        "normal purchase and normal sale",
        "npns",
        "own-use exemption",
        "own use exemption",
        "physical delivery",
        "physical settlement",
    } <= set(NPNS_PHRASES)


def test_commercial_terms_restore_the_dropped_families() -> None:
    assert len(PHYSICAL_COMMERCIAL_TERM_PATTERNS) == 8
    assert len(COMMERCIAL_TERMS) == 16
    # Orders, invoices, receipts, inventory, purchases: dropped in
    # the port, restored here alongside the three surviving families.
    assert {
        "order",
        "invoice",
        "receipt",
        "inventory",
        "purchase",
        "delivery",
        "supply",
        "shipment",
    } <= set(COMMERCIAL_TERMS)
    assert len(COMMERCIAL_PHRASE_PATTERNS) == 5


def test_context_terms_carry_the_prior_gap() -> None:
    # D6: chemicals and construction have no pre-port context terms;
    # the gap is carried, not authored over.
    assert "chemicals" not in CONTEXT_TERMS
    assert "construction" not in CONTEXT_TERMS
    assert set(CONTEXT_TERMS) == {
        "energy",
        "metals",
        "crops",
        "livestock",
        "forestry",
        "environmental",
        "seafood",
    }


def test_pattern_parts_and_venues() -> None:
    # Every part list and context list is a tuple, never a bare string.
    assert all(isinstance(v, tuple) for v in ENERGY_PATTERN_PARTS.values())
    assert all(isinstance(v, tuple) for v in METALS_PATTERN_PARTS.values())
    assert all(isinstance(v, tuple) for v in CONTEXT_TERMS.values())
    assert set(ENERGY_PATTERN_PARTS) == {"prefixes", "modifiers", "bases"}
    assert "coal" in ENERGY_PATTERN_PARTS["bases"]
    assert "copper" in METALS_PATTERN_PARTS["bases"]
    assert len(EXCHANGE_VENUE_PATTERNS) == 6
    assert COMMODITY_HEADER_PHRASE == "commodity contracts"


def test_derivatives_spec_draws_from_the_substrate() -> None:
    from edgar_sec.engine.tables.extraction.specs.derivatives_evidence_specs import (
        DERIVATIVES_EVIDENCE_SPECS,
    )

    spec = DERIVATIVES_EVIDENCE_SPECS["derivatives_hedging"]
    assert spec.commercial_terms == COMMERCIAL_TERMS
    assert spec.npns_phrases == NPNS_PHRASES
    assert spec.commodity_header == COMMODITY_HEADER_PHRASE
