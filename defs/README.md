# `defs/` — Shared Infrastructure

Domain-neutral, phase-independent contracts. Phases consume the public
surfaces exported here and never reimplement or bypass them.

```text
defs/
  sec_http.py           # SEC HTTP client: pacing, retries, caching, metrics, headers
  filing_identity.py    # canonical filing identity: accessions, archive URLs,
                        # occurrence IDs, document locator keys, date-derived years
  table_definitions.py  # shared table-conversion helpers for later content phases
  storage/              # logical datasets, chunk backends, manifests, atomic publication
  sql/                  # SQL AST/compiler/executor boundary
  runtime/              # paths, config bootstrap, partitions, progress, CLI, launcher registry
  viewer/               # read-only local dataset/artifact viewer (see viewer/README.md)
  tests/                # contract tests for the shared contracts (run: pytest defs/tests)
```

## Rules

- New shared behavior lands here only with a reusable contract plus contract
  tests in `defs/tests/`; phase code consumes public contracts, never
  backend-private helpers.
- `filing_identity` is the single owner of accession normalization (one
  canonical 18-digit value; the hyphenated form is derived on display),
  archive URL parsing/construction, occurrence identity
  `(source_cik, accession, document_path)`, and the pre-fetch document locator
  key `(accession, document_path)`. Phases must not rebuild these keys locally.
- `sec_http.default_headers` intentionally sets no `Host` header: the client
  serves both `data.sec.gov` and `www.sec.gov`, and the HTTP library derives
  Host from each URL.

## Tests

```bash
.venv/bin/pytest defs/tests
```

Run separately from phase suites; the `conftest.py` modules collide when
collected together.
