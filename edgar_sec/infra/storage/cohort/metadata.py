"""Cohort browsing and metadata mutation for the cohort catalog."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from .errors import CohortIdentifierError
from .models import CohortRecord


class MetadataMixin:
    """Cohort browsing and metadata mutation mixed into the catalog."""

    def list_cohorts(
        self,
        *,
        tag: str | None = None,
        pinned_only: bool = False,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CohortRecord]:
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        pattern = f"%{search}%" if search is not None else None
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.* FROM cohorts AS c
                WHERE (? IS NULL OR EXISTS (
                    SELECT 1 FROM cohort_tags AS t
                    WHERE t.cohort_id = c.cohort_id AND t.tag = ?
                ))
                AND (? = 0 OR c.pinned = 1)
                AND (? IS NULL OR c.cohort_id LIKE ? OR c.name LIKE ? OR c.description LIKE ?)
                ORDER BY c.created_at DESC, c.cohort_id
                LIMIT ? OFFSET ?
                """,
                (
                    tag,
                    tag,
                    int(pinned_only),
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [self._record(connection, row) for row in rows]

    def cohort_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) FROM cohorts").fetchone()
            return int(row[0])

    def rename_cohort(self, cohort_id: str, new_name: str) -> None:
        if not new_name:
            raise ValueError("cohort name must be non-empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE cohorts SET name = ?, updated_at = ? WHERE cohort_id = ?",
                (new_name, datetime.now(UTC).isoformat(), cohort_id),
            )
            if cursor.rowcount == 0:
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")

    def add_tags(self, cohort_id: str, tags: Sequence[str]) -> None:
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("cohort tags must be non-empty strings")
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                is None
            ):
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")
            connection.executemany(
                "INSERT OR IGNORE INTO cohort_tags (cohort_id, tag, created_at) VALUES (?, ?, ?)",
                ((cohort_id, tag, now) for tag in set(tags)),
            )
            connection.execute(
                "UPDATE cohorts SET updated_at = ? WHERE cohort_id = ?",
                (now, cohort_id),
            )

    def remove_tags(self, cohort_id: str, tags: Sequence[str]) -> None:
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("cohort tags must be non-empty strings")
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                is None
            ):
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")
            connection.executemany(
                "DELETE FROM cohort_tags WHERE cohort_id = ? AND tag = ?",
                ((cohort_id, tag) for tag in set(tags)),
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE cohorts SET updated_at = ? WHERE cohort_id = ?",
                (now, cohort_id),
            )
