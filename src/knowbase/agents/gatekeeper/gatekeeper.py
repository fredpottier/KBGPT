"""
🤖 OSMOSE Agentique - Gatekeeper Delegate

Quality control et promotion Proto→Published.

Phase 1.5 Jours 7-9: Filtrage Contextuel Hybride
- GraphCentralityScorer: TF-IDF + Salience + Fenêtre adaptive
- EmbeddingsContextualScorer: Paraphrases multilingues + Agrégation
- Cascade: Graph → Embeddings → Ajustement confidence
"""

from typing import Dict, Any, Optional, List
import logging
import re
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput
from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.common.clients.redis_client import get_redis_client  # P0.2 Rate limiting
from knowbase.common.clients.qdrant_client import update_chunks_with_canonical_ids  # Phase 1.6
from .graph_centrality_scorer import GraphCentralityScorer
from .embeddings_contextual_scorer import EmbeddingsContextualScorer
from knowbase.ontology.decision_trace import (
    DecisionTrace,
    create_decision_trace,
    NormalizationStrategy,
    StrategyResult
)
from knowbase.ontology.entity_normalizer_neo4j import EntityNormalizerNeo4j
from knowbase.ontology.llm_canonicalizer import LLMCanonicalizer  # Phase 1.6+
from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager  # Phase 1.6+
from knowbase.common.llm_router import get_llm_router  # Phase 1.6+

logger = logging.getLogger(__name__)


class GateProfile:
    """
    Profil de qualité pour Gate Check.

    Chaque profil définit:
    - min_confidence: Seuil confidence minimale
    - required_fields: Champs obligatoires (definition, type)
    - max_length: Longueur max du nom (anti-fragments)
    - min_length: Longueur min du nom
    """

    def __init__(
        self,
        name: str,
        min_confidence: float = 0.7,
        required_fields: Optional[List[str]] = None,
        max_length: int = 100,
        min_length: int = 3
    ):
        self.name = name
        self.min_confidence = min_confidence
        self.required_fields = required_fields or ["name", "type"]
        self.max_length = max_length
        self.min_length = min_length


# Profils prédéfinis
GATE_PROFILES = {
    "STRICT": GateProfile(
        name="STRICT",
        min_confidence=0.85,
        required_fields=["name", "type", "definition"],
        max_length=100,
        min_length=3
    ),
    "BALANCED": GateProfile(
        name="BALANCED",
        min_confidence=0.70,
        required_fields=["name", "type"],
        max_length=100,
        min_length=3
    ),
    "PERMISSIVE": GateProfile(
        name="PERMISSIVE",
        min_confidence=0.60,
        required_fields=["name"],
        max_length=100,
        min_length=2
    )
}


class GateCheckInput(ToolInput):
    """Input pour GateCheck tool."""
    candidates: List[Dict[str, Any]]
    profile_name: str = "BALANCED"
    full_text: Optional[str] = None  # Texte complet pour filtrage contextuel


class GateCheckOutput(ToolOutput):
    """Output pour GateCheck tool."""
    promoted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    retry_recommended: bool = False
    rejection_reasons: Dict[str, List[str]] = {}

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.promoted:
            self.promoted = self.data.get("promoted", [])
        if self.data and not self.rejected:
            self.rejected = self.data.get("rejected", [])
        if self.data and not self.retry_recommended:
            self.retry_recommended = self.data.get("retry_recommended", False)
        if self.data and not self.rejection_reasons:
            self.rejection_reasons = self.data.get("rejection_reasons", {})
        return self


class PromoteConceptsInput(ToolInput):
    """Input pour PromoteConcepts tool."""
    concepts: List[Dict[str, Any]]
    concept_to_chunk_ids: Dict[str, List[str]] = {}  # Phase 1.6: Mapping proto_id → chunk_ids


class PromoteConceptsOutput(ToolOutput):
    """Output pour PromoteConcepts tool."""
    promoted_count: int = 0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.promoted_count:
            self.promoted_count = self.data.get("promoted_count", 0)
        return self


class GatekeeperDelegate(BaseAgent):
    """
    Gatekeeper Delegate Agent.

    Responsabilités:
    - Score chaque candidate selon Gate Profile (STRICT/BALANCED/PERMISSIVE)
    - Promeut concepts ≥ seuil vers Neo4j Published
    - Rejette fragments, stopwords, PII
    - Recommande retry avec BIG model si qualité insuffisante

    Gate Profiles:
    - STRICT: min_confidence=0.85, requires definition
    - BALANCED: min_confidence=0.70, requires name+type
    - PERMISSIVE: min_confidence=0.60, requires name only

    Critères rejet dur:
    - Nom < 3 chars
    - Nom > 100 chars
    - Stopwords (the, and, or, of, etc.)
    - Fragments (ized, ial, ing, tion)
    - PII patterns (email, phone, SSN)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise le Gatekeeper Delegate."""
        super().__init__(AgentRole.GATEKEEPER, config)

        # Profil par défaut
        self.default_profile = config.get("default_profile", "BALANCED") if config else "BALANCED"

        # Hard rejection patterns
        self.stopwords = {"the", "and", "or", "of", "in", "on", "at", "to", "a", "an", "for", "with"}
        self.fragments = {"ized", "ial", "ing", "tion", "ness", "ment", "able", "ful", "less"}

        # PII patterns
        self.pii_patterns = {
            "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
            "phone": re.compile(r"\+?\d[\d\s\-\(\)]{7,}\d"),
            "ssn": re.compile(r"\d{3}-\d{2}-\d{4}")
        }

        # Filtrage Contextuel Hybride (Phase 1.5 Jours 7-9)
        # Activable/désactivable via config
        enable_contextual_filtering = config.get("enable_contextual_filtering", True) if config else True

        if enable_contextual_filtering:
            try:
                self.graph_scorer = GraphCentralityScorer(
                    min_centrality=0.15,
                    enable_tf_idf=True,
                    enable_salience=True
                )
                logger.info("[GATEKEEPER] GraphCentralityScorer initialisé")
            except Exception as e:
                logger.warning(f"[GATEKEEPER] GraphCentralityScorer init failed: {e}, disabled")
                self.graph_scorer = None

            try:
                self.embeddings_scorer = EmbeddingsContextualScorer(
                    model_name="intfloat/multilingual-e5-large",
                    context_window=100,
                    similarity_threshold_primary=0.5,
                    similarity_threshold_competitor=0.4,
                    enable_multi_occurrence=True
                )
                logger.info("[GATEKEEPER] EmbeddingsContextualScorer initialisé")
            except Exception as e:
                logger.warning(f"[GATEKEEPER] EmbeddingsContextualScorer init failed: {e}, disabled")
                self.embeddings_scorer = None
        else:
            self.graph_scorer = None
            self.embeddings_scorer = None
            logger.info("[GATEKEEPER] Filtrage contextuel désactivé (config)")

        # Neo4j client pour Published-KG
        if config:
            neo4j_uri = config.get("neo4j_uri", "bolt://neo4j:7687")  # Docker service name
            neo4j_user = config.get("neo4j_user", "neo4j")
            neo4j_password = config.get("neo4j_password", "graphiti_neo4j_pass")  # From docker-compose
            neo4j_database = config.get("neo4j_database", "neo4j")
        else:
            neo4j_uri = "bolt://neo4j:7687"  # Docker service name
            neo4j_user = "neo4j"
            neo4j_password = "graphiti_neo4j_pass"  # From docker-compose
            neo4j_database = "neo4j"

        try:
            self.neo4j_client = get_neo4j_client(
                uri=neo4j_uri,
                user=neo4j_user,
                password=neo4j_password,
                database=neo4j_database
            )
            if self.neo4j_client.is_connected():
                logger.info("[GATEKEEPER] Neo4j client connected for Published-KG storage")
            else:
                logger.warning("[GATEKEEPER] Neo4j client initialized but not connected (promotion disabled)")
        except Exception as e:
            logger.error(f"[GATEKEEPER] Neo4j client initialization failed: {e}")
            self.neo4j_client = None

        # P0.1 + P1.2: Initialiser EntityNormalizerNeo4j pour canonicalisation avancée
        try:
            if self.neo4j_client and self.neo4j_client.driver:
                self.entity_normalizer = EntityNormalizerNeo4j(self.neo4j_client.driver)
                logger.info(
                    "[GATEKEEPER] EntityNormalizerNeo4j initialized "
                    "(P0.1 Sandbox + P1.2 Structural Similarity enabled)"
                )
            else:
                logger.warning(
                    "[GATEKEEPER] EntityNormalizerNeo4j disabled (Neo4j client unavailable), "
                    "falling back to naive canonicalization"
                )
                self.entity_normalizer = None
        except Exception as e:
            logger.error(f"[GATEKEEPER] EntityNormalizerNeo4j initialization failed: {e}")
            self.entity_normalizer = None

        # Phase 1.6+: LLM Canonicalizer + Adaptive Ontology (Zero-Config Intelligence)
        try:
            self.llm_router = get_llm_router()
            self.llm_canonicalizer = LLMCanonicalizer(self.llm_router)

            # P0.2: Get Redis client pour rate limiting
            try:
                self.redis_client = get_redis_client()
                logger.debug("[GATEKEEPER] Redis client initialized for rate limiting")
            except Exception as redis_err:
                logger.warning(f"[GATEKEEPER] Redis client init failed, rate limiting disabled: {redis_err}")
                self.redis_client = None

            # Init AdaptiveOntology avec Redis (optionnel)
            self.adaptive_ontology = AdaptiveOntologyManager(
                neo4j_client=self.neo4j_client,
                redis_client=self.redis_client
            )

            logger.info(
                "[GATEKEEPER] LLM Canonicalizer + Adaptive Ontology initialized "
                f"(Phase 1.6+ Zero-Config Intelligence, rate_limiting={'ON' if self.redis_client else 'OFF'})"
            )
        except Exception as e:
            logger.error(f"[GATEKEEPER] LLM Canonicalizer initialization failed: {e}")
            self.llm_canonicalizer = None
            self.adaptive_ontology = None
            self.redis_client = None

        logger.info(
            f"[GATEKEEPER] Initialized with default profile '{self.default_profile}' "
            f"(contextual_filtering={'ON' if (self.graph_scorer or self.embeddings_scorer) else 'OFF'})"
        )

    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        self.tools = {
            "gate_check": self._gate_check_tool,
            "promote_concepts": self._promote_concepts_tool
        }

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Exécute gate check sur candidates.

        Args:
            state: État actuel (doit contenir state.candidates)
            instruction: Profil optionnel (STRICT/BALANCED/PERMISSIVE)

        Returns:
            État mis à jour avec state.promoted rempli
        """
        logger.info(f"[GATEKEEPER] Starting gate check for {len(state.candidates)} candidates")

        if not state.candidates:
            logger.warning("[GATEKEEPER] No candidates to process, skipping")
            return state

        # Profil sélectionné
        profile_name = instruction or self.default_profile

        # Étape 1: Gate check
        gate_input = GateCheckInput(
            candidates=state.candidates,
            profile_name=profile_name,
            full_text=state.full_text  # Transmettre texte pour filtrage contextuel
        )

        gate_result = await self.call_tool("gate_check", gate_input)

        if not gate_result.success:
            logger.error(f"[GATEKEEPER] GateCheck failed: {gate_result.message}")
            return state

        # gate_result est déjà un GateCheckOutput (hérite de ToolOutput)
        gate_output = gate_result

        logger.info(
            f"[GATEKEEPER] Gate check complete: {len(gate_output.promoted)} promoted, "
            f"{len(gate_output.rejected)} rejected, retry_recommended={gate_output.retry_recommended}"
        )

        # Mettre à jour état
        state.promoted = gate_output.promoted

        # Étape 1.5: Créer ProtoConcepts dans Neo4j (Phase 1.6 fix)
        # IMPORTANT: Créer ProtoConcepts AVANT chunking pour avoir les vrais IDs Neo4j
        if gate_output.promoted and self.neo4j_client and self.neo4j_client.is_connected():
            for concept in gate_output.promoted:
                # Si proto_concept_id déjà existant, skip
                if concept.get("proto_concept_id"):
                    continue

                # Créer ProtoConcept maintenant
                proto_concept_id = self.neo4j_client.create_proto_concept(
                    tenant_id=state.tenant_id,
                    concept_name=concept.get("name", ""),
                    concept_type=concept.get("type", "Unknown"),
                    segment_id=concept.get("segment_id", "unknown"),
                    document_id=state.document_id,
                    extraction_method=concept.get("extraction_method", "NER"),
                    confidence=concept.get("confidence", 0.0),
                    metadata={
                        "definition": concept.get("definition", ""),
                        "original_name": concept.get("name", ""),
                        "gate_profile": self.default_profile
                    }
                )

                # Ajouter proto_concept_id au concept pour utilisation ultérieure
                concept["proto_concept_id"] = proto_concept_id

                logger.debug(
                    f"[GATEKEEPER:PreProto] Created ProtoConcept '{concept.get('name')}' "
                    f"(id={proto_concept_id[:8] if proto_concept_id else 'FAILED'})"
                )

        # Étape 2: Promouvoir concepts vers Neo4j (si promoted)
        if gate_output.promoted:
            promote_input = PromoteConceptsInput(
                concepts=gate_output.promoted,
                concept_to_chunk_ids=state.concept_to_chunk_ids  # Phase 1.6
            )
            promote_result = await self.call_tool("promote_concepts", promote_input)

            if not promote_result.success:
                logger.error(f"[GATEKEEPER] PromoteConcepts failed: {promote_result.message}")
            else:
                # Problème 1: Persister relations sémantiques dans Neo4j
                if state.relations:
                    concept_mapping = promote_result.data.get("concept_name_to_canonical_id", {})
                    persisted_count = 0
                    skipped_count = 0

                    logger.info(
                        f"[GATEKEEPER:Relations] Starting persistence of {len(state.relations)} relations "
                        f"with {len(concept_mapping)} canonical concepts"
                    )

                    for relation in state.relations:
                        source_name = relation.get("source")
                        target_name = relation.get("target")

                        # Map concept names to canonical_ids
                        source_id = concept_mapping.get(source_name)
                        target_id = concept_mapping.get(target_name)

                        if source_id and target_id:
                            # Persister la relation dans Neo4j
                            try:
                                success = self.neo4j_client.create_concept_link(
                                    tenant_id=state.tenant_id,
                                    source_concept_id=source_id,
                                    target_concept_id=target_id,
                                    relationship_type=relation.get("type", "RELATED_TO"),
                                    weight=relation.get("confidence", 0.7),  # weight au lieu de confidence
                                    metadata={
                                        "segment_id": relation.get("segment_id"),
                                        "created_by": "pattern_miner",
                                        "confidence": relation.get("confidence", 0.7)  # Stocker aussi dans metadata
                                    }
                                )
                                if success:
                                    persisted_count += 1
                                    logger.debug(
                                        f"[GATEKEEPER:Relations] Persisted {relation.get('type')} "
                                        f"relation: {source_name} → {target_name}"
                                    )
                                else:
                                    skipped_count += 1
                                    logger.warning(
                                        f"[GATEKEEPER:Relations] Failed to persist relation: "
                                        f"{source_name} → {target_name}"
                                    )
                            except Exception as e:
                                skipped_count += 1
                                logger.error(
                                    f"[GATEKEEPER:Relations] Error persisting relation "
                                    f"{source_name} → {target_name}: {e}"
                                )
                        else:
                            skipped_count += 1
                            logger.debug(
                                f"[GATEKEEPER:Relations] Skipped relation (concepts not promoted): "
                                f"{source_name} → {target_name} "
                                f"(source_id={source_id}, target_id={target_id})"
                            )

                    logger.info(
                        f"[GATEKEEPER:Relations] Persistence complete: {persisted_count} relations persisted, "
                        f"{skipped_count} skipped"
                    )

        # Log final
        logger.info(
            f"[GATEKEEPER] Gate check complete: {len(state.promoted)} promoted, "
            f"profile='{profile_name}'"
        )

        return state

    def _gate_check_tool(self, tool_input: GateCheckInput) -> ToolOutput:
        """
        Tool GateCheck: Score et filtre candidates selon profil.

        Algorithme:
        1. Hard rejection: Fragments, stopwords, PII
        2. **Filtrage Contextuel Hybride (Phase 1.5 Jours 7-9)**:
           - GraphCentralityScorer: TF-IDF + Salience + Fenêtre adaptive
           - EmbeddingsContextualScorer: Paraphrases multilingues + Agrégation
           - Ajustement confidence selon role (PRIMARY +0.12, COMPETITOR -0.15)
        3. Profile check: Confidence ajustée + required fields
        4. Promote si ≥ seuils

        Args:
            tool_input: Candidates + profile_name + full_text (optionnel)

        Returns:
            Promoted, rejected, retry_recommended
        """
        try:
            candidates = tool_input.candidates
            profile_name = tool_input.profile_name
            full_text = tool_input.full_text

            # Charger profil
            profile = GATE_PROFILES.get(profile_name)
            if not profile:
                logger.warning(f"[GATEKEEPER:GateCheck] Unknown profile '{profile_name}', using BALANCED")
                profile = GATE_PROFILES["BALANCED"]

            # **Phase 1.5 Jours 7-9: Filtrage Contextuel Hybride**
            # Cascade: Graph → Embeddings → Ajustement confidence
            if full_text and (self.graph_scorer or self.embeddings_scorer):
                logger.info(
                    f"[GATEKEEPER:GateCheck] Applying contextual filtering "
                    f"(graph={'ON' if self.graph_scorer else 'OFF'}, "
                    f"embeddings={'ON' if self.embeddings_scorer else 'OFF'})"
                )

                # Étape 1: GraphCentralityScorer
                if self.graph_scorer:
                    candidates = self.graph_scorer.score_entities(candidates, full_text)
                    logger.debug(
                        f"[GATEKEEPER:GateCheck] GraphCentralityScorer applied "
                        f"({len(candidates)} candidates)"
                    )

                # Étape 2: EmbeddingsContextualScorer
                if self.embeddings_scorer:
                    candidates = self.embeddings_scorer.score_entities(candidates, full_text)
                    logger.debug(
                        f"[GATEKEEPER:GateCheck] EmbeddingsContextualScorer applied "
                        f"({len(candidates)} candidates)"
                    )

                # Étape 3: Ajustement confidence selon role
                for candidate in candidates:
                    role = candidate.get("embedding_role", "SECONDARY")
                    original_confidence = candidate.get("confidence", 0.0)

                    # Ajustements selon role
                    if role == "PRIMARY":
                        # Boost PRIMARY (+0.12)
                        candidate["confidence"] = min(original_confidence + 0.12, 1.0)
                        logger.debug(
                            f"[GATEKEEPER:GateCheck] PRIMARY boost: "
                            f"{candidate.get('name', '')} {original_confidence:.2f} → "
                            f"{candidate['confidence']:.2f}"
                        )
                    elif role == "COMPETITOR":
                        # Penalize COMPETITOR (-0.15)
                        candidate["confidence"] = max(original_confidence - 0.15, 0.0)
                        logger.debug(
                            f"[GATEKEEPER:GateCheck] COMPETITOR penalty: "
                            f"{candidate.get('name', '')} {original_confidence:.2f} → "
                            f"{candidate['confidence']:.2f}"
                        )
                    # SECONDARY: pas d'ajustement

                logger.info(
                    f"[GATEKEEPER:GateCheck] Contextual filtering complete "
                    f"({len([c for c in candidates if c.get('embedding_role') == 'PRIMARY'])} PRIMARY, "
                    f"{len([c for c in candidates if c.get('embedding_role') == 'COMPETITOR'])} COMPETITOR)"
                )

            promoted = []
            rejected = []
            rejection_reasons: Dict[str, List[str]] = {}

            for candidate in candidates:
                name = candidate.get("name", "")
                confidence = candidate.get("confidence", 0.0)

                # Hard rejections
                rejection_reason = self._check_hard_rejection(name)

                if rejection_reason:
                    rejected.append(candidate)
                    rejection_reasons[name] = [rejection_reason]
                    continue

                # Profile checks (utilise confidence ajustée)
                if confidence < profile.min_confidence:
                    rejected.append(candidate)
                    rejection_reasons[name] = [f"Confidence {confidence:.2f} < {profile.min_confidence}"]
                    continue

                # Required fields
                missing_fields = []
                for field in profile.required_fields:
                    if not candidate.get(field):
                        missing_fields.append(field)

                if missing_fields:
                    rejected.append(candidate)
                    rejection_reasons[name] = [f"Missing fields: {', '.join(missing_fields)}"]
                    continue

                # Promoted!
                promoted.append(candidate)

            # Retry recommendation: Si < 30% promoted
            promotion_rate = len(promoted) / len(candidates) if candidates else 0.0
            retry_recommended = promotion_rate < 0.3

            logger.debug(
                f"[GATEKEEPER:GateCheck] {len(promoted)} promoted, {len(rejected)} rejected, "
                f"promotion_rate={promotion_rate:.1%}, retry_recommended={retry_recommended}"
            )

            return GateCheckOutput(
                success=True,
                message=f"Gate check complete: {len(promoted)} promoted",
                promoted=promoted,
                rejected=rejected,
                retry_recommended=retry_recommended,
                rejection_reasons=rejection_reasons,
                data={
                    "promoted": promoted,
                    "rejected": rejected,
                    "retry_recommended": retry_recommended,
                    "rejection_reasons": rejection_reasons
                }
            )

        except Exception as e:
            logger.error(f"[GATEKEEPER:GateCheck] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"GateCheck failed: {str(e)}"
            )

    def _check_hard_rejection(self, name: str) -> Optional[str]:
        """
        Vérifie critères de rejet dur.

        Args:
            name: Nom du concept

        Returns:
            Raison du rejet, ou None si accepté
        """
        # Length checks
        if len(name) < 3:
            return f"Too short (<3 chars)"

        if len(name) > 100:
            return f"Too long (>100 chars)"

        # Stopwords
        if name.lower() in self.stopwords:
            return f"Stopword"

        # Fragments
        if name.lower() in self.fragments:
            return f"Fragment"

        # PII patterns
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(name):
                return f"Contains PII ({pii_type})"

        return None

    def _batch_canonicalize_pending_concepts(
        self,
        concepts: List[Dict[str, Any]],
        tenant_id: str,
        batch_size: int = 20
    ) -> Dict[str, tuple]:
        """
        Batch canonicalisation LLM pour TOUS les concepts d'un coup.

        Fix 2025-10-20: Réduire latence réseau de 95% via batch processing.
        - Avant: 556 concepts × (0.5s latency + 0.1s LLM) = 334s total
        - Après: 28 batches × (0.5s latency + 0.5s LLM batch) = 28s total
        - Gain: 306s économisés (~5 min)

        Args:
            concepts: Liste complète des concepts à promouvoir
            tenant_id: ID tenant
            batch_size: Taille des batches (default: 20)

        Returns:
            Dict[concept_name] -> (canonical_name, confidence)

        Example:
            >>> cache = self._batch_canonicalize_pending_concepts(concepts, "default")
            >>> cache["S/4HANA Cloud's"]
            ("SAP S/4HANA Cloud, Public Edition", 0.92)
        """
        if not self.llm_canonicalizer or not self.adaptive_ontology:
            logger.warning(
                "[GATEKEEPER:Batch] LLM Canonicalizer unavailable, skipping batch canonicalization"
            )
            return {}

        # 1. Collecter concepts nécessitant canonicalisation LLM
        pending_concepts = []

        for concept in concepts:
            concept_name = concept.get("name", "")
            if not concept_name:
                continue

            # Check si déjà dans cache ontologie
            cached = self.adaptive_ontology.lookup(concept_name, tenant_id)

            if not cached:
                # Pas de cache → doit être canonicalisé
                pending_concepts.append({
                    "raw_name": concept_name,
                    "context": concept.get("definition", ""),
                    "domain_hint": None
                })

        if not pending_concepts:
            logger.info("[GATEKEEPER:Batch] ✅ All concepts already cached, no LLM calls needed")
            return {}

        logger.info(
            f"[GATEKEEPER:Batch] 🔄 Batch canonicalizing {len(pending_concepts)} concepts "
            f"(batch_size={batch_size})..."
        )

        # 2. Canonicaliser par batches
        results_cache = {}
        total_batches = (len(pending_concepts) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(pending_concepts))
            batch = pending_concepts[start_idx:end_idx]

            logger.debug(
                f"[GATEKEEPER:Batch] Processing batch {batch_idx + 1}/{total_batches} "
                f"({len(batch)} concepts)..."
            )

            try:
                # Appel batch LLM
                batch_results = self.llm_canonicalizer.canonicalize_batch(batch)

                # Stocker résultats dans cache
                for concept_dict, result in zip(batch, batch_results):
                    raw_name = concept_dict["raw_name"]
                    results_cache[raw_name] = (result.canonical_name, result.confidence)

                    # Stocker également dans adaptive ontology pour cache persistant
                    self.adaptive_ontology.store(
                        tenant_id=tenant_id,
                        canonical_name=result.canonical_name,
                        raw_name=raw_name,
                        canonicalization_result=result.model_dump(),
                        context=concept_dict.get("context"),
                        document_id=None  # Pas de document_id pour batch
                    )

                logger.info(
                    f"[GATEKEEPER:Batch] ✅ Batch {batch_idx + 1}/{total_batches} completed "
                    f"({len(batch_results)} concepts)"
                )

            except Exception as e:
                logger.error(
                    f"[GATEKEEPER:Batch] ❌ Batch {batch_idx + 1}/{total_batches} failed: {e}, "
                    f"concepts will use fallback"
                )
                # Continuer avec le batch suivant

        logger.info(
            f"[GATEKEEPER:Batch] ✅ Batch canonicalization complete: {len(results_cache)} concepts cached"
        )

        return results_cache

    def _canonicalize_concept_name(
        self,
        raw_name: str,
        context: Optional[str] = None,
        tenant_id: str = "default",
        document_id: Optional[str] = None
    ) -> tuple[str, float]:
        """
        Canonicalise nom concept via Adaptive Ontology (Phase 1.6+).

        Workflow:
        1. Lookup cache ontologie
        2. Si non trouvé → Check budget LLM (P0.2)
        3. Si budget OK → LLM canonicalization
        4. Store résultat dans ontologie

        Args:
            raw_name: Nom brut du concept
            context: Contexte textuel (optionnel)
            tenant_id: ID tenant
            document_id: ID du document (pour rate limiting P0.2)

        Returns:
            (canonical_name, confidence)
        """
        # Vérifier disponibilité des services
        if not self.llm_canonicalizer or not self.adaptive_ontology:
            logger.debug(
                f"[GATEKEEPER:Canonicalization] LLM Canonicalizer unavailable, "
                f"skipping adaptive canonicalization for '{raw_name}'"
            )
            return raw_name.strip().title(), 0.5

        # 1. Lookup cache ontologie
        cached = self.adaptive_ontology.lookup(raw_name, tenant_id)

        if cached:
            # Cache HIT
            logger.debug(
                f"[GATEKEEPER:Canonicalization] ✅ Cache HIT '{raw_name}' → '{cached['canonical_name']}' "
                f"(confidence={cached['confidence']:.2f}, source={cached.get('source', 'unknown')})"
            )

            # Incrémenter usage stats
            self.adaptive_ontology.increment_usage(cached["canonical_name"], tenant_id)

            return cached["canonical_name"], cached["confidence"]

        # 2. Cache MISS → Check budget LLM (P0.2)
        if document_id:
            budget_ok = self.adaptive_ontology.check_llm_budget(
                document_id=document_id,
                max_llm_calls_per_doc=50
            )

            if not budget_ok:
                logger.warning(
                    f"[GATEKEEPER:Canonicalization] ❌ Budget EXCEEDED for doc '{document_id}', "
                    f"fallback to title case for '{raw_name}'"
                )
                return raw_name.strip().title(), 0.5

        logger.info(
            f"[GATEKEEPER:Canonicalization] 🔍 Cache MISS '{raw_name}', calling LLM canonicalizer..."
        )

        try:
            # 3. LLM canonicalization
            llm_result = self.llm_canonicalizer.canonicalize(
                raw_name=raw_name,
                context=context,
                domain_hint=None  # Auto-détection par LLM
            )

            logger.info(
                f"[GATEKEEPER:Canonicalization] ✅ LLM canonicalized '{raw_name}' → '{llm_result.canonical_name}' "
                f"(confidence={llm_result.confidence:.2f}, type={llm_result.concept_type})"
            )

            # 4. Store dans ontologie adaptive
            self.adaptive_ontology.store(
                tenant_id=tenant_id,
                canonical_name=llm_result.canonical_name,
                raw_name=raw_name,
                canonicalization_result=llm_result.model_dump(),
                context=context,
                document_id=document_id
            )

            return llm_result.canonical_name, llm_result.confidence

        except Exception as e:
            logger.error(
                f"[GATEKEEPER:Canonicalization] ❌ LLM canonicalization failed for '{raw_name}': {e}, "
                f"falling back to title case"
            )
            return raw_name.strip().title(), 0.5

    def _promote_concepts_tool(self, tool_input: PromoteConceptsInput) -> ToolOutput:
        """
        Tool PromoteConcepts: Promeut concepts vers Neo4j Published.

        Args:
            tool_input: Concepts à promouvoir (avec tenant_id dans state)

        Returns:
            Count promoted
        """
        try:
            concepts = tool_input.concepts

            # Si Neo4j non disponible, skip promotion (mode dégradé)
            if not self.neo4j_client or not self.neo4j_client.is_connected():
                logger.warning("[GATEKEEPER:PromoteConcepts] Neo4j unavailable, skipping promotion (degraded mode)")
                return PromoteConceptsOutput(
                    success=True,
                    message=f"Skipped promotion (Neo4j unavailable): {len(concepts)} concepts",
                    promoted_count=0,
                    data={
                        "promoted_count": 0,
                        "skipped_count": len(concepts)
                    }
                )

            # Fix 2025-10-20: Batch LLM canonicalization AVANT la boucle
            # Collecter tous les concepts pour batch processing
            # Fix 2025-10-20 21:30: tool_input n'a pas de .state, extraire tenant_id du premier concept
            tenant_id_for_batch = concepts[0].get("tenant_id", "default") if concepts else "default"
            batch_canonicalization_cache = self._batch_canonicalize_pending_concepts(
                concepts=concepts,
                tenant_id=tenant_id_for_batch
            )

            # Promouvoir chaque concept
            promoted_count = 0
            failed_count = 0
            canonical_ids = []
            concept_name_to_canonical_id = {}  # Problème 1: Map pour relations

            for concept in concepts:
                # Extraire champs du concept
                concept_name = concept.get("name", "")
                concept_type = concept.get("type", "Unknown")
                definition = concept.get("definition", "")
                confidence = concept.get("confidence", 0.0)

                # IMPORTANT: Ne PAS confondre concept_id (Extractor) avec proto_concept_id (Neo4j)
                # Seul proto_concept_id indique qu'un ProtoConcept existe déjà dans Neo4j
                proto_concept_id = concept.get("proto_concept_id", "")  # Neo4j ID uniquement
                tenant_id = concept.get("tenant_id", "default")

                # P0.1 + P1.2: Normalisation via EntityNormalizerNeo4j (ontologie + fuzzy structurel)
                entity_id = None
                normalized_type = concept_type
                is_cataloged = False

                if self.entity_normalizer:
                    try:
                        import time
                        start_time = time.time()

                        entity_id, canonical_name, normalized_type, is_cataloged = self.entity_normalizer.normalize_entity_name(
                            raw_name=concept_name,
                            entity_type_hint=concept_type,
                            tenant_id=tenant_id,
                            include_pending=False  # P0.1 Sandbox: Exclure entités pending
                        )

                        normalization_time_ms = (time.time() - start_time) * 1000

                        if is_cataloged:
                            logger.info(
                                f"[GATEKEEPER:Canonicalization] ✅ Normalized via ontology: '{concept_name}' → '{canonical_name}' "
                                f"(entity_id={entity_id}, type={normalized_type}, time={normalization_time_ms:.2f}ms)"
                            )
                        else:
                            # Fix 2025-10-20: Utiliser batch cache au lieu d'appel individuel
                            if concept_name in batch_canonicalization_cache:
                                canonical_name, llm_confidence = batch_canonicalization_cache[concept_name]
                                logger.debug(
                                    f"[GATEKEEPER:Canonicalization:Batch] ✅ Batch cache hit '{concept_name}' → '{canonical_name}' "
                                    f"(confidence={llm_confidence:.2f})"
                                )
                            else:
                                # Fallback individuel (ne devrait pas arriver, mais sécurité)
                                canonical_name, llm_confidence = self._canonicalize_concept_name(
                                    raw_name=concept_name,
                                    context=definition,
                                    tenant_id=tenant_id,
                                    document_id=concept.get("document_id")
                                )
                                logger.warning(
                                    f"[GATEKEEPER:Canonicalization:Batch] ⚠️ Cache MISS for '{concept_name}', "
                                    f"fallback to individual LLM call"
                                )
                    except Exception as e:
                        logger.warning(
                            f"[GATEKEEPER:Canonicalization] EntityNormalizerNeo4j failed for '{concept_name}': {e}, "
                            f"falling back to LLM canonicalization"
                        )
                        # Fix 2025-10-20: Utiliser batch cache
                        if concept_name in batch_canonicalization_cache:
                            canonical_name, llm_confidence = batch_canonicalization_cache[concept_name]
                        else:
                            canonical_name, llm_confidence = self._canonicalize_concept_name(
                                raw_name=concept_name,
                                context=definition,
                                tenant_id=tenant_id,
                                document_id=concept.get("document_id")
                            )
                        normalization_time_ms = 0.0
                else:
                    # Fix 2025-10-20: Utiliser batch cache
                    if concept_name in batch_canonicalization_cache:
                        canonical_name, llm_confidence = batch_canonicalization_cache[concept_name]
                        logger.debug(
                            f"[GATEKEEPER:Canonicalization:Batch] ✅ Batch cache hit '{concept_name}' → '{canonical_name}' "
                            f"(confidence={llm_confidence:.2f}, EntityNormalizerNeo4j unavailable)"
                        )
                    else:
                        canonical_name, llm_confidence = self._canonicalize_concept_name(
                            raw_name=concept_name,
                            context=definition,
                            tenant_id=tenant_id,
                            document_id=concept.get("document_id")
                        )
                        logger.warning(
                            f"[GATEKEEPER:Canonicalization:Batch] ⚠️ Cache MISS for '{concept_name}', "
                            f"fallback to individual LLM call"
                        )
                    normalization_time_ms = 0.0

                # Générer unified_definition (si manquant, utiliser nom + type)
                unified_definition = definition if definition else f"{concept_type}: {concept_name}"

                # Quality score = confidence (ou calculé via autre logique)
                quality_score = confidence

                try:
                    # Étape 1: Vérifier que ProtoConcept existe (doit être créé dans execute() maintenant)
                    if not proto_concept_id:
                        failed_count += 1
                        logger.error(
                            f"[GATEKEEPER:PromoteConcepts] Missing proto_concept_id for '{concept_name}' "
                            f"(should have been created in execute() step)"
                        )
                        continue

                    # P0.3: Créer DecisionTrace pour audit
                    decision_trace = create_decision_trace(
                        raw_name=concept_name,
                        entity_type_hint=concept_type,
                        tenant_id=tenant_id,
                        document_id=concept.get("document_id"),
                        segment_id=concept.get("segment_id")
                    )

                    # P0.3: Enregistrer stratégie réellement utilisée
                    if is_cataloged:
                        # Stratégie ONTOLOGY_LOOKUP réussie
                        decision_trace.add_strategy_result(StrategyResult(
                            strategy=NormalizationStrategy.ONTOLOGY_LOOKUP,
                            attempted=True,
                            success=True,
                            canonical_name=canonical_name,
                            confidence=1.0,  # Exact match ontologie
                            execution_time_ms=normalization_time_ms,
                            metadata={
                                "entity_id": entity_id,
                                "normalized_type": normalized_type,
                                "match_method": "ontology_exact_or_structural",
                                "is_cataloged": True
                            }
                        ))
                    else:
                        # Fallback HEURISTIC_RULES
                        decision_trace.add_strategy_result(StrategyResult(
                            strategy=NormalizationStrategy.HEURISTIC_RULES,
                            attempted=True,
                            success=True,
                            canonical_name=canonical_name,
                            confidence=confidence,
                            execution_time_ms=normalization_time_ms,
                            metadata={
                                "gate_profile": self.default_profile,
                                "quality_score": quality_score,
                                "method": "naive_title_case",
                                "fallback_reason": "not_in_ontology"
                            }
                        ))

                    # Finaliser trace
                    decision_trace.finalize(
                        canonical_name=canonical_name,
                        strategy=NormalizationStrategy.ONTOLOGY_LOOKUP if is_cataloged else NormalizationStrategy.HEURISTIC_RULES,
                        confidence=1.0 if is_cataloged else confidence,
                        is_cataloged=is_cataloged
                    )

                    decision_trace_json = decision_trace.to_json_string()

                    logger.debug(
                        f"[GATEKEEPER:DecisionTrace] Created trace for '{concept_name}' → '{canonical_name}' "
                        f"(confidence={confidence:.2f}, requires_validation={decision_trace.requires_validation})"
                    )

                    # Phase 1.6: Récupérer chunk_ids pour ce concept (si disponibles)
                    chunk_ids = tool_input.concept_to_chunk_ids.get(proto_concept_id, [])

                    # Étape 2: Promouvoir Proto → Canonical (P1.3: surface_form, P1.6: chunk_ids)
                    canonical_id = self.neo4j_client.promote_to_published(
                        tenant_id=tenant_id,
                        proto_concept_id=proto_concept_id,
                        canonical_name=canonical_name,
                        unified_definition=unified_definition,
                        quality_score=quality_score,
                        metadata={
                            "original_name": concept_name,
                            "extracted_type": concept_type,
                            "gate_profile": self.default_profile
                        },
                        decision_trace_json=decision_trace_json,
                        surface_form=concept_name,  # P1.3: Préserver nom brut extrait
                        chunk_ids=chunk_ids  # P1.6: Cross-référence Neo4j → Qdrant
                    )

                    if canonical_id:
                        promoted_count += 1
                        canonical_ids.append(canonical_id)

                        # Problème 1: Stocker mapping concept_name → canonical_id
                        concept_name_to_canonical_id[concept_name] = canonical_id

                        # Phase 1.6: Mettre à jour chunks Qdrant avec canonical_id
                        if chunk_ids:
                            try:
                                update_chunks_with_canonical_ids(
                                    chunk_ids=chunk_ids,
                                    canonical_concept_id=canonical_id,
                                    collection_name="knowbase"
                                )
                                logger.debug(
                                    f"[GATEKEEPER:Chunks] Updated {len(chunk_ids)} chunks with "
                                    f"canonical_id={canonical_id[:8]}"
                                )
                            except Exception as e:
                                logger.error(
                                    f"[GATEKEEPER:Chunks] Failed to update chunks for {canonical_id[:8]}: {e}"
                                )
                                # Non-bloquant : continuer

                        logger.debug(
                            f"[GATEKEEPER:PromoteConcepts] Promoted '{canonical_name}' "
                            f"(tenant={tenant_id}, quality={quality_score:.2f}, chunks={len(chunk_ids)})"
                        )
                    else:
                        failed_count += 1
                        logger.warning(
                            f"[GATEKEEPER:PromoteConcepts] Failed to promote '{concept_name}' "
                            f"(Neo4j returned empty canonical_id)"
                        )

                except Exception as e:
                    failed_count += 1
                    logger.error(f"[GATEKEEPER:PromoteConcepts] Error promoting '{concept_name}': {e}")

            logger.info(
                f"[GATEKEEPER:PromoteConcepts] Promotion complete: "
                f"{promoted_count} promoted, {failed_count} failed"
            )

            # Problème 1: Retourner mapping pour persistance relations
            return PromoteConceptsOutput(
                success=True,
                message=f"Promoted {promoted_count}/{len(concepts)} concepts to Published-KG",
                promoted_count=promoted_count,
                data={
                    "promoted_count": promoted_count,
                    "failed_count": failed_count,
                    "canonical_ids": canonical_ids,
                    "concept_name_to_canonical_id": concept_name_to_canonical_id  # Problème 1
                }
            )

        except Exception as e:
            logger.error(f"[GATEKEEPER:PromoteConcepts] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"PromoteConcepts failed: {str(e)}"
            )
