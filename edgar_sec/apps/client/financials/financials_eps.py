"""Filed and identity-derived EPS and weighted-share serving.

Per-period facts are grouped by span, cleaned to a unique value per
atom, and merged by (class, year) with the longest span winning.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from edgar_sec.apps.client.financials.financials_series import (
    _FALLBACK_LENGTH_CLASSES,
)
from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    residual_counts,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.identities import (
    cleanest_facts,
    eps_identity_legs,
    unique_value,
)


_EPS_ATOMS: dict[bool, Atom] = {
    False: Atom("H_UNIT_RATE", frozenset({"V_BASIC"})),
    True: Atom("H_UNIT_RATE", frozenset({"V_DILUTED"})),
}
_SHARES_ATOMS: dict[bool, Atom] = {
    False: Atom(
        "H_SHARE",
        frozenset({"M_SHARES_OUTSTANDING", "M_WEIGHTED_AVERAGE", "V_BASIC"}),
    ),
    True: Atom(
        "H_SHARE",
        frozenset({"M_SHARES_OUTSTANDING", "M_WEIGHTED_AVERAGE", "V_DILUTED"}),
    ),
}


class EpsSharesMixin:
    """EPS and weighted-share serving from filed period groups."""

    def _eps_period_groups(
        self,
    ) -> tuple[tuple[str, str, int, tuple[XbrlFact, ...]], ...]:
        """Filed duration periods as (length class, end year, span days, facts)."""
        return self._kernel.graph_once(
            ("eps_period_groups",), self._compute_eps_period_groups
        )

    def _compute_eps_period_groups(
        self,
    ) -> tuple[tuple[str, str, int, tuple[XbrlFact, ...]], ...]:
        groups: dict[tuple[str, str | None, str | None], list[XbrlFact]] = {}
        for fact in self._facts:
            if fact.dimensions or fact.period_type != "duration":
                continue
            if not isinstance(fact.value, (int, float)):
                continue
            key = (str(fact.accession), fact.start_date, fact.end_date)
            groups.setdefault(key, []).append(fact)
        out: list[tuple[str, str, int, tuple[XbrlFact, ...]]] = []
        for (_accession, start, end), facts in groups.items():
            if not start or not end:
                continue
            length_class = normalize_time_coordinate(
                "duration", None, start, end
            ).length_class
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            out.append((length_class, end[:4], span, tuple(facts)))
        return tuple(out)

    def _eps_atoms(self) -> dict[str, tuple[Atom, int]]:
        """Concept atoms with intent-residual counts, decomposed once per filing."""
        return self._kernel.graph_once(("eps_atoms",), self._compute_eps_atoms)

    def _compute_eps_atoms(self) -> dict[str, tuple[Atom, int]]:
        lex = self._taxonomy.token_lexicon
        out: dict[str, tuple[Atom, int]] = {}
        if lex is None:
            return out
        for fact in self._facts:
            if fact.concept_qname in out:
                continue
            atom, residuals, _, _ = decompose_concept(fact.concept_qname, lex)
            intent, _total = residual_counts(residuals)
            out[fact.concept_qname] = (atom, intent)
        return out

    def _eps_slot_value(self, facts: tuple[XbrlFact, ...], atom: Atom) -> float | None:
        """The cleanest unique value among a period's facts at one atom.

        Slot cleaning is the identities route's own: exact atom match,
        fewest intent residuals, one context and one value or abstain.
        """
        atoms = self._eps_atoms()
        matches = [f for f in facts if atoms.get(f.concept_qname, (None, 0))[0] == atom]
        return unique_value(cleanest_facts(matches))

    def _eps_merge(
        self,
        candidates: list[tuple[str, str, int, tuple[float, str]]],
    ) -> dict[tuple[str, str], tuple[float, str]]:
        """Merge per-period candidates by (class, year): longest span wins.

        Equal-length spans serving different values conflict the year
        out entirely rather than letting either value stand.
        """
        best: dict[tuple[str, str], tuple[int, float, str]] = {}
        conflicted: set[tuple[str, str]] = set()
        for length_class, year, span, (value, provenance) in candidates:
            key = (length_class, year)
            if key in conflicted:
                continue
            current = best.get(key)
            if current is None or span > current[0]:
                best[key] = (span, value, provenance)
            elif span == current[0] and value != current[1]:
                conflicted.add(key)
                del best[key]
        return {key: (v, p) for key, (_span, v, p) in best.items()}

    def _eps_served_map(
        self, *, diluted: bool
    ) -> dict[tuple[str, str], tuple[float, str]]:
        """Served EPS by (length class, year): filed, else identity-derived."""
        return self._kernel.graph_once(
            ("eps_served_map", diluted),
            lambda: self._compute_eps_served_map(diluted=diluted),
        )

    def _compute_eps_served_map(
        self, *, diluted: bool
    ) -> dict[tuple[str, str], tuple[float, str]]:
        kind = "DILUTED" if diluted else "BASIC"
        candidates: list[tuple[str, str, int, tuple[float, str]]] = []
        for length_class, year, span, facts in self._eps_period_groups():
            filed = self._eps_slot_value(facts, _EPS_ATOMS[diluted])
            if filed is not None:
                candidates.append((length_class, year, span, (filed, "filed")))
                continue
            legs = eps_identity_legs(facts, diluted=diluted)
            if legs is None:
                continue
            provenance = (
                f"DERIVED_EXACT:ACCOUNTING_IDENTITY:ID_EPS_{kind} "
                f"{legs.numerator_facts[0].concept_qname}({legs.numerator_value}) / "
                f"{legs.shares_facts[0].concept_qname}({legs.shares_value})"
            )
            derived = round(legs.numerator_value / legs.shares_value, 4)
            candidates.append((length_class, year, span, (derived, provenance)))
        return self._eps_merge(candidates)

    def _shares_served_map(self, *, diluted: bool) -> dict[tuple[str, str], float]:
        """Filed weighted-average shares by (length class, year)."""
        return self._kernel.graph_once(
            ("shares_served_map", diluted),
            lambda: self._compute_shares_served_map(diluted=diluted),
        )

    def _compute_shares_served_map(
        self, *, diluted: bool
    ) -> dict[tuple[str, str], float]:
        candidates: list[tuple[str, str, int, tuple[float, str]]] = []
        for length_class, year, span, facts in self._eps_period_groups():
            value = self._eps_slot_value(facts, _SHARES_ATOMS[diluted])
            if value is not None:
                candidates.append((length_class, year, span, (value, "filed")))
        merged = self._eps_merge(candidates)
        return {key: value for key, (value, _provenance) in merged.items()}

    def _eps_class_of(self, keys: Iterable[tuple[str, str]]) -> str | None:
        """The served length class: ANNUAL, else the fallback ladder in order."""
        classes = {cls for cls, _yr in keys}
        if "ANNUAL" in classes:
            return "ANNUAL"
        for fallback in _FALLBACK_LENGTH_CLASSES:
            if fallback in classes:
                return fallback
        return None

    def _eps_scalar_served(
        self, *, diluted: bool
    ) -> tuple[float | None, str | None, str | None]:
        """Latest served EPS, its provenance, and the class it served from."""
        mapping = self._eps_served_map(diluted=diluted)
        cls = self._eps_class_of(mapping.keys())
        if cls is None:
            return None, None, None
        year = max(yr for (c, yr) in mapping if c == cls)
        value, provenance = mapping[(cls, year)]
        return value, provenance, cls

    def _eps_series(self, *, diluted: bool) -> dict[str, float]:
        """Served EPS by year at the served length class."""
        mapping = self._eps_served_map(diluted=diluted)
        cls = self._eps_class_of(mapping.keys())
        if cls is None:
            return {}
        return {
            yr: value
            for (c, yr), (value, _provenance) in sorted(mapping.items())
            if c == cls
        }

    def _eps_yoy(self, *, diluted: bool) -> tuple[float, float] | None:
        """(Delta, fraction) of the served EPS series, latest against prior."""
        series = self._eps_series(diluted=diluted)
        years = sorted(series)
        if len(years) < 2:
            return None
        curr, prior = series[years[-1]], series[years[-2]]
        delta = curr - prior
        pct = delta / abs(prior) if prior != 0 else 0.0
        return delta, pct

    def _shares_scalar_served(
        self, *, diluted: bool
    ) -> tuple[float | None, str | None]:
        """Latest filed shares plus the length class they served from."""
        mapping = self._shares_served_map(diluted=diluted)
        cls = self._eps_class_of(mapping.keys())
        if cls is None:
            return None, None
        year = max(yr for (c, yr) in mapping if c == cls)
        return mapping[(cls, year)], cls

    def _shares_series(self, *, diluted: bool) -> dict[str, float]:
        """Filed shares by year at the served length class."""
        mapping = self._shares_served_map(diluted=diluted)
        cls = self._eps_class_of(mapping.keys())
        if cls is None:
            return {}
        return {yr: value for (c, yr), value in sorted(mapping.items()) if c == cls}

    def _shares_yoy(self, *, diluted: bool) -> tuple[float, float] | None:
        """(Delta, fraction) of the filed shares series, latest against prior."""
        series = self._shares_series(diluted=diluted)
        years = sorted(series)
        if len(years) < 2:
            return None
        curr, prior = series[years[-1]], series[years[-2]]
        delta = curr - prior
        pct = delta / abs(prior) if prior != 0 else 0.0
        return delta, pct
