"""
OSMOSE Artifact Importer - Import chunks et embeddings depuis artefacts S3

Importe les artefacts générés par le mode burst EC2 :
- chunks.jsonl.gz : Chunks avec métadonnées
- embeddings.npy : Matrice numpy des embeddings
- manifest.json : Métadonnées de l'export

Destinations :
- Qdrant : Vecteurs + payloads pour recherche sémantique
- Neo4j : Création documents nodes (optionnel)

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import json
import gzip
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from knowbase.common.clients.qdrant_client import (
    get_qdrant_client,
    ensure_qdrant_collection,
    upsert_chunks,
)

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Résultat d'un import d'artefacts."""

    artifact_id: str
    document_id: str
    document_name: str
    tenant_id: str

    # Stats import
    chunks_imported: int
    qdrant_success: bool
    neo4j_success: bool

    # Timing
    import_timestamp: str
    duration_seconds: float

    # Erreurs éventuelles
    errors: List[str]


class ArtifactImporter:
    """
    Importe les artefacts burst vers Qdrant/Neo4j.

    Usage:
        importer = ArtifactImporter()
        result = importer.import_artifact(
            artifact_dir="/tmp/artifacts/doc-123_abc12345_20251227_120000",
            collection_name="knowbase"
        )
    """

    def __init__(
        self,
        validate_checksums: bool = True,
        batch_size: int = 500
    ):
        """
        Initialise l'importeur.

        Args:
            validate_checksums: Valider les checksums avant import
            batch_size: Taille des batchs Qdrant
        """
        self.validate_checksums = validate_checksums
        self.batch_size = batch_size

        logger.info("[ARTIFACT IMPORTER] Initialized")

    def import_artifact(
        self,
        artifact_dir: Path,
        collection_name: str = "knowbase",
        tenant_id: Optional[str] = None,
        create_neo4j_document: bool = False
    ) -> ImportResult:
        """
        Importe un artefact complet vers Qdrant.

        Args:
            artifact_dir: Répertoire contenant les artefacts
            collection_name: Collection Qdrant cible
            tenant_id: Override tenant_id (sinon utilise celui du manifest)
            create_neo4j_document: Créer node Document dans Neo4j

        Returns:
            ImportResult avec statistiques
        """
        start_time = datetime.now(timezone.utc)
        errors = []
        artifact_dir = Path(artifact_dir)

        # 1. Charger manifest
        manifest_file = artifact_dir / "manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_file}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        artifact_id = manifest["artifact_id"]
        document_id = manifest["document_id"]
        document_name = manifest["document_name"]
        effective_tenant_id = tenant_id or manifest["tenant_id"]

        logger.info(f"[ARTIFACT IMPORTER] Loading artifact: {artifact_id}")
        logger.info(f"   - Document: {document_name} ({document_id})")
        logger.info(f"   - Tenant: {effective_tenant_id}")
        logger.info(f"   - Expected chunks: {manifest['chunk_count']}")

        # 2. Charger chunks
        chunks_file = artifact_dir / manifest["chunks_file"]
        try:
            chunks = self._load_chunks(chunks_file)
            logger.info(f"   - Loaded {len(chunks)} chunks")
        except Exception as e:
            errors.append(f"Failed to load chunks: {e}")
            raise

        # 3. Charger embeddings
        embeddings_file = artifact_dir / manifest["embeddings_file"]
        try:
            embeddings = self._load_embeddings(embeddings_file)
            logger.info(f"   - Loaded embeddings: {embeddings.shape}")
        except Exception as e:
            errors.append(f"Failed to load embeddings: {e}")
            raise

        # 4. Valider checksums si demandé
        if self.validate_checksums:
            try:
                self._validate_checksums(
                    chunks, embeddings,
                    manifest["chunks_checksum"],
                    manifest["embeddings_checksum"]
                )
                logger.info("   - Checksums validated ✓")
            except ValueError as e:
                errors.append(f"Checksum validation failed: {e}")
                raise

        # 5. Valider dimensions
        if len(chunks) != embeddings.shape[0]:
            raise ValueError(
                f"Mismatch: {len(chunks)} chunks vs {embeddings.shape[0]} embeddings"
            )

        # 6. Préparer données pour Qdrant
        qdrant_chunks = self._prepare_qdrant_chunks(
            chunks, embeddings, effective_tenant_id
        )

        # 7. Upsert vers Qdrant
        qdrant_success = False
        try:
            ensure_qdrant_collection(
                collection_name=collection_name,
                vector_size=manifest["embedding_dimension"]
            )

            chunk_ids = upsert_chunks(
                chunks=qdrant_chunks,
                collection_name=collection_name,
                tenant_id=effective_tenant_id
            )

            qdrant_success = len(chunk_ids) == len(chunks)
            logger.info(f"[ARTIFACT IMPORTER] ✅ Qdrant: {len(chunk_ids)} chunks upserted")

        except Exception as e:
            errors.append(f"Qdrant upsert failed: {e}")
            logger.error(f"[ARTIFACT IMPORTER] ❌ Qdrant error: {e}")

        # 8. Créer node Neo4j (optionnel)
        neo4j_success = True
        if create_neo4j_document:
            try:
                self._create_neo4j_document(
                    document_id=document_id,
                    document_name=document_name,
                    tenant_id=effective_tenant_id,
                    chunk_count=len(chunks),
                    metadata=manifest.get("extra_metadata", {})
                )
                logger.info("[ARTIFACT IMPORTER] ✅ Neo4j: Document node created")
            except Exception as e:
                neo4j_success = False
                errors.append(f"Neo4j document creation failed: {e}")
                logger.error(f"[ARTIFACT IMPORTER] ❌ Neo4j error: {e}")

        # 9. Calculer durée
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        result = ImportResult(
            artifact_id=artifact_id,
            document_id=document_id,
            document_name=document_name,
            tenant_id=effective_tenant_id,
            chunks_imported=len(chunks) if qdrant_success else 0,
            qdrant_success=qdrant_success,
            neo4j_success=neo4j_success,
            import_timestamp=end_time.isoformat(),
            duration_seconds=round(duration, 2),
            errors=errors
        )

        logger.info(
            f"[ARTIFACT IMPORTER] Import complete: {artifact_id} "
            f"({result.chunks_imported} chunks in {duration:.2f}s)"
        )

        return result

    def _load_chunks(self, chunks_file: Path) -> List[Dict[str, Any]]:
        """Charge chunks depuis JSONL (compressé ou non)."""

        chunks = []

        if str(chunks_file).endswith(".gz"):
            with gzip.open(chunks_file, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        chunks.append(json.loads(line))
        else:
            with open(chunks_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        chunks.append(json.loads(line))

        return chunks

    def _load_embeddings(self, embeddings_file: Path) -> np.ndarray:
        """Charge embeddings depuis fichier NumPy."""
        return np.load(embeddings_file)

    def _validate_checksums(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        expected_chunks_checksum: str,
        expected_embeddings_checksum: str
    ) -> None:
        """Valide les checksums des données."""

        # Reconstruire contenu chunks pour checksum
        content = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)
        actual_chunks_checksum = hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()[:16]

        if actual_chunks_checksum != expected_chunks_checksum:
            raise ValueError(
                f"Chunks checksum mismatch: {actual_chunks_checksum} vs {expected_chunks_checksum}"
            )

        # Checksum embeddings
        actual_embeddings_checksum = hashlib.sha256(
            embeddings.tobytes()
        ).hexdigest()[:16]

        if actual_embeddings_checksum != expected_embeddings_checksum:
            raise ValueError(
                f"Embeddings checksum mismatch: {actual_embeddings_checksum} vs {expected_embeddings_checksum}"
            )

    def _prepare_qdrant_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Prépare les chunks au format attendu par upsert_chunks."""

        qdrant_chunks = []

        for i, chunk in enumerate(chunks):
            embedding = embeddings[i].tolist()

            qdrant_chunk = {
                "id": chunk["chunk_id"],
                "text": chunk["text"],
                "embedding": embedding,
                "document_id": chunk["document_id"],
                "document_name": chunk["document_name"],
                "segment_id": chunk.get("segment_id", ""),
                "chunk_index": chunk.get("chunk_index", i),
                "proto_concept_ids": chunk.get("concepts", []),
                "canonical_concept_ids": [],
                "tenant_id": tenant_id,
                "char_start": chunk.get("metadata", {}).get("char_start", 0),
                "char_end": chunk.get("metadata", {}).get("char_end", 0),
                # Métadonnées additionnelles
                "slide_index": chunk.get("slide_index"),
                "vision_decision": chunk.get("vision_decision"),
            }

            qdrant_chunks.append(qdrant_chunk)

        return qdrant_chunks

    def _create_neo4j_document(
        self,
        document_id: str,
        document_name: str,
        tenant_id: str,
        chunk_count: int,
        metadata: Dict[str, Any]
    ) -> None:
        """Crée un node Document dans Neo4j."""

        from neo4j import GraphDatabase
        import os

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        query = """
        MERGE (d:Document {id: $document_id, tenant_id: $tenant_id})
        SET d.name = $document_name,
            d.chunk_count = $chunk_count,
            d.imported_at = datetime(),
            d.source = 'burst_import'
        RETURN d.id AS id
        """

        with driver.session() as session:
            result = session.run(
                query,
                document_id=document_id,
                document_name=document_name,
                tenant_id=tenant_id,
                chunk_count=chunk_count
            )
            record = result.single()

        driver.close()

        logger.debug(f"[ARTIFACT IMPORTER] Created Document node: {record['id']}")


def import_artifacts_to_qdrant(
    artifact_dir: Path,
    collection_name: str = "knowbase",
    tenant_id: Optional[str] = None,
    **kwargs
) -> ImportResult:
    """
    Fonction utilitaire pour importer artefacts vers Qdrant.

    Args:
        artifact_dir: Répertoire des artefacts
        collection_name: Collection cible
        tenant_id: Override tenant
        **kwargs: Arguments additionnels pour ArtifactImporter

    Returns:
        ImportResult
    """
    importer = ArtifactImporter(**kwargs)
    return importer.import_artifact(
        artifact_dir=artifact_dir,
        collection_name=collection_name,
        tenant_id=tenant_id,
        create_neo4j_document=False
    )


def import_artifacts_to_neo4j(
    artifact_dir: Path,
    collection_name: str = "knowbase",
    tenant_id: Optional[str] = None,
    **kwargs
) -> ImportResult:
    """
    Fonction utilitaire pour importer artefacts vers Qdrant + Neo4j.

    Args:
        artifact_dir: Répertoire des artefacts
        collection_name: Collection cible
        tenant_id: Override tenant
        **kwargs: Arguments additionnels pour ArtifactImporter

    Returns:
        ImportResult
    """
    importer = ArtifactImporter(**kwargs)
    return importer.import_artifact(
        artifact_dir=artifact_dir,
        collection_name=collection_name,
        tenant_id=tenant_id,
        create_neo4j_document=True
    )


def import_all_artifacts(
    artifacts_root: Path,
    collection_name: str = "knowbase",
    tenant_id: Optional[str] = None,
    create_neo4j_documents: bool = False,
    **kwargs
) -> List[ImportResult]:
    """
    Importe tous les artefacts d'un répertoire racine.

    Parcourt tous les sous-répertoires contenant un manifest.json.

    Args:
        artifacts_root: Répertoire racine (ex: /data/artifacts)
        collection_name: Collection Qdrant cible
        tenant_id: Override tenant_id
        create_neo4j_documents: Créer nodes Document
        **kwargs: Arguments pour ArtifactImporter

    Returns:
        Liste ImportResult pour chaque artefact
    """
    artifacts_root = Path(artifacts_root)
    results = []

    # Trouver tous les répertoires avec manifest.json
    manifest_files = list(artifacts_root.glob("*/manifest.json"))

    logger.info(f"[ARTIFACT IMPORTER] Found {len(manifest_files)} artifacts to import")

    importer = ArtifactImporter(**kwargs)

    for manifest_file in manifest_files:
        artifact_dir = manifest_file.parent

        try:
            result = importer.import_artifact(
                artifact_dir=artifact_dir,
                collection_name=collection_name,
                tenant_id=tenant_id,
                create_neo4j_document=create_neo4j_documents
            )
            results.append(result)

        except Exception as e:
            logger.error(f"[ARTIFACT IMPORTER] Failed to import {artifact_dir.name}: {e}")
            # Créer résultat d'erreur
            results.append(ImportResult(
                artifact_id=artifact_dir.name,
                document_id="",
                document_name="",
                tenant_id=tenant_id or "unknown",
                chunks_imported=0,
                qdrant_success=False,
                neo4j_success=False,
                import_timestamp=datetime.now(timezone.utc).isoformat(),
                duration_seconds=0.0,
                errors=[str(e)]
            ))

    # Stats finales
    success_count = sum(1 for r in results if r.qdrant_success)
    total_chunks = sum(r.chunks_imported for r in results)

    logger.info(
        f"[ARTIFACT IMPORTER] Import complete: {success_count}/{len(results)} artifacts, "
        f"{total_chunks} total chunks"
    )

    return results
