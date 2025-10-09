"""
EntityNormalizer basé sur Neo4j.

Remplace EntityNormalizer YAML pour normalisation via ontologies Neo4j.
"""
from typing import Tuple, Optional, Dict
from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)


class EntityNormalizerNeo4j:
    """
    Normalizer basé sur Neo4j Ontology.

    Recherche entités dans :OntologyEntity via :OntologyAlias.
    """

    def __init__(self, driver: GraphDatabase.driver):
        """
        Initialise normalizer.

        Args:
            driver: Neo4j driver
        """
        self.driver = driver

    def normalize_entity_name(
        self,
        raw_name: str,
        entity_type_hint: Optional[str] = None,
        tenant_id: str = "default"
    ) -> Tuple[Optional[str], str, Optional[str], bool]:
        """
        Normalise nom d'entité via ontologie Neo4j.

        Args:
            raw_name: Nom brut extrait par LLM
            entity_type_hint: Type suggéré par LLM (optionnel, pas contrainte)
            tenant_id: Tenant ID

        Returns:
            Tuple (entity_id, canonical_name, entity_type, is_cataloged)
            - entity_id: ID catalogue (ex: "S4HANA_CLOUD") ou None
            - canonical_name: Nom normalisé (ex: "SAP S/4HANA Cloud")
            - entity_type: Type découvert (peut différer du hint)
            - is_cataloged: True si trouvé dans ontologie
        """
        normalized_search = raw_name.strip().lower()

        with self.driver.session() as session:
            # Query ontologie (index global sur normalized)
            query = """
            MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias {
                normalized: $normalized,
                tenant_id: $tenant_id
            })
            """

            params = {
                "normalized": normalized_search,
                "tenant_id": tenant_id
            }

            # Filtrer par type si hint fourni (mais pas bloquer si pas trouvé)
            if entity_type_hint:
                query += " WHERE ont.entity_type = $entity_type_hint"
                params["entity_type_hint"] = entity_type_hint

            query += """
            RETURN
                ont.entity_id AS entity_id,
                ont.canonical_name AS canonical_name,
                ont.entity_type AS entity_type,
                ont.category AS category,
                ont.vendor AS vendor,
                ont.confidence AS confidence
            LIMIT 1
            """

            result = session.run(query, params)
            record = result.single()

            if record:
                # Trouvé dans ontologie
                logger.debug(
                    f"✅ Normalisé: '{raw_name}' → '{record['canonical_name']}' "
                    f"(type={record['entity_type']}, id={record['entity_id']})"
                )

                return (
                    record["entity_id"],
                    record["canonical_name"],
                    record["entity_type"],
                    True  # is_cataloged
                )

            # Pas trouvé → essayer sans filtrage type
            if entity_type_hint:
                logger.debug(
                    f"⚠️ '{raw_name}' pas trouvé avec type={entity_type_hint}, "
                    "retry sans filtrage type..."
                )

                query_no_type = """
                MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias {
                    normalized: $normalized,
                    tenant_id: $tenant_id
                })
                RETURN
                    ont.entity_id AS entity_id,
                    ont.canonical_name AS canonical_name,
                    ont.entity_type AS entity_type
                LIMIT 1
                """

                result = session.run(query_no_type, {
                    "normalized": normalized_search,
                    "tenant_id": tenant_id
                })
                record = result.single()

                if record:
                    logger.info(
                        f"✅ Normalisé (type corrigé): '{raw_name}' → "
                        f"'{record['canonical_name']}' "
                        f"(type LLM={entity_type_hint} → type réel={record['entity_type']})"
                    )

                    return (
                        record["entity_id"],
                        record["canonical_name"],
                        record["entity_type"],
                        True
                    )

            # Vraiment pas trouvé → retourner brut
            logger.debug(
                f"⚠️ Entité non cataloguée: '{raw_name}' (type={entity_type_hint})"
            )

            return (
                None,
                raw_name.strip(),
                entity_type_hint,
                False  # is_cataloged
            )

    def get_entity_metadata(
        self,
        entity_id: str,
        tenant_id: str = "default"
    ) -> Optional[Dict]:
        """
        Récupère métadonnées complètes d'une entité cataloguée.

        Args:
            entity_id: ID entité catalogue
            tenant_id: Tenant ID

        Returns:
            Dict avec metadata ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (ont:OntologyEntity {
                    entity_id: $entity_id,
                    tenant_id: $tenant_id
                })
                RETURN ont
            """, {"entity_id": entity_id, "tenant_id": tenant_id})

            record = result.single()

            if record:
                ont = record["ont"]
                return dict(ont)

            return None

    def log_uncataloged_entity(
        self,
        raw_name: str,
        entity_type: str,
        tenant_id: str = "default"
    ):
        """
        Log entité non cataloguée pour review admin.

        OPTIONNEL : Peut créer node temporaire ou juste logger.

        Args:
            raw_name: Nom brut
            entity_type: Type suggéré
            tenant_id: Tenant ID
        """
        # Simple log pour maintenant
        logger.info(
            f"📝 Entité non cataloguée loggée: '{raw_name}' "
            f"(type={entity_type}, tenant={tenant_id})"
        )

        # OPTIONNEL : Créer node :UncatalogedEntity pour tracking
        # with self.driver.session() as session:
        #     session.run("""
        #         CREATE (u:UncatalogedEntity {
        #             raw_name: $raw_name,
        #             entity_type: $entity_type,
        #             tenant_id: $tenant_id,
        #             logged_at: datetime()
        #         })
        #     """, {
        #         "raw_name": raw_name,
        #         "entity_type": entity_type,
        #         "tenant_id": tenant_id
        #     })

    def close(self):
        """Ferme connexion Neo4j."""
        if self.driver:
            self.driver.close()


# Instance singleton (comme YAML actuel)
_normalizer_instance: Optional[EntityNormalizerNeo4j] = None


def get_entity_normalizer_neo4j(
    driver: GraphDatabase.driver = None
) -> EntityNormalizerNeo4j:
    """
    Retourne instance singleton du normalizer Neo4j.

    Args:
        driver: Neo4j driver (optionnel si déjà initialisé)

    Returns:
        EntityNormalizerNeo4j instance
    """
    global _normalizer_instance

    if _normalizer_instance is None:
        if driver is None:
            from knowbase.config.settings import get_settings
            settings = get_settings()

            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )

        _normalizer_instance = EntityNormalizerNeo4j(driver)

    return _normalizer_instance


__all__ = ["EntityNormalizerNeo4j", "get_entity_normalizer_neo4j"]
