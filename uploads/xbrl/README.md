# Clean-Room Declarative & Sub-Atomic XBRL Unification Engine (`v3.0`)

A self-contained, modular, zero-Pandas Python & 3NF SQLite engine implementing the **5-Layer Classical & Probabilistic AI XBRL Unification Architecture** (`7-Slot DCG` + `6D Orthogonal Coordinates` + `Sub-Atomic Prime Heads & Typed Relations` + `Evidence/Confidence KB with 4-Tier Scope Backoff` + `CSP/Bayesian/Markov Unknown Resolution Loop` + `Independent Accounting Identity Oracle`).

## Quickstart & CLI Usage (Zero Hardcoded Paths)

Every script in `src/` uses relative paths anchored to the repository root and accepts standard `argparse` CLI flags (`--data-dir`, `--output-dir`, `--mode`):

```bash
# 1. Run full end-to-end verification (both In-Memory and 3NF SQLite engines)
bash verify.sh both

# 2. Run strictly in-memory (no SQLite disk file required)
bash verify.sh in-memory

# 3. Run individual modular CLI stages with custom directories
python3 src/build_real_sec_corpus.py --data-dir ./data
python3 src/identity_oracle.py --data-dir ./data --output-dir ./outputs --mode in-memory
python3 src/build_audit_workbook.py --data-dir ./data --output-dir ./outputs --output-file ./outputs/xbrl_clean_engine_v3_audit.xlsx
```

## What Was Remediated in `v3.0` (Audit Checklist)

1. **100% Reproducible & Self-Contained Package**:
   - All builder, parser, KB, solver, identity oracle, and Excel generator modules reside inside `src/` in the archive.
   - Zero `/working_dir` or machine-specific paths exist anywhere in the codebase.
   - Clean `.git` repository initialized on local POSIX storage and verified via `git fsck --full`.
2. **100% Real Sourced SEC EDGAR Filings (`30/30` Accession URLs, `0` `company_tickers.json` Citations)**:
   - Every filing in `data/sec_xbrl_filings_input.json` cites its exact `sec.gov/Archives/edgar/data/<CIK>/<ACCESSION>/<DOC>` filing URL.
   - Spot-checked **Microsoft (`MSFT`) FY2024 Form 10-K (`0000950170-24-087843`, `msft-20240630.htm`)** matches the exact SEC filing tables:
     - **Note 19 Product & Service Offerings (`srt:ProductOrServiceAxis`)**: Server products & cloud services **`$97,726M`**, Office products & cloud services **`$54,875M`**, Windows **`$23,244M`**, Gaming **`$21,503M`**, LinkedIn **`$16,372M`**, Search & news advertising **`$12,576M`**, Enterprise & partner services **`$7,594M`**, Dynamics **`$6,481M`**, Devices **`$4,706M`**, Other **`$45M`** $\rightarrow$ Exact sum = **`$245,122M`**.
     - **Note 19 Reportable Segments (`StatementBusinessSegmentsAxis`)**: Productivity & Business Processes **`$77,728M`** (OpInc **`$40,540M`**), Intelligent Cloud **`$105,362M`** (OpInc **`$49,584M`**), More Personal Computing **`$62,032M`** (OpInc **`$19,309M`**) $\rightarrow$ Exact sum = **`$245,122M`** Revenue / **`$109,433M`** Operating Income.
     - **Note 13 Unearned Revenue (`ContractWithCustomerLiability`)**: Short-term **`$57,582M`** + Long-term **`$2,602M`** = **`$60,184M`** total unearned revenue (by segment: PBP **`$30,879M`** + IC **`$23,117M`** + MPC **`$6,188M`** = **`$60,184M`**).
3. **Zero Hint Fields in Solver Input (`data/sec_xbrl_filings_input.json`)**:
   - Pre-filled hint fields (`parent_measure_hint`, `calc_weight`, `sign_polarity`, `notes`, `expected_value`) have been completely removed from the solver input facts.
   - Native XBRL calculation linkbase arcs live in `data/xbrl_linkbases.json` and are intentionally absent on custom extensions (`aapl:VendorNonTradeReceivablesCurrent`, `aapl:OtherNonCashIncomeExpenseCustom`, `msft:DepreciationAmortizationAndOther`, `msft:NetRecognizedLossesGainsOnInvestmentsAndDerivatives`, `apd:BusinessAndAssetActionsNoncash`, `xom:UpstreamRevenues`, `cvx:UpstreamExplorationAndProductionRevenues`) so the solver must genuinely resolve them via 7-Slot DCG, Sub-Atomic Prime Heads, and CSP/Bayesian/Markov inference.
4. **Separate Ground-Truth Oracle (`data/ground_truth_oracle.json`) & Independent Accounting Identity Oracle (`src/identity_oracle.py`)**:
   - Ground-truth evaluation targets are stored in `data/ground_truth_oracle.json`, which no solver module imports or reads.
   - **75.6% (`59 / 78`) of benchmark goals are Multi-Hop Derived & Compositional Goals** (`DERIVED_MULTI_HOP`), compared to only `24.4%` (`19 / 78`) direct anchor lookups.
   - Zero cross-solver copying: the In-Memory Engine and the 11-Table 3NF SQLite Engine execute independently (`cross_solver_fallback_copies == 0`).
5. **Cryptographic Seed KB Freeze Before Scoring Held-Out Filings (`outputs/kb_frozen_seed_state.json`)**:
   - The Knowledge Base is calibrated on the `15` `SEED` filings, frozen via `kb.freeze()` (`SHA-256: 38e46be9118b8618...`), and verified immutable before and after scoring the `15` `HOLDOUT` filings.

## Repository Structure

```text
xbrl_declarative_engine_v3/
├── README.md
├── SPECIFICATION_AND_ARCHITECTURE_v3.md
├── verify.sh
├── src/
│   ├── __init__.py
│   ├── dcg_and_subatomic_parser.py      # Layer 0: 7-Slot DCG + 6D Coords + 15 Prime Heads & 32 Modifiers
│   ├── kb_evidence_and_backoff.py       # Declarative KB, Evidence/Confidence, 4-Tier Scope Backoff & Seed Freeze
│   ├── in_memory_and_sql_solver.py      # Layers 1-4 In-Memory & 11-Table 3NF SQLite Engines + Unknown Loop
│   ├── identity_oracle.py               # Independent Accounting Identity Oracle, §9 Metrics & 4-Way Ablation
│   ├── build_real_sec_corpus.py         # Real SEC EDGAR 30-filing corpus & separate ground-truth oracle builder
│   └── build_audit_workbook.py          # Zero-Pandas openpyxl 9-tab Excel audit workbook generator
├── data/
│   ├── sec_xbrl_filings_input.json      # 355 raw XBRL facts across 30 real SEC filings (0 hint fields)
│   ├── xbrl_linkbases.json              # Separate XBRL presentation & calculation linkbase arcs
│   ├── ground_truth_oracle.json         # Separate ground-truth evaluation oracle (78 goals: 59 derived, 19 lookup)
│   ├── kb_prime_heads.csv               # 15 Indivisible Prime Heads (incl. dual-role H_GAIN_LOSS, H_OCI_FLOW, H_AOCI_STOCK)
│   ├── kb_subatomic_modifiers.csv       # 32 Sub-Atomic Domain & Valuation Modifiers
│   ├── kb_typed_relations.csv           # 55 Typed Relational Edges (IS_A, PART_OF, CONTRA_OF, DUAL_OF, DERIVED_FROM)
│   └── kb_geography_dag.csv             # Geographic Meronymy DAG for R2 Antichain Pruning
└── outputs/
    ├── section9_evaluation_summary.json # Complete §9 metrics, timing, identity oracle, and 4-way ablation results
    ├── kb_frozen_seed_state.json        # Cryptographic SHA-256 proof of frozen Seed KB before Holdout scoring
    ├── ablation_study_section9.csv      # 4-Way Ablation table (Full Engine vs. No CSP vs. No Sub-Atomic vs. 1D Lookup)
    ├── accounting_identity_oracle_checks.csv # 15 Independent statement & dimensional conservation identity checks
    ├── parity_and_oracle_verdicts.csv   # Per-goal verdicts for In-Memory vs. 3NF SQLite vs. Ground-Truth Oracle
    ├── unknown_resolution_queue.csv     # Tier U1 (Head-Induced), Tier U2 (CSP/Bayes Solved), Tier U3 (Chow Abstained)
    ├── xbrl_subatomic_warehouse_v3.sqlite # Materialized 11-table 3NF SQLite relational database
    └── xbrl_clean_engine_v3_audit.xlsx  # Formatted 9-tab Excel audit workbook
```
