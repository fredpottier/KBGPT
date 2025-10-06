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

        logger.info(
            f"✅ [Worker] Ontologie générée et stockée: {redis_key} - "
            f"{ontology_result['groups_proposed']} groupes"
        )

        return ontology_result

    except Exception as e:
        logger.error(f"❌ [Worker] Erreur génération ontologie: {e}", exc_info=True)
        raise


__all__ = ["generate_ontology_task"]
