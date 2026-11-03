"""Form 12b-25 review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import (
    COMMISSION_FILE_TOKEN_RE,
    parse_cusip,
)
from edgar_sec.engine.forms.common.signatures.blocks import (
    extract_anchored_signature,
)
from edgar_sec.engine.forms.cover.registrant import (
    next_content_line,
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence

_SUBJECT_KEYS = {
    "subject_10k": "10-K",
    "subject_20f": "20-F",
    "subject_11k": "11-K",
    "subject_10q": "10-Q",
    "subject_10d": "10-D",
    "subject_ncen": "N-CEN",
    "subject_ncsr": "N-CSR",
}
_TRANSITION_KEYS = (
    "transition_10k",
    "transition_20f",
    "transition_11k",
    "transition_10q",
)
_PART2_KEYS = ("part2_a", "part2_b", "part2_c")

_FILE_NUMBER_RE = re.compile(
    r"(?:sec|commission) file (?:number|no\.?)[:\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(
    r"(?:sec|commission) file (?:number|no\.?)", re.IGNORECASE
)
_CUSIP_LABEL_RE = re.compile(r"cusip (?:number|no\.?)", re.IGNORECASE)
_MARKUP_ONLY_RE = re.compile(r"<[^>]+>")
_NAME_CAPTION_RE = re.compile(r"full name of registrant", re.IGNORECASE)
_CONTACT_LABEL_RE = re.compile(r"name and telephone number of person", re.IGNORECASE)
_PHONE_RE = re.compile(r"\(?([0-9]{3})\)?[\s.\-]+([0-9]{3})[\s.\-]+([0-9]{4})")
_Q2_ANCHOR_RE = re.compile(r"have all other periodic reports", re.IGNORECASE)
_Q3_ANCHOR_RE = re.compile(r"anticipated that any significant change", re.IGNORECASE)
_ANSWER_TOKEN_RE = re.compile(r"\[x\]|\[ \]|\(x\)|\(\)|\byes\b|\bno\b", re.IGNORECASE)
_NARRATIVE_INSTRUCTION = "state below in reasonable detail"
_SIGNATURE_ANCHOR = "has caused this notification"
_MIN_NARRATIVE_WORDS = 10


def _scan_value_tokens(lines: list[str], index: int, count: int = 3) -> list[str]:
    tokens: list[str] = []
    cursor = index
    for _ in range(count):
        following = next_content_line(lines, cursor)
        if following is None:
            break
        cursor, text = following
        tokens.extend(token.strip(",;") for token in text.split())
    return tokens


def _extract_file_number(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:40]):
        match = _FILE_NUMBER_RE.search(line)
        if match is not None:
            return match.group(1)
        if _FILE_CAPTION_RE.search(line):
            for token in _scan_value_tokens(lines, index):
                if COMMISSION_FILE_TOKEN_RE.fullmatch(token):
                    return token
    return None


def _extract_cusip(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:40]):
        match = _CUSIP_LABEL_RE.search(line)
        if match is None:
            continue
        tokens = [token.strip(",;") for token in line[match.end() :].split()]
        tokens.extend(_scan_value_tokens(lines, index))
        for token in tokens:
            cusip = parse_cusip(token)
            if cusip is not None:
                return cusip
    return None


def _extract_registrant_name(lines: list[str], start: int, end: int) -> str | None:
    for index in range(start, end):
        match = _NAME_CAPTION_RE.search(lines[index])
        if match is None:
            continue
        remainder = lines[index][match.end() :].strip(" \t:")
        if len(remainder) >= 3:
            name = parse_registrant_identity(remainder).name
            if name is not None:
                return name
        cursor = index
        for _ in range(3):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            name = parse_registrant_identity(text).name
            if name is not None:
                return name
    for index in range(start, end):
        stripped = lines[index].strip()
        if stripped and "part i" not in stripped.lower():
            return parse_registrant_identity(stripped).name
    return None


def _part1_fallback_start(lines: list[str]) -> int | None:
    names = {" ".join(name.lower().split()) for name in FORM_12B25_ITEMS[0].names}
    for index, line in enumerate(lines):
        normalized = " ".join(line.strip().lower().split())
        if normalized in names or any(
            normalized.startswith(f"{name} ") for name in names
        ):
            return index
    return None


def _part_span(
    sections: dict[str, tuple[int, int | None]], part: str, total: int
) -> tuple[int, int]:
    if part not in sections:
        return 0, 0
    start, end = sections[part]
    return min(start, total), total if end is None else min(end + 1, total)


def _answer_tokens(line: str) -> list[tuple[str, str, int, int]]:
    tokens: list[tuple[str, str, int, int]] = []
    for match in _ANSWER_TOKEN_RE.finditer(line):
        text = match.group(0).lower()
        if text in ("[x]", "(x)"):
            kind = "filled"
        elif text in ("[ ]", "()"):
            kind = "empty"
        else:
            kind = "word"
        tokens.append((kind, text, match.start(), match.end()))
    return tokens


def _resolve_answer(
    block_lines: list[str],
) -> tuple[str | None, str | None, tuple[str, str] | None]:
    """Resolve a block's marked answer, its layout convention, or its ambiguity."""
    for line_index, line in enumerate(block_lines):
        tokens = _answer_tokens(line)
        filled_at = next(
            (i for i, token in enumerate(tokens) if token[0] == "filled"), None
        )
        if filled_at is None:
            continue
        filled = tokens[filled_at]
        lo = filled_at
        while lo > 0 and not line[tokens[lo - 1][3] : tokens[lo][2]].strip():
            lo -= 1
        hi = filled_at
        while (
            hi + 1 < len(tokens) and not line[tokens[hi][3] : tokens[hi + 1][2]].strip()
        ):
            hi += 1
        cluster = tokens[lo : hi + 1]
        before = [
            token[1]
            for token in cluster
            if token[0] == "word" and token[3] <= filled[2]
        ]
        after = [
            token[1]
            for token in cluster
            if token[0] == "word" and token[2] >= filled[3]
        ]
        mark_count = sum(1 for token in cluster if token[0] != "word")
        if cluster[0][0] != "word":
            if after:
                return after[0], "mark_first", None
            if line_index + 1 < len(block_lines):
                following = _answer_tokens(block_lines[line_index + 1])
                if following and following[0][0] == "word":
                    return following[0][1], "mark_first", None
        elif mark_count >= 2:
            if before:
                return before[-1], "word_first", None
        elif before and after:
            return None, None, (before[-1], after[0])
        elif before:
            return before[-1], "word_first", None
        elif line_index > 0:
            prior = _answer_tokens(block_lines[line_index - 1])
            if prior and prior[-1][0] == "word":
                return prior[-1][1], "word_first", None
    return None, None, None


def _extract_part4(part_lines: list[str]) -> dict[str, Any]:
    contact_name: str | None = None
    for index, line in enumerate(part_lines):
        if _CONTACT_LABEL_RE.search(line):
            cursor = index
            for _ in range(4):
                following = next_content_line(part_lines, cursor)
                if following is None:
                    break
                cursor, candidate = following
                if _MARKUP_ONLY_RE.fullmatch(candidate):
                    continue
                if "(name)" in candidate.lower():
                    continue
                phone_match = _PHONE_RE.search(candidate)
                if phone_match is not None:
                    candidate = candidate[: phone_match.start()].strip(" \t,-")
                    if not candidate:
                        continue
                contact_name = candidate
                break
            break
    phone_match = _PHONE_RE.search("\n".join(part_lines))
    phone = (
        f"{phone_match.group(1)}-{phone_match.group(2)}-{phone_match.group(3)}"
        if phone_match is not None
        else None
    )
    q2_start = next(
        (i for i, line in enumerate(part_lines) if _Q2_ANCHOR_RE.search(line)),
        None,
    )
    q3_start = next(
        (i for i, line in enumerate(part_lines) if _Q3_ANCHOR_RE.search(line)),
        None,
    )
    q2 = (None, None, None)
    if q2_start is not None:
        stop = q3_start if q3_start is not None else len(part_lines)
        q2 = _resolve_answer(part_lines[q2_start:stop])
    q3 = (None, None, None)
    if q3_start is not None:
        q3 = _resolve_answer(part_lines[q3_start:])
    convention = q2[1] or q3[1] or "word_first"

    def settle(resolved: tuple[str | None, str | None, tuple[str, str] | None]):
        answer, _, fallback = resolved
        if answer is not None:
            return answer
        if fallback is not None:
            return fallback[1] if convention == "mark_first" else fallback[0]
        return None

    q2_answer = settle(q2)
    q3_answer = settle(q3)
    return {
        "contact_name": contact_name,
        "contact_phone": phone,
        "q2_answer": q2_answer,
        "q3_answer": q3_answer,
    }


def analyze_form_12b25_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Form 12b-25 review case producing Part I–IV diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "12B-25")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="12B-25")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()

    sequence = detect_section_sequence(
        text, family="12B-25", taxonomy_items=FORM_12B25_ITEMS
    )
    spans = {
        section.item_identifier.removeprefix("ITEM "): (
            section.start_line,
            section.end_line,
        )
        for section in sequence.sections
    }
    if "PART I" not in spans:
        fallback_start = _part1_fallback_start(lines)
        if fallback_start is not None:
            spans["PART I"] = (
                fallback_start,
                spans.get("PART II", (len(lines), None))[0],
            )
    part1_start, part1_end = _part_span(spans, "PART I", len(lines))
    part3_start, part3_end = _part_span(spans, "PART III", len(lines))
    part3_text = "\n".join(lines[part3_start:part3_end])
    narrative_words = sum(
        len(line.split())
        for line in part3_text.splitlines()
        if _NARRATIVE_INSTRUCTION not in line.lower()
    )
    part4 = lines[slice(*_part_span(spans, "PART IV", len(lines)))]

    states = rep["checkmarks"].get("candidate_states", {})
    for key in (*_SUBJECT_KEYS, *_TRANSITION_KEYS, *_PART2_KEYS):
        rep["checkmarks"][key] = states.get(key) == "checked"
    subject_form = next(
        (form for key, form in _SUBJECT_KEYS.items() if rep["checkmarks"][key]),
        None,
    )
    transition_form = next(
        (
            _SUBJECT_KEYS[f"subject_{key.removeprefix('transition_')}"]
            for key in _TRANSITION_KEYS
            if rep["checkmarks"][key]
        ),
        None,
    )

    signature = extract_anchored_signature(text, (_SIGNATURE_ANCHOR,))

    fields = {
        "sec_file_number": _extract_file_number(lines),
        "cusip": _extract_cusip(lines),
        "subject_form": subject_form,
        "transition_form": transition_form,
        "part1_registrant_name": _extract_registrant_name(
            lines, part1_start, part1_end
        ),
        "part3_narrative_words": narrative_words,
        "part4": _extract_part4(part4),
        "signature": signature,
    }
    rep["form_12b25"] = fields

    if not fields["sec_file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_sec_file_number", "no SEC file number matched in the head"
            )
        )
    if subject_form is None and transition_form is None:
        rep["anomalies"].append(
            anomaly_record(
                "no_subject_report_checked",
                "no subject-report or transition checkbox resolved as checked",
            )
        )
    if not fields["part1_registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_part1_registrant",
                "no registrant name resolved from the Part I caption",
            )
        )
    if narrative_words < _MIN_NARRATIVE_WORDS:
        rep["anomalies"].append(
            anomaly_record(
                "missing_part3_narrative",
                f"Part III narrative holds {narrative_words} words",
            )
        )
    if not fields["part4"]["contact_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_part4_contact",
                "no contact name resolved after the Part IV (1) caption",
            )
        )
    if fields["part4"]["q2_answer"] is None:
        rep["anomalies"].append(
            anomaly_record(
                "missing_part4_q2_answer",
                "no marked Yes/No answer resolved for Part IV (2)",
            )
        )
    if fields["part4"]["q3_answer"] is None:
        rep["anomalies"].append(
            anomaly_record(
                "missing_part4_q3_answer",
                "no marked Yes/No answer resolved for Part IV (3)",
            )
        )
    if not signature["present"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_signature", "no signatory resolved from the signature block"
            )
        )
    return rep


def summarize_form_12b25_cases(
    case_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate individual Form 12b-25 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="12B-25")
    if not summary.get("case_count", 0):
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_12b25", {})

    summary["form_12b25_scorecard"] = {
        "sec_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("sec_file_number")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
        "subject_form_counts": {
            form: sum(
                1 for r in case_reports if fields_of(r).get("subject_form") == form
            )
            for form in _SUBJECT_KEYS.values()
        },
        "transition_count": sum(
            1 for r in case_reports if fields_of(r).get("transition_form")
        ),
        "part2_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _PART2_KEYS
        },
        "part1_registrant_count": sum(
            1 for r in case_reports if fields_of(r).get("part1_registrant_name")
        ),
        "part3_narrative_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("part3_narrative_words", 0) >= _MIN_NARRATIVE_WORDS
        ),
        "part4_contact_count": sum(
            1 for r in case_reports if fields_of(r).get("part4", {}).get("contact_name")
        ),
        "part4_phone_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("part4", {}).get("contact_phone")
        ),
        "part4_q2_answer_counts": {
            answer: sum(
                1
                for r in case_reports
                if fields_of(r).get("part4", {}).get("q2_answer") == answer
            )
            for answer in ("yes", "no")
        },
        "part4_q3_answer_counts": {
            answer: sum(
                1
                for r in case_reports
                if fields_of(r).get("part4", {}).get("q3_answer") == answer
            )
            for answer in ("yes", "no")
        },
        "signature_present_count": sum(
            1 for r in case_reports if fields_of(r).get("signature", {}).get("present")
        ),
        "signature_conformed_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("signature", {}).get("conformed")
        ),
    }
    return summary


analyze_case = analyze_form_12b25_review_case
summarize_cases = summarize_form_12b25_cases

__all__ = [
    "analyze_case",
    "analyze_form_12b25_review_case",
    "summarize_cases",
    "summarize_form_12b25_cases",
]
