"""Text-era parser for SEC Form N-PX filings.

Covers the two attested pre-XML layouts: SGML table issuer blocks in
plain-text submissions and the columnar HTML vote table.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re

from edgar_sec.domain.forms.families.form_npx.models import (
    FormNPxDocument,
    ProxyVoteRow,
)
from edgar_sec.engine.forms.common.entities import is_valid_cusip
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import parse_date

_FILE_NUMBER_RE = re.compile(
    r"Investment Company Act file (?:number|no\.)\s*:?\s*([0-9][0-9-]*)",
    re.IGNORECASE,
)
_FILE_NUMBER_FALLBACK_RE = re.compile(
    r"file (?:number|no\.)\s*:?\s*(811-[0-9-]+)", re.IGNORECASE
)
_PERIOD_RE = re.compile(r"Date of reporting period:\s*(.+)", re.IGNORECASE)
_PERIOD_LABEL_RE = re.compile(r"reporting period:\s*(.*)", re.IGNORECASE)
_MEETING_DATE_RE = re.compile(r"Meeting Date:?\s*(\S+)")
_CUSIP_LABEL_RE = re.compile(r"CUSIP/CINS:\s*(\S+)")
_SECURITY_TOKEN_RE = re.compile(r"Security\s+(\S+)")
_DASH_LINE_RE = re.compile(r"^[-—\s]+$")
_VOTE_CAST_ALT = build_alternation(
    ("For", "Against", "Withhold", "Withheld", "Abstain", "None")
)
_MGMT_POSITION_ALT = build_alternation(("For", "Against", "None"))
_VOTE_LINE_RE = re.compile(
    r"^\s*\d+\s{2,}(.+?)\s{2,}"
    f"({_VOTE_CAST_ALT})"
    r"\s+"
    f"({_MGMT_POSITION_ALT})"
    r"\s*$",
    re.IGNORECASE,
)
_PROPOSAL_NO_RE = re.compile(r"^\d+\.\d+$")
_TICKER_CELL_RE = re.compile(r"[A-Z.]{1,5}")
_VOTE_TOKENS = frozenset({"FOR", "AGAINST", "WITHHOLD", "ABSTAIN", "NONE"})
_LABEL_LINES = frozenset(
    {
        "ISSUER NAME",
        "TICKER",
        "CUSIP",
        "MTG DATE",
        "PROPOSAL",
        "TYPE",
        "MTG TYPE",
        "VOTED?",
        "VOTE",
        "FOR/AGNST MGMT",
    }
)


def _canonical_date(value: str | None) -> str | None:
    """Normalize a filed date string to the MM/DD/YYYY schema shape."""
    if not value:
        return None
    parsed = parse_date(value.strip())
    if parsed is None:
        return value.strip()
    components = parsed.components
    return f"{components.month:02d}/{components.day:02d}/{components.year:04d}"


class _CellLineExtractor(HTMLParser):
    """Collect text lines with table cell boundaries as line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("td", "th", "tr", "table", "p", "br"):
            self.lines.append("")

    def handle_data(self, data: str) -> None:
        for piece in data.split("\n"):
            piece = piece.strip()
            if piece:
                self.lines.append(piece)


def _text_lines(raw_bytes: bytes) -> list[str]:
    text = raw_bytes.decode("utf-8", errors="replace")
    if "<" in text:
        extractor = _CellLineExtractor()
        extractor.feed(text)
        return [line for line in extractor.lines if line]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _period_end(lines: list[str], text: str) -> str | None:
    match = _PERIOD_RE.search(text)
    if match:
        return _canonical_date(match.group(1).split("-")[-1])
    for idx, line in enumerate(lines):
        label = _PERIOD_LABEL_RE.search(line)
        if label is None:
            continue
        value = label.group(1).strip()
        if not value and idx + 1 < len(lines):
            value = lines[idx + 1].strip()
        if value:
            return _canonical_date(value.split("-")[-1])
    return None


def _cover_fields(lines: list[str]) -> dict[str, str | None]:
    text = "\n".join(lines)
    collapsed = " ".join(text.split())
    file_number = None
    match = _FILE_NUMBER_RE.search(collapsed) or _FILE_NUMBER_FALLBACK_RE.search(
        collapsed
    )
    if match:
        file_number = match.group(1)
    period_end = _period_end(lines, text)
    name = None
    for idx, line in enumerate(lines):
        lowered = line.lower()
        if ("file number" in lowered or "file no." in lowered) and idx + 1 < len(lines):
            parts = []
            for following in lines[idx + 1 : idx + 3]:
                if "Exact name of registrant" in following:
                    break
                if any(char in following for char in '<>"'):
                    continue
                if _DASH_LINE_RE.match(following):
                    continue
                parts.append(following)
            if parts:
                name = " ".join(parts)
            break
    return {
        "file_number": file_number,
        "period_of_report": period_end,
        "reporting_person_name": name,
    }


def _issuer_before(lines: list[str], idx: int) -> str:
    for back in range(idx - 1, max(idx - 4, -1), -1):
        candidate = lines[back]
        if candidate and ":" not in candidate and "<" not in candidate:
            return candidate
    return ""


def _sgml_block_rows(lines: list[str]) -> list[ProxyVoteRow]:
    """Parse issuer blocks anchored on Meeting Date lines (text layout)."""
    rows: list[ProxyVoteRow] = []
    issuer = ""
    cusip = None
    meeting_date = ""
    for idx, line in enumerate(lines):
        cusip_match = _CUSIP_LABEL_RE.search(line)
        if cusip_match is None:
            token = _SECURITY_TOKEN_RE.search(line)
            if token is not None and is_valid_cusip(token.group(1)):
                cusip_match = token
        if cusip_match:
            cusip = cusip_match.group(1)
            issuer = _issuer_before(lines, idx) or issuer
        date_match = _MEETING_DATE_RE.search(line)
        if date_match:
            meeting_date = _canonical_date(date_match.group(1)) or ""
            continue
        vote_match = _VOTE_LINE_RE.match(line)
        if vote_match and issuer:
            rows.append(
                ProxyVoteRow(
                    issuer_name=issuer,
                    meeting_date=meeting_date,
                    vote_description=vote_match.group(1).strip(),
                    cusip=cusip,
                    how_voted=(vote_match.group(2),),
                )
            )
    return rows


def _columnar_rows(lines: list[str]) -> list[ProxyVoteRow]:
    """Parse the columnar HTML vote table layout from its cell stream."""
    rows: list[ProxyVoteRow] = []
    idx = 0
    issuer_parts: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        if len(line) == 9 and is_valid_cusip(line) and idx + 2 < len(lines):
            date = _canonical_date(lines[idx + 1])
            if date and parse_date(lines[idx + 1]) is not None:
                name_parts = [
                    p
                    for p in issuer_parts
                    if p.upper().replace("\xa0", " ") not in _LABEL_LINES
                ]
                if len(name_parts) >= 2 and _TICKER_CELL_RE.fullmatch(name_parts[-1]):
                    name_parts = name_parts[:-1]
                issuer = " ".join(name_parts)
                cusip = line
                cursor = idx + 3
                while cursor < len(lines):
                    if len(lines[cursor]) == 9 and is_valid_cusip(lines[cursor]):
                        break
                    if _PROPOSAL_NO_RE.match(lines[cursor]) is None:
                        break
                    if cursor + 4 >= len(lines):
                        break
                    vote = lines[cursor + 4]
                    if vote.upper() not in _VOTE_TOKENS:
                        break
                    rows.append(
                        ProxyVoteRow(
                            issuer_name=issuer,
                            meeting_date=date,
                            vote_description=lines[cursor + 1],
                            cusip=cusip,
                            how_voted=(vote,),
                        )
                    )
                    cursor += 6
                idx = cursor
                issuer_parts = []
                continue
        if line.upper().replace("\xa0", " ") in _LABEL_LINES:
            issuer_parts = []
        else:
            issuer_parts.append(line)
        idx += 1
    return rows


def parse_npx_text(raw_bytes: bytes) -> FormNPxDocument:
    """Parse a text-era Form N-PX filing into the typed domain model."""
    lines = _text_lines(raw_bytes)
    cover = _cover_fields(lines)
    rows = _sgml_block_rows(lines)
    if not rows:
        rows = _columnar_rows(lines)
    return FormNPxDocument(
        submission_type="N-PX",
        vote_rows=tuple(rows),
        period_of_report=cover["period_of_report"],
        reporting_person_name=cover["reporting_person_name"],
        file_number=cover["file_number"],
    )


__all__ = ["parse_npx_text"]
