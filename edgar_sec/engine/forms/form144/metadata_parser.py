"""Extraction of Form 144 signature and remarks metadata."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form144.models import NoticeSignature
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.forms.common.signatures import (
    clean_signature_name,
    extract_signature_block,
)
from edgar_sec.engine.forms.form144.patterns import (
    CONFORMED_SIG_RE,
    NOTICE_DATE_LABEL_RE,
    PLAN_ADOPTION_RE,
)
from edgar_sec.engine.forms.form144.sections import ClassifiedSection


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
) -> NoticeSignature:
    combined = ""
    if section is not None:
        sections = [section] if isinstance(section, ClassifiedSection) else section
        combined += "\n".join(
            " ".join(row) for item in sections for row in item.resolved_grid.rows
        )
    if not combined.strip():
        combined = full_text[-4000:] if len(full_text) > 4000 else full_text

    notice_date: str | None = None
    plan_dates: list[str] = []
    conformed_name: str | None = None

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
        if signature_block.signatories[0].date:
            notice_date = signature_block.signatories[0].date

    if not conformed_name:
        conformed_match = CONFORMED_SIG_RE.search(combined)
        if conformed_match:
            conformed_name = clean_signature_name(conformed_match.group(1))

    if not notice_date:
        notice_match = NOTICE_DATE_LABEL_RE.search(combined)
        if notice_match:
            notice_date = notice_match.group(1).strip()

    plan_match = PLAN_ADOPTION_RE.search(combined)
    if plan_match:
        plan_dates.append(plan_match.group(1).strip())

    return NoticeSignature(
        notice_date=notice_date,
        plan_adoption_dates=tuple(plan_dates),
        signature=f"/s/ {conformed_name}" if conformed_name else None,
    )


__all__ = ["parse_remarks", "parse_signatures"]
