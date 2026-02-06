"""
OSMOSE Pipeline V2.2 - Orchestrateur Extract-then-Structure
============================================================
ADR: doc/ongoing/ADR_HYBRID_EXTRACT_THEN_STRUCTURE_2026-02-01.md

Séquence:
1. Vérifier zones
2. Détecter langue
3. Pass 1.A: extract_and_embed
4. Pass 1.B: cluster zone-first
5. Pass 1.C: structuration a posteriori
6. Pass 1.D: validation gate
7. Anchor resolution (réutilise V2.1)
8. Construire Pass1Result compatible V2.1

Compatibilité: le Pass1Result produit est identique en structure à V2.1.
Le Persister, Pass 2, et l'API ne changent pas.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from knowbase.stratified.models import (
    Anchor,
    AssertionLogEntry,
    AssertionLogReason,
    AssertionStatus,
    AssertionType,
    Concept,
    DocItem,
    DocumentMeta,
    Information,
    Pass1Result,
    Pass1Stats,
    Subject,
    Theme,
)
from knowbase.stratified.pass09.models import GlobalView, Zone
from knowbase.stratified.pass1_v22.local_extractor import LocalAssertionExtractor
from knowbase.stratified.pass1_v22.models import (
    AssertionCluster,
    ConceptStatus,
    ZonedAssertion,
)
from knowbase.stratified.pass1_v22.structure_builder import StructureBuilder
from knowbase.stratified.pass1_v22.validation_gate import ValidationGate, compute_budget
from knowbase.stratified.pass1_v22.zone_clusterer import ZoneFirstClusterer

logger = logging.getLogger(__name__)


class Pass1OrchestratorV22:
    """
    Orchestrateur V2.2 — Pipeline Extract-then-Structure.

    Produit un Pass1Result compatible V2.1 pour que le Persister,
    Pass 2 et l'API fonctionnent sans modification.
    """

    def __init__(
        self,
        llm_client=None,
        allow_fallback: bool = False,
        strict_promotion: bool = False,
        tenant_id: str = "default",
        max_workers: int = 8,
    ):
        self.llm_client = llm_client
        self.allow_fallback = allow_fallback
        self.strict_promotion = strict_promotion
        self.tenant_id = tenant_id
        self.max_workers = max_workers

        # Sous-composants
        self.local_extractor = LocalAssertionExtractor(
            llm_client=llm_client,
            allow_fallback=allow_fallback,
            strict_promotion=strict_promotion,
            max_workers=max_workers,
        )
        self.zone_clusterer = ZoneFirstClusterer()
        self.structure_builder = StructureBuilder(
            llm_client=llm_client,
            max_workers=max_workers,
        )
        self.validation_gate = ValidationGate()

    def process(
        self,
        doc_id: str,
        doc_title: str,
        content: str,
        docitems: Dict[str, DocItem],
        chunks: Dict[str, str],
        global_view: GlobalView,
        chunk_to_docitem_map: Dict,
        sections: List[Dict],
        unit_index: Optional[Dict] = None,
    ) -> Pass1Result:
        """
        Exécute le pipeline V2.2 complet.

        Args:
            doc_id: ID du document
            doc_title: Titre du document
            content: Texte complet du document
            docitems: Mapping docitem_id -> DocItem
            chunks: Mapping chunk_id -> texte
            global_view: GlobalView (DOIT contenir zones)
            chunk_to_docitem_map: Mapping chunk_id -> [docitem_ids]
            sections: Liste des sections Pass 0
            unit_index: Index d'unités (optionnel, non utilisé en V2.2)

        Returns:
            Pass1Result compatible V2.1
        """
        logger.info(
            f"[OSMOSE:Pass1:V2.2] === Début processing {doc_id} ==="
        )

        # 1. Vérifier zones
        zones = global_view.zones
        if not zones:
            logger.error(
                f"[OSMOSE:Pass1:V2.2] ERREUR: GlobalView sans zones pour {doc_id}. "
                "Retour fallback."
            )
            return self._build_empty_result(doc_id, doc_title, content)

        logger.info(
            f"[OSMOSE:Pass1:V2.2] {len(zones)} zones, "
            f"{len(chunks)} chunks, {len(docitems)} docitems"
        )

        # 2. Détecter langue
        doc_language = self._detect_language(content)

        # 3. Construire chunk_to_section_map
        chunk_to_section_map = self._build_chunk_to_section_map(
            sections, chunks, global_view
        )

        # =====================================================================
        # Pass 1.A: Extraction locale + embeddings
        # =====================================================================
        logger.info(f"[OSMOSE:Pass1:V2.2] --- Pass 1.A: Extraction ---")
        assertions, embeddings = self.local_extractor.extract_and_embed(
            chunks=chunks,
            zones=zones,
            chunk_to_section_map=chunk_to_section_map,
            doc_language=doc_language,
        )

        if not assertions:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2] Aucune assertion extraite pour {doc_id}"
            )
            return self._build_empty_result(doc_id, doc_title, content)

        # =====================================================================
        # Pass 1.B: Clustering zone-first
        # =====================================================================
        logger.info(f"[OSMOSE:Pass1:V2.2] --- Pass 1.B: Clustering ---")
        clusters, unlinked_indices = self.zone_clusterer.cluster(
            assertions=assertions,
            embeddings=embeddings,
            zones=zones,
        )

        if not clusters:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2] Aucun cluster formé pour {doc_id}"
            )
            return self._build_empty_result(doc_id, doc_title, content)

        # =====================================================================
        # Pass 1.C: Structuration a posteriori
        # =====================================================================
        logger.info(f"[OSMOSE:Pass1:V2.2] --- Pass 1.C: Structuration ---")
        subject, themes, concepts = self.structure_builder.build(
            clusters=clusters,
            assertions=assertions,
            doc_id=doc_id,
            doc_title=doc_title,
            doc_language=doc_language,
            global_view_summary=global_view.meta_document[:3000],
        )

        # =====================================================================
        # Pass 1.D: Validation gate
        # =====================================================================
        logger.info(f"[OSMOSE:Pass1:V2.2] --- Pass 1.D: Validation ---")
        n_sections = len(global_view.section_summaries)
        active_clusters, draft_clusters, newly_unlinked, active_coverage = \
            self.validation_gate.validate(
                clusters=clusters,
                assertions=assertions,
                embeddings=embeddings,
                budget_config={"n_sections": n_sections},
                llm_client=self.llm_client,
            )

        all_unlinked = set(unlinked_indices) | set(newly_unlinked)

        # Construire le mapping cluster → concept_id
        active_cluster_ids = {c.cluster_id for c in active_clusters}
        concept_id_by_cluster = {}
        active_concept_ids = set()
        for i, cl in enumerate(clusters):
            cid = f"concept_{doc_id}_{i}"
            concept_id_by_cluster[cl.cluster_id] = cid
            if cl.cluster_id in active_cluster_ids:
                active_concept_ids.add(cid)

        # Filtrer concepts et thèmes pour ne garder que les ACTIVE
        active_concepts = [
            c for c in concepts if c.concept_id in active_concept_ids
        ]
        active_theme_ids = {c.theme_id for c in active_concepts}
        active_themes = [t for t in themes if t.theme_id in active_theme_ids]

        # =====================================================================
        # Anchor resolution (réutilise V2.1)
        # =====================================================================
        logger.info(f"[OSMOSE:Pass1:V2.2] --- Anchor Resolution ---")
        informations, assertion_log = self._resolve_and_build(
            assertions=assertions,
            clusters=active_clusters,
            concept_id_by_cluster=concept_id_by_cluster,
            chunk_to_docitem_map=chunk_to_docitem_map,
            docitems=docitems,
            unlinked_indices=all_unlinked,
            doc_id=doc_id,
        )

        # =====================================================================
        # Construire Pass1Result
        # =====================================================================
        content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        doc_meta = DocumentMeta(
            doc_id=doc_id,
            title=doc_title,
            language=doc_language,
            content_hash=content_hash,
        )

        stats = Pass1Stats(
            themes_count=len(active_themes),
            concepts_count=len(active_concepts),
            assertions_total=len(assertions),
            assertions_promoted=len(informations),
            assertions_abstained=sum(
                1 for a in assertion_log
                if a.status == AssertionStatus.ABSTAINED
            ),
            assertions_rejected=sum(
                1 for a in assertion_log
                if a.status == AssertionStatus.REJECTED
            ),
        )

        result = Pass1Result(
            tenant_id=self.tenant_id,
            doc=doc_meta,
            subject=subject,
            themes=active_themes,
            concepts=active_concepts,
            informations=informations,
            assertion_log=assertion_log,
            stats=stats,
        )

        logger.info(
            f"[OSMOSE:Pass1:V2.2] === Résultat {doc_id} ===\n"
            f"  Subject: {subject.name}\n"
            f"  Thèmes: {len(active_themes)}\n"
            f"  Concepts ACTIVE: {len(active_concepts)} "
            f"(DRAFT: {len(draft_clusters)})\n"
            f"  Informations: {len(informations)}\n"
            f"  UNLINKED: {len(all_unlinked)}/{len(assertions)} "
            f"({len(all_unlinked)/len(assertions)*100:.0f}%)\n"
            f"  Active coverage: {active_coverage:.0%}"
        )

        return result

    # ========================================================================
    # SOUS-ROUTINES
    # ========================================================================

    def _resolve_and_build(
        self,
        assertions: List[ZonedAssertion],
        clusters: List[AssertionCluster],
        concept_id_by_cluster: Dict[str, str],
        chunk_to_docitem_map: Dict,
        docitems: Dict[str, DocItem],
        unlinked_indices: set,
        doc_id: str,
    ) -> Tuple[List[Information], List[AssertionLogEntry]]:
        """
        Résout les ancres et construit les Information + AssertionLog.

        Réutilise la logique de chunk_id → docitem_id de V2.1.
        """
        informations = []
        assertion_log = []

        # Construire assertion_id → concept_id depuis les clusters
        assertion_to_concept: Dict[int, str] = {}
        for cluster in clusters:
            concept_id = concept_id_by_cluster.get(cluster.cluster_id, "")
            for idx in cluster.assertion_indices:
                assertion_to_concept[idx] = concept_id

        for idx, assertion in enumerate(assertions):
            if idx in unlinked_indices:
                # UNLINKED / ABSTAINED
                assertion_log.append(AssertionLogEntry(
                    assertion_id=assertion.assertion_id,
                    text=assertion.text,
                    type=self._parse_assertion_type(assertion.type),
                    confidence=assertion.confidence,
                    status=AssertionStatus.ABSTAINED,
                    reason=AssertionLogReason.NO_CONCEPT_MATCH,
                ))
                continue

            concept_id = assertion_to_concept.get(idx)
            if not concept_id:
                assertion_log.append(AssertionLogEntry(
                    assertion_id=assertion.assertion_id,
                    text=assertion.text,
                    type=self._parse_assertion_type(assertion.type),
                    confidence=assertion.confidence,
                    status=AssertionStatus.ABSTAINED,
                    reason=AssertionLogReason.NO_CONCEPT_MATCH,
                ))
                continue

            # Résoudre l'ancre: chunk_id → docitem_id
            chunk_id = assertion.chunk_id
            docitem_ids = chunk_to_docitem_map.get(chunk_id, [])

            if not docitem_ids:
                # Pas de mapping: essayer avec le format tenant:doc:chunk
                for full_id, docitem in docitems.items():
                    if chunk_id in full_id:
                        docitem_ids = [full_id]
                        break

            if not docitem_ids:
                assertion_log.append(AssertionLogEntry(
                    assertion_id=assertion.assertion_id,
                    text=assertion.text,
                    type=self._parse_assertion_type(assertion.type),
                    confidence=assertion.confidence,
                    status=AssertionStatus.REJECTED,
                    reason=AssertionLogReason.NO_DOCITEM_ANCHOR,
                    concept_id=concept_id,
                ))
                continue

            # Utiliser le premier docitem_id
            docitem_id = docitem_ids[0] if isinstance(docitem_ids, list) else docitem_ids

            anchor = Anchor(
                docitem_id=docitem_id,
                span_start=0,
                span_end=len(assertion.text),
            )

            info_id = f"info_{doc_id}_{uuid.uuid4().hex[:8]}"
            informations.append(Information(
                info_id=info_id,
                concept_id=concept_id,
                text=assertion.text,
                type=self._parse_assertion_type(assertion.type),
                confidence=assertion.confidence,
                anchor=anchor,
            ))

            assertion_log.append(AssertionLogEntry(
                assertion_id=assertion.assertion_id,
                text=assertion.text,
                type=self._parse_assertion_type(assertion.type),
                confidence=assertion.confidence,
                status=AssertionStatus.PROMOTED,
                reason=AssertionLogReason.PROMOTED,
                concept_id=concept_id,
                anchor=anchor,
            ))

        return informations, assertion_log

    def _build_chunk_to_section_map(
        self,
        sections: List[Dict],
        chunks: Dict[str, str],
        global_view: GlobalView,
    ) -> Dict[str, str]:
        """Construit un mapping chunk_id → section_id."""
        chunk_to_section = {}

        for section in sections:
            section_id = section.get("id") or section.get("section_id", "")
            chunk_ids = section.get("chunk_ids", [])
            for cid in chunk_ids:
                chunk_to_section[cid] = section_id

        return chunk_to_section

    def _detect_language(self, text: str) -> str:
        """Détecte la langue par heuristique simple."""
        sample = text[:5000].lower()
        fr_words = ["le", "la", "les", "de", "du", "des", "est", "sont", "pour", "avec", "dans"]
        en_words = ["the", "is", "are", "for", "with", "in", "to", "of", "and", "that"]

        words = sample.split()
        fr_count = sum(1 for w in words if w in fr_words)
        en_count = sum(1 for w in words if w in en_words)

        return "fr" if fr_count > en_count else "en"

    def _parse_assertion_type(self, type_str: str) -> AssertionType:
        """Parse un type d'assertion en enum."""
        try:
            return AssertionType(type_str.upper())
        except (ValueError, AttributeError):
            return AssertionType.FACTUAL

    def _build_empty_result(
        self, doc_id: str, doc_title: str, content: str
    ) -> Pass1Result:
        """Construit un Pass1Result vide (fallback)."""
        from knowbase.stratified.models import DocumentStructure

        content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        return Pass1Result(
            tenant_id=self.tenant_id,
            doc=DocumentMeta(
                doc_id=doc_id,
                title=doc_title,
                language="fr",
                content_hash=content_hash,
                tenant_id=self.tenant_id,
            ),
            subject=Subject(
                subject_id=f"subject_{doc_id}",
                name=doc_title or "Document",
                text=doc_title or "Document",
                structure=DocumentStructure.CENTRAL,
                language="fr",
            ),
            themes=[],
            concepts=[],
            informations=[],
            assertion_log=[],
            stats=Pass1Stats(),
        )
