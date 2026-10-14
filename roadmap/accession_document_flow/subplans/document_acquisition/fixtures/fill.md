# `acquisition fixture fill`

## Purpose and status

Fetch selected parser inputs from the fixture's pinned S6 plan into an immutable SQLite
fixture. Fill is independent of acquisition-run projection and S9 run state. Review
generation can then invoke the current parser handlers offline.

## CLI and operator

```text
acquisition fixture fill --fixture <id> --allow-network [--limit <targets>]
```

The CLI requires `--allow-network`; the interactive console asks separately and defaults
to no. Fill revalidates the fixture's published S6 plan pin, applies the configured finite
response-byte limit, and fetches up to the requested number of uncaptured executable
targets. Repeated fills skip targets already stored in the fixture.

```python
def capture_fixture_plan(
    fixture_id: str,
    *,
    paths: AcquisitionPaths,
    max_body_bytes: int,
    transport: AcquisitionTransport,
    limit: int | None = None,
) -> FixturePlanCaptureResult: ...
```

## Capture contract

- Revalidate the pinned S6 bundle and refuse a changed plan identity before requests.
- Fetch only executable target rows from the pinned work-order projection; do not create
  an S9 run, run-state database, attempt, processing receipt, or staged run body.
- Follow inventory-selected target URLs directly. For a catalog-direct
  `exact_form_with_lazy_index` target without an inventory entry, fetch the accession
  index, select the pinned form through the shared index parser/selector, and store the
  verified index page in the fixture. Reuse that page for later targets for the accession;
  validate a selected bundle child against the indexed form.
- Store selected parser-body bytes, plan/capture metadata, and lazy-index provenance in
  Zstandard-compressed SQLite BLOBs. Do not retain ordinary HTTP responses, bundle
  containers, or failed request histories.
- Report failed target counts by failure code. Failed targets are not marked captured and
  can be retried by another fill.
- Enforce the configured response bound on index, source, and selected body bytes.

## Deliberate gaps

- **Request history**: Failed HTTP attempts and ordinary source-response bodies remain
  outside the fixture; only a lazy index required for selection is retained.
- **Production use**: Fixture parser results are diagnostic evidence, not route-budget
  approval or publisher input.

## Tests

Offline tests cover plan-only fill without an acquisition run, direct and bundle-selected
inputs, exact-form index resolution, one-time index caching, response limits, immutable
body storage, and offline parser review.
