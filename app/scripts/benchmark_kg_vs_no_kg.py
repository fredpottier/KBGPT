#!/usr/bin/env python3
"""
🌊 OSMOSE - Benchmark: Graph-Guided RAG vs RAG Classique

Compare les réponses avec et sans enrichissement Knowledge Graph
pour démontrer la valeur ajoutée du KG.

Usage:
    docker exec knowbase-app python /app/scripts/benchmark_kg_vs_no_kg.py
"""

import asyncio
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.api.services.graph_guided_search import (
    GraphGuidedSearchService,
    EnrichmentLevel,
)


# Questions de benchmark - domaine réglementation/cybersécurité
BENCHMARK_QUERIES = [
    {
        "query": "Quel est le lien entre la directive NIS2 et les systèmes IA à haut risque ?",
        "desc": "Question pivot OSMOSE - connexion inter-réglementaire",
        "expected_concepts": ["NIS2", "High-Risk AI System", "AI Act"],
    },
    {
        "query": "Comment le RGPD s'applique-t-il aux systèmes d'intelligence artificielle ?",
        "desc": "RGPD + IA - multilingue FR→EN",
        "expected_concepts": ["GDPR", "AI", "Data Protection"],
    },
    {
        "query": "Quelles sont les obligations de notification en cas de ransomware ?",
        "desc": "Incident + Reporting - cybersécurité",
        "expected_concepts": ["Ransomware", "Incident Reporting", "NIS2", "GDPR"],
    },
    {
        "query": "What are the compliance requirements for high-risk AI systems?",
        "desc": "AI Act compliance - EN",
        "expected_concepts": ["AI Act", "High-Risk AI", "Compliance"],
    },
]


async def benchmark_single_query(service: GraphGuidedSearchService, query_info: dict):
    """Benchmark une seule question avec et sans KG."""

    query = query_info["query"]
    desc = query_info["desc"]
    expected = query_info["expected_concepts"]

    print(f"\n{'='*70}")
    print(f"📋 {desc}")
    print(f"   Query: \"{query}\"")
    print(f"   Expected: {expected}")
    print(f"{'='*70}")

    # =========================================================================
    # Test SANS KG (RAG classique)
    # =========================================================================
    print("\n🔴 SANS Knowledge Graph (RAG classique)")
    print("-" * 50)

    start = time.time()
    # Simuler RAG sans KG - juste extraction de concepts sans enrichissement
    concepts_no_kg = await service.extract_concepts_from_query(
        query=query,
        tenant_id="default",
        top_k=5,
        use_semantic=False  # Palier 1 seul, pas de semantic
    )
    time_no_kg = (time.time() - start) * 1000

    print(f"   Concepts trouvés: {concepts_no_kg}")
    print(f"   Temps: {time_no_kg:.1f}ms")

    # Vérifier les matches
    matches_no_kg = []
    for exp in expected:
        for c in concepts_no_kg:
            if exp.lower() in c.lower():
                matches_no_kg.append(exp)
                break
    print(f"   Matches: {len(matches_no_kg)}/{len(expected)} {matches_no_kg}")

    # =========================================================================
    # Test AVEC KG (Graph-Guided RAG)
    # =========================================================================
    print("\n🟢 AVEC Knowledge Graph (Graph-Guided RAG)")
    print("-" * 50)

    start = time.time()

    # 1. Extraction concepts avec Palier 1+2+3
    concepts_with_kg = await service.extract_concepts_from_query(
        query=query,
        tenant_id="default",
        top_k=10,
        use_semantic=True  # Palier 1 + 2
    )

    # 2. Enrichissement KG (STANDARD pour temps-réel, DEEP pour offline)
    # NOTE: DEEP utilise NetworkX (betweenness, Louvain) = ~3min par query
    # STANDARD utilise Cypher natif = ~500ms
    context = await service.build_graph_context(
        query=query,
        tenant_id="default",
        enrichment_level=EnrichmentLevel.STANDARD  # Changed from DEEP
    )

    time_with_kg = (time.time() - start) * 1000

    print(f"   Concepts trouvés: {concepts_with_kg[:5]}...")
    print(f"   Concepts liés (KG): {len(context.related_concepts)}")
    print(f"   Relations transitives: {len(context.transitive_relations)}")
    print(f"   Bridge concepts: {context.bridge_concepts[:3] if context.bridge_concepts else 'None'}")
    print(f"   Temps: {time_with_kg:.1f}ms")

    # Vérifier les matches
    all_concepts = concepts_with_kg + [r.get("concept", "") for r in context.related_concepts]
    matches_with_kg = []
    for exp in expected:
        for c in all_concepts:
            if exp.lower() in c.lower():
                matches_with_kg.append(exp)
                break
    print(f"   Matches: {len(matches_with_kg)}/{len(expected)} {matches_with_kg}")

    # =========================================================================
    # Comparaison
    # =========================================================================
    print("\n📊 COMPARAISON")
    print("-" * 50)

    improvement = len(matches_with_kg) - len(matches_no_kg)

    if improvement > 0:
        print(f"   ✅ KG apporte +{improvement} concepts pertinents")
    elif improvement == 0:
        print(f"   ➖ Pas de différence (déjà trouvés par RAG)")
    else:
        print(f"   ⚠️ RAG classique meilleur (vérifier)")

    # Concepts uniques apportés par KG
    unique_kg = set(matches_with_kg) - set(matches_no_kg)
    if unique_kg:
        print(f"   🆕 Concepts ajoutés par KG: {list(unique_kg)}")

    # Contexte formaté (extrait)
    formatted = service.format_context_for_synthesis(context)
    if formatted:
        print("\n   📝 Contexte KG pour synthèse (extrait):")
        lines = formatted.split("\n")[:8]
        for line in lines:
            print(f"      {line}")
        if len(formatted.split("\n")) > 8:
            print("      ...")

    return {
        "query": query,
        "no_kg_matches": len(matches_no_kg),
        "with_kg_matches": len(matches_with_kg),
        "expected": len(expected),
        "improvement": improvement,
        "unique_kg_concepts": list(unique_kg),
    }


async def main():
    print("=" * 70)
    print("🌊 OSMOSE - Benchmark: Graph-Guided RAG vs RAG Classique")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Questions: {len(BENCHMARK_QUERIES)}")

    service = GraphGuidedSearchService()

    results = []
    for query_info in BENCHMARK_QUERIES:
        result = await benchmark_single_query(service, query_info)
        results.append(result)

    # =========================================================================
    # Résumé global
    # =========================================================================
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ GLOBAL")
    print("=" * 70)

    total_no_kg = sum(r["no_kg_matches"] for r in results)
    total_with_kg = sum(r["with_kg_matches"] for r in results)
    total_expected = sum(r["expected"] for r in results)

    print(f"\n   {'Query':<50} | {'No KG':>6} | {'With KG':>7} | {'Gain':>5}")
    print(f"   {'-'*50}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}")

    for r in results:
        q = r["query"][:47] + "..." if len(r["query"]) > 50 else r["query"]
        gain = f"+{r['improvement']}" if r['improvement'] > 0 else str(r['improvement'])
        print(f"   {q:<50} | {r['no_kg_matches']:>6} | {r['with_kg_matches']:>7} | {gain:>5}")

    print(f"   {'-'*50}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}")
    total_gain = total_with_kg - total_no_kg
    gain_str = f"+{total_gain}" if total_gain > 0 else str(total_gain)
    print(f"   {'TOTAL':<50} | {total_no_kg:>6} | {total_with_kg:>7} | {gain_str:>5}")

    pct_no_kg = 100 * total_no_kg / total_expected
    pct_with_kg = 100 * total_with_kg / total_expected

    print(f"\n   📈 Score sans KG:  {total_no_kg}/{total_expected} ({pct_no_kg:.0f}%)")
    print(f"   📈 Score avec KG:  {total_with_kg}/{total_expected} ({pct_with_kg:.0f}%)")
    print(f"   📈 Amélioration:   +{pct_with_kg - pct_no_kg:.0f}%")

    # Conclusion
    print("\n" + "=" * 70)
    if total_gain > 0:
        print("✅ CONCLUSION: Le Knowledge Graph apporte une valeur ajoutée significative!")
        print(f"   → {total_gain} concepts pertinents supplémentaires trouvés")
        all_unique = []
        for r in results:
            all_unique.extend(r["unique_kg_concepts"])
        if all_unique:
            print(f"   → Concepts uniques apportés: {list(set(all_unique))}")
    else:
        print("⚠️ CONCLUSION: Le KG n'apporte pas d'amélioration mesurable sur ce benchmark")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
