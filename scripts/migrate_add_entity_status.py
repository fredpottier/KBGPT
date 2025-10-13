#!/usr/bin/env python3
"""
Script de migration Neo4j : Ajouter status='pending' aux entités existantes.

Ce script met à jour toutes les entités Neo4j qui n'ont pas de champ 'status'
pour leur ajouter status='pending' et is_cataloged=False.
"""

import sys
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.neo4j_custom import get_neo4j_client


def migrate_add_entity_status():
    """Ajoute status='pending' à toutes les entités sans status."""

    print("🔄 Migration Neo4j: Ajout du champ 'status' aux entités existantes")
    print("=" * 70)

    client = get_neo4j_client()

    # 1. Compter les entités sans status
    count_query = """
    MATCH (e:Entity)
    WHERE e.status IS NULL
    RETURN count(e) as count
    """

    with client.driver.session() as session:
        result = session.run(count_query)
        record = result.single()
        count_without_status = record["count"] if record else 0

    print(f"📊 Entités sans champ 'status': {count_without_status}")

    if count_without_status == 0:
        print("✅ Aucune entité à migrer")
        return

    # 2. Demander confirmation
    print(f"\n⚠️  Cette opération va ajouter status='pending' et is_cataloged=False")
    print(f"    à {count_without_status} entités.")

    # Pas besoin de confirmation dans un script automatisé
    # Si on veut ajouter confirmation, décommenter ces lignes:
    # response = input("\nContinuer ? (oui/non): ").strip().lower()
    # if response not in ['oui', 'yes', 'y', 'o']:
    #     print("❌ Migration annulée")
    #     return

    # 3. Appliquer la migration
    migration_query = """
    MATCH (e:Entity)
    WHERE e.status IS NULL
    SET e.status = 'pending',
        e.is_cataloged = false,
        e.updated_at = datetime()
    RETURN count(e) as updated_count
    """

    print(f"\n🚀 Application de la migration...")

    with client.driver.session() as session:
        result = session.run(migration_query)
        record = result.single()
        updated_count = record["updated_count"] if record else 0

    print(f"✅ Migration terminée: {updated_count} entités mises à jour")

    # 4. Vérification post-migration
    verify_query = """
    MATCH (e:Entity)
    RETURN
        count(e) as total_entities,
        count(CASE WHEN e.status = 'pending' THEN 1 END) as pending_count,
        count(CASE WHEN e.status = 'validated' THEN 1 END) as validated_count,
        count(CASE WHEN e.status IS NULL THEN 1 END) as no_status_count
    """

    with client.driver.session() as session:
        result = session.run(verify_query)
        record = result.single()

        if record:
            print("\n📊 État après migration:")
            print(f"   • Total entités: {record['total_entities']}")
            print(f"   • Status 'pending': {record['pending_count']}")
            print(f"   • Status 'validated': {record['validated_count']}")
            print(f"   • Sans status: {record['no_status_count']}")

    print("\n🎉 Migration réussie!")


if __name__ == "__main__":
    try:
        migrate_add_entity_status()
    except Exception as e:
        print(f"\n❌ Erreur lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
