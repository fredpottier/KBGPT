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
import redis
from neo4j import AsyncGraphDatabase
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.semantic.setup_infrastructure import setup_all


async def purge_neo4j_data():
    """Purge toutes les données Neo4j (domain agnostic - pas d'ontologie pré-chargée)"""
    print("🗑️  Purge données Neo4j Proto-KG...")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # Labels à purger (TOUS - OSMOSE est domain agnostic)
    osmose_labels = [
        "CandidateEntity",
        "CandidateRelation",
        "CanonicalConcept",
        "ProtoConcept",
        "AdaptiveOntology",
        "DomainContextProfile",
        "Concept",
        "Document",
        "OntologyAlias",
        "OntologyEntity",
        "Topic",
    ]

    try:
        async with driver.session() as session:
            total_deleted = 0

            for label in osmose_labels:
                # Compter avant suppression
                count_result = await session.run(f"""
                    MATCH (n:{label})
                    RETURN count(n) as total
                """)
                count_record = await count_result.single()
                count = count_record["total"] if count_record else 0

                if count > 0:
                    await session.run(f"""
                        MATCH (n:{label})
                        DETACH DELETE n
                    """)
                    print(f"   ✅ {count} nodes {label} supprimés")
                    total_deleted += count
                else:
                    print(f"   ℹ️  Aucun {label} à supprimer")

            if total_deleted == 0:
                print("   ℹ️  Aucune donnée OSMOSE à supprimer")

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

    # Labels OSMOSE à purger (tous les types de nodes)
    osmose_labels = [
        "CandidateEntity",
        "CandidateRelation",
        "CanonicalConcept",
        "ProtoConcept",
        "AdaptiveOntology",
        "DomainContextProfile",
        "Concept",
        "Document",
        "OntologyAlias",
        "OntologyEntity",
        "Topic",
    ]

    try:
        async with driver.session() as session:
            # 1. Supprimer données
            total_deleted = 0
            for label in osmose_labels:
                # Compter avant suppression
                count_result = await session.run(f"""
                    MATCH (n:{label})
                    RETURN count(n) as total
                """)
                count_record = await count_result.single()
                count = count_record["total"] if count_record else 0

                if count > 0:
                    await session.run(f"""
                        MATCH (n:{label})
                        DETACH DELETE n
                    """)
                    print(f"   ✅ {count} nodes {label} supprimés")
                    total_deleted += count

            print(f"   ✅ Total: {total_deleted} nodes supprimés")

            # 2. Supprimer constraints
            constraints_to_drop = [
                "candidate_entity_id",
                "candidate_relation_id",
                "canonical_concept_id",
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
                "candidate_relation_status",
                "canonical_concept_tenant",
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


def purge_redis():
    """Purge toutes les queues et données Redis (DB 0 et DB 1)"""
    print("🗑️  Purge Redis (queues + historique imports)...")

    # Dans Docker, le host est "redis" (nom du service)
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    # DB 0 = Jobs RQ (queues)
    # DB 1 = Historique imports
    databases = [
        (0, "jobs/queues"),
        (1, "historique imports"),
    ]

    try:
        for db_num, db_name in databases:
            client = redis.Redis(host=redis_host, port=redis_port, db=db_num, decode_responses=True)

            # Lister les clés avant purge
            keys = client.keys("*")
            key_count = len(keys)

            if key_count > 0:
                # Afficher quelques clés pour info
                sample_keys = keys[:5]
                print(f"   📋 DB {db_num} ({db_name}): {key_count} clés (ex: {sample_keys})")

                # Purger la base
                client.flushdb()
                print(f"   ✅ DB {db_num}: {key_count} clés supprimées")
            else:
                print(f"   ℹ️  DB {db_num} ({db_name}): vide")

            client.close()

    except Exception as e:
        print(f"   ❌ Erreur purge Redis: {e}")
        raise


def purge_qdrant():
    """Supprime toutes les collections Qdrant OSMOSE"""
    print("🗑️  Purge collections Qdrant...")

    # Collections à purger
    collections_to_purge = [
        'knowwhere_proto',  # Proto-KG OSMOSE
        'knowbase',         # Collection principale recherche
        'rfp_qa',           # Q/A RFP
    ]

    try:
        client = get_qdrant_client()

        # Vérifier les collections existantes
        existing = client.get_collections()
        existing_names = [c.name for c in existing.collections]

        purged = 0
        for collection_name in collections_to_purge:
            if collection_name in existing_names:
                client.delete_collection(collection_name)
                print(f"   ✅ Collection '{collection_name}' supprimée")
                purged += 1
            else:
                print(f"   ℹ️  Collection '{collection_name}' n'existe pas")

        if purged == 0:
            print("   ℹ️  Aucune collection à supprimer")

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
        purge_redis()
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
