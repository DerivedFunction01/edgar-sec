# S9 acquisition settings

## Purpose and status

This page owns S9's configuration boundary. The acquisition byte ceiling is registered
in the shared modular settings provider. No direct `os.environ` or `os.getenv` access
is permitted.

## Reused settings

S9 uses the shared SEC settings for the secret user agent, request rate, timeout,
retry policy, and failure-attempt budget. It uses runtime resource derivation for
worker count, memory limits, threads, and temporary directory. These values are not
duplicated in an S9 monolithic config object.

The response byte ceiling passed to `SecHttpClient` is an optional client argument;
the S9 runner resolves it from the acquisition setting and always supplies a finite
maximum enforced against streamed decoded bytes. The default is 256 MiB: the
initial bounded-response policy admits large filing bodies while still refusing
unbounded transfers. It is an acquisition limit, not an S10 in-memory budget or a
claim that every body below the cap fits every processor. Deployments may lower or
raise it explicitly; `None`/unbounded is not valid.

## Registered setting

The phase-owned setting lives in `edgar_sec/foundation/runtime/settings/acquisition.py`
with only the S9-specific policy that shared settings do not provide:

| Logical key | Environment name | Type | Validation | Consumer |
|---|---|---|---|---|
| `acquisition.max_response_bytes` | `ACQUISITION_MAX_RESPONSE_BYTES` | positive integer | Defaults to `268435456`; finite and greater than zero; no booleans or unbounded sentinel. | Run/capture CLI resolution and bounded acquisition/fixture streaming. |

The registry derives the environment name through `environment_name()` and supports
CLI override, environment/dotenv, stored config, and default precedence without adding
a monolithic settings class.

## Runtime resource policy

- Default worker count comes from `derive_resources()` and
  `auto_worker_count(available_bytes, worker_memory_mib=512, safety_fraction=0.9)`.
  Do not use CPU count, a fixed `max_workers`, or a per-target concurrency default.
- A user-supplied worker count is an upper-bound request, not permission to exceed
  the derived ceiling. `--workers` must be a positive non-boolean integer; choose the
  lesser of the request and derived ceiling. With no request, use the derived count.
- Each worker owns at most one in-flight body. The submitted queue is bounded by the
  same resource plan. Call `reclaim()` at bounded completed-batch intervals.
- SEC pacing is shared through the broker on one host; worker count does not scale
  that host's configured request rate. Each host resolves its own SEC settings and
  environment.

## Invocation overrides and provenance

CLI `--artifacts` chooses a resolved project root; it is not persisted as a secret or
as a path into the run identity. `--retry-failures` is an explicit action, not a
setting. Distribution worker count and fixture IDs are command arguments. Every
attempt records the effective non-secret transport settings needed to explain its
behavior; user-agent credentials and other `secret=True` settings never enter
manifests, receipts, fixture rows, or logs.

## Acceptance

Settings resolve through the shared registry with CLI overrides above environment
and stored config. Run and fixture-capture commands use the finite configured default
when the command-line override is omitted. Invalid response bounds fail before opening the HTTP client, and
the SEC rate limit is not multiplied by local worker concurrency. SEC pacing is
host-local; cross-host rate coordination and checks are explicitly out of scope, and
the local broker limit is not a cluster-wide guarantee. Acquisition distribution
remains unimplemented and in planning.
