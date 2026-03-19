"""Router FastAPI pour le système d'hygiène KG."""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from knowbase.api.schemas.kg_hygiene import (
    BatchRollbackResponse,
    HygieneActionResponse,
    HygieneActionsListResponse,
    HygieneRunRequest,
    HygieneRunResponse,
    HygieneRunStatusResponse,
    HygieneStatsResponse,
    RollbackResponse,
)

logger = logging.getLogger("[OSMOSE] kg_hygiene_router")

router = APIRouter(
    prefix="/api/admin/kg-hygiene",
    tags=["kg-hygiene"],
)

# Stockage en mémoire des runs en cours/terminés (clé = batch_id)
_run_store: Dict[str, dict] = {}
_run_store_lock = threading.Lock()


def _get_neo4j_driver():
    """Obtient le driver Neo4j."""
    import os

    try:
        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

        return GraphDatabase.driver(uri, auth=(user, password))
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        raise HTTPException(status_code=503, detail="Neo4j unavailable")


def _action_to_response(a) -> HygieneActionResponse:
    """Convertit un HygieneAction en HygieneActionResponse."""
    return HygieneActionResponse(
        action_id=a.action_id,
        action_type=a.action_type.value if hasattr(a.action_type, "value") else a.action_type,
        target_node_id=a.target_node_id,
        target_node_type=a.target_node_type,
        before_state=a.before_state if isinstance(a.before_state, dict) else {},
        after_state=a.after_state if isinstance(a.after_state, dict) else {},
        layer=a.layer,
        confidence=a.confidence,
        reason=a.reason,
        rule_name=a.rule_name,
        batch_id=a.batch_id,
        scope=a.scope,
        status=a.status.value if hasattr(a.status, "value") else a.status,
        decision_source=a.decision_source,
        applied_at=a.applied_at,
        rolled_back_at=a.rolled_back_at,
        tenant_id=a.tenant_id,
    )


def _run_hygiene_background(
    batch_id: str,
    tenant_id: str,
    dry_run: bool,
    layers: list,
    scope_str: str,
    scope_params: dict | None,
    auto_apply_threshold: float,
):
    """Exécute le run d'hygiène en background thread."""
    from knowbase.hygiene.engine import HygieneEngine
    from knowbase.hygiene.models import HygieneRunScope

    neo4j_driver = _get_neo4j_driver()
    try:
        engine = HygieneEngine(neo4j_driver, tenant_id)
        scope = HygieneRunScope(scope_str)

        # Override le batch_id pour qu'il corresponde à celui retourné au client
        result = engine.run(
            dry_run=dry_run,
            layers=layers,
            scope=scope,
            scope_params=scope_params,
            auto_apply_threshold=auto_apply_threshold,
        )

        with _run_store_lock:
            _run_store[batch_id] = {
                "status": "completed",
                "batch_id": result.batch_id,
                "total_actions": result.total_actions,
                "applied": result.applied,
                "proposed": result.proposed,
                "skipped_already_suppressed": result.skipped_already_suppressed,
                "dry_run": result.dry_run,
                "errors": result.errors,
                "actions": [_action_to_response(a) for a in result.actions],
            }

    except Exception as e:
        logger.error(f"[OSMOSE:Hygiene] Background run failed: {e}")
        with _run_store_lock:
            _run_store[batch_id] = {
                "status": "failed",
                "batch_id": batch_id,
                "total_actions": 0,
                "applied": 0,
                "proposed": 0,
                "skipped_already_suppressed": 0,
                "dry_run": dry_run,
                "errors": [str(e)],
                "actions": [],
            }
    finally:
        neo4j_driver.close()


@router.post("/run")
async def run_hygiene(
    request: HygieneRunRequest,
    tenant_id: str = Query(default="default"),
):
    """Lance un run d'hygiène KG en background. Retourne immédiatement un batch_id pour polling."""
    batch_id = f"hyg_run_{uuid.uuid4().hex[:8]}"

    # Enregistrer comme "running"
    with _run_store_lock:
        _run_store[batch_id] = {
            "status": "running",
            "batch_id": batch_id,
            "total_actions": 0,
            "applied": 0,
            "proposed": 0,
            "skipped_already_suppressed": 0,
            "dry_run": request.dry_run,
            "errors": [],
            "actions": [],
            "progress": "Démarrage...",
        }

    # Lancer en background
    thread = threading.Thread(
        target=_run_hygiene_background,
        args=(
            batch_id,
            tenant_id,
            request.dry_run,
            request.layers,
            request.scope,
            request.scope_params,
            request.auto_apply_threshold,
        ),
        daemon=True,
    )
    thread.start()

    return {"batch_id": batch_id, "status": "running"}


@router.get("/run-status/{batch_id}", response_model=HygieneRunStatusResponse)
async def get_run_status(batch_id: str):
    """Polling du statut d'un run d'hygiène."""
    with _run_store_lock:
        run_data = _run_store.get(batch_id)

    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run {batch_id} introuvable")

    return HygieneRunStatusResponse(
        batch_id=run_data["batch_id"],
        status=run_data["status"],
        total_actions=run_data["total_actions"],
        applied=run_data["applied"],
        proposed=run_data["proposed"],
        skipped_already_suppressed=run_data["skipped_already_suppressed"],
        dry_run=run_data["dry_run"],
        errors=run_data["errors"],
        actions=run_data.get("actions", []),
        progress=run_data.get("progress"),
    )


@router.get("/actions", response_model=HygieneActionsListResponse)
async def list_actions(
    tenant_id: str = Query(default="default"),
    status: Optional[str] = Query(default=None),
    layer: Optional[int] = Query(default=None),
    action_type: Optional[str] = Query(default=None),
    batch_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Liste les actions d'hygiène avec filtres."""
    from knowbase.hygiene.persistence import HygieneActionPersister

    neo4j_driver = _get_neo4j_driver()
    try:
        persister = HygieneActionPersister(neo4j_driver)

        actions = persister.list_actions(
            tenant_id=tenant_id,
            status=status,
            layer=layer,
            action_type=action_type,
            batch_id=batch_id,
            limit=limit,
            offset=offset,
        )
        total = persister.count_actions(tenant_id=tenant_id, status=status)

        return HygieneActionsListResponse(
            actions=[_action_to_response(a) for a in actions],
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        neo4j_driver.close()


@router.get("/actions/{action_id}", response_model=HygieneActionResponse)
async def get_action(action_id: str):
    """Détail d'une action d'hygiène."""
    from knowbase.hygiene.persistence import HygieneActionPersister

    neo4j_driver = _get_neo4j_driver()
    try:
        persister = HygieneActionPersister(neo4j_driver)
        action = persister.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=f"Action {action_id} introuvable")
        return _action_to_response(action)
    finally:
        neo4j_driver.close()


@router.post("/actions/{action_id}/rollback", response_model=RollbackResponse)
async def rollback_action(action_id: str):
    """Rollback une action d'hygiène."""
    from knowbase.hygiene.rollback import HygieneRollback

    neo4j_driver = _get_neo4j_driver()
    try:
        rollback = HygieneRollback(neo4j_driver)
        result = rollback.rollback_action(action_id)

        return RollbackResponse(
            success=result.success,
            action_id=action_id,
            relations_restored=result.relations_restored,
            relations_failed=result.relations_failed,
            failed_reasons=result.failed_reasons,
            partial=result.partial,
        )
    finally:
        neo4j_driver.close()


@router.post("/actions/{action_id}/reject")
async def reject_action(action_id: str):
    """Rejeter une action PROPOSED."""
    from knowbase.hygiene.models import HygieneActionStatus
    from knowbase.hygiene.persistence import HygieneActionPersister

    neo4j_driver = _get_neo4j_driver()
    try:
        persister = HygieneActionPersister(neo4j_driver)
        action = persister.get_action(action_id)

        if not action:
            raise HTTPException(status_code=404, detail="Action introuvable")
        if action.status != HygieneActionStatus.PROPOSED:
            raise HTTPException(
                status_code=400,
                detail=f"Seules les actions PROPOSED peuvent être rejetées (status={action.status.value})",
            )

        from datetime import datetime, timezone
        persister.update_status(
            action_id,
            HygieneActionStatus.REJECTED,
            rolled_back_at=datetime.now(timezone.utc).isoformat(),
        )

        return {"success": True, "action_id": action_id, "new_status": "REJECTED"}
    finally:
        neo4j_driver.close()


def _resolve_rule(rule_name: str):
    """Résout la bonne instance de règle par son nom."""
    from knowbase.hygiene.rules.layer1_entities import (
        DomainStoplistRule,
        InvalidEntityNameRule,
        StructuralEntityRule,
    )
    from knowbase.hygiene.rules.acronym_dedup import AcronymDedupRule
    from knowbase.hygiene.rules.layer2_entities import (
        CanonicalDedupRule,
        SameCanonEntityDedupRule,
        SingletonNoiseRule,
        WeakEntityRule,
    )
    from knowbase.hygiene.rules.layer3_axes import (
        LowValueAxisRule,
        MisnamedAxisRule,
        RedundantAxisRule,
    )

    registry = {
        r.name: r for r in [
            StructuralEntityRule(),
            InvalidEntityNameRule(),
            DomainStoplistRule(),
            AcronymDedupRule(),
            SingletonNoiseRule(),
            WeakEntityRule(),
            CanonicalDedupRule(),
            SameCanonEntityDedupRule(),
            LowValueAxisRule(),
            RedundantAxisRule(),
            MisnamedAxisRule(),
        ]
    }
    return registry.get(rule_name)


@router.post("/actions/{action_id}/approve")
async def approve_action(action_id: str):
    """Approuver et appliquer une action PROPOSED."""
    from knowbase.hygiene.models import HygieneActionStatus
    from knowbase.hygiene.persistence import HygieneActionPersister

    neo4j_driver = _get_neo4j_driver()
    try:
        persister = HygieneActionPersister(neo4j_driver)
        action = persister.get_action(action_id)

        if not action:
            raise HTTPException(status_code=404, detail="Action introuvable")
        if action.status != HygieneActionStatus.PROPOSED:
            raise HTTPException(
                status_code=400,
                detail=f"Seules les actions PROPOSED peuvent être approuvées (status={action.status.value})",
            )

        # Snapshot complet avant apply (le dry run ne fait qu'un snapshot léger)
        if not action.before_state.get("relations"):
            full_snapshot = persister.snapshot_node(
                action.target_node_id,
                action.target_node_type,
                action.tenant_id,
            )
            action.before_state = full_snapshot

        # Résoudre la vraie règle pour dispatch correct (MERGE_AXIS, MERGE_CANONICAL, etc.)
        rule = _resolve_rule(action.rule_name)
        if not rule:
            # Fallback : règle de base (gère SUPPRESS_* et MERGE_CANONICAL)
            from knowbase.hygiene.rules.base import HygieneRule as BaseRule

            rule = type("FallbackRule", (BaseRule,), {
                "name": property(lambda s: action.rule_name),
                "layer": property(lambda s: action.layer),
                "scan": lambda s, **kw: [],
            })()

        try:
            success = rule.apply_action(neo4j_driver, action)
        except Exception as e:
            logger.error(f"apply_action failed for {action_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Erreur lors de l'application: {str(e)}",
            )

        if success:
            from datetime import datetime, timezone
            persister.update_status(
                action_id,
                HygieneActionStatus.APPLIED,
                applied_at=datetime.now(timezone.utc).isoformat(),
                decision_source="admin_approved",
            )
            # Mettre à jour le before_state si enrichi
            persister.save_action(action)
            return {"success": True, "action_id": action_id, "new_status": "APPLIED"}
        else:
            logger.warning(
                f"apply_action returned False for {action_id} "
                f"(rule={action.rule_name}, type={action.action_type})"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Application echouee (rule={action.rule_name}, type={action.action_type.value})",
            )
    finally:
        neo4j_driver.close()


@router.post("/rollback-batch", response_model=BatchRollbackResponse)
async def rollback_batch(
    batch_id: str = Query(...),
    tenant_id: str = Query(default="default"),
):
    """Rollback un batch complet."""
    from knowbase.hygiene.rollback import HygieneRollback

    neo4j_driver = _get_neo4j_driver()
    try:
        rollback = HygieneRollback(neo4j_driver)
        results = rollback.rollback_batch(batch_id, tenant_id)

        total_rolled = sum(1 for r in results if r.get("success"))
        total_failed = sum(1 for r in results if not r.get("success"))

        return BatchRollbackResponse(
            results=results,
            total_rolled_back=total_rolled,
            total_failed=total_failed,
        )
    finally:
        neo4j_driver.close()


@router.get("/stats", response_model=HygieneStatsResponse)
async def get_stats(
    tenant_id: str = Query(default="default"),
):
    """Stats agrégées des actions d'hygiène."""
    from knowbase.hygiene.persistence import HygieneActionPersister

    neo4j_driver = _get_neo4j_driver()
    try:
        persister = HygieneActionPersister(neo4j_driver)
        stats = persister.get_stats(tenant_id)
        return HygieneStatsResponse(**stats)
    finally:
        neo4j_driver.close()
