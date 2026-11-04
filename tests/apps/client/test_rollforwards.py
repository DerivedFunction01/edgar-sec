"""Level-3 rollforward role specimens for the sale-act re-pointing."""

import pytest

from edgar_sec.apps.client.rollforwards import _level3_role
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_ASSET = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAsset"
_LIABILITY = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisLiability"
_DERIVATIVE = "us-gaap:FairValueNetDerivativeAssetLiabilityMeasuredOnRecurringBasisUnobservableInputsReconciliation"


def _role(qname: str) -> str | None:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(qname, tax.token_lexicon)
    return _level3_role(atom, "duration")


@pytest.mark.parametrize(
    "qname",
    [_ASSET + "Sales", _LIABILITY + "Sales", _DERIVATIVE + "Sales"],
)
def test_sales_role_fires_on_the_act_carrier(qname: str) -> None:
    """Each standard Level-3 sales line takes the sales role."""
    assert _role(qname) == "sales"


@pytest.mark.parametrize(
    "stem",
    [_ASSET, _LIABILITY, _DERIVATIVE],
)
def test_combined_lines_keep_the_sales_role(stem: str) -> None:
    """Combined purchases/sales lines keep their pre-change role."""
    assert _role(stem + "PurchasesSalesIssuancesSettlements") == "sales"


def test_sales_role_ignores_purpose_and_goods_senses() -> None:
    """Neither the held-for-sale purpose nor goods revenue takes the role."""
    assert _role(_ASSET + "HeldForSale") is None
    goods = Atom(
        "H_ASSET",
        frozenset({"M_FAIR_VALUE", "M_RECONCILIATION", "M_SALES_GOODS"}),
    )
    assert _level3_role(goods, "duration") is None
    act = Atom(
        "H_ASSET",
        frozenset({"M_FAIR_VALUE", "M_RECONCILIATION", "M_SALE"}),
    )
    assert _level3_role(act, "duration") == "sales"
