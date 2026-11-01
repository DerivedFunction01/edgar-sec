"""Served scalar and series machinery for the financials catalogue.

Every metric is served at a named span class: the annual class first,
then the fallback ladder, with the served class named alongside.
"""

from __future__ import annotations

from collections.abc import Callable

from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.kernel import FilingKernel


_FALLBACK_LENGTH_CLASSES = ("YTD_3Q", "YTD_2Q", "QUARTER")


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
