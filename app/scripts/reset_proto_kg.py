"""
🌊 OSMOSE - Reset Proto-KG

Script pour purger et réinitialiser complètement le Proto-KG OSMOSE.

Usage:
    # Reset complet (purge + reinit)
    docker-compose exec app python scripts/reset_proto_kg.py

    # Purge seulement les données (garde le schéma)
    docker-compose exec app python scripts/reset_proto_kg.py --data-only

    # Reset complet incluant les constraints/indexes
    docker-compose exec app python scripts/reset_proto_kg.py --full

Options:
    --data-only    Supprime uniquement les données (CandidateEntity/Relation)
    --full         Supprime également les constraints et indexes Neo4j
    --skip-reinit  Ne réinitialise pas après purge (purge seulement)
"""

import asyncio
import argparse
import sys
import os
from neo4j import AsyncGraphDatabase
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.semantic.setup_infrastructure import setup_all


async def purge_neo4j_data():
    """Purge tous les nodes CandidateEntity/CandidateRelation"""
    print("🗑️  Purge données Neo4j Proto-KG...")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        async with driver.session() as session:
            # Compter avant suppression
            count_result = await session.run("""
                MATCH (n)
                WHERE n:CandidateEntity OR n:CandidateRelation
                RETURN count(n) as total
            """)
            count_record = await count_result.single()
            total = count_record["total"] if count_record else 0

            if total > 0:
                # Supprimer
                await session.run("""
                    MATCH (n)
                    WHERE n:CandidateEntity OR n:CandidateRelation
                    DETACH DELETE n
                """)
                print(f"   ✅ {total} nodes supprimés (CandidateEntity/CandidateRelation)")
            else:
                print("   ℹ️  Aucune donnée à supprimer")

    except Exception as e:
        print(f"   ❌ Erreur purge Neo4j: {e}")
        raise
    finally:
        await driver.close()


async def purge_neo4j_full():
    """Purge données + constraints + indexes Neo4j Proto-KG"""
    print("🗑️  Purge COMPLÈTE Neo4j Proto-KG (données + schéma)...")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        async with driver.session() as session:
            # 1. Supprimer données
            await session.run("""
                MATCH (n)
                WHERE n:CandidateEntity OR n:CandidateRelation
                DETACH DELETE n
            """)
            print("   ✅ Données supprimées")

            # 2. Supprimer constraints
            constraints_to_drop = [
                "candidate_entity_id",
                "candidate_relation_id"
            ]

            for constraint_name in constraints_to_drop:
                try:
                    await session.run(f"DROP CONSTRAINT {constraint_name} IF EXISTS")
                    print(f"   ✅ Constraint {constraint_name} supprimée")
                except Exception as e:
                    print(f"   ⚠️  Constraint {constraint_name}: {e}")

            # 3. Supprimer indexes
            indexes_to_drop = [
                "candidate_entity_tenant",
                "candidate_entity_status",
                "candidate_relation_tenant",
                "candidate_relation_status"
            ]

            for index_name in indexes_to_drop:
                try:
                    await session.run(f"DROP INDEX {index_name} IF EXISTS")
                    print(f"   ✅ Index {index_name} supprimé")
                except Exception as e:
                    print(f"   ⚠️  Index {index_name}: {e}")

    except Exception as e:
        print(f"   ❌ Erreur purge complète Neo4j: {e}")
        raise
    finally:
        await driver.close()


def purge_qdrant():
    """Supprime la collection knowwhere_proto"""
    print("🗑️  Purge collection Qdrant...")

    try:
        client = get_qdrant_client()

        # Vérifier si la collection existe
        collections = client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if 'knowwhere_proto' in collection_names:
            client.delete_collection('knowwhere_proto')
            print("   ✅ Collection 'knowwhere_proto' supprimée")
        else:
            print("   ℹ️  Collection 'knowwhere_proto' n'existe pas")

    except Exception as e:
        print(f"   ❌ Erreur purge Qdrant: {e}")
        raise


async def main():
    parser = argparse.ArgumentParser(
        description="🌊 OSMOSE - Reset Proto-KG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python scripts/reset_proto_kg.py                # Reset complet (recommandé)
  python scripts/reset_proto_kg.py --data-only    # Purge données seulement
  python scripts/reset_proto_kg.py --full         # Purge tout + schéma
  python scripts/reset_proto_kg.py --skip-reinit  # Purge sans réinit
        """
    )

    parser.add_argument(
        '--data-only',
        action='store_true',
        help='Supprime uniquement les données (garde constraints/indexes)'
    )

    parser.add_argument(
        '--full',
        action='store_true',
        help='Supprime données + constraints + indexes Neo4j'
    )

    parser.add_argument(
        '--skip-reinit',
        action='store_true',
        help='Ne pas réinitialiser après purge (purge seulement)'
    )

    args = parser.parse_args()

    # Validation
    if args.data_only and args.full:
        print("❌ Erreur: --data-only et --full sont incompatibles")
        sys.exit(1)

    print("=" * 70)
    print("🌊 OSMOSE Proto-KG - Reset")
    print("=" * 70)
    print()

    try:
        # Phase 1: Purge
        if args.full:
            print("📋 Mode: PURGE COMPLÈTE (données + schéma)")
            print()
            await purge_neo4j_full()
        else:
            print("📋 Mode: PURGE DONNÉES")
            print()
            await purge_neo4j_data()

        purge_qdrant()
        print()

        # Phase 2: Réinitialisation
        if not args.skip_reinit:
            print("🔧 Réinitialisation infrastructure...")
            print()
            await setup_all()
        else:
            print("⏭️  Réinitialisation skippée (--skip-reinit)")

        print()
        print("=" * 70)
        print("✅ Proto-KG réinitialisé avec succès !")
        print("=" * 70)

    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ ERREUR: {e}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
