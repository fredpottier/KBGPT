#!/usr/bin/env python3
"""
Script de test Pass 3.5 - Evidence Bundle Resolver

Ce script teste le système Evidence Bundle sur le document
020_RISE_with_SAP_Cloud_ERP_Private_full.

Usage:
    docker compose -f docker-compose.yml exec app python scripts/run_pass35_test.py
"""

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_prerequisites():
    """Vérifie les prérequis avant exécution."""
    from knowbase.common.clients.neo4j_client import Neo4jClient

    client = Neo4jClient()

    # Vérifier le document
    query = """
    MATCH (p:ProtoConcept {document_id: $doc_id})-[:INSTANCE_OF]->(c:CanonicalConcept)
    RETURN count(DISTINCT c) as canonical_count, count(p) as proto_count
    """

    doc_id = "020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357"

    with client.driver.session(database=client.database) as session:
        result = session.run(query, doc_id=doc_id)
        record = result.single()

        if record:
            logger.info(f"Document: {doc_id}")
            logger.info(f"  - CanonicalConcepts: {record['canonical_count']}")
            logger.info(f"  - ProtoConcepts: {record['proto_count']}")
            return record['canonical_count'] > 0

    return False


def find_candidate_pairs_adapted():
    """
    Trouve les paires candidates avec requête adaptée au schéma actuel.

    Adaptation:
    - Utilise concept_name au lieu de label (absent sur ProtoConcepts)
    - Ne requiert pas char_start/char_end (non disponible)
    - Utilise definition comme contexte de citation
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient

    client = Neo4jClient()

    # Requête adaptée au schéma actuel
    query = """
    MATCH (p1:ProtoConcept {document_id: $doc_id})-[:INSTANCE_OF]->(c1:CanonicalConcept)
    MATCH (p2:ProtoConcept {document_id: $doc_id})-[:INSTANCE_OF]->(c2:CanonicalConcept)
    WHERE c1.canonical_id < c2.canonical_id
      AND p1.context_id = p2.context_id
      AND p1.context_id IS NOT NULL
    WITH c1, c2, p1, p2, p1.context_id as shared_context
    RETURN DISTINCT
        c1.canonical_id AS subject_id,
        c1.canonical_name AS subject_label,
        c2.canonical_id AS object_id,
        c2.canonical_name AS object_label,
        shared_context AS shared_context_id,
        p1.definition AS subject_quote,
        p2.definition AS object_quote,
        p1.concept_name AS subject_name,
        p2.concept_name AS object_name
    LIMIT 100
    """

    doc_id = "020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357"
    pairs = []

    with client.driver.session(database=client.database) as session:
        result = session.run(query, doc_id=doc_id)

        for record in result:
            pairs.append({
                "subject_id": record["subject_id"],
                "subject_label": record["subject_label"],
                "object_id": record["object_id"],
                "object_label": record["object_label"],
                "shared_context_id": record["shared_context_id"],
                "subject_quote": record["subject_quote"],
                "object_quote": record["object_quote"],
            })

    return pairs


def analyze_pairs(pairs):
    """Analyse les paires trouvées."""
    logger.info(f"\n{'='*60}")
    logger.info(f"ANALYSE DES PAIRES CANDIDATES")
    logger.info(f"{'='*60}")
    logger.info(f"Total paires trouvées: {len(pairs)}")

    # Grouper par section
    by_section = {}
    for p in pairs:
        ctx = p["shared_context_id"]
        if ctx not in by_section:
            by_section[ctx] = []
        by_section[ctx].append(p)

    logger.info(f"Sections avec paires: {len(by_section)}")

    # Afficher les premières paires
    logger.info(f"\nPremières 10 paires:")
    for i, p in enumerate(pairs[:10]):
        logger.info(f"  {i+1}. {p['subject_label']} <-> {p['object_label']}")
        logger.info(f"      Section: {p['shared_context_id'][:40]}...")
        if p['subject_quote']:
            logger.info(f"      Subject quote: {p['subject_quote'][:60]}...")

    return by_section


def test_predicate_extraction_on_definitions(pairs):
    """
    Teste l'extraction de prédicats sur les définitions disponibles.

    Sprint 1: Sans charspans, on utilise les définitions comme contexte.
    """
    import spacy

    logger.info(f"\n{'='*60}")
    logger.info(f"TEST EXTRACTION PRÉDICATS")
    logger.info(f"{'='*60}")

    try:
        nlp = spacy.load("en_core_web_md")
    except OSError:
        logger.warning("Modèle spaCy en_core_web_md non disponible")
        return []

    predicates_found = []

    for i, p in enumerate(pairs[:20]):
        # Construire un contexte à partir des définitions
        subj_def = p.get("subject_quote", "") or ""
        obj_def = p.get("object_quote", "") or ""

        if not subj_def and not obj_def:
            continue

        # Chercher un verbe dans les définitions
        context = f"{subj_def} {obj_def}"
        doc = nlp(context)

        verbs = [t for t in doc if t.pos_ == "VERB" and t.dep_ not in ("aux", "auxpass")]

        if verbs:
            predicates_found.append({
                "pair": (p["subject_label"], p["object_label"]),
                "verb": verbs[0].lemma_,
                "context": context[:100],
            })

    logger.info(f"Prédicats trouvés: {len(predicates_found)}")
    for pf in predicates_found[:5]:
        logger.info(f"  - {pf['pair'][0]} --[{pf['verb']}]--> {pf['pair'][1]}")

    return predicates_found


def create_test_bundles(pairs, predicates_found):
    """
    Crée des bundles de test sans les persister.
    """
    from knowbase.relations.evidence_bundle_models import (
        EvidenceBundle,
        EvidenceFragment,
        FragmentType,
        ExtractionMethodBundle,
        BundleValidationStatus,
    )
    from ulid import ULID

    logger.info(f"\n{'='*60}")
    logger.info(f"CRÉATION BUNDLES TEST")
    logger.info(f"{'='*60}")

    bundles = []

    # Mapping pour relation type
    VERB_TO_RELATION = {
        "use": "USES",
        "integrate": "INTEGRATES_WITH",
        "connect": "CONNECTS_TO",
        "provide": "PROVIDES",
        "manage": "MANAGES",
        "store": "STORES",
        "process": "PROCESSES",
        "require": "REQUIRES",
        "enable": "ENABLES",
        "support": "SUPPORTS",
    }

    for pf in predicates_found[:10]:
        pair_labels = pf["pair"]
        verb = pf["verb"]

        # Trouver la paire correspondante
        pair = None
        for p in pairs:
            if p["subject_label"] == pair_labels[0] and p["object_label"] == pair_labels[1]:
                pair = p
                break

        if not pair:
            continue

        # Créer fragments
        evidence_subject = EvidenceFragment(
            fragment_id=f"frag:{ULID()}",
            fragment_type=FragmentType.ENTITY_MENTION,
            text=pair["subject_label"],
            source_context_id=pair["shared_context_id"],
            confidence=0.7,  # Réduit car pas de charspan
            extraction_method=ExtractionMethodBundle.FUZZY_MATCH,
        )

        evidence_object = EvidenceFragment(
            fragment_id=f"frag:{ULID()}",
            fragment_type=FragmentType.ENTITY_MENTION,
            text=pair["object_label"],
            source_context_id=pair["shared_context_id"],
            confidence=0.7,
            extraction_method=ExtractionMethodBundle.FUZZY_MATCH,
        )

        evidence_predicate = EvidenceFragment(
            fragment_id=f"frag:{ULID()}",
            fragment_type=FragmentType.PREDICATE_LEXICAL,
            text=verb,
            source_context_id=pair["shared_context_id"],
            confidence=0.6,
            extraction_method=ExtractionMethodBundle.SPACY_DEP,
        )

        # Type de relation
        relation_type = VERB_TO_RELATION.get(verb.lower(), "RELATED_TO")

        # Créer bundle
        bundle = EvidenceBundle(
            bundle_id=f"bnd:{ULID()}",
            tenant_id="default",
            document_id="020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357",
            evidence_subject=evidence_subject,
            evidence_object=evidence_object,
            evidence_predicate=[evidence_predicate],
            subject_concept_id=pair["subject_id"],
            object_concept_id=pair["object_id"],
            relation_type_candidate=relation_type,
            typing_confidence=0.6,
            confidence=0.6,  # min(0.7, 0.7, 0.6)
            validation_status=BundleValidationStatus.CANDIDATE,
        )

        bundles.append(bundle)

    logger.info(f"Bundles créés: {len(bundles)}")
    for b in bundles:
        logger.info(f"  - {b.evidence_subject.text} --[{b.relation_type_candidate}]--> {b.evidence_object.text}")
        logger.info(f"    Confidence: {b.confidence:.2f}")

    return bundles


def validate_test_bundles(bundles):
    """Valide les bundles de test."""
    from knowbase.relations.bundle_validator import validate_bundle

    logger.info(f"\n{'='*60}")
    logger.info(f"VALIDATION BUNDLES")
    logger.info(f"{'='*60}")

    valid_count = 0
    rejected_count = 0
    rejection_reasons = {}

    for bundle in bundles:
        result = validate_bundle(bundle)

        if result.is_valid:
            valid_count += 1
            logger.info(f"  ✅ {bundle.evidence_subject.text} -> {bundle.evidence_object.text}")
        else:
            rejected_count += 1
            reason = result.rejection_reason or "UNKNOWN"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            logger.info(f"  ❌ {bundle.evidence_subject.text} -> {bundle.evidence_object.text}: {reason}")

    logger.info(f"\nRésumé validation:")
    logger.info(f"  - Valides: {valid_count}")
    logger.info(f"  - Rejetés: {rejected_count}")
    if rejection_reasons:
        logger.info(f"  - Raisons de rejet:")
        for reason, count in rejection_reasons.items():
            logger.info(f"      {reason}: {count}")

    return valid_count, rejected_count, rejection_reasons


def main():
    """Point d'entrée principal."""
    logger.info("="*60)
    logger.info("OSMOSE Pass 3.5 - Evidence Bundle Resolver - TEST")
    logger.info("="*60)
    logger.info(f"Démarrage: {datetime.now().isoformat()}")

    # 1. Vérifier prérequis
    logger.info("\n[1/5] Vérification prérequis...")
    if not check_prerequisites():
        logger.error("Prérequis non satisfaits!")
        sys.exit(1)

    # 2. Trouver paires candidates
    logger.info("\n[2/5] Recherche paires candidates...")
    pairs = find_candidate_pairs_adapted()
    if not pairs:
        logger.error("Aucune paire trouvée!")
        sys.exit(1)

    # 3. Analyser paires
    logger.info("\n[3/5] Analyse des paires...")
    by_section = analyze_pairs(pairs)

    # 4. Tester extraction prédicats
    logger.info("\n[4/5] Test extraction prédicats...")
    predicates_found = test_predicate_extraction_on_definitions(pairs)

    # 5. Créer et valider bundles
    logger.info("\n[5/5] Création et validation bundles...")
    bundles = create_test_bundles(pairs, predicates_found)
    valid, rejected, reasons = validate_test_bundles(bundles)

    # Résumé final
    logger.info(f"\n{'='*60}")
    logger.info("RÉSUMÉ FINAL")
    logger.info(f"{'='*60}")
    logger.info(f"Paires candidates trouvées: {len(pairs)}")
    logger.info(f"Sections avec paires: {len(by_section)}")
    logger.info(f"Prédicats extraits: {len(predicates_found)}")
    logger.info(f"Bundles créés: {len(bundles)}")
    logger.info(f"Bundles valides: {valid}")
    logger.info(f"Bundles rejetés: {rejected}")

    # Critères Sprint 1
    logger.info(f"\n{'='*60}")
    logger.info("CRITÈRES SPRINT 1")
    logger.info(f"{'='*60}")
    logger.info(f"[ ] Au moins 5 relations promues: {valid} >= 5 ? {'✅' if valid >= 5 else '❌'}")
    logger.info(f"[ ] Au moins 10 bundles créés: {len(bundles)} >= 10 ? {'✅' if len(bundles) >= 10 else '❌'}")
    logger.info(f"[ ] Taux de rejet >= 60%: {rejected}/{len(bundles)} = {rejected/len(bundles)*100 if bundles else 0:.0f}% ? {'✅' if bundles and rejected/len(bundles) >= 0.6 else '⚠️ (taux attendu pour précision haute)'}")

    logger.info(f"\n⚠️  NOTE: Test en mode dégradé (sans charspans)")
    logger.info(f"    Pour résultats complets, ré-extraire avec charspans")

    return 0


if __name__ == "__main__":
    sys.exit(main())
