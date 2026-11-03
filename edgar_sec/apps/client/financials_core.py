"""Served scalar and series machinery for the financials catalogue.

Every metric is served at a named span class: the annual class first,
then the fallback ladder, with the served class named alongside.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    residual_counts,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.identities import eps_identity_legs


_FALLBACK_LENGTH_CLASSES = ("YTD_3Q", "YTD_2Q", "QUARTER")
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


class FinancialsCore:
    """Kernel-bound serving machinery the metric catalogue is expressed in."""

    def __init__(
        self,
        kernel: FilingKernel,
        *,
        composition_resolver: Callable[[ChainTerms, int | None], CompositionResult]
        | None = None,
    ) -> None:
        self._kernel = kernel
        self._facts = kernel.facts
        self._arcs = kernel.calculation_arcs
        self._definition_arcs = kernel.definition_arcs
        self._taxonomy = kernel.taxonomy
        self._labels = kernel.labels
        self._records = kernel.records
        self._composition_resolver = composition_resolver
        self._composer = kernel.composer

    def _scalar(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        year: int | str | None = None,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> float | None:
        value, _cls = self._scalar_served(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            year=year,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        return value

    def _scalar_served(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        year: int | str | None = None,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> tuple[float | None, str | None]:
        """A scalar plus the length class of the span it was served from."""
        series, cls = self._series_served(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        if year:
            return series.get(str(year)), cls if str(year) in series else None
        if not series:
            return None, None
        sorted_years = sorted(series.keys())
        return series[sorted_years[-1]], cls

    def _series(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> dict[str, float]:
        series, _cls = self._series_served(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        return series

    def _series_served(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> tuple[dict[str, float], str | None]:
        """A series plus the length class it was served from.

        An ANNUAL request the filing carries nothing for falls back to
        the classes actually filed, latest YTD first, then quarter.
        """

        def attempt(cls: str) -> dict[str, float]:
            key = (
                "series",
                target_head,
                frozenset(target_mods),
                frozenset(excluded_mods),
                is_instant,
                valence,
                is_monetary,
                prefer_bare,
                cls,
            )
            computed = self._kernel.series(
                key,
                lambda: self._compute_series(
                    target_head,
                    target_mods,
                    excluded_mods,
                    is_instant=is_instant,
                    valence=valence,
                    is_monetary=is_monetary,
                    prefer_bare=prefer_bare,
                    length_class=cls,
                ),
            )
            return dict(computed)

        series = attempt(length_class)
        if series:
            return series, "INSTANT" if is_instant else length_class
        if is_instant or length_class != "ANNUAL":
            return {}, None
        for fallback in _FALLBACK_LENGTH_CLASSES:
            series = attempt(fallback)
            if series:
                return series, fallback
        return {}, None

    def _compute_series(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> dict[str, float]:
        lex = self._taxonomy.token_lexicon
        if lex is None:
            return {}
        best = self._kernel.best_ranked(
            instant=is_instant,
            length_class=length_class,
            monetary_only=is_monetary,
        )
        by_year: dict[str, tuple[int, float, float]] = {}
        for (qname, yr), (_rank, val) in best.items():
            if len(yr) != 4 or not yr.isdigit():
                continue
            record = self._records.get(qname)
            if record is None:
                continue
            atom = record.atom
            if atom.head != target_head or not target_mods.issubset(atom.modifiers):
                continue
            if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                continue
            if valence and valence not in atom.modifiers:
                continue
            cand = (len(atom.modifiers), -abs(val), val)
            if yr not in by_year:
                by_year[yr] = cand
            elif prefer_bare and cand < by_year[yr]:
                by_year[yr] = cand
            elif not prefer_bare and abs(val) > abs(by_year[yr][2]):
                by_year[yr] = cand
        return {yr: cand[2] for yr, cand in by_year.items()}

    def _yoy(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> tuple[float, float] | None:
        series = self._series(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        years = sorted(series.keys())
        if len(years) < 2:
            return None
        curr, prior = series[years[-1]], series[years[-2]]
        delta = curr - prior
        pct = delta / abs(prior) if prior != 0 else 0.0
        return delta, pct

    def _concept_series(
        self, qname: str, length_class: str = "ANNUAL"
    ) -> dict[str, float]:
        """One concept's values by year, longest span then finest decimals."""
        series, _cls = self._concept_series_served(qname, length_class)
        return series

    def _concept_series_served(
        self, qname: str, length_class: str = "ANNUAL"
    ) -> tuple[dict[str, float], str | None]:
        """A concept series plus its class, with the _series fallback rule."""

        def attempt(cls: str) -> dict[str, float]:
            computed = self._kernel.series(
                ("concept_series", qname, cls),
                lambda: self._compute_concept_series(qname, cls),
            )
            return dict(computed)

        series = attempt(length_class)
        if series:
            return series, length_class
        if length_class != "ANNUAL":
            return {}, None
        for fallback in _FALLBACK_LENGTH_CLASSES:
            series = attempt(fallback)
            if series:
                return series, fallback
        return {}, None

    def _compute_concept_series(
        self, qname: str, length_class: str
    ) -> dict[str, float]:
        best = self._kernel.best_ranked(
            instant=None, length_class=length_class, monetary_only=True
        )
        return {
            yr: val for (concept, yr), (_rank, val) in best.items() if concept == qname
        }

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

        Mirrors the identities route's slot semantics: exact atom match,
        fewest intent residuals, one context and one value or abstain.
        """
        atoms = self._eps_atoms()
        matches = [f for f in facts if atoms.get(f.concept_qname, (None, 0))[0] == atom]
        if not matches:
            return None
        fewest = min(atoms[f.concept_qname][1] for f in matches)
        cleanest = [f for f in matches if atoms[f.concept_qname][1] == fewest]
        contexts = {
            (
                f.unit,
                f.period_type,
                f.start_date,
                f.end_date,
                f.instant_date,
                tuple(sorted(f.dimensions.items())),
            )
            for f in cleanest
        }
        values = {float(f.value) for f in cleanest if isinstance(f.value, (int, float))}
        if len(contexts) != 1 or len(values) != 1:
            return None
        return next(iter(values))

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
