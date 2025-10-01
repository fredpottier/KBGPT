from __future__ import annotations

import json
import os
from pathlib import Path

import debugpy
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from knowbase.api.dependencies import configure_logging, get_settings, warm_clients
from knowbase.api.middleware.user_context import UserContextMiddleware
from knowbase.api.routers import ingest, search, status, imports, sap_solutions, downloads, token_analysis, tenants, health, graphiti, knowledge_graph, users, facts_governance, facts_intelligence, canonicalization


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

    # Middleware contexte utilisateur Phase 2 (enregistrement standard)
    app.add_middleware(UserContextMiddleware)

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
    app.include_router(downloads.router)  # Déjà avec préfixe /api/downloads
    app.include_router(token_analysis.router, prefix="/api")  # Analyse des tokens et coûts
    app.include_router(tenants.router, prefix="/api")  # Gestion multi-tenant
    app.include_router(users.router, prefix="/api")  # Gestion utilisateurs Phase 2 ✅ ACTIVÉ
    app.include_router(health.router, prefix="/api")  # Health checks complets
    app.include_router(graphiti.router, prefix="/api")  # Intégration Graphiti ✅ ACTIVÉ
    app.include_router(knowledge_graph.router, prefix="/api")  # Knowledge Graph Enterprise ✅ ACTIVÉ
    app.include_router(facts_governance.router)  # Facts Gouvernées Phase 3 ✅ ACTIVÉ
    app.include_router(facts_intelligence.router)  # Intelligence IA Facts Phase 3 ✅ ACTIVÉ
    app.include_router(canonicalization.router)  # Canonicalisation Entités Phase 0 ✅ ACTIVÉ

    return app


__all__ = ["create_app"]
