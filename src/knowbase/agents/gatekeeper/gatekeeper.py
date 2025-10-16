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
from .graph_centrality_scorer import GraphCentralityScorer
from .embeddings_contextual_scorer import EmbeddingsContextualScorer
from knowbase.ontology.decision_trace import (
    DecisionTrace,
    create_decision_trace,
    NormalizationStrategy,
    StrategyResult
)

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

        # Étape 2: Promouvoir concepts vers Neo4j (si promoted)
        if gate_output.promoted:
            promote_input = PromoteConceptsInput(concepts=gate_output.promoted)
            promote_result = await self.call_tool("promote_concepts", promote_input)

            if not promote_result.success:
                logger.error(f"[GATEKEEPER] PromoteConcepts failed: {promote_result.message}")

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

            # Promouvoir chaque concept
            promoted_count = 0
            failed_count = 0
            canonical_ids = []

            for concept in concepts:
                # Extraire champs du concept
                concept_name = concept.get("name", "")
                concept_type = concept.get("type", "Unknown")
                definition = concept.get("definition", "")
                confidence = concept.get("confidence", 0.0)
                proto_concept_id = concept.get("proto_concept_id", "")  # Si concept Proto existe
                tenant_id = concept.get("tenant_id", "default")

                # Générer canonical_name (normalisé)
                canonical_name = concept_name.strip().title()

                # Générer unified_definition (si manquant, utiliser nom + type)
                unified_definition = definition if definition else f"{concept_type}: {concept_name}"

                # Quality score = confidence (ou calculé via autre logique)
                quality_score = confidence

                try:
                    # Étape 1: Créer ProtoConcept dans Neo4j (si pas déjà existant)
                    if not proto_concept_id:
                        # Créer ProtoConcept
                        proto_concept_id = self.neo4j_client.create_proto_concept(
                            tenant_id=tenant_id,
                            concept_name=concept_name,
                            concept_type=concept_type,
                            segment_id=concept.get("segment_id", "unknown"),
                            document_id=concept.get("document_id", "unknown"),
                            extraction_method=concept.get("extraction_method", "NER"),
                            confidence=confidence,
                            metadata={
                                "definition": definition,
                                "original_name": concept_name,
                                "gate_profile": self.default_profile
                            }
                        )

                        if not proto_concept_id:
                            failed_count += 1
                            logger.warning(
                                f"[GATEKEEPER:PromoteConcepts] Failed to create ProtoConcept for '{concept_name}'"
                            )
                            continue

                        logger.debug(
                            f"[GATEKEEPER:PromoteConcepts] Created ProtoConcept '{concept_name}' "
                            f"(id={proto_concept_id[:8]})"
                        )

                    # P0.3: Créer DecisionTrace pour audit
                    decision_trace = create_decision_trace(
                        raw_name=concept_name,
                        entity_type_hint=concept_type,
                        tenant_id=tenant_id,
                        document_id=concept.get("document_id"),
                        segment_id=concept.get("segment_id")
                    )

                    # Ajouter stratégie HEURISTIC_RULES (gate check)
                    decision_trace.add_strategy_result(StrategyResult(
                        strategy=NormalizationStrategy.HEURISTIC_RULES,
                        attempted=True,
                        success=True,
                        canonical_name=canonical_name,
                        confidence=confidence,
                        execution_time_ms=0.0,
                        metadata={
                            "gate_profile": self.default_profile,
                            "quality_score": quality_score,
                            "method": "gatekeeper_promotion"
                        }
                    ))

                    # Finaliser trace
                    decision_trace.finalize(
                        canonical_name=canonical_name,
                        strategy=NormalizationStrategy.HEURISTIC_RULES,
                        confidence=confidence,
                        is_cataloged=False  # Pas encore catalogué dans ontologie
                    )

                    decision_trace_json = decision_trace.to_json_string()

                    logger.debug(
                        f"[GATEKEEPER:DecisionTrace] Created trace for '{concept_name}' → '{canonical_name}' "
                        f"(confidence={confidence:.2f}, requires_validation={decision_trace.requires_validation})"
                    )

                    # Étape 2: Promouvoir Proto → Canonical (P1.3: ajout surface_form)
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
                        surface_form=concept_name  # P1.3: Préserver nom brut extrait
                    )

                    if canonical_id:
                        promoted_count += 1
                        canonical_ids.append(canonical_id)
                        logger.debug(
                            f"[GATEKEEPER:PromoteConcepts] Promoted '{canonical_name}' "
                            f"(tenant={tenant_id}, quality={quality_score:.2f})"
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

            return PromoteConceptsOutput(
                success=True,
                message=f"Promoted {promoted_count}/{len(concepts)} concepts to Published-KG",
                promoted_count=promoted_count,
                data={
                    "promoted_count": promoted_count,
                    "failed_count": failed_count,
                    "canonical_ids": canonical_ids
                }
            )

        except Exception as e:
            logger.error(f"[GATEKEEPER:PromoteConcepts] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"PromoteConcepts failed: {str(e)}"
            )
