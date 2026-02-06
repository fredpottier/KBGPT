# src/knowbase/claimfirst/query/temporal_query_engine.py
"""
TemporalQueryEngine - Moteur de requêtes temporelles.

Questions supportées:
A. Since when? - Depuis quand cette capability existe?
B. Still applicable? - Est-ce encore applicable aujourd'hui?
C. Context comparison? - Différences entre contextes A et B?

INV-14: compare() → None si ordre inconnu
INV-17: REMOVED seulement si explicitement documenté
INV-19: ClaimKey candidate → pas de "since when" (timeline = validated only)
INV-23: Toute réponse cite explicitement ses claims sources

S6: V1 assume timeline = cluster-based conservative
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
)
from knowbase.claimfirst.query.latest_selector import (
    LatestSelector,
    LatestPolicy,
    DocumentCandidate,
)
from knowbase.claimfirst.query.uncertainty_signals import (
    UncertaintyAnalysis,
    UncertaintySignal,
    UncertaintySignalType,
)

logger = logging.getLogger(__name__)


class SinceWhenResult(BaseModel):
    """
    Résultat d'une requête "Since when?".

    INV-19: Refuse timeline si ClaimKey candidate (pas validated).
    INV-23: Cite explicitement les claims sources.

    Attributes:
        capability: Capability demandée
        first_occurrence_context: Premier contexte où apparaît
        first_occurrence_claims: Claims sources (INV-23)
        timeline: Timeline ordonnée (None si ordering UNKNOWN)
        timeline_basis: Base de la timeline (S6: "cluster" en V1)
        ordering_confidence: Niveau de confiance dans l'ordre
        refused: Si requête refusée (INV-19)
        refused_reason: Raison du refus
    """

    capability: str = Field(..., description="Capability recherchée")

    first_occurrence_context: Optional[str] = Field(
        default=None,
        description="Premier contexte où la capability apparaît"
    )

    first_occurrence_claims: List[str] = Field(
        default_factory=list,
        description="IDs des claims sources (INV-23 traçabilité)"
    )

    timeline: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Timeline ordonnée [{context, claims}] (None si UNKNOWN)"
    )

    timeline_basis: str = Field(
        default="cluster",
        description="Base de la timeline: 'cluster' (V1) ou 'claimkey' (V2)"
    )

    ordering_confidence: Optional[str] = Field(
        default=None,
        description="Niveau de confiance: CERTAIN, INFERRED, UNKNOWN"
    )

    refused: bool = Field(
        default=False,
        description="Si la requête a été refusée"
    )

    refused_reason: Optional[str] = Field(
        default=None,
        description="Raison du refus (INV-19)"
    )


class StillApplicableResult(BaseModel):
    """
    Résultat d'une requête "Still applicable?".

    INV-17: REMOVED seulement si explicitement documenté.
    INV-23: Cite explicitement les claims sources.

    Attributes:
        claim_id: Claim analysée
        claim_text: Texte de la claim
        is_applicable: True/False/None (uncertain)
        status: APPLICABLE, REMOVED, SUPERSEDED, UNCERTAIN
        latest_context: Contexte latest utilisé
        supporting_claims: Claims qui supportent la réponse (INV-23)
        uncertainty_analysis: Analyse si statut UNCERTAIN
    """

    claim_id: str = Field(..., description="ID de la claim analysée")

    claim_text: str = Field(..., description="Texte de la claim")

    is_applicable: Optional[bool] = Field(
        default=None,
        description="True=applicable, False=removed, None=uncertain"
    )

    status: str = Field(
        default="UNCERTAIN",
        description="APPLICABLE | REMOVED | SUPERSEDED | UNCERTAIN"
    )

    latest_context: Optional[str] = Field(
        default=None,
        description="Contexte latest utilisé pour la vérification"
    )

    supporting_claims: List[str] = Field(
        default_factory=list,
        description="IDs des claims sources (INV-23 traçabilité)"
    )

    removal_evidence: Optional[str] = Field(
        default=None,
        description="Evidence de suppression si status=REMOVED"
    )

    uncertainty_analysis: Optional[UncertaintyAnalysis] = Field(
        default=None,
        description="Analyse d'incertitude si status=UNCERTAIN"
    )

    model_config = {"arbitrary_types_allowed": True}


class TemporalQueryEngine:
    """
    Moteur de requêtes temporelles pour le pipeline Claim-First.

    Questions A, B, C:
    A. Since when? (query_since_when)
    B. Still applicable? (query_still_applicable)
    C. Context comparison? (compare_contexts)

    S6: V1 utilise timeline cluster-based conservative.
    """

    def __init__(
        self,
        neo4j_driver: Optional[Any] = None,
        tenant_id: str = "default",
        latest_selector: Optional[LatestSelector] = None,
    ):
        """
        Initialise le moteur.

        Args:
            neo4j_driver: Driver Neo4j
            tenant_id: Tenant ID
            latest_selector: Sélecteur de latest (optionnel)
        """
        self.neo4j_driver = neo4j_driver
        self.tenant_id = tenant_id
        self.latest_selector = latest_selector or LatestSelector()

        self.stats = {
            "since_when_queries": 0,
            "still_applicable_queries": 0,
            "compare_queries": 0,
            "timeline_refused": 0,
        }

    def query_since_when(
        self,
        capability: str,
        cluster_id: Optional[str] = None,
        axis_key: str = "release_id",
        is_validated_claimkey: bool = True,
    ) -> SinceWhenResult:
        """
        Question A: Depuis quand cette capability existe?

        INV-19: Refuse si ClaimKey candidate (pas validated).
        INV-14: Timeline = None si ordering UNKNOWN.

        S6: V1 assume timeline = cluster-based conservative.

        Args:
            capability: Capability recherchée
            cluster_id: ID du cluster (si connu)
            axis_key: Clé de l'axe pour l'ordre
            is_validated_claimkey: Si l'axe est un ClaimKey validé

        Returns:
            SinceWhenResult avec timeline ou refus
        """
        self.stats["since_when_queries"] += 1

        # INV-19: Refuse timeline si ClaimKey candidate
        if not is_validated_claimkey:
            self.stats["timeline_refused"] += 1
            return SinceWhenResult(
                capability=capability,
                refused=True,
                refused_reason=(
                    "INV-19: Timeline not available for candidate ClaimKey. "
                    "The axis must be validated (≥2 docs, ≥2 distinct values) "
                    "before timeline queries are supported."
                ),
                timeline_basis="cluster",
            )

        if not self.neo4j_driver:
            return SinceWhenResult(
                capability=capability,
                refused=True,
                refused_reason="Neo4j driver not available",
            )

        # Charger les claims et leurs contextes
        timeline_data = self._load_capability_timeline(
            capability=capability,
            cluster_id=cluster_id,
            axis_key=axis_key,
        )

        if not timeline_data["claims"]:
            return SinceWhenResult(
                capability=capability,
                timeline=None,
                ordering_confidence="UNKNOWN",
                timeline_basis="cluster",
            )

        # INV-14: Si ordering UNKNOWN, retourner liste sans ordre
        if timeline_data["ordering_confidence"] == OrderingConfidence.UNKNOWN:
            return SinceWhenResult(
                capability=capability,
                first_occurrence_context=timeline_data["contexts"][0] if timeline_data["contexts"] else None,
                first_occurrence_claims=timeline_data["claims"][:3],  # INV-23
                timeline=None,  # INV-14: Pas de timeline si UNKNOWN
                timeline_basis="cluster",
                ordering_confidence="UNKNOWN",
            )

        # Construire la timeline ordonnée
        timeline = []
        for ctx in timeline_data["ordered_contexts"]:
            claims_in_ctx = [
                c for c in timeline_data["claims"]
                if c in timeline_data["context_claims"].get(ctx, [])
            ]
            timeline.append({
                "context": ctx,
                "claims": claims_in_ctx,  # INV-23
            })

        return SinceWhenResult(
            capability=capability,
            first_occurrence_context=timeline[0]["context"] if timeline else None,
            first_occurrence_claims=timeline[0]["claims"] if timeline else [],  # INV-23
            timeline=timeline,
            timeline_basis="cluster",  # S6
            ordering_confidence=timeline_data["ordering_confidence"].value,
        )

    def query_still_applicable(
        self,
        claim_id: str,
        claim_text: str,
        axes: Dict[str, ApplicabilityAxis],
        policy: Optional[LatestPolicy] = None,
    ) -> StillApplicableResult:
        """
        Question B: Cette claim est-elle encore applicable?

        INV-17: REMOVED seulement si explicitement documenté.
        INV-23: Cite explicitement les claims sources.

        Args:
            claim_id: ID de la claim à vérifier
            claim_text: Texte de la claim
            axes: Axes d'applicabilité disponibles
            policy: Politique de sélection latest

        Returns:
            StillApplicableResult avec statut et analysis
        """
        self.stats["still_applicable_queries"] += 1

        if not self.neo4j_driver:
            return StillApplicableResult(
                claim_id=claim_id,
                claim_text=claim_text,
                status="UNCERTAIN",
                uncertainty_analysis=UncertaintyAnalysis(
                    recommendation="Neo4j driver not available"
                ),
            )

        # 1. Identifier le contexte latest
        candidates = self._load_document_candidates(claim_id)
        latest_result = self.latest_selector.select_latest(
            candidates=candidates,
            axes=axes,
            policy=policy,
        )

        if not latest_result.selected_doc_id:
            # Impossible de déterminer le latest
            return StillApplicableResult(
                claim_id=claim_id,
                claim_text=claim_text,
                status="UNCERTAIN",
                uncertainty_analysis=UncertaintyAnalysis(
                    recommendation=f"Cannot determine latest context: {latest_result.why_selected}"
                ),
            )

        latest_context = latest_result.selected_context_value

        # 2. Vérifier si la claim est dans le latest
        claim_in_latest, related_claims, contradicting = self._check_claim_in_context(
            claim_id=claim_id,
            context_value=latest_context,
        )

        # 3. Déterminer le statut
        if claim_in_latest:
            # Claim présente dans latest → APPLICABLE
            return StillApplicableResult(
                claim_id=claim_id,
                claim_text=claim_text,
                is_applicable=True,
                status="APPLICABLE",
                latest_context=latest_context,
                supporting_claims=[claim_id],  # INV-23
            )

        # INV-17: Vérifier si REMOVED est explicitement documenté
        removal_evidence = self._find_removal_evidence(claim_id, latest_context)

        if removal_evidence:
            return StillApplicableResult(
                claim_id=claim_id,
                claim_text=claim_text,
                is_applicable=False,
                status="REMOVED",
                latest_context=latest_context,
                supporting_claims=removal_evidence["claim_ids"],  # INV-23
                removal_evidence=removal_evidence["text"],
            )

        # Vérifier si superseded
        if contradicting:
            return StillApplicableResult(
                claim_id=claim_id,
                claim_text=claim_text,
                is_applicable=False,
                status="SUPERSEDED",
                latest_context=latest_context,
                supporting_claims=contradicting[:3],  # INV-23
            )

        # Absent mais pas explicitement removed → UNCERTAIN (INV-17)
        analysis = UncertaintyAnalysis.analyze(
            claim_id=claim_id,
            latest_context_claims=related_claims,
            older_context_claims=[claim_id],
            related_claims=related_claims,
            contradicting_claims=contradicting,
        )

        return StillApplicableResult(
            claim_id=claim_id,
            claim_text=claim_text,
            is_applicable=None,
            status="UNCERTAIN",
            latest_context=latest_context,
            supporting_claims=related_claims[:3],  # INV-23
            uncertainty_analysis=analysis,
        )

    def compare_contexts(
        self,
        context_a: str,
        context_b: str,
        axis_key: str = "release_id",
    ) -> Dict[str, Any]:
        """
        Question C: Différences entre contextes A et B?

        INV-14: compare() → None si ordre inconnu.

        Args:
            context_a: Premier contexte
            context_b: Deuxième contexte
            axis_key: Axe de comparaison

        Returns:
            Dict avec différences et claims sources
        """
        self.stats["compare_queries"] += 1

        if not self.neo4j_driver:
            return {
                "error": "Neo4j driver not available",
                "claims_a": [],
                "claims_b": [],
                "added": [],
                "removed": [],
                "modified": [],
            }

        # Charger les claims de chaque contexte
        claims_a = self._load_claims_for_context(context_a)
        claims_b = self._load_claims_for_context(context_b)

        claims_a_ids = set(c["claim_id"] for c in claims_a)
        claims_b_ids = set(c["claim_id"] for c in claims_b)

        # Calculer les différences
        added_ids = claims_b_ids - claims_a_ids
        removed_ids = claims_a_ids - claims_b_ids
        common_ids = claims_a_ids & claims_b_ids

        return {
            "context_a": context_a,
            "context_b": context_b,
            "axis_key": axis_key,
            "claims_a_count": len(claims_a),
            "claims_b_count": len(claims_b),
            "added": [c for c in claims_b if c["claim_id"] in added_ids],  # INV-23
            "removed": [c for c in claims_a if c["claim_id"] in removed_ids],  # INV-23
            "common_count": len(common_ids),
        }

    # === Private methods ===

    def _load_capability_timeline(
        self,
        capability: str,
        cluster_id: Optional[str],
        axis_key: str,
    ) -> Dict[str, Any]:
        """Charge la timeline pour une capability."""
        result = {
            "claims": [],
            "contexts": [],
            "ordered_contexts": [],
            "context_claims": {},
            "ordering_confidence": OrderingConfidence.UNKNOWN,
        }

        try:
            with self.neo4j_driver.session() as session:
                # Recherche par cluster ou fulltext
                if cluster_id:
                    query = """
                    MATCH (c:Claim)-[:IN_CLUSTER]->(cluster:ClaimCluster {cluster_id: $cluster_id})
                    MATCH (c)-[:IN_DOCUMENT]->(d:Document)
                    OPTIONAL MATCH (d)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    RETURN c.claim_id as claim_id,
                           dc.axis_values[$axis_key].scalar_value as context_value
                    """
                    params = {"cluster_id": cluster_id, "axis_key": axis_key}
                else:
                    query = """
                    CALL db.index.fulltext.queryNodes('claim_text_search', $capability)
                    YIELD node AS c, score
                    WHERE score > 0.5
                    MATCH (c)-[:IN_DOCUMENT]->(d:Document)
                    OPTIONAL MATCH (d)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    RETURN c.claim_id as claim_id,
                           dc.axis_values[$axis_key].scalar_value as context_value
                    LIMIT 50
                    """
                    params = {"capability": capability, "axis_key": axis_key}

                records = list(session.run(query, params))

                contexts_set = set()
                for record in records:
                    claim_id = record["claim_id"]
                    context = record["context_value"] or "unknown"

                    result["claims"].append(claim_id)
                    contexts_set.add(context)

                    if context not in result["context_claims"]:
                        result["context_claims"][context] = []
                    result["context_claims"][context].append(claim_id)

                result["contexts"] = list(contexts_set)

                # Essayer d'ordonner les contextes
                # (simplifié - en production utiliserait AxisOrderInferrer)
                try:
                    # Tentative d'ordre numérique
                    numeric_contexts = [(float(c), c) for c in contexts_set if c != "unknown"]
                    numeric_contexts.sort()
                    result["ordered_contexts"] = [c[1] for c in numeric_contexts]
                    result["ordering_confidence"] = OrderingConfidence.CERTAIN
                except (ValueError, TypeError):
                    result["ordered_contexts"] = list(contexts_set)
                    result["ordering_confidence"] = OrderingConfidence.UNKNOWN

        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalQueryEngine] Timeline load failed: {e}")

        return result

    def _load_document_candidates(self, claim_id: str) -> List[DocumentCandidate]:
        """Charge les candidats documents pour une claim."""
        candidates = []

        try:
            with self.neo4j_driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})-[:IN_DOCUMENT]->(d:Document)
                    OPTIONAL MATCH (d)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    RETURN d.doc_id as doc_id,
                           dc.axis_values as axis_values,
                           d.document_type as document_type
                    """,
                    claim_id=claim_id,
                )

                for record in result:
                    axis_values = record["axis_values"] or {}
                    # Extraire la première valeur d'axe trouvée
                    context_value = "unknown"
                    axis_key = "release_id"
                    for key, val in axis_values.items():
                        if isinstance(val, dict) and val.get("scalar_value"):
                            context_value = val["scalar_value"]
                            axis_key = key
                            break

                    candidates.append(DocumentCandidate(
                        doc_id=record["doc_id"],
                        context_value=context_value,
                        axis_key=axis_key,
                        document_type=record["document_type"],
                    ))

        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalQueryEngine] Candidates load failed: {e}")

        return candidates

    def _check_claim_in_context(
        self,
        claim_id: str,
        context_value: str,
    ) -> tuple[bool, List[str], List[str]]:
        """
        Vérifie si une claim est présente dans un contexte.

        Returns:
            (claim_in_context, related_claims, contradicting_claims)
        """
        claim_found = False
        related = []
        contradicting = []

        try:
            with self.neo4j_driver.session() as session:
                # Vérifier présence directe
                result = session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})-[:IN_DOCUMENT]->(d:Document)
                    MATCH (d)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    RETURN count(c) > 0 as found
                    """,
                    claim_id=claim_id,
                    context=context_value,
                )
                record = result.single()
                claim_found = record["found"] if record else False

                # Chercher claims connexes (même cluster)
                result = session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})-[:IN_CLUSTER]->(cluster)
                    MATCH (other:Claim)-[:IN_CLUSTER]->(cluster)
                    WHERE other.claim_id <> $claim_id
                    MATCH (other)-[:IN_DOCUMENT]->(d:Document)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    RETURN other.claim_id as related_id
                    LIMIT 10
                    """,
                    claim_id=claim_id,
                    context=context_value,
                )
                related = [r["related_id"] for r in result]

                # Chercher claims contradictoires
                result = session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})<-[:CONTRADICTS]-(other:Claim)
                    MATCH (other)-[:IN_DOCUMENT]->(d:Document)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    RETURN other.claim_id as contra_id
                    LIMIT 5
                    """,
                    claim_id=claim_id,
                    context=context_value,
                )
                contradicting = [r["contra_id"] for r in result]

        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalQueryEngine] Context check failed: {e}")

        return claim_found, related, contradicting

    def _find_removal_evidence(
        self,
        claim_id: str,
        latest_context: str,
    ) -> Optional[Dict[str, Any]]:
        """
        INV-17: Cherche une evidence explicite de suppression.

        Returns:
            {"claim_ids": [...], "text": "..."} ou None
        """
        try:
            with self.neo4j_driver.session() as session:
                # Chercher mentions explicites de removal/deprecation
                result = session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})-[:IN_CLUSTER]->(cluster)
                    MATCH (removal:Claim)-[:IN_CLUSTER]->(cluster)
                    WHERE removal.text =~ '(?i).*(removed|deprecated|discontinued|replaced by|no longer).*'
                    MATCH (removal)-[:IN_DOCUMENT]->(d:Document)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    RETURN removal.claim_id as removal_id, removal.text as removal_text
                    LIMIT 3
                    """,
                    claim_id=claim_id,
                    context=latest_context,
                )

                records = list(result)
                if records:
                    return {
                        "claim_ids": [r["removal_id"] for r in records],
                        "text": records[0]["removal_text"],
                    }

        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalQueryEngine] Removal check failed: {e}")

        return None

    def _load_claims_for_context(self, context_value: str) -> List[Dict[str, Any]]:
        """Charge toutes les claims d'un contexte."""
        claims = []

        try:
            with self.neo4j_driver.session() as session:
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tenant_id})-[:IN_DOCUMENT]->(d:Document)
                    MATCH (d)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    RETURN c.claim_id as claim_id, c.text as text
                    LIMIT 100
                    """,
                    tenant_id=self.tenant_id,
                    context=context_value,
                )

                claims = [{"claim_id": r["claim_id"], "text": r["text"]} for r in result]

        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalQueryEngine] Claims load failed: {e}")

        return claims

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "since_when_queries": 0,
            "still_applicable_queries": 0,
            "compare_queries": 0,
            "timeline_refused": 0,
        }


__all__ = [
    "TemporalQueryEngine",
    "SinceWhenResult",
    "StillApplicableResult",
]
