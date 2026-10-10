# S9 acquisition paths

## Purpose and status

This is the sole path-layout contract for acquisition runs, fixtures, S10 review
outputs, and S11 snapshots. It follows the inventory split between retained
artifacts, transient resumable runs, and shared runtime/distribution roots. The path
owner implements project/run, fixture, and review roots; chunk attempts, body receipts,
distribution bundles, and S11 snapshot paths remain future execution contracts.

## Resolved path API

```python
from edgar_sec.foundation.runtime.fixtures import FixturePaths
from edgar_sec.infra.storage.review.paths import ReviewPaths

@dataclass(frozen=True, slots=True)
class AcquisitionPaths:
    project: ProjectPaths

    @property
    def artifacts_root(self) -> Path: ...
    @property
    def transient_root(self) -> Path: ...
    @property
    def runtime_root(self) -> Path: ...
    @property
    def runs_root(self) -> Path: ...
    @property
    def fixtures_root(self) -> Path: ...
    def target_plan_dir(self, plan_id: str) -> Path: ...
    def fixture_paths(self, fixture_id: str) -> FixturePaths: ...
    def fixture_root(self, fixture_id: str) -> Path: ...
    def fixture_manifest_path(self, fixture_id: str) -> Path: ...
    def fixture_database_path(self, fixture_id: str) -> Path: ...
    @property
    def review_runs_root(self) -> Path: ...
    def review_paths(self, review_id: str) -> ReviewPaths: ...
    @property
    def snapshots_root(self) -> Path: ...
    def run_dir(self, run_id: str) -> Path: ...
    def run_manifest_path(self, run_id: str) -> Path: ...
    def work_order_root(self, run_id: str) -> Path: ...
    def run_state_path(self, run_id: str) -> Path: ...
    def run_lock_path(self, run_id: str) -> Path: ...
    def run_cancelled_path(self, run_id: str) -> Path: ...
    def run_staging_root(self, run_id: str) -> Path: ...

def resolve_acquisition_paths(
    repo_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> AcquisitionPaths: ...
```

`artifacts_root` comes from `foundation.runtime.paths.resolve_paths()`;
`transient_root` is its shared `transient/` child and run directories use
`transient_dir(artifacts_root, "document_acquisition", run_id)`. `runtime_root` and
`distribution_root` use their shared foundation resolvers, with the distribution root
remaining a separate `ProjectPaths` root. Distribution adapter methods own bundle
destinations rather than acquisition-specific path helpers. `fixture_paths()`
delegates to `foundation.runtime.fixtures.FixturePaths` with dataset
`document_acquisition` and the shared SQLite filename `fixture.sqlite`.
`review_paths()` delegates run/manifest/case layout to
`infra.storage.review.paths.ReviewPaths`; the pipeline path owner selects only the
dataset root.

## Logical layout (not exhaustive, should be consistent with other pipelines rather than reinventing a new name, update as needed.)

```text
{artifacts_root}/
├── document_acquisition/
│   ├── fixtures/
│   │   └── {fixture_id}/
│   │       ├── manifest.json
│   │       └── fixture.sqlite
│   ├── review-runs/
│       └── {review_id}/
│           ├── manifest.jsonl
│           └── cases/{target_id}/
│               ├── source.inert.html       # optional sanitized HTML preview
│               ├── representation.txt     # optional selected text review output
│               └── processing.json
│   └── snapshots/                           # DAG metadata and binary/text payload Parquet
├── transient/
│   └── document_acquisition/
│       └── {run_id}/
│           ├── chunks/
│           │   └── {chunk_id}/attempt-{attempt_id}/
│           │       ├── outcomes.parquet
│           │       └── manifest.json
│           ├── handoff/receipts/{target_id}/{selected_sha256}.json
│           ├── staging/
│           │   ├── incoming/{attempt_id}
│           │   └── selected/{attempt_id}
│           ├── work_order/
│           │   └── part-*.parquet
│           ├── cancelled.json
│           ├── run.lock
│           ├── run_manifest.json
│           └── state.sqlite
├── runtime/
│   └── {broker_id}.sock
└── ... other pipeline roots

{distribution_root}/acquisition/{run_id[:8]}/
└── ... bundles owned by shared distribution infrastructure
```

This follows the existing distribution adapters' default
`distribution_root / pipeline_name / plan_id[:8]`; S9 uses `acquisition` as the
pipeline name and the run ID as its distribution plan ID.

The layout tree is the target S9/S10/S11 contract, not evidence that every path has a
writer. Current path resolution creates no directories or files.

Fixture, review, and snapshot artifacts are retained under the pipeline root.
Run manifests, work orders, mutable state, attempt chunks, and staged
source/selected/processed bodies are resumable transient state under the common
transient root; they are not published payloads and do not auto-expire. The
selected-body receipt is a versioned JSON sidecar under the handoff directory.
`fixture.sqlite` contains S9 fixture metadata and Zstandard-compressed exact
source-response BLOBs. Snapshot relation files, including separate binary and text
payload Parquet relations, use the shared DAG layout under `snapshots_root`; payload
bytes are not stored in a separate directory. DAG reachability governs retention of
snapshot parts.

There is no retained `document_acquisition/runs/` tree: S9 runs are operational
executions over an already-retained S6 plan and live under the shared transient root.
Published target results and payload references live in immutable DAG snapshots, not
copied run directories.

## Raw and processed representations

`StagedBodyRef.sha256` identifies the exact selected source bytes. For direct HTML,
those are the raw HTML bytes; for a bundle target they are the selected child bytes,
while the full bundle response remains separately identified. Fixture capture stores
the full source response in SQLite and replay re-derives a bundle child.
`source.inert.html` is only a sanitized review view and is never treated as raw HTML
evidence.

S10 result metadata keeps source and output digests separate. Plain ASCII `.txt` is a
`text_verbatim` identity result with equal digests and no normalization call. HTML
normalization produces a distinct text digest while its exact source remains
available through replay when the source fixture was captured. Validated standalone
XML is `xml_verbatim` and aliases the source digest rather than writing a duplicate
representation. PDF retains raw source only; extraction is deferred. S10 outputs are
transient until the acquisition snapshot publisher adopts a distinct derived
representation into the text Parquet relation or S7 explicitly retains a review
output. Identity representations alias their source digest and do not create
duplicate payload rows.

## Identity and containment

- Run, fixture, review, target, chunk, and attempt IDs pass the shared safe-ID
  validator before joining paths. IDs are never copied from URLs, accessions,
  filenames, or arbitrary command input.
- Run paths resolve beneath the transient acquisition root, fixture paths beneath the
  retained fixture root, and review paths beneath `review-runs`; containment is checked
  against each owning root. Symlink/path traversal is refused.
- Fixture IDs resolve through `foundation.runtime.fixtures.FixturePaths` to immutable
  `manifest.json` and SQLite `fixture.sqlite`; no per-body path is generated.
- Review run, manifest, cases, and staging paths are owned by
  `infra.storage.review.paths.ReviewPaths`; pipeline owners select the dataset root.
- Staging filenames are generated by the staging owner, not by target IDs or SEC
  paths. An attempt writes to a temporary file and atomically adopts a completed
  body reference only after byte count and digest verification.
- A body-consumption receipt path is deterministically derived from the validated
  run/target IDs and selected-body digest. S10 writes the versioned receipt through
  the S9 path contract; snapshot Parquet publication or explicit discard separately
  authorizes staged-file cleanup.
- Distribution bundle paths are generated by the shared distribution owner and
  validated again on import; a worker-provided relative path cannot escape its
  configured distribution root or overwrite another run.

## API refusal behavior

```python
def validate_run_id(run_id: str) -> str: ...
def validate_fixture_id(fixture_id: str) -> str: ...
def validate_review_id(review_id: str) -> str: ...
def validate_target_id(target_id: str) -> str: ...
def validate_attempt_id(attempt_id: str) -> str: ...
def validate_chunk_id(chunk_id: str) -> str: ...
def validate_response_digest(sha256: str) -> str: ...
def resolve_acquisition_paths(...) -> AcquisitionPaths: ...
```

Invalid IDs, roots outside their configured owner, symlink escapes, malformed
digests, and existing path components with the wrong file/directory kind are refused
with `ValueError`. Path resolution itself creates no run, fixture, review, or staging
files.

## Acceptance

Every command, worker, fixture API, and processing-review adapter obtains paths
through this owner. Tests use `tmp_path`; no generated fixture, review, or run output
is written into the repository tree.
