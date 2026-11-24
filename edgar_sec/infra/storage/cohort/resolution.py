"""Cohort identifier resolution and official-source active pointers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from .errors import CohortIdentifierError

_OFFICIAL_SOURCE_NAMES = frozenset(
    {
        "cik_lookup",
        "company_tickers",
        "company_tickers_exchange",
        "company_tickers_mf",
        "ticker_txt",
    }
)

_OFFICIAL_SOURCE_ALIASES = {
    "universe": "cik_lookup",
    "tickers": "company_tickers",
    "exchange": "company_tickers_exchange",
    "funds": "company_tickers_mf",
    "ticker-file": "ticker_txt",
}


_HEX_PREFIX_RE = re.compile(r"[0-9a-fA-F]+")


class ResolutionMixin:
    """Identifier resolution and source pointers mixed into the catalog."""

    def resolve_cohort_identifier(
        self, id_or_name: str, *, min_prefix_len: int = 7
    ) -> CohortRecord:
        if min_prefix_len < 1:
            raise ValueError("min_prefix_len must be positive")
        source_name = _OFFICIAL_SOURCE_ALIASES.get(id_or_name)
        if source_name is not None:
            with self._connection() as connection:
                pointer = connection.execute(
                    "SELECT active_snapshot_id FROM source_active_pointers WHERE source_name = ?",
                    (source_name,),
                ).fetchone()
                if pointer is None:
                    raise CohortIdentifierError(
                        f"no active {id_or_name} cohort is published"
                    )
                row = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ?",
                    (pointer["active_snapshot_id"],),
                ).fetchone()
                if row is None:
                    raise CohortIdentifierError(
                        f"active {id_or_name} source pointer references a missing cohort"
                    )
                record = self._record(connection, row)
                if record.origin_kind != "official_source" or not record.pinned:
                    raise CohortIdentifierError(
                        f"active {id_or_name} source pointer is not an official pinned cohort"
                    )
                try:
                    details = json.loads(record.origin_json)
                except json.JSONDecodeError as exc:
                    raise CohortIdentifierError(
                        f"active {id_or_name} source metadata is invalid"
                    ) from exc
                if (
                    not isinstance(details, dict)
                    or details.get("source_name") != source_name
                ):
                    raise CohortIdentifierError(
                        f"active {id_or_name} source pointer belongs to a different source"
                    )
                return record
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM cohorts WHERE name = ? LIMIT 1", (id_or_name,)
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ? LIMIT 1", (id_or_name,)
                ).fetchone()
            if row is not None:
                return self._record(connection, row)
            prefix = id_or_name[2:] if id_or_name.startswith("c-") else id_or_name
            if len(prefix) < min_prefix_len:
                raise CohortIdentifierError(
                    f"Ambiguous or short hash prefix {id_or_name!r}; hash lookups require at least {min_prefix_len} characters"
                )
            if _HEX_PREFIX_RE.fullmatch(prefix) is None:
                raise CohortIdentifierError(f"Cohort not found: {id_or_name!r}")
            rows = connection.execute(
                "SELECT * FROM cohorts WHERE cohort_id LIKE ? OR cohort_id LIKE ? ORDER BY cohort_id",
                (f"c-{prefix}%", f"{prefix}%"),
            ).fetchall()
            if not rows:
                raise CohortIdentifierError(f"Cohort not found: {id_or_name!r}")
            if len(rows) > 1:
                matches = ", ".join(row["cohort_id"] for row in rows)
                raise CohortIdentifierError(
                    f"Ambiguous cohort prefix {id_or_name!r}; matches {len(rows)} cohorts: [{matches}]"
                )
            return self._record(connection, rows[0])

    def set_active_source_pointer(
        self, source_name: str, active_snapshot_id: str
    ) -> None:
        if source_name not in _OFFICIAL_SOURCE_NAMES:
            raise CohortIdentifierError(f"unknown official source: {source_name!r}")
        with self._connection() as connection:
            cohort = connection.execute(
                "SELECT origin_kind, origin_json, pinned FROM cohorts WHERE cohort_id = ?",
                (active_snapshot_id,),
            ).fetchone()
            if cohort is None:
                raise CohortIdentifierError(
                    f"active source cohort not found: {active_snapshot_id!r}"
                )
            if cohort["origin_kind"] != "official_source" or not cohort["pinned"]:
                raise CohortIdentifierError(
                    "active source pointer requires an official pinned cohort"
                )
            try:
                details = json.loads(cohort["origin_json"])
            except json.JSONDecodeError as exc:
                raise CohortIdentifierError(
                    "active source cohort metadata is invalid"
                ) from exc
            if (
                not isinstance(details, dict)
                or details.get("source_name") != source_name
            ):
                raise CohortIdentifierError(
                    "active source cohort belongs to a different source"
                )
            connection.execute(
                """
                INSERT INTO source_active_pointers (source_name, active_snapshot_id, pinned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    active_snapshot_id = excluded.active_snapshot_id,
                    pinned_at = excluded.pinned_at
                """,
                (source_name, active_snapshot_id, datetime.now(UTC).isoformat()),
            )

    def get_active_source_pointer(self, source_name: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT active_snapshot_id FROM source_active_pointers WHERE source_name = ?",
                (source_name,),
            ).fetchone()
            return str(row["active_snapshot_id"]) if row is not None else None
