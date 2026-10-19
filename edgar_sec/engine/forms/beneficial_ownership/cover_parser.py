"""Sequential text-based parsing of Schedule 13D/13G reporting person matrices."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    CoverItemEvidence,
    EvidenceState,
    ReportingPersonCover,
)
from edgar_sec.engine.forms.common.statutory import HEADER_LEAK_RE
from edgar_sec.foundation.regex.builder import build_alternation

_POWER_TERMS = build_alternation(
    [
        "NUMBER OF",
        "SHARES",
        "BENEFICIALLY",
        "OWNED",
        "OWNED BY",
        "BY",
        "EACH",
        "REPORTING",
        "PERSON",
        "PERSON WITH",
        "WITH",
    ],
    auto_escape=True,
)
_RE_POWER_WORDS = re.compile(rf"(?i)\b(?:{_POWER_TERMS})\b")
_RE_TABLE_NOISE = re.compile(r"(?i)</?TABLE>|[_=\-‐‑‒–—]{2,}")
_RE_NARRATIVE_TAIL = re.compile(r"(?i)\bITEM\s+\d+[A-Z]?\s*[.:]\s|\bSIGNATURES?\b")
_RE_PERSON_WITH_NOISE = re.compile(r"(?i)\bPERSON\s*[:|]\s*WITH\b")
_RE_ROW_NUMBER_PREFIX = re.compile(r"^\s*(\d{1,2})\s+")
_RE_POWER_LEADING_WITH = re.compile(r"(?i)^\s*WITH\b")
_RE_POWER_TRAILING_WITH = re.compile(r"(?i)\bWITH\s*[:|]?\s*$")
_CHECKED_MARK_ALT = build_alternation(
    (r"\[\s*[X✓]\s*\]", "☒", "✓", r"(?<!\w)X(?!\w)"), compact=False
)
_UNCHECKED_MARK_ALT = build_alternation((r"\[\s*\]", "☐"), compact=False)
_RE_CHECKED_MARK = re.compile(_CHECKED_MARK_ALT, re.IGNORECASE)
_RE_UNCHECKED_MARK = re.compile(_UNCHECKED_MARK_ALT)

_RE_NAME = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?1\)?\s*[.:]?\s*)?(?:NAMES?\s+OF\s+REPORTING\s+PERSONS?|NAME\s+OF\s+REPORTING\s+PERSON)"
)
_RE_GROUP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?2\)?\s*[.:]?\s*)?(?:CHECK\s+(?:THE\s+)?APPROPRIATE\s+BOX\s+IF\s+A\s+MEMBER\s+OF\s+A\s+GROUP)"
)
_RE_SEC_USE = re.compile(r"(?i)(?:^|[\s\n])(?:\(?3\)?\s*[.:]?\s*)?(?:SEC\s+USE\s+ONLY)")
_RE_FUNDS = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?4\)?\s*[.:]?\s*)?(?:SOURCE\s+OF\s+FUNDS)"
)
_RE_LEGAL = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?5\)?\s*[.:]?\s*)?(?:CHECK\s+(?:BOX\s+)?IF\s+DISCLOSURE\s+OF\s+LEGAL\s+PROCEEDINGS)"
)
_RE_CITIZENSHIP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:CITIZENSHIP\s+OR\s+PLACE\s+OF\s+ORGANIZATION)"
)
_RE_SOLE_VOTE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SOLE\s+VOTING(?P<embedded_voting>\s+\d+)?(?:\s+BENEFICIALLY\s+OWNED)?\s+POWER)"
)
_RE_SHARED_VOTE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SHARED(?P<embedded_shared>\s+\d+)?\s+VOTING(?P<embedded_voting>\s+\d+)?\s+POWER)"
)
_RE_SOLE_DISP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SOLE(?P<embedded_sole>\s+\d+)?\s+DISPOSITIVE(?P<embedded_dispositive>\s+\d+)?\s+POWER)"
)
_RE_SHARED_DISP = re.compile(
    r"(?i)(?:^|[\s\n])(?:[:|]\s*)?(?:\(?\d+\)?\s*[.:]?\s*)?(?:SHARED(?P<embedded_shared>\s+\d+)?\s+DISPOSITIVE(?P<embedded_dispositive>\s+\d+)?\s+POWER)"
)
_RE_AGGREGATE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED)"
)
_RE_EXCLUDES = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:CHECK\s+(?:BOX\s+)?IF\s+(?:THE\s+)?AGGREGATE\s+AMOUNT\s+(?:IN\s+ROW\s+\(?\d+\)?|IN\s+ROW\s+\d+)?\s*EXCLUDES)"
)
_RE_PERCENT = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:PERCENT\s+OF\s+CLASS)"
)
_RE_TYPE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:TYPE\s+OF\s+REPORTING\s+PERSON)"
)

_SLOT_DEFS_13D: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("reportingPersonName", 1, _RE_NAME),
    ("memberOfGroup", 2, _RE_GROUP),
    ("secUseOnly", 3, _RE_SEC_USE),
    ("fundType", 4, _RE_FUNDS),
    ("legalProceedings", 5, _RE_LEGAL),
    ("citizenshipOrOrganization", 6, _RE_CITIZENSHIP),
    ("soleVotingPower", 7, _RE_SOLE_VOTE),
    ("sharedVotingPower", 8, _RE_SHARED_VOTE),
    ("soleDispositivePower", 9, _RE_SOLE_DISP),
    ("sharedDispositivePower", 10, _RE_SHARED_DISP),
    ("aggregateAmountOwned", 11, _RE_AGGREGATE),
    ("isAggregateExcludeShares", 12, _RE_EXCLUDES),
    ("percentOfClass", 13, _RE_PERCENT),
    ("typeOfReportingPerson", 14, _RE_TYPE),
)

_SLOT_DEFS_13G: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("reportingPersonName", 1, _RE_NAME),
    ("memberOfGroup", 2, _RE_GROUP),
    ("secUseOnly", 3, _RE_SEC_USE),
    ("citizenshipOrOrganization", 4, _RE_CITIZENSHIP),
    ("soleVotingPower", 5, _RE_SOLE_VOTE),
    ("sharedVotingPower", 6, _RE_SHARED_VOTE),
    ("soleDispositivePower", 7, _RE_SOLE_DISP),
    ("sharedDispositivePower", 8, _RE_SHARED_DISP),
    ("aggregateAmountOwned", 9, _RE_AGGREGATE),
    ("isAggregateExcludeShares", 10, _RE_EXCLUDES),
    ("percentOfClass", 11, _RE_PERCENT),
    ("typeOfReportingPerson", 12, _RE_TYPE),
)

_RE_PERSON_SPLIT = re.compile(
    r"(?im)^\s*1\b\s*[.:]?\s*(?:NAMES?\s+OF\s+REPORTING\s+PERSONS?|NAME\s+OF\s+REPORTING\s+PERSON)"
)
_RE_LABEL_LEGAL = re.compile(
    r"(?i)^(?:\s*PURSUANT\s+TO\s+ITEMS?\s*2\(d\)\s*OR\s*2\(e\)|IS\s+REQUIRED\s+PURSUANT\s+TO\s+ITEMS?\s*2\(d\)\s*OR\s*2\(e\))"
)
_AGGREGATE_PREFIX_ALT = build_alternation(
    ("BY EACH REPORTING PERSON", "BY EACH PERSON"),
    auto_escape=True,
    compact=True,
)
_RE_LABEL_AGGREGATE = re.compile(rf"(?i)^\s*(?:{_AGGREGATE_PREFIX_ALT})")
_RE_LABEL_EXCLUDES = re.compile(
    r"(?i)^\s*CERTAIN\s+SHARES(?:\s*\(SEE\s+INSTRUCTIONS\))?"
)
_RE_LABEL_PERCENT = re.compile(
    r"(?i)^\s*REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s+\(?\d+\)?"
)
_RE_LABEL_INSTRUCTIONS = re.compile(r"(?i)^\s*[*†‡]?\s*\(?\s*SEE\s+INSTRUCTIONS\s*\)?")
_RE_INSTRUCTION_TRAILER = re.compile(r"(?i)^\s*[*†‡]?\s*\(?SEE\s+INSTRUCTIONS\b.*$")
_RE_IRS_ID = re.compile(
    r"(?i)^\s*(?:S\.S\.\s+OR\s+)?I\.R\.S\.\s+IDENTIFICATION\s+NOS?\.?\s+OF\s+ABOVE\s+PERSONS?\s*(?:\(ENTITIES\s+ONLY\))?\s*"
)
_RE_PERSON_ID_TRAILER = re.compile(r"(?i)\s+(?:I\.\s*D\.|ID)\s+NO\.?\s*:?\s*[\d-]+\s*$")
_RE_TYPE_CODES_WITH_REST = re.compile(
    r"(?i)^\s*((?:[A-Z]{2}(?:\s*,\s*|\s+))*[A-Z]{2})(?:\s+(.*))?$"
)
_RE_NUMBER_OF = re.compile(r"(?i)\bNUMBER\s+OF\b.*")
_CITIZENSHIP_TAIL_ALT = build_alternation(
    (
        "SHARES",
        "VOTING POWER",
        "DISPOSITIVE POWER",
        "BENEFICIALLY OWNED",
        "OWNED BY",
        "REPORTING PERSON",
        "PERSON WITH",
    ),
    auto_escape=True,
    compact=True,
)
_RE_CITIZENSHIP_TAIL = re.compile(rf"(?i)\b(?:{_CITIZENSHIP_TAIL_ALT})\b.*$")


def parse_reporting_person_matrix(
    person_text: str,
    family: str = "13D",
    *,
    base_offset: int = 0,
) -> ReportingPersonCover:
    """Parses statutory disclosure slots for a single reporting person."""
    slot_defs = _SLOT_DEFS_13G if family == "13G" else _SLOT_DEFS_13D
    slot_spans: list[tuple[str, int, int, int, re.Pattern[str], tuple[str, ...]]] = []
    cur_pos = 0
    for tag, slot_num, pat in slot_defs:
        match = pat.search(person_text[cur_pos:])
        if match:
            actual_start = cur_pos + match.start()
            actual_end = cur_pos + match.end()
            embedded = tuple(
                value.strip()
                for value in match.groupdict().values()
                if value and value.strip()
            )
            slot_spans.append((tag, slot_num, actual_start, actual_end, pat, embedded))
            cur_pos = actual_end

    items: list[CoverItemEvidence] = []
    comment: str | None = None
    for idx, (tag, num, s_start, s_end, pat, embedded) in enumerate(slot_spans):
        val_end = (
            slot_spans[idx + 1][2] if idx + 1 < len(slot_spans) else len(person_text)
        )
        repeated_label = pat.search(person_text, s_end, val_end)
        if repeated_label is not None:
            val_end = repeated_label.start()
        val = person_text[s_end:val_end]
        val = _RE_TABLE_NOISE.sub(" ", val)
        narrative_start = _RE_NARRATIVE_TAIL.search(val)
        if narrative_start is not None:
            val = val[: narrative_start.start()]
        header_leak = HEADER_LEAK_RE.search(val)
        if header_leak is not None:
            val = val[: header_leak.start()]
        val = val.lstrip(" \t\r\n:.-|")
        if embedded:
            val = " ".join((*embedded, val))

        if tag in {"fundType", "typeOfReportingPerson"}:
            val = val.lstrip(" *†‡")
        row_number = _RE_ROW_NUMBER_PREFIX.match(val)
        if row_number and int(row_number.group(1)) == num:
            val = val[row_number.end() :]

        if tag == "legalProceedings":
            val = _RE_LABEL_LEGAL.sub("", val.strip())
        elif tag == "aggregateAmountOwned":
            val = _RE_LABEL_AGGREGATE.sub("", val.strip())
        elif tag == "isAggregateExcludeShares":
            val = _RE_LABEL_EXCLUDES.sub("", val.strip())
        elif tag == "percentOfClass":
            val = _RE_LABEL_PERCENT.sub("", val.strip())
        elif tag == "typeOfReportingPerson":
            val = _RE_LABEL_INSTRUCTIONS.sub("", val.strip())

        val = val.lstrip(" \t\r\n:.-|")
        if tag == "memberOfGroup":
            val = _RE_CHECKED_MARK.sub("[X]", val)
            val = _RE_UNCHECKED_MARK.sub("[ ]", val)
        if tag in (
            "soleVotingPower",
            "sharedVotingPower",
            "soleDispositivePower",
            "sharedDispositivePower",
        ):
            val = _RE_POWER_LEADING_WITH.sub("", val)
            val = _RE_PERSON_WITH_NOISE.sub(" ", val)
            val = _RE_POWER_WORDS.sub(" ", val)
            val = _RE_POWER_TRAILING_WITH.sub(" ", val)
            val = val.replace(":", " ").replace("|", " ")
            val = val.strip(" \t\r\n:.-|")
        elif tag == "citizenshipOrOrganization":
            val = _RE_NUMBER_OF.sub("", val)
            val = _RE_CITIZENSHIP_TAIL.sub(" ", val)
        elif tag == "reportingPersonName":
            val = _RE_IRS_ID.sub("", val)
            val = _RE_PERSON_ID_TRAILER.sub("", val)

        val = " ".join(val.split()).strip()
        if tag != "reportingPersonName":
            row_parts = val.split(maxsplit=1)
            if len(row_parts) == 2 and row_parts[0] == str(num):
                val = row_parts[1]

        if tag in ("legalProceedings", "isAggregateExcludeShares"):
            if _RE_CHECKED_MARK.search(val):
                state = EvidenceState.CHECKED
                c_val: str | None = "[X]"
            elif _RE_UNCHECKED_MARK.search(val):
                state = EvidenceState.UNCHECKED
                c_val = "[ ]"
            else:
                state = EvidenceState.BLANK
                c_val = None
        else:
            state = EvidenceState.VALUE if val else EvidenceState.BLANK
            c_val = val or None

        if tag == "typeOfReportingPerson" and c_val:
            type_match = _RE_TYPE_CODES_WITH_REST.fullmatch(c_val)
            if type_match:
                c_val = type_match.group(1).strip()
                rem = (type_match.group(2) or "").strip()
                instruction = rem.lstrip("_- *†‡")
                if _RE_INSTRUCTION_TRAILER.match(instruction):
                    rem = ""
                else:
                    rem = rem.lstrip("_- ")
                narrative_start = _RE_NARRATIVE_TAIL.search(rem)
                if narrative_start is not None:
                    rem = rem[: narrative_start.start()].strip()
                if rem:
                    comment = rem

        items.append(
            CoverItemEvidence(
                number=num,
                tag=tag,
                source_text=person_text[s_start:val_end],
                value=c_val,
                state=state,
                start_offset=base_offset + s_start,
                end_offset=base_offset + val_end,
            )
        )
    return ReportingPersonCover(
        items=tuple(items),
        source_text=person_text,
        comment_content=comment,
    )


def extract_reporting_person_covers(
    cover_text: str,
    family: str = "13D",
    *,
    base_offset: int = 0,
) -> tuple[ReportingPersonCover, ...]:
    """Extracts all reporting person disclosure matrices from the cover slice."""
    splits = list(_RE_PERSON_SPLIT.finditer(cover_text))
    if not splits:
        return ()

    people: list[ReportingPersonCover] = []
    for idx, match in enumerate(splits):
        start = match.start()
        end = splits[idx + 1].start() if idx + 1 < len(splits) else len(cover_text)
        people.append(
            parse_reporting_person_matrix(
                cover_text[start:end], family, base_offset=base_offset + start
            )
        )
    return tuple(people)


__all__ = [
    "extract_reporting_person_covers",
    "parse_reporting_person_matrix",
]
