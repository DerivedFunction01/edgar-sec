"""Shared index fixtures and transport fake for acquisition execution tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse

ACCESSION = "0000320193-20-000096"
ACCESSION_COMPACT = ACCESSION.replace("-", "")
INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{ACCESSION_COMPACT}/{ACCESSION}-index.html"
)
BUNDLE_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{ACCESSION_COMPACT}/{ACCESSION}.txt"
)
INDEX = (
    b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
    b"<th>Document</th><th>Type</th><th>Size</th></tr>"
    b"<tr><td>2</td><td>Annual report</td><td><a href='report.htm'>report.htm</a>"
    b"</td><td>10-K</td><td>12</td></tr></table>"
)
UNLINKED_INDEX = (
    b"<table summary='Document Format Files'><tr><th>Seq</th><th>Description</th>"
    b"<th>Document</th><th>Type</th><th>Size</th></tr>"
    b"<tr><td>2</td><td>Annual report</td><td>not linked</td><td>10-K</td><td>12</td></tr>"
    b"<tr><td></td><td>Complete submission text file</td><td><a href='"
    + BUNDLE_URL.encode()
    + b"'>bundle</a></td><td></td><td>100</td></tr></table>"
)


class MemoryTransport:
    def __init__(
        self,
        responses: dict[str, bytes],
        digest_overrides: dict[str, str] | None = None,
        failures: dict[str, StreamFailure] | None = None,
    ) -> None:
        self.responses = responses
        self.digest_overrides = digest_overrides or {}
        self.failures = failures or {}
        self.calls: list[tuple[str, int]] = []
        self.closed = False

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        self.calls.append((url, max_response_bytes))
        validate_redirect(url)
        if url in self.failures:
            return self.failures[url]
        body = self.responses[url]
        path = Path(destination)
        path.write_bytes(body)
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=self.digest_overrides.get(url, hashlib.sha256(body).hexdigest()),
            byte_size=len(body),
            content_type="text/html",
            content_encoding=None,
            path=path,
        )

    def close(self) -> None:
        self.closed = True
