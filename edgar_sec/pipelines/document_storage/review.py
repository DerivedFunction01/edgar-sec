"""Compare two review runs and report what the change did.

The workflow is generate, change the normalizer, generate again, compare. This
module is the compare step, and it exists because `diff -ru` over two review
directories answers the wrong question first: it opens with the sanitized
`.html` files, which are the largest artifacts and the least likely to have
moved. A reviewer then has to filter a filesystem diff down to the documents
whose normalized text actually changed.

This reads the two run manifests, joins them on document id, and writes one
unified diff per document whose output changed. Everything else is a count.

Scope is deliberately narrow. It does not know which change was intended, and
it does not judge whether the new output is better -- that is what reading the
diff is for. It also never regenerates anything, so it cannot be the reason a
review run is stale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import HtmlDiff, unified_diff
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.pipelines.document_storage.review_artifacts import (
    CASES_DIR,
    REVIEW_MANIFEST_NAME,
)

SUMMARY_NAME = "summary.txt"
PATCH_SUFFIX = ".diff.patch"
HTML_SUFFIX = ".diff.html"

UNCHANGED = "unchanged"
CHANGED = "changed"
METADATA_ONLY = "metadata-only"
ADDED = "added"
REMOVED = "removed"

#: Manifest fields that describe *this* run rather than the document, so they
#: are excluded when deciding whether a document's own metadata drifted.
_RUN_FIELDS = frozenset({"fixture_id"})

#: Provenance fields worth comparing when both runs record them. Deliberately a
#: closed vocabulary: see `_document_metadata`.
_COMPARED_FIELDS = (
    "accession",
    "document_path",
    "form",
    "processor_fingerprint",
    "representation",
)


class ReviewDiffError(RuntimeError):
    """Two review runs could not be compared."""


@dataclass(frozen=True, slots=True)
class DocumentDiff:
    """One document's verdict between two runs."""

    document_id: str
    document_path: str
    status: str
    source_changed: bool
    added_lines: int = 0
    removed_lines: int = 0
    patch_path: Path | None = None
    html_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_path": self.document_path,
            "status": self.status,
            "source_changed": self.source_changed,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "patch": str(self.patch_path) if self.patch_path else None,
            "html": str(self.html_path) if self.html_path else None,
        }


@dataclass(frozen=True, slots=True)
class ReviewDiffResult:
    """The whole comparison."""

    output_dir: Path
    base_dir: Path
    new_dir: Path
    documents: tuple[DocumentDiff, ...] = ()
    fixture_mismatch: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for item in self.documents:
            tally[item.status] = tally.get(item.status, 0) + 1
        return tally

    @property
    def has_changes(self) -> bool:
        """Whether anything moved. Drives the command's exit status."""
        return any(item.status != UNCHANGED for item in self.documents)

    def changed(self) -> tuple[DocumentDiff, ...]:
        return tuple(
            item for item in self.documents if item.status in {CHANGED, METADATA_ONLY}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "base": str(self.base_dir),
            "new": str(self.new_dir),
            "counts": self.counts,
            "fixture_mismatch": self.fixture_mismatch,
            "documents": [item.to_dict() for item in self.documents],
        }


def load_run_manifest(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Read one run's manifest, keyed by document id."""
    path = run_dir / REVIEW_MANIFEST_NAME
    if not path.is_file():
        raise ReviewDiffError(
            f"no {REVIEW_MANIFEST_NAME} in {run_dir}; this is not a review run"
        )
    entries: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewDiffError(f"{path}:{number} is not valid JSON: {exc}") from exc
        if not isinstance(entry, dict) or "document_id" not in entry:
            raise ReviewDiffError(f"{path}:{number} is missing document_id")
        document_id = str(entry["document_id"])
        if document_id in entries:
            raise ReviewDiffError(f"{path}:{number} repeats document {document_id}")
        entries[document_id] = entry
    return entries


def _document_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    """The provenance fields recorded for a document.

    Read off a fixed vocabulary rather than from whatever keys a manifest
    happens to hold, so a field a run does not compute (v1's marker and table
    counts) is ignored instead of read as a change. Within that vocabulary an
    absent field is a real difference rather than a schema difference: a run
    reporting no processor fingerprint is not the same evidence as one reporting
    a different one, and a fingerprint present in only one run is exactly the
    "which code produced this?" answer the comparison exists to give.
    """
    return {field: entry.get(field) for field in _COMPARED_FIELDS}


def _metadata_changed(base_entry: dict[str, Any], new_entry: dict[str, Any]) -> bool:
    """Whether either run records a provenance field differently."""
    base_meta = _document_metadata(base_entry)
    new_meta = _document_metadata(new_entry)
    return any(base_meta[field] != new_meta[field] for field in _COMPARED_FIELDS)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _write_document_diff(
    document_id: str, base_text: str, new_text: str, cases_root: Path
) -> tuple[Path, Path, int, int]:
    """Write one document's patch and HTML diff; return paths and line counts."""
    case_dir = cases_root / document_id
    case_dir.mkdir(parents=True, exist_ok=True)
    patch_lines = list(
        unified_diff(
            base_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="base",
            tofile="new",
        )
    )
    patch_path = case_dir / f"{document_id}{PATCH_SUFFIX}"
    atomic_write_text(patch_path, "".join(patch_lines))
    html_path = case_dir / f"{document_id}{HTML_SUFFIX}"
    atomic_write_text(
        html_path,
        HtmlDiff().make_file(
            base_text.splitlines(),
            new_text.splitlines(),
            fromdesc="base",
            todesc="new",
        ),
    )
    added = sum(
        1 for line in patch_lines if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in patch_lines if line.startswith("-") and not line.startswith("---")
    )
    return patch_path, html_path, added, removed


def compare_review_runs(
    base_dir: Path, new_dir: Path, output_dir: Path
) -> ReviewDiffResult:
    """Diff two review runs and write the differences under ``output_dir``."""
    for directory in (base_dir, new_dir):
        if not directory.is_dir():
            raise ReviewDiffError(f"review run not found: {directory}")
    if base_dir.resolve() == new_dir.resolve():
        raise ReviewDiffError(
            f"base and new are the same review run ({base_dir}); a comparison "
            "needs two runs, and regenerating in place would overwrite the "
            "evidence"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ReviewDiffError(
            f"diff output already contains artifacts: {output_dir}. "
            "Choose a new output directory."
        )

    base_entries = load_run_manifest(base_dir)
    new_entries = load_run_manifest(new_dir)
    fixture_mismatch = _fixture_mismatch(base_entries, new_entries)
    cases_root = output_dir / CASES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    documents: list[DocumentDiff] = []
    for document_id in sorted(base_entries.keys() | new_entries.keys()):
        base_entry = base_entries.get(document_id)
        new_entry = new_entries.get(document_id)
        reference = base_entry or new_entry
        assert reference is not None
        document_path = str(reference.get("document_path") or "")
        if base_entry is None:
            documents.append(
                DocumentDiff(document_id, document_path, ADDED, source_changed=False)
            )
            continue
        if new_entry is None:
            documents.append(
                DocumentDiff(document_id, document_path, REMOVED, source_changed=False)
            )
            continue
        # A changed source hash means the fixture itself was re-filled between
        # the two runs. Every output difference for this document is then
        # uninterpretable, so it is called out rather than blended into the
        # change count.
        source_changed = base_entry.get("source_sha256") != new_entry.get(
            "source_sha256"
        )
        base_text = _read_text(
            base_dir / CASES_DIR / document_id / f"{document_id}.txt"
        )
        new_text = _read_text(new_dir / CASES_DIR / document_id / f"{document_id}.txt")
        if base_text != new_text:
            patch, html, added, removed = _write_document_diff(
                document_id, base_text, new_text, cases_root
            )
            documents.append(
                DocumentDiff(
                    document_id,
                    document_path,
                    CHANGED,
                    source_changed,
                    added,
                    removed,
                    patch,
                    html,
                )
            )
            continue
        if _metadata_changed(base_entry, new_entry):
            # The text is identical but something about how it was produced
            # moved. Surfaced because it is a real behavioural change that a
            # text diff cannot show.
            documents.append(
                DocumentDiff(document_id, document_path, METADATA_ONLY, source_changed)
            )
            continue
        documents.append(
            DocumentDiff(document_id, document_path, UNCHANGED, source_changed)
        )

    result = ReviewDiffResult(
        output_dir=output_dir,
        base_dir=base_dir,
        new_dir=new_dir,
        documents=tuple(documents),
        fixture_mismatch=fixture_mismatch,
    )
    atomic_write_text(output_dir / SUMMARY_NAME, render_summary(result))
    return result


def _fixture_mismatch(
    base_entries: dict[str, dict[str, Any]], new_entries: dict[str, dict[str, Any]]
) -> str | None:
    """Report when the two runs reviewed different fixtures."""
    base = {str(entry.get("fixture_id")) for entry in base_entries.values()}
    new = {str(entry.get("fixture_id")) for entry in new_entries.values()}
    if len(base) == 1 and len(new) == 1 and base != new:
        return f"base={base.pop()} new={new.pop()}"
    return None


def render_summary(result: ReviewDiffResult) -> str:
    """Render the human-readable comparison summary."""
    counts = result.counts
    lines = [
        f"base  {result.base_dir}",
        f"new   {result.new_dir}",
        f"out   {result.output_dir}",
        "",
        f"documents   {len(result.documents)}",
        f"changed     {counts.get(CHANGED, 0)}",
        f"metadata    {counts.get(METADATA_ONLY, 0)}",
        f"unchanged   {counts.get(UNCHANGED, 0)}",
        f"added       {counts.get(ADDED, 0)}",
        f"removed     {counts.get(REMOVED, 0)}",
    ]
    source_changed = [item for item in result.documents if item.source_changed]
    if source_changed:
        lines.append(f"resourced   {len(source_changed)}")
    if result.fixture_mismatch:
        lines.append("")
        lines.append(
            f"warning: the two runs reviewed different fixtures ({result.fixture_mismatch})"
        )
    if source_changed:
        lines.append("")
        lines.append(
            "warning: the fixture was re-filled between runs; output diffs for "
            "these documents compare different source bytes and cannot be read "
            "as normalisation changes:"
        )
        for item in source_changed:
            lines.append(f"  {item.document_id}  {item.document_path}")
    moved = result.changed()
    if moved:
        lines.append("")
        lines.append("changed documents:")
        for item in moved:
            suffix = "  [source changed]" if item.source_changed else ""
            lines.append(
                f"  {item.document_id}  +{item.added_lines}/-{item.removed_lines}"
                f"  {item.document_path}{suffix}"
            )
    lines.append("")
    lines.append("no differences" if not result.has_changes else "differences found")
    return "\n".join(lines) + "\n"


__all__ = [
    "ADDED",
    "CHANGED",
    "METADATA_ONLY",
    "REMOVED",
    "SUMMARY_NAME",
    "UNCHANGED",
    "DocumentDiff",
    "ReviewDiffError",
    "ReviewDiffResult",
    "compare_review_runs",
    "load_run_manifest",
    "render_summary",
]
