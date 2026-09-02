"""Cover page layout, address, state/EIN, and checkbox table templates."""

from __future__ import annotations

import re

from defs.sec_forms.vocabulary import (
    ADDRESS_RE,
    CHECKBOX_GRID_RE,
    COMMISSION_FILE_RE,
    COMMISSION_FILE_VALUE_RE,
    EIN_VALUE_RE,
    IRS_EIN_RE,
    REGISTRANT_NAME_RE,
    STATE_INCORPORATION_RE,
    TELEPHONE_RE,
    ZIP_RE,
    ZIP_VALUE_RE,
    is_state_value,
)
from defs.text import (
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
    normalize_checkbox_tokens,
)


def single_row_horizontal_template(source_grid: list[list[str]]) -> str | None:
    """Join single-row multi-cell layout blocks horizontally onto a single line."""
    if len(source_grid) != 1:
        return None
    row = [c.strip() for c in source_grid[0] if c.strip()]
    if len(row) <= 1:
        return None
    return " ".join(row)


def cover_layout_template(source_grid: list[list[str]]) -> str | None:
    """Decompose and reorder cover address, state, EIN, and contact tables into clean prose blocks."""
    if len(source_grid) < 2:
        return None

    compact_grid = [[c.strip() for c in row if c.strip()] for row in source_grid]
    all_text = " ".join(c for r in compact_grid for c in r)
    is_cover = bool(
        (STATE_INCORPORATION_RE.search(all_text) or IRS_EIN_RE.search(all_text))
        or (ADDRESS_RE.search(all_text) or ZIP_RE.search(all_text))
        or (REGISTRANT_NAME_RE.search(all_text) and len(compact_grid) <= 3)
    )
    if not is_cover:
        return None

    state_val, state_label = None, None
    irs_val, irs_label = None, None
    name_val, name_label = None, None
    tel_val, tel_label = None, None
    file_val, file_label = None, None
    addr_parts: list[str] = []
    zip_val: str | None = None
    addr_label: str | None = None
    zip_label: str | None = None

    for row in compact_grid:
        if any(STATE_INCORPORATION_RE.search(c) for c in row) or any(
            IRS_EIN_RE.search(c) for c in row
        ):
            for c in row:
                if STATE_INCORPORATION_RE.search(c):
                    state_label = c
                elif IRS_EIN_RE.search(c):
                    irs_label = c
                elif COMMISSION_FILE_RE.search(c):
                    file_label = c
        elif any(ADDRESS_RE.search(c) for c in row) or any(
            ZIP_RE.search(c) for c in row
        ):
            for c in row:
                if ADDRESS_RE.search(c):
                    addr_label = c
                elif ZIP_RE.search(c):
                    zip_label = c
        elif any(REGISTRANT_NAME_RE.search(c) for c in row):
            for c in row:
                if REGISTRANT_NAME_RE.search(c):
                    name_label = c
        elif any(TELEPHONE_RE.search(c) for c in row):
            for c in row:
                if TELEPHONE_RE.search(c):
                    tel_label = c
        elif any(COMMISSION_FILE_RE.search(c) for c in row):
            for c in row:
                if COMMISSION_FILE_RE.search(c):
                    file_label = c
        else:
            if state_label is None and irs_label is None and addr_label is None:
                for c in row:
                    clean_c = c.strip()
                    if EIN_VALUE_RE.fullmatch(clean_c):
                        irs_val = clean_c
                    elif COMMISSION_FILE_VALUE_RE.fullmatch(clean_c) and not file_val:
                        file_val = clean_c
                    elif not state_val and is_state_value(clean_c):
                        state_val = clean_c
                    elif not name_val and len(row) == 1:
                        name_val = clean_c
                    elif not state_val and c == row[0]:
                        state_val = clean_c
                    elif not irs_val and c == row[-1]:
                        irs_val = clean_c
            else:
                for c in row:
                    clean_c = c.strip()
                    if ZIP_VALUE_RE.fullmatch(clean_c):
                        zip_val = clean_c
                    elif re.search(
                        r"(?:\(\d{3}\)|\b\d{3}[-.]?)\s*\d{3}[-.]?\d{4}\b", clean_c
                    ):
                        tel_val = clean_c
                    else:
                        addr_parts.append(clean_c)

    blocks: list[str] = []
    if name_val or name_label:
        blocks.append(
            f"{name_val}\n{name_label}"
            if name_label and name_val
            else (name_val or name_label or "")
        )
    if file_val or file_label:
        blocks.append(
            f"{file_val}\n{file_label}"
            if file_label and file_val
            else (file_val or file_label or "")
        )
    if state_val or state_label:
        blocks.append(
            f"{state_val}\n{state_label}"
            if state_label and state_val
            else (state_val or state_label or "")
        )
    if irs_val or irs_label:
        blocks.append(
            f"{irs_val}\n{irs_label}"
            if irs_label and irs_val
            else (irs_val or irs_label or "")
        )

    if addr_parts:
        clean_addr = ", ".join(p.rstrip(",") for p in addr_parts if p.strip())
        if zip_val and zip_val not in clean_addr:
            clean_addr = f"{clean_addr} {zip_val}"
        lbls = [l for l in (addr_label, zip_label) if l]
        lbl_line = " ".join(lbls) if lbls else ""
        blocks.append(f"{clean_addr}\n{lbl_line}" if lbl_line else clean_addr)

    if tel_val or tel_label:
        blocks.append(
            f"{tel_val}\n{tel_label}"
            if tel_label and tel_val
            else (tel_val or tel_label or "")
        )

    return "\n\n".join(b for b in blocks if b.strip()) if blocks else None


def checkbox_grid_template(source_grid: list[list[str]]) -> str | None:
    """Format checkbox grid tables (e.g. filer category or yes/no questions) into clean prose lines."""
    if not source_grid:
        return None

    all_text = " ".join(c for r in source_grid for c in r)
    has_check_markers = bool(
        RE_RAW_CHECKED.search(all_text) or RE_RAW_UNCHECKED.search(all_text)
    )
    if not has_check_markers:
        return None

    if not CHECKBOX_GRID_RE.search(all_text):
        return None

    rendered_rows: list[str] = []
    for row in source_grid:
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue
        row_str = " ".join(cells)
        row_str = normalize_checkbox_tokens(row_str)
        rendered_rows.append(row_str)

    return "\n".join(rendered_rows) if rendered_rows else None


__all__ = [
    "checkbox_grid_template",
    "cover_layout_template",
    "single_row_horizontal_template",
]
