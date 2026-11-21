"""F1 equivalence: the CLI surface and core build_plan build ONE plan.

The same fixed inputs go through the CLI plan verb and a
hand-assembled core PlanRequest; both land on one plan_id.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from edgar_sec.engine.tables.extraction.core.profiles import PROFILES, registry_state
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.table_classification.cli import main
from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.planner import (
    DocumentTargetRow,
    FilingRow,
    Plan,
    PlanRequest,
    ProfileApplicationRow,
    build_plan,
    read_plan,
    work_item_id_for,
)
from edgar_sec.pipelines.table_classification.schemas import PLAN_FORMAT_VERSION

_ACCESSIONS = ("0000000002-26-000002", "0000000001-26-000001")
_CREATED_AT = "2026-11-15T00:00:00Z"


def _direct_request() -> PlanRequest:
    """The fixed inputs as a core request, assembled without the translator."""
    accessions = tuple(sorted(_ACCESSIONS))
    filings = tuple(
        FilingRow(accession=a, cik=None, form="", filing_date=None, stratum="B")
        for a in accessions
    )
    application = tuple(
        ProfileApplicationRow(
            accession=a,
            family=profile.family,
            kind=profile.kind,
            vocabulary_seat=profile.vocabulary_seat,
        )
        for profile in PROFILES
        for a in accessions
    )
    exhibit_types: list[str] = []
    for profile in PROFILES:
        for link in profile.exhibit_links:
            if "B" not in link.strata:
                continue
            exhibit_type = link.exhibit_type.strip().upper()
            if exhibit_type and exhibit_type not in exhibit_types:
                exhibit_types.append(exhibit_type)
    targets: list[DocumentTargetRow] = []
    for accession in accessions:
        targets.append(
            DocumentTargetRow(
                accession=accession,
                target_role="primary",
                target_type="primary",
                optional=False,
            )
        )
        targets.extend(
            DocumentTargetRow(
                accession=accession,
                target_role="exhibit",
                target_type=exhibit_type,
                optional=True,
            )
            for exhibit_type in exhibit_types
        )
    return PlanRequest(
        registry_state=registry_state(),
        source_snapshot_id="snap-1",
        normalize_version="",
        renderer_version="",
        filings=filings,
        profile_application=application,
        document_targets=tuple(targets),
        created_at=_CREATED_AT,
    )


def _manifest(plan: Plan) -> dict:
    return json.loads((plan.root / "plan.json").read_text(encoding="utf-8"))


def test_cli_surface_and_core_build_the_same_plan(tmp_path, capsys) -> None:  # noqa: ANN001
    cli_root = tmp_path / "cli"
    code = main(
        [
            "plan",
            "--accession",
            _ACCESSIONS[0],
            "--accession",
            _ACCESSIONS[1],
            "--snapshot-id",
            "snap-1",
            "--stratum",
            "B",
            "--output",
            str(cli_root / "table_classification" / "plans"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    cli_paths = ClassificationPaths(artifacts_root=cli_root)
    cli_plan = read_plan(cli_paths, payload["plan_id"])

    core_paths = ClassificationPaths(artifacts_root=tmp_path / "core")
    request = _direct_request()
    result = build_plan(request, core_paths)
    core_plan = read_plan(core_paths, result.plan_id)

    assert cli_plan.plan_id == core_plan.plan_id == result.plan_id
    assert cli_plan.plan_id.startswith("tcplan-")
    assert payload["plan_id"] == core_plan.plan_id

    cli_items = [(item.work_item_id, item.accession) for item in cli_plan.work_items]
    core_items = [(item.work_item_id, item.accession) for item in core_plan.work_items]
    assert cli_items == core_items
    for item in core_plan.work_items:
        assert item.work_item_id == work_item_id_for(core_plan.plan_id, item.accession)
        assert item.work_item_id.startswith("wi-")

    for plan in (cli_plan, core_plan):
        provenance = plan.provenance
        assert provenance["plan_format_version"] == PLAN_FORMAT_VERSION
        assert provenance["registry_state"] == registry_state()
        assert str(provenance["registry_state"]).startswith("sha256:")
        assert provenance["source_snapshot_id"] == "snap-1"
        assert provenance["profile_count"] == len(request.profile_application)
        assert provenance["profile_count"] == len(plan.profile_application)
        assert provenance["filing_count"] == len(request.filings)
        assert provenance["target_count"] == len(request.document_targets)
        assert provenance["work_item_count"] == len(request.filings)

    assert cli_plan.filings == core_plan.filings
    assert cli_plan.profile_application == core_plan.profile_application
    assert cli_plan.document_targets == core_plan.document_targets

    targets = {
        (row.target_role, row.target_type, row.optional)
        for row in core_plan.document_targets
    }
    assert targets == {("primary", "primary", False), ("exhibit", "EX-13", True)}
    exhibit = next(
        row for row in core_plan.document_targets if row.target_role == "exhibit"
    )
    assert exhibit.geometry_expectation == "expected"
    assert exhibit.provenance_route == "render_to_txt"
    assert exhibit.document_name is None
    assert core_plan.profile_application[0].vocabulary_seat

    for plan in (cli_plan, core_plan):
        manifest = _manifest(plan)
        assert manifest["plan_id"] == plan.plan_id
        for relation, digest in manifest["relations"].items():
            path = plan.root / f"{relation}.parquet"
            assert digest["sha256"] == file_sha256(path)
    cli_relations = _manifest(cli_plan)["relations"]
    core_relations = _manifest(core_plan)["relations"]
    for relation in (
        "filings",
        "profile_application",
        "document_targets",
        "work_items",
    ):
        assert cli_relations[relation] == core_relations[relation]
    cli_provenance = dict(cli_plan.provenance)
    core_provenance = dict(core_plan.provenance)
    cli_created = cli_provenance.pop("created_at")
    core_created = core_provenance.pop("created_at")
    assert cli_provenance == core_provenance
    for created in (cli_created, core_created):
        datetime.strptime(str(created), "%Y-%m-%dT%H:%M:%SZ")

    rebuilt = build_plan(request, core_paths)
    assert rebuilt.plan_id == result.plan_id
    assert rebuilt.reused is True


def test_plan_bundle_lands_under_the_canonical_plans_root(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path)
    result = build_plan(_direct_request(), paths)
    expected = Path(tmp_path) / "table_classification" / "plans" / result.plan_id
    assert result.root == expected
    assert (result.root / "plan.json").is_file()
