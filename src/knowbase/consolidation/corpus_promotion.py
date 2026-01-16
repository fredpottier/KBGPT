"""
Corpus Promotion Engine - Pass 2.0 Unified Promotion.

ADR: doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md
ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

Responsabilités:
1. Charger les ProtoConcepts non-promus
2. Grouper par lex_key (normalisation canonique via compute_lex_key)
3. Appliquer règles de promotion unifiées (doc-level + corpus-level)
4. Créer CanonicalConcepts avec relations INSTANCE_OF
5. Type guard soft pour éviter les faux positifs homonymes

Règles de promotion:
- ≥2 occurrences même document → STABLE
- ≥2 sections différentes → STABLE
- ≥2 documents + signal minimal → STABLE
- singleton + high-signal V2 → SINGLETON

Author: OSMOSE
Date: 2026-01-09
Updated: 2026-01-11 (ADR lex_key normalization)
"""

import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, Counter
from datetime import datetime

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.api.schemas.concepts import ConceptStability
from knowbase.config.feature_flags import get_hybrid_anchor_config
from knowbase.config.settings import get_settings
from knowbase.consolidation.lex_utils import compute_lex_key

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

    # Type Guard Soft (ADR lex_key)
    lex_key: str = ""
    type_bucket: str = "__NONE__"
    type_conflict: bool = False


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

    # ADR lex_key metrics
    protos_without_lex_key: int = 0
    buckets_split_by_type: int = 0
    buckets_type_conflict: int = 0

    @property
    def total_promoted(self) -> int:
        return self.promoted_stable + self.promoted_singleton


@dataclass
class CorpusPromotionResult:
    """Résultat de promotion corpus-level (tous les documents)."""

    proto_concepts_processed: int = 0
    canonical_concepts_created: int = 0
    merged_count: int = 0  # Cross-doc merges
    singleton_count: int = 0
    skipped_count: int = 0
    documents_processed: int = 0
    execution_time_ms: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proto_count": self.proto_concepts_processed,
            "promoted_count": self.canonical_concepts_created,
            "merged_count": self.merged_count,
            "singleton_count": self.singleton_count,
            "skipped_count": self.skipped_count,
            "documents_processed": self.documents_processed,
            "execution_time_ms": self.execution_time_ms,
        }


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

    # Check rôles anchor (peut être une liste)
    anchor_roles = proto.get("anchor_roles") or []
    if isinstance(anchor_roles, str):
        anchor_roles = [anchor_roles]
    normative_roles = {"definition", "constraint", "requirement", "prohibition", "obligation"}
    for role in anchor_roles:
        if role and role.lower() in normative_roles:
            is_normative = True
            reasons.append(f"normative_role:{role}")
            break

    # Check modaux dans quote
    quote = (proto.get("quote") or "").lower()
    normative_modals = ["shall", "must", "required", "shall not", "must not", "prohibited"]
    for modal in normative_modals:
        if modal in quote:
            is_normative = True
            reasons.append(f"normative_modal:{modal}")
            break

    if not is_normative:
        return False, []

    # === 2. NON-TEMPLATE (tous) ===
    template_likelihood = proto.get("template_likelihood") or 0.0
    positional_stability = proto.get("positional_stability") or 0.0
    dominant_zone = (proto.get("dominant_zone") or "main").lower()
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

        # Créer client Neo4j avec les settings (comme Pass2Service)
        settings = get_settings()
        self.neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

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
            Liste de dicts avec propriétés du ProtoConcept (incluant lex_key si présent)
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
        WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        OPTIONAL MATCH (p)-[a:ANCHORED_IN]->(dc:DocumentChunk)
        WITH p, collect(DISTINCT dc.section_path) AS sections,
             collect(DISTINCT a.role) AS anchor_roles
        RETURN p.concept_id AS proto_id,
               p.concept_name AS label,
               p.lex_key AS lex_key,
               p.type_heuristic AS type_heuristic,
               p.anchor_status AS anchor_status,
               p.extract_confidence AS confidence,
               p.definition AS quote,
               p.section_id AS section_path,
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
        lex_key: str,
        exclude_document_id: str,
    ) -> Tuple[int, List[str]]:
        """
        Compte les occurrences cross-corpus pour un lex_key.

        Args:
            lex_key: Clé lexicale normalisée (via compute_lex_key)
            exclude_document_id: Document à exclure (document courant)

        Returns:
            (nombre de documents, liste des document_ids)
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.lex_key = $lex_key
          AND p.document_id <> $exclude_document_id
          AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        RETURN collect(DISTINCT p.document_id) AS document_ids
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=self.tenant_id,
                lex_key=lex_key,
                exclude_document_id=exclude_document_id,
            )
            record = result.single()

        if record:
            doc_ids = record["document_ids"] or []
            return len(doc_ids), doc_ids

        return 0, []

    # =========================================================================
    # Groupement par lex_key (ADR lex_key normalization)
    # =========================================================================

    def _get_lex_key(self, proto: Dict[str, Any]) -> str:
        """
        Récupère le lex_key d'un proto avec fallback transitoire.

        Args:
            proto: Dict avec données du ProtoConcept

        Returns:
            lex_key (depuis proto ou calculé)
        """
        # Prefer stored lex_key
        if proto.get("lex_key"):
            return proto["lex_key"]

        # Fallback: compute on-the-fly + log warning
        label = proto.get("label") or proto.get("concept_name") or ""
        if not label:
            return ""

        logger.debug(
            f"[OSMOSE:CorpusPromotion] Proto {proto.get('proto_id')} missing lex_key, computing on-the-fly"
        )
        return compute_lex_key(label)

    def group_by_lex_key(
        self,
        protos: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Groupe les ProtoConcepts par lex_key (normalisation canonique).

        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

        Uses compute_lex_key() for robust matching:
        - Accents handled (Données → donnee)
        - Punctuation handled (S/4HANA → s 4hana)
        - Plurals handled (documents → document)
        """
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        missing_lex_key_count = 0

        for proto in protos:
            lex_key = self._get_lex_key(proto)
            if not proto.get("lex_key"):
                missing_lex_key_count += 1
            groups[lex_key].append(proto)

        if missing_lex_key_count > 0:
            logger.warning(
                f"[OSMOSE:CorpusPromotion] {missing_lex_key_count}/{len(protos)} protos missing lex_key"
            )

        logger.debug(
            f"[OSMOSE:CorpusPromotion] Grouped {len(protos)} protos into {len(groups)} lex_key groups"
        )

        return groups, missing_lex_key_count

    def split_by_type_if_divergent(
        self,
        lex_key: str,
        protos: List[Dict[str, Any]],
    ) -> List[Tuple[str, List[Dict[str, Any]], bool]]:
        """
        Split un bucket par type si divergence forte (type guard soft).

        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

        Rules:
        - Dominance >= 70% → pas de split, un seul bucket
        - Divergence forte + label court/acronyme → split agressif par type
        - Divergence forte + label normal → garder ensemble + flag type_conflict

        Args:
            lex_key: Clé lexicale du bucket
            protos: Liste des protos du bucket

        Returns:
            Liste de (type_bucket, protos, type_conflict)
        """
        # Collecter les types (type_heuristic sur ProtoConcept)
        types = [p.get("type_heuristic") for p in protos if p.get("type_heuristic")]

        if not types:
            return [("__NONE__", protos, False)]

        counter = Counter(types)
        total = sum(counter.values())
        top_type, top_count = counter.most_common(1)[0]
        dominance = top_count / total

        # Dominance >= 70% → pas de split
        if dominance >= 0.70:
            return [(top_type, protos, False)]

        # Divergence forte détectée
        # Check if short label or acronym
        label_sample = protos[0].get("label") or protos[0].get("concept_name") or ""
        is_short_or_acronym = len(label_sample) < 6 or label_sample.isupper()

        if is_short_or_acronym:
            # Split agressif par type
            grouped = defaultdict(list)
            for p in protos:
                t = p.get("type_heuristic") or "__NONE__"
                grouped[t].append(p)

            logger.info(
                f"[OSMOSE:CorpusPromotion] Type split for short/acronym lex_key '{lex_key}': "
                f"{len(grouped)} buckets (types: {list(grouped.keys())})"
            )
            return [(t, ps, False) for t, ps in grouped.items()]

        # Label normal avec divergence → garder ensemble + flag conflict
        logger.info(
            f"[OSMOSE:CorpusPromotion] Type conflict for lex_key '{lex_key}': "
            f"dominance={dominance:.1%}, types={dict(counter)}"
        )
        return [(top_type, protos, True)]  # type_conflict=True

    # DEPRECATED: Use group_by_lex_key instead
    def group_by_canonical_label(
        self,
        protos: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        DEPRECATED: Utiliser group_by_lex_key().

        Maintenu pour compatibilité temporaire.
        """
        groups, _ = self.group_by_lex_key(protos)
        return groups

    def _normalize_label(self, label: str) -> str:
        """
        DEPRECATED: Utiliser compute_lex_key() depuis lex_utils.

        Maintenu pour compatibilité temporaire.
        """
        return compute_lex_key(label)

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
        lex_key: str,
        protos: List[Dict[str, Any]],
        document_id: str,
        type_bucket: str = "__NONE__",
        type_conflict: bool = False,
    ) -> PromotionDecision:
        """
        Détermine si un groupe de ProtoConcepts doit être promu.

        ADR: doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md
        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

        Règles unifiées:
        1. ≥2 occurrences même document → STABLE
        2. ≥2 sections différentes → STABLE
        3. ≥2 documents + signal minimal → STABLE
        4. singleton + high-signal V2 → SINGLETON

        Args:
            lex_key: Clé lexicale normalisée
            protos: Liste des ProtoConcepts du bucket
            document_id: ID du document courant
            type_bucket: Type dominant du bucket (ou "__NONE__")
            type_conflict: True si divergence de types détectée
        """
        # Sélectionner le meilleur label pour l'affichage
        best_proto = max(protos, key=lambda p: p.get("confidence") or 0.0)
        canonical_label = best_proto.get("label") or best_proto.get("concept_name") or lex_key

        decision = PromotionDecision(
            canonical_label=canonical_label,
            promote=False,
            proto_ids=[p.get("proto_id") for p in protos],
            document_ids=[document_id],
            lex_key=lex_key,
            type_bucket=type_bucket,
            type_conflict=type_conflict,
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

        # Compteur corpus (autres documents) - using lex_key
        corpus_count, corpus_doc_ids = self.count_corpus_occurrences(
            lex_key=lex_key,
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

        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

        Returns:
            ID du CanonicalConcept créé
        """
        import uuid

        # Sélectionner le meilleur proto (plus haute confidence)
        best_proto = max(protos, key=lambda p: p.get("confidence") or 0.0)

        canonical_id = f"cc_{uuid.uuid4().hex[:12]}"

        # Créer le CanonicalConcept avec lex_key, type_bucket, type_conflict
        # MERGE sur (tenant_id, lex_key, type_bucket) pour éviter doublons
        # IMPORTANT: Utiliser canonical_id (pas concept_id) pour cohérence avec le reste du code
        create_query = """
        MERGE (cc:CanonicalConcept {
            tenant_id: $tenant_id,
            lex_key: $lex_key,
            type_bucket: $type_bucket
        })
        ON CREATE SET
            cc.canonical_id = $canonical_id,
            cc.label = $label,
            cc.unified_definition = $unified_definition,
            cc.type_coarse = $type_coarse,
            cc.stability = $stability,
            cc.created_at = datetime(),
            cc.promotion_reason = $reason,
            cc.proto_count = $proto_count,
            cc.document_count = $document_count,
            cc.type_conflict = $type_conflict
        ON MATCH SET
            cc.updated_at = datetime(),
            cc.proto_count = cc.proto_count + $proto_count,
            cc.document_count = cc.document_count + $document_count
        RETURN cc.canonical_id AS id, cc.created_at IS NOT NULL AS is_new
        """

        # Lier les ProtoConcepts du document courant
        link_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.concept_id IN $proto_ids
        MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
        CREATE (p)-[:INSTANCE_OF {created_at: datetime()}]->(cc)
        RETURN count(p) AS linked
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            # Créer CC avec lex_key, type_bucket, définition et type du meilleur proto
            result = session.run(
                create_query,
                canonical_id=canonical_id,
                tenant_id=self.tenant_id,
                label=best_proto.get("label"),
                lex_key=decision.lex_key,
                type_bucket=decision.type_bucket,
                type_conflict=decision.type_conflict,
                unified_definition=best_proto.get("definition") or best_proto.get("quote") or "",
                type_coarse=best_proto.get("type_coarse") or "abstract",
                stability=decision.stability,
                reason=decision.reason,
                proto_count=decision.proto_count,
                document_count=decision.document_count,
            )
            record = result.single()
            # Si le CC existait déjà (MERGE ON MATCH), on récupère son canonical_id
            if record and record.get("id"):
                canonical_id = record["id"]

            # Lier protos
            result = session.run(
                link_query,
                tenant_id=self.tenant_id,
                proto_ids=decision.proto_ids,
                canonical_id=canonical_id,
            )
            linked = result.single()["linked"]

            # Créer les MENTIONED_IN vers les SectionContext
            mentioned_count = self._create_mentioned_in_for_canonical(
                session, canonical_id, decision.proto_ids
            )

        logger.info(
            f"[OSMOSE:CorpusPromotion] Created CanonicalConcept '{best_proto.get('label')}' "
            f"({decision.stability}) with {linked} linked protos, {mentioned_count} MENTIONED_IN"
        )

        return canonical_id

    def _create_mentioned_in_for_canonical(
        self,
        session,
        canonical_id: str,
        proto_ids: List[str]
    ) -> int:
        """
        Crée les relations MENTIONED_IN entre un CanonicalConcept et ses SectionContext.

        ADR: doc/ongoing/ADR_COVERAGE_PROPERTY_NOT_NODE.md (2026-01-16)
        Utilise section_id (UUID) pour matcher avec SectionContext.section_id.
        Fallback sur context_id pour rétrocompatibilité avec données legacy.

        Args:
            session: Session Neo4j active
            canonical_id: ID du CanonicalConcept
            proto_ids: Liste des IDs des ProtoConcepts liés

        Returns:
            Nombre de relations MENTIONED_IN créées
        """
        # ADR_COVERAGE_PROPERTY_NOT_NODE: Utiliser section_id UUID (prioritaire)
        # avec fallback sur context_id pour données legacy
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.concept_id IN $proto_ids
          AND (p.section_id IS NOT NULL OR p.context_id IS NOT NULL)

        // Priorité: section_id UUID (sec_*), sinon context_id
        WITH DISTINCT
            CASE
                WHEN p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
                THEN p.section_id
                ELSE p.context_id
            END AS section_key,
            CASE
                WHEN p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
                THEN 'section_id'
                ELSE 'context_id'
            END AS key_type

        MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})

        // Matcher SectionContext par section_id OU context_id selon key_type
        OPTIONAL MATCH (s1:SectionContext {section_id: section_key, tenant_id: $tenant_id})
        OPTIONAL MATCH (s2:SectionContext {context_id: section_key, tenant_id: $tenant_id})

        WITH cc, COALESCE(s1, s2) AS s
        WHERE s IS NOT NULL

        MERGE (cc)-[r:MENTIONED_IN]->(s)
        ON CREATE SET
            r.created_at = datetime(),
            r.mention_count = 1,
            r.source = 'corpus_promotion'
        ON MATCH SET
            r.mention_count = r.mention_count + 1,
            r.updated_at = datetime()

        RETURN count(r) AS created
        """

        result = session.run(
            query,
            tenant_id=self.tenant_id,
            proto_ids=proto_ids,
            canonical_id=canonical_id,
        )
        record = result.single()
        return record["created"] if record else 0

    def link_corpus_protos_to_canonical(
        self,
        lex_key: str,
        canonical_id: str,
        exclude_document_id: str,
    ) -> int:
        """
        Lie les ProtoConcepts du corpus existant au CanonicalConcept.

        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md
        Utilise lex_key pour le matching cross-doc.

        ADR: doc/ongoing/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md (2026-01-11)
        Utilise context_id pour MENTIONED_IN sparse.

        Returns:
            Nombre de protos liés
        """
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.lex_key = $lex_key
          AND p.document_id <> $exclude_document_id
          AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
        CREATE (p)-[:INSTANCE_OF {created_at: datetime(), linked_by: 'corpus_promotion'}]->(cc)
        RETURN count(p) AS linked
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=self.tenant_id,
                lex_key=lex_key,
                canonical_id=canonical_id,
                exclude_document_id=exclude_document_id,
            )
            linked = result.single()["linked"]

            # ADR_COVERAGE_PROPERTY_NOT_NODE: Utiliser section_id UUID avec fallback context_id
            if linked > 0:
                mentioned_query = """
                MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[:INSTANCE_OF]->(cc:CanonicalConcept {canonical_id: $canonical_id})
                WHERE p.document_id <> $exclude_document_id
                  AND (p.section_id IS NOT NULL OR p.context_id IS NOT NULL)

                // Priorité: section_id UUID (sec_*), sinon context_id
                WITH cc, DISTINCT
                    CASE
                        WHEN p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
                        THEN p.section_id
                        ELSE p.context_id
                    END AS section_key

                // Matcher SectionContext par section_id OU context_id
                OPTIONAL MATCH (s1:SectionContext {section_id: section_key, tenant_id: $tenant_id})
                OPTIONAL MATCH (s2:SectionContext {context_id: section_key, tenant_id: $tenant_id})

                WITH cc, COALESCE(s1, s2) AS s
                WHERE s IS NOT NULL

                MERGE (cc)-[r:MENTIONED_IN]->(s)
                ON CREATE SET
                    r.created_at = datetime(),
                    r.mention_count = 1,
                    r.source = 'corpus_promotion_link'
                ON MATCH SET
                    r.mention_count = r.mention_count + 1,
                    r.updated_at = datetime()

                RETURN count(r) AS created
                """
                mentioned_result = session.run(
                    mentioned_query,
                    tenant_id=self.tenant_id,
                    canonical_id=canonical_id,
                    exclude_document_id=exclude_document_id,
                )
                mentioned_count = mentioned_result.single()["created"]

                logger.info(
                    f"[OSMOSE:CorpusPromotion] Linked {linked} corpus protos to lex_key='{lex_key}', "
                    f"{mentioned_count} MENTIONED_IN created"
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

        ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

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

        # 2. Grouper par lex_key (normalisation canonique)
        groups, missing_lex_key_count = self.group_by_lex_key(protos)
        stats.groups_analyzed = len(groups)
        stats.protos_without_lex_key = missing_lex_key_count

        # 3. Analyser chaque groupe avec type guard soft
        for lex_key, group_protos in groups.items():
            # Type guard: split par type si divergence forte
            type_buckets = self.split_by_type_if_divergent(lex_key, group_protos)

            if len(type_buckets) > 1:
                stats.buckets_split_by_type += 1

            for type_bucket, bucket_protos, type_conflict in type_buckets:
                if type_conflict:
                    stats.buckets_type_conflict += 1

                decision = self.determine_promotion(
                    lex_key=lex_key,
                    protos=bucket_protos,
                    document_id=document_id,
                    type_bucket=type_bucket,
                    type_conflict=type_conflict,
                )

                if decision.promote:
                    # Créer CanonicalConcept
                    canonical_id = self.create_canonical_concept(decision, bucket_protos)

                    # Compteurs
                    if decision.stability == ConceptStability.STABLE.value:
                        stats.promoted_stable += 1
                    else:
                        stats.promoted_singleton += 1

                    # Lier protos corpus si cross-doc
                    if decision.document_count > 1:
                        linked = self.link_corpus_protos_to_canonical(
                            lex_key=lex_key,
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
            f"{stats.crossdoc_promotions} cross-doc, "
            f"missing_lex_key={stats.protos_without_lex_key}, "
            f"type_splits={stats.buckets_split_by_type}, "
            f"type_conflicts={stats.buckets_type_conflict}"
        )

        return stats

    async def promote_corpus(self) -> CorpusPromotionResult:
        """
        Exécute la promotion Pass 2.0 pour TOUT le corpus.

        Cette méthode:
        1. Liste tous les documents avec des ProtoConcepts non promus
        2. Exécute run_promotion() pour chaque document
        3. Agrège les statistiques

        Returns:
            CorpusPromotionResult avec statistiques globales
        """
        import time
        start_time = time.time()

        result = CorpusPromotionResult()

        # 1. Lister tous les documents avec ProtoConcepts non promus
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
        RETURN DISTINCT p.document_id AS document_id, count(p) AS proto_count
        ORDER BY proto_count DESC
        """

        with self.neo4j_client.driver.session(database="neo4j") as session:
            records = session.run(query, tenant_id=self.tenant_id)
            documents = [(r["document_id"], r["proto_count"]) for r in records]

        if not documents:
            logger.info(
                f"[OSMOSE:CorpusPromotion] No unlinked ProtoConcepts to promote "
                f"for tenant={self.tenant_id}"
            )
            result.execution_time_ms = (time.time() - start_time) * 1000
            return result

        logger.info(
            f"[OSMOSE:CorpusPromotion] Starting corpus promotion for "
            f"{len(documents)} documents with {sum(d[1] for d in documents)} ProtoConcepts"
        )

        # 2. Traiter chaque document
        for document_id, proto_count in documents:
            if not document_id:
                continue

            try:
                stats = self.run_promotion(document_id)

                # Agréger les stats
                result.proto_concepts_processed += stats.protos_loaded
                result.canonical_concepts_created += stats.total_promoted
                result.merged_count += stats.crossdoc_promotions
                result.singleton_count += stats.promoted_singleton
                result.skipped_count += stats.not_promoted
                result.documents_processed += 1

            except Exception as e:
                logger.error(
                    f"[OSMOSE:CorpusPromotion] Error promoting document {document_id}: {e}",
                    exc_info=True
                )

        result.execution_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[OSMOSE:CorpusPromotion] Corpus promotion complete: "
            f"{result.documents_processed} docs, "
            f"{result.canonical_concepts_created} concepts created "
            f"({result.merged_count} merged, {result.singleton_count} singletons), "
            f"{result.skipped_count} skipped"
        )

        return result


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
    "CorpusPromotionResult",
    "CorpusPromotionEngine",
    "get_corpus_promotion_engine",
    "check_high_signal_v2",
]
