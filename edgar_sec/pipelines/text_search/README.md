# text_search

Layer 4 pipeline that builds the materialized token/postings index over the
holdings this repo has actually acquired: the document-acquisition snapshot
tip and the facade DocumentCache, unified and deduplicated by payload
SHA-256. The index is derived state, published as Parquet relations under
the artifacts text_search dataset, and queried through the engine and
facade search surfaces.

## Contracts

- **Corpus boundary**: only acquired holdings are indexed; a filing never acquired is absent from the index, and search reports it as not-in-corpus rather than as a no-hit filing.
- **Out-of-core build**: chunk text streams in bounded batches, the already-indexed set is resolved by a DuckDB anti-join on payload SHA-256, and postings/document frequencies are aggregated in DuckDB — no dataset-scale Python structure is materialized.
- **Incrementality**: a rebuild over an unchanged corpus indexes zero new payloads; chunks for an already-indexed payload are reused verbatim.
- **Chunk unit**: the stored section or note where boundaries exist, else a bounded line window over the normalized text.
- **Identity**: `corpus_stats` records the source snapshot id the build read, so a stale index never answers as if current.

## Deliberate gaps

- **No SEC traffic**: the build reads only local stores; discovery of new filings belongs to the acquisition and metadata pipelines.
- **Cache document roles**: DocumentCache rows carry no primary/attachment role, so their chunks carry no role; attachment scope filtering applies to snapshot-sourced documents that carry a role.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `build` | build or incrementally extend the index | `[--artifacts]`, `[--index-root]`, `[--cache-db]` |
| `status` | report the stored index's corpus stats | `[--artifacts]`, `[--index-root]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
.venv/bin/python -m edgar_sec.pipelines.text_search.cli build
.venv/bin/python -m edgar_sec.pipelines.text_search.cli status
```
