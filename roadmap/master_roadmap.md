# SEC Form 10-K Master Extraction & Normalization Roadmap

## End-to-End Implementation Blueprint: From Raw Multi-Era Filings (1990–2026) to an Invariant, Flattened Research Database

---

### Executive Summary & System Mission

The objective of this system is to ingest **200,000 raw SEC Form 10-K annual filings (1990–2026)** across three incompatible formatting eras (unformatted ASCII, hybrid HTML, and modern Inline XBRL) and transform them into a fully normalized, machine-queryable research database (Apache Parquet, DuckDB, JSONL, and PostgreSQL).

The current Phase 2 boundary first derives a no-network, form-partitioned filing
catalog from finalized Phase 1 metadata. Cross-phase handoffs use immutable,
content-derived manifests with paths relative to `ARTIFACTS_ROOT`; the
DuckDB finalized-artifact facade is separate from the compiled SQL executor
reserved for later extraction and LLM-session storage. Portable bundles carry
finalized artifacts only, not chunks or caches.

> **Phase boundary note.** The repository currently implements Phase 01
> (submissions metadata) and Phase 02 (filing catalog and deterministic target
> planning). Phase 02 is metadata preparation only — it does **not** fetch, store,
> or parse raw SEC filing documents. Filing document acquisition (archive fetch,
> retries, caching, raw document storage, parsing, and content extraction) is a
> separate **Phase 2.5** boundary that consumes Phase 02 target plans. Phase 2.5
> is not yet implemented; the semantic extraction phases below (fundamentals,
> domain extraction, flattening) follow acquisition and build on the resolved
> filing documents. This note only records the boundary; it does not change the
> numbered extraction phases in the topology.

The system enforces **Temporal Invariance**: the schema does not break, deprecate, or mutate when accounting rules or SEC disclosure mandates change over time. Every financial, operational, spatial, and qualitative fact extracted from a filing is mapped into an orthogonal coordinate basis:

$$\text{Fact} = \langle \text{Entity}, \text{TemporalScope}, \text{SpatialScope}, \text{Metric}, \text{FacetDict}, \text{ActiveFlagArray}, \text{Provenance} \rangle$$

Researchers and quantitative analysts query this database directly via SQL, DuckDB, or Python **without ever opening a raw 10-K filing**, while retaining line-by-line bidirectional provenance to the source text.

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 END-TO-END SYSTEM PIPELINE TOPOLOGY                                    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                     │
 ┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
 │ PHASE 1: INGESTION, MULTI-ERA NORMALIZATION & EXPLICIT BOUNDARY SEGMENTATION                          │
 │ • Decode ASCII (1992–1997), HTML (1998–2011), and iXBRL (2012–2026) envelopes                         │
 │ • Run Table of Contents (TOC) Disambiguation Heuristic to prevent header false positives              │
 │ • Segment Tier-1 Explicit Items (1–16), Financial Statements, and Notes 1–20                          │
 └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                     │
 ┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
 │ PHASE 2: HIDDEN SECTION SEMANTIC DISCOVERY & POLICY/CRISIS CARTOGRAPHY                                │
 │ • Execute 20 Qualified Tier-3 Hidden Section Regex Engines with 500-char co-occurrence verification   │
 │ • Capture Multi-Scale Divergence (<100 employee micro-caps vs. megacaps: cash runway, burn rate)      │
 │ • Map multi-decade policy shocks (tariffs, CHIPS/IRA subsidies, export bans, SAB 121 crypto)          │
 └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                     │
 ┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
 │ PHASE 3: UNIVERSAL FUNDAMENTALS, TEMPORAL SCOPING & SPATIAL ONTOLOGY                                  │
 │ • Bind numbers to Measurement Tuples: $\text{Value} \times \text{Unit} \times \text{Scale} \times \text{Polarity}$     │
 │ • Distinguish Point-in-Time Instants (Stocks) from Duration-Scoped Intervals (Flows)                  │
 │ • Apply 7 Temporal Precision Tiers and universal `GeographicScope` (US/CA cross-border CBAs)           │
 └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                     │
 ┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
 │ PHASE 4: THE 16-MODULE DOMAIN EXTRACTION ENGINE & ACTIVE FLAG ARRAYS                                  │
 │ • Filter disclosures through the Analytic Utility Test (Computable, Partitionable, Discrete Signals)  │
 │ • Structure facts into: `metrics: []`, `facets: {}`, `active_flags: []`, and `provenance: {}`         │
 │ • Extract across 16 specialized modules (Financials, Debt, Derivatives, Labor, Real Estate, Risks)    │
 └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                     │
 ┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
 │ PHASE 5: FLATTENING, PARQUET DATA ENGINEERING, RECONCILIATION & ANALYTICS                             │
 │ • Populate partitioned Parquet tables (`fiscal_year`, `module_domain`) and relational DDL             │
 │ • Enforce 3-tier partitioned aggregations (`portfolio`, `category`, `atomic_positions`) to stop double-counting│
 │ • Execute automated accounting assertion harness ($\text{Assets} = \text{Liab} + \text{Eq}$, Lease discounting)  │
 └───────────────────────────────────────────────────────────────────────────────────────────────────────┘

```

---

# SECTION 1: THE DISCRETE AND HIDDEN SECTIONS TAXONOMY

Every text block and disclosure across 30+ years of filings is classified into one of four distinct structural tiers:

```
THE 4-TIER STRUCTURAL CLASSIFICATION HIERARCHY
├── TIER 1: EXPLICIT SEC REQUIRED ITEMS
│   └── Top-level numbered items mandated by Form 10-K instructions (Items 1–16 across Parts I–IV).
│
├── TIER 2: CANONICAL SUB-COMPONENTS
│   └── Standard sub-sections nested directly inside Explicit Items (e.g., MD&A Results of Operations; Notes 1–20).
│
├── TIER 3: QUALIFIED HIDDEN SECTIONS
│   └── High-value recurring disclosures lacking dedicated SEC Item numbers that migrate across sections over time.
│
└── TIER 4: EXTRA DETAIL (RAW NARRATIVE TEXT)
    └── Company-specific qualitative narrative, marketing copy, and boilerplate (referenced via Provenance, not mirrored in JSON).

```

---

### 1. Master Inventory of Explicit SEC Items (Tiers 1 & 2)

```
EXPLICIT SEC FORM 10-K HIERARCHY (PARTS I–IV)
├── PART I
│   ├── Item 1. Business [Reg S-K 101]
│   │   ├── 1.1 Corporate History & General Development (101(a))
│   │   ├── 1.2 Principal Products, Services & Operating Segments (101(b),(c))
│   │   ├── 1.3 Raw Materials, Sourcing & Single-Source Dependencies (101(c)(1)(iii))
│   │   ├── 1.4 Intellectual Property, Patents & Exclusivity (101(c)(1)(iv))
│   │   ├── 1.5 Seasonality & Working Capital Practices (101(c)(1)(v),(vi))
│   │   ├── 1.6 Customer Concentration (>10% Revenue) & Channels (101(c)(1)(vii))
│   │   ├── 1.7 Backlog & Long-Term Order Fulfillment (101(c)(1)(viii))
│   │   ├── 1.8 Government Contracts & Sector Regulation (101(c)(1)(ix))
│   │   ├── 1.9 Environmental Compliance Capital Expenditures (101(c)(1)(xii))
│   │   └── 1.10 Human Capital Resources (101(c)(2) as amended 2020; formerly "Employees")
│   ├── Item 1A. Risk Factors [Reg S-K 105] (Mandatory effective Dec 2005; 2-page summary required post-2020)
│   ├── Item 1B. Unresolved Staff Comments [Reg S-K 105] (Effective Dec 2005)
│   ├── Item 1C. Cybersecurity [Reg S-K 106] (Mandatory effective Dec 2023: Strategy, Risk Management & Governance)
│   ├── Item 2. Properties [Reg S-K 102] (Owned/Leased footprints, Fabs, Datacenters, Plants, Refineries)
│   ├── Item 3. Legal Proceedings [Reg S-K 103] (Environmental sanctions >$300k, Civil/Criminal litigation)
│   └── Item 4. Mine Safety Disclosures [Reg S-K 104] (Dodd-Frank §1503 / MSHA citations; effective July 2011)
├── PART II
│   ├── Item 5. Market for Common Equity, Related Stockholder Matters & Issuer Purchases [Reg S-K 201/703]
│   ├── Item 6. [Reserved] (Formerly "Selected Financial Data" [Reg S-K 301] - Eliminated Feb 2021)
│   ├── Item 7. Management's Discussion and Analysis (MD&A) [Reg S-K 303]
│   │   ├── 7.1 Executive Overview & Strategic Trends
│   │   ├── 7.2 Results of Operations (Revenue/Price/Volume variance, COGS, R&D, SG&A, Margins, Non-GAAP)
│   │   ├── 7.3 Liquidity and Capital Resources (Cash flows, debt facilities, available headroom, capex commitments)
│   │   ├── 7.4 Off-Balance Sheet Arrangements & Unconsolidated VIEs
│   │   └── 7.5 Critical Accounting Policies and Estimates
│   ├── Item 7A. Quantitative and Qualitative Disclosures About Market Risk [Reg S-K 305] (Effective 1997/1998)
│   │   ├── Model A: Tabular Contractual Cash Flows by Maturity
│   │   ├── Model B: Hypothetical Sensitivity Analysis (±100 bps yield curve, ±10% FX/Commodity shocks)
│   │   └── Model C: Stochastic Value-at-Risk (VaR) Monte Carlo / Historical Simulation Models
│   ├── Item 8. Financial Statements and Supplementary Data [Reg S-X & Reg S-K 302]
│   │   ├── 8.1 Consolidated Statements of Operations (Income Statement)
│   │   ├── 8.2 Consolidated Balance Sheets
│   │   ├── 8.3 Consolidated Statements of Cash Flows
│   │   ├── 8.4 Consolidated Statements of Stockholders' Equity & Comprehensive Income
│   │   └── 8.5 Standardized Notes to Financial Statements (Notes 1–20 ASC sequence)
│   ├── Item 9. Changes in and Disagreements with Accountants on Accounting & Financial Disclosure [Reg S-K 304]
│   ├── Item 9A. Controls and Procedures [Reg S-K 307 & 308] (SOX §302 DCP & SOX §404 ICFR auditor attestation)
│   ├── Item 9B. Other Information (Quarterly disclosures and Rule 10b5-1 trading plan adoptions)
│   └── Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections [HFCAA] (Effective 2021)
├── PART III (Frequently incorporated by reference from definitive Schedule 14A Proxy Statement)
│   ├── Item 10. Directors, Executive Officers and Corporate Governance [Reg S-K 401, 405, 406, 407]
│   ├── Item 11. Executive Compensation [Reg S-K 402 / Dodd-Frank PVP, CEO Pay Ratio, CIC Parachutes]
│   ├── Item 12. Security Ownership of Beneficial Owners and Management [Reg S-K 201(d) & 403]
│   ├── Item 13. Certain Relationships, Related Transactions, and Director Independence [Reg S-K 404 & 407(a)]
│   └── Item 14. Principal Accountant Fees and Services [Audit, Tax, and All Other Fees]
└── PART IV
    ├── Item 15. Exhibits and Financial Statement Schedules [Reg S-K 601: Ex 10 Contracts, Ex 21 Subsidiaries, Ex 97 Clawbacks]
    └── Item 16. Form 10-K Summary (Voluntary, Effective 2016)

```

---

### 2. The Catalog of 20 Qualified Tier-3 Hidden Sections

A disclosure qualifies as a Tier-3 Hidden Section tag if it exhibits **Cross-Firm Persistence**, **Structural Drift across decades**, and **High Analytical Query Value**.

```
MASTER CATALOG OF 20 QUALIFIED HIDDEN SECTION TAGS
┌──────────────────────────────────────────┬────────────────────────────────────────┬──────────────────────────────────────────┐
│ Tag Identifier                           │ Historical Location Drift Path         │ Heading Synonyms & Target Concepts       │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 1. `TAG_LABOR_UNION_COLLECTIVE_BARGAINING`│ Item 1 (90s) $\to$ Item 1A/Note 14 (00s)│ `"Collective Bargaining Agreements"`,    │
│                                          │ $\to$ Item 1 Human Capital (2020+)     │ `"Labor Relations"`, `"Union Density"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 2. `TAG_FORWARD_LOOKING_CAUTIONARY_NOTES`│ Signatures (pre-95) $\to$ Pre-MD&A (00s)│ `"Cautionary Statement"`, `"Safe Harbor"`│
│                                          │ $\to$ Pre-Item 1 / Cover Page (2020s)  │ `"Forward-Looking Information"`          │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 3. `TAG_ENVIRONMENTAL_REMEDIATION_CERCLA`│ Item 1/Item 3 (90s) $\to$ Note 14 (00s)│ `"Superfund Matters"`, `"CERCLA Sites"`, │
│                                          │ $\to$ Item 3 Threshold Tables (2020s)  │ `"Environmental Remediation Reserves"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 4. `TAG_DERIVATIVES_HEDGING_STRATEGY`    │ MD&A narrative (90s) $\to$ Item 7A/Note│ `"Derivative Instruments"`, `"Hedging"`, │
│                                          │ 5 (00s) $\to$ Level 1-3 Tables (2010s+)│ `"Economic Non-Designated Hedges"`       │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 5. `TAG_OFF_BALANCE_SHEET_VIE_SPV`       │ Note 16 (90s) $\to$ Mandated MD&A (00s)│ `"Off-Balance Sheet Arrangements"`,      │
│                                          │ $\to$ Note 16 / ASC 810 Tables (2020s) │ `"Variable Interest Entities"`, `"SPEs"` │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 6. `TAG_CUSTOMER_SUPPLIER_CONCENTRATION` │ Item 1 paragraph (90s) $\to$ Item 1A   │ `"Major Customers"`, `"Single Source"`,  │
│                                          │ (00s) $\to$ Note 2 Disaggregation (20s)│ `"Customer Concentration >10%"`          │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 7. `TAG_WARRANTY_PRODUCT_RECALL_RESERVE` │ Other Accrued Liab (90s) $\to$ Mandated│ `"Product Warranties"`, `"Recall Costs"`,│
│                                          │ FIN 45 Table (00s) $\to$ MD&A Recalls  │ `"Accrued Warranty Roll-Forward"`        │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 8. `TAG_PATENT_LOSS_OF_EXCLUSIVITY_CLIFF`│ Item 1 text (90s) $\to$ Item 1 Tables  │ `"Patent Expiration Schedule"`, `"LOE"`, │
│                                          │ (00s) $\to$ Item 1A / ANDA Torts (20s) │ `"Generic and Biosimilar Competition"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 9. `TAG_CLINICAL_TRIAL_PIPELINE_STATUS`  │ Item 1 R&D text (90s) $\to$ Pipeline   │ `"Product Pipeline"`, `"Phase 1/2/3"`,   │
│                                          │ Matrix (00s) $\to$ MD&A Spend by Drug  │ `"Regulatory Approval Catalyst Dates"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 10. `TAG_PRE_REVENUE_CASH_RUNWAY_BURN`   │ Note 1 Going Concern (90s) $\to$ MD&A  │ `"Cash Runway"`, `"Capital Sufficiency"`,│
│                                          │ Liquidity (10s) $\to$ ASU 2014-15 Note1│ `"Monthly Burn Rate"`, `"Going Concern"` │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 11. `TAG_GEOPOLITICAL_TARIFFS_TRADE_BAR` │ Item 1 Trade text (90s) $\to$ MD&A     │ `"Section 301 Tariffs"`, `"Customs"`,    │
│                                          │ Cost Inflation (2018) $\to$ Item 1A    │ `"Trade Protectionism and Retaliation"`  │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 12. `TAG_GOVERNMENT_INDUSTRIAL_SUBSIDIES`│ Note 1 Grant Offsets (00s) $\to$ Note  │ `"CHIPS Act Grants"`, `"IRA Credits"`,   │
│                                          │ 11 Taxes / MD&A Capex / Ex 10 (2022+)  │ `"Advanced Manufacturing Tax Credit 45X"`│
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 13. `TAG_EXPORT_CONTROLS_ENTITY_LIST`    │ Item 1 Regulation (90s) $\to$ Item 1A  │ `"BIS Entity List"`, `"EAR Controls"`,   │
│                                          │ China Bans (19) $\to$ Segments (2023+) │ `"Export Restrictions on Advanced AI"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 14. `TAG_CRYPTO_CUSTODY_SAB121`          │ Unreported off-balance sheet (pre-21)  │ `"Staff Accounting Bulletin No. 121"`,   │
│                                          │ $\to$ Balance Sheet Liability (2022+)  │ `"Safeguarding Crypto Asset Liability"`  │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 15. `TAG_ASSET_RETIREMENT_OBLIGATIONS`   │ Aggregated Depletion (90s) $\to$ FAS   │ `"Asset Retirement Obligations"`,        │
│                                          │ 143 Roll-Forward (00s) $\to$ Note 7    │ `"Decommissioning"`, `"Mine Reclamation"`│
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 16. `TAG_MASS_TORT_MDL_LITIGATION_SETTLE`│ Item 3 narrative (90s) $\to$ Note 14   │ `"Multi-District Litigation (MDL)"`,     │
│                                          │ Loss Ranges (00s) $\to$ Escrows (2020s)│ `"Settlement Escrow Fund Commitments"`   │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 17. `TAG_SUPPLY_CHAIN_RESHORING_UFLPA`   │ Sourcing boilerplate (pre-21) $\to$    │ `"Uyghur Forced Labor Prevention Act"`,  │
│                                          │ Item 1 Supply Audits / WROs (2022+)    │ `"Withhold Release Orders"`, `"Nearshore"`│
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 18. `TAG_INFRASTRUCTURE_COMMIT`            │ Unconditional purchase & capacity      │ `"GPU Cluster Supply , Multi-billion dollar cloud hosting Commitments"`,      │
│                                          │ commitments               │ `"Cloud Datacenter Purchase Obligations"`│
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 19. `TAG_DEBT_COVENANT_MOD_WAIVERS`      │ Debt Note text (90s) $\to$ MD&A Credit │ `"Financial Maintenance Covenants"`,     │
│                                          │ Facility Holiday / Amendment Tables    │ `"Covenant Holiday Relief"`, `"Waivers"` │
├──────────────────────────────────────────┼────────────────────────────────────────┼──────────────────────────────────────────┤
│ 20. `TAG_DOMESTIC_CABOTAGE_JONES_ACT`    │ Item 1 Regulation / Item 1A Risks      │ `"Merchant Marine Act of 1920"`,         │
│                                          │ (Persistent across domestic maritime)  │ `"Jones Act Compliance"`, `"Cabotage"`   │
└──────────────────────────────────────────┴────────────────────────────────────────┴──────────────────────────────────────────┘

```

---

# SECTION 2: THE UNIVERSAL QUANTITATIVE FUNDAMENTALS

Every extracted number and date must conform to the **Universal Ontological Fundamentals** to ensure mathematical and dimensional consistency across decades.

### 1. The 6-Parameter Measurement Tuple

Every financial, operational, or physical quantity is stored as a 6-parameter tuple:

$$\text{Measurement} = \langle \text{Magnitude}, \text{Unit}, \text{ScaleMultiplier}, \text{Polarity}, \text{ValuationAttribute}, \text{DurationScope} \rangle$$

* **`Magnitude` (`value`):** Raw extracted numeric scalar (e.g., `4500.0`, `12.5`, `-350.0`).
* **`Unit` (`unit_or_currency`):** Strict unit enum (`USD`, `EUR`, `shares`, `employees`, `square_feet`, `megawatts`, `percent`, `basis_points`, `days`).
* **`ScaleMultiplier` (`scale_multiplier`):** Magnitude exponent declared in filing header (`1` = Units, `1000` = Thousands, `1000000` = Millions, `1000000000` = Billions).
* **`Polarity` (`polarity`):** Standard debit/credit sign convention (`debit_normal_positive`, `credit_normal_positive`, `contra_negative`).
* **`ValuationAttribute` (`valuation_attribute`):** GAAP accounting measurement basis (`historical_cost`, `amortized_cost`, `fair_value_mark_to_market`, `undiscounted_contractual_face`).
* **`DurationScope` (`duration_scope`):** Distinguishes instantaneous **Stocks** ($t$, $\text{Duration} = 0$, e.g., cash balances, debt principal, headcount on Dec 31) from duration-scoped **Flows** ($[t_0, t_1]$, $\text{Duration} > 0$, e.g., annual revenue, capex, employee turnover count) and **Rate Intensities** ($\frac{\Delta M}{\Delta t}$, e.g., monthly cash burn rate, refining throughput barrels/day).

---

### 2. The 7 Temporal Precision Tiers

To handle filings that range from exact calendar dates to floating retail cycles and prospective catalyst targets:

```
TEMPORAL PRECISION TIERS
┌──────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────┐
│ Precision Tier                               │ Technical Format & Example                                             │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 1: Exact Calendar Day                   │ `2024-12-31` (ISO 8601 Date)                                           │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 2: Calendar Month                       │ `2023-11` (YYYY-MM)                                                    │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 3: Fiscal Quarter / Year                │ `FY2024`, `Q3-2023` (Bound to explicit fiscal period dates)            │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 4: Retail 52-53 Week Floating Period    │ `52_week_period_ended_2024-01-27` (Last Saturday in January convention)│
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 5: Seasonal / Operational Window        │ `holiday_retail_surge_q4`, `summer_cruise_season`, `spring_planting`   │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 6: Rolling Lookback Horizon             │ `trailing_twelve_months_ttm`, `last_30_trading_days`, `next_12_months` │
├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Tier 7: Event-Contingent Target              │ `upon_fda_pdufa_approval`, `at_merger_closing`, `upon_debt_default`    │
└──────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────┘

```

---

### 3. Universal Spatial Hierarchy (`GeographicScope`)

Resolves geographic boundary overlaps (US vs. Canada cross-border intertwined unions; North America under USMCA vs. Latin America under retail reporting):

```json
{
  "jurisdiction_scope": "global_worldwide | domestic_united_states | international_ex_united_states | cross_border_us_canada | regional_multicountry | single_country | subnational_state_province",
  "macro_region": "north_america | latin_america_and_caribbean | europe | asia_pacific_apac | greater_china | emea_combined | americas_combined",
  "country_iso_alpha2": "US",
  "country_iso_alpha2_list": ["US", "CA"],
  "us_state_or_territory": "PA",
  "state_province_or_prefecture": "Pennsylvania",
  "city_or_metropolitan_area": "Philadelphia",
  "regional_semantic_definition": "North America automotive segment includes US and Canada; Mexico is allocated to Latin America."
}

```

---

# SECTION 3: THE 16-MODULE DOMAIN EXTRACTION ENGINE

### The Analytic Utility Test & The 4-Element Structured Fact Model

To prevent the JSON from degenerating into a bloated text dump of unstructured narrative, every extracted record must satisfy the **Analytic Utility Test** (Computable arithmetic, Deterministic SQL partitioning, or Discrete screening signal) and collapse into four structured primitives:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                               THE 4-ELEMENT STRUCTURED FACT MODEL                                │
├────────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ 1. `metrics: []`               │ The Quantitative Ledger (Strictly numerical floats + unit enums)│
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 2. `facets: {}`                │ Categorical Classifications (Strict enum keys & values)         │
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 3. `active_flags: []`          │ Discrete Signal Array (Enums that only appear when TRUE)        │
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 4. `provenance: {}`            │ Traceability Coordinates (Container, row label, char offsets)   │
└────────────────────────────────┴─────────────────────────────────────────────────────────────────┘

```

---

### Detailed Domain Extraction Specifications (Modules 01–16)

```
THE COMPLETE 16-MODULE DOMAIN EXTRACTION INVENTORY
├── PILLAR I: FINANCIAL STATEMENTS & EARNINGS QUALITY
│   ├── MODULE 01: Primary Statements Ledger (Item 8)
│   │   ├── Metrics: Gross/Net Revenue, COGS, R&D, SG&A, Operating Income (EBIT), Net Income, Basic/Diluted EPS,
│   │   │            Cash & Equivalents, Accounts Receivable, Inventory, Total Assets, Total Liabilities, Retained Earnings
│   │   ├── Facets: Accounting Standard (US-GAAP), Inventory Costing Method (FIFO/LIFO), Statement Type
│   │   └── Active Flags: `has_restatement_prior_period_error`, `has_auditor_going_concern_paragraph`
│   │
│   ├── MODULE 02: Revenue from Contracts, RPO Backlog & Customers (ASC 606 / Note 2 / Item 1)
│   │   ├── Metrics: Disaggregated Revenue by Stream, Contract Assets, Contract Liabilities (Deferred Revenue),
│   │   │            Remaining Performance Obligations (RPO) Backlog, Customer Concentration Share %
│   │   ├── Facets: Recognition Timing (Point-in-Time vs. Over-Time), Customer Name (DoD, Apple, Walmart)
│   │   └── Active Flags: `has_subscription_recurring_revenue`, `has_customer_concentration_gt_10pct`
│   │
│   ├── MODULE 03: Income Taxes & Tax Contingencies (ASC 740 / Note 11)
│   │   ├── Metrics: Effective Tax Rate %, Current/Deferred Tax Expense, Gross DTA, Valuation Allowance Reserve,
│   │   │            Unrecognized Tax Benefits (UTB / FIN 48) Tax Contingency Reserve
│   │   ├── Facets: Tax Reconciling Driver (R&D credits, Foreign rate differential, GILTI, BEAT, CAMT 15%)
│   │   └── Active Flags: `has_full_dta_valuation_allowance`, `is_subject_to_camt_15pct_minimum_tax`
│   │
│   ├── MODULE 04: Business Combinations, Goodwill & Intangibles (ASC 805 / ASC 350 / Notes 3 & 8)
│   │   ├── Metrics: M&A Purchase Price, Cash/Stock Consideration, Contingent Earnouts, Goodwill by Unit,
│   │   │            Impairment Charges, Future 5-Year Finite-Lived Intangible Amortization Ladder (Y1–Y5)
│   │   ├── Facets: Acquired Entity Name, Intangible Asset Class (Patents, Customer Relationships, Tech)
│   │   └── Active Flags: `has_contingent_consideration_earnout`, `has_goodwill_impairment_charge`
│   │
│   └── MODULE 05: Segment Operations & Multi-Jurisdiction Geography (ASC 280 / Note 15 / Item 1)
│       ├── Metrics: Segment Revenue, Gross Profit, Operating Profit (EBIT), Adjusted EBITDA, Segment Assets,
│       │            Segment Capex, Geographic Revenue by Country, Geographic Long-Lived Assets by Country
│       ├── Facets: Operating Segment Name, Country Code (US, China, Europe, Japan)
│       └── Active Flags: `has_unallocated_corporate_expense_carveout`, `has_intersegment_revenue_eliminations`
│
├── PILLAR II: LIABILITIES, CAPITAL STRUCTURE & FINANCIAL ASSETS
│   ├── MODULE 06: Debt Capital, Credit Facilities & Financing Contracts (ASC 470 / Note 9 / Item 7)
│   │   ├── Metrics: Principal Debt Outstanding, Carrying Value, Available Revolver Headroom, Coupon Rate %,
│   │   │            SOFR Spread bps, 5-Year Contractual Maturity Ladder (Y1–Y5 + Thereafter), Max Leverage Ratio
│   │   ├── Facets: Facility Type (Revolver, Term Loan A/B, Senior Notes, Convertibles, Supplier Finance), Seniority
│   │   └── Active Flags: `has_convertible_capped_call`, `has_supplier_finance_reverse_factoring`, `has_covenant_holiday`
│   │
│   ├── MODULE 07: Derivatives, Options, Warrants & Item 7A Market Risk (ASC 815 / ASC 820 / Note 5 / 7A)
│   │   ├── Metrics: Notional Amount, Gross Asset Fair Value, Gross Liability Fair Value, Net Carrying Value,
│   │   │            Master Netting Offset, Strike Price, Greeks (Δ,Γ,ν,Θ), VaR (99% 1-Day), Sensitivity Shock Impact
│   │   ├── Facets: Risk Class (IR, FX, Commodity, Crypto), Instrument Type (Swap, Collar, Warrant), FV Level (1,2,3)
│   │   └── Active Flags: `has_isda_master_netting_offset`, `has_liability_spac_warrant`, `has_var_model_disclosure`
│   │
│   ├── MODULE 08: Asset Retirement Obligations (AROs) & Restructuring (ASC 410 / ASC 420 / Note 7)
│   │   ├── Metrics: ARO Beginning Balance, Additions, Revisions, Accretion Expense, Settlement Payments, ARO Ending,
│   │   │            Restructuring Reserve Beginning, Severance Charges, Facility Exit Costs, Restructuring Ending
│   │   ├── Facets: Obligation Type (Offshore Decommissioning, Well Plugging, Mine Reclamation, Severance)
│   │   └── Active Flags: `has_environmental_mine_reclamation_bonding`, `has_multi_year_restructuring_plan`
│   │
│   └── MODULE 09: Stock-Based Compensation & Pension/OPEB Obligations (ASC 718 / ASC 715 / Notes 12 & 13)
│       ├── Metrics: Stock Comp Expense, Black-Scholes Volatility %, Unrecognized Stock Comp $, PBO/ABO Obligations,
│       │            Plan Assets Fair Value, Pension Net Funded Status on Balance Sheet, Pension Discount Rate %
│       ├── Facets: Award Plan Type (Options, RSUs, PSUs, ESPP), Asset Class Allocation (Equities, Fixed Income)
│       └── Active Flags: `has_underfunded_pension_liability`, `has_multi_employer_pension_withdrawal_risk`
│
├── PILLAR III: OPERATIONAL INFRASTRUCTURE, ASSETS & WORKFORCE
│   ├── MODULE 10: Labor Unions, Bi-National CBAs & S-K 101 Human Capital (Item 1 / 1A)
│   │   ├── Metrics: Total Headcount, Domestic vs. International Headcount, Union-Covered Headcount, Union Density %,
│   │   │            Strike Duration Days, Strike Financial Impact $, Total Turnover %, TRIR / DART Safety Incident Rates
│   │   ├── Facets: Union Name (UAW, Teamsters, USW, Unifor), Local Chapter, CBA Expiry Date, Proportional Scope Basis
│   │   └── Active Flags: `has_bi_national_intertwined_union`, `has_active_strike_in_period`, `has_works_councils`
│   │
│   ├── MODULE 11: Properties, Industrial Real Estate & ASC 842 Leases (Item 2 / Note 10)
│   │   ├── Metrics: Owned Sq Ft, Leased Sq Ft, Datacenter Megawatts, Capacity Utilization %, Operating Lease ROU Asset,
│   │   │            Operating Lease Liability, Lease WADR Discount Rate %, 5-Year Undiscounted Lease Ladder (Y1–Y5)
│   │   ├── Facets: Facility Type (Cleanroom Fab, Datacenter, Plant, Distribution Hub, Store), Ownership Title (Fee/Lease)
│   │   └── Active Flags: `has_cleanroom_fab_infrastructure`, `has_operating_lease_liabilities_under_asc842`
│   │
│   └── MODULE 12: Inventories, Raw Materials, PP&E & Capex (ASC 330 / ASC 360 / Notes 6 & 7 / Item 1)
│       ├── Metrics: Raw Materials $, WIP $, Finished Goods $, LIFO Reserve, Lower-of-Cost Write-Downs,
│       │            PP&E Gross, Accumulated Depreciation, PP&E Net, Annual Capital Expenditures (Capex)
│       ├── Facets: Inventory Costing (FIFO/LIFO/Average), Critical Raw Material Name (Lithium, Wafers, Cobalt)
│       └── Active Flags: `has_lifo_inventory_reserve`, `has_sole_source_supplier_dependency`
│
└── PILLAR IV: RISKS, GOVERNANCE & POLICY SHOCKS
    ├── MODULE 13: Item 1A Risk Factors, Vulnerabilities & Macro Shocks (Item 1A / Item 7)
    │   ├── Metrics: Quantified Risk Exposure Estimate $, Revenue at Risk %, Patent LOE Expiration Year
    │   ├── Facets: Risk Domain (Geopolitical, Supply Chain, Cyber, Financial, Climate), Stated Mitigation Type
    │   └── Active Flags: `is_emerging_new_risk`, `is_acute_crisis_shock`, `has_single_point_of_failure_tsmc`
    │
    ├── MODULE 14: Legal Proceedings, Mass Tort MDLs & ASC 450 Contingencies (Item 3 / Note 14)
    │   ├── Metrics: Accrued Balance Sheet Legal Reserve, Accrued Superfund Reserve, Plaintiff Claimed Damages,
    │   │            Loss Range Minimum, Loss Range Maximum, Settlement Escrow Funded $, Active Claimants Count
    │   ├── Facets: Matter Type (Mass Tort, Patent, Antitrust, Superfund), MDL Docket #, Presiding Court, ASC 450 Tier
    │   └── Active Flags: `is_consolidated_in_federal_mdl`, `has_active_class_action`, `has_subsidiary_bankruptcy_shield`
    │
    ├── MODULE 15: Corporate Governance, Executive Pay & Dual-Class Power (Part III Items 10–14 / Proxy)
    │   ├── Metrics: Board Size, Independent Director %, Female Director %, NEO Total Comp, CEO Pay Ratio Multiple,
    │   │            Dodd-Frank Compensation Actually Paid (CAP), Insider Voting Power % vs. Economic Ownership %
    │   ├── Facets: Board Leadership (Combined CEO/Chair vs. Independent Chair), Dual-Class Voting Ratio (10:1)
    │   └── Active Flags: `has_dual_class_super_voting_shares`, `is_controlled_company`, `has_clawback_policy_ex97`
    │
    └── MODULE 16: Auditor Quality, PCAOB CAMs, Exhibit Architecture & Policy Shocks (Items 8, 9A, 15 / SAB 121 / IRA)
        ├── Metrics: Auditor Tenure Years, Total Audit Fees $, Material Weaknesses Count, Section 301 Tariff Duties Paid,
        │            CHIPS Act Grant Disbursements $, IRA Section 45X Tax Credits Monetized $, SAB 121 Crypto Asset Parity $
        ├── Facets: Auditor Firm Name (PwC, EY, Deloitte, KPMG), Financial Opinion Type, PCAOB CAM Topic Classifications
        └── Active Flags: `has_pcaob_critical_audit_matters`, `has_icfr_material_weakness`, `has_bis_entity_list_ban`

```

---

# SECTION 4: DATA ENGINEERING, PARQUET STORAGE & RECONCILIATION

### 1. Partitioned Columnar Storage Layout (Apache Parquet)

To prevent SQL double-counting and enable sub-second queries across 200,000 filings:

* Data is stored in **partitioned Apache Parquet files** structured by `fiscal_year` and `module_domain`:
`storage/parquet/fiscal_year=2024/module_domain=debt/data.parquet`
* The database schema strictly partitions reported top-level summary totals from granular atomic leaf facts:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              PARTITIONED RELATIONAL & PARQUET SCHEMA                                   │
├────────────────────────────────┬───────────────────────────────────────────────────────────────────────┤
│ `sec_filing_documents`         │ Master metadata: `cik`, `company_name`, `fiscal_year`, `period_end`   │
├────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ `sec_reported_aggregates`      │ Top-level portfolio totals & subtotals officially reported by mgmt    │
│                                │ (Excluded from leaf sums to mathematically prevent double-counting)   │
├────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ `sec_atomic_records`           │ Discrete leaf-level contracts, facilities, plants, unions, lawsuits   │
│                                │ Contains: `facets` (JSONB), `active_flags` (TEXT[]), `provenance`     │
├────────────────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ `sec_atomic_metrics`           │ Granular typed numbers: `metric_type`, `value`, `unit`, `scale` │
│                                │ (Safe for direct SQL `SUM()`, `AVG()`, `MIN()`, `MAX()` aggregations) │
└────────────────────────────────┴───────────────────────────────────────────────────────────────────────┘

```

## Operator Configuration Boundary (implemented)

All application settings are declared once as typed specs with logical dotted
paths in the shared settings registry (`defs/runtime/settings/`) plus one
`settings.py` per phase, registered through the `phases/settings.py` barrel.
Environment names are generated from the logical paths (e.g.
`filing_extraction.source_batch_size` -> `FILING_EXTRACTION_SOURCE_BATCH_SIZE`),
so new phases add a spec module — never environment exports or ad-hoc
`os.environ` reads. Direct environment access is confined to the generic
`defs/runtime/env.py` boundary and the settings registry; an automated
environment-access scanner in the `check.py` validation gate enforces this on
every modified file.

Resolution precedence: explicit CLI override → direct environment/canonical
`.env` (when the spec allows `env`) → persisted config (when the spec allows
`config`) → default. Machine-derived values (DuckDB threads, memory budget,
spill directory) are never persisted automatically and stay machine-local;
persisted phase settings remain part of the owning phase's reproducibility
contract. Secrets (SEC contact identity, provider credentials) resolve
through the environment or git-ignored `.env` only, and are excluded from
flattened reports and generated dotenv output. `python run.py settings
generate-dotenv` renders a documented `.env` template from the same specs the
runtime resolves, so operator documentation can never drift from behavior.
