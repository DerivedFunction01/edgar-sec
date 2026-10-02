# `edgar_sec/infra/sec_http` — the single point of contact with SEC's HTTP endpoints

Everything that talks to `data.sec.gov` or `www.sec.gov` goes through
`SecHttpClient`. It owns request pacing, retry classification, an on-disk
response cache, run metrics, and a failure ledger, so no caller re-implements
any of them and no caller accidentally retries a 404 four times.

## Purpose

The SEC publishes fair-access guidance that a client must stay well under a
request ceiling and must identify itself. A pipeline that fetches millions of
documents needs more than that: it needs to survive 429s without hammering, to
replay a run without the network, and to remember that a URL already failed
across *separate* runs so it does not keep paying for the same 404.

This is a transport-and-policy package. It does not know what a filing, a
submissions JSON document, or an archive file is — callers pass it a URL and
choose the accessor (`get_bytes`, `get_text`, `get_json`, `get_json_ex`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `client.py` | `SecHttpClient` and `default_headers`; the one place a request is sent. |
| `rate_limit.py` | `RateLimiter`: slot reservation, throttle escalation, quiet-period recovery, and the six pacing constants. |
| `retry.py` | `RetryPolicy`: HTTP status classification and jittered exponential backoff. |
| `cache.py` | `SqlCache`: zstd-compressed response cache and failure ledger in one SQLite file. |
| `metrics.py` | `HttpMetrics`: lock-guarded counters and `snapshot()`. |
| `errors.py` | `PermanentHttpError`, `RetryExhausted`, `ResponseTooLargeError`. |
| `__init__.py` | Docstring only. No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **`session_factory` is the supported test seam.** It replaces
  `requests.Session()` and nothing else changes: pacing, retry classification,
  backoff, the cache, the failure ledger, and metrics all run for real above it.
  `tests.support.build_test_http` and `tests/infra/sec_http/test_client.py`
  inject a scripted session this way, collapsing
  `RateLimiter(min_interval_s=0.001)` and
  `RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0)` so tests stay
  fast. Reaching into `_send` or monkeypatching module internals is not the
  supported route (AGENTS.md §6.5).
- **A `User-Agent` containing `@` is mandatory.** `default_headers` raises
  `ValueError` if the user agent is empty or has no `@`, and the constructor
  independently rejects an empty one. The header set is fixed at
  `{"User-Agent": ..., "Accept-Encoding": "gzip, deflate"}`; the default is
  `foundation.runtime.settings.sec.DEFAULT_USER_AGENT`. This is SEC fair-access
  compliance, enforced at construction rather than by convention.
- **Pacing precedes every send, including retries.** Each iteration of the retry
  loop calls `rate_limiter.acquire()` and sleeps the returned delay, so a
  retried request is paced exactly like a first attempt. `acquire()` reserves the
  slot under a lock and returns the delay rather than sleeping inside it, which
  is what makes one limiter usable from many threads.
- **A throttle widens the interval; a quiet period narrows it.** On HTTP 429,
  `signal_throttle` raises the interval by `THROTTLE_MULTIPLIER = 1.5`, or to the
  `Retry-After` value when one is present, clamped by `MAX_INTERVAL_S = 60.0` and
  `RETRY_AFTER_CAP_S = 120.0`. `Retry-After` is read only when it is all digits,
  otherwise computed backoff is used. After `RECOVERY_QUIET_S = 30.0` seconds
  with no throttle, `acquire()` decays the interval by `RECOVERY_DECAY = 0.10` of
  the excess per call until it reaches `min_interval_s`. The default floor is
  `DEFAULT_MIN_INTERVAL_S = 1.0 / DEFAULT_RATE_LIMIT_RPS`, with
  `DEFAULT_RATE_LIMIT_RPS = 8.0`.
- **Retry classification is total and explicit.** `RetryPolicy.classify` returns
  exactly one of `ok` (200), `throttle` (429), `retry` (408, 425, any 5xx), or
  `permanent` (everything else, including every other 4xx such as 404). Backoff
  is `min(0.5 * 2**attempt, 30.0)` seconds multiplied by
  `1.0 + random.uniform(0.0, 0.25)`; a `retry_after_s` replaces the exponential
  term after being clamped to `[0, 120.0]`. Default `max_retries` is 3, so a
  transient failure gets up to four sends.
- **Network errors and timeouts are retried; 4xx are not.** `Timeout` and
  `RequestException` are caught separately, each signalling
  `rate_limiter.signal_network_error()` — intentionally a no-op, since a failed
  connection is not evidence of a rate signal — and then retrying with backoff,
  ending in `RetryExhausted` on exhaustion. A non-retryable 4xx is recorded in the
  ledger as `permanent=True` and raised as `PermanentHttpError` immediately.
- **A successful fetch clears the URL's failure history.** On a 200 the client
  writes the cache entry and then calls `clear_failure(url)`, so a URL that
  recovered does not carry a stale ledger entry into the next run.
- **The failure ledger is per-URL and spans runs.** `SqlCache` keeps a
  `url_failures` row keyed by `sha256(url)` holding `failed_runs`, `last_kind`,
  `last_status`, `last_detail`, and `permanent`; `record_failure` increments
  `failed_runs` on conflict. Before sending, `_preflight_skip` turns that into a
  decision: a `permanent` entry, or `failed_runs >= max_failure_attempts`
  (default 3), raises `PermanentHttpError` without a request. Pass
  `ignore_failure_history=True` to bypass the preflight. The failure kinds the
  client can record are `timeout`, `network`, `size_exceeded`, `throttle`,
  `retryable_http`, `permanent`, and `bad_json`, plus the client-side
  `ledger_skip`, which is counted in metrics only.
- **The cache is zstd-compressed, keyed by URL, with a selective TTL.** Payloads
  are stored compressed in a `payload BLOB` and decompressed on read. The codec
  itself is not owned here: `compress_payload` / `decompress_payload` come from
  `foundation/compression.py`, which holds the one implementation every BLOB
  column in the tree uses. Expiry is set only for URLs whose path ends in `.json`
  and only when `json_ttl_s > 0`; every other path gets `expires_at = NULL` and
  never expires. The default TTL is `DEFAULT_CACHE_JSON_TTL_S = 90` days. The
  SQLite connection runs in WAL mode with `busy_timeout=5000`, which is what
  makes it safe for concurrent workers.
- **With no `cache_dir` there is no cache and no ledger.** `make_cache_store`
  returns `None` for `cache_dir=None`, and every cache and ledger call in the
  client is guarded. The client works with caching fully disabled; it simply
  loses the failure-history preflight too.
- **`peek_cache` never costs a rate slot.** It reads the store and counts a
  `cache_hit` metric, and is the probe the broker uses to answer a request from
  disk without pacing.
- **`get_json_ex` preserves acquisition provenance.** It returns
  `(payload, byte_count, sha256_of_raw_bytes)` computed from the *unparsed* body,
  so the submissions dataset can record how many bytes it received and their
  digest. `get_json` discards both. Both refuse a non-object JSON root with
  `PermanentHttpError`, and a `JSONDecodeError` is recorded as a permanent
  `bad_json` failure.
- **An optional response size cap exists and is off by default.**
  `max_response_bytes=None` means unlimited; when set, a 200 response larger than
  the cap is recorded as a permanent `size_exceeded` failure and raises
  `ResponseTooLargeError`, which subclasses `PermanentHttpError` — so a caller
  that only catches the base class still handles it.
- **The transport has no transport-level retries.** The mounted `HTTPAdapter` is
  configured with `Retry(total=0, connect=0, read=0)` and a pool of 16
  connections. All retrying is `SecHttpClient`'s own loop, so a request is never
  silently replayed beneath the metrics and the ledger.

**Obligations callers place on this package**

- Supply a `User-Agent` that contains `@`, ideally a real contact address.
- Close the underlying `SqlCache` when the client is done. Nothing registers an
  `atexit` hook; `SqlCache.close()` is the caller's job, and leaving WAL files
  open is how a cache directory becomes undeletable.
- Tolerate the exception taxonomy: `PermanentHttpError` (do not retry),
  `RetryExhausted` (the budget is spent), and `ResponseTooLargeError` (a
  `PermanentHttpError`). `RetryExhausted` is raised for timeout, network, 429,
  and retryable 5xx exhaustion alike. The trailing
  `raise RetryExhausted(url, "exhausted all retry attempts")` is a fallthrough
  for the empty-range case: it fires only when `max_retries` is negative, since
  every other path out of the loop returns or raises first.
- Read `metrics.snapshot()` rather than the individual counters if a consistent
  view matters; direct attribute reads are individually guarded and individually
  stale.
- Accept that `HttpMetrics.record_status` increments `responses_2xx` for *every*
  status it records, including failures. The name is misleading;
  `status_counts` is the field to trust.

## Public surface

- `SecHttpClient` — the client. Accessors `get_bytes`, `get_text`, `get_json`,
  `get_json_ex`, `peek_cache`, `load_failure_entry`. The constructor takes
  `rate_limiter`, `retry_policy`, `timeout_s`, `cache_dir`, `json_ttl_s`,
  `metrics`, `max_failure_attempts`, `ignore_failure_history`,
  `max_response_bytes`, and `session_factory`.
- `SecHttpClient.from_settings` — build a client from a resolved `SecSettings`.
- `default_headers` — the fixed SEC header set, with the `@` guard.
- `RateLimiter` — `acquire()`, `signal_throttle(retry_after_s)`,
  `signal_network_error()`, `snapshot()`, and the `interval` property.
- `DEFAULT_MIN_INTERVAL_S`, `MAX_INTERVAL_S`, `THROTTLE_MULTIPLIER`,
  `RECOVERY_QUIET_S`, `RECOVERY_DECAY`, `RETRY_AFTER_CAP_S` — the pacing
  vocabulary. `rate_limit.py` also re-exports `DEFAULT_RATE_LIMIT_RPS`, which is
  defined in `foundation.runtime.settings.sec`.
- `RetryPolicy` — `classify(status_code)`, `delay(attempt, retry_after_s)`;
  fields `max_retries`, `backoff_base_s`, `backoff_cap_s`, `jitter`.
- `BACKOFF_BASE_S` (`0.5`), `BACKOFF_CAP_S` (`30.0`). `retry.py` also
  re-exports `DEFAULT_MAX_RETRIES` and `DEFAULT_TIMEOUT_S` from
  `foundation.runtime.settings.sec`.
- `SqlCache` — `get`, `put`, `load_failure_entry`, `record_failure`,
  `clear_failure`, `close`; attribute `db_path`, the file
  `cache_dir/responses.sqlite`.
- `make_cache_store` — returns a `SqlCache`, or `None` when `cache_dir is None`.
- `HttpMetrics` — `record_attempt`, `record_status`, `record_failure`,
  `record_retry`, `record_cache_hit`, `snapshot`.
- `PermanentHttpError` — non-retryable failure; carries `url`, `reason`,
  `status_code`.
- `RetryExhausted` — retry budget spent; carries `url`, `reason`, `status_code`.
- `ResponseTooLargeError` — a `PermanentHttpError` subclass raised when
  `max_response_bytes` is exceeded.
- `client.py` re-exports the three error types in its own `__all__` even though
  it imports rather than defines them. Import the error hierarchy from
  `edgar_sec.infra.sec_http.errors`, which is where it is owned.

**Command surface:** none.

## Tests

- `tests/infra/sec_http/test_cache.py`
- `tests/infra/sec_http/test_client.py` — headers, CIK URL padding (a
  `domain.sec_urls` concern asserted here), the cache probe and its hit metric,
  and `get_json_ex` provenance including the non-object-root refusal. The
  scripted session is injected through `session_factory`.
- `tests/infra/sec_http/test_rate_limit.py`
- `tests/infra/sec_http/test_retry.py`

`metrics.py` and `errors.py` have no mirrored test module. `HttpMetrics` is
asserted indirectly (`test_client.py` checks `cache_hits`), and the error types
are asserted through `test_client.py` and
`tests/infra/broker/test_broker.py`. The failure-ledger *preflight* —
`_preflight_skip` raising `PermanentHttpError` from a persisted `url_failures`
row — is not covered by any test in this package.

## Deliberate gaps

- **No in-flight concurrency cap.** `SecHttpClient` contains no `Semaphore`: it
  paces by reserving slots in `RateLimiter` but never limits how many threads may
  be inside a request simultaneously. v1's cap lived in the broker, not the
  transport, and v2's broker uses the same `max_connections=32` default, so this
  is not a regression — but a caller that constructs one client per thread with
  `min_interval_s=0` still gets no ceiling at all. The only cap in the infra
  layer is `threading.Semaphore(max_connections)` in `broker/sec_broker.py`.
  Nothing enforces broker-mediated routing either, so this is a discipline the
  architecture relies on rather than a guarantee the code makes.
- **No read-only cache reader.** `cache.py` offers `SqlCache` and
  `make_cache_store` only. There is no `SqlCacheReader` or any fail-open view, so
  a tool that wants to inspect cached responses without risking a write must
  open the same writable object. The fail-open pattern does exist elsewhere in
  the layer — `storage/fixture_store.FixtureStore.documents()` returns an empty
  tuple when its optional `document_blobs` table is absent — so its absence here
  is a genuine omission rather than a rejection of the idea. (Note that
  `FixtureStore` still *raises* on a missing database; only the partial store
  degrades.)
- **No public handle on the cache file from a `SecHttpClient`.** The client
  resolves `Path(cache_dir).resolve()` and passes it to `make_cache_store`; the
  resulting `SqlCache` is reachable only through the private `_cache` attribute,
  which `test_client.py` in fact pokes.
- **No `Retry-After` handling for a non-digit header.** The parse requires
  `retry_after_hdr.isdigit()`, so the HTTP-date form is ignored and computed
  backoff is used instead. The value does reach `signal_throttle` for the *next*
  request, but `RETRY_AFTER_CAP_S = 120.0` means a server asking for longer is
  ignored.
- **No `Retry-After` for 503.** `classify` sends every 5xx to `retry` with no
  special handling of 503's `Retry-After`, unlike 429.
- **No response size cap by default.** `max_response_bytes` defaults to `None`,
  so an unexpectedly large archive file is read fully into memory before anything
  notices. The broker, which builds its own client with no arguments, inherits
  that default and offers no way to pass a limit.
- **No streaming download.** `get_bytes` reads `response.content`, which
  `requests` has already buffered in full. A caller wanting bounded memory must
  set `max_response_bytes`, which bounds *acceptance* but not the read.
- **No redirect, proxy, or TLS configuration.** The session is mounted for
  `https://` and `http://` with a bare `HTTPAdapter`; there is no
  retry-after-redirect policy, no proxy, and no certificate handling.
- **Metrics are in-process and lost on exit.** `HttpMetrics` is a plain dataclass
  with a lock; nothing persists or aggregates across processes. A
  multi-process run's totals exist only in the broker process, and
  `SecBrokerClient.metrics` returns `None`.
- **`HttpMetrics.responses_2xx` counts every recorded response**, not just
  successful ones. The field name says 2xx; the increment is unconditional. Use
  `status_counts` for anything that matters.
- **The ledger is a per-cache-directory blacklist, not a shared one.** The
  `url_failures` table lives in `cache_dir/responses.sqlite`, so a run with a
  fresh cache directory has no failure history at all, and two runs with
  different `cache_dir` values never see each other's permanent failures. The
  module docstring calls the ledger a cross-run mechanism; that holds only when
  the same cache directory is reused.
- **No test for the ledger preflight.** `_preflight_skip` is the mechanism that
  stops a run paying for the same 404 repeatedly, and no test in this package
  constructs a persisted `url_failures` row and asserts the short-circuit.
  `test_cache.py` covers the table, not the decision built on it.
- **The multi-process story is the broker, and the broker is thin.** See
  [`../broker/README.md`](../broker/README.md): no CLI, no supervisor, no token
  accounting, and `managed_broker` has no consumer outside the tests.