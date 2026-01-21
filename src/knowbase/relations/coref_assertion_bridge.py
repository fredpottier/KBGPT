"""
Bridge entre COREF (Pass 0.5) et Assertion Layer.

Ce module fournit l'interface pour exploiter les chaînes de coréférence
dans la création d'assertions DISCURSIVE avec basis=COREF.

Règles d'utilisation (ADR Scope vs Assertion):
- COREF ne crée PAS d'assertions directement
- COREF fournit des PREUVES de co-référence pour des assertions existantes
- Une assertion DISCURSIVE+COREF nécessite:
  1. Une chaîne de coréférence validée par Pass 0.5
  2. Un pattern discursif détecté (ALTERNATIVE, DEFAULT, etc.)
  3. La résolution de coréférence comme bridge entre les concepts

Ref: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md
Ref: src/knowbase/ingestion/pipelines/pass05_coref.py

Author: Claude Code
Date: 2026-01-21
"""

import logging
from typing import List, Optional, Dict, Any, Tuple

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.relations.types import (
    DiscursiveBasis,
    EvidenceSpan,
    EvidenceSpanRole,
    EvidenceBundle,
)

logger = logging.getLogger(__name__)


class CorefChainInfo:
    """Informations sur une chaîne de coréférence."""

    def __init__(
        self,
        chain_id: str,
        doc_id: str,
        doc_version_id: str,
        mention_ids: List[str],
        representative_mention_id: str,
        confidence: float,
        method: str,
    ):
        self.chain_id = chain_id
        self.doc_id = doc_id
        self.doc_version_id = doc_version_id
        self.mention_ids = mention_ids
        self.representative_mention_id = representative_mention_id
        self.confidence = confidence
        self.method = method


class MentionInfo:
    """Informations sur une mention dans le texte."""

    def __init__(
        self,
        mention_id: str,
        surface: str,
        span_start: int,
        span_end: int,
        chunk_id: Optional[str],
        docitem_id: Optional[str],
        mention_type: str,
        sentence_index: Optional[int] = None,
    ):
        self.mention_id = mention_id
        self.surface = surface
        self.span_start = span_start
        self.span_end = span_end
        self.chunk_id = chunk_id
        self.docitem_id = docitem_id
        self.mention_type = mention_type
        self.sentence_index = sentence_index


class CorefAssertionBridge:
    """
    Bridge entre COREF et Assertion Layer.

    Permet de:
    1. Récupérer les chaînes de coréférence pour un document
    2. Vérifier si deux concepts sont liés par coréférence
    3. Créer des EvidenceSpan basés sur COREF pour les assertions

    NOTE IMPORTANTE:
    Ce bridge ne crée PAS d'assertions. Il fournit des preuves
    pour des assertions détectées par d'autres moyens (patterns discursifs).
    """

    # Seuil minimum de confiance COREF pour utiliser comme preuve
    MIN_COREF_CONFIDENCE = 0.75

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le bridge.

        Args:
            neo4j_client: Client Neo4j (crée un nouveau si non fourni)
            tenant_id: ID du tenant
        """
        self.neo4j_client = neo4j_client or Neo4jClient()
        self.tenant_id = tenant_id

    def get_coref_chains_for_document(
        self,
        doc_version_id: str,
    ) -> List[CorefChainInfo]:
        """
        Récupère toutes les chaînes de coréférence d'un document.

        Args:
            doc_version_id: ID de la version du document

        Returns:
            Liste des chaînes de coréférence
        """
        query = """
        MATCH (c:CoreferenceChain {
            tenant_id: $tenant_id,
            doc_version_id: $doc_version_id
        })
        WHERE c.confidence >= $min_confidence
        RETURN c.chain_id AS chain_id,
               c.doc_id AS doc_id,
               c.doc_version_id AS doc_version_id,
               c.mention_ids AS mention_ids,
               c.representative_mention_id AS representative_mention_id,
               c.confidence AS confidence,
               c.method AS method
        """

        try:
            results = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                doc_version_id=doc_version_id,
                min_confidence=self.MIN_COREF_CONFIDENCE,
            )

            chains = []
            for record in results:
                chains.append(CorefChainInfo(
                    chain_id=record["chain_id"],
                    doc_id=record["doc_id"],
                    doc_version_id=record["doc_version_id"],
                    mention_ids=record["mention_ids"] or [],
                    representative_mention_id=record["representative_mention_id"],
                    confidence=record["confidence"],
                    method=record["method"] or "unknown",
                ))
            return chains

        except Exception as e:
            logger.error(f"[CorefAssertionBridge] Error fetching chains: {e}")
            return []

    def get_mentions_for_chain(
        self,
        chain_id: str,
    ) -> List[MentionInfo]:
        """
        Récupère les mentions d'une chaîne de coréférence.

        Args:
            chain_id: ID de la chaîne

        Returns:
            Liste des mentions
        """
        query = """
        MATCH (c:CoreferenceChain {chain_id: $chain_id, tenant_id: $tenant_id})
        MATCH (m:MentionSpan)
        WHERE m.mention_id IN c.mention_ids
        RETURN m.mention_id AS mention_id,
               m.surface AS surface,
               m.span_start AS span_start,
               m.span_end AS span_end,
               m.chunk_id AS chunk_id,
               m.docitem_id AS docitem_id,
               m.mention_type AS mention_type,
               m.sentence_index AS sentence_index
        ORDER BY m.span_start
        """

        try:
            results = self.neo4j_client.execute_query(
                query,
                chain_id=chain_id,
                tenant_id=self.tenant_id,
            )

            mentions = []
            for record in results:
                mentions.append(MentionInfo(
                    mention_id=record["mention_id"],
                    surface=record["surface"],
                    span_start=record["span_start"],
                    span_end=record["span_end"],
                    chunk_id=record.get("chunk_id"),
                    docitem_id=record.get("docitem_id"),
                    mention_type=record["mention_type"] or "UNKNOWN",
                    sentence_index=record.get("sentence_index"),
                ))
            return mentions

        except Exception as e:
            logger.error(f"[CorefAssertionBridge] Error fetching mentions: {e}")
            return []

    def check_coref_link(
        self,
        doc_version_id: str,
        surface_a: str,
        surface_b: str,
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """
        Vérifie si deux surfaces sont liées par coréférence.

        Args:
            doc_version_id: ID de la version du document
            surface_a: Première surface textuelle
            surface_b: Deuxième surface textuelle

        Returns:
            Tuple (found, confidence, chain_id)
        """
        query = """
        MATCH (c:CoreferenceChain {
            tenant_id: $tenant_id,
            doc_version_id: $doc_version_id
        })
        WHERE c.confidence >= $min_confidence
        WITH c
        MATCH (m1:MentionSpan), (m2:MentionSpan)
        WHERE m1.mention_id IN c.mention_ids
          AND m2.mention_id IN c.mention_ids
          AND toLower(m1.surface) = toLower($surface_a)
          AND toLower(m2.surface) = toLower($surface_b)
        RETURN c.chain_id AS chain_id,
               c.confidence AS confidence
        LIMIT 1
        """

        try:
            results = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                doc_version_id=doc_version_id,
                surface_a=surface_a,
                surface_b=surface_b,
                min_confidence=self.MIN_COREF_CONFIDENCE,
            )

            if results:
                record = results[0]
                return True, record["confidence"], record["chain_id"]
            return False, None, None

        except Exception as e:
            logger.error(f"[CorefAssertionBridge] Error checking coref: {e}")
            return False, None, None

    def create_coref_evidence_span(
        self,
        mention: MentionInfo,
        chain_confidence: float,
        full_text: str,
    ) -> EvidenceSpan:
        """
        Crée un EvidenceSpan basé sur une mention COREF.

        Le span inclut le contexte autour de la mention pour
        permettre une citation intelligible.

        Args:
            mention: Information sur la mention
            chain_confidence: Confiance de la chaîne de coréférence
            full_text: Texte complet du document

        Returns:
            EvidenceSpan avec role=MENTION (la coref sert de bridge)
        """
        # Extraire le contexte (50 chars avant/après)
        context_start = max(0, mention.span_start - 50)
        context_end = min(len(full_text), mention.span_end + 50)

        span_text = full_text[context_start:context_end]

        return EvidenceSpan(
            doc_item_id=mention.docitem_id or "unknown",
            role=EvidenceSpanRole.MENTION,
            text_excerpt=span_text,
            concept_surface_form=mention.surface,
        )

    def get_coref_evidence_for_concepts(
        self,
        doc_version_id: str,
        concept_surface_a: str,
        concept_surface_b: str,
        full_text: str,
    ) -> Tuple[bool, List[EvidenceSpan], float]:
        """
        Récupère les preuves COREF liant deux concepts.

        Cette méthode est utilisée quand un pattern discursif est détecté
        entre deux concepts, et qu'on veut vérifier si COREF renforce
        la preuve via une chaîne de coréférence.

        Args:
            doc_version_id: ID de la version du document
            concept_surface_a: Surface du premier concept
            concept_surface_b: Surface du deuxième concept
            full_text: Texte complet du document

        Returns:
            Tuple (has_coref_support, evidence_spans, confidence)
        """
        # Vérifier s'il existe un lien COREF
        found, confidence, chain_id = self.check_coref_link(
            doc_version_id=doc_version_id,
            surface_a=concept_surface_a,
            surface_b=concept_surface_b,
        )

        if not found or chain_id is None:
            return False, [], 0.0

        # Récupérer les mentions de la chaîne
        mentions = self.get_mentions_for_chain(chain_id)

        if not mentions:
            return False, [], 0.0

        # Créer les EvidenceSpan pour les mentions pertinentes
        evidence_spans = []
        for mention in mentions:
            if mention.surface.lower() in [
                concept_surface_a.lower(),
                concept_surface_b.lower()
            ]:
                span = self.create_coref_evidence_span(
                    mention=mention,
                    chain_confidence=confidence or 0.0,
                    full_text=full_text,
                )
                evidence_spans.append(span)

        return True, evidence_spans, confidence or 0.0


def get_coref_assertion_bridge(
    tenant_id: str = "default",
    neo4j_client: Optional[Neo4jClient] = None,
) -> CorefAssertionBridge:
    """
    Factory pour créer un CorefAssertionBridge.

    Args:
        tenant_id: ID du tenant
        neo4j_client: Client Neo4j optionnel

    Returns:
        Instance de CorefAssertionBridge
    """
    return CorefAssertionBridge(
        neo4j_client=neo4j_client,
        tenant_id=tenant_id,
    )


def can_use_coref_as_evidence(
    doc_version_id: str,
    concept_a: str,
    concept_b: str,
    bridge: Optional[CorefAssertionBridge] = None,
    tenant_id: str = "default",
) -> Tuple[bool, float]:
    """
    Vérifie rapidement si COREF peut servir de preuve pour deux concepts.

    Fonction utilitaire pour les extracteurs de patterns discursifs.

    Args:
        doc_version_id: ID de la version du document
        concept_a: Surface du premier concept
        concept_b: Surface du deuxième concept
        bridge: Instance de CorefAssertionBridge (optionnel)
        tenant_id: ID du tenant

    Returns:
        Tuple (can_use, confidence)
    """
    if bridge is None:
        bridge = get_coref_assertion_bridge(tenant_id=tenant_id)

    found, confidence, _ = bridge.check_coref_link(
        doc_version_id=doc_version_id,
        surface_a=concept_a,
        surface_b=concept_b,
    )

    return found, confidence or 0.0
