"""The three 10-K/A amendment transitions, the identity gate that suppresses
them, and the standard 10-K non-regression.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import BodyEvidencePack, CoverEvidencePack
from edgar_sec.engine.forms.cover.body_start import find_body_start
from edgar_sec.engine.forms.cover.boundary.detector import find_cover_boundary
from edgar_sec.engine.forms.cover.models import (
    BoundaryMethod,
    BoundarySignal,
    CoverBoundaryPolicy,
)
from edgar_sec.engine.forms.cover.profiles import build_annual_profile

_COVER_HEAD = (
    "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
    "Washington, D.C. 20549\n"
    "FORM 10-K/A\n"
    "Annual Report pursuant to Section 13 or 15(d)\n"
    "For the fiscal year ended December 31, 2003\n"
    "Commission File Number 000-12345\n"
    "ACME CORP\n"
    "100 Main Street, Springfield, IL 60606\n"
)

_COVER_FLOAT = (
    "The aggregate market value of the voting and non-voting common equity "
    "held by non-affiliates of the registrant was approximately $27,000,000.\n"
)
_COVER_SHARES = (
    "As of March 5, 2004, there were 1,783,420 shares of Common Stock outstanding.\n"
)

_COVER_BODY = _COVER_HEAD + _COVER_FLOAT + _COVER_SHARES

_POLICY = CoverBoundaryPolicy(signals=tuple(BoundarySignal))
_ANNUAL_COVER_EVIDENCE = CoverEvidencePack(
    identity_terms=("securities and exchange commission", "form 10-k"),
    shape_terms=(
        "aggregate market value",
        "non-affiliates",
        "shares outstanding",
        "washington, d.c. 20549",
        "commission file number",
    ),
    labels=("table of contents", "part i", "item 1"),
    cover_end_terms=(
        "documents incorporated by reference",
        "the following documents are incorporated by reference",
    ),
)
_ANNUAL_BODY_EVIDENCE = BodyEvidencePack(
    structural_headings=(
        "PART I",
        "ITEM 1",
        "ITEM 1A",
        "ITEM 8",
        "ITEM 10",
        "ITEM 15",
    ),
    semantic_headings=(
        "management's discussion and analysis",
        "risk factors",
        "explanatory note",
        "explanatory statement",
        "report of independent registered public accounting firm",
        "report of independent auditors",
        "index to consolidated financial statements",
    ),
)

_PAGE = "\n<PAGE>\n"


def _doc(*parts: str) -> str:
    return "".join(parts)


def test_amendment_transition_fires_on_explanatory_note() -> None:
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nEXPLANATORY NOTE\n\n"
        "This amendment is being filed solely to correct the date on the auditor's report.\n",
        "\nITEM 15. EXHIBITS, FINANCIAL STATEMENT SCHEDULES\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    lines = text.splitlines()
    explanatory_line = next(i for i, ln in enumerate(lines) if "EXPLANATORY NOTE" in ln)
    assert boundary.end_line <= explanatory_line + 2
    assert boundary.method is BoundaryMethod.FALLBACK
    assert boundary.confidence >= 0.60


def test_explanatory_note_transition_is_detected_case_insensitively() -> None:
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nExplanatory Note\n\n"
        "This amendment corrects a typographical error in the filing.\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" in ev_names


def test_amendment_transition_fires_on_report_of_independent_auditors() -> None:
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nREPORT OF INDEPENDENT AUDITORS\n\n"
        "The Board of Directors\n"
        "Acme Corp\n\n"
        "We have audited the accompanying balance sheets of Acme Corp.\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" in ev_names


def test_amendment_transition_fires_on_report_of_independent_registered_firm() -> None:
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nReport of Independent Registered Public Accounting Firm\n\n"
        "To the stockholders of Acme Corp:\n"
        "In our opinion, the financial statements present fairly.\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" in ev_names


def test_amendment_transition_fires_on_signatures() -> None:
    """A short amendment filing has no full body, so SIGNATURES ends the cover."""
    text = _doc(
        _COVER_BODY,
        "\nPortions of the Prospectus are incorporated by reference into Parts II, "
        "III and IV of this Annual Report on Form 10-K.\n",
        _PAGE,
        "\nSIGNATURES\n\n"
        "Pursuant to the requirements of Section 13 or 15(d) of the Securities\n"
        "Exchange Act of 1934, the Registrant has duly caused this report to be\n"
        "signed on its behalf by the undersigned thereunto duly authorized.\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" in ev_names


def test_amendment_transition_is_suppressed_without_cover_identity() -> None:
    text = "Some filler text.\n\nEXPLANATORY NOTE\n\nThis is a note.\n"
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" not in ev_names


def test_standard_10k_resolves_via_part_i_not_amendment_transition() -> None:
    text = _doc(
        _COVER_HEAD
        + "The following documents are incorporated by reference into this report.\n"
        "Item 1. Business\n"
        "Item 1A. Risk Factors\n",
        "\nPART I\n",
        "\nITEM 1. BUSINESS\n",
        "\nThe company manufactures precision instruments worldwide.\n",
    )
    boundary = find_cover_boundary(
        text,
        _POLICY,
        cover_evidence=_ANNUAL_COVER_EVIDENCE,
        body_evidence=_ANNUAL_BODY_EVIDENCE,
    )
    assert boundary.end_line is not None
    ev_names = {ev.name for ev in boundary.evidence}
    assert "amendment_transition" not in ev_names


def test_body_start_resolves_after_amendment_cover_explanatory_note() -> None:
    profile = build_annual_profile("10-K")
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nEXPLANATORY NOTE\n\n"
        "This amendment is being filed solely to correct the date on the "
        "auditor's report and the reference to that date in the consent of "
        "auditors filed as exhibit 23 to this report.\n",
        "\nITEM 15. EXHIBITS, FINANCIAL STATEMENT SCHEDULES\n",
    )
    boundary = find_cover_boundary(
        text,
        profile.boundary,
        cover_evidence=profile.cover_evidence,
        body_evidence=profile.body_evidence,
    )
    bs = find_body_start(text, boundary.end_line, None, profile.body_evidence)
    assert bs.line is not None, (
        f"body_start not found; rejections: {bs.rejection_reasons}"
    )
    assert bs.confidence >= 0.6


def test_body_start_resolves_after_amendment_cover_auditor_report() -> None:
    profile = build_annual_profile("10-K")
    text = _doc(
        _COVER_BODY,
        _PAGE,
        "\nREPORT OF INDEPENDENT AUDITORS\n\n"
        "We have audited the accompanying balance sheets of Acme Corp as of "
        "December 31, 2003 and 2002, and the related statements of operations, "
        "stockholders' equity, and cash flows for each of the three years in "
        "the period ended December 31, 2003. In our opinion, the financial "
        "statements present fairly.\n",
    )
    boundary = find_cover_boundary(
        text,
        profile.boundary,
        cover_evidence=profile.cover_evidence,
        body_evidence=profile.body_evidence,
    )
    bs = find_body_start(text, boundary.end_line, None, profile.body_evidence)
    assert bs.line is not None, (
        f"body_start not found; rejections: {bs.rejection_reasons}"
    )
    assert bs.confidence >= 0.6


__all__: list[str] = []
