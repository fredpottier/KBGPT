#!/usr/bin/env python3
"""
Script de synchronisation des embeddings de concepts Neo4j -> Qdrant.

Usage:
    # Sync complet (tous les concepts)
    python scripts/sync_concept_embeddings.py --tenant default

    # Sync incremental (seulement les modifies depuis dernier sync)
    python scripts/sync_concept_embeddings.py --tenant default --incremental

    # Forcer re-creation de la collection
    python scripts/sync_concept_embeddings.py --tenant default --recreate

    # Voir le statut actuel
    python scripts/sync_concept_embeddings.py --status

Ce script est idempotent et peut etre execute plusieurs fois sans risque.
"""

import argparse
import sys
import json
from pathlib import Path

# Ajouter le repertoire src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.semantic.concept_embedding_service import (
    get_concept_embedding_service,
    QDRANT_CONCEPTS_COLLECTION,
    EMBEDDING_VERSION,
)


def show_status(tenant_id: str = "default"):
    """Affiche le statut du service."""
    service = get_concept_embedding_service()
    status = service.get_status(tenant_id)

    print("\n" + "=" * 60)
    print("CONCEPT EMBEDDING SERVICE STATUS")
    print("=" * 60)
    print(f"Collection:        {QDRANT_CONCEPTS_COLLECTION}")
    print(f"Embedding Version: {EMBEDDING_VERSION}")
    print(f"Tenant:            {tenant_id}")
    print("-" * 60)
    print(f"Available:         {'YES' if status.available else 'NO'}")
    print(f"Collection Exists: {'YES' if status.collection_exists else 'NO'}")
    print(f"Concept Count:     {status.concept_count}")
    print(f"Last Sync:         {status.last_sync or 'Never'}")
    print(f"Message:           {status.message}")
    print("=" * 60 + "\n")

    return status.available


def recreate_collection():
    """Supprime et recree la collection."""
    print("\n[WARNING] Recreating collection - this will delete all indexed concepts!")

    from qdrant_client import QdrantClient
    from knowbase.config.settings import Settings

    settings = Settings()
    client = QdrantClient(url=settings.qdrant_url)

    # Supprimer si existe
    try:
        client.delete_collection(QDRANT_CONCEPTS_COLLECTION)
        print(f"[OK] Deleted collection {QDRANT_CONCEPTS_COLLECTION}")
    except Exception:
        print(f"[INFO] Collection {QDRANT_CONCEPTS_COLLECTION} did not exist")

    # Recreer
    service = get_concept_embedding_service()
    if service.ensure_collection_exists():
        print(f"[OK] Created collection {QDRANT_CONCEPTS_COLLECTION}")
        return True
    else:
        print(f"[ERROR] Failed to create collection")
        return False


def sync_concepts(tenant_id: str, incremental: bool = False):
    """Execute la synchronisation."""
    print(f"\n{'=' * 60}")
    print(f"SYNCING CONCEPTS: tenant={tenant_id}, incremental={incremental}")
    print(f"{'=' * 60}\n")

    service = get_concept_embedding_service()

    # Assurer que la collection existe
    if not service.ensure_collection_exists():
        print("[ERROR] Failed to create/access collection")
        return False

    # Executer la sync
    result = service.sync_concepts(
        tenant_id=tenant_id,
        incremental=incremental,
    )

    # Afficher les resultats
    print("\n" + "-" * 40)
    print("SYNC RESULTS")
    print("-" * 40)
    print(f"Total concepts:  {result.total}")
    print(f"Created:         {result.created}")
    print(f"Updated:         {result.updated}")
    print(f"Unchanged:       {result.unchanged}")
    print(f"Failed:          {result.failed}")
    print(f"Duration:        {result.duration_ms:.0f}ms")
    print(f"Success Rate:    {result.to_dict()['success_rate']}%")

    if result.errors:
        print("\nErrors:")
        for err in result.errors[:10]:
            print(f"  - {err}")

    print("-" * 40 + "\n")

    return result.failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Synchronize concept embeddings from Neo4j to Qdrant"
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant ID (default: 'default')",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only sync concepts modified since last sync",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the collection before sync",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show service status only (no sync)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    try:
        # Mode status uniquement
        if args.status:
            if args.json:
                service = get_concept_embedding_service()
                status = service.get_status(args.tenant)
                print(json.dumps(status.to_dict(), indent=2))
            else:
                show_status(args.tenant)
            return 0

        # Recreer la collection si demande
        if args.recreate:
            if not recreate_collection():
                return 1

        # Executer la sync
        success = sync_concepts(
            tenant_id=args.tenant,
            incremental=args.incremental,
        )

        # Afficher le statut final
        if not args.json:
            show_status(args.tenant)

        return 0 if success else 1

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
