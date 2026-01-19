"""
OSMOSE Linguistic Layer - Modèles de données pour la coréférence

Ce module définit les structures de données pour la Linguistic Coreference Layer (Pass 0.5).

Modèles principaux:
- MentionSpan: Une mention textuelle (pronom, GN défini, nom propre)
- CoreferenceChain: Un cluster de mentions coréférentes
- CorefDecision: Décision d'audit pour chaque résolution
- CorefLink: Lien direct pronom → antécédent

Invariants respectés:
- L1: Evidence-preserving (offsets exacts)
- L5: Linguistic-only (pas de relation conceptuelle)

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10.4
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import uuid4


class MentionType(str, Enum):
    """Type de mention textuelle."""
    PRONOUN = "PRONOUN"      # il, elle, it, they
    NP = "NP"                # groupe nominal défini (le système, the device)
    PROPER = "PROPER"        # nom propre (entités nommées, produits, technologies)
    OTHER = "OTHER"          # autre


class DecisionType(str, Enum):
    """Type de décision de résolution."""
    RESOLVED = "RESOLVED"           # Résolution réussie
    ABSTAIN = "ABSTAIN"             # Abstention (ambiguïté, etc.)
    NON_REFERENTIAL = "NON_REFERENTIAL"  # Pronom non référentiel (il pleut)


class ReasonCode(str, Enum):
    """Code de raison pour les décisions."""
    # Résolution réussie
    UNAMBIGUOUS = "UNAMBIGUOUS"                 # Un seul candidat évident
    LLM_VALIDATED = "LLM_VALIDATED"             # Validé par LLM arbiter
    RULE_MATCHED = "RULE_MATCHED"               # Règle heuristique matchée
    CACHE_HIT = "CACHE_HIT"                     # Résolu via cache
    HIGH_SIMILARITY = "HIGH_SIMILARITY"         # Similarité string très haute (Named↔Named)
    LOW_RISK = "LOW_RISK"                       # Aucun signal de risque (Named↔Named)

    # Abstention
    AMBIGUOUS = "AMBIGUOUS"                     # Plusieurs candidats possibles
    NO_CANDIDATE = "NO_CANDIDATE"               # Aucun antécédent trouvé
    LOW_CONFIDENCE = "LOW_CONFIDENCE"           # Score en dessous du seuil
    LONG_DISTANCE = "LONG_DISTANCE"             # Distance trop grande
    BRIDGING = "BRIDGING"                       # Référence bridging (non coréférentiel)
    NEEDS_LLM_VALIDATION = "NEEDS_LLM_VALIDATION"  # Zone grise, envoyé au LLM
    LLM_ABSTAIN = "LLM_ABSTAIN"                 # LLM incapable de trancher
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"         # LLM indisponible, abstention par défaut

    # Non référentiel
    IMPERSONAL = "IMPERSONAL"                   # Pronom impersonnel (il pleut)
    EXPLETIVE = "EXPLETIVE"                     # Pronom explétif (it is important)
    GENERIC = "GENERIC"                         # Référence générique (on, one)

    # Named↔Named gating - REJECT
    LLM_REJECTED = "LLM_REJECTED"               # LLM a rejeté la coréférence
    STRING_SIMILARITY_LOW = "STRING_SIMILARITY_LOW"  # Jaro-Winkler < 0.55
    NO_TOKEN_OVERLAP = "NO_TOKEN_OVERLAP"       # Token Jaccard = 0


class CorefScope(str, Enum):
    """Portée de la résolution."""
    SAME_SENTENCE = "same_sentence"
    PREV_SENTENCE = "prev_sentence"
    PREV_CHUNK = "prev_chunk"
    WINDOW_K = "window_k"


@dataclass
class MentionSpan:
    """
    Représente une mention textuelle dans un document.

    Ancrage principal sur DocItem (vérité structurelle),
    avec lien secondaire vers TypeAwareChunk (consommation).

    NOTE GOUVERNANCE: Ce span est un fait linguistique,
    pas une assertion sémantique.
    """

    # Identifiants
    tenant_id: str
    doc_id: str
    doc_version_id: str

    # Ancrage principal (DocItem = vérité structurelle)
    docitem_id: str

    # Ancrage secondaire (Chunk = consommation)
    chunk_id: Optional[str] = None

    # Position exacte dans le texte (invariant L1)
    span_start: int = 0
    span_end: int = 0

    # Texte exact (facultatif mais pratique)
    surface: str = ""

    # Classification
    mention_type: MentionType = MentionType.OTHER

    # Langue
    lang: str = "en"

    # Contexte
    sentence_index: Optional[int] = None

    # Métadonnées
    mention_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validation post-initialisation."""
        if self.span_end < self.span_start:
            raise ValueError(f"span_end ({self.span_end}) < span_start ({self.span_start})")

    @property
    def span_key(self) -> str:
        """Clé unique pour ce span."""
        return f"{self.doc_version_id}:{self.docitem_id}:{self.span_start}:{self.span_end}"

    def to_neo4j_props(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "docitem_id": self.docitem_id,
            "chunk_id": self.chunk_id,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "surface": self.surface,
            "mention_type": self.mention_type.value,
            "lang": self.lang,
            "sentence_index": self.sentence_index,
            "mention_id": self.mention_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CorefLink:
    """
    Lien de coréférence entre deux mentions.

    Direction: source (pronom) → target (antécédent)

    NOTE GOUVERNANCE: Ce lien est linguistique, pas sémantique.
    COREFERS_TO n'implique aucune relation conceptuelle (is-a, uses, etc.).
    """

    # Mentions liées
    source_mention_id: str      # Pronom ou mention anaphorique
    target_mention_id: str      # Antécédent

    # Métadonnées de résolution
    method: str = "unknown"     # spacy_coref | coreferee | rule_based | llm_arbiter
    confidence: float = 0.0     # 0.0-1.0
    scope: CorefScope = CorefScope.SAME_SENTENCE
    window_chars: Optional[int] = None

    # Identifiant et timestamp
    link_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> dict:
        """Convertit en propriétés de relation Neo4j."""
        return {
            "method": self.method,
            "confidence": self.confidence,
            "scope": self.scope.value,
            "window_chars": self.window_chars,
            "link_id": self.link_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CoreferenceChain:
    """
    Un cluster (chaîne) de mentions coréférentes dans un document.

    Toutes les mentions d'une chaîne réfèrent au même référent.
    Une mention est désignée comme "representative" (typiquement le nom propre
    ou la première mention complète).
    """

    # Identifiants
    tenant_id: str
    doc_id: str
    doc_version_id: str
    chain_id: str = field(default_factory=lambda: str(uuid4()))

    # Méthode de création
    method: str = "unknown"     # spacy_coref | coreferee | rule_based | hybrid

    # Confiance agrégée
    confidence: float = 0.0

    # Mentions de la chaîne (IDs)
    mention_ids: List[str] = field(default_factory=list)
    representative_mention_id: Optional[str] = None

    # Timestamp
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_mention(self, mention_id: str, is_representative: bool = False):
        """Ajoute une mention à la chaîne."""
        if mention_id not in self.mention_ids:
            self.mention_ids.append(mention_id)
        if is_representative:
            self.representative_mention_id = mention_id

    def to_neo4j_props(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "chain_id": self.chain_id,
            "method": self.method,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CorefDecision:
    """
    Décision d'audit pour une résolution de coréférence.

    Cet objet est STANDARD (pas optionnel) car l'audit est un invariant
    culturel d'OSMOSE.

    Trace toutes les décisions: résolutions, abstentions, et non-référentiels.
    """

    # Identifiants
    tenant_id: str
    doc_version_id: str
    decision_id: str = field(default_factory=lambda: str(uuid4()))

    # Mention concernée
    mention_span_key: str = ""

    # Candidats évalués
    candidate_count: int = 0
    candidate_keys: List[str] = field(default_factory=list)

    # Décision
    chosen_candidate_key: Optional[str] = None  # None si ABSTAIN
    decision_type: DecisionType = DecisionType.ABSTAIN
    confidence: float = 0.0

    # Méthode et raison
    method: str = "unknown"
    reason_code: ReasonCode = ReasonCode.NO_CANDIDATE
    reason_detail: str = ""

    # Timestamp
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_resolved(self) -> bool:
        """Indique si la décision est une résolution réussie."""
        return self.decision_type == DecisionType.RESOLVED

    @property
    def is_abstained(self) -> bool:
        """Indique si la décision est une abstention."""
        return self.decision_type == DecisionType.ABSTAIN

    def to_neo4j_props(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "tenant_id": self.tenant_id,
            "doc_version_id": self.doc_version_id,
            "decision_id": self.decision_id,
            "mention_span_key": self.mention_span_key,
            "candidate_count": self.candidate_count,
            "chosen_candidate_key": self.chosen_candidate_key,
            "decision_type": self.decision_type.value,
            "confidence": self.confidence,
            "method": self.method,
            "reason_code": self.reason_code.value,
            "reason_detail": self.reason_detail,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CoreferenceCluster:
    """
    Résultat intermédiaire d'un engine de coréférence.

    Utilisé pour la communication entre ICorefEngine et le reste du système.
    Converti ensuite en MentionSpan + CoreferenceChain pour persistance.
    """

    # Mentions du cluster (spans bruts avant conversion en MentionSpan)
    mentions: List[dict] = field(default_factory=list)
    # Format: {"start": int, "end": int, "text": str, "sentence_idx": int}

    # Index de la mention représentative
    representative_idx: int = 0

    # Confiance du cluster
    confidence: float = 0.0

    # Méthode
    method: str = "unknown"

    def __len__(self) -> int:
        return len(self.mentions)

    @property
    def representative(self) -> Optional[dict]:
        """Retourne la mention représentative."""
        if self.mentions and 0 <= self.representative_idx < len(self.mentions):
            return self.mentions[self.representative_idx]
        return None


@dataclass
class CorefGraphResult:
    """
    Résultat complet de la résolution de coréférence pour un document.

    Contient toutes les structures à persister dans Neo4j.
    """

    # Document
    doc_id: str
    doc_version_id: str

    # Structures créées
    mention_spans: List[MentionSpan] = field(default_factory=list)
    chains: List[CoreferenceChain] = field(default_factory=list)
    links: List[CorefLink] = field(default_factory=list)
    decisions: List[CorefDecision] = field(default_factory=list)

    # Métriques
    total_pronouns_detected: int = 0
    resolved_count: int = 0
    abstained_count: int = 0
    non_referential_count: int = 0

    # Méthode et timing
    method: str = "unknown"
    processing_time_ms: float = 0.0

    @property
    def resolution_rate(self) -> float:
        """Taux de résolution (0.0-1.0)."""
        total = self.resolved_count + self.abstained_count + self.non_referential_count
        if total == 0:
            return 0.0
        return self.resolved_count / total

    @property
    def abstention_rate(self) -> float:
        """Taux d'abstention (0.0-1.0)."""
        total = self.resolved_count + self.abstained_count + self.non_referential_count
        if total == 0:
            return 0.0
        return self.abstained_count / total

    def summary(self) -> dict:
        """Résumé pour logging."""
        return {
            "doc_id": self.doc_id,
            "mention_spans": len(self.mention_spans),
            "chains": len(self.chains),
            "links": len(self.links),
            "resolved": self.resolved_count,
            "abstained": self.abstained_count,
            "non_referential": self.non_referential_count,
            "resolution_rate": f"{self.resolution_rate:.1%}",
            "abstention_rate": f"{self.abstention_rate:.1%}",
            "method": self.method,
            "time_ms": f"{self.processing_time_ms:.0f}",
        }
