"""Series/class lookups over the published fund series/class relation.

Read-only over the published snapshot tip: no lookup fetches, and a
relation that was never published is reported as absence, not repaired.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.domain.forms.families.form_nmfp.models import FormNMfpDocument

__all__ = [
    "BROWSE_LAYER",
    "TICKERED_LAYER",
    "FundClass",
    "FundClassResult",
    "FundClassesResult",
    "FundSeries",
    "FundSeriesListResult",
    "FundSeriesResult",
    "NMfpSeriesResolution",
    "SeriesClassSurfaces",
    "read_fund_class",
    "read_fund_series",
    "read_registrant_series",
    "read_series_classes",
    "read_ticker_classes",
    "resolve_nmfp_series",
]

BROWSE_LAYER = "browse"
TICKERED_LAYER = "tickered"


@dataclass(frozen=True, slots=True)
class FundSeries:
    """One fund series as the relation layers jointly serve it."""

    cik: str
    series_id: str
    series_name: str | None
    layers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FundClass:
    """One fund class; ``symbol`` is None only when no layer tickers it."""

    cik: str
    series_id: str
    series_name: str | None
    class_id: str
    class_name: str | None
    symbol: str | None
    layers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FundSeriesResult:
    """One series lookup; ``relation_present`` marks an unpublished store."""

    series: FundSeries | None
    snapshot_id: str | None
    relation_present: bool


@dataclass(frozen=True, slots=True)
class FundClassResult:
    """One class lookup; ``relation_present`` marks an unpublished store."""

    fund_class: FundClass | None
    snapshot_id: str | None
    relation_present: bool


@dataclass(frozen=True, slots=True)
class FundClassesResult:
    """A class listing; ``relation_present`` marks an unpublished store."""

    classes: tuple[FundClass, ...]
    snapshot_id: str | None
    relation_present: bool


@dataclass(frozen=True, slots=True)
class FundSeriesListResult:
    """A series listing; ``relation_present`` marks an unpublished store."""

    series: tuple[FundSeries, ...]
    snapshot_id: str | None
    relation_present: bool


@dataclass(frozen=True, slots=True)
class NMfpSeriesResolution:
    """An N-MFP series id resolved against the published relation.

    Conflicts name document-vs-relation disagreements; the relation's
    values are served as-is, never overridden by the document's.
    """

    series_id: str | None
    resolved: bool
    relation_present: bool
    snapshot_id: str | None
    series: FundSeries | None
    classes: tuple[FundClass, ...]
    document_series_name: str | None
    document_series_lei: str | None
    conflicts: tuple[str, ...]


def _relation_rows(parts: dict, relation: str) -> list[tuple]:
    """Rows of one published relation, or none when it was not published."""
    from edgar_sec.infra.storage.duckdb import connect, sql_path_list
    from edgar_sec.pipelines.metadata_sync.series_class import TICKERED_RELATION
    from edgar_sec.pipelines.metadata_sync.series_class_browse import (
        BROWSE_RELATION,
        BROWSE_SERIES_RELATION,
    )

    paths = parts.get(relation)
    if not paths:
        return []
    table = f"read_parquet({sql_path_list(paths)})"
    if relation == TICKERED_RELATION:
        sql = f"SELECT cik, series_id, class_id, symbol FROM {table}"
    elif relation == BROWSE_RELATION:
        sql = (
            "SELECT cik, series_id, series_name, class_id, class_name, symbol "
            f"FROM {table}"
        )
    elif relation == BROWSE_SERIES_RELATION:
        sql = f"SELECT cik, series_id, series_name FROM {table}"
    else:
        return []
    con = connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _merged_view(
    artifacts_root: str | Path | None,
) -> tuple[str | None, dict[str, FundSeries], dict[str, FundClass]]:
    """The published tip merged across layers: (snapshot, series, classes)."""
    from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
    from edgar_sec.pipelines.metadata_sync.series_class import (
        TICKERED_RELATION,
        series_class_part_paths,
        series_class_tip,
    )
    from edgar_sec.pipelines.metadata_sync.series_class_browse import (
        BROWSE_RELATION,
        BROWSE_SERIES_RELATION,
    )

    paths = resolve_metadata_paths(artifacts_root)
    tip = series_class_tip(paths)
    if tip is None:
        return None, {}, {}
    parts = series_class_part_paths(paths, tip)
    tickered = _relation_rows(parts, TICKERED_RELATION)
    browse = _relation_rows(parts, BROWSE_RELATION)
    browse_series = _relation_rows(parts, BROWSE_SERIES_RELATION)
    series: dict[str, FundSeries] = {}
    ciks: dict[str, str] = {}
    names: dict[str, str] = {}
    layers: dict[str, set[str]] = {}
    for cik, series_id, series_name in browse_series:
        ciks[str(series_id)] = str(cik)
        names[str(series_id)] = str(series_name)
        layers.setdefault(str(series_id), set()).add(BROWSE_LAYER)
    for cik, series_id, series_name, _class_id, _class_name, _symbol in browse:
        ciks.setdefault(str(series_id), str(cik))
        names.setdefault(str(series_id), str(series_name))
        layers.setdefault(str(series_id), set()).add(BROWSE_LAYER)
    for cik, series_id, _class_id, _symbol in tickered:
        ciks.setdefault(str(series_id), str(cik))
        layers.setdefault(str(series_id), set()).add(TICKERED_LAYER)
    for series_id, cik in ciks.items():
        series[series_id] = FundSeries(
            cik=cik,
            series_id=series_id,
            series_name=names.get(series_id),
            layers=tuple(
                layer
                for layer in (BROWSE_LAYER, TICKERED_LAYER)
                if layer in layers[series_id]
            ),
        )
    classes: dict[str, FundClass] = {}
    for cik, series_id, series_name, class_id, class_name, symbol in browse:
        classes[str(class_id)] = FundClass(
            cik=str(cik),
            series_id=str(series_id),
            series_name=str(series_name),
            class_id=str(class_id),
            class_name=str(class_name),
            symbol=None if symbol is None else str(symbol),
            layers=(BROWSE_LAYER,),
        )
    for cik, series_id, class_id, symbol in tickered:
        held = classes.get(str(class_id))
        if held is None:
            classes[str(class_id)] = FundClass(
                cik=str(cik),
                series_id=str(series_id),
                series_name=names.get(str(series_id)),
                class_id=str(class_id),
                class_name=None,
                symbol=str(symbol),
                layers=(TICKERED_LAYER,),
            )
        else:
            # The ticker file is the ticker registry of record: its symbol
            # wins over the browse layer's, agreements included.
            classes[str(class_id)] = FundClass(
                cik=held.cik,
                series_id=held.series_id,
                series_name=held.series_name,
                class_id=held.class_id,
                class_name=held.class_name,
                symbol=str(symbol),
                layers=(BROWSE_LAYER, TICKERED_LAYER),
            )
    return tip, series, classes


def read_fund_series(
    artifacts_root: str | Path | None, series_id: str
) -> FundSeriesResult:
    """The relation's record for one series id; None on a miss."""
    tip, series, _classes = _merged_view(artifacts_root)
    return FundSeriesResult(
        series=series.get(series_id),
        snapshot_id=tip,
        relation_present=tip is not None,
    )


def read_fund_class(
    artifacts_root: str | Path | None, class_id: str
) -> FundClassResult:
    """The relation's record for one class id; None on a miss."""
    tip, _series, classes = _merged_view(artifacts_root)
    return FundClassResult(
        fund_class=classes.get(class_id),
        snapshot_id=tip,
        relation_present=tip is not None,
    )


def read_series_classes(
    artifacts_root: str | Path | None, series_id: str
) -> FundClassesResult:
    """Every class the relation carries for one series, by class id."""
    tip, _series, classes = _merged_view(artifacts_root)
    return FundClassesResult(
        classes=tuple(
            classes[class_id]
            for class_id in sorted(classes)
            if classes[class_id].series_id == series_id
        ),
        snapshot_id=tip,
        relation_present=tip is not None,
    )


def read_registrant_series(
    artifacts_root: str | Path | None, cik: str | int
) -> FundSeriesListResult:
    """Every series the relation carries for one registrant, by series id."""
    from edgar_sec.domain.identity import Cik

    wanted = Cik.from_raw(cik).to_10digit()
    tip, series, _classes = _merged_view(artifacts_root)
    return FundSeriesListResult(
        series=tuple(
            series[series_id]
            for series_id in sorted(series)
            if series[series_id].cik == wanted
        ),
        snapshot_id=tip,
        relation_present=tip is not None,
    )


def read_ticker_classes(
    artifacts_root: str | Path | None, symbol: str
) -> FundClassesResult:
    """Every class the relation tickers under one symbol, by class id."""
    wanted = symbol.strip()
    tip, _series, classes = _merged_view(artifacts_root)
    if not wanted:
        return FundClassesResult(
            classes=(), snapshot_id=tip, relation_present=tip is not None
        )
    return FundClassesResult(
        classes=tuple(
            classes[class_id]
            for class_id in sorted(classes)
            if classes[class_id].symbol == wanted
        ),
        snapshot_id=tip,
        relation_present=tip is not None,
    )


def _document_cik(document: "FormNMfpDocument") -> str | None:
    """The document's registrant CIK in served form, or None when absent."""
    from edgar_sec.domain.identity import Cik

    if not document.registrant_cik:
        return None
    try:
        return Cik.from_raw(document.registrant_cik).to_10digit()
    except (TypeError, ValueError):
        return document.registrant_cik.strip()


def resolve_nmfp_series(
    document: "FormNMfpDocument",
    artifacts_root: str | Path | None = None,
) -> NMfpSeriesResolution:
    """Resolve one N-MFP document's series id against the relation.

    Name and registrant disagreements are reported as conflicts; the
    relation carries no LEI, so the document's LEI returns unverified.
    """
    tip, series_map, classes = _merged_view(artifacts_root)
    series = series_map.get(document.series_id) if document.series_id else None
    conflicts: list[str] = []
    if series is not None:
        if (
            document.series_name
            and series.series_name
            and document.series_name.strip() != series.series_name.strip()
        ):
            conflicts.append(
                f"series_name: document serves {document.series_name.strip()!r}; "
                f"relation serves {series.series_name.strip()!r}"
            )
        document_cik = _document_cik(document)
        if document_cik is not None and document_cik != series.cik:
            conflicts.append(
                f"registrant_cik: document serves {document_cik}; "
                f"relation serves {series.cik}"
            )
        resolved_classes = tuple(
            classes[class_id]
            for class_id in sorted(classes)
            if classes[class_id].series_id == series.series_id
        )
    else:
        resolved_classes = ()
    return NMfpSeriesResolution(
        series_id=document.series_id,
        resolved=series is not None,
        relation_present=tip is not None,
        snapshot_id=tip,
        series=series,
        classes=resolved_classes,
        document_series_name=document.series_name,
        document_series_lei=document.series_lei,
        conflicts=tuple(conflicts),
    )


class SeriesClassSurfaces:
    """Series/class lookup surfaces hosted by the ``Edgar`` facade."""

    artifacts_root: Path | None

    def fund_series(self, series_id: str) -> FundSeriesResult:
        """One series from the published relation; a miss is absence."""
        return read_fund_series(self.artifacts_root, series_id)

    def fund_class(self, class_id: str) -> FundClassResult:
        """One class from the published relation; a miss is absence."""
        return read_fund_class(self.artifacts_root, class_id)

    def fund_series_classes(self, series_id: str) -> FundClassesResult:
        """The classes of one series, from the published relation."""
        return read_series_classes(self.artifacts_root, series_id)

    def fund_registrant_series(self, cik: str | int) -> FundSeriesListResult:
        """The series of one registrant, from the published relation."""
        return read_registrant_series(self.artifacts_root, cik)

    def fund_ticker_classes(self, symbol: str) -> FundClassesResult:
        """The classes tickered under one symbol, from the relation."""
        return read_ticker_classes(self.artifacts_root, symbol)

    def resolve_nmfp_series(self, document: "FormNMfpDocument") -> NMfpSeriesResolution:
        """Resolve an N-MFP document's series id against the relation."""
        return resolve_nmfp_series(document, self.artifacts_root)
