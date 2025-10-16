"""
Schéma Neo4j pour Ontologies.

Contraintes, index et structure données.

P0.1 Sandbox Auto-Learning (2025-10-16):
- Ajout champs status, confidence, requires_admin_validation
- Index sur status pour filtrage efficace entités pending
- Support auto-validation (confidence >= 0.95)
"""
from neo4j import GraphDatabase
from typing import List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class OntologyStatus(str, Enum):
    """
    Statut entité ontologie (P0.1 Sandbox Auto-Learning + P0.2 Rollback).

    - AUTO_LEARNED_PENDING: Créé par auto-learning, confidence < 0.95, attend validation admin
    - AUTO_LEARNED_VALIDATED: Créé par auto-learning, confidence >= 0.95, auto-validé
    - MANUAL: Créé manuellement par admin (toujours validé)
    - DEPRECATED: Remplacé par nouvelle entité (P0.2 Rollback), ne doit plus être utilisé
    """
    AUTO_LEARNED_PENDING = "auto_learned_pending"
    AUTO_LEARNED_VALIDATED = "auto_learned_validated"
    MANUAL = "manual"
    DEPRECATED = "deprecated"


class DeprecationReason(str, Enum):
    """
    Raisons de deprecation d'une entité (P0.2 Rollback).

    - INCORRECT_FUSION: Fusion incorrecte détectée (ex: SAP + Oracle fusionnés à tort)
    - WRONG_CANONICAL: Nom canonique incorrect (ex: typo, mauvaise casse)
    - DUPLICATE: Doublon détecté (ex: "SAP S/4HANA" et "S4HANA" doivent fusionner)
    - ADMIN_CORRECTION: Correction manuelle admin sans raison spécifique
    - DATA_QUALITY: Problème qualité données source
    """
    INCORRECT_FUSION = "incorrect_fusion"
    WRONG_CANONICAL = "wrong_canonical"
    DUPLICATE = "duplicate"
    ADMIN_CORRECTION = "admin_correction"
    DATA_QUALITY = "data_quality"


class OntologySchema:
    """Gestion schéma Neo4j ontologies."""

    def __init__(self, driver: GraphDatabase.driver):
        self.driver = driver

    def create_constraints(self) -> List[str]:
        """
        Crée toutes les contraintes nécessaires.

        Returns:
            Liste des contraintes créées
        """
        constraints = []

        with self.driver.session() as session:
            # 1. Contrainte unicité entity_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_entity_id_unique IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    REQUIRE ont.entity_id IS UNIQUE
                """)
                constraints.append("ont_entity_id_unique")
                logger.info("✅ Contrainte ont_entity_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_entity_id_unique existe déjà: {e}")

            # 2. Contrainte unicité alias_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_id_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE alias.alias_id IS UNIQUE
                """)
                constraints.append("ont_alias_id_unique")
                logger.info("✅ Contrainte ont_alias_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_id_unique existe déjà: {e}")

            # 3. Contrainte unicité composite (normalized, entity_type, tenant_id)
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_normalized_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE (alias.normalized, alias.entity_type, alias.tenant_id) IS UNIQUE
                """)
                constraints.append("ont_alias_normalized_unique")
                logger.info("✅ Contrainte ont_alias_normalized_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_normalized_unique existe déjà: {e}")

        return constraints

    def create_indexes(self) -> List[str]:
        """
        Crée tous les index pour performance.

        Returns:
            Liste des index créés
        """
        indexes = []

        with self.driver.session() as session:
            # 1. Index sur normalized (lookup principal)
            try:
                session.run("""
                    CREATE INDEX ont_alias_normalized_idx IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    ON (alias.normalized)
                """)
                indexes.append("ont_alias_normalized_idx")
                logger.info("✅ Index ont_alias_normalized_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_alias_normalized_idx existe déjà: {e}")

            # 2. Index sur entity_type (filtrage)
            try:
                session.run("""
                    CREATE INDEX ont_entity_type_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.entity_type)
                """)
                indexes.append("ont_entity_type_idx")
                logger.info("✅ Index ont_entity_type_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_entity_type_idx existe déjà: {e}")

            # 3. Index sur canonical_name (lowercase pour search)
            try:
                session.run("""
                    CREATE INDEX ont_canonical_lower_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.canonical_name)
                """)
                indexes.append("ont_canonical_lower_idx")
                logger.info("✅ Index ont_canonical_lower_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_canonical_lower_idx existe déjà: {e}")

            # 4. Index sur tenant_id (multi-tenancy)
            try:
                session.run("""
                    CREATE INDEX ont_tenant_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.tenant_id)
                """)
                indexes.append("ont_tenant_idx")
                logger.info("✅ Index ont_tenant_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_tenant_idx existe déjà: {e}")

            # 5. Index sur status (P0.1 Sandbox Auto-Learning - filtrage entités pending)
            try:
                session.run("""
                    CREATE INDEX ont_status_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.status)
                """)
                indexes.append("ont_status_idx")
                logger.info("✅ Index ont_status_idx créé (P0.1 Sandbox)")
            except Exception as e:
                logger.warning(f"Index ont_status_idx existe déjà: {e}")

            # 6. Index sur confidence (P0.1 Sandbox - filtrage par seuil)
            try:
                session.run("""
                    CREATE INDEX ont_confidence_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.confidence)
                """)
                indexes.append("ont_confidence_idx")
                logger.info("✅ Index ont_confidence_idx créé (P0.1 Sandbox)")
            except Exception as e:
                logger.warning(f"Index ont_confidence_idx existe déjà: {e}")

        return indexes

    def validate_schema(self) -> dict:
        """
        Valide que le schéma est correctement créé.

        Returns:
            Dict avec statut validation
        """
        with self.driver.session() as session:
            # Vérifier contraintes
            result = session.run("SHOW CONSTRAINTS")
            constraints = [record["name"] for record in result]

            # Vérifier index
            result = session.run("SHOW INDEXES")
            indexes = [record["name"] for record in result]

            return {
                "constraints": constraints,
                "indexes": indexes,
                "valid": (
                    "ont_entity_id_unique" in constraints and
                    "ont_alias_normalized_idx" in indexes
                )
            }


def create_ontology_entity_with_sandbox(
    driver: GraphDatabase.driver,
    canonical_name: str,
    entity_type: str,
    tenant_id: str,
    confidence: float = 0.0,
    created_by: str = "auto_learning",
    metadata: dict = None
) -> str:
    """
    Crée entité ontologie avec sandbox auto-learning (P0.1).

    Auto-validation si confidence >= 0.95.

    Args:
        driver: Neo4j driver
        canonical_name: Nom canonique entité
        entity_type: Type entité (PRODUCT, COMPANY, CONCEPT, etc.)
        tenant_id: ID tenant (multi-tenancy)
        confidence: Score confidence auto-learning (0-1)
        created_by: Source création ("auto_learning", "admin", "batch")
        metadata: Métadonnées additionnelles (dict)

    Returns:
        entity_id créé (UUID)
    """
    import json
    from datetime import datetime

    metadata = metadata or {}

    # Auto-validation si confidence >= 0.95
    if confidence >= 0.95:
        status = OntologyStatus.AUTO_LEARNED_VALIDATED.value
        requires_admin_validation = False
        validated_by = "auto_validated"
        validated_at = datetime.utcnow().isoformat()
    else:
        status = OntologyStatus.AUTO_LEARNED_PENDING.value
        requires_admin_validation = True
        validated_by = None
        validated_at = None

    # Support création manuelle admin
    if created_by == "admin":
        status = OntologyStatus.MANUAL.value
        requires_admin_validation = False
        validated_by = created_by
        validated_at = datetime.utcnow().isoformat()

    query = """
    CREATE (ont:OntologyEntity {
        entity_id: randomUUID(),
        canonical_name: $canonical_name,
        entity_type: $entity_type,
        tenant_id: $tenant_id,

        status: $status,
        confidence: $confidence,
        requires_admin_validation: $requires_admin_validation,

        created_by: $created_by,
        created_at: datetime(),

        validated_by: $validated_by,
        validated_at: $validated_at,

        metadata_json: $metadata_json
    })
    RETURN ont.entity_id AS entity_id
    """

    with driver.session() as session:
        result = session.run(
            query,
            canonical_name=canonical_name,
            entity_type=entity_type,
            tenant_id=tenant_id,
            status=status,
            confidence=confidence,
            requires_admin_validation=requires_admin_validation,
            created_by=created_by,
            validated_by=validated_by,
            validated_at=validated_at,
            metadata_json=json.dumps(metadata)
        )

        record = result.single()
        entity_id = record["entity_id"]

        logger.info(
            f"[ONTOLOGY:Sandbox] Created entity '{canonical_name}' "
            f"(type={entity_type}, status={status}, confidence={confidence:.2f}, "
            f"requires_validation={requires_admin_validation})"
        )

        return entity_id


def deprecate_ontology_entity(
    driver: GraphDatabase.driver,
    old_entity_id: str,
    new_entity_id: str,
    reason: str,
    deprecated_by: str = "admin",
    tenant_id: str = "default",
    comment: str = None
) -> bool:
    """
    Déprécier une entité ontologie et migrer vers nouvelle (P0.2 Rollback).

    Opérations atomiques:
    1. Marquer old_entity status=DEPRECATED
    2. Créer relation DEPRECATED_BY vers new_entity
    3. Migrer tous les CanonicalConcept qui pointaient vers old_entity

    Args:
        driver: Neo4j driver
        old_entity_id: ID entité à déprécier
        new_entity_id: ID nouvelle entité de remplacement
        reason: Raison deprecation (voir DeprecationReason enum)
        deprecated_by: Qui a fait la deprecation (user_id ou "admin")
        tenant_id: Tenant ID (multi-tenancy)
        comment: Commentaire optionnel admin

    Returns:
        True si deprecation réussie, False sinon
    """
    import json
    from datetime import datetime

    # Validation
    if old_entity_id == new_entity_id:
        logger.error(f"[ONTOLOGY:Rollback] Cannot deprecate entity to itself: {old_entity_id}")
        return False

    logger.info(
        f"[ONTOLOGY:Rollback] Deprecating '{old_entity_id}' → '{new_entity_id}' "
        f"(reason={reason}, by={deprecated_by})"
    )

    with driver.session() as session:
        # Transaction atomique
        def deprecate_tx(tx):
            # 1. Vérifier que les deux entités existent
            check_query = """
            MATCH (old:OntologyEntity {entity_id: $old_entity_id, tenant_id: $tenant_id})
            MATCH (new:OntologyEntity {entity_id: $new_entity_id, tenant_id: $tenant_id})
            RETURN old.canonical_name AS old_name, new.canonical_name AS new_name
            """
            result = tx.run(check_query, {
                "old_entity_id": old_entity_id,
                "new_entity_id": new_entity_id,
                "tenant_id": tenant_id
            })
            record = result.single()

            if not record:
                logger.error(
                    f"[ONTOLOGY:Rollback] Entity not found: old={old_entity_id}, new={new_entity_id}"
                )
                return False

            old_name = record["old_name"]
            new_name = record["new_name"]

            logger.info(
                f"[ONTOLOGY:Rollback] Migrating '{old_name}' → '{new_name}'"
            )

            # 2. Marquer old_entity comme DEPRECATED + créer relation DEPRECATED_BY
            deprecate_query = """
            MATCH (old:OntologyEntity {entity_id: $old_entity_id, tenant_id: $tenant_id})
            MATCH (new:OntologyEntity {entity_id: $new_entity_id, tenant_id: $tenant_id})

            SET old.status = 'deprecated',
                old.deprecated_at = datetime(),
                old.deprecated_by = $deprecated_by,
                old.updated_at = datetime()

            MERGE (old)-[rel:DEPRECATED_BY]->(new)
            SET rel.reason = $reason,
                rel.deprecated_at = datetime(),
                rel.deprecated_by = $deprecated_by,
                rel.comment = $comment

            RETURN count(rel) AS deprecated_count
            """
            result = tx.run(deprecate_query, {
                "old_entity_id": old_entity_id,
                "new_entity_id": new_entity_id,
                "tenant_id": tenant_id,
                "reason": reason,
                "deprecated_by": deprecated_by,
                "comment": comment
            })
            record = result.single()

            if record["deprecated_count"] == 0:
                logger.error("[ONTOLOGY:Rollback] Failed to create DEPRECATED_BY relation")
                return False

            logger.info(
                f"[ONTOLOGY:Rollback] ✅ Marked '{old_name}' as DEPRECATED "
                f"(DEPRECATED_BY → '{new_name}')"
            )

            # 3. Migrer tous les CanonicalConcept qui pointaient vers old_entity
            migrate_query = """
            MATCH (old:OntologyEntity {entity_id: $old_entity_id, tenant_id: $tenant_id})
            MATCH (new:OntologyEntity {entity_id: $new_entity_id, tenant_id: $tenant_id})
            MATCH (canonical:CanonicalConcept)-[rel:NORMALIZED_AS]->(old)

            // Créer nouvelle relation vers new
            MERGE (canonical)-[new_rel:NORMALIZED_AS]->(new)
            SET new_rel.migrated_from = $old_entity_id,
                new_rel.migrated_at = datetime(),
                new_rel.migration_reason = $reason

            // Supprimer ancienne relation
            DELETE rel

            RETURN count(canonical) AS migrated_count
            """
            result = tx.run(migrate_query, {
                "old_entity_id": old_entity_id,
                "new_entity_id": new_entity_id,
                "tenant_id": tenant_id,
                "reason": reason
            })
            record = result.single()
            migrated_count = record["migrated_count"]

            logger.info(
                f"[ONTOLOGY:Rollback] ✅ Migrated {migrated_count} CanonicalConcept(s) "
                f"from '{old_name}' → '{new_name}'"
            )

            return True

        try:
            success = session.execute_write(deprecate_tx)

            if success:
                logger.info(
                    f"[ONTOLOGY:Rollback] ✅ ROLLBACK COMPLETED: '{old_entity_id}' → '{new_entity_id}' "
                    f"(reason={reason})"
                )
            else:
                logger.error(
                    f"[ONTOLOGY:Rollback] ❌ ROLLBACK FAILED: '{old_entity_id}' → '{new_entity_id}'"
                )

            return success

        except Exception as e:
            logger.error(f"[ONTOLOGY:Rollback] Exception during deprecation: {e}")
            return False


def apply_ontology_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """
    Point d'entrée : applique schéma complet.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        schema = OntologySchema(driver)

        logger.info("🚀 Application schéma Neo4j ontologies...")

        # Créer contraintes
        constraints = schema.create_constraints()
        logger.info(f"✅ {len(constraints)} contraintes créées")

        # Créer index
        indexes = schema.create_indexes()
        logger.info(f"✅ {len(indexes)} index créés")

        # Valider
        validation = schema.validate_schema()
        if validation["valid"]:
            logger.info("✅ Schéma validé avec succès")
        else:
            logger.error("❌ Schéma invalide")
            logger.error(f"Contraintes: {validation['constraints']}")
            logger.error(f"Index: {validation['indexes']}")

        return validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    apply_ontology_schema(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password")
    )
