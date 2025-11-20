"""
Service pour purger les données d'ingestion (Qdrant, Neo4j, Redis).

Préserve les configurations (DocumentType, EntityTypeRegistry).
"""
from typing import Dict, List
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "purge_service.log")


class PurgeService:
    """Service pour purger les données d'ingestion du système."""

    def __init__(self):
        """Initialize purge service."""
        pass

    async def purge_all_data(self) -> Dict[str, any]:
        """
        Purge toutes les données d'ingestion.

        Nettoie:
        - Collection Qdrant (tous les points vectoriels)
        - Neo4j (tous les nodes/relations sauf config)
        - Redis (queues RQ, jobs terminés)

        Préserve:
        - DocumentType (SQLite)
        - EntityTypeRegistry (SQLite)
        - Fichiers dans data/ (docs_in, docs_done, slides, thumbnails)

        Returns:
            Dict avec résultats de purge par composant
        """
        logger.warning("🚨 PURGE SYSTÈME DÉMARRÉE - Suppression données d'ingestion")

        results = {
            "qdrant": {"success": False, "message": "", "points_deleted": 0},
            "neo4j": {"success": False, "message": "", "nodes_deleted": 0, "relations_deleted": 0},
            "redis": {"success": False, "message": "", "jobs_deleted": 0},
        }

        # 1. Purge Qdrant
        try:
            results["qdrant"] = await self._purge_qdrant()
        except Exception as e:
            logger.error(f"❌ Erreur purge Qdrant: {e}")
            results["qdrant"]["message"] = str(e)

        # 2. Purge Neo4j
        try:
            results["neo4j"] = await self._purge_neo4j()
        except Exception as e:
            logger.error(f"❌ Erreur purge Neo4j: {e}")
            results["neo4j"]["message"] = str(e)

        # 3. Purge Redis
        try:
            results["redis"] = await self._purge_redis()
        except Exception as e:
            logger.error(f"❌ Erreur purge Redis: {e}")
            results["redis"]["message"] = str(e)

        logger.warning(f"✅ PURGE TERMINÉE - Résultats: {results}")
        return results

    async def _purge_qdrant(self) -> Dict:
        """Purge collection Qdrant (supprime tous les points vectoriels)."""
        logger.info("🔄 Purge Qdrant...")

        try:
            from knowbase.common.clients import get_qdrant_client, ensure_qdrant_collection, get_sentence_transformer
            qdrant_client = get_qdrant_client()
            collection_name = settings.qdrant_collection

            # Récupérer nombre de points avant purge
            collection_info = qdrant_client.get_collection(collection_name)
            points_count = collection_info.points_count

            # Supprimer tous les points de la collection
            # Option 1: Supprimer et recréer (plus propre)
            qdrant_client.delete_collection(collection_name)

            # Recréer collection vide avec la bonne dimension
            vector_size = get_sentence_transformer().get_sentence_embedding_dimension() or 1024
            ensure_qdrant_collection(collection_name, vector_size)

            logger.info(f"✅ Qdrant purgé: {points_count} points supprimés, collection recréée")
            return {
                "success": True,
                "message": f"Collection '{collection_name}' purgée et recréée",
                "points_deleted": points_count,
            }

        except Exception as e:
            logger.error(f"❌ Erreur purge Qdrant: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "points_deleted": 0,
            }

    async def _purge_neo4j(self) -> Dict:
        """Purge Neo4j (supprime nodes et relations d'ingestion).

        PRÉSERVE :
        - OntologyEntity (référentiel ontologies)
        - OntologyAlias (référentiel ontologies)

        SUPPRIME :
        - Entity, Episode, Fact, Relation (données métier)
        """
        logger.info("🔄 Purge Neo4j...")

        try:
            import os
            from neo4j import GraphDatabase
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            try:
                with driver.session() as session:
                    # Compter nodes/relations métier avant purge (EXCLURE ontologies)
                    count_result = session.run("""
                        MATCH (n)
                        WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias
                        OPTIONAL MATCH (n)-[r]->()
                        RETURN count(DISTINCT n) as nodes, count(r) as relations
                    """)
                    counts = count_result.single()
                    nodes_before = counts["nodes"]
                    relations_before = counts["relations"]

                    # Supprimer SEULEMENT les nodes métier (préserver ontologies)
                    # ⚠️ IMPORTANT : Ne PAS toucher aux OntologyEntity et OntologyAlias
                    session.run("""
                        MATCH (n)
                        WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias
                        DETACH DELETE n
                    """)

                    logger.info(
                        f"✅ Neo4j purgé: {nodes_before} nodes métier, "
                        f"{relations_before} relations supprimés (ontologies préservées)"
                    )
                    return {
                        "success": True,
                        "message": f"Neo4j purgé (ontologies préservées)",
                        "nodes_deleted": nodes_before,
                        "relations_deleted": relations_before,
                    }
            finally:
                driver.close()

        except Exception as e:
            logger.error(f"❌ Erreur purge Neo4j: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "nodes_deleted": 0,
                "relations_deleted": 0,
            }

    async def _purge_redis(self) -> Dict:
        """Purge Redis (supprime jobs RQ terminés et queues)."""
        logger.info("🔄 Purge Redis...")

        try:
            import redis
            redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,  # DB par défaut pour RQ
                decode_responses=True
            )

            # Compter clés avant purge
            all_keys = redis_client.keys("rq:*")
            keys_count = len(all_keys)

            # Supprimer toutes les clés RQ (jobs, queues, résultats)
            if keys_count > 0:
                redis_client.delete(*all_keys)

            logger.info(f"✅ Redis purgé: {keys_count} clés RQ supprimées")
            return {
                "success": True,
                "message": f"{keys_count} clés RQ supprimées",
                "jobs_deleted": keys_count,
            }

        except Exception as e:
            logger.error(f"❌ Erreur purge Redis: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "jobs_deleted": 0,
            }


__all__ = ["PurgeService"]
