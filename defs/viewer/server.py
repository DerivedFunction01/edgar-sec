"""FastAPI application for the viewer: JSON API plus optional static UI."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .datasets import (
    DatasetError,
    DatasetRef,
    dataset_column_stats,
    dataset_rows,
    dataset_schema,
    run_dataset_sql,
)
from .discover import (
    ArtifactSummary,
    artifact_id,
    artifact_path,
    discover_artifacts,
    discover_documents,
    summary_to_dict,
)

_UI_DIST = Path(__file__).parent / "ui" / "dist"


def _find(summaries: list[ArtifactSummary], dataset_id: str) -> ArtifactSummary:
    for summary in summaries:
        if summary.id == dataset_id:
            return summary
    raise HTTPException(status_code=404, detail="dataset not found")


def create_app(artifacts_root: Path | None = None) -> FastAPI:
    root = (artifacts_root or Path(".artifacts")).resolve()
    app = FastAPI(title="EDGAR Dataset Viewer", docs_url="/api/docs")

    @app.get("/api/datasets")
    def list_datasets() -> list[dict]:
        return [summary_to_dict(item) for item in discover_artifacts(root)]

    @app.get("/api/documents")
    def list_documents() -> list[dict]:
        return [summary_to_dict(item) for item in discover_documents(root)]

    @app.get("/api/datasets/{dataset_id}/schema")
    def get_schema(dataset_id: str) -> list[dict]:
        summaries = discover_artifacts(root)
        summary = _find(summaries, dataset_id)
        try:
            return dataset_schema(_ref(summary, root))
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/stats")
    def get_stats(dataset_id: str) -> list[dict]:
        summaries = discover_artifacts(root)
        summary = _find(summaries, dataset_id)
        try:
            return dataset_column_stats(_ref(summary, root))
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/datasets/{dataset_id}/rows")
    def get_rows(
        dataset_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
        sort: str | None = None,
        dir: str = Query(default="asc", pattern="^(asc|desc)$"),
        filters: str | None = None,
    ) -> dict:
        summaries = discover_artifacts(root)
        summary = _find(summaries, dataset_id)
        parsed_filters = None
        if filters is not None:
            try:
                parsed_filters = json.loads(filters)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400, detail="filters must be valid JSON"
                ) from exc
            if not isinstance(parsed_filters, list):
                raise HTTPException(
                    status_code=400, detail="filters must be a JSON array"
                )
        try:
            return dataset_rows(
                _ref(summary, root),
                offset=offset,
                limit=limit,
                sort=sort,
                direction=dir,
                filters=parsed_filters,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/datasets/{dataset_id}/sql")
    def post_sql(dataset_id: str, body: dict) -> dict:
        summaries = discover_artifacts(root)
        summary = _find(summaries, dataset_id)
        query = body.get("query")
        if not isinstance(query, str):
            raise HTTPException(status_code=400, detail="body must include 'query'")
        try:
            return run_dataset_sql(_ref(summary, root), query)
        except DatasetError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/documents/{dataset_id}")
    def get_document(dataset_id: str) -> dict:
        documents = discover_documents(root)
        summary = _find(documents, dataset_id)
        path = artifact_path(summary.id, root)
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"summary": summary_to_dict(summary), "content": content}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "artifacts_root": str(root)}

    if _UI_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=_UI_DIST, html=True), name="ui")
    else:  # dev mode: API-only, UI served by vite

        @app.get("/")
        def root_info() -> dict:
            return {
                "service": "edgar-dataset-viewer",
                "ui": "not built; run `bun run build` in defs/viewer/ui "
                "or use `bun run dev`",
            }

    return app


def _ref(summary: ArtifactSummary, root: Path) -> DatasetRef:
    paths = tuple(
        artifact_path(artifact_id(item), root) for item in summary.source_paths
    )
    return DatasetRef(
        dataset_id=summary.id,
        path=artifact_path(summary.id, root) if not paths else paths[0],
        fmt=summary.format,
        paths=paths,
    )
