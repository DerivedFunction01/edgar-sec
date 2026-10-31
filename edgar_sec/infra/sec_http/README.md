# `edgar_sec/infra/sec_http` — the single point of contact with SEC's HTTP endpoints

Everything that talks to `data.sec.gov` or `www.sec.gov` goes through
`SecHttpClient`, which owns pacing, retry classification, the response cache, run
metrics, and the failure ledger.

## Purpose

The SEC's fair-access guidance asks a client to stay well under a request ceiling
and to identify itself. A run fetching millions of documents must also survive
throttling without hammering, replay without the network, and remember a URL that
already failed across *separate* runs.

This is a transport-and-policy package. It knows nothing about filings or archive
files — a caller supplies a URL and chooses the accessor.

## Contracts

**Guarantees to callers**

- **`session_factory` is the supported test seam.** It replaces
  `requests.Session()` and nothing else changes: pacing, retries, cache, ledger,
  and metrics all run for real above it. A test narrows pace or budget through
  `RateLimiter` and `RetryPolicy` rather than reaching into the send path.
- **A `User-Agent` containing `@` is mandatory**, enforced at construction. This
  is SEC fair-access compliance, not a convention.
- **Pacing precedes every send, including retries**, and one limiter serves any
  number of threads.
- **A throttle widens the interval; a quiet period narrows it.** A server's
  `Retry-After` is honoured and clamped. Interval bounds, decay, and the default
  rate are policy: they are declared in `rate_limit.py` and settable through the
  `sec.*` registry in `foundation/runtime/settings/`.
- **Retry classification is total and explicit** — success, throttle, retryable,
  or permanent — so no status falls through unclassified. Backoff is jittered and
  bounded; `max_retries` bounds the sends per request.
- **Network errors and timeouts are retried; other 4xx are not.** A permanent
  status is recorded in the ledger and raised immediately as
  `PermanentHttpError`; an exhausted budget raises `RetryExhausted`.
- **A successful fetch clears the URL's failure history**, so a recovered URL does
  not carry a stale ledger entry into the next run.
- **The failure ledger is per-URL and spans runs.** A URL that previously failed
  permanently, or failed too often, raises before a request is sent;
  `ignore_failure_history=True` bypasses the preflight.
- **The cache is compressed, keyed by URL, with a selective TTL.** Only responses
  whose path implies mutability expire; an immutable archive document never does,
  because re-fetching millions of them would dismantle the cache. A caller that
  knows a URL is mutable despite its path passes `mutable=True` to `get_bytes`.
  The TTL is the `cache.ttl_s` setting; the SQLite connection runs in WAL mode so
  workers can share it.
- **With no `cache_dir` there is no cache and no ledger.** Every cache and ledger
  call is guarded, so the client works fully uncached — and loses the
  failure-history preflight with it.
- **`peek_cache` never costs a rate slot.** It is the probe the broker uses to
  answer a request from disk without pacing.
- **`get_json_ex` preserves acquisition provenance**, returning the byte count and
  digest of the *unparsed* body so a dataset can record what it received.
- **An optional response size cap exists and is off by default.** When set, an
  oversized success is recorded as a permanent failure and raises
  `ResponseTooLargeError`, a `PermanentHttpError` subclass.
- **The transport performs no retries of its own**, so a request is never silently
  replayed beneath the metrics and the ledger.

**Obligations callers place on this package**

- Supply a `User-Agent` containing `@`, ideally a real contact address.
- Close the underlying `SqlCache` when done. Nothing registers an `atexit` hook,
  and leaving WAL files open is how a cache directory becomes undeletable.
- Tolerate the exception taxonomy: `PermanentHttpError` (do not retry),
  `RetryExhausted` (budget spent), `ResponseTooLargeError` (a
  `PermanentHttpError`).
- Read `metrics.snapshot()` rather than individual counters if a consistent view
  matters, and note that `responses_2xx` increments for every recorded status —
  `status_counts` is the field to trust.

## Deliberate gaps

- **No in-flight concurrency cap.** The client reserves limiter slots but never
  limits how many threads may be inside a request, so one client per thread gets
  no ceiling. The only cap is the broker's connection semaphore, and nothing
  enforces broker-mediated routing.
- **No read-only cache view.** Inspecting cached responses means opening the same
  writable object as the client, so a reader that treated an absent optional table
  as empty would be a new capability.
- **No public handle on the cache file** from a `SecHttpClient`; it is reachable
  only through a private attribute, so a caller that must close it has no
  supported route.
- **The ledger is a per-cache-directory blacklist, not a shared one.** A run with
  a fresh cache directory has no failure history, so a URL is remembered across
  runs only when that directory is reused.
- **No test pins the ledger preflight**, which is what stops a run paying for the
  same failure repeatedly.
- **`Retry-After` is honoured only in its numeric form**, so the HTTP-date form is
  ignored and computed backoff is used; a server asking for longer than the cap is
  ignored regardless.
- **Every retryable status is handled alike**, with no special handling of a 503's
  `Retry-After`.
- **No streaming download.** `get_bytes` reads a body `requests` already buffered
  in full, so the size cap bounds *acceptance*, not the read.
- **No redirect, proxy, or TLS configuration.** The session is mounted with a bare
  adapter.
- **Metrics are in-process and lost on exit**, so a multi-process run's totals live
  only wherever the client happens to run. See
  [`../broker/README.md`](../broker/README.md).
