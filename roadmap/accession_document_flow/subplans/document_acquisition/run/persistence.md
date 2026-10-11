# S9 run persistence and SQL

## Purpose and status

The implemented run-state ledger is SQLite schema v2. The operation-aware design below
defines replacement schema v3: target acquisition stays transactional, operation
materialization gets an independent current-state row and append-only attempts, and the
immutable work relation set remains Parquet. This does not use DuckDB for high-frequency
state updates.

## Database schema

Every writable connection enables `PRAGMA foreign_keys=ON`; database creation sets
`PRAGMA user_version=2`. The manifest pins this run-state schema version. Use
constant DDL and bound values:

```sql
CREATE TABLE target_state (
    target_id TEXT PRIMARY KEY,
    executable INTEGER NOT NULL CHECK (executable IN (0, 1)),
    skip_reason TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN
        ('pending', 'skipped', 'acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
    source TEXT CHECK (source IS NULL OR source IN ('live_sec', 'fixture_replay')),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_attempt_id TEXT,
    error_code TEXT,
    source_sha256 TEXT,
    source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
    source_body_relative_path TEXT,
    selected_sha256 TEXT,
    selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
    selected_body_relative_path TEXT,
    CHECK ((executable = 1 AND skip_reason IS NULL) OR
           (executable = 0 AND skip_reason IS NOT NULL)),
    CHECK ((outcome = 'skipped' AND executable = 0) OR
           (outcome <> 'skipped' AND executable = 1)),
    CHECK (outcome = 'failed' OR retryable = 0)
);

CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES target_state(target_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    outcome TEXT NOT NULL CHECK (outcome IN
        ('acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
    attempt_kind TEXT NOT NULL CHECK (attempt_kind IN ('document_body', 'lazy_index')),
    source TEXT NOT NULL CHECK (source IN ('live_sec', 'fixture_replay')),
    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
    error_code TEXT,
    http_status INTEGER,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT NOT NULL,
    source_sha256 TEXT,
    source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
    source_body_relative_path TEXT,
    selected_sha256 TEXT,
    selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
    selected_body_relative_path TEXT,
    UNIQUE (target_id, attempt_number),
    CHECK (outcome = 'failed' OR retryable = 0)
);

CREATE TABLE target_slot_resolutions (
    resolution_id TEXT PRIMARY KEY,
    resolution_schema_version TEXT NOT NULL,
    target_id TEXT NOT NULL REFERENCES target_state(target_id),
    selector TEXT NOT NULL CHECK (selector IN ('submitted_primary', 'exact_form_with_lazy_index')),
    expected_statutory_type TEXT NOT NULL,
    initial_sequence INTEGER NOT NULL CHECK (initial_sequence = 1),
    screen_kind TEXT NOT NULL CHECK (screen_kind IN ('none', 'sgml_type', 'html_cover')),
    screen_result TEXT NOT NULL CHECK (screen_result IN ('not_run', 'form_match', 'type_mismatch', 'unverifiable')),
    evaluator_version TEXT,
    initial_body_sha256 TEXT NOT NULL,
    index_attempt_id TEXT REFERENCES attempts(attempt_id),
    index_response_sha256 TEXT,
    index_parser_version TEXT,
    matching_entry_ids_json TEXT NOT NULL,
    selected_sequence INTEGER CHECK (selected_sequence IS NULL OR selected_sequence > 0),
    selected_retrieval_mode TEXT CHECK (selected_retrieval_mode IS NULL OR selected_retrieval_mode IN ('direct_url', 'bundle_sequence')),
    selected_url TEXT,
    result TEXT NOT NULL CHECK (result IN ('accepted_sequence_1', 'recovered', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
    recorded_at_utc TEXT NOT NULL
);

CREATE INDEX attempts_target_number ON attempts(target_id, attempt_number);
CREATE INDEX target_state_retry ON target_state(outcome, retryable, executable);
```

## Operation-aware schema v3

Schema v3 is a fresh run-state format; it refuses v2 rather than migrating partially
completed work. The immutable run manifest pins `user_version=3`. Retain the v2 tables
and add/extend these fields and relations:

- `target_state.source` accepts `live_sec`, `fixture_replay`, or `snapshot_reuse`.
- `target_state` adds the committed `source_asset_id` and latest `source_request_id`;
  `reused_snapshot_id` is non-null only when the current outcome came from reuse.
- `attempts.attempt_kind` accepts `document_body`, `lazy_index`, or `source_reuse`; its
  `source` uses the same three acquisition origins. Add nullable
  `source_request_id`, `source_asset_id`, `reused_snapshot_id`, `assignment_id`, and
  `worker_id`. Reuse attempts have no HTTP status, response digest, or response path;
  they retain the selected digest/size/path and pinned snapshot ID.
- Existing target attempt number, target outcome, and transaction semantics remain
  unchanged. The added columns let the attempt record locate its S6 input, physical
  bytes, base snapshot, and optional worker provenance without storing body bytes.

```sql
-- The v3 target_state and attempts DDL applies the extensions described above.

CREATE TABLE operation_state (
    operation_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES target_state(target_id),
    operation TEXT NOT NULL CHECK (operation IN
        ('raw', 'render_to_txt', 'render_to_xml')),
    requested INTEGER NOT NULL CHECK (requested IN (0, 1)),
    support_status TEXT NOT NULL CHECK (support_status IN
        ('supported', 'unsupported', 'not_evaluated')),
    outcome TEXT NOT NULL CHECK (outcome IN
        ('not_requested', 'unsupported', 'pending', 'blocked', 'available', 'failed')),
    reason_code TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_attempt_id TEXT,
    representation_id TEXT,
    output_sha256 TEXT,
    output_byte_size INTEGER CHECK (output_byte_size IS NULL OR output_byte_size >= 0),
    output_relative_path TEXT,
    CHECK ((requested = 0 AND outcome = 'not_requested') OR requested = 1),
    CHECK (outcome <> 'unsupported' OR support_status = 'unsupported'),
    CHECK (outcome NOT IN ('pending', 'available', 'failed') OR
           (requested = 1 AND support_status = 'supported')),
    CHECK ((outcome = 'available' AND representation_id IS NOT NULL
            AND output_sha256 IS NOT NULL AND output_byte_size IS NOT NULL) OR
           (outcome <> 'available' AND representation_id IS NULL
            AND output_sha256 IS NULL)),
    CHECK (outcome = 'failed' OR retryable = 0),
    UNIQUE (target_id, operation)
);

CREATE TABLE operation_attempts (
    operation_attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operation_state(operation_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    attempt_kind TEXT NOT NULL CHECK (attempt_kind IN
        ('identity', 'transform', 'representation_reuse')),
    outcome TEXT NOT NULL CHECK (outcome IN ('available', 'failed')),
    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
    reason_code TEXT,
    input_fingerprint_sha256 TEXT NOT NULL,
    representation_id TEXT,
    handler_id TEXT,
    handler_version TEXT,
    capability_id TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    options_sha256 TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    output_sha256 TEXT,
    output_byte_size INTEGER CHECK (output_byte_size IS NULL OR output_byte_size >= 0),
    output_relative_path TEXT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT NOT NULL,
    UNIQUE (operation_id, attempt_number),
    CHECK (outcome = 'failed' OR retryable = 0),
    CHECK ((outcome = 'available' AND output_sha256 IS NOT NULL
            AND output_byte_size IS NOT NULL AND representation_id IS NOT NULL) OR
           (outcome = 'failed' AND output_sha256 IS NULL
            AND output_byte_size IS NULL AND representation_id IS NULL))
);

CREATE INDEX operation_state_schedule ON operation_state(outcome, retryable);
CREATE INDEX operation_attempts_number
    ON operation_attempts(operation_id, attempt_number);
CREATE TRIGGER operation_attempts_no_update BEFORE UPDATE ON operation_attempts
    BEGIN SELECT RAISE(ABORT, 'operation attempt records are append-only'); END;
CREATE TRIGGER operation_attempts_no_delete BEFORE DELETE ON operation_attempts
    BEGIN SELECT RAISE(ABORT, 'operation attempt records are append-only'); END;
```

`operation_state` is seeded from every `work_operations` row. `not_requested` and
`unsupported` have no execution attempt. `pending` is schedulable only when the target
body is acquired; a terminal target failure sets the operation to `blocked` with the
target outcome as `reason_code`. `available` always references a validated output
digest; `failed` carries retryability and an error code. For `raw`, the identity attempt
uses the selected source digest for both input and output and does not make a second
payload file. Render attempts require a distinct output digest when bytes differ.

Each attempt insertion and `operation_state` update commit in one `BEGIN IMMEDIATE`
transaction after the output file has been flushed, hashed, size checked, and atomically
adopted. Operation attempts have append-only update/delete triggers. A render retry
does not reacquire a body; an acquisition retry does not rerun a renderer. `run status`
reports acquisition and processing summaries separately. Publication refuses any
`pending` operation, while `not_requested`, `unsupported`, and `blocked` remain explicit
terminal dispositions.

Snapshot reuse is an acquisition origin, not an HTTP response. Its attempt uses
`attempt_kind='source_reuse'`, `source='snapshot_reuse'`, the pinned base snapshot ID,
and the verified source/payload digest. The response-envelope digest/path are null; the
selected-body digest, size, and staged path are required. A rejected reuse candidate can
be recorded as a failed attempt before a normal source request succeeds; target state
reflects the final successful attempt while both attempts remain in history.

`initialize_run_state` in v3 consumes all work relations and seeds target and operation
state in one transaction. Target and operation completion use separate commit methods;
each appends its attempt and updates only the matching current-state projection after
the output file is adopted. There is no mutable `chunk_state`: chunk completion is
derived from immutable `work_chunks` membership and member target states. Worker import
validates a complete chunk first and commits it in one transaction; assignment and
receipt affinity remain in common distribution metadata.

The current v2 schema added `required_missing`, index lookup attempts, and
target-slot resolutions, initializes at `PRAGMA user_version=2`, and refuses v1
databases. Schema v3 then refuses v2 rather than guessing how to extend an active run.
The exact URL fields exclude credentials, query strings, and response headers. Attempt
and resolution rows are append-only; current status is an updateable projection in
`target_state`. S10 body-consumption receipts remain separate versioned JSON sidecars
so S10 can write them through the S9 path/schema contracts without importing the S9
state service.

## Transaction API

```python
def initialize_run_state(
    database_path: Path,
    targets: Iterable[WorkOrderTarget],
) -> None: ...

def append_attempt_and_update_target(
    database_path: Path,
    attempt: AcquisitionAttempt,
    outcome: AcquisitionOutcome,
) -> None: ...

def summarize_target_state(database_path: Path) -> AcquisitionStatusCounts: ...
```

Initialization inserts every work-order target in one transaction; a duplicate
`target_id` violates the primary key and refuses projection. Each completion commits
the attempt row and current target projection in one `BEGIN IMMEDIATE` transaction.
An acquired row is written only after its staged file is flushed, hashed, size
checked, and atomically adopted. If the DB commit fails, the staged body is removed
or treated as an unreferenced temporary; it is never reported acquired.

All query parameters use SQLite `?` binding. SQL statement text is constant; IDs,
URLs, error messages, paths, and timestamps are never interpolated. Status opens the
DB read-only and reports `PRAGMA integrity_check`/foreign-key errors without repair.
It does not reset attempts, clear locks, or checkpoint by mutation.

## Lock contract

The exclusive run lock is a generated JSON sidecar adjacent to the DB, created with
exclusive file creation. It records run ID, host, PID, start time, and an owner
token. Release removes the lock only if the token still matches. Active local locks
block a second runner; stale same-host PID takeover requires explicit confirmation.
Remote-host locks cannot be proven stale from a PID and require operator recovery.

The SQLite transaction serializes state updates; the sidecar lock prevents two
coordinators from independently scheduling one run. Worker bundles use separate
local ledgers and merge through distribution import, never by concurrently opening
the coordinator database on another host.

## Derived SQL reports

The status summary groups outcomes without loading all targets into memory:

```sql
SELECT outcome, COUNT(*) AS target_count
FROM target_state
GROUP BY outcome
ORDER BY outcome;

SELECT COUNT(*) AS retryable_failure_count
FROM target_state
WHERE outcome = ? AND retryable = ?;
```

The second query binds `failed` and `1`. Per-target detail is filtered by bound
`target_id`; status does not emit document bytes or scan published payload columns. A required
target resolved absent by a recognized lazy index is terminal `required_missing` and
contributes to `complete_with_errors`; optional `not_filed` remains a valid terminal
outcome.

## Tests

Temporary-database tests cover schema version refusal, foreign keys, duplicate target
IDs, transaction rollback, append-only attempt history, failed-then-acquired retry,
body-file/DB commit ordering, read-only status during a writer transaction, DB
corruption, lock ownership, stale-lock refusal, and parameter-bound IDs containing
SQL metacharacters. No test uses the repository artifact tree.
