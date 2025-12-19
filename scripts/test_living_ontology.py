#!/usr/bin/env python3
"""
🌊 OSMOSE Phase 2.3 - Test Living Ontology

Script de test pour valider la découverte de patterns
et la gestion dynamique de l'ontologie.

Usage:
    docker-compose exec app python scripts/test_living_ontology.py
"""

import asyncio
import sys
import os
from datetime import datetime

# Ajouter src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.semantic.ontology import (
    PatternDiscoveryService,
    LivingOntologyManager,
    get_pattern_discovery_service,
    get_living_ontology_manager,
)


async def test_pattern_discovery():
    """Test du PatternDiscoveryService."""

    print("=" * 70)
    print("🌊 OSMOSE Living Ontology - Test Pattern Discovery")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Initialiser service
    print("[1/4] Initialisation PatternDiscoveryService...")
    service = get_pattern_discovery_service()

    # Test découverte types entités
    print("\n[2/4] Découverte nouveaux types d'entités...")
    print("-" * 50)

    try:
        entity_patterns = await service.discover_new_entity_types(
            tenant_id="default",
            min_occurrences=5,  # Seuil bas pour test
            max_results=10
        )

        print(f"   Patterns découverts: {len(entity_patterns)}")
        for p in entity_patterns[:5]:
            print(f"   • {p.suggested_name}")
            print(f"     - Type: {p.pattern_type.value}")
            print(f"     - Occurrences: {p.occurrences}")
            print(f"     - Confidence: {p.confidence:.2f}")
            print(f"     - Concepts: {', '.join(p.support_concepts[:3])}")
            print()

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    # Test découverte patterns de relations
    print("\n[3/4] Découverte patterns de relations...")
    print("-" * 50)

    try:
        relation_patterns = await service.discover_relation_patterns(
            tenant_id="default",
            min_occurrences=5
        )

        print(f"   Patterns découverts: {len(relation_patterns)}")
        for p in relation_patterns[:5]:
            print(f"   • {p.suggested_name}")
            print(f"     - Description: {p.description[:60]}...")
            print(f"     - Occurrences: {p.occurrences}")
            print()

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    # Test découverte raffinements de types
    print("\n[4/4] Découverte raffinements de types...")
    print("-" * 50)

    try:
        refinements = await service.discover_type_refinements(
            tenant_id="default",
            base_type="entity"
        )

        print(f"   Raffinements découverts: {len(refinements)}")
        for p in refinements[:5]:
            print(f"   • {p.suggested_name} (parent: {p.parent_type})")
            print(f"     - Confidence: {p.confidence:.2f}")
            print()

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    print("\n" + "=" * 70)
    print("✅ Test Pattern Discovery terminé!")
    print("=" * 70)


async def test_living_ontology_manager():
    """Test du LivingOntologyManager."""

    print("\n" + "=" * 70)
    print("🌊 OSMOSE Living Ontology - Test Manager")
    print("=" * 70)
    print()

    # Initialiser manager
    print("[1/3] Initialisation LivingOntologyManager...")
    manager = get_living_ontology_manager()

    # Test statistiques
    print("\n[2/3] Récupération statistiques ontologie...")
    print("-" * 50)

    try:
        stats = await manager.get_ontology_stats(tenant_id="default")

        print(f"   Total concepts: {stats['total_concepts']}")
        print(f"   Types uniques: {stats['unique_types']}")
        print(f"   Propositions pending: {stats['pending_proposals']}")
        print(f"   Changements totaux: {stats['total_changes']}")
        print(f"   Seuil auto-promote: {stats['auto_promote_threshold']}")
        print()
        print("   Distribution par type:")
        for type_name, count in list(stats['type_distribution'].items())[:10]:
            print(f"     • {type_name}: {count}")

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    # Test cycle de découverte
    print("\n[3/3] Exécution cycle de découverte...")
    print("-" * 50)

    try:
        results = await manager.run_discovery_cycle(
            tenant_id="default",
            auto_promote=False  # Pas d'auto-promotion pour test
        )

        print(f"   Patterns découverts: {results['patterns_discovered']}")
        print(f"   Propositions créées: {results['proposals_created']}")
        print(f"   Auto-promus: {results['auto_promoted']}")
        print(f"   Rejetés: {results['rejected']}")

        if results['pending_review']:
            print("\n   Propositions en attente de review:")
            for proposal in results['pending_review'][:3]:
                print(f"   • {proposal['type_name']}")
                print(f"     - Confidence: {proposal['confidence']:.2f}")
                print(f"     - Occurrences: {proposal['occurrences']}")

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    print("\n" + "=" * 70)
    print("✅ Test Living Ontology Manager terminé!")
    print("=" * 70)


async def test_full_discovery():
    """Test découverte complète."""

    print("\n" + "=" * 70)
    print("🌊 OSMOSE Living Ontology - Full Discovery Test")
    print("=" * 70)
    print()

    service = get_pattern_discovery_service()

    print("Exécution découverte complète...")

    try:
        results = await service.run_full_discovery(tenant_id="default")

        print(f"\n📊 Résultats:")
        print(f"   • Nouveaux types: {len(results['new_entity_types'])}")
        print(f"   • Patterns relations: {len(results['relation_patterns'])}")
        print(f"   • Raffinements types: {len(results['type_refinements'])}")

        total = sum(len(v) for v in results.values())
        print(f"\n   Total patterns: {total}")

    except Exception as e:
        print(f"   ❌ Erreur: {e}")

    print("\n" + "=" * 70)
    print("✅ Full Discovery terminé!")
    print("=" * 70)


if __name__ == "__main__":
    print("\n" + "🌊" * 35)
    print("  OSMOSE Phase 2.3 - Living Ontology Tests")
    print("🌊" * 35 + "\n")

    asyncio.run(test_pattern_discovery())
    asyncio.run(test_living_ontology_manager())
    asyncio.run(test_full_discovery())

    print("\n" + "=" * 70)
    print("🎉 Tous les tests Living Ontology terminés!")
    print("=" * 70)
    print("\nEndpoints disponibles:")
    print("  GET  /api/living-ontology/stats")
    print("  GET  /api/living-ontology/types")
    print("  GET  /api/living-ontology/patterns")
    print("  POST /api/living-ontology/discover")
    print("  GET  /api/living-ontology/proposals")
    print("  POST /api/living-ontology/proposals/{id}/approve")
    print("  POST /api/living-ontology/proposals/{id}/reject")
    print("  GET  /api/living-ontology/history")
    print()
