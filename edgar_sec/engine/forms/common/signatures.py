"""Reusable parsing utilities for conformed signature blocks and delegations."""

from __future__ import annotations

import re

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
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.dates import (
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
SIG_LEADING_RULE_RE = re.compile(r"^[\*_= \-\t]+")
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
    }:
        return False
    if any(term in lower for term in SIG_BOILERPLATE_TERMS):
        return False
    words = cand.split()
    if not (1 <= len(words) <= 6):
        return False
    return len(words) > 1 or len(cand) >= 4


def clean_signature_name(raw_text: str) -> str:
    """Strip underline runs, prefix labels, and conformed markers from a name."""
    cleaned = CONFORMED_SIGNATURE_RE.sub(" ", raw_text)
    cleaned = CLEAN_LINE_RE.sub(" ", cleaned)
    cleaned = SIG_BY_PREFIX_RE.sub("", cleaned.strip())
    cleaned = PREFIX_STRIP_RE.sub("", cleaned.strip())
    cleaned = SIG_TRAILING_PAREN_NUM_RE.sub("", cleaned.strip())
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned.strip(" ,.-/")


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


def extract_signature_candidate(sig_text: str) -> tuple[str | None, str | None]:
    """Extract signature name and signature date from cleaned signature block text."""
    sig_name: str | None = None
    sig_date: str | None = None
    m_date = RE_FULL_DATE.search(sig_text) or NUMERIC_DATE_RE.search(sig_text)
    if m_date:
        sig_date = m_date.group(0).strip()
    lower = sig_text.lower()
    has_sig_rep_person = "signature of reporting person" in lower
    for pattern in SIGNATURE_NAME_PATTERNS:
        if (
            pattern is SIG_PERSON_PREFIX_RE or pattern is SIG_NAME_RE
        ) and not has_sig_rep_person:
            continue
        match = pattern.search(sig_text)
        if match:
            candidate = match.group(1).strip(" ,.-")
            if is_valid_signature_name(candidate):
                sig_name = candidate
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
    score = score_tokens(tokenize(lower), _COMPILED_SIGNATURE_PACK, _EVIDENCE_CTX)
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
TITLE_CASE_WORD_RE = re.compile(r"^[A-Z][a-zA-Z’‘'\.\-]*$")
ALL_CAPS_WORD_RE = re.compile(r"^[A-Z][A-Z\.\-]*$")
SIG_TRAILING_PAREN_RE = re.compile(r"\s*\([^\)]+\)$")
SIG_SEGMENT_SPLIT_RE = re.compile(r"\s+(?:&|and)\s+")
SIG_NAME_TRIM_CHARS = " ,.-*()_\u2013\u2014/"


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
        cand = f"{cand}, {parts[1].strip(SIG_NAME_TRIM_CHARS)}"
    cand = SIG_TRAILING_PAREN_NUM_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS)
    cand = NUMERIC_DATE_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS)
    cand = RE_FULL_DATE.sub("", cand).strip(SIG_NAME_TRIM_CHARS)
    words = cand.split()
    if not (2 <= len(words) <= 6):
        return None
    lower_words = [w.lower().strip(".,()'-*\u2013\u2014/") for w in words]
    if any(w in DISALLOWED_SIGNATURE_NAME_WORDS for w in lower_words):
        return None
    if any(MONTH_RE.fullmatch(w) for w in lower_words):
        return None
    is_title_or_caps = all(
        TITLE_CASE_WORD_RE.match(w) or ALL_CAPS_WORD_RE.match(w) for w in words
    )
    return cand if is_title_or_caps else None


def scan_signature_grid(
    rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]],
) -> tuple[str | None, str | None]:
    """Scan 2D grid rows to extract clean signatory name and date."""
    sig_name: str | None = None
    sig_date: str | None = None
    for r_idx, row in enumerate(rows):
        r_str = " ".join(row).lower()
        if not sig_name and any(
            marker in r_str for marker in ("signature", "/s/", "-s-")
        ):
            for cell in row:
                cand = extract_clean_signatory_name(cell)
                if cand:
                    sig_name = cand
                    break
            if not sig_name and r_idx + 1 < len(rows):
                for cell in rows[r_idx + 1]:
                    cand = extract_clean_signatory_name(cell)
                    if cand:
                        sig_name = cand
                        break
            if not sig_name and r_idx > 0:
                for cell in rows[r_idx - 1]:
                    cand = extract_clean_signatory_name(cell)
                    if cand:
                        sig_name = cand
                        break

        if not sig_date and any(marker in r_str for marker in ("date", "notice")):
            for cell in row:
                m_date = RE_FULL_DATE.search(cell) or NUMERIC_DATE_RE.search(cell)
                if m_date and "as of" not in cell.lower():
                    sig_date = m_date.group(0).strip()
                    break
        if sig_name and sig_date:
            break
    return sig_name, sig_date


_SIGNATURE_LINE_RE = re.compile(
    r"(?:/s/|signature:)\s*(?:/s/\s*)?([A-Za-z\.\,\s\-]+)", re.IGNORECASE
)
_STRIP_SLASH_S_RE = re.compile(r"^.*?/s/\s*")
_WHITESPACE_SPLIT_RE = re.compile(r"\t+|\s{2,}")


def extract_columnar_signature_and_date(
    lines: Sequence[str],
    *,
    start_idx: int = 0,
    reference_year: int | None = None,
) -> tuple[str | None, str | None]:
    """Scan trailing lines backward for conformed signature and notice date."""
    from edgar_sec.engine.forms.common.tables import (
        is_horizontal_rule_line,
        strip_markup_tags,
    )
    from edgar_sec.foundation.text.dates import parse_date

    sig_name: str | None = None
    sig_date: str | None = None
    total_lines = len(lines)

    for idx in range(total_lines - 1, start_idx - 1, -1):
        line = strip_markup_tags(lines[idx])
        if not line or is_horizontal_rule_line(line):
            continue
        lower = line.lower()
        if (
            "intentional misstatements" in lower
            or "criminal violations" in lower
            or "sec 1147" in lower
        ):
            continue

        if not sig_name and ("/s/" in line or "signature:" in lower):
            m = _SIGNATURE_LINE_RE.search(line)
            if m:
                cand = extract_clean_signatory_name(m.group(1))
                if cand:
                    sig_name = cand

        if not sig_name and ("(signature)" in lower or lower == "signature"):
            for d in range(1, 5):
                if idx - d >= 0:
                    above_l = strip_markup_tags(lines[idx - d])
                    if (
                        above_l
                        and not is_horizontal_rule_line(above_l)
                        and not above_l.lower().startswith("date")
                    ):
                        cols = [
                            c.strip()
                            for c in _WHITESPACE_SPLIT_RE.split(above_l)
                            if c.strip()
                        ]
                        for c in reversed(cols):
                            clean_c = _STRIP_SLASH_S_RE.sub("", c) if "/s/" in c else c
                            cand = extract_clean_signatory_name(clean_c)
                            if cand and not any(
                                k in cand.lower()
                                for k in ("attention:", "signature", "notice", "date")
                            ):
                                sig_name = cand
                                break
                        if sig_name:
                            if not sig_date and len(cols) > 1:
                                parsed = parse_date(
                                    cols[0], reference_year=reference_year
                                )
                                if parsed:
                                    sig_date = parsed.display
                            break

        if not sig_date and ("date of notice" in lower or lower.startswith("date:")):
            p_d = parse_date(line, reference_year=reference_year)
            if p_d and "as of" not in lower:
                sig_date = p_d.display
            else:
                for d in (-2, -1, 1, 2):
                    if 0 <= idx + d < total_lines:
                        adj_l = strip_markup_tags(lines[idx + d])
                        p_adj = parse_date(adj_l, reference_year=reference_year)
                        if p_adj and "as of" not in adj_l.lower():
                            sig_date = p_adj.display
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
    "extract_columnar_signature_and_date",
    "extract_signature_block",
    "extract_signature_candidate",
    "is_signature_table",
    "is_valid_signature_name",
    "parse_conformed_signature",
    "resolve_delegated_signer",
    "scan_signature_grid",
]
