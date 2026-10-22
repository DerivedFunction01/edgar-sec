from __future__ import annotations

import re

from edgar_sec.domain.forms.families.ownership.models import Issuer
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.engine.forms.common.entities import (
    IRS_RE,
    ISSUER_LABEL_TERMS,
    ISSUER_TAIL_RE,
    STRIP_BOX_NUM_RE,
    SYMBOL_TAIL_RE,
    TICKER_DASH_RE,
    TICKER_PAREN_RE,
)

_TRAILING_AND_OR_RE = re.compile(r"\s+(?:and|or)\s*$", flags=re.IGNORECASE)
_NAME_SYMBOL_LINE_RE = re.compile(
    r"name:\s*(.+?)\s+trading symbol:?\s*([A-Za-z0-9][A-Za-z0-9.\-]*)",
    flags=re.IGNORECASE,
)


def parse_issuer(cell_text: str) -> Issuer:
    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]
    for line in lines:
        combined = _NAME_SYMBOL_LINE_RE.search(line)
        if combined:
            irs_match = IRS_RE.search(cell_text)
            return Issuer(
                name=combined.group(1).strip(" ,-") or None,
                trading_symbol=combined.group(2),
                irs_number=irs_match.group(1) if irs_match else None,
            )
    candidate = ""
    last_label_index = -1
    for index, line in enumerate(lines):
        if any(term in line.lower() for term in ISSUER_LABEL_TERMS):
            last_label_index = index
            match = SYMBOL_TAIL_RE.search(line)
            if match:
                tail = match.group(1).strip()
                if tail and tail.lower() not in ("or", "and", "or trading symbol"):
                    candidate = tail
                    break
            match = ISSUER_TAIL_RE.search(line)
            if match:
                tail = match.group(1).strip()
                if tail and not any(
                    term in tail.lower() for term in ("trading symbol", "and address")
                ):
                    candidate = tail
                    break
    if not candidate and last_label_index != -1 and last_label_index + 1 < len(lines):
        candidate = lines[last_label_index + 1]
    if not candidate and lines:
        candidate = lines[-1]

    name: str | None = None
    ticker: str | None = None
    if candidate:
        match = TICKER_PAREN_RE.search(candidate)
        if match:
            name = candidate[: match.start()].rstrip(" ,-")
            ticker = match.group(1).strip("()\"“”',.-")
            if " and " in ticker:
                ticker = ticker.split(" and ")[0].strip()
        else:
            match = TICKER_DASH_RE.search(candidate)
            if match:
                name = candidate[: match.start()].rstrip(" ,-")
                ticker = match.group(1).strip("()\"“”',.-")
            elif " " in candidate:
                parts = candidate.rsplit(" ", 1)
                last = parts[1].strip("()\"“”',.-")
                if (
                    1 <= len(last) <= 6
                    and last.isupper()
                    and last.lower() not in LEGAL_FORMS
                ):
                    name = _TRAILING_AND_OR_RE.sub("", parts[0]).rstrip(" ,-")
                    ticker = last
                else:
                    name = candidate.rstrip(" ,-")
            else:
                name = candidate.rstrip(" ,-")

        if not ticker:
            for delimiter in ("/", " - ", " — ", " and ", " or "):
                if delimiter not in candidate:
                    continue
                parts = candidate.split(delimiter, 1)
                left = parts[0].strip("()\"“”',.- ")
                right = parts[1].strip("()\"“”',.- ")
                if (
                    1 <= len(right) <= 8
                    and right.replace(".", "").isupper()
                    and right.lower() not in LEGAL_FORMS
                ):
                    name = parts[0].rstrip(" ,-")
                    ticker = right
                    break
                if (
                    1 <= len(left) <= 8
                    and left.replace(".", "").isupper()
                    and left.lower() not in LEGAL_FORMS
                ):
                    name = parts[1].rstrip(" ,-")
                    ticker = left
                    break

        if not ticker:
            for line in lines:
                if line == candidate or any(
                    term in line.lower()
                    for term in ("issuer", "trading", "ticker", "i.r.s.")
                ):
                    continue
                match = TICKER_PAREN_RE.search(line)
                if match:
                    ticker = match.group(1).strip("()\"“”',.-")
                    if " and " in ticker:
                        ticker = ticker.split(" and ")[0].strip()
                    break
                stripped = line.strip("()\"“”',.-")
                if (
                    1 <= len(stripped) <= 6
                    and stripped.isupper()
                    and stripped.lower() not in LEGAL_FORMS
                ):
                    ticker = stripped
                    break

    if not name or name in ("=", "-"):
        for line in lines:
            if line == candidate or any(
                term in line.lower()
                for term in (
                    "issuer name",
                    "trading symbol",
                    "ticker symbol",
                    "and ticker",
                    "or trading",
                    "(last)",
                    "(street)",
                )
            ):
                continue
            cleaned = STRIP_BOX_NUM_RE.sub("", line).strip(" ,=-")
            if cleaned and any(char.isalpha() for char in cleaned):
                name = cleaned
                break

    if name:
        name = STRIP_BOX_NUM_RE.sub("", name).strip()
    irs_match = IRS_RE.search(cell_text)
    return Issuer(
        name=name or None,
        trading_symbol=ticker or None,
        irs_number=irs_match.group(1) if irs_match else None,
    )


__all__ = ["parse_issuer"]
