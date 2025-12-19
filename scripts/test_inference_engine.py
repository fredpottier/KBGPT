#!/usr/bin/env python3
"""
🌊 OSMOSE - Test InferenceEngine sur KG existant

Script de test pour valider l'InferenceEngine sur les données
du KG (10 études médicales COVID-19).

Usage:
    docker-compose exec app python scripts/test_inference_engine.py
"""

import asyncio
import sys
import os
from datetime import datetime

# Ajouter src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.semantic.inference import InferenceEngine, InsightType


async def main():
    """Test principal de l'InferenceEngine."""

    print("=" * 70)
    print("🌊 OSMOSE InferenceEngine - Test sur KG existant")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Initialiser l'engine
    print("[1/6] Initialisation InferenceEngine...")
    engine = InferenceEngine()

    # Récupérer stats du graphe
    print("[2/6] Récupération statistiques du graphe...")
    stats = await engine.get_inference_stats(tenant_id="default")
    print(f"   └─ Nœuds: {stats['graph_stats']['nodes']}")
    print(f"   └─ Relations: {stats['graph_stats']['edges']}")
    print(f"   └─ Densité: {stats['graph_stats']['density']:.4f}")
    print(f"   └─ NetworkX disponible: {stats['networkx_available']}")
    print()

    if stats['graph_stats']['nodes'] == 0:
        print("❌ ERREUR: Le graphe est vide. Veuillez d'abord ingérer des documents.")
        return

    # Test 1: Relations Transitives
    print("[3/6] Découverte Relations Transitives (Cypher natif)...")
    transitive = await engine.discover_transitive_relations(
        tenant_id="default",
        max_results=10
    )
    print(f"   └─ {len(transitive)} relations transitives découvertes")
    for i, insight in enumerate(transitive[:3], 1):
        print(f"      {i}. {insight.title}")
        print(f"         → {insight.description}")
        print(f"         → Confidence: {insight.confidence:.2f}")
    print()

    # Test 2: Bridge Concepts
    print("[4/6] Découverte Bridge Concepts (Betweenness Centrality)...")
    bridges = await engine.discover_bridge_concepts(
        tenant_id="default",
        min_betweenness=0.05,
        max_results=10
    )
    print(f"   └─ {len(bridges)} concepts ponts découverts")
    for i, insight in enumerate(bridges[:3], 1):
        print(f"      {i}. {insight.title}")
        print(f"         → {insight.description}")
    print()

    # Test 3: Hidden Clusters
    print("[5/6] Découverte Hidden Clusters (Louvain Community)...")
    clusters = await engine.discover_hidden_clusters(
        tenant_id="default",
        max_results=5
    )
    print(f"   └─ {len(clusters)} clusters thématiques découverts")
    for i, insight in enumerate(clusters[:3], 1):
        print(f"      {i}. {insight.title}")
        print(f"         → {len(insight.concepts_involved)} concepts")
        print(f"         → Confidence (modularité): {insight.confidence:.3f}")
    print()

    # Test 4: Weak Signals
    print("[6/6] Découverte Weak Signals (PageRank + Frequency)...")
    weak_signals = await engine.discover_weak_signals(
        tenant_id="default",
        max_results=10
    )
    print(f"   └─ {len(weak_signals)} signaux faibles découverts")
    for i, insight in enumerate(weak_signals[:3], 1):
        print(f"      {i}. {insight.title}")
        print(f"         → {insight.description}")
    print()

    # Résumé
    print("=" * 70)
    print("📊 RÉSUMÉ DES DÉCOUVERTES")
    print("=" * 70)
    total_insights = len(transitive) + len(bridges) + len(clusters) + len(weak_signals)
    print(f"   Total insights: {total_insights}")
    print(f"   ├─ Relations Transitives: {len(transitive)}")
    print(f"   ├─ Bridge Concepts: {len(bridges)}")
    print(f"   ├─ Hidden Clusters: {len(clusters)}")
    print(f"   └─ Weak Signals: {len(weak_signals)}")
    print()

    # Test discover_all_insights
    print("🔍 Test discover_all_insights (tous types)...")
    all_insights = await engine.discover_all_insights(
        tenant_id="default",
        max_insights_per_type=5
    )
    print(f"   └─ Total via discover_all: {len(all_insights)} insights")
    print()

    # Top 5 insights par importance
    print("🏆 TOP 5 INSIGHTS (par importance):")
    print("-" * 50)
    for i, insight in enumerate(all_insights[:5], 1):
        print(f"{i}. [{insight.insight_type.value.upper()}] {insight.title}")
        print(f"   Importance: {insight.importance:.3f} | Confidence: {insight.confidence:.3f}")
        print(f"   {insight.description[:100]}...")
        print()

    print("✅ Test InferenceEngine terminé avec succès!")


if __name__ == "__main__":
    asyncio.run(main())
