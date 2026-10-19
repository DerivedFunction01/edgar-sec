"""Sequential text-based parsing of Schedule 13D/13G reporting person matrices."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    CoverItemEvidence,
    EvidenceState,
    ReportingPersonCover,
)
from edgar_sec.foundation.regex.builder import build_alternation

_POWER_TERMS = build_alternation(
    [
        "NUMBER OF",
        "SHARES",
        "BENEFICIALLY",
        "OWNED BY",
        "EACH",
        "REPORTING",
        "PERSON WITH",
    ],
    auto_escape=True,
)
_RE_POWER_WORDS = re.compile(rf"(?i)\b(?:{_POWER_TERMS})\b")
_RE_TABLE_NOISE = re.compile(r"(?i)</?TABLE>|[-=]{3,}")

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
    r"(?i)(?:^|[\s\n])(?:\(?5\)?\s*[.:]?\s*)?(?:CHECK\s+BOX\s+IF\s+DISCLOSURE\s+OF\s+LEGAL\s+PROCEEDINGS)"
)
_RE_CITIZENSHIP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:CITIZENSHIP\s+OR\s+PLACE\s+OF\s+ORGANIZATION)"
)
_RE_SOLE_VOTE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SOLE\s+VOTING\s+POWER)"
)
_RE_SHARED_VOTE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SHARED\s+VOTING\s+POWER)"
)
_RE_SOLE_DISP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SOLE\s+DISPOSITIVE\s+POWER)"
)
_RE_SHARED_DISP = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:SHARED\s+DISPOSITIVE\s+POWER)"
)
_RE_AGGREGATE = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED)"
)
_RE_EXCLUDES = re.compile(
    r"(?i)(?:^|[\s\n])(?:\(?\d+\)?\s*[.:]?\s*)?(?:CHECK\s+BOX\s+IF\s+(?:THE\s+)?AGGREGATE\s+AMOUNT\s+(?:IN\s+ROW\s+\(?\d+\)?|IN\s+ROW\s+\d+)?\s*EXCLUDES)"
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
_RE_LABEL_AGGREGATE = re.compile(r"(?i)^\s*BY\s+EACH\s+REPORTING\s+PERSON")
_RE_LABEL_EXCLUDES = re.compile(
    r"(?i)^\s*CERTAIN\s+SHARES(?:\s*\(SEE\s+INSTRUCTIONS\))?"
)
_RE_LABEL_PERCENT = re.compile(
    r"(?i)^\s*REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s+\(?\d+\)?"
)
_RE_LABEL_INSTRUCTIONS = re.compile(r"(?i)^\s*\(SEE\s+INSTRUCTIONS\)")
_RE_IRS_ID = re.compile(r"(?i)(?:S\.S\.\s+OR\s+)?I\.R\.S\.\s+IDENTIFICATION\s+NO\..*")
_RE_NUMBER_OF = re.compile(r"(?i)\bNUMBER\s+OF\b.*")


def parse_reporting_person_matrix(
    person_text: str,
    family: str = "13D",
) -> ReportingPersonCover:
    """Parses statutory disclosure slots for a single reporting person."""
    slot_defs = _SLOT_DEFS_13G if family == "13G" else _SLOT_DEFS_13D
    slot_spans: list[tuple[str, int, int, int]] = []
    cur_pos = 0
    for tag, slot_num, pat in slot_defs:
        match = pat.search(person_text[cur_pos:])
        if match:
            actual_start = cur_pos + match.start()
            actual_end = cur_pos + match.end()
            slot_spans.append((tag, slot_num, actual_start, actual_end))
            cur_pos = actual_end

    items: list[CoverItemEvidence] = []
    comment: str | None = None
    for idx, (tag, num, s_start, s_end) in enumerate(slot_spans):
        val_end = (
            slot_spans[idx + 1][2] if idx + 1 < len(slot_spans) else len(person_text)
        )
        val = person_text[s_end:val_end]
        val = _RE_TABLE_NOISE.sub(" ", val)

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

        if tag in (
            "soleVotingPower",
            "sharedVotingPower",
            "soleDispositivePower",
            "sharedDispositivePower",
        ):
            val = _RE_POWER_WORDS.sub(" ", val)
        elif tag == "citizenshipOrOrganization":
            val = _RE_NUMBER_OF.sub("", val)
        elif tag == "reportingPersonName":
            val = _RE_IRS_ID.sub("", val)

        val = " ".join(val.split()).strip()

        if tag in ("legalProceedings", "isAggregateExcludeShares"):
            if "[X]" in val:
                state = EvidenceState.CHECKED
                c_val: str | None = "[X]"
            elif "[ ]" in val:
                state = EvidenceState.UNCHECKED
                c_val = "[ ]"
            else:
                state = EvidenceState.BLANK
                c_val = None
        else:
            state = EvidenceState.VALUE if val else EvidenceState.BLANK
            c_val = val or None

        if tag == "typeOfReportingPerson" and c_val:
            parts = c_val.split(maxsplit=1)
            c_val = parts[0]
            if len(parts) > 1 and parts[1].strip():
                rem = parts[1].strip().lstrip("_- ")
                if rem and not rem.startswith("Item 1."):
                    comment = rem

        items.append(
            CoverItemEvidence(
                number=num,
                tag=tag,
                source_text=person_text[s_start:val_end],
                value=c_val,
                state=state,
                start_offset=s_start,
                end_offset=val_end,
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
) -> tuple[ReportingPersonCover, ...]:
    """Extracts all reporting person disclosure matrices from the cover slice."""
    splits = list(_RE_PERSON_SPLIT.finditer(cover_text))
    if not splits:
        return ()

    people: list[ReportingPersonCover] = []
    for idx, match in enumerate(splits):
        start = match.start()
        end = splits[idx + 1].start() if idx + 1 < len(splits) else len(cover_text)
        people.append(parse_reporting_person_matrix(cover_text[start:end], family))
    return tuple(people)


__all__ = [
    "extract_reporting_person_covers",
    "parse_reporting_person_matrix",
]
