#!/usr/bin/env python3
"""
Script pour migrer la collection sap_kb vers knowbase dans Qdrant.
"""

import logging
from pathlib import Path
from typing import List
import json

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

logger = setup_logging(Path(__file__).parent.parent.parent.parent.parent / "data" / "logs", "migrate_collection.log")

def migrate_collection(
    source_collection: str,
    target_collection: str,
    batch_size: int = 100
) -> None:
    """
    Migre tous les points d'une collection source vers une collection cible.

    Args:
        source_collection: Nom de la collection source
        target_collection: Nom de la collection cible
        batch_size: Taille des batches pour l'opération
    """
    qdrant_client = get_qdrant_client()

    try:
        # Vérifier si la collection source existe
        collections = qdrant_client.get_collections()
        source_exists = any(col.name == source_collection for col in collections.collections)

        if not source_exists:
            logger.error(f"❌ Collection source '{source_collection}' n'existe pas")
            return

        logger.info(f"✅ Collection source '{source_collection}' trouvée")

        # Obtenir les informations de la collection source
        source_info = qdrant_client.get_collection(source_collection)
        logger.info(f"📊 Collection source contient {source_info.points_count} points")

        # Vérifier si la collection cible existe déjà
        target_exists = any(col.name == target_collection for col in collections.collections)

        if target_exists:
            logger.warning(f"⚠️ Collection cible '{target_collection}' existe déjà")
            response = input(f"Voulez-vous la recréer ? (y/N): ").lower().strip()
            if response == 'y':
                logger.info(f"🗑️ Suppression de la collection '{target_collection}'")
                qdrant_client.delete_collection(target_collection)
            else:
                logger.info("❌ Migration annulée")
                return

        # Créer la collection cible avec la même configuration
        logger.info(f"🔧 Création de la collection '{target_collection}'")
        qdrant_client.create_collection(
            collection_name=target_collection,
            vectors_config=source_info.config.params.vectors
        )

        # Copier tous les points par batches
        logger.info(f"📦 Début de la migration par batches de {batch_size}")

        offset = None
        total_migrated = 0

        while True:
            # Récupérer un batch de points
            scroll_result = qdrant_client.scroll(
                collection_name=source_collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True
            )

            points, next_offset = scroll_result

            if not points:
                break

            # Préparer les points pour l'insertion
            points_to_insert = []
            for point in points:
                points_to_insert.append({
                    "id": point.id,
                    "vector": point.vector,
                    "payload": point.payload
                })

            # Insérer le batch dans la collection cible
            qdrant_client.upsert(
                collection_name=target_collection,
                points=points_to_insert
            )

            total_migrated += len(points)
            logger.info(f"📈 Migré {total_migrated}/{source_info.points_count} points")

            # Mettre à jour l'offset pour le prochain batch
            offset = next_offset
            if not next_offset:
                break

        # Vérifier le résultat
        target_info = qdrant_client.get_collection(target_collection)
        logger.info(f"✅ Migration terminée!")
        logger.info(f"📊 Collection source '{source_collection}': {source_info.points_count} points")
        logger.info(f"📊 Collection cible '{target_collection}': {target_info.points_count} points")

        if source_info.points_count == target_info.points_count:
            logger.info("🎉 Migration réussie - Tous les points ont été copiés!")
        else:
            logger.warning(f"⚠️ Différence de points: {source_info.points_count - target_info.points_count}")

    except Exception as e:
        logger.error(f"❌ Erreur pendant la migration: {e}")
        raise


def main():
    """Point d'entrée principal du script."""
    import argparse

    parser = argparse.ArgumentParser(description="Migrer une collection Qdrant")
    parser.add_argument("--source", default="sap_kb", help="Collection source (défaut: sap_kb)")
    parser.add_argument("--target", default="knowbase", help="Collection cible (défaut: knowbase)")
    parser.add_argument("--batch-size", type=int, default=100, help="Taille des batches (défaut: 100)")
    parser.add_argument("--yes", action="store_true", help="Confirmer automatiquement")

    args = parser.parse_args()

    logger.info(f"🚀 Début de la migration: {args.source} → {args.target}")

    if not args.yes:
        response = input(f"Migrer '{args.source}' vers '{args.target}' ? (y/N): ").lower().strip()
        if response != 'y':
            logger.info("❌ Migration annulée par l'utilisateur")
            return

    migrate_collection(args.source, args.target, args.batch_size)


if __name__ == "__main__":
    main()