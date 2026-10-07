"""Фабрика FastAPI-приложения."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from paper2data import __version__
from paper2data.api.graph import router as graph_router
from paper2data.api.llm import router as llm_router
from paper2data.api.projects import router as projects_router
from paper2data.api.schema import router as schema_router
from paper2data.core.config import settings


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Paper2Data",
        version=__version__,
        description="Локальное приложение для извлечения графа сущностей из научных статей",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
    app.include_router(llm_router, prefix="/api/llm", tags=["llm"])
    app.include_router(schema_router, prefix="/api/schema", tags=["schema"])
    app.include_router(graph_router, prefix="/api/graph", tags=["graph"])

    # M3 extraction: не роняем приложение, если нет jinja2 и т.п.
    try:
        from paper2data.api.extraction import router as extraction_router

        app.include_router(extraction_router, prefix="/api/extraction", tags=["extraction"])
    except ImportError:
        pass

    # M1 papers/ingest: не роняем приложение, если нет PyMuPDF и т.п.
    try:
        from paper2data.api.papers import router as papers_router

        app.include_router(papers_router, prefix="/api/papers", tags=["papers"])
    except ImportError:
        pass

    # M5 figures
    try:
        from paper2data.api.figures import router as figures_router

        app.include_router(figures_router, prefix="/api/figures", tags=["figures"])
    except ImportError:
        pass

    # M4 corpus / evaluation / batch
    try:
        from paper2data.api.evaluation import router as evaluation_router

        app.include_router(evaluation_router, prefix="/api/evaluation", tags=["evaluation"])
    except ImportError:
        pass

    # M6 chem enrichment
    try:
        from paper2data.api.chem import router as chem_router

        app.include_router(chem_router, prefix="/api/chem", tags=["chem"])
    except ImportError:
        pass

    # M6 assistant
    try:
        from paper2data.api.assistant import router as assistant_router

        app.include_router(assistant_router, prefix="/api/assistant", tags=["assistant"])
    except ImportError:
        pass

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if static_dir is not None and static_dir.exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        index_file = static_dir / "index.html"

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            candidate = static_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)

    return app
