"""Text-level signature primitives: marker normalization and name healing.

This module owns the canonical transformations for conformed signature
markers and letter-spaced (mangled) signature text. It is text-level only:
``re`` and ``defs.text`` imports, no HTML or table dependencies. Table-level
consumers compose these primitives with the canonical geometry-first renderer.

Mangled names are a known SEC artifact of condensed fonts: glyph-width
rendering inserts a space after isolated uppercase letters, producing shapes
like ``/s/ S ATYA N ADELLA`` or ``M ICROSOFT C ORPORATION``. Healing removes
whitespace only after isolated single-letter uppercase tokens when the
signature-marker context confirms the mangled shape.
"""

from __future__ import annotations

import re

from defs.text.patterns import RE_CONFORMED_SIGNATURE

__all__ = [
    "heal_mangled_signature_text",
    "normalize_signature_marker",
    "signature_block_has_mangled_text",
]


# Mangled marker shapes: ``/S/`` with the S uppercase, or whitespace inside
# the slashes (``/ S /``, ``/ s /``). Plain ``/s/`` is already canonical.
_MANGLED_MARKER_RE = re.compile(r"/\s+S\s+/|/\s+s\s+/")

# A signature marker followed by a letter-spaced name: ``/s/ A LICE L. J OLLA``
# or ``/ S / S ATYA N ADELLA``. Requires at least one isolated single-letter
# uppercase token pair after the marker so ordinary ``/s/ Alex Smith`` never
# triggers healing.
_MANGLED_SIGNATURE_RE = re.compile(r"/\s*[sS]\s*/\s+[A-Z]\s+[A-Z]")

# Isolated single uppercase letter followed by whitespace and another
# uppercase letter. Only applied when the mangled-signature context is
# confirmed; never applied to arbitrary text.
_ISOLATED_CAPITAL_GAP_RE = re.compile(r"\b([A-Z])\s+(?=[A-Z])")

# Canonical marker with optional leading ``By:`` label.
_MARKER_RE = re.compile(r"^(/\s*S\s*/|/s/)\s*", re.IGNORECASE)


def normalize_signature_marker(text: str) -> str:
    """Return ``text`` with its leading signature marker canonicalized.

    ``/S/``, ``/ S /``, ``/ s /`` and ``/s/`` all become ``/s/``. Any other
    text is returned unchanged.
    """
    match = _MARKER_RE.match(text)
    if not match:
        return text
    return (
        f"/s/ {text[match.end() :].strip()}" if text[match.end() :].strip() else "/s/"
    )


def signature_block_has_mangled_text(cells: tuple[str, ...] | list[str]) -> bool:
    """Return whether any cell carries the mangled marker-plus-name shape."""
    return any(_MANGLED_SIGNATURE_RE.search(cell) for cell in cells)


def heal_mangled_signature_text(text: str) -> str:
    """Heal letter-spaced signature text inside a confirmed mangled block.

    Collapses whitespace after isolated single-letter uppercase tokens and
    canonicalizes the marker. Ordinary capitalized names with real initials
    (``A. Smith``) keep their spacing because the initial keeps its period.
    """
    healed = _ISOLATED_CAPITAL_GAP_RE.sub(r"\1", text)
    return normalize_signature_marker(healed)


def is_conformed_signature_line(line: str) -> bool:
    """Return whether a raw line starts with a conformed ``/s/`` marker."""
    return bool(RE_CONFORMED_SIGNATURE.match(line))
