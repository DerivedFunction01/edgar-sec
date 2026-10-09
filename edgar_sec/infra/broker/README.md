# `edgar_sec/infra/broker` — one SEC client, shared by every worker process

N worker *processes* cannot share a Python object, so per-process rate limiting
multiplies the aggregate request rate by the pool size. `SecBroker` puts the
single `SecHttpClient` — and therefore the single rate limiter, response cache,
failure ledger, and metrics collector — behind a Unix-domain-socket server
speaking a length-prefixed JSON protocol. Workers fetch; the server paces.

## Purpose

Make the aggregate pace a property of the host rather than of the pool. The
server owns the client; `SecBrokerClient` on the worker side never constructs
its own. See *Deliberate gaps* for what this package is not.

## Contracts

**Guarantees**

- **One `SecHttpClient` per host.** `SecBroker.__init__` builds one if none is
  injected, and that instance serves every connection.
- **A warm-cache hit bypasses the rate limiter entirely.** `SecBroker.fetch`
  calls `peek_cache` *before* taking the semaphore, and `peek_cache` reads the
  store without consuming a request slot. A document already on disk costs no
  SEC request and no pacing delay; `force_refresh=True` skips the probe.
- **Connection concurrency is bounded.** `threading.Semaphore(max_connections)`,
  default 32, clamped to at least 1 — the only in-flight concurrency cap in the
  infra layer. `SecHttpClient` has no semaphore of its own.
- **Fetch errors come back as data.** `SecBroker.fetch` catches
  `PermanentHttpError`, `ResponseTooLargeError`, and `RetryExhausted`, then any
  other `Exception`, always returning
  `{"status": "failed", "error": ..., "payload_length": 0}`. A worker that gets a
  404 decides what to do; it never has to distinguish "broker died" from "SEC
  said no". `SecBrokerClient.fetch` mirrors this and adds a two-attempt
  socket-level retry with a socket reset between attempts.
- **The socket is thread-local.** `SecBrokerClient` keeps one connected socket
  per thread in a `threading.local` and drops it on error, so a broken
  connection never poisons a sibling thread.
- **The client is picklable.** `__getstate__`/`__setstate__` reduce it to
  `{"socket_path": ...}` and rebuild the thread-local on the far side, so it can
  be handed to a `ProcessPoolExecutor` worker.
- **Heap is reclaimed on a byte budget.** `_note_bytes` accumulates payload
  bytes served; once the running total crosses
  `_RECLAIM_BYTES_THRESHOLD = 512 MiB` the caller runs
  `foundation.runtime.memory.reclaim()` outside the semaphore. This is
  AGENTS.md §2.2 applied at a bounded batch interval, not per request.
- **Liveness is checked before use, and shutdown is bounded.** `managed_broker`
  polls `client.fetch(HEALTHCHECK_URL)` every 50 ms until `ready_timeout_s`
  (default 5.0) elapses, raising `RuntimeError` naming the socket path if the
  broker never answers; it then stops the server and joins for up to 2.0 s. On
  normal exit from the `with` block it stops and joins for 3.0 s. `serve()`
  unlinks the socket file in a `finally`, and `stop()` only sets an `Event` and
  closes the listening socket, so it is safe to call from another thread.

**Obligations callers place on this package**

- Keep the `SecBroker` to stop it. `stop()` is an instance method; there is no
  signal handler, PID file, or external lifecycle command, so a broker started by
  some other means is not stoppable from outside the process.
- Workers must route through `SecBrokerClient` for the aggregate pace to hold.
  Nothing enforces this routing; it is a contract, not a check.
- `request_id` and `archive_url` in a request frame must both be strings;
  anything else is answered with a `failed` status rather than raising.
- Frame sizes are trusted. `_recv_frame` rejects a negative length but sets no
  upper bound, and the per-socket read timeout is `_READ_TIMEOUT_S = 30.0`.

## Deliberate gaps

- **No broker CLI or supervisor.** A broker is started only by writing
  `SecBroker(...).serve()` or using `managed_broker()`. A long-lived broker that
  outlives its creating process has no supported way to be started, and one that
  crashes cannot be restarted without a supervising process that does not exist
  yet.
- **It is not a token bucket and holds no tokens.** No token accounting exists
  here. Pacing lives entirely in `sec_http/rate_limit.py`,
  where `RateLimiter.acquire()` reserves the next request slot under a lock and
  returns the delay for the caller to sleep outside it. What this package adds
  is *placement* — the limiter is in one process, so a pool cannot multiply it.
- **`BrokerRequestError` is dead.** It is defined and listed in `__all__`, but
  no path raises it: framing failures raise the base `BrokerError`, and a
  broker-reported failure comes back as a `{"status": "failed"}` dict.
- **A warm-cache hit is indistinguishable from a live fetch.** Both come back
  `{"status": "ok", ...}` with no flag; the difference is observable only by
  instrumenting the client.
- **`SecBrokerClient.metrics` always returns `None`.** The shared `HttpMetrics`
  lives on the server's client, so progress reporting has to come from the
  broker process, not the worker.
- **`max_connections` bounds connections, not request rate.** The semaphore is
  held around `get_bytes`, so it limits how many fetches are in flight; the RPS
  ceiling comes from `RateLimiter` inside the client. Raising it does not raise
  the request rate.
- **No `max_response_bytes` reachability from here.** The size cap is a
  `SecHttpClient` constructor argument; a broker that builds its own client with
  no arguments gets the default of `None` — no cap — and `fetch` never forwards a
  size limit.
- **The socket file survives a hard kill.** `serve()` unlinks it in a `finally`,
  which covers `stop()` and ordinary exceptions but not `SIGKILL`. It does
  unlink a stale socket before binding, so the next start recovers; the failure
  mode is limited to a leftover file.
- **No per-request fairness or prioritisation.** Connection handling is
  thread-per-connection, so ordering is whatever the OS accept queue produces.
  There is no queue, no admission control, and no notion of a more urgent
  document.
- **The health check is a shared-code shortcut, not a liveness probe of the
  client.** `HEALTHCHECK_URL` short-circuits inside `fetch` before the client is
  consulted, so a broker whose `SecHttpClient` is broken still passes
  `managed_broker`'s readiness check. It proves the accept loop is running, not
  that SEC is reachable.
- **`managed_broker` has no consumer outside the tests.** It is the only
  lifecycle helper, and nothing outside `daemon.py` constructs a `SecBroker`;
  `pipelines/document_storage/fetching.py` builds `SecBrokerClient` directly.
  `daemon.py` also has no mirrored test module of its own — `managed_broker` is
  only the harness inside `test_broker.py`, and its readiness-timeout
  `RuntimeError` branch is untested.
