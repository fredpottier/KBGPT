"""
🤖 OSMOSE Agentique - Gatekeeper Delegate

Quality control et promotion Proto→Published.
"""

from typing import Dict, Any, Optional, List
import logging
import re

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput

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
            tool_input: Concepts à promouvoir

        Returns:
            Count promoted
        """
        try:
            concepts = tool_input.concepts

            # TODO: Implémenter promotion Neo4j
            # Pour l'instant: mock
            promoted_count = len(concepts)

            logger.debug(f"[GATEKEEPER:PromoteConcepts] {promoted_count} concepts promoted to Neo4j")

            return ToolOutput(
                success=True,
                message=f"Promoted {promoted_count} concepts",
                data={
                    "promoted_count": promoted_count
                }
            )

        except Exception as e:
            logger.error(f"[GATEKEEPER:PromoteConcepts] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"PromoteConcepts failed: {str(e)}"
            )
