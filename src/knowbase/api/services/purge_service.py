"""
Service pour purger les données d'ingestion (Qdrant, Neo4j, Redis, PostgreSQL, fichiers).

Préserve les configurations (DocumentType, EntityTypeRegistry, OntologyEntity, DomainContextProfile).
Préserve aussi le cache d'extraction (data/extraction_cache/) pour permettre le rejeu.

ADR_GRAPH_FIRST_ARCHITECTURE: Mise à jour pour purger aussi le schéma Neo4j (constraints/indexes).
"""
import os
import shutil
from pathlib import Path
from typing import Dict, List
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "purge_service.log")

# Labels Neo4j à PRÉSERVER (configuration)
NEO4J_PRESERVED_LABELS = frozenset({
    "OntologyEntity",
    "OntologyAlias",
    "DomainContextProfile",
})

# Préfixes de constraints à PRÉSERVER
NEO4J_PRESERVED_CONSTRAINT_PREFIXES = (
    "ont_",           # OntologyEntity, OntologyAlias
    "domain_context", # DomainContextProfile
)


class PurgeService:
    """Service pour purger les données d'ingestion du système."""

    def __init__(self):
        """Initialize purge service."""
        pass

    async def purge_all_data(
        self,
        purge_schema: bool = False,
        recreate_schema: bool = False
    ) -> Dict[str, any]:
        """
        Purge toutes les données d'ingestion.

        Args:
            purge_schema: Si True, supprime aussi les constraints/indexes Neo4j
                         (utile pour repartir de zéro après changements de schéma)
            recreate_schema: Si True, recrée le schéma Neo4j après purge (MVP V1 + Pipeline V2)

        Nettoie:
        - Collection Qdrant (tous les points vectoriels)
        - Neo4j (tous les nodes/relations sauf OntologyEntity/OntologyAlias/DomainContextProfile)
        - Neo4j schema (constraints/indexes) si purge_schema=True
        - Redis (queues RQ, jobs terminés)
        - PostgreSQL (sessions, messages de conversation)
        - Répertoires docs_in, docs_done, status files

        Préserve:
        - DocumentType (PostgreSQL/SQLite)
        - EntityTypeRegistry (PostgreSQL/SQLite)
        - OntologyEntity, OntologyAlias, DomainContextProfile (Neo4j)
        - Cache d'extraction (data/extraction_cache/) ⚠️ CRITIQUE

        Returns:
            Dict avec résultats de purge par composant
        """
        schema_msg = " + SCHÉMA NEO4J" if purge_schema else ""
        recreate_msg = " + RECRÉATION SCHÉMA" if recreate_schema else ""
        logger.warning(f"🚨 PURGE SYSTÈME DÉMARRÉE - Suppression données d'ingestion{schema_msg}{recreate_msg}")

        results = {
            "qdrant": {"success": False, "message": "", "points_deleted": 0},
            "neo4j": {"success": False, "message": "", "nodes_deleted": 0, "relations_deleted": 0},
            "redis": {"success": False, "message": "", "jobs_deleted": 0},
            "postgres": {"success": False, "message": "", "sessions_deleted": 0, "messages_deleted": 0},
            "files": {"success": False, "message": "", "files_deleted": 0},
            "schema_recreate": {"success": False, "message": "", "constraints_created": 0, "indexes_created": 0},
        }

        # 1. Purge Qdrant
        try:
            results["qdrant"] = await self._purge_qdrant()
        except Exception as e:
            logger.error(f"❌ Erreur purge Qdrant: {e}")
            results["qdrant"]["message"] = str(e)

        # 2. Purge Neo4j (données + optionnellement schéma)
        try:
            results["neo4j"] = await self._purge_neo4j(purge_schema=purge_schema)
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

        # 6. Recréation du schéma Neo4j si demandé
        if recreate_schema:
            try:
                results["schema_recreate"] = await self._recreate_neo4j_schema()
            except Exception as e:
                logger.error(f"❌ Erreur recréation schéma: {e}")
                results["schema_recreate"]["message"] = str(e)

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

    async def _purge_neo4j(self, purge_schema: bool = False) -> Dict:
        """Purge Neo4j (supprime nodes et relations d'ingestion).

        Args:
            purge_schema: Si True, supprime aussi les constraints/indexes

        PRÉSERVE :
        - OntologyEntity (référentiel ontologies)
        - OntologyAlias (référentiel ontologies)
        - DomainContextProfile (configuration métier)

        SUPPRIME :
        - Tous les autres nodes (Document, CanonicalConcept, SectionContext, etc.)
        - Constraints/indexes (si purge_schema=True) sauf ceux des labels préservés

        NOTE: Utilise des batches pour éviter les timeouts avec des millions de relations.
        """
        logger.info(f"🔄 Purge Neo4j (purge_schema={purge_schema})...")

        try:
            import os
            from neo4j import GraphDatabase
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            constraints_deleted = 0
            indexes_deleted = 0

            try:
                with driver.session() as session:
                    # Construire la clause WHERE pour exclure les labels préservés
                    preserved_labels = list(NEO4J_PRESERVED_LABELS)
                    where_clauses = [f"NOT n:{label}" for label in preserved_labels]
                    where_clause = " AND ".join(where_clauses)

                    # Compter nodes/relations métier avant purge
                    count_result = session.run(f"""
                        MATCH (n)
                        WHERE {where_clause}
                        OPTIONAL MATCH (n)-[r]->()
                        RETURN count(DISTINCT n) as nodes, count(r) as relations
                    """)
                    counts = count_result.single()
                    nodes_before = counts["nodes"]
                    relations_before = counts["relations"]

                    # BATCH DELETE: Supprimer d'abord MENTIONED_IN (souvent des millions)
                    # car c'est la relation la plus volumineuse
                    logger.info("  - Suppression MENTIONED_IN par batches (peut prendre du temps)...")
                    batch_size = 50000
                    total_mentioned_in_deleted = 0
                    while True:
                        result = session.run("""
                            MATCH ()-[r:MENTIONED_IN]->()
                            WITH r LIMIT $batch_size
                            DELETE r
                            RETURN count(r) as deleted
                        """, batch_size=batch_size)
                        deleted = result.single()["deleted"]
                        if deleted == 0:
                            break
                        total_mentioned_in_deleted += deleted
                        logger.info(f"    - {total_mentioned_in_deleted} MENTIONED_IN supprimées...")

                    # BATCH DELETE: Supprimer les autres relations par batches
                    logger.info("  - Suppression autres relations par batches...")
                    total_other_rels_deleted = 0
                    while True:
                        result = session.run(f"""
                            MATCH (n)-[r]->()
                            WHERE {where_clause}
                            WITH r LIMIT $batch_size
                            DELETE r
                            RETURN count(r) as deleted
                        """, batch_size=batch_size)
                        deleted = result.single()["deleted"]
                        if deleted == 0:
                            break
                        total_other_rels_deleted += deleted
                        logger.info(f"    - {total_other_rels_deleted} autres relations supprimées...")

                    # BATCH DELETE: Supprimer les nodes par batches
                    logger.info("  - Suppression nodes par batches...")
                    total_nodes_deleted = 0
                    while True:
                        result = session.run(f"""
                            MATCH (n)
                            WHERE {where_clause}
                            WITH n LIMIT $batch_size
                            DETACH DELETE n
                            RETURN count(n) as deleted
                        """, batch_size=batch_size)
                        deleted = result.single()["deleted"]
                        if deleted == 0:
                            break
                        total_nodes_deleted += deleted
                        logger.info(f"    - {total_nodes_deleted} nodes supprimés...")

                    logger.info(
                        f"  - {nodes_before} nodes, {relations_before} relations supprimés"
                    )

                    # Purge du schéma si demandé
                    if purge_schema:
                        logger.info("  - Purge schéma (constraints/indexes)...")

                        # Récupérer et supprimer les constraints non-préservés
                        constraints_result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
                        for record in constraints_result:
                            constraint_name = record["name"]
                            # Vérifier si c'est un constraint à préserver
                            should_preserve = any(
                                constraint_name.startswith(prefix)
                                for prefix in NEO4J_PRESERVED_CONSTRAINT_PREFIXES
                            )
                            if not should_preserve:
                                try:
                                    session.run(f"DROP CONSTRAINT {constraint_name} IF EXISTS")
                                    constraints_deleted += 1
                                    logger.debug(f"    - Constraint supprimé: {constraint_name}")
                                except Exception as e:
                                    logger.warning(f"    - Échec suppression constraint {constraint_name}: {e}")

                        # Récupérer et supprimer les indexes non-préservés
                        # (les indexes liés aux constraints sont supprimés automatiquement)
                        indexes_result = session.run("""
                            SHOW INDEXES YIELD name, type
                            WHERE type <> 'LOOKUP'
                            RETURN name
                        """)
                        for record in indexes_result:
                            index_name = record["name"]
                            should_preserve = any(
                                index_name.startswith(prefix)
                                for prefix in NEO4J_PRESERVED_CONSTRAINT_PREFIXES
                            )
                            if not should_preserve:
                                try:
                                    session.run(f"DROP INDEX {index_name} IF EXISTS")
                                    indexes_deleted += 1
                                    logger.debug(f"    - Index supprimé: {index_name}")
                                except Exception as e:
                                    # Peut échouer si l'index était lié à un constraint déjà supprimé
                                    pass

                        logger.info(
                            f"  - Schéma purgé: {constraints_deleted} constraints, "
                            f"{indexes_deleted} indexes supprimés"
                        )

                    preserved_str = ", ".join(preserved_labels)
                    schema_str = f", {constraints_deleted} constraints supprimés" if purge_schema else ""
                    logger.info(
                        f"✅ Neo4j purgé: {nodes_before} nodes, {relations_before} relations"
                        f"{schema_str} (préservé: {preserved_str})"
                    )
                    return {
                        "success": True,
                        "message": f"Neo4j purgé (préservé: {preserved_str})",
                        "nodes_deleted": nodes_before,
                        "relations_deleted": relations_before,
                        "constraints_deleted": constraints_deleted,
                        "indexes_deleted": indexes_deleted,
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
                "constraints_deleted": 0,
                "indexes_deleted": 0,
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


    async def _recreate_neo4j_schema(self) -> Dict:
        """Recrée le schéma Neo4j (constraints et indexes).

        Crée les schémas pour:
        - MVP V1: InformationMVP, ClaimKey, Contradiction
        - Pipeline V2: Document, Subject, Theme, Concept, Information
        - Structural: DocumentContext, SectionContext, etc.
        """
        logger.info("🔄 Recréation schéma Neo4j...")

        try:
            import os
            from neo4j import GraphDatabase
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            constraints_created = 0
            indexes_created = 0

            # Schémas à créer
            CONSTRAINTS = [
                # MVP V1: InformationMVP
                ("information_mvp_id", "CREATE CONSTRAINT information_mvp_id IF NOT EXISTS FOR (i:InformationMVP) REQUIRE i.information_id IS UNIQUE"),
                # MVP V1: ClaimKey
                ("claimkey_id", "CREATE CONSTRAINT claimkey_id IF NOT EXISTS FOR (ck:ClaimKey) REQUIRE ck.claimkey_id IS UNIQUE"),
                # MVP V1: Contradiction
                ("contradiction_id", "CREATE CONSTRAINT contradiction_id IF NOT EXISTS FOR (c:Contradiction) REQUIRE c.contradiction_id IS UNIQUE"),
                # Pipeline V2: Document
                ("document_id", "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE"),
                # Pipeline V2: Subject
                ("subject_id", "CREATE CONSTRAINT subject_id IF NOT EXISTS FOR (s:Subject) REQUIRE s.subject_id IS UNIQUE"),
                # Pipeline V2: Theme
                ("theme_id", "CREATE CONSTRAINT theme_id IF NOT EXISTS FOR (t:Theme) REQUIRE t.theme_id IS UNIQUE"),
                # Pipeline V2: Concept
                ("concept_id", "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE"),
                # Pipeline V2: Information
                ("info_id", "CREATE CONSTRAINT info_id IF NOT EXISTS FOR (i:Information) REQUIRE i.info_id IS UNIQUE"),
                # Structural: DocumentContext
                ("doc_context_id", "CREATE CONSTRAINT doc_context_id IF NOT EXISTS FOR (dc:DocumentContext) REQUIRE dc.document_id IS UNIQUE"),
                # Structural: CanonicalConcept
                ("canonical_concept_id", "CREATE CONSTRAINT canonical_concept_id IF NOT EXISTS FOR (cc:CanonicalConcept) REQUIRE cc.concept_id IS UNIQUE"),
                # Structural: ProtoConcept
                ("proto_concept_id", "CREATE CONSTRAINT proto_concept_id IF NOT EXISTS FOR (pc:ProtoConcept) REQUIRE pc.proto_id IS UNIQUE"),
            ]

            INDEXES = [
                # MVP V1: InformationMVP indexes
                ("information_mvp_tenant", "CREATE INDEX information_mvp_tenant IF NOT EXISTS FOR (i:InformationMVP) ON (i.tenant_id)"),
                ("information_mvp_status", "CREATE INDEX information_mvp_status IF NOT EXISTS FOR (i:InformationMVP) ON (i.promotion_status)"),
                ("information_mvp_fingerprint", "CREATE INDEX information_mvp_fingerprint IF NOT EXISTS FOR (i:InformationMVP) ON (i.fingerprint)"),
                ("information_mvp_document", "CREATE INDEX information_mvp_document IF NOT EXISTS FOR (i:InformationMVP) ON (i.document_id)"),
                # MVP V1: ClaimKey indexes
                ("claimkey_tenant", "CREATE INDEX claimkey_tenant IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.tenant_id)"),
                ("claimkey_status", "CREATE INDEX claimkey_status IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.status)"),
                ("claimkey_key", "CREATE INDEX claimkey_key IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.key)"),
                ("claimkey_domain", "CREATE INDEX claimkey_domain IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.domain)"),
                # MVP V1: Contradiction indexes
                ("contradiction_claimkey", "CREATE INDEX contradiction_claimkey IF NOT EXISTS FOR (c:Contradiction) ON (c.claimkey_id)"),
                # Pipeline V2 indexes
                ("document_tenant", "CREATE INDEX document_tenant IF NOT EXISTS FOR (d:Document) ON (d.tenant_id)"),
                ("concept_tenant", "CREATE INDEX concept_tenant IF NOT EXISTS FOR (c:Concept) ON (c.tenant_id)"),
                ("information_tenant", "CREATE INDEX information_tenant IF NOT EXISTS FOR (i:Information) ON (i.tenant_id)"),
                # Structural indexes
                ("canonical_concept_tenant", "CREATE INDEX canonical_concept_tenant IF NOT EXISTS FOR (cc:CanonicalConcept) ON (cc.tenant_id)"),
                ("canonical_concept_type", "CREATE INDEX canonical_concept_type IF NOT EXISTS FOR (cc:CanonicalConcept) ON (cc.type)"),
                ("proto_concept_tenant", "CREATE INDEX proto_concept_tenant IF NOT EXISTS FOR (pc:ProtoConcept) ON (pc.tenant_id)"),
            ]

            try:
                with driver.session() as session:
                    # Créer les constraints
                    logger.info("  - Création des contraintes...")
                    for name, query in CONSTRAINTS:
                        try:
                            session.run(query)
                            constraints_created += 1
                            logger.debug(f"    ✓ Constraint {name}")
                        except Exception as e:
                            logger.warning(f"    ⚠ Constraint {name}: {e}")

                    # Créer les indexes
                    logger.info("  - Création des index...")
                    for name, query in INDEXES:
                        try:
                            session.run(query)
                            indexes_created += 1
                            logger.debug(f"    ✓ Index {name}")
                        except Exception as e:
                            logger.warning(f"    ⚠ Index {name}: {e}")

                logger.info(
                    f"✅ Schéma Neo4j recréé: {constraints_created} contraintes, "
                    f"{indexes_created} index"
                )
                return {
                    "success": True,
                    "message": f"Schéma recréé: {constraints_created} contraintes, {indexes_created} index",
                    "constraints_created": constraints_created,
                    "indexes_created": indexes_created,
                }
            finally:
                driver.close()

        except Exception as e:
            logger.error(f"❌ Erreur recréation schéma Neo4j: {e}")
            return {
                "success": False,
                "message": f"Erreur: {str(e)}",
                "constraints_created": 0,
                "indexes_created": 0,
            }


__all__ = ["PurgeService"]
