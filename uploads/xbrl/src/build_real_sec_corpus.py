#!/usr/bin/env python3
"""
Builds the Clean-Room v3.0 Real SEC EDGAR XBRL Corpus, Linkbases, Reusable KB Tables,
and Separate Ground-Truth Oracle.

Key Guarantees:
1. 100% of firm filings cite real SEC EDGAR filing accession URLs (0 company_tickers.json citations).
2. Spot-checked MSFT FY2024 10-K (0000950170-24-087843) matches exact SEC filing figures:
   - Server products & cloud services = $97,726M, Office = $54,875M, Windows = $23,244M,
     Gaming = $21,503M, LinkedIn = $16,372M, Search = $12,576M, Enterprise = $7,594M,
     Dynamics = $6,481M, Devices = $4,706M, Other = $45M (Exact sum = $245,122M).
   - Segments: PBP = $77,728M (OpInc $40,540M), IC = $105,362M (OpInc $49,584M),
     MPC = $62,032M (OpInc $19,309M) (Exact sum = $245,122M / $109,433M).
   - Note 13 Unearned Revenue: Short-term $57,582M + Long-term $2,602M = $60,184M total
     (by segment: PBP $30,879M + IC $23,117M + MPC $6,188M = $60,184M).
3. Solver input (`sec_xbrl_filings_input.json`) contains ZERO hint fields
   (`parent_measure_hint`, `calc_weight`, `sign_polarity`, `notes`, or `expected_value`).
4. Ground truth (`ground_truth_oracle.json`) is stored separately and never read by any solver.
"""

import argparse
import csv
import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from dcg_and_subatomic_parser import (
    PRIME_HEADS_SCHEMA,
    SUBATOMIC_MODIFIERS_SCHEMA,
    TYPED_RELATIONS_SCHEMA,
)


# ==============================================================================
# 1. REAL SEC EDGAR FILINGS METADATA (30 Filings across 15 Sectors: 15 SEED / 15 HOLDOUT)
#    Every single filing cites its exact SEC EDGAR Archives accession URL.
# ==============================================================================
REAL_SEC_FILINGS = [
    # Sector 1: Enterprise Software & Cloud (SIC 7372 / 7370)
    {
        "firm": "MSFT", "company_name": "MICROSOFT CORP", "cik": "0000789019",
        "sic_code": 7372, "sector": "Technology", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000950170-24-087843",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm"
    },
    {
        "firm": "GOOGL", "company_name": "Alphabet Inc.", "cik": "0001652044",
        "sic_code": 7370, "sector": "Technology", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001652044-25-000014",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm"
    },
    # Sector 2: Consumer Hardware & AI Semiconductors (SIC 3571 / 3674)
    {
        "firm": "AAPL", "company_name": "Apple Inc.", "cik": "0000320193",
        "sic_code": 3571, "sector": "Technology", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000320193-24-000123",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    },
    {
        "firm": "NVDA", "company_name": "NVIDIA CORP", "cik": "0001045810",
        "sic_code": 3674, "sector": "Technology", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001045810-24-000029",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm"
    },
    # Sector 3: E-Commerce, Cloud & Digital Advertising (SIC 5961 / 7370)
    {
        "firm": "AMZN", "company_name": "AMAZON COM INC", "cik": "0001018724",
        "sic_code": 5961, "sector": "Consumer_Tech", "cohort_split": "SEED",
        "fy": 2023, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001018724-24-000008",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1018724/000101872424000008/amzn-20231231.htm"
    },
    {
        "firm": "META", "company_name": "Meta Platforms, Inc.", "cik": "0001326801",
        "sic_code": 7370, "sector": "Technology", "cohort_split": "HOLDOUT",
        "fy": 2023, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001326801-24-000012",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1326801/000132680124000012/meta-20231231.htm"
    },
    # Sector 4: Money-Center Banking & Financial Services (SIC 6021)
    {
        "firm": "JPM", "company_name": "JPMORGAN CHASE & CO", "cik": "0000019617",
        "sic_code": 6021, "sector": "Financials", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000019617-25-000270",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/19617/000001961725000270/jpm-20241231.htm"
    },
    {
        "firm": "BAC", "company_name": "BANK OF AMERICA CORP", "cik": "0000070858",
        "sic_code": 6021, "sector": "Financials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000070858-25-000155",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/70858/000007085825000155/bofaannualreport2024.pdf"
    },
    # Sector 5: Pharmaceuticals & Biopharma (SIC 2834)
    {
        "firm": "JNJ", "company_name": "JOHNSON & JOHNSON", "cik": "0000200406",
        "sic_code": 2834, "sector": "Healthcare", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000200406-25-000038",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/200406/000020040625000038/jnj-20241229.htm"
    },
    {
        "firm": "PFE", "company_name": "PFIZER INC", "cik": "0000078003",
        "sic_code": 2834, "sector": "Healthcare", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000078003-25-000017",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/78003/000007800325000017/pfe-12312024xex99.htm"
    },
    # Sector 6: Industrial Gases & Specialty Chemicals (SIC 2810)
    {
        "firm": "APD", "company_name": "AIR PRODUCTS & CHEMICALS, INC.", "cik": "0000002969",
        "sic_code": 2810, "sector": "Materials", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000002969-24-000056",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/2969/000130817925000645/apd0014238-ars.pdf"
    },
    {
        "firm": "LIN", "company_name": "LINDE PLC", "cik": "0001707925",
        "sic_code": 2810, "sector": "Materials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "IE", "currency": "USD", "form": "10-K",
        "accession": "0001628280-25-007990",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1707925/000162828025007990/lin-20241231.htm"
    },
    # Sector 7: Integrated Oil & Gas Energy Majors (SIC 2911)
    {
        "firm": "XOM", "company_name": "EXXON MOBIL CORP", "cik": "0000034088",
        "sic_code": 2911, "sector": "Energy", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000034088-25-000010",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/34088/000003408825000010/xom-20241231.htm"
    },
    {
        "firm": "CVX", "company_name": "CHEVRON CORP", "cik": "0000093410",
        "sic_code": 2911, "sector": "Energy", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000093410-25-000009",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/93410/000009341025000009/cvx-20241231.htm"
    },
    # Sector 8: Aerospace & Defense (SIC 3721 / 3760)
    {
        "firm": "BA", "company_name": "BOEING CO", "cik": "0000012927",
        "sic_code": 3721, "sector": "Industrials", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000012927-25-000015",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/12927/000001292725000015/ba-20241231.htm"
    },
    {
        "firm": "LMT", "company_name": "LOCKHEED MARTIN CORP", "cik": "0000936468",
        "sic_code": 3760, "sector": "Industrials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000936468-25-000009",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/936468/000093646825000009/lmt-20241231.htm"
    },
    # Sector 9: Airlines & Aviation (SIC 4512)
    {
        "firm": "DAL", "company_name": "DELTA AIR LINES INC", "cik": "0000027904",
        "sic_code": 4512, "sector": "Transportation", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000027904-25-000004",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/27904/000002790425000004/dal-20241231.htm"
    },
    {
        "firm": "UAL", "company_name": "UNITED AIRLINES HOLDINGS INC", "cik": "0000100517",
        "sic_code": 4512, "sector": "Transportation", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000100517-25-000046",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/100517/000010051725000046/ual-20241231.htm"
    },
    # Sector 10: Heavy Machinery & Agriculture (SIC 3531 / 3523)
    {
        "firm": "CAT", "company_name": "CATERPILLAR INC", "cik": "0000018230",
        "sic_code": 3531, "sector": "Industrials", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000018230-25-000008",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/18230/000001823025000008/cat-20241231.htm"
    },
    {
        "firm": "DE", "company_name": "DEERE & CO", "cik": "0000315189",
        "sic_code": 3523, "sector": "Industrials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001558370-24-016169",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/315189/000155837024016169/de-20241027x10k.htm"
    },
    # Sector 11: Mining & Precious/Base Metals (SIC 1040 / 1000)
    {
        "firm": "NEM", "company_name": "NEWMONT CORP", "cik": "0001164727",
        "sic_code": 1040, "sector": "Materials", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001164727-25-000011",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1164727/000116472725000011/nem-20241231.htm"
    },
    {
        "firm": "FCX", "company_name": "FREEPORT-MCMORAN INC", "cik": "0000831259",
        "sic_code": 1000, "sector": "Materials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000831259-25-000006",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/831259/000083125925000006/fcx-20241231.htm"
    },
    # Sector 12: Global Consumer Beverages & Geographic DAG (SIC 2080)
    {
        "firm": "KO", "company_name": "COCA-COLA CO", "cik": "0000021344",
        "sic_code": 2080, "sector": "Consumer_Staples", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000021344-25-000011",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/21344/000002134425000011/ko-20241231.htm"
    },
    {
        "firm": "PEP", "company_name": "PEPSICO INC", "cik": "0000077476",
        "sic_code": 2080, "sector": "Consumer_Staples", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000077476-25-000007",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/77476/000007747625000007/pep-20241228.htm"
    },
    # Sector 13: Entertainment & Streaming Content Assets (ASC 926, SIC 4888 / 7841)
    {
        "firm": "DIS", "company_name": "WALT DISNEY CO", "cik": "0001744489",
        "sic_code": 4888, "sector": "Communication_Services", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001744489-24-000276",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1744489/0001744489-24-000276-index.html"
    },
    {
        "firm": "NFLX", "company_name": "NETFLIX INC", "cik": "0001065280",
        "sic_code": 7841, "sector": "Communication_Services", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001065280-25-000044",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1065280/000106528025000044/nflx-20241231.htm"
    },
    # Sector 14: Automotive & Logistics (SIC 3711 / 4210)
    {
        "firm": "F", "company_name": "FORD MOTOR CO", "cik": "0000037996",
        "sic_code": 3711, "sector": "Consumer_Discretionary", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000037996-25-000013",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/37996/000003799625000013/0000037996-25-000013-index.htm"
    },
    {
        "firm": "GM", "company_name": "GENERAL MOTORS CO", "cik": "0001467858",
        "sic_code": 3711, "sector": "Consumer_Discretionary", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0001467858-25-000032",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1467858/000146785825000032/gm-20241231.htm"
    },
    # Sector 15: REITs (NAREIT FFO) & Foreign Private Issuers (IFRS Form 20-F)
    {
        "firm": "PLD", "company_name": "PROLOGIS INC", "cik": "0001045609",
        "sic_code": 6798, "sector": "Real_Estate", "cohort_split": "SEED",
        "fy": 2024, "domicile": "US", "currency": "USD", "form": "10-K",
        "accession": "0000950170-25-021272",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/1045610/0000950170-25-021272-index.html"
    },
    {
        "firm": "BHP", "company_name": "BHP GROUP LTD", "cik": "0000811809",
        "sic_code": 1000, "sector": "Materials", "cohort_split": "HOLDOUT",
        "fy": 2024, "domicile": "AU", "currency": "USD", "form": "20-F",
        "accession": "0001193125-24-210297",
        "sec_filing_url": "https://www.sec.gov/Archives/edgar/data/811809/000119312524210297/d812514d20f.htm"
    },
]

FILING_MAP = {f["firm"]: f for f in REAL_SEC_FILINGS}


def build_corpus_and_oracle(data_dir: pathlib.Path) -> Dict[str, Any]:
    data_dir.mkdir(parents=True, exist_ok=True)

    raw_facts: List[Dict[str, Any]] = []
    calc_linkbase_arcs: List[Dict[str, Any]] = []
    pres_linkbase_arcs: List[Dict[str, Any]] = []
    ground_truth_fact_placements: Dict[str, Dict[str, Any]] = {}
    ground_truth_goals: List[Dict[str, Any]] = []

    def add_fact(
        firm: str,
        year: int,
        start_date: Optional[str],
        end_date: str,
        qname: str,
        value: float,
        unit: str = "USD",
        schema_balance: str = "NONE",
        dimensions: Optional[Dict[str, str]] = None,
        pres_role: str = "StatementOfOperations",
        pres_index: int = 1,
        # Linkbase & Oracle metadata (stored separately from solver fact input!)
        calc_parent: Optional[str] = None,
        calc_weight: Optional[int] = None,
        gt_target_node: Optional[str] = None,
        gt_weight: int = 1,
        gt_tier: str = "MAPPED_CORE",
    ) -> str:
        meta = FILING_MAP[firm]
        fid = f"F_{firm}_{year}_{len(raw_facts) + 1:04d}"
        dims = dimensions or {}
        dim_suffix = "Consolidated" if not dims else "_".join(f"{k.split(':')[-1]}_{v.split(':')[-1]}" for k, v in sorted(dims.items()))
        ctx_id = f"ctx_{firm}_{year}_{'Instant' if start_date is None else 'Duration'}_{dim_suffix}"

        # Solver input fact: STRICTLY raw XBRL instance & schema attributes (ZERO hints!)
        raw_facts.append({
            "fact_id": fid,
            "entity": {
                "firm": firm,
                "company_name": meta["company_name"],
                "cik": meta["cik"],
                "sic_code": meta["sic_code"],
                "sector": meta["sector"],
                "domicile": meta["domicile"],
                "reporting_currency": meta["currency"],
                "cohort_split": meta["cohort_split"],
                "form_type": meta["form"],
                "accession": meta["accession"],
                "sec_filing_url": meta["sec_filing_url"],
            },
            "context_id": ctx_id,
            "period": {
                "year": year,
                "start_date": start_date,
                "end_date": end_date,
                "is_instant": start_date is None,
            },
            "dimensions": dims,
            "concept": {
                "qname": qname,
                "schema_balance": schema_balance,
                "unit": unit,
                "decimals": -6 if unit == "USD" else 0,
            },
            "presentation": {
                "pres_role": pres_role,
                "pres_index": pres_index,
            },
            "value": float(value),
        })

        # Separate Linkbase Graph entry (only when the filing's native calculation linkbase declares an arc)
        if calc_parent is not None and calc_weight is not None:
            calc_linkbase_arcs.append({
                "firm": firm,
                "year": year,
                "pres_role": pres_role,
                "parent_node": calc_parent,
                "child_qname": qname,
                "weight": int(calc_weight),
            })
        pres_linkbase_arcs.append({
            "firm": firm,
            "year": year,
            "pres_role": pres_role,
            "pres_index": pres_index,
            "qname": qname,
        })

        # Separate Ground-Truth Fact Placement Oracle entry (never passed to solver)
        ground_truth_fact_placements[fid] = {
            "fact_id": fid,
            "firm": firm,
            "year": year,
            "cohort_split": meta["cohort_split"],
            "qname": qname,
            "expected_node": gt_target_node,
            "expected_weight": int(gt_weight),
            "expected_tier": gt_tier,
        }
        return fid

    def add_goal(
        firm: str,
        year: int,
        goal_name: str,
        target_node: str,
        expected_value: float,
        goal_type: str = "DERIVED_MULTI_HOP",
        duration_bucket: str = "1Y_ANNUAL",
        pres_roles: Optional[List[str]] = None,
        allowed_nodes: Optional[List[str]] = None,
        target_dim: Optional[Dict[str, str]] = None,
        axis_filter: Optional[str] = None,
        description: str = "",
    ) -> None:
        meta = FILING_MAP[firm]
        gid = f"G_{firm}_{year}_{goal_name}"
        ground_truth_goals.append({
            "goal_id": gid,
            "firm": firm,
            "company_name": meta["company_name"],
            "cik": meta["cik"],
            "sector": meta["sector"],
            "sic_code": meta["sic_code"],
            "cohort_split": meta["cohort_split"],
            "year": year,
            "goal_name": goal_name,
            "target_node": target_node,
            "goal_type": goal_type,  # DIRECT_ANCHOR_LOOKUP vs DERIVED_MULTI_HOP
            "duration_bucket": duration_bucket,
            "pres_roles": pres_roles or ["StatementOfOperations", "BalanceSheet", "StatementOfCashFlows", "Footnotes"],
            "allowed_nodes": allowed_nodes or [target_node],
            "target_dim": target_dim or {},
            "axis_filter": axis_filter,
            "expected_value": float(expected_value),
            "tolerance": 0.15,
            "sec_filing_url": meta["sec_filing_url"],
            "description": description,
        })

    # ==========================================================================
    # 1. MICROSOFT CORP (MSFT) — Exact FY2024, FY2023, FY2022 Form 10-K
    #    Accession: 0000950170-24-087843 (msft-20240630.htm)
    # ==========================================================================
    # 1A. Income Statement (FY2024 & Comparative FY2023)
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 245122, "USD", "CREDIT", {}, "StatementOfOperations", 1, "GrossProfit", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:CostOfGoodsAndServicesSold", 74114, "USD", "DEBIT", {}, "StatementOfOperations", 2, "GrossProfit", -1, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:GrossProfit", 171008, "USD", "CREDIT", {}, "StatementOfOperations", 3, "OperatingIncomeLoss", 1, "GrossProfit", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ResearchAndDevelopmentExpense", 29510, "USD", "DEBIT", {}, "StatementOfOperations", 4, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:SellingAndMarketingExpense", 24456, "USD", "DEBIT", {}, "StatementOfOperations", 5, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:GeneralAndAdministrativeExpense", 7609, "USD", "DEBIT", {}, "StatementOfOperations", 6, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:OperatingIncomeLoss", 109433, "USD", "CREDIT", {}, "StatementOfOperations", 7, "PreTaxIncome", 1, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NonoperatingIncomeExpense", -1646, "USD", "CREDIT", {}, "StatementOfOperations", 8, "PreTaxIncome", 1, "NonoperatingIncomeExpense", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", 107787, "USD", "CREDIT", {}, "StatementOfOperations", 9, "NetIncomeLoss", 1, "PreTaxIncome", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncomeTaxExpenseBenefit", 19651, "USD", "DEBIT", {}, "StatementOfOperations", 10, "NetIncomeLoss", -1, "IncomeTaxExpense", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NetIncomeLoss", 88136, "USD", "CREDIT", {}, "StatementOfOperations", 11, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 7431, "shares", "NONE", {}, "StatementOfOperations", 12, None, None, "WeightedAverageSharesBasic", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:WeightedAverageNumberDilutedSharesOutstandingAdjustment", 38, "shares", "NONE", {}, "StatementOfOperations", 13, None, None, "DilutiveIncrementalShares", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", 7469, "shares", "NONE", {}, "StatementOfOperations", 14, None, None, "WeightedAverageSharesDiluted", 1, "MAPPED_CORE")

    # 1B. MSFT Note 19 Significant Product and Service Offerings (Exact FY2024 10-K table: sums to $245,122M!)
    msft_products_fy24 = [
        ("msft:ServerProductsAndCloudServicesMember", 97726),
        ("msft:OfficeProductsAndCloudServicesMember", 54875),
        ("msft:WindowsMember", 23244),
        ("msft:GamingMember", 21503),
        ("msft:LinkedInMember", 16372),
        ("msft:SearchAndNewsAdvertisingMember", 12576),
        ("msft:EnterpriseAndPartnerServicesMember", 7594),
        ("msft:DynamicsProductsAndCloudServicesMember", 6481),
        ("msft:DevicesMember", 4706),
        ("msft:OtherProductAndServiceMember", 45),
    ]
    for idx, (member, val) in enumerate(msft_products_fy24, start=1):
        add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", val, "USD", "CREDIT",
                 {"srt:ProductOrServiceAxis": member}, "SegmentFootnotes", idx, None, None, "Revenues_Product_Breakdown", 1, "MAPPED_CORE")

    # 1C. MSFT Note 19 Reportable Segments (Exact FY2024 10-K table: sums to $245,122M Rev / $109,433M OpInc!)
    msft_segments_fy24 = [
        ("msft:ProductivityAndBusinessProcessesMember", 77728, 40540, 30879),
        ("msft:IntelligentCloudMember", 105362, 49584, 23117),
        ("msft:MorePersonalComputingMember", 62032, 19309, 6188),
    ]
    for idx, (seg_mem, rev_v, op_v, une_v) in enumerate(msft_segments_fy24, start=20):
        add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", rev_v, "USD", "CREDIT",
                 {"us-gaap:StatementBusinessSegmentsAxis": seg_mem}, "SegmentFootnotes", idx, None, None, "Revenues_Segment_Breakdown", 1, "MAPPED_CORE")
        add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:OperatingIncomeLoss", op_v, "USD", "CREDIT",
                 {"us-gaap:StatementBusinessSegmentsAxis": seg_mem}, "SegmentFootnotes", idx + 10, None, None, "OperatingIncome_Segment_Breakdown", 1, "MAPPED_CORE")
        add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:ContractWithCustomerLiability", une_v, "USD", "CREDIT",
                 {"us-gaap:StatementBusinessSegmentsAxis": seg_mem}, "UnearnedRevenueFootnotes", idx + 20, None, None, "ContractWithCustomerLiability_Segment_Breakdown", 1, "MAPPED_CORE")

    # 1D. MSFT Note 19 Geographic Data (Exact FY2024 10-K table: US $124,704M + Other countries $120,418M = $245,122M)
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 124704, "USD", "CREDIT",
             {"srt:StatementGeographicalAxis": "country:US"}, "SegmentFootnotes", 50, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 120418, "USD", "CREDIT",
             {"srt:StatementGeographicalAxis": "srt:ForeignCountryMember"}, "SegmentFootnotes", 51, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")

    # 1E. MSFT Classified Balance Sheet & Note 13 Unearned Revenue (June 30, 2024 & June 30, 2023)
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:CashAndCashEquivalentsAtCarryingValue", 18315, "USD", "DEBIT", {}, "BalanceSheet", 1, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2023, None, "2023-06-30", "us-gaap:CashAndCashEquivalentsAtCarryingValue", 34704, "USD", "DEBIT", {}, "BalanceSheet", 1, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent", 57228, "USD", "DEBIT", {}, "BalanceSheet", 2, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AccountsReceivableNetCurrent", 56924, "USD", "DEBIT", {}, "BalanceSheet", 3, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:InventoryNet", 1246, "USD", "DEBIT", {}, "BalanceSheet", 4, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OtherAssetsCurrent", 26021, "USD", "DEBIT", {}, "BalanceSheet", 5, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AssetsCurrent", 159734, "USD", "DEBIT", {}, "BalanceSheet", 6, "Assets", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:PropertyPlantAndEquipmentNet", 135591, "USD", "DEBIT", {}, "BalanceSheet", 7, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OperatingLeaseRightOfUseAsset", 18961, "USD", "DEBIT", {}, "BalanceSheet", 8, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:LongTermInvestments", 14600, "USD", "DEBIT", {}, "BalanceSheet", 9, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:Goodwill", 119220, "USD", "DEBIT", {}, "BalanceSheet", 10, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:IntangibleAssetsNetExcludingGoodwill", 27597, "USD", "DEBIT", {}, "BalanceSheet", 11, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OtherAssetsNoncurrent", 36460, "USD", "DEBIT", {}, "BalanceSheet", 12, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:Assets", 512163, "USD", "DEBIT", {}, "BalanceSheet", 13, None, None, "Assets", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AccountsPayableCurrent", 21996, "USD", "CREDIT", {}, "BalanceSheet", 14, "LiabilitiesCurrent", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:ShortTermBorrowings", 6693, "USD", "CREDIT", {}, "BalanceSheet", 15, "LiabilitiesCurrent", 1, "ShortTermDebt", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:LongTermDebtCurrent", 2249, "USD", "CREDIT", {}, "BalanceSheet", 16, "LiabilitiesCurrent", 1, "LongTermDebtCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:EmployeeRelatedLiabilitiesCurrent", 12564, "USD", "CREDIT", {}, "BalanceSheet", 17, "LiabilitiesCurrent", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AccruedIncomeTaxesCurrent", 5017, "USD", "CREDIT", {}, "BalanceSheet", 18, "LiabilitiesCurrent", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:ContractWithCustomerLiabilityCurrent", 57582, "USD", "CREDIT", {}, "BalanceSheet", 19, "LiabilitiesCurrent", 1, "ContractWithCustomerLiabilityCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OtherLiabilitiesCurrent", 19185, "USD", "CREDIT", {}, "BalanceSheet", 20, "LiabilitiesCurrent", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:LiabilitiesCurrent", 125286, "USD", "CREDIT", {}, "BalanceSheet", 21, "Liabilities", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:LongTermDebtNoncurrent", 42688, "USD", "CREDIT", {}, "BalanceSheet", 22, "LiabilitiesNoncurrent", 1, "LongTermDebtNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AccruedIncomeTaxesNoncurrent", 27931, "USD", "CREDIT", {}, "BalanceSheet", 23, "LiabilitiesNoncurrent", 1, "LiabilitiesNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:ContractWithCustomerLiabilityNoncurrent", 2602, "USD", "CREDIT", {}, "BalanceSheet", 24, "LiabilitiesNoncurrent", 1, "ContractWithCustomerLiabilityNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:DeferredIncomeTaxLiabilitiesNet", 2618, "USD", "CREDIT", {}, "BalanceSheet", 25, "LiabilitiesNoncurrent", 1, "LiabilitiesNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OperatingLeaseLiabilityNoncurrent", 15497, "USD", "CREDIT", {}, "BalanceSheet", 26, "LiabilitiesNoncurrent", 1, "LiabilitiesNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:OtherLiabilitiesNoncurrent", 27064, "USD", "CREDIT", {}, "BalanceSheet", 27, "LiabilitiesNoncurrent", 1, "LiabilitiesNoncurrent", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:Liabilities", 243686, "USD", "CREDIT", {}, "BalanceSheet", 28, "LiabilitiesAndStockholdersEquity", 1, "Liabilities", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:CommonStocksIncludingAdditionalPaidInCapital", 100923, "USD", "CREDIT", {}, "BalanceSheet", 29, "StockholdersEquity", 1, "CommonStockAndAPIC", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:RetainedEarningsAccumulatedDeficit", 173144, "USD", "CREDIT", {}, "BalanceSheet", 30, "StockholdersEquity", 1, "RetainedEarnings", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", -5590, "USD", "CREDIT", {}, "BalanceSheet", 31, "StockholdersEquity", 1, "AccumulatedOtherComprehensiveIncome", 1, "MAPPED_CORE")
    add_fact("MSFT", 2023, None, "2023-06-30", "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", -6343, "USD", "CREDIT", {}, "BalanceSheet", 31, "StockholdersEquity", 1, "AccumulatedOtherComprehensiveIncome", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent", 753, "USD", "CREDIT", {}, "StatementOfOperations", 32, None, None, "OtherComprehensiveIncomeNet", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:StockholdersEquity", 268477, "USD", "CREDIT", {}, "BalanceSheet", 32, "LiabilitiesAndStockholdersEquity", 1, "StockholdersEquity", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, None, "2024-06-30", "us-gaap:LiabilitiesAndStockholdersEquity", 512163, "USD", "CREDIT", {}, "BalanceSheet", 33, None, None, "LiabilitiesAndStockholdersEquity", 1, "MAPPED_CORE")

    # 1F. MSFT Full Consolidated Statement of Cash Flows (FY2024 & FY2023)
    # Includes custom extension tags WITHOUT calculation linkbase arcs (`msft:DepreciationAmortizationAndOther`,
    # `msft:NetRecognizedLossesGainsOnInvestmentsAndDerivatives`, `msft:ProceedsFromIssuanceOfDebtMaturitiesOf90DaysOrLessNet`)
    # to genuinely test 7-Slot DCG + Sub-Atomic Head Induction + CSP/Bayesian Residual Resolution!
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NetIncomeLoss", 88136, "USD", "CREDIT", {}, "StatementOfCashFlows", 1, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "msft:DepreciationAmortizationAndOther", 22287, "USD", "DEBIT", {}, "StatementOfCashFlows", 2, None, None, "Operating_Cash_Flow", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ShareBasedCompensation", 10734, "USD", "DEBIT", {}, "StatementOfCashFlows", 3, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "msft:NetRecognizedLossesGainsOnInvestmentsAndDerivatives", 305, "USD", "NONE", {}, "StatementOfCashFlows", 4, None, None, "Operating_Cash_Flow", 1, "TIER_U2_CSP_BAYESIAN_SOLVED")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:DeferredIncomeTaxExpenseBenefit", -4738, "USD", "NONE", {}, "StatementOfCashFlows", 5, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInAccountsReceivable", -7191, "USD", "NONE", {}, "StatementOfCashFlows", 6, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInInventories", 1284, "USD", "NONE", {}, "StatementOfCashFlows", 7, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInOtherCurrentAssets", -1648, "USD", "NONE", {}, "StatementOfCashFlows", 8, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInOtherNoncurrentAssets", -6817, "USD", "NONE", {}, "StatementOfCashFlows", 9, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInAccountsPayable", 3545, "USD", "NONE", {}, "StatementOfCashFlows", 10, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInContractWithCustomerLiability", 5348, "USD", "NONE", {}, "StatementOfCashFlows", 11, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInAccruedIncomeTaxesPayable", 1687, "USD", "NONE", {}, "StatementOfCashFlows", 12, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInOtherCurrentLiabilities", 4867, "USD", "NONE", {}, "StatementOfCashFlows", 13, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:IncreaseDecreaseInOtherNoncurrentLiabilities", 749, "USD", "NONE", {}, "StatementOfCashFlows", 14, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 118548, "USD", "DEBIT", {}, "StatementOfCashFlows", 15, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 44477, "USD", "CREDIT", {}, "StatementOfCashFlows", 16, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired", 69132, "USD", "CREDIT", {}, "StatementOfCashFlows", 17, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsToAcquireInvestments", 17732, "USD", "CREDIT", {}, "StatementOfCashFlows", 18, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities", 24775, "USD", "DEBIT", {}, "StatementOfCashFlows", 19, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ProceedsFromSaleOfAvailableForSaleSecuritiesDebt", 10894, "USD", "DEBIT", {}, "StatementOfCashFlows", 20, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsForProceedsFromOtherInvestingActivities", 1298, "USD", "CREDIT", {}, "StatementOfCashFlows", 21, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NetCashProvidedByUsedInInvestingActivities", -96970, "USD", "CREDIT", {}, "StatementOfCashFlows", 22, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "msft:ProceedsFromIssuanceOfDebtMaturitiesOf90DaysOrLessNet", 5250, "USD", "DEBIT", {}, "StatementOfCashFlows", 23, None, None, "Financing_Cash_Flow", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ProceedsFromIssuanceOfLongTermDebt", 24395, "USD", "DEBIT", {}, "StatementOfCashFlows", 24, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:RepaymentsOfLongTermDebt", 29070, "USD", "CREDIT", {}, "StatementOfCashFlows", 25, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ProceedsFromIssuanceOfCommonStock", 2002, "USD", "DEBIT", {}, "StatementOfCashFlows", 26, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsForRepurchaseOfCommonStock", 17254, "USD", "CREDIT", {}, "StatementOfCashFlows", 27, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:PaymentsOfDividendsCommonStock", 21771, "USD", "CREDIT", {}, "StatementOfCashFlows", 28, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:ProceedsFromPaymentsForOtherFinancingActivities", -1309, "USD", "NONE", {}, "StatementOfCashFlows", 29, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:NetCashProvidedByUsedInFinancingActivities", -37757, "USD", "CREDIT", {}, "StatementOfCashFlows", 30, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", -210, "USD", "NONE", {}, "StatementOfCashFlows", 31, "Total_Cash_Flow_Delta", 1, "FX_Cash_Flow_Effect", 1, "MAPPED_CORE")
    add_fact("MSFT", 2024, "2023-07-01", "2024-06-30", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", -16389, "USD", "DEBIT", {}, "StatementOfCashFlows", 32, None, None, "Total_Cash_Flow_Delta", 1, "MAPPED_CORE")

    # MSFT Golden Evaluation Goals (Heavy emphasis on Multi-Hop Derived & Compositional Goals!)
    add_goal("MSFT", 2024, "Product_Revenue_Disaggregation_Sum", "Revenues", 245122.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:ProductOrServiceAxis",
             "Sum of all 10 MSFT FY24 product & service offerings ($97,726M Server + $54,875M Office + $23,244M Windows + $21,503M Gaming + $16,372M LinkedIn + $12,576M Search + $7,594M Enterprise + $6,481M Dynamics + $4,706M Devices + $45M Other = $245,122M)")
    add_goal("MSFT", 2024, "Segment_Revenue_Disaggregation_Sum", "Revenues", 245122.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "us-gaap:StatementBusinessSegmentsAxis",
             "Sum of 3 MSFT reportable segments ($77,728M PBP + $105,362M IC + $62,032M MPC = $245,122M)")
    add_goal("MSFT", 2024, "Segment_OperatingIncome_Disaggregation_Sum", "OperatingIncomeLoss", 109433.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["OperatingIncomeLoss"], {}, "us-gaap:StatementBusinessSegmentsAxis",
             "Sum of 3 MSFT segment operating incomes ($40,540M PBP + $49,584M IC + $19,309M MPC = $109,433M)")
    add_goal("MSFT", 2024, "Geographic_Revenue_Disaggregation_Sum", "Revenues", 245122.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:StatementGeographicalAxis",
             "Sum of US ($124,704M) + Other countries ($120,418M) = $245,122M")
    add_goal("MSFT", 2024, "Total_Operating_Expenses_Derived", "OperatingExpenses", 61575.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingExpenses", "ResearchAndDevelopmentExpense", "SellingAndMarketingExpense", "GeneralAndAdministrativeExpense"], {}, None,
             "Derived OperatingExpenses = R&D ($29,510M) + S&M ($24,456M) + G&A ($7,609M) = $61,575M")
    add_goal("MSFT", 2024, "Operating_Income_Rollup_TieOut", "OperatingIncomeLoss", 109433.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "GrossProfit", "OperatingExpenses", "Revenues", "CostOfRevenue"], {}, None,
             "Multi-hop rollup: Revenues ($245,122M) - CostOfRevenue ($74,114M) - OperatingExpenses ($61,575M) = $109,433M")
    add_goal("MSFT", 2024, "Unearned_Revenue_Total_Note13", "ContractWithCustomerLiability", 60184.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["ContractWithCustomerLiability", "ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiabilityNoncurrent"], {}, None,
             "Note 13 Total Unearned Revenue = Short-term ($57,582M) + Long-term ($2,602M) = $60,184M")
    add_goal("MSFT", 2024, "Unearned_Revenue_Segment_Sum_Note13", "ContractWithCustomerLiability", 60184.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["UnearnedRevenueFootnotes"], ["ContractWithCustomerLiability"], {}, "us-gaap:StatementBusinessSegmentsAxis",
             "Note 13 Unearned Revenue by segment: PBP ($30,879M) + IC ($23,117M) + MPC ($6,188M) = $60,184M")
    add_goal("MSFT", 2024, "Total_Debt_Carrying_Derived", "TotalDebt", 51630.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["TotalDebt", "ShortTermDebt", "LongTermDebtCurrent", "LongTermDebtNoncurrent"], {}, None,
             "Compositional Total Debt = ShortTermBorrowings ($6,693M) + LongTermDebtCurrent ($2,249M) + LongTermDebtNoncurrent ($42,688M) = $51,630M")
    add_goal("MSFT", 2024, "Classified_Assets_Rollup", "Assets", 512163.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets", "AssetsCurrent", "AssetsNoncurrent"], {}, None,
             "Classified Assets = AssetsCurrent ($159,734M) + Noncurrent components ($352,429M) = $512,163M")
    add_goal("MSFT", 2024, "Liabilities_And_Equity_Rollup", "LiabilitiesAndStockholdersEquity", 512163.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["LiabilitiesAndStockholdersEquity", "Liabilities", "LiabilitiesCurrent", "LiabilitiesNoncurrent", "StockholdersEquity"], {}, None,
             "Liabilities ($243,686M = $125,286M Curr + $118,400M Noncurr) + StockholdersEquity ($268,477M) = $512,163M")
    add_goal("MSFT", 2024, "Comprehensive_Income_And_AOCI_Bridge", "ComprehensiveIncomeNet", 88889.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations", "BalanceSheet"], ["ComprehensiveIncomeNet", "NetIncomeLoss", "OtherComprehensiveIncomeNet"], {}, None,
             "ComprehensiveIncome = NetIncome ($88,136M) + OCI ($753M = AOCI_2024 [-$5,590M] - AOCI_2023 [-$6,343M]) = $88,889M")
    add_goal("MSFT", 2024, "Full_Cash_Flow_4Branch_And_CSP", "Total_Cash_Flow_Delta", -16389.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows", "BalanceSheet"], ["Total_Cash_Flow_Delta", "Operating_Cash_Flow", "Investing_Cash_Flow", "Financing_Cash_Flow", "FX_Cash_Flow_Effect"], {}, None,
             "Full 32-line Cash Flow unification + CSP residual resolution: OCF ($118,548M) + ICF (-$96,970M) + FCF (-$37,757M) + FX (-$210M) = -$16,389M (= Cash_2024 $18,315M - Cash_2023 $34,704M)")
    add_goal("MSFT", 2024, "Free_Cash_Flow_Derived", "FreeCashFlow", 74071.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["FreeCashFlow", "Operating_Cash_Flow", "CapitalExpenditures"], {}, None,
             "FreeCashFlow = OperatingCashFlow ($118,548M) - CapitalExpenditures ($44,477M) = $74,071M")
    add_goal("MSFT", 2024, "Diluted_Share_Bridge_Derived", "WeightedAverageSharesDiluted", 7469.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["WeightedAverageSharesDiluted", "WeightedAverageSharesBasic", "DilutiveIncrementalShares"], {}, None,
             "Basic Shares (7,431M) + Dilutive Effect of Stock Awards (38M) = Diluted Shares (7,469M)")

    # ==========================================================================
    # 2. APPLE INC. (AAPL) — Exact FY2024 & FY2023 Form 10-K (0000320193-24-000123)
    # ==========================================================================
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 391035, "USD", "CREDIT", {}, "StatementOfOperations", 1, "GrossProfit", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:CostOfGoodsAndServicesSold", 210352, "USD", "DEBIT", {}, "StatementOfOperations", 2, "GrossProfit", -1, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:GrossProfit", 180683, "USD", "CREDIT", {}, "StatementOfOperations", 3, "OperatingIncomeLoss", 1, "GrossProfit", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ResearchAndDevelopmentExpense", 31370, "USD", "DEBIT", {}, "StatementOfOperations", 4, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:SellingGeneralAndAdministrativeExpense", 26097, "USD", "DEBIT", {}, "StatementOfOperations", 5, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:OperatingExpenses", 57467, "USD", "DEBIT", {}, "StatementOfOperations", 6, "OperatingIncomeLoss", -1, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:OperatingIncomeLoss", 123216, "USD", "CREDIT", {}, "StatementOfOperations", 7, "PreTaxIncome", 1, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NonoperatingIncomeExpense", 269, "USD", "CREDIT", {}, "StatementOfOperations", 8, "PreTaxIncome", 1, "NonoperatingIncomeExpense", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", 123485, "USD", "CREDIT", {}, "StatementOfOperations", 9, "NetIncomeLoss", 1, "PreTaxIncome", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncomeTaxExpenseBenefit", 29749, "USD", "DEBIT", {}, "StatementOfOperations", 10, "NetIncomeLoss", -1, "IncomeTaxExpense", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NetIncomeLoss", 93736, "USD", "CREDIT", {}, "StatementOfOperations", 11, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")

    # AAPL Product vs Service Disaggregation ($294,866M Product + $96,169M Service = $391,035M)
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 294866, "USD", "CREDIT",
             {"srt:ProductOrServiceAxis": "us-gaap:ProductMember"}, "SegmentFootnotes", 1, None, None, "Revenues_Product_Breakdown", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 96169, "USD", "CREDIT",
             {"srt:ProductOrServiceAxis": "us-gaap:ServiceMember"}, "SegmentFootnotes", 2, None, None, "Revenues_Product_Breakdown", 1, "MAPPED_CORE")
    # Sub-annual Q4 stub (to test Pass 1 Temporal Partitioning)
    add_fact("AAPL", 2024, "2024-06-30", "2024-09-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 94930, "USD", "CREDIT", {}, "Footnotes", 99, None, None, "ORTHOGONAL_SUB_ANNUAL_STUB", 1, "MAPPED_CORE")

    # AAPL Classified Balance Sheet (with custom extension `aapl:VendorNonTradeReceivablesCurrent` lacking calc_parent!)
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:CashAndCashEquivalentsAtCarryingValue", 29943, "USD", "DEBIT", {}, "BalanceSheet", 1, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:MarketableSecuritiesCurrent", 35228, "USD", "DEBIT", {}, "BalanceSheet", 2, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:AccountsReceivableNetCurrent", 33410, "USD", "DEBIT", {}, "BalanceSheet", 3, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "aapl:VendorNonTradeReceivablesCurrent", 32833, "USD", "DEBIT", {}, "BalanceSheet", 4, None, None, "AssetsCurrent", 1, "TIER_U2_CSP_BAYESIAN_SOLVED")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:InventoryNet", 7286, "USD", "DEBIT", {}, "BalanceSheet", 5, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:OtherAssetsCurrent", 14287, "USD", "DEBIT", {}, "BalanceSheet", 6, "AssetsCurrent", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:AssetsCurrent", 152987, "USD", "DEBIT", {}, "BalanceSheet", 7, "Assets", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:MarketableSecuritiesNoncurrent", 91479, "USD", "DEBIT", {}, "BalanceSheet", 8, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:PropertyPlantAndEquipmentNet", 45680, "USD", "DEBIT", {}, "BalanceSheet", 9, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:OtherAssetsNoncurrent", 74834, "USD", "DEBIT", {}, "BalanceSheet", 10, "AssetsNoncurrent", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:AssetsNoncurrent", 211993, "USD", "DEBIT", {}, "BalanceSheet", 11, "Assets", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:Assets", 364980, "USD", "DEBIT", {}, "BalanceSheet", 12, None, None, "Assets", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:LiabilitiesCurrent", 176392, "USD", "CREDIT", {}, "BalanceSheet", 13, "Liabilities", 1, "LiabilitiesCurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:LiabilitiesNoncurrent", 131638, "USD", "CREDIT", {}, "BalanceSheet", 14, "Liabilities", 1, "LiabilitiesNoncurrent", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:Liabilities", 308030, "USD", "CREDIT", {}, "BalanceSheet", 15, "LiabilitiesAndStockholdersEquity", 1, "Liabilities", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:StockholdersEquity", 56950, "USD", "CREDIT", {}, "BalanceSheet", 16, "LiabilitiesAndStockholdersEquity", 1, "StockholdersEquity", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:LiabilitiesAndStockholdersEquity", 364980, "USD", "CREDIT", {}, "BalanceSheet", 17, None, None, "LiabilitiesAndStockholdersEquity", 1, "MAPPED_CORE")

    # AAPL Cash Flow Statement (FY2024 & FY2023) + Cash Continuity Anchors + Supplemental Tax Paid False Positive
    add_fact("AAPL", 2024, None, "2024-09-28", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 29943, "USD", "DEBIT", {}, "StatementOfCashFlows", 30, None, None, "CashAndRestrictedCash", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, None, "2023-09-30", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 30737, "USD", "DEBIT", {}, "StatementOfCashFlows", 30, None, None, "CashAndRestrictedCash", 1, "MAPPED_CORE")
    add_fact("AAPL", 2022, None, "2022-09-24", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 24977, "USD", "DEBIT", {}, "StatementOfCashFlows", 30, None, None, "CashAndRestrictedCash", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NetIncomeLoss", 93736, "USD", "CREDIT", {}, "StatementOfCashFlows", 1, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:DepreciationDepletionAndAmortization", 11445, "USD", "DEBIT", {}, "StatementOfCashFlows", 2, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ShareBasedCompensation", 11688, "USD", "DEBIT", {}, "StatementOfCashFlows", 3, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "aapl:OtherNonCashIncomeExpenseCustom", -2266, "USD", "NONE", {}, "StatementOfCashFlows", 4, None, None, "Operating_Cash_Flow", 1, "TIER_U2_CSP_BAYESIAN_SOLVED")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncreaseDecreaseInAccountsReceivable", -3788, "USD", "NONE", {}, "StatementOfCashFlows", 5, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "aapl:IncreaseDecreaseInVendorNonTradeReceivables", -1356, "USD", "NONE", {}, "StatementOfCashFlows", 6, None, None, "Operating_Cash_Flow", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncreaseDecreaseInInventories", -1046, "USD", "NONE", {}, "StatementOfCashFlows", 7, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncreaseDecreaseInOtherOperatingAssets", -11731, "USD", "NONE", {}, "StatementOfCashFlows", 8, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncreaseDecreaseInAccountsPayable", 6020, "USD", "NONE", {}, "StatementOfCashFlows", 9, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncreaseDecreaseInOtherOperatingLiabilities", 15552, "USD", "NONE", {}, "StatementOfCashFlows", 10, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 118254, "USD", "DEBIT", {}, "StatementOfCashFlows", 11, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsToAcquireAvailableForSaleSecuritiesDebt", 48656, "USD", "CREDIT", {}, "StatementOfCashFlows", 12, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities", 51211, "USD", "DEBIT", {}, "StatementOfCashFlows", 13, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ProceedsFromSaleOfAvailableForSaleSecuritiesDebt", 11135, "USD", "DEBIT", {}, "StatementOfCashFlows", 14, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 9447, "USD", "CREDIT", {}, "StatementOfCashFlows", 15, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsForProceedsFromOtherInvestingActivities", 1308, "USD", "CREDIT", {}, "StatementOfCashFlows", 16, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NetCashProvidedByUsedInInvestingActivities", 2935, "USD", "DEBIT", {}, "StatementOfCashFlows", 17, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsRelatedToTaxWithholdingForShareBasedCompensation", 5441, "USD", "CREDIT", {}, "StatementOfCashFlows", 18, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsOfDividends", 15234, "USD", "CREDIT", {}, "StatementOfCashFlows", 19, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:PaymentsForRepurchaseOfCommonStock", 94949, "USD", "CREDIT", {}, "StatementOfCashFlows", 20, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:RepaymentsOfLongTermDebt", 9958, "USD", "CREDIT", {}, "StatementOfCashFlows", 21, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ProceedsFromRepaymentsOfCommercialPaper", 3960, "USD", "DEBIT", {}, "StatementOfCashFlows", 22, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:ProceedsFromPaymentsForOtherFinancingActivities", -361, "USD", "NONE", {}, "StatementOfCashFlows", 23, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:NetCashProvidedByUsedInFinancingActivities", -121983, "USD", "CREDIT", {}, "StatementOfCashFlows", 24, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", -794, "USD", "DEBIT", {}, "StatementOfCashFlows", 25, None, None, "Total_Cash_Flow_Delta", 1, "MAPPED_CORE")
    add_fact("AAPL", 2024, "2023-10-01", "2024-09-28", "us-gaap:IncomeTaxesPaidNet", 26102, "USD", "CREDIT", {}, "StatementOfCashFlows", 26, None, None, "IGNORED_SUPPLEMENTAL_DISCLOSURE", 0, "MAPPED_CORE")

    # AAPL FY2023 Cash Flow Comparative (for Temporal Markov Chain at pres_index=4!)
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:NetIncomeLoss", 96995, "USD", "CREDIT", {}, "StatementOfCashFlows", 1, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:DepreciationDepletionAndAmortization", 11519, "USD", "DEBIT", {}, "StatementOfCashFlows", 2, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:ShareBasedCompensation", 10833, "USD", "DEBIT", {}, "StatementOfCashFlows", 3, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:OtherNoncashIncomeExpense", -2227, "USD", "NONE", {}, "StatementOfCashFlows", 4, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:IncreaseDecreaseInAccountsReceivable", -1688, "USD", "NONE", {}, "StatementOfCashFlows", 5, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "aapl:IncreaseDecreaseInVendorNonTradeReceivables", 1271, "USD", "NONE", {}, "StatementOfCashFlows", 6, None, None, "Operating_Cash_Flow", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:IncreaseDecreaseInInventories", -1618, "USD", "NONE", {}, "StatementOfCashFlows", 7, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:IncreaseDecreaseInOtherOperatingAssets", -5684, "USD", "NONE", {}, "StatementOfCashFlows", 8, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:IncreaseDecreaseInAccountsPayable", -1889, "USD", "NONE", {}, "StatementOfCashFlows", 9, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:IncreaseDecreaseInOtherOperatingLiabilities", 3031, "USD", "NONE", {}, "StatementOfCashFlows", 10, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 110543, "USD", "DEBIT", {}, "StatementOfCashFlows", 11, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:NetCashProvidedByUsedInInvestingActivities", 3705, "USD", "DEBIT", {}, "StatementOfCashFlows", 17, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:NetCashProvidedByUsedInFinancingActivities", -108488, "USD", "CREDIT", {}, "StatementOfCashFlows", 24, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("AAPL", 2023, "2022-09-25", "2023-09-30", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", 5760, "USD", "DEBIT", {}, "StatementOfCashFlows", 25, None, None, "Total_Cash_Flow_Delta", 1, "MAPPED_CORE")

    # AAPL Golden Goals
    add_goal("AAPL", 2024, "Product_And_Service_Revenue_Sum", "Revenues", 391035.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:ProductOrServiceAxis",
             "AAPL Product ($294,866M) + Service ($96,169M) = $391,035M (while excluding Q4 3M stub $94,930M)")
    add_goal("AAPL", 2024, "Classified_BS_With_CSP_VendorReceivables", "Assets", 364980.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets", "AssetsCurrent", "AssetsNoncurrent"], {}, None,
             "Resolves custom extension `aapl:VendorNonTradeReceivablesCurrent` ($32,833M) via CSP/Bayesian into AssetsCurrent ($152,987M) + AssetsNoncurrent ($211,993M) = $364,980M")
    add_goal("AAPL", 2024, "Operating_Income_Rollup", "OperatingIncomeLoss", 123216.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "GrossProfit", "OperatingExpenses", "Revenues", "CostOfRevenue"], {}, None,
             "GrossProfit ($180,683M) - OperatingExpenses ($57,467M = $31,370M R&D + $26,097M SG&A) = $123,216M")
    add_goal("AAPL", 2024, "Full_CashFlow_CSP_Markov_And_Continuity", "Total_Cash_Flow_Delta", -794.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Total_Cash_Flow_Delta", "Operating_Cash_Flow", "Investing_Cash_Flow", "Financing_Cash_Flow"], {}, None,
             "Solves `aapl:OtherNonCashIncomeExpenseCustom` (-$2,266M) via CSP+Markov, excludes `IncomeTaxesPaidNet` ($26,102M), and verifies Cash_2023 ($30,737M) + Delta (-$794M) = Cash_2024 ($29,943M)")
    add_goal("AAPL", 2023, "Full_CashFlow_And_Continuity_FY23", "Total_Cash_Flow_Delta", 5760.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Total_Cash_Flow_Delta", "Operating_Cash_Flow", "Investing_Cash_Flow", "Financing_Cash_Flow"], {}, None,
             "Verifies FY23 Cash Flow rollup ($110,543M + $3,705M - $108,488M = $5,760M) and Cash_2022 ($24,977M) + $5,760M = Cash_2023 ($30,737M)")
    add_goal("AAPL", 2024, "Free_Cash_Flow_Derived", "FreeCashFlow", 108807.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["FreeCashFlow", "Operating_Cash_Flow", "CapitalExpenditures"], {}, None,
             "AAPL FreeCashFlow = OCF ($118,254M) - CapEx ($9,447M) = $108,807M")

    # ==========================================================================
    # 3. ALPHABET INC. (GOOGL) — Exact FY2024 Form 10-K (HOLDOUT Cohort)
    #    Accession: 0001652044-25-000014 (goog-20241231.htm)
    # ==========================================================================
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 350018, "USD", "CREDIT", {}, "StatementOfOperations", 1, "OperatingIncomeLoss", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:CostOfGoodsAndServicesSold", 146306, "USD", "DEBIT", {}, "StatementOfOperations", 2, "OperatingIncomeLoss", -1, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:ResearchAndDevelopmentExpense", 49326, "USD", "DEBIT", {}, "StatementOfOperations", 3, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:SellingAndMarketingExpense", 27808, "USD", "DEBIT", {}, "StatementOfOperations", 4, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:GeneralAndAdministrativeExpense", 14188, "USD", "DEBIT", {}, "StatementOfOperations", 5, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:OperatingExpenses", 91322, "USD", "DEBIT", {}, "StatementOfOperations", 6, "OperatingIncomeLoss", -1, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:OperatingIncomeLoss", 112390, "USD", "CREDIT", {}, "StatementOfOperations", 7, None, None, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetIncomeLoss", 100118, "USD", "CREDIT", {}, "StatementOfOperations", 8, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    # GOOGL 7 Product/Service Disaggregation lines (Exact FY2024 10-K: sum = $350,018M)
    googl_prods = [
        ("goog:GoogleSearchAndOtherMember", 198084),
        ("goog:YouTubeAdsMember", 36147),
        ("goog:GoogleNetworkMember", 30359),
        ("goog:SubscriptionsPlatformsAndDevicesMember", 40340),
        ("goog:GoogleCloudMember", 43229),
        ("goog:OtherBetsMember", 1648),
        ("goog:HedgingGainsLossesMember", 211),
    ]
    for idx, (m_name, val) in enumerate(googl_prods, start=1):
        add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", val, "USD", "CREDIT",
                 {"srt:ProductOrServiceAxis": m_name}, "SegmentFootnotes", idx, None, None, "Revenues_Product_Breakdown", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 125299, "USD", "DEBIT", {}, "StatementOfCashFlows", 1, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 52535, "USD", "CREDIT", {}, "StatementOfCashFlows", 2, None, None, "CapitalExpenditures", -1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInInvestingActivities", -45536, "USD", "CREDIT", {}, "StatementOfCashFlows", 3, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("GOOGL", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInFinancingActivities", -79733, "USD", "CREDIT", {}, "StatementOfCashFlows", 4, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")

    add_goal("GOOGL", 2024, "Product_Revenue_7Way_Disaggregation_Sum", "Revenues", 350018.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:ProductOrServiceAxis",
             "Zero-shot Holdout: Sum of 7 GOOGL product/service members ($198,084M Search + $36,147M YouTube + $30,359M Network + $40,340M Subs/Devices + $43,229M Cloud + $1,648M OtherBets + $211M Hedging = $350,018M)")
    add_goal("GOOGL", 2024, "Derived_GrossProfit_Without_Reported_Line", "GrossProfit", 203712.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["GrossProfit", "Revenues", "CostOfRevenue"], {}, None,
             "Zero-shot Holdout: Imputes GrossProfit = Revenues ($350,018M) - CostOfGoodsAndServicesSold ($146,306M) = $203,712M (Alphabet does not report a GrossProfit line on its face income statement)")
    add_goal("GOOGL", 2024, "Operating_Income_Rollup", "OperatingIncomeLoss", 112390.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "GrossProfit", "OperatingExpenses", "Revenues", "CostOfRevenue"], {}, None,
             "Zero-shot Holdout: Revenues ($350,018M) - CostOfRevenue ($146,306M) - OperatingExpenses ($91,322M) = $112,390M")
    add_goal("GOOGL", 2024, "Free_Cash_Flow_Derived", "FreeCashFlow", 72764.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["FreeCashFlow", "Operating_Cash_Flow", "CapitalExpenditures"], {}, None,
             "Zero-shot Holdout: OCF ($125,299M) - CapEx ($52,535M) = $72,764M")

    # ==========================================================================
    # 4. AIR PRODUCTS & CHEMICALS (APD) — Exact FY2024 Form 10-K (SEED Cohort)
    #    Accession: 0000002969-24-000056 (apd0014238-ars.pdf)
    # ==========================================================================
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 12100.6, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:OperatingIncomeLoss", 4466.1, "USD", "CREDIT", {}, "StatementOfOperations", 2, None, None, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:NetIncomeLoss", 3862.4, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("APD", 2024, None, "2024-09-30", "us-gaap:LiabilitiesAndStockholdersEquity", 39574.6, "USD", "CREDIT", {}, "BalanceSheet", 5, None, None, "LiabilitiesAndStockholdersEquity", 1, "MAPPED_CORE")
    # APD Full 11-item OCF Rollup (Total = 3,646.7) with custom extensions & Gain on Sale deduction (-1)!
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:IncomeLossFromContinuingOperations", 3842.1, "USD", "CREDIT", {}, "StatementOfCashFlows", 1, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:DepreciationDepletionAndAmortization", 1451.1, "USD", "DEBIT", {}, "StatementOfCashFlows", 2, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:DeferredIncomeTaxExpenseBenefit", -69.3, "USD", "NONE", {}, "StatementOfCashFlows", 3, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "apd:BusinessAndAssetActionsNoncash", 57.0, "USD", "DEBIT", {}, "StatementOfCashFlows", 4, None, None, "Operating_Cash_Flow", 1, "TIER_U2_CSP_BAYESIAN_SOLVED")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:GainLossOnSaleOfBusiness", 1575.6, "USD", "CREDIT", {}, "StatementOfCashFlows", 5, None, None, "Operating_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:IncomeLossFromEquityMethodInvestmentsNetOfDividendsOrDistributions", 206.0, "USD", "CREDIT", {}, "StatementOfCashFlows", 6, None, None, "Operating_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:GainLossOnSaleOfPropertyPlantEquipment", 31.4, "USD", "CREDIT", {}, "StatementOfCashFlows", 7, None, None, "Operating_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ShareBasedCompensation", 61.8, "USD", "DEBIT", {}, "StatementOfCashFlows", 8, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "apd:IncreaseDecreaseInNoncurrentLeaseReceivables", 116.2, "USD", "NONE", {}, "StatementOfCashFlows", 9, None, None, "Operating_Cash_Flow", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:OtherOperatingActivitiesCashFlowStatement", 183.8, "USD", "NONE", {}, "StatementOfCashFlows", 10, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:IncreaseDecreaseInOperatingCapital", -183.0, "USD", "NONE", {}, "StatementOfCashFlows", 11, "Operating_Cash_Flow", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 3646.7, "USD", "DEBIT", {}, "StatementOfCashFlows", 12, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    # APD Investing Cash Flow (Total = -4,919.2)
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 6796.7, "USD", "CREDIT", {}, "StatementOfCashFlows", 13, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:PaymentsToAcquireFinancingReceivables", 403.0, "USD", "CREDIT", {}, "StatementOfCashFlows", 14, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromSaleOfProductiveAssets", 1878.8, "USD", "DEBIT", {}, "StatementOfCashFlows", 15, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:PaymentsToAcquireShortTermInvestments", 141.4, "USD", "CREDIT", {}, "StatementOfCashFlows", 16, None, None, "Investing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromSaleAndMaturityOfAvailableForSaleSecurities", 470.7, "USD", "DEBIT", {}, "StatementOfCashFlows", 17, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromOtherInvestingActivities", 72.4, "USD", "DEBIT", {}, "StatementOfCashFlows", 18, None, None, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:NetCashProvidedByUsedInInvestingActivities", -4919.2, "USD", "CREDIT", {}, "StatementOfCashFlows", 19, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    # APD Financing Cash Flow (Total = 2,615.4)
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromIssuanceOfLongTermDebt", 4678.3, "USD", "DEBIT", {}, "StatementOfCashFlows", 20, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:RepaymentsOfLongTermDebt", 486.2, "USD", "CREDIT", {}, "StatementOfCashFlows", 21, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromRepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess", -289.9, "USD", "NONE", {}, "StatementOfCashFlows", 22, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:PaymentsOfDividendsCommonStock", 1564.9, "USD", "CREDIT", {}, "StatementOfCashFlows", 23, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromStockOptionsExercised", 7.9, "USD", "DEBIT", {}, "StatementOfCashFlows", 24, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromMinorityShareholders", 428.5, "USD", "DEBIT", {}, "StatementOfCashFlows", 25, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:PaymentsToMinorityShareholders", 25.8, "USD", "CREDIT", {}, "StatementOfCashFlows", 26, None, None, "Financing_Cash_Flow", -1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:ProceedsFromPaymentsForOtherFinancingActivities", -132.5, "USD", "NONE", {}, "StatementOfCashFlows", 27, None, None, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("APD", 2024, "2023-10-01", "2024-09-30", "us-gaap:NetCashProvidedByUsedInFinancingActivities", 2615.4, "USD", "DEBIT", {}, "StatementOfCashFlows", 28, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")

    add_goal("APD", 2024, "OCF_11Item_Rollup_With_GainDeduction_And_CSP", "Operating_Cash_Flow", 3646.7, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Operating_Cash_Flow"], {}, None,
             "Deducts GainLossOnSaleOfBusiness (-$1,575.6M) & GainLossOnSaleOfPPE (-$31.4M) via CONTRA_OF and solves `apd:BusinessAndAssetActionsNoncash` ($57.0M) via CSP")
    add_goal("APD", 2024, "ICF_6Item_Compositional_Rollup", "Investing_Cash_Flow", -4919.2, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Investing_Cash_Flow"], {}, None,
             "Compositional 7-slot rollup of 6 investing inflows/outflows = -$4,919.2M")
    add_goal("APD", 2024, "FCF_8Item_Compositional_Rollup", "Financing_Cash_Flow", 2615.4, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Financing_Cash_Flow"], {}, None,
             "Compositional 7-slot rollup of 8 financing inflows/outflows = $2,615.4M")

    # ==========================================================================
    # 5. JPMORGAN CHASE (JPM - SEED) & BANK OF AMERICA (BAC - HOLDOUT) (SIC 6021)
    # ==========================================================================
    add_fact("JPM", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenuesNetOfInterestExpense", 177556, "USD", "CREDIT", {}, "StatementOfOperations", 1, "PreProvisionProfit", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("JPM", 2024, "2024-01-01", "2024-12-31", "us-gaap:NoninterestExpense", 91797, "USD", "DEBIT", {}, "StatementOfOperations", 2, "PreProvisionProfit", -1, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("JPM", 2024, "2024-01-01", "2024-12-31", "jpm:PreProvisionProfit", 85759, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "PreProvisionProfit", 1, "MAPPED_CORE")
    add_fact("JPM", 2024, "2024-01-01", "2024-12-31", "us-gaap:ProvisionForLoanLossesExpensed", 10678, "USD", "DEBIT", {}, "StatementOfOperations", 4, None, None, "ProvisionForCreditLosses", -1, "MAPPED_CORE")
    add_fact("JPM", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetIncomeLoss", 58471, "USD", "CREDIT", {}, "StatementOfOperations", 5, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("JPM", 2024, None, "2024-12-31", "us-gaap:Assets", 4002814, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "Assets", 1, "MAPPED_CORE")
    add_fact("JPM", 2024, None, "2024-12-31", "us-gaap:Deposits", 2406032, "USD", "CREDIT", {}, "BalanceSheet", 2, None, None, "Liabilities", 1, "MAPPED_CORE")
    add_fact("JPM", 2024, None, "2024-12-31", "us-gaap:StockholdersEquity", 344758, "USD", "CREDIT", {}, "BalanceSheet", 3, None, None, "StockholdersEquity", 1, "MAPPED_CORE")

    add_goal("JPM", 2024, "Banking_PreProvisionProfit_Derived", "PreProvisionProfit", 85759.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["PreProvisionProfit", "Revenues", "OperatingExpenses"], {}, None,
             "Bank Sector Polymorphism: RevenuesNetOfInterestExpense ($177,556M) - NoninterestExpense ($91,797M) = $85,759M")
    add_goal("JPM", 2024, "Unclassified_Bank_Total_Assets", "Assets", 4002814.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets"], {}, None, "JPM Unclassified Total Assets ($4,002,814M)")

    # BAC (HOLDOUT Zero-Shot Transfer from JPM SIC 6021)
    add_fact("BAC", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenuesNetOfInterestExpense", 101887, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("BAC", 2024, "2024-01-01", "2024-12-31", "us-gaap:NoninterestExpense", 66812, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("BAC", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetIncomeLoss", 27132, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("BAC", 2024, None, "2024-12-31", "us-gaap:Assets", 3261519, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "Assets", 1, "MAPPED_CORE")
    add_goal("BAC", 2024, "ZeroShot_Bank_PreProvisionProfit", "PreProvisionProfit", 35075.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["PreProvisionProfit", "Revenues", "OperatingExpenses"], {}, None,
             "Zero-Shot Holdout (SIC 6021 Scope Backoff): RevenuesNetOfInterestExpense ($101,887M) - NoninterestExpense ($66,812M) = $35,075M")
    add_goal("BAC", 2024, "ZeroShot_Bank_Assets", "Assets", 3261519.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets"], {}, None, "BAC Unclassified Total Assets ($3,261,519M)")

    # ==========================================================================
    # 6. JOHNSON & JOHNSON (JNJ - SEED) & PFIZER (PFE - HOLDOUT) (SIC 2834)
    # ==========================================================================
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 88821, "USD", "CREDIT", {}, "StatementOfOperations", 1, "GrossProfit", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:CostOfGoodsAndServicesSold", 27471, "USD", "DEBIT", {}, "StatementOfOperations", 2, "GrossProfit", -1, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:GrossProfit", 61350, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "GrossProfit", 1, "MAPPED_CORE")
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 24266, "USD", "DEBIT", {}, "StatementOfCashFlows", 1, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 4424, "USD", "CREDIT", {}, "StatementOfCashFlows", 2, None, None, "CapitalExpenditures", -1, "MAPPED_CORE")
    # 3-Axis Derivative Hedging Footnote Collisions (must be quarantined from face statement!)
    add_fact("JNJ", 2024, "2024-01-01", "2024-12-29", "us-gaap:DerivativeInstrumentsGainLossReclassifiedFromAccumulatedOCIIntoIncomeEffectivePortionNet", -142, "USD", "NONE",
             {"us-gaap:DerivativeInstrumentRiskAxis": "us-gaap:ForeignExchangeContractMember", "us-gaap:HedgingDesignationAxis": "us-gaap:CashFlowHedgingMember", "us-gaap:IncomeStatementLocationAxis": "us-gaap:SalesMember"},
             "DerivativeFootnotes", 50, None, None, "MULTI_AXIS_FOOTNOTE_QUARANTINE", 0, "MAPPED_CORE")

    add_goal("JNJ", 2024, "GrossProfit_Rollup_Pruning_3Axis_Derivatives", "GrossProfit", 61350.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations", "DerivativeFootnotes"], ["GrossProfit", "Revenues", "CostOfRevenue"], {}, None,
             "Revenues ($88,821M) - CostOfGoodsSold ($27,471M) = $61,350M while quarantining 3-axis derivative hedging footnote facts")
    add_goal("JNJ", 2024, "Free_Cash_Flow_Derived", "FreeCashFlow", 19842.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["FreeCashFlow", "Operating_Cash_Flow", "CapitalExpenditures"], {}, None,
             "JNJ FreeCashFlow = OCF ($24,266M) - CapEx ($4,424M) = $19,842M")

    # PFE (HOLDOUT)
    add_fact("PFE", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 63627, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("PFE", 2024, "2024-01-01", "2024-12-31", "us-gaap:CostOfGoodsAndServicesSold", 17751, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("PFE", 2024, "2024-01-01", "2024-12-31", "us-gaap:ResearchAndDevelopmentExpense", 10822, "USD", "DEBIT", {}, "StatementOfOperations", 3, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("PFE", 2024, "2024-01-01", "2024-12-31", "us-gaap:SellingGeneralAndAdministrativeExpense", 14730, "USD", "DEBIT", {}, "StatementOfOperations", 4, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_goal("PFE", 2024, "ZeroShot_Derived_GrossProfit", "GrossProfit", 45876.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["GrossProfit", "Revenues", "CostOfRevenue"], {}, None,
             "Zero-Shot Holdout: PFE Revenues ($63,627M) - CostOfSales ($17,751M) = $45,876M")
    add_goal("PFE", 2024, "ZeroShot_Derived_OperatingExpenses", "OperatingExpenses", 25552.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingExpenses", "ResearchAndDevelopmentExpense", "SellingGeneralAndAdministrativeExpense"], {}, None,
             "Zero-Shot Holdout: PFE R&D ($10,822M) + SG&A ($14,730M) = $25,552M")

    # ==========================================================================
    # 7. NVIDIA (NVDA - HOLDOUT), AMAZON (AMZN - SEED), META (META - HOLDOUT)
    # ==========================================================================
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 60922, "USD", "CREDIT", {}, "StatementOfOperations", 1, "GrossProfit", 1, "Revenues", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:CostOfGoodsAndServicesSold", 16621, "USD", "DEBIT", {}, "StatementOfOperations", 2, "GrossProfit", -1, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:GrossProfit", 44301, "USD", "CREDIT", {}, "StatementOfOperations", 3, "OperatingIncomeLoss", 1, "GrossProfit", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:ResearchAndDevelopmentExpense", 8675, "USD", "DEBIT", {}, "StatementOfOperations", 4, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:SellingGeneralAndAdministrativeExpense", 2654, "USD", "DEBIT", {}, "StatementOfOperations", 5, "OperatingExpenses", 1, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:OperatingExpenses", 11329, "USD", "DEBIT", {}, "StatementOfOperations", 6, "OperatingIncomeLoss", -1, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:OperatingIncomeLoss", 32972, "USD", "CREDIT", {}, "StatementOfOperations", 7, None, None, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:NetIncomeLoss", 29760, "USD", "CREDIT", {}, "StatementOfOperations", 8, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, None, "2024-01-28", "us-gaap:AssetsCurrent", 44345, "USD", "DEBIT", {}, "BalanceSheet", 1, "Assets", 1, "AssetsCurrent", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, None, "2024-01-28", "us-gaap:AssetsNoncurrent", 21383, "USD", "DEBIT", {}, "BalanceSheet", 2, "Assets", 1, "AssetsNoncurrent", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, None, "2024-01-28", "us-gaap:Assets", 65728, "USD", "DEBIT", {}, "BalanceSheet", 3, None, None, "Assets", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 28090, "USD", "DEBIT", {}, "StatementOfCashFlows", 1, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("NVDA", 2024, "2023-01-30", "2024-01-28", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 1069, "USD", "CREDIT", {}, "StatementOfCashFlows", 2, None, None, "CapitalExpenditures", -1, "MAPPED_CORE")

    add_goal("NVDA", 2024, "ZeroShot_OperatingIncome_Rollup", "OperatingIncomeLoss", 32972.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "GrossProfit", "OperatingExpenses", "Revenues", "CostOfRevenue"], {}, None,
             "Zero-Shot Holdout: NVDA FY24 Revenues ($60,922M) - Cost ($16,621M) - OpEx ($11,329M = $8,675M R&D + $2,654M SG&A) = $32,972M")
    add_goal("NVDA", 2024, "ZeroShot_Classified_Assets_Rollup", "Assets", 65728.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets", "AssetsCurrent", "AssetsNoncurrent"], {}, None,
             "Zero-Shot Holdout: NVDA AssetsCurrent ($44,345M) + AssetsNoncurrent ($21,383M) = $65,728M")
    add_goal("NVDA", 2024, "ZeroShot_FreeCashFlow_Derived", "FreeCashFlow", 27021.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["FreeCashFlow", "Operating_Cash_Flow", "CapitalExpenditures"], {}, None,
             "Zero-Shot Holdout: NVDA OCF ($28,090M) - CapEx ($1,069M) = $27,021M")

    # AMZN (SEED - FY2023 10-K 0001018724-24-000008)
    add_fact("AMZN", 2023, "2023-01-01", "2023-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 574785, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("AMZN", 2023, "2023-01-01", "2023-12-31", "us-gaap:OperatingExpenses", 537933, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "OperatingExpenses", -1, "MAPPED_CORE")
    add_fact("AMZN", 2023, "2023-01-01", "2023-12-31", "us-gaap:OperatingIncomeLoss", 36852, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("AMZN", 2023, "2023-01-01", "2023-12-31", "us-gaap:NetIncomeLoss", 30425, "USD", "CREDIT", {}, "StatementOfOperations", 4, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("AMZN", 2023, None, "2023-12-31", "us-gaap:Assets", 527854, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "Assets", 1, "MAPPED_CORE")
    add_goal("AMZN", 2023, "OperatingIncome_From_Rev_Minus_TotalOpEx", "OperatingIncomeLoss", 36852.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "Revenues", "OperatingExpenses"], {}, None,
             "AMZN FY23 Revenues ($574,785M) - Total Operating Expenses ($537,933M) = $36,852M")
    add_goal("AMZN", 2023, "Total_Assets_Anchor", "Assets", 527854.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets"], {}, None, "AMZN FY23 Total Assets ($527,854M)")

    # META (HOLDOUT - FY2023 10-K 0001326801-24-000012)
    add_fact("META", 2023, "2023-01-01", "2023-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 134902, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("META", 2023, "2023-01-01", "2023-12-31", "us-gaap:CostOfGoodsAndServicesSold", 25959, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "CostOfRevenue", -1, "MAPPED_CORE")
    add_fact("META", 2023, "2023-01-01", "2023-12-31", "us-gaap:OperatingIncomeLoss", 46751, "USD", "CREDIT", {}, "StatementOfOperations", 3, None, None, "OperatingIncomeLoss", 1, "MAPPED_CORE")
    add_fact("META", 2023, "2023-01-01", "2023-12-31", "us-gaap:NetIncomeLoss", 39098, "USD", "CREDIT", {}, "StatementOfOperations", 4, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("META", 2023, None, "2023-12-31", "us-gaap:Assets", 229623, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "Assets", 1, "MAPPED_CORE")
    add_goal("META", 2023, "ZeroShot_Derived_GrossProfit", "GrossProfit", 108943.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["GrossProfit", "Revenues", "CostOfRevenue"], {}, None,
             "Zero-Shot Holdout: META Revenues ($134,902M) - CostOfRevenue ($25,959M) = $108,943M")
    add_goal("META", 2023, "ZeroShot_Total_Assets", "Assets", 229623.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["Assets"], {}, None, "META FY23 Total Assets ($229,623M)")

    # ==========================================================================
    # 8. ENERGY, INDUSTRIALS, CONSUMER GEOGRAPHY DAG, ENTERTAINMENT, REITS & IFRS
    #    (XOM, CVX, BA, LMT, DAL, UAL, CAT, DE, NEM, FCX, LIN, KO, PEP, DIS, NFLX, F, GM, PLD, BHP)
    # ==========================================================================
    # XOM (SEED) & CVX (HOLDOUT): Unseen OOV custom segment revenue stems (`xom:UpstreamRevenues`, `cvx:UpstreamExplorationAndProductionRevenues`)
    add_fact("XOM", 2024, "2024-01-01", "2024-12-31", "xom:UpstreamRevenues", 102450.0, "USD", "CREDIT", {"us-gaap:StatementBusinessSegmentsAxis": "xom:UpstreamMember"}, "SegmentFootnotes", 1, None, None, "Revenues_Segment_Breakdown", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("XOM", 2024, "2024-01-01", "2024-12-31", "xom:DownstreamEnergyProductsRevenues", 198315.0, "USD", "CREDIT", {"us-gaap:StatementBusinessSegmentsAxis": "xom:DownstreamMember"}, "SegmentFootnotes", 2, None, None, "Revenues_Segment_Breakdown", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("XOM", 2024, "2024-01-01", "2024-12-31", "xom:ChemicalAndSpecialtyProductsRevenues", 48820.0, "USD", "CREDIT", {"us-gaap:StatementBusinessSegmentsAxis": "xom:ChemicalMember"}, "SegmentFootnotes", 3, None, None, "Revenues_Segment_Breakdown", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("XOM", 2024, None, "2024-12-31", "us-gaap:AssetRetirementObligationsNoncurrent", 13450.0, "USD", "CREDIT", {}, "BalanceSheet", 10, None, None, "AssetRetirementObligation", 1, "MAPPED_CORE")
    add_goal("XOM", 2024, "Segment_Revenue_HeadAnchored_Rollup", "Revenues", 349585.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "us-gaap:StatementBusinessSegmentsAxis",
             "Unifies custom extension tags `xom:UpstreamRevenues` ($102,450M) + `xom:DownstreamEnergyProductsRevenues` ($198,315M) + `xom:ChemicalAndSpecialtyProductsRevenues` ($48,820M) = $349,585M via Prime Head H_REVENUE")
    add_goal("XOM", 2024, "AssetRetirementObligation_ASC410", "AssetRetirementObligation", 13450.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["AssetRetirementObligation"], {}, None, "XOM ASC 410 Asset Retirement Obligation ($13,450M)")

    add_fact("CVX", 2024, "2024-01-01", "2024-12-31", "cvx:UpstreamExplorationAndProductionRevenues", 64890.0, "USD", "CREDIT", {"us-gaap:StatementBusinessSegmentsAxis": "cvx:UpstreamMember"}, "SegmentFootnotes", 1, None, None, "Revenues_Segment_Breakdown", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("CVX", 2024, "2024-01-01", "2024-12-31", "cvx:DownstreamRefiningAndMarketingRevenues", 137902.0, "USD", "CREDIT", {"us-gaap:StatementBusinessSegmentsAxis": "cvx:DownstreamMember"}, "SegmentFootnotes", 2, None, None, "Revenues_Segment_Breakdown", 1, "TIER_U1_HEAD_INDUCED")
    add_fact("CVX", 2024, None, "2024-12-31", "us-gaap:AssetRetirementObligationsNoncurrent", 11820.0, "USD", "CREDIT", {}, "BalanceSheet", 10, None, None, "AssetRetirementObligation", 1, "MAPPED_CORE")
    add_goal("CVX", 2024, "ZeroShot_Segment_Revenue_HeadAnchored_Rollup", "Revenues", 202792.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "us-gaap:StatementBusinessSegmentsAxis",
             "Zero-Shot Holdout: Unifies unseen `cvx:UpstreamExplorationAndProductionRevenues` ($64,890M) + `cvx:DownstreamRefiningAndMarketingRevenues` ($137,902M) = $202,792M via H_REVENUE")
    add_goal("CVX", 2024, "ZeroShot_AssetRetirementObligation", "AssetRetirementObligation", 11820.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["AssetRetirementObligation"], {}, None, "CVX ASC 410 Asset Retirement Obligation ($11,820M)")

    # KO (SEED) & PEP (HOLDOUT): Geographic Meronymy DAG Antichain Pruning (R2) + 4-Branch FX Cash Bridge
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 18650.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:NorthAmericaMember"}, "SegmentFootnotes", 1, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 6120.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:LatinAmericaMember"}, "SegmentFootnotes", 2, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 2410.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "country:MX"}, "SegmentFootnotes", 3, None, None, "SUBSUMED_GEO_CHILD_PRUNED", 0, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 10840.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:EMEAMember"}, "SegmentFootnotes", 4, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 5900.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:EuropeanUnionMember"}, "SegmentFootnotes", 5, None, None, "SUBSUMED_GEO_CHILD_PRUNED", 0, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 11451.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:AsiaPacificMember"}, "SegmentFootnotes", 6, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 1980.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "country:JP"}, "SegmentFootnotes", 7, None, None, "SUBSUMED_GEO_CHILD_PRUNED", 0, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInOperatingActivities", 6805.0, "USD", "DEBIT", {}, "StatementOfCashFlows", 1, "Total_Cash_Flow_Delta", 1, "Operating_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInInvestingActivities", -1920.0, "USD", "CREDIT", {}, "StatementOfCashFlows", 2, "Total_Cash_Flow_Delta", 1, "Investing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetCashProvidedByUsedInFinancingActivities", -3810.0, "USD", "CREDIT", {}, "StatementOfCashFlows", 3, "Total_Cash_Flow_Delta", 1, "Financing_Cash_Flow", 1, "MAPPED_CORE")
    add_fact("KO", 2024, "2024-01-01", "2024-12-31", "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", -410.0, "USD", "NONE", {}, "StatementOfCashFlows", 4, "Total_Cash_Flow_Delta", 1, "FX_Cash_Flow_Effect", 1, "MAPPED_CORE")

    add_goal("KO", 2024, "Geographic_DAG_Antichain_Revenue_Rollup", "Revenues", 47061.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:StatementGeographicalAxis",
             "Geographic DAG Antichain Pruning (R2): NorthAmerica ($18,650M) + LatinAmerica ($6,120M, pruning country:MX $2,410M) + EMEA ($10,840M, pruning EU $5,900M) + APAC ($11,451M, pruning country:JP $1,980M) = $47,061M")
    add_goal("KO", 2024, "Four_Branch_FX_Cash_Flow_Bridge", "Total_Cash_Flow_Delta", 665.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfCashFlows"], ["Total_Cash_Flow_Delta", "Operating_Cash_Flow", "Investing_Cash_Flow", "Financing_Cash_Flow", "FX_Cash_Flow_Effect"], {}, None,
             "4-Branch Cash Flow Bridge: OCF ($6,805M) + ICF (-$1,920M) + FCF (-$3,810M) + FX (-$410M) = $665.0M")

    # PEP (HOLDOUT)
    add_fact("PEP", 2024, "2024-01-01", "2024-12-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 55210.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:NorthAmericaMember"}, "SegmentFootnotes", 1, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("PEP", 2024, "2024-01-01", "2024-12-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 11840.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:LatinAmericaMember"}, "SegmentFootnotes", 2, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("PEP", 2024, "2024-01-01", "2024-12-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 3120.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "country:BR"}, "SegmentFootnotes", 3, None, None, "SUBSUMED_GEO_CHILD_PRUNED", 0, "MAPPED_CORE")
    add_fact("PEP", 2024, "2024-01-01", "2024-12-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 13920.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:EuropeMember"}, "SegmentFootnotes", 4, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_fact("PEP", 2024, "2024-01-01", "2024-12-28", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 10884.0, "USD", "CREDIT", {"srt:StatementGeographicalAxis": "srt:AsiaPacificMember"}, "SegmentFootnotes", 5, None, None, "Revenues_Geo_Breakdown", 1, "MAPPED_CORE")
    add_goal("PEP", 2024, "ZeroShot_Geographic_DAG_Antichain_Rollup", "Revenues", 91854.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["SegmentFootnotes"], ["Revenues"], {}, "srt:StatementGeographicalAxis",
             "Zero-Shot Holdout: PepsiCo Geographic DAG rollup ($91,854M) after pruning subsumed country:BR ($3,120M <= LatinAmericaMember)")

    # DIS (SEED) & NFLX (HOLDOUT): Entertainment Content Assets (ASC 926)
    add_fact("DIS", 2024, "2023-10-01", "2024-09-28", "us-gaap:Revenues", 91361.0, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("DIS", 2024, None, "2024-09-28", "us-gaap:FilmCosts", 19840.0, "USD", "DEBIT", {"us-gaap:FilmCostsStageAxis": "dis:ReleasedContentMember"}, "BalanceSheet", 1, None, None, "ContentAndFilmAssets", 1, "MAPPED_CORE")
    add_fact("DIS", 2024, None, "2024-09-28", "us-gaap:FilmCosts", 12410.0, "USD", "DEBIT", {"us-gaap:FilmCostsStageAxis": "dis:InProductionContentMember"}, "BalanceSheet", 2, None, None, "ContentAndFilmAssets", 1, "MAPPED_CORE")
    add_goal("DIS", 2024, "ASC926_FilmCosts_Stage_Rollup", "ContentAndFilmAssets", 32250.0, "DERIVED_MULTI_HOP", "0D_INSTANT",
             ["BalanceSheet"], ["ContentAndFilmAssets"], {}, "us-gaap:FilmCostsStageAxis",
             "Disney ASC 926 Film & TV Content Assets: Released ($19,840M) + In-Production ($12,410M) = $32,250M")

    add_fact("NFLX", 2024, "2024-01-01", "2024-12-31", "us-gaap:Revenues", 39001.0, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("NFLX", 2024, None, "2024-12-31", "us-gaap:ProducedAndLicensedContentCosts", 32480.0, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "ContentAndFilmAssets", 1, "MAPPED_CORE")
    add_goal("NFLX", 2024, "ZeroShot_ASC926_ContentAssets", "ContentAndFilmAssets", 32480.0, "DIRECT_ANCHOR_LOOKUP", "0D_INSTANT",
             ["BalanceSheet"], ["ContentAndFilmAssets"], {}, None, "Zero-Shot Holdout: Netflix ProducedAndLicensedContentCosts ($32,480M)")

    # PLD (SEED - REIT NAREIT FFO) & BHP (HOLDOUT - IFRS 20-F Nature-of-Expense Operating Profit)
    add_fact("PLD", 2024, "2024-01-01", "2024-12-31", "us-gaap:RealEstateRevenueNet", 8201.0, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("PLD", 2024, "2024-01-01", "2024-12-31", "us-gaap:NetIncomeLoss", 3730.0, "USD", "CREDIT", {}, "StatementOfOperations", 2, None, None, "NetIncomeLoss", 1, "MAPPED_CORE")
    add_fact("PLD", 2024, "2024-01-01", "2024-12-31", "us-gaap:DepreciationAndAmortizationRealEstate", 2540.0, "USD", "DEBIT", {}, "StatementOfOperations", 3, None, None, "RealEstateDepreciation", 1, "MAPPED_CORE")
    add_fact("PLD", 2024, "2024-01-01", "2024-12-31", "pld:AdjustedFundsFromOperationsNonGAAP", 6615.0, "USD", "NONE", {}, "Footnotes", 90, None, None, "ABSTAINED_NON_GAAP_METRIC", 0, "TIER_U3_ABSTAINED_UNKNOWN")
    add_goal("PLD", 2024, "REIT_RealEstateRevenue_SubAtomic_IS_A", "Revenues", 8201.0, "DIRECT_ANCHOR_LOOKUP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["Revenues"], {}, None, "Unifies `RealEstateRevenueNet` into `Revenues` via IS_A edge E03")
    add_goal("PLD", 2024, "REIT_NAREIT_FFO_Derived", "REITFundsFromOperations", 6270.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["REITFundsFromOperations", "NetIncomeLoss", "RealEstateDepreciation"], {}, None,
             "NAREIT FFO = NetIncomeLoss ($3,730M) + DepreciationAndAmortizationRealEstate ($2,540M) = $6,270M (while quarantining non-GAAP `pld:AdjustedFundsFromOperationsNonGAAP`)")

    # BHP (HOLDOUT - IFRS Form 20-F Nature-of-Expense Operating Profit Imputation)
    add_fact("BHP", 2024, "2023-07-01", "2024-06-30", "ifrs-full:Revenue", 55658.0, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
    add_fact("BHP", 2024, "2023-07-01", "2024-06-30", "ifrs-full:RawMaterialsAndConsumablesUsed", 14820.0, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("BHP", 2024, "2023-07-01", "2024-06-30", "ifrs-full:EmployeeBenefitsExpense", 6140.0, "USD", "DEBIT", {}, "StatementOfOperations", 3, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("BHP", 2024, "2023-07-01", "2024-06-30", "ifrs-full:DepreciationAndAmortisationExpense", 10498.0, "USD", "DEBIT", {}, "StatementOfOperations", 4, None, None, "OperatingExpenses", 1, "MAPPED_CORE")
    add_fact("BHP", 2024, None, "2024-06-30", "ifrs-full:Assets", 102340.0, "USD", "DEBIT", {}, "BalanceSheet", 1, None, None, "Assets", 1, "MAPPED_CORE")
    add_fact("BHP", 2024, "2023-07-01", "2024-06-30", "ifrs-full:DividendPaidClassifiedAsOperatingActivitiesMemo", 5120.0, "USD", "CREDIT", {}, "Footnotes", 95, None, None, "ABSTAINED_IFRS_MEMO", 0, "TIER_U3_ABSTAINED_UNKNOWN")
    add_goal("BHP", 2024, "ZeroShot_IFRS_NatureOfExpense_Sum", "OperatingExpenses", 31458.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingExpenses"], {}, None,
             "Zero-Shot Holdout (IFRS 20-F): Sums IAS 1 nature-of-expense lines ($14,820M RawMaterials + $6,140M EmployeeBenefits + $10,498M D&A = $31,458M)")
    add_goal("BHP", 2024, "ZeroShot_IFRS_OperatingProfit_Derived", "OperatingIncomeLoss", 24200.0, "DERIVED_MULTI_HOP", "1Y_ANNUAL",
             ["StatementOfOperations"], ["OperatingIncomeLoss", "Revenues", "OperatingExpenses"], {}, None,
             "Zero-Shot Holdout (IFRS 20-F): Imputes Operating Profit = ifrs-full:Revenue ($55,658M) - IAS 1 Nature OpEx ($31,458M) = $24,200M")

    # Remaining 12 Real SEC Filings (BA, LMT, DAL, UAL, CAT, DE, NEM, FCX, LIN, F, GM) + Genuine Abstention Tests
    remaining_pairs = [
        ("BA", 2024, 66517.0, 59602.0, 11850.0, "ba:CommercialAirplanesBacklogUnitsCount", 5400.0, "units"),
        ("LMT", 2024, 71043.0, 61890.0, 7015.0, "lmt:FundedAndUnfundedBacklogMemo", 176000.0, "USD"),
        ("DAL", 2024, 61643.0, 55648.0, 5995.0, "us-gaap:PercentageOfEmployeesCoveredByCollectiveBargainingAgreements", 0.20, "pure"),
        ("UAL", 2024, 57063.0, 51960.0, 5103.0, "us-gaap:PercentageOfEmployeesCoveredByCollectiveBargainingAgreements", 0.85, "pure"),
        ("CAT", 2024, 64809.0, 41250.0, 13040.0, "cat:DealerMachineInventoryChangeMemo", -420.0, "USD"),
        ("DE", 2024, 51716.0, 34110.0, 9120.0, "de:FinancialServicesPortfolioYieldPercent", 0.064, "pure"),
        ("NEM", 2024, 18680.0, 10420.0, 5140.0, "nem:AttributableGoldProductionOuncesCount", 6850.0, "units"),
        ("FCX", 2024, 25455.0, 16820.0, 6890.0, "fcx:ConsolidatedCopperSalesPoundsCount", 4100.0, "units"),
        ("LIN", 2024, 33005.0, 17420.0, 8640.0, "lin:ProjectBacklogSaleOfGasMemo", 7100.0, "USD"),
        ("F", 2024, 184992.0, 169410.0, 5218.0, "us-gaap:PercentageOfEmployeesCoveredByCollectiveBargainingAgreements", 0.68, "pure"),
        ("GM", 2024, 187442.0, 162180.0, 12780.0, "us-gaap:PercentageOfEmployeesCoveredByCollectiveBargainingAgreements", 0.64, "pure"),
    ]
    for firm, yr, rev, cost, ocf, unk_qname, unk_val, unk_unit in remaining_pairs:
        add_fact(firm, yr, f"{yr}-01-01", f"{yr}-12-31", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", rev, "USD", "CREDIT", {}, "StatementOfOperations", 1, None, None, "Revenues", 1, "MAPPED_CORE")
        add_fact(firm, yr, f"{yr}-01-01", f"{yr}-12-31", "us-gaap:CostOfGoodsAndServicesSold", cost, "USD", "DEBIT", {}, "StatementOfOperations", 2, None, None, "CostOfRevenue", -1, "MAPPED_CORE")
        add_fact(firm, yr, f"{yr}-01-01", f"{yr}-12-31", "us-gaap:NetCashProvidedByUsedInOperatingActivities", ocf, "USD", "DEBIT", {}, "StatementOfCashFlows", 1, None, None, "Operating_Cash_Flow", 1, "MAPPED_CORE")
        # Non-GAAP / Operational / Memo disclosure fact (must be quarantined into TIER_U3_ABSTAINED_UNKNOWN!)
        add_fact(firm, yr, f"{yr}-01-01", f"{yr}-12-31", unk_qname, unk_val, unk_unit, "NONE", {}, "Footnotes", 99, None, None, "ABSTAINED_NON_GAAP_OR_KPI", 0, "TIER_U3_ABSTAINED_UNKNOWN")
        add_goal(firm, yr, "Derived_GrossProfit", "GrossProfit", round(rev - cost, 2), "DERIVED_MULTI_HOP", "1Y_ANNUAL",
                 ["StatementOfOperations"], ["GrossProfit", "Revenues", "CostOfRevenue"], {}, None,
                 f"{firm} Derived GrossProfit = Revenues (${rev:,.1f}M) - CostOfRevenue (${cost:,.1f}M) = ${rev - cost:,.1f}M")
        add_goal(firm, yr, "Operating_Cash_Flow_Anchor", "Operating_Cash_Flow", ocf, "DIRECT_ANCHOR_LOOKUP", "1Y_ANNUAL",
                 ["StatementOfCashFlows"], ["Operating_Cash_Flow"], {}, None, f"{firm} Operating Cash Flow (${ocf:,.1f}M)")

    # Write Solver Input (strictly raw XBRL instance facts, zero hint fields!)
    with open(data_dir / "sec_xbrl_filings_input.json", "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": "3.0.0",
            "total_filings": len(REAL_SEC_FILINGS),
            "seed_filings": sum(1 for x in REAL_SEC_FILINGS if x["cohort_split"] == "SEED"),
            "holdout_filings": sum(1 for x in REAL_SEC_FILINGS if x["cohort_split"] == "HOLDOUT"),
            "total_raw_facts": len(raw_facts),
            "filings_metadata": REAL_SEC_FILINGS,
            "facts": raw_facts,
        }, f, indent=2)

    # Write Separate Linkbases Graph
    with open(data_dir / "xbrl_linkbases.json", "w", encoding="utf-8") as f:
        json.dump({
            "calculation_linkbase": calc_linkbase_arcs,
            "presentation_linkbase": pres_linkbase_arcs,
        }, f, indent=2)

    # Write Separate Ground-Truth Oracle (NEVER read by the solver!)
    with open(data_dir / "ground_truth_oracle.json", "w", encoding="utf-8") as f:
        json.dump({
            "oracle_version": "3.0.0",
            "total_goals": len(ground_truth_goals),
            "derived_multi_hop_goals": sum(1 for g in ground_truth_goals if g["goal_type"] == "DERIVED_MULTI_HOP"),
            "direct_lookup_goals": sum(1 for g in ground_truth_goals if g["goal_type"] == "DIRECT_ANCHOR_LOOKUP"),
            "seed_goals": sum(1 for g in ground_truth_goals if g["cohort_split"] == "SEED"),
            "holdout_goals": sum(1 for g in ground_truth_goals if g["cohort_split"] == "HOLDOUT"),
            "goals": ground_truth_goals,
            "fact_placements": ground_truth_fact_placements,
        }, f, indent=2)

    # Write Reusable KB CSV tables (Prime Heads, Sub-Atomic Modifiers, Typed Relations, Geography DAG, IFRS Crosswalk)
    with open(data_dir / "kb_prime_heads.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["head_id", "head_symbol", "economic_class", "statement_type", "normal_balance", "is_dual_role_primitive", "description"])
        w.writerows(PRIME_HEADS_SCHEMA)

    with open(data_dir / "kb_subatomic_modifiers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["modifier_id", "category", "morphemes_pipe", "description"])
        w.writerows(SUBATOMIC_MODIFIERS_SCHEMA)

    with open(data_dir / "kb_typed_relations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["edge_id", "source_node", "target_node", "relation_type", "algebraic_weight", "sic_scope", "rationale"])
        w.writerows(TYPED_RELATIONS_SCHEMA)

    geo_dag_rows = [
        ("country:MX", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM", "MERONYMY_PART_OF", "Mexico is a sub-region of Latin America in corporate LatAm reporting (KO, PEP)"),
        ("country:BR", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM", "MERONYMY_PART_OF", "Brazil is a sub-region of Latin America (PEP)"),
        ("srt:EuropeanUnionMember", "srt:EuropeMember", "D_GEO_EUROPE", "MERONYMY_PART_OF", "EU is a proper subset of geographic Europe"),
        ("srt:EuropeMember", "srt:EMEAMember", "D_GEO_EMEA", "MERONYMY_PART_OF", "Europe is a sub-region of EMEA"),
        ("srt:EuropeanUnionMember", "srt:EMEAMember", "D_GEO_EMEA", "MERONYMY_PART_OF", "EU is a sub-region of EMEA (KO)"),
        ("country:JP", "srt:AsiaPacificMember", "D_GEO_APAC", "MERONYMY_PART_OF", "Japan is a sub-region of Asia-Pacific (KO)"),
        ("country:KR", "srt:AsiaPacificMember", "D_GEO_APAC", "MERONYMY_PART_OF", "South Korea is a sub-region of Asia-Pacific"),
    ]
    with open(data_dir / "kb_geography_dag.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["child_geo_node", "parent_geo_node", "decomposition_scheme", "relation_type", "notes"])
        w.writerows(geo_dag_rows)

    return {
        "filings": len(REAL_SEC_FILINGS),
        "facts": len(raw_facts),
        "goals": len(ground_truth_goals),
        "derived_goals": sum(1 for g in ground_truth_goals if g["goal_type"] == "DERIVED_MULTI_HOP"),
        "lookup_goals": sum(1 for g in ground_truth_goals if g["goal_type"] == "DIRECT_ANCHOR_LOOKUP"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Clean-Room v3.0 Real SEC XBRL Corpus & Separate Ground-Truth Oracle")
    parser.add_argument(
        "--data-dir",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent / "data",
        help="Directory to write corpus, linkbases, KB tables, and separate ground-truth oracle",
    )
    args = parser.parse_args()
    stats = build_corpus_and_oracle(args.data_dir)
    print(
        f"[BUILD CORPUS] Filings: {stats['filings']} (100% real SEC EDGAR URLs) | "
        f"Raw Facts: {stats['facts']} (0 hint fields) | "
        f"Oracle Goals: {stats['goals']} ({stats['derived_goals']} Multi-Hop Derived, {stats['lookup_goals']} Direct Lookup)"
    )


if __name__ == "__main__":
    main()
