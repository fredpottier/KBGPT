"""
OSMOSE Evidence Bundle - Candidate Detector (Pass 3.5)

Détection des paires de concepts candidates pour création de bundles.

Sprint 1: Intra-section uniquement, charspans requis.

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set, Tuple

from knowbase.relations.evidence_bundle_models import CandidatePair

logger = logging.getLogger(__name__)


# ===================================
# CYPHER QUERIES
# ===================================

# Sprint 1: Paires intra-section avec charspans document-wide requis
# ADR Evidence Bundle: Utilise char_start_docwide/char_end_docwide synchronisés depuis DocItem
QUERY_INTRA_SECTION_PAIRS = """
MATCH (p1:ProtoConcept {tenant_id: $tenant_id, doc_id: $document_id})
      -[:INSTANCE_OF]->(c1:CanonicalConcept)
MATCH (p2:ProtoConcept {tenant_id: $tenant_id, doc_id: $document_id})
      -[:INSTANCE_OF]->(c2:CanonicalConcept)
WHERE c1.canonical_id < c2.canonical_id
  AND p1.section_id = p2.section_id
  AND p1.section_id IS NOT NULL
  AND p1.char_start_docwide IS NOT NULL
  AND p2.char_start_docwide IS NOT NULL
RETURN
    c1.canonical_id AS subject_id,
    c1.canonical_name AS subject_label,
    c2.canonical_id AS object_id,
    c2.canonical_name AS object_label,
    p1.section_id AS shared_context_id,
    p1.definition AS subject_quote,
    p2.definition AS object_quote,
    p1.char_start_docwide AS subject_char_start,
    p1.char_end_docwide AS subject_char_end,
    p2.char_start_docwide AS object_char_start,
    p2.char_end_docwide AS object_char_end
"""

# Requête pour obtenir les paires déjà traitées (bundles existants)
QUERY_EXISTING_BUNDLES = """
MATCH (eb:EvidenceBundle {tenant_id: $tenant_id, document_id: $document_id})
RETURN eb.subject_concept_id AS subject_id, eb.object_concept_id AS object_id
"""

# Requête pour obtenir le texte d'une section (Option C: via ANCHORED_IN)
# ADR Evidence Bundle: Récupère le texte des DocItems liés aux ProtoConcepts de la section
# Note: Le context_id est le section_id legacy du ProtoConcept (pas du DocItem)
QUERY_SECTION_TEXT = """
MATCH (p:ProtoConcept {section_id: $context_id, tenant_id: $tenant_id})
      -[:ANCHORED_IN]->(d:DocItem)
WHERE d.text IS NOT NULL
WITH DISTINCT d
ORDER BY d.reading_order_index
WITH collect(d.text) AS texts
RETURN reduce(acc = '', t IN texts | acc + t + '\n') AS text
"""

# Alternative: Requête pour document complet (fallback)
QUERY_DOCUMENT_TEXT = """
MATCH (d:DocItem {doc_id: $document_id, tenant_id: $tenant_id})
WHERE d.text IS NOT NULL
WITH d ORDER BY d.reading_order_index
WITH collect(d.text) AS texts
RETURN reduce(acc = '', t IN texts | acc + t + '\n') AS text
"""


# ===================================
# CANDIDATE DETECTOR CLASS
# ===================================

class CandidateDetector:
    """
    Détecteur de paires de concepts candidates pour bundles.

    Sprint 1: Intra-section uniquement.
    - Exige charspans sur les ProtoConcepts
    - Filtre les paires déjà traitées
    """

    def __init__(self, neo4j_client):
        """
        Initialise le détecteur.

        Args:
            neo4j_client: Instance de Neo4jClient
        """
        self.neo4j_client = neo4j_client

    def find_intra_section_pairs(
        self,
        document_id: str,
        tenant_id: str = "default",
        exclude_existing: bool = True,
    ) -> List[CandidatePair]:
        """
        Trouve les paires de concepts intra-section.

        Sprint 1: Uniquement les paires dans la MÊME section,
        avec charspans disponibles.

        Args:
            document_id: ID du document à traiter
            tenant_id: Tenant ID
            exclude_existing: Si True, exclut les paires déjà bundlées

        Returns:
            Liste de CandidatePair
        """
        logger.info(
            f"[OSMOSE:Pass3.5] Finding intra-section pairs for document={document_id}"
        )

        # Récupérer les paires existantes si nécessaire
        existing_pairs: Set[Tuple[str, str]] = set()
        if exclude_existing:
            existing_pairs = self._get_existing_pairs(document_id, tenant_id)
            if existing_pairs:
                logger.info(
                    f"[OSMOSE:Pass3.5] Found {len(existing_pairs)} existing bundles to exclude"
                )

        # Exécuter la requête principale
        pairs: List[CandidatePair] = []
        pairs_skipped_existing = 0
        pairs_skipped_no_charspan = 0

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_INTRA_SECTION_PAIRS,
                tenant_id=tenant_id,
                document_id=document_id,
            )

            for record in result:
                subject_id = record["subject_id"]
                object_id = record["object_id"]

                # Filtrer les paires déjà traitées
                pair_key = (subject_id, object_id)
                pair_key_reverse = (object_id, subject_id)
                if pair_key in existing_pairs or pair_key_reverse in existing_pairs:
                    pairs_skipped_existing += 1
                    continue

                # Vérifier les charspans (double check, normalement filtré par la query)
                if record["subject_char_start"] is None or record["object_char_start"] is None:
                    pairs_skipped_no_charspan += 1
                    continue

                # Créer le CandidatePair
                pair = CandidatePair(
                    subject_concept_id=subject_id,
                    subject_label=record["subject_label"],
                    object_concept_id=object_id,
                    object_label=record["object_label"],
                    shared_context_id=record["shared_context_id"],
                    subject_quote=record["subject_quote"],
                    object_quote=record["object_quote"],
                    subject_char_start=record["subject_char_start"],
                    subject_char_end=record["subject_char_end"],
                    object_char_start=record["object_char_start"],
                    object_char_end=record["object_char_end"],
                )
                pairs.append(pair)

        logger.info(
            f"[OSMOSE:Pass3.5] Found {len(pairs)} candidate pairs "
            f"(skipped: {pairs_skipped_existing} existing, "
            f"{pairs_skipped_no_charspan} no charspan)"
        )

        return pairs

    def _get_existing_pairs(
        self,
        document_id: str,
        tenant_id: str,
    ) -> Set[Tuple[str, str]]:
        """
        Récupère les paires de concepts déjà bundlées.

        Returns:
            Set de tuples (subject_id, object_id)
        """
        existing: Set[Tuple[str, str]] = set()

        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_EXISTING_BUNDLES,
                tenant_id=tenant_id,
                document_id=document_id,
            )

            for record in result:
                existing.add((record["subject_id"], record["object_id"]))

        return existing

    def get_section_text(
        self,
        context_id: str,
        tenant_id: str = "default",
    ) -> Optional[str]:
        """
        Récupère le texte d'une section.

        Args:
            context_id: ID de la section
            tenant_id: Tenant ID

        Returns:
            Texte de la section ou None si non trouvé
        """
        with self.neo4j_client.driver.session(
            database=self.neo4j_client.database
        ) as session:
            result = session.run(
                QUERY_SECTION_TEXT,
                context_id=context_id,
                tenant_id=tenant_id,
            )

            record = result.single()
            if record:
                return record["text"]

        return None

    def get_pairs_by_section(
        self,
        pairs: List[CandidatePair],
    ) -> dict[str, List[CandidatePair]]:
        """
        Groupe les paires par section.

        Utile pour optimiser le parsing spaCy (un seul parse par section).

        Args:
            pairs: Liste de paires candidates

        Returns:
            Dict section_id -> liste de paires
        """
        by_section: dict[str, List[CandidatePair]] = {}

        for pair in pairs:
            section_id = pair.shared_context_id
            if section_id not in by_section:
                by_section[section_id] = []
            by_section[section_id].append(pair)

        return by_section


# ===================================
# HELPER FUNCTIONS
# ===================================

def order_pair_by_position(pair: CandidatePair) -> CandidatePair:
    """
    Ordonne une paire pour que le sujet soit avant l'objet.

    Si l'objet apparaît avant le sujet dans le texte,
    on inverse pour avoir l'ordre de lecture naturel.

    Args:
        pair: Paire candidate

    Returns:
        Paire avec sujet avant objet (par position)
    """
    # Si charspans disponibles, utiliser les positions
    if pair.subject_char_start is not None and pair.object_char_start is not None:
        if pair.object_char_start < pair.subject_char_start:
            # Inverser sujet et objet
            return CandidatePair(
                subject_concept_id=pair.object_concept_id,
                subject_label=pair.object_label,
                object_concept_id=pair.subject_concept_id,
                object_label=pair.subject_label,
                shared_context_id=pair.shared_context_id,
                subject_quote=pair.object_quote,
                object_quote=pair.subject_quote,
                subject_char_start=pair.object_char_start,
                subject_char_end=pair.object_char_end,
                object_char_start=pair.subject_char_start,
                object_char_end=pair.subject_char_end,
            )

    return pair


def filter_self_relations(pairs: List[CandidatePair]) -> List[CandidatePair]:
    """
    Filtre les paires où sujet == objet.

    Args:
        pairs: Liste de paires

    Returns:
        Liste filtrée
    """
    return [p for p in pairs if p.subject_concept_id != p.object_concept_id]
