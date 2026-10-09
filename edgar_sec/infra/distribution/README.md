# `edgar_sec.infra.distribution` — Generic multi-machine distribution engine

## Purpose

A pipeline-agnostic distribution engine providing deterministic chunk partitioning,
isolated worker bundle export, signed cryptographic receipts, coordinator chunk adoption,
and an interactive console.

## Contracts

- **Pipeline-derived paths:** Bundles are namespaced by pipeline (`distrib/<pipeline>/<plan_id[:8]>`) to prevent collision.
- **Pipeline affinity:** `assert_pipeline_affinity` rejects running a worker or importing a bundle across mismatched pipelines.
- **Tamper-evident receipts:** Receipts sign off on SHA-256 chunk hashes; import refuses missing files or altered digests.
- **Idempotent adoption:** Coordinator adoption ignores duplicate chunks cleanly and reports new vs already present counts.

## Deliberate Gaps

- **No transport mechanism**: Distribution writes file bundles to disk; network copying (rsync, scp, NFS) is operator-owned.
- **No cluster scheduler**: Workers execute locally against their bundle; multi-node scheduling is operator-driven.
