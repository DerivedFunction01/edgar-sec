"""Prose patterns: measured values with calibration provenance."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.registry import (
    PROV_COVERAGE_SEED,
    ProsePatternSpec,
)

PROSE_PATTERNS: tuple[ProsePatternSpec, ...] = (
    ProsePatternSpec("income_statement", "summarizes our results of", "before", 8, 0.8),
    ProsePatternSpec("income_statement", "summarizes our results", "before", 8, 0.8),
    ProsePatternSpec(
        "income_statement", "table summarizes our results", "before", 8, 0.8
    ),
    ProsePatternSpec("other", "table presents", "before", 347, 0.813),
    ProsePatternSpec("other", "presents the", "before", 191, 0.803),
    ProsePatternSpec("other", "transition period", "before", 183, 0.824),
    ProsePatternSpec("other", "table presents the", "before", 167, 0.823),
    ProsePatternSpec("other", "allowance for", "before", 156, 0.808),
    ProsePatternSpec("other", "following table presents the", "before", 149, 0.805),
    ProsePatternSpec("other", "which we", "before", 143, 0.831),
    ProsePatternSpec("other", "by our", "before", 140, 0.814),
    ProsePatternSpec("other", "not applicable", "before", 128, 0.831),
    ProsePatternSpec("other", "during the years", "before", 125, 0.801),
    ProsePatternSpec("other", "table presents", "after", 195, 0.83),
    ProsePatternSpec("other", "our consolidated", "after", 175, 0.862),
    ProsePatternSpec("other", "following table presents", "after", 170, 0.81),
    ProsePatternSpec("other", "the following table presents", "after", 170, 0.81),
    ProsePatternSpec("other", "and our", "after", 166, 0.802),
    ProsePatternSpec("other", "to rule", "after", 153, 0.814),
    ProsePatternSpec("other", "pursuant to rule", "after", 152, 0.822),
    ProsePatternSpec("other", "rule of regulation", "after", 145, 0.838),
    ProsePatternSpec("other", "to rule of", "after", 142, 0.83),
    ProsePatternSpec("other", "pursuant to rule of", "after", 141, 0.829),
    ProsePatternSpec("other", "interactive data", "after", 138, 0.831),
    ProsePatternSpec("other", "allowance for", "after", 137, 0.83),
    ProsePatternSpec("other", "to rule of regulation", "after", 135, 0.833),
    ProsePatternSpec("other", "submitted electronically", "after", 135, 0.833),
    ProsePatternSpec("other", "data file", "after", 134, 0.832),
    ProsePatternSpec("other", "interactive data file", "after", 134, 0.832),
    ProsePatternSpec("other", "every interactive data file", "after", 132, 0.83),
    ProsePatternSpec("other", "every interactive", "after", 132, 0.83),
    ProsePatternSpec(
        "other", "registrant has submitted electronically", "after", 132, 0.83
    ),
    ProsePatternSpec("other", "has submitted", "after", 132, 0.83),
    ProsePatternSpec("other", "has submitted electronically", "after", 132, 0.83),
    ProsePatternSpec("other", "every interactive data", "after", 132, 0.83),
    ProsePatternSpec("other", "registrant has submitted", "after", 132, 0.83),
    ProsePatternSpec("other", "the registrant has submitted", "after", 132, 0.83),
    ProsePatternSpec("other", "file required to be", "after", 131, 0.829),
    ProsePatternSpec("other", "to be submitted", "after", 131, 0.834),
    ProsePatternSpec("other", "required to be submitted", "after", 131, 0.834),
    ProsePatternSpec("other", "data file required to", "after", 131, 0.829),
    ProsePatternSpec("other", "interactive data file required", "after", 131, 0.829),
    ProsePatternSpec("other", "data file required", "after", 131, 0.829),
    ProsePatternSpec(
        "stock_comp_rollforward",
        "aggregate intrinsic value",
        "after",
        3,
        1.0,
        PROV_COVERAGE_SEED,
    ),
    ProsePatternSpec(
        "stock_comp_rollforward", "grant date", "after", 5, 0.833, PROV_COVERAGE_SEED
    ),
    ProsePatternSpec(
        "stock_comp_rollforward",
        "intrinsic value",
        "after",
        4,
        1.0,
        PROV_COVERAGE_SEED,
    ),
    # Step 2: debt_maturity's measured lead-in phrase (the map's
    # leadin channel), re-priced on the v3 base's prose window.
)
