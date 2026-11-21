from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.engine.company_family.cohort import (
    FamilyIndexNotFoundError,
    execute_delta_roster,
    sample_cohort,
)


def _dataset(path: Path, rows: list[tuple[int, str, str]]) -> Path:
    table = pa.table(
        {
            "ordinal": [row[0] for row in rows],
            "cik_padded": [row[1] for row in rows],
            "name": [row[2] for row in rows],
        }
    )
    pq.write_table(table, path)
    return path


def test_delta_anti_join_uses_base_cik_and_resets_ordinals(tmp_path: Path) -> None:
    requested = _dataset(
        tmp_path / "requested.parquet",
        [(10, "0000000001", "One"), (20, "0000000002", "Two")],
    )
    base = tmp_path / "base.parquet"
    pq.write_table(pa.table({"cik": ["0000000001"]}), base)
    output = tmp_path / "delta.parquet"

    assert execute_delta_roster(requested, base, output) == 1
    assert pq.read_table(output).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000002", "name": "Two"}
    ]
    assert pq.read_metadata(base).num_rows == 1


def test_modulo_sampling_is_deterministic(tmp_path: Path) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [(index, f"{index + 1:010d}", chr(65 + index)) for index in range(4)],
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    assert sample_cohort(source, first, rate_percent=50) == sample_cohort(
        source, second, rate_percent=50
    )
    assert pq.read_table(first).to_pylist() == pq.read_table(second).to_pylist()


def test_family_sampling_prefers_operating_rows_and_fails_closed(
    tmp_path: Path,
) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [(index, f"{index + 1:010d}", chr(65 + index)) for index in range(4)],
    )
    family = tmp_path / "family.parquet"
    pq.write_table(
        pa.table(
            {
                "cik": ["0000000001", "0000000002", "0000000003"],
                "company_family": ["shared", "shared", "solo"],
                "family_kind": ["spv", "entity", "entity"],
            }
        ),
        family,
    )
    output = tmp_path / "family-sample.parquet"

    assert (
        sample_cohort(
            source,
            output,
            group_by_family=True,
            family_index_dataset=family,
            rate_percent=100,
        )
        == 3
    )
    members = pq.read_table(output).column("cik_padded").to_pylist()
    assert "0000000002" in members
    assert "0000000001" not in members
    with pytest.raises(FamilyIndexNotFoundError):
        sample_cohort(source, tmp_path / "missing.parquet", group_by_family=True)


def test_random_sample_limit_is_seeded(tmp_path: Path) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [(index, f"{index + 1:010d}", chr(65 + index)) for index in range(4)],
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    sample_cohort(source, first, method="random", sample_limit=2, seed=7)
    sample_cohort(source, second, method="random", sample_limit=2, seed=7)

    assert pq.read_table(first).to_pylist() == pq.read_table(second).to_pylist()
    assert pq.read_metadata(first).num_rows == 2
