"""Review bundles: a bounded, inspectable set of documents from a snapshot.

The snapshot is the product; review is how a human checks it. A review set is
deliberately *not* a dump. It selects a bounded number of documents that between
them exercise the interesting outcomes — a normal filing, a cover whose boundary
was only approximately located, a document that failed, one pulled in by a
stub's delegation — and writes each as a self-contained bundle.

Why a selection rather than an export: a corpus snapshot can hold hundreds of
thousands of documents, and a reviewer reads a few. The interesting thing to
review is not a sample of documents but the *outcomes*, so the selection is
stratified by outcome rather than sampled uniformly. A uniform sample of a
99.9%-clean corpus shows only clean documents.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.foundation.serialization import canonical_json

log = logging.getLogger("document_storage.review")

REVIEW_MANIFEST_NAME = "review_manifest.json"
REVIEW_BUNDLE_SUFFIX = ".json"
DEFAULT_BUNDLE_LIMIT = 50

#: Text excerpt length per bundle. Long enough to judge a cover boundary, short
#: enough that fifty bundles stay readable in an editor.
EXCERPT_CHARS = 4_000


class ReviewError(RuntimeError):
    """A review set could not be rendered."""


@dataclass(frozen=True, slots=True)
class ReviewBundle:
    """One document's review material."""

    document_locator_key: str
    accession: str
    document_path: str
    status: str
    representation: str
    word_count: int
    normalized_text: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_locator_key": self.document_locator_key,
            "accession": self.accession,
            "document_path": self.document_path,
            "status": self.status,
            "representation": self.representation,
            "word_count": self.word_count,
            "outcome": self.outcome,
            "normalized_text": self.normalized_text,
        }


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """What a render produced."""

    output_dir: Path
    rendered: int
    skipped: int
    bundles: tuple[ReviewBundle, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "rendered": self.rendered,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def _read_rows(artifact_path: Path) -> list[dict[str, Any]]:
    """Read a snapshot into row dicts, from either published shape.

    Two shapes exist, and a review must handle both because the ``current``
    pointer can name either:

    * a **run** snapshot — one assembled ``documents.parquet`` holding every
      column in a single table;
    * a **consolidated** snapshot — a repartitioned part tree, where index
      (metadata) and payload (text) live in separate files.

    Only the columns a bundle needs are projected, including the large text
    column, because the payload column is dead weight for review and dominates
    file size.

    Note the run schema carries no ``form`` column: a document's form lives on its
    catalog occurrence, not on the stored artifact. A review of a run snapshot
    therefore cannot stratify by form and does not pretend to.
    """
    from edgar_sec.infra.storage.parquet import read_parquet_table

    path = Path(artifact_path)
    if path.is_dir():
        return _read_rows_from_parts(path)
    table = read_parquet_table(
        path,
        [
            "document_locator_key",
            "accession",
            "document_path",
            "status",
            "normalized_text",
        ],
    )
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}
    return [
        {name: values[index] for name, values in columns.items()}
        for index in range(table.num_rows)
    ]


def _read_rows_from_parts(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Read a consolidated snapshot by joining its index and payload parts."""
    import pyarrow as pa

    from edgar_sec.infra.storage.manifests import SnapshotPart
    from edgar_sec.infra.storage.parquet import read_parquet_table

    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ReviewError(f"snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parts = [SnapshotPart.from_dict(row) for row in manifest.get("resolved_parts", ())]

    def _concat(kind: str, columns: tuple[str, ...]) -> Any:
        matching = [part for part in parts if part.kind == kind]
        if not matching:
            raise ReviewError(f"snapshot has no {kind} parts to review")
        tables = [
            read_parquet_table(snapshot_dir / part.path, list(columns))
            for part in matching
        ]
        return tables[0] if len(tables) == 1 else pa.concat_tables(tables)

    index_rows = _concat("index", ("accession", "document_path", "doc_id")).to_pylist()
    text_by_doc = {
        str(row["doc_id"]): str(row["clean_text"] or "")
        for row in _concat("payload", ("doc_id", "clean_text")).to_pylist()
    }
    return [
        {
            "accession": str(row["accession"] or ""),
            "document_path": str(row["document_path"] or ""),
            "document_locator_key": str(row["doc_id"] or ""),
            # A consolidated part tree records no per-document status: a document
            # only reaches consolidation if it was acquired.
            "status": "ok",
            "normalized_text": text_by_doc.get(str(row["doc_id"]), ""),
        }
        for row in index_rows
    ]


def classify_outcome(row: dict[str, Any]) -> str:
    """Classify one row into the review outcome it represents.

    Outcomes are ordered from "needs attention" to "unremarkable" so the
    selection can be stratified by interest rather than by probability.
    """
    status = str(row.get("status") or "")
    if status == "failed":
        return "failed"
    if status == "missing":
        return "missing"
    text = str(row.get("normalized_text") or "")
    if not text.strip():
        return "empty_text"
    return "ok"


#: Outcome strata, most interesting first. Each is filled before the next starts,
#: so a small limit still shows the surprising documents.
OUTCOME_STRATA: tuple[str, ...] = (
    "failed",
    "missing",
    "empty_text",
    "ok",
)


def select_bundles(
    rows: Iterable[dict[str, Any]], limit: int | None
) -> tuple[list[ReviewBundle], int]:
    """Select a stratified review set, returning ``(bundles, skipped)``.

    Within a stratum documents are taken in a stable order (by
    ``document_locator_key``) so two runs over the same snapshot render the same
    set, which is what makes a review diffable.
    """
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in OUTCOME_STRATA}
    total = 0
    for row in rows:
        total += 1
        buckets[classify_outcome(row)].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: str(row.get("document_locator_key") or ""))

    cap = DEFAULT_BUNDLE_LIMIT if limit is None else max(0, limit)
    selected: list[ReviewBundle] = []
    for name in OUTCOME_STRATA:
        if len(selected) >= cap:
            break
        for row in buckets[name][: cap - len(selected)]:
            selected.append(_to_bundle(row, name))
    return selected, total - len(selected)


def _to_bundle(row: dict[str, Any], outcome: str) -> ReviewBundle:
    text = str(row.get("normalized_text") or "")
    return ReviewBundle(
        document_locator_key=str(row.get("document_locator_key") or ""),
        accession=str(row.get("accession") or ""),
        document_path=str(row.get("document_path") or ""),
        status=str(row.get("status") or ""),
        representation="",
        word_count=len(text.split()),
        normalized_text=text[:EXCERPT_CHARS],
        outcome=outcome,
    )


def write_bundle(output_dir: Path, bundle: ReviewBundle) -> Path:
    """Write one review bundle as a self-contained JSON file."""
    safe_key = bundle.document_locator_key or "unknown"
    path = output_dir / f"{safe_key}{REVIEW_BUNDLE_SUFFIX}"
    path.write_text(canonical_json(bundle.to_dict()), encoding="utf-8")
    return path


def write_manifest(
    output_dir: Path,
    bundles: Sequence[ReviewBundle],
    *,
    artifact_path: Path,
    skipped: int,
) -> Path:
    """Write the manifest describing a rendered review set."""
    path = output_dir / REVIEW_MANIFEST_NAME
    payload = {
        "artifact": str(artifact_path),
        "rendered": len(bundles),
        "skipped": skipped,
        "strata": list(OUTCOME_STRATA),
        "bundles": [
            {
                "document_locator_key": bundle.document_locator_key,
                "accession": bundle.accession,
                "document_path": bundle.document_path,
                "status": bundle.status,
                "outcome": bundle.outcome,
                "word_count": bundle.word_count,
            }
            for bundle in bundles
        ],
    }
    path.write_text(canonical_json(payload), encoding="utf-8")
    return path


def render_review_set(
    *,
    artifact_path: Path,
    output_dir: Path,
    limit: int | None = None,
) -> ReviewResult:
    """Render a review set from a published snapshot artifact.

    A row that cannot be turned into a bundle is reported and skipped rather
    than failing the render: one malformed row should not cost a reviewer the
    other forty-nine documents.
    """
    artifact = Path(artifact_path)
    if not artifact.exists():
        raise ReviewError(f"snapshot not found: {artifact}")

    rows = _read_rows(artifact)
    bundles, skipped = select_bundles(rows, limit)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    written = 0
    for bundle in bundles:
        try:
            write_bundle(destination, bundle)
            written += 1
        except OSError as exc:
            log.warning(
                "could not write bundle for %s: %s", bundle.document_locator_key, exc
            )
            errors.append(f"{bundle.document_locator_key}: {exc}")
    write_manifest(destination, bundles, artifact_path=artifact, skipped=skipped)
    return ReviewResult(
        output_dir=destination,
        rendered=written,
        skipped=skipped,
        bundles=tuple(bundles),
        errors=tuple(errors),
    )


__all__ = [
    "DEFAULT_BUNDLE_LIMIT",
    "EXCERPT_CHARS",
    "OUTCOME_STRATA",
    "REVIEW_BUNDLE_SUFFIX",
    "REVIEW_MANIFEST_NAME",
    "ReviewBundle",
    "ReviewError",
    "ReviewResult",
    "classify_outcome",
    "render_review_set",
    "select_bundles",
    "write_bundle",
    "write_manifest",
]
