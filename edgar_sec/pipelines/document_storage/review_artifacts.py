"""Source-first review artifacts for fixture documents.

Shares nothing with the storage pipeline — no plan, chunk, checkpoint, or snapshot —
so a run reproduces from a fixture alone and a diff shows the edit, not the corpus.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

from edgar_sec.domain.document.models import DocumentLocator, RawDocumentBlob
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.foundation.hashing import sha256_bytes, sha256_text
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_bytes, atomic_write_text
from edgar_sec.pipelines.document_storage.fixture_store import (
    FixtureStore,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_storage.paths import CASES_DIR, REVIEW_MANIFEST_NAME
from edgar_sec.pipelines.document_storage.processor import PROCESSOR_FINGERPRINT

#: Per-collection cap when serializing page-marker analysis. The analysis object
#: holds one entry per detected marker; a pathological 10-K can carry hundreds,
#: and the review case for it is a diagnostic, not a dump.
_ANALYSIS_ITEM_LIMIT = 256
_TABLE_GEOMETRY_LIMIT = 128

_HTML_SUFFIXES = (".htm", ".html", ".xhtml")
_SANITIZED_STRIP_TAGS = ("script", "style", "meta", "noscript")
_UNSAFE_ATTRIBUTES = frozenset({"src", "href", "action"})


class ReviewArtifactError(RuntimeError):
    """A review run could not be produced."""


@dataclass(frozen=True, slots=True)
class ReviewCase:
    """One selected document, with the bytes and identity needed to process it."""

    document: RawDocumentBlob
    form: str
    form_source: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class ReviewCaseResult:
    """One document after normalization, with its full structural diagnostics."""

    case: ReviewCase
    normalization: NormalizationResult
    source_text: str

    @property
    def text(self) -> str:
        """The normalized text, exactly as the pipeline would store it."""
        return self.normalization.text


@dataclass(frozen=True, slots=True)
class ReviewSelection:
    """Documents that can be reviewed, and those that cannot.

    One bad payload is a fact about that document, not a reason to withhold the rest;
    failures are named and set a non-zero exit status.
    """

    cases: tuple[ReviewCase, ...]
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewRunResult:
    """What one review run produced."""

    output_dir: Path
    rendered: int
    selected: int
    manifest_path: Path
    failures: tuple[str, ...] = ()
    #: Documents processed under a manifest-declared form rather than a per-document
    #: one; a property of the fixture, so reported once for the run.
    forms_inferred: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "selected": self.selected,
            "rendered": self.rendered,
            "manifest": str(self.manifest_path),
            "forms_inferred": self.forms_inferred,
            "failures": list(self.failures),
        }


def _resolve_form(
    document_id: str, forms: dict[str, str], manifest_forms: Sequence[Any]
) -> tuple[str, str]:
    """Return a document's filing form and where that answer came from.

    ``form`` selects the processing plugin, so a wrong form makes the diff a lie — the
    source is reported rather than assumed, manifest fallback included.
    """
    recorded = (forms.get(document_id) or "").strip()
    if recorded:
        return recorded, "document"
    declared = [str(value) for value in manifest_forms if str(value).strip()]
    if len(declared) == 1:
        return declared[0], "manifest"
    if declared:
        return declared[0], "manifest-first-of-many"
    return "", "unknown"


def _token_matches(document: RawDocumentBlob, token: str) -> bool:
    """Match a selection token by exact document id or path suffix.

    The suffix is what makes ``--id t10k-2094e.txt`` usable before the digest is known.
    """
    if document.doc_id == token:
        return True
    return document.document_path.casefold().endswith(token.casefold())


def _manifest_forms(paths: ProjectPaths, fixture_id: str) -> tuple[Any, ...]:
    manifest_path = paths.fixture_manifest_path(fixture_id)
    if not manifest_path.is_file():
        return ()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(manifest, dict):
        return ()
    forms = manifest.get("forms")
    return tuple(forms) if isinstance(forms, list) else ()


def select_review_cases(
    paths: ProjectPaths,
    fixture_id: str,
    *,
    ids: Sequence[str] = (),
    extensions: Sequence[str] = (),
    limit: int | None = None,
) -> ReviewSelection:
    """Load the documents one review run will process, in document-id order.

    Order is the selection contract: ``limit`` takes the first N ids deterministically.
    """
    database = paths.fixture_db_path(fixture_id)
    manifest_forms = _manifest_forms(paths, fixture_id)
    failures: list[str] = []
    try:
        with FixtureStore(database, read_only=True) as store:
            if not store.has_document_metadata:
                raise ReviewArtifactError(
                    f"fixture {fixture_id!r} records no document metadata in "
                    f"{database}. Re-run 'documents fill --fixture {fixture_id} "
                    "--plan <plan>' to record it: the payloads are already "
                    "stored, so no document is re-fetched."
                )
            forms = store.document_forms()
            if ids:
                # The suffix test cannot be pushed into SQL, so the small metadata table
                # is read whole and filtered here. Only selected payloads decompress.
                documents = [
                    document
                    for document in store.documents()
                    if any(_token_matches(document, token) for token in ids)
                ]
                if extensions:
                    documents = _filter_by_extension(documents, extensions)
                if limit is not None and limit > 0:
                    documents = documents[:limit]
            else:
                documents = list(store.documents(extensions=extensions, limit=limit))

            cases: list[ReviewCase] = []
            for document in documents:
                try:
                    payload = store.get(document.doc_id)
                except FixtureStoreError as exc:
                    failures.append(f"{document.doc_id}: {exc}")
                    continue
                if payload is None:
                    failures.append(
                        f"{document.doc_id}: fixture indexes it but stores no payload"
                    )
                    continue
                digest = sha256_bytes(payload)
                if digest != document.raw_payload_sha256:
                    failures.append(
                        f"{document.doc_id}: source hash mismatch, payload hashes "
                        f"to {digest} but the index records "
                        f"{document.raw_payload_sha256}"
                    )
                    continue
                form, form_source = _resolve_form(
                    document.doc_id, forms, manifest_forms
                )
                cases.append(
                    ReviewCase(
                        document=document,
                        form=form,
                        form_source=form_source,
                        payload=payload,
                    )
                )
    except FixtureStoreError as exc:
        raise ReviewArtifactError(str(exc)) from exc
    return ReviewSelection(cases=tuple(cases), failures=tuple(failures))


def _filter_by_extension(
    documents: Sequence[RawDocumentBlob], extensions: Sequence[str]
) -> list[RawDocumentBlob]:
    wanted = tuple(f".{value.lstrip('.').casefold()}" for value in extensions)
    return [
        document
        for document in documents
        if document.document_path.casefold().endswith(wanted)
    ]


def run_review_case(case: ReviewCase) -> ReviewCaseResult:
    """Normalize one document exactly as a pipeline worker would.

    The hash is re-checked here, not trusted from selection: this runs in a worker.
    """
    digest = sha256_bytes(case.payload)
    if digest != case.document.raw_payload_sha256:
        raise ReviewArtifactError(
            f"source hash mismatch for {case.document.doc_id}: payload hashes "
            f"to {digest}, index records {case.document.raw_payload_sha256}"
        )
    locator = DocumentLocator.from_parts(
        case.document.accession,
        case.document.document_path,
        form=case.form or None,
    )
    normalization = normalize_document(case.payload, form=locator.form)
    return ReviewCaseResult(
        case=case,
        normalization=normalization,
        source_text=case.payload.decode("utf-8", errors="replace"),
    )


def sanitized_source_html(source_text: str) -> str:
    """Render a document's source as HTML safe to open in a browser.

    A reviewer's question is what the browser saw, so the markup is kept; script and
    style bodies, event handlers, and the fetching attributes go.
    """
    tree = parse_html(source_text)
    tree.strip_tags(_SANITIZED_STRIP_TAGS)
    if tree.root is None:
        return ""
    for node in tree.traverse():
        attributes = node.raw_node.attrs
        for name in list(attributes.keys()):
            folded = name.casefold()
            if folded.startswith("on") or folded in _UNSAFE_ATTRIBUTES:
                del attributes[name]
    return tree.html


def bounded_analysis(normalization: NormalizationResult) -> dict[str, Any]:
    """Serialize one document's structural diagnostics, capped.

    ``source_text`` is dropped (already written as the case's own ``.txt``) and
    geometry goes through ``asdict``, or ``json.dumps`` would reject it.
    """
    analysis = normalization.page_analysis
    payload: dict[str, Any] = {}
    if analysis is not None:
        payload = dataclasses.asdict(analysis)
        payload.pop("source_text", None)
        for key in ("markers", "decisions", "unresolved"):
            value = payload.get(key)
            if isinstance(value, (list, tuple)):
                payload[key] = list(value)[:_ANALYSIS_ITEM_LIMIT]
    payload["table_geometries"] = [
        dataclasses.asdict(geometry)
        for geometry in list(normalization.table_geometries)[:_TABLE_GEOMETRY_LIMIT]
    ]
    # Records are frozen dataclasses, not arrays: four anonymous positional
    # columns in the artifact would be the names-only trace one level down.
    payload["stage_trace"] = [record.to_dict() for record in normalization.stage_trace]
    return payload


def _manifest_entry(
    result: ReviewCaseResult, output_sha256: str, fixture_id: str
) -> dict[str, Any]:
    """Identity and provenance for one document, and nothing derived."""
    case = result.case
    document = case.document
    return {
        "accession": document.accession,
        "current_output_sha256": output_sha256,
        "document_id": document.doc_id,
        "document_path": document.document_path,
        "fixture_id": fixture_id,
        "form": case.form,
        "processor_fingerprint": PROCESSOR_FINGERPRINT,
        "representation": result.normalization.representation,
        "source_sha256": document.raw_payload_sha256,
    }


def _is_html(document_path: str) -> bool:
    return document_path.casefold().endswith(_HTML_SUFFIXES)


def new_review_run_id() -> str:
    """Return a review run id from the pipeline's generator: one format for both."""
    from edgar_sec.pipelines.document_storage.operator import new_run_id

    return new_run_id("review")


def _write_pretty_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one review JSON file, pretty-printed and newline-terminated.

    Both for ``diff``: compact JSON makes a two-field change one replaced line, and a
    missing final newline adds a marker to the comparison this exists to make.
    """
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_review_artifacts(
    result: ReviewCaseResult, output_dir: Path, fixture_id: str
) -> dict[str, Any]:
    """Write one document's review case and return its manifest entry.

    Source is written as the original bytes, so a lost byte is distinguishable from a
    byte that was never there. No per-case ``.metadata.json``: the manifest has it.
    """
    case = result.case
    case_id = case.document.doc_id
    output_dir.mkdir(parents=True, exist_ok=True)
    # Trailing newline keeps the file well-formed and two runs diffable.
    serialized = result.text + "\n"
    output_sha256 = sha256_text(serialized)
    atomic_write_text(output_dir / f"{case_id}.txt", serialized)
    atomic_write_bytes(output_dir / f"{case_id}.source.txt", case.payload)
    _write_pretty_json(
        output_dir / f"{case_id}.analysis.json",
        bounded_analysis(result.normalization),
    )
    if _is_html(case.document.document_path):
        atomic_write_text(
            output_dir / f"{case_id}.html", sanitized_source_html(result.source_text)
        )
    return _manifest_entry(result, output_sha256, fixture_id)


def _process_case_task(
    case: ReviewCase, case_dir: Path, fixture_id: str
) -> dict[str, Any]:
    """Module-level worker entry point, so it survives pickling to a child."""
    return write_review_artifacts(run_review_case(case), case_dir, fixture_id)


def render_review_run(
    paths: ProjectPaths,
    fixture_id: str,
    output_dir: Path,
    *,
    ids: Sequence[str] = (),
    extensions: Sequence[str] = (),
    limit: int | None = None,
    workers: int | None = None,
) -> ReviewRunResult:
    """Process the selected documents and write one review run.

    Refuses to write into a non-empty directory: two runs sharing an output root cannot
    be compared, so a code change means a new run id.
    """
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ReviewArtifactError(
            f"review output already contains artifacts: {output_dir}. "
            "Choose a new run id; a review run is never regenerated in place."
        )
    selection = select_review_cases(
        paths, fixture_id, ids=ids, extensions=extensions, limit=limit
    )
    cases = selection.cases
    if not cases:
        raise ReviewArtifactError(
            f"selection matched no reviewable documents in fixture {fixture_id!r}"
            + (f" ({len(selection.failures)} skipped)" if selection.failures else "")
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_root = output_dir / CASES_DIR
    cases_root.mkdir(parents=True, exist_ok=True)

    worker_count = derive_resources().threads if workers is None else workers
    if worker_count < 1:
        raise ReviewArtifactError("workers must be positive")

    failures: list[str] = list(selection.failures)
    entries: dict[str, dict[str, Any]] = {}
    if worker_count == 1 or len(cases) == 1:
        for case in tqdm(cases, desc="Rendering review artifacts", unit="doc"):
            try:
                entries[case.document.doc_id] = _process_case_task(
                    case, cases_root / case.document.doc_id, fixture_id
                )
            except Exception as exc:  # noqa: BLE001 - one document must not end the run
                failures.append(f"{case.document.doc_id}: {exc}")
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(
                    _process_case_task,
                    case,
                    cases_root / case.document.doc_id,
                    fixture_id,
                ): case.document.doc_id
                for case in cases
            }
            for future in tqdm(
                as_completed(futures),
                total=len(cases),
                desc="Rendering review artifacts",
                unit="doc",
            ):
                document_id = futures[future]
                try:
                    entries[document_id] = future.result()
                except Exception as exc:  # noqa: BLE001 - one document must not end the run
                    failures.append(f"{document_id}: {exc}")

    # Selection order, not completion order: the manifest is a stable artifact,
    # and a diff of two runs should not report a reordering as a change.
    manifest = [
        entries[case.document.doc_id]
        for case in cases
        if case.document.doc_id in entries
    ]
    manifest_path = output_dir / REVIEW_MANIFEST_NAME
    atomic_write_text(
        manifest_path,
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in manifest),
    )
    return ReviewRunResult(
        output_dir=output_dir,
        rendered=len(manifest),
        selected=len(cases) + len(selection.failures),
        manifest_path=manifest_path,
        failures=tuple(failures),
        forms_inferred=sum(1 for case in cases if case.form_source != "document"),
    )


__all__ = [
    "CASES_DIR",
    "REVIEW_MANIFEST_NAME",
    "ReviewArtifactError",
    "ReviewCase",
    "ReviewCaseResult",
    "ReviewRunResult",
    "ReviewSelection",
    "bounded_analysis",
    "new_review_run_id",
    "render_review_run",
    "run_review_case",
    "sanitized_source_html",
    "select_review_cases",
    "write_review_artifacts",
]
