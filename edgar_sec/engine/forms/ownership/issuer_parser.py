from __future__ import annotations

import re

from edgar_sec.domain.forms.common.entities import CANONICAL_EXCHANGE_NAMES
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.domain.forms.families.ownership.models import Issuer
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS, NAME_STOPWORDS
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
_SYMBOL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,5}")
_DELIMITER_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,7}")
_QUOTED_TOKEN_RE = re.compile(r"[\"“”'‘’]([A-Za-z0-9.\-]{1,6})[\"“”'‘’]")
_LABELED_SYMBOL_RE = re.compile(
    "(?:"
    + build_alternation(("ticker", "trading symbol", "symbol"))
    + r")\s*:\s*([A-Za-z][A-Za-z0-9.\-]{0,5})\s*$",
    flags=re.IGNORECASE,
)
_LOWER_WORD_RE = re.compile(r"[a-z]+")
_LEADING_DOTTED_SYMBOL_RE = re.compile(r"^([A-Za-z]{1,5}(?:\.[A-Za-z]{1,3})+)\s+(.+)$")
_TIGHT_DASH_TAIL_RE = re.compile(r"^(.{3,}?[A-Za-z])\-([A-Z]{1,6})$")
_TRAILING_GROUP_RE = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\})\s*$")
_SYMBOL_STOPWORDS = (
    NAME_STOPWORDS
    | frozenset(name.lower() for name in CANONICAL_EXCHANGE_NAMES)
    | {"no"}
)
_NAME_TAIL_STOPWORDS = LEGAL_FORMS | frozenset(
    {"partners", "capital", "bank", "symbol", "ticker"}
)


def _valid_symbol_token(token: str) -> bool:
    if not _SYMBOL_TOKEN_RE.fullmatch(token):
        return False
    lowered = token.lower()
    return (
        lowered not in LEGAL_FORMS
        and lowered not in _SYMBOL_STOPWORDS
        and any(char.isalpha() for char in token)
    )


def _group_symbol(content: str) -> str | None:
    direct = content.strip().strip("\"“”'‘’ ")
    if ":" in direct:
        direct = direct.rsplit(":", 1)[1].strip()
    if len(direct) >= 2 and _valid_symbol_token(direct):
        return direct
    for match in _QUOTED_TOKEN_RE.finditer(content):
        if _valid_symbol_token(match.group(1)):
            return match.group(1)
    return None


def _midline_group_symbol(text: str) -> tuple[str, str] | None:
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            end = -1
            for index in range(start, len(text)):
                if text[index] == opener:
                    depth += 1
                elif text[index] == closer:
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            if end == -1:
                break
            token = _group_symbol(text[start + 1 : end])
            if token is not None:
                return token, (text[:start] + text[end + 1 :]).strip(" ,-")
            start = text.find(opener, end + 1)
    return None


def _strip_trailing_groups(text: str) -> str:
    while True:
        stripped = _TRAILING_GROUP_RE.sub("", text)
        if stripped == text:
            return text
        text = stripped


def _is_label_only(line: str) -> bool:
    lowered = line.lower()
    if not any(term in lowered for term in ISSUER_LABEL_TERMS):
        return False
    residue = lowered
    for term in ISSUER_LABEL_TERMS:
        residue = residue.replace(term, " ")
    words = [
        w for w in _LOWER_WORD_RE.findall(residue) if w not in ("and", "or", "the")
    ]
    return sum(len(word) for word in words) < 3


def parse_issuer(cell_text: str) -> Issuer:
    lines = [
        collapsed
        for line in cell_text.splitlines()
        if (collapsed := line.replace("\t", " ").strip())
    ]
    for line in lines:
        combined = _NAME_SYMBOL_LINE_RE.search(line)
        if combined:
            irs_match = IRS_RE.search(cell_text)
            return Issuer(
                name=combined.group(1).strip(" ,-") or None,
                trading_symbol=combined.group(2).upper(),
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
                if (
                    tail
                    and any(char.isalnum() for char in tail)
                    and tail.lower() not in ("or", "and", "or trading symbol")
                ):
                    candidate = tail
                    break
            match = ISSUER_TAIL_RE.search(line)
            if match:
                tail = match.group(1).strip()
                if (
                    tail
                    and any(char.isalnum() for char in tail)
                    and not any(
                        term in tail.lower()
                        for term in ("trading symbol", "and address")
                    )
                ):
                    candidate = tail
                    break
    if not candidate and last_label_index != -1 and last_label_index + 1 < len(lines):
        candidate = lines[last_label_index + 1]
    if not candidate and lines:
        candidate = lines[-1]
    if candidate and _is_label_only(candidate):
        following = lines[last_label_index + 1 :] if last_label_index != -1 else []
        candidate = next(
            (
                line
                for line in following
                if not _is_label_only(line)
                and sum(char.isalpha() for char in line) >= 3
            ),
            "",
        )

    name: str | None = None
    ticker: str | None = None
    if candidate:
        match = TICKER_PAREN_RE.search(candidate)
        if match:
            name = candidate[: match.start()].rstrip(" ,-")
            ticker = match.group(1).strip("()\"“”',.-")
            if " and " in ticker:
                ticker = ticker.split(" and ")[0].strip()
        if not ticker:
            grouped = _midline_group_symbol(candidate)
            if grouped:
                ticker, remainder = grouped
                name = _strip_trailing_groups(remainder).rstrip(" ,-") or None
        if not ticker:
            match = _LEADING_DOTTED_SYMBOL_RE.match(candidate)
            if match and " " in match.group(2):
                ticker = match.group(1)
                name = match.group(2).rstrip(" ,-")
        if not ticker:
            match = TICKER_DASH_RE.search(candidate)
            if match:
                name = candidate[: match.start()].rstrip(" ,-")
                ticker = match.group(1).strip("()\"“”',.-")
            else:
                match = _TIGHT_DASH_TAIL_RE.match(candidate)
                if match and " " in match.group(1):
                    name = match.group(1).rstrip(" ,-")
                    ticker = match.group(2)
        if not ticker and " " in candidate:
            parts = candidate.rsplit(" ", 1)
            last = parts[1].strip("()\"“”',.-")
            head = _TRAILING_AND_OR_RE.sub("", parts[0]).rstrip(" ,-")
            head_last = head.rsplit(" ", 1)[-1].strip(".,").lower() if head else ""
            head_ends_legal = head_last in LEGAL_FORMS
            upper_tail = last.isupper() and (
                last.lower() not in LEGAL_FORMS or head_ends_legal
            )
            lower_tail = (
                last.islower()
                and head_ends_legal
                and last.lower() not in _NAME_TAIL_STOPWORDS
            )
            if (
                _SYMBOL_TOKEN_RE.fullmatch(last)
                and any(char.isalpha() for char in last)
                and (upper_tail or lower_tail)
            ):
                name = head
                ticker = last
            else:
                name = candidate.rstrip(" ,-")
        if not ticker and " " not in candidate:
            name = candidate.rstrip(" ,-")

        if not ticker:
            for delimiter in ("/", " - ", " — ", " and ", " or "):
                if delimiter not in candidate:
                    continue
                parts = candidate.split(delimiter, 1)
                left = parts[0].strip("()\"“”',.- ")
                right = parts[1].strip("()\"“”',.- ")
                if (
                    _DELIMITER_TOKEN_RE.fullmatch(right)
                    and right.replace(".", "").isupper()
                    and right.lower() not in LEGAL_FORMS
                    and right.lower() not in _SYMBOL_STOPWORDS
                ):
                    name = parts[0].rstrip(" ,-")
                    ticker = right
                    break
                if (
                    _DELIMITER_TOKEN_RE.fullmatch(left)
                    and left.replace(".", "").isupper()
                    and left.lower() not in LEGAL_FORMS
                    and left.lower() not in _SYMBOL_STOPWORDS
                ):
                    name = parts[1].rstrip(" ,-")
                    ticker = left
                    break

        if not ticker:
            for line in lines:
                if line == candidate:
                    continue
                labeled = _LABELED_SYMBOL_RE.search(line)
                if labeled and _valid_symbol_token(labeled.group(1)):
                    ticker = labeled.group(1)
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
                if _valid_symbol_token(stripped) and (
                    stripped.isupper() or stripped.islower()
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
            if cleaned and sum(char.isalpha() for char in cleaned) >= 3:
                name = cleaned
                break

    if (
        not ticker
        and name
        and candidate
        and name == candidate.rstrip(" ,-")
        and _valid_symbol_token(name)
        and name.isupper()
    ):
        ticker, name = name, None

    if name:
        name = STRIP_BOX_NUM_RE.sub("", name).strip()
    irs_match = IRS_RE.search(cell_text)
    return Issuer(
        name=name or None,
        trading_symbol=ticker.upper() if ticker else None,
        irs_number=irs_match.group(1) if irs_match else None,
    )


__all__ = ["parse_issuer"]
