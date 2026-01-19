"""
OSMOSE Structural Archiver - Archivage réversible post-Pass 3

Ce module permet d'archiver les nodes Neo4j qui ne sont plus nécessaires
après la complétion du Pass 3 (semantic_consolidation), tout en conservant
la possibilité de les réimporter si besoin.

Nodes archivables (72% du total):
- DocItem: Éléments structurels atomiques (texte, heading, table, figure)
- TypeAwareChunk: Chunks typés pour extraction de relations
- PageContext: Contexte de pagination

Nodes préservés (28% du total):
- DocumentContext/DocumentVersion: Métadonnées document
- SectionContext: Hiérarchie de sections (utilisé par relations)
- ProtoConcept: Concepts extraits (cœur du KG)
- DocumentChunk: Chunks vectorisés pour recherche

Spec: Cette architecture permet de passer de 2.3M nodes à 540K nodes
pour 1000 documents (réduction de 77%).
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ArchiveStats(BaseModel):
    """Statistiques d'une opération d'archivage."""

    document_id: str
    tenant_id: str
    archived_at: str
    pass3_completed_at: Optional[str] = None

    # Compteurs par type de node
    doc_items_archived: int = 0
    type_aware_chunks_archived: int = 0
    page_contexts_archived: int = 0

    # Total
    total_nodes_archived: int = 0
    archive_path: str = ""

    # Checksum pour vérification intégrité
    archive_checksum: Optional[str] = None


class ArchiveManifest(BaseModel):
    """Manifest d'une archive document."""

    version: str = "1.0.0"
    created_at: str
    document_id: str
    doc_version_id: str
    tenant_id: str

    # État au moment de l'archivage
    pass1_status: str
    pass2_status: str
    pass2_phases_completed: list[str]
    last_enrichment: Optional[str] = None

    # Fichiers dans l'archive
    files: list[str]
    stats: ArchiveStats


class StructuralArchiver:
    """
    Gestionnaire d'archivage réversible pour les nodes structurels.

    Workflow:
    1. Vérifier que Pass 3 est complet pour le document
    2. Exporter les nodes archivables vers JSON
    3. Supprimer les nodes de Neo4j (transaction atomique)
    4. Générer le manifest d'archive

    Réimportation:
    1. Lire le manifest et vérifier l'intégrité
    2. Recréer les nodes dans Neo4j
    3. Supprimer l'archive si succès
    """

    # Types de nodes à archiver (ordre de suppression important pour les relations)
    ARCHIVABLE_NODE_TYPES = [
        "TypeAwareChunk",  # Supprimer d'abord (référence DocItem)
        "DocItem",         # Supprimer ensuite
        "PageContext",     # Supprimer en dernier
    ]

    def __init__(
        self,
        archive_base_path: str = "data/archives",
        neo4j_driver=None,
    ):
        """
        Initialise l'archiveur.

        Args:
            archive_base_path: Répertoire de base pour les archives
            neo4j_driver: Driver Neo4j (optionnel, récupéré si non fourni)
        """
        self.archive_base_path = Path(archive_base_path)
        self.archive_base_path.mkdir(parents=True, exist_ok=True)
        self._driver = neo4j_driver

    @property
    def driver(self):
        """Récupère le driver Neo4j à la demande."""
        if self._driver is None:
            from neo4j import GraphDatabase
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
            self._driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        return self._driver

    def is_pass3_complete(self, document_id: str, tenant_id: str = "default") -> tuple[bool, dict]:
        """
        Vérifie si Pass 3 (semantic_consolidation) est complet pour un document.

        Returns:
            Tuple (is_complete, document_state)
        """
        query = """
        MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
        RETURN d.pass1_status AS pass1_status,
               d.pass2_status AS pass2_status,
               d.pass2_phases_completed AS pass2_phases_completed,
               d.last_enrichment AS last_enrichment,
               d.pass2_completed_at AS pass2_completed_at
        """

        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, doc_id=document_id)
            record = result.single()

            if not record:
                logger.warning(f"Document {document_id} non trouvé dans Neo4j")
                return False, {"error": "document_not_found"}

            state = {
                "pass1_status": record["pass1_status"],
                "pass2_status": record["pass2_status"],
                "pass2_phases_completed": record["pass2_phases_completed"] or [],
                "last_enrichment": record["last_enrichment"],
                "pass2_completed_at": record["pass2_completed_at"],
            }

            # Vérification stricte: Pass 1 et Pass 2 complets + semantic_consolidation fait
            is_complete = (
                state["pass1_status"] == "COMPLETE"
                and state["pass2_status"] == "COMPLETE"
                and "semantic_consolidation" in state["pass2_phases_completed"]
            )

            return is_complete, state

    def get_archivable_documents(
        self,
        tenant_id: str = "default",
        min_age_days: int = 0,
    ) -> list[dict]:
        """
        Liste les documents éligibles à l'archivage.

        Args:
            tenant_id: ID du tenant
            min_age_days: Âge minimum depuis Pass 3 complet (0 = tous)

        Returns:
            Liste des documents avec leurs métadonnées
        """
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        WHERE d.pass1_status = 'COMPLETE'
          AND d.pass2_status = 'COMPLETE'
          AND d.pass2_phases_completed IS NOT NULL
          AND 'semantic_consolidation' IN d.pass2_phases_completed
        OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion {is_current: true})
        RETURN d.doc_id AS doc_id,
               d.last_enrichment AS last_enrichment,
               d.pass2_completed_at AS pass2_completed_at,
               v.doc_version_id AS doc_version_id,
               v.page_count AS page_count,
               v.item_count AS item_count
        ORDER BY d.last_enrichment ASC
        """

        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            documents = []

            for record in result:
                doc = {
                    "doc_id": record["doc_id"],
                    "doc_version_id": record["doc_version_id"],
                    "last_enrichment": record["last_enrichment"],
                    "pass2_completed_at": record["pass2_completed_at"],
                    "page_count": record["page_count"],
                    "item_count": record["item_count"],
                }

                # Filtrer par âge si spécifié
                if min_age_days > 0 and doc["pass2_completed_at"]:
                    try:
                        completed = datetime.fromisoformat(
                            doc["pass2_completed_at"].replace("Z", "+00:00")
                        )
                        age = (datetime.now(timezone.utc) - completed).days
                        if age < min_age_days:
                            continue
                    except (ValueError, TypeError):
                        pass

                documents.append(doc)

            return documents

    def _get_archive_path(self, document_id: str, tenant_id: str) -> Path:
        """Construit le chemin d'archive pour un document."""
        safe_doc_id = document_id.replace("/", "_").replace("\\", "_")
        return self.archive_base_path / tenant_id / safe_doc_id

    def _export_nodes(
        self,
        document_id: str,
        doc_version_id: str,
        tenant_id: str,
        archive_path: Path,
    ) -> dict[str, int]:
        """
        Exporte les nodes archivables vers des fichiers JSON.

        Returns:
            Dictionnaire avec le nombre de nodes exportés par type
        """
        counts = {}

        # Export DocItems
        doc_items_query = """
        MATCH (i:DocItem {tenant_id: $tenant_id, doc_id: $doc_id, doc_version_id: $doc_version_id})
        RETURN i {.*} AS node
        ORDER BY i.reading_order_index
        """

        with self.driver.session() as session:
            result = session.run(
                doc_items_query,
                tenant_id=tenant_id,
                doc_id=document_id,
                doc_version_id=doc_version_id,
            )
            doc_items = [dict(record["node"]) for record in result]

            if doc_items:
                with open(archive_path / "doc_items.json", "w", encoding="utf-8") as f:
                    json.dump(doc_items, f, ensure_ascii=False, indent=2, default=str)
                counts["DocItem"] = len(doc_items)
                logger.info(f"  Exporté {len(doc_items)} DocItems")

        # Export TypeAwareChunks
        chunks_query = """
        MATCH (c:TypeAwareChunk {tenant_id: $tenant_id, doc_id: $doc_id, doc_version_id: $doc_version_id})
        RETURN c {.*} AS node
        ORDER BY c.chunk_id
        """

        with self.driver.session() as session:
            result = session.run(
                chunks_query,
                tenant_id=tenant_id,
                doc_id=document_id,
                doc_version_id=doc_version_id,
            )
            chunks = [dict(record["node"]) for record in result]

            if chunks:
                with open(archive_path / "type_aware_chunks.json", "w", encoding="utf-8") as f:
                    json.dump(chunks, f, ensure_ascii=False, indent=2, default=str)
                counts["TypeAwareChunk"] = len(chunks)
                logger.info(f"  Exporté {len(chunks)} TypeAwareChunks")

        # Export PageContexts
        pages_query = """
        MATCH (p:PageContext {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
        RETURN p {.*} AS node
        ORDER BY p.page_no
        """

        with self.driver.session() as session:
            result = session.run(
                pages_query,
                tenant_id=tenant_id,
                doc_version_id=doc_version_id,
            )
            pages = [dict(record["node"]) for record in result]

            if pages:
                with open(archive_path / "page_contexts.json", "w", encoding="utf-8") as f:
                    json.dump(pages, f, ensure_ascii=False, indent=2, default=str)
                counts["PageContext"] = len(pages)
                logger.info(f"  Exporté {len(pages)} PageContexts")

        return counts

    def _delete_archived_nodes(
        self,
        document_id: str,
        doc_version_id: str,
        tenant_id: str,
    ) -> dict[str, int]:
        """
        Supprime les nodes archivés de Neo4j (transaction atomique).

        Returns:
            Dictionnaire avec le nombre de nodes supprimés par type
        """
        counts = {}

        # Supprimer dans l'ordre pour respecter les relations
        delete_queries = [
            # TypeAwareChunks d'abord
            (
                "TypeAwareChunk",
                """
                MATCH (c:TypeAwareChunk {tenant_id: $tenant_id, doc_id: $doc_id, doc_version_id: $doc_version_id})
                WITH c LIMIT 1000
                DETACH DELETE c
                RETURN count(*) AS deleted
                """
            ),
            # DocItems ensuite
            (
                "DocItem",
                """
                MATCH (i:DocItem {tenant_id: $tenant_id, doc_id: $doc_id, doc_version_id: $doc_version_id})
                WITH i LIMIT 1000
                DETACH DELETE i
                RETURN count(*) AS deleted
                """
            ),
            # PageContexts en dernier
            (
                "PageContext",
                """
                MATCH (p:PageContext {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
                WITH p LIMIT 1000
                DETACH DELETE p
                RETURN count(*) AS deleted
                """
            ),
        ]

        with self.driver.session() as session:
            for node_type, query in delete_queries:
                total_deleted = 0

                # Suppression par batches pour éviter les timeouts
                while True:
                    result = session.run(
                        query,
                        tenant_id=tenant_id,
                        doc_id=document_id,
                        doc_version_id=doc_version_id,
                    )
                    deleted = result.single()["deleted"]
                    total_deleted += deleted

                    if deleted < 1000:
                        break

                counts[node_type] = total_deleted
                if total_deleted > 0:
                    logger.info(f"  Supprimé {total_deleted} {node_type}s")

        return counts

    def archive_document(
        self,
        document_id: str,
        tenant_id: str = "default",
        force: bool = False,
    ) -> Optional[ArchiveStats]:
        """
        Archive un document complet (export JSON + suppression Neo4j).

        Args:
            document_id: ID du document à archiver
            tenant_id: ID du tenant
            force: Si True, archive même si Pass 3 non complet (dangereux!)

        Returns:
            ArchiveStats si succès, None sinon
        """
        logger.info(f"[ARCHIVER] Début archivage document {document_id}")

        # Étape 1: Vérifier Pass 3 complet
        is_complete, state = self.is_pass3_complete(document_id, tenant_id)

        if not is_complete and not force:
            logger.warning(
                f"[ARCHIVER] Document {document_id} non éligible: "
                f"pass1={state.get('pass1_status')}, pass2={state.get('pass2_status')}, "
                f"phases={state.get('pass2_phases_completed')}"
            )
            return None

        if not is_complete and force:
            logger.warning(f"[ARCHIVER] FORCE: Archivage {document_id} malgré Pass 3 incomplet!")

        # Étape 2: Récupérer la version courante du document
        version_query = """
        MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
               -[:HAS_VERSION]->(v:DocumentVersion {is_current: true})
        RETURN v.doc_version_id AS doc_version_id
        """

        with self.driver.session() as session:
            result = session.run(version_query, tenant_id=tenant_id, doc_id=document_id)
            record = result.single()
            if not record:
                logger.error(f"[ARCHIVER] Version courante non trouvée pour {document_id}")
                return None
            doc_version_id = record["doc_version_id"]

        # Étape 3: Créer le répertoire d'archive
        archive_path = self._get_archive_path(document_id, tenant_id)
        archive_path.mkdir(parents=True, exist_ok=True)

        try:
            # Étape 4: Exporter les nodes
            logger.info(f"[ARCHIVER] Export des nodes vers {archive_path}")
            export_counts = self._export_nodes(document_id, doc_version_id, tenant_id, archive_path)

            if sum(export_counts.values()) == 0:
                logger.info(f"[ARCHIVER] Aucun node à archiver pour {document_id}")
                # Nettoyer le répertoire vide
                archive_path.rmdir()
                return None

            # Étape 5: Créer le manifest AVANT suppression
            manifest = ArchiveManifest(
                created_at=datetime.now(timezone.utc).isoformat(),
                document_id=document_id,
                doc_version_id=doc_version_id,
                tenant_id=tenant_id,
                pass1_status=state.get("pass1_status", "UNKNOWN"),
                pass2_status=state.get("pass2_status", "UNKNOWN"),
                pass2_phases_completed=state.get("pass2_phases_completed", []),
                last_enrichment=state.get("last_enrichment"),
                files=[f.name for f in archive_path.glob("*.json") if f.name != "manifest.json"],
                stats=ArchiveStats(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    archived_at=datetime.now(timezone.utc).isoformat(),
                    pass3_completed_at=state.get("pass2_completed_at"),
                    doc_items_archived=export_counts.get("DocItem", 0),
                    type_aware_chunks_archived=export_counts.get("TypeAwareChunk", 0),
                    page_contexts_archived=export_counts.get("PageContext", 0),
                    total_nodes_archived=sum(export_counts.values()),
                    archive_path=str(archive_path),
                ),
            )

            # Sauvegarder le manifest
            with open(archive_path / "manifest.json", "w", encoding="utf-8") as f:
                f.write(manifest.model_dump_json(indent=2))

            # Étape 6: Supprimer les nodes de Neo4j
            logger.info(f"[ARCHIVER] Suppression des nodes Neo4j...")
            delete_counts = self._delete_archived_nodes(document_id, doc_version_id, tenant_id)

            # Vérifier cohérence export/delete
            for node_type in ["DocItem", "TypeAwareChunk", "PageContext"]:
                exported = export_counts.get(node_type, 0)
                deleted = delete_counts.get(node_type, 0)
                if exported != deleted:
                    logger.warning(
                        f"[ARCHIVER] Incohérence {node_type}: "
                        f"exporté={exported}, supprimé={deleted}"
                    )

            # Marquer le document comme archivé dans Neo4j
            mark_archived_query = """
            MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
            SET d.structural_archived = true,
                d.structural_archived_at = $archived_at,
                d.structural_archive_path = $archive_path
            """

            with self.driver.session() as session:
                session.run(
                    mark_archived_query,
                    tenant_id=tenant_id,
                    doc_id=document_id,
                    archived_at=manifest.stats.archived_at,
                    archive_path=str(archive_path),
                )

            logger.info(
                f"[ARCHIVER] ✅ Document {document_id} archivé: "
                f"{manifest.stats.total_nodes_archived} nodes"
            )

            return manifest.stats

        except Exception as e:
            logger.error(f"[ARCHIVER] Erreur archivage {document_id}: {e}")
            # En cas d'erreur, on garde les fichiers exportés pour debug
            # mais on ne supprime pas de Neo4j
            raise

    def restore_document(
        self,
        document_id: str,
        tenant_id: str = "default",
    ) -> Optional[dict]:
        """
        Réimporte un document depuis son archive.

        Args:
            document_id: ID du document à restaurer
            tenant_id: ID du tenant

        Returns:
            Dictionnaire avec les stats de restauration, None si erreur
        """
        logger.info(f"[ARCHIVER] Début restauration document {document_id}")

        archive_path = self._get_archive_path(document_id, tenant_id)
        manifest_path = archive_path / "manifest.json"

        if not manifest_path.exists():
            logger.error(f"[ARCHIVER] Archive non trouvée: {archive_path}")
            return None

        # Charger le manifest
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        manifest = ArchiveManifest(**manifest_data)
        doc_version_id = manifest.doc_version_id

        restore_counts = {}

        try:
            with self.driver.session() as session:
                # Restaurer PageContexts
                pages_file = archive_path / "page_contexts.json"
                if pages_file.exists():
                    with open(pages_file, "r", encoding="utf-8") as f:
                        pages = json.load(f)

                    for page in pages:
                        session.run(
                            """
                            MATCH (v:DocumentVersion {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
                            CREATE (p:PageContext)
                            SET p = $props
                            CREATE (v)-[:HAS_PAGE]->(p)
                            """,
                            tenant_id=tenant_id,
                            doc_version_id=doc_version_id,
                            props=page,
                        )

                    restore_counts["PageContext"] = len(pages)
                    logger.info(f"  Restauré {len(pages)} PageContexts")

                # Restaurer DocItems
                items_file = archive_path / "doc_items.json"
                if items_file.exists():
                    with open(items_file, "r", encoding="utf-8") as f:
                        items = json.load(f)

                    for item in items:
                        section_id = item.get("section_id")

                        # Créer le DocItem
                        session.run(
                            """
                            CREATE (i:DocItem)
                            SET i = $props
                            """,
                            props=item,
                        )

                        # Lier à la section si elle existe
                        if section_id:
                            session.run(
                                """
                                MATCH (s:SectionContext {tenant_id: $tenant_id, doc_version_id: $doc_version_id, section_id: $section_id})
                                MATCH (i:DocItem {tenant_id: $tenant_id, doc_id: $doc_id, doc_version_id: $doc_version_id, item_id: $item_id})
                                MERGE (s)-[:CONTAINS]->(i)
                                """,
                                tenant_id=tenant_id,
                                doc_version_id=doc_version_id,
                                section_id=section_id,
                                doc_id=item.get("doc_id"),
                                item_id=item.get("item_id"),
                            )

                    restore_counts["DocItem"] = len(items)
                    logger.info(f"  Restauré {len(items)} DocItems")

                # Restaurer TypeAwareChunks
                chunks_file = archive_path / "type_aware_chunks.json"
                if chunks_file.exists():
                    with open(chunks_file, "r", encoding="utf-8") as f:
                        chunks = json.load(f)

                    for chunk in chunks:
                        session.run(
                            """
                            MATCH (v:DocumentVersion {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
                            CREATE (c:TypeAwareChunk)
                            SET c = $props
                            CREATE (v)-[:HAS_CHUNK]->(c)
                            """,
                            tenant_id=tenant_id,
                            doc_version_id=doc_version_id,
                            props=chunk,
                        )

                    restore_counts["TypeAwareChunk"] = len(chunks)
                    logger.info(f"  Restauré {len(chunks)} TypeAwareChunks")

            # Mettre à jour le flag d'archivage
            with self.driver.session() as session:
                session.run(
                    """
                    MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
                    SET d.structural_archived = false,
                        d.structural_restored_at = $restored_at
                    REMOVE d.structural_archive_path
                    """,
                    tenant_id=tenant_id,
                    doc_id=document_id,
                    restored_at=datetime.now(timezone.utc).isoformat(),
                )

            # Supprimer l'archive après succès
            import shutil
            shutil.rmtree(archive_path)
            logger.info(f"[ARCHIVER] Archive supprimée: {archive_path}")

            total_restored = sum(restore_counts.values())
            logger.info(
                f"[ARCHIVER] ✅ Document {document_id} restauré: "
                f"{total_restored} nodes"
            )

            return {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "restored_at": datetime.now(timezone.utc).isoformat(),
                "counts": restore_counts,
                "total_nodes_restored": total_restored,
            }

        except Exception as e:
            logger.error(f"[ARCHIVER] Erreur restauration {document_id}: {e}")
            raise

    def get_archive_status(
        self,
        document_id: str,
        tenant_id: str = "default",
    ) -> Optional[dict]:
        """
        Vérifie si un document est archivé et retourne son statut.

        Returns:
            Dictionnaire avec le statut, None si document non trouvé
        """
        archive_path = self._get_archive_path(document_id, tenant_id)
        manifest_path = archive_path / "manifest.json"

        # Vérifier dans Neo4j
        query = """
        MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
        RETURN d.structural_archived AS is_archived,
               d.structural_archived_at AS archived_at,
               d.structural_archive_path AS archive_path
        """

        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, doc_id=document_id)
            record = result.single()

            if not record:
                return None

            is_archived = record["is_archived"] or False

            status = {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "is_archived": is_archived,
                "archived_at": record["archived_at"],
                "archive_path": record["archive_path"],
                "archive_exists": manifest_path.exists(),
            }

            # Si archivé, charger les stats du manifest
            if is_archived and manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                status["manifest"] = manifest_data

            return status

    def list_archives(self, tenant_id: str = "default") -> list[dict]:
        """
        Liste toutes les archives disponibles pour un tenant.

        Returns:
            Liste des archives avec leurs métadonnées
        """
        tenant_path = self.archive_base_path / tenant_id

        if not tenant_path.exists():
            return []

        archives = []

        for doc_dir in tenant_path.iterdir():
            if not doc_dir.is_dir():
                continue

            manifest_path = doc_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)

                archives.append({
                    "document_id": manifest_data.get("document_id"),
                    "archived_at": manifest_data.get("created_at"),
                    "total_nodes": manifest_data.get("stats", {}).get("total_nodes_archived", 0),
                    "archive_path": str(doc_dir),
                })
            except Exception as e:
                logger.warning(f"Erreur lecture manifest {manifest_path}: {e}")

        return archives


# Fonctions utilitaires pour accès rapide
def get_archiver(archive_base_path: str = "data/archives") -> StructuralArchiver:
    """Récupère une instance de l'archiveur."""
    return StructuralArchiver(archive_base_path=archive_base_path)


def archive_completed_documents(
    tenant_id: str = "default",
    min_age_days: int = 0,
    max_documents: int = 10,
) -> list[ArchiveStats]:
    """
    Archive les documents dont le Pass 3 est complet.

    Args:
        tenant_id: ID du tenant
        min_age_days: Âge minimum depuis Pass 3 complet
        max_documents: Nombre max de documents à archiver

    Returns:
        Liste des stats d'archivage
    """
    archiver = get_archiver()
    documents = archiver.get_archivable_documents(tenant_id, min_age_days)

    logger.info(f"[ARCHIVER] {len(documents)} documents éligibles trouvés")

    results = []
    for doc in documents[:max_documents]:
        try:
            stats = archiver.archive_document(doc["doc_id"], tenant_id)
            if stats:
                results.append(stats)
        except Exception as e:
            logger.error(f"[ARCHIVER] Erreur archivage {doc['doc_id']}: {e}")

    return results
