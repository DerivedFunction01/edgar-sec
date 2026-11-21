"""Rendered form ground-truth verifier and double-counting detector."""

from __future__ import annotations

from dataclasses import dataclass
from edgar_sec.engine.tables.numeric_cells import ALL_CURRENCY_SYMBOLS, is_numeric_cell
from edgar_sec.engine.xbrl.schema.models import (
    ConceptBreakdown,
    qname_local,
)
from edgar_sec.foundation.text.patterns import RE_DOT_LEADER


@dataclass(frozen=True, slots=True)
class RenderedVerificationResult:
    """Outcome of verifying derived financial components against rendered form."""

    target_label: str
    is_valid: bool
    is_double_counted: bool
    printed_value: float | None
    derived_value: float | None
    discrepancy: float
    message: str = ""
    line_number: int | None = None
    citation: str = ""


class DoubleCountVerifier:
    """Verifies that derived breakdowns match rendered tables without double-counting."""

    @staticmethod
    def _parse_clean_float(cand: str) -> float | None:
        """Parse clean numerical float from candidate cell."""
        clean = cand
        for sym in ALL_CURRENCY_SYMBOLS:
            if sym in clean:
                clean = clean.replace(sym, "")
        clean = clean.replace(",", "").strip()
        if clean.startswith("(") and clean.endswith(")"):
            try:
                return -float(clean[1:-1].strip())
            except ValueError:
                return None
        try:
            return float(clean)
        except ValueError:
            return None

    @classmethod
    def extract_printed_row_value(
        cls,
        rendered_text: str,
        target_label: str,
    ) -> float | None:
        """Locate target label in rendered text and parse printed numerical amount."""
        label_lower = target_label.lower()
        for line in rendered_text.splitlines():
            line_lower = line.lower()
            if label_lower not in line_lower:
                continue
            idx = line_lower.find(label_lower)
            tail = RE_DOT_LEADER.sub(" ", line[idx + len(target_label) :])
            tail_s = tail.strip()
            if is_numeric_cell(tail_s):
                val = cls._parse_clean_float(tail_s)
                if val is not None:
                    return val
            tokens = tail.split()
            for i in range(len(tokens)):
                for length in (4, 3, 2, 1):
                    if i + length <= len(tokens):
                        cand = " ".join(tokens[i : i + length])
                        if is_numeric_cell(cand):
                            val = cls._parse_clean_float(cand)
                            if val is not None:
                                return val
        return None

    @classmethod
    def extract_cited_row_value(
        cls,
        rendered_text: str,
        target_label: str,
        *,
        line_number: int,
        line_range: tuple[int, int],
        column_index: int = 0,
        expected_snippet: str | None = None,
    ) -> tuple[float | None, str]:
        """Read one labelled numeric cell from a pinned line and table column."""
        if line_number < line_range[0] or line_number > line_range[1]:
            return None, "Citation line is outside the declared table range."
        lines = rendered_text.splitlines()
        if line_number < 1 or line_number > len(lines):
            return None, "Citation line does not exist in the rendered text."
        line = lines[line_number - 1]
        if expected_snippet is not None and line.strip() != expected_snippet.strip():
            return None, "Citation snippet does not match the rendered line."
        label_index = line.casefold().find(target_label.casefold())
        if label_index < 0:
            return None, "Citation line does not contain the expected row label."
        tail = RE_DOT_LEADER.sub(" ", line[label_index + len(target_label) :])
        tokens = tail.split()
        cells: list[tuple[float, str]] = []
        index = 0
        while index < len(tokens):
            parsed = None
            for width in range(min(4, len(tokens) - index), 0, -1):
                candidate = " ".join(tokens[index : index + width])
                if is_numeric_cell(candidate):
                    value = cls._parse_clean_float(candidate)
                    if value is not None:
                        parsed = (value, candidate)
                        index += width
                        break
            if parsed is None:
                index += 1
            else:
                cells.append(parsed)
        if column_index < 0 or column_index >= len(cells):
            return None, "Requested period column is absent from the cited row."
        return cells[column_index][0], cells[column_index][1]

    @classmethod
    def verify_cited_row(
        cls,
        rendered_text: str,
        target_label: str,
        expected_value: float,
        *,
        line_number: int,
        line_range: tuple[int, int],
        scale: float = 1.0,
        column_index: int = 0,
        expected_snippet: str | None = None,
        tolerance: float | None = None,
        display_sign: float = 1.0,
    ) -> RenderedVerificationResult:
        printed_value, cell_text = cls.extract_cited_row_value(
            rendered_text,
            target_label,
            line_number=line_number,
            line_range=line_range,
            column_index=column_index,
            expected_snippet=expected_snippet,
        )
        if printed_value is None:
            return RenderedVerificationResult(
                target_label=target_label,
                is_valid=False,
                is_double_counted=False,
                printed_value=None,
                derived_value=expected_value,
                discrepancy=float("inf"),
                message=cell_text,
                line_number=line_number,
            )

        lines = rendered_text.splitlines()
        decimals = len(cell_text.partition(".")[2].rstrip(")"))
        allowed = tolerance
        if allowed is None:
            allowed = 0.5 * scale / (10**decimals)
        discrepancy = abs(printed_value * scale * display_sign - expected_value)
        valid = discrepancy <= allowed
        return RenderedVerificationResult(
            target_label=target_label,
            is_valid=valid,
            is_double_counted=False,
            printed_value=printed_value,
            derived_value=expected_value / scale,
            discrepancy=round(discrepancy, 4),
            message=(
                "Rendered row matches the expected value."
                if valid
                else "Rendered row value differs from the expected value."
            ),
            line_number=line_number,
            citation=f"line {line_number}: {lines[line_number - 1].strip()}",
        )

    @classmethod
    def verify_breakdown(
        cls,
        rendered_text: str,
        breakdown: ConceptBreakdown,
        target_label: str,
    ) -> RenderedVerificationResult:
        """Verify breakdown components against rendered table preventing double-counting."""
        printed_val = cls.extract_printed_row_value(rendered_text, target_label)
        comp_sum = sum(c.value * c.weight for c in breakdown.components)
        derived_val = (
            breakdown.total_value if breakdown.total_value is not None else comp_sum
        )

        # Detect parent inclusion among children
        target_loc = qname_local(breakdown.target_concept).lower()
        has_parent_in_children = any(
            target_loc == qname_local(c.identifier).lower()
            for c in breakdown.components
        )

        # Detect gross and net conflation
        has_gross = any("gross" in c.identifier.lower() for c in breakdown.components)
        has_net = any("net" in c.identifier.lower() for c in breakdown.components)
        has_offset = any(c.weight < 0 for c in breakdown.components)
        gross_net_conflation = has_gross and has_net and not has_offset

        # Detect 2x double counting
        is_double_counted = False
        message = "Verified against rendered table"

        if has_parent_in_children:
            is_double_counted = True
            message = (
                "DOUBLE_COUNTING_DETECTED: target parent included among components"
            )
        elif gross_net_conflation:
            is_double_counted = True
            message = (
                "DOUBLE_COUNTING_DETECTED: gross and net aggregated without offset"
            )
        elif printed_val is not None and abs(comp_sum - (2.0 * printed_val)) < 1.0:
            is_double_counted = True
            message = "DOUBLE_COUNTING_DETECTED: component sum equals 2x printed total"
        elif printed_val is None:
            message = "Rendered row was not found; breakdown is unverified."

        disc = (
            abs(derived_val - printed_val) if printed_val is not None else float("inf")
        )
        is_valid = not is_double_counted and printed_val is not None and disc < 1.0

        return RenderedVerificationResult(
            target_label=target_label,
            is_valid=is_valid,
            is_double_counted=is_double_counted,
            printed_value=printed_val,
            derived_value=derived_val,
            discrepancy=round(disc, 4),
            message=message,
        )
