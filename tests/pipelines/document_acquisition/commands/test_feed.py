"""The feed ingest command callable and its CLI wiring."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands.feed import cmd_feed_ingest
from edgar_sec.pipelines.document_acquisition.options import feed_ingest_options
from tests.pipelines.document_acquisition.test_feed_ingest import _fake_http


def test_cmd_feed_ingest_reports_outcome(tmp_path: Path, capsys) -> None:
    options = feed_ingest_options(
        start=date(2024, 3, 31),
        end=date(2024, 4, 1),
        artifacts_root=tmp_path,
        json_output=True,
    )
    http = _fake_http()
    assert cmd_feed_ingest(options, http_client=http) == 0  # type: ignore[arg-type]
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "feed ingest"
    assert payload["status"] == "ok"
    assert payload["units_fetched"] == 2
    assert payload["new_rows"] == 2
    assert payload["published"] is True


def test_cli_parses_feed_ingest_into_typed_options() -> None:
    args = cli.build_parser().parse_args(
        [
            "feed",
            "ingest",
            "--start",
            "2024-03-31",
            "--end",
            "2024-04-01",
            "--json",
        ]
    )
    assert args.command == "feed"
    assert args.feed_command == "ingest"
    assert callable(args.func)
