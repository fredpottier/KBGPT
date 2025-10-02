#!/usr/bin/env python3
"""
Script CLI Migration Qdrant → Graphiti - Phase 1 Critère 1.5

Migre chunks Qdrant existants (sans knowledge graph) vers Graphiti.

Usage:
    # Dry-run (simulation)
    python scripts/migrate_qdrant_to_graphiti.py --tenant acme_corp --dry-run

    # Migration réelle
    python scripts/migrate_qdrant_to_graphiti.py --tenant acme_corp

    # Avec extraction entities LLM
    python scripts/migrate_qdrant_to_graphiti.py --tenant acme_corp --extract-entities

    # Analyser besoins migration
    python scripts/migrate_qdrant_to_graphiti.py --tenant acme_corp --analyze-only
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Ajouter src/ au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.migration.qdrant_graphiti_migration import (
    migrate_tenant,
    analyze_migration_needs
)


async def main():
    """Point d'entrée CLI"""
    parser = argparse.ArgumentParser(
        description="Migration chunks Qdrant → Graphiti",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Dry-run pour analyser impact
  %(prog)s --tenant acme_corp --dry-run

  # Migration réelle sans extraction entities
  %(prog)s --tenant acme_corp

  # Migration complète avec extraction LLM
  %(prog)s --tenant acme_corp --extract-entities

  # Analyser seulement (pas de migration)
  %(prog)s --tenant acme_corp --analyze-only
        """
    )

    parser.add_argument(
        "--tenant",
        required=True,
        help="ID tenant à migrer (ex: acme_corp)"
    )

    parser.add_argument(
        "--collection",
        default="knowbase",
        help="Collection Qdrant (défaut: knowbase)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulation sans modification (recommandé pour premier test)"
    )

    parser.add_argument(
        "--extract-entities",
        action="store_true",
        help="Extraire entities/relations via LLM (coûteux, désactivé par défaut)"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite nombre chunks à traiter (None = tous)"
    )

    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Analyser besoins migration sans migrer"
    )

    args = parser.parse_args()

    # Validation
    if not args.tenant:
        parser.error("--tenant est obligatoire")

    print("\n" + "="*70)
    print("MIGRATION QDRANT → GRAPHITI")
    print("="*70)
    print(f"\nTenant: {args.tenant}")
    print(f"Collection: {args.collection}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'PRODUCTION'}")
    print(f"Extraction entities: {'OUI' if args.extract_entities else 'NON'}")
    if args.limit:
        print(f"Limite: {args.limit} chunks")

    # Mode analyse uniquement
    if args.analyze_only:
        print("\n📊 Mode ANALYSE uniquement...\n")
        analysis = await analyze_migration_needs(
            tenant_id=args.tenant,
            collection_name=args.collection
        )

        print("\n" + "="*70)
        print("RAPPORT ANALYSE")
        print("="*70)
        print(f"\n📦 Chunks Qdrant:")
        print(f"   - Total: {analysis['chunks_total']}")
        print(f"   - Avec KG: {analysis['chunks_with_kg']}")
        print(f"   - Sans KG: {analysis['chunks_without_kg']}")
        print(f"\n📁 Sources: {analysis['sources_count']}")
        print(f"\n📝 Top 10 sources:")
        for source_info in analysis['top_sources']:
            print(f"   - {source_info['filename']}: {source_info['chunks_count']} chunks")

        if analysis['migration_recommended']:
            print(f"\n✅ Migration recommandée: {analysis['chunks_without_kg']} chunks à traiter")
        else:
            print(f"\n✅ Aucune migration nécessaire (tous chunks ont déjà un KG)")

        print("="*70 + "\n")
        return

    # Confirmation avant migration réelle
    if not args.dry_run:
        print("\n⚠️  ATTENTION: Mode PRODUCTION - Les données seront modifiées!")
        confirmation = input("Taper 'OUI' pour confirmer: ")
        if confirmation != "OUI":
            print("Migration annulée.")
            return

    # Exécution migration
    print("\n🚀 Démarrage migration...\n")

    try:
        stats = await migrate_tenant(
            tenant_id=args.tenant,
            collection_name=args.collection,
            dry_run=args.dry_run,
            extract_entities=args.extract_entities,
            limit=args.limit
        )

        # Afficher rapport détaillé
        stats.print_report()

        # Code retour selon résultats
        if stats.errors > 0:
            print(f"⚠️  Migration terminée avec {stats.errors} erreur(s)")
            sys.exit(1)
        else:
            print(f"✅ Migration réussie!")
            sys.exit(0)

    except Exception as e:
        print(f"\n❌ ERREUR MIGRATION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())