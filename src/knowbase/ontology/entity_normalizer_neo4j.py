"""
EntityNormalizer basé sur Neo4j.

Remplace EntityNormalizer YAML pour normalisation via ontologies Neo4j.

P0.1 Sandbox Auto-Learning (2025-10-16):
- Filtrage entités pending par défaut (status != 'auto_learned_pending')
- Paramètre include_pending pour accès admin explicit

P1.2 Similarité Structurelle (2025-10-16):
- Fallback matching structurel si exact match échoue
- Analyse composants, acronymes, variantes typo
"""
from typing import Tuple, Optional, Dict, List
from neo4j import GraphDatabase
import logging

from knowbase.ontology.structural_similarity import enhanced_fuzzy_match

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
        tenant_id: str = "default",
        include_pending: bool = False
    ) -> Tuple[Optional[str], str, Optional[str], bool]:
        """
        Normalise nom d'entité via ontologie Neo4j.

        P0.1 Sandbox: Exclut entités pending par défaut (sauf si include_pending=True).

        Args:
            raw_name: Nom brut extrait par LLM
            entity_type_hint: Type suggéré par LLM (optionnel, pas contrainte)
            tenant_id: Tenant ID
            include_pending: Si True, inclut entités auto_learned_pending (défaut: False)

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
                "tenant_id": tenant_id,
                "include_pending": include_pending
            }

            # P0.1 Sandbox: Filtrer entités pending par défaut
            where_clauses = []

            if not include_pending:
                where_clauses.append("ont.status <> 'auto_learned_pending'")
                logger.debug(
                    f"[ONTOLOGY:Sandbox] Filtering pending entities for '{raw_name}' "
                    f"(include_pending={include_pending})"
                )

            # Filtrer par type si hint fourni (mais pas bloquer si pas trouvé)
            if entity_type_hint:
                where_clauses.append("ont.entity_type = $entity_type_hint")
                params["entity_type_hint"] = entity_type_hint

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
                logger.debug(
                    f"[ONTOLOGY:Sandbox] Query filters: {where_clauses}"
                )

            query += """
            RETURN
                ont.entity_id AS entity_id,
                ont.canonical_name AS canonical_name,
                ont.entity_type AS entity_type,
                ont.category AS category,
                ont.vendor AS vendor,
                ont.confidence AS confidence,
                ont.status AS status
            LIMIT 1
            """

            result = session.run(query, params)
            record = result.single()

            if record:
                # Trouvé dans ontologie
                logger.info(
                    f"[ONTOLOGY:Sandbox] ✅ FOUND & NORMALIZED: '{raw_name}' → '{record['canonical_name']}' "
                    f"(type={record['entity_type']}, id={record['entity_id']}, status={record.get('status', 'unknown')})"
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
                """

                # P0.1 Sandbox: Toujours filtrer pending (même en fallback)
                if not include_pending:
                    query_no_type += " WHERE ont.status <> 'auto_learned_pending'"

                query_no_type += """
                RETURN
                    ont.entity_id AS entity_id,
                    ont.canonical_name AS canonical_name,
                    ont.entity_type AS entity_type,
                    ont.status AS status
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

            # P1.2: Fallback matching structurel
            # Si exact match échoue, tenter matching structurel sur toutes les entités
            logger.debug(
                f"[ONTOLOGY:StructuralSimilarity] Exact match failed for '{raw_name}', "
                f"trying structural matching..."
            )

            structural_match = self._try_structural_match(
                raw_name=raw_name,
                entity_type_hint=entity_type_hint,
                tenant_id=tenant_id,
                include_pending=include_pending,
                session=session
            )

            if structural_match:
                entity_id, canonical_name, entity_type, match_score = structural_match
                logger.info(
                    f"[ONTOLOGY:StructuralSimilarity] ✅ STRUCTURAL MATCH: '{raw_name}' → '{canonical_name}' "
                    f"(score={match_score:.2f}, type={entity_type}, id={entity_id})"
                )
                return (entity_id, canonical_name, entity_type, True)

            # Vraiment pas trouvé → retourner brut (comportement normal, pas une erreur)
            logger.debug(
                f"[ONTOLOGY:Sandbox] NOT FOUND in ontology: '{raw_name}' "
                f"(type={entity_type_hint}, include_pending={include_pending}, tenant={tenant_id})"
            )

            return (
                None,
                raw_name.strip(),
                entity_type_hint,
                False  # is_cataloged
            )

    def _try_structural_match(
        self,
        raw_name: str,
        entity_type_hint: Optional[str],
        tenant_id: str,
        include_pending: bool,
        session
    ) -> Optional[Tuple[str, str, str, float]]:
        """
        Tente matching structurel sur toutes les entités cataloguées (P1.2).

        Utilisé en fallback quand exact match échoue.
        Récupère toutes les entités et compare structurellement.

        Args:
            raw_name: Nom brut à matcher
            entity_type_hint: Type suggéré (optionnel)
            tenant_id: Tenant ID
            include_pending: Inclure entités pending
            session: Session Neo4j

        Returns:
            Tuple (entity_id, canonical_name, entity_type, match_score) ou None
        """
        # Construire query pour récupérer candidats
        query = """
        MATCH (ont:OntologyEntity {tenant_id: $tenant_id})
        """

        where_clauses = []

        # Filtrer pending si nécessaire
        if not include_pending:
            where_clauses.append("ont.status <> 'auto_learned_pending'")

        # Filtrer par type si fourni (mais ne pas bloquer)
        if entity_type_hint:
            where_clauses.append("ont.entity_type = $entity_type_hint")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += """
        RETURN
            ont.entity_id AS entity_id,
            ont.canonical_name AS canonical_name,
            ont.entity_type AS entity_type
        LIMIT 100
        """

        params = {"tenant_id": tenant_id}
        if entity_type_hint:
            params["entity_type_hint"] = entity_type_hint

        result = session.run(query, params)
        candidates = list(result)

        if not candidates:
            logger.debug(
                f"[ONTOLOGY:StructuralSimilarity] No candidates found for structural matching "
                f"(tenant={tenant_id}, type={entity_type_hint})"
            )
            return None

        logger.debug(
            f"[ONTOLOGY:StructuralSimilarity] Comparing '{raw_name}' against {len(candidates)} candidates..."
        )

        # Comparer structurellement avec tous les candidats
        best_match = None
        best_score = 0.0

        for candidate in candidates:
            canonical_name = candidate["canonical_name"]

            # Matching structurel hybride
            is_match, score, method = enhanced_fuzzy_match(
                raw_name,
                canonical_name,
                textual_threshold=0.85,
                structural_threshold=0.75
            )

            if is_match and score > best_score:
                best_score = score
                best_match = (
                    candidate["entity_id"],
                    candidate["canonical_name"],
                    candidate["entity_type"],
                    score
                )

                logger.debug(
                    f"[ONTOLOGY:StructuralSimilarity] New best match: '{raw_name}' → '{canonical_name}' "
                    f"(score={score:.2f}, method={method})"
                )

        if best_match:
            logger.info(
                f"[ONTOLOGY:StructuralSimilarity] Best structural match found: "
                f"'{raw_name}' → '{best_match[1]}' (score={best_match[3]:.2f})"
            )
            return best_match

        logger.debug(
            f"[ONTOLOGY:StructuralSimilarity] No structural match found for '{raw_name}' "
            f"(checked {len(candidates)} candidates)"
        )

        return None

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
