"""Assembles a BeneficialOwnershipDocument from normalization results."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.signatures import SignatureBlock, Signatory
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    NarrativeItem,
)
from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNER_NAME,
    find_signature_regions,
)
from edgar_sec.engine.forms.common.signatures import (
    extract_signature_block as parse_signature_block,
    extract_signature_candidate,
)
from edgar_sec.engine.forms.normalize import NormalizationResult
from .cover_parser import extract_reporting_person_covers
from .issuer import extract_issuer_metadata

_RE_ITEM_NUM = re.compile(r"\d+")
_RE_FIRST_PERSON = re.compile(
    r"(?im)^\s*1\b\s*[.:]?\s*(?:NAMES?\s+OF\s+REPORTING\s+PERSONS?|NAME\s+OF\s+REPORTING\s+PERSON)"
)


def _signature_block(suffix: str) -> SignatureBlock | None:
    signatories: list[Signatory] = []
    matches = list(RE_CONFORMED_SIGNER_NAME.finditer(suffix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(suffix)
        candidate, date = extract_signature_candidate(suffix[match.start() : end])
        if candidate:
            signatories.append(Signatory(name=candidate, date=date))
    if not signatories:
        regions = find_signature_regions(suffix.splitlines())
        for region in regions:
            parsed = parse_signature_block("\n".join(region.lines))
            if parsed is not None:
                signatories.extend(parsed.signatories)
    if not signatories:
        return None
    return SignatureBlock(
        signatories=tuple(signatories),
        raw_text=suffix.strip(),
    )


def parse_beneficial_ownership_document(
    result: NormalizationResult, *, form: str | None = None
) -> BeneficialOwnershipDocument:
    """Parses a normalized beneficial ownership result into a document model."""
    lines = result.text.splitlines()
    cover_end = (
        result.cover_boundary.end_line
        if result.cover_boundary.end_line is not None
        else (
            result.sections.sections[0].start_line
            if result.sections and result.sections.sections
            else len(lines)
        )
    )
    cover_text = "\n".join(lines[:cover_end])

    first_match = _RE_FIRST_PERSON.search(cover_text)
    header_text = cover_text[: first_match.start()] if first_match else cover_text

    normalized_form = (form or "SC 13D").strip().upper()
    is_13g = "13G" in normalized_form
    family = "13G" if is_13g else "13D"
    is_amendment = normalized_form.endswith("/A")
    if is_13g:
        submission_type = "SCHEDULE 13G/A" if is_amendment else "SCHEDULE 13G"
    else:
        submission_type = "SCHEDULE 13D/A" if is_amendment else "SCHEDULE 13D"

    issuer = extract_issuer_metadata(header_text)
    reporting_persons = extract_reporting_person_covers(cover_text, family=family)

    narrative_items: list[NarrativeItem] = []
    if result.sections and result.sections.sections:
        for s in result.sections.sections:
            num_match = _RE_ITEM_NUM.search(s.item_identifier)
            if num_match:
                num = int(num_match.group(0))
                end_line = s.end_line or len(lines)
                sec_lines = lines[s.start_line : end_line]
                heading = sec_lines[0].strip() if sec_lines else s.raw_heading
                body = "\n".join(sec_lines[1:]).strip() if len(sec_lines) > 1 else ""
                narrative_items.append(
                    NarrativeItem(
                        number=num,
                        heading=heading,
                        text=body,
                        start_offset=s.start_char or 0,
                        end_offset=s.end_char or 0,
                        raw_heading=s.raw_heading,
                    )
                )

    last_item_end = (
        result.sections.sections[-1].end_line
        if (
            result.sections
            and result.sections.sections
            and result.sections.sections[-1].end_line is not None
        )
        else cover_end
    )
    sig_suffix = "\n".join(lines[last_item_end:])
    signature_block = _signature_block(sig_suffix)
    signature_text = signature_block.raw_text if signature_block is not None else None

    return BeneficialOwnershipDocument(
        issuer=issuer,
        reporting_persons=reporting_persons,
        narrative_items=tuple(narrative_items),
        signature_block=signature_block,
        signature_text=signature_text,
        submission_type=submission_type,
        form_family=family,
        residual_text=cover_text,
    )


__all__ = ["parse_beneficial_ownership_document"]
