"""Battery entry type: tiers, the builder, and the shared constants.

Every entry's expected value was verified against its filing — by fact
name and extracted facts where unambiguous, otherwise rendered text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BASIC = "basic"
TEXTBOOK = "textbook"
COMPLEX = "complex"

_FACTS = "facts.parquet: undimensioned consolidated fact in the seed bundle"
_EPS_ROUTE = (
    _FACTS + "; calc-isolated: EPS identity route (attributable income"
    " / weighted-average shares, printed precision)"
)
_EPS_PINNED = (
    _FACTS + "; calc-isolated: EPS identity route pinned - no diluted"
    " weighted-share fact filed; diluted EPS as filed equals basic EPS"
    " as filed"
)


@dataclass(frozen=True, slots=True)
class BatteryEntry:
    """One fact the engine must answer at its verified value."""

    entry_id: str
    tier: str
    firm: str
    accession: str
    qname: str
    expected_value: float
    unit: str = "USD"
    instant: str = ""
    start: str = ""
    end: str = ""
    dimensions: tuple[tuple[str, str], ...] = ()
    mode: str = "REPORTED_ONLY"
    expected_status: str = "REPORTED"
    verification: str = _FACTS


def _e(
    entry_id: str,
    tier: str,
    firm: str,
    accession: str,
    qname: str,
    value: float,
    **kw: Any,
) -> BatteryEntry:
    return BatteryEntry(entry_id, tier, firm, accession, qname, value, **kw)


_MSFT = "0000950170-24-087843"
_MSFT_D = {"start": "2023-07-01", "end": "2024-06-30"}
_MSFT_I = {"instant": "2024-06-30"}
_AAPL = "0000320193-24-000123"
_AAPL_D = {"start": "2023-10-01", "end": "2024-09-28"}
_AAPL_I = {"instant": "2024-09-28"}
_XOM = "0000034088-25-000010"
_D24 = {"start": "2024-01-01", "end": "2024-12-31"}
_I24 = {"instant": "2024-12-31"}
_WMT = "0000104169-24-000056"
_WMT_D = {"start": "2023-02-01", "end": "2024-01-31"}
_WMT_I = {"instant": "2024-01-31"}
_JNJ = "0000200406-25-000038"
_JNJ_D = {"start": "2024-01-01", "end": "2024-12-29"}
_JNJ_I = {"instant": "2024-12-29"}
_CAT = "0000018230-25-000008"
_NFLX = "0001065280-25-000044"
_GOOGL = "0001652044-25-000014"
_BAC24 = "0000070858-25-000139"
_BAC11 = "0000070858-12-000155"
_DUK = "0001326160-25-000072"
_MET = "0001099219-25-000044"
_JPM = "0000019617-25-000270"
_JPM_D = {"start": "2024-01-01", "end": "2024-12-31"}
_JPM_I = {"instant": "2024-12-31"}
_APD = "0000002969-24-000056"
_APD_D = {"start": "2023-10-01", "end": "2024-09-30"}
_APD_I = {"instant": "2024-09-30"}
_AMZN23 = "0001018724-24-000008"
_AMZN23_D = {"start": "2023-01-01", "end": "2023-12-31"}
_AMZN23_I = {"instant": "2023-12-31"}
_DIS = "0001744489-24-000276"
_DIS_D = {"start": "2023-10-01", "end": "2024-09-28"}
_DIS_I = {"instant": "2024-09-28"}
_PRETAX = (
    "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
    "ExtraordinaryItemsNoncontrollingInterest"
)
_ROLLUP = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
_CFI = "us-gaap:NetCashProvidedByUsedInInvestingActivities"
_CFF = "us-gaap:NetCashProvidedByUsedInFinancingActivities"
_CFO_CONT = "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
_CFI_CONT = "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"
_CFF_CONT = "us-gaap:NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"
_REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_CASH = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
_NI = "us-gaap:NetIncomeLoss"
_CFO = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
_OI = "us-gaap:OperatingIncomeLoss"
_RE = "us-gaap:RetainedEarningsAccumulatedDeficit"
