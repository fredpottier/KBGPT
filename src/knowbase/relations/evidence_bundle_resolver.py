"""
OSMOSE Evidence Bundle - Resolver Principal (Pass 3.5)

Orchestrateur du traitement des Evidence Bundles.

Sprint 1: Intra-section uniquement, textuel uniquement.
Objectif: 5-10 relations, précision ≥ 95%

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional

from ulid import ULID

from knowbase.relations.bundle_persistence import BundlePersistence
from knowbase.relations.bundle_validator import (
    validate_bundle,
    apply_validation_to_bundle,
)
from knowbase.relations.candidate_detector import (
    CandidateDetector,
    filter_self_relations,
    order_pair_by_position,
)
from knowbase.relations.confidence_calculator import (
    compute_bundle_confidence_from_fragments,
    compute_predicate_confidence,
    compute_typing_confidence,
)
from knowbase.relations.evidence_bundle_models import (
    BundleProcessingResult,
    BundleProcessingStats,
    BundleValidationStatus,
    CandidatePair,
    EvidenceBundle,
    EvidenceFragment,
    ExtractionMethodBundle,
    FragmentType,
    PredicateCandidate,
)
from knowbase.relations.predicate_extractor import (
    extract_predicate_for_pair,
    get_spacy_model,
)

logger = logging.getLogger(__name__)


# ===================================
# RELATION TYPE MAPPING
# ===================================

# Mapping lemme -> type de relation (Sprint 1: basic)
# Ce mapping sera enrichi en Sprint 2 avec un classifier
PREDICATE_TO_RELATION_TYPE = {
    # Français
    "intégrer": "INTEGRATES_WITH",
    "utiliser": "USES",
    "connecter": "CONNECTS_TO",
    "supporter": "SUPPORTS",
    "permettre": "ENABLES",
    "nécessiter": "REQUIRES",
    "dépendre": "DEPENDS_ON",
    "fournir": "PROVIDES",
    "gérer": "MANAGES",
    "traiter": "PROCESSES",
    "stocker": "STORES",
    "transférer": "TRANSFERS",
    "synchroniser": "SYNCS_WITH",
    "valider": "VALIDATES",
    "contrôler": "CONTROLS",

    # Anglais
    "integrate": "INTEGRATES_WITH",
    "use": "USES",
    "connect": "CONNECTS_TO",
    "support": "SUPPORTS",
    "enable": "ENABLES",
    "require": "REQUIRES",
    "depend": "DEPENDS_ON",
    "provide": "PROVIDES",
    "manage": "MANAGES",
    "process": "PROCESSES",
    "store": "STORES",
    "transfer": "TRANSFERS",
    "sync": "SYNCS_WITH",
    "validate": "VALIDATES",
    "control": "CONTROLS",
}

# Type par défaut si mapping non trouvé
DEFAULT_RELATION_TYPE = "RELATED_TO"


# ===================================
# EVIDENCE BUNDLE RESOLVER
# ===================================

class EvidenceBundleResolver:
    """
    Orchestrateur principal du traitement des Evidence Bundles.

    Sprint 1: Mode intra-section uniquement.
    - Détecte les paires candidates
    - Extrait les prédicats
    - Valide les bundles
    - Persiste et promeut

    Usage:
        resolver = EvidenceBundleResolver(neo4j_client)
        result = resolver.process_document(document_id)
    """

    def __init__(
        self,
        neo4j_client,
        lang: str = "fr",
        auto_promote: bool = True,
        min_confidence_for_promotion: float = 0.6,
    ):
        """
        Initialise le resolver.

        Args:
            neo4j_client: Instance de Neo4jClient
            lang: Code langue par défaut
            auto_promote: Si True, promeut automatiquement les bundles valides
            min_confidence_for_promotion: Seuil de confiance pour promotion
        """
        self.neo4j_client = neo4j_client
        self.lang = lang
        self.auto_promote = auto_promote
        self.min_confidence_for_promotion = min_confidence_for_promotion

        # Composants
        self.candidate_detector = CandidateDetector(neo4j_client)
        self.persistence = BundlePersistence(neo4j_client)

        # Pré-charger le modèle spaCy
        try:
            get_spacy_model(lang)
        except Exception as e:
            logger.warning(f"[OSMOSE:Pass3.5] Could not preload spaCy model: {e}")

    def process_document(
        self,
        document_id: str,
        tenant_id: str = "default",
    ) -> BundleProcessingResult:
        """
        Traite un document complet.

        Pipeline:
        1. Détecter les paires candidates (intra-section)
        2. Pour chaque paire, extraire le prédicat
        3. Construire le bundle
        4. Valider le bundle
        5. Persister
        6. Promouvoir si auto_promote=True

        Args:
            document_id: ID du document
            tenant_id: Tenant ID

        Returns:
            BundleProcessingResult avec stats et bundles
        """
        start_time = time.time()

        logger.info(
            f"[OSMOSE:Pass3.5] Processing document {document_id} "
            f"(tenant={tenant_id}, lang={self.lang})"
        )

        stats = BundleProcessingStats()
        bundles: List[EvidenceBundle] = []

        # Phase 1: Détecter les paires candidates
        pairs = self.candidate_detector.find_intra_section_pairs(
            document_id=document_id,
            tenant_id=tenant_id,
            exclude_existing=True,
        )

        stats.pairs_found = len(pairs)

        # Filtrer les auto-relations
        pairs = filter_self_relations(pairs)

        # Ordonner par position (sujet avant objet)
        pairs = [order_pair_by_position(p) for p in pairs]

        # Filtrer les paires sans charspan
        pairs_with_charspan = [
            p for p in pairs
            if p.subject_char_start is not None
            and p.object_char_start is not None
        ]
        stats.pairs_with_charspan = len(pairs_with_charspan)
        stats.pairs_skipped_no_charspan = len(pairs) - len(pairs_with_charspan)

        logger.info(
            f"[OSMOSE:Pass3.5] Found {len(pairs_with_charspan)} pairs with charspans "
            f"(skipped {stats.pairs_skipped_no_charspan} without)"
        )

        # Grouper par section pour optimiser
        pairs_by_section = self.candidate_detector.get_pairs_by_section(
            pairs_with_charspan
        )

        # Phase 2-6: Traiter chaque section
        for section_id, section_pairs in pairs_by_section.items():
            # Récupérer le texte de la section
            section_text = self.candidate_detector.get_section_text(
                section_id, tenant_id
            )

            if not section_text:
                logger.warning(
                    f"[OSMOSE:Pass3.5] Section {section_id} text not found, skipping"
                )
                continue

            # Traiter chaque paire de la section
            for pair in section_pairs:
                bundle = self._process_pair(
                    pair=pair,
                    section_text=section_text,
                    document_id=document_id,
                    tenant_id=tenant_id,
                )

                if bundle:
                    bundles.append(bundle)
                    stats.bundles_created += 1

                    # Valider et persister
                    bundle = apply_validation_to_bundle(
                        bundle, section_text, self.lang
                    )

                    self.persistence.persist_bundle(bundle)

                    if bundle.validation_status == BundleValidationStatus.REJECTED:
                        stats.bundles_rejected += 1
                        reason = bundle.rejection_reason or "UNKNOWN"
                        stats.rejection_counts[reason] = (
                            stats.rejection_counts.get(reason, 0) + 1
                        )
                    elif self.auto_promote and bundle.confidence >= self.min_confidence_for_promotion:
                        # Promouvoir automatiquement
                        relation_id = self.persistence.promote_bundle_to_relation(
                            bundle.bundle_id, tenant_id
                        )
                        if relation_id:
                            stats.bundles_promoted += 1
                            bundle.promoted_relation_id = relation_id
                            bundle.validation_status = BundleValidationStatus.PROMOTED

        # Résultat final
        processing_time = time.time() - start_time

        result = BundleProcessingResult(
            document_id=document_id,
            tenant_id=tenant_id,
            bundles=bundles,
            stats=stats,
            processing_time_seconds=processing_time,
        )

        logger.info(
            f"[OSMOSE:Pass3.5] Document {document_id} processed in {processing_time:.2f}s: "
            f"{stats.bundles_created} bundles created, "
            f"{stats.bundles_promoted} promoted, "
            f"{stats.bundles_rejected} rejected"
        )

        return result

    def _process_pair(
        self,
        pair: CandidatePair,
        section_text: str,
        document_id: str,
        tenant_id: str,
    ) -> Optional[EvidenceBundle]:
        """
        Traite une paire de concepts.

        Args:
            pair: Paire candidate
            section_text: Texte de la section
            document_id: ID du document
            tenant_id: Tenant ID

        Returns:
            EvidenceBundle ou None si échec
        """
        logger.debug(
            f"[OSMOSE:Pass3.5] Processing pair: "
            f"{pair.subject_label} <-> {pair.object_label}"
        )

        # Extraire le prédicat
        predicate = extract_predicate_for_pair(
            section_text=section_text,
            subject_label=pair.subject_label,
            subject_char_start=pair.subject_char_start,
            subject_char_end=pair.subject_char_end,
            object_label=pair.object_label,
            object_char_start=pair.object_char_start,
            object_char_end=pair.object_char_end,
            lang=self.lang,
        )

        if not predicate:
            logger.debug(
                f"[OSMOSE:Pass3.5] No valid predicate found for pair "
                f"{pair.subject_label} <-> {pair.object_label}"
            )
            return None

        # Construire le bundle
        bundle = self._build_bundle(
            pair=pair,
            predicate=predicate,
            section_text=section_text,
            document_id=document_id,
            tenant_id=tenant_id,
        )

        return bundle

    def _build_bundle(
        self,
        pair: CandidatePair,
        predicate: PredicateCandidate,
        section_text: str,
        document_id: str,
        tenant_id: str,
    ) -> EvidenceBundle:
        """
        Construit un EvidenceBundle à partir d'une paire et d'un prédicat.

        Args:
            pair: Paire candidate
            predicate: Prédicat extrait
            section_text: Texte de la section
            document_id: ID du document
            tenant_id: Tenant ID

        Returns:
            EvidenceBundle
        """
        bundle_id = f"bnd:{str(ULID())}"

        # Fragment sujet (EA)
        evidence_subject = EvidenceFragment(
            fragment_id=f"frag:{str(ULID())}",
            fragment_type=FragmentType.ENTITY_MENTION,
            text=pair.subject_quote or pair.subject_label,
            source_context_id=pair.shared_context_id,
            char_start=pair.subject_char_start,
            char_end=pair.subject_char_end,
            confidence=0.9 if pair.subject_char_start else 0.7,
            extraction_method=(
                ExtractionMethodBundle.CHARSPAN_EXACT
                if pair.subject_char_start
                else ExtractionMethodBundle.FUZZY_MATCH
            ),
        )

        # Fragment objet (EB)
        evidence_object = EvidenceFragment(
            fragment_id=f"frag:{str(ULID())}",
            fragment_type=FragmentType.ENTITY_MENTION,
            text=pair.object_quote or pair.object_label,
            source_context_id=pair.shared_context_id,
            char_start=pair.object_char_start,
            char_end=pair.object_char_end,
            confidence=0.9 if pair.object_char_start else 0.7,
            extraction_method=(
                ExtractionMethodBundle.CHARSPAN_EXACT
                if pair.object_char_start
                else ExtractionMethodBundle.FUZZY_MATCH
            ),
        )

        # Fragment prédicat (EP)
        predicate_confidence = compute_predicate_confidence(predicate)
        evidence_predicate = EvidenceFragment(
            fragment_id=f"frag:{str(ULID())}",
            fragment_type=FragmentType.PREDICATE_LEXICAL,
            text=predicate.text,
            source_context_id=pair.shared_context_id,
            char_start=predicate.char_start,
            char_end=predicate.char_end,
            confidence=predicate_confidence,
            extraction_method=ExtractionMethodBundle.SPACY_DEP,
        )

        # Déterminer le type de relation
        relation_type = PREDICATE_TO_RELATION_TYPE.get(
            predicate.lemma.lower(),
            DEFAULT_RELATION_TYPE,
        )

        # Calculer les confiances
        bundle_confidence = compute_bundle_confidence_from_fragments(
            evidence_subject,
            evidence_object,
            [evidence_predicate],
        )

        typing_confidence = compute_typing_confidence(
            predicate.text,
            relation_type,
            predicate_confidence,
        )

        # Construire le bundle
        bundle = EvidenceBundle(
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            document_id=document_id,
            evidence_subject=evidence_subject,
            evidence_object=evidence_object,
            evidence_predicate=[evidence_predicate],
            subject_concept_id=pair.subject_concept_id,
            object_concept_id=pair.object_concept_id,
            relation_type_candidate=relation_type,
            typing_confidence=typing_confidence,
            confidence=bundle_confidence,
            validation_status=BundleValidationStatus.CANDIDATE,
        )

        logger.debug(
            f"[OSMOSE:Pass3.5] Built bundle {bundle_id}: "
            f"{pair.subject_label} --[{relation_type}]--> {pair.object_label} "
            f"(confidence={bundle_confidence:.3f})"
        )

        return bundle


# ===================================
# CONVENIENCE FUNCTIONS
# ===================================

def process_document_evidence_bundles(
    neo4j_client,
    document_id: str,
    tenant_id: str = "default",
    lang: str = "fr",
    auto_promote: bool = True,
) -> BundleProcessingResult:
    """
    Fonction de convenance pour traiter un document.

    Args:
        neo4j_client: Client Neo4j
        document_id: ID du document
        tenant_id: Tenant ID
        lang: Code langue
        auto_promote: Si True, promeut automatiquement

    Returns:
        BundleProcessingResult
    """
    resolver = EvidenceBundleResolver(
        neo4j_client=neo4j_client,
        lang=lang,
        auto_promote=auto_promote,
    )

    return resolver.process_document(document_id, tenant_id)


def promote_pending_bundles(
    neo4j_client,
    tenant_id: str = "default",
    min_confidence: float = 0.6,
    limit: int = 100,
) -> int:
    """
    Promeut les bundles en attente.

    Args:
        neo4j_client: Client Neo4j
        tenant_id: Tenant ID
        min_confidence: Confiance minimale
        limit: Nombre maximum

    Returns:
        Nombre de bundles promus
    """
    persistence = BundlePersistence(neo4j_client)

    candidates = persistence.get_candidate_bundles(
        tenant_id=tenant_id,
        min_confidence=min_confidence,
        limit=limit,
    )

    promoted = 0
    for bundle in candidates:
        relation_id = persistence.promote_bundle_to_relation(
            bundle.bundle_id, tenant_id
        )
        if relation_id:
            promoted += 1

    logger.info(
        f"[OSMOSE:Pass3.5] Promoted {promoted}/{len(candidates)} pending bundles"
    )

    return promoted
