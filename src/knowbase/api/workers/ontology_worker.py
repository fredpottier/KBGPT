"""
Ontology Worker - Job RQ pour génération ontologie via LLM.

Phase 5B - Solution 3 Hybride
Step 2 - Worker async génération ontologie

Exécuté par worker RQ, appelle OntologyGeneratorService.
"""
import json
from redis import Redis
import os

from knowbase.api.services.ontology_generator_service import OntologyGeneratorService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "ontology_worker.log")


def generate_ontology_task(
    type_name: str,
    entities: list,
    model_preference: str = "claude-sonnet",
    tenant_id: str = "default"
):
    """
    Task RQ: Génère ontologie depuis entités.

    Appelé de manière asynchrone par worker RQ.
    Résultat stocké dans Redis (clé: ontology_proposal:{type_name}:{tenant_id}).

    Args:
        type_name: Type entités
        entities: Liste dicts entités
        model_preference: Modèle LLM
        tenant_id: Tenant ID

    Returns:
        Dict résultat ontologie
    """
    logger.info(
        f"🤖 [Worker] Génération ontologie {type_name} - "
        f"{len(entities)} entités, model={model_preference}"
    )

    try:
        # Créer service
        ontology_service = OntologyGeneratorService()

        # Générer ontologie (appel async LLM)
        # Note: asyncio.run() car worker RQ n'est pas async
        import asyncio
        ontology_result = asyncio.run(
            ontology_service.generate_ontology_from_entities(
                entity_type=type_name,
                entities=entities,
                model_preference=model_preference
            )
        )

        # Stocker résultat dans Redis
        redis_conn = Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=1
        )

        redis_key = f"ontology_proposal:{type_name}:{tenant_id}"
        redis_conn.setex(
            redis_key,
            86400 * 7,  # TTL 7 jours
            json.dumps(ontology_result)
        )

        # Mettre à jour statut normalisation dans registry
        from knowbase.db.base import SessionLocal
        from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

        db = SessionLocal()
        try:
            service = EntityTypeRegistryService(db)
            entity_type = service.get_type_by_name(type_name, tenant_id)

            if entity_type:
                entity_type.normalization_status = 'pending_review'
                db.commit()
                logger.info(f"📝 [Worker] Statut normalisation mis à jour: pending_review")
            else:
                logger.warning(f"⚠️ [Worker] Type {type_name} non trouvé dans registry, statut non mis à jour")
        finally:
            db.close()

        logger.info(
            f"✅ [Worker] Ontologie générée et stockée: {redis_key} - "
            f"{ontology_result['groups_proposed']} groupes"
        )

        return ontology_result

    except Exception as e:
        logger.error(f"❌ [Worker] Erreur génération ontologie: {e}", exc_info=True)

        # Réinitialiser statut normalisation en cas d'erreur
        from knowbase.db.base import SessionLocal
        from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

        db = SessionLocal()
        try:
            service = EntityTypeRegistryService(db)
            entity_type = service.get_type_by_name(type_name, tenant_id)

            if entity_type:
                entity_type.normalization_status = None
                entity_type.normalization_job_id = None
                db.commit()
                logger.info(f"📝 [Worker] Statut normalisation réinitialisé suite à erreur")
        except Exception as db_error:
            logger.error(f"⚠️ [Worker] Erreur lors de la mise à jour du statut: {db_error}")
        finally:
            db.close()

        raise


__all__ = ["generate_ontology_task"]
