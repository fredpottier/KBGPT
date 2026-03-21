# src/knowbase/api/routers/domain_packs.py
"""
API endpoints pour les Domain Packs OSMOSE.

Lifecycle: Upload .osmpack → Install (build image) → Activate → Deactivate → Uninstall

GET   /api/admin/domain-packs/              → liste packs + état
POST  /api/admin/domain-packs/upload        → upload .osmpack
POST  /api/admin/domain-packs/install/{name}→ install builtin pack
POST  /api/admin/domain-packs/activate      → active (start container)
POST  /api/admin/domain-packs/deactivate    → désactive (stop container)
POST  /api/admin/domain-packs/uninstall     → désinstalle (rm image + fichiers)
POST  /api/admin/domain-packs/reprocess     → enrichissement rétroactif
GET   /api/admin/domain-packs/stats/{name}  → stats Neo4j
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from knowbase.api.dependencies import get_tenant_id
from knowbase.api.schemas.domain_packs import (
    PackInfo,
    PackListResponse,
    PackActivateRequest,
    PackActivateResponse,
    PackStatsResponse,
    ReprocessRequest,
    ReprocessResponse,
    ReprocessStatusResponse,
    InstallResponse,
    UninstallResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/domain-packs",
    tags=["Domain Packs"],
)


@router.get("/", response_model=PackListResponse)
async def list_packs(
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste tous les packs disponibles avec leur état."""
    from knowbase.domain_packs.registry import get_pack_registry
    from knowbase.domain_packs.pack_manager import get_pack_manager

    registry = get_pack_registry()
    manager = get_pack_manager()
    all_packs = registry.list_packs()

    pack_infos = []
    active_count = 0

    for pack in all_packs:
        is_active = registry.is_active(pack.name, tenant_id)
        if is_active:
            active_count += 1

        # État du container
        container_state = manager.get_state(pack.name)

        # Infos du manifest
        manifest = manager.get_manifest(pack.name)
        entity_types = []
        ner_model = ""
        ner_model_size_mb = 0

        if manifest:
            entity_types = manifest.provides.entity_types
            ner_model = manifest.provides.ner_model
            ner_model_size_mb = manifest.provides.ner_model_size_mb
        else:
            # Fallback : lire depuis les extracteurs Python
            for extractor in pack.get_entity_extractors():
                entity_types.extend(extractor.entity_type_mapping.keys())

        pack_infos.append(PackInfo(
            name=pack.name,
            display_name=pack.display_name,
            description=pack.description,
            version=pack.version,
            priority=pack.priority,
            is_active=is_active,
            is_builtin=registry.is_builtin(pack.name),
            container_state=container_state,
            entity_types=entity_types,
            ner_model=ner_model,
            ner_model_size_mb=ner_model_size_mb,
        ))

    return PackListResponse(packs=pack_infos, active_count=active_count)


# =========================================================================
# Lifecycle : Upload / Install / Uninstall
# =========================================================================


@router.post("/upload", response_model=InstallResponse)
async def upload_pack(file: UploadFile = File(...)):
    """Upload et installe un fichier .osmpack (zip)."""
    from knowbase.domain_packs.pack_manager import get_pack_manager
    from knowbase.domain_packs.registry import get_pack_registry

    if not file.filename or not (
        file.filename.endswith(".osmpack") or file.filename.endswith(".zip")
    ):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un .osmpack ou .zip",
        )

    manager = get_pack_manager()

    # Sauvegarder le fichier temporairement
    with tempfile.NamedTemporaryFile(
        suffix=".zip", delete=False
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        manifest = manager.install_from_zip(tmp_path)
        # Re-découvrir les packs
        registry = get_pack_registry()
        from knowbase.domain_packs.registry import _discover_packs
        _discover_packs(registry)

        return InstallResponse(
            success=True,
            message=f"Pack '{manifest.name}' v{manifest.version} installé",
            pack_name=manifest.name,
            version=manifest.version,
        )
    except Exception as e:
        logger.error(f"Error installing pack: {e}")
        return InstallResponse(
            success=False,
            message=f"Erreur installation: {e}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/install/{pack_name}", response_model=InstallResponse)
async def install_builtin_pack(pack_name: str):
    """Installe un pack intégré (build l'image Docker)."""
    from knowbase.domain_packs.pack_manager import get_pack_manager

    manager = get_pack_manager()
    manifest = manager.install_builtin(pack_name)

    if manifest:
        return InstallResponse(
            success=True,
            message=f"Pack '{manifest.name}' v{manifest.version} installé (image buildée)",
            pack_name=manifest.name,
            version=manifest.version,
        )
    else:
        return InstallResponse(
            success=False,
            message=f"Pack intégré '{pack_name}' non trouvé ou build échoué",
        )


@router.post("/uninstall", response_model=UninstallResponse)
async def uninstall_pack(request: PackActivateRequest):
    """Désinstalle un pack (supprime container, image et fichiers)."""
    from knowbase.domain_packs.pack_manager import get_pack_manager

    manager = get_pack_manager()
    success = manager.uninstall(request.pack_name)

    return UninstallResponse(
        success=success,
        message=(
            f"Pack '{request.pack_name}' désinstallé"
            if success
            else f"Erreur désinstallation '{request.pack_name}'"
        ),
    )


# =========================================================================
# Activate / Deactivate
# =========================================================================


@router.post("/activate", response_model=PackActivateResponse)
async def activate_pack(
    request: PackActivateRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Active un pack (start container + persist DB)."""
    from knowbase.domain_packs.registry import get_pack_registry
    from knowbase.domain_packs.pack_manager import get_pack_manager

    tenant_id = request.tenant_id or tenant_id
    registry = get_pack_registry()

    pack = registry.get_pack(request.pack_name)
    if not pack:
        raise HTTPException(
            status_code=404,
            detail=f"Pack '{request.pack_name}' not found",
        )

    success = registry.activate(request.pack_name, tenant_id)

    manager = get_pack_manager()
    container_state = manager.get_state(request.pack_name)

    active_packs = [
        p.name for p in registry.get_active_packs(tenant_id)
    ]

    return PackActivateResponse(
        success=success,
        message=f"Pack '{request.pack_name}' activé pour {tenant_id}",
        active_packs=active_packs,
        container_state=container_state,
    )


@router.post("/deactivate", response_model=PackActivateResponse)
async def deactivate_pack(
    request: PackActivateRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Désactive un pack (stop container + persist DB)."""
    from knowbase.domain_packs.registry import get_pack_registry
    from knowbase.domain_packs.pack_manager import get_pack_manager

    tenant_id = request.tenant_id or tenant_id
    registry = get_pack_registry()

    success = registry.deactivate(request.pack_name, tenant_id)

    manager = get_pack_manager()
    container_state = manager.get_state(request.pack_name)

    active_packs = [
        p.name for p in registry.get_active_packs(tenant_id)
    ]

    return PackActivateResponse(
        success=success,
        message=f"Pack '{request.pack_name}' désactivé pour {tenant_id}",
        active_packs=active_packs,
        container_state=container_state,
    )


# =========================================================================
# Reprocess
# =========================================================================


@router.post("/reprocess", response_model=ReprocessResponse)
async def reprocess_pack(
    request: ReprocessRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Lance le reprocessing rétroactif via RQ job."""
    from knowbase.domain_packs.registry import get_pack_registry

    tenant_id = request.tenant_id or tenant_id
    registry = get_pack_registry()

    pack = registry.get_pack(request.pack_name)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{request.pack_name}' not found")

    if not registry.is_active(request.pack_name, tenant_id):
        raise HTTPException(status_code=400, detail=f"Pack '{request.pack_name}' not active")

    try:
        from knowbase.domain_packs.reprocess_job import enqueue_reprocess
        job_id = enqueue_reprocess(request.pack_name, tenant_id)
        return ReprocessResponse(success=True, message="Reprocessing lancé", job_id=job_id)
    except Exception as e:
        logger.error(f"Error enqueuing reprocess: {e}")
        return ReprocessResponse(success=False, message=f"Erreur: {e}")


@router.get("/reprocess-status", response_model=ReprocessStatusResponse)
async def reprocess_status(
    tenant_id: str = Depends(get_tenant_id),
):
    """Status du reprocessing en cours."""
    import json

    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        state_key = f"osmose:domain_pack:reprocess:state:{tenant_id}"
        raw = rc.client.get(state_key)
        if raw:
            data = json.loads(raw)
            return ReprocessStatusResponse(**data)
    except Exception as e:
        logger.error(f"Error reading reprocess status: {e}")

    return ReprocessStatusResponse(state="idle")


# =========================================================================
# Stats + Defaults
# =========================================================================


@router.get("/stats/{pack_name}", response_model=PackStatsResponse)
async def pack_stats(
    pack_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Stats Neo4j pour un pack."""
    from knowbase.domain_packs.registry import get_pack_registry

    registry = get_pack_registry()
    if not registry.get_pack(pack_name):
        raise HTTPException(status_code=404, detail=f"Pack '{pack_name}' not found")

    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        driver = get_neo4j_client().driver

        # Charger les aliases du pack pour compter les matchs
        pack = registry.get_pack(pack_name)
        pack_aliases = {}
        gazetteer_terms = set()
        if pack:
            defaults = pack._load_defaults_json()
            pack_aliases = {
                alias.lower(): canonical
                for alias, canonical in defaults.get("canonical_aliases", {}).items()
            }
            gazetteer_terms = {
                t.lower() for t in defaults.get("product_gazetteer", [])
            }

        with driver.session() as session:
            # Entités créées par le pack
            r1 = session.run(
                "MATCH (e:Entity {tenant_id: $t, source_pack: $p}) RETURN count(e) as n",
                t=tenant_id, p=pack_name,
            )
            entities_created = r1.single()["n"]

            # Claims linkées par le pack
            r2 = session.run(
                "MATCH (c:Claim {tenant_id: $t})-[r:ABOUT]->(e:Entity) "
                "WHERE r.method = $m RETURN count(DISTINCT c) as n",
                t=tenant_id, m=f"domain_pack:{pack_name}",
            )
            claims_linked = r2.single()["n"]

            # Aliases résolus : entités dont le nom est un canonical ET qui ont des aliases
            aliases_resolved = 0
            if pack_aliases:
                canonical_names = list(set(pack_aliases.values()))
                r_aliases = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $t})
                    WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
                      AND e.name IN $canonicals
                    RETURN count(e) as n
                    """,
                    t=tenant_id,
                    canonicals=canonical_names,
                )
                aliases_resolved = r_aliases.single()["n"]

            # Entités matchant le gazetteer
            gazetteer_matches = 0
            if gazetteer_terms:
                r_gaz = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $t})
                    WHERE toLower(e.name) IN $terms
                    RETURN count(e) as n
                    """,
                    t=tenant_id,
                    terms=list(gazetteer_terms)[:500],
                )
                gazetteer_matches = r_gaz.single()["n"]

            # Couverture globale
            r3 = session.run(
                "MATCH (c:Claim {tenant_id: $t}) WITH count(c) as total "
                "MATCH (c2:Claim {tenant_id: $t})-[:ABOUT]->(:Entity) "
                "WITH total, count(DISTINCT c2) as linked "
                "RETURN CASE WHEN total > 0 THEN toFloat(linked)/total ELSE 0.0 END as cov",
                t=tenant_id,
            )
            coverage = r3.single()["cov"]

        return PackStatsResponse(
            pack_name=pack_name,
            entities_created=entities_created,
            claims_linked=claims_linked,
            aliases_resolved=aliases_resolved,
            gazetteer_matches=gazetteer_matches,
            coverage_after=coverage,
        )
    except Exception as e:
        logger.error(f"Error getting stats for pack '{pack_name}': {e}")
        return PackStatsResponse(pack_name=pack_name)


@router.get("/defaults/{pack_name}")
async def pack_defaults(pack_name: str):
    """Retourne les context_defaults.json du pack."""
    from knowbase.domain_packs.registry import get_pack_registry

    registry = get_pack_registry()
    pack = registry.get_pack(pack_name)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_name}' not found")

    return pack._load_defaults_json()
