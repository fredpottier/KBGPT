"""
Module de versioning des features canonicalization pour reproductibilité
Trace algorithme, embeddings, poids utilisés pour garantir résultats identiques
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel


class CanonicalizationVersion(BaseModel):
    """
    Version complète features canonicalization

    Permet reproduction exacte résultats merge/create en traçant:
    - Version algorithme canonicalization
    - Modèle embeddings utilisé
    - Poids/seuils de similarité
    - Configuration LLM si extraction auto
    """

    algorithm_version: str
    """Version algorithme canonicalization (ex: 'v1.0.0')"""

    embedding_model: str
    """Modèle embeddings (ex: 'text-embedding-3-small')"""

    embedding_dimensions: int
    """Dimensions vecteurs embeddings"""

    similarity_threshold: float
    """Seuil similarité pour merge (0.0-1.0)"""

    similarity_weights: Dict[str, float]
    """Poids composantes similarité (name, description, context)"""

    llm_extraction_model: str | None = None
    """Modèle LLM pour extraction auto (ex: 'gpt-4o-mini')"""

    llm_extraction_temperature: float | None = None
    """Température LLM extraction"""

    created_at: datetime = datetime.utcnow()
    """Timestamp création version"""

    @property
    def version_hash(self) -> str:
        """
        Hash unique identifiant cette version features

        Permet détecter changements configuration affectant reproductibilité

        Returns:
            Hash SHA256 de la configuration
        """
        config_dict = {
            "algorithm_version": self.algorithm_version,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "similarity_threshold": self.similarity_threshold,
            "similarity_weights": self.similarity_weights,
            "llm_extraction_model": self.llm_extraction_model,
            "llm_extraction_temperature": self.llm_extraction_temperature,
        }

        config_json = json.dumps(config_dict, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()[:16]

    def to_audit_metadata(self) -> Dict[str, Any]:
        """
        Convertit en metadata pour audit trail

        Returns:
            Dict avec informations versioning pour logs
        """
        return {
            "canonicalization_version": self.algorithm_version,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "similarity_threshold": self.similarity_threshold,
            "version_hash": self.version_hash,
            "llm_model": self.llm_extraction_model,
        }


# Version actuelle features canonicalization
CURRENT_VERSION = CanonicalizationVersion(
    algorithm_version="v1.0.0",
    embedding_model="text-embedding-3-small",
    embedding_dimensions=1536,
    similarity_threshold=0.85,
    similarity_weights={
        "name": 0.5,
        "description": 0.3,
        "context": 0.2
    },
    llm_extraction_model="gpt-4o-mini",
    llm_extraction_temperature=0.0
)


def get_current_version() -> CanonicalizationVersion:
    """
    Retourne version actuelle features canonicalization

    Returns:
        CanonicalizationVersion configurée
    """
    return CURRENT_VERSION


def validate_version_compatibility(
    stored_version_hash: str,
    current_version: CanonicalizationVersion | None = None
) -> bool:
    """
    Vérifie compatibilité entre version stockée et actuelle

    Args:
        stored_version_hash: Hash version stockée dans résultat précédent
        current_version: Version actuelle (défaut: CURRENT_VERSION)

    Returns:
        True si versions compatibles (résultats reproductibles)
    """
    if current_version is None:
        current_version = CURRENT_VERSION

    return stored_version_hash == current_version.version_hash


def create_version_metadata(
    operation: str,
    idempotency_key: str | None = None
) -> Dict[str, Any]:
    """
    Crée metadata versioning pour opération

    Args:
        operation: Type d'opération (merge, create-new, etc.)
        idempotency_key: Clé idempotence si applicable

    Returns:
        Dict avec metadata complète versioning + operation
    """
    version = get_current_version()

    metadata = {
        **version.to_audit_metadata(),
        "operation": operation,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key

    return metadata
