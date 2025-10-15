"""
🤖 OSMOSE Agentique - Gatekeeper Delegate

Quality control et promotion Proto→Published.
"""

from typing import Dict, Any, Optional, List
import logging
import re

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput
from knowbase.common.clients.neo4j_client import get_neo4j_client

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


class GateCheckOutput(ToolOutput):
    """Output pour GateCheck tool."""
    promoted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    retry_recommended: bool = False
    rejection_reasons: Dict[str, List[str]] = {}


class PromoteConceptsInput(ToolInput):
    """Input pour PromoteConcepts tool."""
    concepts: List[Dict[str, Any]]


class PromoteConceptsOutput(ToolOutput):
    """Output pour PromoteConcepts tool."""
    promoted_count: int = 0


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

        # Neo4j client pour Published-KG
        if config:
            neo4j_uri = config.get("neo4j_uri", "bolt://localhost:7687")
            neo4j_user = config.get("neo4j_user", "neo4j")
            neo4j_password = config.get("neo4j_password", "password")
            neo4j_database = config.get("neo4j_database", "neo4j")
        else:
            neo4j_uri = "bolt://localhost:7687"
            neo4j_user = "neo4j"
            neo4j_password = "password"
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

        logger.info(f"[GATEKEEPER] Initialized with default profile '{self.default_profile}'")

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
            profile_name=profile_name
        )

        gate_result = self.call_tool("gate_check", gate_input)

        if not gate_result.success:
            logger.error(f"[GATEKEEPER] GateCheck failed: {gate_result.message}")
            return state

        gate_output = GateCheckOutput(**gate_result.data)

        logger.info(
            f"[GATEKEEPER] Gate check complete: {len(gate_output.promoted)} promoted, "
            f"{len(gate_output.rejected)} rejected, retry_recommended={gate_output.retry_recommended}"
        )

        # Mettre à jour état
        state.promoted = gate_output.promoted

        # Étape 2: Promouvoir concepts vers Neo4j (si promoted)
        if gate_output.promoted:
            promote_input = PromoteConceptsInput(concepts=gate_output.promoted)
            promote_result = self.call_tool("promote_concepts", promote_input)

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
        2. Profile check: Confidence + required fields
        3. Promote si ≥ seuils

        Args:
            tool_input: Candidates + profile_name

        Returns:
            Promoted, rejected, retry_recommended
        """
        try:
            candidates = tool_input.candidates
            profile_name = tool_input.profile_name

            # Charger profil
            profile = GATE_PROFILES.get(profile_name)
            if not profile:
                logger.warning(f"[GATEKEEPER:GateCheck] Unknown profile '{profile_name}', using BALANCED")
                profile = GATE_PROFILES["BALANCED"]

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

                # Profile checks
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

            return ToolOutput(
                success=True,
                message=f"Gate check complete: {len(promoted)} promoted",
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
                return ToolOutput(
                    success=True,
                    message=f"Skipped promotion (Neo4j unavailable): {len(concepts)} concepts",
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
                    # Appel Neo4j promote_to_published()
                    canonical_id = self.neo4j_client.promote_to_published(
                        tenant_id=tenant_id,
                        proto_concept_id=proto_concept_id or f"proto_{concept_name}_{concept_type}",
                        canonical_name=canonical_name,
                        unified_definition=unified_definition,
                        quality_score=quality_score,
                        metadata={
                            "original_name": concept_name,
                            "extracted_type": concept_type,
                            "gate_profile": self.default_profile
                        }
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

            return ToolOutput(
                success=True,
                message=f"Promoted {promoted_count}/{len(concepts)} concepts to Published-KG",
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
