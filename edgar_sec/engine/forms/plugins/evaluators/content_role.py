"""Form-agnostic content role evaluator for D2."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    PrimaryReportProfile,
)
from edgar_sec.domain.forms.families.annual.profiles import (
    PRIMARY_PROFILE_10K,
    PRIMARY_PROFILE_20F,
)
from edgar_sec.domain.forms.families.current.profiles import PRIMARY_PROFILE_8K
from edgar_sec.domain.forms.families.quarterly.profiles import PRIMARY_PROFILE_10Q
from edgar_sec.engine.forms.cover.models import CoverBoundary
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    PROBE_LINE_BOUND,
    probe_exhibit_header,
)
from edgar_sec.foundation.regex.builder import build_alternation

# Registered primary profiles across all form families
_REGISTERED_PRIMARY_PROFILES: tuple[PrimaryReportProfile, ...] = (
    PRIMARY_PROFILE_10K,
    PRIMARY_PROFILE_10Q,
    PRIMARY_PROFILE_8K,
    PRIMARY_PROFILE_20F,
)

# O(1) form code lookup table
_PROFILE_BY_FORM: dict[str, PrimaryReportProfile] = {
    token.upper(): profile
    for profile in _REGISTERED_PRIMARY_PROFILES
    for token in profile.designator_tokens
}

# Bounded window size for opening analysis
OPENING_WINDOW_CHARS = 16_384

# Precompile title patterns for O(1) matching
_TITLE_PATTERNS: dict[str, re.Pattern[str]] = {
    profile.family: re.compile(
        build_alternation(profile.statutory_titles),
        re.IGNORECASE,
    )
    for profile in _REGISTERED_PRIMARY_PROFILES
}


def _matches_profile(
    window: str,
    window_lower: str,
    profile: PrimaryReportProfile,
) -> bool:
    """Check if text window matches a profile's cues.

    Returns True if any designator token or statutory title is found.
    """
    # Check designator tokens (lowercase comparison)
    for token in profile.designator_tokens:
        if token.lower() in window_lower:
            return True

    # Check statutory titles
    for title in profile.statutory_titles:
        if title.lower() in window_lower:
            return True

    return False


def evaluate_document_role(
    text: str,
    *,
    expected_form: str,
    expected_role: str,
    normalization_result: NormalizationResult | None = None,
) -> DocumentRoleAssessment | None:
    """Evaluate document role using form-agnostic decision tree."""
    # 1. Scope gate: O(1) lookup
    expected_profile = _PROFILE_BY_FORM.get(expected_form.upper())
    if expected_profile is None:
        return None

    # 2. Bounded window extraction
    window = text[:OPENING_WINDOW_CHARS]
    window_lower = window.lower()

    # 3. Fast path: Check expected profile first
    if _matches_profile(window, window_lower, expected_profile):
        return DocumentRoleAssessment(
            expected_role=expected_role,
            expected_type="primary_report",
            filing_form=expected_form,
            expected_identity=expected_form,
            observed_kind="primary_report",
            observed_identity=expected_form,
            disposition="consistent",
            evaluator_quality="proposed",
            profile_id=expected_profile.family,
            profile_version=expected_profile.version,
        )

    # 4. Triage path: Check alternate profiles
    for alt_profile in _REGISTERED_PRIMARY_PROFILES:
        if alt_profile.family == expected_profile.family:
            continue
        if _matches_profile(window, window_lower, alt_profile):
            return DocumentRoleAssessment(
                expected_role=expected_role,
                expected_type="primary_report",
                filing_form=expected_form,
                expected_identity=expected_form,
                observed_kind="primary_report",
                observed_identity=alt_profile.family,
                disposition="possible_role_mismatch",
                evaluator_quality="proposed",
                profile_id=expected_profile.family,
                profile_version=expected_profile.version,
            )

    # 5. Exhibit probe: Bounded line split
    probe_lines: tuple[str, ...] = ()
    if normalization_result is not None:
        text_for_probe = normalization_result.text
        window_for_probe = text_for_probe[:OPENING_WINDOW_CHARS]
        probe_lines = tuple(window_for_probe.split("\n", PROBE_LINE_BOUND))

    toc_span: TocSpan | None = None
    if normalization_result is not None:
        toc_span = normalization_result.toc_span

    exhibit_probe = probe_exhibit_header(
        text=text,
        lines=probe_lines,
        toc_span=toc_span,
        filing_form=expected_form,
    )

    if exhibit_probe is not None:
        return DocumentRoleAssessment(
            expected_role=expected_role,
            expected_type="exhibit",
            filing_form=expected_form,
            expected_identity=None,
            observed_kind="exhibit",
            observed_identity=exhibit_probe.exhibit_identity,
            disposition="possible_role_mismatch",
            evaluator_quality="proposed",
            profile_id=expected_profile.family,
            profile_version=expected_profile.version,
        )

    # 6. Abstention
    return DocumentRoleAssessment(
        expected_role=expected_role,
        expected_type="primary_report",
        filing_form=expected_form,
        expected_identity=expected_form,
        observed_kind="unknown",
        observed_identity=None,
        disposition="insufficient_evidence",
        evaluator_quality="proposed",
        profile_id=expected_profile.family,
        profile_version=expected_profile.version,
    )


__all__ = ["evaluate_document_role"]
