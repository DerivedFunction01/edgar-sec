"""Sequential text-based parsing of Schedule 13D/13G reporting person matrices."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    CoverItemEvidence,
    EvidenceState,
    ReportingPersonCover,
)
from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
)
from edgar_sec.engine.forms.common.marks import (
    canonicalize_mark_tokens,
    mark_state_in,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number
from edgar_sec.engine.forms.common.statutory import HEADER_LEAK_RE
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    REPORTING_PERSON_SLOT_NUMBERS_13D,
    REPORTING_PERSON_SLOT_NUMBERS_13G,
)

_SLOT_NUMS_13D = dict(REPORTING_PERSON_SLOT_NUMBERS_13D)
_SLOT_NUMS_13G = dict(REPORTING_PERSON_SLOT_NUMBERS_13G)

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
_RE_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_NARRATIVE_TAIL_ALT = build_alternation(
    (
        r"ITEM\s+\d+(?:\([A-Z0-9]+\))?\s*[.:]?\s",
        r"SIGNATURES?\b",
        r"THIS\s+(?:AMENDMENT|SCHEDULE)\b",
    ),
    auto_escape=False,
    compact=True,
)
_RE_NARRATIVE_TAIL = re.compile(rf"(?i)\b(?:{_NARRATIVE_TAIL_ALT})")
_RE_HEADER_OR_PAGE = re.compile(r"(?i)\bSCHEDULE\s+13[DG]\b|\bCUSIP\b")
_RE_GROUP_OPTION = re.compile(r"(?i)(?:\(\s*([ab])\s*\)|(?<!\w)([ab])[.)])")
_RE_PERSON_WITH_NOISE = re.compile(r"(?i)\bPERSON\s*[:|]\s*WITH\b")
_RE_ROW_NUMBER_PREFIX = re.compile(r"^\s*(\d{1,2})\s+")
_RE_POWER_LEADING_WITH = re.compile(r"(?i)^\s*WITH\b")
_RE_POWER_TRAILING_WITH = re.compile(r"(?i)\bWITH\s*[:|]?\s*$")
_RE_SEE_ROW = re.compile(r"(?i)\bsee\s+(?:item|row)\s+(\d+)")


def _checked_group_option(value: str | None) -> str | None:
    if not value:
        return None
    options = list(_RE_GROUP_OPTION.finditer(value))
    for index, option in enumerate(options):
        end = options[index + 1].start() if index + 1 < len(options) else len(value)
        segment = value[option.end() : end]
        if CANONICAL_CHECKED in segment or "[x]" in segment.lower():
            return (option.group(1) or option.group(2)).lower()
    return None


_ENTITIES_ALT = build_alternation(("&#9;", "&nbsp;", "&#160;"), auto_escape=True)
_WS = rf"(?:[\s]|{_ENTITIES_ALT})"
_SP = rf"(?:[\s\n>]|{_ENTITIES_ALT})"
_RE_HTML_ENTITIES = re.compile(_ENTITIES_ALT)

_TAX_ID_ALT = build_alternation(
    ("I.?R.?S.?", "IRS", "SSN", "TAX"),
    auto_escape=False,
    compact=True,
)
_ID_WORD_ALT = build_alternation(
    ("IDENTIFICATION", "IDENTITY", "ID"),
    auto_escape=True,
    compact=True,
)
_NAME_OF_REPORTING_PERSON_ALT = rf"NAMES?(?:\([A-Z0-9]+\))?(?:{_WS}*(?:AND|&){_WS}*(?:{_TAX_ID_ALT})?{_WS}*(?:{_ID_WORD_ALT})?{_WS}*(?:NUMBER|NOS?\.?)?(?:{_WS}*\(ENTITIES\s+ONLY\))?)?{_WS}+OF{_WS}+REPORTING{_WS}+PERSONS?(?:\([A-Z0-9]+\))?"
_BOX1_WITH_NUMBER_ALT = build_alternation(
    (
        _NAME_OF_REPORTING_PERSON_ALT,
        rf"REPORTING{_WS}+PERSONS?(?:\([A-Z0-9]+\))?",
        rf"I\.?R\.?S\.?{_WS}+IDENTIFICATION{_WS}+(?:NOS?|NUMBER)\.?{_WS}+OF{_WS}+(?:ABOVE|SUCH){_WS}+PERSONS?(?:{_WS}*\(ENTITIES\s+ONLY\))?",
    ),
    auto_escape=False,
    compact=False,
)
_RE_REPORTING_PERSON_CORE = rf"(?:(?:\(?{_WS}*(?:ITEM{_WS}+[1lI]\b|[1lI]\b){_WS}*[\).:]?{_WS}*[:.]?{_WS}*(?:\([a-z0-9]+\){_WS}*)?){_WS}*(?:{_BOX1_WITH_NUMBER_ALT})|(?:(?<=[\n\r])|^{_WS}*){_WS}*(?:{_NAME_OF_REPORTING_PERSON_ALT}))"
_CITIZENSHIP_ALT = build_alternation(
    (
        "CITIZENSHIP OR PLACE OF ORGANIZATION",
        "PLACE OF ORGANIZATION",
        "CITIZENSHIP",
    ),
    auto_escape=True,
    compact=True,
)

_TYPE_PERSON_PHRASE_ALT = build_alternation(
    ("REPORTING PERSON", "PERSON REPORTING", "REPORT PERSON"),
    auto_escape=True,
    compact=True,
)

_SLOT_LABEL_PATTERNS: dict[str, str] = {
    "reportingPersonName": _RE_REPORTING_PERSON_CORE,
    "memberOfGroup": r"(?:\(?\b(?:ITEM\s+2|2)\)?\s*[.:]?\s*)?(?:(?:CHECK\s+)?(?:(?:THE\s+)?APPROPRIATE\s+)?(?:BOX|\[?LINE\]?)\s+IF\s+(?:(?:A|THE)\s+)?(?:MEMBER\s+OF\s+(?:A\s+)?)?(?:GROUP|ROW))",
    "secUseOnly": r"(?:\(?\b(?:ITEM\s+3|3)\)?\s*[.:]?\s*)?(?:SEC\s+USE(?:\s+ONLY)?)",
    "fundType": r"(?:\(?\b(?:ITEM\s+4|4)\)?\s*[.:]?\s*)?(?:SOURCE\s+OF\s+FUNDS)",
    "legalProceedings": r"(?:\(?\b(?:ITEM\s+5|5)\)?\s*[.:]?\s*)?(?:CHECK\s+(?:BOX\s+)?IF\s+DISCLOSURE\s+OF\s+LEGAL\s+PROCEEDINGS)",
    "citizenshipOrOrganization": rf"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:{_CITIZENSHIP_ALT})",
    "soleVotingPower": r"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:SOLE\s+VOTING(?P<embedded_voting>\s+\d+)?(?:\s+BENEFICIALLY\s+OWNED)?\s+POWER)",
    "sharedVotingPower": r"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:SHARED(?P<embedded_shared>\s+\d+)?\s+VOTING(?P<embedded_voting>\s+\d+)?\s+POWER)",
    "soleDispositivePower": r"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:SOLE(?P<embedded_sole>\s+\d+)?\s+DISPOSITIVE(?P<embedded_dispositive>\s+\d+)?\s+POWER)",
    "sharedDispositivePower": r"(?:[:|]\s*)?(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:SHARED(?P<embedded_shared>\s+\d+)?\s+DISPOSITIVE(?P<embedded_dispositive>\s+\d+)?\s+POWER)",
    "aggregateAmountOwned": (
        rf"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?{_WS}*[.:]?{_WS}*(?:AGGREGATE[D]?(?:{_WS}+AMOUNT{_WS}+(?:BENEFICIALLY{_WS}+)?OWNED|:|\b)|AMOUNT{_WS}+(?:BENEFICIALLY{_WS}+)?OWNED)|(?:AGGREGATE[D]?{_WS}+AMOUNT{_WS}+(?:BENEFICIALLY{_WS}+)?OWNED|AMOUNT{_WS}+(?:BENEFICIALLY{_WS}+)?OWNED))"
    ),
    "isAggregateExcludeShares": r"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:CHECK\s+(?:BOX\s+)?IF\s+(?:THE\s+)?AGGREGATE\s+AMOUNT\s+(?:IN\s+(?:ROW|LINE)\s+(?:\[\s*[X✓]?\s*\]\s*)?\(?\d+\)?\s*(?:\[\s*[X✓]?\s*\]\s*)?)?EXCLUDES)",
    "percentOfClass": r"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:PERCENT\s+OF\s+CLASS)",
    "typeOfReportingPerson": rf"(?:\(?\b(?:ITEM\s+\d+|\d+)\)?\s*[.:]?\s*)?(?:TYPE\s+(?:OF|OR)\s+(?:{_TYPE_PERSON_PHRASE_ALT}))",
}

_BARE_ITEM_ALLOWED = {
    "citizenshipOrOrganization",
    "soleVotingPower",
    "sharedVotingPower",
    "soleDispositivePower",
    "sharedDispositivePower",
    "aggregateAmountOwned",
    "percentOfClass",
    "typeOfReportingPerson",
}


def _compile_slot_pattern(field: str, num: int) -> re.Pattern[str]:
    label_pat = _SLOT_LABEL_PATTERNS[field]
    if field in _BARE_ITEM_ALLOWED:
        return re.compile(
            rf"(?i)(?:^|{_SP})(?:{label_pat}|ITEM{_SP}+{num}\b{_SP}*:{_SP}*)"
        )
    return re.compile(rf"(?i)(?:^|{_SP}){label_pat}")


_SLOT_PATTERNS_13G: dict[str, re.Pattern[str]] = {
    field: _compile_slot_pattern(field, num)
    for field, num in REPORTING_PERSON_SLOT_NUMBERS_13G
}

_SLOT_PATTERNS_13D: dict[str, re.Pattern[str]] = {
    field: _compile_slot_pattern(field, num)
    for field, num in REPORTING_PERSON_SLOT_NUMBERS_13D
}


_SLOT_DEFS_13G: tuple[tuple[str, int, re.Pattern[str]], ...] = tuple(
    (field, number, _SLOT_PATTERNS_13G[field])
    for field, number in REPORTING_PERSON_SLOT_NUMBERS_13G
)
_SLOT_DEFS_13D: tuple[tuple[str, int, re.Pattern[str]], ...] = tuple(
    (field, number, _SLOT_PATTERNS_13D[field])
    for field, number in REPORTING_PERSON_SLOT_NUMBERS_13D
)


def _slot_definitions(
    family: str,
) -> tuple[tuple[str, int, re.Pattern[str]], ...]:
    return _SLOT_DEFS_13G if family == "13G" else _SLOT_DEFS_13D


_RE_PERSON_SPLIT = re.compile(rf"(?im)(?:^\s*|\b){_RE_REPORTING_PERSON_CORE}")
_RE_LABEL_LEGAL = re.compile(
    r"(?i)^(?:\s*PURSUANT\s+TO\s+ITEMS?\s*2\(d\)\s*OR\s*2\(e\)|IS\s+REQUIRED\s+PURSUANT\s+TO\s+ITEMS?\s*2\(d\)\s*OR\s*2\(e\))"
)
_AGGREGATE_PREFIX_ALT = build_alternation(
    (
        r"BY\s+(?:EACH\s+)?(?:REPORTING\s+)?PERSON",
        r"PERSON",
    ),
    auto_escape=False,
    compact=True,
)
_RE_LABEL_AGGREGATE = re.compile(rf"(?i)^\s*(?:{_AGGREGATE_PREFIX_ALT})\s*[:.-]?")
_RE_LABEL_EXCLUDES = re.compile(
    r"(?i)^\s*CERTAIN\s+SHARES(?:\s*\(SEE\s+INSTRUCTIONS\))?\s*[:.-]?"
)
_PERCENT_LABEL_ALT = build_alternation(
    (
        r"REPRESENTED\s+BY\s+(?:AMOUNT\s+)?(?:IN\s+)?(?:ROW|LINE)\s*\(?\d+\)?",
        r"REPRESENTED\s+BY\s+AMOUNT",
        r"OWNED\b",
        r"APPROX(?:IMATELY|\.)?",
    ),
    auto_escape=False,
    compact=True,
)
_RE_LABEL_PERCENT = re.compile(rf"(?i)^\s*(?:{_PERCENT_LABEL_ALT})\s*[:.-]?")
_RE_LABEL_INSTRUCTIONS = re.compile(r"(?i)^\s*[*†‡]?\s*\(?\s*SEE\s+INSTRUCTIONS\s*\)?")
_RE_INSTRUCTION_TRAILER = re.compile(r"(?i)^\s*[*†‡]?\s*\(?SEE\s+INSTRUCTIONS\b.*$")
_IRS_LABEL_ALT = build_alternation(
    (
        r"(?:S\.?S\.?\s*(?:OR\s*)?)?I\.?R\.?S\.?\s+IDENTIFICATION\s+(?:NOS?|NUMBER)\.?\s+OF\s+(?:ABOVE|SUCH)\s+PERSONS?(?:\s*\(ENTITIES\s+ONLY\))?",
        r"(?:S\.?S\.?\s*(?:OR\s*)?)?I\.?R\.?S\.?\s+IDENTIFICATION\s+(?:NOS?|NUMBER)\.?(?:\s*\(ENTITIES\s+ONLY\))?",
        r"NOS?\.?\s+OF\s+(?:ABOVE|SUCH)\s+PERSONS?(?:\s*\(ENTITIES\s+ONLY\))?",
        r"I\.?R\.?S\.?\s+IDENTIFICATION\b(?:\s*\(ENTITIES\s+ONLY\))?",
    ),
    auto_escape=False,
    compact=False,
)
_RE_IRS_ID = re.compile(rf"(?i)\s*(?:[/|:,]|(?<!\w)-)*\s*(?:{_IRS_LABEL_ALT})[:\s]*")
_RE_PERSON_ID_TRAILER = re.compile(r"(?i)\s+(?:I\.\s*D\.|ID)\s+NO\.?\s*:?\s*[\d-]+\s*$")
_RE_ENTITIES_TRAILER = re.compile(
    r"(?is)\s*(?:(?:NO\.?\s+OF\s+ABOVE\s+PERSONS?|\(?ENTITIES\s+ONLY\)?)\s*)+$"
)
_RE_ENTITIES_PREFIX = re.compile(
    r"(?is)^\s*(?:(?:NO\.?\s+OF\s+ABOVE\s+PERSONS?|\(?ENTITIES\s+ONLY\)?)\s*)+"
)
_ID_ONLY_ALT = build_alternation(
    (r"\d[\d -]*", r"N/?A", r"NONE\.?"),
    auto_escape=False,
    compact=True,
)
_RE_ID_ONLY = re.compile(rf"(?i)^\s*(?:{_ID_ONLY_ALT})\s*$")
_CHECK_BOX_GROUP_ALT = build_alternation(
    (
        r"(?:\(?\b(?:ITEM\s+2|2)\)?\s*[.:)]*\s*)?CHECK\s+(?:(?:THE\s+)?APPROPRIATE\s+)?(?:BOX|\[?LINE\]?)",
        r"(?:\(?\b(?:ITEM\s+2|2)\)?\s*[.:)]+\s*)CHECK\b",
        r"(?:\(?\b(?:ITEM\s+2|2)\)?\s*[.:)]+\s*)MEMBER\s+OF\s+(?:A\s+)?GROUP\b",
    ),
    auto_escape=False,
    compact=False,
)
_RE_CHECK_BOX_GROUP_HEAD = re.compile(rf"(?i){_CHECK_BOX_GROUP_ALT}")
_RAW_CHECKBOX_RE = re.compile(r"\[\s*[xX ]\s*\]|\(\s*[a-zA-Z]\s*\)\s*\[")
_RE_HYPHEN_WORD_BREAK = re.compile(r"(\b[A-Za-z]+)-\s+([A-Za-z]+\b)")
_RE_TYPE_CODES_WITH_REST = re.compile(
    r"(?i)^\s*((?:[A-Z]{2}(?:\s*,\s*|\s+))*[A-Z]{2})(?:\s+(.*))?$"
)
_RE_NUMBER_OF = re.compile(r"(?i)\bNUMBER\s+OF\b.*")
_CITIZENSHIP_TAIL_ALT = build_alternation(
    (
        r"ITEMS?\s+\d+(?:[–-]\d+)?",
        "NUMBER OF SHARES",
        "SHARES",
        "VOTING POWER",
        "DISPOSITIVE POWER",
        "BENEFICIALLY OWNED",
        "OWNED BY",
        "REPORTING PERSON",
        "PERSON WITH",
    ),
    auto_escape=False,
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
    slot_defs = _slot_definitions(family)
    slot_spans: list[tuple[str, int, int, int, re.Pattern[str], tuple[str, ...]]] = []
    cur_pos = 0
    for tag, slot_num, pat in slot_defs:
        match = pat.search(person_text, cur_pos)
        if match:
            actual_start = match.start()
            actual_end = match.end()
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
        val = _RE_HTML_TAG.sub(" ", val)
        val = _RE_HTML_ENTITIES.sub(" ", val)
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
        if row_number:
            alt_dict = _SLOT_NUMS_13G if family == "13D" else _SLOT_NUMS_13D
            alt_num = alt_dict.get(tag)
            if int(row_number.group(1)) in (num, alt_num):
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
            val = canonicalize_mark_tokens(val)
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
            group_head = _RE_CHECK_BOX_GROUP_HEAD.search(val)
            if group_head is not None:
                group_tail_text = val[group_head.start() :]
                val = val[: group_head.start()]
                if not any(it.tag == "memberOfGroup" and it.value for it in items):
                    opt = _checked_group_option(group_tail_text)
                    if opt:
                        items.append(
                            CoverItemEvidence(
                                number=2,
                                source_text=group_tail_text[:100],
                                value=opt,
                                state=EvidenceState.VALUE,
                                tag="memberOfGroup",
                                start_offset=base_offset,
                                end_offset=base_offset,
                            )
                        )
            irs_label = _RE_IRS_ID.search(val)
            if irs_label is not None:
                before = val[: irs_label.start()].strip(" \t:|/,")
                after = val[irs_label.end() :].lstrip(" \t:.-|/")
                after = _RE_ENTITIES_PREFIX.sub("", after).strip()
                after = _RE_PERSON_ID_TRAILER.sub("", after).strip()
                after = _RE_ENTITIES_TRAILER.sub("", after).strip()
                if not before or before.casefold() in {"and", "or"}:
                    val = after
                elif before.rstrip().endswith("-"):
                    val = before.rstrip()[:-1] + after
                elif not after or _RE_ID_ONLY.fullmatch(after):
                    val = before
                else:
                    val = before
            val = _RE_HYPHEN_WORD_BREAK.sub(r"\1\2", val)
            raw_cb = _RAW_CHECKBOX_RE.search(val)
            if raw_cb is not None:
                val = val[: raw_cb.start()]
            val = val.lstrip(" \t:.-|")
            val = _RE_PERSON_ID_TRAILER.sub("", val)

        val = " ".join(val.split()).strip()
        if tag != "reportingPersonName":
            row_parts = val.split(maxsplit=1)
            if len(row_parts) == 2 and row_parts[0] == str(num):
                val = row_parts[1]

        if tag in ("legalProceedings", "isAggregateExcludeShares"):
            mark_state = mark_state_in(val)
            if mark_state == "checked":
                state = EvidenceState.CHECKED
                c_val: str | None = CANONICAL_CHECKED
            elif mark_state == "unchecked":
                state = EvidenceState.UNCHECKED
                c_val = CANONICAL_UNCHECKED
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
                    clean_rem = rem.strip("-_ \t\r\n")
                    if not _RE_NARRATIVE_TAIL.search(
                        clean_rem
                    ) and not _RE_HEADER_OR_PAGE.search(clean_rem):
                        comment = clean_rem

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
    resolved_items: list[CoverItemEvidence] = []
    by_num = {it.number: it for it in items}
    for it in items:
        if it.value:
            has_num = (
                normalize_schema_number(
                    it.value,
                    integer=True,
                    strip_units=True,
                    strip_footnotes=True,
                    extract_leading_number=True,
                )
                is not None
                or normalize_schema_number(
                    it.value,
                    integer=False,
                    strip_percent=True,
                    strip_footnotes=True,
                    extract_leading_number=True,
                )
                is not None
            )
            if not has_num and (m_see := _RE_SEE_ROW.search(it.value)):
                ref_num = int(m_see.group(1))
                ref_it = by_num.get(ref_num)
                if ref_it and ref_it.value and ref_it.value.strip():
                    it = CoverItemEvidence(
                        number=it.number,
                        tag=it.tag,
                        source_text=it.source_text,
                        value=ref_it.value,
                        state=EvidenceState.VALUE,
                        start_offset=it.start_offset,
                        end_offset=it.end_offset,
                    )
        resolved_items.append(it)
    agg_item = next(
        (it for it in resolved_items if it.tag == "aggregateAmountOwned"), None
    )
    agg_val = agg_item.value if agg_item else None
    if (
        not agg_val
        or normalize_schema_number(
            agg_val,
            integer=True,
            strip_units=True,
            strip_footnotes=True,
            extract_leading_number=True,
        )
        is None
    ):
        for p_tag in (
            "sharedVotingPower",
            "soleVotingPower",
            "sharedDispositivePower",
            "soleDispositivePower",
        ):
            p_it = next((it for it in resolved_items if it.tag == p_tag), None)
            if p_it and p_it.value:
                p_norm = normalize_schema_number(
                    p_it.value,
                    integer=True,
                    strip_units=True,
                    strip_footnotes=True,
                    extract_leading_number=True,
                )
                if p_norm and int(p_norm) > 0:
                    agg_num = 11 if family == "13D" else 9
                    new_agg = CoverItemEvidence(
                        number=agg_num,
                        tag="aggregateAmountOwned",
                        source_text=p_it.source_text,
                        value=p_norm,
                        state=EvidenceState.VALUE,
                        start_offset=p_it.start_offset,
                        end_offset=p_it.end_offset,
                    )
                    if agg_item:
                        resolved_items[resolved_items.index(agg_item)] = new_agg
                    else:
                        resolved_items.append(new_agg)
                    break
    return ReportingPersonCover(
        items=tuple(resolved_items),
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

    merged: list[ReportingPersonCover] = []
    for cov in people:
        prev_name = merged[-1].first_item("reportingPersonName") if merged else None
        cov_name = cov.first_item("reportingPersonName")
        if (
            merged
            and prev_name
            and prev_name.value
            and not any(
                it.tag != "reportingPersonName" and it.value for it in merged[-1].items
            )
            and (not cov_name or not cov_name.value)
            and any(it.tag != "reportingPersonName" and it.value for it in cov.items)
        ):
            prev = merged.pop()
            combined_items = [prev_name] + [
                it for it in cov.items if it.tag != "reportingPersonName"
            ]
            merged.append(
                ReportingPersonCover(
                    items=tuple(combined_items),
                    source_text=prev.source_text + "\n" + cov.source_text,
                    comment_content=cov.comment_content or prev.comment_content,
                )
            )
        else:
            merged.append(cov)
    return tuple(merged)


__all__ = [
    "extract_reporting_person_covers",
    "parse_reporting_person_matrix",
]
