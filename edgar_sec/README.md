# `edgar_sec`

This file maps the package layers and their ownership boundaries. Each package
README documents its own contracts and public surface.

## Layers

Imports flow **downward only**. A layer may import from the layers beneath it
and never from the layers above. This is not a convention — the
`layer-boundary` policy scanner parses every import in the package and fails the
gate on a violation.

```text
Layer 5  apps/          read-only, operator-facing consumers of published artifacts
           │            may read every layer below; nothing may import it
Layer 4  pipelines/    orchestration: CLI, operator, planner, worker, merger
           │            the only layer permitted to sequence the others
Layer 3  engine/       filing transformations and feature construction
           │
Layer 2  infra/        I/O adapters: SEC HTTP, broker, DuckDB, Parquet, CAS
           │
Layer 1  domain/       data contracts and vocabularies. No IO.
           │
Layer 0  foundation/   runtime, memory, hashing, compression, settings, scanners
                         zero internal dependencies on upper layers
```

| Layer | Package | Owns |
| :--- | :--- | :--- |
| 0 | [`foundation/`](foundation/README.md) | cgroup-aware resources, memory reclamation, hashing, canonical JSON, the zstd frame codec, the settings registry, the policy scanners |
| 0 | [`foundation/runtime/`](foundation/runtime/README.md) | paths, env resolution, progress, partitions, interactive prompts, memory |
| 0 | [`foundation/runtime/settings/`](foundation/runtime/settings/README.md) | the single typed settings registry; env names derive from logical dotted paths |
| 0 | [`foundation/scanners/`](foundation/scanners/README.md) | policy scanners and `ALL_SCANNERS` |
| 0 | [`foundation/text/`](foundation/text/README.md) | shared pattern vocabulary: dates, tokens, grammar, unicode, compounds, the Aho-Corasick automaton |
| 0 | [`foundation/regex/`](foundation/regex/README.md) | the regex builder DSL that guarantees longest-first alternation ordering |
| 1 | [`domain/`](domain/README.md) | layer root; contracts only |
| 1 | [`domain/identity.py`](domain/README.md) | `Cik`, `AccessionNumber` |
| 1 | [`domain/document/`](domain/document/README.md) | document and occurrence record contracts, acquisition results |
| 1 | [`domain/document_inventory/`](domain/document_inventory/README.md) | shared inventory records and durable entry schema |
| 1 | [`domain/forms/`](domain/forms/README.md) | cover/form vocabulary: checkmarks, family aliases, field schemas, body evidence |
| 1 | [`domain/taxonomy/`](domain/taxonomy/README.md) | jurisdictions, legal forms, family vocabulary |
| 1 | [`domain/submissions/`](domain/submissions/README.md) | submission schemas |
| 1 | [`domain/filing_catalog/`](domain/filing_catalog/README.md) | catalog schemas and filters |
| 2 | [`infra/`](infra/README.md) | layer root; I/O adapters |
| 2 | [`infra/sec_http/`](infra/sec_http/README.md) | the shared SEC client: pacing, retries, cache, metrics, failure ledger |
| 2 | [`infra/broker/`](infra/broker/README.md) | Unix-socket broker so an arbitrary worker pool shares one rate limit |
| 2 | [`infra/storage/`](infra/storage/README.md) | atomic IO, DuckDB engine, Parquet, snapshot manifests, the document part tree and payload store |
| 3 | [`engine/`](engine/README.md) | layer root; filing transformations and selection feature construction |
| 3 | [`engine/document/`](engine/document/README.md) | input preparation, SGML unpacking, HTML cleaning/projection, page markers, signatures, whitespace |
| 3 | [`engine/tables/`](engine/tables/README.md) | table masking, HTML→ASCII rendering with geometry, false-table rejection |
| 3 | [`engine/forms/`](engine/forms/README.md) | stage order, result record, cover decision chain, family SPI and evaluators |
| 3 | [`engine/reflow/`](engine/reflow/README.md) | conservative ASCII reflow: features, calibrated thresholds, rule cascades |
| 3 | [`engine/forms/plugins/`](engine/forms/plugins/README.md) | the `FormPlugin` SPI and registry |
| 3 | [`engine/selection/`](engine/selection/README.md) | Phase 2 target-plan selection: features, policy, selector, source |
| 3 | [`engine/company_family/`](engine/company_family/README.md) | name normalization and universe-scale family assignment |
| 3 | [`engine/submissions/`](engine/submissions/README.md) | submission unrolling, profiling, building |
| 3 | [`engine/index_pages/`](engine/index_pages/README.md) | pure SEC filing index-page HTML parser |
| 5 | [`apps/`](apps/README.md) | layer root; read-only operator-facing consumers of published artifacts |
| 5 | [`apps/viewer/`](apps/viewer/README.md) | the dataset viewer: a lazy filesystem explorer, manifest-driven virtual datasets, paged DuckDB reads, a guarded read-only SQL console |
| 4 | [`pipelines/`](pipelines/README.md) | layer root; orchestration |
| 4 | [`pipelines/document_inventory/`](pipelines/document_inventory/README.md) | cohort projection, index-page capture/replay, broker-backed worker coordination |
| 4 | [`pipelines/metadata_sync/`](pipelines/metadata_sync/README.md) | Submissions metadata ingest, chunked and resumable |
| 4 | [`pipelines/filing_catalog/`](pipelines/filing_catalog/README.md) | Zero-network catalog materialization and target planning |
| 4 | [`pipelines/document_storage/`](pipelines/document_storage/README.md) | Fetch, normalize, delegate, checkpoint, merge, consolidate |

## Shared engineering contract

Layer boundaries, import/export rules, resource limits, settings, and the mirrored
test-tree contract are defined normatively in [`AGENTS.md`](../AGENTS.md).

## Deliberate gaps

This root package is an architecture map rather than an execution layer; its
capability gaps belong to the owning layer or package README.
