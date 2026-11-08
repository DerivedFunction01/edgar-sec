"""Feed-archives ingest command on the typed-options path."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime

from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.document_acquisition.feed_ingest import (
    build_http_client,
    ingest_feed_archives,
)
from edgar_sec.pipelines.document_acquisition.options import FeedIngestOptions


def cmd_feed_ingest(
    options: FeedIngestOptions,
    *,
    http_client: SecHttpClient | None = None,
    now: datetime | None = None,
) -> int:
    """Ingest the options' date range of Feed tarballs and publish inventory."""
    http = http_client or build_http_client()
    try:
        result = ingest_feed_archives(options, http=http, now=now)
    except (OSError, RuntimeError, ValueError) as error:
        payload = {"command": "feed ingest", "error": str(error), "status": "error"}
        if options.json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"feed ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        if http_client is None:
            http.close()

    payload = {"command": "feed ingest", "status": "ok", **asdict(result)}
    if options.json_output:
        print(json.dumps(payload, sort_keys=True, default=str))
    else:
        print(
            f"Feed ingest {options.start}..{options.end}: "
            f"units={result.units_considered} fetched={result.units_fetched} "
            f"from_store={result.units_from_store} skipped={result.units_skipped} "
            f"bundles={result.bundles} new_rows={result.new_rows} "
            f"published={result.published}"
        )
    return 0


__all__ = ["cmd_feed_ingest"]
