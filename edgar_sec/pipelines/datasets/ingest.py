"""Download one dataset vintage through the registry surface into the store."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from urllib.parse import urlsplit

import edgar_sec.domain.sec_urls as sec_urls
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore

from .paths import DatasetsPaths
from .specs import BDC_POPULATION_SOURCE_ID, DatasetSpec
from .store import VintageLoad, load_bdc_population, load_vintage, open_store


@dataclass(frozen=True, slots=True)
class ImportResult:
    """One imported vintage: archive identity and load outcome."""

    set_id: str
    vintage: str
    archive_sha: str
    source_url: str
    load: VintageLoad


def build_http_client() -> SecHttpClient:
    """Build the SEC HTTP client from runtime settings."""
    runtime = resolve_runtime_settings()
    return SecHttpClient.from_settings(runtime.sec, cache_dir=str(runtime.cache_root))


def dataset_url(spec: DatasetSpec, vintage: str) -> str:
    """Return the registry URL for one vintage of a dataset set."""
    builder = getattr(sec_urls, spec.builder)
    return builder(vintage)


def import_vintage(
    paths: DatasetsPaths,
    spec: DatasetSpec,
    vintage: str,
    *,
    http: SecHttpClient,
    loaded_at: str | None = None,
) -> ImportResult:
    """Download, archive, and load one vintage of one dataset set."""
    url = dataset_url(spec, vintage)
    runtime = resolve_runtime_settings()
    store = BulkArchiveStore(paths.bulk_archives_root)
    staging_dir = store.root / ".downloads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f"{spec.set_id}-{vintage}-", suffix=".zip", dir=staging_dir
    )
    staging = Path(staging_name)
    try:
        os.close(descriptor)
        expected = urlsplit(url)

        def validate_redirect(redirect_url: str) -> None:
            parts = urlsplit(redirect_url)
            if (
                parts.scheme != "https"
                or parts.netloc != expected.netloc
                or parts.path != expected.path
            ):
                raise ValueError(
                    f"dataset redirect left the vintage path: {redirect_url}"
                )

        result = http.stream_to_file(
            url,
            staging,
            max_response_bytes=runtime.sec.bulk_archive_max_bytes,
            validate_redirect=validate_redirect,
        )
        if isinstance(result, StreamFailure):
            raise RuntimeError(
                f"dataset download failed ({result.code}): {result.detail}"
            )
        reference = store.put_file(spec.source_id, staging, source_url=url)
    finally:
        staging.unlink(missing_ok=True)
    stamp = loaded_at or datetime.now(UTC).isoformat(timespec="seconds")
    con = open_store(paths.store_file)
    try:
        load = load_vintage(
            con,
            spec,
            reference.path,
            vintage=vintage,
            archive_sha=reference.sha256,
            source_url=url,
            loaded_at=stamp,
            work_dir=paths.transient_dir(f"load-{spec.set_id}-{vintage}"),
        )
    finally:
        con.close()
    return ImportResult(
        set_id=spec.set_id,
        vintage=vintage,
        archive_sha=reference.sha256,
        source_url=url,
        load=load,
    )


def import_local_archive(
    paths: DatasetsPaths,
    spec: DatasetSpec,
    vintage: str,
    archive_path: Path,
    *,
    source_url: str,
    loaded_at: str | None = None,
) -> ImportResult:
    """Archive and load a vintage ZIP already on disk (no network)."""
    store = BulkArchiveStore(paths.bulk_archives_root)
    reference = store.put_file(spec.source_id, archive_path, source_url=source_url)
    stamp = loaded_at or datetime.now(UTC).isoformat(timespec="seconds")
    con = open_store(paths.store_file)
    try:
        load = load_vintage(
            con,
            spec,
            reference.path,
            vintage=vintage,
            archive_sha=reference.sha256,
            source_url=source_url,
            loaded_at=stamp,
            work_dir=paths.transient_dir(f"load-{spec.set_id}-{vintage}"),
        )
    finally:
        con.close()
    return ImportResult(
        set_id=spec.set_id,
        vintage=vintage,
        archive_sha=reference.sha256,
        source_url=source_url,
        load=load,
    )


def import_bdc_population(
    paths: DatasetsPaths,
    years: tuple[int, ...],
    *,
    http: SecHttpClient,
    loaded_at: str | None = None,
) -> int:
    """Download the BDC Report CSVs and load the population relation."""
    stamp = loaded_at or datetime.now(UTC).isoformat(timespec="seconds")
    work = paths.transient_dir("bdc-population")
    work.mkdir(parents=True, exist_ok=True)
    store = BulkArchiveStore(paths.bulk_archives_root)
    yearly: dict[int, Path] = {}
    for year in years:
        url = sec_urls.bdc_report_url(year)
        payload = http.get_bytes(url)
        raw = work / f"bdc-report-{year}.csv"
        raw.write_bytes(payload)
        reference = store.put_file(BDC_POPULATION_SOURCE_ID, raw, source_url=url)
        yearly[year] = reference.path
    con = open_store(paths.store_file)
    try:
        return load_bdc_population(con, yearly, loaded_at=stamp)
    finally:
        con.close()


__all__ = [
    "ImportResult",
    "build_http_client",
    "dataset_url",
    "import_bdc_population",
    "import_local_archive",
    "import_vintage",
]
