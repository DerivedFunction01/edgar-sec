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
across *separate* runs so it does not keep paying for the same 404. This
package is where those behaviours live.

It is a transport-and-policy package. It does not know what a filing, a
submissions JSON document, or an archive file is — callers pass it a URL and
choose the accessor (`get_bytes`, `get_text`, `get_json`, `get_json_ex`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `client.py` | `SecHttpClient` and `default_headers`; the one place a request is sent (382 loc). |
| `rate_limit.py` | `RateLimiter`: slot reservation, throttle escalation, quiet-period recovery, and the six pacing constants (103 loc). |
| `retry.py` | `RetryPolicy`: HTTP status classification and jittered exponential backoff (56 loc). |
| `cache.py` | `SqlCache`: zstd-compressed response cache and failure ledger in one SQLite file (252 loc). |
| `metrics.py` | `HttpMetrics`: lock-guarded counters and `snapshot()` (74 loc). |
| `errors.py` | `PermanentHttpError`, `RetryExhausted`, `ResponseTooLargeError` (36 loc). |
| `__init__.py` | Docstring only (1 loc). No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **`session_factory` is the supported test seam.** `SecHttpClient.__init__`
  takes `session_factory: Callable[[], Any] | None` and uses it in place of
  `requests.Session()` (`client.py:62,83`). Everything above the transport runs
  for real in tests: pacing, retry classification, backoff, the cache, the
  failure ledger, and metrics. `tests/support.py:130` and
  `tests/infra/sec_http/test_client.py:83` both inject a scripted session this
  way, collapsing `RateLimiter(min_interval_s=0.001)` and
  `RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0)` so tests stay
  fast. Reaching into `_send` or monkeypatching module internals is not the
  supported route; `tests/support.py` exists so the seam is used identically
  everywhere (AGENTS.md §6.5).
- **A `User-Agent` containing `@` is mandatory.** `default_headers` raises
  `ValueError` if the user agent is empty or has no `@`
  (`client.py:36-39`); the constructor independently rejects an empty one
  (`client.py:64-65`). The header set is fixed at
  `{"User-Agent": ..., "Accept-Encoding": "gzip, deflate"}`. The default is
  `foundation.runtime.settings.sec.DEFAULT_USER_AGENT`. This is SEC fair-access
  compliance, enforced at construction rather than by convention.
- **Pacing precedes every send, including retries.** Each iteration of the retry
  loop calls `rate_limiter.acquire()` and sleeps the returned delay
  (`client.py:192-194`), so a retried request is paced exactly like a first
  attempt. `acquire()` reserves the slot under a lock and returns the delay
  rather than sleeping inside it (`rate_limit.py:45-60`), which is what makes a
  shared limiter usable from many threads.
- **A throttle widens the interval; a quiet period narrows it.** On HTTP 429,
  `signal_throttle` raises the interval by `THROTTLE_MULTIPLIER = 1.5`, or to
  the `Retry-After` value when one is present, clamped by `MAX_INTERVAL_S = 60.0`
  and `RETRY_AFTER_CAP_S = 120.0` (`rate_limit.py:62-77`). `client.py:264-274`
  reads `Retry-After` only when it is all digits, and otherwise falls back to
  computed backoff. After `RECOVERY_QUIET_S = 30.0` seconds with no throttle,
  `acquire()` decays the interval by `RECOVERY_DECAY = 0.10` of the excess per
  call until it reaches `min_interval_s` (`rate_limit.py:50-57`). The default
  floor is `DEFAULT_MIN_INTERVAL_S = 1.0 / DEFAULT_RATE_LIMIT_RPS` with
  `DEFAULT_RATE_LIMIT_RPS = 8.0` (`foundation/runtime/settings/sec.py:17`).
- **Retry classification is total and explicit.** `RetryPolicy.classify` returns
  exactly one of `ok` (200), `throttle` (429), `retry` (408, 425, any 5xx), or
  `permanent` (every other 4xx, including 404) (`retry.py:28-39`). Backoff is
  `min(0.5 * 2**attempt, 30.0)` seconds multiplied by
  `1.0 + random.uniform(0.0, 0.25)`; a `retry_after_s` replaces the exponential
  term after being clamped to `[0, 120.0]` (`retry.py:41-47`). Default
  `max_retries` is 3, so a transient failure gets up to four sends
  (`foundation/runtime/settings/sec.py:19`).
- **Network errors and timeouts are retried; 4xx are not.** `requests.exceptions.Timeout`
  and `RequestException` are caught separately, each signalling
  `rate_limiter.signal_network_error()` (which is intentionally a no-op — a
  failed connection is not evidence of a rate signal, `rate_limit.py:79-80`) and
  then retrying with backoff, ending in `RetryExhausted` on exhaustion
  (`client.py:200-233`). A non-retryable 4xx is recorded in the ledger as
  `permanent=True` and raised as `PermanentHttpError` immediately
  (`client.py:310-321`).
- **A successful fetch clears the URL's failure history.** On a 200, the client
  writes the cache entry and then calls `clear_failure(url)` (`client.py:255-258`),
  so a URL that recovered does not carry a stale ledger entry into the next run.
- **The failure ledger is per-URL and spans runs.** `SqlCache` keeps a
  `url_failures` row keyed by `sha256(url)` holding `failed_runs`, `last_kind`,
  `last_status`, `last_detail`, and `permanent` (`cache.py:102-115`);
  `record_failure` increments `failed_runs` on conflict
  (`cache.py:206-217`). Before sending, `_preflight_skip` turns that into a
  decision: a `permanent` entry, or `failed_runs >= max_failure_attempts`
  (default 3), raises `PermanentHttpError` without a request
  (`client.py:144-163`). Pass `ignore_failure_history=True` to bypass the
  preflight. Every failure kind the client can record is
  `timeout`, `network`, `size_exceeded`, `throttle`, `retryable_http`,
  `permanent`, `bad_json`, plus the client-side `ledger_skip` that is counted in
  metrics only.
- **The cache is zstd-compressed, keyed by URL, with a selective TTL.** Payloads
  are stored in a `payload BLOB` compressed with the `zstandard` library
  (`cache.py:133-171`) and decompressed on read (`cache.py:117-131`). A
  compressor and decompressor are cached per thread (`cache.py:20-36`), so
  multi-threaded use does not construct one per call. Expiry is set only for
  URLs whose path ends in `.json` and only when `json_ttl_s > 0`; every other
  path gets `expires_at = NULL` and never expires (`cache.py:47-60`). The
  default TTL is `DEFAULT_CACHE_JSON_TTL_S = 90 * 24 * 60 * 60` seconds
  (`foundation/runtime/settings/paths.py:19`). The SQLite connection runs in WAL
  mode with `busy_timeout=5000` (`cache.py:82-83`), which is what makes it safe
  for concurrent workers.
- **With no `cache_dir` there is no cache and no ledger.** `make_cache_store`
  returns `None` for `cache_dir=None` (`cache.py:244-249`), and every cache and
  ledger call in the client is guarded by `if self._cache` / `is not None`
  (`client.py:120-122,207,225,244,311`). The client works with caching fully
  disabled; it simply loses the failure-history preflight too.
- **`peek_cache` never costs a rate slot.** It reads the store and counts a
  `cache_hit` metric, and is the probe the broker uses to answer a request from
  disk without pacing (`client.py:130-135`).
- **`get_json_ex` preserves acquisition provenance.** It returns
  `(payload, byte_count, sha256_of_raw_bytes)` from the *unparsed* body
  (`client.py:349-373`), so the submissions dataset can record how many bytes it
  received and their digest. `get_json` discards both
  (`client.py:330-347`). Both refuse a non-object JSON root with
  `PermanentHttpError`, and a `JSONDecodeError` is recorded as a permanent
  `bad_json` failure.
- **An optional response size cap exists and is off by default.**
  `max_response_bytes=None` means unlimited; when set, a 200 response larger than
  the cap is recorded as a permanent `size_exceeded` failure and raises
  `ResponseTooLargeError` (`client.py:240-254`). `ResponseTooLargeError`
  subclasses `PermanentHttpError` (`errors.py:28-29`), so a caller that only
  catches the base class still handles it.
- **The transport has no transport-level retries.** The mounted `HTTPAdapter` is
  configured with `Retry(total=0, connect=0, read=0)` and a pool of 16
  connections (`client.py:85-91`). All retrying is `SecHttpClient`'s own loop, so
  a request is not silently replayed beneath the metrics and the ledger.

**Obligations callers place on this package**

- Supply a `User-Agent` that contains `@`, and ideally a real contact address.
  A blank or malformed value is rejected at construction.
- Close the underlying `SqlCache` when the client is done. Nothing registers an
  `atexit` hook; `SqlCache.close()` (`cache.py:238-241`) is the caller's job, and
  leaving WAL files open is how a cache directory becomes undeletable.
- Tolerate the exception taxonomy: `PermanentHttpError` (do not retry),
  `RetryExhausted` (the budget is spent), and `ResponseTooLargeError` (a
  `PermanentHttpError`). `client.py` raises `RetryExhausted` for timeout,
  network, 429, and retryable 5xx exhaustion alike. The trailing
  `raise RetryExhausted(url, "exhausted all retry attempts")` (`client.py:323`)
  is a fallthrough for the empty-range case: it fires only when `max_retries` is
  negative, since every other path out of the loop returns or raises first.
- Read `metrics.snapshot()` rather than reaching at the individual counters, if
  a consistent view matters; each field is read under the lock in `snapshot()`
  (`metrics.py:58-71`), but direct attribute reads are individually guarded and
  individually stale.
- Accept that `HttpMetrics.record_status` increments `responses_2xx` for *every*
  status it records, including failures (`metrics.py:30-38`). The name is
  misleading; `status_counts` is the field to trust.

## Public surface

- `SecHttpClient` — the client. `client.py`. Accessors `get_bytes`, `get_text`,
  `get_json`, `get_json_ex`, `peek_cache`, `load_failure_entry`; constructor
  takes `rate_limiter`, `retry_policy`, `timeout_s`, `cache_dir`, `json_ttl_s`,
  `metrics`, `max_failure_attempts`, `ignore_failure_history`,
  `max_response_bytes`, and `session_factory`.
- `SecHttpClient.from_settings` — build a client from a resolved `SecSettings`.
  `client.py`.
- `default_headers` — the fixed SEC header set, with the `@` guard.
  `client.py`.
- `RateLimiter` — `acquire()`, `signal_throttle(retry_after_s)`,
  `signal_network_error()`, `snapshot()`, and the `interval` property.
  `rate_limit.py`.
- `DEFAULT_MIN_INTERVAL_S`, `MAX_INTERVAL_S`, `THROTTLE_MULTIPLIER`,
  `RECOVERY_QUIET_S`, `RECOVERY_DECAY`, `RETRY_AFTER_CAP_S` — the pacing
  vocabulary. `rate_limit.py`. `rate_limit.py` also re-exports
  `DEFAULT_RATE_LIMIT_RPS`, which is defined in
  `foundation.runtime.settings.sec`.
- `RetryPolicy` — `classify(status_code)`, `delay(attempt, retry_after_s)`;
  fields `max_retries`, `backoff_base_s`, `backoff_cap_s`, `jitter`. `retry.py`.
- `BACKOFF_BASE_S`, `BACKOFF_CAP_S` — `0.5` and `30.0`. `retry.py`.
  `retry.py` also re-exports `DEFAULT_MAX_RETRIES` and `DEFAULT_TIMEOUT_S` from
  `foundation.runtime.settings.sec`.
- `SqlCache` — `get`, `put`, `load_failure_entry`, `record_failure`,
  `clear_failure`, `close`; attribute `db_path` (the file is
  `cache_dir/responses.sqlite`, `cache.py:74`). `cache.py`.
- `make_cache_store` — returns a `SqlCache`, or `None` when `cache_dir is None`.
  `cache.py`.
- `HttpMetrics` — `record_attempt`, `record_status`, `record_failure`,
  `record_retry`, `record_cache_hit`, `snapshot`. `metrics.py`.
- `PermanentHttpError` — non-retryable failure; carries `url`, `reason`,
  `status_code`. `errors.py`.
- `RetryExhausted` — retry budget spent; carries `url`, `reason`,
  `status_code`. `errors.py`.
- `ResponseTooLargeError` — a `PermanentHttpError` subclass raised when
  `max_response_bytes` is exceeded. `errors.py`.
- `client.py` re-exports `PermanentHttpError`, `ResponseTooLargeError`, and
  `RetryExhausted` in its own `__all__` (`client.py:376-382`) even though it
  imports rather than defines them. Import the error hierarchy from
  `edgar_sec.infra.sec_http.errors`, which is where it is owned.

## Tests

- `tests/infra/sec_http/test_cache.py` (62 loc)
- `tests/infra/sec_http/test_client.py` (104 loc) — headers, CIK URL padding
  (which is a `domain.sec_urls` concern asserted here), the cache probe and its
  hit metric, and `get_json_ex` provenance including the non-object-root refusal.
  The scripted session is injected through `session_factory`
  (`test_client.py:83`).
- `tests/infra/sec_http/test_rate_limit.py` (26 loc)
- `tests/infra/sec_http/test_retry.py` (33 loc)

`metrics.py` and `errors.py` have no mirrored test module. `HttpMetrics` is
asserted indirectly (`test_client.py:49` checks `cache_hits`), and the error
types are asserted through `test_client.py` and
`tests/infra/broker/test_broker.py`. The failure-ledger *preflight* —
`_preflight_skip` raising `PermanentHttpError` from a persisted
`url_failures` row — is not covered by any test in this package.

## Deliberate gaps

- **No in-flight concurrency cap.** v1 had a semaphore-bounded transport with an
  explicit concurrency policy, documented at 8 requests in flight independent of
  the 4 RPS start policy. v2's `SecHttpClient` contains no `Semaphore`: it
  paces by reserving slots in `RateLimiter` but never limits how many threads may
  be inside a request simultaneously. The only cap in the infra layer is
  `threading.Semaphore(max_connections)` in `broker/sec_broker.py:97`. A caller
  that constructs one client per thread with `min_interval_s=0` gets no ceiling
  at all. Nothing enforces broker-mediated routing either, so this is a
  discipline the architecture relies on rather than a guarantee the code makes.
- **No read-only cache reader.** `cache.py` offers `SqlCache` and
  `make_cache_store` only. There is no `SqlCacheReader` or any fail-open view,
  so a tool that wants to inspect cached responses without risking a write must
  open the same writable object. The fail-open pattern does exist elsewhere in
  the layer — `storage/payload_store.PayloadStoreReader` is exactly that shape —
  so its absence here is a genuine omission rather than a rejection of the idea.
- **No direct control over the cache file from a `SecHttpClient`.** The client
  resolves `Path(cache_dir).resolve()` and passes it to `make_cache_store`
  (`client.py:74-75`); the resulting `SqlCache` is reachable only through the
  private `_cache` attribute, which `test_client.py:47` in fact pokes. There is
  no public accessor.
- **No `Retry-After` handling for a non-digit header.** The parse requires
  `retry_after_hdr.isdigit()` (`client.py:265-269`), so the HTTP-date form of
  `Retry-After` is ignored and computed backoff is used instead. The value is
  also not honoured for the *next* request unless it reaches `signal_throttle`,
  which it does, but the cap of `RETRY_AFTER_CAP_S = 120.0` means a server asking
  for longer is ignored.
- **No response size cap by default.** `max_response_bytes` defaults to `None`
  (`client.py:61,78`), so an unexpectedly large archive file is read fully into
  memory before anything notices. The broker, which constructs its own client
  with no arguments (`broker/sec_broker.py:92`), inherits that default and
  offers no way to pass a limit.
- **No streaming download.** `get_bytes` reads `response.content`, which
  `requests` has already buffered in full (`client.py:235`). A caller wanting
  bounded memory must set `max_response_bytes` so the check happens *after* the
  full body is in memory, which bounds acceptance but not the read.
- **No redirect, proxy, or TLS configuration.** The session is mounted for
  `https://` and `http://` with a bare `HTTPAdapter` (`client.py:84-91`); there
  is no retry-after-redirect policy, no proxy, and no certificate handling.
- **No `Retry-After` for 503, and 503 is retried generically.** `classify` sends
  every 5xx to `retry` (`retry.py:36-37`) with no special handling of 503's
  `Retry-After`, unlike 429.
- **Metrics are in-process and lost on exit.** `HttpMetrics` is a plain
  dataclass with a lock (`metrics.py:9-23`); nothing persists or aggregates
  across processes. A multi-process run's totals exist only in the broker
  process, and `SecBrokerClient.metrics` returns `None`
  (`broker/sec_broker.py:279-281`).
- **`HttpMetrics.responses_2xx` counts every recorded response**, not just
  successful ones (`metrics.py:33`). The field name says 2xx; the increment is
  unconditional. Use `status_counts` for anything that matters.
- **The ledger is a per-cache-directory blacklist, not a shared one.** The
  `url_failures` table lives in `cache_dir/responses.sqlite`, so a run with a
  fresh cache directory has no failure history at all, and two runs with
  different `cache_dir` values never see each other's permanent failures. The
  module docstring calls the ledger a cross-run mechanism; that holds only when
  the same cache directory is reused.
- **No test for the ledger preflight.** `_preflight_skip` (`client.py:144-163`)
  is the mechanism that stops a run paying for the same 404 repeatedly, and no
  test in this package constructs a persisted `url_failures` row and asserts the
  short-circuit. `test_cache.py` covers the table, not the decision built on it.
- **The broker is the missing multi-process story, and it is thin.** See
  `edgar_sec/infra/broker/README.md`: no CLI, no lifecycle management, no
  token accounting, and `managed_broker` has no consumer outside the tests.
