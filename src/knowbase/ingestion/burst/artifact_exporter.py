"""
OSMOSE Artifact Exporter - Export chunks et embeddings pour mode burst

Génère des artefacts portables pour transfert via S3 :
- chunks.jsonl : Chunks avec métadonnées (sans embeddings)
- embeddings.npy : Matrice numpy des embeddings
- manifest.json : Métadonnées de l'export

Format conçu pour :
- Découpler extraction (EC2) et stockage (local)
- Permettre reprise en cas d'interruption
- Minimiser la taille de transfert

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import json
import gzip
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ExportedArtifact:
    """Métadonnées d'un artefact exporté."""

    artifact_id: str  # UUID unique de l'export
    document_id: str  # ID document source
    document_name: str  # Nom fichier original
    tenant_id: str

    # Fichiers générés
    chunks_file: str  # chunks.jsonl.gz
    embeddings_file: str  # embeddings.npy
    manifest_file: str  # manifest.json

    # Stats
    chunk_count: int
    embedding_dimension: int
    total_tokens: int
    export_timestamp: str

    # Checksums pour validation
    chunks_checksum: str
    embeddings_checksum: str


@dataclass
class ChunkRecord:
    """
    Format d'un chunk dans chunks.jsonl.

    Compatible avec le format Qdrant attendu.
    """
    chunk_id: str  # UUID du chunk
    document_id: str
    document_name: str
    tenant_id: str

    # Contenu
    text: str  # Texte du chunk

    # Position
    slide_index: Optional[int] = None
    segment_id: Optional[str] = None
    chunk_index: int = 0

    # Métadonnées
    vision_decision: Optional[str] = None  # "required", "optional", "skip"
    concepts: List[str] = None  # IDs des concepts associés

    # Payload additionnel pour Qdrant
    metadata: Dict[str, Any] = None


class ArtifactExporter:
    """
    Exporte les résultats d'ingestion en artefacts portables.

    Usage:
        exporter = ArtifactExporter(output_dir="/tmp/artifacts")
        artifact = exporter.export(
            document_id="doc-123",
            document_name="presentation.pptx",
            chunks=chunks_list,
            embeddings=embeddings_array,
            tenant_id="default"
        )
        # Résultat : chunks.jsonl.gz, embeddings.npy, manifest.json
    """

    def __init__(
        self,
        output_dir: Path,
        compress_chunks: bool = True,
        embedding_precision: str = "float32"
    ):
        """
        Initialise l'exporteur.

        Args:
            output_dir: Répertoire de sortie pour les artefacts
            compress_chunks: Compresser chunks.jsonl avec gzip
            embedding_precision: Précision numpy (float32 ou float16)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.compress_chunks = compress_chunks
        self.embedding_dtype = np.float32 if embedding_precision == "float32" else np.float16

        logger.info(f"[ARTIFACT EXPORTER] Initialized (output: {output_dir})")

    def export(
        self,
        document_id: str,
        document_name: str,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        tenant_id: str = "default",
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> ExportedArtifact:
        """
        Exporte chunks et embeddings en artefacts.

        Args:
            document_id: ID unique du document
            document_name: Nom du fichier original
            chunks: Liste de chunks (dicts avec text, metadata, etc.)
            embeddings: Matrice numpy (n_chunks, embedding_dim)
            tenant_id: ID du tenant
            extra_metadata: Métadonnées additionnelles pour manifest

        Returns:
            ExportedArtifact avec chemins et stats
        """
        # Générer ID unique pour cet export
        artifact_id = self._generate_artifact_id(document_id, document_name)

        # Créer sous-répertoire pour ce document
        artifact_dir = self.output_dir / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Valider dimensions
        if len(chunks) != embeddings.shape[0]:
            raise ValueError(
                f"Mismatch: {len(chunks)} chunks vs {embeddings.shape[0]} embeddings"
            )

        embedding_dim = embeddings.shape[1] if len(embeddings.shape) > 1 else 0

        # 1. Exporter chunks (JSONL, optionnellement compressé)
        chunks_file, chunks_checksum = self._export_chunks(
            artifact_dir, chunks, document_id, document_name, tenant_id
        )

        # 2. Exporter embeddings (NumPy binary)
        embeddings_file, embeddings_checksum = self._export_embeddings(
            artifact_dir, embeddings
        )

        # 3. Calculer stats
        total_tokens = sum(
            len(c.get("text", "").split()) for c in chunks
        )

        # 4. Créer manifest
        artifact = ExportedArtifact(
            artifact_id=artifact_id,
            document_id=document_id,
            document_name=document_name,
            tenant_id=tenant_id,
            chunks_file=str(chunks_file.name),
            embeddings_file=str(embeddings_file.name),
            manifest_file="manifest.json",
            chunk_count=len(chunks),
            embedding_dimension=embedding_dim,
            total_tokens=total_tokens,
            export_timestamp=datetime.now(timezone.utc).isoformat(),
            chunks_checksum=chunks_checksum,
            embeddings_checksum=embeddings_checksum,
        )

        # 5. Écrire manifest
        manifest_file = artifact_dir / "manifest.json"
        manifest_data = asdict(artifact)
        if extra_metadata:
            manifest_data["extra_metadata"] = extra_metadata

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        logger.info(
            f"[ARTIFACT EXPORTER] ✅ Export complete: {artifact_id}"
        )
        logger.info(f"   - Chunks: {len(chunks)} ({chunks_file.name})")
        logger.info(f"   - Embeddings: {embeddings.shape} ({embeddings_file.name})")
        logger.info(f"   - Directory: {artifact_dir}")

        return artifact

    def _export_chunks(
        self,
        artifact_dir: Path,
        chunks: List[Dict[str, Any]],
        document_id: str,
        document_name: str,
        tenant_id: str
    ) -> tuple:
        """Exporte chunks en JSONL (optionnellement compressé)."""

        filename = "chunks.jsonl.gz" if self.compress_chunks else "chunks.jsonl"
        filepath = artifact_dir / filename

        # Préparer records
        records = []
        for i, chunk in enumerate(chunks):
            record = ChunkRecord(
                chunk_id=chunk.get("id", f"{document_id}_chunk_{i}"),
                document_id=document_id,
                document_name=document_name,
                tenant_id=tenant_id,
                text=chunk.get("text", chunk.get("full_explanation", "")),
                slide_index=chunk.get("slide_index"),
                segment_id=chunk.get("segment_id"),
                chunk_index=i,
                vision_decision=chunk.get("vision_decision"),
                concepts=chunk.get("concepts", []),
                metadata=chunk.get("metadata", chunk.get("meta", {})),
            )
            records.append(asdict(record))

        # Écrire JSONL
        content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        content_bytes = content.encode("utf-8")

        if self.compress_chunks:
            with gzip.open(filepath, "wt", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        # Checksum
        checksum = hashlib.sha256(content_bytes).hexdigest()[:16]

        return filepath, checksum

    def _export_embeddings(
        self,
        artifact_dir: Path,
        embeddings: np.ndarray
    ) -> tuple:
        """Exporte embeddings en format NumPy binaire."""

        filepath = artifact_dir / "embeddings.npy"

        # Convertir en précision cible
        embeddings_typed = embeddings.astype(self.embedding_dtype)

        # Sauvegarder
        np.save(filepath, embeddings_typed)

        # Checksum sur les données brutes
        checksum = hashlib.sha256(embeddings_typed.tobytes()).hexdigest()[:16]

        return filepath, checksum

    def _generate_artifact_id(self, document_id: str, document_name: str) -> str:
        """Génère un ID unique pour l'artefact."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name_hash = hashlib.sha256(document_name.encode()).hexdigest()[:8]
        return f"{document_id}_{name_hash}_{timestamp}"


def export_ingestion_artifacts(
    output_dir: Path,
    document_id: str,
    document_name: str,
    chunks: List[Dict[str, Any]],
    embeddings: np.ndarray,
    tenant_id: str = "default",
    **kwargs
) -> ExportedArtifact:
    """
    Fonction utilitaire pour exporter des artefacts d'ingestion.

    Args:
        output_dir: Répertoire de sortie
        document_id: ID du document
        document_name: Nom du fichier
        chunks: Liste des chunks
        embeddings: Matrice des embeddings
        tenant_id: ID tenant
        **kwargs: Arguments additionnels pour ArtifactExporter

    Returns:
        ExportedArtifact
    """
    exporter = ArtifactExporter(output_dir, **kwargs)
    return exporter.export(
        document_id=document_id,
        document_name=document_name,
        chunks=chunks,
        embeddings=embeddings,
        tenant_id=tenant_id,
    )
