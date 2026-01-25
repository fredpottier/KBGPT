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
from knowbase.stratified.models.information import (
    InformationMVP,
    InformationType,
    RhetoricalRole,
    SpanInfo,
    ValueInfo,
    ContextInfo,
    PromotionStatus,
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
        # PHASE 1.5: Enrichissement MVP V1 (Usage B - Challenge)
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.5] Enrichissement MVP V1...")

        mvp_enrichment_result = self.assertion_extractor.enrich_with_mvp_v1(
            assertions=promotion_result.promotable,
            context={"product": doc_title}
        )

        # Convertir les assertions enrichies en InformationMVP
        informations_mvp = []
        for enriched in mvp_enrichment_result.enriched:
            # Uniquement les assertions PROMOTED_LINKED ou PROMOTED_UNLINKED
            if enriched.promotion_status in [PromotionStatus.PROMOTED_LINKED, PromotionStatus.PROMOTED_UNLINKED]:
                # Trouver l'ancre pour cette assertion
                anchor_docitem_ids = []
                span_page = 0
                for assertion, anchor, _ in resolved:
                    if assertion.assertion_id == enriched.assertion.assertion_id:
                        anchor_docitem_ids = [anchor.docitem_id]
                        # Extraire la page depuis docitem si disponible
                        docitem = docitems.get(anchor.docitem_id.split(":")[-1])
                        if docitem and hasattr(docitem, 'page'):
                            span_page = docitem.page or 0
                        break

                # Mapper le type d'assertion
                info_type = self._map_to_information_type(enriched.assertion.assertion_type)
                rhetorical_role = self._map_to_rhetorical_role(enriched.assertion.assertion_type)

                info_mvp = InformationMVP(
                    information_id=f"info_mvp_{enriched.assertion.assertion_id}",
                    tenant_id=self.tenant_id,
                    document_id=doc_id,
                    text=enriched.assertion.text,
                    exact_quote=enriched.assertion.text,  # Utilise le texte comme quote
                    type=info_type,
                    rhetorical_role=rhetorical_role,
                    span=SpanInfo(page=span_page),
                    value=enriched.value if enriched.value else ValueInfo(),
                    context=ContextInfo(product=doc_title),
                    promotion_status=enriched.promotion_status,
                    promotion_reason=enriched.promotion_reason,
                    claimkey_id=enriched.claimkey_match.claimkey_id if enriched.claimkey_match else None,
                    confidence=enriched.assertion.confidence,
                    language=subject.language,
                    anchor_docitem_ids=anchor_docitem_ids
                )
                informations_mvp.append(info_mvp)

        logger.info(
            f"[OSMOSE:Pass1:1.5] {len(informations_mvp)} InformationMVP créées "
            f"({mvp_enrichment_result.stats.get('promoted_linked', 0)} LINKED)"
        )

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
            informations_mvp=informations_mvp,
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

    def _map_to_information_type(self, assertion_type: AssertionType) -> InformationType:
        """Mappe AssertionType vers InformationType pour MVP V1."""
        mapping = {
            AssertionType.DEFINITIONAL: InformationType.DEFINITIONAL,
            AssertionType.PRESCRIPTIVE: InformationType.PRESCRIPTIVE,
            AssertionType.CAUSAL: InformationType.CAUSAL,
            AssertionType.COMPARATIVE: InformationType.COMPARATIVE,
            AssertionType.FACTUAL: InformationType.DEFINITIONAL,
            AssertionType.CONDITIONAL: InformationType.PRESCRIPTIVE,
            AssertionType.PERMISSIVE: InformationType.PRESCRIPTIVE,
            AssertionType.PROCEDURAL: InformationType.DEFINITIONAL,
        }
        return mapping.get(assertion_type, InformationType.DEFINITIONAL)

    def _map_to_rhetorical_role(self, assertion_type: AssertionType) -> RhetoricalRole:
        """Mappe AssertionType vers RhetoricalRole pour MVP V1."""
        mapping = {
            AssertionType.DEFINITIONAL: RhetoricalRole.DEFINITION,
            AssertionType.PRESCRIPTIVE: RhetoricalRole.INSTRUCTION,
            AssertionType.CAUSAL: RhetoricalRole.FACT,
            AssertionType.COMPARATIVE: RhetoricalRole.FACT,
            AssertionType.FACTUAL: RhetoricalRole.FACT,
            AssertionType.CONDITIONAL: RhetoricalRole.CLAIM,
            AssertionType.PERMISSIVE: RhetoricalRole.CLAIM,
            AssertionType.PROCEDURAL: RhetoricalRole.EXAMPLE,
        }
        return mapping.get(assertion_type, RhetoricalRole.FACT)


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
