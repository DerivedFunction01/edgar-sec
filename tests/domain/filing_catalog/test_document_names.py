from __future__ import annotations

import pytest

from edgar_sec.domain.filing_catalog.document_names import (
    is_primary_exhibit_filename,
)


@pytest.mark.parametrize(
    "filename",
    [
        "ex-10.1.htm",
        "ex21.txt",
        "exhibit99.htm",
        "dex101.htm",
        "ex-3_1.txt",
        "EX-105.HTML",
    ],
)
def test_statutory_exhibit_filenames_match(filename: str) -> None:
    assert is_primary_exhibit_filename(filename)


@pytest.mark.parametrize(
    "filename",
    [
        "exxon.htm",
        "exp.txt",
        "exas.htm",
        "ex-106.htm",
        "form10k.htm",
        "ex21.pdf",
        None,
        "",
    ],
)
def test_non_exhibit_or_missing_filenames_do_not_match(filename: str | None) -> None:
    assert not is_primary_exhibit_filename(filename)
