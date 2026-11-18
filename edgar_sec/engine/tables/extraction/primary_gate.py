"""Primary hard gates: necessary-section completeness per claim.

A primary family's claim stands only when every necessary core
section is present over the claim geometry's statement cluster;
a missing section removes the claim and records the gate.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from edgar_sec.foundation.text.dates import (
    STRICT_MONTH_PATTERN,
    STRICT_YEAR_TOKEN_PATTERN,
)

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.competition import (
        CompetitionResult,
        GeometryText,
    )

GATE_SETS: dict[str, tuple[str, ...]] = {
    "balance_sheet": ("assets", "liabilities", "equity"),
    "cash_flow": ("operating", "investing", "financing", "cash_reconciliation"),
    "income_statement": (
        "revenues",
        "costs_expenses",
        "other_nonoperating",
        "net_income_close",
    ),
    "equity_statement": (
        "beginning_balances",
        "in_period_activity",
        "ending_balances",
    ),
    "comprehensive_income": (
        "net_income",
        "oci_components",
        "total_comprehensive_income",
    ),
    "combined_operations_ci": (
        "revenues",
        "costs_expenses",
        "other_nonoperating",
        "net_income_close",
        "total_comprehensive_income",
    ),
}

MEASURE_EXTRA: dict[str, tuple[str, ...]] = {
    "income_statement": ("income_tax",),
}

_DATE = rf"(?:{STRICT_MONTH_PATTERN})\s+\d{{1,2}},?\s+(?:{STRICT_YEAR_TOKEN_PATTERN})"
_DATE_NOYEAR = (
    rf"(?:{STRICT_MONTH_PATTERN})\s+\d{{1,2}},?(?:\s+{STRICT_YEAR_TOKEN_PATTERN})?"
)

_NET_CLOSE = (
    r"^net (income|loss|earnings)\b",
    r"^net \((income|loss)\)",
    r"^consolidated net (income|loss|earnings)\b",
)

# Per-section stub patterns (regex, searched case-insensitively over a
# single stub). A section is present iff any stub matches any pattern.
PATTERNS: dict[str, tuple[str, ...]] = {
    # --- balance_sheet ---
    "assets": (
        r"^assets\s*:?$",
        r"^assets and\b",
        r"^current assets\b",
        r"total.*\bassets\b",
    ),
    "liabilities": (
        r"^liabilities\s*:?$",
        r"^liabilities and\b",
        r"^current liabilities\b",
        r"^(long-term|non-current|noncurrent) liabilities\b",
        r"total.*\bliabilities\b",
    ),
    "equity": (
        r"(stockholder|shareholder|member|partner)s?'? (equity|deficit)\b",
        r"(stockholder|shareholder|member|partner)s?'? \(deficit\) equity",
        r"\btotal equity\b",
        r"^equity\s*:?$",
        r"\bliabilities and equity\b",
        r"\btotal capital\b",
        r"^capital\s*:?$",
        r"\bliabilities and capital\b",
        r"trust corpus",
        r"\btotal net assets\b",
        r"^net assets\s*:?$",
    ),
    # --- cash_flow ---
    "operating": (
        r"cash flows? from operating activities",
        r"net cash\b.*\boperating activities",
        r"^operating activities\s*:?$",
    ),
    "investing": (
        r"cash flows? from investing activities",
        r"net cash\b.*\binvesting activities",
        r"^investing activities\s*:?$",
    ),
    "financing": (
        r"cash flows? from financing activities",
        r"net cash\b.*\bfinancing activities",
        r"^financing activities\s*:?$",
    ),
    "cash_reconciliation": (
        r"cash.*\b(beginning|end) of (the )?(period|year)\b",
        r"^(beginning|end) of (the )?(period|year)\s*:?$",
        r"net (increase|decrease|change) in cash\b",
        r"(increase|decrease)\)? in cash\b",
    ),
    # --- income_statement ---
    "revenues": (
        r"^total (net )?(revenues?|sales)\b",
        r"^revenues?\b",
        r"\brevenues?\s*:?$",
        r"^net sales\b",
        r"\bsales\s*:?$",
        r"^interest income\b",
        r"^total interest income\b",
        r"^net interest income\b",
        r"total interest and dividend income",
    ),
    "costs_expenses": (
        r"^(total )?operating expenses\b",
        r"^expenses\s*:?$",
        r"^total expenses\b",
        r"\bcosts? and expenses\b",
        r"^cost of (sales|revenues?|goods sold|services)\b",
        r"^cost of\b.*\bsold\b",
        r"total cost of\b",
        r"non-?interest expense",
    ),
    "other_nonoperating": (
        r"^other (income|expenses?)\b",
        r"other (income|expense), net",
        r"^other \((income|expense)\) (income|expense)\b",
        r"^other (income|expense) \((income|expense)\)",
        r"interest and other (income|expense)",
        r"^other, net",
        r"total other (income|expense)\b",
        r"other nonoperating",
        r"non-?operating (income|expense)",
        r"^nonoperating\b",
        r"^interest expense\b",
        r"^interest income\b",
        r"other noninterest (income|expense)",
        r"investment and other income",
    ),
    "income_tax": (
        r"income tax (expense|benefit)",
        r"provision( \(benefit\))? for income taxes",
        r"provision for income tax\b",
        r"benefit from \(provision for\) income taxes",
        r"^income taxes\s*:?$",
        r"^tax expense\b",
        r"income tax provision",
    ),
    "net_income_close": _NET_CLOSE,
    # --- comprehensive_income ---
    "net_income": _NET_CLOSE,
    "oci_components": (
        r"other comprehensive",
        r"foreign currency translation",
        r"unrealized (gain|gains|loss|losses) on\b",
        r"unrealized holding gains?\b",
        r"reclassification adjustment",
        r"adjustments? for (pension|postretirement|post-employment)",
    ),
    "total_comprehensive_income": (
        r"comprehensive (income|loss)\b",
        r"comprehensive \((income|loss)\) (income|loss)\b",
        r"comprehensive \((income|loss)\)",
    ),
    # --- equity_statement (lexical legs; dated rows handled in code) ---
    "beginning_balances": (
        r"beginning of (the )?(year|period)",
        r"beginning balance",
        r"^balance.*\bbeginning\b",
    ),
    "ending_balances": (
        r"end of (the )?(year|period)",
        r"ending balance",
        r"^balance.*\bend of\b",
    ),
    "in_period_activity": (
        r"net income",
        r"net loss",
        r"net earnings",
        r"comprehensive income",
        r"comprehensive loss",
        r"other comprehensive",
        r"dividend",
        r"compensation",
        r"issuance",
        r"\bissued\b",
        r"sale of",
        r"repurchase",
        r"treasury",
        r"warrant",
        r"exercise",
        r"contribution",
        r"distribution",
        r"conversion",
        r"cumulative effect",
        r"adjustment",
        r"adoption",
        r"allocation",
        r"acquisition",
        r"retirement of",
        r"forfeit",
        r"\bvest",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern, ...]] = {
    section: tuple(re.compile(p, re.IGNORECASE) for p in pats)
    for section, pats in PATTERNS.items()
}

_DATE_ROW = re.compile(_DATE, re.IGNORECASE)
_DATE_ROW_NOYEAR = re.compile(_DATE_NOYEAR, re.IGNORECASE)
_DATE_EXclusions = ("ended", "for the", "per share", "months", "quarter")


def _fold(stub: str) -> str:
    return stub.replace("’", "'").strip()


def _is_dated_balance_row(stub: str) -> bool:
    text = _fold(stub)
    low = text.lower()
    if any(word in low for word in _DATE_EXclusions):
        return False
    match = _DATE_ROW.search(text)
    if match is not None:
        if "balance" in low or "as of" in low:
            return True
        if match.start() == 0 and match.end() == len(text):
            return True
        return match.end() == len(text)
    match = _DATE_ROW_NOYEAR.search(text)
    if match is not None and ("balance" in low or "as of" in low):
        return True
    return False


def section_presence(stubs, family: str) -> dict[str, bool]:
    folded = [_fold(s) for s in stubs]
    sections = list(GATE_SETS[family]) + list(MEASURE_EXTRA.get(family, ()))
    presence: dict[str, bool] = {}
    dated_rows = [i for i, s in enumerate(folded) if _is_dated_balance_row(s)]
    for section in sections:
        pats = _COMPILED[section]
        hit = any(p.search(s) for p in pats for s in folded)
        if section == "total_comprehensive_income":
            hit = any(
                p.search(s)
                for p in pats
                for s in folded
                if "other comprehensive" not in s.lower()
            )
        if family == "equity_statement":
            if section == "beginning_balances":
                hit = hit or len(dated_rows) >= 1
            elif section == "ending_balances":
                hit = hit or len(dated_rows) >= 2
        presence[section] = bool(hit)
    return presence


def missing_sections(stubs, family: str) -> list[str]:
    presence = section_presence(stubs, family)
    return [s for s in GATE_SETS[family] if not presence[s]]


def statement_clusters(
    geometries: tuple[GeometryText, ...] | list[GeometryText],
) -> list[tuple[int, ...]]:
    """Each geometry's statement cluster, as member index tuples.

    A cluster is a maximal run of consecutive geometries sharing
    one home (section_item, note_title) and one head caption.
    """
    clusters: list[tuple[int, ...]] = [()] * len(geometries)
    run: list[int] = []
    run_home: tuple[str | None, str | None] | None = None
    run_caption = ""

    def close_run() -> None:
        members = tuple(run)
        for member in run:
            clusters[member] = members

    for index, geometry in enumerate(geometries):
        home = (geometry.section_item, geometry.note_title)
        caption = geometry.caption.strip()
        joins = (
            bool(run) and home == run_home and (not caption or caption == run_caption)
        )
        if not joins:
            close_run()
            run = []
            run_home = home
            run_caption = caption
        run.append(index)
    close_run()
    return clusters


def apply_primary_gate(
    geometries: tuple[GeometryText, ...] | list[GeometryText],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Final compete_filing pass: refuse gate-incomplete claims.

    For each claimed family with a gate set, missing necessary
    sections over the claim geometry's cluster remove the claim.
    """
    from edgar_sec.engine.tables.extraction.competition import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    clusters = statement_clusters(geometries)
    gated: list[CompetitionResult] = []
    for index, result in enumerate(results):
        targets = [family for family in result.claims if family in GATE_SETS]
        if not targets:
            gated.append(result)
            continue
        stubs = tuple(
            stub for member in clusters[index] for stub in geometries[member].stubs
        )
        refused = {
            family: missing
            for family in targets
            if (missing := missing_sections(stubs, family))
        }
        if not refused:
            gated.append(result)
            continue
        scores = dict(result.scores)
        for family, missing in refused.items():
            score = scores.get(family)
            if score is None:
                continue
            detail = "primary gate: missing " + ", ".join(missing)
            scores[family] = FamilyScore(
                score.family,
                score.total,
                dict(score.by_channel),
                score.evidence + (ClaimEvidence("gate", detail, 0.0),),
            )
        gated.append(
            CompetitionResult(
                claims=tuple(f for f in result.claims if f not in refused),
                contested=tuple(f for f in result.contested if f not in refused),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family not in refused),
            )
        )
    return gated
