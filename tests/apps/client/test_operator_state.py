"""Tests for the operator's bulk-archive and cache-lifecycle rows."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from edgar_sec.apps.client import operator

_DATASET_SOURCES = ("bdc_datasets", "mfrr_datasets", "nmfp_datasets")


def _reference(source_id: str, tmp_path: Path):
    manifest = SimpleNamespace(
        source_id=source_id,
        source_url="https://example.test/archive.zip",
        sha256="ab" * 32,
        byte_size=1234,
        member_count=2,
        fetched_at="2026-01-02T00:00:00Z",
        sec_last_modified=None,
    )
    return SimpleNamespace(manifest=manifest, path=tmp_path / source_id / "archive.zip")


class _FakeFacade:
    """Facade stand-in over a fake bulk store with dataset-shaped ids."""

    def __init__(self, tmp_path: Path, extra_members: dict | None = None) -> None:
        self.artifacts_root = tmp_path
        self._tmp_path = tmp_path
        self.calls: list[str] = []
        self.stats: dict | None = {
            "responses": {"entries": 3, "bytes": 42},
            "content_cache": {"hits": 2},
        }
        self._members: dict[str, dict[str, bytes]] = {
            source_id: {"sub.tsv": b"hello member"} for source_id in _DATASET_SOURCES
        }
        self._members.update(extra_members or {})

    def bulk_archive_sources(self):
        return list(self._members)

    def bulk_archive(self, source_id, sha256=None):
        if source_id in self._members:
            return _reference(source_id, self._tmp_path)
        return None

    def bulk_archive_member(self, source_id, member):
        if source_id not in self._members:
            return None
        payload = self._members[source_id].get(member)
        if payload is None:
            raise ValueError(f"member {member!r} is not in archive")
        return payload

    def cache_stats(self):
        return self.stats

    def clear_cache(self):
        self.calls.append("clear_cache")
        return {"documents": 1, "responses": 2}

    def vacuum_cache(self):
        self.calls.append("vacuum_cache")


def _session(tmp_path: Path) -> tuple[operator.ClientSession, _FakeFacade]:
    facade = _FakeFacade(tmp_path)
    return operator.ClientSession(facade=facade), facade


def test_state_rows_effects() -> None:
    assert operator.REGISTRY["bulk_archive"].effect == "reads_state"
    assert operator.REGISTRY["bulk_archive_member"].effect == "reads_state"
    assert operator.REGISTRY["cache_state"].effect == "reads_state"
    assert operator.REGISTRY["cache_clear"].effect == "destructive"
    assert operator.REGISTRY["cache_vacuum"].effect == "destructive"


def test_bulk_archive_lists_dataset_sources_by_id(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("bulk_archive", session, {})
    assert result.error_code is None
    listed = [entry["source_id"] for entry in result.data["sources"]]
    assert listed == sorted(_DATASET_SOURCES)
    assert result.total == 3


def test_bulk_archive_lists_source_when_facade_root_is_none(
    tmp_path, monkeypatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

    artifacts_root = tmp_path / "artifacts"
    bulk_root = resolve_metadata_paths(artifacts_root).bulk_archives_root
    sha_dir = bulk_root / "submissions_bulk" / ("ab" * 32)
    sha_dir.mkdir(parents=True)

    class _ProductionShapeFacade:
        """Real Edgar shape: artifacts_root None, no bulk providers."""

        artifacts_root = None

        def bulk_archive(self, source_id, sha256=None):
            if source_id == "submissions_bulk":
                return _reference(source_id, tmp_path)
            return None

    facade = _ProductionShapeFacade()
    assert facade.artifacts_root is None
    assert not hasattr(facade, "bulk_archive_sources")
    assert not hasattr(facade, "bulk_sources")
    assert not hasattr(facade, "archive_sources")
    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.paths.resolve_paths",
        lambda: SimpleNamespace(artifacts_root=artifacts_root),
    )
    session = operator.ClientSession(facade=facade)
    result = operator.execute_by_id("bulk_archive", session, {})
    assert result.error_code is None
    assert result.data["present"] is True
    listed = [entry["source_id"] for entry in result.data["sources"]]
    assert listed == ["submissions_bulk"]


def test_bulk_archive_manifest_as_key_value_rows(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"source_id": "bdc_datasets"}
    result = operator.execute_by_id("bulk_archive", session, options)
    assert result.error_code is None
    assert result.data["manifest"]["member_count"] == 2
    assert result.data["manifest"]["sha256"] == "ab" * 32
    labels = [row.label for row in result.components]
    assert "members" in labels
    assert "sha256" in labels


def test_bulk_archive_unstored_source_is_absent(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("bulk_archive", session, {"source_id": "nope"})
    assert result.error_code == "absent"
    assert result.data["present"] is False


def _facts_session(tmp_path: Path) -> operator.ClientSession:
    facade = _FakeFacade(
        tmp_path,
        extra_members={"companyfacts_bulk": {"CIK0000320193.json": b'{"cik": 320193}'}},
    )
    return operator.ClientSession(facade=facade)


def test_bulk_archive_companyfacts_source_arrives_by_data(tmp_path) -> None:
    session = _facts_session(tmp_path)
    result = operator.execute_by_id("bulk_archive", session, {})
    assert result.error_code is None
    listed = [entry["source_id"] for entry in result.data["sources"]]
    assert "companyfacts_bulk" in listed
    assert listed == sorted([*_DATASET_SOURCES, "companyfacts_bulk"])

    manifest = operator.execute_by_id(
        "bulk_archive", session, {"source_id": "companyfacts_bulk"}
    )
    assert manifest.error_code is None
    assert manifest.data["source_id"] == "companyfacts_bulk"
    assert manifest.data["manifest"]["member_count"] == 2

    member = operator.execute_by_id(
        "bulk_archive_member",
        session,
        {"source_id": "companyfacts_bulk", "member": "CIK0000320193.json"},
    )
    assert member.error_code is None
    assert member.data["bytes"] == len(b'{"cik": 320193}')
    assert member.data["present"] is True


def test_bulk_member_reads_bytes_through_dataset_source(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"source_id": "nmfp_datasets", "member": "sub.tsv"}
    result = operator.execute_by_id("bulk_archive_member", session, options)
    assert result.error_code is None
    assert result.data["bytes"] == len(b"hello member")
    assert result.data["saved"] is False


def test_bulk_member_save_reports_path_and_size(tmp_path) -> None:
    session, _ = _session(tmp_path)
    target = tmp_path / "out" / "sub.tsv"
    options = {
        "source_id": "mfrr_datasets",
        "member": "sub.tsv",
        "save_path": str(target),
    }
    result = operator.execute_by_id("bulk_archive_member", session, options)
    assert result.error_code is None
    assert result.data["saved"] is True
    assert result.data["save_path"] == str(target)
    assert result.data["size"] == len(b"hello member")
    assert target.read_bytes() == b"hello member"


def test_bulk_member_unknown_member_is_not_found(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"source_id": "bdc_datasets", "member": "missing.tsv"}
    result = operator.execute_by_id("bulk_archive_member", session, options)
    assert result.error_code == "not_found"


def test_bulk_member_unstored_source_is_absent(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"source_id": "nope", "member": "sub.tsv"}
    result = operator.execute_by_id("bulk_archive_member", session, options)
    assert result.error_code == "absent"
    assert result.data["present"] is False


def test_cache_state_renders_both_tiers(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("cache_state", session, {})
    assert result.error_code is None
    labels = [row.label for row in result.components]
    assert "responses.entries" in labels
    assert "content_cache.hits" in labels
    assert result.data["stats"]["responses"]["entries"] == 3


def test_cache_state_unavailable_is_absent(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.stats = None
    result = operator.execute_by_id("cache_state", session, {})
    assert result.error_code == "absent"
    assert result.data["present"] is False


def test_cache_clear_refuses_without_the_exact_token(tmp_path) -> None:
    session, facade = _session(tmp_path)
    for confirm in ("", "cache", "cache_vacuum", " CACHE_CLEAR "):
        options = {"confirm": confirm}
        result = operator.execute_by_id("cache_clear", session, options)
        assert result.error_code == "refused"
    assert facade.calls == []


def test_cache_clear_with_the_typed_token(tmp_path) -> None:
    session, facade = _session(tmp_path)
    options = {"confirm": "cache_clear"}
    result = operator.execute_by_id("cache_clear", session, options)
    assert result.error_code is None
    assert result.data["cleared"] == {"documents": 1, "responses": 2}
    assert facade.calls == ["clear_cache"]


def test_cache_vacuum_refuses_without_the_exact_token(tmp_path) -> None:
    session, facade = _session(tmp_path)
    options = {"confirm": "cache_clear"}
    result = operator.execute_by_id("cache_vacuum", session, options)
    assert result.error_code == "refused"
    assert facade.calls == []


def test_cache_vacuum_with_the_typed_token(tmp_path) -> None:
    session, facade = _session(tmp_path)
    options = {"confirm": "cache_vacuum"}
    result = operator.execute_by_id("cache_vacuum", session, options)
    assert result.error_code is None
    assert result.data["vacuumed"] is True
    assert facade.calls == ["vacuum_cache"]
