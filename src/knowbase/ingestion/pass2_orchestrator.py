"""
OSMOSE Enrichment Orchestrator

ADR 2026-01-07: Nomenclature validée Claude + ChatGPT
ADR 2026-01-09: Pass 2.0 Corpus Promotion (ADR_UNIFIED_CORPUS_PROMOTION)
Séparation claire Document-level vs Corpus-level phases.

=== PASS 2.0: CORPUS PROMOTION (ADR_UNIFIED_CORPUS_PROMOTION) ===
DOIT s'exécuter EN PREMIER, avant toute autre phase.
Crée les CanonicalConcepts à partir des ProtoConcepts.

- Pass 2.0: CORPUS_PROMOTION - Promotion unifiée doc+corpus

=== DOCUMENT-LEVEL PHASES (Pass 2a-3) ===
Travaillent sur UN document à la fois.

- Pass 2a: STRUCTURAL_TOPICS - Topics H1/H2 + COVERS (scope)
- Pass 2b: CLASSIFY_FINE - Classification LLM fine-grained
- Pass 2b: ENRICH_RELATIONS - Relations candidates (RawAssertions)
- Pass 3:  SEMANTIC_CONSOLIDATION - Relations prouvées (evidence_quote)

=== CORPUS-LEVEL PHASES (Pass 4) ===
Travaillent sur le corpus ENTIER.
IMPORTANT: Exécuter APRÈS document-level pour préserver l'auditabilité.

- Pass 4a: ENTITY_RESOLUTION - Merge doublons cross-doc (PATCH-ER)
- Pass 4b: CORPUS_LINKS - CO_OCCURS_IN_CORPUS (PATCH-LINK)

Modes d'exécution:
- inline: Exécuté immédiatement après Pass 1 (Burst mode)
- background: Job asynchrone (mode normal)
- scheduled: Batch nocturne (corpus stable)

ADR: doc/ongoing/ADR_GRAPH_FIRST_ARCHITECTURE.md
ADR: doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md

Author: OSMOSE
Date: 2026-01-07 (updated 2026-01-09)
"""

import logging
import asyncio
from enum import Enum
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from knowbase.config.feature_flags import get_hybrid_anchor_config
from knowbase.semantic.classification.fine_classifier import (
    FineClassifier,
    get_fine_classifier,
    FineClassificationBatch,
)
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.ingestion.enrichment_tracker import (
    get_enrichment_tracker,
    EnrichmentStatus
)  # ADR 2024-12-30: Enrichment tracking
from knowbase.consolidation.corpus_promotion import (
    CorpusPromotionEngine,
    get_corpus_promotion_engine,
)  # ADR 2026-01-09: Pass 2.0 Corpus Promotion

logger = logging.getLogger(__name__)


class Pass2Mode(str, Enum):
    """Modes d'exécution Pass 2."""

    INLINE = "inline"          # Exécuté immédiatement après Pass 1
    BACKGROUND = "background"  # Job asynchrone (mode normal)
    SCHEDULED = "scheduled"    # Batch nocturne (corpus stable)
    DISABLED = "disabled"      # Pass 2 désactivé


# =============================================================================
# NOMENCLATURE ADR 2026-01-07 (validée Claude + ChatGPT)
# Séparation claire : Document-level vs Corpus-level
# =============================================================================

class DocumentPhase(str, Enum):
    """
    Phases Document-Level (Pass 1-3).

    Chaque phase travaille sur UN document à la fois.
    Les relations créées sont intra-document avec preuves extractives.
    """
    # Pass 2.0: Corpus Promotion (ADR_UNIFIED_CORPUS_PROMOTION)
    # DOIT s'exécuter EN PREMIER, avant toute autre phase
    CORPUS_PROMOTION = "corpus_promotion"    # Promotion unifiée doc+corpus

    # Pass 2a: Structure documentaire
    STRUCTURAL_TOPICS = "structural_topics"  # Topics H1/H2 + COVERS (scope)

    # Pass 2b: Typage et candidates
    CLASSIFY_FINE = "classify_fine"          # Classification LLM fine-grained
    ENRICH_RELATIONS = "enrich_relations"    # Relations candidates (RawAssertions)

    # Pass 3: Preuves sémantiques
    SEMANTIC_CONSOLIDATION = "semantic_consolidation"  # Relations prouvées (evidence_quote)


class CorpusPhase(str, Enum):
    """
    Phases Corpus-Level (Pass 4).

    Ces phases travaillent sur le corpus ENTIER.
    Elles unifient les identités et créent des liens faibles cross-doc.

    IMPORTANT: Exécuter APRÈS les DocumentPhases pour garantir
    que les preuves sont attachées avant le rewiring.
    """
    # Pass 4a: Entity Resolution
    ENTITY_RESOLUTION = "entity_resolution"  # Merge doublons cross-doc (PATCH-ER)

    # Pass 4b: Liens faibles corpus
    CORPUS_LINKS = "corpus_links"            # CO_OCCURS_IN_CORPUS (PATCH-LINK)


# Alias pour compatibilité arrière (deprecated)
class Pass2Phase(str, Enum):
    """
    DEPRECATED: Utiliser DocumentPhase ou CorpusPhase.
    Conservé pour compatibilité avec code existant.
    """
    CORPUS_PROMOTION = "corpus_promotion"  # Pass 2.0 (ADR_UNIFIED_CORPUS_PROMOTION)
    STRUCTURAL_TOPICS = "structural_topics"
    CLASSIFY_FINE = "classify_fine"
    ENRICH_RELATIONS = "enrich_relations"
    SEMANTIC_CONSOLIDATION = "semantic_consolidation"
    CROSS_DOC = "cross_doc"  # Mapped to CorpusPhase.ENTITY_RESOLUTION


@dataclass
class Pass2Stats:
    """Statistiques d'exécution Pass 2."""

    document_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    mode: Pass2Mode = Pass2Mode.BACKGROUND

    # Pass 2.0: Corpus Promotion (ADR_UNIFIED_CORPUS_PROMOTION)
    corpus_promotion_stable: int = 0
    corpus_promotion_singleton: int = 0
    corpus_promotion_crossdoc: int = 0

    # Par phase
    # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a
    structural_topics_count: int = 0
    covers_relations_count: int = 0

    # Pass 2b
    classify_fine_count: int = 0
    classify_fine_changes: int = 0
    enrich_relations_count: int = 0

    # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 3
    pass3_candidates: int = 0
    pass3_verified: int = 0
    pass3_abstained: int = 0

    # Pass 4a: Entity Resolution (corpus-level)
    er_candidates: int = 0
    er_merged: int = 0
    er_proposals: int = 0

    # Pass 4b: Corpus Links (corpus-level)
    corpus_links_created: int = 0
    co_occurs_relations: int = 0

    # Legacy (deprecated)
    cross_doc_concepts: int = 0  # Mapped to er_merged

    # Erreurs
    errors: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass
class Pass2Job:
    """
    Job d'enrichissement (Document + Corpus phases).

    ADR 2026-01-07: Séparation claire des phases document-level vs corpus-level.
    """
    job_id: str
    document_id: str
    tenant_id: str
    mode: Pass2Mode

    # Document-level phases (Pass 2-3)
    phases: List[Pass2Phase]

    # Corpus-level phases (Pass 4) - Optionnel
    corpus_phases: List[CorpusPhase] = field(default_factory=list)

    concepts: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 0  # 0 = normal, 1 = high


class Pass2Orchestrator:
    """
    Orchestrateur Pass 2 du Hybrid Anchor Model.

    Responsabilités:
    1. Déterminer le mode d'exécution selon configuration
    2. Orchestrer les phases: CLASSIFY_FINE, ENRICH_RELATIONS, CROSS_DOC
    3. Gérer les jobs en background/scheduled

    Invariant: Pass 2 ne bloque JAMAIS Pass 1.
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise l'orchestrateur.

        Args:
            tenant_id: ID tenant pour configuration
        """
        self.tenant_id = tenant_id

        # Charger configuration
        config = get_hybrid_anchor_config("pass2_config", tenant_id) or {}
        self.default_mode = Pass2Mode(config.get("mode", "background"))
        self.enabled_phases = [
            Pass2Phase(p) for p in config.get("enabled_phases", [
                # ADR_UNIFIED_CORPUS_PROMOTION: Pass 2.0 EN PREMIER (Promotion unifiée)
                "corpus_promotion",
                # ADR_GRAPH_FIRST_ARCHITECTURE: Pass 2a (Topics/COVERS)
                "structural_topics",
                # Puis Pass 2b (Classification + Relations existantes)
                "classify_fine", "enrich_relations",
                # ADR_GRAPH_FIRST_ARCHITECTURE: Pass 3 (Semantic Consolidation - proven relations)
                "semantic_consolidation",
                # Enfin Cross-doc
                "cross_doc"
            ])
        ]

        # Queue pour jobs background
        self._job_queue: List[Pass2Job] = []
        self._running_jobs: Dict[str, Pass2Job] = {}

        # Classifiers et enrichers
        self._fine_classifier: Optional[FineClassifier] = None
        self._llm_router = None

        logger.info(
            f"[OSMOSE:Pass2Orchestrator] Initialized "
            f"(mode={self.default_mode.value}, phases={[p.value for p in self.enabled_phases]})"
        )

    async def schedule_pass2(
        self,
        document_id: str,
        concepts: List[Dict[str, Any]],
        mode: Optional[Pass2Mode] = None,
        priority: int = 0
    ) -> Pass2Job:
        """
        Planifie l'exécution de Pass 2 pour un document.

        ADR_UNIFIED_CORPUS_PROMOTION: La phase CORPUS_PROMOTION charge les
        ProtoConcepts directement depuis Neo4j. Le paramètre `concepts` est
        conservé pour compatibilité mais n'est plus utilisé par cette phase.

        Args:
            document_id: ID du document traité en Pass 1
            concepts: ProtoConcepts pour référence (non utilisé par CORPUS_PROMOTION)
            mode: Mode d'exécution (utilise default si None)
            priority: Priorité du job (0=normal, 1=high)

        Returns:
            Pass2Job créé
        """
        effective_mode = mode or self.default_mode

        job = Pass2Job(
            job_id=f"p2_{uuid.uuid4().hex[:12]}",
            document_id=document_id,
            tenant_id=self.tenant_id,
            mode=effective_mode,
            phases=self.enabled_phases.copy(),
            concepts=concepts,
            priority=priority
        )

        if effective_mode == Pass2Mode.INLINE:
            # Exécution immédiate
            logger.info(
                f"[OSMOSE:Pass2] Executing INLINE for doc {document_id} "
                f"({len(concepts)} concepts)"
            )
            await self._execute_pass2(job)

        elif effective_mode == Pass2Mode.BACKGROUND:
            # Ajouter à la queue
            self._job_queue.append(job)
            self._job_queue.sort(key=lambda j: (-j.priority, j.created_at))
            logger.info(
                f"[OSMOSE:Pass2] Queued BACKGROUND job {job.job_id} "
                f"for doc {document_id} (queue size: {len(self._job_queue)})"
            )

        elif effective_mode == Pass2Mode.SCHEDULED:
            # Sera traité par le scheduler nocturne
            self._job_queue.append(job)
            logger.info(
                f"[OSMOSE:Pass2] Queued SCHEDULED job {job.job_id} "
                f"for doc {document_id}"
            )

        else:
            logger.info(f"[OSMOSE:Pass2] DISABLED, skipping doc {document_id}")

        return job

    async def _execute_pass2(self, job: Pass2Job) -> Pass2Stats:
        """
        Exécute toutes les phases Pass 2 pour un job.

        Args:
            job: Job à exécuter

        Returns:
            Pass2Stats avec résultats
        """
        stats = Pass2Stats(
            document_id=job.document_id,
            started_at=datetime.now(),
            mode=job.mode
        )

        self._running_jobs[job.job_id] = job

        # ADR 2024-12-30: Track enrichment state
        enrichment_tracker = get_enrichment_tracker(job.tenant_id)
        enrichment_tracker.update_pass2_status(
            document_id=job.document_id,
            status=EnrichmentStatus.IN_PROGRESS
        )

        phases_completed = []

        try:
            # =================================================================
            # Pass 2.0: CORPUS_PROMOTION (ADR_UNIFIED_CORPUS_PROMOTION)
            # DOIT s'exécuter EN PREMIER, avant toute autre phase
            # Crée les CanonicalConcepts à partir des ProtoConcepts
            # =================================================================
            if Pass2Phase.CORPUS_PROMOTION in job.phases:
                await self._phase_corpus_promotion(job, stats)
                phases_completed.append(Pass2Phase.CORPUS_PROMOTION.value)

            # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a: STRUCTURAL_TOPICS
            # Doit s'exécuter AVANT les autres phases pour créer Topics/COVERS
            if Pass2Phase.STRUCTURAL_TOPICS in job.phases:
                await self._phase_structural_topics(job, stats)
                phases_completed.append(Pass2Phase.STRUCTURAL_TOPICS.value)

            # Phase 2b-1: CLASSIFY_FINE
            if Pass2Phase.CLASSIFY_FINE in job.phases:
                await self._phase_classify_fine(job, stats)
                phases_completed.append(Pass2Phase.CLASSIFY_FINE.value)

            # Phase 2b-2: ENRICH_RELATIONS
            if Pass2Phase.ENRICH_RELATIONS in job.phases:
                await self._phase_enrich_relations(job, stats)
                phases_completed.append(Pass2Phase.ENRICH_RELATIONS.value)

            # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 3: SEMANTIC_CONSOLIDATION
            # Extractive verification + proven relations (SEULE source de relations sémantiques)
            if Pass2Phase.SEMANTIC_CONSOLIDATION in job.phases:
                await self._phase_semantic_consolidation(job, stats)
                phases_completed.append(Pass2Phase.SEMANTIC_CONSOLIDATION.value)

            # =================================================================
            # CORPUS-LEVEL PHASES (Pass 4) - ADR 2026-01-07
            # Exécutées APRÈS les phases document-level
            # =================================================================

            # Pass 4a: Entity Resolution (PATCH-ER)
            # Support both new CorpusPhase and legacy Pass2Phase.CROSS_DOC
            if (hasattr(job, 'corpus_phases') and CorpusPhase.ENTITY_RESOLUTION in getattr(job, 'corpus_phases', [])) or \
               Pass2Phase.CROSS_DOC in job.phases:
                await self._phase_entity_resolution(job, stats)
                phases_completed.append(CorpusPhase.ENTITY_RESOLUTION.value)

            # Pass 4b: Corpus Links (PATCH-LINK)
            if hasattr(job, 'corpus_phases') and CorpusPhase.CORPUS_LINKS in getattr(job, 'corpus_phases', []):
                await self._phase_corpus_links(job, stats)
                phases_completed.append(CorpusPhase.CORPUS_LINKS.value)

            # ADR 2024-12-30: Update enrichment tracking - Pass 2 complete
            enrichment_tracker.update_pass2_status(
                document_id=job.document_id,
                status=EnrichmentStatus.COMPLETE,
                relations_extracted=stats.enrich_relations_count,
                classifications_updated=stats.classify_fine_changes,
                cross_doc_links=stats.er_merged + stats.corpus_links_created,
                phases_completed=phases_completed
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2] Job {job.job_id} failed: {e}")
            stats.errors.append(str(e))

            # ADR 2024-12-30: Update enrichment tracking - Pass 2 failed
            enrichment_tracker.update_pass2_status(
                document_id=job.document_id,
                status=EnrichmentStatus.FAILED if not phases_completed else EnrichmentStatus.PARTIAL,
                error=str(e),
                phases_completed=phases_completed
            )

        finally:
            stats.completed_at = datetime.now()
            self._running_jobs.pop(job.job_id, None)

        logger.info(
            f"[OSMOSE:Pass2] Job {job.job_id} completed in {stats.duration_seconds:.1f}s "
            f"(promotion_stable={stats.corpus_promotion_stable}, promotion_singleton={stats.corpus_promotion_singleton}, "
            f"topics={stats.structural_topics_count}, covers={stats.covers_relations_count}, "
            f"classify={stats.classify_fine_count}, relations={stats.enrich_relations_count}, "
            f"pass3_verified={stats.pass3_verified}/{stats.pass3_candidates})"
        )

        return stats

    # =========================================================================
    # Pass 2.0: CORPUS_PROMOTION (ADR_UNIFIED_CORPUS_PROMOTION)
    # =========================================================================

    async def _phase_corpus_promotion(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase CORPUS_PROMOTION: Promotion unifiée des ProtoConcepts.

        ADR_UNIFIED_CORPUS_PROMOTION - Pass 2.0

        DOIT s'exécuter EN PREMIER, avant toute autre phase.
        Crée les CanonicalConcepts à partir des ProtoConcepts.

        Règles de promotion:
        - ≥2 occurrences même document → STABLE
        - ≥2 sections différentes → STABLE
        - ≥2 documents + signal minimal → STABLE (cross-doc)
        - singleton + high-signal V2 → SINGLETON
        """
        logger.info(
            f"[OSMOSE:Pass2.0:CORPUS_PROMOTION] Starting for doc {job.document_id}"
        )

        try:
            # Obtenir le moteur de promotion
            engine = get_corpus_promotion_engine(job.tenant_id)

            # Exécuter la promotion
            promotion_stats = engine.run_promotion(document_id=job.document_id)

            # Mettre à jour les stats
            stats.corpus_promotion_stable = promotion_stats.promoted_stable
            stats.corpus_promotion_singleton = promotion_stats.promoted_singleton
            stats.corpus_promotion_crossdoc = promotion_stats.crossdoc_promotions

            logger.info(
                f"[OSMOSE:Pass2.0:CORPUS_PROMOTION] Completed for doc {job.document_id}: "
                f"stable={promotion_stats.promoted_stable}, "
                f"singleton={promotion_stats.promoted_singleton}, "
                f"crossdoc={promotion_stats.crossdoc_promotions}"
            )

        except Exception as e:
            logger.error(
                f"[OSMOSE:Pass2.0:CORPUS_PROMOTION] Error for doc {job.document_id}: {e}",
                exc_info=True
            )
            stats.errors.append(f"CORPUS_PROMOTION: {str(e)}")

    # =========================================================================
    # Pass 2a: STRUCTURAL_TOPICS (ADR_GRAPH_FIRST_ARCHITECTURE)
    # =========================================================================

    async def _phase_structural_topics(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase STRUCTURAL_TOPICS: Extraction Topics depuis structure documentaire.

        ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a

        Pipeline:
        1. Extraire Topics depuis headers H1/H2
        2. Créer CanonicalConcept type=TOPIC + HAS_TOPIC
        3. Créer COVERS via règles déterministes (MENTIONED_IN + salience)

        IMPORTANT - Topic/COVERS = SCOPE documentaire, JAMAIS lien conceptuel.
        """
        from knowbase.relations.structural_topic_extractor import (
            StructuralTopicExtractor,
            TopicNeo4jWriter,
            CoversBuilder
        )
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        logger.info(
            f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] Starting for doc {job.document_id}"
        )

        try:
            # Récupérer le texte du document
            document_text = await self._get_document_text(job.document_id)

            if not document_text:
                logger.info(
                    f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] No document text for {job.document_id}, skipping"
                )
                return

            # 1. Extraire les topics structurels
            extractor = StructuralTopicExtractor()
            extraction_result = extractor.extract_topics(
                document_id=job.document_id,
                text=document_text,
                metadata={"tenant_id": job.tenant_id}
            )

            stats.structural_topics_count = len(extraction_result.topics)

            if not extraction_result.topics:
                logger.info(
                    f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] No topics extracted for {job.document_id}"
                )
                return

            # 2. Écrire dans Neo4j (Topics + HAS_TOPIC)
            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                logger.warning(
                    f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] Neo4j not connected, skipping persistence"
                )
                return

            writer = TopicNeo4jWriter(neo4j_client, tenant_id=job.tenant_id)
            write_stats = writer.write_topics(job.document_id, extraction_result.topics)

            # 3. Construire COVERS (déterministe, basé sur MENTIONED_IN + salience)
            covers_builder = CoversBuilder(neo4j_client, tenant_id=job.tenant_id)
            covers_stats = covers_builder.build_covers_for_document(
                document_id=job.document_id,
                topics=extraction_result.topics
            )

            stats.covers_relations_count = covers_stats.get("covers_created", 0)

            logger.info(
                f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] Complete: "
                f"{stats.structural_topics_count} topics, "
                f"{stats.covers_relations_count} COVERS relations"
            )

        except Exception as e:
            logger.error(
                f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] Failed: {e}",
                exc_info=True
            )
            stats.errors.append(f"STRUCTURAL_TOPICS: {e}")

    async def _get_document_text(self, document_id: str) -> Optional[str]:
        """
        Récupère le texte complet d'un document.

        Le texte est reconstitué depuis les DocumentChunk.text_preview
        qui contiennent les 200 premiers caractères de chaque chunk.

        Note: Pour Pass 2a (extraction Topics), text_preview suffit car
        on analyse la structure (H1/H2 headers) pas le contenu complet.

        Returns:
            Texte du document ou None si non trouvé
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            return None

        try:
            # Récupérer le texte depuis les DocumentChunk
            # Note: text_preview = 200 premiers chars de chaque chunk
            # Pour l'extraction de Topics (H1/H2), c'est suffisant car les headers
            # sont généralement au début des chunks
            query_chunks = """
            MATCH (dc:DocumentChunk {document_id: $document_id, tenant_id: $tenant_id})
            RETURN dc.text_preview AS text, dc.chunk_index AS idx
            ORDER BY dc.chunk_index
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query_chunks,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )

                chunks = [r["text"] for r in result if r.get("text")]
                if chunks:
                    return "\n\n".join(chunks)

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2a] Failed to get document text: {e}")

        return None

    async def _phase_classify_fine(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase CLASSIFY_FINE: Classification LLM fine-grained.

        Affine les types heuristiques de Pass 1.
        """
        logger.info(
            f"[OSMOSE:Pass2:CLASSIFY_FINE] Starting for {len(job.concepts)} concepts"
        )

        if not self._fine_classifier:
            self._fine_classifier = get_fine_classifier(self.tenant_id)

        try:
            result: FineClassificationBatch = await self._fine_classifier.classify_batch_async(
                job.concepts
            )

            stats.classify_fine_count = result.total_processed
            stats.classify_fine_changes = result.type_changes

            # Mettre à jour les concepts avec les types fins
            result_map = {r.concept_id: r for r in result.results}
            for concept in job.concepts:
                cid = concept.get("id", "")
                if cid in result_map:
                    fine_result = result_map[cid]
                    concept["type_fine"] = fine_result.type_fine.value
                    concept["type_fine_confidence"] = fine_result.confidence
                    concept["type_fine_justification"] = fine_result.justification

            logger.info(
                f"[OSMOSE:Pass2:CLASSIFY_FINE] Complete: "
                f"{stats.classify_fine_count} concepts, {stats.classify_fine_changes} changes"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2:CLASSIFY_FINE] Failed: {e}")
            stats.errors.append(f"CLASSIFY_FINE: {e}")

    async def _phase_enrich_relations(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase ENRICH_RELATIONS: Extraction relations segment-level (ADR 2024-12-30).

        Architecture Pass 2 révisée:
        - Extraction au niveau SEGMENT (pas chunk) pour réduire coût LLM
        - Scoring segments pour sélectionner les plus pertinents
        - 12 prédicats du set fermé uniquement
        - Persiste via RawAssertionWriter

        Remplace l'ancienne approche cross-segment par paires.
        """
        from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer
        from knowbase.relations.segment_relation_extractor import (
            get_segment_relation_extractor,
            PREDICATE_TO_RELATION_TYPE
        )
        from knowbase.relations.types import RawAssertionFlags

        logger.info(
            f"[OSMOSE:Pass2:ENRICH_RELATIONS] Starting segment-level extraction "
            f"for doc {job.document_id} ({len(job.concepts)} concepts)"
        )

        try:
            # Récupérer les segments du document depuis Neo4j
            segments = await self._get_document_segments(job.document_id)

            if not segments:
                logger.info(
                    f"[OSMOSE:Pass2:ENRICH_RELATIONS] No segments found for {job.document_id}"
                )
                return

            # Construire le mapping concept_id → segment_ids (depuis anchors)
            concept_anchors = await self._get_concept_anchors(job.document_id, job.tenant_id)

            if not concept_anchors:
                logger.info(
                    f"[OSMOSE:Pass2:ENRICH_RELATIONS] No concept anchors for {job.document_id}"
                )
                return

            # Utiliser le nouvel extracteur segment-level
            extractor = get_segment_relation_extractor(tenant_id=job.tenant_id)

            extraction_result = await extractor.extract_from_document(
                document_id=job.document_id,
                segments=segments,
                concept_anchors=concept_anchors,
                concept_catalogue=job.concepts,
                max_segments=25  # Top 25 segments par score
            )

            stats.enrich_relations_count = len(extraction_result.relations)

            # Persister les relations extraites
            if extraction_result.relations:
                writer = get_raw_assertion_writer(
                    tenant_id=job.tenant_id,
                    extractor_version="pass2_segment_v1",
                    model_used="gpt-4o-mini"
                )
                writer.reset_stats()

                written_count = 0
                for rel in extraction_result.relations:
                    if not rel.subject_concept_id or not rel.object_concept_id:
                        continue

                    # Mapper predicate vers RelationType
                    relation_type = PREDICATE_TO_RELATION_TYPE.get(rel.predicate)

                    result = writer.write_assertion(
                        subject_concept_id=rel.subject_concept_id,
                        object_concept_id=rel.object_concept_id,
                        predicate_raw=rel.predicate,
                        evidence_text=rel.evidence or f"Pass 2 segment extraction: {rel.predicate}",
                        source_doc_id=job.document_id,
                        source_chunk_id=rel.chunk_id or f"{job.document_id}_pass2",
                        confidence=rel.confidence,
                        source_language="MULTI",
                        flags=RawAssertionFlags(cross_sentence=False),
                        relation_type=relation_type,
                        type_confidence=rel.confidence,
                        evidence_span_start=rel.evidence_span[0] if rel.evidence_span else None,
                        evidence_span_end=rel.evidence_span[1] if rel.evidence_span else None,
                        # ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
                        evidence_context_ids=rel.evidence_context_ids,
                    )
                    if result:
                        written_count += 1

                logger.info(
                    f"[OSMOSE:Pass2:ENRICH_RELATIONS] Persisted {written_count}/{len(extraction_result.relations)} relations"
                )

            logger.info(
                f"[OSMOSE:Pass2:ENRICH_RELATIONS] Complete: "
                f"{extraction_result.segments_processed} segments processed, "
                f"{stats.enrich_relations_count} relations found"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2:ENRICH_RELATIONS] Failed: {e}", exc_info=True)
            stats.errors.append(f"ENRICH_RELATIONS: {e}")

    async def _get_document_segments(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Récupère les segments d'un document depuis Neo4j.

        Returns:
            Liste de dicts avec segment_id, text, section_id, char_offset
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            return []

        try:
            # Récupérer les chunks comme proxy des segments
            # TODO: Stocker segments explicitement si nécessaire
            query = """
            MATCH (dc:DocumentChunk {document_id: $document_id, tenant_id: $tenant_id})
            RETURN dc.chunk_id AS segment_id,
                   dc.text_preview AS text,
                   dc.section_id AS section_id,
                   dc.char_start AS char_offset
            ORDER BY dc.chunk_index
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )

                segments = []
                for record in result:
                    segments.append({
                        "segment_id": record["segment_id"],
                        "text": record["text"] or "",
                        "section_id": record["section_id"],
                        "char_offset": record["char_offset"] or 0
                    })

                return segments

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2] Failed to get segments: {e}")
            return []

    async def _get_concept_anchors(
        self,
        document_id: str,
        tenant_id: str
    ) -> Dict[str, List[str]]:
        """
        Récupère le mapping concept_id → segment_ids depuis Neo4j.

        Returns:
            Dict mapping concept_id vers liste de segment_ids où il est ancré
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            return {}

        try:
            query = """
            MATCH (p:ProtoConcept {document_id: $document_id, tenant_id: $tenant_id})
                  -[:ANCHORED_IN]->(dc:DocumentChunk)
            RETURN p.concept_id AS concept_id, collect(DISTINCT dc.chunk_id) AS segment_ids
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=tenant_id
                )

                anchors = {}
                for record in result:
                    concept_id = record["concept_id"]
                    segment_ids = record["segment_ids"]
                    if concept_id and segment_ids:
                        anchors[concept_id] = segment_ids

                return anchors

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2] Failed to get concept anchors: {e}")
            return {}

    def _predicate_to_relation_type(self, predicate: str) -> Optional["RelationType"]:
        """Convertit un prédicat brut vers un RelationType du set fermé."""
        from knowbase.relations.types import RelationType

        predicate_lower = predicate.lower().strip()

        # Mapping prédicat → type
        mapping = {
            "requires": RelationType.REQUIRES,
            "needs": RelationType.REQUIRES,
            "depends_on": RelationType.REQUIRES,
            "enables": RelationType.ENABLES,
            "allows": RelationType.ENABLES,
            "supports": RelationType.ENABLES,
            "uses": RelationType.USES,
            "utilizes": RelationType.USES,
            "leverages": RelationType.USES,
            "integrates_with": RelationType.INTEGRATES_WITH,
            "integrates": RelationType.INTEGRATES_WITH,
            "connects": RelationType.INTEGRATES_WITH,
            "applies_to": RelationType.APPLIES_TO,
            "governs": RelationType.APPLIES_TO,
            "constrains": RelationType.APPLIES_TO,
            "part_of": RelationType.PART_OF,
            "contains": RelationType.PART_OF,
            "includes": RelationType.PART_OF,
            "is_a": RelationType.SUBTYPE_OF,
            "type_of": RelationType.SUBTYPE_OF,
            "subtype_of": RelationType.SUBTYPE_OF,
            "causes": RelationType.CAUSES,
            "leads_to": RelationType.CAUSES,
            "results_in": RelationType.CAUSES,
            "prevents": RelationType.PREVENTS,
            "blocks": RelationType.PREVENTS,
            "prohibits": RelationType.PREVENTS,
            "replaces": RelationType.REPLACES,
            "supersedes": RelationType.REPLACES,
            "version_of": RelationType.VERSION_OF,
        }

        for key, rel_type in mapping.items():
            if key in predicate_lower:
                return rel_type

        return RelationType.ASSOCIATED_WITH  # Fallback

    def _generate_cross_segment_pairs(
        self,
        concepts: List[Dict[str, Any]],
        max_pairs: int = 50
    ) -> List[Dict[str, Any]]:
        """Génère paires de concepts de segments différents."""

        # Grouper par section
        by_section: Dict[str, List[Dict]] = {}
        for c in concepts:
            section = c.get("section_id", "default")
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(c)

        # Générer paires cross-section
        pairs = []
        sections = list(by_section.keys())

        for i, s1 in enumerate(sections):
            for s2 in sections[i + 1:]:
                for c1 in by_section[s1][:5]:  # Limiter
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

    async def _detect_cross_relations(
        self,
        pairs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Détecte relations entre paires de concepts via LLM."""

        if not pairs:
            return []

        # Construire prompt
        prompt = self._build_cross_relation_prompt(pairs)

        try:
            response = await self._llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": CROSS_RELATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            # Parser réponse
            import json
            import re

            text = response.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return data.get("relations", [])

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2] Cross-relation detection failed: {e}")

        return []

    def _build_cross_relation_prompt(self, pairs: List[Dict[str, Any]]) -> str:
        """Construit prompt pour détection relations."""
        import json
        pairs_json = json.dumps(pairs[:30], ensure_ascii=False, indent=2)
        return f"""Analyze these concept pairs and identify semantic relations.

## Concept Pairs
{pairs_json}

## Instructions
1. For each pair, determine if a meaningful relation exists
2. Only include relations with clear semantic connection
3. Provide predicate (verb/phrase) and confidence

Return JSON with "relations" array."""

    async def _phase_semantic_consolidation(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase SEMANTIC_CONSOLIDATION: Pass 3 - Extractive Verification.

        ADR_GRAPH_FIRST_ARCHITECTURE - Pass 3

        SEULE source de relations sémantiques prouvées.
        Chaque relation DOIT avoir:
        - evidence_context_ids[] non vide
        - Quote extractive du texte source

        Pipeline:
        1. Candidate generation: co-présence Topic/Section
        2. Extractive verification: LLM cite le passage exact ou ABSTAIN
        3. Relation writing: persiste uniquement si preuve valide

        IMPORTANT: ABSTAIN préféré à relation douteuse.
        """
        from knowbase.relations.semantic_consolidation_pass3 import run_pass3_consolidation
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.common.llm_router import get_llm_router
        from knowbase.config.settings import get_settings

        logger.info(
            f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] Starting for doc {job.document_id}"
        )

        try:
            # Initialiser clients
            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                logger.warning(
                    f"[OSMOSE:Pass3] Neo4j not connected, skipping semantic consolidation"
                )
                return

            llm_router = get_llm_router()

            # Exécuter Pass 3
            pass3_stats = await run_pass3_consolidation(
                document_id=job.document_id,
                neo4j_client=neo4j_client,
                llm_router=llm_router,
                tenant_id=job.tenant_id,
                max_candidates=50
            )

            # Mettre à jour stats
            stats.pass3_candidates = pass3_stats.candidates_generated
            stats.pass3_verified = pass3_stats.relations_created
            stats.pass3_abstained = pass3_stats.abstained

            logger.info(
                f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] Complete: "
                f"{stats.pass3_verified}/{stats.pass3_candidates} verified, "
                f"{stats.pass3_abstained} abstained"
            )

        except Exception as e:
            logger.error(
                f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] Failed: {e}",
                exc_info=True
            )
            stats.errors.append(f"SEMANTIC_CONSOLIDATION: {e}")

    # =========================================================================
    # CORPUS-LEVEL PHASES (Pass 4)
    # =========================================================================

    async def _phase_entity_resolution(self, job: Pass2Job, stats: Pass2Stats):
        """
        Pass 4a: Entity Resolution corpus-level (PATCH-ER).

        Fusionne les CanonicalConcepts dupliqués cross-documents.
        Crée des relations MERGED_INTO réversibles.

        Note: Cette phase travaille sur le corpus ENTIER, pas juste un document.
        Le job.document_id sert uniquement de point d'entrée.
        """
        from knowbase.consolidation.corpus_er_pipeline import CorpusERPipeline

        logger.info(
            f"[OSMOSE:Pass4a:ENTITY_RESOLUTION] Starting corpus-level ER"
        )

        try:
            # Lancer l'Entity Resolution sur tout le corpus
            er_pipeline = CorpusERPipeline(tenant_id=job.tenant_id)
            er_stats = await er_pipeline.run()

            # Mettre à jour stats
            stats.er_candidates = er_stats.candidates_found
            stats.er_merged = er_stats.auto_merged
            stats.er_proposals = er_stats.proposals_created

            # Legacy mapping
            stats.cross_doc_concepts = stats.er_merged

            logger.info(
                f"[OSMOSE:Pass4a:ENTITY_RESOLUTION] Complete: "
                f"{stats.er_merged} merged, {stats.er_proposals} proposals"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass4a:ENTITY_RESOLUTION] Failed: {e}")
            stats.errors.append(f"ENTITY_RESOLUTION: {e}")

    async def _phase_corpus_links(self, job: Pass2Job, stats: Pass2Stats):
        """
        Pass 4b: Corpus Links (PATCH-LINK).

        Crée des liens faibles cross-documents:
        - CO_OCCURS_IN_CORPUS: concepts qui apparaissent ensemble dans ≥2 documents

        IMPORTANT: Phase déterministe, SANS LLM.
        Ces liens sont des "indices" pour la navigation, pas des relations sémantiques.
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        logger.info(
            f"[OSMOSE:Pass4b:CORPUS_LINKS] Starting corpus-level linking"
        )

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:Pass4b:CORPUS_LINKS] Neo4j not connected, skipping")
            return

        try:
            # Créer les relations CO_OCCURS_IN_CORPUS
            # Deux concepts "co-occur" s'ils apparaissent dans ≥2 documents différents
            query = """
            // Trouver les paires de concepts qui co-occurent dans ≥2 documents
            MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
            MATCH (c2:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c1.canonical_id < c2.canonical_id  // Éviter doublons
              AND coalesce(c1.concept_type, '') <> 'TOPIC'
              AND coalesce(c2.concept_type, '') <> 'TOPIC'

            // Trouver les documents communs via MENTIONED_IN
            MATCH (c1)-[:MENTIONED_IN]->(ctx1:SectionContext)-[:IN_DOC]->(doc:DocumentContext)
            MATCH (c2)-[:MENTIONED_IN]->(ctx2:SectionContext)-[:IN_DOC]->(doc)
            WHERE ctx1.tenant_id = $tenant_id AND ctx2.tenant_id = $tenant_id

            WITH c1, c2, collect(DISTINCT doc.doc_id) AS shared_docs
            WHERE size(shared_docs) >= 2  // Co-occurrence dans ≥2 documents

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

            RETURN count(r) AS links_created
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=job.tenant_id)
                record = result.single()
                links_created = record["links_created"] if record else 0

            stats.corpus_links_created = links_created
            stats.co_occurs_relations = links_created

            logger.info(
                f"[OSMOSE:Pass4b:CORPUS_LINKS] Complete: {links_created} CO_OCCURS_IN_CORPUS relations"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass4b:CORPUS_LINKS] Failed: {e}")
            stats.errors.append(f"CORPUS_LINKS: {e}")

    # Legacy method for backward compatibility
    async def _phase_cross_doc(self, job: Pass2Job, stats: Pass2Stats):
        """
        DEPRECATED: Utiliser _phase_entity_resolution + _phase_corpus_links.
        Conservé pour compatibilité.
        """
        logger.warning(
            "[OSMOSE:DEPRECATED] _phase_cross_doc is deprecated. "
            "Use _phase_entity_resolution and _phase_corpus_links instead."
        )
        # Exécuter les deux nouvelles phases
        await self._phase_entity_resolution(job, stats)
        await self._phase_corpus_links(job, stats)

    async def _update_corpus_level_scores(self, job: Pass2Job) -> None:
        """
        Met à jour les scores corpus-level des concepts dans Neo4j.

        Calcule:
        - document_frequency: Nombre de documents mentionnant le concept
        - corpus_centrality: Score de centralité dans le graphe global
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:Pass2:CROSS_DOC] Neo4j not connected, skipping score update")
            return

        try:
            # Update document_frequency pour chaque concept du job
            concept_ids = [c.get("id") for c in job.concepts if c.get("id")]

            if not concept_ids:
                return

            query = """
            UNWIND $concept_ids AS cid
            MATCH (c:CanonicalConcept {canonical_id: cid, tenant_id: $tenant_id})
            OPTIONAL MATCH (c)<-[:INSTANCE_OF]-(p:ProtoConcept)
            WITH c, count(DISTINCT p.document_id) AS doc_freq
            SET c.document_frequency = doc_freq,
                c.corpus_updated_at = datetime()
            RETURN count(c) AS updated
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_ids=concept_ids,
                    tenant_id=job.tenant_id
                )
                record = result.single()
                updated_count = record["updated"] if record else 0

            logger.info(
                f"[OSMOSE:Pass2:CROSS_DOC] Updated corpus scores for {updated_count} concepts"
            )

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2:CROSS_DOC] Score update failed: {e}")

    async def process_background_queue(self, max_jobs: int = 10):
        """
        Traite les jobs en attente dans la queue.

        Appelé par un worker background ou un scheduler.

        Args:
            max_jobs: Nombre max de jobs à traiter
        """
        processed = 0

        while self._job_queue and processed < max_jobs:
            job = self._job_queue.pop(0)

            if job.mode == Pass2Mode.SCHEDULED:
                # Les jobs scheduled ne sont traités que par le scheduler nocturne
                self._job_queue.append(job)
                continue

            logger.info(f"[OSMOSE:Pass2] Processing background job {job.job_id}")
            await self._execute_pass2(job)
            processed += 1

        logger.info(
            f"[OSMOSE:Pass2] Background queue processed: "
            f"{processed} jobs, {len(self._job_queue)} remaining"
        )

    @property
    def queue_size(self) -> int:
        """Nombre de jobs en attente."""
        return len(self._job_queue)

    @property
    def running_jobs(self) -> List[str]:
        """IDs des jobs en cours."""
        return list(self._running_jobs.keys())


# =============================================================================
# Prompts
# =============================================================================

CROSS_RELATION_SYSTEM_PROMPT = """You are OSMOSE Relation Detector (Pass 2).

Your task is to identify semantic relations between concept pairs from different document sections.

## Output Format
```json
{
  "relations": [
    {
      "source_id": "concept_a_id",
      "target_id": "concept_b_id",
      "predicate": "enables",
      "confidence": 0.85,
      "bidirectional": false
    }
  ]
}
```

## Predicate Guidelines
Use clear, semantic predicates:
- enables, requires, depends_on (dependency)
- implements, part_of, contains (composition)
- applies_to, governs, constrains (scope)
- contradicts, supersedes, extends (relationship)

## Rules
- Only include relations with confidence >= 0.6
- Prefer specific predicates over vague ones
- Consider type compatibility (entity-entity, rule-process, etc.)
- No self-relations"""


# =============================================================================
# Factory Pattern
# =============================================================================

_orchestrator_instance: Optional[Pass2Orchestrator] = None


def get_pass2_orchestrator(tenant_id: str = "default") -> Pass2Orchestrator:
    """
    Récupère l'instance singleton de l'orchestrateur.

    Args:
        tenant_id: ID tenant

    Returns:
        Pass2Orchestrator instance
    """
    global _orchestrator_instance

    if _orchestrator_instance is None:
        _orchestrator_instance = Pass2Orchestrator(tenant_id=tenant_id)

    return _orchestrator_instance
