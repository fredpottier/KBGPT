#!/usr/bin/env python3
"""
Phase 2.11 - Test Extraction Claims

Script de test pour valider l'extraction de claims (assertions unaires)
depuis du texte technique.

Usage:
    docker-compose exec app python scripts/test_claim_extraction.py
    docker-compose exec app python scripts/test_claim_extraction.py --text "custom text"
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime

# Setup path
sys.path.insert(0, "/app/src")

from openai import AsyncOpenAI

from knowbase.relations import (
    LLMClaimExtractor,
    ClaimExtractionResult,
    RawClaim,
    compute_scope_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Textes de Test
# =============================================================================

TEST_TEXT_SLA = """
SAP S/4HANA Cloud offre une disponibilité garantie de 99.7% pour l'édition standard.
Avec le package Premium Support, le SLA peut atteindre 99.9%.

Pour les clients Enterprise, le temps de réponse garanti est inférieur à 200ms
pour les requêtes standards.

Configuration minimale requise :
- RAM : 64 Go minimum
- Stockage : 500 Go SSD
- CPU : 16 cores

Prix indicatif : 500€ par utilisateur par mois (édition Professional).
Remise volume disponible à partir de 100 utilisateurs.
"""

TEST_TEXT_METRICS = """
Rapport Performance Q4 2023

Customer Retention Rate (CRR) : 92%
Net Promoter Score (NPS) : 67

Evolution du CRR :
- Q1 2023 : 89%
- Q2 2023 : 90%
- Q3 2023 : 91%
- Q4 2023 : 92%

Objectif 2024 : atteindre un CRR de 95%.

Temps moyen de résolution des tickets : 4h
Satisfaction client : 4.2/5
"""

TEST_TEXT_CERTIFICATION = """
SAP S/4HANA Cloud est certifié :
- ISO 27001 (sécurité de l'information)
- SOC 2 Type II (contrôles de sécurité)
- GDPR compliant pour l'Union Européenne

La certification ISO 27001 a été obtenue en 2020.
Renouvellement annuel confirmé.

Note : La certification HIPAA n'est PAS incluse dans l'offre standard.
Elle nécessite le module Healthcare additionnel.
"""

TEST_CONCEPTS = [
    {"id": "concept_s4hana_cloud", "name": "SAP S/4HANA Cloud", "type": "PRODUCT"},
    {"id": "concept_crr", "name": "Customer Retention Rate", "type": "METRIC"},
    {"id": "concept_nps", "name": "Net Promoter Score", "type": "METRIC"},
    {"id": "concept_iso27001", "name": "ISO 27001", "type": "CERTIFICATION"},
    {"id": "concept_soc2", "name": "SOC 2", "type": "CERTIFICATION"},
    {"id": "concept_gdpr", "name": "GDPR", "type": "REGULATION"},
    {"id": "concept_hipaa", "name": "HIPAA", "type": "REGULATION"},
]


# =============================================================================
# Test Functions
# =============================================================================

def print_claim(claim: RawClaim, index: int):
    """Affiche un claim de façon lisible."""
    print(f"\n  [{index}] {claim.claim_type}")
    print(f"      Subject: {claim.subject_concept_id} ({claim.subject_surface_form})")
    print(f"      Value: {claim.value_raw} ({claim.value_type})")
    if claim.value_numeric:
        print(f"      Numeric: {claim.value_numeric} {claim.unit or ''}")
    if claim.scope_struct:
        print(f"      Scope: {json.dumps(claim.scope_struct)}")
    if claim.valid_time_hint:
        print(f"      Time: {claim.valid_time_hint}")
    print(f"      Confidence: {claim.confidence:.2f}")

    flags_active = []
    if claim.flags.negated:
        flags_active.append("NEGATED")
    if claim.flags.hedged:
        flags_active.append("HEDGED")
    if claim.flags.conditional:
        flags_active.append("CONDITIONAL")
    if claim.flags.ambiguous_scope:
        flags_active.append("AMBIGUOUS_SCOPE")

    if flags_active:
        print(f"      Flags: {', '.join(flags_active)}")

    print(f"      Evidence: \"{claim.evidence_text[:80]}...\"" if len(claim.evidence_text) > 80 else f"      Evidence: \"{claim.evidence_text}\"")


async def test_extraction(
    extractor: LLMClaimExtractor,
    text: str,
    concepts: list,
    test_name: str,
):
    """Exécute un test d'extraction."""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}")

    result = await extractor.extract_claims(
        text=text,
        doc_id="test_doc_001",
        chunk_id="chunk_001",
        concepts=concepts,
    )

    print(f"\n📊 Résultats:")
    print(f"   Claims extraits: {len(result.claims)}")
    print(f"   Temps extraction: {result.extraction_time_seconds:.2f}s")
    print(f"   Modèle: {result.model_used}")

    if result.errors:
        print(f"   ⚠️ Erreurs: {result.errors}")

    print(f"\n📋 Claims détectés:")
    for i, claim in enumerate(result.claims, 1):
        print_claim(claim, i)

    # Stats par type
    type_counts = {}
    for claim in result.claims:
        type_counts[claim.claim_type] = type_counts.get(claim.claim_type, 0) + 1

    print(f"\n📈 Répartition par type:")
    for claim_type, count in sorted(type_counts.items()):
        print(f"   {claim_type}: {count}")

    return result


async def test_scope_variants(extractor: LLMClaimExtractor):
    """Test spécifique : détection des variants de scope."""
    print(f"\n{'='*60}")
    print("TEST: Détection Variants (même sujet, scopes différents)")
    print(f"{'='*60}")

    text = """
    SLA S/4HANA Cloud :
    - Édition Standard : 99.7% de disponibilité
    - Édition Enterprise : 99.9% de disponibilité
    - Avec Premium Support : 99.95% de disponibilité
    - Région Chine : 99.5% de disponibilité (infrastructure locale)
    """

    result = await extractor.extract_claims(
        text=text,
        doc_id="test_variants",
        chunk_id="chunk_scope",
        concepts=TEST_CONCEPTS,
    )

    print(f"\n📊 Claims extraits: {len(result.claims)}")

    # Vérifier les scope_keys uniques
    scope_keys = set()
    for claim in result.claims:
        print(f"\n  SLA {claim.value_raw}")
        print(f"    scope_struct: {claim.scope_struct}")
        print(f"    scope_key: {claim.scope_key}")
        scope_keys.add(claim.scope_key)

    print(f"\n✅ Scope keys uniques: {len(scope_keys)}")
    if len(scope_keys) == len(result.claims):
        print("   → Chaque variant a un scope_key distinct (OK)")
    else:
        print("   ⚠️ Certains claims partagent le même scope_key")

    return result


async def main():
    parser = argparse.ArgumentParser(description="Test extraction claims Phase 2.11")
    parser.add_argument("--text", help="Texte personnalisé à analyser")
    parser.add_argument("--model", default="gpt-4o-mini", help="Modèle LLM")
    parser.add_argument("--all", action="store_true", help="Exécuter tous les tests")
    args = parser.parse_args()

    # Init OpenAI client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY non défini")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)

    # Init extractor
    extractor = LLMClaimExtractor(
        llm_client=client,
        model=args.model,
        tenant_id="default",
    )

    print(f"\n🚀 Phase 2.11 - Test Extraction Claims")
    print(f"   Modèle: {args.model}")
    print(f"   Date: {datetime.now().isoformat()}")

    if args.text:
        # Test avec texte personnalisé
        await test_extraction(
            extractor,
            args.text,
            TEST_CONCEPTS,
            "Texte personnalisé",
        )
    elif args.all:
        # Tous les tests
        await test_extraction(
            extractor,
            TEST_TEXT_SLA,
            TEST_CONCEPTS,
            "SLA & Thresholds",
        )
        await test_extraction(
            extractor,
            TEST_TEXT_METRICS,
            TEST_CONCEPTS,
            "Métriques Business (CRR)",
        )
        await test_extraction(
            extractor,
            TEST_TEXT_CERTIFICATION,
            TEST_CONCEPTS,
            "Certifications",
        )
        await test_scope_variants(extractor)
    else:
        # Test par défaut : SLA
        await test_extraction(
            extractor,
            TEST_TEXT_SLA,
            TEST_CONCEPTS,
            "SLA & Thresholds (default)",
        )

    print(f"\n{'='*60}")
    print("✅ Tests terminés")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
