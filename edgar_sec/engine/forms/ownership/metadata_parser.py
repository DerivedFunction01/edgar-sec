from __future__ import annotations

from dataclasses import replace

from edgar_sec.domain.forms.families.ownership.models import (
    FilingPeriod,
    Issuer,
    OwnershipMetadata,
    ReportingOwner,
)
from edgar_sec.engine.forms.common.dates import reported_year
from edgar_sec.engine.forms.common.entities import (
    BARE_BOX_NUM_RE,
    PAREN_BOX_NUM_RE,
    RELATIONSHIP_TO_ISSUER_RE,
)
from edgar_sec.engine.forms.common.extraction import FieldSpec, normalize_value
from edgar_sec.engine.forms.common.marks import canonicalize_filled_marks
from edgar_sec.engine.forms.common.columnar_signatures import (
    extract_columnar_signature_and_date,
)
from edgar_sec.engine.forms.common.signatures import (
    SIG_BOILERPLATE_TERMS,
    extract_clean_signatory_name,
    extract_signature_candidate,
    is_valid_signature_name,
    scan_signature_grid,
)
from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.engine.forms.common.tables import is_instruction_row
from edgar_sec.engine.forms.ownership.field_specs import OWNERSHIP_METADATA_FIELDS
from edgar_sec.engine.forms.ownership.issuer_parser import parse_issuer
from edgar_sec.engine.forms.ownership.period_parser import parse_period
from edgar_sec.engine.forms.ownership.reporting_owner_parser import (
    parse_reporting_owner,
)
from edgar_sec.engine.forms.ownership.relationship_box import parse_relationship_box
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.foundation.text.dates import MONTH_RE, NUMERIC_DATE_RE, RE_FULL_DATE

_METADATA_TABLE_MARKERS = ("table i", "table ii", "non-derivative")
_OWNER_TEMPLATE_FIELDS = frozenset(
    ("last", "first", "middle", "street", "city", "state", "zip")
)
_ISSUER_TEMPLATE_FIELDS = frozenset(("issuer name", "ticker or trading symbol"))
_PERIOD_TEMPLATE_FIELDS = frozenset(("month/day", "year"))
_ALL_TEMPLATE_FIELDS = (
    _OWNER_TEMPLATE_FIELDS | _ISSUER_TEMPLATE_FIELDS | _PERIOD_TEMPLATE_FIELDS
)
_OWNER_LABEL_MARKERS = (
    "issuer name",
    "trading symbol",
    "statement for",
    "4. statement",
)
_PERIOD_LABEL_LINE_TERMS = ("date of event", "requiring statement")
_ISSUER_LOOKAHEAD_EXCLUSIONS = (
    "statement for",
    "relationship",
    "reporting person",
    "table i",
)
_PERIOD_LOOKAHEAD_EXCLUSIONS = ("relationship", "table i")


def _extract_template_fields(
    rows: tuple[tuple[str, ...], ...],
    lowered_rows: tuple[tuple[str, ...], ...],
    accepted_fields: frozenset[str],
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row_index, (row, lowered_row) in enumerate(
        zip(rows, lowered_rows, strict=True)
    ):
        for index, label in enumerate(lowered_row):
            field = label.strip("() :.")
            if field not in accepted_fields or field in fields:
                continue
            right_value = next(
                (cell.strip() for cell in row[index + 1 :] if cell.strip()), ""
            )
            right_clean = right_value.strip("() :.").lower()
            if (
                not right_value
                or right_clean in accepted_fields
                or BARE_BOX_NUM_RE.match(right_clean)
                or any(
                    right_clean.startswith(prefix)
                    for prefix in ("3.", "4.", "5.", "6.", "7.", "table", "irs")
                )
            ):
                above_value = ""
                for previous_row in range(row_index - 1, -1, -1):
                    if any(cell.strip() for cell in rows[previous_row]):
                        if index < len(rows[previous_row]):
                            above_value = rows[previous_row][index].strip()
                        if (
                            not above_value
                            and index > 0
                            and index - 1 < len(rows[previous_row])
                        ):
                            above_value = rows[previous_row][index - 1].strip()
                        break
                above_clean = above_value.strip("() :.").lower()
                if (
                    above_value
                    and above_clean not in accepted_fields
                    and not BARE_BOX_NUM_RE.match(above_clean)
                ):
                    fields[field] = above_value
                    continue
                fields[field] = ""
            elif (
                right_value
                and right_clean not in accepted_fields
                and not BARE_BOX_NUM_RE.match(right_clean)
            ):
                fields[field] = right_value
    return fields


def _canonical_date(
    value: str | None,
    spec: FieldSpec,
    reference_year: int | None,
) -> str | None:
    """Canonicalize a date, retaining the raw text when it cannot be resolved."""
    if not value:
        return value
    normalized = normalize_value(value, spec, reference_year)
    return normalized if normalized is not None else value


def _canonical_period(
    period: FilingPeriod,
    year: int | None,
) -> FilingPeriod:
    """Canonicalize the reported period, anchoring two-digit years to the source."""
    return replace(
        period,
        period_of_report=_canonical_date(
            period.period_of_report,
            OWNERSHIP_METADATA_FIELDS["periodOfReport"],
            year,
        ),
        date_of_original=_canonical_date(
            period.date_of_original,
            OWNERSHIP_METADATA_FIELDS["dateOfOriginalSubmission"],
            year,
        ),
    )


def parse_metadata(
    boxes_section: ClassifiedSection | None,
    signatures_section: ClassifiedSection | None,
    reference_year: int | None = None,
    fallback_sections: tuple[ClassifiedSection, ...] = (),
    text_lines: tuple[str, ...] = (),
) -> OwnershipMetadata:
    if boxes_section is None:
        return OwnershipMetadata(
            issuer=Issuer(),
            reporting_owner=ReportingOwner(),
            period=FilingPeriod(),
        )

    rows = boxes_section.resolved_grid.rows
    lowered_rows = tuple(tuple(cell.lower() for cell in row) for row in rows)
    all_template_fields = _extract_template_fields(
        rows, lowered_rows, _ALL_TEMPLATE_FIELDS
    )
    owner_template_fields = {
        key: value
        for key, value in all_template_fields.items()
        if key in _OWNER_TEMPLATE_FIELDS
    }
    issuer_template_fields = {
        key: value
        for key, value in all_template_fields.items()
        if key in _ISSUER_TEMPLATE_FIELDS
    }
    period_template_fields = {
        key: value
        for key, value in all_template_fields.items()
        if key in _PERIOD_TEMPLATE_FIELDS
    }
    owner_lines: list[str] = []
    owner_seen: set[str] = set()
    role_lines: list[str] = []
    role_seen: set[str] = set()
    issuer_cell = ""
    period_candidates: list[tuple[int, str]] = []

    for row_index, (row, lowered_row) in enumerate(
        zip(rows, lowered_rows, strict=True)
    ):
        if any(
            marker in cell_lower
            for cell_lower in lowered_row
            for marker in _METADATA_TABLE_MARKERS
        ):
            break
        for cell_index, (cell, lower) in enumerate(zip(row, lowered_row, strict=True)):
            if not cell:
                continue
            canonical_cell = canonicalize_filled_marks(cell)
            canonical_lower = canonical_cell.lower()
            if cell_index < 2:
                value = "\n".join(
                    line
                    for line in cell.strip().splitlines()
                    if not any(
                        term in line.lower() for term in _PERIOD_LABEL_LINE_TERMS
                    )
                ).strip()
                if (
                    not any(term in lower for term in _OWNER_LABEL_MARKERS)
                    and not is_instruction_row(value)
                    and BARE_BOX_NUM_RE.match(value) is None
                    and PAREN_BOX_NUM_RE.match(value) is None
                    and STATUTORY_PAGE_ARTIFACT_RE.search(value) is None
                    and HEADER_LEAK_RE.search(value) is None
                    and value
                    and value not in owner_seen
                ):
                    owner_seen.add(value)
                    owner_lines.append(value)

            if (
                "issuer name" in lower
                or ("trading symbol" in lower and "name:" in lower)
            ) and not issuer_cell:
                candidate = cell
                right = next(
                    (value.strip() for value in row[cell_index + 1 :] if value.strip()),
                    "",
                )
                if (
                    right
                    and not BARE_BOX_NUM_RE.match(right)
                    and not any(
                        marker in right.lower()
                        for marker in _ISSUER_LOOKAHEAD_EXCLUSIONS
                    )
                ):
                    candidate = f"{cell}\n{right}"
                elif row_index + 1 < len(rows):
                    fraction = (cell_index + 0.5) / max(1, len(row))
                    for next_row in range(row_index + 1, min(row_index + 4, len(rows))):
                        target_row = rows[next_row]
                        if not target_row:
                            continue
                        target_index = min(
                            len(target_row) - 1, int(fraction * len(target_row))
                        )
                        below = target_row[target_index].strip()
                        below_lower = lowered_rows[next_row][target_index]
                        if (
                            below
                            and not BARE_BOX_NUM_RE.match(below)
                            and not any(
                                marker in below_lower
                                for marker in _ISSUER_LOOKAHEAD_EXCLUSIONS
                            )
                        ):
                            candidate = f"{cell}\n{below}"
                            break
                issuer_cell = candidate
            elif (
                "statement for" in lower
                or ("4." in lower and "month" in lower)
                or "date of event" in lower
                or "requiring statement" in lower
                or "date of original" in lower
                or "if amendment" in lower
            ):
                priority = (
                    0
                    if (
                        "statement for" in lower
                        or "date of event" in lower
                        or "requiring statement" in lower
                    )
                    else 1
                )
                candidate = cell
                right = next(
                    (value.strip() for value in row[cell_index + 1 :] if value.strip()),
                    "",
                )
                if (
                    right
                    and not BARE_BOX_NUM_RE.match(right)
                    and (
                        NUMERIC_DATE_RE.search(right)
                        or RE_FULL_DATE.search(right)
                        or (MONTH_RE.search(right) and any(c.isdigit() for c in right))
                    )
                    and not any(
                        marker in right.lower()
                        for marker in _PERIOD_LOOKAHEAD_EXCLUSIONS
                    )
                ):
                    candidate = f"{cell}\n{right}"
                elif row_index + 1 < len(rows):
                    fraction = (cell_index + 0.5) / max(1, len(row))
                    for next_row in range(row_index + 1, min(row_index + 4, len(rows))):
                        target_row = rows[next_row]
                        if not target_row:
                            continue
                        target_index = min(
                            len(target_row) - 1, int(fraction * len(target_row))
                        )
                        below = target_row[target_index].strip()
                        below_lower = lowered_rows[next_row][target_index]
                        has_date = bool(
                            NUMERIC_DATE_RE.search(below) or RE_FULL_DATE.search(below)
                        )
                        if not has_date:
                            for offset in (1, -1):
                                candidate_index = target_index + offset
                                if 0 <= candidate_index < len(target_row):
                                    adjacent = target_row[candidate_index].strip()
                                    if NUMERIC_DATE_RE.search(
                                        adjacent
                                    ) or RE_FULL_DATE.search(adjacent):
                                        below = adjacent
                                        below_lower = lowered_rows[next_row][
                                            candidate_index
                                        ]
                                        has_date = True
                                        break
                        if has_date and not any(
                            marker in below_lower
                            for marker in _PERIOD_LOOKAHEAD_EXCLUSIONS
                        ):
                            candidate = f"{cell}\n{below}"
                            break
                period_candidates.append((priority, candidate))

            if (
                "relationship" in lower
                or RELATIONSHIP_TO_ISSUER_RE.search(canonical_lower)
                or "10%" in lower
            ):
                role_text = " ".join(
                    canonicalize_filled_marks(value.strip())
                    for value in row[max(0, cell_index - 1) : cell_index + 2]
                    if value.strip()
                )
                if role_text and role_text not in role_seen:
                    role_seen.add(role_text)
                    role_lines.append(role_text)

    period_cell = ""
    if period_candidates:
        period_cell = period_candidates[0][1]
        for _priority, cand in sorted(period_candidates, key=lambda pc: pc[0]):
            parsed_cand = parse_period(cand)
            if parsed_cand.period_of_report or parsed_cand.date_of_original:
                period_cell = cand
                break
    if not period_cell and period_template_fields.get("month/day"):
        period_date = period_template_fields["month/day"]
        year = period_template_fields.get("year")
        if year and year not in period_date:
            period_date = f"{period_date} {year}"
        period_cell = f"Statement for\n{period_date}"

    owner = parse_reporting_owner(
        "\n".join(owner_lines),
        "\n".join(role_lines),
        owner_template_fields,
        reference_year,
        relationship=parse_relationship_box(rows),
    )
    issuer = parse_issuer(issuer_cell)
    if issuer_template_fields:
        issuer = Issuer(
            name=issuer_template_fields.get("issuer name", issuer.name),
            trading_symbol=issuer_template_fields.get(
                "ticker or trading symbol", issuer.trading_symbol
            ),
            irs_number=issuer.irs_number,
        )
    period = parse_period(period_cell)

    signature_name: str | None = None
    signature_date: str | None = None
    if signatures_section is not None:
        grid = signatures_section.resolved_grid
        for row_index, row in enumerate(grid.rows):
            row_text = " ".join(row).lower()
            if (
                "signature of reporting person" in row_text
                or "signature of" in row_text
            ):
                if not signature_name:
                    signature_name, _ = scan_signature_grid((row,))
                    if not signature_name and row_index > 0:
                        previous_row = grid.rows[row_index - 1]
                        signature_name, _ = scan_signature_grid((row, previous_row))
                        if len(previous_row) > 1 and previous_row[1].strip():
                            date_match = RE_FULL_DATE.search(
                                previous_row[1]
                            ) or NUMERIC_DATE_RE.search(previous_row[1])
                            if date_match:
                                signature_date = date_match.group(0).strip()
                if signature_name:
                    break

        if not (signature_name and signature_date):
            clean_lines = [
                line.strip()
                for row in grid.rows
                for cell in row
                if cell and cell.strip()
                for line in cell.splitlines()
                if line.strip()
                and not any(
                    term in line.strip().lower() for term in SIG_BOILERPLATE_TERMS
                )
            ]
            candidate_name, candidate_date = extract_signature_candidate(
                "\n".join(clean_lines)
            )
            if not signature_name and candidate_name:
                signature_name = extract_clean_signatory_name(candidate_name) or (
                    candidate_name if is_valid_signature_name(candidate_name) else None
                )
            if not signature_date:
                signature_date = candidate_date

        if not (signature_name and signature_date):
            grid_name, grid_date = scan_signature_grid(grid.rows)
            if not signature_name and grid_name:
                signature_name = grid_name
            if not signature_date and grid_date:
                signature_date = grid_date

    if not (signature_name and signature_date):
        for fallback in fallback_sections:
            grid_name, grid_date = scan_signature_grid(
                fallback.resolved_grid.rows, strict_dates=True
            )
            if not signature_name and grid_name:
                signature_name = grid_name
            if not signature_date and grid_date:
                signature_date = grid_date
            if signature_name and signature_date:
                break

    if not (signature_name and signature_date) and text_lines:
        start = max(0, int(len(text_lines) * 0.4))
        date_before_text = signature_date
        col_name, col_date = extract_columnar_signature_and_date(
            list(text_lines), start_idx=start, reference_year=reference_year
        )
        if not signature_name and col_name:
            signature_name = col_name
        if not signature_date and col_date:
            signature_date = col_date
        if not (signature_name and signature_date):
            cand_name, cand_date = extract_signature_candidate(
                "\n".join(text_lines[start:])
            )
            if not signature_name and cand_name:
                signature_name = extract_clean_signatory_name(cand_name) or (
                    cand_name if is_valid_signature_name(cand_name) else None
                )
            if not signature_date and cand_date and signature_name:
                signature_date = cand_date
        if not signature_name:
            signature_date = date_before_text

    year = reference_year
    if year is None:
        year = reported_year(
            (period.period_of_report, period.date_of_original, signature_date)
        )
    return OwnershipMetadata(
        issuer=issuer,
        reporting_owner=owner,
        period=_canonical_period(period, year),
        signature_name=signature_name,
        signature_date=_canonical_date(
            signature_date,
            OWNERSHIP_METADATA_FIELDS["signatureDate"],
            year,
        ),
    )


__all__ = ["parse_metadata"]
