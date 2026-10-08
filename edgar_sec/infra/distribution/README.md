# `edgar_sec.infra.distribution` — Generic multi-machine distribution engine

## Purpose

A pipeline-agnostic distribution engine providing deterministic chunk partitioning,
isolated worker bundle export, signed cryptographic receipts, coordinator chunk adoption,
and an interactive console.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Package docstring only. |
| `protocol.py` | `DistributionAdapter`, `WorkerAssignment`, `WorkerReceipt`, and `ImportReport`. |
| `partition.py` | Deterministic round-robin chunk division and content-addressed assignment identity. |
| `guards.py` | `bundle.json` provenance manifest creation and pipeline-affinity assertions. |
| `receipt.py` | Cryptographic worker receipts, SHA-256 chunk hashing, and digest validation. |
| `discovery.py` | Filesystem bundle scanning, status categorization, and interactive selection. |
| `cli.py` | Subparser attachment (`attach_distrib_subparser`) and command dispatch. |
| `menu.py` | Interactive dashboard and management console (`DistribMenuConfig`, `run_distrib_menu`). |

## Contracts

- **Pipeline-derived paths:** Bundles are namespaced by pipeline (`distrib/<pipeline>/<plan_id[:8]>`) to prevent collision.
- **Pipeline affinity:** `assert_pipeline_affinity` rejects running a worker or importing a bundle across mismatched pipelines.
- **Tamper-evident receipts:** Receipts sign off on SHA-256 chunk hashes; import refuses missing files or altered digests.
- **Idempotent adoption:** Coordinator adoption ignores duplicate chunks cleanly and reports new vs already present counts.

## Public Surface

| Entry point | Module |
| :--- | :--- |
| `DistributionAdapter`, `WorkerAssignment`, `WorkerReceipt`, `ImportReport` | `protocol.py` |
| `divide_chunks`, `build_assignment` | `partition.py` |
| `write_bundle_manifest`, `read_bundle_manifest`, `assert_pipeline_affinity` | `guards.py` |
| `build_worker_receipt`, `write_receipt`, `read_receipt`, `verify_receipt_digests` | `receipt.py` |
| `discover_bundles`, `resolve_bundle_choice` | `discovery.py` |
| `attach_distrib_subparser`, `dispatch_distrib_subcommand` | `cli.py` |
| `DistribMenuConfig`, `run_distrib_menu`, `render_distrib_dashboard` | `menu.py` |

## Mirrored Tests

Mirrored tests live under `tests/infra/distribution/`.

## Deliberate Gaps

- **No transport mechanism:** Distribution writes file bundles to disk; network copying (rsync, scp, NFS) is operator-owned.
- **No cluster scheduler:** Workers execute locally against their bundle; multi-node scheduling is operator-driven.
