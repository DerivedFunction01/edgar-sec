"""XBRL-alignment labelling for body table geometries.

Ported verbatim in method and data from the taxonomy corpus lane
(align.py + the labelling decision procedure in its build.py), where
the method was stated in the corpus record before application: a
geometry's numeric cells and a solved role's fact values are compared
as significant-digit strings, so a value printed in thousands matches
the as-filed fact at any power-of-ten scale. Cells whose digits are a
bare year (1990-2030) and digit strings shorter than 3 are excluded.
A geometry takes a family when the best family's score is >= 0.60,
>= 2 of its row labels token-match the role's row labels, and the
best score is >= 2x the runner-up (or the runner-up is <= 0.30).
Schedule note groups label through a structural signature per family;
a geometry that aligns to a group but matches no signature stays
unlabelled for adjudication. When a filing has XBRL and nothing
aligns >= 0.25, the geometry is labelled ``other``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.foundation.text.dates import YEAR_TOKEN_RE
from edgar_sec.foundation.text.words import word_tokens


def sig_digits(value: object) -> str | None:
    """Significant digit string of a number, scale-free; None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        dec = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if dec == 0 or not dec.is_finite():
        return None
    digits = "".join(ch for ch in format(dec.normalize(), "f") if ch.isdigit())
    digits = digits.strip("0")
    if len(digits) < 3:
        return None
    return digits


def cell_digits(text: str) -> str | None:
    """Significant digits of a printed table cell, via the common parser."""
    if YEAR_TOKEN_RE.fullmatch((text or "").strip()):
        return None
    value = clean_numeric(text)
    if value is None:
        return None
    return sig_digits(value)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in word_tokens(text or "") if len(t) >= 3)


_STATEMENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cash_flow", ("cash flow", "cash flows")),
    ("balance_sheet", ("balance sheet", "financial position", "financial condition")),
    (
        "equity_statement",
        ("equity", "stockholders", "shareholders", "partners capital", "changes in capital"),
    ),
    (
        "income_statement",
        ("operations", "income statement", "statements of income", "earnings"),
    ),
)

_GROUP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("aoci", ("accumulated other comprehensive",)),
    ("fair_value", ("fair value",)),
    ("pension", ("pension", "postretirement", "defined benefit", "retirement benefit")),
    ("derivatives", ("derivative", "hedging", "hedge instruments")),
    ("debt", ("debt", "borrowings", "notes payable", "indebtedness", "credit agreement")),
    ("tax", ("income tax", "income taxes", "tax provision")),
    ("lease", ("leases", "operating lease", "finance lease", "lessee")),
    ("intangibles", ("intangible", "goodwill")),
    ("ppe", ("property and equipment", "property, plant")),
    ("inventory", ("inventor",)),
    (
        "compensation",
        ("stock compensation", "share-based", "stock-based", "equity compensation", "stock option"),
    ),
    ("eps", ("per share",)),
    ("repurchase", ("issuer purchases", "share repurchase program")),
    ("labor", ("collective bargaining", "labor contract", "union")),
)


def role_family(title: str, category: str) -> tuple[str | None, str | None]:
    """Return (statement_family, note_group) for a catalog role title.

    Exactly one of the two is non-None when the role maps at all.
    Comprehensive-income-only roles deliberately map to nothing: the
    registry has no such family, and forcing them into income or
    equity would manufacture labels.
    """
    text = (title or "").lower()
    if "comprehensive income" in text and not any(
        k in text for k in ("operations", "equity", "stockholders", "shareholders")
    ):
        return None, None
    for family, keys in _STATEMENT_RULES:
        if any(k in text for k in keys):
            if (
                family == "income_statement"
                and "comprehensive" in text
                and "operations" not in text
            ):
                continue
            return family, None
    for group, keys in _GROUP_RULES:
        if any(k in text for k in keys):
            return None, group
    return None, None


def _first_cells(rows: tuple[tuple[str, ...], ...]) -> list[str]:
    return [(row[0] if row else "").strip().lower() for row in rows]


def _all_text(rows: tuple[tuple[str, ...], ...]) -> str:
    return " ".join(cell for row in rows for cell in row).lower()


def _period_row_count(rows: tuple[tuple[str, ...], ...]) -> int:
    count = 0
    for first in _first_cells(rows):
        if YEAR_TOKEN_RE.fullmatch(first) or first in {
            "thereafter",
            "total",
            "less: unamortized",
            "less unamortized",
        }:
            count += 1
    return count


def schedule_family(group: str, rows: tuple[tuple[str, ...], ...]) -> str | None:
    """The schedule family for one geometry inside a note group, or None."""
    text = _all_text(rows)
    firsts = _first_cells(rows)
    if group == "debt":
        return "debt_maturity" if _period_row_count(rows) >= 3 else None
    if group == "lease":
        return "lease_maturity" if _period_row_count(rows) >= 3 else None
    if group == "tax":
        if any("deferred" in f for f in firsts):
            return "deferred_tax"
        if "%" in text and any(
            k in text for k in ("statutory", "federal", "effective rate")
        ):
            return "tax_reconciliation"
        return None
    if group == "fair_value":
        header = " ".join(firsts[:3]) + text[:600]
        return "fair_value" if ("level 1" in header or "level 2" in header) else None
    if group == "derivatives":
        return "derivatives_hedging"
    if group == "aoci":
        return "aoci"
    if group == "pension":
        keys = ("benefit obligation", "plan assets", "funded status", "net periodic")
        return "pension" if any(k in text for k in keys) else None
    if group == "intangibles":
        return "intangibles" if ("intangible" in text or "amortization" in text) else None
    if group == "ppe":
        return "ppe"
    if group == "inventory":
        return "inventory"
    if group == "compensation":
        keys = ("outstanding", "exercisable", "granted", "restricted stock")
        return "stock_comp_rollforward" if any(k in text for k in keys) else None
    if group == "eps":
        return "eps_reconciliation" if ("basic" in text and "diluted" in text) else None
    if group == "repurchase":
        return "shares_purchased" if _period_row_count(rows) >= 2 else None
    if group == "labor":
        return None  # no reliable signature; adjudication-only family
    return None


_CF_SECTIONS = ("operating activities", "investing activities", "financing activities")


def statement_signature(rows: tuple[tuple[str, ...], ...]) -> dict[str, object]:
    """Statement-family components visible in one table alone.

    Used where no XBRL roles exist (pre-XBRL filings, unaligned
    geometries): the components propose a candidate family and the
    adjudication queue disposes. Never a final label by itself.
    """
    firsts = [r[0].strip().lower() for r in rows if r and r[0].strip()]
    joined = " ".join(firsts)

    def has(*needles: str) -> bool:
        return any(n in cell for cell in firsts for n in needles)

    components = {
        "revenue_row": has(
            "total revenues", "net revenues", "total revenue", "revenues",
            "net sales", "total sales",
        ),
        "net_income_row": has("net income", "net loss", "net earnings"),
        "total_assets_row": has("total assets"),
        "total_liab_row": has("total liabilities"),
        "equity_total_row": has(
            "total equity", "total stockholders", "total shareholders", "total partners"
        ),
        "cf_sections": sum(1 for s in _CF_SECTIONS if s in joined),
        "net_cash_row": has("net cash", "net increase in cash", "net decrease in cash"),
        "begin_balance_row": has(
            "balance, beginning", "beginning balance", "balance at beginning"
        ),
        "end_balance_row": has("balance, ending", "ending balance", "balance at end"),
    }
    candidate: str | None = None
    if components["revenue_row"] and components["net_income_row"]:
        candidate = "income_statement"
    elif components["total_assets_row"] and (
        components["total_liab_row"] or components["equity_total_row"]
    ):
        candidate = "balance_sheet"
    elif int(components["cf_sections"]) >= 2 and components["net_cash_row"]:
        candidate = "cash_flow"
    elif components["begin_balance_row"] and components["end_balance_row"]:
        candidate = "equity_statement"
    return {"candidate": candidate, "components": components}


def score_geometry(
    rows: tuple[tuple[str, ...], ...],
    role_digit_set: frozenset[str],
    role_label_tokens: frozenset[str],
) -> tuple[float, int]:
    """Return (score, label_hits) of one geometry against one solved role."""
    total = 0
    matched = 0
    for row in rows:
        for cell in row:
            digits = cell_digits(cell)
            if digits is None:
                continue
            total += 1
            if digits in role_digit_set:
                matched += 1
    label_hits = 0
    for row in rows:
        if not row:
            continue
        tokens = _tokens(row[0])
        if tokens and len(tokens & role_label_tokens) >= 2:
            label_hits += 1
    if total == 0:
        return 0.0, label_hits
    return matched / total, label_hits


def _passes(best: tuple[float, int, str], rivals: list[float]) -> bool:
    score, hits, _ = best
    if score < 0.60 or hits < 2:
        return False
    runner = max(rivals) if rivals else 0.0
    return score >= 2.0 * runner or runner <= 0.30


def label_geometries(
    geometries: list[dict], roles: list[dict]
) -> list[dict[str, object]]:
    """Apply the alignment decision procedure to every geometry.

    ``geometries`` carry ``table_index`` and ``rows``; ``roles`` carry
    ``title``, ``family``, ``group`` and solved ``rows`` of
    ``{label, values}``. Labels come back in build format: family /
    provenance / score / reason / top-candidates per geometry.
    """
    prepared = []
    for role in roles:
        digits: set[str] = set()
        label_tokens: set[str] = set()
        for row in role["rows"]:
            for value in row["values"]:
                digits_found = sig_digits(value)
                if digits_found is not None:
                    digits.add(digits_found)
            label_tokens |= _tokens(str(row["label"]))
        prepared.append((role, frozenset(digits), frozenset(label_tokens)))

    labels: list[dict[str, object]] = []
    for geo in geometries:
        rows = tuple(tuple(r) for r in geo["rows"])
        per_family: dict[str, tuple[float, int, str]] = {}
        per_group: dict[str, tuple[float, int, str]] = {}
        for role, digits, label_tokens in prepared:
            if not digits:
                continue
            score, hits = score_geometry(rows, digits, label_tokens)
            fam, group = role["family"], role["group"]
            target = per_family if fam else per_group if group else None
            key = fam or group
            if target is None or key is None:
                continue
            if key not in target or score > target[key][0]:
                target[key] = (score, hits, str(role["title"]))

        fam_rank = sorted(per_family.items(), key=lambda kv: -kv[1][0])
        grp_rank = sorted(per_group.items(), key=lambda kv: -kv[1][0])
        label: dict[str, object] = {
            "table_index": geo["table_index"],
            "family": None,
            "provenance": None,
            "score": None,
            "runner_up": None,
            "reason": None,
            "top": [
                {"kind": "family", "key": k, "score": round(v[0], 3), "role": v[2]}
                for k, v in fam_rank[:2]
            ]
            + [
                {"kind": "group", "key": k, "score": round(v[0], 3), "role": v[2]}
                for k, v in grp_rank[:2]
            ],
        }
        fam_best = fam_rank[0] if fam_rank else None
        grp_best = grp_rank[0] if grp_rank else None
        fam_ok = bool(
            fam_best
            and _passes(
                fam_best[1],
                [v[0] for k, v in fam_rank[1:]] + [v[0] for _, v in grp_rank],
            )
        )
        grp_ok = bool(
            grp_best
            and _passes(
                grp_best[1],
                [v[0] for k, v in grp_rank[1:]] + [v[0] for _, v in fam_rank],
            )
        )
        if fam_ok and (not grp_ok or fam_best[1][0] >= grp_best[1][0]):
            label.update(
                family=fam_best[0],
                provenance="aligned",
                score=round(fam_best[1][0], 3),
            )
        elif grp_ok:
            fam = schedule_family(str(grp_best[0]), rows)
            if fam is not None:
                label.update(
                    family=fam,
                    provenance="signature",
                    score=round(grp_best[1][0], 3),
                )
            else:
                label["reason"] = f"group_unresolved:{grp_best[0]}"
                label["score"] = round(grp_best[1][0], 3)
        else:
            best_any = max(
                [v[0] for _, v in fam_rank] + [v[0] for _, v in grp_rank],
                default=0.0,
            )
            label["score"] = round(best_any, 3)
            label["reason"] = "below_threshold" if best_any >= 0.25 else "no_alignment"
        labels.append(label)
    return labels


def apply_aligned_negative(labels: list[dict], *, is_xbrl: bool) -> list[dict]:
    """The build's post-pass: XBRL present and nothing aligned >= 0.25
    means the geometry is ``other`` by the teacher's own verdict."""
    if not is_xbrl:
        for lab in labels:
            lab["reason"] = "no_xbrl"
        return labels
    for lab in labels:
        if lab["family"] is None and lab["reason"] == "no_alignment":
            lab["family"] = "other"
            lab["provenance"] = "aligned_negative"
            lab["reason"] = None
    return labels


def statement_candidates(
    geometries: list[dict], labels: list[dict]
) -> list[dict[str, object]]:
    """Statement-signature candidates over the unlabelled geometries."""
    candidates: list[dict[str, object]] = []
    for geo, lab in zip(geometries, labels, strict=True):
        if lab["family"] is not None:
            continue
        signature = statement_signature(tuple(tuple(r) for r in geo["rows"]))
        if signature["candidate"]:
            candidates.append(
                {
                    "table_index": geo["table_index"],
                    "candidate": signature["candidate"],
                    "components": signature["components"],
                }
            )
    return candidates
