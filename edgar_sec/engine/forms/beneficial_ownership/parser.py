"""Assembles a BeneficialOwnershipDocument from normalization results."""

from __future__ import annotations

import re
from dataclasses import replace

from edgar_sec.domain.forms.common.signatures import SignatureBlock, Signatory
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    NarrativeField,
    NarrativeItem,
)
from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNATURE,
    RE_CONFORMED_SIGNER_NAME,
    find_signature_regions,
)
from edgar_sec.engine.forms.common.signatures import (
    clean_signature_name,
    extract_signature_block as parse_signature_block,
    extract_signature_candidate,
    is_valid_signature_name,
)
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.sections.items.candidates import extract_section_candidates
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.forms.sections.models import CandidateKind, SectionSequence
from edgar_sec.foundation.regex.builder import build_alternation
from .cover_parser import extract_reporting_person_covers
from .issuer import extract_issuer_metadata
from .provenance import build_field_extractions, build_unparsed_sections

_RE_ITEM_NUM = re.compile(r"\d+")
_RE_FIRST_PERSON = re.compile(
    r"(?im)^\s*1\b\s*[.:]?\s*(?:NAMES?\s+OF\s+REPORTING\s+PERSONS?|NAME\s+OF\s+REPORTING\s+PERSON)"
)
_RE_SIGNATURE_HEADER = re.compile(r"(?im)^\s*SIGNATURES?\b")
_RE_SIGNATURE_DATE_LINE = re.compile(r"(?i)^\s*(?:DATED|DATE)\b")
_SIGNATURE_TABLE_TAIL_ALT = build_alternation(
    ("SIGNATURE", "NAME", "NAME/TITLE", "TITLE", "DATE", "BY"),
    auto_escape=True,
)
_RE_SIGNATURE_TABLE_TAIL = re.compile(rf"(?i)\s+(?:{_SIGNATURE_TABLE_TAIL_ALT})\b.*$")
_RE_SIGNATURE_MARKER = re.compile(r"(?i)/\s*s\s*/")
_RE_SIGNATURE_HTML_TAG = re.compile(r"</?[^>]+>")
_RE_NARRATIVE_SUBSECTION = re.compile(
    r"(?im)^[ \t]*\(([a-f])\)(?:\s+and\s+\(([a-f])\))?\.?[ \t]*"
)
_ITEM_SUBSECTION_FIELDS = {
    2: {
        "a": "filingPersonName",
        "b": "principalBusinessAddress",
        "c": "principalBusiness",
        "f": "citizenshipOrOrganization",
    },
    5: {
        "a": "percentageOfClassSecurities",
        "b": "numberOfShares",
        "c": "transactionDesc",
        "d": "listOfShareholders",
        "e": "date5PercentOwnership",
    },
}


def _body_sections(
    result: NormalizationResult,
    family: str,
    line_offsets: list[int],
) -> SectionSequence | None:
    from edgar_sec.domain.forms.families.processing_profiles import get_family_entry

    entry = get_family_entry(family)
    if entry is None or not entry.taxonomy_items:
        return result.sections
    lines = result.text.splitlines()
    cover_end = result.cover_boundary.end_line if result.cover_boundary else 0
    candidate_floor = max(0, (cover_end or 0) - 5)
    candidates = [
        candidate
        for candidate in extract_section_candidates(
            lines, taxonomy_items=entry.taxonomy_items
        )
        if candidate.line_number >= candidate_floor
        and candidate.kind
        in {CandidateKind.STANDARD, CandidateKind.NUMERIC, CandidateKind.GROUPED}
        and not candidate.preceded_by_continuation
    ]
    first_item = next(
        (candidate for candidate in candidates if "1" in candidate.identifiers),
        None,
    )
    start_line = (
        first_item.line_number
        if first_item is not None
        else next(
            (
                candidate.line_number
                for candidate in candidates
                if candidate.kind in {CandidateKind.STANDARD, CandidateKind.NUMERIC}
            ),
            None,
        )
    )
    if start_line is None:
        return result.sections
    start_offset = line_offsets[min(start_line, len(line_offsets) - 1)]
    sequence = detect_section_sequence(
        result.text[start_offset:],
        family=family,
        taxonomy_items=entry.taxonomy_items,
    )
    return replace(
        sequence,
        sections=tuple(
            replace(
                section,
                start_line=section.start_line + start_line,
                end_line=(
                    section.end_line + start_line
                    if section.end_line is not None
                    else None
                ),
                start_char=(
                    section.start_char + start_offset
                    if section.start_char is not None
                    else None
                ),
                end_char=(
                    section.end_char + start_offset
                    if section.end_char is not None
                    else None
                ),
            )
            for section in sequence.sections
        ),
    )


def _signature_block(suffix: str) -> SignatureBlock | None:
    signatories: list[Signatory] = []
    matches = list(RE_CONFORMED_SIGNER_NAME.finditer(suffix))
    matched_markers = set()
    for index, match in enumerate(matches):
        marker = _RE_SIGNATURE_MARKER.search(suffix, match.start(), match.end())
        if marker is not None:
            matched_markers.add(marker.start())
        line_start = suffix.rfind("\n", 0, match.start()) + 1
        line_end = suffix.find("\n", match.end())
        if line_end < 0:
            line_end = len(suffix)
        candidate_text = _RE_SIGNATURE_TABLE_TAIL.sub("", match.group(0))
        candidate, date = extract_signature_candidate(candidate_text)
        date = (
            extract_signature_candidate(suffix[line_start : match.start()])[1] or date
        )
        if index:
            preceding_text = suffix[:line_start].splitlines()
            date_line = next(
                (
                    line
                    for line in reversed(preceding_text)
                    if _RE_SIGNATURE_DATE_LINE.match(line)
                ),
                None,
            )
            if date_line is not None:
                date = extract_signature_candidate(date_line)[1] or date
        elif date is None:
            preceding_text = suffix[:line_start].splitlines()
            date_line = next(
                (
                    line
                    for line in reversed(preceding_text)
                    if _RE_SIGNATURE_DATE_LINE.match(line)
                ),
                None,
            )
            if date_line is not None:
                date = extract_signature_candidate(date_line)[1]
        if candidate:
            signatories.append(Signatory(name=candidate, date=date))
    for marker in _RE_SIGNATURE_MARKER.finditer(suffix):
        if marker.start() in matched_markers:
            continue
        line_start = suffix.rfind("\n", 0, marker.start()) + 1
        line_end = suffix.find("\n", marker.end())
        if line_end < 0:
            line_end = len(suffix)
        line = suffix[line_start:line_end]
        tail = _RE_SIGNATURE_TABLE_TAIL.sub("", suffix[marker.end() : line_end])
        tail = _RE_SIGNATURE_HTML_TAG.sub(" ", tail)
        name = clean_signature_name(tail)
        if not is_valid_signature_name(name):
            candidate, _ = extract_signature_candidate(line)
            name = candidate or ""
        if not name or not is_valid_signature_name(name):
            continue
        _, date = extract_signature_candidate(suffix[line_start : marker.start()])
        if date is None:
            _, date = extract_signature_candidate(line)
        if date is None:
            preceding = suffix[:line_start].splitlines()
            date_line = next(
                (
                    value
                    for value in reversed(preceding)
                    if _RE_SIGNATURE_DATE_LINE.match(value)
                ),
                None,
            )
            if date_line is not None:
                _, date = extract_signature_candidate(date_line)
        signatories.append(Signatory(name=name, date=date))
    if not signatories:
        regions = find_signature_regions(suffix.splitlines())
        for region in regions:
            parsed = parse_signature_block("\n".join(region.lines))
            if parsed is not None:
                signatories.extend(parsed.signatories)
    if not signatories:
        parsed = parse_signature_block(suffix)
        if parsed is not None:
            signatories.extend(parsed.signatories)
    if not signatories:
        sig_lines = suffix.splitlines()
        for line_index, line in enumerate(sig_lines):
            if not _RE_SIGNATURE_DATE_LINE.match(line):
                continue
            _, date = extract_signature_candidate(line)
            for name_line in sig_lines[line_index + 1 : line_index + 5]:
                candidate = name_line.strip(" \t*_=-")
                if not candidate:
                    continue
                if is_valid_signature_name(candidate):
                    signatories.append(Signatory(name=candidate, date=date))
                    break
    if not signatories:
        return None
    return SignatureBlock(
        signatories=tuple(signatories),
        raw_text=suffix.strip(),
    )


def _narrative_fields(
    number: int,
    body: str,
    source_text: str,
    source_start: int,
) -> tuple[NarrativeField, ...]:
    field_map = _ITEM_SUBSECTION_FIELDS.get(number)
    if not field_map or not body.strip():
        return ()
    matches = list(_RE_NARRATIVE_SUBSECTION.finditer(body))
    if not matches or body[: matches[0].start()].strip():
        return ()
    labels = [
        label
        for match in matches
        for label in (match.group(1), match.group(2))
        if label is not None
    ]
    if any(left >= right for left, right in zip(labels, labels[1:])):
        return ()

    fields: list[NarrativeField] = []
    for index, match in enumerate(matches):
        next_start = (
            matches[index + 1].start() if index + 1 < len(matches) else len(body)
        )
        raw_value = body[match.end() : next_start]
        value = raw_value.strip()
        if not value:
            continue
        leading = len(raw_value) - len(raw_value.lstrip())
        trailing = len(raw_value) - len(raw_value.rstrip())
        start_offset = source_start + match.start()
        end_offset = source_start + next_start - trailing
        if not 0 <= start_offset < end_offset <= len(source_text):
            continue
        source_excerpt = source_text[start_offset:end_offset]
        group_labels = tuple(label for label in match.groups() if label)
        shared_group = (
            f"item-{number}-subsection-{''.join(group_labels)}"
            if len(group_labels) > 1
            else None
        )
        for label in group_labels:
            tag = field_map.get(label)
            if tag is not None:
                fields.append(
                    NarrativeField(
                        tag=tag,
                        value=value,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        source_text=source_excerpt,
                        shared_source_group=shared_group,
                    )
                )
    return tuple(fields)


def parse_beneficial_ownership_document(
    result: NormalizationResult, *, form: str | None = None
) -> BeneficialOwnershipDocument:
    """Parses a normalized beneficial ownership result into a document model."""
    lines = result.text.splitlines()
    line_offsets = [0]
    for line in result.text.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    normalized_form = (form or "SC 13D").strip().upper()
    is_13g = "13G" in normalized_form
    family = "13G" if is_13g else "13D"
    is_amendment = normalized_form.endswith("/A")
    if is_13g:
        submission_type = "SCHEDULE 13G/A" if is_amendment else "SCHEDULE 13G"
    else:
        submission_type = "SCHEDULE 13D/A" if is_amendment else "SCHEDULE 13D"

    cover_end = (
        result.cover_boundary.end_line
        if result.cover_boundary.end_line is not None
        else (
            result.sections.sections[0].start_line
            if result.sections and result.sections.sections
            else len(lines)
        )
    )
    sections = _body_sections(result, family, line_offsets)
    if result.cover_boundary is not None and sections is not None and sections.sections:
        cover_end = min(cover_end, sections.sections[0].start_line)
    cover_text = "\n".join(lines[:cover_end])

    first_match = _RE_FIRST_PERSON.search(cover_text)
    header_text = cover_text[: first_match.start()] if first_match else cover_text

    issuer = extract_issuer_metadata(header_text)
    reporting_persons = extract_reporting_person_covers(
        cover_text, family=family, base_offset=0
    )

    signature_regions = tuple(
        region
        for region in find_signature_regions(lines)
        if region.start_line >= cover_end and region.signer_count > 0
    )
    signature_start_line = (
        min(region.start_line for region in signature_regions)
        if signature_regions
        else None
    )
    signature_start_offset: int | None = None
    sig_suffix: str | None = None
    if signature_regions and signature_start_line is not None:
        signature_start_offset = line_offsets[signature_start_line]
        signature_end_line = max(region.end_line for region in signature_regions)
        sig_suffix = result.text[
            signature_start_offset : line_offsets[min(signature_end_line, len(lines))]
        ]
    else:
        for match in RE_CONFORMED_SIGNER_NAME.finditer(result.text):
            line_start = result.text.rfind("\n", 0, match.start()) + 1
            line_end = result.text.find("\n", match.start())
            if line_end < 0:
                line_end = len(result.text)
            signature_headers = list(
                _RE_SIGNATURE_HEADER.finditer(result.text, 0, line_start)
            )
            header_offset = (
                signature_headers[-1].start()
                if signature_headers
                and line_start - signature_headers[-1].start() < 2000
                else None
            )
            if header_offset is None and not RE_CONFORMED_SIGNATURE.match(
                result.text[line_start:line_end]
            ):
                continue
            signature_start_offset = header_offset or line_start
            signature_start_line = result.text.count("\n", 0, signature_start_offset)
            sig_suffix = result.text[signature_start_offset:]
            break
    if sig_suffix is None:
        cover_offset = line_offsets[min(cover_end, len(line_offsets) - 1)]
        signature_headers = [
            match
            for match in _RE_SIGNATURE_HEADER.finditer(result.text)
            if match.start() >= cover_offset
        ]
        for heading in reversed(signature_headers):
            candidate = result.text[heading.start() :]
            if _signature_block(candidate) is None:
                continue
            signature_start_offset = heading.start()
            signature_start_line = result.text.count("\n", 0, heading.start())
            sig_suffix = candidate
            break

    narrative_items: list[NarrativeItem] = []
    if sections and sections.sections:
        for s in sections.sections:
            num_match = _RE_ITEM_NUM.search(s.item_identifier)
            if num_match:
                num = int(num_match.group(0))
                end_line = s.end_line or len(lines)
                if (
                    signature_start_line is not None
                    and s.start_line < signature_start_line
                ):
                    end_line = min(end_line, signature_start_line)
                sec_lines = lines[s.start_line : end_line]
                heading = sec_lines[0].strip() if sec_lines else s.raw_heading
                body = "\n".join(sec_lines[1:]).strip() if len(sec_lines) > 1 else ""
                section_end_offset = min(
                    s.end_char or len(result.text),
                    line_offsets[min(end_line, len(line_offsets) - 1)],
                )
                body_source_start = (
                    result.text.find(body, s.start_char or 0, section_end_offset)
                    if body
                    else -1
                )
                narrative_items.append(
                    NarrativeItem(
                        number=num,
                        heading=heading,
                        text=body,
                        start_offset=s.start_char or 0,
                        end_offset=section_end_offset,
                        raw_heading=s.raw_heading,
                        parsed_fields=(
                            _narrative_fields(
                                num,
                                body,
                                result.text,
                                body_source_start,
                            )
                            if body_source_start >= 0
                            else ()
                        ),
                    )
                )

    last_item_end = (
        sections.sections[-1].end_line
        if (
            sections
            and sections.sections
            and sections.sections[-1].end_line is not None
        )
        else cover_end
    )
    if sig_suffix is None:
        sig_suffix = "\n".join(lines[last_item_end:])
    signature_block = _signature_block(sig_suffix)
    signature_text = signature_block.raw_text if signature_block is not None else None

    document = BeneficialOwnershipDocument(
        issuer=issuer,
        reporting_persons=reporting_persons,
        narrative_items=tuple(narrative_items),
        signature_block=signature_block,
        signature_text=signature_text,
        submission_type=submission_type,
        form_family=family,
        source_length=len(result.text),
    )
    header_end = len(header_text)
    field_extractions = build_field_extractions(document, result.text, header_end)
    unparsed_sections = build_unparsed_sections(
        result.text, field_extractions, document.narrative_items
    )
    return replace(
        document,
        residual_text="\n\n".join(section.text for section in unparsed_sections),
        field_extractions=field_extractions,
        unparsed_sections=unparsed_sections,
    )


__all__ = ["parse_beneficial_ownership_document"]
