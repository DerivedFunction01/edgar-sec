# `edgar_sec.foundation.sql` — read-only validation for operator queries

Layer 0. One module, one job: decide whether a SQL string a human typed is a
read.

## Why this exists, and when it does not

The repository's own SQL is not untrusted. `infra.storage.duckdb_catalog` builds
statements from validated identifiers and escaped literals, so that path needs no
guard — a text filter in front of it would be theatre.

What does need a guard is a **console**: a query string from a browser, of
unknown intent, executed against real files. That is the only case this package
serves, and it exists because that case shipped without one.

## Contract

| Function | Guarantee |
| :--- | :--- |
| `validate_read_only(query)` | Returns the normalized query, or raises `SqlGuardError`. Never returns a partially-validated string. |
| `SqlGuardError` | Subclasses `ValueError`, so a caller can catch either. |
| `ALLOWED_LEADING_KEYWORDS` | The allowlist, exported so the error message and the rule cannot drift apart. |

A statement is accepted only if:

1. It is non-empty after trailing semicolons are stripped.
2. It contains no `;` outside a string literal or comment.
3. Its first meaningful token — after leading comments — is one of `SELECT`,
   `WITH`, `DESCRIBE`, `EXPLAIN`, `SHOW`, or `PRAGMA table_info`.

`PRAGMA` is on the list **only** in the `table_info` form. Bare `PRAGMA` writes.

## What this is not

A guard is a filter, not a sandbox. Passing `validate_read_only` does not make a
query safe to run; it makes it *read-shaped*. The caller still owns:

- a read-only connection (the viewer uses an in-memory one and binds artifacts
  only as table-function arguments),
- a row cap and a payload cap,
- a timeout,
- and refusing table functions (`read_parquet`, `read_csv`, …) in console input,
  since a console that could name any path on disk is not a console over *one*
  dataset.

## Deliberate gaps

- **No AST parse.** A real parser would classify far more precisely. The
  keyword approach is a smaller surface to get wrong and is testable by
  inspection; a half-implemented SQL grammar would be neither.
- **Malformed input is deferred, not diagnosed.** An unterminated string or
  comment runs to end-of-string and the statement is passed on; DuckDB names the
  real syntax problem far better than this could. What matters is that the
  scanner terminates.
- **No allowlist of tables or columns.** The caller scopes the query by what it
  binds as the only visible relation.
- **Not the repository's SQL boundary.** v1 had `sql-boundary` and
  `storage-boundary` scanners policing raw SQL out of phase code; neither
  reached v2, and this module does not replace them. A future scanner may.

## Mirrored tests

`tests/foundation/sql/test_guard.py` — 35 cases: accepted reads, rejected writes
and stacked statements, the `PRAGMA table_info` restriction, separator scanning
through quotes and comments, repeated leading comments, and the
defer-malformed-input contract.
