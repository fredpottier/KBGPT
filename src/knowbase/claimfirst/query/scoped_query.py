# src/knowbase/claimfirst/query/scoped_query.py
"""
ScopedQueryEngine - Moteur de requête avec scoping obligatoire.

INV-8: Applicability over Truth (Scope Épistémique)

Comportements:
- Si contexte clair → filtrer et répondre
- Si contexte ambigu → exposer les options
- Si contexte inconnu → demander clarification

CORRECTIF 5 - Usage des alias à query-time:
- aliases_explicit + aliases_learned → Match direct OK
- aliases_inferred → JAMAIS filtre dur, seulement suggestions

Réponse épistémiquement honnête:
Q: "Quel est le SLA ?"
R: "Plusieurs SLA sont documentés :
    • RISE S/4HANA Private (doc 014): 99.7%
    • SAP BTP (doc 025): 99.95%
    Veuillez préciser le contexte pour une réponse applicable."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.document_context import DocumentContext, ResolutionStatus
from knowbase.claimfirst.resolution.subject_resolver import SubjectResolver, ResolverResult

logger = logging.getLogger(__name__)


@dataclass
class QueryContext:
    """Contexte de requête fourni par l'utilisateur."""

    subject_hint: Optional[str] = None
    """Indication du sujet (ex: 'BTP', 'S/4HANA')."""

    qualifiers: Dict[str, str] = field(default_factory=dict)
    """Qualificateurs (ex: {version: '2023', region: 'EU'})."""

    document_types: List[str] = field(default_factory=list)
    """Types de documents à cibler (ex: ['Security Guide'])."""


@dataclass
class ClaimWithContext:
    """Claim enrichie avec son contexte documentaire."""

    claim: Claim
    """La claim elle-même."""

    doc_context: DocumentContext
    """Contexte du document source."""

    subject_anchor: Optional[SubjectAnchor]
    """SubjectAnchor associé (si résolu)."""

    relevance_score: float = 1.0
    """Score de pertinence [0-1]."""


@dataclass
class QueryResponse:
    """Réponse à une requête scopée."""

    # Réponse principale
    answer: Optional[str] = None
    """Réponse synthétisée (si contexte clair)."""

    # Claims sources
    claims: List[ClaimWithContext] = field(default_factory=list)
    """Claims trouvées avec leur contexte."""

    # Métadonnées de la réponse
    subject: Optional[str] = None
    """Sujet principal de la réponse."""

    source_docs: List[str] = field(default_factory=list)
    """Documents sources."""

    confidence: str = "unknown"
    """Niveau de confiance: 'high', 'medium', 'low', 'unknown'."""

    # États spéciaux
    disambiguation_required: bool = False
    """Si True, l'utilisateur doit préciser le contexte."""

    candidates: List[Dict[str, Any]] = field(default_factory=list)
    """Candidats pour désambiguïsation."""

    not_found: bool = False
    """Si True, aucune information trouvée."""

    message: Optional[str] = None
    """Message explicatif (pour disambiguation ou not_found)."""

    # Suggestions (pour aliases_inferred)
    suggestions: List[str] = field(default_factory=list)
    """Suggestions de reformulation ("Voulez-vous dire X ?")."""


class ScopedQueryEngine:
    """
    Moteur de requête avec scoping obligatoire (INV-8).

    Comportements:
    - Un seul sujet clair → répondre avec les claims applicables
    - Plusieurs sujets possibles → demander désambiguïsation
    - Aucun sujet trouvé → "non documenté dans le corpus"

    CORRECTIF 5: aliases_inferred ne sont JAMAIS utilisés pour filtre dur.
    """

    def __init__(
        self,
        neo4j_driver: Any = None,
        subject_resolver: Optional[SubjectResolver] = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le moteur de requête.

        Args:
            neo4j_driver: Driver Neo4j pour récupérer les données
            subject_resolver: Résolveur de sujets (optionnel)
            tenant_id: Tenant ID par défaut
        """
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.subject_resolver = subject_resolver or SubjectResolver(tenant_id=tenant_id)

        # Stats
        self._stats = {
            "queries_processed": 0,
            "single_subject_answers": 0,
            "disambiguations": 0,
            "not_found": 0,
        }

    def query(
        self,
        question: str,
        user_context: Optional[QueryContext] = None,
        max_claims: int = 20,
    ) -> QueryResponse:
        """
        Requête avec gestion du scope.

        Args:
            question: Question de l'utilisateur
            user_context: Contexte fourni par l'utilisateur
            max_claims: Nombre max de claims à retourner

        Returns:
            QueryResponse avec réponse ou demande de clarification
        """
        self._stats["queries_processed"] += 1

        if not self.driver:
            return QueryResponse(
                not_found=True,
                message="Database connection not available."
            )

        user_context = user_context or QueryContext()

        # 1. Extraire le sujet implicite de la question
        implicit_subject = self._extract_question_subject(question)

        # 2. Déterminer le sujet à rechercher
        search_subject = user_context.subject_hint or implicit_subject

        # 3. Résoudre vers SubjectAnchor(s)
        if search_subject:
            resolver_results = self._resolve_query_subject(search_subject)
        else:
            # Pas de sujet détecté → chercher dans tout le corpus
            resolver_results = []

        # 4. Analyser les résultats de résolution
        return self._build_response(
            question=question,
            resolver_results=resolver_results,
            user_context=user_context,
            max_claims=max_claims,
        )

    def _extract_question_subject(self, question: str) -> Optional[str]:
        """
        Extrait le sujet implicite de la question.

        Heuristiques:
        - Termes capitalisés
        - Noms de produits connus
        - Patterns "X's SLA", "SLA for X"

        Args:
            question: Question de l'utilisateur

        Returns:
            Sujet extrait ou None
        """
        import re

        # Pattern "X's <quelque chose>" ou "<quelque chose> for X"
        patterns = [
            re.compile(r"([A-Z][a-zA-Z0-9/\-]+(?:\s+[A-Z][a-zA-Z0-9/\-]+)*)'s\s+", re.UNICODE),
            re.compile(r"(?:for|of|in)\s+([A-Z][a-zA-Z0-9/\-]+(?:\s+[A-Z][a-zA-Z0-9/\-]+)*)", re.UNICODE),
            re.compile(r"([A-Z][a-zA-Z0-9/\-]+(?:\s+[A-Z][a-zA-Z0-9/\-]+){1,3})", re.UNICODE),
        ]

        for pattern in patterns:
            match = pattern.search(question)
            if match:
                subject = match.group(1).strip()
                # Filtrer les mots courants
                if subject.lower() not in {"the", "a", "an", "this", "that", "what", "how"}:
                    return subject

        return None

    def _resolve_query_subject(self, search_subject: str) -> List[ResolverResult]:
        """
        Résout le sujet de recherche vers des SubjectAnchors.

        Args:
            search_subject: Sujet à rechercher

        Returns:
            Liste de ResolverResult
        """
        # Récupérer les SubjectAnchors existants
        existing_anchors = self._get_all_subject_anchors()

        # Résoudre le sujet
        result = self.subject_resolver.resolve(
            raw_subject=search_subject,
            existing_anchors=existing_anchors,
            create_if_missing=False,  # Ne pas créer à query-time
        )

        # Si AMBIGUOUS, retourner aussi les candidats
        if result.status == ResolutionStatus.AMBIGUOUS and result.candidates:
            return [
                ResolverResult(
                    anchor=candidate,
                    status=ResolutionStatus.AMBIGUOUS,
                    confidence=score,
                    match_type="embedding",
                )
                for candidate, score in result.candidates
            ]

        # Sinon retourner le résultat unique
        if result.anchor:
            return [result]

        return []

    def _build_response(
        self,
        question: str,
        resolver_results: List[ResolverResult],
        user_context: QueryContext,
        max_claims: int,
    ) -> QueryResponse:
        """
        Construit la réponse en fonction des résultats de résolution.

        Args:
            question: Question originale
            resolver_results: Résultats de résolution
            user_context: Contexte utilisateur
            max_claims: Max claims

        Returns:
            QueryResponse
        """
        # Cas 1: Un seul sujet clair (RESOLVED)
        resolved_results = [
            r for r in resolver_results
            if r.status == ResolutionStatus.RESOLVED
        ]

        if len(resolved_results) == 1:
            return self._build_single_subject_response(
                anchor=resolved_results[0].anchor,
                question=question,
                user_context=user_context,
                max_claims=max_claims,
            )

        # Cas 2: Plusieurs sujets possibles → demander désambiguïsation
        if len(resolver_results) > 1:
            return self._build_disambiguation_response(
                results=resolver_results,
                question=question,
            )

        # Cas 3: Un seul sujet LOW_CONFIDENCE
        low_conf_results = [
            r for r in resolver_results
            if r.status == ResolutionStatus.LOW_CONFIDENCE
        ]

        if len(low_conf_results) == 1:
            return self._build_single_subject_response(
                anchor=low_conf_results[0].anchor,
                question=question,
                user_context=user_context,
                max_claims=max_claims,
                confidence="medium",
            )

        # Cas 4: Aucun sujet trouvé
        self._stats["not_found"] += 1
        return QueryResponse(
            not_found=True,
            message="Aucun document ne traite de ce sujet dans le corpus.",
        )

    def _build_single_subject_response(
        self,
        anchor: SubjectAnchor,
        question: str,
        user_context: QueryContext,
        max_claims: int,
        confidence: str = "high",
    ) -> QueryResponse:
        """
        Construit une réponse pour un sujet unique.

        Args:
            anchor: SubjectAnchor résolu
            question: Question originale
            user_context: Contexte utilisateur
            max_claims: Max claims
            confidence: Niveau de confiance

        Returns:
            QueryResponse
        """
        self._stats["single_subject_answers"] += 1

        # Récupérer les claims pour ce sujet
        claims_with_context = self._get_claims_for_subject(
            anchor=anchor,
            qualifiers=user_context.qualifiers,
            max_claims=max_claims,
        )

        if not claims_with_context:
            return QueryResponse(
                subject=anchor.canonical_name,
                not_found=True,
                message=f"Aucune information documentée pour '{anchor.canonical_name}' "
                        f"avec ces critères.",
            )

        # Extraire les documents sources
        source_docs = list({cwc.doc_context.doc_id for cwc in claims_with_context})

        return QueryResponse(
            claims=claims_with_context,
            subject=anchor.canonical_name,
            source_docs=source_docs,
            confidence=confidence,
        )

    def _build_disambiguation_response(
        self,
        results: List[ResolverResult],
        question: str,
    ) -> QueryResponse:
        """
        Construit une réponse demandant désambiguïsation.

        Args:
            results: Résultats de résolution multiples
            question: Question originale

        Returns:
            QueryResponse avec disambiguation_required=True
        """
        self._stats["disambiguations"] += 1

        candidates = []
        suggestions = []

        for result in results[:5]:  # Limiter à 5 candidats
            if result.anchor:
                # Prévisualiser les claims
                preview = self._preview_claims_for_subject(result.anchor)

                candidates.append({
                    "subject": result.anchor.canonical_name,
                    "subject_id": result.anchor.subject_id,
                    "confidence": result.confidence,
                    "claims_preview": preview,
                })

                # Si alias inféré, suggérer reformulation (CORRECTIF 5)
                if result.match_type == "embedding":
                    suggestions.append(
                        f"Voulez-vous dire '{result.anchor.canonical_name}' ?"
                    )

        return QueryResponse(
            disambiguation_required=True,
            candidates=candidates,
            suggestions=suggestions[:3],  # Max 3 suggestions
            message="Plusieurs sujets correspondent à votre recherche. "
                    "Veuillez préciser le contexte.",
        )

    def _get_claims_for_subject(
        self,
        anchor: SubjectAnchor,
        qualifiers: Optional[Dict[str, str]] = None,
        max_claims: int = 20,
    ) -> List[ClaimWithContext]:
        """
        Récupère les claims pour un sujet avec filtrage par qualificateurs.

        Cypher:
        MATCH (sa:SubjectAnchor {subject_id: $subject_id})
        MATCH (dc:DocumentContext)-[:ABOUT_SUBJECT]->(sa)
        MATCH (d:Document)-[:HAS_CONTEXT]->(dc)
        MATCH (c:Claim)-[:IN_DOCUMENT]->(d)
        WHERE dc.qualifiers.version = $version OR $version IS NULL
        RETURN c, dc, d.doc_id

        Args:
            anchor: SubjectAnchor ciblé
            qualifiers: Filtres optionnels
            max_claims: Nombre max

        Returns:
            Liste de ClaimWithContext
        """
        if not self.driver:
            return []

        qualifiers = qualifiers or {}

        # Construire la query Cypher avec filtres optionnels
        # (exclut les claims archivées — Chantier 0 Phase 1B)
        query = """
        MATCH (sa:SubjectAnchor {subject_id: $subject_id, tenant_id: $tenant_id})
        MATCH (dc:DocumentContext)-[:ABOUT_SUBJECT]->(sa)
        MATCH (d:Document)-[:HAS_CONTEXT]->(dc)
        MATCH (c:Claim)-[:IN_DOCUMENT]->(d)
        WHERE c.tenant_id = $tenant_id
          AND (c.archived IS NULL OR c.archived = false)
        """

        # Ajouter les filtres de qualificateurs
        params = {
            "subject_id": anchor.subject_id,
            "tenant_id": self.tenant_id,
        }

        if qualifiers.get("version"):
            query += " AND dc.qualifiers.version = $version"
            params["version"] = qualifiers["version"]

        if qualifiers.get("region"):
            query += " AND dc.qualifiers.region = $region"
            params["region"] = qualifiers["region"]

        query += f" RETURN c, dc LIMIT {max_claims}"

        claims_with_context = []

        try:
            with self.driver.session() as session:
                result = session.run(query, params)

                for record in result:
                    claim_data = dict(record["c"])
                    dc_data = dict(record["dc"])

                    claim = Claim.from_neo4j_record(claim_data)
                    doc_context = DocumentContext.from_neo4j_record(dc_data)

                    claims_with_context.append(ClaimWithContext(
                        claim=claim,
                        doc_context=doc_context,
                        subject_anchor=anchor,
                    ))

        except Exception as e:
            logger.error(f"[ScopedQueryEngine] Failed to get claims: {e}")

        return claims_with_context

    def _preview_claims_for_subject(
        self,
        anchor: SubjectAnchor,
        max_preview: int = 3,
    ) -> List[str]:
        """
        Prévisualise les claims pour un sujet (pour désambiguïsation).

        Args:
            anchor: SubjectAnchor
            max_preview: Nombre de claims à prévisualiser

        Returns:
            Liste de textes de claims (tronqués)
        """
        claims = self._get_claims_for_subject(anchor, max_claims=max_preview)

        return [
            cwc.claim.text[:100] + "..." if len(cwc.claim.text) > 100 else cwc.claim.text
            for cwc in claims
        ]

    def _get_all_subject_anchors(self) -> List[SubjectAnchor]:
        """
        Récupère tous les SubjectAnchors du tenant.

        Returns:
            Liste de SubjectAnchor
        """
        if not self.driver:
            return []

        anchors = []

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (sa:SubjectAnchor {tenant_id: $tenant_id})
                    RETURN sa
                    """,
                    {"tenant_id": self.tenant_id}
                )

                for record in result:
                    anchor_data = dict(record["sa"])
                    anchors.append(SubjectAnchor.from_neo4j_record(anchor_data))

        except Exception as e:
            logger.error(f"[ScopedQueryEngine] Failed to get subject anchors: {e}")

        return anchors

    def query_by_subject_id(
        self,
        subject_id: str,
        qualifiers: Optional[Dict[str, str]] = None,
        max_claims: int = 20,
    ) -> QueryResponse:
        """
        Requête directe par subject_id (après désambiguïsation).

        Args:
            subject_id: ID du SubjectAnchor
            qualifiers: Filtres optionnels
            max_claims: Nombre max de claims

        Returns:
            QueryResponse
        """
        # Récupérer le SubjectAnchor
        anchor = self._get_subject_anchor_by_id(subject_id)

        if not anchor:
            return QueryResponse(
                not_found=True,
                message=f"Sujet non trouvé: {subject_id}",
            )

        # Récupérer les claims
        claims_with_context = self._get_claims_for_subject(
            anchor=anchor,
            qualifiers=qualifiers,
            max_claims=max_claims,
        )

        source_docs = list({cwc.doc_context.doc_id for cwc in claims_with_context})

        return QueryResponse(
            claims=claims_with_context,
            subject=anchor.canonical_name,
            source_docs=source_docs,
            confidence="high",
        )

    def _get_subject_anchor_by_id(self, subject_id: str) -> Optional[SubjectAnchor]:
        """Récupère un SubjectAnchor par son ID."""
        if not self.driver:
            return None

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (sa:SubjectAnchor {subject_id: $subject_id, tenant_id: $tenant_id})
                    RETURN sa
                    """,
                    {"subject_id": subject_id, "tenant_id": self.tenant_id}
                )

                record = result.single()
                if record:
                    return SubjectAnchor.from_neo4j_record(dict(record["sa"]))

        except Exception as e:
            logger.error(f"[ScopedQueryEngine] Failed to get subject anchor: {e}")

        return None

    def get_stats(self) -> dict:
        """Retourne les statistiques."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        for key in self._stats:
            self._stats[key] = 0


__all__ = [
    "ScopedQueryEngine",
    "QueryResponse",
    "QueryContext",
    "ClaimWithContext",
]
