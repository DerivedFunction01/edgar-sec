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

## Deliberate gaps

- **Linkbase XML Graph Parsing**: XML arc traversal and cycle detection are handled in downstream stages; this package owns file classification, network resolution, and tabular indexing.
- **Dynamic Taxonomy Resolution**: Fetching remote external taxonomies (such as FASB or IFRS standard schemas) is deferred to the taxonomy cache manager.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
└── xbrl/  # Root directory for all published XBRL artifacts.
    ├── linkbases/  # Directory housing linkbase Parquet inventories.
    │   ├── linkbases.parquet  # Default linkbase inventory Parquet file path.
    │   └── {cohort_id}_linkbases.parquet  # Return the Parquet path for a named cohort's linkbases.
    └── xml/  # Directory housing cached linkbase XML source files.

{repo_root}/
└── edgar_sec/
    └── engine/
        └── xbrl/
            └── taxonomy/  # Directory housing accounting domain taxonomy files.
                ├── prime_heads.json  # Default path to prime heads taxonomy file.
                ├── subatomic_modifiers.json  # Default path to subatomic modifiers taxonomy file.
                └── typed_relations.json  # Default path to typed relations taxonomy file.

{uploads_root}/
└── xbrl/
    └── seed_cohort.json  # Default path to the clean seed cohort input JSON.
```
<!-- AUTOGEN:PATHS:END -->
