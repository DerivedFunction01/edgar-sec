"""Equivalence scoped swaps: sibling swaps inside their declared scopes."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
    NEAR,
    UNRELATED,
    classify_pair,
    presumed_atom,
    rank_equivalents,
)
from tests.engine.xbrl.solve.concepts.equivalence_support import (
    _atom,
    _scoped_portion_group,
)


def test_scoped_sibling_swap_fires_only_inside_its_scope() -> None:
    """A scoped group swaps on its named coordinates and nowhere else."""
    groups = (_scoped_portion_group(),)
    current = Atom("H_EXPENSE", frozenset({"M_CURRENT", "M_TAX"}))
    deferred = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    ranked = rank_equivalents(
        "firm-x:Current",
        current,
        (("firm-a:Deferred", deferred),),
        sibling_groups=groups,
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"

    off_head = Atom("H_LIABILITY", frozenset({"M_DEFERRED", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Current",
            current,
            (("firm-a:Off", off_head),),
            sibling_groups=groups,
        )
        == ()
    )
    current_tax = Atom("H_LIABILITY", frozenset({"M_CURRENT", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Current",
            current_tax,
            (("firm-a:Off", off_head),),
            sibling_groups=groups,
        )
        == ()
    )
    wide = Atom("H_EXPENSE", frozenset({"M_CURRENT", "M_TAX", "M_OCI"}))
    wide_deferred = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX", "M_OCI"}))
    assert (
        rank_equivalents(
            "firm-x:Wide",
            wide,
            (("firm-a:Wide", wide_deferred),),
            sibling_groups=groups,
        )
        == ()
    )
    recon_current = Atom(
        "H_INCOME",
        frozenset({"M_CURRENT", "M_RECONCILIATION", "M_TAX", "M_TAX_INCOME"}),
    )
    recon_deferred = Atom(
        "H_INCOME",
        frozenset({"M_DEFERRED", "M_RECONCILIATION", "M_TAX", "M_TAX_INCOME"}),
    )
    ranked = rank_equivalents(
        "firm-x:Recon",
        recon_current,
        (("firm-a:Recon", recon_deferred),),
        sibling_groups=groups,
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"


def test_scoped_membership_cannot_leak_across_groups() -> None:
    """Deferred vs Noncurrent stays unrelated with both groups in play."""
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup

    groups = (
        _scoped_portion_group(),
        SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    )
    deferred_tax = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    noncurrent_tax = Atom("H_EXPENSE", frozenset({"M_NONCURRENT", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Deferred",
            deferred_tax,
            (("firm-a:Noncurrent", noncurrent_tax),),
            sibling_groups=groups,
        )
        == ()
    )


def test_tax_portion_pairs_are_sibling_swaps() -> None:
    """Current and deferred portions of income tax expense are near kin."""
    current = _atom("us-gaap:CurrentIncomeTaxExpenseBenefit")
    deferred = _atom("us-gaap:DeferredIncomeTaxExpenseBenefit")
    assert classify_pair(current, deferred) == NEAR
    ranked = rank_equivalents(
        "us-gaap:CurrentIncomeTaxExpenseBenefit",
        current,
        (("us-gaap:DeferredIncomeTaxExpenseBenefit", deferred),),
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"
    for current_q, deferred_q in (
        (
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearCurrentIncomeTaxesAmount",
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearDeferredIncomeTaxesAmount",
        ),
        (
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearCurrentIncomeTaxesPercent",
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearDeferredIncomeTaxesPercent",
        ),
    ):
        assert classify_pair(_atom(current_q), _atom(deferred_q)) == NEAR


def test_tax_bearing_swap_shapes_outside_the_portion_scope_stay_unrelated() -> None:
    """Same swap shape, wrong coordinates: the scope refuses these pairs."""
    near_miss = (
        _atom("us-gaap:AccrualForTaxesOtherThanIncomeTaxesCurrent"),
        _atom("us-gaap:DeferredIncomeTaxesAndTaxCredits"),
    )
    assert classify_pair(*near_miss) == UNRELATED
    asset_acquisition = (
        _atom("bmy:AssetAcquisitionDeferredIncomeTaxLiability"),
        _atom("us-gaap:AccruedIncomeTaxesCurrent"),
    )
    assert classify_pair(*asset_acquisition) == UNRELATED
    revenue_shape = (
        _atom("asml:ContractWithCustomerAssetRevenueRecognizedDuringTheCurrentYear"),
        _atom("msft:ContractWithCustomerLiabilityRevenueDeferred"),
    )
    assert classify_pair(*revenue_shape) == UNRELATED


def test_operations_scope_portion_pairs_are_sibling_swaps() -> None:
    """Continuing/discontinued portions swap on a fixed measurement basis."""
    for continuing_q, discontinued_q in (
        (
            "us-gaap:NetCashProvidedByUsedInContinuingOperations",
            "us-gaap:NetCashProvidedByUsedInDiscontinuedOperations",
        ),
        (
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
            "us-gaap:DiscontinuedOperationIncomeLossFromDiscontinuedOperationBeforeIncomeTax",
        ),
        (
            "bac:IncomeLossFromContinuingOperationsAfterIncomeLossFromSubsidiariesNetOfTax",
            "us-gaap:IncomeLossFromDiscontinuedOperationsNetOfTax",
        ),
    ):
        continuing = _atom(continuing_q)
        discontinued = _atom(discontinued_q)
        assert classify_pair(continuing, discontinued) == NEAR
        ranked = rank_equivalents(
            continuing_q, continuing, ((discontinued_q, discontinued),)
        )
        assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"


def test_operations_scope_refuses_involvement_and_component_shapes() -> None:
    """Involvement senses and whole-vs-component shapes never swap."""
    for continuing_q, discontinued_q in (
        (
            "us-gaap:ContinuingInvolvementWithTransferredFinancialAssetsPrincipalAmountOutstanding",
            "fcx:DiscontinuedOperationContingentReceivable",
        ),
        (
            "bac:TransfersContinuingInvolvementServicingFeeAdvances",
            "jnj:DiscontinuedOperationTransitionManufacturingAgreementTerm",
        ),
    ):
        assert classify_pair(_atom(continuing_q), _atom(discontinued_q)) == UNRELATED


def test_operations_scope_refuses_the_tax_effect_shape() -> None:
    """Shared M_TAX alone fixes no basis: a whole never swaps its component."""
    continuing = _atom(
        "bac:IncomeLossfromContinuingOperationsbeforeIncomeLossFromSubsidiariesNetofTax"
    )
    tax_effect = _atom("us-gaap:DiscontinuedOperationTaxEffectOfDiscontinuedOperation")
    assert classify_pair(continuing, tax_effect) == UNRELATED


def test_operations_scope_anticipates_the_eps_basis_pairs() -> None:
    """Per-share continuing/discontinued pairs swap on the EPS contexts."""
    for basis in ("Basic", "Diluted"):
        continuing = _atom(
            f"us-gaap:NetIncomeLossFromContinuingOperationsAvailableToCommonShareholders{basis}"
        )
        discontinued = _atom(
            f"us-gaap:NetIncomeLossFromDiscontinuedOperationsAvailableToCommonShareholders{basis}"
        )
        assert classify_pair(continuing, discontinued) == NEAR


def test_corpus_deferred_noncurrent_shapes_stay_unrelated() -> None:
    """A corpus Deferred/Noncurrent pair is not a swap on any declared axis."""
    deferred = _atom("us-gaap:DeferredIncomeTaxLiabilities")
    noncurrent = _atom("alb:TaxIndemnificationLiabilityNoncurrent")
    assert deferred.modifiers == frozenset({"M_DEFERRED", "M_TAX"})
    assert noncurrent.modifiers == frozenset({"M_NONCURRENT", "M_TAX"})
    assert classify_pair(deferred, noncurrent) == UNRELATED


def test_presumed_atom_axis_resolution_is_name_aware() -> None:
    """The silence test consults the named axis, not the first group found."""
    from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup

    entry = DefaultCoordinate(
        head="H_EXPENSE",
        identity_modifiers=("M_DEFERRED",),
        axis="MATURITY_HORIZON",
        presumed_modifier="M_CURRENT",
        rationale="Synthetic: portion identity, horizon default.",
        attestation_class="anticipated",
    )
    groups = (
        _scoped_portion_group(),
        SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    )
    atom = Atom("H_EXPENSE", frozenset({"M_DEFERRED"}))
    presumed = presumed_atom(atom, (entry,), sibling_groups=groups)
    assert presumed.modifiers == frozenset({"M_DEFERRED", "M_CURRENT"})
