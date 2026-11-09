# xbrl

Layer 3 engine package providing discovery, classification, and serialization of SEC XBRL taxonomy linkbases and instance data.

## Purpose

SEC EDGAR filings contain multiple distinct data artifacts across standard US-GAAP definitions and registrant-specific extension taxonomies. This package isolates the structural recognition of calculation (`_cal`), presentation (`_pre`), definition (`_def`), label (`_lab`), schema (`.xsd`), and instance documents directly from filing index entries.

By decomposing taxonomy linkbases into explicit typed relational structures and persisting them to compressed Parquet datasets, this engine establishes the grounded substrate needed for subsequent multi-hop financial derivation, accounting conservation checks, and semantic unification.

## Contracts

- **Deterministic Classification**: An inventory entry is matched to at most one linkbase type using strict document type, filename suffix, and description guards; ambiguous entries default to `None`.
- **Pure Transform Invariant**: Linkbase classification and extraction are pure transformations over parsed index pages and perform zero I/O or network requests.
- **Layer Boundary Enforcement**: All modules import downward only into `infra`, `domain`, and `foundation`; no imports from `pipelines`, `apps`, or `tools` are permitted.
- **Atomic Parquet Persistence**: Linkbase tables are written through the infra storage layer's Parquet writer, using its governed compression and row-group sizing without pipeline-local overrides.
- **Streaming XML Parsing**: Calculation, presentation, label, and instance XML documents are parsed in bounded memory with defensive entity handling.
- **Declared-Type Fact Typing**: Instance facts are typed by declared item type only (extension declarations over the archive table for the instance's own namespace vintages); a fact declared outside the closed numeric item-type family parses as a string, and undeclared concepts keep the float-sniff fallback.
- **Stitched Precedence**: A stitched series pools one selected filing set; lineage supersession applies first, then the latest reporter by filed date wins an identical period key (ties: amendment form, then accession), and every superseded value is retained naming its superseder, never dropped.
- **Exact Period Identity**: Stitched values are keyed by exact (start, end) or instant plus concept, unit, and dimensions; a quarter and a year-to-date span ending the same day are distinct values, never merged by year.
- **Derived-Quarter Honesty**: A derived discrete quarter exists only where no reported quarter serves the span, carries status DERIVED with both filed legs named as inputs, and a chain that cannot close exactly records a refusal with its reason — never an interpolated or partial difference.
- **Non-Additive Types Refuse Derivation**: Concepts declared with per-share, share-count, or rate item types are span averages, not accumulations; un-accumulation refuses them by declared type, never by concept name.
- **Calendar Breaks**: A transition period or a fiscal-year-end change splits the series; values on both sides serve, and no stitch or derivation crosses a break.

## Deliberate gaps

- **Dynamic Taxonomy Resolution**: Fetching remote external taxonomies (such as FASB or IFRS standard schemas) is deferred to the taxonomy archive: `tools/xbrl_discovery` builds per-vintage slices from the official releases, and this engine reads slices only.
- **Baked Seed Bundle Dei Facts**: The seed bundles' baked `facts.parquet` rows still carry mis-typed dei cover facts as numeric (their original strings are unrecoverable from the bundles), so the parse-time typing fix corrects them only on regeneration from live SEC instance documents, which has no offline source path.
- **Stitched Statements**: Only the stitched financials series is served; which filing's calculation and presentation arcs would govern a stitched statement is undecided, so no stitched statement surface exists.
- **Residual Non-Additive Monetary Concepts**: A small class of monetary concepts is keyed to an opening balance or a period-vesting measurement rather than accumulated over sub-periods (contract-liability revenue recognized; vested-in-period fair value); no taxonomy coordinate separates them from additive monetary flows, so their derived quarters serve as DERIVED with inputs named and this class is the recorded exception to the derivation narrowing.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
└── xbrl/  # Root directory for all published XBRL artifacts.
    └── xml/  # Directory housing cached linkbase XML source files.

{repo_root}/
└── edgar_sec/
    └── engine/
        └── xbrl/
            └── taxonomy/  # Directory housing accounting domain taxonomy files.
                ├── archive/  # Default directory of the per-vintage taxonomy archive slices.
                ├── atom_relations.json  # Default path to atom relations taxonomy file.
                ├── axis_families.json  # Default path to axis families taxonomy file.
                ├── commodity_graph.json  # Default path to commodity graph taxonomy file.
                ├── default_coordinates.json  # Default path to presumed-coordinate defaults taxonomy file.
                ├── geography_dag.json  # Default path to geography DAG taxonomy file.
                ├── grammatical_frames.json  # Default path to grammatical frames taxonomy file.
                ├── human_capital_graph.json  # Default path to human capital graph taxonomy file.
                ├── industries.json  # Default path to industry profiles taxonomy file.
                ├── instruments_dag.json  # Default path to financial instruments DAG file.
                ├── member_roles.json  # Default path to member roles taxonomy file.
                ├── prime_heads.json  # Default path to prime heads taxonomy file.
                ├── query_aliases.json  # Default path to query aliases taxonomy file.
                ├── relation_types.json  # Default path to relation types taxonomy file.
                ├── sibling_groups.json  # Default path to sibling-axis groups taxonomy file.
                ├── statement_roots.json  # Default path to statement root patterns taxonomy file.
                ├── subatomic_modifiers.json  # Default path to subatomic modifiers taxonomy file.
                ├── subspace_invariants.json  # Default path to multidimensional subspace routing invariants file.
                ├── token_lexicon.json  # Default path to token lexicon taxonomy file.
                ├── units.json  # Default path to units taxonomy file.
                ├── valence.json  # Default path to movement valence taxonomy file.
                └── valuation_rules.json  # Default path to valuation and fair value rules file.
```
<!-- AUTOGEN:PATHS:END -->
