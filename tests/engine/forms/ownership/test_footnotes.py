from edgar_sec.engine.forms.ownership.footnotes import parse_footnotes
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection, SectionRole
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid


def test_parse_footnotes_collects_entries_across_one_multiline_cell() -> None:
    section = ClassifiedSection(
        role=SectionRole.FOOTNOTES,
        table_index=1,
        raw_node=None,
        resolved_grid=ResolvedGrid(
            rows=(
                (
                    "Explanation of Responses:\n"
                    "  (1) Gift of shares to charitable foundation.\n"
                    "  [2] Shares acquired under the applicable plan.",
                ),
            ),
            column_alignments=(),
            column_widths=(),
        ),
    )

    assert parse_footnotes([section]) == {
        "1": "Gift of shares to charitable foundation.",
        "2": "Shares acquired under the applicable plan.",
    }
