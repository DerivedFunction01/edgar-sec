"""Decomposer tests: expression facets, evidence gating, tags."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
    infer_semantic_frame,
)
from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_head_class_arbitration_prefers_primary_over_instrument(
    taxonomy: DomainTaxonomy,
) -> None:
    """A PRIMARY flow head beats an INSTRUMENT head in the same region (B2)."""
    assert taxonomy.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "us-gaap:InterestExpenseFederalFundsPurchased", taxonomy.token_lexicon
    )
    assert atom.head == "H_EXPENSE"
    assert atom.modifiers == frozenset({"M_DEBT", "M_INTEREST"})


def test_expression_records_relation_claims(taxonomy: DomainTaxonomy) -> None:
    """EXCLUDING joins the expression's relations with its operand atom."""
    assert taxonomy.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy.token_lexicon,
    )
    assert [kind for kind, _ in expr.relations] == ["EXCLUDING"]
    assert expr.relations[0][1].modifiers == frozenset({"M_TAX"})


def test_expression_carries_temporal_facet_and_derived_horizon(
    taxonomy: DomainTaxonomy,
) -> None:
    """The interval lives on the expression; the horizon derives from it."""
    assert taxonomy.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        taxonomy.token_lexicon,
    )
    assert expr.temporal is not None
    assert (expr.temporal.lo_months, expr.temporal.hi_months) == (0, 12)
    assert expr.derived_horizon == "M_CURRENT"


def test_frame_carries_indexicals_and_temporal(taxonomy: DomainTaxonomy) -> None:
    """The semantic frame no longer discards indexicals or the interval."""
    frame = infer_semantic_frame(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        taxonomy,
    )
    assert frame.temporal is not None
    assert frame.indexicals


def test_coexistence_admission_requires_a_declared_pair() -> None:
    """RR2: a suppressed candidate attributes only via a declared pair."""
    from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon

    compound = LexiconEntry(
        ("property", "plant", "and", "equipment"),
        "modifier",
        atom="M_PPE_CAPEX",
    )
    tail = LexiconEntry(
        ("equipment", "disposals"),
        "head",
        head="H_CASH",
        claim_class="TAIL",
    )
    plain = TokenLexicon((compound, tail))
    atom, _, _, _ = decompose_concept("x:PropertyPlantAndEquipmentDisposals", plain)
    assert atom.head == "H_UNKNOWN"
    assert atom.modifiers == frozenset({"M_PPE_CAPEX"})
    declared = LexiconEntry(
        ("equipment", "disposals"),
        "head",
        head="H_CASH",
        claim_class="TAIL",
        coexists_with=("property plant and equipment",),
    )
    with_pair = TokenLexicon((compound, declared))
    atom2, _, _, _ = decompose_concept(
        "x:PropertyPlantAndEquipmentDisposals", with_pair
    )
    assert atom2.head == "H_CASH"


def test_requires_evidence_claim_never_fires() -> None:
    """Q6: an evidence-gated claim is inert while no evidence channel exists."""
    from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon

    gated = LexiconEntry(
        ("impairment",),
        "head",
        head="H_EXPENSE",
        claim_class="PRIMARY",
        requires_evidence=True,
    )
    lex = TokenLexicon((gated,))
    atom, _, _, _ = decompose_concept("x:Impairment", lex)
    assert atom.head == "H_UNKNOWN"


def test_requires_evidence_claim_fires_when_satisfied() -> None:
    """Q6 twin: a satisfied evidence context lets the gated claim fire."""
    from edgar_sec.engine.xbrl.normalize.lexicon import (
        EvidenceContext,
        LexiconEntry,
        TokenLexicon,
    )

    gated = LexiconEntry(
        ("impairment",),
        "head",
        head="H_EXPENSE",
        claim_class="PRIMARY",
        requires_evidence=True,
    )
    lex = TokenLexicon((gated,))
    satisfied = EvidenceContext("0000000001-24-000001", "x:Impairment", True)
    atom, _, _, _ = decompose_concept("x:Impairment", lex, evidence=satisfied)
    assert atom.head == "H_EXPENSE"
    unsatisfied = EvidenceContext("0000000001-24-000001", "x:Impairment", False)
    atom, _, _, _ = decompose_concept("x:Impairment", lex, evidence=unsatisfied)
    assert atom.head == "H_UNKNOWN"


def test_impairment_descriptive_tag_spans_heads_without_moving_them(
    tax: DomainTaxonomy,
) -> None:
    """The impairment tag filters across heads; heads and family EXACT hold."""
    from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
        EXACT,
        UNRELATED,
        classify_pair,
    )

    from edgar_sec.engine.xbrl.normalize.lexicon import EvidenceContext

    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def attested(qname: str) -> EvidenceContext:
        return EvidenceContext("0000000001-24-000001", qname, True)

    loss_qname = "us-gaap:ImpairmentOfOilAndGasProperties"
    loss, _, _, _ = decompose_concept(loss_qname, lex, evidence=attested(loss_qname))
    held_qname = "us-gaap:ImpairmentOfLongLivedAssetsHeldForUse"
    held, _, _, _ = decompose_concept(held_qname, lex, evidence=attested(held_qname))
    disposed_qname = "us-gaap:ImpairmentOfLongLivedAssetsToBeDisposedOf"
    disposed, _, _, _ = decompose_concept(
        disposed_qname, lex, evidence=attested(disposed_qname)
    )
    population, _, _, _ = decompose_concept(
        "us-gaap:FinancingReceivableCollectivelyEvaluatedForImpairment", lex
    )
    balance, _, _, _ = decompose_concept(
        "asml:AccumulatedDepreciationDepletionAmortizationAndImpairment"
        "PropertyPlantAndEquipment",
        lex,
    )
    textblock, _, _, _ = decompose_concept(
        "nee:ImpairmentOfEquityMethodInvestmentsPolicyPolicyTextBlock", lex
    )
    for atom in (loss, held, disposed, population, balance, textblock):
        assert "M_IMPAIRMENT" in atom.modifiers
    assert loss.head == "H_INCOME"
    assert population.head == "H_ASSET"
    assert balance.head == "H_ASSET"
    assert textblock.head == "H_ASSET"
    assert classify_pair(held, disposed) == EXACT
    assert classify_pair(loss, population) == UNRELATED


def test_descriptive_tags_ride_across_heads_part2(tax: DomainTaxonomy) -> None:
    """Accumulated/cumulative/litigation/environmental tags cross heads."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    contra, _, _, _ = decompose_concept(
        "us-gaap:AccumulatedDepreciationDepletionAndAmortization", lex
    )
    aoci, _, _, _ = decompose_concept(
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", lex
    )
    hedge, _, _, _ = decompose_concept(
        "us-gaap:FairValueHedgeCumulativeIncreaseDecreaseInFairValueOfHedgedItem",
        lex,
    )
    settlement, _, _, _ = decompose_concept("us-gaap:LitigationSettlementExpense", lex)
    remediation, _, _, _ = decompose_concept(
        "us-gaap:EnvironmentalRemediationExpense", lex
    )
    assert "M_ACCUMULATED" in contra.modifiers and contra.head == "H_ASSET"
    assert "M_ACCUMULATED" in aoci.modifiers and aoci.head == "H_EQUITY"
    assert "M_CUMULATIVE" in hedge.modifiers
    assert settlement.head == "H_EXPENSE"
    assert settlement.modifiers == frozenset({"M_LITIGATION", "M_SETTLEMENT"})
    assert remediation.modifiers == frozenset({"M_ENVIRONMENTAL"})
    assert remediation.head == "H_EXPENSE"


def test_revenue_components_carry_identity_off_the_bare_atom(
    tax: DomainTaxonomy,
) -> None:
    """Fee/commission components decompose distinctly from headline Revenues."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def atom_of(qname: str):
        atom, _, _, _ = decompose_concept(qname, lex)
        return atom

    headline = atom_of("us-gaap:Revenues")
    assert headline.head == "H_REVENUE"
    assert headline.modifiers == frozenset()

    expected = {
        "bac:FeesAndCommissions1": {"M_FEES_COMMISSIONS"},
        "jpm:FeesAndCommissions1": {"M_FEES_COMMISSIONS"},
        "jpm:FeesAndCommissionsDepositorAccounts1": {
            "M_FEES_COMMISSIONS",
            "M_DEPOSITOR_ACCOUNTS",
        },
        "jpm:FeesAndCommissionsLendingActivities": {
            "M_FEES_COMMISSIONS",
            "M_LENDING_ACTIVITIES",
        },
        "jpm:FeesAndCommissionsOther1": {"M_FEES_COMMISSIONS", "M_OTHER"},
        "jpm:MortgageProductionRevenue": {"M_MORTGAGE_PRODUCTION"},
        "us-gaap:BrokerageCommissionsRevenue": {"M_BROKERAGE_COMMISSIONS"},
        "us-gaap:PrincipalTransactionsRevenue": {"M_PRINCIPAL_TRANSACTIONS"},
        "pld:ManagementFeesRevenue1": {"M_MANAGEMENT_FEES"},
        "us-gaap:PropertyManagementFeeRevenue": {"M_MANAGEMENT_FEES"},
    }
    atoms = {}
    for qname, mods in expected.items():
        atom = atom_of(qname)
        assert atom.head == "H_REVENUE", qname
        assert atom.modifiers == frozenset(mods), qname
        assert atom != headline, qname
        atoms[qname] = atom

    # JPM's enumerated components are pairwise distinct atoms.
    jpm_atoms = [a for q, a in atoms.items() if q.startswith("jpm:")]
    jpm_atoms.append(atom_of("us-gaap:BrokerageCommissionsRevenue"))
    jpm_atoms.append(atom_of("us-gaap:PrincipalTransactionsRevenue"))
    assert len(set(jpm_atoms)) == len(jpm_atoms)

    # The fees stem carries onto already-identified component lines.
    servicing = atom_of("us-gaap:FeesAndCommissionsMortgageBankingAndServicing")
    assert servicing.modifiers == frozenset(
        {"M_FEES_COMMISSIONS", "M_MORTGAGE_BANKING"}
    )

    # The XVA name carries the valuation-adjustment coordinate.
    xva = atom_of("bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets")
    assert xva.head == "H_ASSET"
    assert xva.modifiers == frozenset({"M_DERIVATIVE", "M_VALUATION_ADJUSTMENT"})


def test_adjustment_coordinates_claim_only_their_terms(tax: DomainTaxonomy) -> None:
    """Valuation/reclassification adjustments claim; other senses stay residual."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def atom_of(qname: str):
        atom, _, _, _ = decompose_concept(qname, lex)
        return atom

    cva_assets = atom_of(
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeAssets"
    )
    assert cva_assets.head == "H_ASSET"
    assert cva_assets.modifiers == frozenset(
        {"M_DERIVATIVE", "M_RISK_CREDIT", "M_VALUATION_ADJUSTMENT"}
    )
    cva_liabs = atom_of(
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeLiabilities"
    )
    assert cva_liabs.head == "H_LIABILITY"
    assert "M_VALUATION_ADJUSTMENT" in cva_liabs.modifiers

    singular = atom_of(
        "amzn:OtherComprehensiveIncomeLossReclassificationAdjustmentFromAOCINetOfTax"
    )
    assert singular.modifiers == frozenset({"M_OCI", "M_RECLASS_ADJUSTMENT", "V_NET"})
    plural = atom_of(
        "us-gaap:OtherComprehensiveIncomeLossAvailableForSaleSecurities"
        "AdjustmentBeforeReclassificationAdjustmentsAndTax"
    )
    assert "M_RECLASS_ADJUSTMENT" in plural.modifiers

    # The plural valuation phrase names other relations and never claims.
    for qname in (
        "us-gaap:FederalHomeLoanBankAdvancesValuationAdjustmentsForHedgingActivities",
        "us-gaap:OtherRealEstateValuationAdjustments",
    ):
        assert "M_VALUATION_ADJUSTMENT" not in atom_of(qname).modifiers
