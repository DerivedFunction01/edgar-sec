"""Unified source-qualified Item 601 and Form 20-F coverage ledger."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.exhibits import CoverageStatus, SourceRef


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    """Source-qualified authority code row."""

    authority_id: str
    code: str
    title: str
    coverage_status: CoverageStatus
    source_refs: tuple[SourceRef, ...]
    pack_id: str | None = None
    evaluator_quality: str | None = None


def get_coverage_entry(authority_id: str, code: str) -> CoverageEntry | None:
    """Get a coverage entry by authority and code.

    Normalizes code by stripping EX-, EXHIBIT, and trailing periods.
    Falls back to base code for sub-code lookups (e.g., 10.42 -> 10).
    """
    code = code.strip()
    code = code.upper()
    if code.startswith("EX-"):
        code = code[3:]
    if code.startswith("EXHIBIT "):
        code = code[10:]
    code = code.rstrip(".")

    entry = _LOOKUP.get((authority_id, code), None)
    if entry is None and "." in code:
        base_code = code.split(".")[0]
        entry = _LOOKUP.get((authority_id, base_code), None)
    return entry


def list_coverage_entries(authority_id: str | None = None) -> tuple[CoverageEntry, ...]:
    """List coverage entries. Filter by authority if given."""
    if authority_id is not None:
        return tuple(v for k, v in _LOOKUP.items() if k[0] == authority_id)
    return tuple(_LOOKUP.values())


def is_code_reserved(authority_id: str, code: str) -> bool:
    """Check if a code is in the reserved range."""
    entry = get_coverage_entry(authority_id, code)
    return entry is not None and entry.coverage_status == "reserved"


def is_code_supported(authority_id: str, code: str) -> bool:
    """Check if a code is supported (candidate/partial/unsupported/historical)."""
    entry = get_coverage_entry(authority_id, code)
    return entry is not None and entry.coverage_status in (
        "candidate",
        "partial",
        "unsupported",
        "historical",
    )


def is_code_historical(authority_id: str, code: str) -> bool:
    """Check if a code is historical (e.g., 11, 26, 27, 29, 100)."""
    entry = get_coverage_entry(authority_id, code)
    return entry is not None and entry.coverage_status == "historical"


# Authoritative Item 601 descriptions from 17 CFR § 229.601(b)
ITEM_601_DESCRIPTIONS: dict[str, tuple[str, CoverageStatus]] = {
    "1": ("Underwriting agreement", "candidate"),
    "1.A": ("Form of underwriting agreement", "candidate"),
    "1.B": ("Form of dealer agreement", "candidate"),
    "2": (
        "Plan of acquisition, reorganization, arrangement, liquidation, or succession",
        "candidate",
    ),
    "3": ("Articles of incorporation and bylaws", "partial"),
    "3.1": ("Articles of incorporation", "candidate"),
    "3.2": ("Bylaws", "candidate"),
    "3.A": ("Certificate of incorporation", "candidate"),
    "3.B": ("Bylaws", "candidate"),
    "4": (
        "Instruments defining the rights of security holders, including indentures",
        "candidate",
    ),
    "5": ("Opinion re legality", "candidate"),
    "6": ("Reserved", "reserved"),
    "7": ("Correspondence from independent accountant re non-reliance", "candidate"),
    "8": ("Opinion re tax matters", "candidate"),
    "9": ("Voting trust agreement", "candidate"),
    "10": ("Material contracts", "partial"),
    "11": ("Statement re computation of per share earnings", "historical"),
    "12": ("Statement re computation of ratios", "candidate"),
    "13": (
        "Annual report to security holders, Form 10-Q or quarterly report",
        "candidate",
    ),
    "14": ("Code of ethics", "candidate"),
    "15": ("Letter re unaudited interim financial information", "candidate"),
    "16": ("Letter re change in certifying accountant", "candidate"),
    "17": ("Correspondence on departure of director", "candidate"),
    "18": ("Letter re change in accounting principles", "candidate"),
    "19": ("Insider trading policies and procedures", "candidate"),
    "20": ("Other documents or statements to security holders", "candidate"),
    "21": ("Subsidiaries of the registrant", "candidate"),
    "22": ("Subsidiary guarantors and issuers of guaranteed securities", "candidate"),
    "23": ("Consents of experts and counsel", "candidate"),
    "24": ("Power of attorney", "candidate"),
    "25": ("Statement of eligibility of trustee (Form T-1)", "candidate"),
    "26": ("Invitations for competitive bids", "historical"),
    "27": ("Financial Data Schedule", "historical"),
    "28": ("Information from reports to state insurance authorities", "candidate"),
    "29": ("Additional exhibits (historical)", "historical"),
    "30": ("Foreign jurisdictions preventing inspections disclosure", "candidate"),
    "31": ("Rule 13a-14(a)/15d-14(a) Certifications (Section 302)", "partial"),
    "31.1": ("Certification of CEO/CFO pursuant to Section 302", "candidate"),
    "31.2": ("Certification of CFO pursuant to Section 302", "candidate"),
    "32": ("Section 1350 Certifications (Section 906)", "candidate"),
    "32.1": ("Certification pursuant to Section 906", "candidate"),
    "32.2": ("Certification pursuant to Section 906", "candidate"),
    "33": ("Assessment of compliance with servicing criteria (ABS)", "candidate"),
    "34": (
        "Attestation report on compliance with servicing criteria (ABS)",
        "candidate",
    ),
    "35": ("Servicer compliance statement (ABS)", "candidate"),
    "36": ("Depositor certification for shelf offerings of ABS", "candidate"),
    "95": ("Mine safety disclosure exhibit", "candidate"),
    "96": ("Technical report summary (mining)", "candidate"),
    "97": (
        "Policy relating to recovery of erroneously awarded compensation",
        "candidate",
    ),
    "98": ("Reports, opinions, or appraisals in de-SPAC transactions", "candidate"),
    "99": ("Additional exhibits", "partial"),
    "99.1": ("Press release", "candidate"),
    "100": ("XBRL Related Documents", "historical"),
    "101": ("Interactive Data File (XBRL)", "unsupported"),
    "101.INS": ("XBRL Instance File", "unsupported"),
    "102": ("Asset Data File (ABS-EE)", "unsupported"),
    "103": ("Asset Related Documents (ABS-EE)", "unsupported"),
    "104": ("Cover Page Interactive Data File", "unsupported"),
    "106": ("Static Pool PDF", "unsupported"),
    "107": ("Filing Fee Table", "candidate"),
}

# Authoritative Form 20-F Item 19 descriptions
FORM_20F_DESCRIPTIONS: dict[str, tuple[str, CoverageStatus]] = {
    "1": ("The articles of incorporation or association and bylaws", "disabled"),
    "2": ("Instruments defining the rights of holders of securities", "disabled"),
    "3": ("Voting trust agreements", "disabled"),
    "4": ("Material contracts", "disabled"),
    "5": ("Material foreign patents list", "disabled"),
    "6": ("[Reserved]", "reserved"),
    "7": ("[Reserved]", "reserved"),
    "8": ("List of all subsidiaries", "disabled"),
    "9": ("Statement pursuant to instructions to Item 8.A.4", "disabled"),
    "10": (
        "Notice required by Rule 104 of Regulation BTR (blackout period)",
        "disabled",
    ),
    "11": ("Code of ethics and insider trading policies", "disabled"),
    "12": (
        "Certifications required by Rule 13a-14(a) or 15d-14(a) (Section 302)",
        "disabled",
    ),
    "13": (
        "Certifications required by Rule 13a-14(b) and Section 1350 (Section 906)",
        "disabled",
    ),
    "14": ("Legal opinion required by Instruction 3 of Item 7.B", "disabled"),
    "15": ("Additional exhibits and documents incorporated by reference", "disabled"),
    "16": ("Mine safety disclosure", "disabled"),
    "17": ("Subsidiary guarantors and issuers of guaranteed securities", "disabled"),
    "18": ("[Reserved]", "reserved"),
    "97": (
        "Policy relating to recovery of erroneously awarded compensation",
        "disabled",
    ),
    "98": ("[Reserved]", "reserved"),
    "99": ("[Reserved]", "reserved"),
    "100": ("[Reserved]", "reserved"),
    "101": ("Interactive Data File", "disabled"),
    "102": ("[Reserved]", "reserved"),
    "103": ("[Reserved]", "reserved"),
    "104": ("Cover Page Interactive Data File", "disabled"),
}


# Build lookup tables
def _build_601_ledger() -> dict[tuple[str, str], CoverageEntry]:
    """Build Item 601 coverage ledger from authoritative descriptions."""
    rows: list[CoverageEntry] = []
    source_refs = SourceRef(
        source_path="https://www.ecfr.gov/current/title-17/chapter-II/part-229/subpart-229.600/section-229.601",
        section_or_lines="17 CFR § 229.601(b)",
        note="eCFR Item 601 authoritative source",
    )
    for code, (title, status) in ITEM_601_DESCRIPTIONS.items():
        rows.append(
            CoverageEntry(
                authority_id="reg_s_k_item_601",
                code=code,
                title=title,
                coverage_status=status,
                source_refs=source_refs,
            )
        )
    return {("reg_s_k_item_601", e.code): e for e in rows}


def _build_20f_ledger() -> dict[tuple[str, str], CoverageEntry]:
    """Build Form 20-F coverage ledger from authoritative descriptions."""
    rows: list[CoverageEntry] = []
    source_refs = SourceRef(
        source_path="https://www.sec.gov/files/form20-f.pdf",
        section_or_lines="Item 19",
        note="SEC Form 20-F Instructions as to Exhibits",
    )
    for code, (title, status) in FORM_20F_DESCRIPTIONS.items():
        rows.append(
            CoverageEntry(
                authority_id="form_20f",
                code=code,
                title=title,
                coverage_status=status,
                source_refs=source_refs,
            )
        )
    return {("form_20f", e.code): e for e in rows}


_LOOKUP: dict[tuple[str, str], CoverageEntry] = {}
_LOOKUP.update(_build_601_ledger())
_LOOKUP.update(_build_20f_ledger())

__all__ = [
    "CoverageEntry",
    "get_coverage_entry",
    "list_coverage_entries",
    "is_code_reserved",
    "is_code_supported",
    "is_code_historical",
]
