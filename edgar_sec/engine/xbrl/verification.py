"""Rendered form ground-truth verifier and double-counting detector."""

from __future__ import annotations

from dataclasses import dataclass
from edgar_sec.engine.tables.numeric_cells import ALL_CURRENCY_SYMBOLS, is_numeric_cell
from edgar_sec.engine.xbrl.models import ConceptBreakdown
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
        target_loc = breakdown.target_concept.split(":")[-1].lower()
        has_parent_in_children = any(
            target_loc == c.identifier.split(":")[-1].lower()
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

        disc = abs(derived_val - printed_val) if printed_val is not None else 0.0
        is_valid = not is_double_counted and (printed_val is None or disc < 1.0)

        return RenderedVerificationResult(
            target_label=target_label,
            is_valid=is_valid,
            is_double_counted=is_double_counted,
            printed_value=printed_val,
            derived_value=derived_val,
            discrepancy=round(disc, 4),
            message=message,
        )
