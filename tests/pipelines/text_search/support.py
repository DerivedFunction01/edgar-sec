"""Cache-store fixtures for text_search pipeline tests."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from edgar_sec.foundation.hashing import sha256_bytes

_DDL = """
CREATE TABLE IF NOT EXISTS cached_documents (
    accession TEXT NOT NULL,
    cik INTEGER NOT NULL,
    form TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content BLOB NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (accession, filename)
)
"""


def make_cache_db(path: Path, documents: list[tuple[str, int, str, str, str]]) -> Path:
    """Create a DocumentCache-shaped sqlite file holding plain-text documents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute(_DDL)
        for accession, cik, form, filename, text in documents:
            content = text.encode("utf-8")
            con.execute(
                "INSERT INTO cached_documents (accession, cik, form, filename, "
                "content_type, sha256, byte_size, content, cached_at) "
                "VALUES (?, ?, ?, ?, 'text/plain', ?, ?, ?, ?)",
                (
                    accession,
                    cik,
                    form,
                    filename,
                    sha256_bytes(content),
                    len(content),
                    content,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ),
            )
        con.commit()
    finally:
        con.close()
    return path
