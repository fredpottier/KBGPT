from __future__ import annotations

import json
import os
from pathlib import Path

import debugpy
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from knowbase.api.dependencies import configure_logging, get_settings, warm_clients
from knowbase.api.routers import ingest, search, status


def create_app() -> FastAPI:
    settings = get_settings()
    logger = configure_logging()
    warm_clients()

    if os.getenv("DEBUG_MODE") == "true":
        logger.info("Attaching debugpy on port 5678...")
        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()
        logger.info("Debugger attached!")

    app = FastAPI()

    openapi_path = Path(__file__).with_name("openapi.json")
    if openapi_path.exists():
        custom_openapi_spec = json.loads(openapi_path.read_text(encoding="utf-8"))
        app.openapi = lambda: custom_openapi_spec
    else:
        logger.warning("Custom openapi.json introuvable, utilisation du schéma par défaut.")

    public_root = settings.presentations_dir.parent
    slides_dir = public_root / "slides"
    presentations_dir = settings.presentations_dir

    if slides_dir.exists():
        app.mount("/static/slides", StaticFiles(directory=slides_dir), name="slides")
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
    app.include_router(status.router)

    return app


__all__ = ["create_app"]
