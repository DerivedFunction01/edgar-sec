"""Tests for seed_xbrl CLI tool."""

from pathlib import Path

from edgar_sec.engine.xbrl.storage import read_linkbase_parquet
from edgar_sec.tools.seed_xbrl import main
from tests.support import fixture_path


def test_seed_xbrl_cli_with_fixtures(tmp_path: Path) -> None:
    """Verify CLI execution using local fixture inputs."""
    out_parquet = tmp_path / "linkbases.parquet"
    fix_html = fixture_path("xbrl/msft_index_page.html")
    cohort_json = fixture_path("xbrl/seed_cohort.json")
    ret = main(
        [
            "--output",
            str(out_parquet),
            "--cohort-file",
            str(cohort_json),
            "--use-fixtures",
            "--fixture-html",
            str(fix_html),
            "--limit",
            "2",
        ]
    )
    assert ret == 0
    assert out_parquet.exists()
    table = read_linkbase_parquet(out_parquet)
    assert table.num_rows > 0
