"""
OSMOSE Pipeline V2 - Pass 1 Orchestrator
=========================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Orchestre les phases de Pass 1 (Lecture Stratifiée):
- 1.1 Document Analysis → Subject + Structure + Themes
- 1.2 Concept Identification → Concepts (max 15)
- 1.3 Assertion Extraction → RawAssertions
- 1.3b Anchor Resolution → chunk_id → docitem_id (CRITIQUE)
- 1.4 Semantic Linking + Promotion → Information + AssertionLog

Retourne: Pass1Result (contrat JSON canonique)
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import hashlib
import uuid

from knowbase.stratified.models import (
    DocumentMeta,
    Subject,
    Theme,
    Concept,
    Information,
    Anchor,
    DocItem,
    AssertionType,
    AssertionStatus,
    AssertionLogReason,
    AssertionLogEntry,
    Pass1Stats,
    Pass1Result,
)
from knowbase.stratified.pass1.document_analyzer import DocumentAnalyzerV2
from knowbase.stratified.pass1.concept_identifier import ConceptIdentifierV2
from knowbase.stratified.pass1.assertion_extractor import (
    AssertionExtractorV2,
    RawAssertion,
    ConceptLink,
    PromotionResult,
)
from knowbase.stratified.pass1.anchor_resolver import (
    AnchorResolverV2,
    build_chunk_to_docitem_mapping,
)

logger = logging.getLogger(__name__)


class Pass1OrchestratorV2:
    """
    Orchestrateur Pass 1 pour Pipeline V2.

    Enchaîne les phases de lecture stratifiée et produit un Pass1Result
    conforme au contrat JSON canonique.

    Usage:
        orchestrator = Pass1OrchestratorV2(llm_client=client)
        result = orchestrator.process(
            doc_id="doc_123",
            doc_title="Mon Document",
            content="...",
            docitems={...},
            chunks={...}
        )
    """

    def __init__(
        self,
        llm_client=None,
        allow_fallback: bool = False,
        strict_promotion: bool = True,
        tenant_id: str = "default"
    ):
        """
        Args:
            llm_client: Client LLM compatible
            allow_fallback: Autorise les heuristiques fallback (tests only)
            strict_promotion: Mode strict pour Promotion Policy (ALWAYS only)
            tenant_id: Identifiant du tenant
        """
        self.llm_client = llm_client
        self.allow_fallback = allow_fallback
        self.strict_promotion = strict_promotion
        self.tenant_id = tenant_id

        # Initialiser les composants
        self.document_analyzer = DocumentAnalyzerV2(
            llm_client=llm_client,
            allow_fallback=allow_fallback
        )
        self.concept_identifier = ConceptIdentifierV2(
            llm_client=llm_client,
            allow_fallback=allow_fallback
        )
        self.assertion_extractor = AssertionExtractorV2(
            llm_client=llm_client,
            allow_fallback=allow_fallback,
            strict_promotion=strict_promotion
        )
        self.anchor_resolver = AnchorResolverV2()

    def process(
        self,
        doc_id: str,
        doc_title: str,
        content: str,
        docitems: Dict[str, DocItem],
        chunks: Dict[str, str],
        source_url: Optional[str] = None,
        toc: Optional[str] = None,
        chunk_to_docitem_map: Optional[Dict[str, List[str]]] = None
    ) -> Pass1Result:
        """
        Exécute Pass 1 complet sur un document.

        Args:
            doc_id: Identifiant du document
            doc_title: Titre du document
            content: Contenu textuel complet
            docitems: Dict docitem_id → DocItem (depuis Pass 0)
            chunks: Dict chunk_id → texte (pour extraction assertions)
            source_url: URL source du document
            toc: Table des matières
            chunk_to_docitem_map: Mapping pré-calculé chunk_id → [docitem_ids]
                                  Si None, sera reconstruit automatiquement

        Returns:
            Pass1Result avec toutes les structures sémantiques
        """
        logger.info(f"[OSMOSE:Pass1] Début traitement: {doc_title[:50]}")

        # Calculer le hash du contenu
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # =====================================================================
        # PHASE 1.1: Document Analysis
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.1] Analyse structurelle...")

        toc_extracted = toc or self.document_analyzer.extract_toc_from_content(content)
        subject, themes, is_hostile = self.document_analyzer.analyze(
            doc_id=doc_id,
            doc_title=doc_title,
            content=content,
            toc=toc_extracted
        )

        logger.info(
            f"[OSMOSE:Pass1:1.1] Sujet: {subject.text[:50]}... | "
            f"Structure: {subject.structure.value} | "
            f"Themes: {len(themes)} | "
            f"Hostile: {is_hostile}"
        )

        # =====================================================================
        # PHASE 1.2: Concept Identification
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.2] Identification concepts...")

        concepts, refused_terms = self.concept_identifier.identify(
            doc_id=doc_id,
            subject_text=subject.text,
            structure=subject.structure.value,
            themes=themes,
            content=content,
            is_hostile=is_hostile,
            language=subject.language
        )

        logger.info(
            f"[OSMOSE:Pass1:1.2] {len(concepts)} concepts identifiés, "
            f"{len(refused_terms)} termes refusés"
        )

        # =====================================================================
        # PHASE 1.3: Assertion Extraction
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.3] Extraction assertions...")

        raw_assertions = self.assertion_extractor.extract_assertions(
            chunks=chunks,
            doc_language=subject.language
        )

        # Filtrage par Promotion Policy
        promotion_result = self.assertion_extractor.filter_by_promotion_policy(raw_assertions)

        logger.info(
            f"[OSMOSE:Pass1:1.3] {len(raw_assertions)} assertions extraites → "
            f"{len(promotion_result.promotable)} promotables"
        )

        # Liaison sémantique aux concepts
        concept_links = self.assertion_extractor.link_to_concepts(
            assertions=promotion_result.promotable,
            concepts=concepts
        )

        # =====================================================================
        # PHASE 1.3b: Anchor Resolution (CRITIQUE)
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.3b] Résolution ancrages...")

        # Utiliser le mapping pré-calculé si fourni, sinon le reconstruire
        if chunk_to_docitem_map is None:
            chunk_to_docitem_map = build_chunk_to_docitem_mapping(chunks, docitems)
            logger.debug("[OSMOSE:Pass1:1.3b] Mapping chunk→DocItem reconstruit")
        else:
            logger.info(f"[OSMOSE:Pass1:1.3b] Utilisation mapping pré-calculé ({len(chunk_to_docitem_map)} chunks)")

        self.anchor_resolver.set_context(
            chunk_to_docitem_map=chunk_to_docitem_map,
            docitems=docitems,
            chunks=chunks
        )

        resolved, failed = self.anchor_resolver.resolve_all(
            assertions=promotion_result.promotable,
            links=concept_links
        )

        # =====================================================================
        # PHASE 1.4: Création Information + AssertionLog
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.4] Création Information + Log...")

        informations = []
        assertion_log = []

        # Créer les Information pour les assertions résolues
        for assertion, anchor, concept_id in resolved:
            info = Information(
                info_id=f"info_{uuid.uuid4().hex[:8]}",
                concept_id=concept_id,
                text=assertion.text,
                type=assertion.assertion_type,
                confidence=assertion.confidence,
                anchor=anchor
            )
            informations.append(info)

            # Log: PROMOTED
            assertion_log.append(AssertionLogEntry(
                assertion_id=assertion.assertion_id,
                text=assertion.text,
                type=assertion.assertion_type,
                confidence=assertion.confidence,
                status=AssertionStatus.PROMOTED,
                reason=AssertionLogReason.PROMOTED,
                concept_id=concept_id,
                anchor=anchor
            ))

        # Logger les assertions non résolues (ABSTAINED)
        for assertion, reason, details in failed:
            assertion_log.append(AssertionLogEntry(
                assertion_id=assertion.assertion_id,
                text=assertion.text,
                type=assertion.assertion_type,
                confidence=assertion.confidence,
                status=AssertionStatus.ABSTAINED,
                reason=reason,
                concept_id=None,
                anchor=None
            ))

        # Logger les assertions filtrées par Promotion Policy (REJECTED)
        for assertion, policy_reason in promotion_result.abstained:
            reason = (
                AssertionLogReason.LOW_CONFIDENCE
                if policy_reason == "low_confidence"
                else AssertionLogReason.POLICY_REJECTED
            )
            assertion_log.append(AssertionLogEntry(
                assertion_id=assertion.assertion_id,
                text=assertion.text,
                type=assertion.assertion_type,
                confidence=assertion.confidence,
                status=AssertionStatus.REJECTED,
                reason=reason,
                concept_id=None,
                anchor=None
            ))

        # =====================================================================
        # CONSTRUIRE LE RÉSULTAT
        # =====================================================================
        logger.info("[OSMOSE:Pass1] Construction Pass1Result...")

        doc_meta = DocumentMeta(
            doc_id=doc_id,
            title=doc_title,
            language=subject.language,
            content_hash=content_hash,
            source_url=source_url
        )

        stats = Pass1Stats(
            themes_count=len(themes),
            concepts_count=len(concepts),
            assertions_total=len(assertion_log),
            assertions_promoted=len(informations),
            assertions_abstained=sum(1 for a in assertion_log if a.status == AssertionStatus.ABSTAINED),
            assertions_rejected=sum(1 for a in assertion_log if a.status == AssertionStatus.REJECTED)
        )

        result = Pass1Result(
            tenant_id=self.tenant_id,
            doc=doc_meta,
            subject=subject,
            themes=themes,
            concepts=concepts,
            informations=informations,
            assertion_log=assertion_log,
            stats=stats
        )

        # Log final
        logger.info(
            f"[OSMOSE:Pass1] TERMINÉ: "
            f"{stats.themes_count} themes, "
            f"{stats.concepts_count} concepts, "
            f"{stats.assertions_promoted} informations, "
            f"({stats.assertions_abstained} abstained, {stats.assertions_rejected} rejected)"
        )

        return result


# ============================================================================
# FONCTION UTILITAIRE
# ============================================================================

def run_pass1(
    doc_id: str,
    doc_title: str,
    content: str,
    docitems: Dict[str, DocItem],
    chunks: Dict[str, str],
    llm_client=None,
    tenant_id: str = "default",
    chunk_to_docitem_map: Optional[Dict[str, List[str]]] = None,
    **kwargs
) -> Pass1Result:
    """
    Fonction utilitaire pour exécuter Pass 1.

    Wrapper simplifié autour de Pass1OrchestratorV2.
    """
    orchestrator = Pass1OrchestratorV2(
        llm_client=llm_client,
        tenant_id=tenant_id,
        **kwargs
    )
    return orchestrator.process(
        doc_id=doc_id,
        doc_title=doc_title,
        content=content,
        docitems=docitems,
        chunks=chunks,
        chunk_to_docitem_map=chunk_to_docitem_map
    )
