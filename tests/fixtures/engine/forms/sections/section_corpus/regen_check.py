#!/usr/bin/env python3
"""Re-verify the section corpus's dropped (regenerable) texts.

Tooling layer: re-banks each dropped_texts.json specimen from the
archives and checks it against the registry and the index's expected.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edgar_sec.foundation.runtime.env import get_env  # noqa: E402
from edgar_sec.infra.sec_http.client import SecHttpClient  # noqa: E402
from edgar_sec.infra.sec_http.rate_limit import RateLimiter  # noqa: E402
from edgar_sec.tools.section_corpus.build import (  # noqa: E402
    _fetch_body,
    bank_specimen,
    prepare_jobs,
)

CORPUS = Path(__file__).resolve().parent


def main() -> int:
    index = {
        e["id"]: e
        for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    }
    dropped = json.loads((CORPUS / "dropped_texts.json").read_text(encoding="utf-8"))
    user_agent = get_env("SEC_USER_AGENT")
    if not user_agent:
        raise ValueError("SEC_USER_AGENT must be set in the process environment")
    client = SecHttpClient(user_agent=user_agent, rate_limiter=RateLimiter())
    jobs = [
        {
            "slug": index[e["id"]]["family"],
            "form": index[e["id"]]["form"],
            "accession": index[e["id"]]["accession"],
            "document": index[e["id"]]["document"],
            "era": index[e["id"]].get("era"),
        }
        for e in dropped
    ]
    prepare_jobs(jobs, client)
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        (scratch / "taxonomies.json").write_bytes(
            (CORPUS / "taxonomies.json").read_bytes()
        )
        for entry, job in zip(dropped, jobs, strict=True):
            spec = index[entry["id"]]
            try:
                record = bank_specimen(scratch, job, _fetch_body(job, client))
            except Exception as exc:  # noqa: BLE001 - report and continue
                failures += 1
                print(f"FAIL {entry['id']}: {type(exc).__name__}: {exc}")
                continue
            regen = (scratch / entry["text"]).read_bytes()
            if entry["class"] == "identical":
                digest = hashlib.sha256(regen).hexdigest()
                ok = digest == entry["banked_sha256"]
            else:
                ok = record["baseline"] == spec["expected"]
            print(f"{'OK' if ok else 'FAIL'} {entry['id']} ({entry['class']})")
            failures += 0 if ok else 1
    print(f"dropped={len(dropped)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
