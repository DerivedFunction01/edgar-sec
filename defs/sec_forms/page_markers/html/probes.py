"""Raw HTML probes and regex constants for page-marker discovery."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from defs.regex import build_alternation

from ..constants import (
    _RECIPE_PLATFORM_RE,
    PROSE_GUARD_STOP_WORDS,
)

_LABEL_TAGS = ("font", "p", "div", "span", "td", "th", "b", "i", "a", "em")
_RECIPE_CACHE_LIMIT = 512
_RECIPE_VARIANTS_LIMIT = 4
_RECIPE_CACHE: OrderedDict[str, list[frozenset[tuple[str, str]]]] = OrderedDict()
_RECIPE_REJECTED: OrderedDict[tuple[str, int], None] = OrderedDict()
_LABEL_TAG_PATTERN = build_alternation(_LABEL_TAGS)
_RAW_LABEL_RE = re.compile(
    rf"(?is)<(?P<tag>{_LABEL_TAG_PATTERN})\b[^>]*>"
    r"\s*(?:page\s+)?(?:[a-z]\s*[-\u2013\u2014]\s*)?"
    r"(?:\d{1,4}|[ivxlcdm]{1,8})\s*</(?P=tag)\s*>"
)
_RAW_STRONG_TOKEN_RE = re.compile(
    r"(?is)(?:^|[>\s])(?:"
    r"[a-z]\s*[-\u2013\u2014]\s*\d{1,4}"
    r"|(?:page\s*)\d{1,4}"
    r")(?:\s*(?:<|$))"
)
_RAW_PAGE_ATTR_RE = re.compile(r"(?is)\b(?:class|id|name)\s*=\s*[\"'][^\"']*\bpage")
_MULTIYEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_DECIMAL_RE = re.compile(r"\d\.\d")
_PAREN_NUMBER_RE = re.compile(r"\(\s*[\d.,]+\s*\)")


def _raw_label_tags(source_text: str) -> tuple[str, ...] | None:
    if not _RAW_STRONG_TOKEN_RE.search(source_text):
        if _has_page_structural_hint(source_text):
            return None
        return ()
    if _has_page_structural_hint(source_text):
        return None
    matched = {
        match.group("tag").casefold()
        for match in _RAW_LABEL_RE.finditer(source_text)
        if _RAW_STRONG_TOKEN_RE.search(match.group(0))
    }
    tags = tuple(tag for tag in _LABEL_TAGS if tag in matched)
    return tags or None


def html_has_page_label_evidence(source_text: str) -> bool:
    if not source_text:
        return False
    lowered = source_text.casefold()
    return bool(
        _RAW_STRONG_TOKEN_RE.search(source_text)
        or "<hr" in lowered
        or "<table" in lowered
    )


def _has_page_structural_hint(source_text: str) -> bool:
    return bool(
        _RAW_PAGE_ATTR_RE.search(source_text) or "page-break" in source_text.casefold()
    )


def _html_recipe_signature(source_text: str) -> str:
    for comment in re.findall(r"<!--(.*?)-->", source_text[:100_000], re.DOTALL):
        flat = " ".join(comment.split())
        if _RECIPE_PLATFORM_RE.search(flat):
            return re.sub(r"\d+", "#", flat.casefold())[:96]
    return ""


def _recipe_fingerprint(profile: frozenset[tuple[str, str]]) -> int:
    return hash(profile)


def _recipe_learn(
    signature: str,
    markers: list[Any],
    candidates: list[dict[str, Any]],
) -> None:
    if not signature or len(markers) < 3:
        return
    paths = {marker.node_path for marker in markers if marker.node_path}
    profile = frozenset(
        (str(getattr(item["node"], "name", "")).casefold(), item.get("attr_text", ""))
        for item in candidates
        if item.get("path") in paths
    )
    if not profile:
        return
    variants = _RECIPE_CACHE.setdefault(signature, [])
    if profile in variants:
        variants.remove(profile)
    else:
        variants[:] = variants[-(_RECIPE_VARIANTS_LIMIT - 1) :]
    variants.append(profile)
    _RECIPE_CACHE.move_to_end(signature)
    while len(_RECIPE_CACHE) > _RECIPE_CACHE_LIMIT:
        _RECIPE_CACHE.popitem(last=False)


__all__ = [
    "PROSE_GUARD_STOP_WORDS",
    "_DECIMAL_RE",
    "_LABEL_TAGS",
    "_LABEL_TAG_PATTERN",
    "_MULTIYEAR_RE",
    "_PAREN_NUMBER_RE",
    "_RAW_LABEL_RE",
    "_RAW_PAGE_ATTR_RE",
    "_RAW_STRONG_TOKEN_RE",
    "_RECIPE_CACHE",
    "_RECIPE_CACHE_LIMIT",
    "_RECIPE_REJECTED",
    "_RECIPE_VARIANTS_LIMIT",
    "_THOUSANDS_RE",
    "_has_page_structural_hint",
    "_html_recipe_signature",
    "_raw_label_tags",
    "_recipe_fingerprint",
    "_recipe_learn",
    "html_has_page_label_evidence",
]
