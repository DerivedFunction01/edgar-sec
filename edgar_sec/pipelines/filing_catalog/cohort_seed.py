from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.selection.policy import SeedFiler
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.duckdb import connect


def cohort_seed_filers(record: CohortRecord, dataset: Path) -> dict[str, SeedFiler]:
    try:
        with connect() as con:
            rows = con.execute(
                "SELECT cik_padded FROM read_parquet(?) ORDER BY ordinal",
                [str(dataset)],
            ).fetchall()
    except Exception as error:
        raise ValueError(
            f"unable to read cohort seeds {record.cohort_id!r}: {error}"
        ) from error

    seed_map: dict[str, SeedFiler] = {}
    for (cik_value,) in rows:
        if (
            not isinstance(cik_value, str)
            or len(cik_value) != 10
            or not cik_value.isdigit()
        ):
            raise ValueError(f"cohort contains invalid seed CIK: {cik_value!r}")
        if cik_value in seed_map:
            raise ValueError(f"cohort contains duplicate seed CIK: {cik_value}")
        seed_map[cik_value] = SeedFiler(
            cik=cik_value,
            seed_group="cohort",
            coverage_tags=record.name or record.cohort_id,
            notes=f"From cohort {record.cohort_id}",
        )
    return seed_map
