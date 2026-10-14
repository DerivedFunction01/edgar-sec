"""Immutable human labels for pinned exhibit review artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import validate_path_component
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json

LabelOutcome = Literal["positive", "negative", "ambiguous"]
ObservedKind = Literal[
    "exhibit", "primary_report", "data_file", "graphic", "paper", "unknown"
]
AnnotationKind = Literal["independent", "adjudication"]


class ReviewLabelError(ValueError):
    pass


def _required_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ReviewLabelError(f"{name} is invalid")
    return value.strip()


def _review_context(artifact: dict[str, object]) -> dict[str, object]:
    digest = artifact.get("artifact_sha256")
    unsigned = dict(artifact)
    unsigned.pop("artifact_sha256", None)
    if (
        artifact.get("artifact_type") != "document_acquisition.processing_review"
        or artifact.get("artifact_version") != 3
        or not is_sha256_hex_digest(digest)
        or canonical_hash(unsigned) != digest
    ):
        raise ReviewLabelError("processing review artifact is invalid or unsupported")
    fixture = artifact.get("fixture")
    processing = artifact.get("processing")
    if not isinstance(fixture, dict) or not isinstance(processing, dict):
        raise ReviewLabelError("processing review identity is invalid")
    assessment = processing.get("exhibit_assessment")
    fingerprint = processing.get("exhibit_assessment_fingerprint")
    if (
        artifact.get("target_role") != "exhibit"
        or not isinstance(assessment, dict)
        or not is_sha256_hex_digest(fingerprint)
        or assessment.get("expected_role") != "exhibit"
        or assessment.get("expected_type") != artifact.get("target_type")
        or not isinstance(assessment.get("expected_identity"), dict)
    ):
        raise ReviewLabelError("review artifact has no eligible exhibit assessment")
    expected_identity = assessment["expected_identity"]
    try:
        identity = ExhibitIdentity(**expected_identity)
        accession = AccessionNumber.from_any(str(artifact["accession"]))
        issuer_cik = Cik.from_raw(accession.raw[:10])
    except (KeyError, TypeError, ValueError) as error:
        raise ReviewLabelError("review artifact identity is invalid") from error
    if (
        not isinstance(fixture.get("fixture_id"), str)
        or not fixture["fixture_id"]
        or not isinstance(fixture.get("capture_id"), str)
        or not fixture["capture_id"]
        or fixture.get("target_id") != artifact.get("target_id")
        or not isinstance(artifact.get("form"), str)
        or not isinstance(artifact.get("target_type"), str)
    ):
        raise ReviewLabelError("review artifact fixture identity is incomplete")
    selected_sha256 = fixture.get("body_sha256")
    if not is_sha256_hex_digest(selected_sha256):
        raise ReviewLabelError("selected-body digest is invalid")
    required_versions = (
        assessment.get("evaluator_version"),
        assessment.get("taxonomy_version"),
        assessment.get("profile_id"),
        assessment.get("profile_version"),
        assessment.get("pack_id"),
        assessment.get("pack_version"),
    )
    if not all(isinstance(value, str) and value for value in required_versions):
        raise ReviewLabelError("assessment version pins are incomplete")
    predicted_outcome = {
        "consistent": "positive",
        "possible_role_mismatch": "negative",
        "insufficient_evidence": "ambiguous",
    }.get(assessment.get("disposition"))
    if predicted_outcome is None:
        raise ReviewLabelError("assessment disposition is unsupported")
    return {
        "fixture_id": fixture.get("fixture_id"),
        "capture_id": fixture.get("capture_id"),
        "target_id": fixture.get("target_id"),
        "accession": str(accession),
        "issuer_cik": str(issuer_cik),
        "accession_year_code": accession.raw[11:13],
        "form": artifact.get("form"),
        "target_type": artifact.get("target_type"),
        "selected_sha256": selected_sha256,
        "processing_review_sha256": digest,
        "assessment_fingerprint": fingerprint,
        "predicted_outcome": predicted_outcome,
        "expected_identity": {
            "authority_id": identity.authority_id,
            "code": identity.code,
        },
        "versions": {
            "evaluator_version": assessment["evaluator_version"],
            "taxonomy_version": assessment["taxonomy_version"],
            "profile_id": assessment["profile_id"],
            "profile_version": assessment["profile_version"],
            "pack_id": assessment["pack_id"],
            "pack_version": assessment["pack_version"],
        },
    }


def _utc_timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ReviewLabelError("annotation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ReviewLabelError("annotation timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ReviewLabelError("annotation timestamp must be UTC")
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_review_label(
    review_artifact: dict[str, object],
    *,
    outcome: LabelOutcome,
    observed_kind: ObservedKind,
    annotator_id: str,
    annotated_at_utc: str,
    evidence_ref: str,
    rationale: str = "",
    observed_identity: ExhibitIdentity | None = None,
    annotation_kind: AnnotationKind = "independent",
    supersedes_label_sha256: tuple[str, ...] = (),
) -> dict[str, object]:
    context = _review_context(review_artifact)
    if outcome not in {"positive", "negative", "ambiguous"}:
        raise ReviewLabelError("label outcome is invalid")
    if observed_kind not in {
        "exhibit",
        "primary_report",
        "data_file",
        "graphic",
        "paper",
        "unknown",
    }:
        raise ReviewLabelError("observed kind is invalid")
    if annotation_kind not in {"independent", "adjudication"}:
        raise ReviewLabelError("annotation kind is invalid")
    if not isinstance(rationale, str):
        raise ReviewLabelError("annotation rationale is invalid")
    if len(rationale) > 2048:
        raise ReviewLabelError("annotation rationale is too long")
    if observed_identity is not None and not isinstance(
        observed_identity, ExhibitIdentity
    ):
        raise ReviewLabelError("observed exhibit identity is invalid")
    if (observed_kind == "exhibit") != (observed_identity is not None):
        raise ReviewLabelError("observed exhibit identity is inconsistent")
    expected_identity = context["expected_identity"]
    observed = (
        {"authority_id": observed_identity.authority_id, "code": observed_identity.code}
        if observed_identity is not None
        else None
    )
    matches = observed_kind == "exhibit" and observed == expected_identity
    if (outcome == "positive" and not matches) or (outcome == "negative" and matches):
        raise ReviewLabelError("label outcome conflicts with observed identity")
    if annotation_kind == "independent" and supersedes_label_sha256:
        raise ReviewLabelError("independent annotation cannot replace labels")
    if annotation_kind == "adjudication" and len(supersedes_label_sha256) < 2:
        raise ReviewLabelError("adjudication must cite at least two prior labels")
    if len(set(supersedes_label_sha256)) != len(supersedes_label_sha256) or any(
        not is_sha256_hex_digest(value) for value in supersedes_label_sha256
    ):
        raise ReviewLabelError("superseded label digests are invalid")

    unsigned = {
        "artifact_type": "document_acquisition.exhibit_label",
        "artifact_version": 1,
        "label_scope": "planned_exhibit_identity",
        **context,
        "outcome": outcome,
        "observed_kind": observed_kind,
        "observed_identity": observed,
        "annotator_id": _required_text(annotator_id, "annotator ID", 128),
        "annotation_kind": annotation_kind,
        "annotated_at_utc": _utc_timestamp(annotated_at_utc),
        "evidence_ref": _required_text(evidence_ref, "evidence reference", 512),
        "rationale": _required_text(rationale, "annotation rationale", 2048)
        if rationale.strip()
        else "",
        "supersedes_label_sha256": sorted(supersedes_label_sha256),
    }
    return {**unsigned, "artifact_sha256": canonical_hash(unsigned)}


def validate_review_label(
    record: dict[str, object],
    review_artifact: dict[str, object],
    prior_labels: tuple[dict[str, object], ...] = (),
) -> None:
    digest = record.get("artifact_sha256")
    unsigned = dict(record)
    unsigned.pop("artifact_sha256", None)
    if (
        record.get("artifact_type") != "document_acquisition.exhibit_label"
        or record.get("artifact_version") != 1
        or not is_sha256_hex_digest(digest)
        or canonical_hash(unsigned) != digest
    ):
        raise ReviewLabelError("review label digest or schema is invalid")
    expected = build_review_label(
        review_artifact,
        outcome=record["outcome"],
        observed_kind=record["observed_kind"],
        annotator_id=record["annotator_id"],
        annotated_at_utc=record["annotated_at_utc"],
        evidence_ref=record["evidence_ref"],
        rationale=record["rationale"],
        observed_identity=(
            ExhibitIdentity(**record["observed_identity"])
            if record["observed_identity"] is not None
            else None
        ),
        annotation_kind=record["annotation_kind"],
        supersedes_label_sha256=tuple(record["supersedes_label_sha256"]),
    )
    if expected != record:
        raise ReviewLabelError("review label is not pinned to this processing artifact")
    prior = tuple(
        item for item in prior_labels if item.get("artifact_sha256") != digest
    )
    if record["annotation_kind"] == "independent":
        if any(
            item.get("annotation_kind") == "adjudication"
            and item.get("annotated_at_utc", "") <= record["annotated_at_utc"]
            for item in prior
        ):
            raise ReviewLabelError("independent labels cannot follow adjudication")
        if any(
            item.get("annotation_kind") == "independent"
            and item.get("annotator_id") == record["annotator_id"]
            for item in prior
        ):
            raise ReviewLabelError("annotator already labeled this case")
    if record["annotation_kind"] == "adjudication":
        superseded = set(record["supersedes_label_sha256"])
        prior_independent = {
            item["artifact_sha256"]: item
            for item in prior
            if item.get("annotation_kind") == "independent"
        }
        selected = [prior_independent.get(item) for item in superseded]
        if (
            len(selected) < 2
            or any(item is None for item in selected)
            or len({item["outcome"] for item in selected if item is not None}) < 2
            or any(item["annotator_id"] == record["annotator_id"] for item in selected)
            or any(
                item["annotated_at_utc"] >= record["annotated_at_utc"]
                for item in selected
                if item is not None
            )
            or superseded != set(prior_independent)
        ):
            raise ReviewLabelError("adjudication does not resolve independent labels")


def _case_label_directory(
    review_root: Path, context: dict[str, object], *, create: bool
) -> Path:
    root = Path(review_root)
    if root.is_symlink() or not root.is_dir():
        raise ReviewLabelError("review root must be an existing directory")
    current = root
    for component in (
        "labels",
        str(context["fixture_id"]),
        str(context["capture_id"]),
        str(context["target_id"]),
    ):
        try:
            safe_component = validate_path_component(component, "label path")
        except ValueError as error:
            raise ReviewLabelError("review label identity is unsafe") from error
        current = current / safe_component
        if current.is_symlink():
            raise ReviewLabelError("review label path contains a symlink")
        if current.exists() and not current.is_dir():
            raise ReviewLabelError("review label path is not a directory")
        if not current.exists() and create:
            current.mkdir()
        if current.exists() and not current.resolve().is_relative_to(root.resolve()):
            raise ReviewLabelError("review label path escapes its root")
    return current


def load_case_review_labels(
    review_root: Path, review_artifact: dict[str, object]
) -> tuple[dict[str, object], ...]:
    if review_artifact.get("artifact_version") != 3:
        return ()
    processing = review_artifact.get("processing")
    if (
        isinstance(processing, dict)
        and processing.get("exhibit_assessment") is None
        and processing.get("exhibit_assessment_fingerprint") is None
    ):
        return ()
    context = _review_context(review_artifact)
    directory = _case_label_directory(review_root, context, create=False)
    if not directory.exists():
        return ()
    records = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ReviewLabelError("review label sidecar is unsafe")
        try:
            raw = path.read_text(encoding="utf-8")
            record = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ReviewLabelError("review label sidecar is unreadable") from error
        if not isinstance(record, dict) or canonical_json(record) != raw:
            raise ReviewLabelError("review label sidecar is not canonical JSON")
        if path.name != f"{record.get('artifact_sha256')}.json":
            raise ReviewLabelError("review label filename differs from digest")
        records.append(record)
    labels = tuple(records)
    if sum(label.get("annotation_kind") == "adjudication" for label in labels) > 1:
        raise ReviewLabelError("case has multiple adjudication labels")
    for record in labels:
        validate_review_label(record, review_artifact, labels)
    return labels


def load_processing_review_artifact(path: Path) -> tuple[Path, dict[str, object]]:
    requested = Path(path).expanduser()
    if requested.is_symlink() or requested.name != "processing-review.json":
        raise ReviewLabelError("processing review path is invalid")
    case_root = requested.parent
    cases_root = case_root.parent
    review_root = cases_root.parent
    if (
        review_root.is_symlink()
        or not review_root.is_dir()
        or cases_root.name != "cases"
        or not requested.is_file()
    ):
        raise ReviewLabelError("processing review path is outside a review run")
    current = review_root
    for part in requested.relative_to(review_root).parts:
        current = current / part
        if current.is_symlink():
            raise ReviewLabelError("processing review path contains a symlink")
    if not requested.resolve().is_relative_to(review_root.resolve()):
        raise ReviewLabelError("processing review path escapes its run")
    try:
        raw = requested.read_text(encoding="utf-8")
        artifact = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewLabelError("processing review artifact is unreadable") from error
    if not isinstance(artifact, dict) or canonical_json(artifact) != raw:
        raise ReviewLabelError("processing review artifact is not canonical JSON")
    _review_context(artifact)
    return review_root, artifact


def write_review_label(
    review_root: Path,
    review_artifact: dict[str, object],
    record: dict[str, object],
) -> Path:
    context = _review_context(review_artifact)
    digest = record.get("artifact_sha256")
    if (
        not is_sha256_hex_digest(digest)
        or canonical_hash(
            {key: value for key, value in record.items() if key != "artifact_sha256"}
        )
        != digest
    ):
        raise ReviewLabelError("review label digest is invalid")
    label_directory = _case_label_directory(review_root, context, create=True)
    path = label_directory / f"{digest}.json"
    encoded = canonical_json(record)
    if path.exists():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.read_text("utf-8") != encoded
        ):
            raise ReviewLabelError("review label conflicts with existing output")
    else:
        validate_review_label(
            record,
            review_artifact,
            load_case_review_labels(review_root, review_artifact),
        )
        atomic_write_json(path, record)
    return path
