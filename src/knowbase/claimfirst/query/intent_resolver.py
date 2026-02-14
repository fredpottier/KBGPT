# src/knowbase/claimfirst/query/intent_resolver.py
"""
IntentResolver - Résolution d'intention avec disambiguation.

INV-18: Disambiguation UI enrichie (sample + facets + entities)
INV-24: ≥2 candidats sauf exact match lexical (garde-fou)

C3: Garde-fou lexical - jamais réduire à 1 candidat sans exact match.
- Seuils numériques: DELTA_THRESHOLD = 0.15, MIN_CONFIDENCE = 0.75
- MAIS jamais 1 candidat sans identification explicite (lexicale)
- MAX_SOFT_CLUSTERS = 3 si pas d'exact match
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# C3: Seuils pour filtrage des candidats
DELTA_THRESHOLD = 0.15  # Écart minimum entre candidats pour considérer un seul
MIN_CONFIDENCE = 0.75   # Confiance minimum pour retenir un candidat
MAX_SOFT_CLUSTERS = 3   # Maximum de clusters à retourner si pas d'exact match


@dataclass
class ClusterCandidate:
    """
    Candidat cluster pour la résolution d'intention.

    Attributes:
        cluster_id: ID du cluster
        label: Label du cluster
        score: Score de match (0-1)
        entities: Entités principales du cluster
        facets: Facettes dominantes
        doc_count: Nombre de documents
        claim_count: Nombre de claims
        sample_claim_text: Exemple de claim (pour disambiguation UI)
    """
    cluster_id: str
    label: str
    score: float
    entities: List[str] = field(default_factory=list)
    facets: List[str] = field(default_factory=list)
    doc_count: int = 0
    claim_count: int = 0
    sample_claim_text: Optional[str] = None


class DisambiguationOption(BaseModel):
    """
    Option de disambiguation pour l'UI (INV-18 enrichie).

    Attributes:
        cluster_id: ID du cluster
        label: Label affiché
        sample_claim_text: Exemple de claim du cluster
        facet_names: Facettes dominantes
        entity_names: Entités principales
        doc_count: Nombre de documents source
        scope_preview: Aperçu du scope (contextes couverts)
    """

    cluster_id: str = Field(..., description="ID du cluster")
    label: str = Field(..., description="Label du cluster")
    sample_claim_text: str = Field(..., description="Exemple de claim")
    facet_names: List[str] = Field(default_factory=list, description="Facettes dominantes")
    entity_names: List[str] = Field(default_factory=list, description="Entités principales")
    doc_count: int = Field(default=0, description="Nombre de documents")
    scope_preview: Optional[str] = Field(default=None, description="Aperçu du scope")


class TargetClaimIntent(BaseModel):
    """
    Intention résolue pour une requête.

    INV-24: candidate_clusters a ≥2 éléments sauf exact match lexical.

    Attributes:
        query: Requête originale
        candidate_clusters: Clusters candidats (≥2 sauf exact match - INV-24)
        disambiguation_needed: Si disambiguation requise
        disambiguation_options: Options enrichies pour l'UI
        selected_cluster_id: Cluster sélectionné si non ambigu
        exact_match: Si un exact match lexical a été trouvé
        confidence: Confiance dans la résolution
    """

    query: str = Field(..., description="Requête originale")

    candidate_clusters: List[str] = Field(
        default_factory=list,
        description="IDs des clusters candidats (jamais 1 sauf exact match - INV-24)"
    )

    disambiguation_needed: bool = Field(
        default=False,
        description="Si l'utilisateur doit choisir"
    )

    disambiguation_options: List[DisambiguationOption] = Field(
        default_factory=list,
        description="Options enrichies pour disambiguation UI"
    )

    selected_cluster_id: Optional[str] = Field(
        default=None,
        description="Cluster sélectionné (si non ambigu)"
    )

    exact_match: bool = Field(
        default=False,
        description="Si exact match lexical trouvé"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance dans la résolution"
    )


class IntentResolver:
    """
    Résout l'intention d'une requête vers des clusters de claims.

    INV-18: Disambiguation UI enrichie
    INV-24: Garde-fou lexical - ≥2 candidats sauf exact match

    C3: Le garde-fou est LEXICAL, pas juste numérique.
    Un seul candidat n'est autorisé que si _is_explicit_identification() == True.
    """

    def __init__(
        self,
        neo4j_driver: Optional[Any] = None,
        embeddings_client: Optional[Any] = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le resolver.

        Args:
            neo4j_driver: Driver Neo4j pour accès aux clusters
            embeddings_client: Client embeddings pour scoring
            tenant_id: Tenant ID
        """
        self.neo4j_driver = neo4j_driver
        self.embeddings_client = embeddings_client
        self.tenant_id = tenant_id

        self.stats = {
            "queries_resolved": 0,
            "exact_matches": 0,
            "disambiguations_needed": 0,
            "single_candidates_blocked": 0,
        }

    def resolve(
        self,
        query: str,
        candidates: List[ClusterCandidate],
        force_disambiguation: bool = False,
    ) -> TargetClaimIntent:
        """
        Résout l'intention d'une requête.

        INV-24 + C3: Garde-fou lexical.
        - Si ≤1 candidat après filtrage MAIS pas d'exact match → force ≥2
        - Exact match = mention explicite du label ou entité dans la query

        Args:
            query: Requête utilisateur
            candidates: Clusters candidats avec scores
            force_disambiguation: Forcer la disambiguation

        Returns:
            TargetClaimIntent avec candidats et options
        """
        self.stats["queries_resolved"] += 1

        if not candidates:
            return TargetClaimIntent(
                query=query,
                candidate_clusters=[],
                disambiguation_needed=True,
                confidence=0.0,
            )

        # Trier par score décroissant
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)

        # Filtrer par seuil minimum
        filtered = [c for c in sorted_candidates if c.score >= MIN_CONFIDENCE]

        if not filtered:
            # Aucun candidat au-dessus du seuil → prendre les top 3
            filtered = sorted_candidates[:MAX_SOFT_CLUSTERS]

        # C3: Vérifier exact match lexical
        exact_match_candidate = self._find_exact_match(query, filtered)

        if exact_match_candidate:
            # Exact match trouvé → 1 candidat autorisé
            self.stats["exact_matches"] += 1
            return TargetClaimIntent(
                query=query,
                candidate_clusters=[exact_match_candidate.cluster_id],
                disambiguation_needed=False,
                disambiguation_options=[self._to_option(exact_match_candidate)],
                selected_cluster_id=exact_match_candidate.cluster_id,
                exact_match=True,
                confidence=exact_match_candidate.score,
            )

        # INV-24: Sans exact match, jamais réduire à 1 candidat
        if len(filtered) == 1:
            # Ajouter le 2ème meilleur pour respecter INV-24
            if len(sorted_candidates) > 1:
                filtered.append(sorted_candidates[1])
            self.stats["single_candidates_blocked"] += 1
            logger.debug(
                f"[OSMOSE:IntentResolver] INV-24: Added second candidate "
                f"(no exact match for '{query}')"
            )

        # Vérifier si le delta entre top-2 est suffisant
        if len(filtered) >= 2:
            delta = filtered[0].score - filtered[1].score
            needs_disambiguation = delta < DELTA_THRESHOLD or force_disambiguation
        else:
            needs_disambiguation = True

        # Limiter à MAX_SOFT_CLUSTERS
        final_candidates = filtered[:MAX_SOFT_CLUSTERS]

        # Construire les options de disambiguation (INV-18 enrichies)
        options = [self._to_option(c) for c in final_candidates]

        if needs_disambiguation:
            self.stats["disambiguations_needed"] += 1

        return TargetClaimIntent(
            query=query,
            candidate_clusters=[c.cluster_id for c in final_candidates],
            disambiguation_needed=needs_disambiguation,
            disambiguation_options=options,
            selected_cluster_id=final_candidates[0].cluster_id if not needs_disambiguation else None,
            exact_match=False,
            confidence=final_candidates[0].score if final_candidates else 0.0,
        )

    def _find_exact_match(
        self,
        query: str,
        candidates: List[ClusterCandidate],
    ) -> Optional[ClusterCandidate]:
        """
        Cherche un exact match lexical dans les candidats.

        C3: Exact match = mention explicite dans la query.
        - Label du cluster apparaît textuellement
        - Ou entité/facet du cluster mentionnée explicitement

        Args:
            query: Requête utilisateur
            candidates: Candidats à vérifier

        Returns:
            Candidat avec exact match ou None
        """
        query_lower = query.lower()

        for candidate in candidates:
            if self._is_explicit_identification(query_lower, candidate):
                return candidate

        return None

    def _is_explicit_identification(
        self,
        query_lower: str,
        candidate: ClusterCandidate,
    ) -> bool:
        """
        Vérifie si la query identifie explicitement ce candidat.

        C3: Garde-fou LEXICAL, pas numérique.

        Args:
            query_lower: Query en lowercase
            candidate: Candidat à vérifier

        Returns:
            True si identification explicite
        """
        # Check 1: Label du cluster apparaît textuellement
        label_lower = candidate.label.lower()
        if len(label_lower) >= 4 and label_lower in query_lower:
            return True

        # Check 2: Mots significatifs du label (≥4 chars) présents
        label_words = [w for w in label_lower.split() if len(w) >= 4]
        if label_words:
            matches = sum(1 for w in label_words if w in query_lower)
            if matches >= len(label_words) * 0.7:  # 70% des mots matchent
                return True

        # Check 3: Entité mentionnée explicitement
        for entity in candidate.entities:
            entity_lower = entity.lower()
            if len(entity_lower) >= 4 and entity_lower in query_lower:
                return True

        # Check 4: Facette mentionnée explicitement
        for facet in candidate.facets:
            facet_lower = facet.lower()
            if len(facet_lower) >= 4 and facet_lower in query_lower:
                return True

        return False

    def _to_option(self, candidate: ClusterCandidate) -> DisambiguationOption:
        """
        Convertit un candidat en option de disambiguation enrichie (INV-18).

        Args:
            candidate: Candidat à convertir

        Returns:
            DisambiguationOption enrichie
        """
        return DisambiguationOption(
            cluster_id=candidate.cluster_id,
            label=candidate.label,
            sample_claim_text=candidate.sample_claim_text or f"Claims about {candidate.label}",
            facet_names=candidate.facets[:3],  # Top 3 facettes
            entity_names=candidate.entities[:5],  # Top 5 entités
            doc_count=candidate.doc_count,
            scope_preview=f"{candidate.doc_count} documents, {candidate.claim_count} claims",
        )

    def resolve_from_neo4j(
        self,
        query: str,
        limit: int = 10,
    ) -> TargetClaimIntent:
        """
        Résout l'intention en chargeant les clusters depuis Neo4j.

        Args:
            query: Requête utilisateur
            limit: Nombre max de clusters à considérer

        Returns:
            TargetClaimIntent
        """
        if not self.neo4j_driver:
            return TargetClaimIntent(
                query=query,
                candidate_clusters=[],
                disambiguation_needed=True,
                confidence=0.0,
            )

        # Charger les clusters candidats
        candidates = self._load_candidates_from_neo4j(query, limit)

        return self.resolve(query, candidates)

    def _load_candidates_from_neo4j(
        self,
        query: str,
        limit: int,
    ) -> List[ClusterCandidate]:
        """
        Charge les clusters candidats depuis Neo4j.

        Args:
            query: Requête pour scoring
            limit: Nombre max de clusters

        Returns:
            Liste de ClusterCandidate
        """
        candidates = []

        try:
            with self.neo4j_driver.session() as session:
                # Recherche fulltext sur le label des clusters
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes('claim_text_search', $query)
                    YIELD node AS claim, score
                    WITH claim, score
                    WHERE (claim.archived IS NULL OR claim.archived = false)
                    MATCH (claim)-[:IN_CLUSTER]->(cluster:ClaimCluster {tenant_id: $tenant_id})
                    WITH cluster, max(score) as max_score, count(claim) as matching_claims
                    MATCH (c:Claim)-[:IN_CLUSTER]->(cluster)
                    WITH cluster, max_score, matching_claims, count(c) as total_claims
                    OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cluster)
                    OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
                    OPTIONAL MATCH (c)-[:HAS_FACET]->(f:Facet)
                    WITH cluster, max_score, matching_claims, total_claims,
                         collect(DISTINCT e.name)[0..5] as entities,
                         collect(DISTINCT f.name)[0..3] as facets,
                         collect(c.text)[0] as sample_text
                    RETURN cluster.cluster_id as cluster_id,
                           cluster.canonical_label as label,
                           max_score as score,
                           cluster.doc_count as doc_count,
                           total_claims as claim_count,
                           entities,
                           facets,
                           sample_text
                    ORDER BY max_score DESC
                    LIMIT $limit
                    """,
                    query=query,
                    tenant_id=self.tenant_id,
                    limit=limit,
                )

                for record in result:
                    candidates.append(ClusterCandidate(
                        cluster_id=record["cluster_id"],
                        label=record["label"] or "Unknown",
                        score=min(record["score"] / 10.0, 1.0),  # Normaliser
                        entities=record["entities"] or [],
                        facets=record["facets"] or [],
                        doc_count=record["doc_count"] or 0,
                        claim_count=record["claim_count"] or 0,
                        sample_claim_text=record["sample_text"],
                    ))

        except Exception as e:
            logger.warning(f"[OSMOSE:IntentResolver] Neo4j query failed: {e}")

        return candidates

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "queries_resolved": 0,
            "exact_matches": 0,
            "disambiguations_needed": 0,
            "single_candidates_blocked": 0,
        }


__all__ = [
    "IntentResolver",
    "TargetClaimIntent",
    "DisambiguationOption",
    "ClusterCandidate",
    "DELTA_THRESHOLD",
    "MIN_CONFIDENCE",
    "MAX_SOFT_CLUSTERS",
]
