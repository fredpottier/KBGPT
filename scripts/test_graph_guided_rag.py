#!/usr/bin/env python3
"""
🌊 OSMOSE - Test Graph-Guided RAG

Script de test pour valider l'intégration du Graph-Guided RAG
dans le endpoint /search.

Usage:
    docker-compose exec app python scripts/test_graph_guided_rag.py
"""

import asyncio
import sys
import os
from datetime import datetime

# Ajouter src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.api.services.graph_guided_search import (
    GraphGuidedSearchService,
    EnrichmentLevel,
)


async def test_graph_context():
    """Test du service GraphGuidedSearch."""

    print("=" * 70)
    print("🌊 OSMOSE Graph-Guided RAG - Test Service")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Initialiser le service
    print("[1/5] Initialisation GraphGuidedSearchService...")
    service = GraphGuidedSearchService()

    # Test queries
    test_queries = [
        "Quels sont les effets du Remdesivir sur les patients COVID-19 ?",
        "Comment fonctionne le traitement par ventilation mécanique ?",
        "Quels sont les facteurs de risque pour les patients hospitalisés ?",
    ]

    for i, query in enumerate(test_queries, 2):
        print(f"\n[{i}/5] Test query: \"{query[:50]}...\"")
        print("-" * 50)

        # Test LIGHT
        print("   → Niveau LIGHT...")
        context_light = await service.build_graph_context(
            query=query,
            tenant_id="default",
            enrichment_level=EnrichmentLevel.LIGHT
        )
        print(f"      Query concepts: {context_light.query_concepts}")
        print(f"      Related concepts: {len(context_light.related_concepts)}")
        print(f"      Time: {context_light.processing_time_ms:.1f}ms")

        # Test STANDARD
        print("   → Niveau STANDARD...")
        context_std = await service.build_graph_context(
            query=query,
            tenant_id="default",
            enrichment_level=EnrichmentLevel.STANDARD
        )
        print(f"      Query concepts: {context_std.query_concepts}")
        print(f"      Related concepts: {len(context_std.related_concepts)}")
        print(f"      Transitive relations: {len(context_std.transitive_relations)}")
        print(f"      Time: {context_std.processing_time_ms:.1f}ms")

        # Test DEEP
        print("   → Niveau DEEP...")
        context_deep = await service.build_graph_context(
            query=query,
            tenant_id="default",
            enrichment_level=EnrichmentLevel.DEEP
        )
        print(f"      Query concepts: {context_deep.query_concepts}")
        print(f"      Related concepts: {len(context_deep.related_concepts)}")
        print(f"      Transitive relations: {len(context_deep.transitive_relations)}")
        print(f"      Thematic cluster: {context_deep.thematic_cluster is not None}")
        print(f"      Bridge concepts: {context_deep.bridge_concepts}")
        print(f"      Time: {context_deep.processing_time_ms:.1f}ms")

        # Afficher le contexte formaté
        formatted = service.format_context_for_synthesis(context_deep)
        if formatted:
            print("\n   📝 Contexte formaté (extrait):")
            lines = formatted.split("\n")[:15]
            for line in lines:
                print(f"      {line}")
            if len(formatted.split("\n")) > 15:
                print("      ...")

    print("\n" + "=" * 70)
    print("✅ Test Graph-Guided RAG terminé!")
    print("=" * 70)


async def test_expansion_terms():
    """Test des termes d'expansion pour query expansion."""

    print("\n" + "=" * 70)
    print("🔍 Test Query Expansion Terms")
    print("=" * 70)

    service = GraphGuidedSearchService()

    query = "COVID-19 treatment outcomes"

    context = await service.build_graph_context(
        query=query,
        tenant_id="default",
        enrichment_level=EnrichmentLevel.DEEP
    )

    expansion_terms = context.get_expansion_terms()

    print(f"\nQuery: \"{query}\"")
    print(f"Query concepts: {context.query_concepts}")
    print(f"\nExpansion terms ({len(expansion_terms)}):")
    for term in expansion_terms:
        print(f"   • {term}")

    print("\n✅ Test expansion terminé!")


if __name__ == "__main__":
    asyncio.run(test_graph_context())
    asyncio.run(test_expansion_terms())
