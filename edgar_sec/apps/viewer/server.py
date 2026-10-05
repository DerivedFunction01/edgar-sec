"""HTTP surface for the dataset viewer — read-only over one artifacts root.

A request carries an opaque dataset id, never a path or a column. Discovery re-runs per
request rather than being cached, because the revision token is the invalidation source.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from edgar_sec.apps.viewer.console import run_dataset_sql
from edgar_sec.apps.viewer.datasets import (
    MAX_LIMIT,
    DatasetError,
    DatasetRef,
    dataset_blob,
    dataset_column_stats,
    dataset_rows,
    dataset_schema,
)
from edgar_sec.apps.viewer.loaders import iter_documents, run_all
from edgar_sec.apps.viewer.model import (
    ArtifactSummary,
    artifact_id,
    artifact_path,
    artifact_table,
    compute_revision,
    decode_artifact_id,
    file_size,
    mtime_iso,
    summary_to_dict,
)
from edgar_sec.apps.viewer.tree import (
    MAX_TEXT_BYTES,
    ROOT_NODE_ID,
    read_text_file,
    tree_children,
)

__all__ = ["UI_DIST", "create_app"]

UI_DIST = Path(__file__).parent / "ui" / "dist"


def _ref(summary: ArtifactSummary, root: Path) -> DatasetRef:
    """Turn a listing entry into a readable dataset.

    Parts re-resolve from the entry's own ``source_paths``, never by globbing, so a file
    appearing after publication cannot join a read a different byte set described.
    """
    if summary.source_paths:
        paths = tuple(
            artifact_path(artifact_id(item), root) for item in summary.source_paths
        )
    else:
        paths = (artifact_path(summary.id, root),)
    return DatasetRef(
        dataset_id=summary.id,
        paths=paths,
        fmt=summary.format,
        table=summary.table or artifact_table(summary.id),
    )


def _find(summaries: list[ArtifactSummary], dataset_id: str) -> ArtifactSummary:
    for summary in summaries:
        if summary.id == dataset_id:
            return summary
    raise HTTPException(status_code=404, detail="dataset not found")


def _find_dataset(dataset_id: str, root: Path) -> ArtifactSummary:
    """Resolve a manifest-backed dataset or a supported physical table file."""
    for summary in run_all(root, include_sqlite=False):
        if summary.id == dataset_id:
            return summary
    try:
        _, table = decode_artifact_id(dataset_id)
        path = artifact_path(dataset_id, root)
    except DatasetError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    formats = {
        ".parquet": "parquet",
        ".csv": "csv",
        ".tsv": "csv",
        ".jsonl": "jsonl",
        ".ndjson": "jsonl",
        ".db": "sqlite",
        ".sqlite": "sqlite",
        ".duckdb": "duckdb",
    }
    fmt = formats.get(path.suffix.lower())
    if not path.is_file() or fmt is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    if fmt in {"sqlite", "duckdb"} and not table:
        raise HTTPException(
            status_code=400, detail="expand the database and select a table"
        )
    if fmt not in {"sqlite", "duckdb"} and table:
        raise HTTPException(status_code=404, detail="dataset not found")
    relative_path = path.resolve().relative_to(root.resolve()).as_posix()
    size = file_size(path)
    return ArtifactSummary(
        id=dataset_id,
        relative_path=relative_path,
        phase="files",
        run_id=None,
        kind="file_table" if table else "file_dataset",
        format=fmt,
        size_bytes=size,
        mtime=mtime_iso(path),
        revision=compute_revision(size, path.stat().st_mtime_ns),
        source_paths=(relative_path,),
        table=table,
    )


def create_app(artifacts_root: Path | None = None) -> FastAPI:
    """Build the viewer application.

    ``artifacts_root`` defaults to the resolved project root; passing it is how the
    tests and ``--artifacts-root`` override that.
    """
    if artifacts_root is None:
        from edgar_sec.foundation.runtime.paths import resolve_paths

        root = resolve_paths().artifacts_root.resolve()
    else:
        root = Path(artifacts_root).resolve()

    # The OpenAPI document lives under /api so it can never collide with the
    # static UI mount at "/", and so every endpoint the server owns is namespaced.
    app = FastAPI(
        title="EDGAR Dataset Viewer",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "artifacts_root": str(root)}

    @app.get("/api/datasets")
    def list_datasets() -> list[dict]:
        return [summary_to_dict(item) for item in run_all(root, include_sqlite=False)]

    @app.get("/api/documents")
    def list_documents() -> list[dict]:
        return [summary_to_dict(item) for item in iter_documents(root)]

    @app.get("/api/tree")
    def get_tree(parent_id: str | None = None) -> list[dict]:
        try:
            return tree_children(
                root, None if parent_id in {None, ROOT_NODE_ID} else parent_id
            )
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/files/{file_id}/text")
    def get_text(
        file_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=MAX_TEXT_BYTES, ge=1, le=MAX_TEXT_BYTES),
    ) -> dict:
        try:
            return read_text_file(root, file_id, offset=offset, limit=limit)
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/schema")
    def get_schema(dataset_id: str) -> list[dict]:
        summary = _find_dataset(dataset_id, root)
        try:
            return dataset_schema(_ref(summary, root))
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/stats")
    def get_stats(dataset_id: str) -> list[dict]:
        summary = _find_dataset(dataset_id, root)
        try:
            return dataset_column_stats(_ref(summary, root))
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/rows")
    def get_rows(
        dataset_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=MAX_LIMIT),
        sort: str | None = None,
        dir: str = Query(default="asc", pattern="^(asc|desc)$"),
        filters: str | None = None,
        search: str | None = None,
    ) -> dict:
        summary = _find_dataset(dataset_id, root)
        parsed = _parse_filters(filters)
        try:
            return dataset_rows(
                _ref(summary, root),
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filters=parsed,
                search=search,
            )
        except (DatasetError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/blob")
    def get_blob(
        dataset_id: str,
        column: str = Query(..., description="Target blob column name"),
        pk_col: str | None = Query(default=None),
        pk_val: str | None = Query(default=None),
        row_index: int | None = Query(default=None, ge=0),
    ) -> dict:
        summary = _find_dataset(dataset_id, root)
        try:
            return dataset_blob(
                _ref(summary, root),
                column=column,
                pk_col=pk_col,
                pk_val=pk_val,
                row_index=row_index,
            )
        except (DatasetError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/datasets/{dataset_id}/sql")
    def post_sql(dataset_id: str, body: dict) -> JSONResponse:
        summary = _find_dataset(dataset_id, root)
        query = body.get("query")
        if not isinstance(query, str):
            raise HTTPException(status_code=400, detail="body must include 'query'")
        if summary.format == "duckdb":
            raise HTTPException(
                status_code=400,
                detail="SQL console is disabled for native DuckDB files",
            )
        try:
            return JSONResponse(content=run_dataset_sql(_ref(summary, root), query))
        except DatasetError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/documents/{dataset_id}")
    def get_document(dataset_id: str) -> dict:
        summary = _find(iter_documents(root), dataset_id)
        try:
            content = json.loads(artifact_path(summary.id, root).read_text("utf-8"))
        except (OSError, json.JSONDecodeError, DatasetError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"summary": summary_to_dict(summary), "content": content}

    if UI_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    else:

        @app.get("/")
        def root_info() -> dict:
            return {
                "service": "edgar-dataset-viewer",
                "ui": (
                    "not built; run `bun install && bun run build` in "
                    "edgar_sec/apps/viewer/ui, or use `--api-only`"
                ),
            }

    return app


def _parse_filters(raw: str | None) -> list[dict] | None:
    """Parse the ``filters`` query parameter as a JSON array of filter objects."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="filters must be valid JSON"
        ) from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="filters must be a JSON array")
    return parsed
