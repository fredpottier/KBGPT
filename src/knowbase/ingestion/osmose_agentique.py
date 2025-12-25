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

from collections import Counter
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
from knowbase.common.llm_router import LLMRouter, TaskType  # Phase 1.8: Document Context
from knowbase.ontology.domain_context_injector import get_domain_context_injector  # Domain Context injection

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

        logger.info(
            f"[OSMOSE AGENTIQUE] Service initialized - OSMOSE enabled: {self.config.enable_osmose}"
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
        """Lazy init du LLMRouter (Phase 1.8)."""
        if self.llm_router is None:
            self.llm_router = LLMRouter()
            logger.info("[OSMOSE AGENTIQUE] LLMRouter initialized (Phase 1.8)")

        return self.llm_router

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

        # Traitement OSMOSE Agentique
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
                        tenant_id=tenant
                    )

                    if chunks:
                        # Insérer chunks dans Qdrant
                        chunk_ids = upsert_chunks(
                            chunks=chunks,
                            collection_name="knowbase",
                            tenant_id=tenant
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
                                tenant_id=tenant
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
