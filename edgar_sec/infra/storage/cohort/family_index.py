"""Active family-index pointer administration for the cohort catalog."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest

from .errors import CohortIdentifierError
from .models import FamilyIndexRecord

_FAMILY_INDEX_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class FamilyIndexMixin:
    """Family-index pointer administration mixed into the catalog."""

    def set_active_family_index(
        self,
        universe_cohort_id: str,
        family_index_id: str,
        rules_fingerprint: str,
        dataset_sha256: str,
    ) -> None:
        if not isinstance(family_index_id, str) or not _FAMILY_INDEX_ID_RE.fullmatch(
            family_index_id
        ):
            raise ValueError(
                "family_index_id must be 32 lowercase hexadecimal characters"
            )
        if not is_sha256_hex_digest(rules_fingerprint):
            raise ValueError("rules_fingerprint must be a lowercase SHA-256 digest")
        if not is_sha256_hex_digest(dataset_sha256):
            raise ValueError("dataset_sha256 must be a lowercase SHA-256 digest")

        dataset_file = self.paths.family_index_file(family_index_id)
        relative_dataset = self.paths.relative_path(dataset_file)
        expected_dataset = f"family_index/{family_index_id}/company_family.parquet"
        if relative_dataset != expected_dataset:
            raise ValueError("family index path is not canonical")
        if not dataset_file.is_file():
            raise ValueError("family index dataset file is missing")
        if file_sha256(dataset_file) != dataset_sha256:
            raise ValueError("family index dataset digest does not match")

        pinned_at = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM cohorts WHERE cohort_id = ?", (universe_cohort_id,)
                ).fetchone()
                is None
            ):
                raise CohortIdentifierError(
                    f"Universe cohort not found: {universe_cohort_id!r}"
                )
            connection.execute(
                """
                INSERT INTO active_family_indices (
                    universe_cohort_id, family_index_id, rules_fingerprint,
                    dataset_path, dataset_sha256, pinned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(universe_cohort_id) DO UPDATE SET
                    family_index_id = excluded.family_index_id,
                    rules_fingerprint = excluded.rules_fingerprint,
                    dataset_path = excluded.dataset_path,
                    dataset_sha256 = excluded.dataset_sha256,
                    pinned_at = excluded.pinned_at
                """,
                (
                    universe_cohort_id,
                    family_index_id,
                    rules_fingerprint,
                    relative_dataset,
                    dataset_sha256,
                    pinned_at,
                ),
            )

    def get_active_family_index(
        self, universe_cohort_id: str
    ) -> FamilyIndexRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM active_family_indices WHERE universe_cohort_id = ?",
                (universe_cohort_id,),
            ).fetchone()
            if row is None:
                return None
            return FamilyIndexRecord(
                universe_cohort_id=row["universe_cohort_id"],
                family_index_id=row["family_index_id"],
                rules_fingerprint=row["rules_fingerprint"],
                dataset_path=row["dataset_path"],
                dataset_sha256=row["dataset_sha256"],
                pinned_at=row["pinned_at"],
            )

    def list_family_indices(
        self,
        *,
        universe_cohort_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FamilyIndexRecord]:
        """List family index records, optionally filtered by universe cohort."""
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        with self._connection() as connection:
            if universe_cohort_id is not None:
                rows = connection.execute(
                    "SELECT * FROM active_family_indices WHERE universe_cohort_id = ? "
                    "ORDER BY pinned_at DESC LIMIT ? OFFSET ?",
                    (universe_cohort_id, limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM active_family_indices ORDER BY pinned_at DESC "
                    "LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [
                FamilyIndexRecord(
                    universe_cohort_id=row["universe_cohort_id"],
                    family_index_id=row["family_index_id"],
                    rules_fingerprint=row["rules_fingerprint"],
                    dataset_path=row["dataset_path"],
                    dataset_sha256=row["dataset_sha256"],
                    pinned_at=row["pinned_at"],
                )
                for row in rows
            ]
