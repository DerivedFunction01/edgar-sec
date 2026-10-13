"""Quota selection over a feature snapshot."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any

from tqdm import tqdm

from edgar_sec.engine.selection.policy import (
    KNOWN_DIMENSIONS,
    SeedFiler,
    SelectionPolicy,
    normalize_value,
)
from edgar_sec.engine.selection.cell_allocation import (
    account_staged_candidates,
    equalized_cell_targets,
)
from edgar_sec.engine.selection.source import (
    POOL_COLUMNS,
    CandidateFilters,
    CandidateSource,
)
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)

CLASSIFICATION_DIMENSIONS = (
    "company_family",
    "form",
    "era",
    "sic_code",
    "entity_type",
    "lifecycle_class",
)
DEFAULT_RESERVE_MAX_PAGES = 100
_ACTIVE_TABLE = "active_locator_keys"
_RESERVE_TABLE = "reserve_locator_keys"
_COVERAGE_TABLE = "selection_coverage"
_EXHIBIT_ACCESSIONS_TABLE = "selection_exhibit_accessions"
_SIGNATURE_TABLE = "selection_signatures"
_CELL_TABLE = "selection_cells"


@dataclass(frozen=True, slots=True)
class SelectionResult:
    active_keys_path: Path
    reserve_keys_path: Path
    active_count: int
    reserve_count: int
    report: dict[str, Any] = field(default_factory=dict)
    snapshot_dir: Path = Path()
    _temporary_directory: TemporaryDirectory[str] | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def active_locators(self) -> Iterator[str]:
        return _stream_column(self.active_keys_path, "document_locator_key")

    @property
    def reserve_locators(self) -> Iterator[str]:
        return _stream_column(self.reserve_keys_path, "document_locator_key")

    @property
    def active_candidates(self) -> Iterator[dict[str, Any]]:
        return _stream_candidates(
            self.snapshot_dir, self.active_keys_path, reserve=False
        )

    @property
    def reserve_candidates(self) -> Iterator[dict[str, Any]]:
        return _stream_candidates(
            self.snapshot_dir, self.reserve_keys_path, reserve=False
        )

    def close(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()


def _stream_column(path: Path, column: str) -> Iterator[str]:
    with connect() as con:
        cursor = con.execute(
            f"SELECT {column} FROM read_parquet(?) ORDER BY {column}", [str(path)]
        )
        while row := cursor.fetchone():
            yield str(row[0])


def _stream_candidates(
    snapshot_dir: Path, keys_path: Path, *, reserve: bool
) -> Iterator[dict[str, Any]]:
    from edgar_sec.engine.selection.snapshot import load_snapshot_paths

    snapshot = load_snapshot_paths(snapshot_dir)
    projection = ", ".join(f"l.{column}" for column in POOL_COLUMNS)
    with connect() as con:
        cursor = con.execute(
            f"SELECT {projection} FROM {snapshot.locator_relation} l "
            "JOIN read_parquet(?) k USING (document_locator_key) "
            "ORDER BY l.document_locator_key",
            [str(keys_path)],
        )
        while row := cursor.fetchone():
            yield dict(zip(POOL_COLUMNS, row, strict=True))


def classification_signature(candidate: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        normalize_value(candidate.get(dimension))
        for dimension in CLASSIFICATION_DIMENSIONS
    )


class DeficitSelector:
    def __init__(
        self,
        snapshot_dir: str | Path,
        policy: SelectionPolicy,
        seed_filers: dict[str, SeedFiler] | None = None,
        *,
        seed_cik_relation: str | None = None,
        page_size: int | None = None,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.policy = policy
        self.seed_filers = seed_filers or {}
        self.seed_cik_relation = seed_cik_relation
        self.page_size = page_size or policy.page_size
        self._threads = threads
        self._memory_limit = memory_limit

    def select(
        self,
        parent_locator_path: str | Path | None = None,
        *,
        progress: ProgressCallback = None,
    ) -> SelectionResult:
        target_units = self.policy.requested_units()
        source = CandidateSource(
            self.snapshot_dir,
            self.policy.seed,
            page_size=self.page_size,
            filters=CandidateFilters(
                document_suffixes=tuple(self.policy.document_suffixes),
                max_reported_size=self.policy.max_reported_size,
                date_selection=self.policy.date_selection_clauses,
            ),
            threads=self._threads,
            memory_limit=self._memory_limit,
        )
        owner = TemporaryDirectory(prefix="selection-state-")
        state_dir = Path(owner.name)
        active_path = state_dir / "active_keys.parquet"
        reserve_path = state_dir / "reserve_keys.parquet"
        con: Any
        active_count = 0
        reserve_count = 0
        deduplicated_signatures = 0
        allocation: dict[str, Any] = {}

        with source.session(
            database=state_dir / "selection.duckdb",
            temp_directory=state_dir / "duckdb-temp",
        ):
            con = source._require()
            self._create_state(con)
            if parent_locator_path is not None:
                parent_relation = (
                    "SELECT document_locator_key FROM read_parquet("
                    f"{sql_literal(str(Path(parent_locator_path).resolve()))})"
                )
                parent_count, distinct_count = con.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT document_locator_key) "
                    f"FROM ({parent_relation})"
                ).fetchone()
                if parent_count != distinct_count:
                    raise ValueError("parent selection contains duplicate locator keys")
                source.register_selected_relation(parent_relation)
                con.execute(
                    f"INSERT INTO {_ACTIVE_TABLE} "
                    f"SELECT document_locator_key FROM ({parent_relation})"
                )
                missing = con.execute(
                    f"SELECT document_locator_key FROM ({parent_relation}) p "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {source.locator_relation} l "
                    "WHERE l.document_locator_key = p.document_locator_key) "
                    "ORDER BY document_locator_key LIMIT 5"
                ).fetchone()
                if missing:
                    raise ValueError(
                        "parent plan references locator keys absent from the selection "
                        f"snapshot: {missing[0]}"
                    )
                for candidate in source.load_candidates_for_locator_relation(
                    parent_relation
                ):
                    self._account(con, candidate)
                active_count = int(parent_count)
            else:
                active_count = 0

            emit_progress(progress, {"type": "merge_stage", "stage": "selection_seeds"})
            active_count += self._select_seed_filers(
                source, con, active_count, target_units
            )
            emit_progress(
                progress, {"type": "merge_stage", "stage": "selection_composites"}
            )
            added, composite_deduplicated = self._select_composites(
                source, con, active_count, target_units
            )
            active_count += added
            deduplicated_signatures += composite_deduplicated
            emit_progress(
                progress, {"type": "merge_stage", "stage": "selection_floors"}
            )
            active_count, floor_deduplicated = self._select_floors(
                source, con, active_count, target_units
            )
            deduplicated_signatures += floor_deduplicated
            emit_progress(
                progress, {"type": "merge_stage", "stage": "selection_form_era"}
            )
            allocation, active_count, allocation_deduplicated = (
                self._allocate_form_era_cells(
                    source, con, active_count, target_units, progress
                )
            )
            deduplicated_signatures += allocation_deduplicated
            emit_progress(
                progress, {"type": "merge_stage", "stage": "selection_weighted"}
            )
            active_count, weighted_deduplicated = self._fill_weighted(
                source, con, active_count, target_units
            )
            deduplicated_signatures += weighted_deduplicated
            emit_progress(
                progress, {"type": "merge_stage", "stage": "selection_reserve"}
            )
            reserve_count = self._select_reserve(source, con)

            active_occurrences = int(
                con.execute(
                    f"SELECT COUNT(*) FROM {source.occurrence_relation} o "
                    f"JOIN {_ACTIVE_TABLE} a USING (document_locator_key)"
                ).fetchone()[0]
            )
            coverage = self._floor_coverage(con)
            unique_families = int(
                con.execute(
                    f"SELECT COUNT(DISTINCT company_family) FROM {_SIGNATURE_TABLE} "
                    "WHERE company_family <> 'none'"
                ).fetchone()[0]
            )
            report = self._build_report(
                target_units=target_units,
                active_count=active_count,
                active_occurrences=active_occurrences,
                reserve_count=reserve_count,
                deduplicated_signatures=deduplicated_signatures,
                unique_families=unique_families,
                coverage=coverage,
                allocation=allocation,
            )
            copy_query_to_parquet(
                con,
                f"SELECT document_locator_key FROM {_ACTIVE_TABLE} "
                "ORDER BY document_locator_key",
                active_path,
            )
            copy_query_to_parquet(
                con,
                f"SELECT document_locator_key FROM {_RESERVE_TABLE} "
                "ORDER BY document_locator_key",
                reserve_path,
            )

        return SelectionResult(
            active_keys_path=active_path,
            reserve_keys_path=reserve_path,
            active_count=active_count,
            reserve_count=reserve_count,
            report=report,
            snapshot_dir=self.snapshot_dir,
            _temporary_directory=owner,
        )

    @staticmethod
    def _create_state(con: Any) -> None:
        con.execute(
            f"CREATE TEMP TABLE {_ACTIVE_TABLE} "
            "(document_locator_key VARCHAR PRIMARY KEY)"
        )
        con.execute(
            f"CREATE TEMP TABLE {_RESERVE_TABLE} "
            "(document_locator_key VARCHAR PRIMARY KEY)"
        )
        con.execute(
            f"CREATE TEMP TABLE {_COVERAGE_TABLE} "
            "(dimension VARCHAR, value VARCHAR, unit_count BIGINT, "
            "PRIMARY KEY (dimension, value))"
        )
        con.execute(
            f"CREATE TEMP TABLE {_EXHIBIT_ACCESSIONS_TABLE} "
            "(value VARCHAR, accession VARCHAR, PRIMARY KEY (value, accession))"
        )
        signature_columns = ", ".join(
            f"{dimension} VARCHAR NOT NULL" for dimension in CLASSIFICATION_DIMENSIONS
        )
        signature_keys = ", ".join(CLASSIFICATION_DIMENSIONS)
        con.execute(
            f"CREATE TEMP TABLE {_SIGNATURE_TABLE} "
            f"({signature_columns}, signature_count BIGINT, PRIMARY KEY ({signature_keys}))"
        )
        con.execute(
            f"CREATE TEMP TABLE {_CELL_TABLE} "
            "(form VARCHAR, era VARCHAR, available BIGINT, selected BIGINT, taken BIGINT, "
            "PRIMARY KEY (form, era))"
        )

    @staticmethod
    def _account(con: Any, candidate: dict[str, Any]) -> None:
        signature = classification_signature(candidate)
        signature_columns = ", ".join(CLASSIFICATION_DIMENSIONS)
        placeholders = ", ".join("?" for _ in CLASSIFICATION_DIMENSIONS)
        con.execute(
            f"INSERT INTO {_SIGNATURE_TABLE} ({signature_columns}, signature_count) "
            f"VALUES ({placeholders}, 1) ON CONFLICT ({signature_columns}) "
            "DO UPDATE SET signature_count = selection_signatures.signature_count + 1",
            signature,
        )
        cell = (str(candidate.get("form")), str(candidate.get("era")))
        con.execute(
            f"INSERT INTO {_CELL_TABLE} "
            "(form, era, available, selected, taken) VALUES (?, ?, 0, 1, 0) "
            "ON CONFLICT (form, era) DO UPDATE SET "
            "selected = selection_cells.selected + 1",
            cell,
        )
        for dimension in KNOWN_DIMENSIONS:
            value = normalize_value(candidate.get(dimension))
            if dimension == "primary_exhibit_like":
                inserted = con.execute(
                    f"INSERT INTO {_EXHIBIT_ACCESSIONS_TABLE} VALUES (?, ?) "
                    "ON CONFLICT DO NOTHING RETURNING accession",
                    [value, str(candidate["representative_accession"])],
                ).fetchone()
                if inserted is None:
                    continue
            con.execute(
                f"INSERT INTO {_COVERAGE_TABLE} VALUES (?, ?, 1) "
                "ON CONFLICT (dimension, value) DO UPDATE SET "
                "unit_count = selection_coverage.unit_count + 1",
                [dimension, value],
            )

    def _coverage_count(self, con: Any, dimension: str, value: str) -> int:
        row = con.execute(
            f"SELECT unit_count FROM {_COVERAGE_TABLE} "
            "WHERE dimension = ? AND value = ?",
            [dimension, normalize_value(value)],
        ).fetchone()
        return int(row[0]) if row else 0

    def _signature_count(self, con: Any, signature: tuple[str, ...]) -> int:
        where = " AND ".join(f"{name} = ?" for name in CLASSIFICATION_DIMENSIONS)
        row = con.execute(
            f"SELECT signature_count FROM {_SIGNATURE_TABLE} WHERE {where}",
            signature,
        ).fetchone()
        return int(row[0]) if row else 0

    def _record(
        self,
        source: CandidateSource,
        con: Any,
        candidate: dict[str, Any],
        *,
        check_cap: bool = True,
    ) -> tuple[bool, bool]:
        key = str(candidate["document_locator_key"])
        if con.execute(
            f"SELECT 1 FROM selected_keys WHERE document_locator_key = ? LIMIT 1",
            [key],
        ).fetchone():
            return False, False
        signature = classification_signature(candidate)
        capped = self.policy.max_per_company_classification
        if (
            check_cap
            and capped is not None
            and self._signature_count(con, signature) >= capped
        ):
            return False, True
        source.add_selected(key)
        con.execute(f"INSERT INTO {_ACTIVE_TABLE} VALUES (?)", [key])
        self._account(con, candidate)
        return True, False

    def _select_seed_filers(
        self, source: CandidateSource, con: Any, active_count: int, target_units: int
    ) -> int:
        if active_count >= target_units or not self.seed_filers:
            if self.seed_cik_relation is None:
                return 0
        if self.seed_cik_relation is not None:
            source.register_cik_relation(self.seed_cik_relation)
        else:
            source.register_cik_iterable(self.seed_filers)
        remaining = target_units - active_count
        if remaining <= 0:
            return 0
        added = 0
        for candidate in source.pool_for_registered_ciks(
            limit_per_cik=5, limit=remaining
        ):
            recorded, _ = self._record(source, con, candidate, check_cap=False)
            added += int(recorded)
        return added

    def _select_composites(
        self, source: CandidateSource, con: Any, active_count: int, target_units: int
    ) -> tuple[int, int]:
        added_total = 0
        deduplicated = 0
        for composite in self.policy.composites:
            required = int(composite.get("min", 1))
            added = 0
            for candidate in source.pool_for_composite(
                composite.get("filters", {}), limit=max(required * 2, 60)
            ):
                if added >= required or active_count + added_total >= target_units:
                    break
                recorded, capped = self._record(source, con, candidate)
                added += int(recorded)
                added_total += int(recorded)
                deduplicated += int(capped)
        return added_total, deduplicated

    def _deficits(self, con: Any) -> list[tuple[float, str, str, int]]:
        deficits: list[tuple[float, str, str, int]] = []
        for dimension, requirements in self.policy.floors.items():
            for value, required in requirements.items():
                if required <= 0:
                    continue
                filled = self._coverage_count(con, dimension, value)
                if filled < required:
                    deficits.append(
                        (
                            (required - filled) / required,
                            dimension,
                            value,
                            required - filled,
                        )
                    )
        deficits.sort(key=lambda item: -item[0])
        return deficits

    def _select_floors(
        self, source: CandidateSource, con: Any, active_count: int, target_units: int
    ) -> tuple[int, int]:
        deduplicated = 0
        for _ in range(self.policy.max_pool_rounds):
            if active_count >= target_units:
                return active_count, deduplicated
            deficits = self._deficits(con)
            if not deficits:
                return active_count, deduplicated
            progressed = False
            for _, dimension, value, needed in deficits:
                if active_count >= target_units:
                    break
                if dimension == "primary_exhibit_like":
                    exclude_selected_accessions = True
                else:
                    exclude_selected_accessions = False
                accepted = False
                for candidate in source.pool_for_value(
                    dimension,
                    value,
                    limit=min(needed * 2, self.policy.pool_per_value),
                    exclude_selected_accessions=exclude_selected_accessions,
                ):
                    recorded, capped = self._record(source, con, candidate)
                    deduplicated += int(capped)
                    if recorded:
                        active_count += 1
                        progressed = accepted = True
                        break
                if active_count >= target_units:
                    break
            if not progressed:
                return active_count, deduplicated
        return active_count, deduplicated

    def _allocate_form_era_cells(
        self,
        source: CandidateSource,
        con: Any,
        active_count: int,
        target_units: int,
        progress: ProgressCallback,
    ) -> tuple[dict[str, Any], int, int]:
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "selection_form_era_staging_started",
            },
        )
        staging_started = monotonic()
        with tqdm(
            desc="staging form/era candidates",
            unit="candidate",
            disable=progress is None,
        ) as availability_bar:
            availability_bar.set_postfix_str("filtering and ranking candidates")
            availability_bar.refresh()
            raw_candidate_count, candidate_count, staged_cell_count, cap_rejected = (
                source.stage_form_era_candidates(
                    CLASSIFICATION_DIMENSIONS,
                    self.policy.max_per_company_classification,
                )
            )
            source.populate_staged_cell_availability(_CELL_TABLE)
            availability_bar.total = candidate_count
            availability_bar.update(candidate_count)
            availability_bar.set_postfix_str(
                f"{candidate_count:,}/{raw_candidate_count:,} cap-eligible; "
                f"{monotonic() - staging_started:.1f}s"
            )
        cell_rows = []
        cursor = con.execute(
            f"SELECT form, era, selected, available FROM {_CELL_TABLE} "
            "WHERE selected > 0 OR available > 0 "
            f"ORDER BY {self._era_order_sql()}, form, era"
        )
        while row := cursor.fetchone():
            cell_rows.append((str(row[0]), str(row[1]), int(row[2]), int(row[3])))
        cell_count = len(cell_rows)
        available_rows = sum(cell[3] for cell in cell_rows)
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "selection_form_era_staging_complete",
                "rows": candidate_count,
                "cap_rejected": cap_rejected,
                "cells": cell_count,
                "elapsed_seconds": round(monotonic() - staging_started, 2),
            },
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "selection_form_era_availability_complete",
                "rows": available_rows,
                "cells": staged_cell_count,
            },
        )
        budget = max(0, target_units - active_count)
        if not cell_count:
            emit_progress(
                progress,
                {
                    "type": "merge_stage",
                    "stage": "selection_form_era_complete",
                    "rows": active_count,
                    "remaining": budget,
                },
            )
            return (
                {
                    "budget": budget,
                    "unallocated": budget,
                    "cap_rejected_candidates": cap_rejected,
                    "final_target_min": 0,
                    "final_target_max": 0,
                    "cells": [],
                },
                active_count,
                0,
            )
        targets = equalized_cell_targets(cell_rows, budget)
        target_rows = [
            (form, era, target - selected, order)
            for order, (form, era, selected, _) in enumerate(cell_rows)
            if (target := targets[(form, era)]) > selected
        ]
        started = monotonic()
        deduplicated = 0
        staged_count = source.stage_form_era_additions(target_rows)
        source.register_selected_relation(
            "SELECT document_locator_key FROM selection_cell_additions"
        )
        added = account_staged_candidates(
            con, CLASSIFICATION_DIMENSIONS, KNOWN_DIMENSIONS
        )
        if added != staged_count:
            raise RuntimeError(
                "staged form/era candidate count changed during accounting"
            )
        active_count += added
        remaining = max(0, target_units - active_count)
        selected_by_cell = {
            (str(form), str(era)): int(selected)
            for form, era, selected in con.execute(
                f"SELECT form, era, selected FROM {_CELL_TABLE}"
            ).fetchall()
        }
        report_cells = []
        for form, era, starting, available in cell_rows:
            target = targets[(form, era)]
            selected = selected_by_cell[(form, era)]
            report_cells.append(
                {
                    "form": form,
                    "era": era,
                    "available": available,
                    "eligible_capacity": available,
                    "starting_selected": starting,
                    "target": target,
                    "additional_target": target - starting,
                    "selected": selected,
                    "shortfall": max(0, target - selected),
                }
            )
        target_values = list(targets.values())
        report = {
            "budget": budget,
            "unallocated": remaining,
            "cap_rejected_candidates": cap_rejected,
            "final_target_min": min(target_values, default=0),
            "final_target_max": max(target_values, default=0),
            "cells": report_cells,
        }
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "selection_form_era_complete",
                "rows": active_count,
                "remaining": remaining,
                "elapsed_seconds": round(monotonic() - started, 2),
            },
        )
        return report, active_count, deduplicated

    def _era_order_sql(self) -> str:
        if not self.policy.era_bands:
            return "CASE WHEN era IS NULL THEN 0 ELSE 0 END"
        branches = " ".join(
            f"WHEN {sql_literal(band.name)} THEN {rank}"
            for rank, band in enumerate(self.policy.era_bands)
        )
        return f"CASE era {branches} ELSE {len(self.policy.era_bands)} END"

    def _fill_weighted(
        self, source: CandidateSource, con: Any, active_count: int, target_units: int
    ) -> tuple[int, int]:
        deduplicated = 0
        for page_index in range(self.policy.max_pages):
            if active_count >= target_units:
                return active_count, deduplicated
            page = source.candidate_page(page_index)
            had_candidates = False
            for candidate in page:
                had_candidates = True
                if active_count >= target_units:
                    break
                if not self._violates_cap(con, candidate, target_units):
                    recorded, capped = self._record(source, con, candidate)
                    active_count += int(recorded)
                    deduplicated += int(capped)
            if not had_candidates:
                return active_count, deduplicated
        return active_count, deduplicated

    def _violates_cap(
        self, con: Any, candidate: dict[str, Any], target_units: int
    ) -> bool:
        for dimension, cap in self.policy.caps.items():
            filled = self._coverage_count(
                con, dimension, normalize_value(candidate.get(dimension))
            )
            if (filled + 1) / target_units > cap:
                return True
        return False

    def _select_reserve(self, source: CandidateSource, con: Any) -> int:
        reserve_count = 0
        if self.policy.reserve_size <= 0:
            return reserve_count
        for page_index in range(DEFAULT_RESERVE_MAX_PAGES):
            if reserve_count >= self.policy.reserve_size:
                break
            had_candidates = False
            for candidate in source.candidate_page(page_index):
                had_candidates = True
                if reserve_count >= self.policy.reserve_size:
                    break
                key = str(candidate["document_locator_key"])
                if con.execute(
                    "SELECT 1 FROM selected_keys WHERE document_locator_key = ? LIMIT 1",
                    [key],
                ).fetchone():
                    continue
                source.add_selected(key)
                con.execute(f"INSERT INTO {_RESERVE_TABLE} VALUES (?)", [key])
                reserve_count += 1
            if not had_candidates:
                break
        return reserve_count

    def _floor_coverage(self, con: Any) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for dimension, requirements in self.policy.floors.items():
            result[dimension] = {
                str(value): self._coverage_count(con, dimension, value)
                for value in requirements
            }
        return result

    def _build_report(
        self,
        *,
        target_units: int,
        active_count: int,
        active_occurrences: int,
        reserve_count: int,
        deduplicated_signatures: int,
        unique_families: int,
        coverage: dict[str, dict[str, int]],
        allocation: dict[str, Any],
    ) -> dict[str, Any]:
        underfilled: dict[str, dict[str, dict[str, int]]] = {}
        for dimension, requirements in self.policy.floors.items():
            for value, required in requirements.items():
                filled = coverage[dimension].get(str(value), 0)
                if filled < required:
                    underfilled.setdefault(dimension, {})[value] = {
                        "required": required,
                        "selected": filled,
                        "deficit": required - filled,
                    }
        allocation_cells = allocation.get("cells") or []
        return {
            "policy_fingerprint": self.policy.policy_fingerprint,
            "corpus_id": self.policy.corpus_id,
            "level": self.policy.level,
            "target_units": target_units,
            "active_locators_count": active_count,
            "active_occurrences_count": active_occurrences,
            "reserve_locators_count": reserve_count,
            "deduplicated_company_classifications": deduplicated_signatures,
            "unique_company_families": unique_families,
            "underfilled_floors": underfilled,
            "era_band_count": len(self.policy.era_bands),
            "derives_era_bands": self.policy.derives_era_bands,
            "date_selection": list(self.policy.date_selection),
            "date_selection_text": self.policy.date_selection_text,
            "form_era_allocation": {
                "budget": allocation.get("budget", 0),
                "cap_rejected_candidates": allocation.get("cap_rejected_candidates", 0),
                "final_target_min": allocation.get("final_target_min", 0),
                "final_target_max": allocation.get("final_target_max", 0),
                "unallocated": allocation.get("unallocated", 0),
                "cell_count": len(allocation_cells),
                "underfilled_cells": sum(
                    1 for cell in allocation_cells if cell["shortfall"] > 0
                ),
                "cells": allocation_cells,
            },
        }


__all__ = [
    "CLASSIFICATION_DIMENSIONS",
    "DEFAULT_RESERVE_MAX_PAGES",
    "DeficitSelector",
    "SelectionResult",
    "classification_signature",
]
