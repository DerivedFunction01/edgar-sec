"""Scored name matching over the catalog's name data.

Candidates score on normalized token sets with corporate suffixes
folded away; the resolver consumes the ranked list.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

__all__ = ["score_name_candidates"]


_EXACT_SCORE = 0.98
_SUFFIX_TOKENS = frozenset(
    {
        "inc",
        "corp",
        "corporation",
        "company",
        "co",
        "ltd",
        "llc",
        "plc",
        "lp",
        "sa",
        "nv",
        "ag",
        "holdings",
        "holding",
        "group",
        "the",
        "and",
        "of",
    }
)


def _normalize(text: str) -> tuple[str, frozenset[str]]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.casefold())
    words = cleaned.split()
    tokens = frozenset(word for word in words if word not in _SUFFIX_TOKENS)
    return " ".join(words), tokens


def _score(
    query_norm: str,
    query_tokens: frozenset,
    entry_norm: str,
    entry_tokens: frozenset,
) -> float:
    if query_norm and query_norm == entry_norm:
        return 1.0
    if query_tokens and query_tokens == entry_tokens:
        return _EXACT_SCORE
    score = 0.0
    if query_tokens and entry_tokens:
        common = len(query_tokens & entry_tokens)
        if common:
            score = max(score, common / len(query_tokens | entry_tokens))
            if query_tokens <= entry_tokens or entry_tokens <= query_tokens:
                ratio = min(len(query_tokens), len(entry_tokens)) / max(
                    len(query_tokens), len(entry_tokens)
                )
                score = max(score, 0.8 + 0.15 * ratio)
    if query_norm and entry_norm:
        if query_norm in entry_norm or entry_norm in query_norm:
            score = max(score, 0.85)
        ratio = SequenceMatcher(None, query_norm, entry_norm).ratio()
        score = max(score, ratio * 0.92)
    return round(min(score, 0.97), 4)


def _entry_parts(entry: Any) -> tuple[str, str, list[str]]:
    if isinstance(entry, dict):
        raw_name = entry.get("name", "")
        raw_cik = entry.get("cik", "")
        raw_tickers = entry.get("tickers", ()) or ()
    else:
        raw_name = getattr(entry, "name", "")
        raw_cik = getattr(entry, "cik", "")
        raw_tickers = getattr(entry, "tickers", ()) or ()
    cik = getattr(raw_cik, "value", raw_cik)
    return str(raw_name), str(cik), [str(t) for t in raw_tickers]


def _entry_dict(entry: Any) -> dict[str, Any]:
    entry_name, cik, tickers = _entry_parts(entry)
    return {"name": entry_name, "cik": cik, "tickers": tickers}


def score_name_candidates(query: str, entries: Any) -> list[dict[str, Any]]:
    """Score catalog name entries against ``query``, best first."""
    query_norm, query_tokens = _normalize(query)
    scored: list[dict[str, Any]] = []
    for entry in entries:
        entry_name, cik, tickers = _entry_parts(entry)
        if not entry_name:
            continue
        entry_norm, entry_tokens = _normalize(entry_name)
        value = _score(query_norm, query_tokens, entry_norm, entry_tokens)
        if value > 0:
            scored.append(
                {"name": entry_name, "cik": cik, "tickers": tickers, "score": value}
            )
    scored.sort(key=lambda item: (-item["score"], item["name"], item["cik"]))
    return scored[:10]
