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
from knowbase.stratified.pass1.concept_refiner import (
    ConceptRefinerV2,
    SaturationMetrics,
)
from knowbase.stratified.pass09 import GlobalViewBuilder, GlobalView, Pass09Config
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
        tenant_id: str = "default",
        enable_pass09: bool = True,
        pass09_config: Optional[Pass09Config] = None,
        enable_pointer_mode: bool = False,
        enable_pass12b: bool = True,
    ):
        """
        Args:
            llm_client: Client LLM compatible
            allow_fallback: Autorise les heuristiques fallback (tests only)
            strict_promotion: Mode strict pour Promotion Policy (ALWAYS only)
            tenant_id: Identifiant du tenant
            enable_pass09: Active Pass 0.9 Global View Construction
            pass09_config: Configuration Pass 0.9 (optionnel)
            enable_pointer_mode: Active le mode Pointer-Based Extraction (anti-reformulation)
            enable_pass12b: Active Pass 1.2b - Raffinement itératif des concepts (V2.1)
        """
        self.llm_client = llm_client
        self.allow_fallback = allow_fallback
        self.strict_promotion = strict_promotion
        self.tenant_id = tenant_id
        self.enable_pass12b = enable_pass12b
        self.enable_pass09 = enable_pass09
        self.enable_pointer_mode = enable_pointer_mode

        # Initialiser Pass 0.9 Global View Builder
        self.global_view_builder = GlobalViewBuilder(
            llm_client=llm_client,
            config=pass09_config,
        ) if enable_pass09 else None

        # Initialiser les composants Pass 1
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

        # V2.1: Pass 1.2b - Raffinement itératif des concepts
        self.concept_refiner = ConceptRefinerV2(
            llm_client=llm_client
        ) if enable_pass12b else None

    def process(
        self,
        doc_id: str,
        doc_title: str,
        content: str,
        docitems: Dict[str, DocItem],
        chunks: Dict[str, str],
        source_url: Optional[str] = None,
        toc: Optional[str] = None,
        chunk_to_docitem_map: Optional[Dict[str, List[str]]] = None,
        sections: Optional[List[Dict]] = None,
        unit_index: Optional[Dict] = None,
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
            sections: Liste des sections depuis Pass 0 (pour Pass 0.9)
            unit_index: Index des unités depuis Pass 0 (pour Pointer-Based Extraction)
                       Si None et enable_pointer_mode=True, sera construit automatiquement

        Returns:
            Pass1Result avec toutes les structures sémantiques
        """
        import asyncio

        logger.info(f"[OSMOSE:Pass1] Début traitement: {doc_title[:50]}")

        # Calculer le hash du contenu
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # =====================================================================
        # PHASE 0.9: Global View Construction (NOUVEAU)
        # =====================================================================
        global_view: Optional[GlobalView] = None
        analysis_content = content  # Par défaut, utiliser le contenu brut

        if self.enable_pass09 and self.global_view_builder:
            logger.info("[OSMOSE:Pass0.9] Construction vue globale...")

            # Préparer les sections si non fournies ou vides
            if not sections:  # None ou liste vide
                # Créer des sections artificielles depuis les chunks
                sections = self._create_sections_from_chunks(chunks)
                logger.info(f"[OSMOSE:Pass0.9] Sections créées depuis chunks: {len(sections)}")

            try:
                # Utiliser build_sync pour éviter les problèmes avec asyncio.run()
                # dans un contexte FastAPI déjà async
                global_view = self.global_view_builder.build_sync(
                    doc_id=doc_id,
                    tenant_id=self.tenant_id,
                    sections=sections,
                    chunks=chunks,
                    doc_title=doc_title,
                    full_text=content,
                )

                # Utiliser le meta-document pour l'analyse
                if global_view and global_view.meta_document:
                    analysis_content = global_view.meta_document
                    logger.info(
                        f"[OSMOSE:Pass0.9] GlobalView construite: "
                        f"{len(analysis_content)} chars, "
                        f"{global_view.coverage.coverage_ratio:.1%} coverage"
                    )
                else:
                    logger.warning("[OSMOSE:Pass0.9] GlobalView vide, fallback sur content brut")

            except Exception as e:
                logger.error(f"[OSMOSE:Pass0.9] Erreur construction GlobalView: {e}")
                logger.info("[OSMOSE:Pass0.9] Fallback sur content brut")
        else:
            logger.info("[OSMOSE:Pass0.9] Pass 0.9 désactivé, utilisation content brut")

        # =====================================================================
        # PHASE 1.1: Document Analysis
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.1] Analyse structurelle...")

        toc_extracted = toc or self.document_analyzer.extract_toc_from_content(content)

        # Utiliser le TOC enrichi de GlobalView si disponible
        toc_for_analysis = toc_extracted
        if global_view and global_view.toc_enhanced:
            toc_for_analysis = global_view.toc_enhanced
            logger.info("[OSMOSE:Pass1:1.1] Utilisation TOC enrichie depuis GlobalView")

        subject, themes, is_hostile = self.document_analyzer.analyze(
            doc_id=doc_id,
            doc_title=doc_title,
            content=analysis_content,  # ← CHANGEMENT CLÉ: meta-document
            toc=toc_for_analysis
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

        # Budget adaptatif basé sur le nombre de sections
        n_sections = len(sections) if sections else None

        concepts, refused_terms = self.concept_identifier.identify(
            doc_id=doc_id,
            subject_text=subject.text,
            structure=subject.structure.value,
            themes=themes,
            content=analysis_content,  # ← CHANGEMENT CLÉ: meta-document
            is_hostile=is_hostile,
            language=subject.language,
            n_sections=n_sections  # Budget adaptatif (2026-01-27)
        )

        logger.info(
            f"[OSMOSE:Pass1:1.2] {len(concepts)} concepts identifiés, "
            f"{len(refused_terms)} termes refusés"
        )

        # =====================================================================
        # PHASE 1.3: Assertion Extraction
        # =====================================================================
        logger.info("[OSMOSE:Pass1:1.3] Extraction assertions...")

        # Mode Pointer-Based: extraction anti-reformulation
        pointer_results = None
        if self.enable_pointer_mode:
            logger.info("[OSMOSE:Pass1:1.3:POINTER] Mode Pointer-Based activé")
            pointer_results = self._extract_pointer_based(
                docitems=docitems,
                unit_index=unit_index,
                concepts=concepts,
                doc_language=subject.language,
            )

        # Extraction classique (utilisée si pointer non activé ou en complément)
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
        # PHASE 1.4b: Saturation Check + Pass 1.2b Itératif (V2.1)
        # =====================================================================
        if self.enable_pass12b and self.concept_refiner:
            logger.info("[OSMOSE:Pass1:1.4b] Vérification saturation conceptuelle...")

            # Convertir assertion_log en format dict pour le refiner
            assertion_log_dicts = [
                {
                    'assertion_id': a.assertion_id,
                    'text': a.text,
                    'type': a.type.value if a.type else None,
                    'status': a.status.value if a.status else None,
                    'reason': a.reason.value if a.reason else None,
                    'concept_id': a.concept_id,
                }
                for a in assertion_log
            ]

            iteration = 0
            prev_saturation = None

            while True:
                # Calculer métriques de saturation
                saturation = self.concept_refiner.calculate_saturation(assertion_log_dicts)

                logger.info(
                    f"[OSMOSE:Pass1:Saturation] Iteration {iteration}: "
                    f"promoted={saturation.promoted}, no_concept_match={saturation.no_concept_match} "
                    f"({saturation.no_concept_match_rate:.1%} of total), "
                    f"coverage={saturation.coverage_rate:.1%}"
                )

                # C4: Vérifier si itération nécessaire (rate > 10% ET count > 20)
                if not saturation.should_iterate:
                    logger.info(
                        f"[OSMOSE:Pass1:Saturation] Arrêt: "
                        f"rate={saturation.no_concept_match_rate:.1%} ou count={saturation.no_concept_match}"
                    )
                    break

                if iteration > 0 and prev_saturation:
                    # Vérifier rendement marginal
                    if not self.concept_refiner.should_continue_iteration(
                        prev_saturation, saturation, iteration, len(concepts)
                    ):
                        break

                # Pass 1.2b: Identifier concepts manquants
                logger.info(
                    f"[OSMOSE:Pass1:1.2b] Iteration {iteration + 1}: "
                    f"{saturation.no_concept_match} non-liées "
                    f"({saturation.quality_unlinked_count} de qualité)"
                )

                unlinked = [
                    a for a in assertion_log_dicts
                    if a.get('status') == 'ABSTAINED' and a.get('reason') == 'no_concept_match'
                ]

                new_concepts, refused = self.concept_refiner.refine_concepts(
                    unlinked_assertions=unlinked,
                    existing_concepts=[c.model_dump() for c in concepts],
                    themes=[t.model_dump() for t in themes],
                    language=subject.language
                )

                if not new_concepts:
                    logger.info(f"[OSMOSE:Pass1:1.2b] Aucun nouveau concept valide, arrêt")
                    break

                # Ajouter les nouveaux concepts
                for nc in new_concepts:
                    from knowbase.stratified.models import ConceptRole
                    concept = Concept(
                        concept_id=f"concept_{doc_id}_{len(concepts)}",
                        theme_id=nc.get('theme_id', themes[0].theme_id if themes else ""),
                        name=nc['name'],
                        role=ConceptRole(nc.get('role', 'STANDARD')),
                        lexical_triggers=nc.get('lexical_triggers', [])
                    )
                    concepts.append(concept)

                logger.info(f"[OSMOSE:Pass1:1.2b] +{len(new_concepts)} concepts → total {len(concepts)}")

                # Re-run linking uniquement sur les assertions non-liées
                unlinked_assertions = [
                    a for a in promotion_result.promotable
                    if any(
                        log.get('assertion_id') == a.assertion_id
                        and log.get('reason') == 'no_concept_match'
                        for log in assertion_log_dicts
                    )
                ]

                if unlinked_assertions:
                    new_links = self.assertion_extractor.link_to_concepts(
                        assertions=unlinked_assertions,
                        concepts=concepts
                    )

                    # Re-resolve les assertions nouvellement liées
                    new_resolved, new_failed = self.anchor_resolver.resolve_all(
                        assertions=unlinked_assertions,
                        links=new_links
                    )

                    # Mettre à jour les structures
                    for assertion, anchor, concept_id in new_resolved:
                        info = Information(
                            info_id=f"info_{uuid.uuid4().hex[:8]}",
                            concept_id=concept_id,
                            text=assertion.text,
                            type=assertion.assertion_type,
                            confidence=assertion.confidence,
                            anchor=anchor
                        )
                        informations.append(info)
                        resolved.append((assertion, anchor, concept_id))

                        # Mettre à jour assertion_log_dicts
                        for log in assertion_log_dicts:
                            if log.get('assertion_id') == assertion.assertion_id:
                                log['status'] = 'PROMOTED'
                                log['reason'] = 'promoted'
                                log['concept_id'] = concept_id
                                break

                prev_saturation = saturation
                iteration += 1

            logger.info(
                f"[OSMOSE:Pass1:Saturation] Final: {len(concepts)} concepts, "
                f"{saturation.coverage_rate:.1%} coverage après {iteration} itération(s)"
            )

            # Reconstruire assertion_log depuis assertion_log_dicts si modifié
            if iteration > 0:
                # Mettre à jour les entrées existantes dans assertion_log
                # (les nouveaux concepts sont déjà dans la liste concepts)
                pass  # Les mises à jour ont été faites in-place via assertion_log_dicts

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

    def _create_sections_from_chunks(self, chunks: Dict[str, str]) -> List[Dict]:
        """
        Crée des sections artificielles depuis les chunks.

        Utilisé quand les sections Pass 0 ne sont pas fournies.
        Regroupe les chunks par blocs de ~5 pour simuler des sections.
        """
        chunk_ids = list(chunks.keys())
        sections = []
        chunk_per_section = 5  # Environ 5 chunks par section virtuelle

        for i in range(0, len(chunk_ids), chunk_per_section):
            section_chunk_ids = chunk_ids[i : i + chunk_per_section]
            section_id = f"section_{i // chunk_per_section + 1}"
            sections.append({
                "id": section_id,
                "section_id": section_id,
                "title": f"Section {i // chunk_per_section + 1}",
                "level": 1,
                "chunk_ids": section_chunk_ids,
            })

        return sections

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

    # =========================================================================
    # POINTER-BASED EXTRACTION (Anti-Reformulation)
    # =========================================================================

    def _extract_pointer_based(
        self,
        docitems: Dict[str, DocItem],
        unit_index: Optional[Dict],
        concepts: List[Concept],
        doc_language: str,
    ) -> Optional[Dict]:
        """
        Extraction Pointer-Based: le LLM pointe vers des unités au lieu de copier.

        Cette méthode:
        1. Construit l'index des unités si non fourni
        2. Formate les unités pour le LLM (U1: text, U2: text, ...)
        3. Appelle le LLM pour extraire les concepts avec unit_id
        4. Valide les concepts pointés (3 niveaux)
        5. Reconstruit le texte verbatim depuis l'index

        Args:
            docitems: Dict docitem_id → DocItem
            unit_index: Index des unités (depuis Pass 0)
            concepts: Concepts déjà identifiés
            doc_language: Langue du document

        Returns:
            Dict avec 'anchored' (concepts validés), 'rejected', 'stats'
            ou None si erreur
        """
        try:
            from knowbase.stratified.pass1.assertion_unit_indexer import (
                AssertionUnitIndexer,
                format_units_for_llm,
            )
            from knowbase.stratified.pass1.pointer_validator import PointerValidator
            from knowbase.stratified.pass1.pointer_schemas import (
                parse_pointer_response,
                ConceptAnchored,
                Anchor,
            )
        except ImportError as e:
            logger.error(f"[OSMOSE:Pass1:POINTER] Import error: {e}")
            return None

        # 1. Construire l'index si non fourni
        if not unit_index:
            logger.info("[OSMOSE:Pass1:POINTER] Construction index unités...")
            indexer = AssertionUnitIndexer()
            unit_index = {}
            for docitem_id, docitem in docitems.items():
                text = getattr(docitem, 'text', '') or getattr(docitem, 'content', '') or ''
                item_type = getattr(docitem, 'item_type', None)
                if hasattr(item_type, 'value'):
                    item_type = item_type.value

                if text and len(text.strip()) >= 30:
                    result = indexer.index_docitem(docitem_id, text, item_type)
                    if result.units:
                        unit_index[docitem_id] = result

            logger.info(f"[OSMOSE:Pass1:POINTER] Index construit: {len(unit_index)} DocItems")

        if not unit_index:
            logger.warning("[OSMOSE:Pass1:POINTER] Aucune unité indexée, skip pointer mode")
            return None

        # 2. Extraire les concepts via LLM avec pointage EN PARALLÈLE
        # Fix 2026-01-27: Parallélisation comme assertion_extractor.py
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import os

        max_workers = int(os.environ.get("OSMOSE_LLM_WORKERS", 8))
        all_pointer_concepts = []
        total_units = 0

        # Préparer les tâches
        tasks = []
        for docitem_id, unit_result in unit_index.items():
            units = unit_result.units if hasattr(unit_result, 'units') else []
            if not units:
                continue
            total_units += len(units)
            units_text = format_units_for_llm(units)
            tasks.append((docitem_id, units_text))

        logger.info(
            f"[OSMOSE:Pass1:POINTER] Extraction parallèle: {len(tasks)} DocItems, "
            f"{max_workers} workers, {total_units} unités"
        )

        errors_count = 0

        # Extraction parallèle avec ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_docitem = {
                executor.submit(
                    self._call_llm_pointer_extraction,
                    docitem_id,
                    units_text,
                    doc_language,
                ): docitem_id
                for docitem_id, units_text in tasks
            }

            for future in as_completed(future_to_docitem):
                docitem_id = future_to_docitem[future]
                try:
                    pointer_concepts = future.result()
                    if pointer_concepts:
                        for pc in pointer_concepts:
                            pc['docitem_id'] = docitem_id
                        all_pointer_concepts.extend(pointer_concepts)
                except Exception as e:
                    errors_count += 1
                    logger.warning(f"[OSMOSE:Pass1:POINTER] Erreur {docitem_id}: {e}")

        if errors_count > 0:
            logger.warning(f"[OSMOSE:Pass1:POINTER] {errors_count} DocItems en erreur sur {len(tasks)}")

        logger.info(
            f"[OSMOSE:Pass1:POINTER] LLM extraction: {len(all_pointer_concepts)} concepts "
            f"depuis {total_units} unités"
        )

        if not all_pointer_concepts:
            return {'anchored': [], 'rejected': [], 'stats': {'total': 0}}

        # 3. Valider les concepts pointés
        validator = PointerValidator()
        valid, abstained, stats = validator.validate_batch(all_pointer_concepts, unit_index)

        # 4. Convertir en ConceptAnchored
        anchored_concepts = []
        for concept_dict in valid:
            # Trouver l'unité
            docitem_id = concept_dict.get('docitem_id', '')
            unit_id = concept_dict.get('unit_id', '')
            unit_result = unit_index.get(docitem_id)

            if unit_result:
                unit = unit_result.get_unit_by_local_id(unit_id) if hasattr(unit_result, 'get_unit_by_local_id') else None
                if unit:
                    anchor = Anchor(
                        docitem_id=docitem_id,
                        unit_id=unit_id,
                        char_start=unit.char_start,
                        char_end=unit.char_end,
                        unit_type=unit.unit_type,
                    )

                    anchored = ConceptAnchored(
                        label=concept_dict.get('label', ''),
                        concept_type=concept_dict.get('type', 'FACTUAL'),
                        exact_quote=concept_dict.get('exact_quote', unit.text),
                        anchor=anchor,
                        validation_status="VALID" if not concept_dict.get('_downgraded_from') else "DOWNGRADED",
                        validation_score=0.0,  # À enrichir
                        value_kind=concept_dict.get('value_kind'),
                        downgraded_from=concept_dict.get('_downgraded_from'),
                    )
                    anchored_concepts.append(anchored)

        logger.info(
            f"[OSMOSE:Pass1:POINTER] Résultat: {len(anchored_concepts)} concepts ancrés, "
            f"{len(abstained)} rejetés ({stats.abstain_rate:.1%} ABSTAIN rate)"
        )

        return {
            'anchored': anchored_concepts,
            'rejected': abstained,
            'stats': {
                'total': stats.total,
                'valid': stats.valid,
                'downgraded': stats.downgraded,
                'abstained': stats.abstained,
                'valid_rate': stats.valid_rate,
            },
        }

    def _call_llm_pointer_extraction(
        self,
        docitem_id: str,
        units_text: str,
        language: str,
    ) -> List[Dict]:
        """
        Appelle le LLM pour extraire les concepts en mode pointer.

        Args:
            docitem_id: ID du DocItem
            units_text: Texte formaté avec unités (U1: ..., U2: ...)
            language: Langue du document

        Returns:
            Liste de dicts avec keys: label, type, unit_id, confidence, value_kind
        """
        if not self.llm_client:
            logger.warning("[OSMOSE:Pass1:POINTER] Pas de client LLM, skip extraction")
            return []

        # Charger le prompt
        from pathlib import Path
        import yaml

        prompts_path = Path(__file__).parent.parent / "prompts" / "pass1_prompts.yaml"
        prompts = {}
        if prompts_path.exists():
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = yaml.safe_load(f) or {}

        prompt_config = prompts.get("pointer_concept_extraction", {})
        system_prompt = prompt_config.get("system", self._default_pointer_system())
        user_template = prompt_config.get("user", self._default_pointer_user())

        user_prompt = user_template.format(
            docitem_id=docitem_id,
            language=language,
            units_text=units_text[:3000],  # Limite pour éviter troncature
        )

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000
            )

            # Parser la réponse
            return self._parse_pointer_response(response)

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass1:POINTER] Erreur LLM pour {docitem_id}: {e}")
            return []

    def _parse_pointer_response(self, response: str) -> List[Dict]:
        """Parse la réponse JSON du LLM pointer extraction."""
        import json
        import re

        # Extraire le JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            concepts = data.get("concepts", [])

            # Valider le format de chaque concept
            valid_concepts = []
            for c in concepts:
                unit_id = c.get("unit_id", "")
                if unit_id and unit_id.startswith("U") and unit_id[1:].isdigit():
                    valid_concepts.append({
                        "label": c.get("label", ""),
                        "type": c.get("type", "FACTUAL"),
                        "unit_id": unit_id,
                        "confidence": c.get("confidence", 0.8),
                        # FIX 2026-01-27: value_kind sera détecté automatiquement par le validator
                        # "value_kind": c.get("value_kind"),  # SUPPRIMÉ
                    })
                else:
                    logger.debug(f"[OSMOSE:Pass1:POINTER] Invalid unit_id: {unit_id}")

            return valid_concepts

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass1:POINTER] JSON parse error: {e}")
            return []

    def _default_pointer_system(self) -> str:
        """Prompt système par défaut pour extraction pointer."""
        # FIX 2026-01-27: Labels doivent utiliser mots du texte, pas de value_kind
        return """Tu es un expert en extraction de concepts pour OSMOSE.

MÉTHODE POINTER-BASED:
Le texte est découpé en unités numérotées (U1, U2, U3...).
Tu dois POINTER vers l'unité qui contient le concept, PAS copier le texte.

TYPES DE CONCEPTS:
- PRESCRIPTIVE: Obligation, règle ("must", "shall", "required")
- DEFINITIONAL: Définition, explication
- FACTUAL: Information vérifiable
- PERMISSIVE: Option, possibilité

RÈGLES CRITIQUES:
1. Retourne UNIQUEMENT le numéro d'unité (U1, U2...)
2. NE PROPOSE UN CONCEPT QUE SI TU PEUX POINTER UNE UNITÉ
3. SI AUCUNE UNITÉ NE CORRESPOND, NE RETOURNE PAS LE CONCEPT
4. ⚠️ Le LABEL doit contenir AU MOINS 2 MOTS présents dans le texte de l'unité
5. ❌ INTERDIT: labels abstraits ("security requirement", "data protection")
6. ✅ UTILISER les mots exacts du texte pour construire le label"""

    def _default_pointer_user(self) -> str:
        """Prompt utilisateur par défaut pour extraction pointer."""
        # FIX 2026-01-27: Labels doivent utiliser mots du texte, suppression value_kind
        return """Extrais les concepts de ce texte avec unités numérotées.

DOCITEM_ID: {docitem_id}
LANGUE: {language}

TEXTE AVEC UNITÉS:
{units_text}

⚠️ RÈGLE LABEL: Le label DOIT utiliser des MOTS PRÉSENTS dans l'unité pointée.
❌ INTERDIT: labels abstraits ("security requirement", "compliance standard")
✅ CORRECT: labels avec mots du texte ("TLS version", "data encryption", "audit trail")

Réponds avec ce JSON:
```json
{{
  "concepts": [
    {{"label": "Nom avec MOTS DU TEXTE", "type": "PRESCRIPTIVE", "unit_id": "U1", "confidence": 0.9}}
  ]
}}
```"""


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
    sections: Optional[List[Dict]] = None,
    unit_index: Optional[Dict] = None,
    enable_pass09: bool = True,
    enable_pointer_mode: bool = False,
    **kwargs
) -> Pass1Result:
    """
    Fonction utilitaire pour exécuter Pass 1.

    Wrapper simplifié autour de Pass1OrchestratorV2.

    Args:
        sections: Liste des sections depuis Pass 0 (pour Pass 0.9)
        unit_index: Index des unités depuis Pass 0 (pour Pointer-Based Extraction)
        enable_pass09: Active Pass 0.9 Global View Construction (défaut: True)
        enable_pointer_mode: Active Pointer-Based Extraction (défaut: False)
    """
    orchestrator = Pass1OrchestratorV2(
        llm_client=llm_client,
        tenant_id=tenant_id,
        enable_pass09=enable_pass09,
        enable_pointer_mode=enable_pointer_mode,
        **kwargs
    )
    return orchestrator.process(
        doc_id=doc_id,
        doc_title=doc_title,
        content=content,
        docitems=docitems,
        chunks=chunks,
        chunk_to_docitem_map=chunk_to_docitem_map,
        sections=sections,
        unit_index=unit_index,
    )
