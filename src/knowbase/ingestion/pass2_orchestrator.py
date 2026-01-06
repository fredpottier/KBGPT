"""
Hybrid Anchor Model - Pass 2 Orchestrator

Orchestrateur configurable pour l'enrichissement Pass 2.
Modes d'exécution:
- inline: Exécuté immédiatement après Pass 1 (Burst mode)
- background: Job asynchrone (mode normal)
- scheduled: Batch nocturne (corpus stable)

Phases Pass 2:
- CLASSIFY_FINE: Classification LLM fine-grained
- ENRICH_RELATIONS: Relations cross-segment + inférences
- CROSS_DOC: Consolidation corpus-level

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
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

logger = logging.getLogger(__name__)


class Pass2Mode(str, Enum):
    """Modes d'exécution Pass 2."""

    INLINE = "inline"          # Exécuté immédiatement après Pass 1
    BACKGROUND = "background"  # Job asynchrone (mode normal)
    SCHEDULED = "scheduled"    # Batch nocturne (corpus stable)
    DISABLED = "disabled"      # Pass 2 désactivé


class Pass2Phase(str, Enum):
    """Phases de Pass 2."""

    # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a: Structural Topics / COVERS
    STRUCTURAL_TOPICS = "structural_topics"  # NEW: Extract Topics from H1/H2, create COVERS

    # Pass 2b: Classification et Relations
    CLASSIFY_FINE = "classify_fine"
    ENRICH_RELATIONS = "enrich_relations"

    # Cross-document consolidation
    CROSS_DOC = "cross_doc"


@dataclass
class Pass2Stats:
    """Statistiques d'exécution Pass 2."""

    document_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    mode: Pass2Mode = Pass2Mode.BACKGROUND

    # Par phase
    # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a
    structural_topics_count: int = 0
    covers_relations_count: int = 0

    # Pass 2b
    classify_fine_count: int = 0
    classify_fine_changes: int = 0
    enrich_relations_count: int = 0

    # Cross-doc
    cross_doc_concepts: int = 0

    # Erreurs
    errors: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass
class Pass2Job:
    """Job Pass 2 en attente."""

    job_id: str
    document_id: str
    tenant_id: str
    mode: Pass2Mode
    phases: List[Pass2Phase]
    concepts: List[Dict[str, Any]]
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
                # ADR_GRAPH_FIRST_ARCHITECTURE: Pass 2a en premier (Topics/COVERS)
                "structural_topics",
                # Puis Pass 2b (Classification + Relations)
                "classify_fine", "enrich_relations",
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

        Args:
            document_id: ID du document traité en Pass 1
            concepts: CanonicalConcepts créés en Pass 1
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
            # ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a: STRUCTURAL_TOPICS
            # Doit s'exécuter AVANT les autres phases pour créer Topics/COVERS
            if Pass2Phase.STRUCTURAL_TOPICS in job.phases:
                await self._phase_structural_topics(job, stats)
                phases_completed.append(Pass2Phase.STRUCTURAL_TOPICS.value)

            # Phase 2b-1: CLASSIFY_FINE
            if Pass2Phase.CLASSIFY_FINE in job.phases:
                await self._phase_classify_fine(job, stats)
                phases_completed.append(Pass2Phase.CLASSIFY_FINE.value)

            # Phase 2: ENRICH_RELATIONS
            if Pass2Phase.ENRICH_RELATIONS in job.phases:
                await self._phase_enrich_relations(job, stats)
                phases_completed.append(Pass2Phase.ENRICH_RELATIONS.value)

            # Phase 3: CROSS_DOC
            if Pass2Phase.CROSS_DOC in job.phases:
                await self._phase_cross_doc(job, stats)
                phases_completed.append(Pass2Phase.CROSS_DOC.value)

            # ADR 2024-12-30: Update enrichment tracking - Pass 2 complete
            enrichment_tracker.update_pass2_status(
                document_id=job.document_id,
                status=EnrichmentStatus.COMPLETE,
                relations_extracted=stats.enrich_relations_count,
                classifications_updated=stats.classify_fine_changes,
                cross_doc_links=stats.cross_doc_concepts,
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
            f"(topics={stats.structural_topics_count}, covers={stats.covers_relations_count}, "
            f"classify={stats.classify_fine_count}, relations={stats.enrich_relations_count})"
        )

        return stats

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
            # Essayer de récupérer le texte depuis le Document node
            query = """
            MATCH (d:Document {document_id: $document_id, tenant_id: $tenant_id})
            RETURN d.text_content AS text
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if record and record.get("text"):
                    return record["text"]

            # Fallback: concaténer les chunks
            query_chunks = """
            MATCH (dc:DocumentChunk {document_id: $document_id, tenant_id: $tenant_id})
            RETURN dc.text_preview AS text
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

    async def _phase_cross_doc(self, job: Pass2Job, stats: Pass2Stats):
        """
        Phase CROSS_DOC: Consolidation corpus-level.

        - Consolide RawAssertions → CanonicalRelations
        - Regroupe CanonicalConcepts similaires cross-documents
        - Calcule scores corpus-level
        """
        from knowbase.relations.relation_consolidator import get_relation_consolidator
        from knowbase.relations.canonical_relation_writer import get_canonical_relation_writer

        logger.info(
            f"[OSMOSE:Pass2:CROSS_DOC] Starting for doc {job.document_id}"
        )

        try:
            # Étape 1: Consolider les RawAssertions du document en CanonicalRelations
            consolidator = get_relation_consolidator(tenant_id=job.tenant_id)
            consolidator.reset_stats()

            canonical_relations = consolidator.consolidate_all(doc_id=job.document_id)
            stats.cross_doc_concepts = len(canonical_relations)

            if canonical_relations:
                # Étape 2: Persister les CanonicalRelations
                writer = get_canonical_relation_writer(tenant_id=job.tenant_id)
                writer.reset_stats()

                for cr in canonical_relations:
                    writer.write_canonical_relation(cr)

                writer_stats = writer.get_stats()
                logger.info(
                    f"[OSMOSE:Pass2:CROSS_DOC] Persisted {writer_stats.get('written', 0)} CanonicalRelations "
                    f"(merged={writer_stats.get('merged', 0)}, skipped={writer_stats.get('skipped', 0)})"
                )

            # Étape 3: Update scores corpus-level des concepts
            await self._update_corpus_level_scores(job)

            consolidator_stats = consolidator.get_stats()
            logger.info(
                f"[OSMOSE:Pass2:CROSS_DOC] Complete: "
                f"{consolidator_stats.get('canonical_created', 0)} relations consolidated, "
                f"{consolidator_stats.get('validated', 0)} validated"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2:CROSS_DOC] Failed: {e}")
            stats.errors.append(f"CROSS_DOC: {e}")

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
