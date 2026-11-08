"""Selection rows for the client operator: seeds, combinators, inspection.

Rows contribute through ``register(registry)`` and ``GATHERERS``; operator
imports stay inside functions so this module loads standalone.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import MISSING, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from edgar_sec.foundation.runtime.interactive import prompt_confirm, prompt_text
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "ClearSetsOptions",
    "CombineOptions",
    "DiffOptions",
    "DropSetOptions",
    "FilterAccessionsOptions",
    "FilterFormOptions",
    "PeekOptions",
    "SeedCompanyOptions",
    "SeedDatasetOptions",
    "SeedQueryOptions",
    "SeedSnapshotOptions",
    "VarsOptions",
    "build_specs",
    "catalog_rows",
    "filter_result_to_accessions",
    "make_working_set",
    "register",
    "result_accessions",
    "store_working_set",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


_INTO = "Names the target set; the seed makes it the current set."
_SOURCE = "Name of the set to filter; empty means the current set."
_INTO_SOURCE = "Target set name; empty means the source set, updated in place."
_QUERY_HELP = "Selects by ticker. Refusal: a seed with no tickers, CIKs, accessions, forms, or dates is refused; a limit alone is not a constraint."
_SNAP_HELP = "Selects by form. Refusal: a seed with no forms, CIKs, or dates is refused; a limit alone is not a constraint."
_ID_HELP = "Company identifier: a CIK or ticker resolves directly; a name resolves through scored candidates over the catalog's name data, and a near-tie refuses with the candidates listed rather than picking one. It is the seed's constraint, so an empty identifier is refused."
_FILE_HELP = "JSON or Parquet dataset with an accession column/list (the xbrl_review dataset idiom); the file is the constraint, so an empty path is refused. Accessions only are retained, never a result."
_FORM_HELP = "Forms to remove or keep; an empty list is refused, and a set with no retained result is refused because its forms cannot be known."
_MSG_QUERY = "seed refused: no constraining input (tickers, ciks, accessions, forms, or dates); a limit alone is not a constraint"
_MSG_SNAP = "seed refused: no constraining input (forms, ciks, or dates); a limit alone is not a constraint"


@dataclass(frozen=True, slots=True)
class SeedQueryOptions:
    """Options for seeding a set from a fetch query."""

    into: str = _f("main", _INTO)
    tickers: tuple[str, ...] = _f((), _QUERY_HELP)
    ciks: tuple[str, ...] = _f((), "Selects by CIK; see tickers for the refusal rule.")
    accessions: tuple[str, ...] = _f((), "Selects by accession; see tickers.")
    forms: tuple[str, ...] = _f((), "Selects by form; forms alone constrain a seed.")
    dates: str | None = _f(None, "Facade date vocabulary (e.g. 2024); dates constrain.")
    limit: int | None = _f(None, "Caps filings; a limit alone is not a constraint.")


@dataclass(frozen=True, slots=True)
class SeedSnapshotOptions:
    """Options for seeding a set from a snapshot query."""

    into: str = _f("main", _INTO)
    forms: tuple[str, ...] = _f((), _SNAP_HELP)
    ciks: tuple[str, ...] = _f((), "Selects by CIK; see forms for the refusal rule.")
    dates: str | None = _f(None, "Facade date vocabulary; dates alone constrain.")
    limit: int | None = _f(None, "Caps filings; a limit alone is not a constraint.")


@dataclass(frozen=True, slots=True)
class SeedCompanyOptions:
    """Options for seeding a set from one company's filings."""

    into: str = _f("main", _INTO)
    identifier: str = _f("", _ID_HELP)
    forms: tuple[str, ...] = _f((), "Narrows the company's filings by form type.")
    dates: str | None = _f(None, "Narrows the company's filings by date selection.")
    limit: int | None = _f(None, "Caps the number of filings taken.")


@dataclass(frozen=True, slots=True)
class SeedDatasetOptions:
    """Options for seeding a set from a dataset file's accession list."""

    into: str = _f("main", _INTO)
    file: Path = _f(Path(""), _FILE_HELP)


@dataclass(frozen=True, slots=True)
class CombineOptions:
    """Options for a binary combinator over two named sets."""

    left: str = _f("", "Name of the left set; empty means the current set.")
    right: str = _f("", "Name of the right set; it must name an existing set.")
    into: str = _f("", "Target set name; empty means the left set's name.")


@dataclass(frozen=True, slots=True)
class FilterAccessionsOptions:
    """Options for removing or keeping listed accessions in a set."""

    source: str = _f("", _SOURCE)
    into: str = _f("", _INTO_SOURCE)
    accessions: tuple[str, ...] = _f(
        (), "Accessions to remove or keep; empty is refused."
    )


@dataclass(frozen=True, slots=True)
class FilterFormOptions:
    """Options for removing or keeping filings of listed forms in a set."""

    source: str = _f("", _SOURCE)
    into: str = _f("", _INTO_SOURCE)
    forms: tuple[str, ...] = _f((), _FORM_HELP)


@dataclass(frozen=True, slots=True)
class DropSetOptions:
    """Options for dropping one named set."""

    name: str = _f("", "Name of the set to drop; empty means the current set.")


@dataclass(frozen=True, slots=True)
class ClearSetsOptions:
    """Options for clearing every named set."""


@dataclass(frozen=True, slots=True)
class VarsOptions:
    """Options for listing the named sets."""


@dataclass(frozen=True, slots=True)
class PeekOptions:
    """Options for showing a set's first rows."""

    name: str = _f("", "Name of the set to peek at; empty means the current set.")
    limit: int = _f(10, "Maximum rows shown; total versus shown is declared.")


@dataclass(frozen=True, slots=True)
class DiffOptions:
    """Options for comparing two named sets."""

    left: str = _f("", "Name of the left set; empty means the current set.")
    right: str = _f("", "Name of the right set; it must name an existing set.")
    sample_limit: int = _f(5, "Maximum sample accessions per side. Refused below 0.")


def _accession_text(filing: Any) -> str:
    accession = getattr(filing, "accession", filing)
    return str(getattr(accession, "value", accession))


def catalog_rows(result: Any) -> list[dict[str, Any]]:
    """Catalog-index rows for a retained result, from its catalog surface."""
    if result is None:
        return []
    to_arrow = getattr(result, "to_arrow", None)
    if callable(to_arrow):
        table = to_arrow()
        return [
            {k: ("" if v is None else v) for k, v in row.items()}
            for row in table.to_pylist()
        ]
    sql = getattr(result, "sql", None)
    if callable(sql):
        query = "SELECT accession, form, filing_date FROM catalog ORDER BY accession"
        return [
            {"accession": r[0], "form": r[1] or "", "filing_date": r[2] or ""}
            for r in sql(query).fetchall()
        ]
    rows: list[dict[str, Any]] = []
    try:
        iterator = iter(result)
    except TypeError:
        return rows
    for filing in iterator:
        form = str(getattr(filing, "form", "") or "")
        date = str(getattr(filing, "filing_date", "") or "")
        rows.append(
            {"accession": _accession_text(filing), "form": form, "filing_date": date}
        )
    return rows


def result_accessions(result: Any) -> frozenset[str]:
    """The accession key set of a retained result, via its catalog rows."""
    return frozenset(
        str(r["accession"]) for r in catalog_rows(result) if r.get("accession")
    )


def filter_result_to_accessions(result: Any, keep: frozenset[str]) -> Any:
    """A retained result narrowed to ``keep`` accessions, or None if inexpressible."""
    if result is None:
        return None
    items = getattr(result, "items", None)
    if items is not None:
        return replace(
            result, items=tuple(i for i in items if _accession_text(i) in keep)
        )
    if getattr(result, "query_backed", False) and getattr(result, "query_sql", None):
        if keep:
            ordered = sorted(keep)
            marks = ", ".join("?" for _ in ordered)
            sql = f"SELECT * FROM ({result.query_sql}) WHERE accession IN ({marks})"
            params = tuple(result.query_params) + tuple(ordered)
        else:
            sql = f"SELECT * FROM ({result.query_sql}) WHERE 1 = 0"
            params = tuple(result.query_params)
        return replace(result, query_sql=sql, query_params=params)
    if hasattr(result, "items"):
        collected = tuple(i for i in result if _accession_text(i) in keep)
        return replace(
            result, items=collected, snapshot_backed=False, query_backed=False
        )
    accessions = getattr(result, "accessions", None)
    if isinstance(accessions, (list, tuple)):
        import copy

        clone = copy.copy(result)
        clone.accessions = [a for a in accessions if str(a) in keep]
        return clone
    return None


def make_working_set(accessions: Iterable[str] | None = None, *, result: Any = None):
    """Build a WorkingSet; a result alone takes its catalog accessions.

    Shared construction for later feed-event and local-search seeds.
    """
    from edgar_sec.apps.client.operator import WorkingSet

    if accessions is None:
        accessions = result_accessions(result) if result is not None else ()
    return WorkingSet(accessions=frozenset(accessions), result=result)


def store_working_set(
    session: Any,
    name: str,
    accessions: Iterable[str] | None = None,
    *,
    result: Any = None,
):
    """Store a set built by ``make_working_set`` and make it the current set."""
    working = make_working_set(accessions, result=result)
    return session.add_set(name, working.accessions, result=working.result)


def _key_value(title: str, data: dict[str, Any], rows: Iterable[tuple[str, str]]):
    from edgar_sec.apps.client.operator import OpResult

    components = tuple(KeyValueRow(label, value) for label, value in rows)
    values = {"kind": "key_value", "title": title, "components": components}
    values["data"] = data
    values["total"] = values["shown"] = len(components)
    values["hints"] = ("vars", "peek")
    return OpResult(**values)


def _grid(
    title: str, data: dict[str, Any], headers: tuple[str, ...], rows: tuple, total: int
):
    from edgar_sec.apps.client.operator import OpResult

    values = {"kind": "grid", "title": title, "data": data, "total": total}
    values["components"] = (Grid(headers=headers, rows=rows),)
    values["shown"] = len(rows)
    values["hints"] = ("vars", "diff")
    return OpResult(**values)


def _error(kind: str, code: str, title: str, message: str):
    from edgar_sec.apps.client.operator import OpResult

    values = {"kind": kind, "title": title, "error_code": code}
    values["components"] = (ProseRow(message),)
    values["data"] = {"message": message}
    return OpResult(**values)


def _not_found(kind: str, title: str, name: str):
    return _error(kind, "not_found", title, f"set not found: {name or '(none)'}")


def _resolve(session: Any, name: str) -> tuple[str, Any]:
    resolved = name or session.current_set_name
    return (resolved, session.sets.get(resolved)) if resolved else ("", None)


def _seeded(session: Any, into: str, result: Any, source: str, extra: dict):
    working = store_working_set(session, into, result=result)
    data = {"set": into, "count": len(working), "source": source, **extra}
    rows = (("set", into), ("count", str(len(working))), ("source", source))
    return _key_value(f"Seeded set {into}", data, rows)


def _bad_limit(limit: int | None) -> bool:
    return limit is not None and limit < 1


def _execute_seed_query(options: SeedQueryOptions, session: Any):
    title = "Seed from fetch query"
    if not (
        options.tickers
        or options.ciks
        or options.accessions
        or options.forms
        or options.dates
    ):
        return _error("key_value", "refused", title, _MSG_QUERY)
    if _bad_limit(options.limit):
        return _error("key_value", "invalid_options", title, "limit below 1")
    context = session.read_context
    result = session.facade.fetch(
        tickers=tuple(options.tickers),
        ciks=tuple(options.ciks),
        accessions=tuple(options.accessions),
        forms=tuple(options.forms),
        dates=options.dates,
        limit=options.limit,
        mode=context.mode,
        snapshot=context.snapshot,
    )
    extra = {"mode": context.mode, "snapshot": context.snapshot}
    return _seeded(session, options.into, result, "query", extra)


def _execute_seed_snapshot(options: SeedSnapshotOptions, session: Any):
    title = "Seed from snapshot query"
    if not (options.forms or options.ciks or options.dates):
        return _error("key_value", "refused", title, _MSG_SNAP)
    if _bad_limit(options.limit):
        return _error("key_value", "invalid_options", title, "limit below 1")
    snapshot = session.read_context.snapshot
    result = session.facade.from_snapshot(
        snapshot,
        forms=tuple(options.forms),
        ciks=tuple(options.ciks),
        dates=options.dates,
        limit=options.limit,
    )
    return _seeded(session, options.into, result, "snapshot", {"snapshot": snapshot})


def _execute_seed_company(options: SeedCompanyOptions, session: Any):
    title = "Seed from company filings"
    if not options.identifier.strip():
        return _error("key_value", "refused", title, "seed refused: no identifier")
    if _bad_limit(options.limit):
        return _error("key_value", "invalid_options", title, "limit below 1")
    from edgar_sec.apps.client.operator_company import _resolve_company

    company, resolution, failure = _resolve_company(
        session, options.identifier, "key_value"
    )
    if failure is not None:
        return failure
    result = company.filings(
        forms=tuple(options.forms) or None, limit=options.limit, dates=options.dates
    )
    extra = {"identifier": options.identifier, "via": resolution.get("via", "")}
    return _seeded(session, options.into, result, "company", extra)


def _accessions_from_json(payload: Any) -> list[str]:
    items = payload.get("accessions", []) if isinstance(payload, dict) else payload
    found: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str) and item:
                found.append(item)
            elif isinstance(item, dict) and item.get("accession"):
                found.append(str(item["accession"]))
    return found


def _dataset_accessions(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _accessions_from_json(json.loads(path.read_text(encoding="utf-8")))
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["accession"])
        return [str(v) for v in table.column("accession").to_pylist() if v]
    raise ValueError(f"unsupported dataset file type: {suffix or 'none'}")


def _execute_seed_dataset(options: SeedDatasetOptions, session: Any):
    title = "Seed from dataset file"
    if str(options.file) in ("", "."):
        return _error("key_value", "refused", title, "seed refused: no dataset file")
    if not options.file.is_file():
        return _error(
            "key_value", "not_found", title, f"no dataset file: {options.file}"
        )
    try:
        accessions = _dataset_accessions(options.file)
    except Exception as exc:  # noqa: BLE001 - a bad dataset is a coded refusal
        return _error("key_value", "invalid_options", title, str(exc))
    working = store_working_set(session, options.into, accessions)
    data = {"set": options.into, "count": len(working), "source": "dataset"}
    rows = (("set", options.into), ("count", str(len(working))), ("source", "dataset"))
    return _key_value(f"Seeded set {options.into}", data, rows)


def _combine(session: Any, options: CombineOptions, mode: str, title: str):
    left_name, left = _resolve(session, options.left)
    right = session.sets.get(options.right) if options.right else None
    if left is None:
        return _not_found("key_value", title, left_name)
    if right is None:
        return _not_found("key_value", title, options.right)
    if mode == "union":
        survivors = left.accessions | right.accessions
        retained = None
        if left.result is not None and right.accessions <= left.accessions:
            retained = left.result
        elif right.result is not None and left.accessions <= right.accessions:
            retained = right.result
    elif mode == "intersect":
        survivors = left.accessions & right.accessions
        base = left if left.result is not None else right
        retained = None
        if base.result is not None:
            retained = filter_result_to_accessions(base.result, frozenset(survivors))
    else:
        survivors = left.accessions - right.accessions
        retained = None
        if left.result is not None:
            retained = filter_result_to_accessions(left.result, frozenset(survivors))
    into = options.into or left_name
    working = store_working_set(session, into, survivors, result=retained)
    data = {"set": into, "left": left_name, "right": options.right}
    data["count"] = len(working)
    data["retained_result"] = retained is not None
    rows = (
        ("set", into),
        ("left", f"{left_name} ({len(left)})"),
        ("right", f"{options.right} ({len(right)})"),
        ("count", str(len(working))),
    )
    return _key_value(title, data, rows)


def _execute_union(options: CombineOptions, session: Any):
    return _combine(session, options, "union", "Set union")


def _execute_intersect(options: CombineOptions, session: Any):
    return _combine(session, options, "intersect", "Set intersect")


def _execute_difference(options: CombineOptions, session: Any):
    return _combine(session, options, "difference", "Set difference")


def _filter_accessions(session, options, keep: bool, title: str):
    name, source = _resolve(session, options.source)
    if source is None:
        return _not_found("key_value", title, name)
    if not options.accessions:
        return _error("key_value", "invalid_options", title, "accession list required")
    listed = frozenset(options.accessions)
    survivors = source.accessions & listed if keep else source.accessions - listed
    retained = None
    if source.result is not None:
        retained = filter_result_to_accessions(source.result, frozenset(survivors))
    into = options.into or name
    working = store_working_set(session, into, survivors, result=retained)
    data = {"set": into, "source": name, "count": len(working)}
    rows = (("set", into), ("source", name), ("count", str(len(working))))
    return _key_value(title, data, rows)


def _execute_remove_accessions(options: FilterAccessionsOptions, session: Any):
    return _filter_accessions(session, options, keep=False, title="Remove accessions")


def _execute_keep_accessions(options: FilterAccessionsOptions, session: Any):
    return _filter_accessions(session, options, keep=True, title="Keep accessions")


def _filter_form(session: Any, options: FilterFormOptions, keep: bool, title: str):
    name, source = _resolve(session, options.source)
    if source is None:
        return _not_found("key_value", title, name)
    if not options.forms:
        return _error("key_value", "invalid_options", title, "a form list is required")
    if source.result is None:
        return _error(
            "key_value",
            "refused",
            title,
            f"set {name} has no retained result, so its forms cannot be known",
        )
    wanted = {form.upper() for form in options.forms}
    by_accession = {
        str(r["accession"]): str(r.get("form") or "").upper()
        for r in catalog_rows(source.result)
    }
    survivors = frozenset(
        a for a in source.accessions if (by_accession.get(a, "") in wanted) == keep
    )
    retained = filter_result_to_accessions(source.result, survivors)
    into = options.into or name
    working = store_working_set(session, into, survivors, result=retained)
    data = {"set": into, "source": name, "count": len(working), "forms": sorted(wanted)}
    rows = (("set", into), ("source", name), ("count", str(len(working))))
    return _key_value(title, data, rows)


def _execute_remove_form(options: FilterFormOptions, session: Any):
    return _filter_form(session, options, keep=False, title="Remove by form")


def _execute_keep_form(options: FilterFormOptions, session: Any):
    return _filter_form(session, options, keep=True, title="Keep by form")


def _execute_drop_set(options: DropSetOptions, session: Any):
    name, working = _resolve(session, options.name)
    if working is None:
        return _not_found("key_value", "Drop set", name)
    del session.sets[name]
    if session.current_set_name == name:
        session.current_set_name = ""
    data = {"dropped": name, "count": len(working)}
    rows = (("dropped", name), ("count", str(len(working))))
    return _key_value("Drop set", data, rows)


def _execute_clear_sets(options: ClearSetsOptions, session: Any):
    cleared = len(session.sets)
    session.sets.clear()
    session.current_set_name = ""
    return _key_value("Clear sets", {"cleared": cleared}, (("cleared", str(cleared)),))


def _execute_vars(options: VarsOptions, session: Any):
    rows: list[tuple[str, ...]] = []
    sets: list[dict[str, Any]] = []
    for name in sorted(session.sets):
        count = len(session.sets[name])
        current = name == session.current_set_name
        rows.append((name, str(count), "current" if current else ""))
        sets.append({"name": name, "count": count, "current": current})
    data = {"sets": sets, "current_set": session.current_set_name}
    return _grid(
        "Working sets", data, ("set", "count", "current"), tuple(rows), len(rows)
    )


def _execute_peek(options: PeekOptions, session: Any):
    name, working = _resolve(session, options.name)
    if working is None:
        return _not_found("grid", "Peek set", name)
    if options.limit < 1:
        return _error("grid", "invalid_options", "Peek set", "limit below 1")
    if working.result is not None:
        catalog = {
            str(r["accession"]): r
            for r in catalog_rows(working.result)
            if str(r.get("accession")) in working.accessions
        }
        shown = [catalog[key] for key in sorted(catalog)][: options.limit]
        data_rows = [
            {
                "accession": str(r["accession"]),
                "form": str(r.get("form") or ""),
                "filing_date": str(r.get("filing_date") or ""),
            }
            for r in shown
        ]
        grid_rows = tuple(
            (r["accession"], r["form"], r["filing_date"]) for r in data_rows
        )
        return _grid(
            f"Peek {name}",
            {"set": name, "rows": data_rows},
            ("accession", "form", "filing_date"),
            grid_rows,
            len(working),
        )
    ordered = sorted(working.accessions)[: options.limit]
    data_rows = [{"accession": item} for item in ordered]
    grid_rows = tuple((item,) for item in ordered)
    return _grid(
        f"Peek {name}",
        {"set": name, "rows": data_rows},
        ("accession",),
        grid_rows,
        len(working),
    )


def _execute_diff(options: DiffOptions, session: Any):
    title = "Diff sets"
    left_name, left = _resolve(session, options.left)
    right = session.sets.get(options.right) if options.right else None
    if left is None:
        return _not_found("key_value", title, left_name)
    if right is None:
        return _not_found("key_value", title, options.right)
    if options.sample_limit < 0:
        return _error("key_value", "invalid_options", title, "sample_limit below 0")
    both = left.accessions & right.accessions
    left_only = left.accessions - right.accessions
    right_only = right.accessions - left.accessions
    cap = options.sample_limit
    data = {"left": left_name, "right": options.right, "left_total": len(left)}
    data["right_total"] = len(right)
    data["intersection"] = len(both)
    data["left_only"] = len(left_only)
    data["right_only"] = len(right_only)
    data["intersection_sample"] = sorted(both)[:cap]
    data["left_only_sample"] = sorted(left_only)[:cap]
    data["right_only_sample"] = sorted(right_only)[:cap]
    rows = (
        ("left", f"{left_name} ({len(left)})"),
        ("right", f"{options.right} ({len(right)})"),
        ("intersection", str(len(both))),
        ("left only", str(len(left_only))),
        ("right only", str(len(right_only))),
    )
    return _key_value(title, data, rows)


_READS = frozenset({"vars", "peek", "diff"})
_GRID_KIND = frozenset({"vars", "peek"})
_LABELS = {
    "seed_query": "Seed from fetch query",
    "seed_snapshot": "Seed from snapshot query",
    "seed_company": "Seed from company filings",
    "seed_dataset": "Seed from dataset file",
    "union": "Set union",
    "intersect": "Set intersect",
    "difference": "Set difference",
    "remove_accessions": "Remove accessions",
    "keep_accessions": "Keep accessions",
    "remove_form": "Remove by form",
    "keep_form": "Keep by form",
    "drop_set": "Drop set",
    "clear_sets": "Clear sets",
    "vars": "List working sets",
    "peek": "Peek at a set",
    "diff": "Diff two sets",
}
_SPEC_ROWS = (
    ("seed_query", SeedQueryOptions, _execute_seed_query),
    ("seed_snapshot", SeedSnapshotOptions, _execute_seed_snapshot),
    ("seed_company", SeedCompanyOptions, _execute_seed_company),
    ("seed_dataset", SeedDatasetOptions, _execute_seed_dataset),
    ("union", CombineOptions, _execute_union),
    ("intersect", CombineOptions, _execute_intersect),
    ("difference", CombineOptions, _execute_difference),
    ("remove_accessions", FilterAccessionsOptions, _execute_remove_accessions),
    ("keep_accessions", FilterAccessionsOptions, _execute_keep_accessions),
    ("remove_form", FilterFormOptions, _execute_remove_form),
    ("keep_form", FilterFormOptions, _execute_keep_form),
    ("drop_set", DropSetOptions, _execute_drop_set),
    ("clear_sets", ClearSetsOptions, _execute_clear_sets),
    ("vars", VarsOptions, _execute_vars),
    ("peek", PeekOptions, _execute_peek),
    ("diff", DiffOptions, _execute_diff),
)


def _spec(row: tuple):
    from edgar_sec.apps.client.operator import OperationSpec

    op_id, options_type, executor = row
    values = {"id": op_id, "label": _LABELS[op_id], "options_type": options_type}
    values["effect"] = "reads_state" if op_id in _READS else "mutates_selection"
    values["requires"] = "none"
    values["result_kind"] = "grid" if op_id in _GRID_KIND else "key_value"
    values["hints"] = ("vars", "peek")
    values["executor"] = executor
    return OperationSpec(**values)


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    return tuple(_spec(row) for row in _SPEC_ROWS)


def register(registry: dict) -> dict:
    """Add this module's rows to ``registry``, refusing duplicate ids."""
    from edgar_sec.apps.client.operator import assemble_registry

    specs = build_specs()
    assemble_registry(registry.values(), specs)
    for spec in specs:
        registry[spec.id] = spec
    return registry


def __getattr__(name: str):
    if name == "SPECS":
        return build_specs()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _split(raw: str) -> tuple[str, ...]:
    return tuple(raw.replace(",", " ").split())


def _current(session: Any) -> str:
    return str(getattr(session, "current_set_name", "") or "main")


def _parse_int(raw: str, default: int | None) -> int | None:
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


def _bool_prompt(options_type: type, name: str, label: str) -> str:
    if name == "confirm":
        return "capture this search to disk?"
    if name == "exhaustive":
        names = {item.name for item in fields(options_type)}
        return "exhaustive capture?" if "confirm" in names else "exhaustive retrieval?"
    return f"{label}?"


def _gather_options(session: Any, options_type: type):
    """Prompt for one row's fields by dataclass type; the menu gather mechanism.

    Sequences prompt as separated lists, ints fall back to their default,
    set-name fields default to the current set. Steps 4-7 rows reuse this.
    """
    hints = get_type_hints(options_type)
    values: dict[str, Any] = {}
    for item in fields(options_type):
        annotation = hints.get(item.name, item.type)
        default = None if item.default is MISSING else item.default
        label = item.name.replace("_", " ")
        if annotation is bool:
            values[item.name] = prompt_confirm(
                _bool_prompt(options_type, item.name, label), bool(default)
            )
        elif get_origin(annotation) is tuple:
            values[item.name] = _split(prompt_text(label, ""))
        elif annotation is Path:
            values[item.name] = Path(prompt_text(label, "").strip())
        elif int in get_args(annotation) or annotation is int:
            fallback = default if isinstance(default, int) else None
            raw = prompt_text(label, "" if fallback is None else str(fallback))
            values[item.name] = _parse_int(raw, fallback)
        elif item.name in ("into", "source", "left", "name"):
            values[item.name] = prompt_text(label, _current(session)).strip()
        elif str in get_args(annotation):
            values[item.name] = prompt_text(label, "").strip() or None
        else:
            values[item.name] = prompt_text(label, str(default or "")).strip()
    return options_type(**values)


GATHERERS: dict[str, Callable[[Any], Any]] = {
    row[0]: (lambda session, kind=row[1]: _gather_options(session, kind))
    for row in _SPEC_ROWS
}
