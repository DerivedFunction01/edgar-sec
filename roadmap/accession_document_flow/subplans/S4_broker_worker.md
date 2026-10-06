# S4 — Broker-Backed Inventory Worker and Bounded Process Pool

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S4**.
- Status: execution-layer design; bounded worker pool, broker lifecycle, and
  coordinator-owned publication.
- Depends on: S1 cohort contract, S2 index fixture store, S3 parser.
- Non-blocking: S5 snapshot publication, S6 target planning.

## Objective

Execute one accession per process-pool task: fetch its `-index.html` through a
shared SEC broker, parse the response, and return a typed outcome. Bound work by a
memory-derived process budget, keep HTTP and artifact writing out of workers, and
publish only after the complete cohort is validated.

## Discovery boundary

S4 is strictly an index discovery and parsing engine:

- S4 fetches and parses `-index.html` pages for unindexed accessions.
- S4 **never** synthesizes `InventoryEntry` rows from catalog hints or filing
  summaries. Entries are strictly factual rows observed in `Document Format Files`
  or `Data Files`.
- S4 does not infer form capability rules or bypass decisions. If an explicit
  catalog-direct target path is used in S6, it operates as an independent planning
  source adapter outside of S4.

## Contract: `SecBrokerClient`

The only HTTP seam visible to workers. Injected by the coordinator; workers never
instantiate their own `SecHttpClient`.

```python
class SecBrokerClient:
    def fetch_index(
        self, accession: AccessionNumber, index_url: str
    ) -> IndexPageEnvelope | IndexFetchFailure: ...

@dataclass(frozen=True, slots=True)
class IndexFetchFailure:
    accession: AccessionNumber
    code: Literal["transport_error", "response_too_large"]
    retryable: bool
    detail: str
```

`IndexPageEnvelope` carries `accession`, `index_url`, `response_size`, and
`html_bytes`; S3 computes the digest from those exact bytes. The broker owns the
settings-backed `SecHttpClient`, its cache, rate limiter, retries, and failure
ledger. The broker's rate limiter is authoritative for SEC requests; the process pool
only scales CPU work and shares that limiter.

The broker enforces a configured maximum response-byte budget before parser
expansion and returns `response_too_large` rather than truncating a page. The
concrete budget limit is not fixed arbitrarily: it is derived after S0 empirical
response measurements and worker memory headroom. The transport must abort reading an
oversized body as soon as the limit breach is detected; it never returns partial bytes.

## Worker lifecycle and IPC memory

1. The coordinator validates the complete cohort before any request and starts one
   `SecBroker`/`managed_broker` for the run.
2. A bounded `ProcessPoolExecutor` worker receives an accession and index URL,
   fetches through `SecBrokerClient`, then parses both index tables via
   `parse_html_index(IndexPageInput(accession, index_url, html_bytes))`.
3. Worker return payload:
   - By default, the worker returns typed `IndexParseOutcome` (with parsed entries,
     bundle metadata, and digests) or `IndexFetchFailure`. Raw HTML bytes are **not**
     returned over IPC to minimize coordinator heap pressure.
   - When fixture capture is explicitly requested by the coordinator, the worker
     returns raw HTML bytes alongside the outcome.
4. The coordinator alone writes fixture DB rows, Parquet, manifests, and pointers in
   stable accession order. It retains no full-cohort response list and calls
   `reclaim()` at bounded result intervals.
5. A failed fetch or unrecognized page is an explicit error; it never becomes an
   empty inventory.

## Worker budget and scaling

- Worker pool sizing derives from `derive_resources().workers`; its default worker
  factory calls `auto_worker_count` with cgroup-aware available memory, worker-memory
  estimate, and a safety fraction.
- Submitted-but-uncollected tasks are strictly bounded by the worker budget.
- Memory budget calculation explicitly includes:
  - Broker response buffering in the parent process.
  - IPC serialization of response bytes into the child worker.
  - Worker HTML DOM and parsing expansion.
- Hardcoded worker counts or static memory ceilings are prohibited.

## Coordinator invariants

- No child worker opens SQLite or writes a published artifact.
- One failed accession does not silently become empty; typed errors propagate.
- Every recognized source-table row is retained; oversized responses fail explicitly
  and are never partially parsed or published.
- Fixture capture is opt-in from the coordinator; it does not change the worker's
  logical parsing outcome.

## Tests

- Fake broker success, 429 rate limit backoff, and transport failure.
- Picklable worker arguments and typed results.
- All worker requests aggregate through one shared broker instance.
- Bounded in-flight responses under a fixed memory budget.
- Stable result order independent of task completion order.
- One failed accession does not become empty or emit partial rows.
- A response exceeding the byte budget triggers `response_too_large` and stops reading;
  no partial rows are parsed or published.
- IPC payload verification: raw HTML is returned only when fixture capture is active.
- Worker exception cleanup: pool processes terminate cleanly on unexpected crash.
- No child-side writes to SQLite or Parquet.
- All accessions validated before the first request.
- Pool derives its size from resources without hardcoded worker limits.
- `reclaim()` called at bounded intervals.
- Fixture capture opt-in does not alter normal output.
- One parser exception does not erase sibling results.

## Acceptance criteria

The coordinator owns a settings-backed broker lifecycle and a memory-derived
`ProcessPoolExecutor` whose workers fetch one index page through `SecBrokerClient`
and parse it; submitted tasks are bounded by the worker budget, page errors are
typed, every row from accepted pages is retained, and fixture/Parquet writing is
coordinator-owned. An evidence-gated response-byte budget refuses an oversized page
without truncation. No worker creates its own HTTP client or writes artifacts.

