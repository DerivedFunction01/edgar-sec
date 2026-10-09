import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.query import (
    find_across_cohorts,
    query_cohort_members,
)


def _register(paths: CohortPaths, catalog: CohortCatalog, name: str, rows):
    roster = hashlib.sha256(name.encode()).hexdigest()
    cohort_id = f"c-{roster[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "ordinal": [row[0] for row in rows],
                "cik_padded": [row[1] for row in rows],
                "name": [row[2] for row in rows],
            }
        ),
        dataset,
    )
    return catalog.register_cohort(
        cohort_id=cohort_id,
        name=name,
        origin_kind="file_import",
        roster_id=roster,
        row_count=len(rows),
        distinct_cik_count=len(rows),
        dataset_sha256=file_sha256(dataset),
        dataset_path=paths.relative_path(dataset),
    )


def test_member_pages_are_ordered_and_filterable(tmp_path: Path) -> None:
    dataset = tmp_path / "members.parquet"
    pq.write_table(
        pa.table(
            {
                "ordinal": [2, 0, 1],
                "cik_padded": ["0000000003", "0000000001", "0000000002"],
                "name": ["Acme", "Beta", "Acme Energy"],
            }
        ),
        dataset,
    )

    total, first = query_cohort_members(dataset, limit=2, offset=0)
    _, second = query_cohort_members(dataset, limit=2, offset=2)
    filtered, matches = query_cohort_members(dataset, name_substr="acme")

    assert total == 3
    assert [member.ordinal for member in first + second] == [0, 1, 2]
    assert filtered == 2
    assert [member.name for member in matches] == ["Acme Energy", "Acme"]


def test_global_find_uses_stable_cohort_then_ordinal_pages(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    first = _register(
        paths,
        catalog,
        "Alpha",
        [(1, "0000000002", "Match"), (0, "0000000001", "Match")],
    )
    second = _register(paths, catalog, "Beta", [(0, "0000000003", "Match")])

    count, page_one = find_across_cohorts(catalog, name_substr="match", limit=2)
    _, page_two = find_across_cohorts(catalog, name_substr="match", limit=2, offset=2)

    assert count == 3
    assert [(m.cohort_id, m.ordinal) for m in page_one + page_two] == [
        (record.cohort_id, ordinal)
        for record in sorted((first, second), key=lambda item: item.cohort_id)
        for ordinal in range(record.row_count)
    ]
