"""
Knowledge Proof Service - OSMOSE Answer+Proof Bloc B

Genere le resume structure de l'etat de la connaissance pour une reponse.
Ce service collecte les metriques depuis le KG et les formate pour l'UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from collections import Counter

from knowbase.config.settings import Settings
from knowbase.common.logging import setup_logging
from .confidence_engine import (
    EpistemicState,
    ContractState,
    KGSignals,
    DomainSignals,
    get_confidence_engine,
)

_settings = Settings()
logger = setup_logging(_settings.logs_dir, "knowledge_proof_service.log")


@dataclass
class KnowledgeProofSummary:
    """Resume de l'etat de la connaissance (Bloc B)."""

    # Fondements
    concepts_count: int = 0
    relations_count: int = 0
    relation_types: List[str] = field(default_factory=list)
    sources_count: int = 0

    # Coherence (basee sur Confidence Engine)
    contradictions_count: int = 0
    coherence_status: str = "unknown"  # "coherent", "debate", "incomplete"

    # Solidite (metriques KG)
    maturity_percent: float = 0.0
    avg_confidence: float = 0.0

    # Nature (extensible via LivingOntology)
    dominant_concept_types: List[str] = field(default_factory=list)
    solidity: str = "Fragile"  # "Fragile", "Partielle", "Etablie"

    # Etat global (calcule par Confidence Engine)
    epistemic_state: EpistemicState = EpistemicState.INCOMPLETE
    contract_state: ContractState = ContractState.COVERED

    # KG Signals bruts pour audit
    kg_signals: Optional[KGSignals] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour l'API."""
        return {
            "concepts_count": self.concepts_count,
            "relations_count": self.relations_count,
            "relation_types": self.relation_types,
            "sources_count": self.sources_count,
            "contradictions_count": self.contradictions_count,
            "coherence_status": self.coherence_status,
            "maturity_percent": self.maturity_percent,
            "avg_confidence": self.avg_confidence,
            "dominant_concept_types": self.dominant_concept_types,
            "solidity": self.solidity,
            "epistemic_state": self.epistemic_state.value,
            "contract_state": self.contract_state.value,
        }


def get_dominant_concept_types(concept_types: List[str], top_n: int = 3) -> List[str]:
    """
    Retourne les types de concepts les plus frequents.

    Note: Les types proviennent de LivingOntology et sont extensibles.
    Aucun mapping hardcode - on retourne les types tels quels.
    """
    if not concept_types:
        return []
    counts = Counter(concept_types)
    return [t for t, _ in counts.most_common(top_n)]


def determine_solidity(avg_confidence: float, sources_count: int) -> str:
    """Determine la solidite de la reponse."""
    if avg_confidence >= 0.8 and sources_count >= 2:
        return "Etablie"
    elif avg_confidence >= 0.5:
        return "Partielle"
    else:
        return "Fragile"


def determine_coherence_status(epistemic_state: EpistemicState) -> str:
    """Mappe l'etat epistemique vers un status de coherence."""
    if epistemic_state == EpistemicState.DEBATE:
        return "debate"
    elif epistemic_state == EpistemicState.INCOMPLETE:
        return "incomplete"
    else:
        return "coherent"


class KnowledgeProofService:
    """Service pour construire le Knowledge Proof Summary (Bloc B)."""

    def __init__(self, neo4j_driver=None):
        """Initialise le service avec un driver Neo4j optionnel."""
        self._neo4j_driver = neo4j_driver
        self._confidence_engine = get_confidence_engine()

    def _get_neo4j_driver(self):
        """Recupere le driver Neo4j (lazy loading)."""
        if self._neo4j_driver is None:
            try:
                from knowbase.semantic.clients.neo4j_client import get_neo4j_driver
                self._neo4j_driver = get_neo4j_driver()
            except Exception as e:
                logger.warning(f"Could not get Neo4j driver: {e}")
                return None
        return self._neo4j_driver

    def build_proof_summary(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        sources: List[str],
        tenant_id: str = "default",
        domain_signals: Optional[DomainSignals] = None,
    ) -> KnowledgeProofSummary:
        """
        Construit le Knowledge Proof Summary.

        Args:
            query_concepts: Concepts identifies dans la question
            related_concepts: Relations du graph_context
            sources: Documents sources utilises
            tenant_id: Tenant ID
            domain_signals: Signaux domaine (optionnel)

        Returns:
            KnowledgeProofSummary
        """
        # Collecter les metriques depuis le KG
        kg_metrics = self._collect_kg_metrics(
            query_concepts,
            related_concepts,
            tenant_id
        )

        # Calculer les KG Signals
        kg_signals = KGSignals(
            typed_edges_count=kg_metrics.get("relations_count", 0),
            avg_conf=kg_metrics.get("avg_confidence", 0.0),
            validated_ratio=kg_metrics.get("maturity_ratio", 0.0),
            conflicts_count=kg_metrics.get("conflicts_count", 0),
            orphan_concepts_count=kg_metrics.get("orphan_count", 0),
            independent_sources_count=len(sources) if sources else 0,
            expected_edges_missing_count=0,  # A implementer
        )

        # Domain signals par defaut si non fourni
        if domain_signals is None:
            domain_signals = DomainSignals(
                in_scope_domains=[],
                matched_domains=["default"],  # Assume COVERED par defaut
            )

        # Evaluer via Confidence Engine
        confidence_result = self._confidence_engine.evaluate(kg_signals, domain_signals)

        # Construire le summary
        return KnowledgeProofSummary(
            concepts_count=kg_metrics.get("concepts_count", 0),
            relations_count=kg_metrics.get("relations_count", 0),
            relation_types=kg_metrics.get("relation_types", []),
            sources_count=len(sources) if sources else 0,
            contradictions_count=kg_metrics.get("conflicts_count", 0),
            coherence_status=determine_coherence_status(confidence_result.epistemic_state),
            maturity_percent=kg_metrics.get("maturity_ratio", 0.0) * 100,
            avg_confidence=kg_metrics.get("avg_confidence", 0.0),
            dominant_concept_types=kg_metrics.get("dominant_types", []),
            solidity=determine_solidity(
                kg_metrics.get("avg_confidence", 0.0),
                len(sources) if sources else 0
            ),
            epistemic_state=confidence_result.epistemic_state,
            contract_state=confidence_result.contract_state,
            kg_signals=kg_signals,
        )

    def _collect_kg_metrics(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        Collecte les metriques depuis le KG.

        Essaie d'abord Neo4j, puis fallback sur les donnees du graph_context.
        """
        # Tenter la requete Neo4j
        neo4j_metrics = self._query_neo4j_metrics(query_concepts, tenant_id)
        if neo4j_metrics:
            return neo4j_metrics

        # Fallback: calculer depuis related_concepts
        return self._compute_from_graph_context(query_concepts, related_concepts)

    def _query_neo4j_metrics(
        self,
        concept_names: List[str],
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Execute une requete Cypher pour collecter les metriques."""
        driver = self._get_neo4j_driver()
        if not driver or not concept_names:
            return None

        try:
            cypher = """
            UNWIND $concept_names AS name
            MATCH (c:CanonicalConcept {tenant_id: $tid})
            WHERE toLower(c.canonical_name) = toLower(name)
            OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept {tenant_id: $tid})
            WHERE type(r) <> 'ASSOCIATED_WITH'

            WITH
              collect(DISTINCT c) AS concepts,
              collect(DISTINCT r) AS relations,
              collect(DISTINCT type(r)) AS relation_types,
              collect(DISTINCT c.concept_type) AS concept_types

            UNWIND relations AS rel
            WITH
              concepts,
              relations,
              relation_types,
              concept_types,
              CASE WHEN rel IS NOT NULL THEN rel.confidence ELSE null END AS conf,
              CASE WHEN rel IS NOT NULL AND rel.maturity = 'VALIDATED' THEN 1 ELSE 0 END AS validated,
              CASE WHEN type(rel) = 'CONFLICTS_WITH' THEN 1 ELSE 0 END AS conflict

            RETURN
              size(concepts) AS concepts_count,
              size(relations) AS relations_count,
              relation_types,
              concept_types,
              avg(conf) AS avg_confidence,
              toFloat(sum(validated)) / CASE WHEN size(relations) > 0 THEN size(relations) ELSE 1 END AS maturity_ratio,
              sum(conflict) AS conflicts_count
            """

            with driver.session() as session:
                result = session.run(cypher, {
                    "concept_names": concept_names,
                    "tid": tenant_id,
                })
                record = result.single()

                if record:
                    concept_types = record.get("concept_types", []) or []
                    relation_types = record.get("relation_types", []) or []
                    # Filtrer les None
                    relation_types = [t for t in relation_types if t]

                    return {
                        "concepts_count": record.get("concepts_count", 0) or 0,
                        "relations_count": record.get("relations_count", 0) or 0,
                        "relation_types": relation_types,
                        "avg_confidence": record.get("avg_confidence", 0.0) or 0.0,
                        "maturity_ratio": record.get("maturity_ratio", 0.0) or 0.0,
                        "conflicts_count": record.get("conflicts_count", 0) or 0,
                        "orphan_count": 0,  # A calculer separement si besoin
                        "dominant_types": get_dominant_concept_types(concept_types),
                    }

        except Exception as e:
            logger.warning(f"Neo4j query failed: {e}")

        return None

    def _compute_from_graph_context(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Calcule les metriques depuis les donnees du graph_context.

        Fallback quand Neo4j n'est pas disponible.
        """
        if not related_concepts:
            return {
                "concepts_count": len(query_concepts) if query_concepts else 0,
                "relations_count": 0,
                "relation_types": [],
                "avg_confidence": 0.0,
                "maturity_ratio": 0.0,
                "conflicts_count": 0,
                "orphan_count": len(query_concepts) if query_concepts else 0,
                "dominant_types": [],
            }

        # Compter les concepts uniques
        all_concepts = set(query_concepts or [])
        for rel in related_concepts:
            if rel.get("source"):
                all_concepts.add(rel["source"])
            if rel.get("concept"):
                all_concepts.add(rel["concept"])

        # Extraire les types de relations
        relation_types = []
        confidences = []
        conflicts = 0

        for rel in related_concepts:
            rel_type = rel.get("relation")
            if rel_type:
                relation_types.append(rel_type)
                if rel_type == "CONFLICTS_WITH":
                    conflicts += 1

            conf = rel.get("confidence", 0.0)
            if conf:
                confidences.append(conf)

        # Types uniques
        unique_types = list(set(relation_types))

        # Moyenne confidence
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "concepts_count": len(all_concepts),
            "relations_count": len(related_concepts),
            "relation_types": unique_types,
            "avg_confidence": avg_conf,
            "maturity_ratio": 0.5,  # Estimation par defaut
            "conflicts_count": conflicts,
            "orphan_count": 0,
            "dominant_types": [],  # Pas disponible sans Neo4j
        }


# === Singleton ===

_knowledge_proof_service: Optional[KnowledgeProofService] = None


def get_knowledge_proof_service() -> KnowledgeProofService:
    """Retourne l'instance singleton du KnowledgeProofService."""
    global _knowledge_proof_service
    if _knowledge_proof_service is None:
        _knowledge_proof_service = KnowledgeProofService()
    return _knowledge_proof_service


__all__ = [
    "KnowledgeProofSummary",
    "KnowledgeProofService",
    "get_knowledge_proof_service",
    "get_dominant_concept_types",
    "determine_solidity",
]
