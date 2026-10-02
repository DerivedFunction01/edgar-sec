# `edgar_sec.foundation.sql` — read-only validation for operator queries

Layer 0. One module, one job: decide whether a SQL string a human typed is a
read.

## Layout

| Module | Responsibility |
| :--- | :--- |
| [`guard.py`](guard.py) | Verb allowlist, statement-separator scan, leading-comment stripping, `validate_read_only`. |
| `__init__.py` | One-line docstring. No re-exports, per AGENTS.md §1.2. |

## Why this exists

The repository's own SQL is not untrusted. `infra.storage.duckdb_catalog` builds
statements from validated identifiers and escaped literals, so that path needs no
guard. What needs one is a **console** — a query string of unknown intent run
against real files. That is the only case this package serves.

## Contract

| Symbol | Guarantee |
| :--- | :--- |
| `validate_read_only(query)` | Returns the normalized query, or raises `SqlGuardError`. Never returns a partially-validated string. |
| `SqlGuardError` | Subclasses `ValueError`, so a caller can catch either. |
| `ALLOWED_LEADING_KEYWORDS` | The allowlist, exported so the error message and the rule cannot drift apart. |

A statement is accepted only if:

1. It is non-empty after trailing semicolons are stripped.
2. It contains no `;` outside a string literal or comment. The scan tracks quote
   state and treats `''` / `""` as an escaped quote rather than a terminator.
3. Its first meaningful token — after **every** leading line and block comment,
   stripped repeatedly — is one of `SELECT`, `WITH`, `DESCRIBE`, `EXPLAIN`,
   `SHOW`, or `PRAGMA table_info`.

The separator check runs before the verb check, so `DROP TABLE a; SELECT 1` is
reported as a multiple-statement problem rather than a verb problem.
`PRAGMA` is on the list **only** in the `table_info` form: bare `PRAGMA` writes.

## Public surface

`from edgar_sec.foundation.sql.guard import ALLOWED_LEADING_KEYWORDS,
SqlGuardError, validate_read_only`

## Command surface

None. No `__main__.py`, no entry point. The only caller is
`edgar_sec.apps.viewer.console.run_dataset_sql`.

## A guard is a filter, not a sandbox

Passing `validate_read_only` does not make a query safe to run; it makes it
*read-shaped*. The caller still owns the rest, and `apps/viewer/console.py` owns
all four: a read-only in-memory connection scoped to a private `dataset` view, a
row cap and a payload cap, a timeout, and a refusal of table functions
(`read_parquet`, `read_json`, `read_csv`, `sqlite_scan`) so a console scoped to
one dataset cannot reach another file on disk.

## Mirrored tests

[`tests/foundation/sql/test_guard.py`](../../../tests/foundation/sql/test_guard.py)
— 35 cases: accepted reads, rejected writes and stacked statements, the
`PRAGMA table_info` restriction, separator scanning through quotes and comments,
repeated leading comments, and the defer-malformed-input contract.

## Deliberate gaps

- **No AST parse.** A real parser would classify far more precisely. The keyword
  approach is a smaller surface to get wrong; a half-implemented SQL grammar
  would be neither.
- **Malformed input is deferred, not diagnosed.** An unterminated string or
  comment runs to end-of-string and the statement is passed on; DuckDB names the
  real syntax problem better than this could. What matters is that the scanner
  terminates.
- **No allowlist of tables or columns.** The caller scopes the query by what it
  binds as the only visible relation.
- **Not the repository's SQL boundary.** v1's `sql-boundary` and
  `storage-boundary` scanners (`.v1/defs/sql/checks.py`,
  `.v1/defs/storage/checks.py`) did not reach v2, and this module does not
  replace them. A future scanner may.