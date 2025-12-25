"""
Service pour purger les données d'ingestion (Qdrant, Neo4j, Redis, PostgreSQL, fichiers).

Préserve les configurations (DocumentType, EntityTypeRegistry, OntologyEntity).
Préserve aussi le cache d'extraction (data/extraction_cache/) pour permettre le rejeu.
"""
import os
import shutil
from pathlib import Path
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
        - Neo4j (tous les nodes/relations sauf OntologyEntity/OntologyAlias)
        - Redis (queues RQ, jobs terminés)
        - PostgreSQL (sessions, messages de conversation)
        - Répertoires docs_in, docs_done, status files

        Préserve:
        - DocumentType (PostgreSQL/SQLite)
        - EntityTypeRegistry (PostgreSQL/SQLite)
        - OntologyEntity, OntologyAlias (Neo4j)
        - Cache d'extraction (data/extraction_cache/) ⚠️ CRITIQUE

        Returns:
            Dict avec résultats de purge par composant
        """
        logger.warning("🚨 PURGE SYSTÈME DÉMARRÉE - Suppression données d'ingestion")

        results = {
            "qdrant": {"success": False, "message": "", "points_deleted": 0},
            "neo4j": {"success": False, "message": "", "nodes_deleted": 0, "relations_deleted": 0},
            "redis": {"success": False, "message": "", "jobs_deleted": 0},
            "postgres": {"success": False, "message": "", "sessions_deleted": 0, "messages_deleted": 0},
            "files": {"success": False, "message": "", "files_deleted": 0},
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

        # 4. Purge PostgreSQL (sessions, messages)
        try:
            results["postgres"] = await self._purge_postgres()
        except Exception as e:
            logger.error(f"❌ Erreur purge PostgreSQL: {e}")
            results["postgres"]["message"] = str(e)

        # 5. Purge répertoires fichiers (docs_in, docs_done, status)
        try:
            results["files"] = await self._purge_file_directories()
        except Exception as e:
            logger.error(f"❌ Erreur purge fichiers: {e}")
            results["files"]["message"] = str(e)

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
        """Purge Redis (jobs RQ, historique imports, queues).

        DB 0 (RQ jobs):
        - rq:* (jobs, queues RQ)
        - knowbase:* (autres clés applicatives)

        DB 1 (Import history):
        - import:* (détails imports)
        - import_history:* (liste historique)
        """
        logger.info("🔄 Purge Redis...")

        try:
            import redis

            total_deleted = 0

            # DB 0 - Jobs RQ
            redis_db0 = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,
                decode_responses=True
            )
            patterns_db0 = ["rq:*", "knowbase:*"]
            for pattern in patterns_db0:
                keys = redis_db0.keys(pattern)
                if keys:
                    redis_db0.delete(*keys)
                    logger.info(f"  - DB0: {len(keys)} clés '{pattern}' supprimées")
                    total_deleted += len(keys)

            # DB 1 - Historique imports
            redis_db1 = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=1,
                decode_responses=True
            )
            patterns_db1 = ["import:*", "import_history:*"]
            for pattern in patterns_db1:
                keys = redis_db1.keys(pattern)
                if keys:
                    redis_db1.delete(*keys)
                    logger.info(f"  - DB1: {len(keys)} clés '{pattern}' supprimées")
                    total_deleted += len(keys)

            logger.info(f"✅ Redis purgé: {total_deleted} clés supprimées (DB0 + DB1)")
            return {
                "success": True,
                "message": f"{total_deleted} clés supprimées (RQ + historique imports)",
                "jobs_deleted": total_deleted,
            }

        except Exception as e:
            logger.error(f"❌ Erreur purge Redis: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "jobs_deleted": 0,
            }

    async def _purge_postgres(self) -> Dict:
        """Purge PostgreSQL (sessions et messages de conversation).

        PRÉSERVE :
        - User (utilisateurs)
        - DomainContext (configuration métier globale) ⚠️ CRITIQUE
        - DocumentType (configuration)
        - EntityTypeRegistry (configuration)
        - AuditLog (traçabilité - important!)

        SUPPRIME :
        - Session (conversations)
        - SessionMessage (messages de conversation)
        """
        logger.info("🔄 Purge PostgreSQL (sessions)...")

        try:
            from knowbase.db import get_db
            from knowbase.db.models import Session, SessionMessage

            # Obtenir une session DB
            db = next(get_db())

            try:
                # Compter avant suppression
                messages_count = db.query(SessionMessage).count()
                sessions_count = db.query(Session).count()

                # Supprimer dans l'ordre (messages d'abord à cause des FK)
                db.query(SessionMessage).delete()
                db.query(Session).delete()
                db.commit()

                logger.info(
                    f"✅ PostgreSQL purgé: {sessions_count} sessions, "
                    f"{messages_count} messages supprimés"
                )
                return {
                    "success": True,
                    "message": f"{sessions_count} sessions, {messages_count} messages supprimés",
                    "sessions_deleted": sessions_count,
                    "messages_deleted": messages_count,
                }
            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Erreur purge PostgreSQL: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "sessions_deleted": 0,
                "messages_deleted": 0,
            }

    async def _purge_file_directories(self) -> Dict:
        """Purge répertoires de fichiers traités.

        SUPPRIME :
        - data/docs_in/* (documents en attente)
        - data/docs_done/* (documents traités)
        - data/status/*.status (fichiers de statut)

        PRÉSERVE (CRITIQUE) :
        - data/extraction_cache/*.knowcache.json (cache d'extraction LLM)
        - data/public/* (slides, thumbnails, presentations)
        """
        logger.info("🔄 Purge répertoires fichiers...")

        try:
            # Chemins relatifs au projet
            data_dir = Path(settings.data_dir) if hasattr(settings, 'data_dir') else Path("/app/data")

            # Si on est en local (Windows), utiliser un chemin différent
            if not data_dir.exists():
                data_dir = Path("data")

            docs_in_dir = data_dir / "docs_in"
            docs_done_dir = data_dir / "docs_done"
            status_dir = data_dir / "status"

            files_deleted = 0

            # Purge docs_in
            if docs_in_dir.exists():
                for f in docs_in_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                        files_deleted += 1
                    elif f.is_dir():
                        shutil.rmtree(f)
                        files_deleted += 1
                logger.info(f"  - docs_in purgé")

            # Purge docs_done
            if docs_done_dir.exists():
                for f in docs_done_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                        files_deleted += 1
                    elif f.is_dir():
                        shutil.rmtree(f)
                        files_deleted += 1
                logger.info(f"  - docs_done purgé")

            # Purge status files (*.status uniquement)
            if status_dir.exists():
                for f in status_dir.glob("*.status"):
                    f.unlink()
                    files_deleted += 1
                logger.info(f"  - status files purgés")

            # ⚠️ NE PAS toucher à extraction_cache !
            logger.info(f"  - extraction_cache PRÉSERVÉ ✅")

            logger.info(f"✅ Fichiers purgés: {files_deleted} éléments supprimés")
            return {
                "success": True,
                "message": f"{files_deleted} fichiers/dossiers supprimés (cache préservé)",
                "files_deleted": files_deleted,
            }

        except Exception as e:
            logger.error(f"❌ Erreur purge fichiers: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "files_deleted": 0,
            }


__all__ = ["PurgeService"]
