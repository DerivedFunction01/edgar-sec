"""Extraction of Form 144 signature and remarks metadata."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form144.models import NoticeSignature
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.forms.common.columnar_signatures import (
    extract_columnar_signature_and_date,
)
from edgar_sec.engine.forms.common.signatures import (
    extract_signature_block,
    scan_signature_grid,
)
from edgar_sec.engine.forms.form144.patterns import (
    NOTICE_DATE_LABEL_RE,
    PLAN_ADOPTION_RE,
)
from edgar_sec.engine.forms.form144.sections import ClassifiedSection
from edgar_sec.engine.forms.common.dates import normalize_iso_date


def parse_remarks(sections: list[ClassifiedSection] | None) -> str | None:
    values: list[str] = []
    for section in sections or []:
        text = " ".join(
            " ".join(cell.strip() for cell in row if cell.strip())
            for row in section.resolved_grid.rows
        ).strip()
        if text.lower().startswith("remarks:"):
            text = text[len("remarks:") :].strip()
        if text:
            values.append(text)
    return "\n".join(values) or None


def parse_signatures(
    section: ClassifiedSection
    | list[ClassifiedSection]
    | tuple[ClassifiedSection, ...]
    | None,
    full_text: str = "",
    reference_year: int | None = None,
    *,
    fallback_sections: tuple[ClassifiedSection, ...] = (),
    text_lines: tuple[str, ...] = (),
) -> NoticeSignature:
    sections_list = (
        [section]
        if isinstance(section, ClassifiedSection)
        else list(section)
        if section is not None
        else []
    )
    combined = "\n".join(
        " ".join(row) for item in sections_list for row in item.resolved_grid.rows
    )
    if not combined.strip():
        combined = full_text[-4000:] if len(full_text) > 4000 else full_text

    notice_date: str | None = None
    plan_dates: list[str] = []
    conformed_name: str | None = None

    for sec_item in sections_list:
        grid_name, grid_date = scan_signature_grid(sec_item.resolved_grid.rows)
        if not conformed_name and grid_name:
            conformed_name = grid_name
        if not notice_date and grid_date:
            notice_date = grid_date
        if conformed_name and notice_date:
            break

    if not (conformed_name and notice_date):
        for fallback in fallback_sections:
            grid_name, grid_date = scan_signature_grid(
                fallback.resolved_grid.rows, strict_dates=True
            )
            if not conformed_name and grid_name:
                conformed_name = grid_name
            if not notice_date and grid_date:
                notice_date = grid_date
            if conformed_name and notice_date:
                break

    if not conformed_name:
        signature_block = extract_signature_block(combined)
        if (not signature_block or not signature_block.signatories) and full_text:
            marker = full_text.lower().rfind("/s/")
            if marker >= 0:
                start = max(0, marker - 2000)
                end = min(len(full_text), marker + 2000)
                fallback = full_text[start:end]
            else:
                fallback = full_text[-4000:] if len(full_text) > 4000 else full_text
            fallback = parse_html(fallback).text()
            fallback_block = extract_signature_block(fallback)
            if fallback_block and fallback_block.signatories:
                combined = fallback
                signature_block = fallback_block
        if signature_block and signature_block.signatories:
            conformed_name = signature_block.signatories[0].name
            if signature_block.signatories[0].date and not notice_date:
                notice_date = signature_block.signatories[0].date

    if (not conformed_name or not notice_date) and (full_text or text_lines):
        tail_lines = [
            line.strip()
            for line in (
                text_lines or parse_html(full_text[-4000:]).text().splitlines()
            )
            if line.strip()
        ]
        columnar_name, columnar_date = extract_columnar_signature_and_date(
            tail_lines, reference_year=reference_year
        )
        if not conformed_name and columnar_name:
            conformed_name = columnar_name
        if not notice_date and columnar_date:
            notice_date = columnar_date

    if not notice_date:
        notice_match = NOTICE_DATE_LABEL_RE.search(combined)
        if notice_match:
            notice_date = (notice_match.group(1) or notice_match.group(2)).strip()

    plan_match = PLAN_ADOPTION_RE.search(combined)
    if plan_match:
        plan_dates.append(plan_match.group(1).strip())

    notice_date = normalize_iso_date(notice_date, reference_year) or notice_date
    plan_dates = [
        normalize_iso_date(value, reference_year) or value for value in plan_dates
    ]

    return NoticeSignature(
        notice_date=notice_date,
        plan_adoption_dates=tuple(plan_dates),
        signature=f"/s/ {conformed_name}" if conformed_name else None,
    )


__all__ = ["parse_remarks", "parse_signatures"]
