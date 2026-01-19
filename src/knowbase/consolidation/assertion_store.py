"""
AssertionStore - Persistence des assertions et DocContextFrame dans Neo4j.

Ce module gère:
1. Relation EXTRACTED_FROM avec propriétés assertion (polarity, scope, markers)
2. Stockage DocContextFrame sur les nœuds Document
3. Index optimisés pour les diff queries

Architecture (ADR Section 7 - PR4):
- (:ProtoConcept)-[:EXTRACTED_FROM {polarity, scope, markers, confidence}]->(:Document)
- (:Document {doc_context_json, detected_variant, variant_confidence})

Usage:
    store = AssertionStore(tenant_id="default")
    await store.ensure_indexes()
    await store.persist_document_context(doc_id, doc_context_frame)
    await store.persist_assertion(proto_id, doc_id, assertion_data)

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 7 (PR4)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


@dataclass
class AssertionData:
    """Données d'assertion pour une relation EXTRACTED_FROM."""
    polarity: str = "unknown"
    scope: str = "unknown"
    markers: List[str] = field(default_factory=list)
    confidence: float = 0.5
    qualifier_source: str = "unknown"  # explicit, inherited, heuristic
    is_override: bool = False
    evidence_passage: Optional[str] = None  # Texte source (tronqué)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "polarity": self.polarity,
            "scope": self.scope,
            "markers": self.markers,
            "confidence": self.confidence,
            "qualifier_source": self.qualifier_source,
            "is_override": self.is_override,
        }


@dataclass
class DocumentContextData:
    """Données de DocContextFrame pour un Document."""
    detected_variant: Optional[str] = None
    variant_confidence: float = 0.0
    doc_scope: str = "unknown"  # variant_specific, mixed, general
    edition: Optional[str] = None
    global_markers: List[str] = field(default_factory=list)
    metadata_json: Optional[str] = None  # JSON sérialisé du DocContextFrame complet

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected_variant": self.detected_variant,
            "variant_confidence": self.variant_confidence,
            "doc_scope": self.doc_scope,
            "edition": self.edition,
            "global_markers": self.global_markers,
        }


class AssertionStore:
    """
    Gestionnaire de persistence des assertions dans Neo4j.

    Responsabilités:
    1. Créer/mettre à jour les relations EXTRACTED_FROM avec propriétés assertion
    2. Stocker les DocContextFrame sur les nœuds Document
    3. Créer les index optimisés pour les diff queries
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise l'AssertionStore.

        Args:
            tenant_id: ID du tenant
        """
        self.tenant_id = tenant_id
        self._neo4j_client = None

    def _get_neo4j_client(self):
        """Lazy init du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            self._neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )
        return self._neo4j_client

    async def ensure_indexes(self) -> None:
        """
        Crée les index optimisés pour les diff queries.

        Index créés:
        - Document.id (lookup rapide)
        - EXTRACTED_FROM.polarity (filtrage par polarity)
        - EXTRACTED_FROM.scope (filtrage par scope)
        - Composite index sur markers (liste)
        """
        client = self._get_neo4j_client()

        queries = [
            # Index sur Document.id
            """
            CREATE INDEX document_id IF NOT EXISTS
            FOR (d:Document) ON (d.id, d.tenant_id)
            """,
            # Index sur Document.detected_variant
            """
            CREATE INDEX document_variant IF NOT EXISTS
            FOR (d:Document) ON (d.detected_variant)
            """,
            # Index sur ProtoConcept pour join rapide
            """
            CREATE INDEX proto_tenant IF NOT EXISTS
            FOR (p:ProtoConcept) ON (p.tenant_id)
            """,
            # Index fulltext sur markers pour recherche
            # Note: les index relationship property nécessitent Neo4j 5.7+
            # On utilise une approche alternative via CONTAINS sur markers
        ]

        try:
            with client.driver.session(database="neo4j") as session:
                for query in queries:
                    try:
                        session.run(query)
                    except Exception as idx_err:
                        # Index peut déjà exister ou syntaxe non supportée
                        logger.debug(f"[AssertionStore] Index query skipped: {idx_err}")

            logger.info("[AssertionStore] Indexes created/verified")

        except Exception as e:
            logger.warning(f"[AssertionStore] Index creation failed: {e}")

    async def ensure_document(
        self,
        document_id: str,
        document_name: Optional[str] = None,
        context_data: Optional[DocumentContextData] = None,
    ) -> bool:
        """
        Crée ou met à jour un nœud Document avec son contexte.

        Args:
            document_id: ID du document
            document_name: Nom du document
            context_data: Données de DocContextFrame

        Returns:
            True si succès
        """
        client = self._get_neo4j_client()

        # Préparer les données de contexte
        ctx = context_data or DocumentContextData()

        query = """
        MERGE (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        ON CREATE SET
            d.name = $doc_name,
            d.detected_variant = $detected_variant,
            d.variant_confidence = $variant_confidence,
            d.doc_scope = $doc_scope,
            d.edition = $edition,
            d.global_markers = $global_markers,
            d.doc_context_json = $context_json,
            d.created_at = datetime()
        ON MATCH SET
            d.name = COALESCE($doc_name, d.name),
            d.detected_variant = COALESCE($detected_variant, d.detected_variant),
            d.variant_confidence = $variant_confidence,
            d.doc_scope = $doc_scope,
            d.edition = COALESCE($edition, d.edition),
            d.global_markers = $global_markers,
            d.doc_context_json = $context_json,
            d.updated_at = datetime()
        RETURN d.id AS doc_id
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    doc_id=document_id,
                    tenant_id=self.tenant_id,
                    doc_name=document_name,
                    detected_variant=ctx.detected_variant,
                    variant_confidence=ctx.variant_confidence,
                    doc_scope=ctx.doc_scope,
                    edition=ctx.edition,
                    global_markers=ctx.global_markers,
                    context_json=ctx.metadata_json,
                )
                record = result.single()
                return record is not None

        except Exception as e:
            logger.error(f"[AssertionStore] Failed to ensure document {document_id}: {e}")
            return False

    async def persist_assertion(
        self,
        proto_concept_id: str,
        document_id: str,
        assertion: AssertionData,
    ) -> bool:
        """
        Crée ou met à jour une relation EXTRACTED_FROM avec les propriétés assertion.

        Args:
            proto_concept_id: ID du ProtoConcept
            document_id: ID du Document source
            assertion: Données d'assertion

        Returns:
            True si succès
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept {concept_id: $proto_id, tenant_id: $tenant_id})
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (pc)-[r:EXTRACTED_FROM]->(d)
        ON CREATE SET
            r.polarity = $polarity,
            r.scope = $scope,
            r.markers = $markers,
            r.confidence = $confidence,
            r.qualifier_source = $qualifier_source,
            r.is_override = $is_override,
            r.evidence_preview = $evidence,
            r.created_at = datetime()
        ON MATCH SET
            r.polarity = CASE
                WHEN $confidence > r.confidence THEN $polarity
                ELSE r.polarity
            END,
            r.scope = CASE
                WHEN $confidence > r.confidence THEN $scope
                ELSE r.scope
            END,
            r.markers = CASE
                WHEN size($markers) > size(COALESCE(r.markers, [])) THEN $markers
                ELSE COALESCE(r.markers, [])
            END,
            r.confidence = CASE
                WHEN $confidence > r.confidence THEN $confidence
                ELSE r.confidence
            END,
            r.updated_at = datetime()
        RETURN r IS NOT NULL AS created
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    proto_id=proto_concept_id,
                    doc_id=document_id,
                    tenant_id=self.tenant_id,
                    polarity=assertion.polarity,
                    scope=assertion.scope,
                    markers=assertion.markers,
                    confidence=assertion.confidence,
                    qualifier_source=assertion.qualifier_source,
                    is_override=assertion.is_override,
                    evidence=assertion.evidence_passage[:200] if assertion.evidence_passage else None,
                )
                record = result.single()
                return record["created"] if record else False

        except Exception as e:
            logger.error(
                f"[AssertionStore] Failed to persist assertion "
                f"{proto_concept_id} -> {document_id}: {e}"
            )
            return False

    async def persist_assertions_batch(
        self,
        assertions: List[Dict[str, Any]],
        document_id: str,
    ) -> int:
        """
        Persiste plusieurs assertions en batch.

        Args:
            assertions: Liste de dicts avec {proto_id, polarity, scope, markers, confidence, ...}
            document_id: ID du Document source

        Returns:
            Nombre d'assertions créées/mises à jour
        """
        if not assertions:
            return 0

        client = self._get_neo4j_client()

        query = """
        UNWIND $assertions AS a
        MATCH (pc:ProtoConcept {concept_id: a.proto_id, tenant_id: $tenant_id})
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (pc)-[r:EXTRACTED_FROM]->(d)
        ON CREATE SET
            r.polarity = a.polarity,
            r.scope = a.scope,
            r.markers = a.markers,
            r.confidence = a.confidence,
            r.qualifier_source = a.qualifier_source,
            r.is_override = a.is_override,
            r.created_at = datetime()
        ON MATCH SET
            r.polarity = CASE WHEN a.confidence > r.confidence THEN a.polarity ELSE r.polarity END,
            r.scope = CASE WHEN a.confidence > r.confidence THEN a.scope ELSE r.scope END,
            r.confidence = CASE WHEN a.confidence > r.confidence THEN a.confidence ELSE r.confidence END,
            r.markers = CASE
                WHEN size(a.markers) > size(COALESCE(r.markers, [])) THEN a.markers
                ELSE COALESCE(r.markers, [])
            END,
            r.updated_at = datetime()
        RETURN count(r) AS created
        """

        # Normaliser les données
        assertion_data = []
        for a in assertions:
            assertion_data.append({
                "proto_id": a.get("proto_id") or a.get("concept_id"),
                "polarity": a.get("polarity", "unknown"),
                "scope": a.get("scope", "unknown"),
                "markers": a.get("markers", []),
                "confidence": a.get("confidence", 0.5),
                "qualifier_source": a.get("qualifier_source", "unknown"),
                "is_override": a.get("is_override", False),
            })

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    assertions=assertion_data,
                    doc_id=document_id,
                    tenant_id=self.tenant_id,
                )
                record = result.single()
                count = record["created"] if record else 0
                logger.info(f"[AssertionStore] Persisted {count} assertions for doc {document_id}")
                return count

        except Exception as e:
            logger.error(f"[AssertionStore] Batch assertion persist failed: {e}")
            return 0

    async def get_document_context(
        self,
        document_id: str,
    ) -> Optional[DocumentContextData]:
        """
        Récupère le DocContextFrame d'un document.

        Args:
            document_id: ID du document

        Returns:
            DocumentContextData ou None si non trouvé
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        RETURN
            d.detected_variant AS detected_variant,
            d.variant_confidence AS variant_confidence,
            d.doc_scope AS doc_scope,
            d.edition AS edition,
            d.global_markers AS global_markers,
            d.doc_context_json AS context_json
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    doc_id=document_id,
                    tenant_id=self.tenant_id,
                )
                record = result.single()

                if record:
                    return DocumentContextData(
                        detected_variant=record["detected_variant"],
                        variant_confidence=record["variant_confidence"] or 0.0,
                        doc_scope=record["doc_scope"] or "unknown",
                        edition=record["edition"],
                        global_markers=record["global_markers"] or [],
                        metadata_json=record["context_json"],
                    )
                return None

        except Exception as e:
            logger.error(f"[AssertionStore] Failed to get document context: {e}")
            return None

    async def get_assertions_for_document(
        self,
        document_id: str,
        polarity_filter: Optional[str] = None,
        scope_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Récupère toutes les assertions d'un document.

        Args:
            document_id: ID du document
            polarity_filter: Filtrer par polarity
            scope_filter: Filtrer par scope

        Returns:
            Liste des assertions avec concept_id et propriétés
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept)-[r:EXTRACTED_FROM]->(d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        WHERE pc.tenant_id = $tenant_id
        """ + ("""AND r.polarity = $polarity_filter""" if polarity_filter else "") + """
        """ + ("""AND r.scope = $scope_filter""" if scope_filter else "") + """
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            cc.canonical_id AS canonical_id,
            r.polarity AS polarity,
            r.scope AS scope,
            r.markers AS markers,
            r.confidence AS confidence,
            r.qualifier_source AS qualifier_source,
            r.is_override AS is_override
        ORDER BY r.confidence DESC
        """

        try:
            params = {"doc_id": document_id, "tenant_id": self.tenant_id}
            if polarity_filter:
                params["polarity_filter"] = polarity_filter
            if scope_filter:
                params["scope_filter"] = scope_filter

            with client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"[AssertionStore] Failed to get assertions: {e}")
            return []

    async def get_concepts_with_conflicting_polarity(
        self,
        min_confidence: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Trouve les concepts avec des polarités conflictuelles.

        Un conflit = même concept avec POSITIVE dans un doc et DEPRECATED/NEGATIVE dans un autre.

        Args:
            min_confidence: Confiance minimale

        Returns:
            Liste des concepts avec détails du conflit
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept)-[r1:EXTRACTED_FROM]->(d1:Document)
        MATCH (pc)-[r2:EXTRACTED_FROM]->(d2:Document)
        WHERE pc.tenant_id = $tenant_id
          AND d1 <> d2
          AND r1.confidence >= $min_conf
          AND r2.confidence >= $min_conf
          AND r1.polarity <> r2.polarity
          AND r1.polarity IN ['positive', 'negative', 'deprecated']
          AND r2.polarity IN ['positive', 'negative', 'deprecated']
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            collect(DISTINCT {
                doc_id: d1.id,
                polarity: r1.polarity,
                markers: r1.markers
            }) AS assertions_1,
            collect(DISTINCT {
                doc_id: d2.id,
                polarity: r2.polarity,
                markers: r2.markers
            }) AS assertions_2
        LIMIT 100
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    tenant_id=self.tenant_id,
                    min_conf=min_confidence,
                )
                conflicts = []
                for record in result:
                    conflicts.append({
                        "concept_id": record["concept_id"],
                        "label": record["label"],
                        "conflict_type": "polarity",
                        "details": {
                            "assertions_a": record["assertions_1"],
                            "assertions_b": record["assertions_2"],
                        }
                    })
                return conflicts

        except Exception as e:
            logger.error(f"[AssertionStore] Conflict query failed: {e}")
            return []


# Singleton
_assertion_store_instances: Dict[str, AssertionStore] = {}


def get_assertion_store(tenant_id: str = "default") -> AssertionStore:
    """Retourne l'instance singleton de l'AssertionStore pour un tenant."""
    global _assertion_store_instances
    if tenant_id not in _assertion_store_instances:
        _assertion_store_instances[tenant_id] = AssertionStore(tenant_id=tenant_id)
    return _assertion_store_instances[tenant_id]


__all__ = [
    "AssertionData",
    "DocumentContextData",
    "AssertionStore",
    "get_assertion_store",
]
