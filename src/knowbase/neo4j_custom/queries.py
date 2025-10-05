"""
Neo4j Queries - Helpers pour requêtes courantes Facts

Fonctions helper pour:
- CRUD Facts
- Détection conflits
- Timeline
- Statistiques
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from .client import Neo4jCustomClient
from . import schemas

logger = logging.getLogger(__name__)


class FactsQueries:
    """Helper class pour requêtes Facts Neo4j."""

    def __init__(self, client: Neo4jCustomClient, tenant_id: str = "default"):
        self.client = client
        self.tenant_id = tenant_id

    # ===================================
    # CREATE
    # ===================================

    def create_fact(
        self,
        subject: str,
        predicate: str,
        object_str: str,
        value: float,
        unit: str,
        value_type: str = "numeric",
        fact_type: str = "GENERAL",
        status: str = "proposed",
        confidence: float = 0.0,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        source_chunk_id: Optional[str] = None,
        source_document: Optional[str] = None,
        extraction_method: Optional[str] = None,
        extraction_model: Optional[str] = None,
        extraction_prompt_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Crée un nouveau fact dans Neo4j.

        Args:
            subject: Sujet du fact (ex: "SAP S/4HANA Cloud")
            predicate: Prédicat (ex: "SLA_garantie")
            object_str: Objet textuel (ex: "99.7%")
            value: Valeur numérique (ex: 99.7)
            unit: Unité (ex: "%")
            value_type: Type valeur ("numeric", "text", "date")
            fact_type: Type fact ("SERVICE_LEVEL", "CAPACITY", etc.)
            status: Statut ("proposed", "approved", "rejected")
            confidence: Confiance extraction (0.0-1.0)
            valid_from: Date début validité (ISO format)
            valid_until: Date fin validité (ISO format, optionnel)
            source_chunk_id: UUID chunk source Qdrant
            source_document: Nom document source
            extraction_method: Méthode extraction
            extraction_model: Modèle LLM utilisé
            extraction_prompt_id: ID prompt utilisé

        Returns:
            Dict représentant le fact créé
        """
        # Validation applicative (Neo4j Community ne supporte pas contraintes Enterprise)
        VALID_STATUSES = ["proposed", "approved", "rejected", "conflicted"]

        if not subject or not predicate:
            raise ValueError("subject and predicate are required")

        if not self.tenant_id:
            raise ValueError("tenant_id is required")

        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}, got: {status}")

        fact_uuid = str(uuid.uuid4())
        valid_from_dt = valid_from or datetime.utcnow().isoformat()

        parameters = {
            "uuid": fact_uuid,
            "tenant_id": self.tenant_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_str,
            "value": value,
            "unit": unit,
            "value_type": value_type,
            "fact_type": fact_type,
            "status": status,
            "confidence": confidence,
            "valid_from": valid_from_dt,
            "valid_until": valid_until,
            "source_chunk_id": source_chunk_id,
            "source_document": source_document,
            "approved_by": None,
            "approved_at": None,
            "extraction_method": extraction_method,
            "extraction_model": extraction_model,
            "extraction_prompt_id": extraction_prompt_id,
        }

        results = self.client.execute_write_query(schemas.CREATE_FACT, parameters)

        if results:
            fact_node = results[0]["f"]
            logger.info(f"✅ Fact created - UUID: {fact_uuid}, Subject: {subject}, Predicate: {predicate}")
            return self._node_to_dict(fact_node)

        raise Exception("Failed to create fact")

    # ===================================
    # READ
    # ===================================

    def get_fact_by_uuid(self, fact_uuid: str) -> Optional[Dict[str, Any]]:
        """
        Récupère un fact par UUID.

        Args:
            fact_uuid: UUID du fact

        Returns:
            Dict fact ou None si non trouvé
        """
        results = self.client.execute_query(
            schemas.GET_FACT_BY_UUID,
            {"uuid": fact_uuid, "tenant_id": self.tenant_id}
        )

        if results:
            return self._node_to_dict(results[0]["f"])

        return None

    def get_facts_by_status(
        self,
        status: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Récupère facts par statut.

        Args:
            status: Statut ("proposed", "approved", "rejected", "conflicted")
            limit: Nombre max résultats

        Returns:
            Liste de facts
        """
        results = self.client.execute_query(
            schemas.GET_FACTS_BY_STATUS,
            {"tenant_id": self.tenant_id, "status": status, "limit": limit}
        )

        return [self._node_to_dict(r["f"]) for r in results]

    def get_facts_by_subject_predicate(
        self,
        subject: str,
        predicate: str
    ) -> List[Dict[str, Any]]:
        """
        Récupère facts par subject + predicate.

        Args:
            subject: Sujet
            predicate: Prédicat

        Returns:
            Liste de facts (tri par valid_from DESC)
        """
        results = self.client.execute_query(
            schemas.GET_FACTS_BY_SUBJECT_PREDICATE,
            {"tenant_id": self.tenant_id, "subject": subject, "predicate": predicate}
        )

        return [self._node_to_dict(r["f"]) for r in results]

    # ===================================
    # UPDATE
    # ===================================

    def update_fact_status(
        self,
        fact_uuid: str,
        status: str,
        approved_by: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Met à jour le statut d'un fact.

        Args:
            fact_uuid: UUID du fact
            status: Nouveau statut ("approved", "rejected", "conflicted")
            approved_by: User ID qui approuve (si status="approved")

        Returns:
            Dict fact mis à jour ou None
        """
        results = self.client.execute_write_query(
            schemas.UPDATE_FACT_STATUS,
            {
                "uuid": fact_uuid,
                "tenant_id": self.tenant_id,
                "status": status,
                "approved_by": approved_by,
            }
        )

        if results:
            logger.info(f"✅ Fact status updated - UUID: {fact_uuid}, Status: {status}")
            return self._node_to_dict(results[0]["f"])

        return None

    # ===================================
    # DELETE
    # ===================================

    def delete_fact(self, fact_uuid: str) -> bool:
        """
        Supprime un fact.

        Args:
            fact_uuid: UUID du fact

        Returns:
            True si supprimé, False sinon
        """
        try:
            self.client.execute_write_query(
                schemas.DELETE_FACT,
                {"uuid": fact_uuid, "tenant_id": self.tenant_id}
            )

            logger.info(f"✅ Fact deleted - UUID: {fact_uuid}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete fact {fact_uuid}: {e}")
            return False

    # ===================================
    # DÉTECTION CONFLITS
    # ===================================

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """
        Détecte conflits entre facts approuvés et proposés.

        Returns:
            Liste de conflits avec details:
            {
                "fact_approved": {...},
                "fact_proposed": {...},
                "conflict_type": "CONTRADICTS" | "OVERRIDES",
                "value_diff_pct": 0.05
            }
        """
        results = self.client.execute_query(
            schemas.DETECT_CONFLICTS,
            {"tenant_id": self.tenant_id}
        )

        conflicts = []
        for r in results:
            conflicts.append({
                "fact_approved": self._node_to_dict(r["f1"]),
                "fact_proposed": self._node_to_dict(r["f2"]),
                "conflict_type": r["conflict_type"],
                "value_diff_pct": r["value_diff_pct"],
            })

        logger.info(f"Found {len(conflicts)} conflicts")
        return conflicts

    def detect_duplicates(self) -> List[Dict[str, Any]]:
        """
        Détecte duplicates (même valeur, sources différentes).

        Returns:
            Liste de duplicates
        """
        results = self.client.execute_query(
            schemas.DETECT_DUPLICATES,
            {"tenant_id": self.tenant_id}
        )

        duplicates = []
        for r in results:
            duplicates.append({
                "fact_approved": self._node_to_dict(r["f1"]),
                "fact_proposed": self._node_to_dict(r["f2"]),
                "conflict_type": r["conflict_type"],
            })

        logger.info(f"Found {len(duplicates)} duplicates")
        return duplicates

    # ===================================
    # TIMELINE
    # ===================================

    def get_fact_timeline(
        self,
        subject: str,
        predicate: str
    ) -> List[Dict[str, Any]]:
        """
        Récupère timeline complète d'un fact.

        Args:
            subject: Sujet
            predicate: Prédicat

        Returns:
            Liste historique valeurs (tri DESC)
        """
        results = self.client.execute_query(
            schemas.GET_FACT_TIMELINE,
            {"tenant_id": self.tenant_id, "subject": subject, "predicate": predicate}
        )

        return [dict(r) for r in results]

    def get_fact_at_date(
        self,
        subject: str,
        predicate: str,
        target_date: str
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère fact valide à une date donnée (point-in-time query).

        Args:
            subject: Sujet
            predicate: Prédicat
            target_date: Date cible (ISO format)

        Returns:
            Fact valide à cette date ou None
        """
        results = self.client.execute_query(
            schemas.GET_FACT_AT_DATE,
            {
                "tenant_id": self.tenant_id,
                "subject": subject,
                "predicate": predicate,
                "target_date": target_date,
            }
        )

        if results:
            return self._node_to_dict(results[0]["f"])

        return None

    # ===================================
    # STATISTIQUES
    # ===================================

    def count_facts_by_status(self) -> Dict[str, int]:
        """
        Compte facts par statut.

        Returns:
            Dict {status: count}
        """
        results = self.client.execute_query(
            schemas.COUNT_FACTS_BY_STATUS,
            {"tenant_id": self.tenant_id}
        )

        return {r["status"]: r["count"] for r in results}

    def count_facts_by_type(self) -> Dict[str, int]:
        """
        Compte facts par type.

        Returns:
            Dict {fact_type: count}
        """
        results = self.client.execute_query(
            schemas.COUNT_FACTS_BY_TYPE,
            {"tenant_id": self.tenant_id}
        )

        return {r["fact_type"]: r["count"] for r in results}

    def get_conflicts_count(self) -> int:
        """
        Compte nombre de facts en conflit.

        Returns:
            Nombre de conflits
        """
        results = self.client.execute_query(
            schemas.GET_CONFLICTS_COUNT,
            {"tenant_id": self.tenant_id}
        )

        if results:
            return results[0]["conflicts_count"]

        return 0

    # ===================================
    # HELPERS
    # ===================================

    def _node_to_dict(self, node: Any) -> Dict[str, Any]:
        """
        Convertit node Neo4j en dict Python.

        Args:
            node: Node Neo4j

        Returns:
            Dict représentant le node
        """
        if hasattr(node, "_properties"):
            # Node object
            return dict(node._properties)
        elif isinstance(node, dict):
            # Déjà un dict
            return node
        else:
            # Autre type
            return {"value": node}
