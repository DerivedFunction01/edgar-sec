"""Re-fetch captured test fixtures from their SEC sources into a cache.

The tracked manifest keys each captured fixture by source and sha256;
full-form rows populate the cache, live-form rows fetch as diffs only.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

from edgar_sec.engine.document.unpacking.unpacker import (
    SgmlSubDocument,
    strip_pem_envelope,
    unpack_sgml_submission,
)
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.runtime.paths import dataset_root, resolve_paths
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.runtime.settings.sec import DEFAULT_RATE_LIMIT_RPS
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.storage.atomic import atomic_write_bytes

MANIFEST_NAME = "captured_manifest.json"
_FIXTURES_DATASET = "fixtures"
_CACHE_DIR = "captured"
_RETRY_PAUSE_S = 10

_TOKEN_SCRIPT = re.compile(
    rb'<script type="text/javascript"\s+src="/[A-Za-z0-9_\-]+'
    rb'(?:/[A-Za-z0-9_\-]+)+" *></script>(?=</body>)',
    re.IGNORECASE,
)
# Block spans stay local: the unpacker returns bodies, not whole blocks.
_RE_DOCUMENT_SPAN = re.compile(rb"(?is)<DOCUMENT>.*?</DOCUMENT>")


def default_manifest_path() -> Path:
    """The tracked captured-fixture manifest, beside the fixtures it keys."""
    return resolve_paths().repo_root / "tests" / "fixtures" / MANIFEST_NAME


def load_manifest(manifest_path: Path | None = None) -> dict[str, Any]:
    """The captured-fixture manifest payload."""
    path = manifest_path or default_manifest_path()
    return json.loads(path.read_text(encoding="utf-8"))


def captured_fixture_cache_root() -> Path:
    """Cache root: the ``fixtures.cache_root`` override when set, else the
    artifacts-root convention ``<artifacts_root>/fixtures/captured``.
    """
    configured = resolve_settings().get("fixtures.cache_root", "")
    text = str(configured).strip() if configured is not None else ""
    if text:
        return Path(text)
    return dataset_root(resolve_paths().artifacts_root, _FIXTURES_DATASET) / _CACHE_DIR


def cache_path(name: str, cache_root: Path | None = None) -> Path:
    """One captured fixture's path inside the cache."""
    return (cache_root or captured_fixture_cache_root()) / name


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _client() -> SecHttpClient:
    """The SEC fetch client; the user agent rides the environment seam."""
    user_agent = get_env("SEC_USER_AGENT")
    if not user_agent:
        raise ValueError("SEC_USER_AGENT must be set in the process environment")
    limiter = RateLimiter(min_interval_s=1 / DEFAULT_RATE_LIMIT_RPS)
    return SecHttpClient(user_agent=user_agent, rate_limiter=limiter)


def _strip_token_script(content: bytes) -> bytes:
    """Remove the CDN token script injected immediately before </body>;
    its per-request token is what makes the raw fetch unverifiable.
    """
    return _TOKEN_SCRIPT.sub(b"", content)


def _document_name(entry: dict[str, Any]) -> str | None:
    """The document an extraction row keys on: the fixture name after "__"."""
    base = entry["path"].rsplit("/", 1)[-1]
    if "__" not in base:
        return None
    return base.split("__", 1)[1] or None


def _select_sub_document(
    docs: list[SgmlSubDocument], entry: dict[str, Any]
) -> int | None:
    """The sub-document an extraction row keys on: <FILENAME> first;
    the row's extract_type only when no sub-document carries a filename.
    """
    document_name = _document_name(entry)
    if document_name:
        for index, doc in enumerate(docs):
            if doc.filename == document_name:
                return index
    if entry.get("extract_type") and not any(doc.filename for doc in docs):
        for index, doc in enumerate(docs):
            if doc.doc_type == entry["extract_type"]:
                return index
    if len(docs) == 1:
        return 0
    return None


def _block_spans(payload: bytes) -> list[bytes]:
    """Whole <DOCUMENT> block slices in envelope order, each running
    through one trailing newline — the form the block captures carry.
    """
    spans = []
    for match in _RE_DOCUMENT_SPAN.finditer(payload):
        end = match.end()
        if payload[end : end + 2] == b"\r\n":
            end += 2
        elif payload[end : end + 1] == b"\n":
            end += 1
        spans.append(payload[match.start() : end])
    return spans


def _extract_document(payload: bytes, entry: dict[str, Any]) -> bytes | None:
    """One document out of a submission payload, in the capture's form
    ("block"/"body"), selected over the unpacker's sub-documents.
    """
    content = strip_pem_envelope(payload)
    docs = unpack_sgml_submission(content)
    index = _select_sub_document(docs, entry)
    if index is None:
        return None
    if entry["extract"] == "body":
        return docs[index].raw_payload
    spans = _block_spans(content)
    if index >= len(spans):
        return None
    return spans[index]


def _normalize_content(entry: dict[str, Any], payload: bytes) -> bytes | None:
    """Fetched content in the form the manifest hash keys: extraction
    first, then the token-script strip; None on an extraction miss.
    """
    content = payload
    if entry.get("extract"):
        content = _extract_document(content, entry)
        if content is None:
            return None
    if entry.get("strip_script"):
        content = _strip_token_script(content)
    return content


def _stored_form(entry: dict[str, Any], content: bytes) -> tuple[bytes, bool]:
    """Content in its stored form, and whether it verifies: a gzip row
    stores re-gzipped (zero mtime) and verifies on the content hash.
    """
    if entry.get("stored") == "gzip":
        stored = gzip.compress(content, mtime=0)
        return stored, _sha256(content) == entry["content_sha256"]
    return content, _sha256(content) == entry["sha256"]


def _fetch_with_retry(client: SecHttpClient, url: str) -> bytes:
    """Fetch one source; a refusal earns one retry after a pause, since
    the Archives directories refuse transiently (the census's LISTED rows).
    """
    try:
        return client.get_bytes(url, force_refresh=True)
    except Exception:
        time.sleep(_RETRY_PAUSE_S)
        return client.get_bytes(url, force_refresh=True)


def populate(
    client: SecHttpClient,
    manifest: dict[str, Any],
    cache_root: Path,
    *,
    only: str | None = None,
) -> list[str]:
    """Fetch every full-form row into the cache, verifying its hash; a row
    whose source refuses is reported FAILED and the rest still populate.
    """
    lines = []
    for entry in manifest["fixtures"]:
        if entry["form"] != "full" or (only and only not in entry["path"]):
            continue
        try:
            payload = _fetch_with_retry(client, entry["source_url"])
        except Exception as exc:  # per-row tolerance: report, never starve the rest
            lines.append(f"FAILED {entry['path']} ({type(exc).__name__})")
            continue
        content = _normalize_content(entry, payload)
        if content is None:
            lines.append(f"MISMATCH {entry['path']} (no matching document block)")
            continue
        stored, ok = _stored_form(entry, content)
        target = cache_root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, stored)
        lines.append(f"{'OK' if ok else 'MISMATCH'} {entry['path']}")
    return lines


def verify_cache(manifest: dict[str, Any], cache_root: Path) -> list[str]:
    """Check the populated cache against the manifest, without fetching."""
    lines = []
    for entry in manifest["fixtures"]:
        if entry["form"] != "full":
            continue
        target = cache_root / entry["path"]
        if not target.is_file():
            lines.append(f"MISSING {entry['path']}")
            continue
        payload = target.read_bytes()
        if entry.get("stored") == "gzip":
            ok = _sha256(gzip.decompress(payload)) == entry["content_sha256"]
        else:
            ok = _sha256(payload) == entry["sha256"]
        lines.append(f"{'OK' if ok else 'MISMATCH'} {entry['path']}")
    return lines


def check_live(
    client: SecHttpClient,
    manifest: dict[str, Any],
    fixtures_root: Path,
) -> list[str]:
    """Diff every live-form row's source against its tracked capture.
    MATCH can move a row to the cache class; DIFF is the dynamic proof.
    EFTS rows record a POST query the fetch client cannot replay: SKIP.
    """
    lines = []
    for entry in manifest["fixtures"]:
        if entry["form"] != "live":
            continue
        if "query" in entry or entry["path"].startswith("efts/"):
            lines.append(f"SKIP {entry['path']} (POST query replay unsupported)")
            continue
        payload = client.get_bytes(entry["source_url"], force_refresh=True)
        capture = (fixtures_root / entry["path"]).read_bytes()
        lines.append(f"{'MATCH' if payload == capture else 'DIFF'} {entry['path']}")
    return lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixture_cache")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--only", default=None, help="populate only rows whose path contains this text"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check the populated cache; fetch nothing",
    )
    parser.add_argument(
        "--check-live",
        action="store_true",
        help="diff live-form sources against their captures",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Populate the captured-fixture cache from the tracked manifest."""
    args = _build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    cache_root = args.cache_root or captured_fixture_cache_root()
    if args.verify_only:
        lines = verify_cache(manifest, cache_root)
        print("\n".join(lines))
        return 1 if any(not line.startswith("OK") for line in lines) else 0
    client = _client()
    if args.check_live:
        fixtures_root = (args.manifest or default_manifest_path()).parent
        lines = check_live(client, manifest, fixtures_root)
        print("\n".join(lines))
        return 1 if any(line.startswith("ERROR") for line in lines) else 0
    lines = populate(client, manifest, cache_root, only=args.only)
    print("\n".join(lines))
    return 1 if any(not line.startswith("OK") for line in lines) else 0


__all__ = [
    "MANIFEST_NAME",
    "cache_path",
    "captured_fixture_cache_root",
    "check_live",
    "default_manifest_path",
    "load_manifest",
    "main",
    "populate",
    "verify_cache",
]


if __name__ == "__main__":
    sys.exit(main())
