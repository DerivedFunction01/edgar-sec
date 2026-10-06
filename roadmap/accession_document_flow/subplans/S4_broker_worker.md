# S4 — Broker-Backed Inventory Worker and Bounded Process Pool

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S4**.
- Status: execution-layer design; bounded worker pool, broker lifecycle, and
  coordinator-owned publication.
- Depends on: S1 cohort contract, S2 index fixture store, S3 parser.
- Non-blocking: S5 snapshot publication.

## Objective

Execute one accession per process-pool task: fetch its `-index.html` through a
shared SEC broker, parse the response, and return a typed outcome. Bound work by a
memory-derived process budget, keep HTTP and artifact writing out of workers, and
publish only after the complete cohort is validated.

## Contract: `SecBrokerClient`

The only HTTP seam visible to workers. Injected by the coordinator; workers never
instantiate their own `SecHttpClient`.

```text
class SecBrokerClient:
    def fetch_index(self, index_url) -> IndexPageEnvelope
    def request(self, url) -> IndexPageEnvelope
```

`IndexPageEnvelope` carries `accession`, `index_url`, `response_sha256`,
`response_size`, and `html_bytes`. The broker owns the settings-backed
`SecHttpClient`, its cache, rate limiter, retries, and failure ledger. The broker's
rate limiter is authoritative for SEC requests; the process pool only scales CPU
work and shares that limiter.

## Worker lifecycle

1. The coordinator validates the complete cohort before any request and starts one
   `SecBroker`/`managed_broker` for the run.
2. A bounded `ProcessPoolExecutor` worker receives an accession and index URL,
   fetches through `SecBrokerClient`, hashes the response, parses both index
   tables via `parse_html_index()`, and returns a typed `IndexParseOutcome` plus
   page bytes when fixture capture is requested.
3. The coordinator alone writes fixture DB rows, Parquet, manifests, and pointers in
   stable accession order. It retains no full-cohort response list and calls
   `reclaim()` at bounded result intervals.
4. A failed fetch or unrecognized page is an explicit error; it never becomes an
   empty inventory.

## Worker budget and scaling

- Use `derive_resources().workers`; its default worker factory calls
  `auto_worker_count` with cgroup-aware available memory, a worker-memory estimate,
  and a safety fraction. The audit measures index-page parse cost and response
  memory to tune the worker-memory setting.
- Bound submitted-but-uncollected tasks by the resolved worker budget, counting
  broker, IPC, response-byte, and parser-DOM memory.
- No hardcoded worker counts.

## Coordinator invariants

- No child opens SQLite or writes a published artifact.
- One failed accession does not silently become empty; typed errors propagate.
- Fixture capture is opt-in from the coordinator; it does not change the worker's
  output shape.

## Tests

- Fake broker success and failure.
- Picklable worker setup and results.
- All worker requests aggregate through one broker.
- Bounded in-flight responses under a fixed budget.
- Stable result order independent of task completion order.
- One failed accession does not become empty.
- Worker exception cleanup.
- No child-side writes.
- All accessions validated before the first request.
- No hardcoded worker count; the pool derives its size from resources.
- `reclaim()` called at bounded intervals.
- Fixture capture opt-in does not alter normal output.
- One parser exception does not erase sibling results.

## Acceptance criteria

The coordinator owns a settings-backed broker lifecycle and a memory-derived
`ProcessPoolExecutor` whose workers fetch one index page through `SecBrokerClient`
and parse it; submitted tasks are bounded by the worker budget, page errors are
typed, and fixture/Parquet writing is coordinator-owned. No worker creates its own
HTTP client or writes artifacts.
