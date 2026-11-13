"""Verdict scoring over assembled assignments, in three accountings:
original counting against the gold label, full-report placement at the
geometry's measured position in the whole, and the original counting
re-graded inside each label-provenance stratum.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from edgar_sec.engine.tables.extraction.assembly import SECOND_SET_TAG
from edgar_sec.engine.tables.extraction.registry import (
    CONTAINMENT_PARENTS,
    CORE_FAMILIES,
    RESIDUAL_FAMILY,
)

ADMITTED_FAMILIES = (
    "subsequent_events",
    "segment_reporting",
    "commitments_contingencies",
    "related_party",
)
STRATA = ("audited", "aligned_negative", "signature", "unlabelled")
PLACED_CATEGORIES = (
    "exact_main",
    "exact_variant",
    "exact_second_set",
    "exact_section",
    "section_of_gold",
    "contained_subset",
    "contained_parent",
    "dual_service",
    "admitted_family",
    "residual",
)
CORE_TERMS = "core: precision >= 0.90 and recall >= 0.85"
FLOOR_TERMS = "schedule floor: support >= 30, precision >= 0.80"


def stratum_of(label: dict | None) -> str:
    """One label's provenance stratum, from its recorded stamps."""
    if label is None:
        return "unlabelled"
    if label.get("provenance") == "signature":
        return "signature"
    if label.get("audited"):
        return "audited"
    if label.get("provenance") == "aligned_negative":
        return "aligned_negative"
    return "unlabelled"


def error_classes(row: dict) -> tuple[str | None, str | None]:
    """The (false-negative, false-positive) classes of one scored row."""
    gold, pred = row["gold"], row["pred"]
    if pred == gold:
        return None, None
    fn_class = fp_class = None
    if gold is not None and gold != RESIDUAL_FAMILY:
        if pred == RESIDUAL_FAMILY:
            fn_class = "fn_to_residual"
        elif (
            CONTAINMENT_PARENTS.get(pred) == gold
            or CONTAINMENT_PARENTS.get(gold) == pred
        ):
            fn_class = "fn_to_related"
        else:
            fn_class = "fn_to_rival"
    if pred != RESIDUAL_FAMILY:
        if gold is None:
            fp_class = "fp_unlabelled"
        elif gold == RESIDUAL_FAMILY:
            fp_class = "fp_residual_gold"
        elif CONTAINMENT_PARENTS.get(pred) == gold:
            fp_class = "fp_containment_consistent"
        elif CONTAINMENT_PARENTS.get(gold) == pred:
            fp_class = "fp_parent_over_subset"
        elif gold in row["group_tags"]:
            fp_class = "fp_dual_consistent"
        else:
            fp_class = "fp_rival"
    return fn_class, fp_class


def placement_category(row: dict) -> str | None:
    """The row's full-report placement, or None when it is not placed."""
    gold, pred = row["gold"], row["pred"]
    if gold is not None and pred == gold:
        if gold == RESIDUAL_FAMILY:
            return "residual"
        if row["section_member"]:
            return "exact_section"
        if SECOND_SET_TAG in row["group_tags"]:
            return "exact_second_set"
        if row["group_role"] == "variant":
            return "exact_variant"
        return "exact_main"
    if gold is None:
        if pred in ADMITTED_FAMILIES:
            return "admitted_family"
        if pred == RESIDUAL_FAMILY:
            return "unlabelled_residual"
        return None
    if gold == RESIDUAL_FAMILY and pred in ADMITTED_FAMILIES:
        return "admitted_family"
    if row["section_member"] and row["group_family"] == gold:
        return "section_of_gold"
    if CONTAINMENT_PARENTS.get(pred) == gold:
        return "contained_subset"
    if CONTAINMENT_PARENTS.get(gold) == pred:
        return "contained_parent"
    if gold in row["group_tags"]:
        return "dual_service"
    return None


def _family_stats(rows: list[dict]) -> dict:
    support: Counter = Counter()
    predicted: Counter = Counter()
    correct: Counter = Counter()
    for row in rows:
        gold_key = row["gold"] if row["gold"] is not None else "null"
        support[gold_key] += 1
        predicted[row["pred"]] += 1
        if row["pred"] == row["gold"]:
            correct[gold_key] += 1
    stats = {}
    for family in sorted(set(support) | set(predicted), key=str):
        sup = support.get(family, 0)
        pred_n = predicted.get(family, 0)
        cor = correct.get(family, 0)
        stats[family] = {
            "support": sup,
            "predicted": pred_n,
            "correct": cor,
            "precision": round(cor / pred_n, 4) if pred_n else None,
            "recall": round(cor / sup, 4) if sup else None,
        }
    return stats


def _verdicts(families: dict) -> dict:
    verdicts = {}
    for family in CORE_FAMILIES:
        fam = families.get(family, {})
        p, r = fam.get("precision"), fam.get("recall")
        verdicts[family] = {
            "terms": CORE_TERMS,
            "precision": p,
            "recall": r,
            "pass": bool(
                p is not None and r is not None and p >= 0.90 and r >= 0.85
            ),
        }
    for family, fam in families.items():
        if family in CORE_FAMILIES or family in (RESIDUAL_FAMILY, "null"):
            continue
        if fam["support"] >= 30:
            p = fam["precision"]
            verdicts[family] = {
                "terms": FLOOR_TERMS,
                "precision": p,
                "recall": fam["recall"],
                "pass": bool(p is not None and p >= 0.80),
            }
    return verdicts


def _placement(rows: list[dict]) -> dict:
    by_category: Counter = Counter()
    by_gold: dict[str, Counter] = defaultdict(Counter)
    by_pred: dict[str, Counter] = defaultdict(Counter)
    placed = placed_labelled = labelled = 0
    for row in rows:
        category = placement_category(row)
        gold_key = row["gold"] if row["gold"] is not None else "null"
        if row["gold"] is not None:
            labelled += 1
        if category is not None:
            by_category[category] += 1
            by_gold[gold_key][category] += 1
            by_pred[row["pred"]][category] += 1
            if category != "unlabelled_residual":
                placed += 1
                if row["gold"] is not None:
                    placed_labelled += 1
    families = {}
    gold_families = {row["gold"] for row in rows if row["gold"] is not None}
    pred_families = {row["pred"] for row in rows}
    for family in sorted(gold_families | pred_families | {RESIDUAL_FAMILY}):
        gold_counter = by_gold.get(family, Counter())
        pred_counter = by_pred.get(family, Counter())
        support = sum(
            1 for row in rows if row["gold"] == family
        )
        predicted = sum(1 for row in rows if row["pred"] == family)
        placed_gold = sum(
            n for cat, n in gold_counter.items() if cat != "unlabelled_residual"
        )
        placed_pred = sum(
            n for cat, n in pred_counter.items() if cat != "unlabelled_residual"
        )
        families[family] = {
            "support": support,
            "predicted": predicted,
            "placed_from_gold": placed_gold,
            "placed_from_pred": placed_pred,
            "placement_recall": round(placed_gold / support, 4)
            if support
            else None,
            "placement_precision": round(placed_pred / predicted, 4)
            if predicted
            else None,
            "gold_categories": dict(gold_counter),
            "pred_categories": dict(pred_counter),
        }
    scored = len(rows)
    return {
        "scored": scored,
        "labelled": labelled,
        "placed": placed,
        "placed_labelled": placed_labelled,
        "placed_rate": round(placed / scored, 4) if scored else None,
        "placed_rate_labelled": round(placed_labelled / labelled, 4)
        if labelled
        else None,
        "by_category": dict(by_category),
        "families": families,
    }


def score_rows(rows: list[dict], groups: list[dict]) -> dict:
    """All three accountings over scored rows and assembled groups."""
    families = _family_stats(rows)
    fn_by_family: dict[str, Counter] = defaultdict(Counter)
    fp_by_family: dict[str, Counter] = defaultdict(Counter)
    decomposition: Counter = Counter()
    for row in rows:
        fn_class, fp_class = error_classes(row)
        if fn_class is not None:
            fn_by_family[row["gold"]][fn_class] += 1
            fn_by_family[row["gold"]][f"assigned:{row['pred']}"] += 1
        if fp_class is not None:
            decomposition[fp_class] += 1
            fp_by_family[row["pred"]][fp_class] += 1
    mains: Counter = Counter()
    mains_head: Counter = Counter()
    mains_any: Counter = Counter()
    variants: Counter = Counter()
    for group in groups:
        if group["role"] == "main":
            mains[group["family"]] += 1
            if group["head_gold"] == group["family"]:
                mains_head[group["family"]] += 1
            if group["family"] in group["member_golds"]:
                mains_any[group["family"]] += 1
        else:
            variants[group["family"]] += 1
    for family, fam in families.items():
        fam["mains"] = mains.get(family, 0)
        fam["mains_head_correct"] = mains_head.get(family, 0)
        fam["mains_any_correct"] = mains_any.get(family, 0)
        fam["variants"] = variants.get(family, 0)
        fam["false_negatives"] = dict(fn_by_family.get(family, {}))
        fam["false_positives"] = dict(fp_by_family.get(family, {}))
    total_correct = sum(fam["correct"] for fam in families.values())
    named_correct = sum(
        fam["correct"]
        for key, fam in families.items()
        if key not in (RESIDUAL_FAMILY, "null")
    )
    strata = {}
    for stratum in STRATA:
        subset = [row for row in rows if row["stratum"] == stratum]
        stats = _family_stats(subset)
        strata[stratum] = {
            "scored": len(subset),
            "total_correct": sum(f["correct"] for f in stats.values()),
            "named_correct": sum(
                f["correct"]
                for key, f in stats.items()
                if key not in (RESIDUAL_FAMILY, "null")
            ),
            "families": stats,
        }
    return {
        "families": families,
        "verdicts": _verdicts(families),
        "total_correct": total_correct,
        "named_correct": named_correct,
        "decomposition": dict(decomposition),
        "placement": _placement(rows),
        "strata": strata,
    }
