"""
Decision Trace pour canonicalisation (P0.3).

Trace complète des décisions de normalisation:
- Stratégies tentées (ontology lookup, fuzzy, LLM, heuristics)
- Scores de chaque stratégie
- Décision finale
- Timestamp et metadata

Permet audit et debugging des décisions de canonicalisation.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class NormalizationStrategy(str, Enum):
    """Stratégies de normalisation (ordre priorité)."""
    ONTOLOGY_LOOKUP = "ontology_lookup"  # Neo4j exact match
    FUZZY_MATCHING = "fuzzy_matching"    # Similarité >= 90%
    LLM_CANONICALIZATION = "llm_canonicalization"  # GPT-4o-mini
    HEURISTIC_RULES = "heuristic_rules"  # Acronymes, casse
    FALLBACK = "fallback"                # Garde tel quel


class StrategyResult(BaseModel):
    """Résultat d'une stratégie de normalisation."""
    strategy: NormalizationStrategy
    attempted: bool = Field(..., description="Si stratégie a été tentée")
    success: bool = Field(False, description="Si stratégie a trouvé une correspondance")
    canonical_name: Optional[str] = Field(None, description="Nom canonique trouvé")
    confidence: float = Field(0.0, description="Score confidence (0-1)")
    execution_time_ms: float = Field(0.0, description="Temps exécution en ms")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata additionnelles")

    class Config:
        json_schema_extra = {
            "example": {
                "strategy": "ontology_lookup",
                "attempted": True,
                "success": True,
                "canonical_name": "SAP S/4HANA Cloud",
                "confidence": 1.0,
                "execution_time_ms": 12.5,
                "metadata": {
                    "entity_id": "S4HANA_CLOUD",
                    "entity_type": "PRODUCT",
                    "match_type": "exact"
                }
            }
        }


class DecisionTrace(BaseModel):
    """
    Trace complète d'une décision de canonicalisation (P0.3).

    Stocké en JSON dans Neo4j CanonicalConcept.decision_trace_json.
    """
    # Input
    raw_name: str = Field(..., description="Nom brut extrait")
    entity_type_hint: Optional[str] = Field(None, description="Type suggéré par extraction")
    tenant_id: str = Field("default", description="Tenant ID")

    # Stratégies tentées (ordre)
    strategies: List[StrategyResult] = Field(default_factory=list, description="Stratégies tentées")

    # Décision finale
    final_canonical_name: str = Field(..., description="Nom canonique final retenu")
    final_strategy: NormalizationStrategy = Field(..., description="Stratégie ayant réussi")
    final_confidence: float = Field(..., description="Confidence finale (0-1)")
    is_cataloged: bool = Field(False, description="Si trouvé dans ontologie")

    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp décision")
    total_execution_time_ms: float = Field(0.0, description="Temps total exécution ms")
    document_id: Optional[str] = Field(None, description="ID document source")
    segment_id: Optional[str] = Field(None, description="ID segment source")

    # Flags
    requires_validation: bool = Field(False, description="Si nécessite validation admin (P0.1 Sandbox)")
    auto_validated: bool = Field(False, description="Si auto-validé (confidence >= 0.95)")

    class Config:
        json_schema_extra = {
            "example": {
                "raw_name": "sap s/4hana",
                "entity_type_hint": "PRODUCT",
                "tenant_id": "default",
                "strategies": [
                    {
                        "strategy": "ontology_lookup",
                        "attempted": True,
                        "success": True,
                        "canonical_name": "SAP S/4HANA Cloud",
                        "confidence": 1.0,
                        "execution_time_ms": 12.5,
                        "metadata": {"entity_id": "S4HANA_CLOUD", "match_type": "exact"}
                    }
                ],
                "final_canonical_name": "SAP S/4HANA Cloud",
                "final_strategy": "ontology_lookup",
                "final_confidence": 1.0,
                "is_cataloged": True,
                "timestamp": "2025-10-16T10:30:00Z",
                "total_execution_time_ms": 15.2,
                "document_id": "doc_123",
                "segment_id": "seg_456",
                "requires_validation": False,
                "auto_validated": True
            }
        }

    def add_strategy_result(self, result: StrategyResult):
        """Ajoute résultat d'une stratégie."""
        self.strategies.append(result)
        self.total_execution_time_ms += result.execution_time_ms

    def finalize(
        self,
        canonical_name: str,
        strategy: NormalizationStrategy,
        confidence: float,
        is_cataloged: bool
    ):
        """Finalise la décision."""
        self.final_canonical_name = canonical_name
        self.final_strategy = strategy
        self.final_confidence = confidence
        self.is_cataloged = is_cataloged

        # P0.1 Sandbox: Déterminer si nécessite validation
        if confidence < 0.95 and is_cataloged:
            self.requires_validation = True
            self.auto_validated = False
        else:
            self.requires_validation = False
            self.auto_validated = True

    def to_json_string(self) -> str:
        """Serialize to JSON string for Neo4j storage."""
        import json
        return json.dumps(self.model_dump(), default=str)

    @classmethod
    def from_json_string(cls, json_str: str) -> "DecisionTrace":
        """Deserialize from JSON string."""
        import json
        data = json.loads(json_str)
        return cls(**data)


def create_decision_trace(
    raw_name: str,
    entity_type_hint: Optional[str] = None,
    tenant_id: str = "default",
    document_id: Optional[str] = None,
    segment_id: Optional[str] = None
) -> DecisionTrace:
    """
    Factory function pour créer DecisionTrace (P0.3).

    Args:
        raw_name: Nom brut extrait
        entity_type_hint: Type suggéré
        tenant_id: Tenant ID
        document_id: ID document source
        segment_id: ID segment source

    Returns:
        DecisionTrace initialisé
    """
    return DecisionTrace(
        raw_name=raw_name,
        entity_type_hint=entity_type_hint,
        tenant_id=tenant_id,
        document_id=document_id,
        segment_id=segment_id,
        final_canonical_name="",  # À remplir
        final_strategy=NormalizationStrategy.FALLBACK,  # À remplir
        final_confidence=0.0  # À remplir
    )


__all__ = [
    "NormalizationStrategy",
    "StrategyResult",
    "DecisionTrace",
    "create_decision_trace"
]
