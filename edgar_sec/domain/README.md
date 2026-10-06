# `edgar_sec/domain/` — Layer 1: value objects, vocabulary, and schema contracts

Layer 1 holds the facts every other layer agrees on and none of them may
specialise: identity primitives, EDGAR URL shapes, statutory vocabulary, Arrow
schemas, and the frozen dataclasses that cross layer boundaries. It performs no
IO, opens no files, and reaches no network.

## Purpose

`edgar_sec/domain/` is the only place a value may be *defined* rather than
*produced*. A CIK, a form family, a cover-page label, a dataset column list: all
of it is declared here once, and `infra`, `engine`, and `pipelines` import
downward. What this layer is not: it does not fetch, persist, parse, classify, or
schedule. A rule that needs a request, a file handle, a thread, or a stage
counter belongs above this layer.

## Layout

Layer 1 may import from `foundation` only; the `layer-boundary` scanner enforces
the downward-only rule. Domain schemas declare PyArrow types without depending on
the storage layer.

| Module / package | Responsibility |
| :--- | :--- |
| `identity.py` | CIK and accession identity primitives |
| `sec_urls.py` | EDGAR URL construction and archive URL parsing |
| `document/` | Document locator, occurrence, and acquisition records, flat block stream, acquisition route |
| `document_inventory/` | Shared inventory records and durable entry schema |
| `filing_catalog/` | Catalog schemas, version identifiers, planning filter vocabulary |
| `forms/` | Form/cover vocabulary, schemas, family aliases, body evidence, evaluator decisions |
| `submissions/` | Submission dataset schema and record models |
| `taxonomy/` | Jurisdiction, legal-form, and company-name vocabulary; statement, schedule, and table specifications |

Consumers import public symbols from their leaf modules; package `__init__.py`
files do not re-export child symbols.

## Contracts

**Guarantees this layer makes.**

- A value is defined once. Identity primitives, the form-family alias table, the
  Arrow column lists, and the filter vocabularies each have a single owning
  module; consumers read them rather than restating them.
- Vocabulary tables are immutable, so a caller can share one across threads and
  processes without copying, and a result never depends on call order.
- Document locator and occurrence keys have one canonical derivation, reducing the
  accession to its unhyphenated form first so the hyphenated and unhyphenated
  spellings are one filing. The Python and catalog-SQL spellings are pinned
  against each other by a cross-layer contract test.
- Compiled alternations are built by `foundation.regex.builder`, which orders
  branches longest-first, so a caller adding a term cannot introduce a shorter
  branch that shadows a longer one.
- Domain modules define values and schemas without performing filesystem,
  network, or database I/O.

**Obligations callers place on this layer.**

- Import downward only. The scanner rejects any import whose callee layer ranks
  above the caller's.
- Keep behavior that fetches, persists, parses, or schedules work in the owning
  upper layer rather than in domain records.
- Bump a schema's version constant rather than editing a column list. Each
  schema here carries its own version identifier, and the values are persisted
  into plans, checkpoints, and published artifacts.

## Public surface

- `Cik`, `AccessionNumber` — `edgar_sec/domain/identity.py`.
- EDGAR URL constants, builders, and the archive-URL parser —
  `edgar_sec/domain/sec_urls.py`.
- The per-package surfaces are documented in each subpackage README:
  [document](document/README.md),
  [document_inventory](document_inventory/README.md),
  [filing_catalog](filing_catalog/README.md),
  [forms](forms/README.md), [submissions](submissions/README.md),
  [taxonomy](taxonomy/README.md).

## Tests

Tests mirror `edgar_sec/domain/` under `tests/domain/`.

## Deliberate gaps

- **Endpoint coverage stops at submissions and the archive.** `sec_urls.py` builds
  the submissions document, historical submissions, and archive document URLs. The
  XBRL `companyconcept`/`companyfacts` APIs are not here at all, and the
  `company_tickers.json` endpoint is a pipeline-local constant, so a caller
  needing one of those assembles the URL itself.
- **The `layer-boundary` scanner does not check for cycles.** It flags upward
  layer-rank dependencies only, so a same-layer import cycle passes the gate and
  remains a review responsibility.
