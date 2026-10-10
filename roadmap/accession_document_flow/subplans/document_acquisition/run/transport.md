# S9 bounded SEC transport

## Purpose and status

This is the large-response HTTP boundary used by `acquisition run`. It is design-only.
`SecHttpClient.get_bytes()` and the existing broker response still materialize payload
bytes, so S9 requires a lower-layer streaming extension before implementation.

## Proposed transport contract

The implementation belongs to `infra.sec_http` and its shared broker, not to the
pipeline runner. The application-facing operation is file-backed:

```python
@dataclass(frozen=True, slots=True)
class StreamedResponse:
    status_code: int
    requested_url: str
    final_url: str
    sha256: str
    byte_size: int
    content_type: str | None
    content_encoding: str | None

@dataclass(frozen=True, slots=True)
class StreamFailure:
    code: Literal[
        "http_not_found", "http_error", "timeout", "transport_error",
        "response_too_large", "unsafe_redirect", "empty_body",
    ]
    retryable: bool
    http_status: int | None

def stream_to_file(
    url: str,
    destination: Path,
    *,
    max_response_bytes: int,
    validate_redirect: Callable[[str], None],
) -> StreamedResponse | StreamFailure: ...
```

The broker retains ownership of the SEC session, rate limiter, retry policy, and
failure ledger. It returns typed metadata/path handles only; body bytes do not cross
process IPC. The stream helper must use the repository's injected `session_factory`
test seam and must not bypass the broker's shared pacing.

## Transfer sequence

1. Validate the original archive URL in the acquisition target validator.
2. Create an owner-generated temporary file under the run staging root.
3. Request a streamed response; disable automatic redirect following and validate
   every redirect against HTTPS, exact SEC archive host, and the same accession
   directory before following it.
4. Stream decoded response chunks to disk and incrementally hash/count them. A
   declared `Content-Length` may reject early but never replaces the actual byte
   count. Apply the finite configured limit after HTTP content decoding.
5. Flush and atomically adopt only a non-empty successful response. The committed
   response metadata records requested/final URL, status, MIME/encoding, digest, and
   observed byte count.

On timeout, 404, redirect refusal, transport failure, empty response, or size breach,
close the response and remove the partial file. A direct 404 is `http_not_found`,
not `not_filed`. Respect `Retry-After`, shared rate limiting, and configured SEC
retry/failure budgets. Preserve each attempt and do not retry terminal failures.

## Cache and retry boundary

The current SEC cache returns in-memory bytes. Until an equivalent file-backed cache
exists, streamed S9 body requests bypass that cache; they must not call `get_bytes()`
for a cache hit. Every live response's attempt provenance identifies the request and
final URL. Fixture replay does not construct or call this transport.

## Resource and failure contract

- The response-size setting is finite and validated before the HTTP session starts.
- Each in-flight response owns one staging file; active bodies and the submitted
  queue are bounded by the resource-derived worker plan.
- Partial bytes are never a successful body. A stream failure removes its temporary
  path, preserves any earlier attempt outcome, and leaves an eligible target
  retryable only when the typed transport policy says so.
- Generated output paths do not include accession, URL, filename, or response data.

## Tests

Fake streamed responses cover chunk boundaries, absent/false `Content-Length`, gzip
expansion, response exactly at/over the byte cap, empty body, timeout, cancellation,
404, `429`/`Retry-After`, permanent and retryable status codes, redirect within and
outside the accession, and cleanup after each failure. Tests assert incremental
digest equality and that the broker result contains no payload bytes.
