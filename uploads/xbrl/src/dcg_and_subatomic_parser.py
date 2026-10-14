#!/usr/bin/env python3
"""
Layer 0: Compositional 7-Slot Definite Clause Grammar (DCG) Parser,
6D Coordinate Unpacker, and Sub-Atomic Prime Head & Modifier Factorizer.

Zero external dependencies (Python standard library only).
"""

from dataclasses import dataclass, field
from functools import lru_cache
import datetime
import re
from typing import Any, Dict, List, Optional, Set, Tuple

STOPWORD_PREPOSITIONS = {
    "Of", "On", "In", "To", "From", "And", "For", "By", "With", "At", "Or", "Related", "The", "Into"
}

# ==============================================================================
# 1. SUB-ATOMIC PRIME HEADS (15 Indivisible Economic Primitives)
# ==============================================================================
PRIME_HEADS_SCHEMA = [
    ("H_REVENUE", "REVENUE", "FLOW_INFLOW", "IncomeStatement", "CREDIT", 0,
     "Gross or net top-line economic inflow from goods, services, leases, or premiums"),
    ("H_COST", "COST", "FLOW_DIRECT_COST", "IncomeStatement", "DEBIT", 0,
     "Direct cost of goods/services sold or capitalized acquisition cost"),
    ("H_EXPENSE", "EXPENSE", "FLOW_OUTFLOW", "IncomeStatement", "DEBIT", 0,
     "Operating or non-operating period expense outflow (R&D, SG&A, D&A, Tax, Interest)"),
    ("H_GAIN_LOSS", "GAIN_LOSS", "FLOW_DUAL_PRIMITIVE", "IncomeStatement_Or_OCI", "SIGNED_DELTA", 1,
     "Dual-role primitive & component: Realized/Unrealized/Reclassified gain or loss"),
    ("H_NET_INCOME", "NET_INCOME", "FLOW_BOTTOM_LINE", "IncomeStatement", "CREDIT", 0,
     "Bottom-line or intermediate profit subtotal (GrossProfit, OperatingIncome, NetIncome)"),
    ("H_OCI_FLOW", "OCI_FLOW", "FLOW_DUAL_PRIMITIVE", "ComprehensiveIncome", "SIGNED_DELTA", 1,
     "Dual-role primitive & component: Period other comprehensive income flow (unrealized FX, AFS, hedges)"),
    ("H_AOCI_STOCK", "AOCI_STOCK", "STOCK_DUAL_PRIMITIVE", "BalanceSheet", "SIGNED_DELTA", 1,
     "Dual-role primitive & component: Cumulative unrealized OCI reserve inside StockholdersEquity"),
    ("H_CASH", "CASH", "FLOW_OR_STOCK_LIQUIDITY", "CashFlow_Or_BalanceSheet", "DEBIT", 0,
     "Cash and cash equivalents anchor or cash flow statement movement"),
    ("H_ASSET", "ASSET", "STOCK_RESOURCE", "BalanceSheet", "DEBIT", 0,
     "Present economic resource controlled by the entity (Receivables, Inventory, PP&E, Goodwill, Intangibles)"),
    ("H_LIABILITY", "LIABILITY", "STOCK_OBLIGATION", "BalanceSheet", "CREDIT", 0,
     "Present economic obligation (Payables, Unearned Revenue, Debt, Lease Liabilities, ARO, Loss Reserves)"),
    ("H_EQUITY", "EQUITY", "STOCK_RESIDUAL_CLAIM", "BalanceSheet", "CREDIT", 0,
     "Residual claim on assets after deducting liabilities (CommonStock, RetainedEarnings, StockholdersEquity)"),
    ("H_CONTRA", "CONTRA", "VALUATION_OFFSET", "BalanceSheet_Or_Income", "CONTRA", 0,
     "Valuation allowance, accumulated depreciation/amortization, or treasury stock offset"),
    ("H_COMMITMENT", "COMMITMENT", "STOCK_BACKLOG_MEMO", "FootnoteDisclosure", "CREDIT", 0,
     "Contracted revenue backlog (RPO) or uncommenced lease/purchase commitment"),
    ("H_SHARE_UNIT", "SHARE_UNIT", "DENOMINATION_COUNT", "Income_Or_Cover", "NONE", 0,
     "Common share count (basic, diluted, issued, outstanding) or per-share denominator"),
    ("H_METRIC_RATIO", "METRIC_RATIO", "NON_GAAP_OR_KPI", "FootnoteDisclosure", "NONE", 0,
     "Operational count, headcount, union share, or non-GAAP/ratio metric"),
]

# ==============================================================================
# 2. SUB-ATOMIC MODIFIERS (32 Compositional Domain & Valuation Modifiers)
# ==============================================================================
SUBATOMIC_MODIFIERS_SCHEMA = [
    ("M_SALES_GOODS", "REVENUE_TYPE", "Sales|Goods|Product|Merchandise|Hardware|Automotive", "Physical goods or product sales"),
    ("M_SERVICE_CLOUD", "REVENUE_TYPE", "Service|Services|Cloud|Subscription|SaaS|Server|Office|Dynamics", "Cloud, subscription, or service revenue"),
    ("M_REAL_ESTATE", "REVENUE_TYPE", "RealEstate|Rental|Leasing|Property|Homebuilding", "Real estate rental or property revenue/assets"),
    ("M_INSURANCE_PREMIUM", "REVENUE_TYPE", "Premium|Premiums|Policyholder|Underwriting", "Insurance earned premiums or underwriting"),
    ("M_BANKING_INTEREST", "DOMAIN_VERTICAL", "InterestIncome|InterestExpense|Interest|NetInterest", "Interest income, expense, or net interest margin"),
    ("M_BANKING_NONINTEREST", "DOMAIN_VERTICAL", "Noninterest|Fee|Commission", "Banking noninterest income or expense"),
    ("M_RD", "EXPENSE_NATURE", "Research|Development", "Research and development activities"),
    ("M_SGA", "EXPENSE_NATURE", "Selling|General|Administrative|Marketing", "Selling, general, and administrative activities"),
    ("M_DA_DEPLETION", "EXPENSE_NATURE", "Depreciation|Depletion|Amortization|Amortisation", "Depreciation, depletion, and amortization"),
    ("M_SBC", "EXPENSE_NATURE", "ShareBased|StockBased|EmployeeBenefits", "Share-based compensation or employee benefits"),
    ("M_TAX_INCOME", "EXPENSE_NATURE", "IncomeTax|IncomeTaxes|Tax|Taxes|DeferredIncomeTax", "Current or deferred income taxes"),
    ("M_REALIZED", "REALIZATION_STATE", "Realized|Recognized|SaleOf|Maturities|Paid|Received", "Realized in cash or recognized in P&L"),
    ("M_UNREALIZED", "REALIZATION_STATE", "Unrealized|Unrecognized|FairValue|Remeasurement|Translation", "Unrealized fair-value or OCI mark-to-market"),
    ("M_RECLASSIFIED_OCI", "REALIZATION_STATE", "Reclassified|Reclassification|FromAOCI|FromAccumulatedOCI", "Recycled from AOCI into Net Income"),
    ("M_DERIVATIVE_HEDGE", "INSTRUMENT_TYPE", "Derivative|Derivatives|Hedge|Hedging|Forward|Swap|Option", "Derivative or hedging instrument"),
    ("M_AFS_SECURITY", "INSTRUMENT_TYPE", "AvailableForSale|MarketableSecurities|DebtSecurities|Investments", "Available-for-sale or marketable securities"),
    ("M_FX_CURRENCY", "INSTRUMENT_TYPE", "ForeignCurrency|ExchangeRate|ForeignExchange|Translation", "Foreign exchange transaction or translation"),
    ("M_RECEIVABLE", "WORKING_CAPITAL", "Receivable|Receivables|VendorNonTrade", "Trade, financing, or vendor non-trade receivables"),
    ("M_INVENTORY", "WORKING_CAPITAL", "Inventory|Inventories|RawMaterials|Consumables", "Merchandise, materials, or WIP inventory"),
    ("M_PAYABLE_ACCRUED", "WORKING_CAPITAL", "Payable|Payables|Accrued|Compensation", "Accounts payable or accrued liabilities"),
    ("M_CONTRACT_UNEARNED", "WORKING_CAPITAL", "ContractWithCustomerLiability|Unearned|DeferredRevenue", "Unearned / deferred contract revenue"),
    ("M_PPE_TANGIBLE", "LONG_LIVED_ASSET", "PropertyPlantAndEquipment|Property|ProductiveAssets", "Tangible property, plant, and equipment"),
    ("M_INTANGIBLE_GOODWILL", "LONG_LIVED_ASSET", "Goodwill|Intangible|Intangibles|FiniteLived", "Goodwill and intangible assets"),
    ("M_CONTENT_FILM", "DOMAIN_VERTICAL", "FilmCost|FilmCosts|ContentCost|ContentAssets|ProducedAndLicensed", "ASC 926 film and streaming content"),
    ("M_LEASE_ROU", "LONG_LIVED_ASSET", "OperatingLease|FinanceLease|RightOfUse|Lease", "ASC 842 right-of-use assets and lease liabilities"),
    ("M_DEBT_BORROWING", "FINANCING_CLAIM", "Debt|LongTermDebt|ShortTermBorrowings|CommercialPaper|Notes", "Short-term or long-term debt borrowings"),
    ("M_ARO_DECOMMISSIONING", "DOMAIN_VERTICAL", "AssetRetirementObligation|AssetRetirementObligations|Decommissioning", "ASC 410 asset retirement obligation"),
    ("M_TREASURY_REPURCHASE", "EQUITY_COMPONENT", "TreasuryStock|RepurchaseOfCommonStock|Repurchase", "Share repurchase or treasury stock contra-equity"),
    ("M_RETAINED_EARNINGS", "EQUITY_COMPONENT", "RetainedEarnings|AccumulatedDeficit", "Cumulative retained earnings"),
    ("M_DIVIDEND", "EQUITY_COMPONENT", "Dividend|Dividends", "Common or preferred dividends"),
    ("M_COMMON_DILUTION", "EQUITY_COMPONENT", "CommonStock|PaidInCapital|WeightedAverageNumber|Diluted|Basic", "Common equity and share dilution"),
    ("M_CURRENT_HORIZON", "MATURITY_HORIZON", "Current|ShortTerm|NinetyDays|ThreeMonths|YearOne", "Current (<= 12 months) liquidity/maturity"),
]

# ==============================================================================
# 3. TYPED RELATIONAL EDGES (IS_A, PART_OF, CONTRA_OF, DUAL_OF, DERIVED_FROM)
# ==============================================================================
TYPED_RELATIONS_SCHEMA = [
    # IS_A Specialization Hierarchy (Sub-Atomic subtypes -> Canonical Parent)
    ("E01", "SalesRevenueGoods", "Revenues", "IS_A", 1.0, "ALL", "Product sales revenue is a subtype of Revenues (H_REVENUE, {M_SALES_GOODS})"),
    ("E02", "ServiceAndCloudRevenue", "Revenues", "IS_A", 1.0, "ALL", "Service/cloud revenue is a subtype of Revenues (H_REVENUE, {M_SERVICE_CLOUD})"),
    ("E03", "RealEstateRevenue", "Revenues", "IS_A", 1.0, "SIC_6798", "Real estate rental revenue is a subtype of Revenues (H_REVENUE, {M_REAL_ESTATE})"),
    ("E04", "InsurancePremiumsEarned", "Revenues", "IS_A", 1.0, "SIC_6331", "Earned premiums are a subtype of Revenues (H_REVENUE, {M_INSURANCE_PREMIUM})"),
    ("E05", "BankingRevenuesNetOfInterest", "Revenues", "IS_A", 1.0, "SIC_6021", "Bank revenues net of interest expense is a subtype of Revenues"),
    ("E06", "ResearchAndDevelopmentExpense", "OperatingExpenses", "IS_A", 1.0, "ALL", "R&D expense is a nature subtype of OperatingExpenses (H_EXPENSE, {M_RD})"),
    ("E07", "SellingAndMarketingExpense", "OperatingExpenses", "IS_A", 1.0, "ALL", "S&M expense is a nature subtype of OperatingExpenses (H_EXPENSE, {M_SGA})"),
    ("E08", "GeneralAndAdministrativeExpense", "OperatingExpenses", "IS_A", 1.0, "ALL", "G&A expense is a nature subtype of OperatingExpenses (H_EXPENSE, {M_SGA})"),
    ("E09", "SellingGeneralAndAdministrativeExpense", "OperatingExpenses", "IS_A", 1.0, "ALL", "SG&A expense is a subtype of OperatingExpenses (H_EXPENSE, {M_SGA})"),
    # PART_OF & CONTRA_OF Statement Rollup Algebra
    ("E10", "Revenues", "GrossProfit", "PART_OF", 1.0, "ALL", "Revenues contribute +1.0 to GrossProfit"),
    ("E11", "CostOfRevenue", "GrossProfit", "CONTRA_OF", -1.0, "ALL", "CostOfRevenue is deducted (-1.0) from Revenues to form GrossProfit"),
    ("E12", "GrossProfit", "OperatingIncomeLoss", "PART_OF", 1.0, "ALL", "GrossProfit contributes +1.0 to OperatingIncomeLoss"),
    ("E13", "OperatingExpenses", "OperatingIncomeLoss", "CONTRA_OF", -1.0, "ALL", "OperatingExpenses are deducted (-1.0) from GrossProfit"),
    ("E14", "ResearchAndDevelopmentExpense", "OperatingExpenses", "PART_OF", 1.0, "ALL", "R&D rolls up (+1.0) into OperatingExpenses"),
    ("E15", "SellingAndMarketingExpense", "OperatingExpenses", "PART_OF", 1.0, "ALL", "S&M rolls up (+1.0) into OperatingExpenses"),
    ("E16", "GeneralAndAdministrativeExpense", "OperatingExpenses", "PART_OF", 1.0, "ALL", "G&A rolls up (+1.0) into OperatingExpenses"),
    ("E17", "SellingGeneralAndAdministrativeExpense", "OperatingExpenses", "PART_OF", 1.0, "ALL", "SG&A rolls up (+1.0) into OperatingExpenses"),
    ("E18", "OperatingIncomeLoss", "PreTaxIncome", "PART_OF", 1.0, "ALL", "OperatingIncomeLoss contributes +1.0 to PreTaxIncome"),
    ("E19", "NonoperatingIncomeExpense", "PreTaxIncome", "PART_OF", 1.0, "ALL", "NonoperatingIncomeExpense contributes +1.0 to PreTaxIncome"),
    ("E20", "PreTaxIncome", "NetIncomeLoss", "PART_OF", 1.0, "ALL", "PreTaxIncome contributes +1.0 to NetIncomeLoss"),
    ("E21", "IncomeTaxExpense", "NetIncomeLoss", "CONTRA_OF", -1.0, "ALL", "IncomeTaxExpense is deducted (-1.0) from PreTaxIncome"),
    # Dual-Role GainLoss & OCI / AOCI Algebra
    ("E22", "RealizedInvestmentGainLoss", "NonoperatingIncomeExpense", "PART_OF", 1.0, "ALL", "Realized investment gain/loss is part of NonoperatingIncomeExpense (+1.0)"),
    ("E23", "UnrealizedEquityInvestmentGainLoss", "NonoperatingIncomeExpense", "PART_OF", 1.0, "ALL", "ASU 2016-01 equity fair-value gain/loss is part of NonoperatingIncomeExpense (+1.0)"),
    ("E24", "DerivativeGainLossRecognizedInIncome", "NonoperatingIncomeExpense", "PART_OF", 1.0, "ALL", "P&L derivative gain/loss is part of NonoperatingIncomeExpense (+1.0)"),
    ("E25", "FXTransactionGainLoss", "NonoperatingIncomeExpense", "PART_OF", 1.0, "ALL", "ASC 830 FX transaction gain/loss is part of NonoperatingIncomeExpense (+1.0)"),
    ("E26", "RealizedGainOnSaleOfBusinessOrPPE", "Operating_Cash_Flow", "CONTRA_OF", -1.0, "ALL", "Realized gain on sale of business/PP&E is subtracted (-1.0) in OCF indirect reconciliation"),
    ("E27", "UnrealizedAFSDebtGainLossOCI", "OtherComprehensiveIncomeNet", "PART_OF", 1.0, "ALL", "Unrealized AFS debt gain/loss rolls into OtherComprehensiveIncomeNet (+1.0)"),
    ("E28", "FXTranslationAOCICTA", "OtherComprehensiveIncomeNet", "PART_OF", 1.0, "ALL", "Foreign currency translation adjustment rolls into OtherComprehensiveIncomeNet (+1.0)"),
    ("E29", "CashFlowHedgeGainLossOCI", "OtherComprehensiveIncomeNet", "PART_OF", 1.0, "ALL", "Effective cash flow hedge unrealized gain/loss rolls into OCI (+1.0)"),
    ("E30", "ReclassificationFromAOCIToNetIncome", "OtherComprehensiveIncomeNet", "CONTRA_OF", -1.0, "ALL", "Recycling reclassification out of AOCI reduces OCI (-1.0) and enters NetIncome (+1.0)"),
    ("E31", "NetIncomeLoss", "ComprehensiveIncomeNet", "PART_OF", 1.0, "ALL", "NetIncomeLoss contributes +1.0 to ComprehensiveIncomeNet"),
    ("E32", "OtherComprehensiveIncomeNet", "ComprehensiveIncomeNet", "PART_OF", 1.0, "ALL", "OtherComprehensiveIncomeNet contributes +1.0 to ComprehensiveIncomeNet"),
    ("E33", "OtherComprehensiveIncomeNet", "AccumulatedOtherComprehensiveIncome", "DUAL_OF", 1.0, "ALL", "Stock-flow conservation bridge: AOCI(t) - AOCI(t-1) = OCI(t)"),
    # Balance Sheet Hierarchy & Stock-Flow Duals
    ("E34", "AssetsCurrent", "Assets", "PART_OF", 1.0, "ALL", "Current assets roll into Total Assets (+1.0)"),
    ("E35", "AssetsNoncurrent", "Assets", "PART_OF", 1.0, "ALL", "Noncurrent assets roll into Total Assets (+1.0)"),
    ("E36", "LiabilitiesCurrent", "Liabilities", "PART_OF", 1.0, "ALL", "Current liabilities roll into Total Liabilities (+1.0)"),
    ("E37", "LiabilitiesNoncurrent", "Liabilities", "PART_OF", 1.0, "ALL", "Noncurrent liabilities roll into Total Liabilities (+1.0)"),
    ("E38", "Liabilities", "LiabilitiesAndStockholdersEquity", "PART_OF", 1.0, "ALL", "Total Liabilities roll into LiabilitiesAndStockholdersEquity (+1.0)"),
    ("E39", "StockholdersEquity", "LiabilitiesAndStockholdersEquity", "PART_OF", 1.0, "ALL", "StockholdersEquity rolls into LiabilitiesAndStockholdersEquity (+1.0)"),
    ("E40", "CommonStockAndAPIC", "StockholdersEquity", "PART_OF", 1.0, "ALL", "CommonStock and APIC roll into StockholdersEquity (+1.0)"),
    ("E41", "RetainedEarnings", "StockholdersEquity", "PART_OF", 1.0, "ALL", "RetainedEarnings roll into StockholdersEquity (+1.0)"),
    ("E42", "AccumulatedOtherComprehensiveIncome", "StockholdersEquity", "PART_OF", 1.0, "ALL", "AOCI reserve rolls into StockholdersEquity (+1.0)"),
    ("E43", "TreasuryStock", "StockholdersEquity", "CONTRA_OF", -1.0, "ALL", "TreasuryStock is a contra-equity deduction (-1.0) from StockholdersEquity"),
    ("E44", "ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiability", "PART_OF", 1.0, "ALL", "Short-term unearned revenue is part of total unearned revenue (+1.0)"),
    ("E45", "ContractWithCustomerLiabilityNoncurrent", "ContractWithCustomerLiability", "PART_OF", 1.0, "ALL", "Long-term unearned revenue is part of total unearned revenue (+1.0)"),
    # Cash Flow & Multi-Hop Derived Financial Metrics
    ("E46", "Operating_Cash_Flow", "Total_Cash_Flow_Delta", "PART_OF", 1.0, "ALL", "Operating cash flow contributes +1.0 to Total_Cash_Flow_Delta"),
    ("E47", "Investing_Cash_Flow", "Total_Cash_Flow_Delta", "PART_OF", 1.0, "ALL", "Investing cash flow contributes +1.0 to Total_Cash_Flow_Delta"),
    ("E48", "Financing_Cash_Flow", "Total_Cash_Flow_Delta", "PART_OF", 1.0, "ALL", "Financing cash flow contributes +1.0 to Total_Cash_Flow_Delta"),
    ("E49", "FX_Cash_Flow_Effect", "Total_Cash_Flow_Delta", "PART_OF", 1.0, "ALL", "FX exchange rate effect on cash contributes +1.0 to Total_Cash_Flow_Delta"),
    ("E50", "Total_Cash_Flow_Delta", "CashAndRestrictedCash", "DUAL_OF", 1.0, "ALL", "Cash continuity equation: Cash(t-1) + Total_Cash_Flow_Delta(t) = Cash(t)"),
    ("E51", "Operating_Cash_Flow", "FreeCashFlow", "DERIVED_FROM", 1.0, "ALL", "FreeCashFlow = Operating_Cash_Flow (+1.0) - CapitalExpenditures (-1.0)"),
    ("E52", "CapitalExpenditures", "FreeCashFlow", "DERIVED_FROM", -1.0, "ALL", "CapitalExpenditures deducted (-1.0) from Operating_Cash_Flow to derive FreeCashFlow"),
    ("E53", "ShortTermDebt", "TotalDebt", "DERIVED_FROM", 1.0, "ALL", "Short-term debt contributes +1.0 to TotalDebt"),
    ("E54", "LongTermDebtCurrent", "TotalDebt", "DERIVED_FROM", 1.0, "ALL", "Current portion of long-term debt contributes +1.0 to TotalDebt"),
    ("E55", "LongTermDebtNoncurrent", "TotalDebt", "DERIVED_FROM", 1.0, "ALL", "Noncurrent long-term debt contributes +1.0 to TotalDebt"),
]


@dataclass
class SevenSlotAndSubAtomicFrame:
    namespace: str
    raw_name: str
    tokens: List[str]
    # 7 DCG Semantic Slots
    flow_prefix: str = "NONE"
    polarity: str = "NEUTRAL"
    realization_state: str = "UNKNOWN"
    domain_kernel: List[str] = field(default_factory=list)
    aggregation_state: str = "DEFAULT_NET"
    includes: List[str] = field(default_factory=list)
    excludes: List[str] = field(default_factory=list)
    carrying_basis: str = "DEFAULT"
    horizon: str = "UNSPECIFIED"
    expected_weight: int = 1
    # Sub-Atomic Prime Head & Modifiers + 6D Coordinate Tuple
    prime_head: str = "H_ASSET"
    modifiers: List[str] = field(default_factory=list)
    recognition_book: str = "B_FACE_STATEMENT"
    coord_6d: Tuple[str, str, str, str, str, str] = ("K_UNKNOWN", "T_UNSPECIFIED", "V_DEFAULT", "P_UNKNOWN", "U_MONETARY", "A_CONSOLIDATED")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "namespace": self.namespace,
            "raw_name": self.raw_name,
            "flow_prefix": self.flow_prefix,
            "polarity": self.polarity,
            "realization_state": self.realization_state,
            "domain_kernel": self.domain_kernel,
            "aggregation_state": self.aggregation_state,
            "set_modifiers": {"includes": self.includes, "excludes": self.excludes},
            "valuation_basis": {"carrying": self.carrying_basis, "horizon": self.horizon},
            "expected_weight": self.expected_weight,
            "prime_head": self.prime_head,
            "modifiers": self.modifiers,
            "recognition_book": self.recognition_book,
            "coord_6d": list(self.coord_6d),
        }


@lru_cache(maxsize=4096)
def split_camel_case(raw_name: str) -> Tuple[str, ...]:
    cleaned = raw_name.replace("_", "")
    return tuple(re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|[A-Z][a-z]+|\d+", cleaned))


def infer_prime_head_and_modifiers(
    tokens: Tuple[str, ...],
    flow_prefix: str,
    realization_state: str,
    horizon: str,
    schema_balance: str,
    pres_role: str = "",
    unit: str = "USD",
) -> Tuple[str, List[str], str, Tuple[str, str, str, str, str, str]]:
    joined = "".join(tokens)
    tok_set = set(tokens)

    # 1. Extract Sub-Atomic Modifiers
    mods: List[str] = []
    for mod_id, _cat, pat_pipe, _desc in SUBATOMIC_MODIFIERS_SCHEMA:
        sub_pats = pat_pipe.split("|")
        if any(sp in joined or sp in tok_set for sp in sub_pats):
            mods.append(mod_id)

    # 2. Infer Indivisible Prime Head (H_*)
    prime_head = "H_ASSET"
    if unit in ("shares", "shares_K", "shares_M") or "Shares" in tok_set or "Warrants" in tok_set:
        prime_head = "H_SHARE_UNIT"
    elif unit in ("pure", "RATIO_SHARE", "COUNT", "coins", "units", "berth_days") or (
        any(t in tok_set for t in ("Percentage", "Percent", "Ratio", "Employees", "Headcount", "Count", "NonGAAP"))
    ):
        prime_head = "H_METRIC_RATIO"
    elif "RemainingPerformanceObligation" in joined or "Uncommenced" in joined or "Commitment" in joined:
        prime_head = "H_COMMITMENT"
    elif "AccumulatedOtherComprehensive" in joined or ("AOCI" in joined and "Reclassified" not in joined):
        prime_head = "H_AOCI_STOCK"
    elif "OtherComprehensiveIncome" in joined or "ExchangeDifferencesOnTranslating" in joined:
        prime_head = "H_OCI_FLOW"
    elif any(t in tok_set for t in ("Gain", "Gains", "Loss", "Losses")) and not any(
        t in joined for t in ("OperatingIncomeLoss", "NetIncomeLoss", "ProfitLoss", "IncomeLossFromContinuingOperations")
    ):
        prime_head = "H_GAIN_LOSS"
    elif any(t in joined for t in ("CashAndCashEquivalents", "RestrictedCash", "CashProvidedByUsedIn", "CashFlowsFromUsedIn", "ExchangeRateOnCash", "ExchangeRateChangesOnCash")) or (
        pres_role == "StatementOfCashFlows" and flow_prefix in ("INFLOW_PROCEEDS", "OUTFLOW_PAYMENTS", "OUTFLOW_NET_INVESTING", "BIDIRECTIONAL_FINANCING_FLOW", "NET_CASH_SUMMARY")
    ):
        prime_head = "H_CASH"
    elif any(t in joined for t in ("Revenue", "Revenues", "PremiumsEarned", "NetInvestmentIncome")) and not any(
        t in joined for t in ("Unearned", "DeferredRevenue", "CostOf", "ContractWithCustomerLiability")
    ):
        prime_head = "H_REVENUE"
    elif any(t in joined for t in ("CostOfGoods", "CostOfSales", "CostOfRevenue", "RawMaterialsAndConsumables")):
        prime_head = "H_COST"
    elif any(t in joined for t in ("GrossProfit", "OperatingIncomeLoss", "ProfitLossFromOperating", "PreProvisionProfit", "NetIncomeLoss", "ProfitLoss", "IncomeLossFromContinuing", "ComprehensiveIncomeNet")):
        prime_head = "H_NET_INCOME"
    elif any(t in tok_set for t in ("Expense", "Expenses", "Tax", "Taxes", "Depreciation", "Amortization", "Amortisation", "Provision", "Benefits")) and pres_role != "BalanceSheet":
        prime_head = "H_EXPENSE"
    elif any(t in joined for t in ("TreasuryStock", "AccumulatedDepreciation", "AccumulatedAmortization", "AllowanceFor")):
        prime_head = "H_CONTRA"
    elif any(t in joined for t in ("StockholdersEquity", "CommonStock", "RetainedEarnings", "PaidInCapital")) or (
        joined == "Equity"
    ):
        prime_head = "H_EQUITY"
    elif any(t in joined for t in ("Liabilities", "Liability", "Payable", "UnearnedRevenue", "LongTermDebt", "ShortTermBorrowings", "ShortTermDebt", "CommercialPaper", "Deposits", "AssetRetirementObligation", "UnpaidClaims")):
        prime_head = "H_LIABILITY"
    elif schema_balance == "CREDIT" and pres_role == "BalanceSheet":
        prime_head = "H_LIABILITY"
    else:
        prime_head = "H_ASSET"

    # 3. Recognition Book
    if prime_head == "H_OCI_FLOW":
        book = "B_OCI_UNREALIZED"
    elif prime_head == "H_AOCI_STOCK":
        book = "B_EQUITY_AOCI_RESERVE"
    elif pres_role == "StatementOfCashFlows":
        book = "B_CASH_FLOW_STATEMENT"
    elif pres_role == "BalanceSheet":
        book = "B_BALANCE_SHEET"
    elif pres_role == "StatementOfOperations":
        book = "B_INCOME_STATEMENT"
    else:
        book = "B_FOOTNOTE_DISCLOSURE"

    # 4. 6D Coordinate Tuple (Kernel, Time, Valuation, Statement, Unit, Axis)
    k_dim = f"K_{prime_head.replace('H_', '')}"
    t_dim = f"T_{horizon}" if horizon != "UNSPECIFIED" else ("T_INSTANT" if pres_role == "BalanceSheet" else "T_DURATION")
    v_dim = "V_FAIR_VALUE" if "M_UNREALIZED" in mods else ("V_GROSS" if "Gross" in tok_set else "V_NET_CARRYING")
    p_dim = f"P_{book.replace('B_', '')}"
    u_dim = f"U_{unit.upper().replace('/', '_PER_')}"
    a_dim = "A_CONSOLIDATED"

    return prime_head, mods, book, (k_dim, t_dim, v_dim, p_dim, u_dim, a_dim)


def decompose_xbrl_concept(
    qname: str,
    schema_balance: str = "NONE",
    pres_role: str = "",
    unit: str = "USD",
) -> SevenSlotAndSubAtomicFrame:
    """
    Deterministic Layer 0 parser implementing Algorithm 1 (7-Slot DCG) +
    6D Coordinate Unpacking + Sub-Atomic Prime Head & Modifier Factorization.
    """
    if ":" in qname:
        namespace, raw_name = qname.split(":", 1)
    else:
        namespace, raw_name = "default", qname

    tokens = list(split_camel_case(raw_name))
    phi = SevenSlotAndSubAtomicFrame(namespace=namespace, raw_name=raw_name, tokens=tokens)

    cursor = 0
    joined_prefix = "".join(tokens[:5])
    if joined_prefix.startswith("ProceedsFromRepaymentsOf") or joined_prefix.startswith("ProceedsFromPaymentsFor"):
        phi.flow_prefix = "BIDIRECTIONAL_FINANCING_FLOW"
        phi.expected_weight = 1
        cursor = 4
    elif joined_prefix.startswith("PaymentsForProceedsFrom"):
        phi.flow_prefix = "OUTFLOW_NET_INVESTING"
        phi.expected_weight = -1
        cursor = 4
    elif joined_prefix.startswith("ProceedsFrom") or joined_prefix.startswith("CashProvidedBy"):
        phi.flow_prefix = "INFLOW_PROCEEDS"
        phi.expected_weight = 1
        cursor = 2
    elif (
        joined_prefix.startswith("PaymentsFor")
        or joined_prefix.startswith("RepaymentsOf")
        or joined_prefix.startswith("PaymentsTo")
        or joined_prefix.startswith("PaymentsOf")
        or joined_prefix.startswith("PaymentsRelated")
        or joined_prefix.startswith("PurchaseOf")
        or joined_prefix.startswith("AdditionsTo")
    ):
        phi.flow_prefix = "OUTFLOW_PAYMENTS"
        phi.expected_weight = -1
        cursor = 3 if joined_prefix.startswith("PaymentsToAcquire") else 2
    elif joined_prefix.startswith("IncreaseDecreaseIn") or joined_prefix.startswith("ChangeIn"):
        phi.flow_prefix = "WORKING_CAPITAL_NET_DELTA"
        phi.expected_weight = 1
        cursor = 3 if joined_prefix.startswith("IncreaseDecreaseIn") else 2
    elif (
        joined_prefix.startswith("Depreciation")
        or joined_prefix.startswith("AmortizationOf")
        or joined_prefix.startswith("ProvisionFor")
        or joined_prefix.startswith("ShareBased")
        or joined_prefix.startswith("DeferredIncomeTax")
        or joined_prefix.startswith("OtherOperatingActivities")
    ):
        phi.flow_prefix = "NONCASH_OPERATING_ADJUSTMENT"
        phi.realization_state = "NONCASH_ACCRUAL"
        phi.expected_weight = 1
    elif joined_prefix.startswith("NetCashProvidedByUsedIn") or joined_prefix.startswith("CashFlowsFromUsedIn"):
        phi.flow_prefix = "NET_CASH_SUMMARY"
        phi.expected_weight = 1
        cursor = 5

    for tok in tokens:
        if tok in {"Gain", "Gains", "Income", "Benefit", "Proceeds"}:
            phi.polarity = "POSITIVE_GAIN" if phi.polarity in {"NEUTRAL", "POSITIVE_GAIN"} else "BIDIRECTIONAL_GAIN_LOSS"
        elif tok in {"Loss", "Losses", "Expense", "Expenses", "Cost", "Payments", "Repayments"}:
            phi.polarity = "NEGATIVE_LOSS" if phi.polarity in {"NEUTRAL", "NEGATIVE_LOSS"} else "BIDIRECTIONAL_GAIN_LOSS"

        if tok in {"Unrealized", "Unrecognized", "Noncash", "NonCash", "Deferred", "ShareBased", "Depreciation", "Amortization"}:
            phi.realization_state = "NONCASH_OR_UNREALIZED"
        elif tok in {"Realized", "Paid", "Received", "Recognized"}:
            phi.realization_state = "CASH_REALIZED"

    if raw_name.startswith("GainLossOnSaleOf") or raw_name.startswith("IncomeLossFromEquityMethodInvestmentsNetOfDividends"):
        phi.flow_prefix = "NONCASH_GAIN_DEDUCTION"
        phi.expected_weight = -1

    clause_mode = "KERNEL_MODE"
    i = cursor
    while i < len(tokens):
        tok = tokens[i]
        if tok == "Including":
            clause_mode = "INCLUDE_MODE"
        elif tok in {"Excluding", "OtherThan"}:
            clause_mode = "EXCLUDE_MODE"
        elif tok == "Net" and i + 1 < len(tokens) and tokens[i + 1] == "Of":
            phi.aggregation_state = "NET_OF_EXPLICIT_ITEM"
            clause_mode = "EXCLUDE_MODE"
            i += 1
        elif tok in {"Gross", "BeforeTax"}:
            phi.aggregation_state = "GROSS_PRE_TAX"
        elif tok in {"Net", "NetOfTax"}:
            phi.aggregation_state = "NET_AFTER_TAX"
        elif tok in {"Current", "Noncurrent"}:
            phi.horizon = tok.upper()
        elif tok in {"AtCarryingValue", "CarryingValue", "FairValue", "PrincipalAmount", "HeldForSale"}:
            phi.carrying_basis = tok.upper()
        else:
            if clause_mode == "KERNEL_MODE":
                if tok not in STOPWORD_PREPOSITIONS:
                    phi.domain_kernel.append(tok)
            elif clause_mode == "INCLUDE_MODE":
                phi.includes.append(tok)
            elif clause_mode == "EXCLUDE_MODE":
                phi.excludes.append(tok)
        i += 1

    prime_head, mods, book, coord_6d = infer_prime_head_and_modifiers(
        tuple(tokens), phi.flow_prefix, phi.realization_state, phi.horizon, schema_balance, pres_role, unit
    )
    phi.prime_head = prime_head
    phi.modifiers = mods
    phi.recognition_book = book
    phi.coord_6d = coord_6d
    return phi


def discretize_duration_bucket(start_date: Optional[str], end_date: str, is_instant: bool) -> Tuple[int, str]:
    if is_instant or not start_date:
        return 0, "0D_INSTANT"
    d1 = datetime.date.fromisoformat(start_date)
    d2 = datetime.date.fromisoformat(end_date)
    delta = (d2 - d1).days
    if 80 <= delta <= 100:
        return delta, "3M_QUARTERLY"
    elif 175 <= delta <= 195:
        return delta, "6M_SEMIANNUAL"
    elif 265 <= delta <= 285:
        return delta, "9M_YTD"
    elif 350 <= delta <= 380:
        return delta, "1Y_ANNUAL"
    return delta, "OTHER_STUB"
