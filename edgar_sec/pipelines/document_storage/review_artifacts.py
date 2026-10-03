"""Source-first review artifacts for fixture documents.

The workflow this exists for: point it at a fixture, read what the normalizer
produced for a bounded set of documents, change the normalizer, run it again,
compare the two. That last step is `documents review`; this module only produces
the thing being compared.

It deliberately shares nothing with the storage pipeline. There is no plan, no
chunk, no checkpoint, no Parquet, and no published snapshot, because a review
run is evidence about *this* code on *these* documents. A pipeline run answers a
different question -- what does the corpus look like -- and every one of those
stages would make the answer depend on corpus state rather than on the code
under review. A review run that could not be reproduced from a fixture alone
would be worse than useless: the diff would show what the snapshot did, not what
the edit did.

The one dependency that is not negotiable is the fixture's own document
metadata. A payload key is a one-way digest, so accession, path, MIME and source
hash cannot be recovered from it, and the normalizer needs a `DocumentLocator`
(including its filing form, which selects the processing plugin) to run at all.
That is what `FixtureStore.document_blobs` records.
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

    Kept separate rather than raising on the first bad document: a fixture holds
    thousands of documents, and one missing or corrupt payload is a fact about
    that document, not a reason to withhold review of the rest. Skipped
    documents are named in ``failures`` and set a non-zero exit status, so this
    is reported rather than silent.
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
    #: Documents processed under a form taken from the fixture manifest rather
    #: than recorded per document. Reported once for the run instead of per case,
    #: because it is a property of the fixture, not of any one document.
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
    """Return the filing form for a document and where that answer came from.

    ``form`` is not cosmetic: it selects the processing plugin, so a document
    reviewed under the wrong form normalizes differently from the same document
    in a pipeline run, and the resulting diff would be a lie. The source of the
    form is therefore reported alongside it rather than assumed.

    A fixture payload stored without a per-document form falls back to the first
    entry in the fixture manifest's form list, so a multi-form fixture reviews
    every such document as its first form. That fallback is reproduced, and
    labelled ``manifest-first-of-many``, because silently correcting it would
    make review output incomparable with the artifacts it is meant to replace.
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

    The suffix match is what makes ``--id t10k-2094e.txt`` usable at all: a
    document's id is a digest of its accession and path, so before you know the
    digest the only handle a reviewer has is the filename they saw in EDGAR.
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

    Order is the selection contract: ``limit`` takes the first N ids from a
    stable ordering, so two runs of the same fixture with the same limit review
    the same documents and their diffs are comparable.
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
                # Token matching includes a path-suffix test, which cannot be
                # pushed into SQL, so the whole (small) metadata table is read
                # and filtered here. Only the selected payloads are decompressed.
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

    The hash is re-checked in here rather than trusted from selection: this
    function is what a worker process runs, and attributing a corrupt payload to
    its own document is more useful than failing the whole run.
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

    The reviewer's real question about an HTML filing is "what did the browser
    see", which needs the markup, not the extracted text. Script and style
    bodies go, and so do event handlers and the three attributes that fetch or
    navigate, because a reviewer opening a filing from an unknown registrant
    should not be running that registrant's markup.
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

    ``source_text`` is dropped: the analysis carries the full document it was
    derived from, which is already written as the case's own ``.txt``, and
    serializing it would double the artifact for no diagnostic value.

    Geometry is converted through ``asdict`` because these payloads go straight
    to ``json.dumps``; a live ``TableGeometry`` would raise there rather than
    write something a reviewer could read.
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
    """Identity and provenance for one document, and nothing derived.

    Deliberately not a second copy of the analysis. Counting markers, tables and
    stages here alongside numbers the analysis file already carries was
    affordable only while the normalizer was incomplete and those counts stood in
    for quality. Now that the analysis reports what it actually detected, a table
    count obtained by substring-matching ``<table`` in the source would be a worse
    number that still had to be explained.
    """
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
    """Return a sortable, unique identity for a review run.

    Delegates to the pipeline's run-id generator rather than minting a second
    format: a review run and a storage run are the same kind of thing to a
    reader browsing ``.artifacts``, and two id schemes would make them look
    unrelated.
    """
    from edgar_sec.pipelines.document_storage.operator import new_run_id

    return new_run_id("review")


def _write_pretty_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one review JSON file, pretty-printed and newline-terminated.

    Pretty rather than canonical because a reviewer opens these in an editor and
    diffs them by eye, and compact JSON turns a two-field change into a single
    replaced line. The trailing newline is not cosmetic either: without it
    ``diff`` and git both mark the file ``\\ No newline at end of file``, adding a
    line of noise to precisely the comparison this tool exists to make.
    """
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_review_artifacts(
    result: ReviewCaseResult, output_dir: Path, fixture_id: str
) -> dict[str, Any]:
    """Write one document's review case and return its manifest entry.

    Four files, each answering one question: ``.txt`` what the normalizer
    produced, ``.source.txt`` what it was given, ``.analysis.json`` why the
    output looks like it does, and ``.html`` what a browser was handed.

    The source is written as the original bytes rather than a re-encoded
    string, because a 1990s latin-1 filing decoded to UTF-8 and back is not the
    file that was fetched, and without it "did the normalizer lose this, or was
    it never there" would have to be re-derived from the fixture.

    There is deliberately no per-case ``.metadata.json``: every field such a file
    would hold is already in the run manifest, so it would be a second copy of
    the same facts in a per-document file that then had to be diffed alongside
    the manifest.
    """
    case = result.case
    case_id = case.document.doc_id
    output_dir.mkdir(parents=True, exist_ok=True)
    # Trailing newline so the file is a well-formed text file and so two runs
    # that differ only in a missing final newline still diff.
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

    Refuses to write into a non-empty directory. Two runs that share an output
    root cannot be compared -- the second would overwrite the first, and the
    diff would report nothing -- so a code change means a new run id, which is
    the whole point of the workflow.
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
