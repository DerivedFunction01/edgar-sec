"""Private compiled rules for cover and body evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.domain.forms.common.models import derive_lexical_pack
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.evidence import (
    CompiledEvidencePack,
    LexicalEvidencePack,
    compile_evidence_pack,
)


@dataclass(frozen=True, slots=True)
class CompiledCoverRules:
    """Compiled cover regexes and the compiled lexical body-evidence pack."""

    incorporated: re.Pattern[str]
    cover_identity: re.Pattern[str]
    cover_start_identity: re.Pattern[str]
    cover_start_shape: re.Pattern[str]
    body_semantic: re.Pattern[str]
    lexical: CompiledEvidencePack


def _lexical_for(body_evidence: object | None) -> CompiledEvidencePack:
    """Compile the lexical pack for a body evidence object. An explicit `lexical` pack
    wins; otherwise one is derived from legacy body vocabulary fields.
    """
    lexical = getattr(body_evidence, "lexical", None)
    if isinstance(lexical, LexicalEvidencePack):
        return compile_evidence_pack(lexical)
    return compile_evidence_pack(
        derive_lexical_pack(
            body_ngrams=tuple(getattr(body_evidence, "body_ngrams", ())),
            body_verbs=tuple(getattr(body_evidence, "body_verbs", ())),
            body_terms=tuple(getattr(body_evidence, "body_terms", ())),
            cover_terms=tuple(getattr(body_evidence, "cover_terms", ())),
        )
    )


_COMPILE_CACHE: dict[tuple[int, int], CompiledCoverRules] = {}


def compile_cover_rules(
    cover_evidence: object | None = None,
    body_evidence: object | None = None,
) -> CompiledCoverRules:
    """Compile profile evidence with no hardcoded form-family assumptions. Cached by
    object identity: evidence packs are profile-level, reused across a batch.
    """
    key = (id(cover_evidence), id(body_evidence))
    cached = _COMPILE_CACHE.get(key)
    if cached is not None:
        return cached
    labels = tuple(getattr(cover_evidence, "labels", COVER_LABELS_FLAT))
    identity = tuple(
        getattr(cover_evidence, "identity_terms", COVER_START_IDENTITY_TERMS)
    )
    shape = tuple(getattr(cover_evidence, "shape_terms", COVER_LABELS_FLAT))
    headings = tuple(getattr(body_evidence, "semantic_headings", ()))
    incorporated = tuple(getattr(cover_evidence, "cover_end_terms", ()))
    result = CompiledCoverRules(
        incorporated=re.compile(
            build_alternation(
                incorporated,
                auto_escape=True,
                compact=True,
                flexible_whitespace=True,
                never_match_empty=True,
            ),
            re.IGNORECASE,
        ),
        cover_identity=re.compile(
            rf"(?:{COVER_START_IDENTITY_TERMS[0]}|"
            rf"{COVER_START_IDENTITY_TERMS[1]}|"
            rf"{build_alternation(labels, auto_escape=True, compact=True, never_match_empty=True)})",
            re.IGNORECASE,
        ),
        cover_start_identity=re.compile(
            build_alternation(
                identity, auto_escape=False, compact=True, never_match_empty=True
            ),
            re.IGNORECASE,
        ),
        cover_start_shape=re.compile(
            build_alternation(
                shape, auto_escape=True, compact=True, never_match_empty=True
            ),
            re.IGNORECASE,
        ),
        body_semantic=re.compile(
            build_alternation(
                headings, auto_escape=True, compact=True, never_match_empty=True
            ),
            re.IGNORECASE,
        ),
        lexical=_lexical_for(body_evidence),
    )
    _COMPILE_CACHE[key] = result
    return result


__all__ = ["CompiledCoverRules", "compile_cover_rules"]
