from __future__ import annotations

import json
import os
from pathlib import Path

import debugpy
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from knowbase.api.dependencies import configure_logging, get_settings, warm_clients
from knowbase.api.routers import ingest, search, status, imports, sap_solutions


def create_app() -> FastAPI:
    settings = get_settings()
    logger = configure_logging()
    warm_clients()

    if os.getenv("DEBUG_APP") == "true":
        logger.info("🐛 Attaching debugpy to FastAPI app on port 5678...")
        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()
        logger.info("🐛 FastAPI debugger attached!")

    app = FastAPI()

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    openapi_path = Path(__file__).with_name("openapi.json")
    if openapi_path.exists():
        custom_openapi_spec = json.loads(openapi_path.read_text(encoding="utf-8"))
        app.openapi = lambda: custom_openapi_spec
    else:
        logger.warning("Custom openapi.json introuvable, utilisation du schéma par défaut.")

    presentations_dir = settings.presentations_dir
    slides_dir = settings.slides_dir
    thumbnails_dir = settings.thumbnails_dir
    public_root = slides_dir.parent

    if slides_dir.exists():
        app.mount("/static/slides", StaticFiles(directory=slides_dir), name="slides")
    if thumbnails_dir.exists():
        app.mount(
            "/static/thumbnails",
            StaticFiles(directory=thumbnails_dir),
            name="thumbnails",
        )
    if presentations_dir.exists():
        app.mount(
            "/static/presentations",
            StaticFiles(directory=presentations_dir),
            name="presentations",
        )
    if public_root.exists():
        app.mount("/static", StaticFiles(directory=public_root), name="static")

    app.include_router(search.router)
    app.include_router(ingest.router)
    app.include_router(status.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(sap_solutions.router)  # Déjà avec préfixe /api/sap-solutions

    return app


__all__ = ["create_app"]
