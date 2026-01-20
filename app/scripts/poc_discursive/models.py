"""
POC Discursive Relation Discrimination - Modeles Pydantic

Ce module definit les modeles de donnees pour le POC.
ATTENTION: Code jetable, non destine a la production.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """Sorties autorisees du discriminateur."""
    ACCEPT = "ACCEPT"  # Type 1 - Relation discursive
    REJECT = "REJECT"  # Type 2 - Relation deduite
    ABSTAIN = "ABSTAIN"  # Contexte insuffisant


class RejectReason(str, Enum):
    """Raisons de rejet (Type 2)."""
    TRANSITIVE = "TRANSITIVE"  # Chaine A -> C -> B
    EXTERNAL_KNOWLEDGE = "EXTERNAL_KNOWLEDGE"  # Connaissance hors texte
    CAUSAL = "CAUSAL"  # Causalite non affirmee
    CONCEPT_MISSING = "CONCEPT_MISSING"  # Concept intermediaire requis


class AbstainReason(str, Enum):
    """Raisons d'abstention."""
    BROKEN_REFERENT = "BROKEN_REFERENT"  # Referent rompu
    AMBIGUOUS = "AMBIGUOUS"  # Ambiguite non resolvable
    INSUFFICIENT = "INSUFFICIENT"  # Contexte insuffisant


class TestCaseCategory(str, Enum):
    """Categories de cas de test."""
    CANONICAL_TYPE1 = "CANONICAL_TYPE1"  # Doit etre accepte
    CANONICAL_TYPE2 = "CANONICAL_TYPE2"  # Doit etre rejete
    FRONTIER = "FRONTIER"  # Cas frontiere (ABSTAIN attendu souvent)


class Confidence(str, Enum):
    """Auto-evaluation de confiance du LLM."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Extract(BaseModel):
    """Un extrait textuel."""
    id: str = Field(..., description="Identifiant unique de l'extrait")
    text: str = Field(..., description="Texte de l'extrait")
    source: Optional[str] = Field(None, description="Source du document")
    section: Optional[str] = Field(None, description="Section d'origine")


class ConceptBundle(BaseModel):
    """Bundle d'extraits pour un concept."""
    name: str = Field(..., description="Nom du concept")
    extracts: list[Extract] = Field(..., description="Extraits (1-2 max)")


class EvidenceBundle(BaseModel):
    """Evidence Bundle complet pour une paire de concepts."""
    scope: Optional[Extract] = Field(None, description="Contexte global (optionnel)")
    concept_a: ConceptBundle = Field(..., description="Premier concept")
    concept_b: ConceptBundle = Field(..., description="Second concept")
    proposed_relation: str = Field(..., description="Relation proposee A -> B")


class TestCase(BaseModel):
    """Un cas de test complet."""
    id: str = Field(..., description="Identifiant du cas")
    description: str = Field(..., description="Description du scenario")
    category: TestCaseCategory = Field(..., description="Categorie attendue")
    evidence_bundle: EvidenceBundle = Field(..., description="Bundle de preuves")
    expected_verdict: Verdict = Field(..., description="Verdict attendu")
    rationale: str = Field(..., description="Pourquoi ce verdict est attendu")


class Citation(BaseModel):
    """Une citation textuelle utilisee dans la justification."""
    extract_id: str = Field(..., description="ID de l'extrait cite")
    quote: str = Field(..., description="Citation exacte")


class DiscriminationResult(BaseModel):
    """Resultat de discrimination pour un cas de test."""
    test_case_id: str = Field(..., description="ID du cas teste")
    verdict: Verdict = Field(..., description="Verdict rendu")
    citations: list[Citation] = Field(default_factory=list, description="Citations utilisees")
    referent_resolution: Optional[str] = Field(
        None,
        description="Raisonnement de resolution de referent (si ACCEPT)"
    )
    reject_reason: Optional[RejectReason] = Field(
        None,
        description="Raison du rejet (si REJECT)"
    )
    abstain_reason: Optional[AbstainReason] = Field(
        None,
        description="Raison de l'abstention (si ABSTAIN)"
    )
    confidence: Confidence = Field(..., description="Auto-evaluation de confiance")
    raw_reasoning: str = Field(..., description="Raisonnement brut du LLM")


class TestSuiteResult(BaseModel):
    """Resultats complets d'une suite de tests."""
    total_cases: int
    results: list[DiscriminationResult]

    # Metriques Type 1
    type1_total: int = 0
    type1_correct_accept: int = 0
    type1_incorrect_reject: int = 0
    type1_abstain: int = 0

    # Metriques Type 2
    type2_total: int = 0
    type2_correct_reject: int = 0
    type2_incorrect_accept: int = 0  # CRITIQUE - faux positifs
    type2_abstain: int = 0

    # Metriques Frontieres
    frontier_total: int = 0
    frontier_abstain: int = 0
    frontier_accept: int = 0
    frontier_reject: int = 0

    # Metriques globales
    justifications_with_citations: int = 0
    justifications_without_citations: int = 0  # CRITIQUE - echec si > 0


class POCVerdict(str, Enum):
    """Verdict final du POC."""
    FAILURE = "FAILURE"  # Criteres d'echec atteints
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # Trop conservateur
    SUCCESS = "SUCCESS"  # Distinction operable


class POCConclusion(BaseModel):
    """Conclusion finale du POC."""
    verdict: POCVerdict
    summary: str

    # Criteres d'echec
    type2_false_positive_rate: float
    unjustified_accepts: int

    # Metriques v2 (frontieres)
    frontier_correct_rate: float = 0.0  # Taux de verdicts corrects
    frontier_abstain_count: int = 0  # Nombre reel d'ABSTAIN

    # Analyse
    critical_failures: list[str]
    recommendations: list[str]
