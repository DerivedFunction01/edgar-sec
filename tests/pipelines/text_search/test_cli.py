"""Tests for the text_search CLI surface."""

from __future__ import annotations

from edgar_sec.pipelines.text_search.cli import main

from .support import make_cache_db


def test_cli_build_then_status(tmp_path, capsys) -> None:  # noqa: ANN001
    artifacts = tmp_path / "artifacts"
    cache_db = make_cache_db(
        artifacts / "cache" / "documents.sqlite",
        [("0000000001-26-000001", 1, "10-K", "a.txt", "Revenue and liquidity.\n")],
    )
    code = main(
        [
            "build",
            "--artifacts",
            str(artifacts),
            "--cache-db",
            str(cache_db),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "payloads=1" in out
    code = main(["status", "--artifacts", str(artifacts)])
    assert code == 0
    assert "payloads=1" in capsys.readouterr().out
