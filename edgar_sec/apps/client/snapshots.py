"""DAG snapshot management console and offline filing retrieval engine."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
import threading
from typing import Any

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.document.canonical import CanonicalAttachmentRow
from edgar_sec.apps.runner.config import DateFilterInput
from edgar_sec.domain.filing_catalog.filters import (
    DateSelection,
    resolve_date_selection,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.filing_catalog.document_names import (
    PRIMARY_EXHIBIT_FILENAME_PATTERN,
)
from edgar_sec.domain.forms.common.aliases import (
    FORM_FAMILY_ALIASES,
    FORM_FAMILY_SUFFIXES,
)
from edgar_sec.engine.forms.render import render_filing
from edgar_sec.engine.selection.predicates import date_selection_sql
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.resolution import compile_virtual_views
from edgar_sec.infra.storage.dag.traversal import LineageChain, walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_literal
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.specs import (
    ACQUISITION_RELATIONS,
)


class SnapshotConsole:
    """Management console for DAG snapshot tags, branches, and retention."""

    def __init__(self, artifacts_root: Path | str | None = None) -> None:
        self.artifacts_root = (
            Path(artifacts_root)
            if artifacts_root is not None
            else resolve_paths().artifacts_root
        )
        self.snapshots_root = resolve_acquisition_paths(
            artifacts_root=self.artifacts_root
        ).snapshots_root

    def _catalog(self) -> DAGCatalog:
        return DAGCatalog(self.snapshots_root)

    def tag(self, name: str, snapshot_id: str | None = None, message: str = "") -> None:
        """Create or update an immutable tag pointing to a snapshot."""
        catalog = self._catalog()
        target_id = snapshot_id
        if target_id is None:
            ptr = catalog.read_pointer("main")
            if ptr is None:
                raise ValueError(
                    "cannot tag without snapshot_id: main branch has no tip"
                )
            target_id = str(ptr["snapshot_id"])
        catalog.create_tag(name, target_id, message=message)

    def tags(self) -> list[dict[str, Any]]:
        """List all registered tags."""
        return self._catalog().list_tags()

    def get_tag(self, name: str) -> dict[str, Any] | None:
        """Retrieve tag record by name."""
        return self._catalog().get_tag(name)

    def delete_tag(self, name: str) -> bool:
        """Delete a tag by name."""
        return self._catalog().delete_tag(name)

    def branches(self) -> dict[str, str]:
        """Return all branch names and their tip snapshot IDs."""
        return self._catalog().list_branches()

    def current(self, branch: str = "main") -> str | None:
        """Return the tip snapshot ID for the given branch."""
        ptr = self._catalog().read_pointer(branch)
        return str(ptr["snapshot_id"]) if ptr is not None else None

    def list(self) -> list[dict[str, Any]]:
        """List all snapshots in topological order."""
        return self._catalog().list_snapshots()

    def gc(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Collect unreferenced snapshots and reclaim disk space."""
        from edgar_sec.infra.storage.dag.retention import (
            analyze_retention,
            purge_unreferenced,
        )

        report = analyze_retention(self.snapshots_root)
        purged = purge_unreferenced(self.snapshots_root, report, dry_run=dry_run)
        return {
            "reclaimed_bytes": report.prunable_byte_size,
            "purged_snapshots": purged,
            "prunable_snapshots": list(report.prunable_snapshots),
            "dry_run": dry_run,
        }


def query_filings_from_snapshot(
    artifacts_root: Path | str | None = None,
    *,
    snapshot_id_or_tag: str = "main",
    forms: Sequence[str] = (),
    ciks: Sequence[str | int] = (),
    dates: DateFilterInput = None,
    limit: int | None = None,
) -> FilingsResult:
    """Hydrate a FilingsResult directly from a published DAG snapshot."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    snapshots_root = resolve_acquisition_paths(artifacts_root=root).snapshots_root
    catalog = DAGCatalog(snapshots_root)

    resolved_id: str | None = None
    tag = catalog.get_tag(snapshot_id_or_tag)
    if tag is not None:
        resolved_id = str(tag["snapshot_id"])
    else:
        ptr = catalog.read_pointer(snapshot_id_or_tag)
        if ptr is not None:
            resolved_id = str(ptr["snapshot_id"])
        elif catalog.has_snapshot(snapshot_id_or_tag):
            resolved_id = snapshot_id_or_tag

    if resolved_id is None:
        raise ValueError(f"snapshot, tag, or branch not found: {snapshot_id_or_tag!r}")

    target_forms = {f.upper() for f in forms} if forms else None
    target_ciks = {str(Cik.from_raw(c).value).zfill(10) for c in ciks} if ciks else None
    resolved_dates = resolve_date_selection(dates)
    return FilingsResult(
        run_id=f"snapshot-{resolved_id}",
        plan_id="",
        target_parquet_glob="",
        run_state_sqlite_path=Path(""),
        artifacts_root=root,
        snapshot_id=resolved_id,
        snapshot_backed=True,
        snapshot_forms=tuple(sorted(target_forms or ())),
        snapshot_ciks=tuple(sorted(target_ciks or ())),
        snapshot_date_selection=resolved_dates,
        snapshot_limit=limit,
    )


def _snapshot_lineage(
    artifacts_root: Path, snapshot_id: str
) -> tuple[Path, LineageChain]:
    snapshots_root = resolve_acquisition_paths(
        artifacts_root=artifacts_root
    ).snapshots_root
    return snapshots_root, walk_lineage(snapshots_root, snapshot_id)


def is_exhibit_sql(document_type_expr: str, filename_expr: str) -> str:
    """SQL translation of ``is_exhibit_attachment`` over the given expressions."""
    pattern = sql_literal(PRIMARY_EXHIBIT_FILENAME_PATTERN)
    return (
        f"(upper({document_type_expr}) LIKE 'EX-%' OR "
        f"regexp_full_match({filename_expr}, {pattern}))"
    )


_FORM_ALIAS_MAP: dict[str, str] = {
    alias.upper(): family
    for family, aliases in FORM_FAMILY_ALIASES.items()
    for alias in aliases
} | {family: family for family in FORM_FAMILY_ALIASES}


def register_form_alias_map(con: Any) -> None:
    """Register the alias lookup table the role translation reads from."""
    rows = ", ".join(
        f"({sql_literal(raw)}, {sql_literal(family)})"
        for raw, family in sorted(_FORM_ALIAS_MAP.items())
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE form_alias_map (raw VARCHAR, family VARCHAR)"
    )
    con.execute(f"INSERT INTO form_alias_map VALUES {rows}")


def _sql_trim(expr: str) -> str:
    return (
        f"regexp_replace(regexp_replace(COALESCE({expr}, ''), "
        f"'^\\s+', ''), '\\s+$', '')"
    )


def _sql_upper_trim(expr: str) -> str:
    return f"upper({_sql_trim(expr)})"


def _sql_lower_trim(expr: str) -> str:
    return f"lower({_sql_trim(expr)})"


def _sql_collapse(expr: str) -> str:
    return f"regexp_replace({_sql_upper_trim(expr)}, '\\s+', ' ', 'g')"


def _sql_form_family(collapsed_expr: str) -> str:
    result = collapsed_expr
    for suffix in FORM_FAMILY_SUFFIXES:
        result = f"regexp_replace({result}, {sql_literal(suffix + '$')}, '')"
    result = f"trim({result}, '_-')"
    return f"CASE WHEN {result} = '' THEN {collapsed_expr} ELSE {result} END"


def _sql_normalize_form(expr: str) -> str:
    collapsed = _sql_collapse(expr)
    family = _sql_form_family(collapsed)
    return (
        "coalesce("
        f"(SELECT family FROM form_alias_map WHERE raw = {collapsed}), "
        f"(SELECT family FROM form_alias_map WHERE raw = {family}), "
        f"{collapsed})"
    )


def attachment_role_sql(
    table_kind_expr: str, document_type_expr: str, form_expr: str
) -> str:
    """SQL translation of ``attachment_role``; needs ``register_form_alias_map``."""
    doc_type = _sql_upper_trim(document_type_expr)
    primary = (
        f"COALESCE({form_expr}, '') <> '' AND {doc_type} <> '' AND "
        f"{_sql_normalize_form(document_type_expr)} = "
        f"{_sql_normalize_form(form_expr)}"
    )
    return (
        "CASE "
        f"WHEN {table_kind_expr} = 'data_file' THEN 'data_file' "
        f"WHEN {doc_type} = 'GRAPHIC' AND "
        f"{table_kind_expr} IS DISTINCT FROM 'data_file' THEN 'graphic' "
        f"WHEN {primary} THEN 'primary' "
        f"WHEN starts_with({doc_type}, 'EX-') THEN 'exhibit' "
        "ELSE NULL END"
    )


def classify_linkbase_sql(
    document_type_expr: str, filename_expr: str, description_expr: str
) -> str:
    """SQL translation of ``classify_linkbase`` over the given expressions."""
    dt = _sql_upper_trim(document_type_expr)
    fn = _sql_lower_trim(filename_expr)
    desc = _sql_upper_trim(description_expr)
    return (
        "CASE "
        f"WHEN {dt} = 'EX-101.CAL' OR ends_with({fn}, '_cal.xml') OR "
        f"contains({desc}, 'CALCULATION LINKBASE') THEN 'calculation' "
        f"WHEN {dt} = 'EX-101.PRE' OR ends_with({fn}, '_pre.xml') OR "
        f"contains({desc}, 'PRESENTATION LINKBASE') THEN 'presentation' "
        f"WHEN {dt} = 'EX-101.DEF' OR ends_with({fn}, '_def.xml') OR "
        f"contains({desc}, 'DEFINITION LINKBASE') THEN 'definition' "
        f"WHEN {dt} = 'EX-101.LAB' OR ends_with({fn}, '_lab.xml') OR "
        f"contains({desc}, 'LABEL LINKBASE') THEN 'label' "
        f"WHEN {dt} = 'EX-101.SCH' OR ends_with({fn}, '.xsd') OR "
        f"contains({desc}, 'TAXONOMY EXTENSION SCHEMA') THEN 'schema' "
        f"WHEN {dt} = 'EX-101.INS' OR "
        f"(starts_with({dt}, 'EX-') AND ends_with({dt}, '.INS')) OR "
        f"ends_with({fn}, '_htm.xml') OR "
        f"contains({desc}, 'EXTRACTED XBRL INSTANCE') OR "
        f"contains({desc}, 'XBRL INSTANCE DOCUMENT') THEN 'instance' "
        f"WHEN ends_with({fn}, '-xbrl.zip') OR ends_with({fn}, '_xbrl.zip') "
        "THEN 'package' "
        "ELSE NULL END"
    )


def register_snapshot_views(
    con: Any,
    artifacts_root: Path,
    snapshot_id: str,
    *,
    forms: Sequence[str] = (),
    ciks: Sequence[str] = (),
    dates: DateSelection = (),
    limit: int | None = None,
    filter_forms: Sequence[str] = (),
    date_prefix: str | None = None,
    filter_limit: int | None = None,
    filter_empty: bool = False,
) -> dict[str, str]:
    """Register snapshot-backed result views on an existing DuckDB connection."""
    snapshots_root, lineage = _snapshot_lineage(artifacts_root, snapshot_id)
    views = compile_virtual_views(con, ACQUISITION_RELATIONS, lineage, snapshots_root)
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW accession_ciks AS "
        f"SELECT * FROM {sql_identifier(views['accession_ciks'])}"
    )
    target_view = sql_identifier(views["target_results"])
    cik_view = sql_identifier(views["accession_ciks"])
    selected = ["accession IS NOT NULL"]
    if forms:
        form_literals = [sql_literal(form.upper()) for form in forms]
        selected.append("upper(form) IN (" + ", ".join(form_literals) + ")")
    raw_cik = "COALESCE(c.cik, regexp_extract(t.target_url, 'data/([0-9]+)/', 1))"
    normalized_cik = f"printf('%010d', try_cast({raw_cik} AS BIGINT))"
    if ciks:
        cik_literals = [sql_literal(cik) for cik in ciks]
        selected.append("cik IN (" + ", ".join(cik_literals) + ")")
    if dates:
        selected.append("(" + date_selection_sql(dates) + ")")
    where = " AND ".join(selected)
    limit_sql = f" LIMIT {sql_literal(int(limit))}" if limit is not None else ""
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW initial_targets AS "
        f"SELECT * FROM (SELECT DISTINCT t.target_id, t.accession, t.form, "
        f"t.filing_date, t.target_url, t.outcome, t.selected_sha256, t.byte_size, "
        f"{normalized_cik} AS cik, try_cast(t.filing_date AS DATE) AS parsed_report_date "
        f"FROM {target_view} t LEFT JOIN {cik_view} c ON t.accession = c.accession) "
        f"candidates WHERE {where} ORDER BY accession{limit_sql}"
    )
    post_filters: list[str] = []
    if filter_empty:
        post_filters.append("FALSE")
    if filter_forms:
        post_literals = [sql_literal(form) for form in filter_forms]
        post_filters.append("form IN (" + ", ".join(post_literals) + ")")
    if date_prefix is not None:
        post_filters.append(
            f"starts_with(COALESCE(filing_date, ''), {sql_literal(date_prefix)})"
        )
    post_where = " WHERE " + " AND ".join(post_filters) if post_filters else ""
    post_limit = (
        f" LIMIT {sql_literal(int(filter_limit))}" if filter_limit is not None else ""
    )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW selected_targets AS "
        f"SELECT * FROM initial_targets{post_where} ORDER BY accession{post_limit}"
    )
    selected_view = "selected_targets"
    slots = sql_identifier(views["acquisition_slots"])
    assets = sql_identifier(views["source_assets"])
    slot_types = sql_identifier(views["slot_types"])
    source_payloads = sql_identifier(views["source_payloads"])
    payload_index = sql_identifier(views["payload_index"])
    attempts = sql_identifier(views["acquisition_attempts"])
    register_form_alias_map(con)
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW catalog AS SELECT DISTINCT accession, form, "
        f"filing_date, '' AS report_date, regexp_extract(target_url, '([^/]+)$', 1) "
        f"AS primary_document, target_url AS primary_doc_url FROM {selected_view}"
    )
    con.execute("CREATE OR REPLACE TEMP VIEW filings AS SELECT * FROM catalog")
    filename_expr = (
        "regexp_extract(COALESCE(sa.canonical_path, s.locator), '([^/]+)$', 1)"
    )
    exhibit_predicate = is_exhibit_sql("COALESCE(st.statutory_type, '')", filename_expr)
    form_expr = (
        f"(SELECT form FROM {selected_view} t WHERE t.accession = s.accession LIMIT 1)"
    )
    role_expr = attachment_role_sql("NULL", "st.statutory_type", form_expr)
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW index AS SELECT s.accession, s.sequence, "
        f"COALESCE(st.statutory_type, '') AS document_type, "
        f"{filename_expr} AS filename, "
        f"'' AS description, COALESCE(pi.byte_size, 0) AS size, s.locator AS url, "
        f"{exhibit_predicate} AS is_exhibit, {role_expr} AS role "
        f"FROM {slots} s JOIN (SELECT DISTINCT accession FROM {selected_view}) chosen "
        f"USING (accession) LEFT JOIN {assets} sa ON s.source_asset_id = sa.source_asset_id "
        f"LEFT JOIN {slot_types} st ON s.accession = st.accession AND s.sequence = st.sequence "
        f"LEFT JOIN {source_payloads} sp ON sp.source_asset_id = s.source_asset_id "
        f"LEFT JOIN {payload_index} pi ON pi.payload_sha256 = sp.payload_sha256"
    )
    con.execute("CREATE OR REPLACE TEMP VIEW attachments AS SELECT * FROM index")
    con.execute(
        "CREATE OR REPLACE TEMP VIEW exhibits AS SELECT accession, "
        "(SELECT form FROM selected_targets t WHERE t.accession = i.accession LIMIT 1) AS form, "
        "document_type, description, filename, size, url, role FROM index i "
        "WHERE i.is_exhibit"
    )
    linkbase_expr = classify_linkbase_sql("document_type", "filename", "description")
    con.execute(
        "CREATE OR REPLACE TEMP VIEW linkbases AS SELECT accession, "
        "(SELECT form FROM selected_targets t WHERE t.accession = i.accession LIMIT 1) AS form, "
        f"{linkbase_expr} AS linkbase_type, document_type, filename, url "
        "FROM index i WHERE linkbase_type IS NOT NULL"
    )
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW payload AS SELECT st.target_id, st.accession, "
        "CASE WHEN pi.payload_sha256 IS NOT NULL THEN 'acquired' ELSE 'planned' "
        "END AS outcome, "
        "COALESCE(ac.attempt_count, 0)::INTEGER AS attempt_count, "
        "0::BIGINT AS duration_ms, "
        "COALESCE(st.selected_sha256, '') AS body_sha256, "
        "COALESCE(pi.byte_size, 0) AS body_byte_size, '' AS body_storage_path "
        f"FROM {selected_view} st "
        f"LEFT JOIN {payload_index} pi ON pi.payload_sha256 = st.selected_sha256 "
        f"LEFT JOIN (SELECT target_id, count(*) AS attempt_count FROM {attempts} "
        "GROUP BY target_id) ac ON ac.target_id = st.target_id"
    )
    con.execute("CREATE OR REPLACE TEMP VIEW staged AS SELECT * FROM payload")
    con.execute(
        "CREATE OR REPLACE TEMP VIEW joined AS SELECT c.accession, c.form, "
        "c.filing_date, c.primary_document, p.outcome, NULL::BIGINT AS body_byte_size, "
        "NULL::VARCHAR AS body_storage_path, c.primary_doc_url AS target_url "
        "FROM catalog c LEFT JOIN payload p USING (accession)"
    )
    return {
        name: name
        for name in ("catalog", "index", "exhibits", "linkbases", "payload", "joined")
    }


_SESSION_CACHE: dict[tuple[Path, str], tuple[Any, dict[str, str]]] = {}
_SESSION_LOCK = threading.Lock()


def clear_snapshot_session_cache() -> None:
    """Close and clear cached DuckDB snapshot connections."""
    with _SESSION_LOCK:
        for con, _ in _SESSION_CACHE.values():
            try:
                con.close()
            except Exception:
                pass
        _SESSION_CACHE.clear()


def _get_snapshot_connection(
    artifacts_root: Path, snapshot_id: str
) -> tuple[Any, dict[str, str]]:
    key = (Path(artifacts_root).resolve(), str(snapshot_id))
    with _SESSION_LOCK:
        entry = _SESSION_CACHE.get(key)
        if entry is None:
            snapshots_root, lineage = _snapshot_lineage(artifacts_root, snapshot_id)
            con = connect()
            views = compile_virtual_views(
                con, ACQUISITION_RELATIONS, lineage, snapshots_root
            )
            entry = (con, views)
            _SESSION_CACHE[key] = entry
        return entry


class SnapshotSession:
    """Reusable session caching compiled views for lazy snapshot access."""

    def __init__(self, artifacts_root: Path, snapshot_id: str) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.snapshot_id = snapshot_id

    def connection(self) -> tuple[Any, dict[str, str]]:
        return _get_snapshot_connection(self.artifacts_root, self.snapshot_id)

    def load_payload(self, sha256: str) -> bytes:
        return _load_snapshot_payload(self.artifacts_root, self.snapshot_id, sha256)

    def load_attachments(self, accession: str) -> tuple[FilingAttachment, ...]:
        return _snapshot_attachments(self.artifacts_root, self.snapshot_id, accession)


def _load_snapshot_payload(
    artifacts_root: Path, snapshot_id: str, sha256: str
) -> bytes:
    con, views = _get_snapshot_connection(artifacts_root, snapshot_id)
    for relation in ("text_payloads", "binary_payloads"):
        view = sql_identifier(views[relation])
        row = con.execute(
            f"SELECT payload_bytes FROM {view} WHERE payload_sha256 = ? LIMIT 1",
            [sha256],
        ).fetchone()
        if row is not None and row[0] is not None:
            return bytes(row[0])
    raise FileNotFoundError(f"snapshot payload {sha256!r} is missing")


def _snapshot_attachments(
    artifacts_root: Path, snapshot_id: str, accession: str
) -> tuple[FilingAttachment, ...]:
    con, views = _get_snapshot_connection(artifacts_root, snapshot_id)
    slots = sql_identifier(views["acquisition_slots"])
    assets = sql_identifier(views["source_assets"])
    types = sql_identifier(views["slot_types"])
    payloads = sql_identifier(views["source_payloads"])
    payload_index = sql_identifier(views["payload_index"])
    targets = sql_identifier(views["target_results"])
    form_row = con.execute(
        f"SELECT form FROM {targets} WHERE accession = ? LIMIT 1",
        [accession],
    ).fetchone()
    form = str(form_row[0]) if form_row and form_row[0] else ""
    rows = con.execute(
        f"SELECT s.sequence, st.statutory_type, "
        f"COALESCE(sa.canonical_path, s.locator), s.locator, "
        f"sp.payload_sha256, pi.byte_size "
        f"FROM {slots} s LEFT JOIN {assets} sa ON s.source_asset_id = sa.source_asset_id "
        f"LEFT JOIN {types} st ON s.accession = st.accession AND s.sequence = st.sequence "
        f"LEFT JOIN {payloads} sp ON sp.source_asset_id = s.source_asset_id "
        f"LEFT JOIN {payload_index} pi ON pi.payload_sha256 = sp.payload_sha256 "
        "WHERE s.accession = ? ORDER BY s.sequence",
        [accession],
    ).fetchall()
    attachments = []
    for seq, doc_type, path, url, sha, byte_size in rows:
        row = CanonicalAttachmentRow(
            entry_id=None,
            accession=accession,
            table_kind=None,
            sequence=int(seq) if seq is not None else None,
            document_type=str(doc_type) if doc_type else None,
            document_label=None,
            description=None,
            filename=Path(str(path or "")).name or None,
            href=None,
            archive_url=str(url) if url else None,
            byte_size=int(byte_size) if byte_size is not None else None,
            payload_sha256=str(sha) if sha else None,
        )
        attachments.append(row.to_attachment(form=form))
    return tuple(attachments)


def _make_snapshot_filing(
    row: tuple[Any, ...],
    artifacts_root: Path,
    snapshot_id: str,
    session: SnapshotSession | None = None,
) -> FilingAggregate:
    sess = session or SnapshotSession(artifacts_root, snapshot_id)
    (
        target_id,
        accession,
        form,
        filing_date,
        target_url,
        outcome,
        sha,
        byte_size,
        cik,
    ) = row
    cik_inst = Cik.from_raw(cik) if cik else Cik.from_raw(1)
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=cik_inst,
        ciks=(cik_inst,),
        form=str(form),
        filing_date=str(filing_date or ""),
        primary_document_path=str(target_url).split("/")[-1] if target_url else "",
        primary_sha256=str(sha) if sha else None,
        primary_document_url=str(target_url or ""),
        attachment_loader=lambda _f: sess.load_attachments(str(accession)),
        fetcher=((lambda _f: sess.load_payload(str(sha))) if sha else None),
        renderer=lambda f, operation=None: render_filing(
            f, operation=operation or "raw"
        ),
    )


def iter_snapshot_filings(result: FilingsResult) -> Iterator[FilingAggregate]:
    if result.snapshot_id is None:
        return
    session = SnapshotSession(result.artifacts_root, result.snapshot_id)
    with connect() as con:
        register_snapshot_views(
            con,
            result.artifacts_root,
            result.snapshot_id,
            forms=result.snapshot_forms,
            ciks=result.snapshot_ciks,
            dates=result.snapshot_date_selection,
            limit=result.snapshot_limit,
            filter_forms=result.snapshot_filter_forms,
            date_prefix=result.snapshot_date_prefix,
            filter_limit=result.snapshot_filter_limit,
            filter_empty=result.snapshot_filter_empty,
        )
        cursor = con.execute(
            "SELECT target_id, accession, form, filing_date, target_url, outcome, "
            "selected_sha256, byte_size, cik FROM selected_targets ORDER BY accession"
        )
        while rows := cursor.fetchmany(resolve_read_batch_size()):
            for row in rows:
                yield _make_snapshot_filing(
                    row, result.artifacts_root, result.snapshot_id, session=session
                )


def snapshot_filing_at(
    result: FilingsResult, *, offset: int = 0, latest: bool = False
) -> FilingAggregate | None:
    if result.snapshot_id is None:
        return None
    session = SnapshotSession(result.artifacts_root, result.snapshot_id)
    with connect() as con:
        register_snapshot_views(
            con,
            result.artifacts_root,
            result.snapshot_id,
            forms=result.snapshot_forms,
            ciks=result.snapshot_ciks,
            dates=result.snapshot_date_selection,
            limit=result.snapshot_limit,
            filter_forms=result.snapshot_filter_forms,
            date_prefix=result.snapshot_date_prefix,
            filter_limit=result.snapshot_filter_limit,
            filter_empty=result.snapshot_filter_empty,
        )
        order = "filing_date DESC, accession DESC" if latest else "accession"
        row = con.execute(
            "SELECT target_id, accession, form, filing_date, target_url, outcome, "
            "selected_sha256, byte_size, cik FROM selected_targets "
            f"ORDER BY {order} LIMIT 1 OFFSET ?",
            [int(offset)],
        ).fetchone()
    return (
        _make_snapshot_filing(
            row, result.artifacts_root, result.snapshot_id, session=session
        )
        if row is not None
        else None
    )


__all__ = [
    "SnapshotConsole",
    "SnapshotSession",
    "query_filings_from_snapshot",
]
