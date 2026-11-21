# text_search

Layer 3 query engine over the materialized text index: BM25 ranking from
the index's stored postings and corpus statistics, and exact/regex
matching over chunk text in DuckDB. The two modes are different operations
with different result semantics and are kept separate in the surface.

## Contracts

- **Mode semantics**: BM25 hits carry a score; exact and regex hits carry none, only deterministic locations.
- **Coverage on every result**: each result states the index identity, its source snapshot id, and the accessions/documents/chunks searched; a caller-named target absent from the corpus is reported not-in-corpus, never folded into a plain no-match.
- **Excerpts are stored text**: an excerpt is a slice of the stored chunk text around the match, never generated or paraphrased.
- **Attachment scope is explicit**: a filing-level search means all documents unless the caller passes the primary-only scope.

## Deliberate gaps

- **No semantic or XPath modes**: ranking is BM25 over the stored vocabulary only.
- **Date filters need stored dates**: documents whose source carries no filing date are excluded by a date filter rather than guessed into range.
