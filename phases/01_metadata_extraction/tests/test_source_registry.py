import json
from pathlib import Path

import pytest
from conftest import imp

source_registry = imp("phases.01_metadata_extraction.core.source_registry")
registry = imp("phases.01_metadata_extraction.core.registry")
paths_core = imp("phases.01_metadata_extraction.core.paths")


class FakeClient:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.urls = []

    def get_bytes(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payload


def _payload() -> bytes:
    return json.dumps(
        {
            "0": {"cik_str": 20, "ticker": "KTRO", "title": "K TRON"},
            "1": {"cik_str": 20, "ticker": "KTROA", "title": "K TRON"},
            "2": {"cik_str": 37996, "ticker": "F", "title": "FORD MOTOR CO"},
        },
        separators=(",", ":"),
    ).encode("utf-8")


def test_refresh_publishes_immutable_source_snapshot(tmp_path):
    client = FakeClient(_payload())
    first = source_registry.refresh_company_tickers(
        artifacts_root=tmp_path,
        user_agent="Test/1.0 test@example.com",
        client=client,
    )
    second = source_registry.refresh_company_tickers(
        artifacts_root=tmp_path,
        user_agent="Test/1.0 test@example.com",
        client=client,
    )

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["listing_row_count"] == 3
    assert first["unique_cik_count"] == 2
    assert first["duplicate_listing_count"] == 0
    assert (
        paths_core.resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(tmp_path)})
        .source_manifest_path("company_tickers", first["snapshot_id"])
        .is_file()
    )
    assert len(client.urls) == 2


def test_compare_sources_writes_registry_and_effective_csv(tmp_path):
    client = FakeClient(_payload())
    source = source_registry.refresh_company_tickers(
        artifacts_root=tmp_path,
        user_agent="Test/1.0 test@example.com",
        client=client,
    )
    curated = tmp_path / "curated.csv"
    curated.write_text(
        "cik,name\n20,K Tron curated\n1761,Tranzonic\n", encoding="utf-8"
    )

    source_manifest_path = paths_core.resolve_metadata_paths(
        env={"ARTIFACTS_ROOT": str(tmp_path)}
    ).source_manifest_path("company_tickers", source["snapshot_id"])
    result = registry.compare_sources(
        curated_input_path=curated,
        source_manifest_path=source_manifest_path,
        artifacts_root=tmp_path,
    )

    assert result["curated_count"] == 2
    assert result["active_listing_row_count"] == 3
    assert result["active_unique_cik_count"] == 2
    assert result["overlap_count"] == 1
    assert result["active_only_cik_count"] == 1
    assert result["curated_only_cik_count"] == 1
    csv_path = Path(result["effective_csv_path"])
    assert csv_path.read_text(encoding="utf-8") == (
        "cik,name\n0000000020,K Tron curated\n0000001761,Tranzonic\n"
        "0000037996,FORD MOTOR CO\n"
    )
    assert Path(result["registry_path"]).is_file()
    assert Path(result["new_ciks_path"]).is_file()
    assert "manifests" not in Path(result["registry_path"]).parts
    assert "manifests" not in Path(result["listing_path"]).parts
    assert "manifests" not in Path(result["worklist_path"]).parts
    assert Path(result["effective_csv_path"]).parent.name == result["registry_id"]
    assert not (tmp_path / "uploads" / "company_tickers.json").exists()


def test_parse_rejects_invalid_entries():
    raw = json.dumps(
        {"0": {"cik_str": "not-a-cik", "ticker": "X", "title": "X"}}
    ).encode()
    with pytest.raises(source_registry.SourceRegistryError, match="invalid cik_str"):
        source_registry.parse_company_tickers(
            raw, snapshot_id="snapshot", observed_at="2026-01-01T00:00:00Z"
        )
