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
from edgar_sec.pipelines.metadata_sync.registry import registry_id_for
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_UNIVERSE_NAME,
    SOURCE_URL,
    refresh_company_tickers,
)
from tests.support import (
    FakeSession,
    build_test_client,
    build_test_http,
    cik_payload,
    fixture_path,
    roster_of,
)

# A live listing naming a registrant the curated seed does not cover.
SOURCE_TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    "2": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}

MINI = ["0000001985", "0000001761", "0000000020", "0000037996"]

TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}


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


def _publish_source(state: WizardState, snapshot_id: str, *, retrieved_at: str) -> None:
    """Publish a source manifest so cohort discovery reads a real one."""
    path = state.metadata().source_manifest_file(SOURCE_NAME, snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_kind": "metadata_source_snapshot",
                "source": SOURCE_NAME,
                "snapshot_id": snapshot_id,
                "retrieved_at": retrieved_at,
                "unique_cik_count": 2,
                "listing_row_count": 2,
            }
        ),
        encoding="utf-8",
    )


def _publish_universe_source(
    state: WizardState, snapshot_id: str, *, retrieved_at: str = "2026-10-02T00:00:00Z"
) -> None:
    """Publish a universe source manifest so the picker can offer it."""
    path = state.metadata().source_manifest_file(SOURCE_UNIVERSE_NAME, snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_kind": "metadata_source_snapshot",
                "source": SOURCE_UNIVERSE_NAME,
                "snapshot_id": snapshot_id,
                "retrieved_at": retrieved_at,
                "distinct_cik_count": 987472,
                "line_count": 1061751,
            }
        ),
        encoding="utf-8",
    )


#: With no published rosters the menu is 1 csv, 2 registry, 3 universe, 4 another path.
UNIVERSE_CHOICE = "3"


def _choose(answer: str):
    """Answer the cohort menu with one entry and every other prompt with its default."""

    def prompt(label: str, default: str = "") -> str:
        return answer if label == "Cohort number" else default

    return prompt


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
    monkeypatch.setattr(
        flow,
        "ask_augment_cohort",
        lambda _s: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"),
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
    monkeypatch.setattr(
        flow,
        "ask_augment_cohort",
        lambda _s: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"),
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


# ---------------------------------------------------------------- the cohort


def _write_seed(tmp_path: Path, name: str = "seed.csv") -> Path:
    path = tmp_path / name
    path.write_text(
        "cik,name\n0000001985,ACCEL\n0000001761,TRANZONIC\n", encoding="utf-8"
    )
    return path


def test_the_seed_and_the_source_listings_are_offered_together(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The union is the cohort that reflects who files now, not who filed then."""
    seed = _write_seed(tmp_path)
    _publish_source(state, "src-1", retrieved_at="2026-09-30T00:00:00Z")
    prompts: list[str] = []
    monkeypatch.setattr(
        flow,
        "ensure_registry",
        lambda **kwargs: {
            "registry_id": registry_id_for(kwargs["source_snapshot_id"], "fp"),
            "row_count": 2,
            "reused": False,
        },
    )
    monkeypatch.setattr(
        flow,
        "prompt_text",
        lambda label, default="": (
            prompts.append(label) or ("2" if label == "Cohort number" else default)
        ),
    )
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)

    options = flow.ask_augment_cohort(state)

    out = capsys.readouterr().out
    assert options is not None
    assert options.registry_id
    assert "seed and active listings" in out
    # The seed is named and the observation aged, because a source can be stale.
    assert str(seed) in out
    assert "2026-09-30T00:00:00Z" in out
    assert "Cohort number" in prompts


def test_a_missing_source_is_offered_a_consented_refresh(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A live SEC request defaults to no."""
    seed = _write_seed(tmp_path)
    refreshed: list[Path] = []
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: False)
    monkeypatch.setattr(flow, "cmd_refresh", lambda root: refreshed.append(root))
    monkeypatch.setattr(
        flow,
        "prompt_text",
        lambda label, default="": "2" if label == "Cohort number" else default,
    )

    assert flow.ask_augment_cohort(state) is None

    out = capsys.readouterr().out
    assert "No SEC listing source snapshot is published" in out
    # The decline names what is still possible, not a fetch that never started.
    assert "the seed alone can still be used as a cohort" in out
    assert refreshed == []


def test_a_consented_source_refresh_targets_the_session_artifacts_root(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project-default root would write outside the tree the session reads."""
    seed = _write_seed(tmp_path)
    refreshed: list[Path] = []
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: True)
    monkeypatch.setattr(flow, "cmd_refresh", lambda root: refreshed.append(root))
    monkeypatch.setattr(
        flow,
        "prompt_text",
        lambda label, default="": "2" if label == "Cohort number" else default,
    )

    flow.ask_augment_cohort(state)

    assert refreshed == [tmp_path]


def test_a_published_comparison_is_offered_as_a_cohort(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A roster the operator already published stays reachable by hand."""
    seed = _write_seed(tmp_path)
    _publish_source(state, "src-1", retrieved_at="2026-09-30T00:00:00Z")
    _publish_roster(state, "reg-1", source_snapshot_id="src-1")
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    # Choice 2 is the first published roster, after the source-aware option.
    monkeypatch.setattr(
        flow,
        "prompt_text",
        lambda label, default="": "2" if "Cohort number" in label else default,
    )

    options = flow.ask_augment_cohort(state)

    assert options is not None
    assert options.registry_id == "reg-1"
    assert "reg-1" in capsys.readouterr().out


def test_a_missing_seed_path_is_reported(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        flow, "DEFAULT_INPUT", "uploads/definitely-absent.csv", raising=False
    )
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    assert flow.ask_augment_cohort(state) is None
    assert "does not exist" in capsys.readouterr().out


def test_a_blank_seed_cancels(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": "")
    assert flow.ask_augment_cohort(state) is None


def _publish_roster(state: WizardState, registry_id: str, *, source_snapshot_id: str):
    """Publish a real registry so the cohort list reads genuine manifests."""
    from edgar_sec.pipelines.metadata_sync.registry import (
        EFFECTIVE_INPUT_MANIFEST_KIND,
        REGISTRY_SCHEMA_VERSION,
    )
    from edgar_sec.pipelines.metadata_sync.roster import (
        ROSTER_MANIFEST_KIND,
        ROSTER_SCHEMA_VERSION,
        write_roster,
    )

    metadata = state.metadata()
    roster_path = metadata.effective_cik_roster(registry_id)
    roster_path.parent.mkdir(parents=True, exist_ok=True)
    roster = roster_of(("0000001985", "0000001761"))
    digest = write_roster(roster, roster_path)
    roster_path.with_name(roster_path.name + ".manifest.json").write_text(
        json.dumps(
            {
                "manifest_kind": ROSTER_MANIFEST_KIND,
                "schema_version": ROSTER_SCHEMA_VERSION,
                "registry_id": registry_id,
                "artifact_sha256": digest,
                "roster_id": roster.roster_id,
            }
        ),
        encoding="utf-8",
    )
    effective = metadata.effective_input_file(registry_id)
    effective.write_text("cik,name\n0000001985,ACCEL\n", encoding="utf-8")
    (metadata.registry_manifest_root(registry_id) / "..").mkdir(
        parents=True, exist_ok=True
    )
    effective.with_name("effective_cik_input.csv.manifest.json").write_text(
        json.dumps(
            {
                "manifest_kind": EFFECTIVE_INPUT_MANIFEST_KIND,
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "registry_id": registry_id,
                "source_snapshot_id": source_snapshot_id,
                "curated_cik_count": 2,
                "active_cik_count": 2,
                "artifact_path": str(effective),
                "artifact_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )


def test_the_menu_still_delegates_augmentation_to_the_journey() -> None:
    """The action is a hand-off, so the menu owns no cohort logic."""
    menu = {action.key: action for action in operator_module.build_operator_menu()}
    assert menu["4"].label == "Augment published snapshot"
    assert callable(menu["5"].callback)


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
    assert (
        main(
            [
                "plan",
                "--input",
                str(fixture_path("cik_sec_mini.csv")),
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
    """A source-derived CIK absent from the base is fetched and published."""
    session.register_bytes(SOURCE_URL, json.dumps(SOURCE_TICKERS).encode("utf-8"))
    metadata = resolve_metadata_paths(tmp_path)
    published = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    main(
        [
            "sources",
            "compare",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--source-manifest",
            str(metadata.source_manifest_file(SOURCE_NAME, published["snapshot_id"])),
            "--artifacts",
            str(tmp_path),
        ]
    )
    registry_id = _parse_output(capsys.readouterr().out)["registry_id"]
    capsys.readouterr()

    base = _publish_base_via_cli(session, tmp_path, capsys, monkeypatch)

    # NEWCO is in the live listing but not the seed, so the union is not covered.
    session.register(submissions_url("0000005555"), cik_payload("0000005555", "NEWCO"))
    assert (
        main(
            [
                "augment",
                "--roster",
                registry_id,
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
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
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
    main(
        [
            "augment",
            "--input",
            str(delta_csv),
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


# ---------------------------------------------------- the shared cohort picker


def test_the_universe_is_offered_once_a_snapshot_is_published(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The universe is a cohort like any other, so it belongs in the same menu."""
    seed = _write_seed(tmp_path)
    _publish_universe_source(state, "uni-1")
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: False)
    monkeypatch.setattr(flow, "prompt_text", _choose(UNIVERSE_CHOICE))

    options = flow.ask_augment_cohort(state)

    out = capsys.readouterr().out
    assert options is not None
    assert options.universe
    assert "full registrant universe" in out
    assert "987,472 CIKs" in out
    assert "uni-1" in out


def test_the_universe_is_absent_until_a_snapshot_exists(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """An option that would fail later must not be offered."""
    seed = _write_seed(tmp_path)
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    flow.ask_augment_cohort(state)

    assert "full registrant universe" not in capsys.readouterr().out


def test_a_csv_cohort_needs_no_published_source(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The regression: asking for a CSV must not require a ticker snapshot."""
    seed = _write_seed(tmp_path)
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(
        flow, "confirm_network", lambda *a, **k: pytest.fail("asked to fetch")
    )
    monkeypatch.setattr(flow, "prompt_text", lambda label, default="": default)

    options = flow.ask_augment_cohort(state)

    assert options is not None
    assert options.input_path == seed
    assert "No SEC listing source snapshot" not in capsys.readouterr().out


def test_the_picker_is_the_same_one_planning_uses(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Two near-duplicate pickers would drift; there is one, labelled per purpose."""
    seed = _write_seed(tmp_path)
    _publish_universe_source(state, "uni-1")
    monkeypatch.setattr(flow, "DEFAULT_INPUT", str(seed), raising=False)
    monkeypatch.setattr(flow, "confirm_network", lambda *a, **k: False)
    monkeypatch.setattr(flow, "prompt_text", _choose(UNIVERSE_CHOICE))

    flow.ask_cohort_source(state, purpose="Cohort to plan over")

    assert "Cohort to plan over:" in capsys.readouterr().out
