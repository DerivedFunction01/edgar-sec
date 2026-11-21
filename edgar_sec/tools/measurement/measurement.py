"""Population-first measurement protocol.

Adjudication records with the false claim's true class as a first-
class field, per-stratum estimators that are never blended, the
grouped scored contract pricing, and seal/disjointness checks.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.signature_profiles import (
    SIGNATURE_TERMS,
)

FAMILIES = tuple(sorted({term.family for term in SIGNATURE_TERMS}))
# The adjudication brief judges the build-excluded
# commitments_contingencies family on its face, and the
# false-claim taxonomy priced its gold class wider.
GOLD_FAMILIES = FAMILIES + ("commitments_contingencies",)
VERDICTS = ("member", "not-member", "split-group")
MECHANISMS = ("contested-twin", "stub-mass", "mixed")
UNCLASSIFIED = "unclassified"

# General (non-gold) classes of the false-claim taxonomy
# (vocabulary of record: 2026-11-14-greenfield-step2a/taxonomy.json).
PLAIN_CLASSES = (
    "acquisition-detail",
    "composition",
    "grant-activity",
    "hierarchy",
    "ladder-detail",
    "ladder-of-the-other-subject",
    "movement-detail",
    "percentage-rows",
    "provision-detail",
    "restatement-recast",
    "segment-detail",
    "statement-summary",
    "summary-columns",
    "supplemental-schedule",
)
PREFIXED_CLASSES = ("host-shape:", "host-variant:", "neighbor-shape:", "shape:")

STRATA = ("B", "D")
CLOSE_FLOOR = 0.90


def is_true_class(value: str) -> bool:
    """A legal false_claim_true_class: gold family or named class."""
    if value == UNCLASSIFIED:
        return True
    if value.startswith("gold:"):
        return value[5:] in GOLD_FAMILIES
    if value in PLAIN_CLASSES:
        return True
    for prefix in PREFIXED_CLASSES:
        if value.startswith(prefix):
            return value[len(prefix) :] in GOLD_FAMILIES
    return False


@dataclass(frozen=True, slots=True)
class AdjudicationRecord:
    """One blind adjudication of one sampled specimen."""

    specimen_id: str
    stratum: str
    claimed_family: str
    verdict: str
    true_family: str | None = None
    false_claim_true_class: str | None = None
    false_claim_mechanism: str | None = None

    @property
    def is_false_claim(self) -> bool:
        """A false claim: not a member, or a member of another family."""
        if self.verdict == "not-member":
            return True
        return self.true_family is not None and self.true_family != self.claimed_family

    @property
    def is_member(self) -> bool:
        """A strict-counting member of the claimed family."""
        return self.verdict == "member" and not self.is_false_claim

    def problems(self) -> tuple[str, ...]:
        """Protocol violations on this record, named."""
        found: list[str] = []
        if self.stratum not in STRATA:
            found.append(f"unknown stratum {self.stratum!r}")
        if self.claimed_family not in FAMILIES:
            found.append(f"unknown claimed family {self.claimed_family!r}")
        if self.verdict not in VERDICTS:
            found.append(f"unknown verdict {self.verdict!r}")
        if self.true_family is not None and self.true_family not in GOLD_FAMILIES:
            found.append(f"unknown true family {self.true_family!r}")
        if self.is_false_claim:
            if self.false_claim_true_class is None:
                found.append("false claim without false_claim_true_class")
            elif not is_true_class(self.false_claim_true_class):
                found.append(
                    f"illegal false_claim_true_class {self.false_claim_true_class!r}"
                )
            elif (
                self.true_family is not None
                and self.false_claim_true_class != f"gold:{self.true_family}"
            ):
                found.append("gold true family must be classed gold:<family>")
            if self.false_claim_mechanism is None:
                found.append("false claim without false_claim_mechanism")
            elif self.false_claim_mechanism not in MECHANISMS:
                found.append(f"unknown mechanism {self.false_claim_mechanism!r}")
        else:
            if self.false_claim_true_class is not None:
                found.append("member record carries a false-claim class")
            if self.false_claim_mechanism is not None:
                found.append("member record carries a false-claim mechanism")
        return tuple(found)


@dataclass(frozen=True, slots=True)
class Rate:
    """One labelled estimator reading: value over its own denominator."""

    estimator: str
    stratum: str
    family: str
    value: float | None
    n: int


def precision_rates(
    records: tuple[AdjudicationRecord, ...],
) -> tuple[Rate, Rate]:
    """Strict and form-present precision of one claim sample."""
    n = len(records)
    strict = sum(1 for r in records if r.is_member)
    form = sum(1 for r in records if r.is_member or r.verdict == "split-group")
    family = records[0].claimed_family if records else ""
    stratum = records[0].stratum if records else ""
    return (
        Rate("precision-strict", stratum, family, strict / n if n else None, n),
        Rate(
            "precision-form-present",
            stratum,
            family,
            form / n if n else None,
            n,
        ),
    )


def labelled_recall(
    records: tuple[AdjudicationRecord, ...], family: str, stratum: str
) -> Rate:
    """Recall over an adjudicated member sample (labelled estimator)."""
    members = [
        r
        for r in records
        if r.true_family == family
        or (r.true_family is None and r.is_member and r.claimed_family == family)
    ]
    claimed = sum(1 for r in members if r.claimed_family == family)
    n = len(members)
    return Rate(
        "recall-labelled-sample",
        stratum,
        family,
        claimed / n if n else None,
        n,
    )


def sweep_recall(
    claimed_members: float,
    sweep_members: int,
    sweep_drawn: int,
    sweep_pool: int,
    family: str,
    stratum: str,
) -> Rate:
    """Sweep-estimated recall for a label-free stratum (D-form)."""
    misses = sweep_members / sweep_drawn * sweep_pool if sweep_drawn else 0.0
    total = claimed_members + misses
    return Rate(
        "recall-sweep-estimated",
        stratum,
        family,
        claimed_members / total if total else None,
        sweep_drawn,
    )


def unclassified_remainder(
    records: tuple[AdjudicationRecord, ...],
) -> dict[str, Rate]:
    """The priced unclassified remainder, per stratum, false claims only."""
    out: dict[str, Rate] = {}
    for stratum in STRATA:
        false_claims = [r for r in records if r.stratum == stratum and r.is_false_claim]
        un = sum(1 for r in false_claims if r.false_claim_true_class == UNCLASSIFIED)
        n = len(false_claims)
        out[stratum] = Rate(
            "unclassified-remainder", stratum, "", un / n if n else None, n
        )
    return out


@dataclass(frozen=True, slots=True)
class GroupReturn:
    """One family's grouped scored return over one geometry."""

    specimen_id: str
    stratum: str
    family: str
    score: float
    state: str
    is_top: bool


def _member_map(
    records: tuple[AdjudicationRecord, ...],
) -> dict[tuple[str, str], bool]:
    return {(r.specimen_id, r.claimed_family): r.is_member for r in records}


def top_member_rates(
    returns: tuple[GroupReturn, ...],
    records: tuple[AdjudicationRecord, ...],
) -> tuple[Rate, ...]:
    """Per family/stratum: member rate of top-scored contested returns."""
    members = _member_map(records)
    keys = sorted({(g.stratum, g.family) for g in returns if g.is_top})
    out: list[Rate] = []
    for stratum, family in keys:
        tops = [
            g
            for g in returns
            if g.is_top and g.stratum == stratum and g.family == family
        ]
        judged = [g for g in tops if (g.specimen_id, g.family) in members]
        hits = sum(1 for g in judged if members[(g.specimen_id, g.family)])
        n = len(judged)
        out.append(
            Rate(
                "grouped-top-member",
                stratum,
                family,
                hits / n if n else None,
                n,
            )
        )
    return tuple(out)


SCORE_BANDS = ((5.0, 7.5), (7.5, 10.0), (10.0, 15.0), (15.0, math.inf))


def calibration_rows(
    returns: tuple[GroupReturn, ...],
    records: tuple[AdjudicationRecord, ...],
) -> tuple[Rate, ...]:
    """Member rate by score band across the returned set, per stratum."""
    members = _member_map(records)
    out: list[Rate] = []
    for stratum in STRATA:
        for low, high in SCORE_BANDS:
            band = [
                g for g in returns if g.stratum == stratum and low <= g.score < high
            ]
            judged = [g for g in band if (g.specimen_id, g.family) in members]
            hits = sum(1 for g in judged if members[(g.specimen_id, g.family)])
            n = len(judged)
            label = f"calibration[{low:g},{high:g})"
            out.append(Rate(label, stratum, "", hits / n if n else None, n))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class GateSign:
    """The aoci seat gate's population sign and its disposition."""

    decision: str
    true_members_killed: int
    false_claims_killed: int
    differing: int


def aoci_gate_sign(
    differing_records: tuple[AdjudicationRecord, ...],
) -> GateSign:
    """Price the claims the seat gate removes, from their adjudications.

    The derivation sign repeating on population removes the gate;
    any false kill at all records the gate's acceptance instead.
    """
    judged = [r for r in differing_records if r.claimed_family == "aoci_rollforward"]
    true_killed = sum(1 for r in judged if not r.is_false_claim)
    false_killed = sum(1 for r in judged if r.is_false_claim)
    decision = (
        "remove" if judged and false_killed == 0 and true_killed > 0 else "accept"
    )
    return GateSign(decision, true_killed, false_killed, len(judged))


def false_claim_classes(
    records: tuple[AdjudicationRecord, ...], family: str
) -> dict[str, int]:
    """One family's false claims by true class, both strata kept apart."""
    out: dict[str, int] = {}
    for r in records:
        if r.claimed_family != family or not r.is_false_claim:
            continue
        key = f"{r.stratum}:{r.false_claim_true_class}"
        out[key] = out.get(key, 0) + 1
    return out


def verify_disjoint(drawn: set[str], prior: dict[str, set[str]]) -> dict[str, int]:
    """Overlap counts of a draw against every prior stratum's list."""
    return {name: len(drawn & names) for name, names in prior.items()}


def accession_list_hash(accessions: set[str]) -> str:
    """SHA-256 of a stratum's sorted accession list, its seal identity."""
    return hashlib.sha256("\n".join(sorted(accessions)).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SealRecord:
    """A held-out stratum priced before it is opened, spent once."""

    stratum: str
    list_hash: str
    priced_at: str
    sample_plan: str
    spent: bool = False

    def open(self, opened_at: str) -> SealRecord:
        """Spend the seal once; refuse a re-spend or an unpriced open."""
        if self.spent:
            raise ValueError(f"stratum {self.stratum} already spent")
        if opened_at < self.priced_at:
            raise ValueError(f"stratum {self.stratum} opened before priced")
        return SealRecord(
            self.stratum,
            self.list_hash,
            self.priced_at,
            self.sample_plan,
            spent=True,
        )


def close_status(rates: tuple[Rate, ...], family: str, form_of: dict[str, str]) -> str:
    """A family's close state: full, half (one form only), or open."""
    forms = {
        form_of[r.stratum]
        for r in rates
        if r.family == family
        and r.estimator
        in ("precision-strict", "recall-labelled-sample", "recall-sweep-estimated")
        and r.value is not None
    }
    if len(forms) == 2:
        return "closed-both-forms"
    if len(forms) == 1:
        return f"half-close-{next(iter(forms))}-only"
    return "open"
