# ADR SCOPE Discursive Candidate Mining - Implémentation V1
# Ref: doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
#
# Ce module implémente le SCOPE Candidate Mining conformément à l'ADR:
# - INV-SCOPE-01: Pas de relation Concept→Concept directe
# - INV-SCOPE-02: Marquage DISCURSIVE + basis=["SCOPE"]
# - INV-SCOPE-03: Multi-span ≥2 DocItems obligatoire
# - INV-SCOPE-04: ABSTAIN motivé (Miner ou Verifier)
# - INV-SCOPE-05: Budgets = garde-fous épistémiques
# - INV-SCOPE-06: Routing = query-time only

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from ulid import ULID

from neo4j import Driver

from knowbase.relations.types import (
    CandidatePair,
    CandidatePairStatus,
    DiscursiveAbstainReason,
    DiscursiveBasis,
    EvidenceBundle,
    EvidenceSpan,
    EvidenceSpanRole,
    ScopeMiningConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data classes pour les résultats Cypher
# =============================================================================

@dataclass
class DocItemInfo:
    """Information sur un DocItem."""
    doc_item_id: str
    text: str
    item_type: Optional[str]
    section_id: str
    document_id: str
    page_no: Optional[int]


@dataclass
class ConceptInScope:
    """Concept présent dans un scope avec ses métriques de saillance."""
    concept_id: str
    canonical_name: str
    mention_count: int
    first_position: int  # Position du premier DocItem mentionnant ce concept
    doc_item_ids: List[str]  # IDs des DocItems où ce concept est ancré


@dataclass
class SectionScope:
    """Scope d'une section avec ses DocItems et concepts."""
    section_id: str
    document_id: str
    doc_items: List[DocItemInfo]
    concepts: List[ConceptInScope]


@dataclass
class MiningResult:
    """Résultat du mining pour une section."""
    section_id: str
    candidates: List[CandidatePair]
    abstained: List[Tuple[str, str, DiscursiveAbstainReason, str]]  # (pivot_id, other_id, reason, justification)
    stats: Dict[str, int]


# =============================================================================
# Scope Setter Selection (algorithme déterministe)
# Ref: ADR section "Scope Setter Selection"
# =============================================================================

def select_scope_setter(
    doc_items: List[DocItemInfo],
    min_text_length: int = 20
) -> Optional[DocItemInfo]:
    """
    Sélectionne le scope_setter d'une liste de DocItems.

    Algorithme déterministe (pas de LLM):
    1. HEADING de section (item_type = "heading")
    2. Premier DocItem textuel avec len(text) > min_text_length
    3. Fallback: Premier DocItem (même court)
    4. Échec: None si liste vide

    Args:
        doc_items: Liste des DocItems de la section
        min_text_length: Longueur min pour un DocItem textuel substantiel

    Returns:
        DocItemInfo du scope_setter ou None si section vide
    """
    if not doc_items:
        return None

    # 1. Heading
    headings = [d for d in doc_items if d.item_type == "heading"]
    if headings:
        return headings[0]

    # 2. Premier DocItem textuel substantiel
    textual = [d for d in doc_items if len(d.text or "") > min_text_length]
    if textual:
        return textual[0]

    # 3. Fallback
    return doc_items[0]


# =============================================================================
# Salience Scoring
# =============================================================================

def compute_salience_score(concept: ConceptInScope, total_doc_items: int) -> float:
    """
    Calcule le score de saillance d'un concept dans une section.

    Score = mention_count * position_weight

    position_weight = 1 - (first_position / total_doc_items)
    (Plus le concept apparaît tôt, plus il est saillant)
    """
    if total_doc_items == 0:
        return float(concept.mention_count)

    position_weight = 1.0 - (concept.first_position / total_doc_items)
    return concept.mention_count * (1.0 + position_weight)


# =============================================================================
# ScopeCandidateMiner
# =============================================================================

class ScopeCandidateMiner:
    """
    Générateur de CandidatePairs basé sur la co-présence dans un scope documentaire.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md

    Ce miner:
    - Ne crée JAMAIS de relation directe (INV-SCOPE-01)
    - Produit des CandidatePairs avec EvidenceBundles multi-span (INV-SCOPE-03)
    - Émet des ABSTAIN motivés au niveau Miner (INV-SCOPE-04)
    - Respecte les budgets épistémiques (INV-SCOPE-05)
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        config: Optional[ScopeMiningConfig] = None,
        tenant_id: str = "default"
    ):
        self.driver = neo4j_driver
        self.config = config or ScopeMiningConfig()
        self.tenant_id = tenant_id

    def mine_section(self, section_id: str) -> MiningResult:
        """
        Mine les CandidatePairs pour une section donnée.

        Pipeline:
        1. Récupère les DocItems de la section
        2. Récupère les concepts ancrés dans ces DocItems
        3. Sélectionne le scope_setter
        4. Sélectionne les pivots (top_k par saillance)
        5. Génère les paires (pivot, other)
        6. Construit les EvidenceBundles
        7. Filtre les bundles invalides (ABSTAIN)

        Args:
            section_id: ID de la section à miner

        Returns:
            MiningResult avec candidates et stats
        """
        stats = {
            "doc_items": 0,
            "concepts": 0,
            "pivots_selected": 0,
            "pairs_generated": 0,
            "pairs_valid": 0,
            "abstained_weak_bundle": 0,
            "abstained_no_scope_setter": 0,
        }

        # 1. Récupère la section avec ses DocItems et concepts
        section_scope = self._fetch_section_scope(section_id)

        if not section_scope:
            logger.warning(f"Section not found: {section_id}")
            return MiningResult(
                section_id=section_id,
                candidates=[],
                abstained=[],
                stats=stats
            )

        stats["doc_items"] = len(section_scope.doc_items)
        stats["concepts"] = len(section_scope.concepts)

        # 2. Sélectionne le scope_setter
        scope_setter = select_scope_setter(
            section_scope.doc_items,
            self.config.min_text_length_for_scope_setter
        )

        if not scope_setter:
            logger.warning(f"No scope_setter found for section: {section_id}")
            stats["abstained_no_scope_setter"] = 1
            return MiningResult(
                section_id=section_id,
                candidates=[],
                abstained=[("", "", DiscursiveAbstainReason.NO_SCOPE_SETTER, "Section vide")],
                stats=stats
            )

        # 3. Applique budget max_concepts_per_scope
        concepts = section_scope.concepts[:self.config.max_concepts_per_scope]

        if len(concepts) < 2:
            logger.debug(f"Not enough concepts in section {section_id}: {len(concepts)}")
            return MiningResult(
                section_id=section_id,
                candidates=[],
                abstained=[],
                stats=stats
            )

        # 4. Calcule saillance et sélectionne pivots
        total_items = len(section_scope.doc_items)
        for c in concepts:
            c.salience_score = compute_salience_score(c, total_items)

        # Tri par saillance décroissante
        concepts_sorted = sorted(concepts, key=lambda c: c.salience_score, reverse=True)
        pivots = concepts_sorted[:self.config.top_k_pivots]
        stats["pivots_selected"] = len(pivots)

        # 5. Génère les paires (pivot, other)
        candidates = []
        abstained = []
        pairs_count = 0

        for pivot in pivots:
            for other in concepts_sorted:
                if other.concept_id == pivot.concept_id:
                    continue

                if pairs_count >= self.config.max_pairs_per_scope:
                    break

                pairs_count += 1
                stats["pairs_generated"] = pairs_count

                # 6. Construit l'EvidenceBundle
                bundle = self._build_evidence_bundle(
                    scope_setter=scope_setter,
                    pivot=pivot,
                    other=other,
                    section_scope=section_scope
                )

                # 7. Vérifie validité du bundle (INV-SCOPE-03)
                if not bundle.is_valid():
                    stats["abstained_weak_bundle"] += 1
                    abstained.append((
                        pivot.concept_id,
                        other.concept_id,
                        DiscursiveAbstainReason.WEAK_BUNDLE,
                        f"Bundle invalide: {len(set(s.doc_item_id for s in bundle.spans))} spans distincts < 2"
                    ))
                    continue

                # Crée le CandidatePair
                candidate = CandidatePair(
                    candidate_id=str(ULID()),
                    pivot_concept_id=pivot.concept_id,
                    other_concept_id=other.concept_id,
                    pivot_surface_form=pivot.canonical_name,
                    other_surface_form=other.canonical_name,
                    evidence_bundle=bundle,
                    section_id=section_id,
                    document_id=section_scope.document_id,
                    pivot_salience_score=pivot.salience_score,
                    other_salience_score=other.salience_score,
                    status=CandidatePairStatus.PENDING,
                )
                candidates.append(candidate)
                stats["pairs_valid"] += 1

            if pairs_count >= self.config.max_pairs_per_scope:
                break

        logger.info(
            f"SCOPE mining section {section_id}: "
            f"{stats['pairs_valid']} candidates, "
            f"{stats['abstained_weak_bundle']} abstained (WEAK_BUNDLE)"
        )

        return MiningResult(
            section_id=section_id,
            candidates=candidates,
            abstained=abstained,
            stats=stats
        )

    def mine_document(self, document_id: str) -> List[MiningResult]:
        """
        Mine toutes les sections d'un document.

        Args:
            document_id: ID du document

        Returns:
            Liste de MiningResult (un par section)
        """
        section_ids = self._fetch_document_sections(document_id)
        results = []

        for section_id in section_ids:
            result = self.mine_section(section_id)
            results.append(result)

        total_candidates = sum(len(r.candidates) for r in results)
        total_abstained = sum(len(r.abstained) for r in results)

        logger.info(
            f"SCOPE mining document {document_id}: "
            f"{len(section_ids)} sections, "
            f"{total_candidates} candidates, "
            f"{total_abstained} abstained"
        )

        return results

    def _fetch_section_scope(self, section_id: str) -> Optional[SectionScope]:
        """
        Récupère le scope complet d'une section: DocItems + Concepts ancrés.

        Cypher:
        - SectionContext → DocItem (CONTAINS)
        - DocItem ← ProtoConcept (ANCHORED_IN)
        - ProtoConcept → CanonicalConcept (INSTANCE_OF)
        """
        query = """
        MATCH (sc:SectionContext {context_id: $section_id, tenant_id: $tenant_id})
        MATCH (sc)-[:CONTAINS]->(di:DocItem)
        OPTIONAL MATCH (pc:ProtoConcept)-[:ANCHORED_IN]->(di)
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
        WITH sc, di, pc, cc
        ORDER BY di.reading_order_index
        WITH sc,
             collect(DISTINCT {
                 doc_item_id: di.item_id,
                 text: di.text,
                 item_type: di.item_type,
                 page_no: di.page_no,
                 position: di.reading_order_index
             }) AS doc_items,
             collect(DISTINCT {
                 concept_id: COALESCE(cc.concept_id, pc.concept_id),
                 canonical_name: COALESCE(cc.label, cc.canonical_name, pc.concept_name),
                 doc_item_id: di.item_id
             }) AS concept_mentions
        RETURN sc.context_id AS section_id,
               sc.doc_id AS document_id,
               doc_items,
               concept_mentions
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                section_id=section_id,
                tenant_id=self.tenant_id
            )
            record = result.single()

            if not record:
                return None

            # Parse DocItems
            doc_items = []
            for di in record["doc_items"]:
                if di.get("doc_item_id"):
                    doc_items.append(DocItemInfo(
                        doc_item_id=di["doc_item_id"],
                        text=di.get("text", ""),
                        item_type=di.get("item_type"),
                        section_id=section_id,
                        document_id=record["document_id"],
                        page_no=di.get("page_no"),
                    ))

            # Agrège les concepts avec leurs métriques
            concept_map: Dict[str, ConceptInScope] = {}
            for idx, cm in enumerate(record["concept_mentions"]):
                cid = cm.get("concept_id")
                if not cid:
                    continue

                if cid not in concept_map:
                    concept_map[cid] = ConceptInScope(
                        concept_id=cid,
                        canonical_name=cm.get("canonical_name", ""),
                        mention_count=0,
                        first_position=idx,
                        doc_item_ids=[],
                    )

                concept_map[cid].mention_count += 1
                if cm.get("doc_item_id"):
                    concept_map[cid].doc_item_ids.append(cm["doc_item_id"])

            return SectionScope(
                section_id=section_id,
                document_id=record["document_id"],
                doc_items=doc_items,
                concepts=list(concept_map.values()),
            )

    def _fetch_document_sections(self, document_id: str) -> List[str]:
        """Récupère les IDs des sections d'un document."""
        query = """
        MATCH (d:Document {document_id: $document_id, tenant_id: $tenant_id})
        MATCH (d)-[:HAS_SECTION]->(sc:SectionContext)
        RETURN sc.context_id AS section_id
        ORDER BY sc.context_id
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                document_id=document_id,
                tenant_id=self.tenant_id
            )
            return [r["section_id"] for r in result]

    def _build_evidence_bundle(
        self,
        scope_setter: DocItemInfo,
        pivot: ConceptInScope,
        other: ConceptInScope,
        section_scope: SectionScope
    ) -> EvidenceBundle:
        """
        Construit un EvidenceBundle pour une paire (pivot, other).

        Structure:
        - span1: scope_setter (role=SCOPE_SETTER)
        - span2+: mentions des concepts (role=MENTION)

        Le bundle doit avoir ≥2 DocItems distincts pour être valide (INV-SCOPE-03).
        """
        spans = []

        # Span 1: scope_setter
        spans.append(EvidenceSpan(
            doc_item_id=scope_setter.doc_item_id,
            role=EvidenceSpanRole.SCOPE_SETTER,
            text_excerpt=scope_setter.text[:200] if scope_setter.text else "",
            concept_id=None,
            concept_surface_form=None,
        ))

        # Spans pour le pivot
        for di_id in pivot.doc_item_ids[:2]:  # Max 2 spans par concept
            di = next((d for d in section_scope.doc_items if d.doc_item_id == di_id), None)
            if di:
                spans.append(EvidenceSpan(
                    doc_item_id=di_id,
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt=di.text[:200] if di.text else "",
                    concept_id=pivot.concept_id,
                    concept_surface_form=pivot.canonical_name,
                ))

        # Spans pour other
        for di_id in other.doc_item_ids[:2]:  # Max 2 spans par concept
            di = next((d for d in section_scope.doc_items if d.doc_item_id == di_id), None)
            if di:
                spans.append(EvidenceSpan(
                    doc_item_id=di_id,
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt=di.text[:200] if di.text else "",
                    concept_id=other.concept_id,
                    concept_surface_form=other.canonical_name,
                ))

        return EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=spans,
            section_id=section_scope.section_id,
            document_id=section_scope.document_id,
        )


# =============================================================================
# Fonctions utilitaires
# =============================================================================

def get_mining_stats(results: List[MiningResult]) -> Dict[str, int]:
    """Agrège les stats de plusieurs MiningResult."""
    total = {
        "sections": len(results),
        "doc_items": 0,
        "concepts": 0,
        "pivots_selected": 0,
        "pairs_generated": 0,
        "pairs_valid": 0,
        "abstained_weak_bundle": 0,
        "abstained_no_scope_setter": 0,
    }

    for r in results:
        for k, v in r.stats.items():
            if k in total:
                total[k] += v

    return total
