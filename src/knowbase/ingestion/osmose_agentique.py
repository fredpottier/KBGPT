"""
OSMOSE Agentique - Phase 1.5 Integration

Remplace SemanticPipelineV2 par Architecture Agentique (6 agents).

Architecture:
    Document → OsmoseAgentique → SupervisorAgent (FSM) → Proto-KG
                                      ↓
                     ExtractorOrchestrator → PatternMiner
                           → GatekeeperDelegate → Neo4j Published

Author: OSMOSE Phase 1.5
Date: 2025-10-15
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime
from functools import lru_cache

from knowbase.agents.supervisor.supervisor import SupervisorAgent
from knowbase.agents.base import AgentState
from knowbase.ingestion.osmose_integration import (
    OsmoseIntegrationConfig,
    OsmoseIntegrationResult
)
from knowbase.semantic.segmentation.topic_segmenter import get_topic_segmenter
from knowbase.semantic.config import get_semantic_config
from knowbase.ingestion.text_chunker import get_text_chunker  # Phase 1.6: Chunking
from knowbase.common.clients.qdrant_client import upsert_chunks  # Phase 1.6: Qdrant
from knowbase.common.llm_router import LLMRouter, TaskType, get_llm_router  # Phase 1.8: Document Context
from knowbase.ontology.domain_context_injector import get_domain_context_injector  # Domain Context injection
from knowbase.entity_resolution.deferred_reevaluator import get_deferred_reevaluator  # Phase 2.12: Entity Resolution

# ===== Phase 2 - Hybrid Anchor Model =====
from knowbase.config.feature_flags import is_feature_enabled, get_hybrid_anchor_config
from knowbase.ingestion.enrichment_tracker import (
    get_enrichment_tracker,
    EnrichmentStatus
)  # ADR 2024-12-30: Enrichment tracking
from knowbase.navigation import get_navigation_layer_builder  # ADR: Navigation Layer

# Logger pour ce module (pas de manipulation du root logger pour eviter les doublons)
logger = logging.getLogger(__name__)

# Cache global pour les résumés de documents (Phase 1.8)
# Clé: hash(document_id), Valeur: résumé généré
_document_context_cache: Dict[str, str] = {}


class OsmoseAgentiqueService:
    """
    Service d'intégration OSMOSE Architecture Agentique Phase 1.5.

    Remplace l'approche directe SemanticPipelineV2 par l'orchestration
    via SupervisorAgent (FSM Master).

    Avantages Phase 1.5:
    - Routing intelligent NO_LLM/SMALL/BIG (maîtrise coûts)
    - Budget caps durs (SMALL: 120, BIG: 8, VISION: 2)
    - Quality gates (STRICT/BALANCED/PERMISSIVE)
    - Rate limiting (500/100/50 RPM)
    - Retry logic (1 retry BIG si Gate < 30%)
    - Multi-tenant quotas (Redis)
    """

    def __init__(
        self,
        config: Optional[OsmoseIntegrationConfig] = None,
        supervisor_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialise le service agentique.

        Args:
            config: Configuration OSMOSE (legacy, filtres, feature flags)
            supervisor_config: Configuration SupervisorAgent (FSM, retry)
        """
        self.config = config or OsmoseIntegrationConfig.from_env()
        self.supervisor_config = supervisor_config or {}
        self.supervisor: Optional[SupervisorAgent] = None
        self.topic_segmenter = None  # Lazy init
        self.text_chunker = None  # Lazy init (Phase 1.6)
        self.llm_router = None  # Lazy init (Phase 1.8: Document Context)

        # ===== Phase 2 - Hybrid Anchor Model =====
        self.hybrid_chunker = None  # Lazy init
        self.hybrid_extractor = None  # Lazy init
        self.heuristic_classifier = None  # Lazy init
        self.anchor_scorer = None  # Lazy init
        self.pass2_orchestrator = None  # Lazy init

        # Check if Hybrid Anchor Model is enabled
        self.use_hybrid_anchor = is_feature_enabled("phase_2_hybrid_anchor")

        logger.info(
            f"[OSMOSE AGENTIQUE] Service initialized - OSMOSE enabled: {self.config.enable_osmose}, "
            f"Hybrid Anchor Model: {self.use_hybrid_anchor}"
        )

    def _get_supervisor(self) -> SupervisorAgent:
        """Lazy init du SupervisorAgent."""
        if self.supervisor is None:
            self.supervisor = SupervisorAgent(config=self.supervisor_config)
            logger.info("[OSMOSE AGENTIQUE] SupervisorAgent initialized")

        return self.supervisor

    def _get_topic_segmenter(self):
        """Lazy init du TopicSegmenter."""
        if self.topic_segmenter is None:
            semantic_config = get_semantic_config()
            self.topic_segmenter = get_topic_segmenter(semantic_config)
            logger.info("[OSMOSE AGENTIQUE] TopicSegmenter initialized")

        return self.topic_segmenter

    def _get_text_chunker(self):
        """Lazy init du TextChunker (Phase 1.6)."""
        if self.text_chunker is None:
            self.text_chunker = get_text_chunker(
                model_name="intfloat/multilingual-e5-large",
                chunk_size=512,
                overlap=128
            )
            logger.info("[OSMOSE AGENTIQUE] TextChunker initialized (512 tokens, overlap 128)")

        return self.text_chunker

    def _get_llm_router(self) -> LLMRouter:
        """Lazy init du LLMRouter singleton (Phase 1.8, avec support Burst Mode)."""
        if self.llm_router is None:
            self.llm_router = get_llm_router()  # Singleton avec Burst Mode
            logger.info("[OSMOSE AGENTIQUE] LLMRouter initialized (Phase 1.8)")

        return self.llm_router

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model Lazy Init Methods
    # =========================================================================

    def _get_hybrid_chunker(self):
        """Lazy init du HybridAnchorChunker (Phase 2)."""
        if self.hybrid_chunker is None:
            from knowbase.ingestion.hybrid_anchor_chunker import get_hybrid_anchor_chunker
            self.hybrid_chunker = get_hybrid_anchor_chunker(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HybridAnchorChunker initialized")

        return self.hybrid_chunker

    def _get_hybrid_extractor(self):
        """Lazy init du HybridAnchorExtractor (Phase 2)."""
        if self.hybrid_extractor is None:
            from knowbase.semantic.extraction.hybrid_anchor_extractor import (
                get_hybrid_anchor_extractor
            )
            self.hybrid_extractor = get_hybrid_anchor_extractor(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HybridAnchorExtractor initialized")

        return self.hybrid_extractor

    def _get_heuristic_classifier(self):
        """Lazy init du HeuristicClassifier (Phase 2)."""
        if self.heuristic_classifier is None:
            from knowbase.semantic.classification.heuristic_classifier import (
                get_heuristic_classifier
            )
            self.heuristic_classifier = get_heuristic_classifier(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HeuristicClassifier initialized")

        return self.heuristic_classifier

    def _get_anchor_scorer(self):
        """Lazy init du AnchorBasedScorer (Phase 2)."""
        if self.anchor_scorer is None:
            from knowbase.agents.gatekeeper.anchor_based_scorer import (
                AnchorBasedScorer
            )
            self.anchor_scorer = AnchorBasedScorer(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] AnchorBasedScorer initialized")

        return self.anchor_scorer

    def _get_pass2_orchestrator(self):
        """Lazy init du Pass2Orchestrator (Phase 2)."""
        if self.pass2_orchestrator is None:
            from knowbase.ingestion.pass2_orchestrator import get_pass2_orchestrator
            self.pass2_orchestrator = get_pass2_orchestrator(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] Pass2Orchestrator initialized")

        return self.pass2_orchestrator

    def _extract_document_metadata(self, full_text: str) -> Dict[str, Any]:
        """
        Extrait métadonnées basiques du document sans LLM.

        Phase 1.8: Extraction heuristique titre, headers, mots-clés.

        Args:
            full_text: Texte complet du document

        Returns:
            Dict avec title, headers, keywords
        """
        metadata: Dict[str, Any] = {
            "title": None,
            "headers": [],
            "keywords": []
        }

        lines = full_text.split("\n")
        non_empty_lines = [l.strip() for l in lines if l.strip()]

        # Heuristique titre: première ligne non-vide courte (<100 chars)
        if non_empty_lines:
            first_line = non_empty_lines[0]
            if len(first_line) < 100:
                metadata["title"] = first_line

        # Extraction headers via patterns (# Header, HEADER:, Header majuscule isolé)
        header_patterns = [
            r'^#{1,3}\s+(.+)$',  # Markdown headers
            r'^([A-Z][A-Z0-9\s]{2,50}):?\s*$',  # UPPERCASE headers
            r'^(\d+\.?\s+[A-Z].{5,80})$',  # Numbered headers
        ]

        for line in non_empty_lines[:50]:  # Limiter aux 50 premières lignes
            for pattern in header_patterns:
                match = re.match(pattern, line)
                if match:
                    header = match.group(1).strip()
                    if header and len(header) < 100 and header not in metadata["headers"]:
                        metadata["headers"].append(header)
                        if len(metadata["headers"]) >= 10:
                            break
            if len(metadata["headers"]) >= 10:
                break

        # Extraction mots-clés: termes SAP fréquents + noms propres capitalisés
        sap_keywords = set()

        # Pattern SAP: "SAP X", "S/4HANA", "BTP", etc.
        sap_pattern = r'\b(SAP\s+\w+(?:\s+\w+)?|S/4HANA(?:\s+Cloud)?|BTP|Fiori|HANA|SuccessFactors|Ariba|Concur)\b'
        for match in re.finditer(sap_pattern, full_text, re.IGNORECASE):
            term = match.group(1)
            if term:
                sap_keywords.add(term)

        # Pattern noms propres: mots capitalisés répétés
        proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', full_text)
        noun_counts = Counter(proper_nouns)

        # Garder les plus fréquents (>2 occurrences)
        for noun, count in noun_counts.most_common(20):
            if count > 2 and noun not in ["The", "This", "That", "These", "What", "How", "Where"]:
                sap_keywords.add(noun)

        metadata["keywords"] = list(sap_keywords)[:15]

        return metadata

    async def _generate_document_summary(
        self,
        document_id: str,
        full_text: str,
        max_length: int = 500
    ) -> tuple[str, float]:
        """
        Génère un résumé contextuel du document ET évalue sa densité technique.

        Phase 1.8 Task T1.8.1.0: Document Context Global.
        Phase 1.8.2: Ajout technical_density_hint pour stratégie extraction domain-agnostic.

        Ce résumé est utilisé pour:
        - Désambiguïser les acronymes/abréviations
        - Préférer les noms complets officiels
        - Contexte domaine pour meilleure extraction

        Le technical_density_hint (0.0-1.0) indique si le document contient
        du vocabulaire technique spécialisé nécessitant une extraction LLM.

        Args:
            document_id: ID unique pour cache
            full_text: Texte complet du document
            max_length: Longueur max du résumé (caractères)

        Returns:
            Tuple (résumé contextuel, technical_density_hint 0.0-1.0)
        """
        # Vérifier cache global (inclut maintenant le hint)
        cache_key = hashlib.md5(document_id.encode()).hexdigest()

        if cache_key in _document_context_cache:
            cached = _document_context_cache[cache_key]
            # Support ancien format (string) et nouveau format (tuple)
            if isinstance(cached, tuple):
                logger.info(f"[PHASE1.8:Context] Cache hit for document {document_id[:20]}...")
                return cached
            else:
                # Ancien format: retourner avec hint par défaut
                return (cached, 0.5)

        logger.info(f"[PHASE1.8:Context] Generating document context for {document_id[:20]}...")

        # Extraction métadonnées sans LLM
        metadata = self._extract_document_metadata(full_text)

        # Construire prompt pour LLM
        # Limiter texte envoyé au LLM (premiers 4000 chars + derniers 1000)
        text_sample = full_text[:4000]
        if len(full_text) > 5000:
            text_sample += "\n[...]\n" + full_text[-1000:]

        # Prompt générique (domain-agnostic) avec évaluation densité technique
        system_prompt = """You are a document analyst. Your task is to:
1. Generate a concise document summary (1-2 paragraphs, max 500 characters)
2. Evaluate the technical density of the document

For the summary, focus on:
- Main theme/topic of the document
- Full official names of products, solutions, or key terms mentioned
- Industry or domain context
- Target audience

For technical density evaluation (0.0-1.0):
- 0.0-0.3: Simple text (marketing, general communication, basic explanations)
- 0.3-0.5: Moderate technical content (business documents, standard procedures)
- 0.5-0.7: Technical content (specialized domain vocabulary, acronyms, jargon)
- 0.7-1.0: Highly technical (scientific papers, technical specifications, dense terminology)

Answer in JSON format:
{"summary": "your summary here", "technical_density": 0.X}

Write the summary in the same language as the document."""

        # Injection du Domain Context si disponible
        try:
            injector = get_domain_context_injector()
            system_prompt = injector.inject_context(system_prompt, tenant_id="default")
            logger.info("[PHASE1.8:Context] Domain Context injected into summary prompt")
        except Exception as e:
            logger.debug(f"[PHASE1.8:Context] No Domain Context available: {e}")

        user_prompt = f"""Document metadata:
- Title: {metadata.get('title', 'Unknown')}
- Headers: {', '.join(metadata.get('headers', [])[:5])}
- Keywords detected: {', '.join(metadata.get('keywords', [])[:10])}

Document text sample:
{text_sample}

Analyze this document and provide JSON response:"""

        try:
            llm_router = self._get_llm_router()

            # Utiliser LONG_TEXT_SUMMARY pour ce type de tâche
            response = await llm_router.acomplete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=400
            )

            # Parser la réponse JSON
            import json
            technical_density = 0.5  # Défaut
            summary = response

            try:
                # Chercher JSON dans la réponse
                json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    summary = data.get("summary", response)
                    technical_density = float(data.get("technical_density", 0.5))
                    # Clamp entre 0 et 1
                    technical_density = max(0.0, min(1.0, technical_density))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[PHASE1.8:Context] Failed to parse JSON response: {e}")
                # Garder le response brut comme summary

            # Tronquer si trop long
            if len(summary) > max_length:
                summary = summary[:max_length-3] + "..."

            # Stocker en cache (nouveau format tuple)
            _document_context_cache[cache_key] = (summary, technical_density)

            logger.info(
                f"[PHASE1.8:Context] Generated context ({len(summary)} chars, "
                f"technical_density={technical_density:.2f}) for document {document_id[:20]}..."
            )

            return (summary, technical_density)

        except Exception as e:
            logger.warning(f"[PHASE1.8:Context] Failed to generate summary: {e}")

            # Fallback: construire contexte minimal depuis métadonnées
            fallback = f"Document: {metadata.get('title', 'Unknown')}. "
            if metadata.get('keywords'):
                fallback += f"Topics: {', '.join(metadata['keywords'][:5])}."

            # Fallback hint: 0.5 (neutre)
            _document_context_cache[cache_key] = (fallback, 0.5)
            return (fallback, 0.5)

    def _cross_reference_chunks_and_concepts(
        self,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        concept_to_chunk_ids: Dict[str, List[str]],
        tenant_id: str
    ) -> None:
        """
        Établit le cross-référencement bidirectionnel Neo4j ↔ Qdrant.

        Après création des chunks, cette méthode :
        1. Récupère le mapping Proto → Canonical depuis Neo4j
        2. Met à jour les chunks Qdrant avec canonical_concept_ids
        3. Met à jour les CanonicalConcepts Neo4j avec chunk_ids

        Args:
            chunks: Liste des chunks créés
            chunk_ids: IDs des chunks dans Qdrant
            concept_to_chunk_ids: Mapping proto_id → chunk_ids
            tenant_id: ID tenant
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.common.clients.qdrant_client import get_qdrant_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )
        qdrant_client = get_qdrant_client()

        try:
            # Étape 1: Récupérer mapping Proto → Canonical depuis Neo4j
            proto_to_canonical = {}
            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run("""
                    MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
                    WHERE p.tenant_id = $tenant_id
                    RETURN p.concept_id as proto_id, c.canonical_id as canonical_id
                """, tenant_id=tenant_id)

                for record in result:
                    proto_to_canonical[record["proto_id"]] = record["canonical_id"]

            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] Retrieved {len(proto_to_canonical)} Proto→Canonical mappings"
            )

            # Étape 2: Construire mapping chunk_id → canonical_concept_ids
            chunk_to_canonicals = {}
            canonical_to_chunks = {}  # Pour update Neo4j

            for chunk, chunk_id in zip(chunks, chunk_ids):
                proto_ids = chunk.get("proto_concept_ids", [])
                canonical_ids = []

                for proto_id in proto_ids:
                    canonical_id = proto_to_canonical.get(proto_id)
                    if canonical_id:
                        canonical_ids.append(canonical_id)
                        # Mapper Canonical → Chunks pour Neo4j update
                        if canonical_id not in canonical_to_chunks:
                            canonical_to_chunks[canonical_id] = []
                        canonical_to_chunks[canonical_id].append(chunk_id)

                if canonical_ids:
                    chunk_to_canonicals[chunk_id] = canonical_ids

            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] Mapped {len(chunk_to_canonicals)} chunks to canonical concepts"
            )

            # Étape 3: Update chunks Qdrant avec canonical_concept_ids (batch)
            if chunk_to_canonicals:
                # Utiliser set_payload pour update uniquement le champ (plus efficace)
                for chunk_id, canonical_ids in chunk_to_canonicals.items():
                    qdrant_client.set_payload(
                        collection_name="knowbase",
                        payload={"canonical_concept_ids": canonical_ids},
                        points=[chunk_id]
                    )

                logger.info(
                    f"[OSMOSE AGENTIQUE:CrossRef] ✅ Updated {len(chunk_to_canonicals)} chunks in Qdrant with canonical_concept_ids"
                )

            # Étape 4: Update CanonicalConcepts Neo4j avec chunk_ids (batch)
            if canonical_to_chunks:
                with neo4j_client.driver.session(database="neo4j") as session:
                    for canonical_id, chunk_list in canonical_to_chunks.items():
                        session.run("""
                            MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
                            SET c.chunk_ids = $chunk_ids
                        """, canonical_id=canonical_id, tenant_id=tenant_id, chunk_ids=chunk_list)

                logger.info(
                    f"[OSMOSE AGENTIQUE:CrossRef] ✅ Updated {len(canonical_to_chunks)} CanonicalConcepts in Neo4j with chunk_ids"
                )

            # Log résumé
            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] ✅ Cross-reference complete: "
                f"{len(chunk_to_canonicals)} chunks ↔ {len(canonical_to_chunks)} concepts"
            )

        except Exception as e:
            logger.error(f"[OSMOSE AGENTIQUE:CrossRef] Error during cross-reference: {e}", exc_info=True)
            raise

    def _should_process_with_osmose(
        self,
        document_type: str,
        text_content: str
    ) -> tuple[bool, Optional[str]]:
        """
        Détermine si le document doit être traité avec OSMOSE.

        Args:
            document_type: Type document ("pptx" ou "pdf")
            text_content: Contenu textuel du document

        Returns:
            (should_process, skip_reason)
        """
        # Feature flag global désactivé
        if not self.config.enable_osmose:
            return False, "OSMOSE globally disabled"

        # Feature flag par type de document
        if document_type == "pptx" and not self.config.osmose_for_pptx:
            return False, "OSMOSE disabled for PPTX"

        if document_type == "pdf" and not self.config.osmose_for_pdf:
            return False, "OSMOSE disabled for PDF"

        # Filtre par longueur texte
        text_length = len(text_content)

        if text_length < self.config.min_text_length:
            return False, f"Text too short: {text_length} < {self.config.min_text_length}"

        if text_length > self.config.max_text_length:
            return False, f"Text too long: {text_length} > {self.config.max_text_length}"

        return True, None

    def _calculate_adaptive_timeout(self, num_segments: int) -> int:
        """
        Calcule un timeout adaptatif basé sur la complexité du document.

        Formule Phase 2 OSMOSE (avec extraction relations LLM):
        - Temps de base : 120s (2 min)
        - Temps par segment : 90s (60s extraction NER + 30s relation extraction LLM)
        - Temps FSM overhead : 120s (mining, gatekeeper, promotion, relation writing, indexing)
        - Min : 600s (10 min), Max : settings.osmose_timeout_seconds (défaut 1h, configurable)

        Rationale Phase 2:
        - Extraction relations LLM ajoute ~30-50% overhead par segment
        - Documents larges (500+ concepts) peuvent prendre 60-90 min avec Phase 2
        - Cas réel observé: 553 concepts, 2246 relations → 48 min (timeout à 30 min!)

        Architecture centralisée timeouts (Phase 2 refactor):
        - Utilise settings.osmose_timeout_seconds (property calculée depuis MAX_DOCUMENT_PROCESSING_TIME)
        - Timeout unifié: 1 seule variable à configurer (MAX_DOCUMENT_PROCESSING_TIME)

        Exemples (avec max par défaut 3600s / 1h):
        - 1 segment : 120 + 90*1 + 120 = 330s → clamped à min=600s (10 min)
        - 10 segments : 120 + 90*10 + 120 = 1140s (19 min)
        - 20 segments : 120 + 90*20 + 120 = 2040s (34 min)
        - 30 segments : 120 + 90*30 + 120 = 2940s (49 min) ✅ OK pour doc 230 slides
        - 50 segments : 120 + 90*50 + 120 = 4740s (79 min) → capped à max=3600s (1h)
        - 60 segments : 120 + 90*60 + 120 = 5640s → capped à max=3600s (1h)

        Args:
            num_segments: Nombre de segments détectés

        Returns:
            Timeout en secondes
        """
        from knowbase.config.settings import get_settings

        settings = get_settings()

        base_time = 120  # 2 min base
        time_per_segment = 90  # 90s (1.5 min) par segment (extraction + relations Phase 2)
        fsm_overhead = 120  # 2 min pour mining, gatekeeper, promotion, relation writing, indexing

        calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

        # Bornes: utilise architecture centralisée via settings
        min_timeout = 600  # Minimum absolu: 10 minutes (réduit car max augmenté à 1h)
        max_timeout = settings.osmose_timeout_seconds  # Depuis MAX_DOCUMENT_PROCESSING_TIME

        adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))

        logger.info(
            f"⏱️ Adaptive timeout: {adaptive_timeout}s "
            f"(calculated={calculated_timeout}s, max={max_timeout}s, min={min_timeout}s, segments={num_segments})"
        )

        return adaptive_timeout

    async def process_document_agentique(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None
    ) -> OsmoseIntegrationResult:
        """
        Pipeline OSMOSE Agentique - Architecture Phase 1.5.

        Remplace SemanticPipelineV2 par SupervisorAgent (FSM Master).

        FSM Pipeline:
        INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS
             → GATE_CHECK → PROMOTE → FINALIZE → DONE

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du fichier
            text_content: Contenu textuel extrait
            tenant_id: ID tenant (multi-tenancy)

        Returns:
            Résultat OSMOSE avec métriques agentiques
        """
        start_time = asyncio.get_event_loop().time()
        print(f"[DEBUG OSMOSE] >>> ENTRY process_document_agentique: doc={document_id}")

        # Déterminer type de document
        document_type = document_path.suffix.lower().replace(".", "")
        print(f"[DEBUG OSMOSE] Document type: {document_type}")

        # Résultat OSMOSE
        result = OsmoseIntegrationResult(
            document_id=document_id,
            document_title=document_title,
            document_path=str(document_path),
            document_type=document_type,
        )

        # Vérifier filtres activation
        should_process, skip_reason = self._should_process_with_osmose(
            document_type, text_content
        )

        if not should_process:
            logger.warning(
                f"[OSMOSE AGENTIQUE] Skipping document {document_id}: {skip_reason}"
            )
            result.osmose_success = False
            result.osmose_error = skip_reason
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time
            return result

        # ===== Phase 2: Hybrid Anchor Model =====
        # Si le feature flag est activé, utiliser le nouveau pipeline
        if self.use_hybrid_anchor:
            logger.info(
                f"[OSMOSE:HybridAnchor] 🌊 Using Hybrid Anchor Model pipeline for {document_id}"
            )
            return await self.process_document_hybrid_anchor(
                document_id=document_id,
                document_title=document_title,
                document_path=document_path,
                text_content=text_content,
                tenant_id=tenant_id
            )

        # ===== Legacy: OSMOSE Agentique (Phase 1.5) =====
        logger.info(
            f"[OSMOSE AGENTIQUE] Processing document {document_id} "
            f"({len(text_content)} chars) with SupervisorAgent FSM"
        )

        osmose_start = asyncio.get_event_loop().time()

        try:
            # Étape 1: Créer AgentState initial
            tenant = tenant_id or self.config.default_tenant_id

            initial_state = AgentState(
                document_id=document_id,
                tenant_id=tenant,
                full_text=text_content,  # Stocker texte complet pour filtrage contextuel
                input_text=text_content  # Phase 2.9: Texte pour extraction doc-level
            )

            logger.info(
                f"[OSMOSE AGENTIQUE] AgentState created: "
                f"doc={document_id}, tenant={tenant}, "
                f"budgets={initial_state.budget_remaining}"
            )

            # Phase 1.8: Générer document_context pour désambiguïsation concepts
            # Phase 1.8.2: Récupérer aussi technical_density_hint (domain-agnostic)
            print(f"[DEBUG OSMOSE] Phase 1.8: Generating document context...")
            try:
                document_context, technical_density_hint = await self._generate_document_summary(
                    document_id=document_id,
                    full_text=text_content,
                    max_length=500
                )
                initial_state.document_context = document_context
                initial_state.technical_density_hint = technical_density_hint
                logger.info(
                    f"[PHASE1.8:Context] Document context generated ({len(document_context)} chars, "
                    f"technical_density={technical_density_hint:.2f})"
                )
            except Exception as e:
                logger.warning(f"[PHASE1.8:Context] Failed to generate context: {e}")
                print(f"[DEBUG OSMOSE] Phase 1.8: Context generation FAILED: {e}")
                # Non-bloquant: continuer sans contexte, hint par défaut 0.5
                initial_state.technical_density_hint = 0.5

            print(f"[DEBUG OSMOSE] Phase 1.8: Context done. Starting segmentation...")

            # Étape 2: Segmentation sémantique avec TopicSegmenter
            segmenter = self._get_topic_segmenter()
            print(f"[DEBUG OSMOSE] TopicSegmenter obtained, calling segment_document...")

            try:
                # Appel TopicSegmenter (async)
                topics = await segmenter.segment_document(
                    document_id=document_id,
                    text=text_content,
                    detect_language=True
                )

                # Convertir Topic objects → dicts pour AgentState.segments
                initial_state.segments = []
                for topic in topics:
                    # Concaténer textes des windows pour obtenir le texte complet du segment
                    segment_text = " ".join([w.text for w in topic.windows])

                    # Déterminer langue (si détectée dans anchors ou windows)
                    # Fallback: "en" si non détecté
                    segment_language = "en"  # TODO: Extraire de topic metadata si disponible

                    segment_dict = {
                        "topic_id": topic.topic_id,
                        "segment_id": topic.topic_id,  # Phase 2.9 FIX: Alias pour compatibilité orchestrator
                        "text": segment_text,
                        "language": segment_language,
                        "start_page": 0,  # TODO: Extraire de windows metadata
                        "end_page": 1,    # TODO: Extraire de windows metadata
                        "keywords": topic.anchors,  # NER entities + TF-IDF keywords
                        "cohesion_score": topic.cohesion_score,
                        "section_path": topic.section_path
                    }

                    initial_state.segments.append(segment_dict)

                logger.info(
                    f"[OSMOSE AGENTIQUE] TopicSegmenter: {len(initial_state.segments)} segments "
                    f"(avg cohesion: {sum(t.cohesion_score for t in topics) / max(len(topics), 1):.2f})"
                )

                # Calculer timeout adaptatif basé sur nombre de segments
                adaptive_timeout = self._calculate_adaptive_timeout(len(initial_state.segments))
                initial_state.timeout_seconds = adaptive_timeout
                logger.info(
                    f"[OSMOSE AGENTIQUE] Adaptive timeout: {adaptive_timeout}s "
                    f"({len(initial_state.segments)} segments)"
                )

            except Exception as e:
                logger.error(f"[OSMOSE AGENTIQUE] TopicSegmenter failed: {e}")
                logger.warning("[OSMOSE AGENTIQUE] Falling back to single-segment (full document)")

                # Fallback: Document complet = 1 segment
                initial_state.segments = [{
                    "topic_id": "seg-fallback",
                    "segment_id": "seg-fallback",  # Phase 2.9 FIX: Alias pour compatibilité orchestrator
                    "text": text_content,
                    "language": "en",
                    "start_page": 0,
                    "end_page": 1,
                    "keywords": [],
                    "cohesion_score": 1.0,
                    "section_path": "full_document"
                }]

                # Calculer timeout adaptatif même pour fallback
                adaptive_timeout = self._calculate_adaptive_timeout(1)
                initial_state.timeout_seconds = adaptive_timeout
                logger.info(
                    f"[OSMOSE AGENTIQUE] Adaptive timeout (fallback): {adaptive_timeout}s (1 segment)"
                )

            # Étape 3: Lancer SupervisorAgent FSM
            print(f"[DEBUG OSMOSE] Segmentation done. Getting SupervisorAgent...")
            supervisor = self._get_supervisor()
            print(f"[DEBUG OSMOSE] SupervisorAgent obtained.")

            # DEBUG: Vérifier que les segments sont bien présents
            logger.info(
                f"[OSMOSE AGENTIQUE] 🔍 DEBUG: Passing {len(initial_state.segments)} segments to SupervisorAgent"
            )
            print(f"[DEBUG OSMOSE] Passing {len(initial_state.segments)} segments to SupervisorAgent")
            if initial_state.segments:
                logger.info(
                    f"[OSMOSE AGENTIQUE] 🔍 DEBUG: First segment keys: {list(initial_state.segments[0].keys())}"
                )
                print(f"[DEBUG OSMOSE] First segment keys: {list(initial_state.segments[0].keys())}")

            print(f"[DEBUG OSMOSE] >>> Calling supervisor.execute() with timeout={self.config.timeout_seconds}s...")
            final_state = await asyncio.wait_for(
                supervisor.execute(initial_state),
                timeout=self.config.timeout_seconds
            )
            print(f"[DEBUG OSMOSE] <<< supervisor.execute() COMPLETED")

            logger.info(
                f"[OSMOSE AGENTIQUE] SupervisorAgent FSM completed: "
                f"state={final_state.current_step}, steps={final_state.steps_count}, "
                f"cost=${final_state.cost_incurred:.3f}, "
                f"promoted={len(final_state.promoted)}"
            )

            # Étape 3.5: Phase 1.6 - Créer chunks dans Qdrant avec cross-référence
            # IMPORTANT: Utiliser final_state.promoted (avec proto_concept_id Neo4j) au lieu de candidates
            if final_state.promoted:  # Seulement si concepts promus (avec proto_concept_id)
                try:
                    text_chunker = self._get_text_chunker()

                    # Créer chunks avec embeddings + attribution concepts
                    # NOTE: final_state.promoted contient maintenant proto_concept_id Neo4j
                    chunks = text_chunker.chunk_document(
                        text=text_content,
                        document_id=document_id,
                        document_name=document_title,
                        segment_id=initial_state.segments[0]["topic_id"] if initial_state.segments else "seg-0",
                        concepts=final_state.promoted,  # Concepts promus avec proto_concept_id Neo4j
                        tenant_id=tenant,
                    )

                    if chunks:
                        # Insérer chunks dans Qdrant
                        chunk_ids = upsert_chunks(
                            chunks=chunks,
                            collection_name="knowbase",
                            tenant_id=tenant,
                        )

                        # Construire mapping concept_id → chunk_ids pour Gatekeeper
                        concept_to_chunk_ids = {}
                        for chunk, chunk_id in zip(chunks, chunk_ids):
                            for proto_id in chunk.get("proto_concept_ids", []):
                                if proto_id not in concept_to_chunk_ids:
                                    concept_to_chunk_ids[proto_id] = []
                                concept_to_chunk_ids[proto_id].append(chunk_id)

                        # Stocker dans state pour utilisation par Gatekeeper
                        final_state.concept_to_chunk_ids = concept_to_chunk_ids

                        logger.info(
                            f"[OSMOSE AGENTIQUE:Chunks] Created {len(chunks)} chunks in Qdrant "
                            f"({len(concept_to_chunk_ids)} concepts referenced)"
                        )

                        # ===== Phase 1.6: Cross-référencement bidirectionnel Neo4j ↔ Qdrant =====
                        try:
                            self._cross_reference_chunks_and_concepts(
                                chunks=chunks,
                                chunk_ids=chunk_ids,
                                concept_to_chunk_ids=concept_to_chunk_ids,
                                tenant_id=tenant,
                            )
                        except Exception as e:
                            logger.error(
                                f"[OSMOSE AGENTIQUE:CrossRef] Error cross-referencing chunks and concepts: {e}",
                                exc_info=True
                            )
                            # Non-bloquant : continuer même si cross-ref échoue
                    else:
                        logger.warning(
                            f"[OSMOSE AGENTIQUE:Chunks] No chunks created for document {document_id}"
                        )

                except Exception as e:
                    logger.error(f"[OSMOSE AGENTIQUE:Chunks] Error creating chunks: {e}", exc_info=True)
                    # Non-bloquant : continuer sans chunks

            # Étape 4: Mapper résultats vers OsmoseIntegrationResult
            osmose_duration = asyncio.get_event_loop().time() - osmose_start

            result.osmose_success = final_state.current_step == "done" and len(final_state.errors) == 0
            result.osmose_error = "; ".join(final_state.errors) if final_state.errors else None

            result.concepts_extracted = len(final_state.candidates)
            result.canonical_concepts = len(final_state.promoted)

            # Métriques Phase 1.5 (nouvelles)
            result.osmose_duration_seconds = osmose_duration
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            # Métriques agentiques (extension OsmoseIntegrationResult nécessaire)
            # Pour l'instant, log uniquement
            logger.info(
                f"[OSMOSE AGENTIQUE] Metrics: "
                f"cost=${final_state.cost_incurred:.3f}, "
                f"llm_calls={final_state.llm_calls_count}, "
                f"budget_remaining={final_state.budget_remaining}, "
                f"promotion_rate={len(final_state.promoted)/len(final_state.candidates)*100 if final_state.candidates else 0:.1f}%"
            )

            # ===== Compter métriques réelles Proto-KG (Neo4j + Qdrant) =====
            try:
                from knowbase.common.clients.neo4j_client import get_neo4j_client
                from knowbase.common.clients.qdrant_client import get_qdrant_client
                from knowbase.config.settings import get_settings

                settings = get_settings()
                neo4j_client = get_neo4j_client(
                    uri=settings.neo4j_uri,
                    user=settings.neo4j_user,
                    password=settings.neo4j_password,
                    database="neo4j"
                )
                qdrant_client = get_qdrant_client()

                # Compter ProtoConcept dans Neo4j
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_proto = session.run(
                        "MATCH (n:ProtoConcept) WHERE n.tenant_id = $tenant_id RETURN count(n) as cnt",
                        tenant_id=tenant_id
                    )
                    record_proto = result_proto.single()
                    proto_count = record_proto["cnt"] if record_proto else 0

                # Compter CanonicalConcept dans Neo4j
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_canonical = session.run(
                        "MATCH (n:CanonicalConcept) WHERE n.tenant_id = $tenant_id RETURN count(n) as cnt",
                        tenant_id=tenant_id
                    )
                    record_canonical = result_canonical.single()
                    canonical_count = record_canonical["cnt"] if record_canonical else 0

                # Compter relations dans Neo4j (entre concepts du tenant)
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_rels = session.run(
                        """
                        MATCH (a:CanonicalConcept)-[r]->(b:CanonicalConcept)
                        WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
                        RETURN count(r) as cnt
                        """,
                        tenant_id=tenant_id
                    )
                    record_rels = result_rels.single()
                    relations_count = record_rels["cnt"] if record_rels else 0

                # Compter chunks dans Qdrant
                try:
                    collection_info = qdrant_client.get_collection(settings.qdrant_collection)
                    chunks_count = collection_info.points_count
                except Exception:
                    chunks_count = 0

                # Remplir les champs Proto-KG metrics
                result.proto_kg_concepts_stored = proto_count + canonical_count  # Total concepts
                result.proto_kg_relations_stored = relations_count
                result.proto_kg_embeddings_stored = chunks_count

                logger.info(
                    f"[OSMOSE AGENTIQUE:Proto-KG] Real metrics: "
                    f"{proto_count} ProtoConcept + {canonical_count} CanonicalConcept = {proto_count + canonical_count} total, "
                    f"{relations_count} relations, {chunks_count} chunks in Qdrant"
                )

            except Exception as e:
                logger.warning(f"[OSMOSE AGENTIQUE:Proto-KG] Could not query real metrics: {e}")
                # Laisser les valeurs à 0 par défaut en cas d'erreur

            # Log succès
            if result.osmose_success:
                logger.info(
                    f"[OSMOSE AGENTIQUE] ✅ Document {document_id} processed successfully: "
                    f"{result.canonical_concepts} concepts promoted in {osmose_duration:.1f}s"
                )

                # Phase 2.12: Notify Entity Resolution for reevaluation trigger
                try:
                    reevaluator = get_deferred_reevaluator(tenant_id or "default")
                    should_reevaluate = reevaluator.notify_document_ingested()
                    if should_reevaluate:
                        # Trigger async reevaluation (non-blocking)
                        asyncio.create_task(self._trigger_entity_resolution_reevaluation(tenant_id))
                except Exception as er_error:
                    logger.warning(f"[OSMOSE AGENTIQUE] Entity resolution notification failed: {er_error}")
            else:
                logger.error(
                    f"[OSMOSE AGENTIQUE] ❌ Document {document_id} processing failed: "
                    f"{result.osmose_error}"
                )

            return result

        except asyncio.TimeoutError:
            error_msg = f"OSMOSE Agentique timeout after {self.config.timeout_seconds}s"
            logger.error(f"[OSMOSE AGENTIQUE] {error_msg} for document {document_id}")

            result.osmose_success = False
            result.osmose_error = error_msg
            result.osmose_duration_seconds = self.config.timeout_seconds
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            return result

        except Exception as e:
            error_msg = f"OSMOSE Agentique error: {str(e)}"
            logger.error(
                f"[OSMOSE AGENTIQUE] {error_msg} for document {document_id}",
                exc_info=True
            )

            result.osmose_success = False
            result.osmose_error = error_msg
            result.osmose_duration_seconds = asyncio.get_event_loop().time() - osmose_start
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            return result

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model Pipeline
    # =========================================================================

    async def process_document_hybrid_anchor(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None
    ) -> OsmoseIntegrationResult:
        """
        Pipeline Hybrid Anchor Model - Phase 2.

        Architecture à 2 Passes:
        - Pass 1 (~10 min): EXTRACT → GATE_CHECK → RELATIONS → CHUNK
        - Pass 2 (async): CLASSIFY_FINE → ENRICH_RELATIONS → CROSS_DOC

        ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du fichier
            text_content: Contenu textuel extrait
            tenant_id: ID tenant

        Returns:
            OsmoseIntegrationResult
        """
        start_time = asyncio.get_event_loop().time()
        tenant = tenant_id or self.config.default_tenant_id

        logger.info(
            f"[OSMOSE:HybridAnchor] 🌊 Starting Pass 1 for document {document_id} "
            f"({len(text_content)} chars)"
        )

        # Résultat
        document_type = document_path.suffix.lower().replace(".", "")
        result = OsmoseIntegrationResult(
            document_id=document_id,
            document_title=document_title,
            document_path=str(document_path),
            document_type=document_type,
        )

        # ADR 2024-12-30: Track enrichment state
        enrichment_tracker = get_enrichment_tracker(tenant)
        enrichment_tracker.update_pass1_status(
            document_id=document_id,
            status=EnrichmentStatus.IN_PROGRESS
        )

        try:
            # ===== PASS 1: Socle de Vérité Exploitable =====

            # Étape 1: Segmentation
            segmenter = self._get_topic_segmenter()
            topics = await segmenter.segment_document(
                document_id=document_id,
                text=text_content,
                detect_language=True
            )

            segments = []
            for topic in topics:
                segment_text = " ".join([w.text for w in topic.windows])
                segments.append({
                    "segment_id": topic.topic_id,
                    "text": segment_text,
                    "section_id": topic.section_path,
                    # 2024-12-30: Propager char_offset pour positions globales des anchors
                    "char_offset": topic.char_offset,
                })

            logger.info(
                f"[OSMOSE:HybridAnchor] Segmentation: {len(segments)} segments"
            )

            # Étape 2: Générer contexte document
            document_context = ""
            try:
                document_context, _ = await self._generate_document_summary(
                    document_id=document_id,
                    full_text=text_content,
                    max_length=500
                )
            except Exception as e:
                logger.warning(f"[OSMOSE:HybridAnchor] Document context failed: {e}")

            # Étape 3: EXTRACT_CONCEPTS + ANCHOR_RESOLUTION
            extractor = self._get_hybrid_extractor()
            extraction_result = await extractor.extract_batch(
                segments=segments,
                document_id=document_id,
                document_context=document_context,
                max_concurrent=5
            )

            proto_concepts = extraction_result.proto_concepts
            logger.info(
                f"[OSMOSE:HybridAnchor] Extraction: {len(proto_concepts)} ProtoConcepts "
                f"({len(extraction_result.rejected_concepts)} rejected)"
            )

            # Étape 4: Classification heuristique (Pass 1)
            classifier = self._get_heuristic_classifier()
            for pc in proto_concepts:
                quote = pc.anchors[0].quote if pc.anchors else ""
                classification = classifier.classify(
                    label=pc.label,
                    context=pc.definition or "",
                    quote=quote
                )
                pc.type_heuristic = classification.concept_type.value

            # Étape 5: GATE_CHECK simplifié (scoring + promotion)
            scorer = self._get_anchor_scorer()

            # Construire corpus labels pour TF-IDF
            corpus_labels = [pc.label for pc in proto_concepts]

            # Scorer les proto-concepts
            scored_protos = scorer.score_proto_concepts(
                proto_concepts=proto_concepts,
                corpus_labels=corpus_labels
            )

            # Déterminer promotions
            promotion_decisions = scorer.determine_promotion(scored_protos)

            # Créer CanonicalConcepts pour les concepts promus
            from knowbase.agents.gatekeeper.anchor_based_scorer import (
                create_canonical_from_protos
            )
            from knowbase.api.schemas.concepts import ConceptStability

            canonical_concepts = []
            promoted_protos = []

            for decision in promotion_decisions:
                if decision["promote"]:
                    # Récupérer tous les protos pour ce label
                    proto_ids = decision["all_proto_ids"]
                    protos_for_label = [
                        pc for pc in proto_concepts
                        if pc.id in proto_ids
                    ]

                    if protos_for_label:
                        stability = ConceptStability(decision["stability"])
                        canonical = create_canonical_from_protos(
                            proto_concepts=protos_for_label,
                            stability=stability
                        )
                        canonical_concepts.append(canonical)
                        promoted_protos.extend(protos_for_label)

            logger.info(
                f"[OSMOSE:HybridAnchor] Promotion: {len(canonical_concepts)} CanonicalConcepts "
                f"(stable={len([d for d in promotion_decisions if d.get('stability') == 'stable'])}, "
                f"singleton={len([d for d in promotion_decisions if d.get('stability') == 'singleton'])})"
            )

            # Étape 6: CHUNKING document-centric avec anchors
            chunker = self._get_hybrid_chunker()

            # Collecter tous les anchors des proto-concepts promus
            # + mapping concept_id → label pour enrichir le payload Qdrant
            all_anchors = []
            concept_labels: Dict[str, str] = {}
            for pc in promoted_protos:
                all_anchors.extend(pc.anchors)
                concept_labels[pc.id] = pc.label

            chunks = chunker.chunk_document(
                text=text_content,
                document_id=document_id,
                document_name=document_title,
                anchors=all_anchors,
                concept_labels=concept_labels,  # Mapping pour enrichir le payload
                tenant_id=tenant,
                segments=segments  # V2.1: Segment mapping
            )

            logger.info(
                f"[OSMOSE:HybridAnchor] Chunking: {len(chunks)} chunks "
                f"(0 concept-focused, {sum(len(c.get('anchored_concepts', [])) for c in chunks)} anchors)"
            )

            # Étape 7: Persister dans Qdrant
            if chunks:
                chunk_ids = upsert_chunks(
                    chunks=chunks,
                    collection_name="knowbase",
                    tenant_id=tenant,
                )
                logger.info(
                    f"[OSMOSE:HybridAnchor] Qdrant: {len(chunk_ids)} chunks inserted"
                )

            # Étape 8: Persister dans Neo4j (concepts + chunks + anchored_in)
            await self._persist_hybrid_anchor_to_neo4j(
                proto_concepts=promoted_protos,
                canonical_concepts=canonical_concepts,
                document_id=document_id,
                tenant_id=tenant,
                chunks=chunks  # Passer les chunks pour créer DocumentChunk + ANCHORED_IN
            )

            # ================================================================
            # Étape 8b: Navigation Layer (ADR: ADR_NAVIGATION_LAYER.md)
            # ================================================================
            # Crée les ContextNodes (DocumentContext, SectionContext) et
            # les liens MENTIONED_IN pour la navigation corpus-level.
            # IMPORTANT: Couche NON-SÉMANTIQUE, jamais utilisée par le RAG.
            # ================================================================
            try:
                # Construire mapping section → concepts via anchors
                section_to_concepts: Dict[str, set] = defaultdict(set)
                proto_to_canonical: Dict[str, str] = {}

                # Mapper proto_id → canonical_id
                for cc in canonical_concepts:
                    for proto_id in cc.proto_concept_ids:
                        proto_to_canonical[proto_id] = cc.id

                # Collecter concepts par section
                for proto in promoted_protos:
                    canonical_id = proto_to_canonical.get(proto.id)
                    if not canonical_id:
                        continue

                    # Via proto.section_id
                    if proto.section_id:
                        section_to_concepts[proto.section_id].add(canonical_id)

                    # Via anchors (peut avoir plusieurs sections)
                    for anchor in proto.anchors:
                        if anchor.section_id:
                            section_to_concepts[anchor.section_id].add(canonical_id)

                # Préparer sections au format attendu
                sections_for_nav = [
                    {"path": section_path, "level": 0, "concept_ids": list(concept_ids)}
                    for section_path, concept_ids in section_to_concepts.items()
                ]

                # Tous les canonical_ids pour le document
                all_canonical_ids = [cc.id for cc in canonical_concepts]

                # Construire la Navigation Layer
                nav_builder = get_navigation_layer_builder(tenant_id=tenant)
                nav_stats = nav_builder.build_for_document(
                    document_id=document_id,
                    document_name=document_title,
                    document_type=document_type,
                    sections=sections_for_nav,
                    concept_mentions={f"doc:{document_id}": all_canonical_ids}
                )

                logger.info(
                    f"[OSMOSE:HybridAnchor] Navigation Layer: "
                    f"{len(sections_for_nav)} sections, {len(all_canonical_ids)} concepts, "
                    f"stats={nav_stats}"
                )

            except Exception as nav_error:
                # Navigation Layer non-critique, log warning mais continue
                logger.warning(
                    f"[OSMOSE:HybridAnchor] Navigation Layer failed: {nav_error}"
                )

            # ================================================================
            # RELATIONS: Déplacées vers Pass 2 (ADR 2024-12-30)
            # ================================================================
            # Invariant: Pass 1 ne produit PAS de relations.
            # - RAG utilisable immédiatement après Pass 1
            # - Relations extraites en Pass 2 au niveau SEGMENT (non chunk)
            # - Pass 2 utilise scoring pour sélectionner segments pertinents
            # - Voir: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md (Addendum 2024-12-30)
            # ================================================================

            # ===== PASS 2: Enrichissement (async) =====
            pass2_config = get_hybrid_anchor_config("pass2_config", tenant)
            pass2_mode = pass2_config.get("mode", "background") if pass2_config else "background"

            if pass2_mode != "disabled" and canonical_concepts:
                orchestrator = self._get_pass2_orchestrator()

                # Convertir CanonicalConcepts en dicts pour Pass 2
                concepts_for_pass2 = [
                    {
                        "id": cc.id,
                        "label": cc.label,
                        "definition": cc.definition_consolidated,
                        "type_heuristic": cc.type_fine or "abstract",
                        "section_id": None,  # TODO: récupérer depuis protos
                    }
                    for cc in canonical_concepts
                ]

                # Planifier Pass 2
                from knowbase.ingestion.pass2_orchestrator import Pass2Mode
                mode_enum = Pass2Mode(pass2_mode)

                await orchestrator.schedule_pass2(
                    document_id=document_id,
                    concepts=concepts_for_pass2,
                    mode=mode_enum
                )

                logger.info(
                    f"[OSMOSE:HybridAnchor] Pass 2 scheduled ({pass2_mode}): "
                    f"{len(concepts_for_pass2)} concepts"
                )

            # ===== Finaliser résultat =====
            pass1_duration = asyncio.get_event_loop().time() - start_time

            result.osmose_success = True
            result.concepts_extracted = len(proto_concepts)
            result.canonical_concepts = len(canonical_concepts)
            result.osmose_duration_seconds = pass1_duration
            result.total_duration_seconds = pass1_duration

            # ADR 2024-12-30: Update enrichment tracking - Pass 1 complete
            enrichment_tracker.update_pass1_status(
                document_id=document_id,
                status=EnrichmentStatus.COMPLETE,
                concepts_extracted=len(proto_concepts),
                concepts_promoted=len(canonical_concepts),
                chunks_created=len(chunks)
            )
            # Mark Pass 2 as pending (ready for enrichment)
            enrichment_tracker.update_pass2_status(
                document_id=document_id,
                status=EnrichmentStatus.PENDING
            )

            logger.info(
                f"[OSMOSE:HybridAnchor] ✅ Pass 1 complete for {document_id}: "
                f"{len(canonical_concepts)} concepts, {len(chunks)} chunks in {pass1_duration:.1f}s"
            )

            return result

        except Exception as e:
            error_msg = f"Hybrid Anchor Model error: {str(e)}"
            logger.error(
                f"[OSMOSE:HybridAnchor] ❌ {error_msg} for document {document_id}",
                exc_info=True
            )

            result.osmose_success = False
            result.osmose_error = error_msg
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            # ADR 2024-12-30: Update enrichment tracking - Pass 1 failed
            enrichment_tracker.update_pass1_status(
                document_id=document_id,
                status=EnrichmentStatus.FAILED,
                error=error_msg
            )

            return result

    async def _persist_hybrid_anchor_to_neo4j(
        self,
        proto_concepts: List[Any],
        canonical_concepts: List[Any],
        document_id: str,
        tenant_id: str,
        chunks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, int]:
        """
        Persiste les concepts Hybrid Anchor dans Neo4j.

        Crée selon l'ADR:
        - ProtoConcept nodes avec leurs attributs
        - CanonicalConcept nodes avec stability et needs_confirmation
        - Relations INSTANCE_OF entre Proto et Canonical
        - DocumentChunk nodes (si chunks fournis)
        - Relations ANCHORED_IN entre concepts et chunks

        Args:
            proto_concepts: Liste des ProtoConcepts (promus uniquement)
            canonical_concepts: Liste des CanonicalConcepts
            document_id: ID du document
            tenant_id: ID tenant
            chunks: Liste des chunks avec anchored_concepts (optionnel)

        Returns:
            Dict avec compteurs créés
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        stats = {
            "proto_created": 0,
            "canonical_created": 0,
            "relations_created": 0,
            "chunks_created": 0,
            "anchored_in_created": 0
        }

        try:
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                logger.warning("[OSMOSE:HybridAnchor:Neo4j] Not connected, skipping persistence")
                return stats

            # ================================================================
            # Étape 1: Créer les ProtoConcepts
            # ================================================================
            # Build mapping proto_id -> canonical_id pour les relations
            proto_to_canonical: Dict[str, str] = {}
            for cc in canonical_concepts:
                for proto_id in cc.proto_concept_ids:
                    proto_to_canonical[proto_id] = cc.id

            # Batch create ProtoConcepts
            proto_query = """
            UNWIND $protos AS proto
            MERGE (p:ProtoConcept {concept_id: proto.id, tenant_id: $tenant_id})
            ON CREATE SET
                p.concept_name = proto.label,
                p.definition = proto.definition,
                p.type_heuristic = proto.type_heuristic,
                p.document_id = proto.document_id,
                p.section_id = proto.section_id,
                p.created_at = datetime(),
                p.extraction_method = 'hybrid_anchor'
            ON MATCH SET
                p.definition = COALESCE(proto.definition, p.definition),
                p.updated_at = datetime()
            RETURN count(p) AS created
            """

            proto_data = [
                {
                    "id": pc.id,
                    "label": pc.label,
                    "definition": pc.definition,
                    "type_heuristic": pc.type_heuristic,
                    "document_id": pc.document_id,
                    "section_id": getattr(pc, 'section_id', None)
                }
                for pc in proto_concepts
            ]

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    proto_query,
                    protos=proto_data,
                    tenant_id=tenant_id
                )
                record = result.single()
                if record:
                    stats["proto_created"] = record["created"]

            # ================================================================
            # Étape 2: Créer les CanonicalConcepts avec stability
            # ================================================================
            canonical_query = """
            UNWIND $canonicals AS cc
            MERGE (c:CanonicalConcept {canonical_id: cc.id, tenant_id: $tenant_id})
            ON CREATE SET
                c.canonical_name = cc.label,
                c.canonical_key = toLower(replace(cc.label, ' ', '_')),
                c.unified_definition = cc.definition_consolidated,
                c.type_fine = cc.type_fine,
                c.stability = cc.stability,
                c.needs_confirmation = cc.needs_confirmation,
                c.status = 'HYBRID_ANCHOR',
                c.created_at = datetime()
            ON MATCH SET
                c.unified_definition = COALESCE(cc.definition_consolidated, c.unified_definition),
                c.type_fine = COALESCE(cc.type_fine, c.type_fine),
                c.stability = cc.stability,
                c.needs_confirmation = cc.needs_confirmation,
                c.updated_at = datetime()
            RETURN count(c) AS created
            """

            canonical_data = [
                {
                    "id": cc.id,
                    "label": cc.label,
                    "definition_consolidated": cc.definition_consolidated,
                    "type_fine": cc.type_fine,
                    "stability": cc.stability.value if hasattr(cc.stability, 'value') else str(cc.stability),
                    "needs_confirmation": cc.needs_confirmation
                }
                for cc in canonical_concepts
            ]

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    canonical_query,
                    canonicals=canonical_data,
                    tenant_id=tenant_id
                )
                record = result.single()
                if record:
                    stats["canonical_created"] = record["created"]

            # ================================================================
            # Étape 3: Créer les relations INSTANCE_OF (Proto → Canonical)
            # ================================================================
            relation_query = """
            UNWIND $relations AS rel
            MATCH (p:ProtoConcept {concept_id: rel.proto_id, tenant_id: $tenant_id})
            MATCH (c:CanonicalConcept {canonical_id: rel.canonical_id, tenant_id: $tenant_id})
            MERGE (p)-[r:INSTANCE_OF]->(c)
            ON CREATE SET r.created_at = datetime()
            RETURN count(r) AS created
            """

            relation_data = [
                {"proto_id": proto_id, "canonical_id": canonical_id}
                for proto_id, canonical_id in proto_to_canonical.items()
            ]

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    relation_query,
                    relations=relation_data,
                    tenant_id=tenant_id
                )
                record = result.single()
                if record:
                    stats["relations_created"] = record["created"]

            # ================================================================
            # Étape 4: Créer les DocumentChunk nodes
            # ================================================================
            if chunks:
                chunk_query = """
                UNWIND $chunks AS chunk
                MERGE (dc:DocumentChunk {chunk_id: chunk.id, tenant_id: $tenant_id})
                ON CREATE SET
                    dc.document_id = chunk.document_id,
                    dc.document_name = chunk.document_name,
                    dc.chunk_index = chunk.chunk_index,
                    dc.chunk_type = chunk.chunk_type,
                    dc.char_start = chunk.char_start,
                    dc.char_end = chunk.char_end,
                    dc.token_count = chunk.token_count,
                    dc.text_preview = left(chunk.text, 200),
                    dc.created_at = datetime()
                ON MATCH SET
                    dc.updated_at = datetime()
                RETURN count(dc) AS created
                """

                chunk_data = [
                    {
                        "id": c.get("id"),
                        "document_id": c.get("document_id"),
                        "document_name": c.get("document_name"),
                        "chunk_index": c.get("chunk_index", 0),
                        "chunk_type": c.get("chunk_type", "document_centric"),
                        "char_start": c.get("char_start", 0),
                        "char_end": c.get("char_end", 0),
                        "token_count": c.get("token_count", 0),
                        "text": c.get("text", "")[:200]
                    }
                    for c in chunks
                ]

                with neo4j_client.driver.session(database="neo4j") as session:
                    result = session.run(
                        chunk_query,
                        chunks=chunk_data,
                        tenant_id=tenant_id
                    )
                    record = result.single()
                    if record:
                        stats["chunks_created"] = record["created"]

                # ================================================================
                # Étape 5: Créer les relations ANCHORED_IN (Concept → Chunk)
                # ================================================================
                # Collecter toutes les relations concept → chunk depuis anchored_concepts
                anchored_relations = []
                for chunk in chunks:
                    chunk_id = chunk.get("id")
                    for ac in chunk.get("anchored_concepts", []):
                        concept_id = ac.get("concept_id")
                        if concept_id and chunk_id:
                            anchored_relations.append({
                                "concept_id": concept_id,
                                "chunk_id": chunk_id,
                                "role": ac.get("role", "mention"),
                                "span_start": ac.get("span", [0, 0])[0] if ac.get("span") else 0,
                                "span_end": ac.get("span", [0, 0])[1] if ac.get("span") else 0
                            })

                if anchored_relations:
                    anchored_query = """
                    UNWIND $relations AS rel
                    MATCH (p:ProtoConcept {concept_id: rel.concept_id, tenant_id: $tenant_id})
                    MATCH (dc:DocumentChunk {chunk_id: rel.chunk_id, tenant_id: $tenant_id})
                    MERGE (p)-[r:ANCHORED_IN]->(dc)
                    ON CREATE SET
                        r.role = rel.role,
                        r.span_start = rel.span_start,
                        r.span_end = rel.span_end,
                        r.created_at = datetime()
                    RETURN count(r) AS created
                    """

                    with neo4j_client.driver.session(database="neo4j") as session:
                        result = session.run(
                            anchored_query,
                            relations=anchored_relations,
                            tenant_id=tenant_id
                        )
                        record = result.single()
                        if record:
                            stats["anchored_in_created"] = record["created"]

            logger.info(
                f"[OSMOSE:HybridAnchor:Neo4j] ✅ Persisted: "
                f"{stats['proto_created']} ProtoConcepts, "
                f"{stats['canonical_created']} CanonicalConcepts, "
                f"{stats['relations_created']} INSTANCE_OF, "
                f"{stats['chunks_created']} DocumentChunks, "
                f"{stats['anchored_in_created']} ANCHORED_IN"
            )

            return stats

        except Exception as e:
            logger.error(
                f"[OSMOSE:HybridAnchor:Neo4j] ❌ Persistence error: {e}",
                exc_info=True
            )
            return stats

    async def _extract_intra_document_relations(
        self,
        canonical_concepts: List[Any],
        text_content: str,
        document_id: str,
        tenant_id: str,
        document_chunks: Optional[List[Dict[str, Any]]] = None
    ) -> int:
        """
        Extrait et persiste les relations intra-document (Pass 1.5).

        Option A' (ADR 2024-12-30): Si document_chunks fournis, utilise
        extract_relations_chunk_aware() qui itère sur les DocumentChunks
        avec fenêtre [i-1, i, i+1] et catalogue filtré par anchored_concepts.

        Args:
            canonical_concepts: Liste des CanonicalConcepts (promus en Pass 1)
            text_content: Texte complet du document (fallback si pas de chunks)
            document_id: ID du document source
            tenant_id: ID tenant
            document_chunks: Liste des DocumentChunks avec anchored_concepts (Option A')

        Returns:
            Nombre de RawAssertions créées
        """
        from knowbase.relations.llm_relation_extractor import LLMRelationExtractor
        from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer

        logger.info(
            f"[OSMOSE:HybridAnchor:Relations] Extracting intra-document relations "
            f"for {len(canonical_concepts)} concepts"
            f"{f', {len(document_chunks)} chunks (Option A)' if document_chunks else ' (legacy mode)'}"
        )

        # Convertir CanonicalConcepts en format attendu par LLMRelationExtractor
        # 2024-12-30: Inclure proto_concept_ids pour mapping anchored_concepts → canonical
        concepts_for_extraction = []
        for cc in canonical_concepts:
            concept_dict = {
                "canonical_id": cc.id,
                "canonical_name": cc.label,
                "concept_type": cc.type_fine or "abstract",
                "surface_forms": list(cc.surface_forms) if hasattr(cc, 'surface_forms') and cc.surface_forms else [],
                # Proto IDs pour mapping anchors (qui utilisent proto_id) vers canonical
                "proto_concept_ids": list(cc.proto_concept_ids) if hasattr(cc, 'proto_concept_ids') and cc.proto_concept_ids else []
            }
            concepts_for_extraction.append(concept_dict)

        # Initialiser l'extracteur LLM
        extractor = LLMRelationExtractor(
            model="gpt-4o-mini",
            max_context_chars=8000,
            use_id_first=True  # Utiliser ID-First (V3/V4)
        )

        try:
            # Option A' : Extraction alignée sur DocumentChunks (recommandée)
            # 2024-12-30: Version ASYNC parallélisée pour performance
            if document_chunks and len(document_chunks) > 0:
                logger.info(
                    f"[OSMOSE:HybridAnchor:Relations] Using PARALLEL chunk-aware extraction "
                    f"(Option A', async with max_concurrent=10)"
                )
                extraction_result = await extractor.extract_relations_chunk_aware_async(
                    document_chunks=document_chunks,
                    all_concepts=concepts_for_extraction,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    window_size=1,  # Fenêtre [i-1, i, i+1]
                    max_concepts=100,
                    min_type_confidence=0.65,
                    doc_top_k=15,
                    lex_fallback_threshold=8,
                    max_concurrent=10  # 10 appels LLM en parallèle
                )
            else:
                # Fallback: Extraction legacy sur full_text (déprécié)
                logger.warning(
                    f"[OSMOSE:HybridAnchor:Relations] No chunks provided, "
                    f"falling back to legacy extraction (DEPRECATED)"
                )
                extraction_result = extractor.extract_relations_type_first(
                    concepts=concepts_for_extraction,
                    full_text=text_content,
                    document_id=document_id,
                    chunk_id=f"{document_id}_full",
                    min_type_confidence=0.65
                )

            if not extraction_result.relations:
                logger.info(
                    f"[OSMOSE:HybridAnchor:Relations] No relations extracted "
                    f"({extraction_result.stats.get('relations_extracted', 0)} attempted)"
                )
                return 0

            logger.info(
                f"[OSMOSE:HybridAnchor:Relations] Extracted {len(extraction_result.relations)} relations "
                f"(valid={extraction_result.stats.get('relations_valid', 0)}, "
                f"invalid_type={extraction_result.stats.get('relations_invalid_type', 0)}, "
                f"invalid_index={extraction_result.stats.get('relations_invalid_index', 0)})"
            )

            # Initialiser le writer
            writer = get_raw_assertion_writer(
                tenant_id=tenant_id,
                extractor_version="2.10.0",
                model_used="gpt-4o-mini"
            )
            writer.reset_stats()

            # Écrire chaque relation comme RawAssertion
            for rel in extraction_result.relations:
                writer.write_assertion(
                    subject_concept_id=rel.subject_concept_id,
                    object_concept_id=rel.object_concept_id,
                    predicate_raw=rel.predicate_raw,
                    evidence_text=rel.evidence,
                    source_doc_id=document_id,
                    source_chunk_id=f"{document_id}_full",
                    confidence=rel.confidence,
                    source_language="MULTI",
                    subject_surface_form=rel.subject_surface_form,
                    object_surface_form=rel.object_surface_form,
                    flags=rel.flags,
                    evidence_span_start=rel.evidence_start_char,
                    evidence_span_end=rel.evidence_end_char,
                    # Phase 2.10 Type-First fields
                    relation_type=rel.relation_type,
                    type_confidence=rel.type_confidence,
                    alt_type=rel.alt_type,
                    alt_type_confidence=rel.alt_type_confidence,
                    relation_subtype_raw=rel.relation_subtype_raw,
                    context_hint=rel.context_hint
                )

            stats = writer.get_stats()
            logger.info(
                f"[OSMOSE:HybridAnchor:Relations] ✅ Persisted {stats['written']} RawAssertions "
                f"(skipped: {stats['skipped_duplicate']} duplicates, "
                f"{stats['skipped_no_concept']} missing concepts)"
            )

            return stats['written']

        except Exception as e:
            logger.error(
                f"[OSMOSE:HybridAnchor:Relations] ❌ Error extracting relations: {e}",
                exc_info=True
            )
            return 0

    async def _trigger_entity_resolution_reevaluation(
        self,
        tenant_id: Optional[str] = None
    ) -> None:
        """
        Trigger async entity resolution reevaluation.

        Phase 2.12: Called when document count threshold is reached.
        Non-blocking - runs in background.

        Args:
            tenant_id: Tenant ID
        """
        try:
            from knowbase.entity_resolution.deferred_reevaluator import run_reevaluation_job
            result = await run_reevaluation_job(
                tenant_id=tenant_id or "default",
                dry_run=False
            )
            logger.info(
                f"[OSMOSE AGENTIQUE:EntityResolution] Reevaluation complete: "
                f"{result.promoted_to_auto} promoted to AUTO, "
                f"{result.still_deferred} still deferred"
            )
        except Exception as e:
            logger.warning(f"[OSMOSE AGENTIQUE:EntityResolution] Reevaluation failed: {e}")


# Helper function pour compatibility
async def process_document_with_osmose_agentique(
    document_id: str,
    document_title: str,
    document_path: Path,
    text_content: str,
    tenant_id: Optional[str] = None,
    config: Optional[OsmoseIntegrationConfig] = None
) -> OsmoseIntegrationResult:
    """
    Helper function pour traitement document avec OSMOSE Agentique.

    Compatible avec signature legacy `process_document_with_osmose()`.

    Args:
        document_id: ID unique du document
        document_title: Titre du document
        document_path: Chemin du fichier
        text_content: Contenu textuel extrait
        tenant_id: ID tenant (multi-tenancy)
        config: Configuration OSMOSE

    Returns:
        Résultat OSMOSE Agentique
    """
    # DEBUG Phase 2.9: Trace entrée fonction
    print(f"[DEBUG OSMOSE] >>> ENTRY process_document_with_osmose_agentique: doc={document_id}, text_len={len(text_content)}")
    logger.info(f"[DEBUG OSMOSE] >>> ENTRY process_document_with_osmose_agentique: doc={document_id}")

    service = OsmoseAgentiqueService(config=config)
    print(f"[DEBUG OSMOSE] OsmoseAgentiqueService created, calling process_document_agentique...")

    return await service.process_document_agentique(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=text_content,
        tenant_id=tenant_id
    )
