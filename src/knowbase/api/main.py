﻿from __future__ import annotations

import json
import os
from pathlib import Path

import debugpy
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from knowbase.api.dependencies import configure_logging, get_settings, warm_clients
from knowbase.api.routers import ingest, search, status, imports, sap_solutions, downloads, token_analysis, facts, ontology, entities, entity_types, jobs, document_types, admin, auth, documents


def create_app() -> FastAPI:
    settings = get_settings()
    logger = configure_logging()
    warm_clients()

    # Initialiser base de données SQLite (entity_types_registry)
    from knowbase.db import init_db
    init_db()
    logger.info("✅ Base de données SQLite initialisée (entity_types_registry)")

    if os.getenv("DEBUG_APP") == "true":
        logger.info("🐛 Attaching debugpy to FastAPI app on port 5678...")
        debugpy.listen(("0.0.0.0", 5678))
        debugpy.wait_for_client()
        logger.info("🐛 FastAPI debugger attached!")

    # Rate Limiting - Phase 0 Security Hardening
    limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

    app = FastAPI(
        title="SAP Knowbase API",
        description="""
        **API Knowledge Base SAP** avec Knowledge Graph Neo4j Native.

        ## Fonctionnalités principales

        ### 📚 Recherche & Ingestion
        - Recherche hybride vectorielle (Qdrant) + Knowledge Graph (Neo4j)
        - Ingestion documents (PDF, PPTX, Excel, DOCX)
        - Traitement RFP Q/A automatisé

        ### 🧠 Knowledge Graph Facts (Phase 2)
        - CRUD complet Facts structurés
        - Gouvernance approve/reject avec workflow
        - Détection conflits (CONTRADICTS, OVERRIDES, OUTDATED)
        - Timeline historique valeurs
        - Statistiques agrégées

        ### 🔐 Multi-tenancy
        - Isolation tenant_id pour tous les endpoints
        - Headers: `X-Tenant-ID`, `X-User-ID`

        ## Endpoints principaux

        - **`/api/facts`** : CRUD Facts Knowledge Graph
        - **`/search`** : Recherche hybride multi-sources
        - **`/api/imports`** : Historique imports documents
        - **`/api/sap-solutions`** : Catalogue SAP
        - **`/api/token-analysis`** : Analyse coûts LLM

        ## Architecture
        - **Backend** : FastAPI + Pydantic v2
        - **Vector DB** : Qdrant (embeddings)
        - **Knowledge Graph** : Neo4j Native (facts structurés)
        - **LLM** : Multi-provider (OpenAI, Anthropic, Ollama)
        """,
        version="2.0.0",
        contact={
            "name": "SAP Knowbase Team",
            "email": "support@example.com",
        },
        license_info={
            "name": "Proprietary",
        },
        openapi_tags=[
            {
                "name": "Facts",
                "description": "**Knowledge Graph Facts** - CRUD, gouvernance, conflits, timeline, stats (Phase 2 - Neo4j Native)"
            },
            {
                "name": "Search",
                "description": "Recherche hybride vectorielle + Knowledge Graph"
            },
            {
                "name": "Ingestion",
                "description": "Import et traitement documents (PDF, PPTX, Excel)"
            },
            {
                "name": "Status",
                "description": "Monitoring systèmes (Qdrant, Neo4j, Redis, LLM)"
            },
            {
                "name": "Imports",
                "description": "Historique imports et statistiques"
            },
            {
                "name": "SAP Solutions",
                "description": "Catalogue solutions SAP"
            },
            {
                "name": "Downloads",
                "description": "Téléchargement documents source"
            },
            {
                "name": "Token Analysis",
                "description": "Analyse coûts et tokens LLM"
            },
            {
                "name": "Ontology",
                "description": "Gestion catalogues d'ontologies (entités Knowledge Graph)"
            },
            {
                "name": "Entities",
                "description": "Gestion entités dynamiques - validation, pending, types découverts (Phase 1)"
            },
            {
                "name": "Entity Types",
                "description": "Registry types d'entités découverts - approve/reject, compteurs, workflow validation (Phase 2)"
            },
            {
                "name": "Document Types",
                "description": "Gestion types de documents pour guider extraction LLM (Phase 6)"
            },
        ],
    )

    # Configure Rate Limiting state
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info("✅ Rate limiting configuré : 100 requêtes/minute par IP")

    # Configure CORS - Allow frontend to make requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # Frontend Next.js dev
            "http://localhost:8501",  # Frontend Streamlit legacy
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8501",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("✅ CORS configuré pour localhost:3000 et localhost:8501")

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
    app.include_router(facts.router, prefix="/api")  # Facts API - Neo4j Native (Phase 2)
    app.include_router(ontology.router, prefix="/api")  # Ontology API - Catalogues entités
    app.include_router(entities.router, prefix="/api")  # Entities API - Gestion entités dynamiques (Phase 1)
    app.include_router(entity_types.router, prefix="/api")  # Entity Types Registry - Workflow validation types (Phase 2)
    app.include_router(jobs.router, prefix="/api")  # Jobs API - Monitoring jobs async RQ (Phase 5B)
    app.include_router(document_types.router, prefix="/api")  # Document Types - Guidage extraction LLM (Phase 6)
    app.include_router(documents.router, prefix="/api")  # Documents API - Document Backbone lifecycle (Phase 1 Week 4)
    app.include_router(admin.router, prefix="/api")  # Admin API - Purge data, health check (Phase 7)
    app.include_router(auth.router, prefix="/api")  # Auth API - JWT Authentication (Phase 0)

    return app


__all__ = ["create_app"]
