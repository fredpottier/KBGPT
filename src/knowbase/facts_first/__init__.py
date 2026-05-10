"""
OSMOSIS V4 Facts-First — modules d'extraction structurée par type.

Composants :
- [A] QuestionAnalyzer : type detection multi-label top-2 (CH-41.1)
- [B] EvidenceCollector : Claims Neo4j + chunks Qdrant (CH-41.2)
- [C] Type-Adaptive Structurer (CH-41.3)
- [D] Composer (LLM = formatage uniquement)
- [E] Verifier (déterministe + NLI ciblé)

ADR : doc/ongoing/chantiers/2026-05-06_CH-41_ADR_FACTS_FIRST.md
Schémas figés : schemas/facts_first/facts_first_v1_*.json
"""

from .question_analyzer import (
    AnalyzerResult,
    QuestionAnalyzer,
    RoutingDecision,
    get_question_analyzer,
)
from .evidence_collector import (
    EvidenceClaim,
    EvidenceBundle,
    EvidenceCollector,
    get_evidence_collector,
)
from .list_structurer import (
    ListStructurer,
    StructurerResult,
    get_list_structurer,
)
from .list_composer import (
    ListComposer,
    ComposerResult,
    get_list_composer,
)
from .list_verifier import (
    Channel1ListVerifier,
    VerifierIssue,
    VerifierReport,
    get_list_verifier,
)
from .factual_structurer import (
    FactualStructurer,
    StructurerResult as FactualStructurerResult,
    get_factual_structurer,
)
from .factual_composer import (
    FactualComposer,
    ComposerResult as FactualComposerResult,
    get_factual_composer,
)
from .factual_verifier import (
    Channel1FactualVerifier,
    get_factual_verifier,
)
from .self_corrector import (
    SelfCorrector,
    SelfCorrectionDecision,
    get_self_corrector,
)
from .nli_channel2 import (
    Channel2NLIVerifier,
    Channel2Report,
    get_channel2_verifier,
)
from .evidence_rerouter import (
    EvidenceRerouter,
    RerouterDecision,
    get_evidence_rerouter,
)
from .temporal_pipeline import (
    TemporalStructurer,
    TemporalComposer,
    Channel1TemporalVerifier,
    get_temporal_structurer, get_temporal_composer, get_temporal_verifier,
)
from .comparison_pipeline import (
    ComparisonStructurer,
    ComparisonComposer,
    Channel1ComparisonVerifier,
    get_comparison_structurer, get_comparison_composer, get_comparison_verifier,
)
from .causal_pipeline import (
    CausalStructurer,
    CausalComposer,
    Channel1CausalVerifier,
    get_causal_structurer, get_causal_composer, get_causal_verifier,
)

__all__ = [
    "AnalyzerResult",
    "QuestionAnalyzer",
    "RoutingDecision",
    "get_question_analyzer",
    "EvidenceClaim",
    "EvidenceBundle",
    "EvidenceCollector",
    "get_evidence_collector",
    "ListStructurer",
    "StructurerResult",
    "get_list_structurer",
    "ListComposer",
    "ComposerResult",
    "get_list_composer",
    "Channel1ListVerifier",
    "VerifierIssue",
    "VerifierReport",
    "get_list_verifier",
    "FactualStructurer",
    "FactualStructurerResult",
    "get_factual_structurer",
    "FactualComposer",
    "FactualComposerResult",
    "get_factual_composer",
    "Channel1FactualVerifier",
    "get_factual_verifier",
    "SelfCorrector",
    "SelfCorrectionDecision",
    "get_self_corrector",
    "Channel2NLIVerifier",
    "Channel2Report",
    "get_channel2_verifier",
    "EvidenceRerouter",
    "RerouterDecision",
    "get_evidence_rerouter",
    "TemporalStructurer", "TemporalComposer", "Channel1TemporalVerifier",
    "get_temporal_structurer", "get_temporal_composer", "get_temporal_verifier",
    "ComparisonStructurer", "ComparisonComposer", "Channel1ComparisonVerifier",
    "get_comparison_structurer", "get_comparison_composer", "get_comparison_verifier",
    "CausalStructurer", "CausalComposer", "Channel1CausalVerifier",
    "get_causal_structurer", "get_causal_composer", "get_causal_verifier",
]
