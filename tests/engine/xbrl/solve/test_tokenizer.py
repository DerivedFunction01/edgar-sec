"""Tests for the concept tokenizer service over the domain taxonomy."""

from __future__ import annotations

import pytest

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import EXACT, NEAR
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)


def _tokenizer() -> ConceptTokenizer:
    return ConceptTokenizer(load_domain_taxonomy())


def test_tokenizer_requires_a_token_lexicon() -> None:
    """A taxonomy without a lexicon cannot tokenize."""
    bare = DomainTaxonomy(prime_heads=(), subatomic_modifiers=())
    with pytest.raises(ValueError, match="token lexicon"):
        ConceptTokenizer(bare)


def test_tokenizer_archetype_record() -> None:
    """The ASC-606 archetype's record carries atom, relation, provenance."""
    record = _tokenizer().tokenize(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert record.atom == Atom(
        "H_REVENUE", frozenset({"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"})
    )
    assert record.presumed_atom == record.atom
    assert record.residuals == ()
    assert [relation for relation, _ in record.relations] == ["EXCLUDING"]
    assert record.operator is None
    assert [match.entry.phrase for match in record.matches] == [
        ("revenue", "from", "contract", "with", "customer"),
        ("excluding", "assessed", "tax"),
    ]


def test_tokenizer_net_of_tax_record() -> None:
    """NetOfTax: NET_OF operator, two operands, V_NET, no tax claim."""
    record = _tokenizer().tokenize(
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax"
    )
    assert record.operator == "NET_OF"
    assert len(record.operands) == 2
    assert "V_NET" in record.atom.modifiers
    assert "M_TAX" not in record.atom.modifiers
    assert record.relations == (("NET_OF", record.operands[1]),)
    assert record.operands[1] == Atom("H_UNKNOWN", frozenset({"M_TAX"}))


def test_tokenizer_maturity_bucket_record() -> None:
    """A maturity bucket carries its number indexical and temporal facet."""
    record = _tokenizer().tokenize(
        "amzn:FinancingObligationsFutureMinimumPaymentsDueInFiveYears"
    )
    assert record.atom == Atom("H_CASH", frozenset({"M_FINANCING", "M_MATURITY"}))
    assert record.indexicals == ("num=5",)
    assert record.temporal is not None
    assert record.temporal.shape == "BUCKET"
    assert (record.temporal.lo_months, record.temporal.hi_months) == (48, 60)
    assert record.derived_horizon == "M_NONCURRENT"


def test_tokenizer_equivalents_rank_ap_pair_via_default() -> None:
    """Bare AP ranks current first; accrued-current is via-default NEAR."""
    tokenizer = _tokenizer()
    ranked = tokenizer.equivalents(
        "us-gaap:AccountsPayable",
        ("us-gaap:AccruedLiabilitiesCurrent", "us-gaap:AccountsPayableCurrent"),
    )
    assert [item.qname for item in ranked] == [
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccruedLiabilitiesCurrent",
    ]
    assert ranked[0].tier == NEAR and ranked[0].rule == "single_modifier_difference"
    assert ranked[0].via_default is False
    assert ranked[1].tier == NEAR and ranked[1].rule == "via_default"
    assert ranked[1].via_default is True


def test_tokenizer_record_presumed_atom_applies_defaults() -> None:
    """The record's presumed atom presumes current for a bare payable."""
    record = _tokenizer().tokenize("us-gaap:AccountsPayable")
    assert record.atom == Atom("H_LIABILITY", frozenset({"M_ACCOUNTS_PAYABLE"}))
    assert record.presumed_atom == Atom(
        "H_LIABILITY", frozenset({"M_ACCOUNTS_PAYABLE", "M_CURRENT"})
    )


def test_tokenizer_equivalents_accept_atom_targets_and_pairs() -> None:
    """Atom targets and (qname, atom) candidate pairs rank directly."""
    tokenizer = _tokenizer()
    ranked = tokenizer.equivalents(
        Atom("H_REVENUE"),
        (
            ("firm-a:Revenues", Atom("H_REVENUE")),
            ("firm-b:CostOfRevenue", Atom("H_COST")),
        ),
    )
    assert len(ranked) == 1
    assert ranked[0].qname == "firm-a:Revenues"
    assert ranked[0].tier == EXACT and ranked[0].rule == "equality"
