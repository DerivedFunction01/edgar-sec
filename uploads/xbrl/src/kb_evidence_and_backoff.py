#!/usr/bin/env python3
"""
Declarative Knowledge Base with Evidence/Confidence Scoring, 4-Tier Scope Backoff (§C2, §C13),
Subsumption & Geographic Meronymy DAG (R2), and Cryptographic Seed Freeze before Holdout Scoring.

Zero external dependencies (Python standard library only).
"""

import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from dcg_and_subatomic_parser import (
    PRIME_HEADS_SCHEMA,
    SUBATOMIC_MODIFIERS_SCHEMA,
    TYPED_RELATIONS_SCHEMA,
)


class EvidenceAndBackoffKnowledgeBase:
    """
    Implements the 4 Declarative KB Tables + Evidence/Confidence Scoring + 4-Tier Scope Backoff:
      Tier 1: (Firm=e, Sector=s, Year=y)   -> specificity = 4
      Tier 2: (Firm=e, Sector=s, Year=*)   -> specificity = 3
      Tier 3: (Firm=*, Sector=s, Year=*)   -> specificity = 2
      Tier 4: (Firm=*, Sector=*, Year=*)   -> specificity = 1 (Universal US-GAAP / IFRS)
    Supports strict `freeze()` after calibrating on the SEED cohort so HOLDOUT evaluation
    is guaranteed zero-shot with cryptographic SHA-256 verification.
    """

    def __init__(self) -> None:
        self.is_frozen: bool = False
        self.frozen_sha256: Optional[str] = None

        # 1. OntologyTree & Typed Relational Edges
        self.typed_relations = [
            {
                "edge_id": eid,
                "source_node": src,
                "target_node": tgt,
                "relation_type": rtype,
                "weight": float(w),
                "sic_scope": sic,
                "rationale": rat,
            }
            for (eid, src, tgt, rtype, w, sic, rat) in TYPED_RELATIONS_SCHEMA
        ]

        # 2. Geographic Meronymy DAG (Child <= Parent) for R2 Antichain Pruning
        self.geography_subsumption = {
            ("country:MX", "srt:LatinAmericaMember"),
            ("country:BR", "srt:LatinAmericaMember"),
            ("srt:EuropeanUnionMember", "srt:EuropeMember"),
            ("srt:EuropeMember", "srt:EMEAMember"),
            ("srt:EuropeanUnionMember", "srt:EMEAMember"),
            ("country:JP", "srt:AsiaPacificMember"),
            ("country:KR", "srt:AsiaPacificMember"),
        }

        # 3. Declarative Anchor & Compositional Unification Rules with Evidence/Confidence & Scope Tuple
        self.unification_rules: List[Dict[str, Any]] = [
            # Exact Anchor Rules (Tier 4 Universal & Tier 3 Sector)
            {"rule_id": "R_ANCHOR_REV_1", "target_node": "ANCHOR:Revenues", "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 25},
            {"rule_id": "R_ANCHOR_REV_2", "target_node": "ANCHOR:Revenues", "qname": "us-gaap:Revenues", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 19},
            {"rule_id": "R_ANCHOR_REV_IFRS", "target_node": "ANCHOR:Revenues", "qname": "ifrs-full:Revenue", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_REV_REIT", "target_node": "ANCHOR:Revenues", "qname": "us-gaap:RealEstateRevenueNet", "pattern": {}, "weight": 1, "scope": ("*", "Real_Estate", "*"), "n_support": 5, "N_eligible": 5},
            {"rule_id": "R_ANCHOR_REV_BANK", "target_node": "ANCHOR:Revenues", "qname": "us-gaap:RevenuesNetOfInterestExpense", "pattern": {}, "weight": 1, "scope": ("*", "Financials", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_COST_1", "target_node": "ANCHOR:CostOfRevenue", "qname": "us-gaap:CostOfGoodsAndServicesSold", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 22, "N_eligible": 22},
            {"rule_id": "R_ANCHOR_GP", "target_node": "ANCHOR:GrossProfit", "qname": "us-gaap:GrossProfit", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 20, "N_eligible": 20},
            {"rule_id": "R_ANCHOR_OPEX", "target_node": "ANCHOR:OperatingExpenses", "qname": "us-gaap:OperatingExpenses", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 15, "N_eligible": 15},
            {"rule_id": "R_ANCHOR_OPEX_BANK", "target_node": "ANCHOR:OperatingExpenses", "qname": "us-gaap:NoninterestExpense", "pattern": {}, "weight": 1, "scope": ("*", "Financials", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_OPINC", "target_node": "ANCHOR:OperatingIncomeLoss", "qname": "us-gaap:OperatingIncomeLoss", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 25, "N_eligible": 25},
            {"rule_id": "R_ANCHOR_PREPROV_BANK", "target_node": "ANCHOR:PreProvisionProfit", "qname": "jpm:PreProvisionProfit", "pattern": {}, "weight": 1, "scope": ("JPM", "Financials", "*"), "n_support": 3, "N_eligible": 3},
            {"rule_id": "R_ANCHOR_PROV_LOAN_LOSS", "target_node": "ANCHOR:ProvisionForCreditLosses", "qname": "us-gaap:ProvisionForLoanLossesExpensed", "pattern": {}, "weight": -1, "scope": ("*", "Financials", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_DEPOSITS_BANK", "target_node": "ANCHOR:Liabilities", "qname": "us-gaap:Deposits", "pattern": {}, "weight": 1, "scope": ("*", "Financials", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_NONOP", "target_node": "ANCHOR:NonoperatingIncomeExpense", "qname": "us-gaap:NonoperatingIncomeExpense", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 12, "N_eligible": 12},
            {"rule_id": "R_ANCHOR_PRETAX", "target_node": "ANCHOR:PreTaxIncome", "qname": "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 16, "N_eligible": 16},
            {"rule_id": "R_ANCHOR_TAX", "target_node": "ANCHOR:IncomeTaxExpense", "qname": "us-gaap:IncomeTaxExpenseBenefit", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 20, "N_eligible": 20},
            {"rule_id": "R_ANCHOR_NI", "target_node": "ANCHOR:NetIncomeLoss", "qname": "us-gaap:NetIncomeLoss", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 28, "N_eligible": 28},
            {"rule_id": "R_ANCHOR_OCI", "target_node": "ANCHOR:OtherComprehensiveIncomeNet", "qname": "us-gaap:OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 14, "N_eligible": 14},
            {"rule_id": "R_ANCHOR_AOCI", "target_node": "ANCHOR:AccumulatedOtherComprehensiveIncome", "qname": "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
            {"rule_id": "R_ANCHOR_COMMON_APIC", "target_node": "ANCHOR:CommonStockAndAPIC", "qname": "us-gaap:CommonStocksIncludingAdditionalPaidInCapital", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 20, "N_eligible": 20},
            {"rule_id": "R_ANCHOR_RETAINED_EARN", "target_node": "ANCHOR:RetainedEarnings", "qname": "us-gaap:RetainedEarningsAccumulatedDeficit", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_ANCHOR_ASSETS", "target_node": "ANCHOR:Assets", "qname": "us-gaap:Assets", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 28, "N_eligible": 28},
            {"rule_id": "R_ANCHOR_ASSETS_IFRS", "target_node": "ANCHOR:Assets", "qname": "ifrs-full:Assets", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 6, "N_eligible": 6},
            {"rule_id": "R_ANCHOR_ASSETS_CURR", "target_node": "ANCHOR:AssetsCurrent", "qname": "us-gaap:AssetsCurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 22, "N_eligible": 22},
            {"rule_id": "R_ANCHOR_ASSETS_NONCURR", "target_node": "ANCHOR:AssetsNoncurrent", "qname": "us-gaap:AssetsNoncurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
            {"rule_id": "R_ANCHOR_LIAB_CURR", "target_node": "ANCHOR:LiabilitiesCurrent", "qname": "us-gaap:LiabilitiesCurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 22, "N_eligible": 22},
            {"rule_id": "R_ANCHOR_LIAB_NONCURR", "target_node": "ANCHOR:LiabilitiesNoncurrent", "qname": "us-gaap:LiabilitiesNoncurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
            {"rule_id": "R_ANCHOR_LIAB", "target_node": "ANCHOR:Liabilities", "qname": "us-gaap:Liabilities", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_ANCHOR_EQ", "target_node": "ANCHOR:StockholdersEquity", "qname": "us-gaap:StockholdersEquity", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 26, "N_eligible": 26},
            {"rule_id": "R_ANCHOR_LIAB_EQ", "target_node": "ANCHOR:LiabilitiesAndStockholdersEquity", "qname": "us-gaap:LiabilitiesAndStockholdersEquity", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 26, "N_eligible": 26},
            {"rule_id": "R_ANCHOR_UNEARNED_TOT", "target_node": "ANCHOR:ContractWithCustomerLiability", "qname": "us-gaap:ContractWithCustomerLiability", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 12, "N_eligible": 12},
            {"rule_id": "R_ANCHOR_UNEARNED_CURR", "target_node": "ANCHOR:ContractWithCustomerLiabilityCurrent", "qname": "us-gaap:ContractWithCustomerLiabilityCurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 15, "N_eligible": 15},
            {"rule_id": "R_ANCHOR_UNEARNED_NONCURR", "target_node": "ANCHOR:ContractWithCustomerLiabilityNoncurrent", "qname": "us-gaap:ContractWithCustomerLiabilityNoncurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 15, "N_eligible": 15},
            {"rule_id": "R_ANCHOR_ST_DEBT", "target_node": "ANCHOR:ShortTermDebt", "qname": "us-gaap:ShortTermBorrowings", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 14, "N_eligible": 14},
            {"rule_id": "R_ANCHOR_LTD_CURR", "target_node": "ANCHOR:LongTermDebtCurrent", "qname": "us-gaap:LongTermDebtCurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
            {"rule_id": "R_ANCHOR_LTD_NONCURR", "target_node": "ANCHOR:LongTermDebtNoncurrent", "qname": "us-gaap:LongTermDebtNoncurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 22, "N_eligible": 22},
            {"rule_id": "R_ANCHOR_ARO", "target_node": "ANCHOR:AssetRetirementObligation", "qname": "us-gaap:AssetRetirementObligationsNoncurrent", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 8, "N_eligible": 8},
            {"rule_id": "R_ANCHOR_FILM_1", "target_node": "ANCHOR:ContentAndFilmAssets", "qname": "us-gaap:FilmCosts", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 5, "N_eligible": 5},
            {"rule_id": "R_ANCHOR_FILM_2", "target_node": "ANCHOR:ContentAndFilmAssets", "qname": "us-gaap:ProducedAndLicensedContentCosts", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 4, "N_eligible": 4},
            {"rule_id": "R_ANCHOR_REIT_DA", "target_node": "ANCHOR:RealEstateDepreciation", "qname": "us-gaap:DepreciationAndAmortizationRealEstate", "pattern": {}, "weight": 1, "scope": ("*", "Real_Estate", "*"), "n_support": 5, "N_eligible": 5},
            {"rule_id": "R_ANCHOR_SHARES_BASIC", "target_node": "ANCHOR:WeightedAverageSharesBasic", "qname": "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_ANCHOR_SHARES_DIL_ADJ", "target_node": "ANCHOR:DilutiveIncrementalShares", "qname": "us-gaap:WeightedAverageNumberDilutedSharesOutstandingAdjustment", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 20, "N_eligible": 20},
            {"rule_id": "R_ANCHOR_SHARES_DIL", "target_node": "ANCHOR:WeightedAverageSharesDiluted", "qname": "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 25, "N_eligible": 25},
            {"rule_id": "R_ANCHOR_OCF", "target_node": "ANCHOR:Operating_Cash_Flow", "qname": "us-gaap:NetCashProvidedByUsedInOperatingActivities", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 28, "N_eligible": 28},
            {"rule_id": "R_ANCHOR_ICF", "target_node": "ANCHOR:Investing_Cash_Flow", "qname": "us-gaap:NetCashProvidedByUsedInInvestingActivities", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 28, "N_eligible": 28},
            {"rule_id": "R_ANCHOR_FCF", "target_node": "ANCHOR:Financing_Cash_Flow", "qname": "us-gaap:NetCashProvidedByUsedInFinancingActivities", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 28, "N_eligible": 28},
            {"rule_id": "R_ANCHOR_FX_CF", "target_node": "ANCHOR:FX_Cash_Flow_Effect", "qname": "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 20, "N_eligible": 20},
            {"rule_id": "R_ANCHOR_CF_DELTA", "target_node": "ANCHOR:Total_Cash_Flow_Delta", "qname": "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 25, "N_eligible": 25},
            {"rule_id": "R_ANCHOR_CAPEX", "target_node": "ANCHOR:CapitalExpenditures", "qname": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 26, "N_eligible": 26},

            # Compositional 7-Slot & Sub-Atomic Prime Head Rules
            {"rule_id": "R_SUBATOMIC_REV_HEAD", "target_node": "Revenues", "qname": None,
             "pattern": {"prime_head": "H_REVENUE", "pres_role": "SegmentFootnotes"}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
            {"rule_id": "R_SUBATOMIC_OPEX_NATURE", "target_node": "OperatingExpenses", "qname": None,
             "pattern": {"prime_head": "H_EXPENSE", "pres_role": "StatementOfOperations", "modifiers_any": ["M_RD", "M_SGA", "M_SBC", "M_DA_DEPLETION"]}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 22, "N_eligible": 22},
            {"rule_id": "R_SUBATOMIC_IFRS_RAW_MAT", "target_node": "OperatingExpenses", "qname": "ifrs-full:RawMaterialsAndConsumablesUsed",
             "pattern": {}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 4, "N_eligible": 4},
            {"rule_id": "R_COMP_WC_DELTA", "target_node": "Operating_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "WORKING_CAPITAL_NET_DELTA", "pres_role": "StatementOfCashFlows"}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 25, "N_eligible": 25},
            {"rule_id": "R_COMP_NONCASH_ADJ", "target_node": "Operating_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "NONCASH_OPERATING_ADJUSTMENT", "pres_role": "StatementOfCashFlows"}, "weight": 1, "scope": ("*", "*", "*"), "n_support": 25, "N_eligible": 25},
            {"rule_id": "R_COMP_GAIN_DEDUCT", "target_node": "Operating_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "NONCASH_GAIN_DEDUCTION", "pres_role": "StatementOfCashFlows"}, "weight": -1, "scope": ("*", "*", "*"), "n_support": 14, "N_eligible": 14},
            {"rule_id": "R_COMP_ICF_OUTFLOW", "target_node": "Investing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "OUTFLOW_PAYMENTS", "pres_role": "StatementOfCashFlows", "kernel_any": ["Property", "Plant", "Equipment", "Available", "Securities", "Businesses", "Investments", "Receivables"]},
             "weight": -1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_COMP_ICF_NET_OUT", "target_node": "Investing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "OUTFLOW_NET_INVESTING", "pres_role": "StatementOfCashFlows", "kernel_any": ["Investing"]},
             "weight": -1, "scope": ("*", "*", "*"), "n_support": 16, "N_eligible": 16},
            {"rule_id": "R_COMP_ICF_INFLOW", "target_node": "Investing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "INFLOW_PROCEEDS", "pres_role": "StatementOfCashFlows", "kernel_any": ["Maturities", "Securities", "Productive", "Investing"]},
             "weight": 1, "scope": ("*", "*", "*"), "n_support": 26, "N_eligible": 26},
            {"rule_id": "R_COMP_FCF_OUTFLOW", "target_node": "Financing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "OUTFLOW_PAYMENTS", "pres_role": "StatementOfCashFlows", "kernel_any": ["Withholding", "Dividends", "Repurchase", "Debt", "Minority"]},
             "weight": -1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_COMP_FCF_INFLOW", "target_node": "Financing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "INFLOW_PROCEEDS", "pres_role": "StatementOfCashFlows", "kernel_any": ["Issuance", "Options", "Minority", "Common"]},
             "weight": 1, "scope": ("*", "*", "*"), "n_support": 24, "N_eligible": 24},
            {"rule_id": "R_COMP_FCF_BIDIR", "target_node": "Financing_Cash_Flow", "qname": None,
             "pattern": {"flow_prefix": "BIDIRECTIONAL_FINANCING_FLOW", "pres_role": "StatementOfCashFlows", "kernel_any": ["Commercial", "Paper", "Debt", "Financing"]},
             "weight": 1, "scope": ("*", "*", "*"), "n_support": 18, "N_eligible": 18},
        ]

        # 4. ConceptPropertyAssertions (False-Positive Exclusion & Cash Continuity Anchors)
        self.property_assertions = [
            {"prop_id": "P_SUPP_TAX_PAID", "qname": "us-gaap:IncomeTaxesPaidNet", "property": "is_supplemental_cash_disclosure", "excluded": True, "reason": "Supplemental cash flow footnote disclosure (IncomeTaxesPaidNet)", "scope": ("*", "*", "*")},
            {"prop_id": "P_SUPP_INT_PAID", "qname": "us-gaap:InterestPaidNet", "property": "is_supplemental_cash_disclosure", "excluded": True, "reason": "Supplemental cash flow footnote disclosure (InterestPaidNet)", "scope": ("*", "*", "*")},
            {"prop_id": "P_CASH_ANCHOR_1", "qname": "us-gaap:CashAndCashEquivalentsAtCarryingValue", "property": "is_balance_sheet_cash_anchor", "excluded": False, "reason": "Balance Sheet Cash Anchor", "scope": ("*", "*", "*")},
            {"prop_id": "P_CASH_ANCHOR_2", "qname": "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "property": "is_balance_sheet_cash_anchor", "excluded": False, "reason": "ASU 2016-18 Total Cash & Restricted Cash Anchor", "scope": ("*", "*", "*")},
        ]

    @staticmethod
    def laplace_confidence(n_support: int, n_eligible: int) -> float:
        return round((n_support + 1.0) / (n_eligible + 2.0), 4)

    @staticmethod
    def scope_specificity(rule_scope: Tuple[str, str, str], firm: str, sector: str, year: int) -> Tuple[int, str]:
        rf, rs, ry = rule_scope
        if rf not in ("*", firm):
            return 0, "NO_MATCH"
        if rs not in ("*", sector):
            return 0, "NO_MATCH"
        if ry not in ("*", str(year), year):
            return 0, "NO_MATCH"
        if rf == firm and str(ry) == str(year):
            return 4, "Tier 1 (Firm+Year)"
        if rf == firm and ry == "*":
            return 3, "Tier 2 (Firm-Persistent)"
        if rf == "*" and rs == sector:
            return 2, "Tier 3 (Sector Backoff)"
        return 1, "Tier 4 (Universal US-GAAP/IFRS)"

    def compute_sha256(self) -> str:
        payload = json.dumps(
            {
                "typed_relations": self.typed_relations,
                "unification_rules": self.unification_rules,
                "property_assertions": self.property_assertions,
                "geography_subsumption": sorted(list(self.geography_subsumption)),
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def freeze(self) -> str:
        """Freezes the KB after SEED calibration and returns the cryptographic SHA-256 digest."""
        self.is_frozen = True
        self.frozen_sha256 = self.compute_sha256()
        return self.frozen_sha256

    def assert_frozen_integrity(self) -> None:
        if not self.is_frozen or not self.frozen_sha256:
            raise RuntimeError("KB must be frozen via kb.freeze() before scoring HOLDOUT filings!")
        current_hash = self.compute_sha256()
        if current_hash != self.frozen_sha256:
            raise RuntimeError(f"KB mutation detected during HOLDOUT scoring! Expected {self.frozen_sha256}, got {current_hash}")

    def add_induced_rule(self, rule: Dict[str, Any]) -> None:
        if self.is_frozen:
            raise RuntimeError("Cannot add induced rule to a frozen Knowledge Base!")
        if not any(r["rule_id"] == rule["rule_id"] for r in self.unification_rules):
            self.unification_rules.append(rule)

    def is_geo_subsumed(self, child_member: str, present_members: Set[str]) -> Optional[str]:
        for (c_node, p_node) in self.geography_subsumption:
            if c_node == child_member and p_node in present_members:
                return p_node
        return None
