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
    DocumentPhase,
    CorpusPhase,
    get_pass2_orchestrator,
)
from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer, RawAssertionWriter
from knowbase.relations.claim_consolidator import get_claim_consolidator
from knowbase.relations.relation_consolidator import get_relation_consolidator
from knowbase.relations.canonical_claim_writer import get_canonical_claim_writer
from knowbase.relations.canonical_relation_writer import get_canonical_relation_writer
from knowbase.consolidation import get_corpus_er_pipeline, CorpusERConfig
from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.relations.types import RelationType, RawAssertionFlags
from knowbase.relations.structural_topic_extractor import process_document_topics
from knowbase.relations.semantic_consolidation_pass3 import run_pass3_consolidation

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

    # Entity Resolution stats
    er_standalone_concepts: int = 0
    er_merged_concepts: int = 0
    er_pending_proposals: int = 0

    # Jobs en attente
    pending_jobs: int = 0
    running_jobs: int = 0

    # Dernière exécution
    last_run: Optional[datetime] = None
    last_run_duration_s: Optional[float] = None


@dataclass
class EnrichmentStatus:
    """
    Statut étendu pour la page Enrichment.

    ADR 2026-01-07: Nomenclature Document-level vs Corpus-level.
    """
    # === DOCUMENT-LEVEL OUTPUT ===

    # Pass 1 output
    proto_concepts: int = 0
    canonical_concepts: int = 0
    mentioned_in_count: int = 0

    # Pass 2a output (Structural Topics)
    topics_count: int = 0
    has_topic_count: int = 0
    covers_count: int = 0

    # Pass 2b output
    raw_assertions: int = 0

    # Pass 3 output (Semantic Consolidation)
    proven_relations: int = 0  # Relations avec evidence_context_ids non vide

    # === CORPUS-LEVEL OUTPUT (Pass 4) ===

    # Pass 4a: Entity Resolution
    er_standalone_concepts: int = 0
    er_merged_concepts: int = 0
    er_pending_proposals: int = 0

    # Pass 4b: Corpus Links
    co_occurs_relations: int = 0  # CO_OCCURS_IN_CORPUS count

    # === JOBS ===
    pending_jobs: int = 0
    running_jobs: int = 0


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
    Service Enrichment - Orchestration des phases Document + Corpus level.

    ADR 2026-01-07: Nomenclature validée Claude + ChatGPT.

    === DOCUMENT-LEVEL PHASES ===
    Pass 2a: STRUCTURAL_TOPICS - Topics H1/H2 + COVERS (scope)
    Pass 2b: CLASSIFY_FINE - Classification LLM fine-grained
    Pass 2b: ENRICH_RELATIONS - Relations candidates (RawAssertions)
    Pass 3:  SEMANTIC_CONSOLIDATION - Relations prouvées (evidence_quote)

    === CORPUS-LEVEL PHASES ===
    Pass 4a: ENTITY_RESOLUTION - Merge doublons cross-doc (PATCH-ER)
    Pass 4b: CORPUS_LINKS - CO_OCCURS_IN_CORPUS (PATCH-LINK)
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

        # Entity Resolution stats
        er_query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WITH count(c) AS total,
             sum(CASE WHEN c.er_status = 'STANDALONE' OR c.er_status IS NULL THEN 1 ELSE 0 END) AS standalone,
             sum(CASE WHEN c.er_status = 'MERGED' THEN 1 ELSE 0 END) AS merged
        OPTIONAL MATCH (p:MergeProposal {tenant_id: $tenant_id})
        WHERE p.applied = false OR p.applied IS NULL
        WITH total, standalone, merged, count(p) AS pending
        RETURN standalone, merged, pending
        """
        try:
            result = self._execute_query(er_query, {"tenant_id": self.tenant_id})
            if result:
                status.er_standalone_concepts = result[0].get("standalone", 0)
                status.er_merged_concepts = result[0].get("merged", 0)
                status.er_pending_proposals = result[0].get("pending", 0)
        except Exception as e:
            logger.error(f"[Pass2Service] Error counting ER stats: {e}")

        # Jobs en attente
        status.pending_jobs = self._orchestrator.queue_size
        status.running_jobs = len(self._orchestrator.running_jobs)

        return status

    async def run_classify_fine(
        self,
        document_id: Optional[str] = None,
        limit: int = 500,
        process_all: bool = False
    ) -> Pass2Result:
        """
        Exécute CLASSIFY_FINE sur les concepts.

        Affine les types heuristiques avec classification LLM.

        Args:
            document_id: Filtrer par document (optionnel)
            limit: Nombre de concepts par batch (défaut: 500)
            process_all: Si True, boucle jusqu'à traiter TOUS les concepts

        Returns:
            Pass2Result avec statistiques cumulées
        """
        start_time = time.time()
        result = Pass2Result(phase="CLASSIFY_FINE")

        total_processed = 0
        total_updated = 0
        total_type_changes = 0
        iteration = 0
        max_iterations = 1000  # Sécurité anti-boucle infinie

        try:
            from knowbase.ingestion.pass2_orchestrator import Pass2Job, Pass2Stats
            import uuid

            while iteration < max_iterations:
                iteration += 1

                # Récupérer concepts à classifier
                where_clause = "WHERE c.tenant_id = $tenant_id"
                if document_id:
                    where_clause += " AND c.source_doc_id = $doc_id"

                # FIXED 2024-12-31: Utiliser les bons noms de propriétés Neo4j
                query = f"""
                MATCH (c:CanonicalConcept)
                {where_clause}
                AND (c.type_fine IS NULL OR c.type_fine = '' OR c.type_fine_justification = 'Fallback to heuristic type')
                RETURN c.canonical_id AS id,
                       c.canonical_name AS label,
                       c.type_fine AS type_heuristic,
                       c.unified_definition AS definition
                LIMIT $limit
                """

                params = {"tenant_id": self.tenant_id, "limit": limit}
                if document_id:
                    params["doc_id"] = document_id

                concepts = self._execute_query(query, params)

                if not concepts:
                    if iteration == 1:
                        result.details["message"] = "No concepts to classify"
                    break

                logger.info(f"[Pass2Service] CLASSIFY_FINE iteration {iteration}: {len(concepts)} concepts")

                # Convertir en format attendu par l'orchestrateur
                concept_dicts = [
                    {
                        "id": c["id"],
                        "label": c.get("label") or "",
                        "type_heuristic": c.get("type_heuristic") or "abstract",
                        "definition": c.get("definition") or ""
                    }
                    for c in concepts
                ]

                # Créer un job pour ce batch
                job = Pass2Job(
                    job_id=f"p2_classify_{uuid.uuid4().hex[:8]}",
                    document_id=document_id or "all",
                    tenant_id=self.tenant_id,
                    mode=Pass2Mode.INLINE,
                    phases=[Pass2Phase.CLASSIFY_FINE],
                    concepts=concept_dicts
                )

                stats = Pass2Stats(document_id=job.document_id)
                await self._orchestrator._phase_classify_fine(job, stats)

                # Persister les changements dans Neo4j
                batch_updates = 0
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
                        batch_updates += 1

                total_processed += len(concepts)
                total_updated += batch_updates
                total_type_changes += stats.classify_fine_changes

                logger.info(
                    f"[Pass2Service] CLASSIFY_FINE iteration {iteration} done: "
                    f"{batch_updates} updated, {stats.classify_fine_changes} type changes"
                )

                # Si process_all=False, ne faire qu'une seule itération
                if not process_all:
                    break

            result.items_processed = total_processed
            result.items_updated = total_updated
            result.details = {
                "iterations": iteration,
                "concepts_processed": total_processed,
                "type_changes": total_type_changes,
                "process_all": process_all
            }

        except Exception as e:
            logger.error(f"[Pass2Service] CLASSIFY_FINE failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[Pass2Service] CLASSIFY_FINE complete: {total_processed} concepts, "
            f"{total_updated} updated, {result.execution_time_ms/1000:.1f}s"
        )
        return result

    async def run_enrich_relations(
        self,
        document_id: Optional[str] = None,
        max_relations_per_doc: int = 150
    ) -> Pass2Result:
        """
        ADR-Compliant ENRICH_RELATIONS using segment-first extraction.

        Extrait relations au niveau SEGMENT avec:
        - Scoring segments (anchor density, concept diversity, section type)
        - Budgets stricts: 8 relations/segment, 150/document
        - Evidence obligatoire: quote + chunk_id + span
        - 12 prédicats fermés uniquement
        - Fuzzy matching >= 70%

        ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

        Args:
            document_id: Document à traiter (requis pour extraction segment)
            max_relations_per_doc: Budget max par document (défaut: 150)

        Returns:
            Pass2Result avec statistiques et observabilité
        """
        from knowbase.relations.segment_window_relation_extractor import (
            extract_document_relations,
            persist_relations
        )

        start_time = time.time()
        result = Pass2Result(phase="ENRICH_RELATIONS")

        try:
            if not document_id:
                # Si pas de document_id, récupérer les documents à traiter
                doc_ids = self._get_documents_needing_enrichment()
                if not doc_ids:
                    result.details["message"] = "No documents to enrich"
                    result.success = True
                    return result
            else:
                doc_ids = [document_id]

            total_relations = 0
            total_segments = 0
            all_observability = []

            for doc_id in doc_ids:
                # Extraire avec scoring segments + budgets ADR
                relations, observability = await extract_document_relations(
                    document_id=doc_id,
                    tenant_id=self.tenant_id,
                    max_per_document=max_relations_per_doc
                )

                # Persister avec guardrails ADR + Verify-to-Persist pour conflicts_with
                written = await persist_relations(relations, doc_id, self.tenant_id)

                total_relations += written
                total_segments += len(observability)
                all_observability.extend(observability)

                # Log observabilité par segment
                for obs in observability:
                    logger.info(
                        f"[OSMOSE:Pass2] Segment {obs.segment_id}: "
                        f"proposed={obs.relations_proposed}, "
                        f"validated={obs.relations_validated}, "
                        f"rejected={obs.relations_rejected}, "
                        f"fuzzy_rate={obs.fuzzy_match_rate:.1%}"
                    )

            result.items_processed = total_segments
            result.items_created = total_relations
            result.success = True
            result.details = {
                "documents_processed": len(doc_ids),
                "segments_analyzed": total_segments,
                "relations_created": total_relations,
                "budget_per_doc": max_relations_per_doc,
                "observability_summary": {
                    "total_proposed": sum(o.relations_proposed for o in all_observability),
                    "total_validated": sum(o.relations_validated for o in all_observability),
                    "total_rejected": sum(o.relations_rejected for o in all_observability),
                }
            }

        except Exception as e:
            logger.error(f"[Pass2Service] ENRICH_RELATIONS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[Pass2Service] ENRICH_RELATIONS complete: "
            f"{result.items_created} relations from {result.items_processed} segments, "
            f"{result.execution_time_ms/1000:.1f}s"
        )
        return result

    def _get_documents_needing_enrichment(self) -> List[str]:
        """
        Récupère les documents qui n'ont pas encore été enrichis par Pass 2.

        Exclut les documents qui ont déjà des RawAssertions pour éviter
        les doublons (RawAssertionWriter utilise CREATE, pas MERGE).
        """
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        WHERE d.document_id IS NOT NULL

        // Compter les RawAssertions existantes pour ce document
        OPTIONAL MATCH (ra:RawAssertion {tenant_id: $tenant_id, source_doc_id: d.document_id})
        WITH d, count(ra) AS existing_relations

        // Ne retourner que les documents sans RawAssertions
        WHERE existing_relations = 0

        RETURN d.document_id AS doc_id
        ORDER BY d.document_id
        LIMIT 100
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})
        doc_ids = [r["doc_id"] for r in results if r.get("doc_id")]

        logger.info(f"[Pass2Service] Found {len(doc_ids)} documents needing enrichment (excluding already processed)")
        return doc_ids

    def _generate_cross_section_pairs(
        self,
        concepts: List[Dict[str, Any]],
        max_pairs: int
    ) -> List[Dict[str, Any]]:
        """
        Génère paires de concepts de sections différentes.

        Stratégie: échantillonnage diversifié pour couvrir le corpus.
        """
        import random

        by_section: Dict[str, List[Dict]] = {}

        for c in concepts:
            section = c.get("section_id") or "default"
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(c)

        pairs = []
        sections = list(by_section.keys())

        # Limite par section basée sur le nombre total de sections
        # Pour avoir une bonne couverture avec max_pairs paires
        concepts_per_section = max(3, min(10, int((max_pairs / len(sections)) ** 0.5))) if sections else 5

        logger.debug(f"[Pass2Service] Generating pairs: {len(sections)} sections, {concepts_per_section} concepts/section max")

        for i, s1 in enumerate(sections):
            for s2 in sections[i + 1:]:
                # Échantillonner aléatoirement pour diversité
                sample1 = by_section[s1][:concepts_per_section] if len(by_section[s1]) <= concepts_per_section else random.sample(by_section[s1], concepts_per_section)
                sample2 = by_section[s2][:concepts_per_section] if len(by_section[s2]) <= concepts_per_section else random.sample(by_section[s2], concepts_per_section)

                for c1 in sample1:
                    for c2 in sample2:
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
        llm_router,
        batch_size: int = 40  # Pairs per LLM call
    ) -> List[Dict[str, Any]]:
        """
        Détecte relations via LLM avec batching.

        Traite toutes les paires en lots de batch_size.
        """
        import json
        import re
        import asyncio

        if not pairs:
            return []

        all_relations = []
        total_batches = (len(pairs) + batch_size - 1) // batch_size

        logger.info(f"[Pass2Service] Processing {len(pairs)} pairs in {total_batches} batches")

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(pairs))
            batch_pairs = pairs[start:end]

            pairs_json = json.dumps(batch_pairs, ensure_ascii=False, indent=2)

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
4. Skip pairs with no meaningful relation

Return JSON: {{"relations": [{{"source_id": "...", "target_id": "...", "predicate": "REQUIRES", "confidence": 0.85}}]}}"""

            try:
                logger.info(f"[Pass2Service] Batch {batch_idx + 1}/{total_batches}: sending {len(batch_pairs)} pairs to LLM")
                response = await llm_router.acomplete(
                    task_type=TaskType.KNOWLEDGE_EXTRACTION,
                    messages=[
                        {"role": "system", "content": "You are OSMOSE Pass 2 Relation Detector. Output only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )

                text = response.strip() if response else ""
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    batch_relations = data.get("relations", [])
                    all_relations.extend(batch_relations)
                    logger.info(f"[Pass2Service] Batch {batch_idx + 1}: detected {len(batch_relations)} relations")
                else:
                    logger.warning(f"[Pass2Service] Batch {batch_idx + 1}: no JSON found in LLM response")

            except Exception as e:
                logger.error(f"[Pass2Service] Batch {batch_idx + 1} failed: {e}")

            # Small delay between batches to avoid rate limiting
            if batch_idx < total_batches - 1:
                await asyncio.sleep(0.5)

        logger.info(f"[Pass2Service] Total relations detected: {len(all_relations)}")
        return all_relations

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

    def run_corpus_er(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None
    ) -> Pass2Result:
        """
        Exécute Corpus Entity Resolution.

        Fusionne les CanonicalConcepts dupliqués à travers le corpus.

        Spec: PATCH-ER-04/05/06 (ChatGPT calibration)
        - TopK + Mutual Best pruning
        - Decision v2 (AUTO/PROPOSE/REJECT)
        - Hard budget proposals cap

        Args:
            dry_run: Si True, preview sans exécuter les merges
            limit: Limite de concepts à analyser (pour tests)

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="CORPUS_ER")

        try:
            # Obtenir le pipeline ER avec config par défaut
            pipeline = get_corpus_er_pipeline(
                tenant_id=self.tenant_id,
                config=CorpusERConfig()
            )

            try:
                # Exécuter le pipeline
                stats = pipeline.run(dry_run=dry_run, limit=limit)

                result.items_processed = stats.concepts_analyzed
                result.items_created = stats.auto_merges
                result.items_updated = stats.proposals_created

                result.details = {
                    "dry_run": dry_run,
                    "concepts_analyzed": stats.concepts_analyzed,
                    "candidates_generated": stats.candidates_generated,
                    "candidates_after_topk": stats.candidates_after_topk,
                    "candidates_after_mutual": stats.candidates_after_mutual,
                    "auto_merges": stats.auto_merges,
                    "proposals_created": stats.proposals_created,
                    "proposals_dropped_by_cap": stats.proposals_dropped_by_cap,
                    "rejections": stats.rejections,
                    "reject_breakdown": {
                        "compat_low": stats.reject_compat_low,
                        "lex_sem_low": stats.reject_lex_sem_low,
                        "not_proposal": stats.reject_not_proposal,
                    },
                    "edges_rewired": stats.edges_rewired,
                    "instance_of_rewired": stats.instance_of_rewired,
                    "distribution": stats.log_summary(),
                }

                if stats.errors:
                    result.errors = stats.errors[:10]

                logger.info(
                    f"[Pass2Service] CORPUS_ER complete: {stats.log_summary()}"
                )

            finally:
                pipeline.close()

        except Exception as e:
            logger.error(f"[Pass2Service] CORPUS_ER failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    async def run_corpus_links(self) -> Pass2Result:
        """
        Pass 4b: Corpus Links (PATCH-LINK).

        ADR 2026-01-07: Crée des liens faibles cross-documents.

        - CO_OCCURS_IN_CORPUS: concepts qui apparaissent ensemble dans ≥2 documents
        - Phase déterministe, SANS LLM
        - Les liens sont des "indices" pour navigation, pas des relations sémantiques

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="CORPUS_LINKS")

        try:
            # Créer les relations CO_OCCURS_IN_CORPUS
            query = """
            // Trouver les paires de concepts qui co-occurent dans ≥2 documents
            MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
            MATCH (c2:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c1.canonical_id < c2.canonical_id
              AND coalesce(c1.concept_type, '') <> 'TOPIC'
              AND coalesce(c2.concept_type, '') <> 'TOPIC'

            // Trouver les documents communs via MENTIONED_IN
            MATCH (c1)-[:MENTIONED_IN]->(ctx1:SectionContext)-[:IN_DOC]->(doc:DocumentContext)
            MATCH (c2)-[:MENTIONED_IN]->(ctx2:SectionContext)-[:IN_DOC]->(doc)
            WHERE ctx1.tenant_id = $tenant_id AND ctx2.tenant_id = $tenant_id

            WITH c1, c2, collect(DISTINCT doc.doc_id) AS shared_docs
            WHERE size(shared_docs) >= 2

            // Créer ou mettre à jour la relation
            MERGE (c1)-[r:CO_OCCURS_IN_CORPUS]->(c2)
            ON CREATE SET
                r.created_at = datetime(),
                r.doc_count = size(shared_docs),
                r.shared_doc_ids = shared_docs,
                r.tenant_id = $tenant_id
            ON MATCH SET
                r.updated_at = datetime(),
                r.doc_count = size(shared_docs),
                r.shared_doc_ids = shared_docs

            RETURN count(r) AS links_created,
                   sum(CASE WHEN r.created_at = datetime() THEN 1 ELSE 0 END) AS new_links
            """

            results = self._execute_query(query, {"tenant_id": self.tenant_id})

            links_created = results[0]["links_created"] if results else 0
            new_links = results[0].get("new_links", links_created) if results else 0

            result.items_processed = links_created
            result.items_created = new_links
            result.items_updated = links_created - new_links

            result.details = {
                "co_occurs_relations_total": links_created,
                "new_relations_created": new_links,
                "existing_relations_updated": links_created - new_links,
                "min_doc_threshold": 2,
            }

            logger.info(
                f"[Pass2Service] CORPUS_LINKS complete: {links_created} CO_OCCURS_IN_CORPUS relations"
            )

        except Exception as e:
            logger.error(f"[Pass2Service] CORPUS_LINKS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    async def run_full_pass2(
        self,
        document_id: Optional[str] = None,
        skip_classify: bool = False,
        skip_enrich: bool = False,
        skip_consolidate: bool = False,
        skip_corpus_er: bool = False
    ) -> Dict[str, Pass2Result]:
        """
        Exécute Pass 2 complet sur TOUS les concepts.

        Phases dans l'ordre:
        1. CLASSIFY_FINE - Traite TOUS les concepts en boucle
        2. ENRICH_RELATIONS - Détecte relations cross-segment
        3. CONSOLIDATE_CLAIMS - Consolide les claims
        4. CONSOLIDATE_RELATIONS - Consolide les relations
        5. CORPUS_ER - Entity Resolution corpus-level

        Args:
            document_id: Filtrer par document
            skip_classify: Ignorer CLASSIFY_FINE
            skip_enrich: Ignorer ENRICH_RELATIONS
            skip_consolidate: Ignorer consolidation
            skip_corpus_er: Ignorer CORPUS_ER

        Returns:
            Dict avec résultats par phase
        """
        logger.info("[Pass2Service] Starting FULL Pass 2 (process_all=True)")
        results = {}

        if not skip_classify:
            # FIXED 2024-12-31: process_all=True pour traiter TOUS les concepts
            results["classify_fine"] = await self.run_classify_fine(
                document_id=document_id,
                limit=500,  # 500 concepts par batch
                process_all=True  # Boucle jusqu'à traiter tous les concepts
            )

        if not skip_enrich:
            results["enrich_relations"] = await self.run_enrich_relations(document_id)

        if not skip_consolidate:
            results["consolidate_claims"] = self.run_consolidate_claims()
            results["consolidate_relations"] = self.run_consolidate_relations()

        if not skip_corpus_er:
            results["corpus_er"] = self.run_corpus_er(dry_run=False)

        logger.info(f"[Pass2Service] FULL Pass 2 complete: {len(results)} phases executed")
        return results

    async def run_structural_topics(
        self,
        document_id: Optional[str] = None
    ) -> Pass2Result:
        """
        Exécute Pass 2a: Structural Topics.

        Extrait Topics depuis H1/H2 headers et crée:
        - CanonicalConcept type=TOPIC
        - HAS_TOPIC (Document → Topic)
        - COVERS (Topic → Concept)

        Args:
            document_id: Document à traiter (optionnel, tous si None)

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="STRUCTURAL_TOPICS")

        try:
            # Récupérer documents à traiter
            if document_id:
                doc_ids = [document_id]
            else:
                doc_ids = self._get_documents_without_topics()

            if not doc_ids:
                result.details["message"] = "No documents to process"
                result.success = True
                return result

            total_topics = 0
            total_covers = 0

            for doc_id in doc_ids:
                # Récupérer le texte du document depuis Qdrant
                text = await self._get_document_text(doc_id)
                if not text:
                    logger.warning(f"[Pass2Service] No text for document {doc_id}")
                    continue

                # Extraire et persister les topics
                stats = process_document_topics(
                    document_id=doc_id,
                    text=text,
                    neo4j_client=self._neo4j_client,
                    tenant_id=self.tenant_id
                )

                total_topics += stats.get("topics_count", 0)
                total_covers += stats.get("covers_stats", {}).get("covers_created", 0)

            result.items_processed = len(doc_ids)
            result.items_created = total_topics
            result.success = True
            result.details = {
                "documents_processed": len(doc_ids),
                "topics_created": total_topics,
                "covers_created": total_covers
            }

        except Exception as e:
            logger.error(f"[Pass2Service] STRUCTURAL_TOPICS failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[Pass2Service] STRUCTURAL_TOPICS complete: "
            f"{result.items_created} topics, {result.execution_time_ms/1000:.1f}s"
        )
        return result

    def _get_documents_without_topics(self) -> List[str]:
        """Récupère les documents qui n'ont pas encore de Topics."""
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        WHERE d.document_id IS NOT NULL

        // Compter les HAS_TOPIC existants
        OPTIONAL MATCH (d)-[:HAS_TOPIC]->(t:CanonicalConcept {concept_type: 'TOPIC'})
        WITH d, count(t) AS existing_topics

        // Ne retourner que les documents sans Topics
        WHERE existing_topics = 0

        RETURN d.document_id AS doc_id
        ORDER BY d.document_id
        LIMIT 100
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})
        return [r["doc_id"] for r in results if r.get("doc_id")]

    async def _get_document_text(self, document_id: str) -> Optional[str]:
        """Récupère le texte complet d'un document depuis Qdrant."""
        from knowbase.common.clients.qdrant_client import get_qdrant_client
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        try:
            qdrant = get_qdrant_client()

            scroll_result = qdrant.scroll(
                collection_name="knowbase",
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id)
                        ),
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=self.tenant_id)
                        )
                    ]
                ),
                limit=200,
                with_payload=True,
                with_vectors=False
            )

            if scroll_result and scroll_result[0]:
                # Concaténer tous les chunks
                chunks = sorted(
                    scroll_result[0],
                    key=lambda p: p.payload.get("chunk_index", 0) if p.payload else 0
                )
                texts = [p.payload.get("text", "") for p in chunks if p.payload]
                return "\n\n".join(texts)

        except Exception as e:
            logger.error(f"[Pass2Service] Failed to get document text: {e}")

        return None

    async def run_semantic_consolidation(
        self,
        document_id: Optional[str] = None,
        max_candidates: int = 50
    ) -> Pass2Result:
        """
        Exécute Pass 3: Semantic Consolidation.

        Pipeline:
        1. Génère candidats via co-présence Topic/Section
        2. Vérifie chaque candidat avec LLM extractif
        3. Persiste les relations avec preuves

        Args:
            document_id: Document à traiter (optionnel, tous si None)
            max_candidates: Nombre max de candidats par document

        Returns:
            Pass2Result avec statistiques
        """
        start_time = time.time()
        result = Pass2Result(phase="SEMANTIC_CONSOLIDATION")

        try:
            # Récupérer documents à traiter
            if document_id:
                doc_ids = [document_id]
            else:
                doc_ids = self._get_documents_with_topics()

            if not doc_ids:
                result.details["message"] = "No documents with Topics to consolidate"
                result.success = True
                return result

            llm_router = get_llm_router()
            total_candidates = 0
            total_relations = 0
            total_abstained = 0

            for doc_id in doc_ids:
                stats = await run_pass3_consolidation(
                    document_id=doc_id,
                    neo4j_client=self._neo4j_client,
                    llm_router=llm_router,
                    tenant_id=self.tenant_id,
                    max_candidates=max_candidates
                )

                total_candidates += stats.candidates_generated
                total_relations += stats.relations_created
                total_abstained += stats.abstained

            result.items_processed = total_candidates
            result.items_created = total_relations
            result.success = True
            result.details = {
                "documents_processed": len(doc_ids),
                "candidates_evaluated": total_candidates,
                "relations_created": total_relations,
                "abstained": total_abstained
            }

        except Exception as e:
            logger.error(f"[Pass2Service] SEMANTIC_CONSOLIDATION failed: {e}")
            result.success = False
            result.errors.append(str(e))

        result.execution_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[Pass2Service] SEMANTIC_CONSOLIDATION complete: "
            f"{result.items_created} relations, {result.execution_time_ms/1000:.1f}s"
        )
        return result

    def _get_documents_with_topics(self) -> List[str]:
        """Récupère les documents qui ont des Topics (prêts pour Pass 3)."""
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})-[:HAS_TOPIC]->(t:CanonicalConcept {concept_type: 'TOPIC'})
        RETURN DISTINCT d.document_id AS doc_id
        ORDER BY d.document_id
        LIMIT 100
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})
        return [r["doc_id"] for r in results if r.get("doc_id")]

    def get_enrichment_status(self) -> EnrichmentStatus:
        """
        Récupère le statut étendu pour la page Enrichment.

        Inclut les métriques Pass 2a (Topics/COVERS) et Pass 3 (relations prouvées).

        Returns:
            EnrichmentStatus avec toutes les métriques
        """
        status = EnrichmentStatus()

        # Requêtes pour toutes les métriques
        queries = {
            "proto_concepts": "MATCH (p:ProtoConcept {tenant_id: $tenant_id}) RETURN count(p) AS count",
            "canonical_concepts": "MATCH (c:CanonicalConcept {tenant_id: $tenant_id}) WHERE c.concept_type <> 'TOPIC' OR c.concept_type IS NULL RETURN count(c) AS count",
            "mentioned_in_count": "MATCH ()-[r:MENTIONED_IN]->() RETURN count(r) AS count",
            "topics_count": "MATCH (c:CanonicalConcept {tenant_id: $tenant_id, concept_type: 'TOPIC'}) RETURN count(c) AS count",
            "has_topic_count": "MATCH ()-[r:HAS_TOPIC]->() RETURN count(r) AS count",
            "covers_count": "MATCH ()-[r:COVERS]->() RETURN count(r) AS count",
            "raw_assertions": "MATCH (ra:RawAssertion {tenant_id: $tenant_id}) RETURN count(ra) AS count",
        }

        for key, query in queries.items():
            try:
                result = self._execute_query(query, {"tenant_id": self.tenant_id})
                setattr(status, key, result[0]["count"] if result else 0)
            except Exception as e:
                logger.error(f"[Pass2Service] Error counting {key}: {e}")

        # Compter relations prouvées (avec evidence_context_ids non vide)
        proven_query = """
        MATCH (s:CanonicalConcept {tenant_id: $tenant_id})-[r]->(o:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.evidence_context_ids IS NOT NULL
          AND size(r.evidence_context_ids) > 0
          AND r.source = 'pass3_extractive'
        RETURN count(r) AS count
        """
        try:
            result = self._execute_query(proven_query, {"tenant_id": self.tenant_id})
            status.proven_relations = result[0]["count"] if result else 0
        except Exception as e:
            logger.error(f"[Pass2Service] Error counting proven_relations: {e}")

        # === CORPUS-LEVEL STATS (Pass 4) ===

        # Pass 4a: Entity Resolution stats
        er_query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WITH count(c) AS total,
             sum(CASE WHEN c.er_status = 'STANDALONE' OR c.er_status IS NULL THEN 1 ELSE 0 END) AS standalone,
             sum(CASE WHEN c.er_status = 'MERGED' THEN 1 ELSE 0 END) AS merged
        OPTIONAL MATCH (p:MergeProposal {tenant_id: $tenant_id})
        WHERE p.applied = false OR p.applied IS NULL
        WITH total, standalone, merged, count(p) AS pending
        RETURN standalone, merged, pending
        """
        try:
            result = self._execute_query(er_query, {"tenant_id": self.tenant_id})
            if result:
                status.er_standalone_concepts = result[0].get("standalone", 0)
                status.er_merged_concepts = result[0].get("merged", 0)
                status.er_pending_proposals = result[0].get("pending", 0)
        except Exception as e:
            logger.error(f"[Pass2Service] Error counting ER stats: {e}")

        # Pass 4b: Corpus Links stats (CO_OCCURS_IN_CORPUS)
        co_occurs_query = """
        MATCH ()-[r:CO_OCCURS_IN_CORPUS]->()
        WHERE r.tenant_id = $tenant_id OR r.tenant_id IS NULL
        RETURN count(r) AS count
        """
        try:
            result = self._execute_query(co_occurs_query, {"tenant_id": self.tenant_id})
            status.co_occurs_relations = result[0]["count"] if result else 0
        except Exception as e:
            logger.error(f"[Pass2Service] Error counting co_occurs_relations: {e}")

        # Jobs en attente
        status.pending_jobs = self._orchestrator.queue_size
        status.running_jobs = len(self._orchestrator.running_jobs)

        return status


# Singleton
_service_instance: Optional[Pass2Service] = None


def get_pass2_service(tenant_id: str = "default") -> Pass2Service:
    """Récupère l'instance singleton du service."""
    global _service_instance
    if _service_instance is None or _service_instance.tenant_id != tenant_id:
        _service_instance = Pass2Service(tenant_id=tenant_id)
    return _service_instance
