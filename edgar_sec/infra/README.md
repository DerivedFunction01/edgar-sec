# `edgar_sec/infra` — Layer 2: external systems, protocols, and persistence

This layer owns everything that touches the world outside the process: the SEC
HTTP protocol, the same-host acquisition broker, and every byte of durable
state on disk or in SQLite. It is not a place for business rules, and it holds
no knowledge of which phase is running or why an artifact is being written.

## Purpose

Three subpackages, each a complete vertical over one external system:

- `sec_http/` — the shared client for `data.sec.gov` and `www.sec.gov`: pacing,
  retry classification, a compressed on-disk response cache, metrics, and a
  failure ledger that remembers a URL that already failed. See
  [`sec_http/README.md`](sec_http/README.md).
- `broker/` — a Unix-domain-socket server so an arbitrary number of worker
  *processes* share exactly one `SecHttpClient`, and therefore one aggregate
  request pace, instead of each process pacing itself. See
  [`broker/README.md`](broker/README.md).
- `storage/` — atomic filesystem publication, Parquet and DuckDB I/O, the
  filing-catalog SQL builders, and the document-snapshot machinery (parts,
  manifests, the raw-payload fixture store, chunk checkpoints). See
  [`storage/README.md`](storage/README.md).

The unifying rule is that a resource budget, a serialization format, or a
protocol detail is decided **once, here**, from a machine probe or a settings
lookup, and every layer above consumes the decision rather than re-making it.

## Module map

| Subpackage | Owns |
| :--- | :--- |
| `sec_http/` | The request seam, pacing, retry classification, the compressed response cache and failure ledger, metrics, and the transport error taxonomy. |
| `broker/` | The socket protocol and its lifecycle helper, wrapping one client for the whole host. |
| `storage/` | Atomic publication, the Parquet format vocabulary, the DuckDB connection factory, catalog SQL builders, document snapshots, and the fixture payload store. |

Each subpackage README carries its own module→responsibility table. The layer
exports no symbols of its own, so there is nothing here to re-document.

## Contracts

**Boundaries**

- **Layer 2 may import only `edgar_sec.domain` and `edgar_sec.foundation`** —
  never `engine` or `pipelines`. The `layer-boundary` scanner
  (`foundation/scanners/layers.py`) enforces this by ranking the importing and
  imported module's layer from each module's AST, so an `infra` → `engine` or
  `infra` → `pipelines` import fails the gate rather than depending on review.
- Same-layer imports are unrestricted, and the scanner compares layer ranks
  only: an import cycle *inside* `infra` would not be reported. Keep subpackage
  dependencies one-directional in practice.

**Guarantees this layer makes to its callers**

- **One DuckDB connection factory, and it is always bounded.**
  `storage/duckdb.connect()` is the only `duckdb.connect()` call site in
  `edgar_sec`, and it sets the four values AGENTS.md §2.3 requires from
  `foundation.runtime.resources.derive_resources()` — at connection time, not at
  import time, so importing the module does not probe the machine.
- **One Parquet format vocabulary.** `storage/parquet.py` owns
  `DEFAULT_ROW_GROUP_SIZE = 128_000` and `DEFAULT_COMPRESSION = "zstd"`, the
  values AGENTS.md §2.5 names; every Parquet writer in the layer takes them
  rather than re-declaring a literal.
- **Publication is atomic.** Every writer stages to a temp file and renames, so
  a crashed run never leaves a half-written artifact in a published directory.
  The one exception is named in [`storage/README.md`](storage/README.md).
- **JSON leaves the layer through the shared primitive.**
  `storage/atomic.py`'s `atomic_write_json` serializes with
  `foundation.serialization.canonical_json` unless a caller explicitly asks for
  human-readable output; the `json-io` scanner flags a redefined JSON helper or
  a non-atomic write shape anywhere else.
- **Settings arrive through the registry.** No module here reads the
  environment directly, which is what keeps `environment-access` clean, and path
  roots are passed in as arguments rather than resolved from machine state.
- **No barrel re-exports.** Every `__init__.py` in the layer is a docstring, so
  importing one module does not drag in DuckDB or PyArrow. Consumers import from
  the leaf module.

**Obligations callers place on this layer**

- Take a DuckDB connection from `storage/duckdb.connect()` and pass a shared
  `RuntimeResourceProfile` (or `None`) rather than per-call numbers. The
  resource contract holds by the single call site, not by a runtime check, so a
  bypass loses it silently.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes; a
  per-call literal reintroduces the inconsistency they exist to remove.
- Treat a snapshots root passed into `storage/manifests.py` as
  `ProjectPaths.documents_root`. The layout is
  `<documents_root>/<snapshot_id>/manifest.json` with the pointer under
  `<documents_root>/current/`; `manifests.py` does not create or resolve that
  root for you.
- Inject network fakes at the transport seam
  (`SecHttpClient(session_factory=...)`); monkeypatching client internals is
  not a supported route.
- Close what you open. Nothing in this layer registers an `atexit` hook: the
  DuckDB connection, `SqlCache`, and `FixtureStore` are the caller's to close.

## Public surface

The surface is the union of the three subpackages and is documented where it is
owned: `sec_http/README.md` (client, limiter, retry policy, cache, metrics,
transport errors), `broker/README.md` (`SecBroker`, `SecBrokerClient`,
`managed_broker`), and `storage/README.md` (the atomic writers, the Parquet and
DuckDB vocabularies, the snapshot and fixture surface).

## Command surface

None. The layer is library-only: no `__main__`, no CLI, no packaging entry
point.

## Mirrored tests

`tests/infra/` mirrors this package one directory per subpackage, with one test
file per source module (AGENTS.md §6). Three modules have no mirrored test file
and are covered only through their callers: `sec_http/metrics.py`,
`sec_http/errors.py`, and `broker/daemon.py`. The storage subpackage names its
one uncovered module in its own README.

## Deliberate gaps

- **No command surface anywhere in the layer.** The broker is library-only,
  started in-process by `managed_broker()` or by a pipeline, and
  `SecBroker.serve()` is a blocking loop with no signal handling: only a caller
  holding the `SecBroker` object can stop it.
- **No persisted project configuration.** Run options are resolved per
  invocation by Layer 4 commands; nothing here reads or writes a stored config.
- **Intra-package cycles are invisible to the gate**, as noted under
  Boundaries.
- **Subpackage limitations are owned below**, and are not restated here:
  `sec_http/README.md` (no in-flight concurrency cap in the client, no
  read-only cache view), `broker/README.md` (a thin broker with no token
  accounting and no supervisor), and `storage/README.md` (SQL built directly
  with no scanner over it, Parquet as the only chunk format, no file-backed
  DuckDB staging).
