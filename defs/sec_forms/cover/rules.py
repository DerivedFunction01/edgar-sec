"""Private compiled rules for cover and body evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from defs.regex import build_alternation
from defs.sec_forms.vocabulary import (
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)


@dataclass(frozen=True, slots=True)
class CompiledCoverRules:
    """Compiled regexes selected from a cover/body evidence pack."""

    incorporated: re.Pattern[str]
    cover_identity: re.Pattern[str]
    cover_start_identity: re.Pattern[str]
    cover_start_shape: re.Pattern[str]
    body_semantic: re.Pattern[str]
    body_ngram: re.Pattern[str]
    body_verb: re.Pattern[str]


def compile_cover_rules(
    cover_evidence: object | None = None,
    body_evidence: object | None = None,
) -> CompiledCoverRules:
    """Compile profile evidence without hardcoded form-family assumptions."""
    labels = tuple(getattr(cover_evidence, "labels", COVER_LABELS_FLAT))
    identity = tuple(
        getattr(cover_evidence, "identity_terms", COVER_START_IDENTITY_TERMS)
    )
    shape = tuple(getattr(cover_evidence, "shape_terms", COVER_LABELS_FLAT))
    ngrams = tuple(getattr(body_evidence, "body_ngrams", ()))
    verbs = tuple(getattr(body_evidence, "body_verbs", ()))
    headings = tuple(getattr(body_evidence, "semantic_headings", ()))
    incorporated = tuple(getattr(cover_evidence, "cover_end_terms", ()))
    return CompiledCoverRules(
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
        body_ngram=re.compile(
            build_alternation(
                ngrams, auto_escape=True, compact=True, never_match_empty=True
            ),
            re.IGNORECASE,
        ),
        body_verb=re.compile(
            build_alternation(
                verbs, auto_escape=True, compact=True, never_match_empty=True
            ),
            re.IGNORECASE,
        ),
    )


__all__ = ["CompiledCoverRules", "compile_cover_rules"]
