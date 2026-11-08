"""Filename-family selection of EX-99 exhibits.

Selection is filename-based only: the filing index ``type`` field is an
icon token, never a document type, so it is never consulted here.
"""

from __future__ import annotations

import re

from edgar_sec.engine.forms.earnings.models import ExhibitCandidate

_MANGLED_RE = re.compile(r"exv99w(\d+)")
_EXHIBIT_RE = re.compile(r"exhibit[-_]?99(\.(\d+)|-(\d+)|_(\d+)|(\d+))?")
_SHORT_RE = re.compile(r"exh[-_]?99(\.(\d+)|-(\d+)|_(\d+)|(\d+))?")
_MODERN_RE = re.compile(r"ex[-_]?99(\.(\d+)|-(\d+)|_(\d+)|(\d+))?")

_FAMILIES = (
    ("mangled", _MANGLED_RE),
    ("exhibit", _EXHIBIT_RE),
    ("short", _SHORT_RE),
    ("modern", _MODERN_RE),
)

_IMAGE_EXTS = frozenset({"jpg", "jpeg", "gif", "png", "bmp", "tif", "tiff"})
_INDEX_NAMES = frozenset({"index.html"})


def classify_kind(filename: str) -> str:
    """Classify one exhibit filename by its extension."""
    lowered = filename.lower()
    ext = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if ext in _IMAGE_EXTS:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext in ("htm", "html"):
        return "html"
    return "text"


def match_exhibit_filename(filename: str) -> tuple[int, str] | None:
    """Return (exhibit number, family) when a filename names an EX-99."""
    lowered = filename.lower()
    if lowered.endswith(("-index.html", "-index-headers.html")):
        return None
    if lowered in _INDEX_NAMES:
        return None
    for family, pattern in _FAMILIES:
        match = pattern.search(lowered)
        if match is None:
            continue
        number = next(
            (
                int(group)
                for group in match.groups()
                if group is not None and group.isdigit()
            ),
            0,
        )
        return number, family
    return None


def select_exhibit_candidates(
    attachments: tuple[tuple[str, str], ...],
) -> tuple[ExhibitCandidate, ...]:
    """Order (filename, document_type) pairs into exhibit candidates."""
    picked: list[ExhibitCandidate] = []
    for filename, document_type in attachments:
        matched = match_exhibit_filename(filename)
        if matched is None:
            continue
        number, family = matched
        picked.append(
            ExhibitCandidate(
                filename=filename,
                document_type=document_type,
                exhibit_number=number,
                family=family,
                kind=classify_kind(filename),
            )
        )
    picked.sort(key=lambda candidate: (candidate.exhibit_number, candidate.filename))
    return tuple(picked)


__all__ = ["classify_kind", "match_exhibit_filename", "select_exhibit_candidates"]
