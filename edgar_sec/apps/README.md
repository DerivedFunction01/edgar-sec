# `edgar_sec/apps` — Layer 5: read-only consumers of published artifacts

An app is an operator-facing way to look at what a pipeline has already
published. It browses, pages, and queries. It does not fetch, transform,
checkpoint, or publish. That is the whole definition, and it is enforced
structurally rather than by convention.

## What an app is — and is not

**Is:** a long-lived service or tool with a public surface, reading published
artifacts through their manifests.

**Is not:** a batch pipeline. An app has no chunks, no plan, no worker, no
retry ledger, and no resumability, so none of AGENTS.md §4's pipeline contracts
bind it and none of the three pipeline packages' operational rules apply.

The distinction is not cosmetic. A viewer that grew a plan and a worker would
have become a pipeline, and putting it in `pipelines/` would have been correct.

## The one clause this layer adds

`apps/` sits at rank 5, above `pipelines/` (4). It may import anything beneath
it. The rule the scanner enforces is the reverse:

> **Nothing below `apps/` may import it.**

So a batch pipeline can never take a dependency on an operator-facing
application. That is the entire new invariant.

Be precise about what it does *not* buy: an app has the same read access a
pipeline already had. This is an **organizational** boundary first and a safety
boundary second. Cite it for the clause above, not as general protection.

The roadmap previously rejected `apps/` (see `v2_refactor_roadmap.md` §0) on the
premise that it "imports no pipeline internals." The dataset viewer falsifies
that premise — it resolves published snapshots by reading pipeline manifests —
which is what re-opened the decision.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `viewer/` | The dataset viewer: a lazy filesystem explorer over the artifacts root, manifest-driven virtual datasets, paged DuckDB reads, and a guarded read-only SQL console. See [`viewer/README.md`](viewer/README.md). |

## Contracts this package guarantees

- **Read-only, structurally.** The viewer opens an in-memory DuckDB connection.
  Columnar, CSV, JSONL, and SQLite artifacts are bound only as *table-function
  arguments*, which cannot write. A native `.duckdb` file is the one exception:
  it is `ATTACH`ed `READ_ONLY` so its tables can be browsed, and it never
  reaches the SQL console.
- **Server-bound paths.** The browser supplies opaque ids. Paths are resolved
  server-side and confined to the artifacts root; symlinks and dot-paths are
  skipped, so neither the tree walk nor an id can escape the root.
- **Bounded reads.** Row paging uses `LIMIT ? OFFSET ?` with `limit + 1` to
  compute `has_more` — never an unbounded scan and never a `COUNT` to answer
  "is there more" — and is additionally capped by serialized response bytes.
  Opening a table is a `DESCRIBE`; column statistics are opt-in.
- **Guarded console SQL.** The console is read-only and single-statement, gated
  by `foundation.sql.guard`, with row and payload caps and an interrupt-based
  timeout.

## Public surface

None yet beyond the module below. `apps/__init__.py` is a docstring: this
package re-exports nothing, per AGENTS.md §1.2.

## Command surface

None at the layer root. Each app owns its own entry point
(`python -m edgar_sec.apps.viewer`) and is registered in the root `run.py`
launcher.

## Mirrored tests

`tests/apps/` mirrors this package module-for-module. The layer itself has no
logic to test; its contract is enforced by the `layer-boundary` scanner and by
`tests/test_network_isolation.py`, which walks the import graph and fails if an
app can reach `infra.sec_http`.

## Deliberate gaps

- **One app, so far.** The dataset viewer is the only member. A shared app
  framework — a common HTTP shell, session handling, or a UI kit — is
  deliberately *not* built yet. When a second app exists and the duplication is
  real, extract the core then. Building it now would be speculative: the one
  duplication candidate (the HTTP shell) has exactly one consumer.
- **The layer is not a batch layer**, and nothing here is exempt by accident. It
  is exempt because it is not subject to the pipeline contracts in the first
  place.
- **No auth, and no remote binding.** The viewer binds `127.0.0.1` by default.
  It is a local operator tool; it is not a service and has no multi-user story.
- **`tools/ops/` is not a second home for operator tooling.** Roadmap §1.5
  proposed a Tier 3 `tools/ops/` for monitors and diagnostics. Those are
  operator-facing utilities, so this layer is their destination; shipping both
  would leave two homes for the same category.
