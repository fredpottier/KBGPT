"""
Confidence Engine v2 - OSMOSE Answer+Proof

Evaluateur epistemique deterministe pour le Knowledge Graph.
Ce module calcule l'etat de confiance d'une reponse basee sur les signaux KG.

Design Principle:
"Osmos does not optimize for producing answers.
 Osmos optimizes for determining what it knows, why it knows it,
 and where its knowledge boundaries lie."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class EpistemicState(str, Enum):
    """Etat epistemique de la connaissance (ce que le KG sait)."""
    ESTABLISHED = "established"   # Relations coherentes, validees, multi-sources
    PARTIAL = "partial"           # Relations presentes mais fragiles
    DEBATE = "debate"             # Conflits detectes entre sources
    INCOMPLETE = "incomplete"     # Concepts orphelins ou relations manquantes


class ContractState(str, Enum):
    """Etat contractuel (ce que le DomainContext attend)."""
    COVERED = "covered"           # Question dans le perimetre
    OUT_OF_SCOPE = "out_of_scope" # Question hors perimetre


@dataclass
class KGSignals:
    """Signaux collectes sur le sous-graphe de la reponse (Answer Subgraph).

    Le sous-graphe est defini comme l'ensemble des typed_edges
    qui apparaissent dans reasoning_trace.steps[].supports.
    """
    typed_edges_count: int = 0              # Nombre de relations typees utilisees
    avg_conf: float = 0.0                   # Moyenne confidence des relations
    validated_ratio: float = 0.0            # ratio maturity VALIDATED / total
    conflicts_count: int = 0                # CONFLICTS_WITH detectes
    orphan_concepts_count: int = 0          # Concepts avec degree typed = 0
    independent_sources_count: int = 0      # Documents distincts supportant les relations
    expected_edges_missing_count: int = 0   # Relations attendues mais absentes (optionnel)


@dataclass
class DomainSignals:
    """Signaux depuis DomainContextStore."""
    in_scope_domains: List[str] = field(default_factory=list)   # sub_domains du tenant
    matched_domains: List[str] = field(default_factory=list)    # Domaines matches par la question

    @property
    def contract_state(self) -> ContractState:
        """COVERED si match non vide, sinon OUT_OF_SCOPE."""
        return ContractState.COVERED if self.matched_domains else ContractState.OUT_OF_SCOPE


@dataclass
class ConfidenceResult:
    """Resultat complet du Confidence Engine."""
    epistemic_state: EpistemicState
    contract_state: ContractState
    badge: str
    micro_text: str
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    rules_fired: List[str] = field(default_factory=list)
    cta: Optional[Dict[str, str]] = None
    kg_signals: Optional[KGSignals] = None
    domain_signals: Optional[DomainSignals] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour l'API."""
        return {
            "epistemic_state": self.epistemic_state.value,
            "contract_state": self.contract_state.value,
            "badge": self.badge,
            "micro_text": self.micro_text,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "rules_fired": self.rules_fired,
            "cta": self.cta,
            "kg_signals": {
                "typed_edges_count": self.kg_signals.typed_edges_count,
                "avg_conf": self.kg_signals.avg_conf,
                "validated_ratio": self.kg_signals.validated_ratio,
                "conflicts_count": self.kg_signals.conflicts_count,
                "orphan_concepts_count": self.kg_signals.orphan_concepts_count,
                "independent_sources_count": self.kg_signals.independent_sources_count,
                "expected_edges_missing_count": self.kg_signals.expected_edges_missing_count,
            } if self.kg_signals else None,
            "domain_signals": {
                "in_scope_domains": self.domain_signals.in_scope_domains,
                "matched_domains": self.domain_signals.matched_domains,
            } if self.domain_signals else None,
        }


# === Confidence Engine Core ===

def compute_epistemic_state(s: KGSignals) -> tuple[EpistemicState, List[str]]:
    """
    Calcule l'etat epistemique depuis les signaux KG.

    Retourne (etat, regles_declenchees).

    Table de verite:
    | E | C | O | M | S | EpistemicState |
    |---|---|---|---|---|----------------|
    | 0 | * | * | * | * | INCOMPLETE     |
    | 1 | 1 | * | * | * | DEBATE         |
    | 1 | 0 | 1 | * | * | INCOMPLETE     |
    | 1 | 0 | 0 | 1 | * | INCOMPLETE     |
    | 1 | 0 | 0 | 0 | 1 | ESTABLISHED    |
    | 1 | 0 | 0 | 0 | 0 | PARTIAL        |

    Ou:
    - E = typed_edges_count > 0
    - C = conflicts_count > 0
    - O = orphan_concepts_count > 0
    - M = expected_edges_missing_count > 0
    - S = (validated_ratio >= 0.70 AND avg_conf >= 0.80 AND sources >= 2)
    """
    rules_fired = []

    # 0) Cas extreme : pas de relations typees
    if s.typed_edges_count == 0:
        rules_fired.append("NO_TYPED_EDGES")
        return EpistemicState.INCOMPLETE, rules_fired

    # 1) Conflits = DEBATE prioritaire (le conflit l'emporte toujours)
    if s.conflicts_count > 0:
        rules_fired.append("CONFLICT_DETECTED")
        return EpistemicState.DEBATE, rules_fired

    rules_fired.append("NO_CONFLICT")

    # 2) Incompletude structurelle
    if s.orphan_concepts_count > 0:
        rules_fired.append("ORPHAN_CONCEPTS")
        return EpistemicState.INCOMPLETE, rules_fired

    if s.expected_edges_missing_count and s.expected_edges_missing_count > 0:
        rules_fired.append("MISSING_EXPECTED_EDGES")
        return EpistemicState.INCOMPLETE, rules_fired

    # 3) Etablie vs Partielle
    strong_maturity = s.validated_ratio >= 0.70
    strong_conf = s.avg_conf >= 0.80
    multi_sources = s.independent_sources_count >= 2

    if strong_maturity:
        rules_fired.append("STRONG_MATURITY")
    else:
        rules_fired.append("WEAK_MATURITY")

    if strong_conf:
        rules_fired.append("STRONG_CONFIDENCE")
    else:
        rules_fired.append("WEAK_CONFIDENCE")

    if multi_sources:
        rules_fired.append("MULTI_SOURCES")
    else:
        rules_fired.append("SINGLE_SOURCE")

    if strong_maturity and strong_conf and multi_sources:
        return EpistemicState.ESTABLISHED, rules_fired

    # 4) Sinon : relations coherentes mais fragiles
    return EpistemicState.PARTIAL, rules_fired


def compute_contract_state(d: DomainSignals) -> ContractState:
    """
    Calcule l'etat contractuel depuis les signaux Domain.

    Aucune intelligence ici : c'est un contrat explicite.
    """
    return d.contract_state


# === Badge et Messages ===

BADGE_CONFIG = {
    (EpistemicState.ESTABLISHED, ContractState.COVERED): {
        "badge": "Reponse controlee",
        "micro_text": "Soutenue par {edges} relations validees / {sources} sources",
        "icon": "check_circle",
        "color": "green",
    },
    (EpistemicState.PARTIAL, ContractState.COVERED): {
        "badge": "Reponse partiellement controlee",
        "micro_text": "Certaines parties restent peu etayees - voir Couverture",
        "icon": "warning",
        "color": "yellow",
        "cta": {"label": "Voir couverture", "action": "scroll_to_coverage"},
    },
    (EpistemicState.DEBATE, ContractState.COVERED): {
        "badge": "Reponse controversee",
        "micro_text": "Sources en desaccord - arbitrage requis",
        "icon": "error",
        "color": "orange",
        "cta": {"label": "Voir les divergences", "action": "scroll_to_conflicts"},
    },
    (EpistemicState.INCOMPLETE, ContractState.COVERED): {
        "badge": "Reponse non garantie",
        "micro_text": "Le graphe ne permet pas de soutenir la reponse de bout en bout",
        "icon": "cancel",
        "color": "red",
        "cta": {"label": "Voir ce qu'il manque", "action": "scroll_to_gaps"},
    },
    # OUT_OF_SCOPE - meme badge quel que soit l'etat epistemique
    (EpistemicState.ESTABLISHED, ContractState.OUT_OF_SCOPE): {
        "badge": "Hors perimetre",
        "micro_text": "Domaine non couvert par votre DomainContext",
        "icon": "help_outline",
        "color": "gray",
        "cta": {"label": "Ajouter ce domaine", "action": "open_domain_config"},
    },
    (EpistemicState.PARTIAL, ContractState.OUT_OF_SCOPE): {
        "badge": "Hors perimetre",
        "micro_text": "Domaine non couvert par votre DomainContext",
        "icon": "help_outline",
        "color": "gray",
        "cta": {"label": "Ajouter ce domaine", "action": "open_domain_config"},
    },
    (EpistemicState.DEBATE, ContractState.OUT_OF_SCOPE): {
        "badge": "Hors perimetre",
        "micro_text": "Domaine non couvert par votre DomainContext",
        "icon": "help_outline",
        "color": "gray",
        "cta": {"label": "Ajouter ce domaine", "action": "open_domain_config"},
    },
    (EpistemicState.INCOMPLETE, ContractState.OUT_OF_SCOPE): {
        "badge": "Hors perimetre",
        "micro_text": "Domaine non couvert par votre DomainContext",
        "icon": "help_outline",
        "color": "gray",
        "cta": {"label": "Ajouter ce domaine", "action": "open_domain_config"},
    },
}


def build_confidence_result(
    kg_signals: KGSignals,
    domain_signals: DomainSignals,
) -> ConfidenceResult:
    """
    Construit le resultat complet du Confidence Engine.

    Point d'entree principal pour l'API.
    """
    # Calculer les etats
    epistemic_state, rules_fired = compute_epistemic_state(kg_signals)
    contract_state = compute_contract_state(domain_signals)

    # Recuperer la config du badge
    config = BADGE_CONFIG.get(
        (epistemic_state, contract_state),
        BADGE_CONFIG[(EpistemicState.INCOMPLETE, ContractState.COVERED)]
    )

    # Formater le micro-text
    micro_text = config["micro_text"].format(
        edges=kg_signals.typed_edges_count,
        sources=kg_signals.independent_sources_count,
    )

    # Construire les warnings
    warnings = []
    if epistemic_state == EpistemicState.PARTIAL:
        if kg_signals.validated_ratio < 0.70:
            warnings.append(f"Seulement {kg_signals.validated_ratio*100:.0f}% des relations sont validees")
        if kg_signals.independent_sources_count < 2:
            warnings.append("Une seule source independante")

    # Construire les blockers
    blockers = []
    if epistemic_state == EpistemicState.DEBATE:
        blockers.append(f"{kg_signals.conflicts_count} conflit(s) detecte(s) entre sources")
    if epistemic_state == EpistemicState.INCOMPLETE:
        if kg_signals.typed_edges_count == 0:
            blockers.append("Aucune relation typee dans le graphe")
        if kg_signals.orphan_concepts_count > 0:
            blockers.append(f"{kg_signals.orphan_concepts_count} concept(s) non relie(s)")

    return ConfidenceResult(
        epistemic_state=epistemic_state,
        contract_state=contract_state,
        badge=config["badge"],
        micro_text=micro_text,
        warnings=warnings,
        blockers=blockers,
        rules_fired=rules_fired,
        cta=config.get("cta"),
        kg_signals=kg_signals,
        domain_signals=domain_signals,
    )


# === Singleton Service ===

_confidence_engine: Optional["ConfidenceEngine"] = None


class ConfidenceEngine:
    """Service Confidence Engine."""

    def evaluate(
        self,
        kg_signals: KGSignals,
        domain_signals: DomainSignals,
    ) -> ConfidenceResult:
        """Evalue la confiance d'une reponse."""
        return build_confidence_result(kg_signals, domain_signals)

    def evaluate_from_dict(
        self,
        kg_signals_dict: Dict[str, Any],
        domain_signals_dict: Dict[str, Any],
    ) -> ConfidenceResult:
        """Evalue depuis des dictionnaires (pour l'API)."""
        kg_signals = KGSignals(
            typed_edges_count=kg_signals_dict.get("typed_edges_count", 0),
            avg_conf=kg_signals_dict.get("avg_conf", 0.0),
            validated_ratio=kg_signals_dict.get("validated_ratio", 0.0),
            conflicts_count=kg_signals_dict.get("conflicts_count", 0),
            orphan_concepts_count=kg_signals_dict.get("orphan_concepts_count", 0),
            independent_sources_count=kg_signals_dict.get("independent_sources_count", 0),
            expected_edges_missing_count=kg_signals_dict.get("expected_edges_missing_count", 0),
        )
        domain_signals = DomainSignals(
            in_scope_domains=domain_signals_dict.get("in_scope_domains", []),
            matched_domains=domain_signals_dict.get("matched_domains", []),
        )
        return self.evaluate(kg_signals, domain_signals)


def get_confidence_engine() -> ConfidenceEngine:
    """Retourne l'instance singleton du Confidence Engine."""
    global _confidence_engine
    if _confidence_engine is None:
        _confidence_engine = ConfidenceEngine()
    return _confidence_engine


__all__ = [
    "EpistemicState",
    "ContractState",
    "KGSignals",
    "DomainSignals",
    "ConfidenceResult",
    "compute_epistemic_state",
    "compute_contract_state",
    "build_confidence_result",
    "ConfidenceEngine",
    "get_confidence_engine",
]
