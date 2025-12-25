"""
🤖 OSMOSE Agentique - Agent de Base

Classe de base pour tous les agents de l'architecture agentique.
Implémente le pattern Tool-Based Agent avec JSON I/O strict.

Architecture: Supervisor + Specialists (6 agents)
Phase 1.5 V1.1
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Rôles des agents dans l'architecture."""
    SUPERVISOR = "supervisor"
    EXTRACTOR = "extractor_orchestrator"
    MINER = "pattern_miner"
    GATEKEEPER = "gatekeeper_delegate"
    BUDGET = "budget_manager"
    DISPATCHER = "llm_dispatcher"


class SegmentWithConcepts(BaseModel):
    """Phase 2.9: Segment avec ses concepts locaux pour extraction segment-level."""
    segment_id: str
    text: str
    topic_id: str = ""
    local_concept_ids: List[str] = Field(default_factory=list)  # IDs concepts extraits de ce segment
    catalogue_concept_ids: List[str] = Field(default_factory=list)  # IDs catalogue hybride (local + global)


class AgentState(BaseModel):
    """État partagé entre agents (passé via FSM)."""
    document_id: str
    tenant_id: str = "default"
    full_text: Optional[str] = None  # Texte complet pour filtrage contextuel
    input_text: Optional[str] = None  # Phase 2.9: Texte complet pour extraction doc-level (alias full_text)
    document_name: Optional[str] = None  # Phase 2: Nom document pour relation extraction
    document_context: Optional[str] = None  # Phase 1.8: Résumé document pour désambiguïsation concepts
    technical_density_hint: float = 0.5  # Phase 1.8.2: Hint LLM (0-1) pour ajuster stratégie extraction
    chunk_ids: List[str] = Field(default_factory=list)  # Phase 2: IDs chunks pour relation extraction

    # Budget tracking
    budget_remaining: Dict[str, int] = Field(default_factory=lambda: {
        "SMALL": 120,
        "BIG": 8,
        "VISION": 2
    })

    # Extraction state
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    promoted: List[Dict[str, Any]] = Field(default_factory=list)
    relations: List[Dict[str, Any]] = Field(default_factory=list)  # Problème 1: Relations sémantiques

    # Phase 2.9: Segments avec concepts pour extraction segment-level
    segments_with_concepts: Dict[str, SegmentWithConcepts] = Field(default_factory=dict)

    # Phase 2: Stats extraction relations
    relation_extraction_stats: Dict[str, Any] = Field(default_factory=dict)

    # Phase 2.9.4: Résultats extraction (segment-level + doc-level)
    extraction_results: Dict[str, Any] = Field(default_factory=dict)

    # Phase 1.6: Cross-référence Neo4j ↔ Qdrant
    concept_to_chunk_ids: Dict[str, List[str]] = Field(default_factory=dict)  # {"proto-123": ["chunk-456"]}

    # Metrics
    cost_incurred: float = 0.0
    llm_calls_count: Dict[str, int] = Field(default_factory=lambda: {
        "SMALL": 0,
        "BIG": 0,
        "VISION": 0
    })

    # FSM tracking
    current_step: str = "init"
    steps_count: int = 0
    max_steps: int = 50
    started_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 3600  # 60 min/doc (nécessaire pour gros documents 200+ slides)

    # Errors
    errors: List[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class ToolInput(BaseModel):
    """Schema de base pour input de tool (JSON strict)."""
    pass


class ToolOutput(BaseModel):
    """Schema de base pour output de tool (JSON strict)."""
    success: bool
    message: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    """
    Agent de base pour architecture agentique OSMOSE.

    Tous les agents héritent de cette classe et implémentent:
    - execute(): Logique métier de l'agent
    - get_tools(): Liste des tools disponibles
    - validate_state(): Validation de l'état avant exécution
    """

    def __init__(
        self,
        role: AgentRole,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialise l'agent.

        Args:
            role: Rôle de l'agent
            config: Configuration spécifique à l'agent
        """
        self.role = role
        self.config = config or {}
        self.tools: Dict[str, Any] = {}

        # Charger les tools de l'agent
        self._register_tools()

        logger.info(f"[AGENTS] {self.role.value} initialized with {len(self.tools)} tools")

    @abstractmethod
    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        pass

    @abstractmethod
    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Exécute la logique de l'agent.

        Args:
            state: État actuel partagé
            instruction: Instruction optionnelle du Supervisor

        Returns:
            État mis à jour
        """
        pass

    def validate_state(self, state: AgentState) -> bool:
        """
        Valide l'état avant exécution.

        Args:
            state: État à valider

        Returns:
            True si état valide
        """
        # Vérifications communes
        if state.steps_count >= state.max_steps:
            logger.error(f"[AGENTS] {self.role.value}: Max steps reached")
            return False

        elapsed = time.time() - state.started_at
        if elapsed > state.timeout_seconds:
            logger.error(f"[AGENTS] {self.role.value}: Timeout reached ({elapsed:.1f}s)")
            return False

        return True

    async def call_tool(
        self,
        tool_name: str,
        tool_input: ToolInput
    ) -> ToolOutput:
        """
        Appelle un tool de l'agent (supporte async et sync tools).

        Args:
            tool_name: Nom du tool
            tool_input: Input JSON du tool

        Returns:
            Output JSON du tool
        """
        import inspect

        if tool_name not in self.tools:
            logger.error(f"[AGENTS] {self.role.value}: Tool '{tool_name}' not found")
            return ToolOutput(
                success=False,
                message=f"Tool '{tool_name}' not found"
            )

        tool_func = self.tools[tool_name]

        try:
            # Détecter si le tool est async et appeler en conséquence
            if inspect.iscoroutinefunction(tool_func):
                # Tool async : utiliser await
                result = await tool_func(tool_input)
            else:
                # Tool synchrone : appel direct
                result = tool_func(tool_input)

            logger.debug(f"[AGENTS] {self.role.value}: Tool '{tool_name}' executed successfully")
            return result
        except Exception as e:
            logger.error(f"[AGENTS] {self.role.value}: Tool '{tool_name}' failed: {e}", exc_info=True)
            return ToolOutput(
                success=False,
                message=f"Tool execution failed: {str(e)}"
            )

    def get_tool_names(self) -> List[str]:
        """Retourne la liste des noms de tools."""
        return list(self.tools.keys())
