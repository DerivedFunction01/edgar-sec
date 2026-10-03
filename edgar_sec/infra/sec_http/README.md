# `edgar_sec/infra/sec_http` — the single point of contact with SEC's HTTP endpoints

Everything that talks to `data.sec.gov` or `www.sec.gov` goes through
`SecHttpClient`, which owns request pacing, retry classification, the on-disk
response cache, run metrics, and the failure ledger, so no caller re-implements
any of them and no caller accidentally retries a 404 four times.

## Purpose

The SEC's fair-access guidance asks a client to stay well under a request
ceiling and to identify itself. A run that fetches millions of documents needs
more: it must survive 429s without hammering, replay a run without the network,
and remember a URL that already failed across *separate* runs so it does not
keep paying for the same 404.

This is a transport-and-policy package. It knows nothing about filings,
submissions documents, or archive files — a caller supplies a URL and chooses
the accessor.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `client.py` | `SecHttpClient` and `default_headers`; the one place a request is sent. |
| `rate_limit.py` | `RateLimiter`: slot reservation, throttle escalation, quiet-period recovery, and the pacing policy. |
| `retry.py` | `RetryPolicy`: HTTP status classification and jittered exponential backoff. |
| `cache.py` | `SqlCache`: zstd-compressed response cache and failure ledger in one SQLite file. |
| `metrics.py` | `HttpMetrics`: lock-guarded counters and `snapshot()`. |
| `errors.py` | The transport error taxonomy. |
| `__init__.py` | Docstring only. No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **`session_factory` is the supported test seam.** It replaces
  `requests.Session()` and nothing else changes: pacing, retry classification,
  backoff, the cache, the failure ledger, and metrics all run for real above it.
  `tests.support.build_test_http` injects a scripted session this way, so a test
  that needs a different pace or budget narrows it through `RateLimiter` and
  `RetryPolicy` rather than reaching into the client's send path.
- **A `User-Agent` containing `@` is mandatory**, enforced at construction, and
  the header set is fixed at
  `{"User-Agent": ..., "Accept-Encoding": "gzip, deflate"}`. This is SEC
  fair-access compliance, not a convention.
- **Pacing precedes every send, including retries.** A retried request is paced
  exactly like a first attempt, and one limiter serves any number of threads.
- **A throttle widens the interval; a quiet period narrows it.** On 429 the
  interval is multiplied by `THROTTLE_MULTIPLIER = 1.5`, or raised to the
  server's `Retry-After` when that header is all digits, clamped by
  `MAX_INTERVAL_S = 60.0` and `RETRY_AFTER_CAP_S = 120.0`. After
  `RECOVERY_QUIET_S = 30.0` seconds with no throttle, the interval decays by
  `RECOVERY_DECAY = 0.10` of the excess per call down to the floor,
  `DEFAULT_MIN_INTERVAL_S = 1.0 / DEFAULT_RATE_LIMIT_RPS` with
  `DEFAULT_RATE_LIMIT_RPS = 8.0`.
- **Retry classification is total and explicit.** `classify` returns exactly one
  of `ok` (200), `throttle` (429), `retry` (408, 425, any 5xx), or `permanent`
  (every other status, including 404). A `Retry-After` replaces the computed
  backoff after being clamped to `RETRY_AFTER_CAP_S`; otherwise backoff doubles
  from `BACKOFF_BASE_S = 0.5` up to `BACKOFF_CAP_S = 30.0` seconds, with jitter.
  `max_retries` defaults to 3, so a transient failure gets up to four sends.
- **Network errors and timeouts are retried; 4xx are not.** A timeout and a
  connection failure are handled separately, each signalling the limiter's
  network-error hook — intentionally a no-op, since a failed connection is not
  evidence of a rate signal — and then retrying with backoff, ending in
  `RetryExhausted`. A non-retryable 4xx is recorded in the ledger as
  `permanent=True` and raised as `PermanentHttpError` immediately.
- **A successful fetch clears the URL's failure history**, so a URL that
  recovered does not carry a stale ledger entry into the next run.
- **The failure ledger is per-URL and spans runs.** A `url_failures` row keyed by
  `sha256(url)` holds `failed_runs`, `last_kind`, `last_status`, `last_detail`,
  and `permanent`, and `failed_runs` accumulates on conflict. Before sending, a
  `permanent` entry or `failed_runs >= max_failure_attempts` (default 3) raises
  `PermanentHttpError` without a request; pass `ignore_failure_history=True` to
  bypass the preflight. The failure kinds the client records in the ledger are
  `timeout`, `network`, `size_exceeded`, `throttle`, `retryable_http`,
  `permanent`, and `bad_json`; `http_retry` and `ledger_skip` are counted in
  metrics only.
- **The cache is zstd-compressed, keyed by URL, with a selective TTL.** Expiry is
  set only for URLs whose path ends in `.json` and only when `ttl_s > 0`;
  every other path never expires. The default TTL is 90 days
  (`DEFAULT_CACHE_TTL_S`). The SQLite connection runs in WAL mode with a
  busy timeout, which is what makes it safe for concurrent workers. Payload
  compression is the shared codec in `foundation/compression.py`, not a local
  one.
- **With no `cache_dir` there is no cache and no ledger.** Every cache and ledger
  call is guarded, so the client works with caching fully disabled — and loses
  the failure-history preflight with it.
- **`peek_cache` never costs a rate slot.** It counts a `cache_hit` metric and is
  the probe the broker uses to answer a request from disk without pacing.
- **`get_json_ex` preserves acquisition provenance.** It returns
  `(payload, byte_count, sha256_of_raw_bytes)` computed from the *unparsed* body,
  so a dataset can record how many bytes it received and their digest;
  `get_json` discards both. Both refuse a non-object JSON root with
  `PermanentHttpError`, and a `JSONDecodeError` is recorded as a permanent
  `bad_json` failure.
- **An optional response size cap exists and is off by default.**
  `max_response_bytes=None` means unlimited; when set, a 200 larger than the cap
  is recorded as a permanent `size_exceeded` failure and raises
  `ResponseTooLargeError`, which subclasses `PermanentHttpError` so a caller
  catching only the base class still handles it.
- **The transport has no transport-level retries.** The mounted `HTTPAdapter` is
  configured with retries disabled, so a request is never silently replayed
  beneath the metrics and the ledger.

**Obligations callers place on this package**

- Supply a `User-Agent` that contains `@`, ideally a real contact address.
- Close the underlying `SqlCache` when the client is done. Nothing registers an
  `atexit` hook, and leaving WAL files open is how a cache directory becomes
  undeletable.
- Tolerate the exception taxonomy: `PermanentHttpError` (do not retry),
  `RetryExhausted` (the budget is spent, for timeout, network, 429, and
  retryable 5xx alike), and `ResponseTooLargeError` (a `PermanentHttpError`).
- Read `metrics.snapshot()` rather than the individual counters if a consistent
  view matters.
- `HttpMetrics.responses_2xx` increments for *every* recorded status, not only
  2xx. The name is misleading; `status_counts` is the field to trust.

## Public surface

Entry points by owning module; each module's docstring is authoritative for its
members.

- `client.py` — `SecHttpClient` and its accessors `get_bytes`, `get_text`,
  `get_json`, `get_json_ex`, `peek_cache`, `load_failure_entry`; the
  `SecHttpClient.from_settings` constructor; and `default_headers`.
- `rate_limit.py` — `RateLimiter` and the pacing constants.
- `retry.py` — `RetryPolicy` and the backoff constants.
- `cache.py` — `SqlCache` and `make_cache_store`.
- `metrics.py` — `HttpMetrics`.
- `errors.py` — the error hierarchy. `client.py` re-exports the same three
  names, but this is where they are owned.

**Command surface:** none.

## Mirrored tests

`tests/infra/sec_http/`, one file per source module, with network fakes injected
through `session_factory`. The modules without a mirrored file are named in
[`../README.md`](../README.md); what the failure-ledger preflight does *not* pin
is named under *Deliberate gaps*.

## Deliberate gaps

- **No in-flight concurrency cap.** The client paces by reserving limiter slots
  but never limits how many threads may be inside a request simultaneously, so a
  caller that constructs one client per thread with `min_interval_s=0` gets no
  ceiling. The layer's only cap is the broker's connection semaphore, and
  nothing enforces broker-mediated routing.
- **No read-only cache view.** `cache.py` offers no fail-open reader, so
  inspecting cached responses means opening the same writable object as the
  client. A `SqlCacheReader` here would treat an absent optional table as empty
  instead of raising, letting a caller inspect a cache without creating or
  repairing it first.
- **No public handle on the cache file from a `SecHttpClient`.** The `SqlCache`
  the client builds is reachable only through a private attribute, so a caller
  that must close it has no supported route to the handle.
- **The ledger is a per-cache-directory blacklist, not a shared one.** The
  `url_failures` table lives in `cache_dir/responses.sqlite`, so a run with a
  fresh cache directory has no failure history at all and two runs with
  different `cache_dir` values never see each other's permanent failures. A URL
  is remembered across runs only when the same cache directory is reused.
- **No test pins the ledger preflight.** It is the mechanism that stops a run
  paying for the same 404 repeatedly, and no test constructs a persisted
  `url_failures` row and asserts the short-circuit.
- **No `Retry-After` handling for a non-digit header.** The parse requires the
  header to be all digits, so the HTTP-date form is ignored and computed backoff
  is used instead; and because `RETRY_AFTER_CAP_S = 120.0`, a server asking for
  longer is ignored regardless.
- **No `Retry-After` for 503.** Every 5xx is classified as `retry` with no
  special handling of 503's `Retry-After`, unlike 429.
- **No response size cap by default**, so an unexpectedly large archive file is
  read fully into memory before anything notices.
- **No streaming download.** `get_bytes` reads a response body that `requests`
  has already buffered in full, so `max_response_bytes` bounds *acceptance*, not
  the read. Bounded memory requires the caller to accept that trade.
- **No redirect, proxy, or TLS configuration.** The session is mounted for
  `https://` and `http://` with a bare adapter; there is no redirect policy, no
  proxy, and no certificate handling.
- **Metrics are in-process and lost on exit.** Nothing persists or aggregates
  them across processes, so a multi-process run's totals live only wherever the
  client happens to run. See [`../broker/README.md`](../broker/README.md) for
  what a brokered run can and cannot report.
