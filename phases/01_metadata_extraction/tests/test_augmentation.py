import json
from pathlib import Path

import pytest
from conftest import imp

application = imp("phases.01_metadata_extraction.core.application")
augmentation = imp("phases.01_metadata_extraction.core.augmentation")
config = imp("phases.01_metadata_extraction.core.config")
paths_mod = imp("defs.runtime.paths")
paths_core = imp("phases.01_metadata_extraction.core.paths")
resources_mod = imp("defs.runtime.resources")
source_registry = imp("phases.01_metadata_extraction.core.source_registry")
artifacts_mod = imp("defs.runtime.artifacts")


class FakeSourceClient:
    def __init__(self, payload: bytes):
        self.payload = payload

    def get_bytes(self, _url: str) -> bytes:
        return self.payload


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}"):
        self.status_code = status_code
        self.content = content
        self.headers = {}


class FakeSession:
    def __init__(self):
        self.payloads = {}

    def get(self, url, headers=None, timeout=None):
        payload = self.payloads.get(url)
        if payload is None:
            return FakeResponse(404, b"not found")
        return FakeResponse(200, json.dumps(payload).encode("utf-8"))


@pytest.fixture()
def fake_sec(monkeypatch):
    session = FakeSession()

    def register(url, payload):
        session.payloads[url] = payload

    def fake_build(options):
        from defs import sec_http

        client = imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
            http=sec_http.SecHttpClient(
                user_agent=options.user_agent,
                rate_limiter=sec_http.RateLimiter(min_interval_s=0.001),
                retry_policy=sec_http.RetryPolicy(
                    max_retries=1, backoff_base_s=0.001, jitter=0.0
                ),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )
        return client

    monkeypatch.setattr(application, "_build_client", fake_build)
    return session, register


def _options(tmp_path, **overrides):
    values = {
        "input_path": str(tmp_path / "curated.csv"),
        "artifacts_dir": str(tmp_path / "run"),
        "chunk_size": 10,
        "partition_count": 1,
        "user_agent": "Test/1.0 test@example.com",
    }
    values.update(overrides)
    return config.RunOptions(**values)


def test_augmentation_uses_existing_manifest_and_publishes_new_snapshot(
    tmp_path, fake_sec, monkeypatch
):
    _session, register = fake_sec
    base_url = "https://data.sec.gov/submissions/CIK0000000020.json"
    register(
        base_url,
        {
            "cik": "0000000020",
            "name": "K TRON",
            "filings": {"recent": {}, "files": []},
        },
    )
    curated = tmp_path / "curated.csv"
    curated.write_text("cik,name\n20,K Tron\n", encoding="utf-8")
    base_options = _options(
        tmp_path, input_path=str(curated), artifacts_dir=str(tmp_path / "base")
    )
    application.build_plan(base_options)
    application.run_chunk(
        config.RunOptions(
            **{**base_options.to_dict(), "chunk_id": 1, "partition_id": 1}
        )
    )
    application.merge_one_partition(base_options, 1)
    base_report = application.merge(base_options)
    base_hash = base_report.artifact_sha256
    manifests = artifacts_mod.find_manifests(
        "submission_metadata", phase="metadata", artifacts_root=str(tmp_path)
    )
    base_manifest = next(
        item for item in manifests if item["artifact_sha256"] == base_hash
    )
    base_manifest_path = tmp_path / artifacts_mod.manifest_relative_path(
        phase="metadata",
        dataset="submission_metadata",
        artifact_id_value=base_manifest["artifact_id"],
    )

    source_payload = json.dumps(
        {
            "0": {"cik_str": 20, "ticker": "KTRO", "title": "K TRON"},
            "1": {"cik_str": 1761, "ticker": "TRZ", "title": "TRANZONIC"},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    source = source_registry.refresh_company_tickers(
        artifacts_root=tmp_path,
        user_agent="Test/1.0 test@example.com",
        client=FakeSourceClient(source_payload),
    )
    source_manifest_path = paths_core.resolve_metadata_paths(
        env={"ARTIFACTS_ROOT": str(tmp_path)}
    ).source_manifest_path("company_tickers", source["snapshot_id"])

    register(
        "https://data.sec.gov/submissions/CIK0000001761.json",
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "filings": {"recent": {}, "files": []},
        },
    )
    augment_options = _options(
        tmp_path,
        artifacts_dir=str(tmp_path / "augment"),
        source_manifest=str(source_manifest_path),
        base_metadata_manifest=str(base_manifest_path),
        augmentation=True,
    )
    plan = application.build_plan(augment_options)
    assert plan["row_count"] == 1
    assert plan["cik_padded"] == ["0000001761"]
    assert "manifests" not in Path(plan["worklist_path"]).parts
    application.run_chunk(
        config.RunOptions(
            **{
                **augment_options.to_dict(),
                "chunk_id": 1,
                "partition_id": 1,
            }
        )
    )
    application.merge_one_partition(augment_options, 1)
    opened = []
    real_artifact = augmentation.FinalizedArtifact

    class _SpyArtifact:
        def __init__(self, path, **kwargs):
            opened.append({"path": str(path), **kwargs})
            self._inner = real_artifact(path, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(augmentation, "FinalizedArtifact", _SpyArtifact)
    augmented_report = application.merge(augment_options)

    profile = resources_mod.derive_resources()
    assert len(opened) == 2
    for entry in opened:
        assert entry["threads"] == profile.threads
        assert entry["memory_limit"] == profile.memory_limit
        assert entry["temp_directory"] == profile.temp_directory

    assert augmented_report.row_count == 2
    assert augmented_report.report_source == "augmented_snapshot"
    assert augmented_report.artifact_sha256 != base_hash
    assert base_report.artifact_sha256 == base_hash
    assert Path(augmented_report.output_path).is_file()
