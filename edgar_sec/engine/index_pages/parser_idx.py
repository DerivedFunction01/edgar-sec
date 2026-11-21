"""Pure streaming transformation: SEC full/daily index ``.idx`` payloads to rows.

One row model covers every flavour; the pipe flavours (master, xbrl) and the
fixed-width flavours (company, form, crawler) differ only in row layout.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from edgar_sec.domain.sec_urls import normalize_accession
from edgar_sec.foundation.text.dates import parse_date

__all__ = [
    "PARSER_FINGERPRINT",
    "IndexRow",
    "MalformedIndexRow",
    "iter_index_rows",
    "parse_index_bytes",
]

PARSER_FINGERPRINT = "index-idx-v1"

PIPE_FLAVOURS = frozenset({"master", "xbrl"})
FIXED_FLAVOURS = frozenset({"company", "form", "crawler"})
INDEX_FLAVOURS = PIPE_FLAVOURS | FIXED_FLAVOURS

_NAME_WIDTH = 62
_SEPARATOR_MIN = 40
_TAIL_RE = re.compile(r"(?:^|\s)(\d{1,10})\s+(\S+)\s+(\S+)\s*$")


@dataclass(frozen=True, slots=True)
class IndexRow:
    """One index row: the filing the index proves exists, as served."""

    cik: int
    company_name: str
    form_type: str
    date_filed: date
    filename: str

    @property
    def cik_padded(self) -> str:
        """The CIK zero-padded to ten digits."""
        return str(self.cik).zfill(10)

    @property
    def accession(self) -> str | None:
        """The unhyphenated accession named by the row's filename, if any."""
        base = self.filename.rstrip("/").rsplit("/", 1)[-1]
        for suffix in ("-index.htm", "-index.html", ".txt"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return normalize_accession(base)


@dataclass(frozen=True, slots=True)
class MalformedIndexRow:
    """A data line that could not be read as a row, kept as an outcome."""

    line_number: int
    raw: str
    reason: str


IndexOutcome = IndexRow | MalformedIndexRow


def parse_index_bytes(payload: bytes, flavour: str) -> Iterator[IndexOutcome]:
    """Stream outcomes from one index payload, line by line.

    The payload is never loaded as a document: lines are pulled from a
    byte stream and each yields at most one outcome.
    """
    return iter_index_rows(io.BytesIO(payload), flavour)


def iter_index_rows(
    lines: Iterable[bytes | str], flavour: str
) -> Iterator[IndexOutcome]:
    """Yield one outcome per data line after the dashed separator line."""
    if flavour not in INDEX_FLAVOURS:
        raise ValueError(f"unknown index flavour: {flavour!r}")
    in_data = False
    for line_number, raw_line in enumerate(lines, start=1):
        line = _decode_line(raw_line).rstrip("\r\n")
        if not in_data:
            stripped = line.strip()
            if len(stripped) >= _SEPARATOR_MIN and set(stripped) == {"-"}:
                in_data = True
            continue
        if not line.strip():
            continue
        if flavour in PIPE_FLAVOURS:
            yield _parse_pipe_row(line, line_number)
        else:
            yield _parse_fixed_row(line, line_number, flavour)


def _decode_line(raw_line: bytes | str) -> str:
    if isinstance(raw_line, str):
        return raw_line
    try:
        return raw_line.decode("utf-8")
    except UnicodeDecodeError:
        return raw_line.decode("latin-1")


def _parse_date(text: str) -> date | None:
    parsed = parse_date(text)
    if parsed is None or parsed.source != text:
        return None
    parts = parsed.components
    try:
        return date(parts.year, parts.month, parts.day)
    except ValueError:
        return None


def _parse_pipe_row(line: str, line_number: int) -> IndexOutcome:
    fields = [field.strip() for field in line.split("|")]
    if len(fields) != 5:
        return MalformedIndexRow(
            line_number, line, f"expected 5 pipe fields, got {len(fields)}"
        )
    cik_text, name, form, date_text, filename = fields
    if not cik_text.isdigit():
        return MalformedIndexRow(line_number, line, "CIK is not numeric")
    filed = _parse_date(date_text)
    if filed is None:
        return MalformedIndexRow(line_number, line, f"bad date filed: {date_text!r}")
    if not name or not form or not filename:
        return MalformedIndexRow(line_number, line, "empty name, form, or filename")
    return IndexRow(int(cik_text), name, form, filed, filename)


def _parse_fixed_row(line: str, line_number: int, flavour: str) -> IndexOutcome:
    match = _TAIL_RE.search(line)
    if match is None:
        return MalformedIndexRow(line_number, line, "no CIK/date/filename tail")
    head = line[: match.start(1)]
    if len(head) <= _NAME_WIDTH:
        return MalformedIndexRow(line_number, line, "head shorter than the name field")
    if flavour == "form":
        form, name = head[:-_NAME_WIDTH].strip(), head[-_NAME_WIDTH:].strip()
    else:
        name, form = head[:_NAME_WIDTH].strip(), head[_NAME_WIDTH:].strip()
    filed = _parse_date(match.group(2))
    if filed is None:
        return MalformedIndexRow(
            line_number, line, f"bad date filed: {match.group(2)!r}"
        )
    if not name or not form:
        return MalformedIndexRow(line_number, line, "empty name or form")
    return IndexRow(int(match.group(1)), name, form, filed, match.group(3))
