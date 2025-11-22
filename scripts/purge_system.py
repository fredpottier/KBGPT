#!/usr/bin/env python3
"""
🌊 OSMOSE - Purge Système Complète

Script pour purger TOUTES les données du système KnowWhere/OSMOSE.

Usage:
    # Depuis l'hôte
    python scripts/purge_system.py

    # Depuis le conteneur
    docker-compose exec app python scripts/purge_system.py

Purge:
    ✅ Redis: TOUTES les clés (FLUSHDB) - includes import queues, RQ jobs, cache
    ✅ Qdrant: Collections knowbase, rfp_qa
    ✅ Neo4j: Tous les nodes du tenant 'default' (préserve autres tenants)
    ✅ Fichiers: docs_done/, status/*.status

Préserve:
    ⚠️ Cache d'extraction: data/extraction_cache/ (JAMAIS touché)
    ⚠️ Documents source: data/docs_in/ (non purgés par défaut)
    ⚠️ Schéma Neo4j: Constraints et indexes (sauf avec --full)
"""

import os
import sys
import asyncio
import argparse
import shutil
from pathlib import Path

# Redis
import redis

# Neo4j
from neo4j import GraphDatabase

# Qdrant
from qdrant_client import QdrantClient


def purge_redis_all():
    """Purge COMPLÈTE Redis (FLUSHDB) - supprime TOUTES les clés."""
    print("🗑️  Purge Redis (FLUSHDB - toutes les clés)...")

    try:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        client = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

        # Compter clés avant purge
        keys_before = client.dbsize()

        # FLUSHDB: supprime TOUTES les clés de la DB
        client.flushdb()

        print(f"   ✅ {keys_before} clés Redis supprimées (FLUSHDB)")
        return {"success": True, "keys_deleted": keys_before}

    except Exception as e:
        print(f"   ❌ Erreur purge Redis: {e}")
        return {"success": False, "error": str(e)}


def purge_qdrant():
    """Purge collections Qdrant knowbase et rfp_qa."""
    print("🗑️  Purge Qdrant (collections knowbase, rfp_qa)...")

    try:
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))

        client = QdrantClient(host=qdrant_host, port=qdrant_port)

        collections_to_delete = ["knowbase", "rfp_qa"]
        deleted = []

        for collection_name in collections_to_delete:
            try:
                # Vérifier si existe
                collections = client.get_collections()
                collection_names = [c.name for c in collections.collections]

                if collection_name in collection_names:
                    client.delete_collection(collection_name)
                    deleted.append(collection_name)
                    print(f"   ✅ Collection '{collection_name}' supprimée")
                else:
                    print(f"   ℹ️  Collection '{collection_name}' n'existe pas")

            except Exception as e:
                print(f"   ⚠️  Erreur suppression '{collection_name}': {e}")

        return {"success": True, "collections_deleted": deleted}

    except Exception as e:
        print(f"   ❌ Erreur purge Qdrant: {e}")
        return {"success": False, "error": str(e)}


def purge_neo4j(tenant_id: str = "default"):
    """Purge Neo4j - supprime tous les nodes du tenant spécifié.

    Args:
        tenant_id: Tenant à purger (défaut: 'default')
    """
    print(f"🗑️  Purge Neo4j (tenant: {tenant_id})...")

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        try:
            with driver.session() as session:
                # Compter nodes avant suppression
                count_result = session.run("""
                    MATCH (n)
                    WHERE n.tenant_id = $tenant_id
                    RETURN count(n) as total
                """, tenant_id=tenant_id)

                count_record = count_result.single()
                nodes_before = count_record["total"] if count_record else 0

                if nodes_before > 0:
                    # Supprimer tous les nodes du tenant (DETACH DELETE pour les relations)
                    session.run("""
                        MATCH (n)
                        WHERE n.tenant_id = $tenant_id
                        DETACH DELETE n
                    """, tenant_id=tenant_id)

                    print(f"   ✅ {nodes_before} nodes supprimés (tenant: {tenant_id})")
                else:
                    print(f"   ℹ️  Aucun node à supprimer (tenant: {tenant_id})")

                return {"success": True, "nodes_deleted": nodes_before}

        finally:
            driver.close()

    except Exception as e:
        print(f"   ❌ Erreur purge Neo4j: {e}")
        return {"success": False, "error": str(e)}


def purge_files():
    """Purge fichiers docs_done/ et status/*.status.

    ⚠️ NE TOUCHE PAS à data/extraction_cache/ (précieux!)
    ⚠️ NE TOUCHE PAS à data/docs_in/ (source documents)
    """
    print("🗑️  Purge fichiers (docs_done/, status/)...")

    try:
        base_dir = Path(__file__).parent.parent / "data"

        # 1. Purge docs_done/
        docs_done = base_dir / "docs_done"
        if docs_done.exists():
            files_before = len(list(docs_done.glob("*")))
            for item in docs_done.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            print(f"   ✅ docs_done/ purgé ({files_before} fichiers)")
        else:
            print(f"   ℹ️  docs_done/ n'existe pas")

        # 2. Purge status/*.status
        status_dir = base_dir / "status"
        if status_dir.exists():
            status_files = list(status_dir.glob("*.status"))
            status_count = len(status_files)
            for f in status_files:
                f.unlink()
            print(f"   ✅ status/*.status purgé ({status_count} fichiers)")
        else:
            print(f"   ℹ️  status/ n'existe pas")

        # ⚠️ VÉRIFICATION : extraction_cache/ est PRÉSERVÉ
        cache_dir = base_dir / "extraction_cache"
        if cache_dir.exists():
            cache_count = len(list(cache_dir.glob("*.knowcache.json")))
            print(f"   ✅ extraction_cache/ PRÉSERVÉ ({cache_count} caches)")

        return {"success": True}

    except Exception as e:
        print(f"   ❌ Erreur purge fichiers: {e}")
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="🌊 OSMOSE - Purge Système Complète",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python scripts/purge_system.py                    # Purge complète (recommandé)
  python scripts/purge_system.py --tenant myorg     # Purge tenant spécifique Neo4j

⚠️  Ce script purge TOUTES les données mais PRÉSERVE:
    - data/extraction_cache/ (caches précieux)
    - data/docs_in/ (documents source)
    - Schéma Neo4j (constraints/indexes)
        """
    )

    parser.add_argument(
        '--tenant',
        default='default',
        help='Tenant Neo4j à purger (défaut: default)'
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🌊 OSMOSE - PURGE SYSTÈME COMPLÈTE")
    print("=" * 70)
    print()
    print("⚠️  Cette opération va supprimer:")
    print("   • Toutes les clés Redis (import queues, jobs, cache)")
    print("   • Collections Qdrant (knowbase, rfp_qa)")
    print(f"   • Nodes Neo4j (tenant: {args.tenant})")
    print("   • Fichiers docs_done/ et status/")
    print()
    print("✅ Préservé:")
    print("   • data/extraction_cache/ (JAMAIS touché)")
    print("   • data/docs_in/ (documents source)")
    print()

    # Confirmation
    try:
        response = input("Continuer? [y/N] ")
        if response.lower() not in ['y', 'yes', 'o', 'oui']:
            print("❌ Annulé par l'utilisateur")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n❌ Annulé par l'utilisateur")
        sys.exit(0)

    print()
    print("🚀 Démarrage purge...")
    print()

    results = {}

    # 1. Redis
    results['redis'] = purge_redis_all()
    print()

    # 2. Qdrant
    results['qdrant'] = purge_qdrant()
    print()

    # 3. Neo4j
    results['neo4j'] = purge_neo4j(tenant_id=args.tenant)
    print()

    # 4. Fichiers
    results['files'] = purge_files()
    print()

    # Résumé
    print("=" * 70)
    all_success = all(r.get('success', False) for r in results.values())

    if all_success:
        print("✅ PURGE COMPLÈTE RÉUSSIE")
        print()
        print("Résultats:")
        if 'redis' in results and results['redis']['success']:
            print(f"  • Redis: {results['redis'].get('keys_deleted', 0)} clés supprimées")
        if 'qdrant' in results and results['qdrant']['success']:
            collections = results['qdrant'].get('collections_deleted', [])
            print(f"  • Qdrant: {len(collections)} collections supprimées ({', '.join(collections)})")
        if 'neo4j' in results and results['neo4j']['success']:
            print(f"  • Neo4j: {results['neo4j'].get('nodes_deleted', 0)} nodes supprimés")
        if 'files' in results and results['files']['success']:
            print(f"  • Fichiers: docs_done/ et status/ purgés")
    else:
        print("⚠️  PURGE PARTIELLE - Certaines erreurs rencontrées")
        print()
        print("Erreurs:")
        for component, result in results.items():
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                print(f"  • {component}: {error}")

    print("=" * 70)

    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
