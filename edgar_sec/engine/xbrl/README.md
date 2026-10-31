# xbrl

Layer 3 engine package providing discovery, classification, and serialization of SEC XBRL taxonomy linkbases and instance data.

## Purpose

SEC EDGAR filings contain multiple distinct data artifacts across standard US-GAAP definitions and registrant-specific extension taxonomies. This package isolates the structural recognition of calculation (`_cal`), presentation (`_pre`), definition (`_def`), label (`_lab`), schema (`.xsd`), and instance documents directly from filing index entries.

By decomposing taxonomy linkbases into explicit typed relational structures and persisting them to compressed Parquet datasets, this engine establishes the grounded substrate needed for subsequent multi-hop financial derivation, accounting conservation checks, and semantic unification.

## Contracts

- **Deterministic Classification**: An inventory entry is matched to at most one linkbase type using strict document type, filename suffix, and description guards; ambiguous entries default to `None`.
- **Pure Transform Invariant**: `classify_linkbase_entry` and `extract_filing_linkbases` are pure transformations over parsed index pages and perform zero I/O or network requests.
- **Layer Boundary Enforcement**: All modules import downward only into `infra`, `domain`, and `foundation`; no imports from `pipelines`, `apps`, or `tools` are permitted.
- **Atomic Parquet Persistence**: Linkbase tables are written via `infra.storage.parquet.write_parquet_table` using `zstd` compression and governed row group sizes without pipeline-local overrides.
- **Streaming XML Parsing**: Calculation, presentation, label, and instance XML documents are parsed in bounded memory with defensive entity handling.
- **Declared-Type Fact Typing**: Instance facts are typed by declared item type only (extension declarations over the archive table for the instance's own namespace vintages); a fact declared outside the closed numeric item-type family parses as a string, and undeclared concepts keep the float-sniff fallback.

## Deliberate gaps

- **Dynamic Taxonomy Resolution**: Fetching remote external taxonomies (such as FASB or IFRS standard schemas) is deferred to the taxonomy cache manager.
- **Baked Seed Bundle Dei Facts**: The seed bundles' baked `facts.parquet` rows still carry mis-typed dei cover facts as numeric (323 of 511 numeric dei rows; their original strings are unrecoverable from the bundles), so the parse-time typing fix corrects them only on regeneration from live SEC instance documents, which has no offline source path.

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
                ├── atom_relations.json  # Default path to atom relations taxonomy file.
                ├── axis_families.json  # Default path to axis families taxonomy file.
                ├── geography_dag.json  # Default path to geography DAG taxonomy file.
                ├── grammatical_frames.json  # Default path to grammatical frames taxonomy file.
                ├── industries.json  # Default path to industry profiles taxonomy file.
                ├── instruments_dag.json  # Default path to financial instruments DAG file.
                ├── member_roles.json  # Default path to member roles taxonomy file.
                ├── prime_heads.json  # Default path to prime heads taxonomy file.
                ├── relation_types.json  # Default path to relation types taxonomy file.
                ├── subatomic_modifiers.json  # Default path to subatomic modifiers taxonomy file.
                ├── subspace_invariants.json  # Default path to multidimensional subspace routing invariants file.
                ├── token_lexicon.json  # Default path to token lexicon taxonomy file.
                ├── units.json  # Default path to units taxonomy file.
                └── valuation_rules.json  # Default path to valuation and fair value rules file.
```
<!-- AUTOGEN:PATHS:END -->
