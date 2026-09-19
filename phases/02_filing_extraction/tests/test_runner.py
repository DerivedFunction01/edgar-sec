"""Tests for the Phase 02 interactive runner, status discovery, and launcher entry."""

from __future__ import annotations

import builtins
import importlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

run = importlib.import_module("phases.02_filing_extraction.run")
discovery = importlib.import_module("phases.02_filing_extraction.core.discovery")
schemas = importlib.import_module("phases.01_metadata_extraction.core.schemas")
materializer = importlib.import_module("phases.02_filing_extraction.core.materialize")
target_plan = importlib.import_module("phases.02_filing_extraction.core.target_plan")
fixtures = importlib.import_module("phases.02_filing_extraction.tests.test_materialize")
phase_config = importlib.import_module("phases.02_filing_extraction.core.config")

row = fixtures.row

from pathlib import Path

from defs.runtime import resolve_paths
from defs.runtime.registry import find_entry


def test_registry_entry_points_at_run_module() -> None:
    entry = find_entry("filing-catalog")
    assert entry is not None
    assert entry.module == "phases.02_filing_extraction.run"


def test_discover_catalogs_empty_root(tmp_path) -> None:
    assert discovery.discover_catalogs(str(tmp_path / "catalogs")) == []


def test_discover_catalogs_valid_and_skips_noise(tmp_path) -> None:
    snap_dir = (
        tmp_path
        / "manifests"
        / "filing_extraction"
        / "filing_catalog"
        / "snapshots"
        / "abc123"
    )
    snap_dir.mkdir(parents=True)
    manifest = {
        "manifest_kind": "filing_catalog_snapshot",
        "snapshot_id": "abc123",
        "catalog_id": "abc123",
        "source_artifact_sha256": "deadbeef",
        "form_count": 1,
        "target_rows": 3,
        "form_counts": {"10-K": 3},
    }
    (snap_dir / "snapshot.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = discovery.discover_catalogs(str(tmp_path / "manifests"))
    assert len(result) == 1
    summary = result[0]
    assert summary["catalog_id"] == "abc123"
    assert summary["source_artifact_sha256"] == "deadbeef"
    assert summary["form_count"] == 1
    assert summary["target_rows"] == 3


def test_discover_catalogs_ignores_metadata_snapshot_manifests(tmp_path) -> None:
    manifests_root = tmp_path / "manifests"
    meta_snap = manifests_root / "metadata" / "submission_metadata" / "snapshots" / "S1"
    meta_snap.mkdir(parents=True)
    (meta_snap / "snapshot.manifest.json").write_text(
        json.dumps(
            {
                "manifest_kind": "submission_metadata_snapshot",
                "snapshot_id": "S1",
                "schema_version": "1.0.0",
                "resolved_parts": [],
            }
        ),
        encoding="utf-8",
    )
    cat_snap = (
        manifests_root / "filing_extraction" / "filing_catalog" / "snapshots" / "S0"
    )
    cat_snap.mkdir(parents=True)
    (cat_snap / "snapshot.manifest.json").write_text(
        json.dumps(
            {
                "manifest_kind": "filing_catalog_snapshot",
                "snapshot_id": "S0",
                "dataset": "filing_catalog",
                "schema_version": "1.1.0",
                "target_rows": 42,
                "form_count": 2,
                "form_counts": {"10-K": 30, "10-Q": 12},
                "parts": [],
            }
        ),
        encoding="utf-8",
    )

    result = discovery.discover_catalogs(str(manifests_root))
    assert [c["catalog_id"] for c in result] == ["S0"]
    assert result[0]["target_rows"] == 42
    assert result[0]["form_count"] == 2


def test_discover_plans_valid_and_skips_noise(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    runs = tmp_path / "runs"
    valid = runs / "plan001"
    valid.mkdir(parents=True)
    (valid / "plan.json").write_text(
        json.dumps(
            {
                "run_id": "plan001",
                "catalog_id": "abc123",
                "forms": ["10-K"],
                "amendment": "both",
                "limit": None,
                "counts": {"10-K": 3},
            }
        ),
        encoding="utf-8",
    )
    noisy = runs / "no_plan"
    noisy.mkdir(parents=True)
    (noisy / "targets.parquet").write_bytes(b"x")

    result = discovery.discover_plans(str(runs))
    assert len(result) == 1
    summary = result[0]
    assert summary["run_id"] == "plan001"
    assert summary["forms"] == ["10-K"]
    assert summary["amendment"] == "both"
    assert summary["selected_rows"] == 3


def test_discover_plans_scans_immutable_collection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    plans_root = tmp_path / "manifests" / "filing_extraction" / "target_plans"
    published = plans_root / "planABC"
    published.mkdir(parents=True)
    (published / "plan.json").write_text(
        json.dumps(
            {
                "plan_id": "planABC",
                "scope": "deterministic",
                "counts": {"10-K": 2},
            }
        ),
        encoding="utf-8",
    )
    staging = plans_root / ".staging-planABC-123"
    staging.mkdir()
    (staging / "plan.json").write_text(
        json.dumps({"plan_id": "planABC"}), encoding="utf-8"
    )

    result = discovery.discover_plans(str(tmp_path / "runs"))
    by_id = {p["plan_id"]: p for p in result}
    assert set(by_id) == {"planABC"}
    assert by_id["planABC"]["scope"] == "deterministic"


def test_status_does_not_scan_parquet(tmp_path, monkeypatch) -> None:
    # A catalog directory that only contains Parquet must not be reported.
    catalogs = tmp_path / "catalogs" / "only_parquet"
    catalogs.mkdir(parents=True)
    (catalogs / "data.parquet").write_bytes(b"x")
    captured = {}

    def fake_catalogs(root=None, *args, **kwargs):
        captured["catalogs_root"] = root
        return []

    def fake_plans(root=None, *args, **kwargs):
        captured["plans_root"] = root
        return []

    monkeypatch.setattr(discovery, "discover_catalogs", fake_catalogs)
    monkeypatch.setattr(discovery, "discover_plans", fake_plans)
    result = discovery.status(str(tmp_path / "catalogs"), str(tmp_path / "runs"))
    assert result == {"catalogs": [], "plans": []}
    assert captured["catalogs_root"] == str(tmp_path / "catalogs")
    assert captured["plans_root"] == str(tmp_path / "runs")


def test_main_forwards_subcommand_to_cli(monkeypatch) -> None:
    captured = {}

    def fake_cli(argv):
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr(run, "cli_main", fake_cli)
    assert run.main(["materialize", "--source-manifest", "m.json"]) == 0
    assert captured["argv"] == ["materialize", "--source-manifest", "m.json"]


def test_materialize_menu_uses_manifest_phase_one_default(
    monkeypatch, tmp_path
) -> None:
    source = (
        tmp_path
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"parquet placeholder")
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    responses = iter(["", "", ""])
    captured = {}
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    def fake_materialize(**kwargs):
        captured.update(kwargs)
        return {"catalog_id": "x"}

    monkeypatch.setattr(run, "materialize", fake_materialize)

    run._menu_materialize()

    assert captured["source_artifact"] == str(source)
    # The durable engine default applies; the runner never redirects the
    # snapshot into the transient catalogs scratch tree.
    assert "output_root" not in captured
    assert callable(captured["progress"])


def test_plan_menu_uses_only_discovered_catalog_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    catalog = {"catalog_id": "catalog-1", "target_rows": 100, "form_count": 5}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])
    responses = iter(["1", "", ""])
    captured = {}
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    def fake_plan(catalog_path, output_root, **kwargs):
        captured["catalog"] = catalog_path
        captured["output_root"] = output_root
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["catalog"] == "catalog-1"
    assert captured["scope"] == "deterministic"
    assert captured["output_root"] == str(
        tmp_path / "transient" / "filing_extraction" / "runs"
    )
    assert captured["forms"] == ()
    assert captured["amendment"] == "both"
    assert captured["limit"] is None
    assert callable(captured["progress"])


def test_menu_plan_fixture_scope_generates_template_and_stops(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    catalog = {"catalog_id": "catalog-1", "target_rows": 10, "form_count": 2}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])
    responses = iter(["2", ""])  # Scope 2 = policy, then default-Y for template
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    policy_created = []

    def fake_auto_policy(catalog_id, dest):
        policy_created.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("{}", encoding="utf-8")
        return dest

    monkeypatch.setattr(run, "_auto_generate_policy", fake_auto_policy)

    plan_called = []
    monkeypatch.setattr(run, "plan", lambda *a, **k: plan_called.append(True))

    run._menu_plan()

    assert len(policy_created) == 1
    assert len(plan_called) == 0  # Should NOT run plan immediately
    out = capsys.readouterr().out
    assert "Created default selection policy template at:" in out
    assert "Edit it, then rerun" in out


def test_menu_plan_fixture_scope_runs_with_existing_policy(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    catalog = {"catalog_id": "catalog-1", "target_rows": 10, "form_count": 2}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])

    pol_file = resolve_paths("filing_extraction").phase_root / "selection_policy.json"
    pol_file.parent.mkdir(parents=True, exist_ok=True)
    pol_file.write_text(
        json.dumps({"corpus_id": "menu_corpus", "forms": ["10-K"]}),
        encoding="utf-8",
    )

    responses = iter(["2", ""])  # Scope 2 = policy, then default policy selection
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    captured = {}

    def fake_plan(catalog_path, output_root, **kwargs):
        captured["catalog"] = catalog_path
        captured["output_root"] = output_root
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["catalog"] == "catalog-1"
    assert captured["scope"] == "policy"
    assert captured["selection_policy_path"] == str(pol_file)


def test_menu_plan_policy_scope_toggles_between_valid_policies(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    catalog = {"catalog_id": "catalog-1", "target_rows": 10, "form_count": 2}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])

    phase_root = resolve_paths("filing_extraction").phase_root
    phase_root.mkdir(parents=True, exist_ok=True)
    first = phase_root / "selection_policy.json"
    second = phase_root / "selection_policy_copy.json"
    first.write_text(
        json.dumps({"corpus_id": "corpus_one", "forms": ["10-K"]}),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps({"corpus_id": "corpus_two", "forms": ["10-K", "10-Q"]}),
        encoding="utf-8",
    )
    # Unrelated JSON in the same directory must be excluded from the picker.
    (phase_root / "config.json").write_text(
        json.dumps({"source_batch_size": 512}), encoding="utf-8"
    )

    responses = iter(["2", "2"])  # Scope 2 = policy, then pick the second policy
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    captured = {}

    def fake_plan(catalog_path, output_root, **kwargs):
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["scope"] == "policy"
    assert captured["selection_policy_path"] == str(second)
    out = capsys.readouterr().out
    assert "corpus_one" in out
    assert "corpus_two" in out


def test_menu_plan_policy_scope_accepts_custom_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    catalog = {"catalog_id": "catalog-1", "target_rows": 10, "form_count": 2}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])

    phase_root = resolve_paths("filing_extraction").phase_root
    phase_root.mkdir(parents=True, exist_ok=True)
    (phase_root / "selection_policy.json").write_text(
        json.dumps({"corpus_id": "corpus_one", "forms": ["10-K"]}),
        encoding="utf-8",
    )
    custom = tmp_path / "elsewhere" / "custom_policy.json"
    custom.parent.mkdir(parents=True)
    custom.write_text(
        json.dumps({"corpus_id": "custom_corpus", "forms": ["10-K"]}),
        encoding="utf-8",
    )

    responses = iter(["2", str(custom)])  # Scope 2, then a custom policy path
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    captured = {}

    def fake_plan(catalog_path, output_root, **kwargs):
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["scope"] == "policy"
    assert captured["selection_policy_path"] == str(custom)


def test_main_help_returns_zero() -> None:
    assert run.main(["--help"]) == 0


def test_interactive_menu_status_then_exit(monkeypatch, capsys) -> None:
    responses = iter(["4", "0"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))
    monkeypatch.setattr(
        discovery, "status", lambda *a, **k: {"catalogs": [], "plans": []}
    )
    assert run.interactive_menu() == 0
    out = capsys.readouterr().out
    assert "Show status" in out


def test_interactive_menu_invalid_then_exit(monkeypatch) -> None:
    responses = iter(["9", "0"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))
    assert run.interactive_menu() == 0


def _build_source(tmp_path):
    source = tmp_path / "submission_metadata.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [row("0000000001")], schema=schemas.SUBMISSION_METADATA_SCHEMA
        ),
        source,
    )
    (tmp_path / "merge_report.json").write_text("{}", encoding="utf-8")
    return source


def test_materialize_and_plan_emit_stage_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    source = _build_source(tmp_path)
    events: list[dict] = []
    result = materializer.materialize(
        str(source), str(tmp_path / "catalogs"), progress=events.append
    )
    stages = [event["stage"] for event in events if event["type"] == "merge_stage"]
    assert stages == [
        "validate_source",
        "company_profiles",
        "targets:part-00000.parquet",
        "publish_manifest",
    ]
    assert events[1]["rows"] == 1
    # The announced unit total matches the emitted stage count exactly.
    target_event = next(
        event for event in events if event.get("stage") == "targets:part-00000.parquet"
    )
    assert target_event["rows"] == 1

    plan_events: list[dict] = []
    target_plan.plan(
        result["catalog_id"], str(tmp_path / "runs"), progress=plan_events.append
    )
    plan_stages = [
        event["stage"] for event in plan_events if event["type"] == "merge_stage"
    ]
    assert plan_stages == ["select_targets", "targets:10-K", "publish_plan"]
    assert plan_events[0]["forms"] == 1
    assert plan_events[0]["total_units"] == len(plan_stages)
    assert plan_events[1]["rows"] == 1


def test_materialize_appends_multiple_cik_batches(tmp_path) -> None:
    source = tmp_path / "submission_metadata.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [row("0000000002"), row("0000000001")],
            schema=schemas.SUBMISSION_METADATA_SCHEMA,
        ),
        source,
    )
    (tmp_path / "merge_report.json").write_text("{}", encoding="utf-8")

    result = materializer.materialize(
        str(source),
        str(tmp_path / "catalogs"),
        source_batch_size=1,
    )

    cat_id = result.get("snapshot_id", result.get("catalog_id"))
    target = tmp_path / "catalogs" / cat_id / "filing_targets" / "part-00000.parquet"
    assert pq.read_table(target).num_rows == 2


def test_phase2_config_serializes_target_forms_and_amendment() -> None:
    cfg = phase_config.Phase2Config(
        source_batch_size=500,
        target_forms=("10-K", "10-Q"),
        amendment="original",
    )
    data = cfg.to_dict()
    assert data["source_batch_size"] == 500
    assert data["target_forms"] == ["10-K", "10-Q"]
    assert data["amendment"] == "original"
    restored = phase_config.Phase2Config.from_dict(data)
    assert restored.target_forms == ("10-K", "10-Q")
    assert restored.amendment == "original"


def test_phase2_config_normalizes_target_forms() -> None:
    cfg = phase_config.Phase2Config(
        target_forms=("  10-k  ", "10-Q", "", "8-K"),
    )
    assert cfg.target_forms == ("10-K", "10-Q", "8-K")


def test_phase2_config_rejects_invalid_amendment() -> None:
    with pytest.raises(ValueError, match="amendment must be both"):
        phase_config.Phase2Config(amendment="invalid")


def test_plan_menu_uses_config_defaults_for_full_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    config_path = tmp_path / "filing_extraction" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "config": {
                    "target_forms": ["10-K", "10-Q"],
                    "amendment": "original",
                },
            }
        ),
        encoding="utf-8",
    )
    catalog = {"catalog_id": "catalog-1", "target_rows": 100, "form_count": 5}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])
    responses = iter(["1", "", ""])
    captured = {}
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    def fake_plan(catalog_path, output_root, **kwargs):
        captured["catalog"] = catalog_path
        captured["output_root"] = output_root
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["forms"] == ("10-K", "10-Q")
    assert captured["amendment"] == "original"


def test_plan_menu_allows_form_override_from_config_default(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    config_path = tmp_path / "filing_extraction" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "config": {
                    "target_forms": ["10-K"],
                    "amendment": "both",
                },
            }
        ),
        encoding="utf-8",
    )
    catalog = {"catalog_id": "catalog-1", "target_rows": 100, "form_count": 5}
    monkeypatch.setattr(run.discovery, "discover_catalogs", lambda *_args: [catalog])
    responses = iter(["1", "8-K, 10-Q", ""])
    captured = {}
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(responses))

    def fake_plan(catalog_path, output_root, **kwargs):
        captured["catalog"] = catalog_path
        captured["output_root"] = output_root
        captured.update(kwargs)
        return {"run_id": "r"}

    monkeypatch.setattr(run, "plan", fake_plan)

    run._menu_plan()

    assert captured["forms"] == ("8-K", "10-Q")
    assert captured["amendment"] == "both"
