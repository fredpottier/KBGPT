"""
Pass 2 Service - Orchestration des phases Pass 2 du Hybrid Anchor Model

Ce service intègre et réutilise le code existant:
- FineClassifier pour CLASSIFY_FINE
- RawAssertionWriter pour persister les relations extraites
- RelationConsolidator/ClaimConsolidator pour la consolidation
- CanonicalRelationWriter/CanonicalClaimWriter pour l'écriture

Endpoints exposés via /api/admin/pass2

Author: OSMOSE Phase 2
Date: 2024-12
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from knowbase.ingestion.pass2_orchestrator import (
    Pass2Orchestrator,
    Pass2Mode,
    Pass2Phase,
    get_pass2_orchestrator,
)
from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer, RawAssertionWriter
from knowbase.relations.claim_consolidator import get_claim_consolidator
from knowbase.relations.relation_consolidator import get_relation_consolidator
from knowbase.relations.canonical_claim_writer import get_canonical_claim_writer
from knowbase.relations.canonical_relation_writer import get_canonical_relation_writer
from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.relations.types import RelationType, RawAssertionFlags

logger = logging.getLogger(__name__)


@dataclass
class Pass2Status:
    """Statut global de Pass 2."""

    # Statistiques Neo4j
    proto_concepts: int = 0
    canonical_concepts: int = 0
    raw_assertions: int = 0
    raw_claims: int = 0
    canonical_relations: int = 0
    canonical_claims: int = 0

    # Jobs en attente
    pending_jobs: int = 0
    running_jobs: int = 0

    # Dernière exécution
    last_run: Optional[datetime] = None
    last_run_duration_s: Optional[float] = None


@dataclass
class Pass2Result:
    """Résultat d'exécution Pass 2."""

    success: bool = True
    phase: str = ""

    # Statistiques
    items_processed: int = 0
    items_created: int = 0
    items_updated: int = 0

    # Timing
    execution_time_ms: float = 0

    # Erreurs
    errors: List[str] = field(default_factory=list)

    # Détails par phase
    details: Dict[str, Any] = field(default_factory=dict)


class Pass2Service:
    """
    Service Pass 2 - Orchestration des enrichissements post-ingestion.

    Phases disponibles:
    1. CLASSIFY_FINE - Classification LLM fine-grained des concepts
    2. ENRICH_RELATIONS - Extraction relations cross-segment + persistence
    3. CONSOLIDATE_CLAIMS - Consolidation RawClaims → CanonicalClaims
    4. CONSOLIDATE_RELATIONS - Consolidation RawAssertions → CanonicalRelations
    5. CROSS_DOC - Consolidation corpus-level (TODO)
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service.

        Args:
            tenant_id: ID tenant pour isolation
        """
        self.tenant_id = tenant_id

        # Neo4j client
        settings = get_settings()
        self._neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        # Orchestrateur Pass 2 existant
        self._orchestrator = get_pass2_orchestrator(tenant_id)

        logger.info(f"[Pass2Service] Initialized for tenant={tenant_id}")

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Exécute une requête Cypher."""
        if not self._neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self._neo4j_client, 'database', 'neo4j')
        with self._neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def get_status(self) -> Pass2Status:
        """
        Récupère le statut global de Pass 2.

        Returns:
            Pass2Status avec statistiques
        """
        status = Pass2Status()

        # Compter les nœuds Neo4j
        queries = {
            "proto_concepts": "MATCH (p:ProtoConcept {tenant_id: $tenant_id}) RETURN count(p) AS count",
            "canonical_concepts": "MATCH (c:CanonicalConcept {tenant_id: $tenant_id}) RETURN count(c) AS count",
            "raw_assertions": "MATCH (ra:RawAssertion {tenant_id: $tenant_id}) RETURN count(ra) AS count",
            "raw_claims": "MATCH (rc:RawClaim {tenant_id: $tenant_id}) RETURN count(rc) AS count",
            "canonical_relations": "MATCH (cr:CanonicalRelation {tenant_id: $tenant_id}) RETURN count(cr) AS count",
            "canonical_claims": "MATCH (cc:CanonicalClaim {tenant_id: $tenant_id}) RETURN count(cc) AS count",
        }

        for key, query in queries.items():
            try:
                result = self._execute_query(query, {"tenant_id": self.tenant_id})
                setattr(status, key, result[0]["count"] if result else 0)
            except Exception as e:
                logger.error(f"[Pass2Service] Error counting {key}: {e}")

        # Jobs en attente
        status.pending_jobs = self._orchestrator.queue_size
        status.running_jobs = len(self._orchestrator.running_jobs)

        return status

    async def run_classify_fine(
        self,
        document_id: Optional[str] = None,
        limit: int = 100
    ) -> Pass2Result:
        """
        Exécute CLASSIFY_FINE sur les concepts.

        Affine les types heuristiques avec classification LLM.

        Args:
            document_id: Filtrer par document (optionnel)
            limit: Nombre max de concepts à traiter

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="CLASSIFY_FINE")

        try:
            # Récupérer concepts à classifier
            where_clause = "WHERE c.tenant_id = $tenant_id"
            if document_id:
                where_clause += " AND c.source_doc_id = $doc_id"

            query = f"""
            MATCH (c:CanonicalConcept)
            {where_clause}
            AND (c.type_fine IS NULL OR c.type_fine = '')
            RETURN c.canonical_id AS id, c.label AS label,
                   c.type_heuristic AS type_heuristic, c.definition AS definition
            LIMIT $limit
            """

            params = {"tenant_id": self.tenant_id, "limit": limit}
            if document_id:
                params["doc_id"] = document_id

            concepts = self._execute_query(query, params)
            result.items_processed = len(concepts)

            if not concepts:
                result.details["message"] = "No concepts to classify"
                return result

            # Convertir en format attendu par l'orchestrateur
            concept_dicts = [
                {
                    "id": c["id"],
                    "label": c["label"],
                    "type_heuristic": c.get("type_heuristic"),
                    "definition": c.get("definition", "")
                }
                for c in concepts
            ]

            # Créer un job fictif pour réutiliser le code existant
            from knowbase.ingestion.pass2_orchestrator import Pass2Job, Pass2Stats
            import uuid

            job = Pass2Job(
                job_id=f"p2_manual_{uuid.uuid4().hex[:8]}",
                document_id=document_id or "all",
                tenant_id=self.tenant_id,
                mode=Pass2Mode.INLINE,
                phases=[Pass2Phase.CLASSIFY_FINE],
                concepts=concept_dicts
            )

            stats = Pass2Stats(document_id=job.document_id)
            await self._orchestrator._phase_classify_fine(job, stats)

            # Persister les changements dans Neo4j
            updates = 0
            for concept in job.concepts:
                if concept.get("type_fine"):
                    update_query = """
                    MATCH (c:CanonicalConcept {canonical_id: $id, tenant_id: $tenant_id})
                    SET c.type_fine = $type_fine,
                        c.type_fine_confidence = $confidence,
                        c.type_fine_justification = $justification
                    """
                    self._execute_query(update_query, {
                        "id": concept["id"],
                        "tenant_id": self.tenant_id,
                        "type_fine": concept.get("type_fine"),
                        "confidence": concept.get("type_fine_confidence", 0),
                        "justification": concept.get("type_fine_justification", "")
                    })
                    updates += 1

            result.items_updated = updates
            result.details = {
                "concepts_processed": stats.classify_fine_count,
                "type_changes": stats.classify_fine_changes
            }

        except Exception as e:
            logger.error(f"[Pass2Service] CLASSIFY_FINE failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    async def run_enrich_relations(
        self,
        document_id: Optional[str] = None,
        max_pairs: int = 50
    ) -> Pass2Result:
        """
        Exécute ENRICH_RELATIONS avec persistence.

        Détecte relations cross-segment et les persiste en RawAssertions.

        Args:
            document_id: Filtrer par document (optionnel)
            max_pairs: Nombre max de paires à analyser

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="ENRICH_RELATIONS")

        try:
            # Récupérer concepts par section
            where_clause = "WHERE c.tenant_id = $tenant_id"
            if document_id:
                where_clause += " AND c.source_doc_id = $doc_id"

            query = f"""
            MATCH (c:CanonicalConcept)
            {where_clause}
            RETURN c.canonical_id AS id, c.label AS label,
                   c.type_fine AS type_fine, c.type_heuristic AS type_heuristic,
                   c.section_id AS section_id, c.source_doc_id AS doc_id
            """

            params = {"tenant_id": self.tenant_id}
            if document_id:
                params["doc_id"] = document_id

            concepts = self._execute_query(query, params)

            if not concepts:
                result.details["message"] = "No concepts found"
                return result

            # Générer paires cross-section
            pairs = self._generate_cross_section_pairs(concepts, max_pairs)
            result.items_processed = len(pairs)

            if not pairs:
                result.details["message"] = "No cross-section pairs"
                return result

            # Détecter relations via LLM
            llm_router = get_llm_router()
            relations = await self._detect_relations_llm(pairs, llm_router)

            # Persister en RawAssertions
            writer = get_raw_assertion_writer(self.tenant_id)
            written_count = 0

            for rel in relations:
                if rel.get("confidence", 0) < 0.6:
                    continue

                # Mapper predicate vers RelationType
                relation_type = self._map_predicate_to_type(rel.get("predicate", ""))

                # Récupérer les concepts sources pour les surface forms
                source_concept = next((c for c in concepts if c["id"] == rel["source_id"]), None)
                target_concept = next((c for c in concepts if c["id"] == rel["target_id"]), None)

                if not source_concept or not target_concept:
                    continue

                assertion_id = writer.write_assertion(
                    subject_concept_id=rel["source_id"],
                    object_concept_id=rel["target_id"],
                    predicate_raw=rel.get("predicate", "ASSOCIATED_WITH"),
                    evidence_text=f"Cross-section relation detected: {source_concept['label']} → {target_concept['label']}",
                    source_doc_id=source_concept.get("doc_id", "unknown"),
                    source_chunk_id=f"pass2_enrich_{start_time}",
                    confidence=rel.get("confidence", 0.7),
                    subject_surface_form=source_concept.get("label"),
                    object_surface_form=target_concept.get("label"),
                    relation_type=relation_type,
                    type_confidence=rel.get("confidence", 0.7),
                )

                if assertion_id:
                    written_count += 1

            result.items_created = written_count
            result.details = {
                "pairs_analyzed": len(pairs),
                "relations_detected": len(relations),
                "raw_assertions_created": written_count,
                "writer_stats": writer.get_stats()
            }

        except Exception as e:
            logger.error(f"[Pass2Service] ENRICH_RELATIONS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def _generate_cross_section_pairs(
        self,
        concepts: List[Dict[str, Any]],
        max_pairs: int
    ) -> List[Dict[str, Any]]:
        """Génère paires de concepts de sections différentes."""
        by_section: Dict[str, List[Dict]] = {}

        for c in concepts:
            section = c.get("section_id") or "default"
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(c)

        pairs = []
        sections = list(by_section.keys())

        for i, s1 in enumerate(sections):
            for s2 in sections[i + 1:]:
                for c1 in by_section[s1][:5]:
                    for c2 in by_section[s2][:5]:
                        pairs.append({
                            "concept_a": {
                                "id": c1.get("id"),
                                "label": c1.get("label"),
                                "type": c1.get("type_fine") or c1.get("type_heuristic"),
                            },
                            "concept_b": {
                                "id": c2.get("id"),
                                "label": c2.get("label"),
                                "type": c2.get("type_fine") or c2.get("type_heuristic"),
                            }
                        })
                        if len(pairs) >= max_pairs:
                            return pairs

        return pairs

    async def _detect_relations_llm(
        self,
        pairs: List[Dict[str, Any]],
        llm_router
    ) -> List[Dict[str, Any]]:
        """Détecte relations via LLM."""
        import json
        import re

        if not pairs:
            return []

        pairs_json = json.dumps(pairs[:30], ensure_ascii=False, indent=2)

        prompt = f"""Analyze these concept pairs and identify semantic relations.

## Concept Pairs
{pairs_json}

## Valid Relation Types
- REQUIRES, USES, ENABLES, INTEGRATES_WITH
- PART_OF, SUBTYPE_OF, EXTENDS
- VERSION_OF, REPLACES, DEPRECATES, PRECEDES
- ALTERNATIVE_TO, APPLIES_TO
- CAUSES, PREVENTS, CONFLICTS_WITH
- ASSOCIATED_WITH (weak link)

## Instructions
1. For each pair with a clear semantic relation, output it
2. Only include relations with confidence >= 0.6
3. Use one of the valid relation types as predicate

Return JSON: {{"relations": [{{"source_id": "...", "target_id": "...", "predicate": "REQUIRES", "confidence": 0.85}}]}}"""

        try:
            response = await llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": "You are OSMOSE Pass 2 Relation Detector. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            text = response.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return data.get("relations", [])
        except Exception as e:
            logger.error(f"[Pass2Service] LLM relation detection failed: {e}")

        return []

    def _map_predicate_to_type(self, predicate: str) -> RelationType:
        """Mappe un predicate vers un RelationType."""
        predicate_upper = predicate.upper().replace(" ", "_")

        try:
            return RelationType(predicate_upper)
        except ValueError:
            # Mapping des variantes courantes
            mappings = {
                "DEPENDS_ON": RelationType.REQUIRES,
                "NEEDS": RelationType.REQUIRES,
                "CONTAINS": RelationType.PART_OF,
                "HAS": RelationType.PART_OF,
                "IS_A": RelationType.SUBTYPE_OF,
                "TYPE_OF": RelationType.SUBTYPE_OF,
                "IMPLEMENTS": RelationType.EXTENDS,
                "ACTIVATES": RelationType.ENABLES,
                "CONNECTS_TO": RelationType.INTEGRATES_WITH,
                "WORKS_WITH": RelationType.INTEGRATES_WITH,
                "SUCCEEDS": RelationType.REPLACES,
                "OBSOLETES": RelationType.DEPRECATES,
                "COMES_AFTER": RelationType.PRECEDES,
                "FOLLOWED_BY": RelationType.PRECEDES,
                "COMPETES_WITH": RelationType.ALTERNATIVE_TO,
                "SIMILAR_TO": RelationType.ASSOCIATED_WITH,
                "RELATED_TO": RelationType.ASSOCIATED_WITH,
            }
            return mappings.get(predicate_upper, RelationType.ASSOCIATED_WITH)

    def run_consolidate_claims(
        self,
        subject_concept_id: Optional[str] = None,
        claim_type: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> Pass2Result:
        """
        Exécute consolidation Claims.

        Regroupe RawClaims → CanonicalClaims avec calcul maturité.

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="CONSOLIDATE_CLAIMS")

        try:
            # Utiliser le code existant
            consolidator = get_claim_consolidator()
            canonical_claims = consolidator.consolidate_all(
                subject_concept_id=subject_concept_id,
                claim_type=claim_type,
                doc_id=doc_id
            )

            result.items_processed = len(canonical_claims)

            if canonical_claims:
                writer = get_canonical_claim_writer()
                writer.write_batch(canonical_claims)
                result.items_created = len(canonical_claims)

            stats = consolidator.get_stats()
            result.details = {
                "groups_processed": stats.get("groups_processed", 0),
                "validated": stats.get("validated", 0),
                "conflicts_detected": stats.get("conflicts_detected", 0),
                "supersessions_detected": stats.get("supersessions_detected", 0)
            }

        except Exception as e:
            logger.error(f"[Pass2Service] CONSOLIDATE_CLAIMS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def run_consolidate_relations(
        self,
        subject_concept_id: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> Pass2Result:
        """
        Exécute consolidation Relations.

        Regroupe RawAssertions → CanonicalRelations avec typed edges.

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="CONSOLIDATE_RELATIONS")

        try:
            # Utiliser le code existant
            consolidator = get_relation_consolidator()
            canonical_relations = consolidator.consolidate_all(
                subject_concept_id=subject_concept_id,
                doc_id=doc_id
            )

            result.items_processed = len(canonical_relations)

            if canonical_relations:
                writer = get_canonical_relation_writer()
                writer.write_batch(canonical_relations)
                result.items_created = len(canonical_relations)

            stats = consolidator.get_stats()
            result.details = {
                "groups_processed": stats.get("groups_processed", 0),
                "validated": stats.get("validated", 0),
                "ambiguous": stats.get("ambiguous", 0)
            }

        except Exception as e:
            logger.error(f"[Pass2Service] CONSOLIDATE_RELATIONS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    async def run_full_pass2(
        self,
        document_id: Optional[str] = None,
        skip_classify: bool = False,
        skip_enrich: bool = False,
        skip_consolidate: bool = False
    ) -> Dict[str, Pass2Result]:
        """
        Exécute Pass 2 complet.

        Phases dans l'ordre:
        1. CLASSIFY_FINE (optionnel)
        2. ENRICH_RELATIONS (optionnel)
        3. CONSOLIDATE_CLAIMS
        4. CONSOLIDATE_RELATIONS

        Args:
            document_id: Filtrer par document
            skip_classify: Ignorer CLASSIFY_FINE
            skip_enrich: Ignorer ENRICH_RELATIONS
            skip_consolidate: Ignorer consolidation

        Returns:
            Dict avec résultats par phase
        """
        results = {}

        if not skip_classify:
            results["classify_fine"] = await self.run_classify_fine(document_id)

        if not skip_enrich:
            results["enrich_relations"] = await self.run_enrich_relations(document_id)

        if not skip_consolidate:
            results["consolidate_claims"] = self.run_consolidate_claims()
            results["consolidate_relations"] = self.run_consolidate_relations()

        return results


# Singleton
_service_instance: Optional[Pass2Service] = None


def get_pass2_service(tenant_id: str = "default") -> Pass2Service:
    """Récupère l'instance singleton du service."""
    global _service_instance
    if _service_instance is None or _service_instance.tenant_id != tenant_id:
        _service_instance = Pass2Service(tenant_id=tenant_id)
    return _service_instance
