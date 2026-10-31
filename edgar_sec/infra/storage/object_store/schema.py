"""SQLite schema owned by the generic object store."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspace_sessions (
    session_id TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_workspace_session (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    session_id TEXT NOT NULL REFERENCES workspace_sessions(session_id) ON DELETE CASCADE,
    switched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS objects (
    object_id TEXT PRIMARY KEY,
    schema_name TEXT NOT NULL,
    parent_object_id TEXT REFERENCES objects(object_id) ON DELETE SET NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_objects_parent ON objects (parent_object_id);

CREATE TABLE IF NOT EXISTS object_session_aliases (
    session_id TEXT NOT NULL REFERENCES workspace_sessions(session_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, alias_name)
);
CREATE INDEX IF NOT EXISTS idx_session_aliases_target
    ON object_session_aliases (target_id);
"""
