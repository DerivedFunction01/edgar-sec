# S9 acquisition settings

## Purpose and status

This page owns S9's configuration boundary. It is design-only; new settings must be
registered in `edgar_sec/foundation/runtime/settings/` before the acquisition
pipeline is implemented. No direct `os.environ` or `os.getenv` access is permitted.

## Reused settings

S9 uses the shared SEC settings for the secret user agent, request rate, timeout,
retry policy, and failure-attempt budget. It uses runtime resource derivation for
worker count, memory limits, threads, and temporary directory. These values are not
duplicated in an S9 monolithic config object.

The response byte ceiling passed to `SecHttpClient` is currently an optional client
argument, not a complete S9 settings contract. S9 requires a finite, configured
maximum and enforces it against streamed decoded bytes. The default is 256 MiB: the
initial bounded-response policy admits large filing bodies while still refusing
unbounded transfers. It is an acquisition limit, not an S10 in-memory budget or a
claim that every body below the cap fits every processor. Deployments may lower or
raise it explicitly; `None`/unbounded is not valid.

## Proposed setting registry

Add a phase-owned settings module (proposed key prefix `acquisition`) with only the
S9-specific policy that shared settings do not provide:

| Logical key | Environment name | Type | Validation | Consumer |
|---|---|---|---|---|
| `acquisition.max_response_bytes` | `ACQUISITION_MAX_RESPONSE_BYTES` | positive integer | Defaults to `268435456`; finite and greater than zero; no booleans or unbounded sentinel. | Streaming HTTP operation and preflight summary. |

The settings spec provides this entry through the existing modular registry and
`environment_name()` resolution. The concrete registry function/type should match
the neighboring SEC/runtime settings modules, rather than introducing a new settings
class.

## Runtime resource policy

- Default worker count comes from `derive_resources()` and
  `auto_worker_count(available_bytes, worker_memory_mib=512, safety_fraction=0.9)`.
  Do not use CPU count, a fixed `max_workers`, or a per-target concurrency default.
- A user-supplied worker count is an upper-bound request, not permission to exceed
  the derived ceiling. `--workers` must be a positive non-boolean integer; choose the
  lesser of the request and derived ceiling. With no request, use the derived count.
- Each worker owns at most one in-flight body. The submitted queue is bounded by the
  same resource plan. Call `reclaim()` at bounded completed-batch intervals.
- SEC pacing is shared through the broker; worker count does not scale the configured
  request rate.

## Invocation overrides and provenance

CLI `--artifacts` chooses a resolved project root; it is not persisted as a secret or
as a path into the run identity. `--retry-failures` is an explicit action, not a
setting. Distribution worker count and fixture IDs are command arguments. Every
attempt records the effective non-secret transport settings needed to explain its
behavior; user-agent credentials and other `secret=True` settings never enter
manifests, receipts, fixture rows, or logs.

## Acceptance

Settings resolve through the shared registry with CLI overrides above environment
and stored config. Invalid response bounds fail before opening the HTTP client, and
the SEC rate limit is not multiplied by local worker concurrency. Live distributed
workers remain deferred until cross-host rate coordination is specified; the local
broker limit is not represented as a cluster-wide guarantee.
