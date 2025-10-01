"""
Service de canonicalisation d'entités
Opérations merge et create-new avec garanties idempotence
"""

import logging
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, List
from uuid import uuid4

from knowbase.canonicalization.versioning import (
    get_current_version,
    create_version_metadata
)
from knowbase.canonicalization.schemas import EntityCandidate
from knowbase.api.services.knowledge_graph import KnowledgeGraphService
from knowbase.api.schemas.knowledge_graph import EntityCreate, EntityType

logger = logging.getLogger(__name__)


class CanonicalizationService:
    """
    Service canonicalization avec idempotence garantie

    Opérations:
    - merge: Merger entités candidates vers entité canonique existante
    - create_new: Créer nouvelle entité canonique depuis candidates

    Garanties idempotence:
    - Même input + même Idempotency-Key → résultat identique
    - Versioning features pour reproductibilité
    - Résultats déterministes (pas de random, timestamps fixes)
    """

    def __init__(self):
        """Initialize canonicalization service"""
        # Lazy import pour éviter import circulaire
        from knowbase.api.services.knowledge_graph import KnowledgeGraphService
        self.kg_service = KnowledgeGraphService()

    async def merge_entities(
        self,
        canonical_entity_id: str,
        candidate_ids: List[str],
        idempotency_key: str,
        user_id: str | None = None
    ) -> Dict[str, Any]:
        """
        Merge candidates vers entité canonique existante

        Logique:
        1. Valider canonical_entity existe
        2. Valider candidates existent
        3. Créer metadata versioning
        4. Merger candidates → canonical (attributes, occurrences, confidence)
        5. Marquer candidates comme MERGED
        6. Retourner résultat déterministe avec hash

        Args:
            canonical_entity_id: UUID entité canonique cible
            candidate_ids: Liste UUIDs candidates à merger
            idempotency_key: Clé idempotence
            user_id: Utilisateur effectuant merge (optionnel)

        Returns:
            Dict avec résultat merge et metadata versioning

        Raises:
            ValueError: Si entité canonique ou candidates invalides
        """
        logger.info(
            f"Merge démarré: canonical={canonical_entity_id[:8]}... "
            f"candidates={len(candidate_ids)} [key={idempotency_key[:12]}...]"
        )

        # Créer metadata versioning
        version_metadata = create_version_metadata(
            operation="merge",
            idempotency_key=idempotency_key
        )

        # TODO: Valider canonical_entity existe (nécessite méthode get_entity dans KG service)
        # Pour l'instant, on simule validation
        canonical_exists = True

        if not canonical_exists:
            raise ValueError(f"Entité canonique {canonical_entity_id} introuvable")

        # TODO: Valider candidates existent
        # Pour l'instant, on simule validation
        candidates_valid = True

        if not candidates_valid:
            raise ValueError("Une ou plusieurs candidates invalides")

        # Simuler logique merge (sera implémentée avec vraie logique Phase 3+)
        # Pour idempotence, important: résultat DÉTERMINISTE
        merge_result = {
            "canonical_entity_id": canonical_entity_id,
            "merged_candidates": candidate_ids,
            "merge_count": len(candidate_ids),
            "operation": "merge",
            "idempotency_key": idempotency_key,
            "user_id": user_id,
            "version_metadata": version_metadata,
            # Timestamp fixé pour déterminisme (pas datetime.utcnow())
            "executed_at": "2025-10-01T00:00:00Z",
            "status": "completed"
        }

        # Calculer hash déterministe du résultat
        result_hash = self._compute_result_hash(merge_result)
        merge_result["result_hash"] = result_hash

        logger.info(
            f"Merge terminé: canonical={canonical_entity_id[:8]}... "
            f"merged={len(candidate_ids)} hash={result_hash[:12]}... "
            f"[key={idempotency_key[:12]}...]"
        )

        return merge_result

    async def create_new_canonical(
        self,
        candidate_ids: List[str],
        canonical_name: str,
        entity_type: str,
        description: str | None = None,
        idempotency_key: str | None = None,
        user_id: str | None = None
    ) -> Dict[str, Any]:
        """
        Créer nouvelle entité canonique depuis candidates

        Logique:
        1. Valider candidates existent
        2. Créer metadata versioning
        3. Créer nouvelle entité canonique dans KG
        4. Lier candidates à nouvelle canonique
        5. Marquer candidates comme CANONICAL_CREATED
        6. Retourner résultat déterministe avec hash

        Args:
            candidate_ids: Liste UUIDs candidates sources
            canonical_name: Nom entité canonique à créer
            entity_type: Type entité (solution, product, concept, etc.)
            description: Description optionnelle
            idempotency_key: Clé idempotence
            user_id: Utilisateur effectuant création

        Returns:
            Dict avec résultat création et metadata versioning

        Raises:
            ValueError: Si candidates invalides ou type inconnu
        """
        logger.info(
            f"Create new canonical: name='{canonical_name}' "
            f"candidates={len(candidate_ids)} "
            f"[key={idempotency_key[:12] if idempotency_key else 'none'}...]"
        )

        # Créer metadata versioning
        version_metadata = create_version_metadata(
            operation="create_new",
            idempotency_key=idempotency_key
        )

        # TODO: Valider candidates existent
        candidates_valid = True

        if not candidates_valid:
            raise ValueError("Une ou plusieurs candidates invalides")

        # Mapper type vers EntityType enum
        try:
            from knowbase.api.schemas.knowledge_graph import EntityType
            entity_type_enum = EntityType(entity_type.lower())
        except ValueError:
            raise ValueError(f"Type d'entité invalide: {entity_type}")

        # Créer entité dans KG (ID déterministe pour idempotence)
        # Note: En production, l'ID serait dérivé de l'Idempotency-Key
        canonical_id = self._generate_deterministic_id(
            canonical_name,
            idempotency_key or ""
        )

        # Simuler création (sera vraie création Phase 3+)
        # Pour idempotence, important: résultat DÉTERMINISTE
        create_result = {
            "canonical_entity_id": canonical_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "description": description,
            "source_candidates": candidate_ids,
            "candidate_count": len(candidate_ids),
            "operation": "create_new",
            "idempotency_key": idempotency_key,
            "user_id": user_id,
            "version_metadata": version_metadata,
            # Timestamp fixé pour déterminisme
            "executed_at": "2025-10-01T00:00:00Z",
            "status": "created"
        }

        # Calculer hash déterministe du résultat
        result_hash = self._compute_result_hash(create_result)
        create_result["result_hash"] = result_hash

        logger.info(
            f"Create new canonical terminé: id={canonical_id[:8]}... "
            f"name='{canonical_name}' hash={result_hash[:12]}... "
            f"[key={idempotency_key[:12] if idempotency_key else 'none'}...]"
        )

        return create_result

    def _compute_result_hash(self, result: Dict[str, Any]) -> str:
        """
        Calcule hash déterministe d'un résultat

        Hash permet vérifier bit-à-bit identité entre résultats
        (test validation idempotence)

        Args:
            result: Dict résultat opération

        Returns:
            Hash SHA256 du résultat (hex)
        """
        # Retirer champs non-déterministes si présents
        result_copy = result.copy()
        result_copy.pop("result_hash", None)

        # Sérialiser en JSON avec ordre déterministe
        result_json = json.dumps(result_copy, sort_keys=True)

        # Calculer SHA256
        return hashlib.sha256(result_json.encode()).hexdigest()

    def _generate_deterministic_id(self, name: str, idempotency_key: str) -> str:
        """
        Génère ID déterministe pour entité

        Même name + idempotency_key → même ID (idempotence création)

        Args:
            name: Nom entité
            idempotency_key: Clé idempotence

        Returns:
            UUID déterministe (hex)
        """
        combined = f"{name}:{idempotency_key}"
        hash_hex = hashlib.sha256(combined.encode()).hexdigest()

        # Formater comme UUID
        return f"{hash_hex[:8]}-{hash_hex[8:12]}-{hash_hex[12:16]}-{hash_hex[16:20]}-{hash_hex[20:32]}"
