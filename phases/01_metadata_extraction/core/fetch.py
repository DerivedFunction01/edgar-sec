"""SEC client construction and one-CIK normalization helpers."""

from __future__ import annotations

from defs.sec_http import make_sec_http_client, resolve_sec_transport_profile

from .config import RunOptions
from .normalize import normalize_submissions
from .sec_client import SubmissionsClient


def build_client(options: RunOptions) -> SubmissionsClient:
    options.validate()
    http = make_sec_http_client(profile=resolve_sec_transport_profile())
    return SubmissionsClient(http=http)


def fetch_and_normalize(client: SubmissionsClient, target, snapshot_id: str) -> dict:
    from .application import utc_now_iso

    result = client.fetch_cik(target.cik_padded)
    common = {
        "cik_padded": target.cik_padded,
        "input_name": target.name,
        "snapshot_id": snapshot_id,
        "fetched_at": utc_now_iso(),
        "source_url": result.source_url,
        "historical_payloads": result.historical_payloads,
        "historical_errors": result.historical_errors,
        "response_sha256": result.response_sha256,
    }
    if not result.fetched_ok:
        common.update(
            {"byte_count": 0, "historical_payloads": [], "response_sha256": ""}
        )
        common["historical_errors"] = [
            result.terminal_error() or "unknown fetch failure"
        ]
        return normalize_submissions({}, **common)
    common["byte_count"] = result.byte_count
    return normalize_submissions(result.payload, **common)
