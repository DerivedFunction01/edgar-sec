"""Canonical page-artifact tokens, template normalization, and metadata.
A token in the text carries an id and nothing else, so a position in published text never becomes a
second source of truth about page numbers; every payload attribute lives in the sidecar.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .models import PageArtifactPolicy, PageBreakArtifact, PageMarkerKind

PAGE_BREAK_TOKEN_KIND = "PAGE_BREAK"
REPEATING_HEADER_TOKEN_KIND = "REPEATING_HEADER"
REPEATING_FOOTER_TOKEN_KIND = "REPEATING_FOOTER"

#: Longest template id the normalizer records, as a hexadecimal character count.
TEMPLATE_ID_LENGTH = 16

_TOKEN_KINDS = {
    PageMarkerKind.REPEATING_HEADER: REPEATING_HEADER_TOKEN_KIND,
    PageMarkerKind.REPEATING_FOOTER: REPEATING_FOOTER_TOKEN_KIND,
}

_DIGIT_RUN_RE = re.compile(r"(?<![\w-])\d+(?![\w-])")
_WHITESPACE_RE = re.compile(r"\s+")


def token_kind_for(marker_kind: str) -> str:
    """Map a marker kind to its rendered token kind; page breaks by default."""

    return _TOKEN_KINDS.get(marker_kind, PAGE_BREAK_TOKEN_KIND)


def render_page_artifact(token_kind: str, artifact_id: int) -> str:
    """Render the canonical id-only token line."""

    return f"[[SEC:{token_kind} id={artifact_id}]]"


def normalize_template_text(text: str) -> tuple[str, int | None]:
    """Collapse whitespace and replace digit runs with ``#`` placeholders.
    Returns the zero-based slot a page number occupied when exactly one digit run was replaced; several runs record no slot, as the position is then ambiguous.
    """

    normalized = _WHITESPACE_RE.sub(" ", text.strip())
    slots: list[int] = []

    def _replace(match: re.Match[str]) -> str:
        slots.append(len(slots))
        return "#"

    normalized = _DIGIT_RUN_RE.sub(_replace, normalized)
    slot = slots[0] if len(slots) == 1 else None
    return normalized, slot


def template_id_for(rendered_text: str) -> str:
    """Return the stable template id for normalized rendered text."""

    return hashlib.sha1(rendered_text.encode("utf-8")).hexdigest()[:TEMPLATE_ID_LENGTH]


def note_template(
    templates: dict[str, dict[str, Any]],
    marker_kind: str,
    captured_text: str,
    *,
    page_number: int | str | None = None,
) -> str:
    """Deduplicate captured furniture text into ``templates`` and return its id.
    ``captured_text`` is rendered text, never raw HTML. An unnormalizable capture records nothing and returns an empty id, never a template keyed by the empty string.
    """

    rendered, slot = normalize_template_text(captured_text)
    if not rendered:
        return ""
    template_id = template_id_for(rendered)
    entry = templates.get(template_id)
    if entry is None:
        entry = {
            "kind": marker_kind,
            "rendered_text": rendered,
            "occurrences": 0,
            "page_number_slot": slot,
        }
        templates[template_id] = entry
    entry["occurrences"] += 1
    if page_number is not None and slot is None and entry["page_number_slot"] is None:
        entry["page_number_slot"] = None
    return template_id


def artifact_metadata_entry(
    artifact: PageBreakArtifact, artifact_id: int
) -> dict[str, Any]:
    """Serialize one artifact for the metadata sidecar."""

    kind = artifact.source if artifact.source.startswith("repeating_") else "page_break"
    return {
        "id": artifact_id,
        "kind": kind,
        "page_number": artifact.page_number,
        "namespace": artifact.namespace,
        "source": artifact.source,
        "node_path": list(artifact.node_path) if artifact.node_path else None,
        "line_span": [artifact.start_line, artifact.end_line]
        if artifact.start_line is not None
        else None,
        "char_span": [artifact.start, artifact.end]
        if artifact.start is not None and artifact.end is not None
        else None,
        "template_id": artifact.template_id,
        "removable": artifact.removable,
    }


def build_page_artifact_metadata(
    policy: PageArtifactPolicy,
    source_identity: str,
    templates: dict[str, dict[str, Any]],
    artifacts: list[tuple[int, PageBreakArtifact]],
) -> dict[str, Any]:
    """Build the deterministic ``page_artifacts`` metadata dictionary.
    Templates emit in id order and artifacts in assigned-id order, so two runs over one document agree byte for byte.
    """

    return {
        "policy": policy.value,
        "source_identity": source_identity,
        "templates": dict(sorted(templates.items())),
        "artifacts": [
            artifact_metadata_entry(artifact, artifact_id)
            for artifact_id, artifact in sorted(artifacts, key=lambda item: item[0])
        ],
    }


__all__ = [
    "PAGE_BREAK_TOKEN_KIND",
    "REPEATING_FOOTER_TOKEN_KIND",
    "REPEATING_HEADER_TOKEN_KIND",
    "TEMPLATE_ID_LENGTH",
    "artifact_metadata_entry",
    "build_page_artifact_metadata",
    "normalize_template_text",
    "note_template",
    "render_page_artifact",
    "template_id_for",
    "token_kind_for",
]
