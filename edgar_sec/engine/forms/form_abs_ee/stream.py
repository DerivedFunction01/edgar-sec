"""Streaming summary of ABS asset-data exhibits (EX-102 / EX-103)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_abs_ee.models import (
    AssetDataSummary,
    CompanionSignal,
    ExhibitKind,
)
from edgar_sec.domain.forms.families.form_abs_ee.taxonomy import (
    ASSET_RECORD_TAG,
    ASSETDATA_NAMESPACE_PREFIX,
    ASSETDATA_NAMESPACE_SUFFIX,
    ASSETDATA_ROOT_TAG,
    COMMENT_RECORD_TAG,
    COMMENTS_ROOT_TAG,
    EXHIBIT_TYPES,
)

_CHUNK = 1 << 20


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return namespace, local
    return "", tag


def probe_asset_data_root(path: Path) -> tuple[str, str] | None:
    """(namespace, local tag) of the document root, read incrementally."""
    try:
        events = ET.iterparse(path, events=("start",))
        for _, elem in events:
            return _split_tag(elem.tag)
    except ET.ParseError:
        return None
    return None


def classify_asset_root(
    namespace: str, local: str
) -> tuple[ExhibitKind, str | None] | None:
    """Classify a document root as EX-102 / EX-103; None when not asset data."""
    if not namespace and local == COMMENTS_ROOT_TAG:
        return ExhibitKind.EX_103, None
    if local.lower() != ASSETDATA_ROOT_TAG:
        return None
    if not namespace:
        return ExhibitKind.EX_103, None
    if namespace.startswith(ASSETDATA_NAMESPACE_PREFIX) and namespace.endswith(
        ASSETDATA_NAMESPACE_SUFFIX
    ):
        asset_class = namespace[
            len(ASSETDATA_NAMESPACE_PREFIX) : -len(ASSETDATA_NAMESPACE_SUFFIX)
        ]
        return ExhibitKind.EX_102, asset_class or None
    return None


def _record_tag_for(root_local: str) -> str:
    return COMMENT_RECORD_TAG if root_local == COMMENTS_ROOT_TAG else ASSET_RECORD_TAG


def summarize_asset_data(path: Path) -> AssetDataSummary | None:
    """Stream one asset-data file into its summary; None when not asset data."""
    root_info = probe_asset_data_root(path)
    if root_info is None:
        return None
    classified = classify_asset_root(*root_info)
    if classified is None:
        return None
    kind, asset_class = classified
    record_tag = _record_tag_for(root_info[1])
    records = 0
    root: ET.Element | None = None
    try:
        events = ET.iterparse(path, events=("start", "end"))
        for event, elem in events:
            if event == "start" and root is None:
                root = elem
                continue
            if event != "end":
                continue
            if _split_tag(elem.tag)[1] == record_tag:
                records += 1
                if root is not None:
                    root.clear()
    except ET.ParseError:
        return None
    comments, comment_chars, cdata_sections = _scan_lexical(path)
    return AssetDataSummary(
        kind=kind,
        asset_class=asset_class,
        root_tag=root_info[1],
        record_count=records,
        comment_count=comments,
        comment_chars=comment_chars,
        cdata_sections=cdata_sections,
    )


def _scan_lexical(path: Path) -> tuple[int, int, int]:
    """Count comments, comment bytes, and CDATA sections in one pass.

    iterparse does not surface comment nodes, so comments are counted
    lexically with a CDATA-aware state machine; memory stays bounded.
    """
    comments = 0
    comment_chars = 0
    cdata_sections = 0
    state = "text"
    buffer = b""
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            buffer += chunk
            while True:
                if state == "text":
                    comment_at = buffer.find(b"<!--")
                    cdata_at = buffer.find(b"<![CDATA[")
                    if comment_at == -1 and cdata_at == -1:
                        buffer = buffer[-9:]
                        break
                    if cdata_at != -1 and (comment_at == -1 or cdata_at < comment_at):
                        cdata_sections += 1
                        state = "cdata"
                        buffer = buffer[cdata_at + 9 :]
                    else:
                        comments += 1
                        state = "comment"
                        buffer = buffer[comment_at + 4 :]
                elif state == "comment":
                    end = buffer.find(b"-->")
                    if end == -1:
                        comment_chars += max(0, len(buffer) - 2)
                        buffer = buffer[-2:]
                        break
                    comment_chars += end
                    state = "text"
                    buffer = buffer[end + 3 :]
                else:
                    end = buffer.find(b"]]>")
                    if end == -1:
                        buffer = buffer[-2:]
                        break
                    state = "text"
                    buffer = buffer[end + 3 :]
    return comments, comment_chars, cdata_sections


def detect_companions(document_types: Iterable[str]) -> tuple[CompanionSignal, ...]:
    """Companion presence signals from a host submission's document types."""
    present = {str(code).strip().upper() for code in document_types}
    return tuple(
        CompanionSignal(exhibit_type=code, present=code in present)
        for code in EXHIBIT_TYPES
    )


__all__ = [
    "classify_asset_root",
    "detect_companions",
    "probe_asset_data_root",
    "summarize_asset_data",
]
