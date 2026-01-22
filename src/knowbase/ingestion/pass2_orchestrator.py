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

# ADR SCOPE Discursive Candidate Mining
from knowbase.relations.scope_candidate_miner import (
    ScopeCandidateMiner,
    get_mining_stats,
)
from knowbase.relations.scope_verifier import (
    ScopeVerifier,
    candidate_to_raw_assertion,
    get_scope_verifier,
)
from knowbase.relations.types import ScopeMiningConfig

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

    # Pass 2c: Assertions normatives (ADR_NORMATIVE_RULES_SPEC_FACTS)
    NORMATIVE_EXTRACTION = "normative_extraction"  # NormativeRule + SpecFact

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
    NORMATIVE_EXTRACTION = "normative_extraction"  # Pass 2c (ADR_NORMATIVE_RULES_SPEC_FACTS)
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

    # ADR SCOPE Discursive Candidate Mining
    scope_sections_processed: int = 0
    scope_candidates_mined: int = 0
    scope_asserted: int = 0
    scope_abstained: int = 0

    # Pass 2c: Normative Extraction (ADR_NORMATIVE_RULES_SPEC_FACTS)
    normative_rules_extracted: int = 0
    normative_rules_deduplicated: int = 0
    spec_facts_extracted: int = 0
    spec_facts_deduplicated: int = 0

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
                # ADR_NORMATIVE_RULES_SPEC_FACTS: Pass 2c (NormativeRule + SpecFact)
                "normative_extraction",
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

            # Phase 2c: NORMATIVE_EXTRACTION (ADR_NORMATIVE_RULES_SPEC_FACTS)
            if Pass2Phase.NORMATIVE_EXTRACTION in job.phases:
                await self._phase_normative_extraction(job, stats)
                phases_completed.append(Pass2Phase.NORMATIVE_EXTRACTION.value)

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
            f"scope={stats.scope_asserted}/{stats.scope_candidates_mined}, "
            f"normative_rules={stats.normative_rules_extracted}, spec_facts={stats.spec_facts_extracted}, "
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
            # 1. Connecter à Neo4j
            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                logger.warning(
                    f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] Neo4j not connected, skipping"
                )
                return

            # 2. Extraire topics depuis SectionContext (refactored)
            # Utilise les sections déjà extraites lors de l'ingestion
            # plutôt que de parser le texte brut
            extractor = StructuralTopicExtractor()
            extraction_result = extractor.extract_topics_from_section_contexts(
                document_id=job.document_id,
                neo4j_driver=neo4j_client.driver,
                tenant_id=job.tenant_id,
                max_topics=30,  # Gating anti-explosion
                max_level=2     # H1 + H2
            )

            stats.structural_topics_count = len(extraction_result.topics)

            if not extraction_result.topics:
                logger.info(
                    f"[OSMOSE:Pass2a:STRUCTURAL_TOPICS] No topics extracted for {job.document_id}"
                )
                return

            # 3. Écrire dans Neo4j (Topics + HAS_TOPIC)
            writer = TopicNeo4jWriter(neo4j_client, tenant_id=job.tenant_id)
            write_stats = writer.write_topics(job.document_id, extraction_result.topics)

            # 4. Construire COVERS (déterministe, basé sur MENTIONED_IN + salience)
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
            MATCH (dc:DocumentChunk {doc_id: $document_id, tenant_id: $tenant_id})
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
        from knowbase.relations.types import RawAssertionFlags, AssertionKind
        # ADR Relations Discursivement Déterminées
        from knowbase.relations.discursive_pattern_extractor import (
            DiscursivePatternExtractor,
            get_discursive_pattern_extractor,
        )

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

            # Persister les relations LLM extraites (EXPLICIT)
            writer = get_raw_assertion_writer(
                tenant_id=job.tenant_id,
                extractor_version="pass2_segment_v1",
                model_used="gpt-4o-mini"
            )
            writer.reset_stats()

            written_llm_count = 0
            if extraction_result.relations:
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
                        evidence_context_ids=rel.evidence_context_ids,
                        # ADR Relations Discursivement Déterminées: LLM = EXPLICIT
                        assertion_kind=AssertionKind.EXPLICIT,
                    )
                    if result:
                        written_llm_count += 1

                logger.info(
                    f"[OSMOSE:Pass2:ENRICH_RELATIONS] Persisted {written_llm_count}/{len(extraction_result.relations)} LLM relations (EXPLICIT)"
                )

            # ===== ADR Relations Discursivement Déterminées =====
            # Extraction des relations discursives via patterns textuels
            # Contrat E1-E6: Pattern-first, concepts existants uniquement
            discursive_extractor = get_discursive_pattern_extractor()

            # Préparer les concepts pour l'extracteur discursif
            # Format: [{"concept_id": str, "canonical_name": str, "surface_forms": List[str]}]
            # Note: Les concepts peuvent avoir "canonical_id", "concept_id", ou "id" selon la source
            concepts_for_discursive = [
                {
                    "concept_id": c.get("canonical_id") or c.get("concept_id") or c.get("id") or "",
                    "canonical_name": c.get("canonical_name") or c.get("name") or "",
                    "surface_forms": c.get("surface_forms") or [c.get("canonical_name") or c.get("name") or ""],
                }
                for c in job.concepts
            ]

            # Concaténer le texte des segments pour l'analyse discursive
            full_text = " ".join([s.get("text", "") for s in segments])

            discursive_result = discursive_extractor.extract(
                text=full_text,
                concepts=concepts_for_discursive,
                document_id=job.document_id,
            )

            written_discursive_count = 0
            if discursive_result.valid_candidates:
                for candidate in discursive_result.valid_candidates:
                    result = writer.write_assertion(
                        subject_concept_id=candidate.subject_concept_id,
                        object_concept_id=candidate.object_concept_id,
                        predicate_raw=candidate.predicate_raw,
                        evidence_text=candidate.evidence_text,
                        source_doc_id=job.document_id,
                        source_chunk_id=f"{job.document_id}_discursive",
                        confidence=candidate.pattern_confidence,
                        source_language="MULTI",
                        flags=RawAssertionFlags(cross_sentence=False),
                        relation_type=candidate.relation_type,
                        type_confidence=candidate.pattern_confidence,
                        evidence_span_start=candidate.evidence_start,
                        evidence_span_end=candidate.evidence_end,
                        # ADR Relations Discursivement Déterminées: Pattern = DISCURSIVE
                        assertion_kind=AssertionKind.DISCURSIVE,
                        discursive_basis=[candidate.discursive_basis],
                    )
                    if result:
                        written_discursive_count += 1

                logger.info(
                    f"[OSMOSE:Pass2:ENRICH_RELATIONS] Persisted {written_discursive_count}/{len(discursive_result.valid_candidates)} discursive relations"
                )

            # ===== ADR SCOPE Discursive Candidate Mining =====
            # Mining de relations basé sur co-présence dans SectionContext
            # Ref: doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
            written_scope_count = 0
            scope_abstained_count = 0
            scope_sections_count = 0
            scope_candidates_count = 0

            try:
                from knowbase.common.clients.neo4j_client import get_neo4j_client
                from knowbase.config.settings import get_settings

                settings = get_settings()
                neo4j_client = get_neo4j_client(
                    uri=settings.neo4j_uri,
                    user=settings.neo4j_user,
                    password=settings.neo4j_password,
                    database="neo4j"
                )

                if neo4j_client.is_connected():
                    # Récupérer les sections du document avec concepts
                    sections_query = """
                    MATCH (sc:SectionContext {tenant_id: $tenant_id})
                    WHERE sc.doc_id = $document_id
                    MATCH (sc)-[:CONTAINS]->(di:DocItem)
                    MATCH (pc:ProtoConcept)-[:ANCHORED_IN]->(di)
                    WITH sc, count(DISTINCT pc) as concept_count
                    WHERE concept_count >= 2
                    RETURN sc.context_id as section_id
                    """

                    with neo4j_client.driver.session(database="neo4j") as session:
                        result = session.run(
                            sections_query,
                            tenant_id=job.tenant_id,
                            document_id=job.document_id
                        )
                        section_ids = [r["section_id"] for r in result]

                    if section_ids:
                        # Configurer le miner et verifier SCOPE
                        scope_config = ScopeMiningConfig(
                            max_pairs_per_scope=20,  # Budget par section
                            top_k_pivots=5,
                        )
                        scope_miner = ScopeCandidateMiner(
                            neo4j_client.driver,
                            config=scope_config,
                            tenant_id=job.tenant_id
                        )
                        scope_verifier = get_scope_verifier(config=scope_config)

                        scope_sections_count = len(section_ids)

                        # Traiter chaque section
                        for section_id in section_ids:
                            try:
                                # 1. Mining
                                mining_result = scope_miner.mine_section(section_id)
                                candidates = mining_result.candidates
                                scope_candidates_count += len(candidates)

                                if not candidates:
                                    continue

                                # 2. Verification LLM
                                batch_result = await scope_verifier.verify_batch(
                                    candidates, max_concurrent=3
                                )

                                scope_abstained_count += batch_result.abstained

                                # 3. Écrire les relations validées
                                for cand, vr in zip(candidates, batch_result.results):
                                    if vr.verdict == "ASSERT":
                                        raw_assertion = candidate_to_raw_assertion(
                                            cand, vr, tenant_id=job.tenant_id
                                        )
                                        if raw_assertion:
                                            result = writer.write_assertion(
                                                subject_concept_id=raw_assertion.subject_concept_id,
                                                object_concept_id=raw_assertion.object_concept_id,
                                                predicate_raw=raw_assertion.predicate_raw,
                                                evidence_text=raw_assertion.evidence_text,
                                                source_doc_id=raw_assertion.source_doc_id,
                                                source_chunk_id=raw_assertion.source_chunk_id,
                                                confidence=raw_assertion.confidence_final,
                                                source_language="MULTI",
                                                flags=raw_assertion.flags,
                                                relation_type=raw_assertion.relation_type,
                                                type_confidence=raw_assertion.type_confidence,
                                                assertion_kind=raw_assertion.assertion_kind,
                                                discursive_basis=raw_assertion.discursive_basis,
                                            )
                                            if result:
                                                written_scope_count += 1

                            except Exception as section_err:
                                logger.warning(
                                    f"[OSMOSE:Pass2:SCOPE] Section {section_id} error: {section_err}"
                                )

                        logger.info(
                            f"[OSMOSE:Pass2:SCOPE] Complete: {scope_sections_count} sections, "
                            f"{scope_candidates_count} candidates, "
                            f"{written_scope_count} asserted, {scope_abstained_count} abstained"
                        )

            except Exception as scope_err:
                logger.warning(f"[OSMOSE:Pass2:SCOPE] SCOPE extraction skipped: {scope_err}")

            # Update stats for SCOPE
            stats.scope_sections_processed = scope_sections_count
            stats.scope_candidates_mined = scope_candidates_count
            stats.scope_asserted = written_scope_count
            stats.scope_abstained = scope_abstained_count

            # Update stats to include LLM, discursive, AND SCOPE relations
            stats.enrich_relations_count = written_llm_count + written_discursive_count + written_scope_count

            logger.info(
                f"[OSMOSE:Pass2:ENRICH_RELATIONS] Complete: "
                f"{extraction_result.segments_processed} segments processed, "
                f"{written_llm_count} LLM, {written_discursive_count} discursive, {written_scope_count} SCOPE relations"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2:ENRICH_RELATIONS] Failed: {e}", exc_info=True)
            stats.errors.append(f"ENRICH_RELATIONS: {e}")

    async def _get_document_segments(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Récupère les segments d'un document depuis Neo4j.

        Option C (Structural Graph): Utilise TypeAwareChunks si disponibles.
        Fallback: Utilise DocumentChunks (legacy).

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
            with neo4j_client.driver.session(database="neo4j") as session:
                # Option C: Essayer d'abord les TypeAwareChunks (Structural Graph)
                # Filtrer par is_relation_bearing=true pour n'avoir que les narratifs
                type_aware_query = """
                MATCH (tac:TypeAwareChunk {doc_id: $document_id, tenant_id: $tenant_id})
                WHERE tac.is_relation_bearing = true
                RETURN tac.chunk_id AS segment_id,
                       tac.text AS text,
                       tac.section_id AS section_id,
                       0 AS char_offset,
                       tac.kind AS chunk_kind
                ORDER BY tac.page_no, tac.chunk_id
                """

                result = session.run(
                    type_aware_query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )

                segments = []
                for record in result:
                    segments.append({
                        "segment_id": record["segment_id"],
                        "text": record["text"] or "",
                        "section_id": record["section_id"],
                        "char_offset": record["char_offset"] or 0,
                        "chunk_kind": record.get("chunk_kind"),  # Métadonnée Option C
                    })

                if segments:
                    logger.info(
                        f"[OSMOSE:Pass2] Using {len(segments)} TypeAwareChunks "
                        f"(Option C) for document {document_id}"
                    )
                    return segments

                # Fallback: DocumentChunks (legacy)
                legacy_query = """
                MATCH (dc:DocumentChunk {doc_id: $document_id, tenant_id: $tenant_id})
                RETURN dc.chunk_id AS segment_id,
                       dc.text_preview AS text,
                       dc.section_id AS section_id,
                       dc.char_start AS char_offset
                ORDER BY dc.chunk_index
                """

                result = session.run(
                    legacy_query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )

                for record in result:
                    segments.append({
                        "segment_id": record["segment_id"],
                        "text": record["text"] or "",
                        "section_id": record["section_id"],
                        "char_offset": record["char_offset"] or 0
                    })

                if segments:
                    logger.info(
                        f"[OSMOSE:Pass2] Using {len(segments)} DocumentChunks "
                        f"(legacy) for document {document_id}"
                    )

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
            MATCH (p:ProtoConcept {doc_id: $document_id, tenant_id: $tenant_id})
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

    async def _get_document_docitems(
        self,
        document_id: str,
        neo4j_client
    ) -> List[Dict[str, Any]]:
        """
        Récupère les DocItem d'un document depuis Neo4j.

        DocItem est le modèle principal d'extraction (10K+ par corpus typique).
        Utilisé par NORMATIVE_EXTRACTION au lieu des Segments.

        Returns:
            Liste de dicts avec item_id, text, section_id, item_type, page_no
        """
        if not neo4j_client.is_connected():
            return []

        try:
            query = """
            MATCH (di:DocItem {doc_id: $document_id, tenant_id: $tenant_id})
            WHERE di.text IS NOT NULL
              AND size(di.text) >= 20
            RETURN di.item_id AS item_id,
                   di.text AS text,
                   di.section_id AS section_id,
                   di.item_type AS item_type,
                   di.page_no AS page_no,
                   di.charspan_start AS char_start,
                   di.charspan_end AS char_end
            ORDER BY di.reading_order_index
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )

                docitems = []
                for record in result:
                    docitems.append({
                        "item_id": record["item_id"],
                        "text": record["text"] or "",
                        "section_id": record["section_id"],
                        "item_type": record["item_type"],
                        "page_no": record["page_no"],
                        "char_start": record["char_start"],
                        "char_end": record["char_end"],
                    })

                return docitems

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2c] Failed to get DocItems: {e}")
            return []

    async def _get_all_document_ids(
        self,
        neo4j_client,
        tenant_id: str
    ) -> List[str]:
        """
        Récupère tous les IDs de documents du corpus depuis Neo4j.

        Utilisé quand document_id == "all" pour traiter tout le corpus.

        Returns:
            Liste des document IDs uniques
        """
        if not neo4j_client.is_connected():
            return []

        try:
            # Récupérer les doc_id uniques depuis DocItem
            query = """
            MATCH (di:DocItem {tenant_id: $tenant_id})
            WHERE di.doc_id IS NOT NULL
            RETURN DISTINCT di.doc_id AS doc_id
            ORDER BY doc_id
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=tenant_id)
                doc_ids = [record["doc_id"] for record in result if record["doc_id"]]

            logger.info(
                f"[OSMOSE:Pass2c] Found {len(doc_ids)} documents in corpus"
            )
            return doc_ids

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2c] Failed to get document IDs: {e}")
            return []

    # =========================================================================
    # Pass 2c: NORMATIVE_EXTRACTION (ADR_NORMATIVE_RULES_SPEC_FACTS)
    # =========================================================================

    async def _phase_normative_extraction(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase NORMATIVE_EXTRACTION: Extraction de NormativeRule et SpecFact.

        ADR_NORMATIVE_RULES_SPEC_FACTS - Pass 2c

        Pipeline:
        1. NormativePatternExtractor: Détecte les marqueurs modaux (must/shall/required)
        2. StructureParser: Parse les tables et listes clé-valeur
        3. NormativeWriter: Persiste dans Neo4j avec déduplication

        Les NormativeRule et SpecFact sont NON-TRAVERSABLES mais indexables.

        NOTE: Si document_id == "all", itère sur tous les documents du corpus.
        """
        from knowbase.relations.normative_pattern_extractor import (
            NormativePatternExtractor,
        )
        from knowbase.relations.structure_parser import StructureParser
        from knowbase.relations.normative_writer import (
            NormativeWriter,
            get_normative_writer,
        )
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        logger.info(
            f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Starting for doc {job.document_id}"
        )

        try:
            # Initialiser Neo4j client
            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                logger.warning(
                    f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Neo4j not connected, skipping"
                )
                return

            # Déterminer les documents à traiter
            # Si document_id == "all" ou vide, traiter tous les documents du corpus
            doc_ids_to_process = []
            if not job.document_id or job.document_id == "all":
                # Récupérer tous les document IDs depuis Neo4j
                doc_ids_to_process = await self._get_all_document_ids(neo4j_client, job.tenant_id)
                logger.info(
                    f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Corpus mode: {len(doc_ids_to_process)} documents to process"
                )
            else:
                doc_ids_to_process = [job.document_id]

            if not doc_ids_to_process:
                logger.info(
                    f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] No documents found for tenant {job.tenant_id}"
                )
                return

            # Initialiser les extracteurs
            normative_extractor = NormativePatternExtractor(min_confidence=0.6)
            structure_parser = StructureParser(min_confidence=0.6)

            # Initialiser le writer
            writer = get_normative_writer(
                neo4j_client=neo4j_client,
                tenant_id=job.tenant_id,
            )

            total_rules = 0
            total_rules_dedup = 0
            total_facts = 0
            total_facts_dedup = 0
            total_links = 0

            # Traiter chaque document
            for doc_id in doc_ids_to_process:
                # Récupérer les DocItem du document
                docitems = await self._get_document_docitems(doc_id, neo4j_client)

                if not docitems:
                    logger.debug(
                        f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] No DocItem for {doc_id}, skipping"
                    )
                    continue

                logger.info(
                    f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Processing {doc_id}: {len(docitems)} DocItems"
                )

                all_rules = []
                all_facts = []

                # Traiter chaque DocItem
                for docitem in docitems:
                    item_id = docitem.get("item_id", "")
                    item_text = docitem.get("text", "")
                    section_id = docitem.get("section_id")

                    if not item_text or len(item_text) < 20:
                        continue

                    # 1. Extraire les règles normatives
                    rules = normative_extractor.extract_from_text(
                        text=item_text,
                        source_doc_id=doc_id,
                        source_chunk_id=item_id,
                        source_segment_id=item_id,
                        evidence_section=section_id,
                        tenant_id=job.tenant_id,
                    )
                    all_rules.extend(rules)

                    # 2. Extraire les SpecFacts depuis les structures
                    facts = structure_parser.extract_from_text(
                        text=item_text,
                        source_doc_id=doc_id,
                        source_chunk_id=item_id,
                        source_segment_id=item_id,
                        evidence_section=section_id,
                        tenant_id=job.tenant_id,
                    )
                    all_facts.extend(facts)

                # 3. Persister dans Neo4j
                if all_rules:
                    rule_stats = writer.write_rules(all_rules)
                    total_rules += rule_stats.rules_written
                    total_rules_dedup += rule_stats.rules_deduplicated

                if all_facts:
                    fact_stats = writer.write_facts(all_facts)
                    total_facts += fact_stats.facts_written
                    total_facts_dedup += fact_stats.facts_deduplicated

                # 4. Créer les liens vers le document
                links_created = writer.link_to_document(doc_id)
                total_links += links_created

                logger.debug(
                    f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] {doc_id}: "
                    f"{len(all_rules)} rules, {len(all_facts)} facts"
                )

            # Mettre à jour les stats globales
            stats.normative_rules_extracted = total_rules
            stats.normative_rules_deduplicated = total_rules_dedup
            stats.spec_facts_extracted = total_facts
            stats.spec_facts_deduplicated = total_facts_dedup

            logger.info(
                f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Complete: "
                f"{len(doc_ids_to_process)} docs processed, "
                f"{total_rules} rules (+{total_rules_dedup} dedup), "
                f"{total_facts} facts (+{total_facts_dedup} dedup), "
                f"{total_links} doc links"
            )

        except Exception as e:
            logger.error(
                f"[OSMOSE:Pass2c:NORMATIVE_EXTRACTION] Failed: {e}",
                exc_info=True
            )
            stats.errors.append(f"NORMATIVE_EXTRACTION: {e}")

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

        NOTE: Si document_id == "all", itère sur tous les documents du corpus.
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

            # Déterminer les documents à traiter
            # Si document_id == "all" ou vide, traiter tous les documents du corpus
            doc_ids_to_process = []
            if not job.document_id or job.document_id == "all":
                # Récupérer tous les document IDs depuis Neo4j
                doc_ids_to_process = await self._get_all_document_ids(neo4j_client, job.tenant_id)
                logger.info(
                    f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] Corpus mode: {len(doc_ids_to_process)} documents to process"
                )
            else:
                doc_ids_to_process = [job.document_id]

            if not doc_ids_to_process:
                logger.info(
                    f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] No documents found for tenant {job.tenant_id}"
                )
                return

            # Agrégateurs globaux
            total_candidates = 0
            total_verified = 0
            total_abstained = 0

            # Traiter chaque document
            for doc_id in doc_ids_to_process:
                logger.info(f"[OSMOSE:Pass3] Processing document {doc_id}")

                # Exécuter Pass 3 pour ce document
                pass3_stats = await run_pass3_consolidation(
                    document_id=doc_id,
                    neo4j_client=neo4j_client,
                    llm_router=llm_router,
                    tenant_id=job.tenant_id,
                    max_candidates=50
                )

                total_candidates += pass3_stats.candidates_generated
                total_verified += pass3_stats.relations_created
                total_abstained += pass3_stats.abstained

                if pass3_stats.candidates_generated > 0:
                    logger.info(
                        f"[OSMOSE:Pass3] {doc_id}: {pass3_stats.relations_created}/{pass3_stats.candidates_generated} verified"
                    )

            # Mettre à jour stats globales
            stats.pass3_candidates = total_candidates
            stats.pass3_verified = total_verified
            stats.pass3_abstained = total_abstained

            logger.info(
                f"[OSMOSE:Pass3:SEMANTIC_CONSOLIDATION] Complete: "
                f"{len(doc_ids_to_process)} docs processed, "
                f"{total_verified}/{total_candidates} verified, "
                f"{total_abstained} abstained"
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
            WITH c, count(DISTINCT p.doc_id) AS doc_freq
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
