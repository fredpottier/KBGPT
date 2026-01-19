"""
OSMOSE Evidence Bundle - Neo4j Persistence (Pass 3.5)

Persistance des bundles et promotion en SemanticRelations.

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from ulid import ULID

from knowbase.relations.evidence_bundle_models import (
    BundleValidationStatus,
    EvidenceBundle,
    EvidenceFragment,
)

logger = logging.getLogger(__name__)


# ===================================
# CYPHER QUERIES
# ===================================

# Création d'un EvidenceBundle
QUERY_CREATE_BUNDLE = """
MERGE (eb:EvidenceBundle {bundle_id: $bundle_id})
SET eb.tenant_id = $tenant_id,
    eb.document_id = $document_id,
    eb.subject_concept_id = $subject_concept_id,
    eb.object_concept_id = $object_concept_id,
    eb.relation_type_candidate = $relation_type_candidate,
    eb.typing_confidence = $typing_confidence,
    eb.confidence = $confidence,
    eb.validation_status = $validation_status,
    eb.rejection_reason = $rejection_reason,
    eb.evidence_subject_json = $evidence_subject_json,
    eb.evidence_object_json = $evidence_object_json,
    eb.evidence_predicate_json = $evidence_predicate_json,
    eb.evidence_link_json = $evidence_link_json,
    eb.created_at = datetime($created_at),
    eb.validated_at = $validated_at,
    eb.schema_version = $schema_version
RETURN eb.bundle_id AS bundle_id
"""

# Récupération d'un bundle par ID
QUERY_GET_BUNDLE = """
MATCH (eb:EvidenceBundle {bundle_id: $bundle_id, tenant_id: $tenant_id})
RETURN eb
"""

# Mise à jour du statut d'un bundle
QUERY_UPDATE_BUNDLE_STATUS = """
MATCH (eb:EvidenceBundle {bundle_id: $bundle_id, tenant_id: $tenant_id})
SET eb.validation_status = $status,
    eb.rejection_reason = $rejection_reason,
    eb.validated_at = datetime($validated_at)
RETURN eb.bundle_id AS bundle_id
"""

# Promotion: créer SemanticRelation à partir d'un bundle
QUERY_PROMOTE_BUNDLE = """
MATCH (eb:EvidenceBundle {bundle_id: $bundle_id, tenant_id: $tenant_id})
MATCH (subj:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
MATCH (obj:CanonicalConcept {canonical_id: $object_concept_id, tenant_id: $tenant_id})

// Créer la SemanticRelation
CREATE (sr:SemanticRelation {
    relation_id: $relation_id,
    tenant_id: $tenant_id,
    relation_type: $relation_type,
    confidence: $confidence,
    source_bundle_id: $bundle_id,
    created_at: datetime($created_at)
})

// Lier aux concepts
CREATE (subj)-[:HAS_RELATION]->(sr)
CREATE (sr)-[:TARGETS]->(obj)

// Marquer le bundle comme promu
SET eb.validation_status = 'PROMOTED',
    eb.promoted_relation_id = $relation_id,
    eb.validated_at = datetime($validated_at)

RETURN sr.relation_id AS relation_id
"""

# Récupération des bundles par document
QUERY_GET_BUNDLES_BY_DOCUMENT = """
MATCH (eb:EvidenceBundle {tenant_id: $tenant_id, document_id: $document_id})
RETURN eb
ORDER BY eb.created_at DESC
"""

# Récupération des bundles candidats à la promotion
QUERY_GET_CANDIDATE_BUNDLES = """
MATCH (eb:EvidenceBundle {tenant_id: $tenant_id, validation_status: 'CANDIDATE'})
WHERE eb.confidence >= $min_confidence
RETURN eb
ORDER BY eb.confidence DESC
LIMIT $limit
"""

# Suppression d'un bundle
QUERY_DELETE_BUNDLE = """
MATCH (eb:EvidenceBundle {bundle_id: $bundle_id, tenant_id: $tenant_id})
DETACH DELETE eb
"""


# ===================================
# PERSISTENCE CLASS
# ===================================

class BundlePersistence:
    """
    Gère la persistance des EvidenceBundles dans Neo4j.
    """

    def __init__(self, neo4j_client):
        """
        Initialise le gestionnaire de persistance.

        Args:
            neo4j_client: Instance de Neo4jClient
        """
        self.neo4j_client = neo4j_client

    def persist_bundle(
        self,
        bundle: EvidenceBundle,
    ) -> str:
        """
        Persiste un bundle dans Neo4j.

        Args:
            bundle: Bundle à persister

        Returns:
            bundle_id du bundle persisté
        """
        logger.info(
            f"[OSMOSE:Pass3.5] Persisting bundle {bundle.bundle_id} "
            f"({bundle.subject_concept_id} -> {bundle.object_concept_id})"
        )

        # Sérialiser les fragments en JSON
        evidence_subject_json = _fragment_to_json(bundle.evidence_subject)
        evidence_object_json = _fragment_to_json(bundle.evidence_object)
        evidence_predicate_json = json.dumps([
            _fragment_to_dict(ep) for ep in bundle.evidence_predicate
        ])
        evidence_link_json = (
            _fragment_to_json(bundle.evidence_link)
            if bundle.evidence_link else None
        )

        # Préparer les paramètres
        params = {
            "bundle_id": bundle.bundle_id,
            "tenant_id": bundle.tenant_id,
            "document_id": bundle.document_id,
            "subject_concept_id": bundle.subject_concept_id,
            "object_concept_id": bundle.object_concept_id,
            "relation_type_candidate": bundle.relation_type_candidate,
            "typing_confidence": bundle.typing_confidence,
            "confidence": bundle.confidence,
            "validation_status": bundle.validation_status.value if hasattr(bundle.validation_status, 'value') else bundle.validation_status,
            "rejection_reason": bundle.rejection_reason,
            "evidence_subject_json": evidence_subject_json,
            "evidence_object_json": evidence_object_json,
            "evidence_predicate_json": evidence_predicate_json,
            "evidence_link_json": evidence_link_json,
            "created_at": bundle.created_at.isoformat(),
            "validated_at": bundle.validated_at.isoformat() if bundle.validated_at else None,
            "schema_version": bundle.schema_version,
        }

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(QUERY_CREATE_BUNDLE, **params)
            record = result.single()

            if record:
                logger.debug(
                    f"[OSMOSE:Pass3.5] Bundle {bundle.bundle_id} persisted"
                )
                return record["bundle_id"]

        raise RuntimeError(f"Failed to persist bundle {bundle.bundle_id}")

    def get_bundle_by_id(
        self,
        bundle_id: str,
        tenant_id: str = "default",
    ) -> Optional[EvidenceBundle]:
        """
        Récupère un bundle par son ID.

        Args:
            bundle_id: ID du bundle
            tenant_id: Tenant ID

        Returns:
            EvidenceBundle ou None
        """
        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_GET_BUNDLE,
                bundle_id=bundle_id,
                tenant_id=tenant_id,
            )
            record = result.single()

            if record:
                return _record_to_bundle(record["eb"])

        return None

    def promote_bundle_to_relation(
        self,
        bundle_id: str,
        tenant_id: str = "default",
    ) -> Optional[str]:
        """
        Promeut un bundle en SemanticRelation.

        Crée la SemanticRelation et met à jour le bundle.

        Args:
            bundle_id: ID du bundle à promouvoir
            tenant_id: Tenant ID

        Returns:
            relation_id de la relation créée ou None
        """
        # Récupérer le bundle
        bundle = self.get_bundle_by_id(bundle_id, tenant_id)
        if not bundle:
            logger.error(f"[OSMOSE:Pass3.5] Bundle {bundle_id} not found")
            return None

        if bundle.validation_status == BundleValidationStatus.PROMOTED:
            logger.warning(
                f"[OSMOSE:Pass3.5] Bundle {bundle_id} already promoted"
            )
            return bundle.promoted_relation_id

        if bundle.validation_status == BundleValidationStatus.REJECTED:
            logger.error(
                f"[OSMOSE:Pass3.5] Cannot promote rejected bundle {bundle_id}"
            )
            return None

        # Générer l'ID de la relation
        relation_id = f"rel:{str(ULID())}"
        now = datetime.utcnow()

        logger.info(
            f"[OSMOSE:Pass3.5] Promoting bundle {bundle_id} to relation {relation_id}"
        )

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_PROMOTE_BUNDLE,
                bundle_id=bundle_id,
                tenant_id=tenant_id,
                subject_concept_id=bundle.subject_concept_id,
                object_concept_id=bundle.object_concept_id,
                relation_id=relation_id,
                relation_type=bundle.relation_type_candidate,
                confidence=bundle.confidence,
                created_at=now.isoformat(),
                validated_at=now.isoformat(),
            )
            record = result.single()

            if record:
                logger.info(
                    f"[OSMOSE:Pass3.5] Bundle {bundle_id} promoted to {relation_id}"
                )
                return record["relation_id"]

        return None

    def mark_bundle_rejected(
        self,
        bundle_id: str,
        rejection_reason: str,
        tenant_id: str = "default",
    ) -> bool:
        """
        Marque un bundle comme rejeté.

        Args:
            bundle_id: ID du bundle
            rejection_reason: Raison du rejet
            tenant_id: Tenant ID

        Returns:
            True si succès
        """
        now = datetime.utcnow()

        logger.info(
            f"[OSMOSE:Pass3.5] Rejecting bundle {bundle_id}: {rejection_reason}"
        )

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_UPDATE_BUNDLE_STATUS,
                bundle_id=bundle_id,
                tenant_id=tenant_id,
                status=BundleValidationStatus.REJECTED.value,
                rejection_reason=rejection_reason,
                validated_at=now.isoformat(),
            )
            record = result.single()

            return record is not None

    def get_bundles_by_document(
        self,
        document_id: str,
        tenant_id: str = "default",
    ) -> List[EvidenceBundle]:
        """
        Récupère tous les bundles d'un document.

        Args:
            document_id: ID du document
            tenant_id: Tenant ID

        Returns:
            Liste de bundles
        """
        bundles: List[EvidenceBundle] = []

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_GET_BUNDLES_BY_DOCUMENT,
                tenant_id=tenant_id,
                document_id=document_id,
            )

            for record in result:
                bundle = _record_to_bundle(record["eb"])
                if bundle:
                    bundles.append(bundle)

        return bundles

    def get_candidate_bundles(
        self,
        tenant_id: str = "default",
        min_confidence: float = 0.5,
        limit: int = 100,
    ) -> List[EvidenceBundle]:
        """
        Récupère les bundles candidats à la promotion.

        Args:
            tenant_id: Tenant ID
            min_confidence: Confiance minimale
            limit: Nombre maximum de bundles

        Returns:
            Liste de bundles candidats
        """
        bundles: List[EvidenceBundle] = []

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_GET_CANDIDATE_BUNDLES,
                tenant_id=tenant_id,
                min_confidence=min_confidence,
                limit=limit,
            )

            for record in result:
                bundle = _record_to_bundle(record["eb"])
                if bundle:
                    bundles.append(bundle)

        return bundles

    def delete_bundle(
        self,
        bundle_id: str,
        tenant_id: str = "default",
    ) -> bool:
        """
        Supprime un bundle.

        Args:
            bundle_id: ID du bundle
            tenant_id: Tenant ID

        Returns:
            True si succès
        """
        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            session.run(
                QUERY_DELETE_BUNDLE,
                bundle_id=bundle_id,
                tenant_id=tenant_id,
            )
            return True


# ===================================
# HELPERS
# ===================================

def _fragment_to_dict(fragment: EvidenceFragment) -> dict:
    """Convertit un fragment en dictionnaire."""
    return {
        "fragment_id": fragment.fragment_id,
        "fragment_type": fragment.fragment_type.value if hasattr(fragment.fragment_type, 'value') else fragment.fragment_type,
        "text": fragment.text,
        "source_context_id": fragment.source_context_id,
        "source_page": fragment.source_page,
        "char_start": fragment.char_start,
        "char_end": fragment.char_end,
        "confidence": fragment.confidence,
        "extraction_method": fragment.extraction_method.value if hasattr(fragment.extraction_method, 'value') else fragment.extraction_method,
    }


def _fragment_to_json(fragment: EvidenceFragment) -> str:
    """Convertit un fragment en JSON."""
    return json.dumps(_fragment_to_dict(fragment))


def _json_to_fragment(json_str: str) -> EvidenceFragment:
    """Convertit un JSON en fragment."""
    data = json.loads(json_str)
    return EvidenceFragment(**data)


def _record_to_bundle(node) -> Optional[EvidenceBundle]:
    """Convertit un noeud Neo4j en EvidenceBundle."""
    try:
        # Parser les fragments JSON
        evidence_subject = _json_to_fragment(node["evidence_subject_json"])
        evidence_object = _json_to_fragment(node["evidence_object_json"])

        predicate_list = json.loads(node["evidence_predicate_json"])
        evidence_predicate = [EvidenceFragment(**p) for p in predicate_list]

        evidence_link = None
        if node.get("evidence_link_json"):
            evidence_link = _json_to_fragment(node["evidence_link_json"])

        # Parser les dates
        created_at = node["created_at"]
        if hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        validated_at = node.get("validated_at")
        if validated_at and hasattr(validated_at, "to_native"):
            validated_at = validated_at.to_native()

        return EvidenceBundle(
            bundle_id=node["bundle_id"],
            tenant_id=node["tenant_id"],
            document_id=node["document_id"],
            evidence_subject=evidence_subject,
            evidence_object=evidence_object,
            evidence_predicate=evidence_predicate,
            evidence_link=evidence_link,
            subject_concept_id=node["subject_concept_id"],
            object_concept_id=node["object_concept_id"],
            relation_type_candidate=node["relation_type_candidate"],
            typing_confidence=node["typing_confidence"],
            confidence=node["confidence"],
            validation_status=BundleValidationStatus(node["validation_status"]),
            rejection_reason=node.get("rejection_reason"),
            promoted_relation_id=node.get("promoted_relation_id"),
            created_at=created_at,
            validated_at=validated_at,
            schema_version=node.get("schema_version", "1.0.0"),
        )
    except Exception as e:
        logger.error(f"[OSMOSE:Pass3.5] Error parsing bundle: {e}")
        return None
