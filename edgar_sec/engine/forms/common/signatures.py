"""Reusable parsing utilities for conformed signature blocks and delegations."""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.domain.forms.common.signatures import (
    COMMON_SIGNATURE_LEXICAL_PACK,
    CORPORATE_OFFICER_TITLES,
    CORPORATE_SIGNATORY_ROLES,
    NOTARY_AND_JURAT_PHRASES,
    POA_AUTH_TERMS,
    DelegationKind,
    Signatory,
    SignatureBlock,
)
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_ALT,
    CONFORMED_SIGNATURE_RE,
    RE_CONFORMED_SIGNER_NAME,
    RE_SIGNATURE_HTML_TAG,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import Token, tokenize
from edgar_sec.foundation.text.dates import (
    ISO_DATE_RE,
    MONTH_NAME_RE,
    MONTH_PATTERN,
    MONTH_RE,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
)
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

CLEAN_LINE_RE = re.compile(r"[_=\-\*]{2,}")
WHITESPACE_RE = re.compile(r"\s+")
PREFIX_STRIP_TERMS = (
    r"by\s*:?",
    r"for\s*:?",
    r"signature\s*:?",
)
PREFIX_STRIP_ALT = build_alternation(PREFIX_STRIP_TERMS, auto_escape=False)
PREFIX_STRIP_RE = re.compile(rf"(?i)^(?:{PREFIX_STRIP_ALT})\s*")

NOTARY_JURAT_ALT = build_alternation(
    NOTARY_AND_JURAT_PHRASES, auto_escape=True, compact=True
)
NOTARY_JURAT_RE = re.compile(NOTARY_JURAT_ALT, re.IGNORECASE)

OFFICER_TITLE_ALT = build_alternation(
    CORPORATE_OFFICER_TITLES, auto_escape=True, compact=True
)
OFFICER_TITLE_RE = re.compile(OFFICER_TITLE_ALT, re.IGNORECASE)

SIGNATORY_ROLE_ALT = build_alternation(
    CORPORATE_SIGNATORY_ROLES, auto_escape=True, compact=True
)
SIGNATORY_ROLE_RE = re.compile(SIGNATORY_ROLE_ALT, re.IGNORECASE)

POA_AUTH_ALT = build_alternation(POA_AUTH_TERMS, auto_escape=True, compact=True)
POA_AUTH_RE = re.compile(POA_AUTH_ALT, re.IGNORECASE)

SIG_NAME_TERMINATOR_ALT = build_alternation(
    [r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"\n", r"$"],
    auto_escape=False,
)
SIG_NAME_RE = re.compile(
    rf"Signature of Reporting Person(?:\s+Date)?\s+([A-Za-z’‘'\.\- ]+?)(?:{SIG_NAME_TERMINATOR_ALT})",
    re.IGNORECASE,
)
SIG_BY_NAME_TITLE_ALT = build_alternation(
    (
        "accounting",
        "assistant",
        "attorney",
        "chief",
        "comp",
        "counsel",
        "dir",
        "director",
        "exec",
        "executive",
        "financial",
        "general counsel",
        "manager",
        "managing",
        "member",
        "officer",
        "partner",
        "pres",
        "president",
        "principal",
        "prog",
        "sec",
        "secretary",
        "treas",
        "treasurer",
        "trustee",
        "vice",
    ),
    auto_escape=True,
)
SIG_BY_NAME_TERMINATOR_ALT = build_alternation(
    [
        r"\n",
        r"Name\s*:",
        r"Title\s*:",
        r"For\s*:",
        r"Date\b",
        r"\(?\s*POA\b",
        r",?\s+attorney-in-fact\b",
        r"\s*-\s*attorney-in-fact\b",
        r",?\s+attorney\s+in\s+fact\b",
        r",?\s+power\s+of\s+attorney\b",
        r",?\s+authorized\s+signer\b",
        r",?\s+attorney\b",
        r",?\s+poa\b",
        r",?\s+esq\b",
        rf",?\s+(?:{SIG_BY_NAME_TITLE_ALT})\b\.?",
        r"$",
    ],
    auto_escape=False,
)
SIG_BY_NAME_RE = re.compile(
    rf"\bBy\s*:\s*(?:By\s+)?(?:{CONFORMED_SIGNATURE_ALT})?\s*"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){0,5}?)"
    rf"(?=\s*(?:{SIG_BY_NAME_TERMINATOR_ALT}))",
    re.IGNORECASE,
)
SIG_DELEGATED_NAME_SUFFIX_ALT = build_alternation(
    ("power of attorney", "attorney-in-fact", "attorney in fact"),
    auto_escape=True,
)
SIG_DELEGATED_SPLIT_RE = re.compile(rf"(?i)\b(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b")
SIG_BY_PREFIX_RE = re.compile(r"(?i)^(?:by\s*:?\s*)+")
SIG_TRAILING_PAREN_NUM_RE = re.compile(r"\s*\(\d+\)$")
SIG_CONFORMED_PREFIX_RE = re.compile(rf"(?i)^(?:{CONFORMED_SIGNATURE_ALT})\s*")
SIG_LEADING_RULE_RE = re.compile(r"^[\*_= \-\t_]+")
SIG_RULE_RUN_RE = re.compile(r"[_=]+")
_TRAILING_DATE_WORD_RE = re.compile(r"\s+date\s*$", flags=re.IGNORECASE)
_TRAILING_OFFICER_WORD_RE = re.compile(r"\s+officers?$", flags=re.IGNORECASE)
_TRAILING_MONTH_WORD_RE = re.compile(
    rf"\s+(?:{MONTH_PATTERN})\s*$", flags=re.IGNORECASE
)
REVERSED_CONFORMED_CELL_RE = re.compile(r"^\s*(?:\*\s*)?s/\s*[A-Za-z]")
SIG_DELEGATED_NAME_RE = re.compile(
    r"(?:^|\n)\s*([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    rf"\s*,?\s+(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b",
    re.IGNORECASE,
)
SIG_UNDERLINED_NAME_RE = re.compile(
    r"[_=-]{2,}\s*"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    r"\s*[_=-]{2,}",
    re.IGNORECASE,
)
SIG_PERSON_PREFIX_RE = re.compile(
    r"(?:^|\n)[^\S\r\n]*([A-Za-z’‘'\.\- ]{3,40}?)[^\S\r\n]*\n(?:\s*\d{2,4}\s*\n)?\s*\*{1,2}\s*Signature of Reporting Person",
    re.IGNORECASE,
)
SIG_BOILERPLATE_TERMS: tuple[str, ...] = (
    "criminal",
    "violation",
    "omb number",
    "omb approval",
    "federal",
    "intentional",
    "misstatement",
    "instruction",
    "valid omb",
    "respond",
    "warning",
    "pursuant",
    "reminder",
    "note:",
    "potential persons",
    "displays a currently",
    "18 u.s.c.",
    "15 u.s.c.",
    "sec 1474",
    "sec 2474",
    "table i",
    "table ii",
    "table 1",
    "table 2",
    "cusip",
    "introductory note",
    "schedule 13",
)

SIGNATURE_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    RE_CONFORMED_SIGNER_NAME,
    SIG_UNDERLINED_NAME_RE,
    SIG_BY_NAME_RE,
    SIG_DELEGATED_NAME_RE,
    SIG_PERSON_PREFIX_RE,
    SIG_NAME_RE,
)


def is_valid_signature_name(cand: str) -> bool:
    """Validate candidate signature name string against boilerplate and length."""
    if not cand or len(cand) > 60:
        return False
    lower = cand.lower().strip(" .:-")
    if lower in {
        "date",
        "signature",
        "reporting person",
        "power of attorney",
        "attorney-in-fact",
        "attorney in fact",
        "common stock",
        "units",
        "code",
        "d",
        "i",
        "a",
        "table i",
        "table ii",
        "table 1",
        "table 2",
        "certify",
    }:
        return False
    if any(term in lower for term in SIG_BOILERPLATE_TERMS):
        return False
    if MONTH_NAME_RE.fullmatch(cand.strip(" .,")):
        return False
    if lower.rstrip(" .") in (
        "attorney-in-fact",
        "attorney in fact",
        "attorney-in-fact for",
        "attorney in fact for",
    ):
        return False
    words = cand.split()
    if not (1 <= len(words) <= 6):
        return False
    return len(words) > 1 or len(cand) >= 4


_NAME_INITIAL_END_RE = re.compile(r"(?:^|\s)[A-Z]\.$")
_DUPLICATE_NAME_RE = re.compile(r"^([A-Z][A-Za-z.\s',-]+?)\s+\1$")


def clean_signature_name(raw_text: str) -> str:
    """Strip underline runs, prefix labels, and conformed markers from a name."""
    cleaned = RE_SIGNATURE_HTML_TAG.sub(" ", raw_text)
    cleaned = CONFORMED_SIGNATURE_RE.sub(" ", cleaned)
    cleaned = CLEAN_LINE_RE.sub(" ", cleaned)
    cleaned = SIG_BY_PREFIX_RE.sub("", cleaned.strip())
    cleaned = PREFIX_STRIP_RE.sub("", cleaned.strip())
    cleaned = SIG_TRAILING_PAREN_NUM_RE.sub("", cleaned.strip())
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(" ,-/")
    if cleaned.endswith(".") and not _NAME_INITIAL_END_RE.search(cleaned):
        cleaned = cleaned[:-1].strip(" ,-/")
    if dup_match := _DUPLICATE_NAME_RE.match(cleaned):
        cleaned = dup_match.group(1).strip(" ,-/")
    return cleaned


def parse_conformed_signature(text: str) -> tuple[str, bool]:
    """Extract signatory name and return whether conformed markings were found."""
    is_conformed = bool(CONFORMED_SIGNATURE_RE.search(text))
    cleaned = clean_signature_name(text)
    return cleaned, is_conformed


def resolve_delegated_signer(
    text: str,
) -> tuple[str, DelegationKind, str | None]:
    """Resolve signatory name, delegation kind, and agent name if delegated."""
    cleaned = clean_signature_name(text)
    if bool(SIG_DELEGATED_NAME_RE.search(text)):
        parts = SIG_DELEGATED_SPLIT_RE.split(cleaned)
        agent = parts[0].strip(" ,.-/") if parts else None
        return cleaned, DelegationKind.POWER_OF_ATTORNEY, agent
    return cleaned, DelegationKind.DIRECT, None


_SURNAME_FIRST_RE = re.compile(
    r"(?i)(?:/\s*s\s*/|(?<![a-z])s/)\s*(?:by\s*:?\s*)?"
    r"([A-Z][A-Za-z\-']+,\s*[A-Z][A-Za-z\.\-']+(?:\s+[A-Z]\.)?)"
)
_LABEL_NEXT_LINE_RE = re.compile(
    r"(?im)^\s*\*{0,2}\s*signature of reporting person\s*\n\s*([^\n]{2,60}?)\s*$"
)


def extract_signature_candidate(sig_text: str) -> tuple[str | None, str | None]:
    """Extract signature name and signature date from cleaned signature block text."""
    sig_name: str | None = None
    sig_date: str | None = None
    lower = sig_text.lower()
    has_sig_rep_person = "signature of reporting person" in lower
    lines = sig_text.splitlines()

    def _first_date(text: str) -> str | None:
        unruled = SIG_RULE_RUN_RE.sub(" ", text)
        found = (
            RE_FULL_DATE.search(unruled)
            or NUMERIC_DATE_RE.search(unruled)
            or ISO_DATE_RE.search(unruled)
        )
        return found.group(0).strip() if found else None

    for line in lines:
        if CONFORMED_SIGNATURE_RE.search(line) or (
            "date" in line.lower() and len(line) < 60 and "as of" not in line.lower()
        ):
            sig_date = _first_date(line)
            if sig_date:
                break
    label_idx: int | None = None
    if has_sig_rep_person:
        label_idx = max(
            i
            for i, line in enumerate(lines)
            if "signature of reporting person" in line.lower()
        )
    if not sig_date:
        for index, line in enumerate(lines[:-1]):
            if label_idx is not None and not label_idx - 15 <= index <= label_idx + 9:
                continue
            if label_idx is None and index < len(lines) - 25:
                continue
            if not CONFORMED_SIGNATURE_RE.search(line) or _first_date(line):
                continue
            following = lines[index + 1]
            paired = _first_date(following)
            if not paired or CONFORMED_SIGNATURE_RE.search(following):
                continue
            rest = SIG_RULE_RUN_RE.sub(" ", following.replace(paired, " ")).strip(
                " ,.-\t"
            )
            if len(rest) <= 48 and not any(char.isdigit() for char in rest):
                sig_date = paired
                break
    if not sig_date and label_idx is not None:
        for line in lines[label_idx : label_idx + 9]:
            if "as of" in line.lower():
                continue
            sig_date = _first_date(line)
            if sig_date:
                break
        if not sig_date:
            for back in range(max(0, label_idx - 2), label_idx):
                found = _first_date(lines[back])
                if not found:
                    continue
                rest = lines[back].replace(found, " ").strip(" ,.-\t")
                if not rest or extract_clean_signatory_name(rest):
                    sig_date = found
                    break
    if not sig_date and not has_sig_rep_person:
        for line in lines:
            if "as of" in line.lower():
                continue
            sig_date = _first_date(line)
            if sig_date:
                break
    for pattern in SIGNATURE_NAME_PATTERNS:
        if (
            pattern is SIG_PERSON_PREFIX_RE or pattern is SIG_NAME_RE
        ) and not has_sig_rep_person:
            continue
        match = pattern.search(sig_text)
        if match:
            candidate = match.group(1).strip(" ,.-")
            candidate = _TRAILING_MONTH_WORD_RE.sub("", candidate).strip(" ,.-")
            candidate = WHITESPACE_RE.sub(" ", candidate)
            if is_valid_signature_name(candidate):
                sig_name = candidate
                break
    if sig_name is None or len(sig_name.split()) == 1:
        m_sf = _SURNAME_FIRST_RE.search(sig_text)
        if m_sf:
            cand_sf = m_sf.group(1).strip(" ,-")
            if is_valid_signature_name(cand_sf) and (
                sig_name is None or cand_sf.startswith(sig_name)
            ):
                sig_name = cand_sf
    if not sig_name and has_sig_rep_person:
        m_lbl = _LABEL_NEXT_LINE_RE.search(sig_text)
        if m_lbl:
            sig_name = extract_clean_signatory_name(m_lbl.group(1))
    if not sig_name and has_sig_rep_person:
        label_line = max(
            i
            for i, line in enumerate(lines)
            if "signature of reporting person" in line.lower()
        )
        for back in range(max(0, label_line - 3), label_line):
            prev = _TRAILING_DATE_WORD_RE.sub("", lines[back]).strip()
            if prev and SIG_RULE_RUN_RE.sub("", prev).strip():
                cleaned_prev = extract_clean_signatory_name(prev)
                if cleaned_prev:
                    sig_name = cleaned_prev
                    break
    return sig_name, sig_date


def extract_signature_block(text: str) -> SignatureBlock | None:
    """Parse text into a structured signature block with detected signatories."""
    if not text.strip():
        return None
    has_notary = bool(NOTARY_JURAT_RE.search(text))
    sig_name, sig_date = extract_signature_candidate(text)
    signatories: list[Signatory] = []
    if sig_name:
        signatories.append(Signatory(name=sig_name, date=sig_date))
    return SignatureBlock(
        signatories=tuple(signatories),
        is_conformed=bool(CONFORMED_SIGNATURE_RE.search(text)),
        has_notary=has_notary,
        raw_text=text,
    )


_COMPILED_SIGNATURE_PACK = compile_evidence_pack(COMMON_SIGNATURE_LEXICAL_PACK)
_EVIDENCE_CTX = EvidenceContext(min_words=1)


def is_signature_table(
    lower: str,
    past_tables: bool,
    *,
    extra_markers: tuple[str, ...] = (),
    tokens: Sequence[Token] | None = None,
) -> bool:
    """Classify whether table text represents a conformed signature section."""
    if not past_tables and not any(
        k in lower
        for k in (
            "signature",
            "misstatement",
            "criminal",
            "presents",
            "attorney",
            "notary",
            "sworn",
            "signatory",
            "yours",
        )
    ):
        return False
    resolved = tokens if tokens is not None else tokenize(lower)
    score = score_tokens(resolved, _COMPILED_SIGNATURE_PACK, _EVIDENCE_CTX)
    if "signature_decisive" in score.satisfied_tiers and not score.exclusions:
        return True
    if not past_tables:
        return False
    if any(marker in lower for marker in ("/s/", "-s-", "signature:", *extra_markers)):
        return True
    if (
        len(lower) < 80
        and ("date" in lower or "dated" in lower)
        and bool(NUMERIC_DATE_RE.search(lower) or MONTH_RE.search(lower))
    ):
        return True
    return score.score >= 2 and not score.exclusions


DISALLOWED_SIGNATURE_NAME_WORDS: frozenset[str] = frozenset(
    (
        "reporting",
        "person",
        "signature",
        "date",
        "power",
        "attorney",
        "fact",
        "units",
        "stock",
        "common",
        "shares",
        "title",
        "security",
        "derivative",
        "month",
        "year",
        "see",
        "instruction",
        "copies",
        "form",
        "page",
        "intentional",
        "misstatements",
        "omissions",
        "facts",
        "constitute",
        "federal",
        "criminal",
        "violations",
        "note",
        "inc",
        "corp",
        "corporation",
        "company",
        "llc",
        "gross",
        "proceeds",
        "market",
        "value",
        "aggregate",
        "approximate",
        "approx",
    )
)

SIG_DELIMITER_TERMS = (
    r",\s*",
    r"\s+by\b",
    r"\s+as\b",
    r"\s+for\b",
    r"\s+poa\b",
    r"\s+attorney-in-fact\b",
    r"\s+attorney\s+in\s+fact\b",
    r"\s+atty\s+in\s+fact\b",
    r"\s+atty\b",
    r"\s*[\u2013\u2014]\s*",
    r"\s*/\s*",
    r"\n",
    r"\t",
    r"\s{2,}",
)
SIG_DELIMITER_ALT = build_alternation(SIG_DELIMITER_TERMS, auto_escape=False)
SIG_DELIMITER_SPLIT_RE = re.compile(rf"(?i)(?:{SIG_DELIMITER_ALT})")
SIG_LABEL_TERMS = (
    r"\*{0,2}\s*signature\s+of\s+reporting\s+person",
    r"\(?\s*signature\s*\)?",
    r"\(?\s*signed\s*\)?",
)
SIG_LABEL_ALT = build_alternation(SIG_LABEL_TERMS, auto_escape=False)
SIG_LABEL_RE = re.compile(rf"(?i){SIG_LABEL_ALT}")
TITLE_CASE_WORD_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ][a-zA-ZÀ-ÖØ-öø-ÿ’‘'\.\-]*$")
ALL_CAPS_WORD_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ\.\-]*$")
SIG_TRAILING_PAREN_RE = re.compile(r"\s*\([^\)]+\)$")
SIG_SEGMENT_SPLIT_RE = re.compile(r"\s+(?:&|and)\s+")
SIG_NAME_TRIM_CHARS = " ,.-*()_\u2013\u2014/"
SIG_NAME_TRIM_CHARS_NO_DOT = " ,-*()_\u2013\u2014/"


def _comma_delimited(text: str, head_word: str) -> bool:
    pos = text.find(head_word)
    if pos < 0:
        return False
    return text[pos + len(head_word) :].lstrip(" \t").startswith(",")


def extract_clean_signatory_name(raw_text: str) -> str | None:
    """Extract and validate clean Title Cased signatory name from raw cell text."""
    if not raw_text:
        return None
    s = SIG_TRAILING_PAREN_RE.sub("", raw_text.strip())
    if " & " in s or " and " in s:
        segments = SIG_SEGMENT_SPLIT_RE.split(s)
        cleaned_segs = [extract_clean_signatory_name(seg) for seg in segments]
        if all(seg is not None for seg in cleaned_segs):
            return " & ".join(cleaned_segs)
        if (
            cleaned_segs
            and cleaned_segs[0] is not None
            and all(seg is None for seg in cleaned_segs[1:])
        ):
            return cleaned_segs[0]
    s = SIG_LEADING_RULE_RE.sub("", s.strip())
    s = SIG_BY_PREFIX_RE.sub("", s.strip())
    s = SIG_CONFORMED_PREFIX_RE.sub("", s.strip())
    s = SIG_LEADING_RULE_RE.sub("", s.strip())
    m_sig_label = SIG_LABEL_RE.search(s)
    if m_sig_label:
        before = s[: m_sig_label.start()].strip()
        after = s[m_sig_label.end() :].strip()
        s = before if before else after
    s = SIG_TRAILING_PAREN_NUM_RE.sub("", s.strip())
    parts = SIG_DELIMITER_SPLIT_RE.split(s)
    cand = (
        parts[0].strip(SIG_NAME_TRIM_CHARS) if parts else s.strip(SIG_NAME_TRIM_CHARS)
    )
    if len(parts) > 1 and parts[1].strip(SIG_NAME_TRIM_CHARS).lower() in (
        "jr",
        "jr.",
        "sr",
        "sr.",
        "ii",
        "iii",
        "iv",
        "v",
    ):
        cand = f"{cand}, {parts[1].strip(SIG_NAME_TRIM_CHARS_NO_DOT)}"
    elif len(parts) > 1 and len(cand.split()) == 1 and _comma_delimited(s, cand):
        rest = parts[1].strip(SIG_NAME_TRIM_CHARS_NO_DOT)
        rest_words = rest.split()
        if (
            1 <= len(rest_words) <= 3
            and all(
                TITLE_CASE_WORD_RE.match(w) or ALL_CAPS_WORD_RE.match(w)
                for w in rest_words
            )
            and not any(
                w.lower().strip(".,()'-*\u2013\u2014/")
                in DISALLOWED_SIGNATURE_NAME_WORDS
                for w in rest_words
            )
            and not OFFICER_TITLE_RE.search(rest)
            and not SIGNATORY_ROLE_RE.search(rest)
        ):
            cand = f"{cand}, {rest}"
    cand = SIG_TRAILING_PAREN_NUM_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    cand = NUMERIC_DATE_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    cand = RE_FULL_DATE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    words = cand.split()
    if not (2 <= len(words) <= 6):
        return None
    lower_words = [w.lower().strip(".,()'-*\u2013\u2014/") for w in words]
    if any(w in DISALLOWED_SIGNATURE_NAME_WORDS for w in lower_words):
        return None
    if any(MONTH_RE.fullmatch(w) for w in lower_words):
        return None
    title_probe = _TRAILING_OFFICER_WORD_RE.sub("", cand)
    if OFFICER_TITLE_RE.fullmatch(title_probe) or SIGNATORY_ROLE_RE.fullmatch(
        title_probe
    ):
        return None
    is_title_or_caps = all(
        TITLE_CASE_WORD_RE.match(w.strip(",")) or ALL_CAPS_WORD_RE.match(w.strip(","))
        for w in words
    )
    return cand if is_title_or_caps else None


def _name_from_cell(cell: str) -> str | None:
    cand = extract_clean_signatory_name(cell)
    if cand is None and "\n" in cell:
        cand = extract_clean_signatory_name(" ".join(cell.split()))
    if cand is None:
        matches = list(CONFORMED_SIGNATURE_RE.finditer(cell))
        if matches:
            cand = extract_clean_signatory_name(cell[matches[-1].start() :])
    return cand


def scan_signature_grid(
    rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]],
    *,
    strict_dates: bool = False,
) -> tuple[str | None, str | None]:
    """Scan 2D grid rows to extract clean signatory name and date."""
    sig_name: str | None = None
    sig_date: str | None = None
    for r_idx, row in enumerate(rows):
        r_str = " ".join(row).lower()
        row_is_signature = any(
            marker in r_str for marker in ("signature", "/s/", "-s-")
        ) or any(REVERSED_CONFORMED_CELL_RE.match(cell) for cell in row)
        if not sig_name and row_is_signature:
            for cell in row:
                cand = _name_from_cell(cell)
                if cand:
                    sig_name = cand
                    break
            if not sig_name and r_idx + 1 < len(rows):
                for cell in rows[r_idx + 1]:
                    cand = _name_from_cell(cell)
                    if cand:
                        sig_name = cand
                        break
            if not sig_name and r_idx > 0:
                for cell in rows[r_idx - 1]:
                    cand = _name_from_cell(cell)
                    if cand:
                        sig_name = cand
                        break

        date_marker = any(marker in r_str for marker in ("date", "notice"))
        if not sig_date and (row_is_signature or (date_marker and not strict_dates)):
            for cell in row:
                if not date_marker and len(cell.strip()) > 40:
                    continue
                m_date = (
                    RE_FULL_DATE.search(cell)
                    or NUMERIC_DATE_RE.search(cell)
                    or ISO_DATE_RE.search(cell)
                )
                if m_date and "as of" not in cell.lower():
                    sig_date = m_date.group(0).strip()
                    break
            if not sig_date and row_is_signature:
                for cell in row:
                    if "/s/" not in cell.lower() and "-s-" not in cell.lower():
                        continue
                    unruled = SIG_RULE_RUN_RE.sub(" ", cell)
                    m_date = (
                        RE_FULL_DATE.search(unruled)
                        or NUMERIC_DATE_RE.search(unruled)
                        or ISO_DATE_RE.search(unruled)
                    )
                    if m_date and "as of" not in cell.lower():
                        sig_date = m_date.group(0).strip()
                        break
        if sig_name and sig_date:
            break
    return sig_name, sig_date


__all__ = [
    "CLEAN_LINE_RE",
    "CONFORMED_SIGNATURE_ALT",
    "CONFORMED_SIGNATURE_RE",
    "NOTARY_JURAT_ALT",
    "NOTARY_JURAT_RE",
    "OFFICER_TITLE_ALT",
    "OFFICER_TITLE_RE",
    "POA_AUTH_ALT",
    "POA_AUTH_RE",
    "PREFIX_STRIP_ALT",
    "PREFIX_STRIP_RE",
    "PREFIX_STRIP_TERMS",
    "SIGNATORY_ROLE_ALT",
    "SIGNATORY_ROLE_RE",
    "SIGNATURE_NAME_PATTERNS",
    "SIG_BOILERPLATE_TERMS",
    "SIG_BY_NAME_RE",
    "SIG_BY_NAME_TERMINATOR_ALT",
    "SIG_BY_NAME_TITLE_ALT",
    "SIG_DELEGATED_NAME_RE",
    "SIG_DELEGATED_NAME_SUFFIX_ALT",
    "SIG_NAME_RE",
    "SIG_NAME_TERMINATOR_ALT",
    "SIG_NAME_TRIM_CHARS",
    "SIG_PERSON_PREFIX_RE",
    "SIG_UNDERLINED_NAME_RE",
    "WHITESPACE_RE",
    "clean_signature_name",
    "extract_clean_signatory_name",
    "extract_signature_block",
    "extract_signature_candidate",
    "is_signature_table",
    "is_valid_signature_name",
    "parse_conformed_signature",
    "resolve_delegated_signer",
    "scan_signature_grid",
]
