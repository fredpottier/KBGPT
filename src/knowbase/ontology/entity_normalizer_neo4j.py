"""
EntityNormalizer basé sur Neo4j.

Remplace EntityNormalizer YAML pour normalisation via ontologies Neo4j.

P0.1 Sandbox Auto-Learning (2025-10-16):
- Filtrage entités pending par défaut (status != 'auto_learned_pending')
- Paramètre include_pending pour accès admin explicit

P1.2 Similarité Structurelle (2025-10-16):
- Fallback matching structurel si exact match échoue
- Analyse composants, acronymes, variantes typo

Phase 1.8 LLM-as-a-Judge (2025-12-17):
- Validation LLM pour clusters d'entités similaires
- Inspiré par KGGen Section 3.3 (Stanford/FAR AI)
- Réduit faux positifs de clustering de ~47%
"""
from typing import Tuple, Optional, Dict, List, Any
from neo4j import GraphDatabase
import logging
import json

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

    # =========================================================================
    # Phase 1.8 - LLM-as-a-Judge Validation (Inspired by KGGen Section 3.3)
    # =========================================================================

    async def validate_cluster_via_llm(
        self,
        concept_a: Dict[str, Any],
        concept_b: Dict[str, Any],
        threshold: float = 0.85
    ) -> Tuple[bool, float, str]:
        """
        Valide si deux concepts doivent être fusionnés via LLM-as-a-Judge.

        Inspiré par KGGen Section 3.3 (Stanford/FAR AI) qui utilise une validation
        LLM binaire à chaque étape de clustering pour réduire les faux positifs.

        Args:
            concept_a: Premier concept {name, type, aliases, context}
            concept_b: Second concept {name, type, aliases, context}
            threshold: Seuil de confiance pour merger (default 0.85)

        Returns:
            Tuple (should_merge, confidence, reason)
            - should_merge: True si les concepts sont équivalents
            - confidence: Score de confiance de la décision
            - reason: Explication de la décision
        """
        from knowbase.common.llm_router import get_llm_router, TaskType
        from knowbase.semantic.extraction.prompts import get_llm_judge_prompt

        try:
            # Obtenir le router LLM
            llm_router = get_llm_router()

            # Construire le prompt
            prompts = get_llm_judge_prompt(concept_a, concept_b)

            # Appel LLM (utiliser SMALL pour économiser le budget)
            response = await llm_router.generate_structured(
                task_type=TaskType.CONCEPT_EXTRACTION,  # Réutiliser config extraction
                system_prompt=prompts["system_prompt"],
                user_prompt=prompts["user_prompt"],
                response_format={"type": "json_object"}
            )

            # Parser la réponse
            result = json.loads(response.content)

            should_merge = result.get("should_merge", False)
            confidence = float(result.get("confidence", 0.5))
            reason = result.get("reason", "No reason provided")

            # Appliquer le seuil
            if should_merge and confidence >= threshold:
                logger.info(
                    f"[PHASE1.8:LLM-Judge] ✅ MERGE APPROVED: "
                    f"'{concept_a.get('name')}' ≡ '{concept_b.get('name')}' "
                    f"(confidence={confidence:.2f}, reason={reason[:50]}...)"
                )
                return (True, confidence, reason)
            elif should_merge and confidence < threshold:
                logger.info(
                    f"[PHASE1.8:LLM-Judge] ⚠️ MERGE REJECTED (low confidence): "
                    f"'{concept_a.get('name')}' vs '{concept_b.get('name')}' "
                    f"(confidence={confidence:.2f} < threshold={threshold})"
                )
                return (False, confidence, f"Confidence too low: {confidence:.2f} < {threshold}")
            else:
                logger.info(
                    f"[PHASE1.8:LLM-Judge] ❌ MERGE REJECTED: "
                    f"'{concept_a.get('name')}' ≠ '{concept_b.get('name')}' "
                    f"(reason={reason[:50]}...)"
                )
                return (False, confidence, reason)

        except json.JSONDecodeError as e:
            logger.error(f"[PHASE1.8:LLM-Judge] JSON parse error: {e}")
            return (False, 0.0, f"JSON parse error: {e}")
        except Exception as e:
            logger.error(f"[PHASE1.8:LLM-Judge] Error: {e}")
            # Fallback conservateur: ne pas fusionner en cas d'erreur
            return (False, 0.0, f"LLM validation error: {e}")

    async def validate_cluster_batch(
        self,
        cluster_candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]],
        threshold: float = 0.85
    ) -> List[Tuple[bool, float, str]]:
        """
        Valide un batch de paires de concepts via LLM-as-a-Judge.

        Utile pour valider plusieurs paires en parallèle.

        Args:
            cluster_candidates: Liste de tuples (concept_a, concept_b)
            threshold: Seuil de confiance pour merger

        Returns:
            Liste de tuples (should_merge, confidence, reason)
        """
        import asyncio

        # Limiter la parallélisation pour éviter rate limits
        max_concurrent = 5
        semaphore = asyncio.Semaphore(max_concurrent)

        async def validate_with_limit(pair: Tuple[Dict[str, Any], Dict[str, Any]]):
            async with semaphore:
                return await self.validate_cluster_via_llm(pair[0], pair[1], threshold)

        # Exécuter en parallèle avec limite
        tasks = [validate_with_limit(pair) for pair in cluster_candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Gérer les exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[PHASE1.8:LLM-Judge] Batch item {i} failed: {result}")
                final_results.append((False, 0.0, f"Exception: {result}"))
            else:
                final_results.append(result)

        return final_results

    def should_use_llm_judge(
        self,
        similarity_score: float,
        concept_type_match: bool,
        min_similarity: float = 0.75,
        max_similarity: float = 0.95
    ) -> bool:
        """
        Détermine si la validation LLM-as-a-Judge est nécessaire.

        Appelé avant validate_cluster_via_llm pour économiser les appels LLM.

        Args:
            similarity_score: Score de similarité entre concepts
            concept_type_match: True si les types correspondent
            min_similarity: Seuil min pour considérer LLM (default 0.75)
            max_similarity: Seuil max (au-dessus = merge automatique, default 0.95)

        Returns:
            True si LLM validation est recommandée
        """
        # Cas 1: Similarité trop basse → pas de merge, pas de LLM
        if similarity_score < min_similarity:
            logger.debug(
                f"[PHASE1.8:LLM-Judge] Skip validation: similarity {similarity_score:.2f} < {min_similarity}"
            )
            return False

        # Cas 2: Similarité très haute ET types matchent → merge auto, pas de LLM
        if similarity_score >= max_similarity and concept_type_match:
            logger.debug(
                f"[PHASE1.8:LLM-Judge] Auto-merge: similarity {similarity_score:.2f} >= {max_similarity}"
            )
            return False

        # Cas 3: Zone grise → LLM validation recommandée
        logger.debug(
            f"[PHASE1.8:LLM-Judge] Validation needed: similarity {similarity_score:.2f} in [{min_similarity}, {max_similarity}]"
        )
        return True

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
