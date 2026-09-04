# `defs/taxonomy/` — Financial Table Taxonomy & Empirical Probe Engine

Domain-grounded classification, 2D geometric constraints, vocabulary census, and empirical table probing across SEC filings (10-K, 10-Q, 20-F, 40-F).

```text
defs/taxonomy/
  tables/                  # Table classification engine and base contracts
    classifier.py          # Multi-zone BoW classifier with zone routing (headers vs row-stubs vs full)
    families.py            # Canonical registry of all active TableFamilySpecs
    specs.py               # TableFamilySpec, EvidenceTier, ShapeConstraint, RepairPolicy
    shapes.py              # 2D geometric shape constraints (min/max cols, rows, numeric density)
  components/              # Domain-specific table family specifications
    financials/            # Core financial statements (Balance Sheet, Income, Cash Flow, Equity)
      balance_sheet.py
      income_statement.py
      cash_flow.py
      equity.py
    schedules/             # Disclosures & Footnote Schedules
      debt_maturity.py     # Contractual debt maturities
      deferred_tax.py      # Deferred tax assets & liabilities rollforward
      eps_reconciliation.py# Basic & diluted EPS reconciliations
      fair_value.py        # ASC 820 Fair value measurement & hierarchy (Levels 1-3)
      lease_maturity.py    # Undiscounted operating/finance lease commitments
      pension.py           # Defined benefit pension & postretirement obligations
      shares_purchased.py  # Item 703 monthly share repurchases
      stock_comp.py        # Stock option / RSU / PSU activity rollforward
      tax_reconciliation.py# Statutory to effective tax rate reconciliation
  probe/                   # Empirical corpus probe, vocabulary census, and spec optimizer
    cache.py               # Parallel multi-worker table extraction & 2D grid healing into Parquet
    census.py              # Cross-firm vocabulary census, n-gram mining (unigram, bigram, trigram)
    audit.py               # Cross-family collision matrix, sole-match evaluation, subsumption analysis
    optimizer.py           # Auto-classification spec synthesis, keyword density curves, union detection
    inspector.py           # Diagnostic 2D grid viewer and ASCII template rendering preview
    cli.py                 # Canonical CLI surface for benchmarking, census, discovery, and optimization
```

---

## Core Architecture

1. **Form Neutrality & Intrinsic Table Geometry**:
   - The classifier does not hardcode SEC Item numbers (e.g. "Item 8").
   - Classifications evaluate intrinsic table features:
     - **Header Zone**: Multi-level column headers (e.g. *Level 1, Level 2, Level 3, Total* or *Operating Leases, Finance Leases*).
     - **Row Stub Zone (Col 0)**: Line-item labels (e.g. *Common Stock, Additional Paid-In Capital, Retained Earnings*).
     - **Full Normalized Grid**: Distinctive terminology across all cells.
     - **Shape Constraints**: Validated column counts, row bounds, and numeric density thresholds.

2. **Strict Layering & Non-Circular Imports**:
   - `defs.taxonomy` imports from `defs.tables` and `defs.text.bow`.
   - `defs.tables` (and its rendering templates) **never** import from `defs.taxonomy`.

3. **Collision-Free Orthogonality**:
   - Table families enforce single unigram exclusion rules (veto terms) and priority tiers.
   - Evaluated on over 140,000 empirical tables across 1,000 filings with **0 cross-family collisions (100% orthogonal)**.

---

## Probe CLI Command Surface

The probe CLI operates over atomic Parquet caches produced from real pipeline database blobs:

```bash
# 1. Build or expand the probe cache across N table-bearing filings (parallel workers + tqdm)
.venv/bin/python -m defs.taxonomy.probe.cli --build-cache --limit 1000

# 2. Benchmark all active table families across the entire corpus (auto-discovers cache)
.venv/bin/python -m defs.taxonomy.probe.cli --benchmark

# 3. Cross-firm vocabulary census (unigrams, bigrams, trigrams in row stubs or headers)
.venv/bin/python -m defs.taxonomy.probe.cli --census --ngram 3 --zone row_labels

# 4. Discover distinctive n-grams for candidate tables matching seed keywords
.venv/bin/python -m defs.taxonomy.probe.cli --discover --seed "derivative" "hedging" --ngram 2

# 5. Group unclassified tables into candidate clusters
.venv/bin/python -m defs.taxonomy.probe.cli --cluster-unclassified

# 6. Auto-synthesize non-colliding TableFamilySpec JSON & keyword density curves
.venv/bin/python -m defs.taxonomy.probe.cli --synthesize-spec "derivative instruments"

# 7. Detect multi-part table schedule unions (adjacent tables sharing footnote headings)
.venv/bin/python -m defs.taxonomy.probe.cli --detect-unions

# 8. Test dynamic rules from an external JSON or Python file
.venv/bin/python -m defs.taxonomy.probe.cli --benchmark --rules candidate_rules.json

# 9. Inspect 2D healed grid and ASCII template preview for a specific table index
.venv/bin/python -m defs.taxonomy.probe.cli --inspect 42
```

---

## Adding a New Table Family

1. Create a new specification file under `defs/taxonomy/components/financials/` or `defs/taxonomy/components/schedules/`.
2. Define the `TableFamilySpec` with:
   - `ShapeConstraint` (minimum columns, rows, numeric density).
   - `LexicalEvidencePack` (required phrases, supporting n-grams, unigram exclusions).
   - `RepairPolicy` (`NO_REPAIR`, `PRESENTATION_ONLY`, `SAFE_GRID_REPAIR`, or `FAMILY_TEMPLATE`).
   - `priority: int` (e.g. 100 for primary financial statements, 80 for fair value hierarchies, 50 for footnote disclosures).
3. Register the specification in `defs/taxonomy/tables/families.py`.
4. Validate with contract tests (`pytest defs/tests/test_table_taxonomy_contracts.py`) and probe benchmarks (`--benchmark`).

---

## Multi-Classification & Semantic Facet Tagging

Tables frequently contain overlapping disclosures (e.g. a Fair Value hierarchy table disclosing derivative instrument levels).

`classify_table` performs multi-candidate evaluation:
- **Primary `family`**: The winning candidate sorted by `(priority, confidence, score)` descending. Determines the table's physical `RepairPolicy` and grid template.
- **Secondary `tags` (`tuple[str, ...]`)**: Additional matching family names tagged as semantic facets without risking conflicting physical mutations.
- **`all_matches` (`tuple[FamilyMatch, ...]`)**: Full list of candidate matches, each preserving individual `confidence`, `score`, `priority`, and multi-zone `VocabularyEvidence`.

