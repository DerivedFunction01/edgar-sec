"""Index (.idx) parsers: every fixture parses row-for-row against ground truth."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from edgar_sec.engine.index_pages.parser_idx import (
    IndexRow,
    MalformedIndexRow,
    iter_index_rows,
    parse_index_bytes,
)
from tests.support import fixture_path

FIXTURE_DIR = fixture_path("index_pages")
GROUND_TRUTH = json.loads((FIXTURE_DIR / "ground_truth.json").read_text("utf-8"))


def _canon(row: IndexRow) -> str:
    return (
        f"{row.cik}|{row.company_name}|{row.form_type}"
        f"|{row.date_filed.isoformat()}|{row.filename}"
    )


def _parse(name: str, flavour: str) -> tuple[list[IndexRow], list[MalformedIndexRow]]:
    payload = (FIXTURE_DIR / name).read_bytes()
    rows: list[IndexRow] = []
    malformed: list[MalformedIndexRow] = []
    for outcome in parse_index_bytes(payload, flavour):
        if isinstance(outcome, IndexRow):
            rows.append(outcome)
        else:
            malformed.append(outcome)
    return rows, malformed


@pytest.mark.parametrize("name", sorted(GROUND_TRUTH))
def test_fixture_matches_ground_truth(name: str) -> None:
    truth = GROUND_TRUTH[name]
    rows, malformed = _parse(name, truth["flavour"])
    assert len(rows) == truth["rows"]
    assert len(malformed) == truth["malformed"]
    digest = hashlib.sha256("\n".join(_canon(row) for row in rows).encode())
    assert digest.hexdigest() == truth["sha256"]
    if rows:
        assert _canon(rows[0]).split("|") == [str(v) for v in truth["first"]]
        assert _canon(rows[-1]).split("|") == [str(v) for v in truth["last"]]


def _normalized(row: IndexRow) -> tuple[str, str, str, str]:
    filename = row.filename
    if filename.startswith("http"):
        filename = filename.split("/Archives/", 1)[1]
        filename = filename.removesuffix("-index.htm") + ".txt"
    return (row.cik_padded, row.form_type, row.date_filed.isoformat(), filename)


def test_the_four_daily_flavours_agree_row_for_row() -> None:
    """One day's flavours are four orderings of the same filing set."""
    from collections import Counter

    parsed = {
        flavour: Counter(
            _normalized(row)
            for row in _parse(f"daily-{flavour}.20150102.idx", flavour)[0]
        )
        for flavour in ("master", "company", "form", "crawler")
    }
    assert parsed["master"] == parsed["company"] == parsed["form"] == parsed["crawler"]
    assert (
        sum(parsed["master"].values())
        == GROUND_TRUTH["daily-master.20150102.idx"]["rows"]
    )


def test_malformed_rows_degrade_with_good_rows_intact() -> None:
    rows, malformed = _parse("malformed-master.idx", "master")
    assert len(rows) == 5
    assert len(malformed) == 5
    assert all(item.reason for item in malformed)
    truth = GROUND_TRUTH["malformed-master.idx"]
    assert _canon(rows[0]).split("|") == [str(v) for v in truth["first"]]
    rows_fw, malformed_fw = _parse("malformed-company.idx", "company")
    assert len(rows_fw) == 5
    assert len(malformed_fw) == 3


def test_streaming_over_a_line_iterator() -> None:
    lines: Iterator[bytes] = (
        line
        for line in (FIXTURE_DIR / "daily-master.20150102.idx")
        .read_bytes()
        .splitlines(keepends=True)
    )
    outcomes = list(iter_index_rows(lines, "master"))
    assert len(outcomes) == GROUND_TRUTH["daily-master.20150102.idx"]["rows"]
    first = outcomes[0]
    assert isinstance(first, IndexRow)
    assert first.accession == "000119312515000678"
    assert first.cik_padded == "0001000209"


def test_unknown_flavour_is_refused() -> None:
    with pytest.raises(ValueError):
        list(iter_index_rows([], "nope"))


def test_fixture_dir_is_the_committed_capture() -> None:
    assert isinstance(FIXTURE_DIR, Path)
    assert (FIXTURE_DIR / "daily-master.20150102.idx").is_file()
