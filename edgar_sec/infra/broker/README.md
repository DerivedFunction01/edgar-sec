# `edgar_sec/infra/broker` — one SEC client, shared by every worker process

This package exists so that N worker *processes* behave as one polite client.
Each worker talks to a Unix-domain-socket server over a length-prefixed JSON
protocol; the server owns the single `SecHttpClient`, and therefore the single
rate limiter, response cache, failure ledger, and metrics collector.

## Purpose

A worker in a process pool cannot share a Python object with its siblings, so
per-process rate limiting multiplies the aggregate request rate by the pool size
— the failure the roadmap calls out for multi-process SEC acquisition
(`v2_refactor_roadmap.md` §3.3). `SecBroker` moves the client out of the worker
and into a server, which makes the aggregate pace a property of the host rather
than of the pool.

What this package is not: it does not rate-limit anything itself, and it is not a
token bucket. See *Deliberate gaps*.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `sec_broker.py` | `SecBroker` (server) and `SecBrokerClient` (worker side), the length-prefixed frame codec, and the healthcheck sentinel (361 loc). |
| `daemon.py` | `managed_broker()`: run a broker on a background thread for the duration of a `with` block (61 loc). |
| `__init__.py` | Docstring only (1 loc). No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **One `SecHttpClient` per host.** `SecBroker.__init__` builds a `SecHttpClient`
  if none is injected (`sec_broker.py:92`), and that single instance serves every
  connection. A worker that uses `SecBrokerClient` never constructs its own
  client, so the aggregate pace is the broker's `RateLimiter` and nothing else.
  `pipelines/document_storage/fetching.py` is the production consumer.
- **A warm-cache probe bypasses the rate limiter entirely.** `SecBroker.fetch`
  calls `self._client.peek_cache(archive_url)` before taking the semaphore
  (`sec_broker.py:120-131`), and `peek_cache` reads the store without consuming
  a request slot (`sec_http/client.py:130-135`). A document already on disk
  therefore costs no SEC request and no pacing delay. `force_refresh=True` skips
  the probe.
- **Connection concurrency is bounded.** `threading.Semaphore(max_connections)`,
  default 32, clamped to at least 1 (`sec_broker.py:91,97`). This is the *only*
  in-flight concurrency cap in the infra layer — `SecHttpClient` has no
  semaphore of its own.
- **Fetch errors come back as data, not as exceptions.** `SecBroker.fetch`
  catches `PermanentHttpError`, `ResponseTooLargeError`, and `RetryExhausted`
  explicitly and then any other `Exception` (`sec_broker.py:141-152`), always
  returning `{"status": "failed", "error": ..., "payload_length": 0}`. A worker
  that gets a 404 back decides what to do; it does not have to distinguish
  "broker died" from "SEC said no". `SecBrokerClient.fetch` mirrors this and adds
  a two-attempt socket-level retry with a connection reset between attempts
  (`sec_broker.py:327-338`).
- **The socket is a thread-local resource.** `SecBrokerClient._get_socket`
  keeps one connected socket per thread in a `threading.local`
  (`sec_broker.py:283-293`), and `_reset_socket` drops it on error, so a
  broken connection never poisons a sibling thread.
- **The client is picklable.** `__getstate__`/`__setstate__` reduce it to
  `{"socket_path": ...}` and rebuild the thread-local on the far side
  (`sec_broker.py:272-277`), so a `SecBrokerClient` can be handed to a
  `ProcessPoolExecutor` worker. `tests/infra/broker/test_broker.py:94-101` pins
  this.
- **Heap is reclaimed on a byte budget.** `_note_bytes` accumulates payload
  bytes served and returns `True` once the running total crosses
  `_RECLAIM_BYTES_THRESHOLD = 512 * 1024 * 1024`; the caller then invokes
  `foundation.runtime.memory.reclaim()` (`gc.collect()` + `malloc_trim(0)`)
  outside the semaphore (`sec_broker.py:34,124-125,156-158,166-172`). This is
  AGENTS.md §2.2 applied at a bounded batch interval, rather than per request.
- **Liveness is checked before use.** `managed_broker` polls
  `client.fetch(HEALTHCHECK_URL)` every 50 ms until
  `ready_timeout_s` (default 5.0) elapses, and raises `RuntimeError` naming the
  socket path if the broker never answers (`daemon.py:37-52`). It then calls
  `server.stop()` and joins the thread for up to 2.0 s on that failure path.
- **Shutdown is bounded.** On exit from the `with` block, `managed_broker` calls
  `stop()` and joins the serving thread with a 3.0 s timeout
  (`daemon.py:54-58`). `SecBroker.serve` unlinks the socket file in its `finally`
  (`sec_broker.py:250-254`), and `stop()` is safe to call from another thread
  because it only sets an `Event` and closes the listening socket.

**Obligations callers place on this package**

- Callers must hold the `SecBroker` to stop it. `stop()` is an instance method
  and there is no signal handler, PID file, or external lifecycle command; a
  broker started by some other means is not stoppable from outside the process.
- Workers must use `SecBrokerClient`, not their own `SecHttpClient`, if the
  aggregate pace is to hold. Nothing in the code enforces this routing; it is a
  contract, not a check.
- The `request_id` and `archive_url` fields of a request frame must both be
  strings. Anything else is answered with a `failed` status rather than raising
  (`sec_broker.py:186-193`).
- Frame sizes are trusted. `_recv_frame` rejects a negative length
  (`sec_broker.py:65-66`) but sets no upper bound, and the read timeout is
  `_READ_TIMEOUT_S = 30.0` per socket.

## Public surface

- `SecBroker` — the socket server; owns one `SecHttpClient` and serves fetch
  RPCs. `sec_broker.py`.
- `SecBrokerClient` — the worker-side client; picklable, thread-local socket,
  two socket-level attempts. `sec_broker.py`.
- `BrokerError` — transport and framing failure. `sec_broker.py`.
- `BrokerRequestError` — a broker-reported failure for one archive URL.
  `sec_broker.py`.
- `PROTOCOL_VERSION` — the wire protocol integer, `1`. `sec_broker.py`. Declared
  but not currently read by either endpoint: framing is a bare
  `!I` length header plus JSON (`sec_broker.py:29-30`), so there is no
  version negotiation on the wire.
- `HEALTHCHECK_URL` — the sentinel URL `"healthcheck://broker"` that
  `SecBroker.fetch` answers locally without touching the client
  (`sec_broker.py:33,113-119`), and that `managed_broker` uses as its readiness
  probe. `sec_broker.py`.
- `managed_broker` — context manager hosting a live broker for a block.
  `daemon.py`.

## Tests

- `tests/infra/broker/test_broker.py` (101 loc) — three tests: broker lifecycle
  and fetch including a warm-cache hit that must not call `get_bytes`; ten
  concurrent threads against one broker with `max_connections=8`; and pickle
  round-trip of `SecBrokerClient`.

## Deliberate gaps

- **There is no broker CLI.** v1 shipped `.v1/defs/sec_http/broker_cli.py`
  (340 loc). v2 has no `__main__.py`, no argparse entry point, and no console
  script anywhere in `broker/`. Starting a broker means writing code that calls
  `SecBroker(...).serve()` or using `managed_broker()`. The consequence is
  concrete: a long-lived broker that outlives its creating process has no
  supported way to be started, and one that crashes cannot be restarted without
  a supervising process that does not exist yet.
- **It is not a token bucket, and it holds no tokens.** The roadmap describes
  this component as a "Unix-socket token bucket" and a "4 RPS central token
  bucket" in `v2_refactor_roadmap.md` §1.2, §3.3, §8 and in
  `roadmap/refactor_v2/phase_2_5.md`. No token accounting exists. The pacing
  lives in `sec_http/rate_limit.py`: `RateLimiter.acquire()` reserves the next
  request slot under a lock and returns the delay, and the caller sleeps outside
  the lock. What this package adds is *placement* — the limiter is inside a
  single process, so a pool cannot multiply it. The word "token bucket" is a
  standing misnomer, not a missing feature.
- **No warm-cache probe result is distinguishable from a live fetch.** A cache
  hit and a fresh `get_bytes` both come back as `{"status": "ok", ...}` with no
  flag. The behaviour is observable only by instrumenting the client.
- **`SecBrokerClient.metrics` always returns `None`** (`sec_broker.py:279-281`).
  A worker cannot read the shared `HttpMetrics`, which live on the server's
  client. Progress reporting has to come from the broker process, not the worker.
- **`max_connections` bounds connections, not request rate.** The semaphore is
  acquired around `get_bytes` (`sec_broker.py:132-155`), so it limits how many
  fetches are in flight simultaneously; the RPS ceiling comes from
  `RateLimiter` inside the client. Raising `max_connections` does not raise the
  request rate.
- **No `max_response_bytes` reachability from this package.** The size cap is a
  `SecHttpClient` constructor argument (`sec_http/client.py:61,78`); a broker
  that builds its own client with no arguments gets the default of `None`, i.e.
  no cap. The broker never forwards a size limit in `fetch`.
- **The socket file is not cleaned up on a hard kill.** `serve()` unlinks it in a
  `finally`, which covers `stop()` and normal exceptions, but not `SIGKILL`.
  `serve()` does unlink a stale socket before binding (`sec_broker.py:224-227`),
  so the next start recovers; the failure mode is limited to a leftover file.
- **No per-request fairness or prioritisation.** Connection handling is
  thread-per-connection (`sec_broker.py:241-243`), so ordering is whatever the
  OS accept queue produces. There is no queue, no admission control, and no
  notion of a more urgent document.
- **Health checking is a shared-code shortcut, not a liveness probe of the
  client.** `HEALTHCHECK_URL` short-circuits inside `fetch` before the client is
  consulted (`sec_broker.py:113-119`), so a broker whose `SecHttpClient` is
  broken still passes `managed_broker`'s readiness check. It proves the accept
  loop is running, not that SEC is reachable.
- **`managed_broker` has no consumer outside the tests.** It is the only
  lifecycle helper, and `pipelines/document_storage/fetching.py` constructs
  `SecBroker`/`SecBrokerClient` directly. `managed_broker` is the tested path;
  whatever the pipeline does is not covered by this package's test module.
- **No test module for `daemon.py` on its own.** `managed_broker` is exercised
  as the harness inside `test_broker.py`; the readiness-timeout and
  `RuntimeError` branch (`daemon.py:47-52`) is not tested.
