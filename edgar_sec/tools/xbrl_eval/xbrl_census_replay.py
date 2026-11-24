"""Faithful-tier replay and record adjudication for the XBRL census."""

from __future__ import annotations

import json
from collections import Counter

from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.query import QueryStatus
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from edgar_sec.tools.xbrl_eval.xbrl_census_corpus import span_days


SUCCESS = {QueryStatus.REPORTED, QueryStatus.DERIVED, QueryStatus.VERIFIED}


_RANK = {
    "VERIFIED": 0,
    "REPORTED": 1,
    "CONFLICT": 2,
    "DERIVED": 3,
    "AMBIGUOUS": 4,
    "UNAVAILABLE": 5,
}


def values_equal(a: float | None, b: float | None) -> bool:
    """Relative-tolerance numeric equality; None matches only None."""
    if a is None or b is None:
        return a is b
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def result_record(result, scope: FactScope | None) -> dict:
    """Serialize one query result (plus its scope) for offline replay."""
    rec = {
        "status": str(result.status),
        "value": result.value,
        "candidates": list(result.candidate_qnames),
        "tier": result.tier,
        "reported_qname": (
            result.reported_fact.concept_qname if result.reported_fact else None
        ),
        "equivalents": [
            {
                "qname": e.qname,
                "tier": e.tier,
                "via_default": e.via_default,
                "distance": e.modifier_distance,
            }
            for e in result.equivalents
        ],
    }
    if scope is not None:
        rec["scope"] = {
            "start": scope.start_date,
            "end": scope.end_date,
            "instant": scope.instant_date,
            "unit": scope.unit,
            "span": span_days(scope.start_date, scope.end_date),
            "kind": "instant" if scope.instant_date else "duration",
        }
    if str(result.status) == "CONFLICT":
        rec["candidate_facts"] = [
            {
                "qname": f.concept_qname,
                "value": f.value if isinstance(f.value, (int, float)) else None,
                "decimals": f.decimals,
                "unit": f.unit,
                "start": f.start_date,
                "end": f.end_date,
                "instant": f.instant_date,
                "dimensions": f.dimensions,
            }
            for f in result.candidate_facts
        ]
    return rec


def group_key(scope_rec: dict) -> tuple:
    """The faithful-tier group a scope record belongs to."""
    s = scope_rec["scope"]
    if s["kind"] == "instant":
        return ("instant", s["instant"])
    return ("duration", s["start"], s["end"])


def tier_outcome(records: list[dict]) -> dict | None:
    """The tier's outcome under the facade's split precedence.

    VERIFIED > REPORTED > CONFLICT > DERIVED > AMBIGUOUS > UNAVAILABLE;
    ties keep scope order, mirroring the fiscal tier outcome.
    """
    best = None
    for rec in records:
        if best is None or _RANK[rec["status"]] < _RANK[best["status"]]:
            best = rec
    return best


def replay_faithful(records: list[dict], facts: tuple[XbrlFact, ...]) -> dict | None:
    """R1-strict faithful outcome over recorded scopes; never reimplements the engine."""
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault(group_key(rec), []).append(rec)
    dur_spans = {
        key: span_days(key[1], key[2]) for key in groups if key[0] == "duration"
    }
    t1_key = max(dur_spans, key=lambda k: dur_spans[k]) if dur_spans else None
    instant_counts: Counter = Counter()
    for fact in facts:
        if not fact.dimensions and fact.period_type == "instant" and fact.instant_date:
            instant_counts[fact.instant_date] += 1
    t1 = groups.get(t1_key, []) if t1_key else []
    t1_outcome = tier_outcome(t1)
    if t1_outcome is not None and t1_outcome["status"] in {str(s) for s in SUCCESS}:
        return t1_outcome
    if t1_outcome is not None and t1_outcome["status"] != "UNAVAILABLE":
        qnames = {q for rec in t1 for q in rec["candidates"]}
        has_duration = any(
            f.concept_qname in qnames and f.period_type == "duration" for f in facts
        )
        if has_duration:
            return t1_outcome
    fy_instants = [key for key in groups if key[0] == "instant"]
    t2_outcome = None
    if fy_instants:
        modal = max(
            fy_instants,
            key=lambda k: (instant_counts.get(k[1], 0), k[1]),
        )
        t2_outcome = tier_outcome(groups[modal])
    if t1_outcome is not None and t1_outcome["status"] != "UNAVAILABLE":
        return t2_outcome if t2_outcome is not None else t1_outcome
    if t2_outcome is not None and t2_outcome["status"] != "UNAVAILABLE":
        return t2_outcome
    return records[0] if records else None


def classify(facade: dict, faithful: dict | None) -> str:
    """Classify a facade outcome against its faithful-tier replay."""
    if faithful is None:
        return "unfaithful non-answer"
    f_ok = facade["status"] in {str(s) for s in SUCCESS}
    t_ok = faithful["status"] in {str(s) for s in SUCCESS}
    if t_ok:
        if not f_ok:
            return "refused"
        if facade["status"] == faithful["status"] and values_equal(
            facade["value"], faithful["value"]
        ):
            return "correct"
        return "wrong-value"
    if f_ok:
        return "wrong-span"
    if facade["status"] == faithful["status"]:
        if (
            values_equal(facade["value"], faithful["value"])
            and facade["candidates"] == faithful["candidates"]
        ):
            return "honest-faithful"
        return "unfaithful non-answer"
    return "unfaithful non-answer"


def tolerance(fact: dict) -> float:
    """Rounding-interval half-width implied by a fact's stated decimals."""
    if fact["decimals"] is None:
        return 0.0001
    return 0.5 * (10.0 ** (-fact["decimals"]))


def intervals_consistent(facts: list[dict]) -> bool:
    """True iff all numeric values form one rounding-interval cluster."""
    intervals = sorted(
        (f["value"] - tolerance(f), f["value"] + tolerance(f))
        for f in facts
        if f["value"] is not None
    )
    low = high = None
    for lo, hi in intervals:
        if low is None:
            low, high = lo, hi
        elif lo <= high and hi >= low:
            low, high = max(low, lo), min(high, hi)
        else:
            return False
    return True


def conflict_is_precision_duplicate(rec: dict) -> bool | None:
    """Adjudicate a CONFLICT record's candidate facts (register A)."""
    facts = rec.get("candidate_facts")
    if not facts:
        return None
    by_context: dict[tuple, list[dict]] = {}
    for f in facts:
        key = (
            f["unit"],
            f["start"],
            f["end"],
            f["instant"],
            json.dumps(f["dimensions"], sort_keys=True),
        )
        by_context.setdefault(key, []).append(f)
    multi = [fs for fs in by_context.values() if len({f["value"] for f in fs}) > 1]
    if not multi:
        return None
    return all(intervals_consistent(fs) for fs in multi)


def attribute(facade: dict, records: list[dict]) -> dict | None:
    """First recorded scope whose (status, value, candidates) match the facade's."""
    for rec in records:
        if (
            rec["status"] == facade["status"]
            and values_equal(rec["value"], facade["value"])
            and rec["candidates"] == facade["candidates"]
        ):
            return rec
    for rec in records:
        if rec["status"] == facade["status"] and values_equal(
            rec["value"], facade["value"]
        ):
            return rec
    return None


def scope_matches(fact: XbrlFact, scope: dict) -> bool:
    """True when an undimensioned fact sits inside the recorded scope."""
    if fact.dimensions:
        return False
    if scope["kind"] == "instant":
        return fact.period_type == "instant" and fact.instant_date == scope["instant"]
    return (
        fact.period_type == "duration"
        and fact.start_date == scope["start"]
        and fact.end_date == scope["end"]
    )


def near_guard_violation(facade_rec: dict, attributed: dict | None, facts) -> bool:
    """Independent guard check: divergent values inside the best tier group."""
    if attributed is None:
        return False
    best = facade_rec["equivalents"][0]
    group = [
        e
        for e in facade_rec["equivalents"]
        if (e["tier"], e["via_default"]) == (best["tier"], best["via_default"])
    ]
    if len(group) <= 1:
        return False
    per_qname: dict[str, list[dict]] = {}
    for e in group:
        vals = [
            {"value": float(f.value), "decimals": f.decimals}
            for f in facts
            if f.concept_qname == e["qname"]
            and scope_matches(f, attributed["scope"])
            and (
                attributed["scope"]["unit"] is None
                or f.unit == attributed["scope"]["unit"]
            )
            and isinstance(f.value, (int, float))
        ]
        if vals:
            per_qname[e["qname"]] = vals
    qnames = list(per_qname)
    for i, a in enumerate(qnames):
        for b in qnames[i + 1 :]:
            if not intervals_consistent(per_qname[a] + per_qname[b]):
                return True
    return False


def faithful_keys(records: list[dict], facts) -> set:
    """The duration and instant group keys forming the faithful tiers."""
    keys = set()
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault(group_key(rec), []).append(rec)
    dur = {k: span_days(k[1], k[2]) for k in groups if k[0] == "duration"}
    if dur:
        keys.add(max(dur, key=lambda k: dur[k]))
    inst = [k for k in groups if k[0] == "instant"]
    if inst:
        counts: Counter = Counter()
        for f in facts:
            if not f.dimensions and f.period_type == "instant" and f.instant_date:
                counts[f.instant_date] += 1
        keys.add(max(inst, key=lambda k: (counts.get(k[1], 0), k[1])))
    return keys
