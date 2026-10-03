# `edgar_sec/apps` — Layer 5: read-only consumers of published artifacts

An app is an operator-facing way to look at what a pipeline has already published.
It browses, pages, and queries. It does not fetch, transform, checkpoint, or
publish.

**It is not a batch pipeline.** No chunks, no plan, no worker, no retry ledger,
no resumability — so none of AGENTS.md §4's pipeline contracts bind it. An app
that grew a plan and a worker would have become a pipeline, and `pipelines/` would
have been its home.

## The one clause this layer adds

`apps/` sits at rank 5, above `pipelines/` (4). It may import anything beneath it.
The rule the `layer-boundary` scanner enforces is the reverse:

> **Nothing below `apps/` may import it.**

That is the entire invariant, and it buys organizational separation rather
than safety: an app has the same read access a pipeline has.

`tests/test_network_isolation.py` proves the second half of the contract — the
viewer cannot reach `infra.sec_http` — because the temptation is structurally
higher for a viewer than for an offline phase: it browses what a *network*
pipeline produced, so reaching for the client would be the easy wrong move.

The viewer is also what makes this layer worth having. It resolves published
snapshots by asking the owning pipeline to interpret their manifests, so an app
does in fact read pipeline internals — read-only, through the public leaf
modules. That is exactly the dependency direction the clause above permits, and
a layer placed below `pipelines/` could not have it.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |
| `viewer/` | The dataset viewer: a lazy filesystem explorer, manifest-driven virtual datasets, paged DuckDB reads, a guarded read-only SQL console. Its own contracts are in [`viewer/README.md`](viewer/README.md). |

## Contracts this package guarantees

- **Read-only, structurally.** Every DuckDB connection is in-memory. Artifacts
  are bound as table-function arguments, or `ATTACH`ed `READ_ONLY`.
- **Server-bound paths.** The browser supplies opaque ids; resolution is confined
  to the artifacts root, and the walk skips symlinks and dot-paths.
- **Bounded reads.** Paging is `LIMIT ? OFFSET ?` with `limit + 1`, capped again
  by serialized response bytes.
- **Guarded console SQL.** Read-only, single-statement, row- and payload-capped,
  interrupt-bounded.

That is the layer's whole share of the contract; the mechanisms behind each
clause belong to the app that implements them.

## Public surface

None. `apps/__init__.py` is a docstring and the package re-exports nothing, per
AGENTS.md §1.2.

## Command surface

None at the layer root. Each app owns its own entry point
(`python -m edgar_sec.apps.viewer.cli`) and is registered in the root `run.py`
launcher.

## Mirrored tests

`tests/apps/` mirrors this package. The layer root has no logic of its own: its
contract is enforced by the `layer-boundary` scanner and
`tests/test_network_isolation.py`, and the viewer's by `tests/apps/viewer/`.

## Deliberate gaps

- **One app, so far.** The viewer is the only member. A shared app framework — a
  common HTTP shell, session handling, a UI kit — is deliberately not built. The
  duplication candidates have exactly one consumer each; extract them when a
  second app makes the duplication real.
- **`tools/ops/` is not a second home for operator tooling.** Monitors and
  diagnostics are operator-facing, so this layer is their destination; shipping a
  separate `tools/ops/` tree as well would leave two homes for one category.
- **No auth, and no remote binding.** Every app binds loopback by default. This
  is local operator tooling, not a service, and it has no multi-user story.
