#!/usr/bin/env python3
"""
🌊 OSMOSE Phase 2.7 - Test Concept Matching Engine (Palier 1 + 2)

Script de test pour valider le matching multilingue avec fusion RRF.

Usage:
    docker exec knowbase-app python /app/scripts/test_concept_matching_p2.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.api.services.graph_guided_search import GraphGuidedSearchService


# Golden Set Phase 2.7
GOLDEN_SET = [
    {
        "query": "Comment l'intelligence artificielle change la cybersécurité ?",
        "expected": ["AI", "Artificial Intelligence", "Cybersecurity", "Cyber"],
        "desc": "FR→EN: ia→AI, cybersécurité→Cybersecurity"
    },
    {
        "query": "Quels sont les risques des systèmes à haut risque selon NIS2 ?",
        "expected": ["NIS2", "High-Risk", "Risk"],
        "desc": "NIS2 + High-Risk AI System"
    },
    {
        "query": "Comment gérer un incident ransomware et le reporting ?",
        "expected": ["Ransomware", "Incident", "GDPR", "Reporting"],
        "desc": "Ransomware + Incident Management + GDPR"
    },
    {
        "query": "Quelles sont les obligations de conformité AI Act ?",
        "expected": ["AI Act", "Compliance", "High-Risk"],
        "desc": "AI Act + Compliance"
    },
    {
        "query": "Quel est le lien entre RGPD et protection des données dans l'IA ?",
        "expected": ["GDPR", "Data Protection", "AI", "Privacy"],
        "desc": "FR→EN: RGPD→GDPR"
    },
]


async def test_golden_set():
    """Test du golden set avec Palier 1 + 2 (fusion RRF)."""

    print("=" * 70)
    print("🌊 OSMOSE Phase 2.7 - Test Concept Matching (Palier 1 + 2)")
    print("=" * 70)
    print()

    service = GraphGuidedSearchService()

    total_score = 0
    max_score = 0

    for i, test in enumerate(GOLDEN_SET, 1):
        print(f"\n[{i}/5] {test['desc']}")
        print(f"    Query: {test['query']}")
        print("-" * 60)

        # Test avec Palier 1 + 2 (use_semantic=True)
        concepts = await service.extract_concepts_from_query(
            query=test['query'],
            tenant_id="default",
            top_k=10,
            use_semantic=True  # Activer Palier 2
        )

        print(f"    Concepts trouvés: {concepts}")
        print(f"    Expected (partiel): {test['expected']}")

        # Compter les matches
        found = []
        for exp in test['expected']:
            for c in concepts:
                if exp.lower() in c.lower():
                    found.append(exp)
                    break

        score = len(found)
        max_expected = len(test['expected'])
        total_score += score
        max_score += max_expected

        status = "✅" if score >= max_expected * 0.6 else "⚠️" if score >= 1 else "❌"
        print(f"    {status} Score: {score}/{max_expected} ({found})")

    # Résumé
    print("\n" + "=" * 70)
    print(f"📊 RÉSULTAT GLOBAL: {total_score}/{max_score} ({100*total_score/max_score:.0f}%)")
    print("=" * 70)

    # Comparaison avec Palier 1 seul
    print("\n📈 Comparaison Palier 1 seul vs Palier 1+2:")
    print("-" * 60)

    for test in GOLDEN_SET[:2]:  # Juste 2 exemples
        # Palier 1 seul
        concepts_lex = await service.extract_concepts_from_query(
            query=test['query'],
            tenant_id="default",
            use_semantic=False
        )

        # Palier 1 + 2
        concepts_both = await service.extract_concepts_from_query(
            query=test['query'],
            tenant_id="default",
            use_semantic=True
        )

        print(f"\n    Query: {test['query'][:50]}...")
        print(f"    Palier 1 seul:  {concepts_lex[:5]}")
        print(f"    Palier 1 + 2:   {concepts_both[:5]}")


if __name__ == "__main__":
    asyncio.run(test_golden_set())
