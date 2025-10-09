"""
Normalization Worker - Job RQ pour normalisation entités (merge).

Phase 5B - Solution 3 Hybride
Step 4 - Worker async normalisation

Exécute EntityMergeService en batch + crée snapshot pour undo.
"""
import json
from datetime import datetime, timedelta

from knowbase.api.services.entity_merge_service import EntityMergeService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "normalization_worker.log")


def normalize_entities_task(
    type_name: str,
    merge_groups: list,
    tenant_id: str = "default",
    create_snapshot: bool = True
):
    """
    Task RQ: Normalise entités via batch merge.

    Args:
        type_name: Type entités
        merge_groups: Groupes validés par user
        tenant_id: Tenant ID
        create_snapshot: Créer snapshot pour undo

    Returns:
        Dict résultat normalisation
    """
    logger.info(
        f"🔄 [Worker] Normalisation {type_name} - "
        f"{len(merge_groups)} groupes, tenant={tenant_id}"
    )

    try:
        # Créer snapshot avant normalisation (pour undo)
        snapshot_id = None
        if create_snapshot:
            snapshot_id = _create_snapshot(type_name, merge_groups, tenant_id)
            logger.info(f"📸 Snapshot créé: {snapshot_id}")

        # Exécuter batch merge
        merge_service = EntityMergeService()
        result = merge_service.batch_merge_from_preview(
            merge_groups=merge_groups,
            tenant_id=tenant_id
        )

        # Enrichir résultat avec snapshot info
        result["snapshot_id"] = snapshot_id
        result["snapshot_expires_at"] = (
            datetime.utcnow() + timedelta(hours=24)
        ).isoformat() if snapshot_id else None

        logger.info(
            f"✅ [Worker] Normalisation terminée: "
            f"{result['entities_merged']} entités mergées, "
            f"{len(result['errors'])} erreurs"
        )

        # Auto-save ontologie dans Neo4j (boucle feedback fermée)
        try:
            from knowbase.ontology.ontology_saver import save_ontology_to_neo4j

            save_ontology_to_neo4j(
                merge_groups=merge_groups,
                entity_type=type_name,
                tenant_id=tenant_id,
                source="llm_generated"
            )

            logger.info(f"✅ Ontologie sauvegardée dans Neo4j: {type_name}")

        except Exception as e:
            logger.error(f"⚠️ Erreur sauvegarde ontologie Neo4j: {e}")
            # Non-bloquant, continuer

        return result

    except Exception as e:
        logger.error(f"❌ [Worker] Erreur normalisation: {e}", exc_info=True)
        raise


def _create_snapshot(
    type_name: str,
    merge_groups: list,
    tenant_id: str
) -> str:
    """
    Crée snapshot pré-normalisation dans SQLite.

    Args:
        type_name: Type
        merge_groups: Groupes à merger
        tenant_id: Tenant ID

    Returns:
        snapshot_id (UUID)
    """
    import uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    snapshot_id = str(uuid.uuid4())

    # Connexion SQLite
    engine = create_engine('sqlite:////data/entity_types_registry.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Créer table si pas existante
        from sqlalchemy import text
        session.execute(text("""
        CREATE TABLE IF NOT EXISTS normalization_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            type_name TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            merge_groups_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            restored BOOLEAN DEFAULT FALSE
        )
        """))

        # Insérer snapshot
        expires_at = datetime.utcnow() + timedelta(hours=24)

        session.execute(
            text("""
            INSERT INTO normalization_snapshots
            (snapshot_id, type_name, tenant_id, merge_groups_json, expires_at)
            VALUES (:snapshot_id, :type_name, :tenant_id, :merge_groups_json, :expires_at)
            """),
            {
                "snapshot_id": snapshot_id,
                "type_name": type_name,
                "tenant_id": tenant_id,
                "merge_groups_json": json.dumps(merge_groups),
                "expires_at": expires_at
            }
        )

        session.commit()

        logger.info(f"📸 Snapshot {snapshot_id} créé (TTL 24h)")

        return snapshot_id

    except Exception as e:
        session.rollback()
        logger.error(f"❌ Erreur création snapshot: {e}")
        raise
    finally:
        session.close()


def undo_normalization_task(
    snapshot_id: str,
    type_name: str,
    merge_groups: list,
    tenant_id: str = "default"
):
    """
    Task RQ: Annule normalisation (restaure snapshot).

    **Opérations**:
    1. Pour chaque groupe: recrée entités duplicatas supprimées
    2. Restaure relations originales (best effort)
    3. Supprime entité master normalisée
    4. Marque snapshot comme restored

    Args:
        snapshot_id: ID snapshot
        type_name: Type
        merge_groups: Groupes du snapshot
        tenant_id: Tenant ID

    Returns:
        Dict résultat undo
    """
    logger.info(
        f"↩️ [Worker] Undo normalisation {type_name} - "
        f"snapshot={snapshot_id}, {len(merge_groups)} groupes"
    )

    try:
        from neo4j import GraphDatabase
        import os

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        entities_restored = 0
        masters_deleted = 0

        with driver.session() as session:
            for group in merge_groups:
                master_uuid = group["master_uuid"]
                canonical_name = group["canonical_name"]

                # ÉTAPE 1: Supprimer d'abord le master normalisé (qui contient les données mergées)
                query_delete_master = """
                MATCH (master:Entity {uuid: $master_uuid, tenant_id: $tenant_id})
                DETACH DELETE master
                RETURN count(master) AS deleted
                """

                result_delete = session.run(
                    query_delete_master,
                    master_uuid=master_uuid,
                    tenant_id=tenant_id
                )
                record = result_delete.single()
                if record and record["deleted"] > 0:
                    masters_deleted += 1

                # ÉTAPE 2: Recréer TOUTES les entités originales (y compris le master avec ses données originales)
                for entity in group["entities"]:
                    # CREATE entité (toujours, y compris l'ancien master)
                    query_create = """
                    CREATE (e:Entity {
                        uuid: $uuid,
                        name: $name,
                        entity_type: $entity_type,
                        description: $description,
                        status: 'pending',
                        tenant_id: $tenant_id,
                        created_at: datetime(),
                        restored_from_snapshot: $snapshot_id
                    })
                    RETURN e
                    """

                    session.run(
                        query_create,
                        uuid=entity["uuid"],
                        name=entity["name"],
                        entity_type=type_name,
                        description=entity.get("description", ""),
                        tenant_id=tenant_id,
                        snapshot_id=snapshot_id
                    )

                    entities_restored += 1

        driver.close()

        # Marquer snapshot comme restored
        _mark_snapshot_restored(snapshot_id)

        logger.info(
            f"✅ [Worker] Undo terminé: {entities_restored} entités restaurées, "
            f"{masters_deleted} masters supprimés"
        )

        return {
            "snapshot_id": snapshot_id,
            "entities_restored": entities_restored,
            "masters_deleted": masters_deleted,
            "restored_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ [Worker] Erreur undo: {e}", exc_info=True)
        raise


def _mark_snapshot_restored(snapshot_id: str):
    """Marque snapshot comme restored dans SQLite."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:////data/entity_types_registry.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        session.execute(
            text("""
            UPDATE normalization_snapshots
            SET restored = TRUE
            WHERE snapshot_id = :snapshot_id
            """),
            {"snapshot_id": snapshot_id}
        )
        session.commit()
        logger.info(f"✅ Snapshot {snapshot_id} marqué restored")
    except Exception as e:
        session.rollback()
        logger.error(f"❌ Erreur mark restored: {e}")
        raise
    finally:
        session.close()


__all__ = ["normalize_entities_task", "undo_normalization_task"]
