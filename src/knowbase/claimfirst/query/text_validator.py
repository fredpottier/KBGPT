# src/knowbase/claimfirst/query/text_validator.py
"""
TextValidator - Validation de texte utilisateur contre le corpus.

Question D: Ce texte est-il conforme au corpus?

INV-23: Toute réponse cite explicitement ses claims sources.

Statuts possibles:
- CONFIRMED: Le texte est supporté par des claims
- INCORRECT: Le texte contredit des claims
- UNCERTAIN: Pas assez d'évidence
- NOT_DOCUMENTED: Le sujet n'est pas documenté dans le corpus
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ValidationStatus(str, Enum):
    """Statut de validation du texte."""

    CONFIRMED = "confirmed"
    """Le texte est supporté par des claims du corpus."""

    INCORRECT = "incorrect"
    """Le texte contredit des claims du corpus."""

    UNCERTAIN = "uncertain"
    """Pas assez d'évidence pour confirmer ou infirmer."""

    NOT_DOCUMENTED = "not_documented"
    """Le sujet n'est pas documenté dans le corpus."""


class TextValidationResult(BaseModel):
    """
    Résultat de validation d'un texte utilisateur.

    INV-23: Cite explicitement les claims sources.

    Attributes:
        user_text: Texte utilisateur validé
        status: Statut de validation
        supporting_claims: Claims qui supportent le texte
        contradicting_claims: Claims qui contredisent le texte
        confidence: Confiance dans la validation [0-1]
        explanation: Explication de la validation
        context_used: Contexte utilisé pour la validation
    """

    user_text: str = Field(..., description="Texte utilisateur validé")

    status: ValidationStatus = Field(
        default=ValidationStatus.UNCERTAIN,
        description="Statut de validation"
    )

    # INV-23: Claims sources obligatoires
    supporting_claims: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Claims qui supportent le texte [{claim_id, text, similarity}]"
    )

    contradicting_claims: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Claims qui contredisent le texte [{claim_id, text, similarity}]"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance dans la validation"
    )

    explanation: str = Field(
        default="",
        description="Explication de la validation"
    )

    context_used: Optional[str] = Field(
        default=None,
        description="Contexte utilisé pour la validation (si spécifié)"
    )


class TextValidator:
    """
    Valide un texte utilisateur contre le corpus de claims.

    Question D: Ce texte est-il conforme au corpus?

    Approche:
    1. Chercher des claims similaires (supporting)
    2. Chercher des claims contradictoires
    3. Déterminer le statut basé sur les scores

    INV-23: Toujours citer les claims sources.
    """

    # Seuils de validation
    SUPPORTING_THRESHOLD = 0.80  # Similarité pour supporter
    CONTRADICTING_THRESHOLD = 0.70  # Similarité pour contradiction
    MIN_CLAIMS_FOR_DECISION = 2  # Minimum de claims pour décision

    def __init__(
        self,
        neo4j_driver: Optional[Any] = None,
        embeddings_client: Optional[Any] = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le validateur.

        Args:
            neo4j_driver: Driver Neo4j
            embeddings_client: Client embeddings pour similarité
            tenant_id: Tenant ID
        """
        self.neo4j_driver = neo4j_driver
        self.embeddings_client = embeddings_client
        self.tenant_id = tenant_id

        self.stats = {
            "validations": 0,
            "confirmed": 0,
            "incorrect": 0,
            "uncertain": 0,
            "not_documented": 0,
        }

    def validate(
        self,
        user_statement: str,
        target_context: Optional[str] = None,
        subject_filter: Optional[str] = None,
    ) -> TextValidationResult:
        """
        Valide un texte utilisateur contre le corpus.

        Args:
            user_statement: Texte à valider
            target_context: Contexte cible (ex: "2023") - optionnel
            subject_filter: Filtre sur le sujet - optionnel

        Returns:
            TextValidationResult avec statut et claims sources
        """
        self.stats["validations"] += 1

        if not self.neo4j_driver:
            return TextValidationResult(
                user_text=user_statement,
                status=ValidationStatus.UNCERTAIN,
                explanation="Neo4j driver not available",
            )

        # 1. Chercher des claims similaires
        supporting = self._find_supporting_claims(
            user_statement, target_context, subject_filter
        )

        # 2. Chercher des claims contradictoires
        contradicting = self._find_contradicting_claims(
            user_statement, target_context, subject_filter
        )

        # 3. Déterminer le statut
        result = self._determine_status(
            user_statement, supporting, contradicting, target_context
        )

        # Mettre à jour les stats
        self.stats[result.status.value] += 1

        return result

    def _find_supporting_claims(
        self,
        statement: str,
        context: Optional[str],
        subject_filter: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Cherche des claims qui supportent le statement.

        Args:
            statement: Texte à valider
            context: Contexte cible (optionnel)
            subject_filter: Filtre sujet (optionnel)

        Returns:
            Liste de claims supportantes avec scores
        """
        claims = []

        try:
            with self.neo4j_driver.session() as session:
                # Recherche fulltext
                query = """
                CALL db.index.fulltext.queryNodes('claim_text_search', $statement)
                YIELD node AS c, score
                WHERE score > $threshold AND c.tenant_id = $tenant_id
                """

                params = {
                    "statement": statement,
                    "threshold": self.SUPPORTING_THRESHOLD * 10,  # Fulltext scores are 0-10+
                    "tenant_id": self.tenant_id,
                }

                # Ajouter filtre contexte si spécifié
                if context:
                    query += """
                    MATCH (c)-[:IN_DOCUMENT]->(d:Document)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    """
                    params["context"] = context

                query += """
                RETURN c.claim_id as claim_id, c.text as text, score
                ORDER BY score DESC
                LIMIT 10
                """

                result = session.run(query, params)

                for record in result:
                    similarity = min(record["score"] / 10.0, 1.0)  # Normaliser
                    if similarity >= self.SUPPORTING_THRESHOLD:
                        claims.append({
                            "claim_id": record["claim_id"],
                            "text": record["text"],
                            "similarity": round(similarity, 3),
                        })

        except Exception as e:
            logger.warning(f"[OSMOSE:TextValidator] Supporting search failed: {e}")

        return claims

    def _find_contradicting_claims(
        self,
        statement: str,
        context: Optional[str],
        subject_filter: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Cherche des claims qui contredisent le statement.

        Approche: Chercher des claims sur le même sujet avec CONTRADICTS relation
        ou des termes de négation.

        Args:
            statement: Texte à valider
            context: Contexte cible (optionnel)
            subject_filter: Filtre sujet (optionnel)

        Returns:
            Liste de claims contradictoires avec scores
        """
        claims = []

        try:
            with self.neo4j_driver.session() as session:
                # Chercher claims similaires puis vérifier les relations CONTRADICTS
                query = """
                CALL db.index.fulltext.queryNodes('claim_text_search', $statement)
                YIELD node AS c, score
                WHERE score > $threshold AND c.tenant_id = $tenant_id
                OPTIONAL MATCH (c)-[:CONTRADICTS]-(contra:Claim)
                """

                params = {
                    "statement": statement,
                    "threshold": self.CONTRADICTING_THRESHOLD * 10,
                    "tenant_id": self.tenant_id,
                }

                if context:
                    query += """
                    WITH c, score, contra
                    MATCH (target:Claim)-[:IN_DOCUMENT]->(d:Document)-[:HAS_CONTEXT]->(dc:DocumentContext)
                    WHERE (target = c OR target = contra)
                      AND any(k IN keys(dc.axis_values) WHERE dc.axis_values[k].scalar_value = $context)
                    """
                    params["context"] = context

                query += """
                WITH DISTINCT coalesce(contra, c) as claim, score
                WHERE claim IS NOT NULL
                RETURN claim.claim_id as claim_id, claim.text as text, score
                ORDER BY score DESC
                LIMIT 5
                """

                result = session.run(query, params)

                for record in result:
                    # Vérifier si le texte de la claim contient des négations
                    # ou contredit sémantiquement le statement
                    claim_text = record["text"].lower()
                    statement_lower = statement.lower()

                    # Heuristique simple: négation détectée
                    has_negation = any(
                        neg in claim_text
                        for neg in ["not ", "no ", "cannot", "don't", "doesn't", "isn't", "aren't"]
                    )

                    # Si le claim parle du même sujet mais avec négation
                    if has_negation:
                        similarity = min(record["score"] / 10.0, 1.0)
                        claims.append({
                            "claim_id": record["claim_id"],
                            "text": record["text"],
                            "similarity": round(similarity, 3),
                        })

        except Exception as e:
            logger.warning(f"[OSMOSE:TextValidator] Contradicting search failed: {e}")

        return claims

    def _determine_status(
        self,
        statement: str,
        supporting: List[Dict[str, Any]],
        contradicting: List[Dict[str, Any]],
        context: Optional[str],
    ) -> TextValidationResult:
        """
        Détermine le statut de validation basé sur les claims trouvées.

        Args:
            statement: Texte validé
            supporting: Claims supportantes
            contradicting: Claims contradictoires
            context: Contexte utilisé

        Returns:
            TextValidationResult complet
        """
        # Cas 1: Rien trouvé → NOT_DOCUMENTED
        if not supporting and not contradicting:
            return TextValidationResult(
                user_text=statement,
                status=ValidationStatus.NOT_DOCUMENTED,
                explanation="No relevant claims found in the corpus.",
                context_used=context,
            )

        # Cas 2: Contradictions trouvées → INCORRECT
        if contradicting:
            # Calculer confiance basée sur le meilleur score
            best_contra_score = max(c["similarity"] for c in contradicting)
            confidence = best_contra_score

            return TextValidationResult(
                user_text=statement,
                status=ValidationStatus.INCORRECT,
                supporting_claims=supporting[:3],  # INV-23
                contradicting_claims=contradicting[:3],  # INV-23
                confidence=round(confidence, 3),
                explanation=(
                    f"The statement contradicts {len(contradicting)} claim(s) in the corpus. "
                    f"See contradicting_claims for details."
                ),
                context_used=context,
            )

        # Cas 3: Assez de support → CONFIRMED
        if len(supporting) >= self.MIN_CLAIMS_FOR_DECISION:
            best_support_score = max(c["similarity"] for c in supporting)
            confidence = best_support_score

            return TextValidationResult(
                user_text=statement,
                status=ValidationStatus.CONFIRMED,
                supporting_claims=supporting[:5],  # INV-23
                contradicting_claims=[],
                confidence=round(confidence, 3),
                explanation=(
                    f"The statement is supported by {len(supporting)} claim(s) in the corpus."
                ),
                context_used=context,
            )

        # Cas 4: Support partiel → UNCERTAIN
        best_score = max(c["similarity"] for c in supporting) if supporting else 0
        confidence = best_score * 0.7  # Réduire car incertain

        return TextValidationResult(
            user_text=statement,
            status=ValidationStatus.UNCERTAIN,
            supporting_claims=supporting,  # INV-23
            contradicting_claims=[],
            confidence=round(confidence, 3),
            explanation=(
                f"Found {len(supporting)} related claim(s) but not enough evidence "
                f"to fully confirm. Verification recommended."
            ),
            context_used=context,
        )

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "validations": 0,
            "confirmed": 0,
            "incorrect": 0,
            "uncertain": 0,
            "not_documented": 0,
        }


__all__ = [
    "TextValidator",
    "TextValidationResult",
    "ValidationStatus",
]
