"""Parquet store for the materialized text index over acquired holdings.

Relations are plain Parquet files under one index root, keyed by payload
SHA-256, so a build is a set of immutable files a query opens read-only.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.runtime.paths import resolve_paths

from .duckdb import connect, sql_identifier, sql_path_list
from .parquet import read_parquet_table, write_parquet_table

CHUNKS_FILE = "chunks.parquet"
POSTINGS_FILE = "postings.parquet"
TERM_STATS_FILE = "term_stats.parquet"
DOCUMENTS_FILE = "documents.parquet"
CORPUS_STATS_FILE = "corpus_stats.parquet"

INDEX_FILES = (
    CHUNKS_FILE,
    POSTINGS_FILE,
    TERM_STATS_FILE,
    DOCUMENTS_FILE,
    CORPUS_STATS_FILE,
)

DOCUMENTS_SCHEMA = pa.schema(
    [
        ("payload_sha256", pa.string(), False),
        ("accession", pa.string(), False),
        ("cik", pa.int64(), True),
        ("form", pa.string(), True),
        ("filename", pa.string(), False),
        ("logical_document_id", pa.string(), True),
        ("document_role", pa.string(), True),
        ("source", pa.string(), False),
        ("filing_date", pa.string(), True),
    ]
)

CHUNKS_SCHEMA = pa.schema(
    [
        ("chunk_id", pa.string(), False),
        ("payload_sha256", pa.string(), False),
        ("section_name", pa.string(), True),
        ("note_label", pa.string(), True),
        ("start_line", pa.int64(), False),
        ("end_line", pa.int64(), False),
        ("chunk_text", pa.string(), False),
        ("chunk_length", pa.int64(), False),
    ]
)

POSTINGS_SCHEMA = pa.schema(
    [
        ("term", pa.string(), False),
        ("chunk_id", pa.string(), False),
        ("term_frequency", pa.int64(), False),
        ("chunk_length", pa.int64(), False),
    ]
)

TERM_STATS_SCHEMA = pa.schema(
    [
        ("term", pa.string(), False),
        ("chunk_frequency", pa.int64(), False),
        ("total_frequency", pa.int64(), False),
    ]
)

CORPUS_STATS_SCHEMA = pa.schema(
    [
        ("source_snapshot_id", pa.string(), True),
        ("built_at", pa.string(), False),
        ("accession_count", pa.int64(), False),
        ("document_count", pa.int64(), False),
        ("payload_count", pa.int64(), False),
        ("chunk_count", pa.int64(), False),
        ("posting_count", pa.int64(), False),
        ("term_count", pa.int64(), False),
        ("total_tokens", pa.int64(), False),
        ("avg_chunk_length", pa.float64(), False),
        ("new_payload_count", pa.int64(), False),
        ("reused_payload_count", pa.int64(), False),
    ]
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TERM_LENGTH = 2
WINDOW_MAX_LINES = 200
WINDOW_MAX_CHARS = 16_000


def tokenize(text: str) -> Counter[str]:
    """Term counts for one chunk; terms are lowercase alphanumerics, len >= 2."""
    counts: Counter[str] = Counter()
    for match in _TOKEN_RE.finditer(text.lower()):
        term = match.group(0)
        if len(term) >= _MIN_TERM_LENGTH:
            counts[term] += 1
    return counts


def tokenize_query(text: str) -> list[str]:
    """Distinct query terms in first-seen order, under the index vocabulary."""
    seen: dict[str, None] = {}
    for match in _TOKEN_RE.finditer(text.lower()):
        term = match.group(0)
        if len(term) >= _MIN_TERM_LENGTH:
            seen.setdefault(term)
    return list(seen)


@dataclass(frozen=True, slots=True)
class ChunkSpan:
    """One chunk's text and provenance within its payload."""

    section_name: str | None
    note_label: str | None
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True, slots=True)
class SectionSpan:
    """A stored section or note boundary over a payload's lines."""

    name: str | None
    note_label: str | None
    start_line: int
    end_line: int


def chunk_text(text: str, sections: Sequence[SectionSpan] = ()) -> Iterator[ChunkSpan]:
    """Yield section/note chunks where boundaries exist, else line windows."""
    lines = text.splitlines()
    if sections:
        for span in sections:
            start = max(0, span.start_line - 1)
            end = min(len(lines), span.end_line)
            if end <= start:
                continue
            yield ChunkSpan(
                section_name=span.name,
                note_label=span.note_label,
                start_line=start + 1,
                end_line=end,
                text="\n".join(lines[start:end]),
            )
        return
    index = 0
    total = len(lines)
    while index < total:
        end = index
        chars = 0
        while end < total and end - index < WINDOW_MAX_LINES:
            chars += len(lines[end]) + 1
            end += 1
            if chars >= WINDOW_MAX_CHARS:
                break
        yield ChunkSpan(
            section_name=None,
            note_label=None,
            start_line=index + 1,
            end_line=end,
            text="\n".join(lines[index:end]),
        )
        index = end


def chunk_id_for(payload_sha256: str, ordinal: int) -> str:
    """Deterministic chunk id for one payload ordinal."""
    digest = hashlib.sha256(f"{payload_sha256}:{ordinal}".encode()).hexdigest()
    return digest[:32]


def default_index_root(artifacts_root: Path | str | None = None) -> Path:
    """Index root under the artifacts tree's text_search dataset."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    return root / "text_search" / "index"


class TextIndexStore:
    """File-backed index relations under one root directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path_for(self, file_name: str) -> Path:
        return self.root / file_name

    @property
    def chunks_path(self) -> Path:
        return self.path_for(CHUNKS_FILE)

    @property
    def postings_path(self) -> Path:
        return self.path_for(POSTINGS_FILE)

    @property
    def term_stats_path(self) -> Path:
        return self.path_for(TERM_STATS_FILE)

    @property
    def documents_path(self) -> Path:
        return self.path_for(DOCUMENTS_FILE)

    @property
    def corpus_stats_path(self) -> Path:
        return self.path_for(CORPUS_STATS_FILE)

    def exists(self) -> bool:
        """True only when every relation file is present."""
        return all(self.path_for(name).is_file() for name in INDEX_FILES)

    def corpus_stats(self) -> Mapping[str, object] | None:
        """The single corpus_stats row, or None when no index is stored."""
        if not self.corpus_stats_path.is_file():
            return None
        table = read_parquet_table(self.corpus_stats_path)
        if table.num_rows == 0:
            return None
        row = table.to_pylist()[0]
        return dict(row)

    def connect(self):  # noqa: ANN202 - storage Connection type is a leaf alias
        """DuckDB connection with one read-only view per index relation."""
        con = connect()
        views = {
            "chunks": self.chunks_path,
            "postings": self.postings_path,
            "term_stats": self.term_stats_path,
            "documents": self.documents_path,
            "corpus_stats": self.corpus_stats_path,
        }
        for name, path in views.items():
            view_name = sql_identifier(name)
            con.execute(
                f"CREATE OR REPLACE VIEW {view_name} AS "
                f"SELECT * FROM read_parquet({sql_path_list([str(path)])})"
            )
        return con

    def write_relation(self, file_name: str, table: pa.Table) -> int:
        """Atomically write one relation table under the index root."""
        self.root.mkdir(parents=True, exist_ok=True)
        return write_parquet_table(table, self.path_for(file_name))


__all__ = [
    "CHUNKS_FILE",
    "CHUNKS_SCHEMA",
    "CORPUS_STATS_FILE",
    "CORPUS_STATS_SCHEMA",
    "DOCUMENTS_FILE",
    "DOCUMENTS_SCHEMA",
    "INDEX_FILES",
    "POSTINGS_FILE",
    "POSTINGS_SCHEMA",
    "TERM_STATS_FILE",
    "TERM_STATS_SCHEMA",
    "WINDOW_MAX_CHARS",
    "WINDOW_MAX_LINES",
    "ChunkSpan",
    "SectionSpan",
    "TextIndexStore",
    "chunk_id_for",
    "chunk_text",
    "default_index_root",
    "tokenize",
    "tokenize_query",
]
