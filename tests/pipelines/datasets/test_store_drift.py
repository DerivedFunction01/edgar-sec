"""Store loads under schema drift: wider vintages widen, narrower NULL-fill."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from edgar_sec.pipelines.datasets.paths import resolve_datasets_paths
from edgar_sec.pipelines.datasets.specs import spec_for
from edgar_sec.pipelines.datasets.store import load_vintage, open_store


def _zip(path: Path, members: dict[str, str]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    path.write_bytes(buffer.getvalue())
    return path


def test_width_drift_across_vintages(tmp_path: Path) -> None:
    narrow = _zip(
        tmp_path / "narrow.zip",
        {"NMFP_SUBMISSION.tsv": "ACCESSION_NUMBER\tCIK\n0001\t111\n0002\t222\n"},
    )
    wide = _zip(
        tmp_path / "wide.zip",
        {"NMFP_SUBMISSION.tsv": ("ACCESSION_NUMBER\tCIK\tEXTRA\n0003\t333\tx\n")},
    )
    paths = resolve_datasets_paths(tmp_path)
    con = open_store(paths.store_file)
    try:
        for vintage, archive in (("2010q4", narrow), ("2026_09", wide)):
            load_vintage(
                con,
                spec_for("nmfp"),
                archive,
                vintage=vintage,
                archive_sha="b" * 64,
                source_url="https://www.sec.gov/example.zip",
                loaded_at="2026-11-08T00:00:00+00:00",
                work_dir=tmp_path / vintage,
            )
        rows = con.execute(
            "SELECT vintage, CIK, EXTRA FROM nmfp_submission ORDER BY vintage"
        ).fetchall()
    finally:
        con.close()
    assert rows == [
        ("2010q4", "111", None),
        ("2010q4", "222", None),
        ("2026_09", "333", "x"),
    ]
