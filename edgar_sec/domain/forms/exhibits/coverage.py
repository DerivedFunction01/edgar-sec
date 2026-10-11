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
    """Get a coverage entry by authority and code."""
    return _LOOKUP.get((authority_id, code), None)


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
    """Check if a code is a supported (candidate/partial/unsupported)."""
    entry = get_coverage_entry(authority_id, code)
    return entry is not None and entry.coverage_status in (
        "candidate",
        "partial",
        "unsupported",
    )


def _build_601_ledger() -> dict[tuple[str, str], CoverageEntry]:
    """Build Item 601 coverage ledger."""
    rows: list[CoverageEntry] = []
    # Items 1-107 per Item 601 instructions
    # Candidate items: 1, 2, 5, 8, 9, 13-19, 21-25, 32-36, 95-98, 107
    candidate_items = (
        [1, 2, 5, 8, 9]
        + list(range(13, 20))
        + list(range(21, 26))
        + list(range(32, 37))
        + list(range(95, 99))
        + [107]
    )
    # Partial items: 3, 4, 10, 31, 99
    partial_items = [3, 4, 10, 31, 99]
    # Unsupported items: 7, 20, 101-104, 106
    unsupported_items = [7, 20] + list(range(101, 105)) + [106]
    # Reserved items: 6, 11-12, 26-30, 37-94, 100, 105
    reserved_items = (
        [6, 11, 12] + list(range(26, 31)) + list(range(37, 95)) + [100, 105]
    )

    item_titles = {
        1: "Cover Page",
        2: "Table of Contents",
        3: "Order of the Annual Report",
        4: "Summary of Financial Statements",
        5: "Selected Financial Data",
        6: "Reserved",
        7: "Reserved",
        8: "Financial Statements",
        9: "Changes in and Disagreements with Accountants",
        10: "Directors, Executive Officers, Promoters and Control Persons",
        11: "Reserved",
        12: "Reserved",
        13: "Security Ownership of Certain Beneficial Owners and Management",
        14: "Certain Relationships and Related Transactions",
        15: "Principal Accounting Fees and Services",
        16: "Reserved",
        17: "Reserved",
        18: "Reserved",
        19: "Reserved",
        20: "Reserved",
        21: "Subsidiaries",
        22: "Unresolved Staff Comments",
        23: "Properties",
        24: "Legal Proceedings",
        25: "Mine Safety Disclosures",
        26: "Reserved",
        27: "Reserved",
        28: "Reserved",
        29: "Reserved",
        30: "Reserved",
        31: "Reserved",
        32: "Exhibits",
        33: "Reserved",
        34: "Reserved",
        35: "Reserved",
        36: "Reserved",
    }

    all_items = sorted(
        candidate_items + partial_items + unsupported_items + reserved_items
    )
    for item in all_items:
        title = item_titles.get(item, f"Item {item}")
        if item in candidate_items:
            status = "candidate"
        elif item in partial_items:
            status = "partial"
        elif item in unsupported_items:
            status = "unsupported"
        else:
            status = "reserved"
        rows.append(
            CoverageEntry(
                authority_id="reg_s_k_item_601",
                code=str(item),
                title=title,
                coverage_status=status,
                source_refs=(
                    SourceRef(
                        source_path="edgar_sec/domain/forms/exhibits/coverage.py",
                        section_or_lines=f"{item}",
                    ),
                ),
            )
        )
    return {("reg_s_k_item_601", e.code): e for e in rows}


def _build_20f_ledger() -> dict[tuple[str, str], CoverageEntry]:
    """Build Form 20-F coverage ledger (all disabled/reserved)."""
    rows: list[CoverageEntry] = []
    # Items 1-104 per Form 20-F instructions (all disabled in D1)
    for item in range(1, 105):
        status = "disabled" if item <= 84 else "reserved"
        rows.append(
            CoverageEntry(
                authority_id="form_20f",
                code=str(item),
                title=f"Item {item}",
                coverage_status=status,
                source_refs=(
                    SourceRef(
                        source_path="edgar_sec/domain/forms/exhibits/coverage.py",
                        section_or_lines=f"{item}",
                    ),
                ),
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
]
