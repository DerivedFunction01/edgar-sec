SCHEMA_VERSION = 6


_OUTCOMES = (
    "pending",
    "skipped",
    "acquired",
    "not_filed",
    "required_missing",
    "ambiguous",
    "failed",
)


_SCHEMA = (
    """CREATE TABLE target_state (
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
    )""",
    """CREATE TABLE attempts (
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
        selected_filename TEXT,
        UNIQUE (target_id, attempt_number),
        CHECK (outcome = 'failed' OR retryable = 0)
    )""",
    """CREATE TABLE target_slot_resolutions (
        resolution_id TEXT PRIMARY KEY,
        resolution_schema_version TEXT NOT NULL,
        target_id TEXT NOT NULL REFERENCES target_state(target_id),
        selector TEXT NOT NULL CHECK (selector IN ('submitted_primary', 'exact_form_with_lazy_index', 'sgml_bundle_scan')),
        expected_statutory_type TEXT NOT NULL,
        initial_sequence INTEGER CHECK (initial_sequence IS NULL OR initial_sequence = 1),
        screen_kind TEXT NOT NULL CHECK (screen_kind IN ('none', 'sgml_type', 'html_cover')),
        screen_result TEXT NOT NULL CHECK (screen_result IN ('not_run', 'form_match', 'type_mismatch', 'unverifiable')),
        evaluator_version TEXT,
        initial_body_sha256 TEXT NOT NULL,
        index_attempt_id TEXT REFERENCES attempts(attempt_id),
        index_response_sha256 TEXT,
        index_parser_version TEXT,
        matching_entry_ids_json TEXT NOT NULL,
        selected_sequence INTEGER CHECK (selected_sequence IS NULL OR selected_sequence > 0),
        selected_retrieval_mode TEXT CHECK (selected_retrieval_mode IS NULL OR selected_retrieval_mode IN ('direct_url', 'bundle_sequence', 'bundle_scan')),
        selected_url TEXT,
        result TEXT NOT NULL CHECK (result IN ('accepted_sequence_1', 'recovered', 'selected_in_bundle', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
        recorded_at_utc TEXT NOT NULL
    )""",
    "CREATE INDEX attempts_target_number ON attempts(target_id, attempt_number)",
    "CREATE INDEX target_state_retry ON target_state(outcome, retryable, executable)",
    """CREATE TRIGGER attempts_no_update BEFORE UPDATE ON attempts
       BEGIN SELECT RAISE(ABORT, 'attempt records are append-only'); END""",
    """CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts
       BEGIN SELECT RAISE(ABORT, 'attempt records are append-only'); END""",
    """CREATE TRIGGER resolutions_no_update BEFORE UPDATE ON target_slot_resolutions
       BEGIN SELECT RAISE(ABORT, 'resolution records are append-only'); END""",
    """CREATE TRIGGER resolutions_no_delete BEFORE DELETE ON target_slot_resolutions
       BEGIN SELECT RAISE(ABORT, 'resolution records are append-only'); END""",
)


_INSERT_TARGET = """INSERT INTO target_state
    (target_id, executable, skip_reason, outcome)
    VALUES (?, ?, ?, ?)"""


_INSERT_ATTEMPT = """INSERT INTO attempts (
    attempt_id, target_id, attempt_number, outcome, attempt_kind, source, retryable,
    error_code, http_status, requested_url, final_url, started_at_utc,
    finished_at_utc, source_sha256, source_byte_size, source_body_relative_path,
    selected_sha256, selected_byte_size, selected_body_relative_path, selected_filename
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


_UPDATE_TARGET = """UPDATE target_state SET
    outcome = ?, source = ?, retryable = ?, attempt_count = ?, last_attempt_id = ?,
    error_code = ?, source_sha256 = ?, source_byte_size = ?,
    source_body_relative_path = ?, selected_sha256 = ?, selected_byte_size = ?,
    selected_body_relative_path = ?
WHERE target_id = ? AND executable = 1"""


_INSERT_RESOLUTION = """INSERT INTO target_slot_resolutions (
    resolution_id, resolution_schema_version, target_id, selector,
    expected_statutory_type, initial_sequence, screen_kind, screen_result,
    evaluator_version, initial_body_sha256, index_attempt_id,
    index_response_sha256, index_parser_version, matching_entry_ids_json,
    selected_sequence, selected_retrieval_mode, selected_url, result, recorded_at_utc
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


_SELECT_PENDING = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state WHERE outcome = 'pending' ORDER BY target_id"""


_SELECT_RETRY = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state
WHERE outcome = 'pending' OR (outcome = 'failed' AND retryable = 1)
ORDER BY target_id"""


_COUNT_OUTCOMES = (
    "SELECT outcome, COUNT(*) FROM target_state GROUP BY outcome ORDER BY outcome"
)


_COUNT_RETRYABLE = """SELECT COUNT(*) FROM target_state
WHERE outcome = ? AND retryable = ?"""


_GET_TARGET = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state WHERE target_id = ?"""


_GET_ATTEMPT = """SELECT attempt_id, target_id, attempt_number, attempt_kind, source,
    requested_url, outcome, retryable, error_code, http_status, final_url,
    started_at_utc, finished_at_utc, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path, selected_filename
FROM attempts WHERE target_id = ? AND attempt_id = ?"""


_COUNT_ATTEMPTED = "SELECT COUNT(*) FROM target_state WHERE attempt_count > 0"


__all__ = [
    "SCHEMA_VERSION",
]
