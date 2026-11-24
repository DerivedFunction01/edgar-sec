"""Scalar and series serving over the ranked fact pool.

One scan per (coordinate, class) serves scalars, series, and winners;
an annual request falls back through the classes actually filed.
"""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.models import split_concept_qname
from edgar_sec.engine.xbrl.taxonomy.archive import standard_prefixes


_FALLBACK_LENGTH_CLASSES = ("YTD_3Q", "YTD_2Q", "QUARTER")
# Metric-definition exclusions at the scalar-selection seam: concepts
# whose modifier shape names a different measure than the metric.
REVENUE_EXCLUDED_MODS = frozenset({"M_PRO_FORMA", "M_DEPR_AMORT"})
OCF_EXCLUDED_MODS = frozenset({"M_NET_BOTTOMLINE"})


def _calc_distance(
    children: dict[str, list[str]], ancestor: str, target: str
) -> int | None:
    """Shortest calc-arc path from ancestor down to target, if any."""
    seen = {ancestor}
    frontier = [ancestor]
    distance = 0
    while frontier:
        distance += 1
        following: list[str] = []
        for node in frontier:
            for child in children.get(node, []):
                if child == target:
                    return distance
                if child not in seen:
                    seen.add(child)
                    following.append(child)
        frontier = following
    return None


class SeriesMixin:
    """Scalar, series, and concept-series serving over the kernel."""

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
        series = self._series_at_class(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        if series:
            return series, "INSTANT" if is_instant else length_class
        if is_instant or length_class != "ANNUAL":
            return {}, None
        for fallback in _FALLBACK_LENGTH_CLASSES:
            series = self._series_at_class(
                target_head,
                target_mods,
                excluded_mods,
                is_instant=is_instant,
                valence=valence,
                is_monetary=is_monetary,
                prefer_bare=prefer_bare,
                length_class=fallback,
            )
            if series:
                return series, fallback
        return {}, None

    def _series_at_class(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str,
    ) -> dict[str, float]:
        """One exact length class of a metric series; no fallback ladder."""
        pair = self._series_pair_at_class(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        return dict(pair[0])

    def _series_winners_at_class(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str,
    ) -> dict[str, str]:
        """Winning concept per year of one exact length class's series."""
        pair = self._series_pair_at_class(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        return dict(pair[1])

    def _series_pair_at_class(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str,
    ) -> tuple[dict[str, float], dict[str, str]]:
        """The (series, winners) pair of one scan, cached per key.

        Both accessors project from this pair: one full scan per
        (coordinate, class), however many halves are consumed.
        """
        key = (
            "series_full",
            target_head,
            frozenset(target_mods),
            frozenset(excluded_mods),
            is_instant,
            valence,
            is_monetary,
            prefer_bare,
            length_class,
        )
        return self._kernel.graph_once(
            key,
            lambda: self._compute_series_full(
                target_head,
                target_mods,
                excluded_mods,
                is_instant=is_instant,
                valence=valence,
                is_monetary=is_monetary,
                prefer_bare=prefer_bare,
                length_class=length_class,
            ),
        )

    def _compute_series_full(
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
    ) -> tuple[dict[str, float], dict[str, str]]:
        """One exact class's series and the winning concept per year."""
        lex = self._taxonomy.token_lexicon
        if lex is None:
            return {}, {}
        best = self._kernel.best_ranked(
            instant=is_instant,
            length_class=length_class,
            monetary_only=is_monetary,
        )
        by_year: dict[str, tuple[int, float, float]] = {}
        winners: dict[str, str] = {}
        pools: dict[str, list[tuple[str, float]]] = {}
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
            pools.setdefault(yr, []).append((qname, val))
            cand = (len(atom.modifiers), -abs(val), val)
            if yr not in by_year:
                by_year[yr] = cand
                winners[yr] = qname
            elif prefer_bare and cand < by_year[yr]:
                by_year[yr] = cand
                winners[yr] = qname
            elif not prefer_bare and abs(val) > abs(by_year[yr][2]):
                by_year[yr] = cand
                winners[yr] = qname
        if target_head == "H_REVENUE" and not target_mods:
            self._serve_standard_ancestors(by_year, winners, pools)
        return {yr: cand[2] for yr, cand in by_year.items()}, winners

    def _serve_standard_ancestors(
        self,
        by_year: dict[str, tuple[int, float, float]],
        winners: dict[str, str],
        pools: dict[str, list[tuple[str, float]]],
    ) -> None:
        """A revenue pick inside a standard total's calc tree yields to it.

        The pick is a component of that total, not the whole; the
        nearest standard calc ancestor in the pool serves instead.
        """
        standard = standard_prefixes()
        children: dict[str, list[str]] | None = None
        for yr, winner in winners.items():
            if split_concept_qname(winner)[0] in standard:
                continue
            candidates = [
                (qname, val)
                for qname, val in pools[yr]
                if qname != winner and split_concept_qname(qname)[0] in standard
            ]
            if not candidates:
                continue
            if children is None:
                children = self._calc_children()
            ranked = []
            for qname, val in candidates:
                distance = _calc_distance(children, qname, winner)
                if distance is not None:
                    ranked.append((distance, -abs(val), qname, val))
            if not ranked:
                continue
            _distance, _neg, qname, val = min(ranked)
            record = self._records.get(qname)
            mods = len(record.atom.modifiers) if record is not None else 0
            by_year[yr] = (mods, -abs(val), val)
            winners[yr] = qname

    def _calc_children(self) -> dict[str, list[str]]:
        """Calc children by parent over the filer's own linkbase, built once."""
        return self._kernel.graph_once(("calc_children",), self._build_calc_children)

    def _build_calc_children(self) -> dict[str, list[str]]:
        children: dict[str, list[str]] = {}
        for arc in self._arcs:
            children.setdefault(arc.parent_qname, []).append(arc.child_qname)
        return children

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
        series = self._concept_series_at_class(qname, length_class)
        if series:
            return series, length_class
        if length_class != "ANNUAL":
            return {}, None
        for fallback in _FALLBACK_LENGTH_CLASSES:
            series = self._concept_series_at_class(qname, fallback)
            if series:
                return series, fallback
        return {}, None

    def _concept_series_at_class(
        self, qname: str, length_class: str
    ) -> dict[str, float]:
        """One concept's series at one exact length class; no ladder."""
        computed = self._kernel.series(
            ("concept_series", qname, length_class),
            lambda: self._compute_concept_series(qname, length_class),
        )
        return dict(computed)

    def _compute_concept_series(
        self, qname: str, length_class: str
    ) -> dict[str, float]:
        return self._kernel.best_ranked_values(
            qname, instant=None, length_class=length_class, monetary_only=True
        )
