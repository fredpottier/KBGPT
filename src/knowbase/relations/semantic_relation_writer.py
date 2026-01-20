"""
ADR Relations Discursivement Déterminées - SemanticRelation Writer

Promeut les CanonicalRelations en SemanticRelations avec calcul du DefensibilityTier.

Pipeline: RawAssertion → CanonicalRelation → SemanticRelation

Le SemanticRelation est traversable par le runtime Graph-First avec:
- semantic_grade: transparence sur l'origine des preuves (EXPLICIT/DISCURSIVE/MIXED)
- defensibility_tier: autorisation d'usage runtime (STRICT/EXTENDED)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2025-01-20
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    CanonicalRelation,
    SemanticRelation,
    SemanticGrade,
    DefensibilityTier,
    SupportStrength,
    ExtractionMethod,
    compute_semantic_grade,
    compute_bundle_diversity,
)
from knowbase.relations.tier_attribution import (
    compute_defensibility_tier,
    TierAttributionResult,
)

logger = logging.getLogger(__name__)


class SemanticRelationWriter:
    """
    Promeut et écrit des SemanticRelations à partir de CanonicalRelations.

    Responsabilités:
    1. Calculer le semantic_grade à partir des compteurs EXPLICIT/DISCURSIVE
    2. Calculer le defensibility_tier via les règles de l'ADR
    3. Créer le nœud SemanticRelation dans Neo4j
    4. Créer les arêtes vers les CanonicalConcepts

    Le tier STRICT est attribué aux relations défendables du texte:
    - EXPLICIT → STRICT (toujours)
    - MIXED → STRICT (au moins une preuve EXPLICIT)
    - DISCURSIVE → STRICT ou EXTENDED selon matrice basis → tier
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize writer.

        Args:
            neo4j_client: Neo4j client instance (creates one if not provided)
            tenant_id: Tenant ID for multi-tenancy
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "promoted": 0,
            "strict": 0,
            "extended": 0,
            "explicit_grade": 0,
            "discursive_grade": 0,
            "mixed_grade": 0,
            "errors": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def promote_relation(
        self,
        canonical: CanonicalRelation,
        discursive_bases: Optional[List[str]] = None,
        extraction_method: ExtractionMethod = ExtractionMethod.HYBRID,
        span_count: int = 1,
        has_marker_in_text: bool = True,
        promotion_reason: Optional[str] = None,
    ) -> Optional[SemanticRelation]:
        """
        Promeut une CanonicalRelation en SemanticRelation.

        Args:
            canonical: CanonicalRelation à promouvoir
            discursive_bases: Bases discursives (pour calcul tier si DISCURSIVE)
            extraction_method: Méthode d'extraction utilisée
            span_count: Nombre de spans dans l'EvidenceBundle
            has_marker_in_text: True si marqueur textuel présent (or, unless, etc.)
            promotion_reason: Raison optionnelle pour audit

        Returns:
            SemanticRelation promue, ou None si erreur
        """
        try:
            # 1. Calculer semantic_grade à partir des compteurs
            semantic_grade = compute_semantic_grade(
                canonical.explicit_support_count,
                canonical.discursive_support_count
            )

            # Track grade stats
            if semantic_grade == SemanticGrade.EXPLICIT:
                self._stats["explicit_grade"] += 1
            elif semantic_grade == SemanticGrade.DISCURSIVE:
                self._stats["discursive_grade"] += 1
            elif semantic_grade == SemanticGrade.MIXED:
                self._stats["mixed_grade"] += 1

            # 2. Calculer defensibility_tier via les règles ADR
            # Convertir les bases string en enum si nécessaire
            from knowbase.relations.types import DiscursiveBasis
            bases = []
            if discursive_bases:
                for b in discursive_bases:
                    try:
                        bases.append(DiscursiveBasis(b) if isinstance(b, str) else b)
                    except ValueError:
                        pass

            tier_result: TierAttributionResult = compute_defensibility_tier(
                semantic_grade=semantic_grade,
                discursive_bases=bases if bases else None,
                relation_type=canonical.relation_type,
                extraction_method=extraction_method,
                span_count=span_count,
                has_marker_in_text=has_marker_in_text,
            )

            # Track tier stats
            if tier_result.tier == DefensibilityTier.STRICT:
                self._stats["strict"] += 1
            else:
                self._stats["extended"] += 1

            # 3. Construire SupportStrength
            support = SupportStrength(
                support_count=canonical.total_assertions,
                explicit_count=canonical.explicit_support_count,
                discursive_count=canonical.discursive_support_count,
                doc_coverage=canonical.distinct_documents,
                distinct_sections=canonical.distinct_sections,
                bundle_diversity=compute_bundle_diversity(canonical.distinct_sections),
            )

            # 4. Créer SemanticRelation
            semantic_id = f"sr_{ULID()}"
            semantic_relation = SemanticRelation(
                semantic_relation_id=semantic_id,
                canonical_relation_id=canonical.canonical_relation_id,
                tenant_id=canonical.tenant_id,
                relation_type=canonical.relation_type,
                subject_concept_id=canonical.subject_concept_id,
                object_concept_id=canonical.object_concept_id,
                semantic_grade=semantic_grade,
                defensibility_tier=tier_result.tier,
                support_strength=support,
                confidence=canonical.confidence_p50,
                promoted_at=datetime.utcnow(),
                promotion_reason=promotion_reason or tier_result.reason,
            )

            # 5. Écrire dans Neo4j
            self._write_to_neo4j(semantic_relation)

            self._stats["promoted"] += 1
            logger.debug(
                f"[SemanticRelationWriter] Promoted: {semantic_id} "
                f"(grade={semantic_grade.value}, tier={tier_result.tier.value})"
            )

            return semantic_relation

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[SemanticRelationWriter] Error promoting relation: {e}")
            return None

    def _write_to_neo4j(self, relation: SemanticRelation) -> None:
        """
        Write SemanticRelation node and edges to Neo4j.

        Creates:
        - SemanticRelation node
        - PROMOTED_FROM edge to CanonicalRelation
        - SEMANTIC_SUBJECT edge to subject CanonicalConcept
        - SEMANTIC_OBJECT edge to object CanonicalConcept
        """
        # Handle enum values
        relation_type_str = relation.relation_type.value if hasattr(relation.relation_type, 'value') else str(relation.relation_type)
        semantic_grade_str = relation.semantic_grade.value if hasattr(relation.semantic_grade, 'value') else str(relation.semantic_grade)
        tier_str = relation.defensibility_tier.value if hasattr(relation.defensibility_tier, 'value') else str(relation.defensibility_tier)

        query = """
        // Create SemanticRelation node
        CREATE (sr:SemanticRelation {
            semantic_relation_id: $semantic_relation_id,
            canonical_relation_id: $canonical_relation_id,
            tenant_id: $tenant_id,
            relation_type: $relation_type,
            subject_concept_id: $subject_concept_id,
            object_concept_id: $object_concept_id,
            semantic_grade: $semantic_grade,
            defensibility_tier: $defensibility_tier,
            support_count: $support_count,
            explicit_count: $explicit_count,
            discursive_count: $discursive_count,
            doc_coverage: $doc_coverage,
            distinct_sections: $distinct_sections,
            bundle_diversity: $bundle_diversity,
            confidence: $confidence,
            promoted_at: datetime($promoted_at),
            promotion_reason: $promotion_reason
        })

        // Link to canonical relation
        WITH sr
        MATCH (cr:CanonicalRelation {canonical_relation_id: $canonical_relation_id})
        CREATE (sr)-[:PROMOTED_FROM]->(cr)

        // Link to subject concept
        WITH sr
        MATCH (s:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
        CREATE (sr)-[:SEMANTIC_SUBJECT]->(s)

        // Link to object concept
        WITH sr
        MATCH (o:CanonicalConcept {canonical_id: $object_concept_id, tenant_id: $tenant_id})
        CREATE (sr)-[:SEMANTIC_OBJECT]->(o)

        RETURN sr.semantic_relation_id AS id
        """

        params = {
            "semantic_relation_id": relation.semantic_relation_id,
            "canonical_relation_id": relation.canonical_relation_id,
            "tenant_id": relation.tenant_id,
            "relation_type": relation_type_str,
            "subject_concept_id": relation.subject_concept_id,
            "object_concept_id": relation.object_concept_id,
            "semantic_grade": semantic_grade_str,
            "defensibility_tier": tier_str,
            "support_count": relation.support_strength.support_count,
            "explicit_count": relation.support_strength.explicit_count,
            "discursive_count": relation.support_strength.discursive_count,
            "doc_coverage": relation.support_strength.doc_coverage,
            "distinct_sections": relation.support_strength.distinct_sections,
            "bundle_diversity": relation.support_strength.bundle_diversity,
            "confidence": relation.confidence,
            "promoted_at": relation.promoted_at.isoformat(),
            "promotion_reason": relation.promotion_reason,
        }

        self._execute_query(query, params)

    def promote_batch(
        self,
        canonicals: List[CanonicalRelation],
        **kwargs
    ) -> List[SemanticRelation]:
        """
        Promote multiple CanonicalRelations.

        Args:
            canonicals: List of CanonicalRelation instances
            **kwargs: Additional args passed to promote_relation

        Returns:
            List of promoted SemanticRelations
        """
        promoted = []
        for canonical in canonicals:
            result = self.promote_relation(canonical, **kwargs)
            if result:
                promoted.append(result)

        logger.info(
            f"[SemanticRelationWriter] Promoted {len(promoted)}/{len(canonicals)} relations "
            f"(STRICT={self._stats['strict']}, EXTENDED={self._stats['extended']})"
        )

        return promoted

    def get_stats(self) -> Dict[str, int]:
        """Get promotion statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "promoted": 0,
            "strict": 0,
            "extended": 0,
            "explicit_grade": 0,
            "discursive_grade": 0,
            "mixed_grade": 0,
            "errors": 0
        }


# Singleton-like access
_writer_instance: Optional[SemanticRelationWriter] = None


def get_semantic_relation_writer(
    tenant_id: str = "default",
    **kwargs
) -> SemanticRelationWriter:
    """Get or create SemanticRelationWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = SemanticRelationWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
