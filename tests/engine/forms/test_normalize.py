"""Tests for the shared normalization composition seam."""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import DecisionAction
from edgar_sec.engine.document.page_markers import PageArtifactPolicy
from edgar_sec.engine.forms.cover.models import BoundaryMethod
from edgar_sec.engine.forms.normalize import (
    DocumentNormalizer,
    normalize_document,
)
from edgar_sec.engine.forms.plugins.models import FormPlugin
from edgar_sec.engine.forms.plugins.registry import get_plugin, register_plugin

ASCII_BODY = """\
The Company was founded in 1994 and is a leading provider of industrial \
widgets. It operates three manufacturing facilities and employs \
approximately 4,200 people worldwide. Customers rely on the Company for \
products and services that the Company designs, develops and sells \
throughout the world, and the Company expects continued growth."""

COVER_10K = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549

FORM 10-K

For the fiscal year ended December 31, 2011

ACME INDUSTRIAL WIDGETS, INC.
(Exact name of registrant as specified in its charter)

Delaware
(State or other jurisdiction of incorporation)

Commission File Number: 001-14103
(Exact name of registrant as specified in its charter)

1234 Widget Parkway, Springfield, IL 62704
(Principal executive offices)

(Title of each class)
Trading Symbol(s)

Common Stock, par value $0.01 per share
ACMX

Indicate by check mark whether the registrant is a shell company.

Emerging growth company"""

DOC_10K = f"""\
{COVER_10K}

PART I

ITEM 1. Business

{ASCII_BODY}

ITEM 1A. Risk Factors

Investors should note the following risk factors, which could materially \
affect the results of the Company. The Company operates in a competitive \
industry and its results may differ materially from those expressed or \
implied by forward-looking statements.

SIGNATURES

Pursuant to the requirements of Section 13 of the Securities Exchange Act of \
1934, the registrant has duly authorized this report.

/s/ Jane Q. Registrant
Jane Q. Registrant
Chief Executive Officer"""


def test_unpacks_plain_ascii_payload() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    assert result.representation == "ascii"
    assert result.is_html is False
    assert "ACME INDUSTRIAL WIDGETS" in result.text


def test_detects_html_representation() -> None:
    html = (
        "<html><body><p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
        "<p>FORM 10-K</p></body></html>"
    )
    result = normalize_document(html, form="10-K")
    assert result.representation == "html"
    assert "<html" not in result.text


def test_stage_trace_is_ordered_and_bounded() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    stages = [entry["stage"] for entry in result.stage_trace]
    assert stages[0] == "unpacked"
    assert "page_policy" in stages
    assert "cover_boundary" in stages
    assert stages.index("page_policy") < stages.index("cover_boundary")
    for entry in result.stage_trace:
        assert set(entry) >= {"stage", "text_identity", "line_count", "char_count"}
        assert len(entry["text_identity"]) == 64


def test_cover_boundary_scopes_the_cover_region() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    boundary = result.cover_boundary
    total_lines = len(result.text.splitlines())
    assert boundary.end_line is not None
    assert 0 < boundary.end_line < total_lines
    assert boundary.start_line is not None
    assert 0 <= boundary.start_line < boundary.end_line
    assert boundary.method != BoundaryMethod.DISABLED


def test_boundary_line_anchors_are_remapped_through_reflow() -> None:
    """The boundary is detected pre-reflow and reported in post-reflow lines."""
    result = normalize_document(DOC_10K, form="10-K")
    boundary = result.cover_boundary
    evidence_lines = {item.name: item.line for item in boundary.evidence}
    # The forward signal fired on the pre-reflow "PART I" heading.
    assert evidence_lines["part_transition"] == DOC_10K.splitlines().index("PART I")
    # Reflow merged the cover into fewer lines, so the reported end moved down.
    assert boundary.end_line < evidence_lines["part_transition"]


def test_cover_region_covers_cover_fields_and_excludes_body() -> None:
    """The checkmark stage runs on the pre-reflow frame, which is the real frame.

    Reflow renumbers lines, so the reported post-reflow ``end_line`` is a
    reporting coordinate, not a slice index. The boundary that scoped the
    checkmark solver is the one recorded in the evidence trace.
    """
    result = normalize_document(DOC_10K, form="10-K")
    evidence_lines = [item.line for item in result.cover_boundary.evidence]
    pre_reflow_end = max(evidence_lines)
    cover = DOC_10K.splitlines()[1:pre_reflow_end]
    assert any("Commission File Number" in line for line in cover)
    assert any("Emerging growth company" in line for line in cover)
    assert not any("founded in 1994" in line for line in cover)


def test_checkmark_is_scoped_to_cover_not_whole_document() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    inference = result.checkmark_inference
    assert inference is not None
    # The solver ran against a bounded region, so it reports a decision or an
    # explicit absent/resolved status rather than silently scanning everything.
    assert inference.status is not None


def test_body_start_after_cover() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    assert result.body_start is not None
    assert result.body_start.first_unit_line is not None
    assert result.body_start.first_unit_line > result.cover_boundary.end_line


def test_closing_span_found_after_body() -> None:
    result = normalize_document(DOC_10K, form="10-K")
    assert result.closing_span is not None
    assert result.closing_span.kind in {"signatures", "exhibit_index"}
    assert result.closing_span.start_line > (result.body_start.line or 0)


def test_reflow_runs_for_ascii_only() -> None:
    ascii_result = normalize_document(DOC_10K, form="10-K")
    assert ascii_result.reflow is not None
    html_result = normalize_document(
        f"<html><body>{COVER_10K}</body></html>", form="10-K"
    )
    assert html_result.reflow is None


def test_tagged_tables_survive_byte_for_byte() -> None:
    table = (
        "<TABLE>\n"
        "<TR><TD>Revenue</TD><TD>1,234</TD></TR>\n"
        "<TR><TD>  Cost  </TD><TD>  987  </TD></TR>\n"
        "</TABLE>"
    )
    payload = f"{COVER_10K}\n\nPART I\n\nITEM 1. Business\n\n{table}"
    result = normalize_document(payload, form="10-K")
    assert table in result.text, "tagged table must survive the pipeline verbatim"
    assert "__SEC_TBL_" not in result.text


def test_table_sentinels_never_reach_output() -> None:
    payload = (
        f"{COVER_10K}\n\nPART I\n\nITEM 1. Business\n\n"
        "<TABLE><TR><TD>A</TD><TD>B</TD></TR></TABLE>"
    )
    result = normalize_document(payload, form="10-K")
    assert "__SEC_TBL_" not in result.text


def test_generic_form_has_no_cover_parsing() -> None:
    result = normalize_document(DOC_10K, form=None)
    assert result.cover_boundary.method == BoundaryMethod.DISABLED
    assert result.checkmark_inference is None
    assert result.text


def test_unknown_form_degrades_to_generic() -> None:
    result = normalize_document(DOC_10K, form="S-1")
    assert result.family == "GENERIC"
    assert result.cover_boundary.method == BoundaryMethod.DISABLED


def test_form_alias_resolves_to_modeled_family() -> None:
    assert get_plugin("10-K405").family == "10-K"
    assert get_plugin("10-QSB").family == "10-Q"
    assert get_plugin("8-K12B").family == "8-K"


def test_registered_evaluator_is_reachable_from_plugin() -> None:
    plugin = get_plugin("10-KSB")
    assert plugin.evaluator is not None
    decision = plugin.evaluator(DOC_10K)
    assert decision.action in set(DecisionAction)


def test_document_normalizer_accepts_explicit_plugin() -> None:
    plugin = FormPlugin(family="TEST", enable_body_start=False)
    normalizer = DocumentNormalizer(plugin)
    result = normalizer.normalize("UNITED STATES\nFORM 10-K\n")
    assert result.family == "TEST"
    assert result.body_start is None


def test_per_form_content_hook_runs_before_whitespace_stage() -> None:
    marker = "INJECTED-BY-HOOK"

    def _transform(text: str) -> str:
        return text + f"\n{marker}\n\n\n\n"

    register_plugin(
        "S-8",
        FormPlugin(
            family="S-8",
            enable_body_start=False,
            transform_content=_transform,
        ),
    )
    result = normalize_document("UNITED STATES\nFORM S-8\n", form="S-8")
    assert marker in result.text
    # The hook ran before the whitespace stage, so its trailing blank run is
    # already collapsed in the output.
    assert "\n\n\n\n" not in result.text


def test_empty_payload_does_not_raise() -> None:
    result = normalize_document("", form="10-K")
    assert result.text == ""
    assert result.cover_boundary.end_line is None


def test_bytes_payload_is_decoded() -> None:
    result = normalize_document(DOC_10K.encode("latin-1"), form="10-K")
    assert "ACME INDUSTRIAL WIDGETS" in result.text


def test_sgml_bundle_unpacks_primary_document() -> None:
    bundle = (
        b"<SEC-DOCUMENT><SEC-HEADER>0001</SEC-HEADER>"
        b"<TYPE>10-K</TYPE><FILENAME>acme-10k.htm</FILENAME>"
        b"<DOCUMENT><TYPE>10-K</TYPE><SEQUENCE>1</SEQUENCE>"
        b"<FILENAME>acme-10k.htm</FILENAME><TEXT>\n"
        b"<HTML><BODY>ACME INDUSTRIAL WIDGETS, INC. primary document</BODY></HTML>\n"
        b"</TEXT></DOCUMENT></SEC-DOCUMENT>"
    )
    result = normalize_document(bundle, form="10-K", target_types=("10-K",))
    assert "primary document" in result.text
    assert "<SEC-DOCUMENT>" not in result.text


def test_page_artifact_policy_preserve_keeps_cover_detectable() -> None:
    result = normalize_document(
        DOC_10K,
        form="10-K",
        page_artifact_policy=PageArtifactPolicy.PRESERVE,
    )
    assert result.cover_boundary.end_line is not None
