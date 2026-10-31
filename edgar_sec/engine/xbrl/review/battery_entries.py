"""Battery entry definitions: tiers, the entry type, and the set.

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

BATTERY_SET: tuple[BatteryEntry, ...] = (
    # Basic tier — cash, revenue, assets, liabilities, net income.
    _e("msft-cash", BASIC, "MSFT", _MSFT, _CASH, 18_315_000_000.0, **_MSFT_I),
    _e("msft-revenue", BASIC, "MSFT", _MSFT, _REV, 245_122_000_000.0, **_MSFT_D),
    _e(
        "msft-assets",
        BASIC,
        "MSFT",
        _MSFT,
        "us-gaap:Assets",
        512_163_000_000.0,
        **_MSFT_I,
    ),
    _e(
        "msft-liabilities",
        BASIC,
        "MSFT",
        _MSFT,
        "us-gaap:Liabilities",
        243_686_000_000.0,
        **_MSFT_I,
    ),
    _e("msft-net-income", BASIC, "MSFT", _MSFT, _NI, 88_136_000_000.0, **_MSFT_D),
    _e("aapl-cash", BASIC, "AAPL", _AAPL, _CASH, 29_943_000_000.0, **_AAPL_I),
    _e("aapl-revenue", BASIC, "AAPL", _AAPL, _REV, 391_035_000_000.0, **_AAPL_D),
    _e(
        "aapl-assets",
        BASIC,
        "AAPL",
        _AAPL,
        "us-gaap:Assets",
        364_980_000_000.0,
        **_AAPL_I,
    ),
    _e(
        "aapl-liabilities",
        BASIC,
        "AAPL",
        _AAPL,
        "us-gaap:Liabilities",
        308_030_000_000.0,
        **_AAPL_I,
    ),
    _e("aapl-net-income", BASIC, "AAPL", _AAPL, _NI, 93_736_000_000.0, **_AAPL_D),
    _e("xom-cash", BASIC, "XOM", _XOM, _CASH, 23_029_000_000.0, **_I24),
    _e(
        "xom-revenue", BASIC, "XOM", _XOM, "us-gaap:Revenues", 349_585_000_000.0, **_D24
    ),
    _e("xom-assets", BASIC, "XOM", _XOM, "us-gaap:Assets", 453_475_000_000.0, **_I24),
    _e(
        "xom-liabilities",
        BASIC,
        "XOM",
        _XOM,
        "us-gaap:Liabilities",
        182_869_000_000.0,
        **_I24,
    ),
    _e("xom-net-income", BASIC, "XOM", _XOM, _NI, 33_680_000_000.0, **_D24),
    _e("wmt-cash", BASIC, "WMT", _WMT, _CASH, 9_867_000_000.0, **_WMT_I),
    _e("wmt-revenue", BASIC, "WMT", _WMT, _REV, 642_637_000_000.0, **_WMT_D),
    _e("wmt-assets", BASIC, "WMT", _WMT, "us-gaap:Assets", 252_399_000_000.0, **_WMT_I),
    _e("wmt-net-income", BASIC, "WMT", _WMT, _NI, 15_511_000_000.0, **_WMT_D),
    _e("jnj-cash", BASIC, "JNJ", _JNJ, _CASH, 24_105_000_000.0, **_JNJ_I),
    _e("jnj-revenue", BASIC, "JNJ", _JNJ, _REV, 88_821_000_000.0, **_JNJ_D),
    _e("jnj-assets", BASIC, "JNJ", _JNJ, "us-gaap:Assets", 180_104_000_000.0, **_JNJ_I),
    _e(
        "jnj-liabilities",
        BASIC,
        "JNJ",
        _JNJ,
        "us-gaap:Liabilities",
        108_614_000_000.0,
        **_JNJ_I,
    ),
    _e("jnj-net-income", BASIC, "JNJ", _JNJ, _NI, 14_066_000_000.0, **_JNJ_D),
    _e("cat-cash", BASIC, "CAT", _CAT, _CASH, 6_889_000_000.0, **_I24),
    _e("cat-revenue", BASIC, "CAT", _CAT, "us-gaap:Revenues", 64_809_000_000.0, **_D24),
    _e("cat-assets", BASIC, "CAT", _CAT, "us-gaap:Assets", 87_764_000_000.0, **_I24),
    _e(
        "cat-liabilities",
        BASIC,
        "CAT",
        _CAT,
        "us-gaap:Liabilities",
        68_270_000_000.0,
        **_I24,
    ),
    _e(
        "cat-net-income",
        BASIC,
        "CAT",
        _CAT,
        "us-gaap:ProfitLoss",
        10_788_000_000.0,
        **_D24,
        verification=_FACTS
        + "; CAT reports no NetIncomeLoss — ProfitLoss is its net income concept",
    ),
    _e("nflx-cash", BASIC, "NFLX", _NFLX, _CASH, 7_804_733_000.0, **_I24),
    _e(
        "nflx-revenue",
        BASIC,
        "NFLX",
        _NFLX,
        "us-gaap:Revenues",
        39_000_966_000.0,
        **_D24,
    ),
    _e("nflx-assets", BASIC, "NFLX", _NFLX, "us-gaap:Assets", 53_630_374_000.0, **_I24),
    _e(
        "nflx-liabilities",
        BASIC,
        "NFLX",
        _NFLX,
        "us-gaap:Liabilities",
        28_886_807_000.0,
        **_I24,
    ),
    _e("nflx-net-income", BASIC, "NFLX", _NFLX, _NI, 8_711_631_000.0, **_D24),
    _e("googl-cash", BASIC, "GOOGL", _GOOGL, _CASH, 23_466_000_000.0, **_I24),
    _e("googl-revenue", BASIC, "GOOGL", _GOOGL, _REV, 350_018_000_000.0, **_D24),
    _e(
        "googl-assets",
        BASIC,
        "GOOGL",
        _GOOGL,
        "us-gaap:Assets",
        450_256_000_000.0,
        **_I24,
    ),
    _e(
        "googl-liabilities",
        BASIC,
        "GOOGL",
        _GOOGL,
        "us-gaap:Liabilities",
        125_172_000_000.0,
        **_I24,
    ),
    _e("googl-net-income", BASIC, "GOOGL", _GOOGL, _NI, 100_118_000_000.0, **_D24),
    # Basic tier, repair extension — JPM, APD, AMZN (FY2023), DIS, whose
    # bundles were regenerated from their registry filings in the
    # 2026-10-26 corpus-integrity repair. AMZN and DIS file no
    # undimensioned Liabilities total, so they carry no liabilities entry.
    _e(
        "jpm-cash",
        BASIC,
        "JPM",
        _JPM,
        _ROLLUP,
        469_317_000_000.0,
        **_JPM_I,
        verification=(
            "facts.parquet: undimensioned consolidated fact in the seed "
            "bundle; JPM files no plain cash concept, the ASU 2016-18 "
            "rollup is its cash total"
        ),
    ),
    _e(
        "jpm-revenue",
        BASIC,
        "JPM",
        _JPM,
        "us-gaap:RevenuesNetOfInterestExpense",
        177_556_000_000.0,
        **_JPM_D,
    ),
    _e(
        "jpm-assets",
        BASIC,
        "JPM",
        _JPM,
        "us-gaap:Assets",
        4_002_814_000_000.0,
        **_JPM_I,
    ),
    _e(
        "jpm-liabilities",
        BASIC,
        "JPM",
        _JPM,
        "us-gaap:Liabilities",
        3_658_056_000_000.0,
        **_JPM_I,
    ),
    _e("jpm-net-income", BASIC, "JPM", _JPM, _NI, 58_471_000_000.0, **_JPM_D),
    _e("apd-cash", BASIC, "APD", _APD, _CASH, 2_979_700_000.0, **_APD_I),
    _e(
        "apd-revenue",
        BASIC,
        "APD",
        _APD,
        "us-gaap:Revenues",
        12_100_600_000.0,
        **_APD_D,
    ),
    _e("apd-assets", BASIC, "APD", _APD, "us-gaap:Assets", 39_574_600_000.0, **_APD_I),
    _e(
        "apd-liabilities",
        BASIC,
        "APD",
        _APD,
        "us-gaap:Liabilities",
        20_900_900_000.0,
        **_APD_I,
    ),
    _e("apd-net-income", BASIC, "APD", _APD, _NI, 3_828_200_000.0, **_APD_D),
    _e("amzn-cash", BASIC, "AMZN", _AMZN23, _CASH, 73_387_000_000.0, **_AMZN23_I),
    _e("amzn-revenue", BASIC, "AMZN", _AMZN23, _REV, 574_785_000_000.0, **_AMZN23_D),
    _e(
        "amzn-assets",
        BASIC,
        "AMZN",
        _AMZN23,
        "us-gaap:Assets",
        527_854_000_000.0,
        **_AMZN23_I,
    ),
    _e("amzn-net-income", BASIC, "AMZN", _AMZN23, _NI, 30_425_000_000.0, **_AMZN23_D),
    _e("dis-cash", BASIC, "DIS", _DIS, _CASH, 6_002_000_000.0, **_DIS_I),
    _e(
        "dis-revenue",
        BASIC,
        "DIS",
        _DIS,
        "us-gaap:Revenues",
        91_361_000_000.0,
        **_DIS_D,
    ),
    _e("dis-assets", BASIC, "DIS", _DIS, "us-gaap:Assets", 196_219_000_000.0, **_DIS_I),
    _e("dis-net-income", BASIC, "DIS", _DIS, _NI, 4_972_000_000.0, **_DIS_D),
    # Textbook tier — gross profit, operating income, retained earnings,
    # the three cash-flow sections, basic and diluted EPS.
    _e(
        "msft-gross-profit",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        "us-gaap:GrossProfit",
        171_008_000_000.0,
        **_MSFT_D,
    ),
    _e(
        "msft-operating-income",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        _OI,
        109_433_000_000.0,
        **_MSFT_D,
    ),
    _e(
        "msft-retained-earnings",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        _RE,
        173_144_000_000.0,
        **_MSFT_I,
    ),
    _e("msft-cfo", TEXTBOOK, "MSFT", _MSFT, _CFO, 118_548_000_000.0, **_MSFT_D),
    _e(
        "msft-cfi",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        "us-gaap:NetCashProvidedByUsedInInvestingActivities",
        -96_970_000_000.0,
        **_MSFT_D,
    ),
    _e(
        "msft-cff",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        "us-gaap:NetCashProvidedByUsedInFinancingActivities",
        -37_757_000_000.0,
        **_MSFT_D,
    ),
    _e(
        "msft-eps-basic",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        "us-gaap:EarningsPerShareBasic",
        11.86,
        unit="USD/shares",
        **_MSFT_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "msft-eps-diluted",
        TEXTBOOK,
        "MSFT",
        _MSFT,
        "us-gaap:EarningsPerShareDiluted",
        11.8,
        unit="USD/shares",
        **_MSFT_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "aapl-gross-profit",
        TEXTBOOK,
        "AAPL",
        _AAPL,
        "us-gaap:GrossProfit",
        180_683_000_000.0,
        **_AAPL_D,
    ),
    _e(
        "aapl-operating-income",
        TEXTBOOK,
        "AAPL",
        _AAPL,
        _OI,
        123_216_000_000.0,
        **_AAPL_D,
    ),
    _e(
        "aapl-retained-earnings",
        TEXTBOOK,
        "AAPL",
        _AAPL,
        _RE,
        -19_154_000_000.0,
        **_AAPL_I,
    ),
    _e("aapl-cfo", TEXTBOOK, "AAPL", _AAPL, _CFO, 118_254_000_000.0, **_AAPL_D),
    _e(
        "aapl-eps-diluted",
        TEXTBOOK,
        "AAPL",
        _AAPL,
        "us-gaap:EarningsPerShareDiluted",
        6.08,
        **_AAPL_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "jnj-gross-profit",
        TEXTBOOK,
        "JNJ",
        _JNJ,
        "us-gaap:GrossProfit",
        61_350_000_000.0,
        **_JNJ_D,
    ),
    _e("jnj-cfo", TEXTBOOK, "JNJ", _JNJ, _CFO, 24_266_000_000.0, **_JNJ_D),
    _e(
        "jnj-cfi",
        TEXTBOOK,
        "JNJ",
        _JNJ,
        "us-gaap:NetCashProvidedByUsedInInvestingActivities",
        -18_599_000_000.0,
        **_JNJ_D,
    ),
    _e(
        "jnj-eps-diluted",
        TEXTBOOK,
        "JNJ",
        _JNJ,
        "us-gaap:EarningsPerShareDiluted",
        5.79,
        **_JNJ_D,
        verification=_EPS_ROUTE,
    ),
    _e("wmt-operating-income", TEXTBOOK, "WMT", _WMT, _OI, 27_012_000_000.0, **_WMT_D),
    _e("wmt-retained-earnings", TEXTBOOK, "WMT", _WMT, _RE, 89_814_000_000.0, **_WMT_I),
    _e("wmt-cfo", TEXTBOOK, "WMT", _WMT, _CFO, 35_726_000_000.0, **_WMT_D),
    _e(
        "wmt-eps-basic",
        TEXTBOOK,
        "WMT",
        _WMT,
        "us-gaap:EarningsPerShareBasic",
        1.92,
        unit="USD/shares",
        **_WMT_D,
        verification=_EPS_ROUTE,
    ),
    _e("cat-operating-income", TEXTBOOK, "CAT", _CAT, _OI, 13_072_000_000.0, **_D24),
    _e("cat-retained-earnings", TEXTBOOK, "CAT", _CAT, _RE, 59_352_000_000.0, **_I24),
    _e("cat-cfo", TEXTBOOK, "CAT", _CAT, _CFO, 12_035_000_000.0, **_D24),
    _e(
        "cat-eps-diluted",
        TEXTBOOK,
        "CAT",
        _CAT,
        "us-gaap:EarningsPerShareDiluted",
        22.05,
        unit="USD/shares",
        **_D24,
        verification=_EPS_ROUTE,
    ),
    _e("nflx-operating-income", TEXTBOOK, "NFLX", _NFLX, _OI, 10_417_614_000.0, **_D24),
    _e(
        "nflx-retained-earnings", TEXTBOOK, "NFLX", _NFLX, _RE, 31_300_917_000.0, **_I24
    ),
    _e("nflx-cfo", TEXTBOOK, "NFLX", _NFLX, _CFO, 7_361_364_000.0, **_D24),
    _e(
        "googl-operating-income",
        TEXTBOOK,
        "GOOGL",
        _GOOGL,
        _OI,
        112_390_000_000.0,
        **_D24,
    ),
    _e(
        "googl-retained-earnings",
        TEXTBOOK,
        "GOOGL",
        _GOOGL,
        _RE,
        245_084_000_000.0,
        **_I24,
    ),
    _e("googl-cfo", TEXTBOOK, "GOOGL", _GOOGL, _CFO, 125_299_000_000.0, **_D24),
    _e(
        "googl-eps-diluted",
        TEXTBOOK,
        "GOOGL",
        _GOOGL,
        "us-gaap:EarningsPerShareDiluted",
        8.04,
        unit="USD/shares",
        **_D24,
        verification=_EPS_ROUTE,
    ),
    _e("xom-retained-earnings", TEXTBOOK, "XOM", _XOM, _RE, 470_903_000_000.0, **_I24),
    _e("xom-cfo", TEXTBOOK, "XOM", _XOM, _CFO, 55_022_000_000.0, **_D24),
    _e(
        "xom-eps-diluted",
        TEXTBOOK,
        "XOM",
        _XOM,
        "us-gaap:EarningsPerShareDiluted",
        7.84,
        unit="USD/shares",
        **_D24,
        verification=_EPS_PINNED,
    ),
    # Textbook tier, repair extension — the same four firms. APD and DIS
    # file their operating and financing cash flows under the
    # ContinuingOperations concepts; JPM and DIS carry pretax income in
    # place of an operating-income line they do not present.
    _e("jpm-pretax-income", TEXTBOOK, "JPM", _JPM, _PRETAX, 75_081_000_000.0, **_JPM_D),
    _e(
        "jpm-retained-earnings", TEXTBOOK, "JPM", _JPM, _RE, 376_166_000_000.0, **_JPM_I
    ),
    _e("jpm-cfo", TEXTBOOK, "JPM", _JPM, _CFO, -42_012_000_000.0, **_JPM_D),
    _e("jpm-cfi", TEXTBOOK, "JPM", _JPM, _CFI, -163_403_000_000.0, **_JPM_D),
    _e("jpm-cff", TEXTBOOK, "JPM", _JPM, _CFF, 63_447_000_000.0, **_JPM_D),
    _e(
        "jpm-eps-basic",
        TEXTBOOK,
        "JPM",
        _JPM,
        "us-gaap:EarningsPerShareBasic",
        19.79,
        unit="USD/shares",
        **_JPM_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "jpm-eps-diluted",
        TEXTBOOK,
        "JPM",
        _JPM,
        "us-gaap:EarningsPerShareDiluted",
        19.75,
        unit="USD/shares",
        **_JPM_D,
        verification=_EPS_ROUTE,
    ),
    _e("apd-operating-income", TEXTBOOK, "APD", _APD, _OI, 4_466_100_000.0, **_APD_D),
    _e("apd-retained-earnings", TEXTBOOK, "APD", _APD, _RE, 19_545_700_000.0, **_APD_I),
    _e("apd-cfo", TEXTBOOK, "APD", _APD, _CFO_CONT, 3_646_700_000.0, **_APD_D),
    _e("apd-cfi", TEXTBOOK, "APD", _APD, _CFI_CONT, -4_919_200_000.0, **_APD_D),
    _e("apd-cff", TEXTBOOK, "APD", _APD, _CFF_CONT, 2_615_400_000.0, **_APD_D),
    _e(
        "apd-eps-basic",
        TEXTBOOK,
        "APD",
        _APD,
        "us-gaap:EarningsPerShareBasic",
        17.21,
        unit="USD/shares",
        **_APD_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "apd-eps-diluted",
        TEXTBOOK,
        "APD",
        _APD,
        "us-gaap:EarningsPerShareDiluted",
        17.18,
        unit="USD/shares",
        **_APD_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "amzn-operating-income",
        TEXTBOOK,
        "AMZN",
        _AMZN23,
        _OI,
        36_852_000_000.0,
        **_AMZN23_D,
    ),
    _e(
        "amzn-retained-earnings",
        TEXTBOOK,
        "AMZN",
        _AMZN23,
        _RE,
        113_618_000_000.0,
        **_AMZN23_I,
    ),
    _e("amzn-cfo", TEXTBOOK, "AMZN", _AMZN23, _CFO, 84_946_000_000.0, **_AMZN23_D),
    _e("amzn-cfi", TEXTBOOK, "AMZN", _AMZN23, _CFI, -49_833_000_000.0, **_AMZN23_D),
    _e("amzn-cff", TEXTBOOK, "AMZN", _AMZN23, _CFF, -15_879_000_000.0, **_AMZN23_D),
    _e(
        "amzn-eps-basic",
        TEXTBOOK,
        "AMZN",
        _AMZN23,
        "us-gaap:EarningsPerShareBasic",
        2.95,
        unit="USD/shares",
        **_AMZN23_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "amzn-eps-diluted",
        TEXTBOOK,
        "AMZN",
        _AMZN23,
        "us-gaap:EarningsPerShareDiluted",
        2.9,
        unit="USD/shares",
        **_AMZN23_D,
        verification=_EPS_ROUTE,
    ),
    _e("dis-pretax-income", TEXTBOOK, "DIS", _DIS, _PRETAX, 7_569_000_000.0, **_DIS_D),
    _e("dis-retained-earnings", TEXTBOOK, "DIS", _DIS, _RE, 49_722_000_000.0, **_DIS_I),
    _e("dis-cfo", TEXTBOOK, "DIS", _DIS, _CFO_CONT, 13_971_000_000.0, **_DIS_D),
    _e("dis-cfi", TEXTBOOK, "DIS", _DIS, _CFI, -6_881_000_000.0, **_DIS_D),
    _e("dis-cff", TEXTBOOK, "DIS", _DIS, _CFF_CONT, -15_288_000_000.0, **_DIS_D),
    _e(
        "dis-eps-basic",
        TEXTBOOK,
        "DIS",
        _DIS,
        "us-gaap:EarningsPerShareBasic",
        2.72,
        unit="USD/shares",
        **_DIS_D,
        verification=_EPS_ROUTE,
    ),
    _e(
        "dis-eps-diluted",
        TEXTBOOK,
        "DIS",
        _DIS,
        "us-gaap:EarningsPerShareDiluted",
        2.72,
        unit="USD/shares",
        **_DIS_D,
        verification=_EPS_ROUTE,
    ),
    # Complex tier — concept switch, dimensioned slices, fair-value and
    # adjustment-bearing concepts, a derivation-backed total.
    _e(
        "bac-2011-cash-predecessor",
        COMPLEX,
        "BAC",
        _BAC11,
        _CASH,
        120_102_000_000.0,
        instant="2011-12-31",
        verification="rendered text L7045 (WS1 specimen audit); also in RELATION_SET",
    ),
    _e(
        "bac-2024-cash-rollup",
        COMPLEX,
        "BAC",
        _BAC24,
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        290_114_000_000.0,
        instant="2024-12-31",
        verification="rendered text L4564 (WS1 register F); also in RELATION_SET",
    ),
    _e(
        "aapl-segment-revenue-china",
        COMPLEX,
        "AAPL",
        _AAPL,
        _REV,
        66_952_000_000.0,
        **_AAPL_D,
        dimensions=(
            ("us-gaap:StatementBusinessSegmentsAxis", "aapl:GreaterChinaSegmentMember"),
        ),
        verification="facts.parquet: dimensioned segment fact (StatementBusinessSegmentsAxis)",
    ),
    _e(
        "msft-cash-only-slice",
        COMPLEX,
        "MSFT",
        _MSFT,
        "us-gaap:Cash",
        11_571_000_000.0,
        **_MSFT_I,
        dimensions=(("us-gaap:FinancialInstrumentAxis", "us-gaap:CashMember"),),
        verification="facts.parquet: dimensioned fact (FinancialInstrumentAxis=CashMember); pair-set provenance, MSFT text L1661",
    ),
    _e(
        "met-level3-transfers-in",
        COMPLEX,
        "MET",
        _MET,
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAssetTransfersIntoLevel3",
        232_000_000.0,
        **_D24,
        dimensions=(
            (
                "us-gaap:FairValueByAssetClassAxis",
                "us-gaap:CorporateDebtSecuritiesMember",
            ),
        ),
        verification="facts.parquet: dimensioned Level 3 reconciliation fact (FairValueByAssetClassAxis)",
    ),
    _e(
        "bac-xva-derivative-assets",
        COMPLEX,
        "BAC",
        _BAC24,
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeAssets",
        328_000_000.0,
        instant="2024-12-31",
        verification=_FACTS + "; adjustment-bearing concept (ASC 820 XVA family)",
    ),
    _e(
        "duk-revenue-including-assessed-tax",
        COMPLEX,
        "DUK",
        _DUK,
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        30_050_000_000.0,
        **_D24,
        verification="rendered text L6149 (WS4 pair-set provenance): excise taxes recognized on a gross basis",
    ),
    _e(
        "msft-liabilities-and-equity-verified",
        COMPLEX,
        "MSFT",
        _MSFT,
        "us-gaap:LiabilitiesAndStockholdersEquity",
        512_163_000_000.0,
        mode="VERIFY_DERIVATION",
        expected_status="VERIFIED",
        **_MSFT_I,
        verification=_FACTS
        + "; derivation check against the filing's calculation arcs",
    ),
)
