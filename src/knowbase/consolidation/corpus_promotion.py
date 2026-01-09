"""
Corpus Promotion Engine - Pass 2.0 Unified Promotion.

ADR: doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md

Responsabilités:
1. Charger les ProtoConcepts non-promus
2. Grouper par label canonique (via NormalizationEngine)
3. Appliquer règles de promotion unifiées (doc-level + corpus-level)
4. Créer CanonicalConcepts avec relations INSTANCE_OF

Règles de promotion:
- ≥2 occurrences même document → STABLE
- ≥2 sections différentes → STABLE
- ≥2 documents + signal minimal → STABLE
- singleton + high-signal V2 → SINGLETON

Author: OSMOSE
Date: 2026-01-09
"""

import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.api.schemas.concepts import ConceptStability
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class CorpusPromotionConfig:
    """Configuration pour la promotion corpus-level."""

    # Seuils de promotion doc-level
    min_proto_for_stable: int = 2
    min_sections_for_stable: int = 2

    # Seuils cross-doc
    min_documents_for_stable: int = 2

    # High-signal V2 (signaux structurels)
    max_label_length: int = 120
    max_template_likelihood: float = 0.5
    max_positional_stability: float = 0.8

    # Signaux minimaux pour cross-doc
    require_span_for_crossdoc: bool = True
    min_confidence_for_crossdoc: float = 0.7


@dataclass
class PromotionDecision:
    """Décision de promotion pour un groupe de ProtoConcepts."""

    canonical_label: str
    promote: bool
    stability: Optional[str] = None
    reason: str = ""

    # Métriques
    proto_count: int = 0
    section_count: int = 0
    document_count: int = 0

    # Signaux
    is_high_signal: bool = False
    has_minimal_signal: bool = False
    high_signal_reasons: List[str] = field(default_factory=list)

    # IDs
    proto_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)


@dataclass
class CorpusPromotionStats:
    """Statistiques de promotion Pass 2.0."""

    document_id: str
    tenant_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Compteurs
    protos_loaded: int = 0
    groups_analyzed: int = 0
    promoted_stable: int = 0
    promoted_singleton: int = 0
    not_promoted: int = 0

    # Cross-doc
    crossdoc_promotions: int = 0
    corpus_protos_linked: int = 0

    @property
    def total_promoted(self) -> int:
        return self.promoted_stable + self.promoted_singleton


# =============================================================================
# High-Signal V2 Check (avec signaux structurels)
# =============================================================================

def check_high_signal_v2(
    proto: Dict[str, Any],
    config: CorpusPromotionConfig,
) -> Tuple[bool, List[str]]:
    """
    Vérifie si un ProtoConcept est high-signal V2.

    Nouvelle définition (ADR_UNIFIED_CORPUS_PROMOTION):
    High-Signal = Normatif + Non-Template + Signal-Contenu

    Args:
        proto: Dict avec données du ProtoConcept
        config: Configuration de promotion

    Returns:
        (is_high_signal, reasons)
    """
    reasons = []
    label = proto.get("label", "")

    # === 1. NORMATIF (au moins un) ===
    is_normative = False

    # Check rôle anchor
    anchor_role = proto.get("anchor_role", "").lower()
    normative_roles = {"definition", "constraint", "requirement", "prohibition", "obligation"}
    if anchor_role in normative_roles:
        is_normative = True
        reasons.append(f"normative_role:{anchor_role}")

    # Check modaux dans quote
    quote = proto.get("quote", "").lower()
    normative_modals = ["shall", "must", "required", "shall not", "must not", "prohibited"]
    for modal in normative_modals:
        if modal in quote:
            is_normative = True
            reasons.append(f"normative_modal:{modal}")
            break

    if not is_normative:
        return False, []

    # === 2. NON-TEMPLATE (tous) ===
    template_likelihood = proto.get("template_likelihood", 0.0)
    positional_stability = proto.get("positional_stability", 0.0)
    dominant_zone = proto.get("dominant_zone", "main").lower()
    is_repeated_bottom = proto.get("is_repeated_bottom", False)

    # Check template
    if template_likelihood >= config.max_template_likelihood:
        logger.debug(f"[OSMOSE:HighSignalV2] Rejected '{label}': template_likelihood={template_likelihood}")
        return False, []

    # Check positional stability (footer/header)
    if positional_stability >= config.max_positional_stability:
        logger.debug(f"[OSMOSE:HighSignalV2] Rejected '{label}': positional_stability={positional_stability}")
        return False, []

    # Check BOTTOM_ZONE répété
    if dominant_zone == "bottom" and is_repeated_bottom:
        logger.debug(f"[OSMOSE:HighSignalV2] Rejected '{label}': repeated BOTTOM_ZONE")
        return False, []

    reasons.append("non_template")

    # === 3. SIGNAL-CONTENU (au moins un) ===
    has_content_signal = False

    # Check zone principale
    if dominant_zone == "main":
        has_content_signal = True
        reasons.append("main_zone")

    # Check section_path
    section_path = proto.get("section_path", "")
    if section_path and section_path.strip():
        has_content_signal = True
        reasons.append("has_section")

    if not has_content_signal:
        logger.debug(f"[OSMOSE:HighSignalV2] Rejected '{label}': no content signal")
        return False, []

    # Check longueur label
    if len(label) > config.max_label_length:
        logger.debug(f"[OSMOSE:HighSignalV2] Rejected '{label[:50]}...': label too long ({len(label)} chars)")
        return False, []

    reasons.append(f"label_length_ok:{len(label)}")

    logger.info(f"[OSMOSE:HighSignalV2] '{label}' is HIGH-SIGNAL: {reasons}")
    return True, reasons


# =============================================================================
# Corpus Promotion Engine
# =============================================================================

class CorpusPromotionEngine:
    """
    Moteur de promotion unifiée Pass 2.0.

    Exécuté au début de Pass 2, AVANT toute autre phase d'enrichissement.
    """

    def __init__(
        self,
        tenant_id: str = "default",
        config: Optional[CorpusPromotionConfig] = None,
    ):
        self.tenant_id = tenant_id
        self.config = config or self._load_config()
        self.neo4j_client = get_neo4j_client()

        logger.info(
            f"[OSMOSE:CorpusPromotion] Initialized for tenant={tenant_id} "
            f"(min_docs={self.config.min_documents_for_stable})"
        )

    def _load_config(self) -> CorpusPromotionConfig:
        """Charge la configuration depuis feature flags."""
        promotion_config = get_hybrid_anchor_config("promotion_config", self.tenant_id) or {}

        return CorpusPromotionConfig(
            min_proto_for_stable=promotion_config.get("min_proto_concepts_for_stable", 2),
            min_sections_for_stable=promotion_config.get("min_anchor_sections_for_stable", 2),
            min_documents_for_stable=promotion_config.get("min_documents_for_stable", 2),
            max_label_length=promotion_config.get("max_label_length_for_singleton", 120),
            max_template_likelihood=promotion_config.get("max_template_likelihood", 0.5),
            max_positional_stability=promotion_config.get("max_positional_stability", 0.8),
        )

    # =========================================================================
    # Chargement Neo4j
    # =========================================================================

    def load_unlinked_proto_concepts(
        self,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Charge les ProtoConcepts non-promus du document courant.

        Returns:
            Liste de dicts avec propriétés du ProtoConcept
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
        WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        OPTIONAL MATCH (p)-[a:ANCHORED_IN]->(dc:DocumentChunk)
        WITH p, collect(DISTINCT dc.section_path) AS sections,
             collect(DISTINCT a.role) AS anchor_roles
        RETURN p.concept_id AS proto_id,
               p.label AS label,
               p.anchor_status AS anchor_status,
               p.confidence AS confidence,
               p.quote AS quote,
               p.section_path AS section_path,
               p.template_likelihood AS template_likelihood,
               p.positional_stability AS positional_stability,
               p.dominant_zone AS dominant_zone,
               sections,
               anchor_roles,
               p.document_id AS document_id
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=self.tenant_id,
                document_id=document_id,
            )
            protos = [dict(record) for record in result]

        logger.info(
            f"[OSMOSE:CorpusPromotion] Loaded {len(protos)} unlinked ProtoConcepts "
            f"from document {document_id}"
        )

        return protos

    def count_corpus_occurrences(
        self,
        canonical_label: str,
        exclude_document_id: str,
    ) -> Tuple[int, List[str]]:
        """
        Compte les occurrences cross-corpus pour un label canonique.

        Args:
            canonical_label: Label normalisé
            exclude_document_id: Document à exclure (document courant)

        Returns:
            (nombre de documents, liste des document_ids)
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE toLower(trim(p.label)) = $canonical_label
          AND p.document_id <> $exclude_document_id
          AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        RETURN collect(DISTINCT p.document_id) AS document_ids
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=self.tenant_id,
                canonical_label=canonical_label.lower().strip(),
                exclude_document_id=exclude_document_id,
            )
            record = result.single()

        if record:
            doc_ids = record["document_ids"] or []
            return len(doc_ids), doc_ids

        return 0, []

    # =========================================================================
    # Groupement par label canonique
    # =========================================================================

    def group_by_canonical_label(
        self,
        protos: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Groupe les ProtoConcepts par label canonique.

        Utilise une normalisation simple: lowercase + strip + collapse whitespace.
        TODO: Intégrer NormalizationEngine quand disponible pour concepts.
        """
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for proto in protos:
            label = proto.get("label", "")
            canonical_form = self._normalize_label(label)
            groups[canonical_form].append(proto)

        logger.debug(
            f"[OSMOSE:CorpusPromotion] Grouped {len(protos)} protos into {len(groups)} canonical groups"
        )

        return groups

    def _normalize_label(self, label: str) -> str:
        """
        Normalise un label de concept pour le groupement.

        Applique:
        1. lowercase
        2. strip
        3. collapse multiple whitespace
        4. normalize common abbreviations

        Args:
            label: Label brut

        Returns:
            Label normalisé pour comparaison
        """
        import re

        if not label:
            return ""

        # Lowercase + strip
        normalized = label.lower().strip()

        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        # Normalize common patterns (optional, domain-agnostic)
        # Ex: "s/4 hana" → "s/4hana", "sap s/4hana" → "sap s/4hana"
        normalized = normalized.replace('s/4 hana', 's/4hana')

        return normalized

    # =========================================================================
    # Logique de promotion
    # =========================================================================

    def _check_minimal_signal(
        self,
        protos: List[Dict[str, Any]],
    ) -> bool:
        """
        Vérifie si au moins un proto a le signal minimal requis pour cross-doc.

        Signal minimal (ADR amendement ChatGPT):
        - anchor_status = SPAN
        - OU role ∈ {definition, constraint}
        - OU confidence >= 0.7
        """
        for proto in protos:
            # Check SPAN
            if proto.get("anchor_status") == "SPAN":
                return True

            # Check rôles structurants
            anchor_roles = proto.get("anchor_roles", [])
            if any(r in ["definition", "constraint"] for r in anchor_roles):
                return True

            # Check confidence
            confidence = proto.get("confidence") or 0.0
            if confidence >= self.config.min_confidence_for_crossdoc:
                return True

        return False

    def determine_promotion(
        self,
        canonical_label: str,
        protos: List[Dict[str, Any]],
        document_id: str,
    ) -> PromotionDecision:
        """
        Détermine si un groupe de ProtoConcepts doit être promu.

        Règles unifiées (ADR_UNIFIED_CORPUS_PROMOTION):
        1. ≥2 occurrences même document → STABLE
        2. ≥2 sections différentes → STABLE
        3. ≥2 documents + signal minimal → STABLE
        4. singleton + high-signal V2 → SINGLETON
        """
        decision = PromotionDecision(
            canonical_label=canonical_label,
            promote=False,
            proto_ids=[p.get("proto_id") for p in protos],
            document_ids=[document_id],
        )

        # Compteurs doc-level
        doc_count = len(protos)
        decision.proto_count = doc_count

        # Sections uniques
        all_sections: Set[str] = set()
        for proto in protos:
            sections = proto.get("sections", [])
            all_sections.update(s for s in sections if s)
        decision.section_count = len(all_sections)

        # High-signal V2 check
        for proto in protos:
            is_hs, reasons = check_high_signal_v2(proto, self.config)
            if is_hs:
                decision.is_high_signal = True
                decision.high_signal_reasons.extend(reasons)
                break

        # Signal minimal pour cross-doc
        decision.has_minimal_signal = self._check_minimal_signal(protos)

        # Compteur corpus (autres documents)
        corpus_count, corpus_doc_ids = self.count_corpus_occurrences(
            canonical_label=canonical_label,
            exclude_document_id=document_id,
        )
        decision.document_count = 1 + corpus_count  # doc courant + corpus
        decision.document_ids.extend(corpus_doc_ids)

        # === Règles de promotion ===

        # Règle 1: ≥2 occurrences même document
        if doc_count >= self.config.min_proto_for_stable:
            decision.promote = True
            decision.stability = ConceptStability.STABLE.value
            decision.reason = f"≥{self.config.min_proto_for_stable} occurrences même document ({doc_count})"
            return decision

        # Règle 2: ≥2 sections différentes
        if decision.section_count >= self.config.min_sections_for_stable:
            decision.promote = True
            decision.stability = ConceptStability.STABLE.value
            decision.reason = f"≥{self.config.min_sections_for_stable} sections différentes ({decision.section_count})"
            return decision

        # Règle 3: ≥2 documents + signal minimal
        if corpus_count >= 1 and decision.has_minimal_signal:
            decision.promote = True
            decision.stability = ConceptStability.STABLE.value
            decision.reason = f"≥2 documents + signal minimal (1 + {corpus_count} corpus)"
            return decision

        # Règle 4: singleton + high-signal V2
        if doc_count == 1 and decision.is_high_signal:
            decision.promote = True
            decision.stability = ConceptStability.SINGLETON.value
            decision.reason = f"singleton high-signal V2: {decision.high_signal_reasons[:2]}"
            return decision

        # Pas de promotion
        decision.reason = "insufficient signals for promotion"
        return decision

    # =========================================================================
    # Création CanonicalConcepts
    # =========================================================================

    def create_canonical_concept(
        self,
        decision: PromotionDecision,
        protos: List[Dict[str, Any]],
    ) -> str:
        """
        Crée un CanonicalConcept et lie les ProtoConcepts via INSTANCE_OF.

        Returns:
            ID du CanonicalConcept créé
        """
        import uuid

        # Sélectionner le meilleur proto (plus haute confidence)
        best_proto = max(protos, key=lambda p: p.get("confidence") or 0.0)

        canonical_id = f"cc_{uuid.uuid4().hex[:12]}"

        # Créer le CanonicalConcept
        create_query = """
        CREATE (cc:CanonicalConcept {
            concept_id: $canonical_id,
            tenant_id: $tenant_id,
            label: $label,
            stability: $stability,
            created_at: datetime(),
            promotion_reason: $reason,
            proto_count: $proto_count,
            document_count: $document_count
        })
        RETURN cc.concept_id AS id
        """

        # Lier les ProtoConcepts du document courant
        link_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.concept_id IN $proto_ids
        MATCH (cc:CanonicalConcept {concept_id: $canonical_id, tenant_id: $tenant_id})
        CREATE (p)-[:INSTANCE_OF {created_at: datetime()}]->(cc)
        RETURN count(p) AS linked
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            # Créer CC
            session.run(
                create_query,
                canonical_id=canonical_id,
                tenant_id=self.tenant_id,
                label=best_proto.get("label"),
                stability=decision.stability,
                reason=decision.reason,
                proto_count=decision.proto_count,
                document_count=decision.document_count,
            )

            # Lier protos
            result = session.run(
                link_query,
                tenant_id=self.tenant_id,
                proto_ids=decision.proto_ids,
                canonical_id=canonical_id,
            )
            linked = result.single()["linked"]

        logger.info(
            f"[OSMOSE:CorpusPromotion] Created CanonicalConcept '{best_proto.get('label')}' "
            f"({decision.stability}) with {linked} linked protos"
        )

        return canonical_id

    def link_corpus_protos_to_canonical(
        self,
        canonical_label: str,
        canonical_id: str,
        exclude_document_id: str,
    ) -> int:
        """
        Lie les ProtoConcepts du corpus existant au CanonicalConcept.

        Returns:
            Nombre de protos liés
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE toLower(trim(p.label)) = $canonical_label
          AND p.document_id <> $exclude_document_id
          AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        MATCH (cc:CanonicalConcept {concept_id: $canonical_id, tenant_id: $tenant_id})
        CREATE (p)-[:INSTANCE_OF {created_at: datetime(), linked_by: 'corpus_promotion'}]->(cc)
        RETURN count(p) AS linked
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=self.tenant_id,
                canonical_label=canonical_label.lower().strip(),
                canonical_id=canonical_id,
                exclude_document_id=exclude_document_id,
            )
            linked = result.single()["linked"]

        if linked > 0:
            logger.info(
                f"[OSMOSE:CorpusPromotion] Linked {linked} corpus protos to '{canonical_label}'"
            )

        return linked

    # =========================================================================
    # Point d'entrée principal
    # =========================================================================

    def run_promotion(
        self,
        document_id: str,
    ) -> CorpusPromotionStats:
        """
        Exécute la promotion Pass 2.0 pour un document.

        Args:
            document_id: ID du document à traiter

        Returns:
            Statistiques de promotion
        """
        stats = CorpusPromotionStats(
            document_id=document_id,
            tenant_id=self.tenant_id,
            started_at=datetime.now(),
        )

        logger.info(
            f"[OSMOSE:CorpusPromotion] Starting Pass 2.0 for document {document_id}"
        )

        # 1. Charger ProtoConcepts non-promus
        protos = self.load_unlinked_proto_concepts(document_id)
        stats.protos_loaded = len(protos)

        if not protos:
            logger.info(
                f"[OSMOSE:CorpusPromotion] No unlinked protos for document {document_id}"
            )
            stats.completed_at = datetime.now()
            return stats

        # 2. Grouper par label canonique
        groups = self.group_by_canonical_label(protos)
        stats.groups_analyzed = len(groups)

        # 3. Analyser chaque groupe
        for canonical_label, group_protos in groups.items():
            decision = self.determine_promotion(
                canonical_label=canonical_label,
                protos=group_protos,
                document_id=document_id,
            )

            if decision.promote:
                # Créer CanonicalConcept
                canonical_id = self.create_canonical_concept(decision, group_protos)

                # Compteurs
                if decision.stability == ConceptStability.STABLE.value:
                    stats.promoted_stable += 1
                else:
                    stats.promoted_singleton += 1

                # Lier protos corpus si cross-doc
                if decision.document_count > 1:
                    linked = self.link_corpus_protos_to_canonical(
                        canonical_label=canonical_label,
                        canonical_id=canonical_id,
                        exclude_document_id=document_id,
                    )
                    stats.corpus_protos_linked += linked
                    stats.crossdoc_promotions += 1
            else:
                stats.not_promoted += 1

        stats.completed_at = datetime.now()

        logger.info(
            f"[OSMOSE:CorpusPromotion] Pass 2.0 completed for {document_id}: "
            f"{stats.total_promoted} promoted (stable={stats.promoted_stable}, "
            f"singleton={stats.promoted_singleton}), {stats.not_promoted} not promoted, "
            f"{stats.crossdoc_promotions} cross-doc"
        )

        return stats


# =============================================================================
# Factory
# =============================================================================

_engines: Dict[str, CorpusPromotionEngine] = {}


def get_corpus_promotion_engine(tenant_id: str = "default") -> CorpusPromotionEngine:
    """Retourne une instance singleton du CorpusPromotionEngine."""
    if tenant_id not in _engines:
        _engines[tenant_id] = CorpusPromotionEngine(tenant_id=tenant_id)
    return _engines[tenant_id]


__all__ = [
    "CorpusPromotionConfig",
    "PromotionDecision",
    "CorpusPromotionStats",
    "CorpusPromotionEngine",
    "get_corpus_promotion_engine",
    "check_high_signal_v2",
]
