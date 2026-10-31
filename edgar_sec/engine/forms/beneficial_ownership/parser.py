"""Assembles a BeneficialOwnershipDocument from normalization results."""

from __future__ import annotations

import re
from dataclasses import replace

from edgar_sec.domain.forms.common.signatures import SignatureBlock, Signatory
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    NarrativeField,
    NarrativeItem,
    ReportingPersonCover,
)
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_CONFORMED_SIGNATURE,
    RE_CONFORMED_SIGNER_NAME,
)
from edgar_sec.engine.document.page_markers.signatures import (
    find_signature_regions,
)
from edgar_sec.engine.forms.common.entities import is_valid_entity_name
from edgar_sec.engine.forms.common.signatures import (
    OFFICER_TITLE_RE,
    clean_signature_name,
    extract_signature_block as parse_signature_block,
    extract_signature_candidate,
    is_valid_signature_name,
)
from edgar_sec.engine.forms.common.dates import normalize_iso_date, reported_year
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.sections.items.candidates import extract_section_candidates
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.forms.sections.models import CandidateKind, SectionSequence
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    ALL_SEC_DATE_FORMATS,
    SEC_DATE_FORMATS,
    parse_date,
)
from .cover_parser import extract_reporting_person_covers
from .issuer import extract_issuer_metadata
from .item_subsections import extract_subsections
from .provenance import build_field_extractions, build_unparsed_sections
from .signatures import extract_beneficial_ownership_signature_block as _signature_block
from edgar_sec.engine.forms.common.numbers import normalize_schema_number
from .vocabulary import (
    REPORTING_PERSON_SLOT_NUMBERS_13D,
    REPORTING_PERSON_SLOT_NUMBERS_13G,
)

_RE_ITEM_NUM = re.compile(r"\d+")
_RE_REPORTING_PERSON_CORE = r"(?:(?:\(?\s*(?:ITEM\s+[1lI]\b|[1lI]\b)\s*\)?\s*[:.]?\s*(?:\([a-z0-9]+\)\s*)?)\s*(?:NAMES?\s+OF\s+REPORTING\s+PERSONS?|REPORTING\s+PERSONS?)|(?:(?<=[\n\r])|^\s*)\s*NAMES?\s+OF\s+REPORTING\s+PERSONS?)"
_RE_FIRST_PERSON = re.compile(rf"(?im)(?:^\s*|\b){_RE_REPORTING_PERSON_CORE}")
_RE_SIGNATURE_HEADER = re.compile(
    r"(?im)^\s*(?:SIGNATURES?|AFTER\s+REASONABLE\s+INQUIRY)\b"
)
_RE_SIGNATURE_DATE_LINE = re.compile(r"(?i)^\s*(?:DATED|DATE)\b")
_EVENT_DATE_CUE_ALT = build_alternation(
    ("date of event", "as of", "dated", "a/o"),
    auto_escape=True,
    compact=True,
)
_RE_DATE_CUE = re.compile(rf"(?i)\b(?:{_EVENT_DATE_CUE_ALT})\b")
_COVER_ROW_ALT = build_alternation(
    (
        "reporting person",
        "reporting persons",
        "voting power",
        "dispositive power",
        "place of organization",
        "citizenship",
        "type of reporting person",
        "aggregate amount",
        "source of funds",
        "sec use only",
    ),
    auto_escape=True,
    compact=True,
)
_RE_COVER_ROW = re.compile(rf"(?i)\b(?:{_COVER_ROW_ALT})\b")


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
        if candidate.kind
        in {CandidateKind.STANDARD, CandidateKind.NUMERIC, CandidateKind.GROUPED}
        and (
            not candidate.preceded_by_continuation
            or (candidate.kind == CandidateKind.STANDARD and candidate.title)
        )
        and not _RE_COVER_ROW.search(candidate.raw_text)
    ]
    if candidate_floor and candidate_floor < len(lines) - 5:
        filtered = [c for c in candidates if c.line_number >= candidate_floor]
        if filtered:
            candidates = filtered
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


def _narrative_fields(
    number: int,
    body: str,
    source_text: str,
    source_start: int,
    family: str = "13G",
) -> tuple[NarrativeField, ...]:
    return extract_subsections(
        number,
        body,
        family=family,
        base_offset=source_start,
    )


def _find_narrative_event_date(
    lines: list[str],
    reference_year: int | None,
) -> str | None:
    allow_2d = reference_year is not None
    formats = ALL_SEC_DATE_FORMATS if allow_2d else SEC_DATE_FORMATS
    for index, line in enumerate(lines):
        if not _RE_DATE_CUE.search(line):
            continue
        window = lines[max(0, index - 3) : min(len(lines), index + 4)]
        for candidate_line in window:
            stripped = candidate_line.strip()
            if not stripped:
                continue
            parsed = parse_date(stripped, reference_year=reference_year)
            if (
                not parsed
                or parsed.ambiguous
                or (not allow_2d and "2digit" in parsed.format_id)
            ):
                for fmt in formats:
                    if m := fmt.pattern.search(stripped):
                        cp = parse_date(m.group(0), reference_year=reference_year)
                        if (
                            cp
                            and not cp.ambiguous
                            and (allow_2d or "2digit" not in cp.format_id)
                        ):
                            parsed = cp
                            break
            if (
                parsed
                and not parsed.ambiguous
                and (allow_2d or "2digit" not in parsed.format_id)
            ):
                if iso := normalize_iso_date(parsed.display, reference_year):
                    return iso
    return None


def _enrich_reporting_persons_with_ownership(
    reporting_persons: tuple[ReportingPersonCover, ...],
    narrative_items: tuple[NarrativeItem, ...],
    family: str,
) -> tuple[ReportingPersonCover, ...]:
    """Enriches reporting persons missing core ownership from narrative Items 4 or 5."""
    item_num = 4 if family == "13G" else 5
    item = next((it for it in narrative_items if it.number == item_num), None)
    ownership_map: dict[str, NarrativeField] = {}
    if item and item.parsed_fields:
        ownership_map.update({f.tag: f for f in item.parsed_fields if f.value})

    if family == "13G":
        item5 = next((it for it in narrative_items if it.number == 5), None)
        if item5 and item5.parsed_fields:
            for f in item5.parsed_fields:
                if f.tag and f.value and f.tag not in ownership_map:
                    ownership_map[f.tag] = f

    item3 = next((it for it in narrative_items if it.number == 3), None)
    if item3 and item3.parsed_fields:
        for f in item3.parsed_fields:
            if f.tag and f.value:
                ownership_map[f.tag] = f

    if not ownership_map and not any(
        rp.first_item("percentOfClass") or rp.first_item("aggregateAmountOwned")
        for rp in reporting_persons
    ):
        return reporting_persons

    slot_map = (
        dict(REPORTING_PERSON_SLOT_NUMBERS_13G)
        if family == "13G"
        else dict(REPORTING_PERSON_SLOT_NUMBERS_13D)
    )

    target_idx = None
    for idx, rp in enumerate(reporting_persons):
        agg = rp.first_item("aggregateAmountOwned")
        pct = rp.first_item("percentOfClass")
        agg_val = agg.value if agg else None
        pct_val = pct.value if pct else None
        agg_valid = (
            normalize_schema_number(
                agg_val,
                integer=True,
                strip_units=True,
                strip_footnotes=True,
                extract_leading_number=True,
            )
            is not None
        )
        pct_valid = (
            normalize_schema_number(
                pct_val,
                integer=False,
                strip_percent=True,
                strip_footnotes=True,
                extract_leading_number=True,
            )
            is not None
        )
        if not (agg_valid and pct_valid):
            target_idx = idx
            break

    if target_idx is None:
        if reporting_persons:
            p0 = reporting_persons[0]
            if any(
                tag in ownership_map and not p0.first_item(tag)
                for tag in ("typeOfReportingPerson", "fundType")
            ):
                target_idx = 0
            else:
                return reporting_persons
        else:
            return reporting_persons

    target_person = reporting_persons[target_idx]
    new_items: list[CoverItemEvidence] = []
    handled_tags: set[str] = set()

    for ev in target_person.items:
        tag = ev.tag
        if tag in ownership_map:
            handled_tags.add(tag)
            if tag in {"typeOfReportingPerson", "fundType"}:
                curr_valid = bool(ev.value and ev.value.strip())
            else:
                is_int = tag != "percentOfClass"
                curr_valid = (
                    normalize_schema_number(
                        ev.value,
                        integer=is_int,
                        strip_units=is_int,
                        strip_percent=not is_int,
                        strip_footnotes=True,
                        extract_leading_number=True,
                    )
                    is not None
                )
            if not curr_valid:
                narrative_f = ownership_map[tag]
                if tag in {"typeOfReportingPerson", "fundType"}:
                    narrative_valid = bool(
                        narrative_f.value and narrative_f.value.strip()
                    )
                else:
                    narrative_valid = (
                        normalize_schema_number(
                            narrative_f.value,
                            integer=is_int,
                            strip_units=is_int,
                            strip_percent=not is_int,
                            strip_footnotes=True,
                            extract_leading_number=True,
                        )
                        is not None
                    )
                if narrative_valid:
                    ev = replace(
                        ev,
                        value=narrative_f.value,
                        source_text=narrative_f.source_text,
                        state=EvidenceState.VALUE,
                        start_offset=narrative_f.start_offset,
                        end_offset=narrative_f.end_offset,
                    )
        new_items.append(ev)

    for tag, narrative_f in ownership_map.items():
        if tag not in handled_tags and tag in slot_map:
            if tag in {"typeOfReportingPerson", "fundType"}:
                narrative_valid = bool(narrative_f.value and narrative_f.value.strip())
            else:
                is_int = tag != "percentOfClass"
                narrative_valid = (
                    normalize_schema_number(
                        narrative_f.value,
                        integer=is_int,
                        strip_units=is_int,
                        strip_percent=not is_int,
                        strip_footnotes=True,
                        extract_leading_number=True,
                    )
                    is not None
                )
            if not narrative_valid:
                continue
            slot_num = slot_map[tag]
            new_items.append(
                CoverItemEvidence(
                    number=slot_num,
                    source_text=narrative_f.source_text,
                    value=narrative_f.value,
                    state=EvidenceState.VALUE,
                    tag=tag,
                    start_offset=narrative_f.start_offset,
                    end_offset=narrative_f.end_offset,
                )
            )

    enriched_person = replace(target_person, items=tuple(new_items))
    updated_rps = list(reporting_persons)
    updated_rps[target_idx] = enriched_person

    for idx, rp in enumerate(updated_rps):
        agg = rp.first_item("aggregateAmountOwned")
        pct = rp.first_item("percentOfClass")
        agg_v = (
            normalize_schema_number(
                agg.value if agg else None,
                integer=True,
                strip_units=True,
                strip_footnotes=True,
                extract_leading_number=True,
            )
            if agg
            else None
        )
        pct_v = (
            normalize_schema_number(
                pct.value if pct else None,
                integer=False,
                strip_percent=True,
                strip_footnotes=True,
                extract_leading_number=True,
            )
            if pct
            else None
        )
        if pct_v == "0" and agg_v is None:
            ev_zero = CoverItemEvidence(
                number=slot_map.get(
                    "aggregateAmountOwned", 9 if family == "13G" else 11
                ),
                source_text=pct.source_text if pct else "0",
                value="0",
                state=EvidenceState.VALUE,
                tag="aggregateAmountOwned",
                start_offset=pct.start_offset if pct else 0,
                end_offset=pct.end_offset if pct else 0,
            )
            new_list = list(rp.items)
            if agg:
                new_list[new_list.index(agg)] = ev_zero
            else:
                new_list.append(ev_zero)
            updated_rps[idx] = replace(rp, items=tuple(new_list))
        elif agg_v == "0" and pct_v is None:
            ev_zero = CoverItemEvidence(
                number=slot_map.get("percentOfClass", 11 if family == "13G" else 13),
                source_text=agg.source_text if agg else "0",
                value="0",
                state=EvidenceState.VALUE,
                tag="percentOfClass",
                start_offset=agg.start_offset if agg else 0,
                end_offset=agg.end_offset if agg else 0,
            )
            new_list = list(rp.items)
            if pct:
                new_list[new_list.index(pct)] = ev_zero
            else:
                new_list.append(ev_zero)
            updated_rps[idx] = replace(rp, items=tuple(new_list))
    return tuple(updated_rps)


def parse_beneficial_ownership_document(
    result: NormalizationResult,
    *,
    form: str | None = None,
    reference_year: int | None = None,
) -> BeneficialOwnershipDocument:
    """Parses a normalized beneficial ownership result into a document model."""
    lines_keep = result.text.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in lines_keep]
    line_offsets = [0]
    for line in lines_keep:
        line_offsets.append(line_offsets[-1] + len(line))
    normalized_form = (form or "SC 13D").strip().upper()
    is_13g = "13G" in normalized_form
    family = "13G" if is_13g else "13D"
    is_amendment = normalized_form.endswith("/A")
    if is_13g:
        submission_type = "SCHEDULE 13G/A" if is_amendment else "SCHEDULE 13G"
    else:
        submission_type = "SCHEDULE 13D/A" if is_amendment else "SCHEDULE 13D"

    sections = _body_sections(result, family, line_offsets)
    if sections and sections.sections:
        cover_end = sections.sections[0].start_line
    elif result.cover_boundary and result.cover_boundary.end_line is not None:
        cover_end = result.cover_boundary.end_line
    elif result.sections and result.sections.sections:
        cover_end = result.sections.sections[0].start_line
    else:
        cover_end = len(lines)
    cover_text = "\n".join(lines[:cover_end])

    first_match = _RE_FIRST_PERSON.search(cover_text)
    header_text = cover_text[: first_match.start()] if first_match else cover_text

    issuer = extract_issuer_metadata(header_text)
    reference_year = reference_year or reported_year((issuer.event_date,))
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
        lookback_line = signature_start_line
        for b in range(
            signature_start_line - 1,
            max(cover_end, signature_start_line - 8),
            -1,
        ):
            if (
                _RE_SIGNATURE_HEADER.search(lines[b])
                or _RE_SIGNATURE_DATE_LINE.search(lines[b])
                or parse_date(lines[b].strip()) is not None
            ):
                lookback_line = b
        signature_start_offset = line_offsets[lookback_line]
        sig_suffix = result.text[signature_start_offset:]
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
            if header_offset is None:
                lookback_offset = line_start
                pre_lines = result.text[:line_start].splitlines(keepends=True)
                for b in range(len(pre_lines) - 1, max(0, len(pre_lines) - 8), -1):
                    bl = pre_lines[b].strip()
                    if _RE_SIGNATURE_DATE_LINE.search(bl) or parse_date(bl) is not None:
                        lookback_offset = sum(len(l) for l in pre_lines[:b])
                signature_start_offset = lookback_offset
            else:
                signature_start_offset = header_offset
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
        if not signature_headers and (
            not result.cover_boundary or result.cover_boundary.approximate
        ):
            signature_headers = list(_RE_SIGNATURE_HEADER.finditer(result.text))
        best_cand = None
        for heading in reversed(signature_headers):
            candidate = result.text[heading.start() :]
            sb = _signature_block(candidate)
            if sb is None:
                continue
            if best_cand is None:
                best_cand = (heading, candidate)
            if any(s.date for s in sb.signatories):
                best_cand = (heading, candidate)
        if best_cand is not None:
            heading, sig_suffix = best_cand
            signature_start_offset = heading.start()
            signature_start_line = result.text.count("\n", 0, heading.start())

    narrative_items: list[NarrativeItem] = []
    if sections and sections.sections:
        for s in sections.sections:
            num_match = _RE_ITEM_NUM.search(s.item_identifier)
            if num_match:
                num = int(num_match.group(0))
                end_line = (s.end_line + 1) if s.end_line is not None else len(lines)
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
                                family=family,
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
    if signature_block is None and narrative_items:
        tail_candidate = narrative_items[-1].text[-500:]
        tail_sig = _signature_block(tail_candidate)
        if tail_sig is not None and tail_sig.signatories:
            signature_block = tail_sig
    signature_text = signature_block.raw_text if signature_block is not None else None

    if not issuer.issuer_name:
        item1 = next((item for item in narrative_items if item.number == 1), None)
        if item1 is not None:
            item1_name = None
            if item1.parsed_fields:
                item1_name = next(
                    (
                        f.value
                        for f in item1.parsed_fields
                        if f.tag == "issuerName" and f.value
                    ),
                    None,
                )
            if not item1_name and item1.text:
                first_line = item1.text.splitlines()[0].strip(" \t-_=</TABLE>")
                if first_line and is_valid_entity_name(first_line):
                    item1_name = first_line
            if item1_name:
                issuer = replace(issuer, issuer_name=item1_name)

    if not issuer.event_date and signature_block and signature_block.signatories:
        for sig in signature_block.signatories:
            if sig.date:
                p = parse_date(sig.date, reference_year=reference_year)
                if p is not None and not p.ambiguous:
                    issuer = replace(issuer, event_date=p.iso)
                    break

    if not reporting_persons:
        item2 = next((item for item in narrative_items if item.number == 2), None)
        if item2 is not None and item2.parsed_fields:
            item2_name = next(
                (
                    f.value
                    for f in item2.parsed_fields
                    if f.tag == "filingPersonName" and f.value
                ),
                None,
            )
            if item2_name:
                evidence = CoverItemEvidence(
                    number=1,
                    source_text=item2_name,
                    value=item2_name,
                    state=EvidenceState.VALUE,
                    tag="reportingPersonName",
                )
                reporting_persons = (
                    ReportingPersonCover(
                        items=(evidence,),
                        source_text=item2.text,
                    ),
                )
        elif signature_block and signature_block.signatories:
            first_sig = signature_block.signatories[0]
            if first_sig.name:
                evidence = CoverItemEvidence(
                    number=1,
                    source_text=first_sig.name,
                    value=first_sig.name,
                    state=EvidenceState.VALUE,
                    tag="reportingPersonName",
                )
                reporting_persons = (
                    ReportingPersonCover(
                        items=(evidence,),
                        source_text=first_sig.name,
                    ),
                )

    fixed_rps = []
    for rp in reporting_persons:
        item1 = rp.first_item("reportingPersonName") or rp.first_item(1)
        if (
            (item1 is None or not item1.value)
            and signature_block
            and signature_block.signatories
        ):
            first_sig = signature_block.signatories[0]
            if first_sig.name:
                evidence = CoverItemEvidence(
                    number=1,
                    source_text=first_sig.name,
                    value=first_sig.name,
                    state=EvidenceState.VALUE,
                    tag="reportingPersonName",
                )
                fixed_items = (evidence,) + tuple(
                    it
                    for it in rp.items
                    if it.number != 1 and it.tag != "reportingPersonName"
                )
                rp = replace(rp, items=fixed_items)
        fixed_rps.append(rp)
    reporting_persons = tuple(fixed_rps)

    reporting_persons = _enrich_reporting_persons_with_ownership(
        reporting_persons, tuple(narrative_items), family
    )

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
    event_date = (
        normalize_iso_date(document.issuer.event_date, reference_year)
        or document.issuer.event_date
    )
    if event_date is None and signature_block and signature_block.signatories:
        sig_date = next((s.date for s in signature_block.signatories if s.date), None)
        if sig_date:
            event_date = normalize_iso_date(sig_date, reference_year) or sig_date
    if event_date is None:
        event_date = _find_narrative_event_date(lines[cover_end:], reference_year)
    issuer = replace(document.issuer, event_date=event_date)
    signature_block = document.signature_block
    if signature_block is not None:
        signature_block = replace(
            signature_block,
            signatories=tuple(
                replace(
                    signatory,
                    date=normalize_iso_date(signatory.date, reference_year)
                    or signatory.date,
                )
                for signatory in signature_block.signatories
            ),
        )
    return replace(
        document,
        issuer=issuer,
        signature_block=signature_block,
        residual_text="\n\n".join(section.text for section in unparsed_sections),
        field_extractions=field_extractions,
        unparsed_sections=unparsed_sections,
    )


__all__ = ["parse_beneficial_ownership_document"]
