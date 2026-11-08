"""Facts command: download through the command surface, or reuse the store."""

from __future__ import annotations

import io
import json
import zipfile as zipfile_module
from pathlib import Path

from edgar_sec.pipelines.metadata_sync.commands.facts import cmd_facts_ingest
from edgar_sec.pipelines.metadata_sync.facts_store import read_facts_for_cik
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from tests.pipelines.metadata_sync.test_companyfacts import _StreamingHttp
from tests.pipelines.metadata_sync.test_facts_store import _member


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile_module.ZipFile(buffer, "w") as archive:
        archive.writestr("CIK0000320193.json", _member("Apple", 300))
    return buffer.getvalue()


def test_cmd_facts_ingest_downloads_ingests_and_publishes(tmp_path: Path) -> None:
    http = _StreamingHttp(_zip_bytes())

    result = cmd_facts_ingest(artifacts_root=tmp_path, workers=1, http=http)

    assert result == 0
    paths = resolve_metadata_paths(tmp_path)
    facts = read_facts_for_cik(paths.facts_store_file, 320193)
    assert [fact.value for fact in facts] == [300.0, 150.0]
    assert json.dumps([fact.tag for fact in facts]) == '["Assets", "Liabilities"]'


def test_cmd_facts_ingest_from_store_needs_no_http(tmp_path: Path) -> None:
    cmd_facts_ingest(
        artifacts_root=tmp_path, workers=1, http=_StreamingHttp(_zip_bytes())
    )

    result = cmd_facts_ingest(artifacts_root=tmp_path, workers=1, from_store=True)

    assert result == 0
    paths = resolve_metadata_paths(tmp_path)
    assert len(read_facts_for_cik(paths.facts_store_file, 320193)) == 2
