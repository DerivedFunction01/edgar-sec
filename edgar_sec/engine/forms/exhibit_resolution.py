"""Exhibit resolution per family profile (R3).

One resolver ties a registry profile's exhibit links to a filing's
document inventory: candidacy is metadata-decided, body confirmation
and the delegation judgement run only on flagged candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.vocabulary import (
    EX13_TEXT_ANCHOR_RE,
    is_ex13_type,
)
from edgar_sec.domain.forms.families.annual.evidence import EX13_DELEGATION_VERBS
from edgar_sec.engine.forms.plugins.exhibit_selection import evaluate_exhibit_body
from edgar_sec.engine.tables.extraction.core.profiles import PROFILES

#: Characters either side of an exhibit anchor scanned for a verb.
DELEGATION_WINDOW_CHARS = 300

_AUTHORITY_ID = "reg_s_k_item_601"
_CODE_BY_BASE_TYPE = {"EX-13": "13"}


@dataclass(frozen=True, slots=True)
class ExhibitCandidateInput:
    """One inventory document: its index type, name, and body text."""

    document_type: str | None
    document_name: str
    body_text: str | None = None


@dataclass(frozen=True, slots=True)
class DelegationJudgement:
    """Whether the primary delegates its statements to the exhibit."""

    is_stub: bool
    exhibit_index_only: bool
    anchors: int
    verbs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedExhibit:
    """One resolved candidate: families, confirmation, delegation."""

    document_name: str
    document_type: str | None
    code: str
    families: tuple[str, ...]
    body_disposition: str | None
    body_confirmed: bool
    delegation: DelegationJudgement | None = None


def linked_exhibit_families(stratum: str) -> dict[str, tuple[str, ...]]:
    """Registry exhibit links for one stratum: base type to families."""
    linked: dict[str, list[str]] = {}
    for profile in PROFILES:
        for link in profile.exhibit_links:
            if stratum in link.strata:
                linked.setdefault(link.exhibit_type, []).append(profile.family)
    return {base: tuple(families) for base, families in linked.items()}


def _is_candidate(base_type: str, document_type: str | None) -> bool:
    """Metadata candidacy: the index type against the domain family."""
    if base_type == "EX-13":
        return is_ex13_type(document_type)
    if not document_type:
        return False
    value = document_type.strip().upper()
    return value == base_type or value.startswith(f"{base_type}.")


def _identity_code(base_type: str, document_type: str | None, family_code: str) -> str:
    """The candidate's own exhibit code for body confirmation: the
    evaluator compares exact identities (EX-13.1 confirms against 13.1,
    not the family base 13), as both standing consumers name it."""
    if not document_type:
        return family_code
    value = document_type.strip().upper()
    if value.endswith(".PDF"):
        value = value[:-4]
    while value.endswith(")") and "(" in value:
        value = value[: value.rfind("(")].rstrip(".")
    if value.endswith(".A"):
        value = value[:-2]
    code = value.removeprefix("EX-")
    return code if code.startswith(family_code) else family_code


def delegation_judgement(primary_text: str | None) -> DelegationJudgement | None:
    """The anchor-window scan over the primary's normalized text.

    A verb inside an anchor's window means the primary delegates;
    anchors with no verb in any window are index-only mentions.
    """
    if not primary_text:
        return None
    anchors = list(EX13_TEXT_ANCHOR_RE.finditer(primary_text))
    if not anchors:
        return None
    verbs_found: list[str] = []
    for anchor in anchors:
        start = max(0, anchor.start() - DELEGATION_WINDOW_CHARS)
        end = min(len(primary_text), anchor.end() + DELEGATION_WINDOW_CHARS)
        window = primary_text[start:end].lower()
        for verb in EX13_DELEGATION_VERBS:
            if verb in window and verb not in verbs_found:
                verbs_found.append(verb)
    return DelegationJudgement(
        is_stub=bool(verbs_found),
        exhibit_index_only=not verbs_found,
        anchors=len(anchors),
        verbs=tuple(verbs_found),
    )


def resolve_exhibits(
    inventory: tuple[ExhibitCandidateInput, ...] | list[ExhibitCandidateInput],
    *,
    stratum: str,
    filing_form: str,
    primary_text: str | None = None,
) -> tuple[ResolvedExhibit, ...]:
    """Resolve one filing's inventory against the registry links.

    Candidacy is decided from index metadata alone; the body
    evaluator and the delegation judgement run only on candidates.
    """
    linked = linked_exhibit_families(stratum)
    if not linked:
        return ()
    delegation: DelegationJudgement | None = None
    delegation_computed = False
    resolved: list[ResolvedExhibit] = []
    for candidate in inventory:
        for base_type, families in linked.items():
            if not _is_candidate(base_type, candidate.document_type):
                continue
            code = _CODE_BY_BASE_TYPE.get(
                base_type, base_type.removeprefix("EX-").split(".")[0]
            )
            disposition: str | None = None
            confirmed = False
            if candidate.body_text is not None:
                identity = ExhibitIdentity(
                    _AUTHORITY_ID,
                    _identity_code(base_type, candidate.document_type, code),
                )
                assessment = evaluate_exhibit_body(
                    candidate.body_text,
                    filing_form=filing_form,
                    expected_type=base_type,
                    expected_identity=identity,
                )
                if assessment is not None:
                    disposition = assessment.disposition
                    # Confirmation is role confirmation: the body
                    # designates this candidate's own exhibit code
                    # with no contradicting evidence. The evaluator's
                    # consistent bar additionally demands a cover
                    # title inside its opening window, which portion
                    # exhibits (the measured carrier population) do
                    # not carry; a designation for a different
                    # exhibit stays a mismatch and never confirms.
                    confirmed = disposition == "consistent" or (
                        disposition != "possible_role_mismatch"
                        and assessment.observed_identity == identity
                        and not assessment.contradicting_evidence
                        and any(
                            span.signal_id.startswith("exhibit_code_")
                            for span in assessment.supporting_evidence
                        )
                    )
            if not delegation_computed:
                delegation = delegation_judgement(primary_text)
                delegation_computed = True
            resolved.append(
                ResolvedExhibit(
                    document_name=candidate.document_name,
                    document_type=candidate.document_type,
                    code=code,
                    families=families,
                    body_disposition=disposition,
                    body_confirmed=confirmed,
                    delegation=delegation,
                )
            )
    return tuple(resolved)
