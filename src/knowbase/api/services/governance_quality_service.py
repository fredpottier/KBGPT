"""
OSMOSE Graph Governance - Quality Layer

ADR_GRAPH_GOVERNANCE_LAYERS - Phase A

Ce service implémente la couche Quality/Confidence du framework de gouvernance.
Il calcule et persiste des métadonnées de qualité sur les relations existantes
SANS modifier leur sémantique.

IMPORTANT (garde-fous ADR):
- Les scores sont des indicateurs de CONSOMMATION, pas des décisions de VERITE
- confidence_tier=LOW signifie "moins de preuves", pas "probablement faux"
- Une relation LOW peut être parfaitement vraie (document rare mais fiable)
- Ces scores ne justifient JAMAIS la suppression d'une relation

Métriques calculées:
- evidence_count: Nombre d'éléments dans evidence_context_ids
- evidence_strength: Score normalisé (0-1) basé sur evidence_count
- confidence_tier: HIGH (>=5), MEDIUM (2-4), LOW (1), WEAK (0 ou CO_OCCURS)
- doc_coverage: Nombre de documents distincts (si applicable)

Date: 2026-01-07
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from datetime import datetime

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


class ConfidenceTier(str, Enum):
    """
    Tier de confiance basé sur le support probatoire.

    IMPORTANT: Ces tiers sont des indicateurs de SUPPORT, pas de VERITE.
    Une relation LOW n'est pas "fausse", elle a simplement moins de preuves.
    """
    HIGH = "HIGH"       # >= 5 preuves, support solide
    MEDIUM = "MEDIUM"   # 2-4 preuves, support modéré
    LOW = "LOW"         # 1 preuve, support minimal
    WEAK = "WEAK"       # 0 preuves ou CO_OCCURS_IN_CORPUS uniquement


# Seuils pour les tiers (configurables)
TIER_THRESHOLDS = {
    "high": 5,    # >= 5 preuves = HIGH
    "medium": 2,  # >= 2 preuves = MEDIUM
    "low": 1,     # >= 1 preuve = LOW
    # 0 = WEAK
}


@dataclass
class QualityScoringStats:
    """Statistiques du scoring qualité."""
    relations_scored: int = 0
    high_tier_count: int = 0
    medium_tier_count: int = 0
    low_tier_count: int = 0
    weak_tier_count: int = 0
    co_occurs_marked: int = 0
    avg_evidence_count: float = 0.0
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relations_scored": self.relations_scored,
            "tier_distribution": {
                "HIGH": self.high_tier_count,
                "MEDIUM": self.medium_tier_count,
                "LOW": self.low_tier_count,
                "WEAK": self.weak_tier_count,
            },
            "co_occurs_marked": self.co_occurs_marked,
            "avg_evidence_count": round(self.avg_evidence_count, 2),
            "high_confidence_ratio": round(
                self.high_tier_count / self.relations_scored * 100, 1
            ) if self.relations_scored > 0 else 0,
            "processing_time_ms": round(self.processing_time_ms, 1),
        }


@dataclass
class GovernanceMetrics:
    """Métriques de gouvernance du KG."""
    # Comptages par tier
    total_relations: int = 0
    high_tier: int = 0
    medium_tier: int = 0
    low_tier: int = 0
    weak_tier: int = 0

    # Relations sans scoring (à traiter)
    unscored_relations: int = 0

    # CO_OCCURS spécifiques
    co_occurs_count: int = 0

    # Ratios
    high_confidence_ratio: float = 0.0
    avg_evidence_count: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_relations": self.total_relations,
            "tier_distribution": {
                "HIGH": self.high_tier,
                "MEDIUM": self.medium_tier,
                "LOW": self.low_tier,
                "WEAK": self.weak_tier,
            },
            "unscored_relations": self.unscored_relations,
            "co_occurs_count": self.co_occurs_count,
            "high_confidence_ratio": round(self.high_confidence_ratio * 100, 1),
            "avg_evidence_count": round(self.avg_evidence_count, 2),
        }


class GovernanceQualityService:
    """
    Service de gouvernance qualité pour le Knowledge Graph.

    Implémente la Quality Layer de l'ADR Graph Governance Layers.
    Calcule et persiste des métadonnées de qualité sur les relations
    SANS modifier leur sémantique.
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

    def _execute_query(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Execute une requête Cypher."""
        if not self.neo4j.driver:
            return []

        database = getattr(self.neo4j, 'database', 'neo4j')
        with self.neo4j.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def compute_confidence_tier(self, evidence_count: int) -> ConfidenceTier:
        """
        Calcule le tier de confiance basé sur le nombre de preuves.

        Args:
            evidence_count: Nombre d'éléments dans evidence_context_ids

        Returns:
            ConfidenceTier correspondant
        """
        if evidence_count >= TIER_THRESHOLDS["high"]:
            return ConfidenceTier.HIGH
        elif evidence_count >= TIER_THRESHOLDS["medium"]:
            return ConfidenceTier.MEDIUM
        elif evidence_count >= TIER_THRESHOLDS["low"]:
            return ConfidenceTier.LOW
        else:
            return ConfidenceTier.WEAK

    def compute_evidence_strength(self, evidence_count: int) -> float:
        """
        Calcule un score de force probatoire normalisé (0-1).

        Utilise une fonction logarithmique pour éviter que 100 preuves
        ne soit "100x mieux" que 1 preuve.

        Args:
            evidence_count: Nombre de preuves

        Returns:
            Score entre 0 et 1
        """
        if evidence_count == 0:
            return 0.0

        import math
        # Log scaling: 1 preuve = 0.3, 5 preuves = 0.7, 10+ = ~0.9
        # Formule: min(1.0, 0.3 + 0.4 * log2(evidence_count))
        score = 0.3 + 0.4 * math.log2(max(1, evidence_count))
        return min(1.0, score)

    async def score_all_relations(self) -> QualityScoringStats:
        """
        Calcule et persiste les scores de qualité sur TOUTES les relations.

        Cette méthode est idempotente - peut être exécutée plusieurs fois.
        Elle met à jour les propriétés:
        - evidence_count: int
        - evidence_strength: float
        - confidence_tier: string (HIGH/MEDIUM/LOW/WEAK)
        - governance_scored_at: datetime

        Returns:
            QualityScoringStats avec les résultats
        """
        start_time = datetime.now()
        stats = QualityScoringStats()

        logger.info(f"[Governance:Quality] Starting quality scoring for tenant={self.tenant_id}")

        # 1. Scorer les relations sémantiques (avec evidence_context_ids)
        query_semantic = """
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[r]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.evidence_context_ids IS NOT NULL
          AND type(r) <> 'CO_OCCURS_IN_CORPUS'
        WITH r,
             size(r.evidence_context_ids) AS ev_count
        SET r.evidence_count = ev_count,
            r.evidence_strength = CASE
              WHEN ev_count = 0 THEN 0.0
              WHEN ev_count = 1 THEN 0.3
              WHEN ev_count = 2 THEN 0.5
              WHEN ev_count = 3 THEN 0.6
              WHEN ev_count = 4 THEN 0.65
              WHEN ev_count >= 5 THEN 0.7 + (0.3 * (1 - 1.0/(ev_count - 4)))
              ELSE 0.3
            END,
            r.confidence_tier = CASE
              WHEN ev_count >= 5 THEN 'HIGH'
              WHEN ev_count >= 2 THEN 'MEDIUM'
              WHEN ev_count >= 1 THEN 'LOW'
              ELSE 'WEAK'
            END,
            r.governance_scored_at = datetime()
        RETURN
            count(r) AS total,
            sum(CASE WHEN ev_count >= 5 THEN 1 ELSE 0 END) AS high_count,
            sum(CASE WHEN ev_count >= 2 AND ev_count < 5 THEN 1 ELSE 0 END) AS medium_count,
            sum(CASE WHEN ev_count = 1 THEN 1 ELSE 0 END) AS low_count,
            sum(CASE WHEN ev_count = 0 THEN 1 ELSE 0 END) AS weak_count,
            avg(ev_count) AS avg_ev
        """

        results = self._execute_query(query_semantic, {"tenant_id": self.tenant_id})

        if results:
            r = results[0]
            stats.relations_scored = r.get("total", 0) or 0
            stats.high_tier_count = r.get("high_count", 0) or 0
            stats.medium_tier_count = r.get("medium_count", 0) or 0
            stats.low_tier_count = r.get("low_count", 0) or 0
            stats.weak_tier_count = r.get("weak_count", 0) or 0
            stats.avg_evidence_count = r.get("avg_ev", 0.0) or 0.0

        # 2. Marquer les CO_OCCURS_IN_CORPUS comme WEAK systématiquement
        query_co_occurs = """
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[r:CO_OCCURS_IN_CORPUS]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        SET r.evidence_count = coalesce(r.doc_count, 0),
            r.evidence_strength = 0.1,
            r.confidence_tier = 'WEAK',
            r.governance_scored_at = datetime()
        RETURN count(r) AS co_occurs_count
        """

        co_results = self._execute_query(query_co_occurs, {"tenant_id": self.tenant_id})
        if co_results:
            stats.co_occurs_marked = co_results[0].get("co_occurs_count", 0) or 0
            stats.weak_tier_count += stats.co_occurs_marked

        # 3. Scorer les relations sans evidence_context_ids (legacy)
        query_legacy = """
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[r]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.evidence_context_ids IS NULL
          AND type(r) <> 'CO_OCCURS_IN_CORPUS'
          AND r.confidence_tier IS NULL
        SET r.evidence_count = 0,
            r.evidence_strength = 0.0,
            r.confidence_tier = 'WEAK',
            r.governance_scored_at = datetime()
        RETURN count(r) AS legacy_count
        """

        legacy_results = self._execute_query(query_legacy, {"tenant_id": self.tenant_id})
        if legacy_results:
            legacy_count = legacy_results[0].get("legacy_count", 0) or 0
            stats.weak_tier_count += legacy_count
            stats.relations_scored += legacy_count

        # Calculer le temps de traitement
        stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(
            f"[Governance:Quality] Scoring complete: "
            f"{stats.relations_scored} relations scored, "
            f"HIGH={stats.high_tier_count}, MEDIUM={stats.medium_tier_count}, "
            f"LOW={stats.low_tier_count}, WEAK={stats.weak_tier_count}"
        )

        return stats

    async def get_governance_metrics(self) -> GovernanceMetrics:
        """
        Récupère les métriques de gouvernance actuelles.

        Returns:
            GovernanceMetrics avec l'état actuel du KG
        """
        metrics = GovernanceMetrics()

        # Comptage par tier
        query_tiers = """
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[r]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE type(r) <> 'MENTIONED_IN'
          AND type(r) <> 'IN_DOC'
          AND type(r) <> 'INSTANCE_OF'
          AND type(r) <> 'HAS_TOPIC'
          AND type(r) <> 'COVERS'
        RETURN
            count(r) AS total,
            sum(CASE WHEN r.confidence_tier = 'HIGH' THEN 1 ELSE 0 END) AS high,
            sum(CASE WHEN r.confidence_tier = 'MEDIUM' THEN 1 ELSE 0 END) AS medium,
            sum(CASE WHEN r.confidence_tier = 'LOW' THEN 1 ELSE 0 END) AS low,
            sum(CASE WHEN r.confidence_tier = 'WEAK' THEN 1 ELSE 0 END) AS weak,
            sum(CASE WHEN r.confidence_tier IS NULL THEN 1 ELSE 0 END) AS unscored,
            sum(CASE WHEN type(r) = 'CO_OCCURS_IN_CORPUS' THEN 1 ELSE 0 END) AS co_occurs,
            avg(coalesce(r.evidence_count, 0)) AS avg_ev
        """

        results = self._execute_query(query_tiers, {"tenant_id": self.tenant_id})

        if results:
            r = results[0]
            metrics.total_relations = r.get("total", 0) or 0
            metrics.high_tier = r.get("high", 0) or 0
            metrics.medium_tier = r.get("medium", 0) or 0
            metrics.low_tier = r.get("low", 0) or 0
            metrics.weak_tier = r.get("weak", 0) or 0
            metrics.unscored_relations = r.get("unscored", 0) or 0
            metrics.co_occurs_count = r.get("co_occurs", 0) or 0
            metrics.avg_evidence_count = r.get("avg_ev", 0.0) or 0.0

            if metrics.total_relations > 0:
                metrics.high_confidence_ratio = metrics.high_tier / metrics.total_relations

        return metrics

    async def get_relations_by_tier(
        self,
        tier: ConfidenceTier,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Récupère les relations d'un tier spécifique.

        Utile pour l'UI d'exploration par niveau de confiance.

        Args:
            tier: Tier à filtrer
            limit: Nombre max de résultats

        Returns:
            Liste de relations avec leurs métadonnées
        """
        query = """
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[r]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.confidence_tier = $tier
        RETURN
            c1.canonical_name AS subject,
            type(r) AS predicate,
            c2.canonical_name AS object,
            r.evidence_count AS evidence_count,
            r.evidence_strength AS evidence_strength,
            r.confidence_tier AS confidence_tier,
            r.evidence_context_ids AS evidence_ids
        ORDER BY r.evidence_count DESC
        LIMIT $limit
        """

        return self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "tier": tier.value,
            "limit": limit
        })


# Singleton
_governance_quality_service: Optional[GovernanceQualityService] = None


def get_governance_quality_service(tenant_id: str = "default") -> GovernanceQualityService:
    """Récupère le service de gouvernance qualité."""
    global _governance_quality_service
    if _governance_quality_service is None or _governance_quality_service.tenant_id != tenant_id:
        _governance_quality_service = GovernanceQualityService(tenant_id=tenant_id)
    return _governance_quality_service


__all__ = [
    "ConfidenceTier",
    "QualityScoringStats",
    "GovernanceMetrics",
    "GovernanceQualityService",
    "get_governance_quality_service",
]
