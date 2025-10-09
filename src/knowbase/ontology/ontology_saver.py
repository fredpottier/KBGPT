"""
Sauvegarde ontologies générées par LLM dans Neo4j.
"""
from typing import List, Dict
from datetime import datetime, timezone
from neo4j import GraphDatabase
import uuid
import logging

logger = logging.getLogger(__name__)


def save_ontology_to_neo4j(
    merge_groups: List[Dict],
    entity_type: str,
    tenant_id: str = "default",
    source: str = "llm_generated",
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None
):
    """
    Sauvegarde ontologie générée dans Neo4j.

    Args:
        merge_groups: Groupes validés par user
        entity_type: Type d'entité
        tenant_id: Tenant ID
        source: Source ontologie ("llm_generated" | "manual")
        neo4j_uri: URI Neo4j (optionnel)
        neo4j_user: User (optionnel)
        neo4j_password: Password (optionnel)
    """
    if not neo4j_uri:
        from knowbase.config.settings import get_settings
        settings = get_settings()
        neo4j_uri = settings.neo4j_uri
        neo4j_user = settings.neo4j_user
        neo4j_password = settings.neo4j_password

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as session:
            for group in merge_groups:
                entity_id = group["canonical_key"]
                canonical_name = group["canonical_name"]
                confidence = group.get("confidence", 0.95)

                # Créer/update OntologyEntity
                session.run("""
                    MERGE (ont:OntologyEntity {entity_id: $entity_id})
                    SET ont.canonical_name = $canonical_name,
                        ont.entity_type = $entity_type,
                        ont.source = $source,
                        ont.confidence = $confidence,
                        ont.tenant_id = $tenant_id,
                        ont.created_at = coalesce(ont.created_at, datetime()),
                        ont.updated_at = datetime(),
                        ont.version = coalesce(ont.version, '1.0.0')
                """, {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "source": source,
                    "confidence": confidence,
                    "tenant_id": tenant_id
                })

                # Créer aliases depuis entités mergées
                for entity in group["entities"]:
                    alias_name = entity["name"]

                    # Skip si alias == canonical (éviter doublon)
                    if alias_name.lower() == canonical_name.lower():
                        continue

                    alias_id = str(uuid.uuid4())
                    normalized = alias_name.lower().strip()

                    session.run("""
                        MATCH (ont:OntologyEntity {entity_id: $entity_id})
                        MERGE (alias:OntologyAlias {
                            normalized: $normalized,
                            entity_type: $entity_type,
                            tenant_id: $tenant_id
                        })
                        ON CREATE SET
                            alias.alias_id = $alias_id,
                            alias.alias = $alias
                        MERGE (ont)-[:HAS_ALIAS]->(alias)
                    """, {
                        "entity_id": entity_id,
                        "alias_id": alias_id,
                        "alias": alias_name,
                        "normalized": normalized,
                        "entity_type": entity_type,
                        "tenant_id": tenant_id
                    })

        logger.info(
            f"✅ Ontologie sauvegardée: {entity_type}, "
            f"{len(merge_groups)} groupes, {sum(len(g['entities']) for g in merge_groups)} aliases"
        )

    finally:
        driver.close()


__all__ = ["save_ontology_to_neo4j"]
