"""The interactive augmentation journey, settled before request budget is spent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest
from edgar_sec.pipelines.metadata_sync import augment_flow as flow
from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.augmentation import AugmentPreflight
from edgar_sec.pipelines.metadata_sync.cli import main
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.operator import WizardState
from edgar_sec.pipelines.metadata_sync.options import plan_options
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import (
    FakeSession,
    build_test_client,
    cik_payload,
    fixture_path,
    roster_of,
)

MINI = ["0000001985", "0000001761", "0000000020", "0000037996"]


@pytest.fixture()
def state(tmp_path: Path) -> WizardState:
    return WizardState(artifacts_root=str(tmp_path))


def _publish_snapshot_stub(state: WizardState, snapshot_id: str) -> None:
    """Enough for base selection, which reads manifests only."""
    metadata = state.metadata()
    path = metadata.snapshot_manifest(snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"snapshot_id": snapshot_id, "row_count": 3, "parts": []}),
        encoding="utf-8",
    )
    catalog = DAGCatalog(metadata.snapshots_root)
    node = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=snapshot_id,
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp-" + snapshot_id,
    )
    catalog.record_node(node)


def _fake_preflight(*, delta_rows: int = 1, requested: int = 4, base: str = "base"):
    """A stand-in preflight, so these tests assert interaction order only."""
    return AugmentPreflight(
        base_snapshot_id=base,
        requested_count=requested,
        already_present_count=requested - delta_rows,
        delta_count=delta_rows,
    )


def _empty_preflight(requested: int = 4, base: str = "base"):
    return AugmentPreflight(
        base_snapshot_id=base,
        requested_count=requested,
        already_present_count=requested,
        delta_count=0,
    )


def _stub_journey(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, *, delta_rows: int = 1
) -> list[dict]:
    """Wire an augment run whose cohort and arithmetic are already decided."""
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), state.metadata().artifacts_root
    )
    monkeypatch.setattr(
        flow,
        "ask_augment_cohort",
        lambda _s: plan_options(
            cohort=record.cohort_id,
            artifacts_root=Path(state.artifacts_root),
        ),
    )
    monkeypatch.setattr(
        flow,
        "preflight_augment",
        lambda *a, **k: _fake_preflight(delta_rows=delta_rows),
    )
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: True)
    seen: list[dict] = []
    monkeypatch.setattr(
        flow, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )
    return seen


# ------------------------------------------------------------ the happy paths


def test_a_blank_new_snapshot_id_means_derive_it(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requiring a hand-typed id was the one identity not derived from content."""
    _publish_snapshot_stub(state, "base")
    seen = _stub_journey(state, monkeypatch)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.run_augment(state)

    assert seen[0]["base_snapshot_id"] == "base"
    assert seen[0]["new_snapshot_id"] == ""


def test_the_base_defaults_to_the_current_snapshot(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Augmenting usually means augmenting what is published."""
    _publish_snapshot_stub(state, "older")
    _publish_snapshot_stub(state, "published-id")
    catalog = DAGCatalog(state.metadata().snapshots_root)
    catalog.write_pointer("main", "published-id")
    seen = _stub_journey(state, monkeypatch)
    # A blank base answer keeps the pointer where it is.
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": "")

    flow.run_augment(state)

    assert seen[0]["base_snapshot_id"] == "published-id"


def test_an_earlier_snapshot_can_be_chosen_as_the_base(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backfilling onto an older base is a legitimate correction."""
    _publish_snapshot_stub(state, "older")
    _publish_snapshot_stub(state, "current")
    catalog = DAGCatalog(state.metadata().snapshots_root)
    catalog.write_pointer("main", "current")
    seen = _stub_journey(state, monkeypatch)
    # Snapshots list in chronological order, so "older" is choice 1 and "current" choice 2.
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": "1")

    flow.run_augment(state)

    assert seen[0]["base_snapshot_id"] == "older"


def test_a_declined_fetch_runs_nothing(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _publish_snapshot_stub(state, "base")
    seen = _stub_journey(state, monkeypatch)
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: False)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.run_augment(state)

    assert seen == []
    assert "nothing was fetched" in capsys.readouterr().out


# ------------------------------------------------------------- the no-op path


def test_an_already_covered_cohort_never_asks_to_fetch(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Nothing to fetch must not be discovered only after every question is asked."""
    _publish_snapshot_stub(state, "base")
    asked: list[str] = []
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), state.metadata().artifacts_root
    )
    monkeypatch.setattr(
        flow,
        "ask_augment_cohort",
        lambda _s: plan_options(
            cohort=record.cohort_id,
            artifacts_root=Path(state.artifacts_root),
        ),
    )
    monkeypatch.setattr(
        flow, "preflight_augment", lambda *a, **k: _empty_preflight(base="base")
    )
    monkeypatch.setattr(
        flow, "confirm_network", lambda *a, **k: asked.append("network") or True
    )
    called: list[object] = []
    monkeypatch.setattr(flow, "cmd_augment", lambda *a, **k: called.append("augment"))
    monkeypatch.setattr(
        flow, "prompt_text", lambda label, default="": asked.append(label) or default
    )

    flow.run_augment(state)

    out = capsys.readouterr().out
    assert called == []
    assert asked == []
    assert "already holds every requested CIK" in out
    assert "current snapshot is unchanged" in out


def test_the_operator_sees_the_arithmetic_not_just_the_outcome(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _publish_snapshot_stub(state, "base")
    _stub_journey(state, monkeypatch, delta_rows=2)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.run_augment(state)

    out = capsys.readouterr().out
    assert "4 requested" in out
    assert "already in base base" in out
    assert "2 to fetch" in out


def test_an_unreadable_base_is_reported_not_raised(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A base that cannot be read must not read as an empty one."""
    _publish_snapshot_stub(state, "base")
    seen = _stub_journey(state, monkeypatch)

    def boom(*_a, **_k):
        raise FileNotFoundError("snapshot payload not found")

    monkeypatch.setattr(flow, "preflight_augment", boom)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.run_augment(state)

    assert seen == []
    assert "cannot plan that augmentation" in capsys.readouterr().out


def test_no_published_snapshot_cancels_the_augment(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """There is nothing to augment without a base."""
    seen = _stub_journey(state, monkeypatch)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.run_augment(state)

    assert seen == []
    assert "no published snapshot to augment" in capsys.readouterr().out


def test_published_cohorts_are_the_only_picker_choices(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), state.metadata().artifacts_root
    )
    observed: dict[str, Any] = {}

    def choose(items, *, prompt_label):
        observed["keys"] = [item.key for item in items]
        observed["labels"] = [item.label for item in items]
        observed["prompt"] = prompt_label
        return items[0]

    monkeypatch.setattr(flow, "prompt_paginated_choice", choose)
    options = flow.ask_augment_cohort(state)

    assert options is not None
    assert options.cohort == record.cohort_id
    assert observed["keys"] == [record.cohort_id]
    assert observed["prompt"] == "Cohort to augment"
    assert "CIKs" in observed["labels"][0]


def test_no_published_cohorts_cancels_selection(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(flow, "prompt_paginated_choice", lambda items, **_: None)
    assert flow.ask_augment_cohort(state) is None
    assert "no published cohorts" in capsys.readouterr().out


def test_the_menu_still_delegates_augmentation_to_the_journey() -> None:
    """The action is a hand-off, so the menu owns no cohort logic."""
    menu = {action.key: action for action in operator_module.build_operator_menu()}
    assert menu["4"].label == "Augment published snapshot"
    assert callable(menu["d"].callback)
    assert callable(menu["p"].callback)


# ------------------------------------------------- the command, through ``main``


def _parse_output(out: str) -> dict[str, Any]:
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        pass
    result: dict[str, Any] = {}
    for raw_line in out.splitlines():
        if not raw_line.startswith("  "):
            continue
        line = raw_line.strip()
        if not line or line.startswith("-"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, val = parts
            if val.isdigit() and key in (
                "row_count",
                "chunk_size",
                "chunk_count",
                "part_count",
                "duplicate_count",
                "base_row_count",
                "delta_row_count",
                "total_row_count",
                "requested_cik_count",
                "already_present_count",
                "new_cik_count",
            ):
                result[key] = int(val)
            elif val == "True":
                result[key] = True
            elif val == "False":
                result[key] = False
            elif val == "none":
                result[key] = None
            else:
                result[key] = val
        elif len(parts) == 1:
            result[parts[0]] = ""
    return result


def _publish_base_via_cli(session, tmp_path, capsys, monkeypatch) -> str:
    """Publish a real base snapshot over the CLI, and return its snapshot id."""
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    assert (
        main(
            [
                "plan",
                "--cohort",
                record.cohort_id,
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    planned = _parse_output(capsys.readouterr().out)
    _seed_session_for(monkeypatch)
    assert (
        main(["run", "--plan-id", planned["plan_id"], "--artifacts", str(tmp_path)])
        == 0
    )
    capsys.readouterr()
    assert (
        main(["merge", "--plan-id", planned["plan_id"], "--artifacts", str(tmp_path)])
        == 0
    )
    return _parse_output(capsys.readouterr().out)["snapshot_id"]


def _seed_session(session) -> None:
    """Register one submissions payload per CIK in the committed mini manifest."""
    for cik in MINI:
        session.register(submissions_url(cik), cik_payload(cik, f"COMPANY {cik}"))


def _seed_session_for(monkeypatch) -> None:
    session = FakeSession()
    _seed_session(session)
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.run.build_client",
        lambda: build_test_client(session),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.augment.build_client",
        lambda: build_test_client(session),
    )


# -------------------------------------------------------------------- augment


def test_augment_fetches_only_what_the_base_is_missing(
    session: FakeSession, tmp_path: Path, capsys, monkeypatch
) -> None:
    """A selected published cohort is reduced against the base snapshot."""
    base = _publish_base_via_cli(session, tmp_path, capsys, monkeypatch)
    requested = tmp_path / "requested.csv"
    requested.write_text(
        "cik,name\n" + "".join(f"{cik},CO {cik}\n" for cik in [*MINI, "0000005555"]),
        encoding="utf-8",
    )
    record, _paths, _roster = publish_test_cohort(requested, tmp_path)
    session.register(submissions_url("0000005555"), cik_payload("0000005555", "NEWCO"))
    assert (
        main(
            [
                "augment",
                "--cohort",
                record.cohort_id,
                "--base-snapshot-id",
                base,
                "--artifacts",
                str(tmp_path),
            ]
        )
        == 0
    )
    result = _parse_output(capsys.readouterr().out)
    assert result["no_op"] is False
    assert result["base_snapshot_id"] == base
    assert result["delta_row_count"] == 1
    assert result["refetched_ciks"] == "0000005555"
    assert result["total_row_count"] == result["base_row_count"] + 1
    assert result["already_present_count"] == 4


def test_augment_reports_a_covered_cohort_as_a_successful_no_op(
    session: FakeSession, tmp_path: Path, capsys, monkeypatch
) -> None:
    """The ordinary case for a stale seed: nothing fetched, written, or moved."""
    metadata = resolve_metadata_paths(tmp_path)
    base = _publish_base_via_cli(session, tmp_path, capsys, monkeypatch)
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    pointer_before = current_snapshot_id(metadata)
    plans_root = metadata.metadata_root / "plans"
    plans_before = sorted(p.name for p in plans_root.iterdir())
    # Client construction costs request budget, not merely its first request.
    clients: list[object] = []
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.augment.build_client",
        lambda: clients.append(1) or None,
    )

    exit_code = main(
        [
            "augment",
            "--cohort",
            record.cohort_id,
            "--base-snapshot-id",
            base,
            "--artifacts",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    raw = capsys.readouterr().out
    result = _parse_output(raw)
    assert result["no_op"] is True
    assert result["delta_row_count"] == 0
    assert result.get("refetched_ciks", "") == ""
    assert result["requested_cik_count"] == result["already_present_count"] == 4
    assert result["total_row_count"] == 4
    assert "nothing published" in raw
    # No client, no new plan directory, no pointer movement.
    assert clients == []
    assert sorted(p.name for p in plans_root.iterdir()) == plans_before
    assert current_snapshot_id(metadata) == pointer_before


def test_merge_refuses_a_delta_plan_and_leaves_the_snapshot_intact(
    session: FakeSession, tmp_path: Path, capsys, monkeypatch
) -> None:
    """The generic merge path must not be able to publish a delta alone."""
    metadata = resolve_metadata_paths(tmp_path)
    base = _publish_base_via_cli(session, tmp_path, capsys, monkeypatch)
    manifest_before = metadata.snapshot_manifest(base).read_bytes()

    # An augment the base does not fully cover writes a delta plan.
    session.register(submissions_url("0000005555"), cik_payload("0000005555", "NEWCO"))
    delta_csv = tmp_path / "delta.csv"
    delta_csv.write_text("cik,name\n0000005555,NEWCO\n", encoding="utf-8")
    record, _paths, _roster = publish_test_cohort(delta_csv, tmp_path)
    main(
        [
            "augment",
            "--cohort",
            record.cohort_id,
            "--base-snapshot-id",
            base,
            "--new-snapshot-id",
            "aug",
            "--artifacts",
            str(tmp_path),
        ]
    )
    augmented = _parse_output(capsys.readouterr().out)
    assert augmented["no_op"] is False
    assert augmented["delta_row_count"] == 1
    delta_plan = augmented["delta_plan_id"]
    assert main(["merge", "--plan-id", delta_plan, "--artifacts", str(tmp_path)]) == 1
    assert "delta plan" in capsys.readouterr().err
    # The correctly augmented snapshot and the pointer are both untouched.
    assert current_snapshot_id(metadata) == "aug"
    assert metadata.snapshot_manifest(base).read_bytes() == manifest_before
    assert metadata.snapshot_manifest("aug").is_file()


def test_the_picker_pages_through_catalog_cohorts(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runtime picker receives every published cohort from catalog pages."""
    from types import SimpleNamespace

    first_page = [
        SimpleNamespace(cohort_id=f"cohort-{index}", name=None, row_count=1)
        for index in range(100)
    ]
    second_page = [SimpleNamespace(cohort_id="last-cohort", name="last", row_count=2)]

    class Catalog:
        def __init__(self, _paths):
            self.calls = []

        def list_cohorts(self, *, limit, offset):
            self.calls.append((limit, offset))
            return first_page if offset == 0 else second_page

    catalog = Catalog(None)
    monkeypatch.setattr(flow, "CohortCatalog", lambda _paths: catalog)
    observed: dict[str, Any] = {}

    def choose(items, *, prompt_label):
        observed["items"] = items
        observed["prompt_label"] = prompt_label
        return items[-1]

    monkeypatch.setattr(flow, "prompt_paginated_choice", choose)

    options = flow.ask_published_cohort(state, purpose="Cohort to plan over")

    assert options is not None
    assert options.cohort == "last-cohort"
    assert catalog.calls == [(100, 0), (100, 100)]
    assert len(observed["items"]) == 101
    assert observed["prompt_label"] == "Cohort to plan over"
