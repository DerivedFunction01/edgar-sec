"""Signature block parsing for beneficial ownership filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.signatures import Signatory, SignatureBlock
from edgar_sec.engine.document.page_markers.signatures import (
    find_signature_regions,
)
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_CONFORMED_SIGNER_NAME,
    RE_INLINE_SIGNATURE_DELIM,
    RE_SIGNATURE_ALONE,
    RE_SIGNATURE_DASHES,
    RE_SIGNATURE_DATE_LINE,
    RE_SIGNATURE_HTML_TAG,
    RE_SIGNATURE_INLINE_DATE,
    RE_SIGNATURE_LABEL,
    RE_SIGNATURE_TABLE_TAIL,
)
from edgar_sec.engine.forms.common.signatures import (
    OFFICER_TITLE_RE,
    clean_signature_name,
    extract_signature_block as parse_signature_block,
    extract_signature_candidate,
    is_valid_signature_name,
)
from edgar_sec.foundation.text.dates import parse_date


def extract_beneficial_ownership_signature_block(
    suffix: str,
) -> SignatureBlock | None:
    """Extract signatories and conformed date from signature region."""
    signatories: list[Signatory] = []
    matches = list(RE_CONFORMED_SIGNER_NAME.finditer(suffix))
    matched_markers = set()
    for index, match in enumerate(matches):
        marker = CONFORMED_SIGNATURE_RE.search(suffix, match.start(), match.end())
        line_start = suffix.rfind("\n", 0, match.start()) + 1
        candidate_text = RE_SIGNATURE_TABLE_TAIL.sub("", match.group(0))
        candidate_text = RE_SIGNATURE_DASHES.sub("", candidate_text)
        candidate, date = extract_signature_candidate(candidate_text)
        date = (
            extract_signature_candidate(suffix[line_start : match.start()])[1] or date
        )
        if date is None:
            preceding_text = suffix[:line_start].splitlines()
            for prev_line in reversed(
                preceding_text[max(0, len(preceding_text) - 10) :]
            ):
                prev_s = prev_line.strip(" \t*_=-")
                if not prev_s:
                    continue
                cand_d = extract_signature_candidate(prev_s)[1]
                if cand_d:
                    date = cand_d
                    break
                p = parse_date(prev_s)
                if p and not p.ambiguous:
                    date = prev_s
                    break
        if candidate:
            if marker is not None:
                matched_markers.add(marker.start())
            candidate = clean_signature_name(candidate)
            signatories.append(Signatory(name=candidate, date=date))
    for marker in CONFORMED_SIGNATURE_RE.finditer(suffix):
        if marker.start() in matched_markers:
            continue
        line_start = suffix.rfind("\n", 0, marker.start()) + 1
        line_end = suffix.find("\n", marker.end())
        if line_end < 0:
            line_end = len(suffix)
        line = suffix[line_start:line_end]
        tail = RE_SIGNATURE_TABLE_TAIL.sub("", suffix[marker.end() : line_end])
        tail = RE_SIGNATURE_DASHES.sub("", tail)
        tail = RE_SIGNATURE_HTML_TAG.sub(" ", tail)
        name = clean_signature_name(tail)
        if not is_valid_signature_name(name):
            words = tail.split()
            half = len(words) // 2
            if len(words) >= 2 and words[:half] == words[half:]:
                cand = " ".join(words[:half])
                if is_valid_signature_name(clean_signature_name(cand)):
                    name = clean_signature_name(cand)
        if not is_valid_signature_name(name):
            candidate, _ = extract_signature_candidate(line)
            name = clean_signature_name(candidate) if candidate else ""
        if not name or not is_valid_signature_name(name):
            continue
        _, date = extract_signature_candidate(suffix[line_start : marker.start()])
        if date is None:
            _, date = extract_signature_candidate(line)
        if date is None:
            if m_date := RE_SIGNATURE_INLINE_DATE.search(line):
                cand_d = m_date.group(1).strip()
                if (p := parse_date(cand_d)) and not p.ambiguous:
                    date = cand_d
        if date is None:
            preceding = suffix[:line_start].splitlines()
            for prev_line in reversed(preceding[max(0, len(preceding) - 10) :]):
                prev_cand = prev_line.strip(" \t*_=-")
                if not prev_cand:
                    continue
                cand_d = extract_signature_candidate(prev_cand)[1]
                if cand_d:
                    date = cand_d
                    break
                p = parse_date(prev_cand)
                if p and not p.ambiguous:
                    date = prev_cand
                    break
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
            stripped_line = line.strip()
            p_line = parse_date(stripped_line)
            is_date_line = (
                p_line is not None
                and not p_line.ambiguous
                and len(stripped_line) <= 50
                and not CONFORMED_SIGNATURE_RE.search(stripped_line)
            )
            if (
                not RE_SIGNATURE_DATE_LINE.match(line)
                and not RE_SIGNATURE_ALONE.match(stripped_line)
                and not is_date_line
            ):
                continue
            date = stripped_line if is_date_line else None
            if not date:
                _, date = extract_signature_candidate(line)
            if not date:
                for adj_idx in (
                    line_index + 1,
                    line_index + 2,
                    line_index - 1,
                    line_index - 2,
                ):
                    if 0 <= adj_idx < len(sig_lines):
                        cand_adj = sig_lines[adj_idx].strip(" \t*_=-")
                        if cand_adj and (p := parse_date(cand_adj)) and not p.ambiguous:
                            cand_d = extract_signature_candidate(cand_adj)[1]
                            date = cand_d or cand_adj
                            break
            name_candidate = None
            for name_line in sig_lines[
                line_index + 1 : min(len(sig_lines), line_index + 10)
            ]:
                candidate = name_line.strip(" \t*_=-")
                p_cand = parse_date(candidate)
                if (
                    not candidate
                    or candidate.startswith("<")
                    or RE_SIGNATURE_LABEL.match(candidate)
                    or RE_SIGNATURE_DATE_LINE.match(candidate)
                    or (p_cand is not None and len(p_cand.source) >= len(candidate) - 4)
                ):
                    continue
                if m_title := OFFICER_TITLE_RE.search(candidate):
                    prefix = candidate[: m_title.start()].strip(" \t*_=-,")
                    if m_sig := RE_INLINE_SIGNATURE_DELIM.search(prefix):
                        prefix = prefix[m_sig.end() :].strip(" \t*_=-,")
                    cleaned_name = clean_signature_name(prefix)
                    if prefix and is_valid_signature_name(prefix):
                        if not any(s.name == cleaned_name for s in signatories):
                            if not date:
                                before_sig = candidate[: m_title.start()]
                                if p_before := parse_date(before_sig):
                                    date = p_before.source
                            signatories.append(Signatory(name=cleaned_name, date=date))
                        break
                    for prev_line in reversed(
                        sig_lines[max(0, line_index - 4) : line_index]
                    ):
                        prev_cand = prev_line.strip(" \t*_=-")
                        if (
                            prev_cand
                            and is_valid_signature_name(prev_cand)
                            and not OFFICER_TITLE_RE.search(prev_cand)
                            and parse_date(prev_cand) is None
                        ):
                            name_candidate = clean_signature_name(prev_cand)
                            break
                    if name_candidate and not any(
                        s.name == name_candidate for s in signatories
                    ):
                        signatories.append(Signatory(name=name_candidate, date=date))
                        break
                elif is_valid_signature_name(candidate):
                    cleaned_cand = clean_signature_name(candidate)
                    if not any(s.name == cleaned_cand for s in signatories):
                        signatories.append(Signatory(name=cleaned_cand, date=date))
                    break
            if not signatories and date:
                for prev_line in reversed(
                    sig_lines[max(0, line_index - 4) : line_index]
                ):
                    prev_cand = prev_line.strip(" \t*_=-")
                    cand_name = clean_signature_name(prev_cand) if prev_cand else ""
                    if (
                        cand_name
                        and is_valid_signature_name(cand_name)
                        and not OFFICER_TITLE_RE.search(cand_name)
                        and not any(s.name == cand_name for s in signatories)
                    ):
                        signatories.append(Signatory(name=cand_name, date=date))
                        break
    if not signatories:
        return None
    return SignatureBlock(
        signatories=tuple(signatories),
        raw_text=suffix.strip(),
    )
