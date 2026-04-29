"""
R6 — Personas V1 (3 profils utilisateurs).

Chaque persona est un override structuré qui module :
- la verbosity de la short_answer
- la fallback_policy (strict / permissive)
- les seuils kg_trust pour AUTHORITATIVE/RELIABLE/PARTIAL/FALLBACK
- les drill-down activés
- le synthesis_style (factual / exploratory / executive)

3 personas V1 (cf. RUNTIME_EXPLOITATION §6) :
- compliance_officer : strict, audit trail max, drill-down complet, hard abstention
- explorer : permissive, surface contradictions/EXCEPTIONS, drill-down riche
- reader : concis, pas de drill-down, fallback permissive (RAG sémantique)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Persona(str, Enum):
    """Personas V1."""

    COMPLIANCE_OFFICER = "compliance_officer"
    EXPLORER = "explorer"
    READER = "reader"


class FallbackPolicy(str, Enum):
    """Politique de fallback en cas de kg_trust < FALLBACK threshold."""

    STRICT = "STRICT"
    """Hard abstention : retourne explicitement 'données insuffisantes'."""

    PERMISSIVE = "PERMISSIVE"
    """Soft fallback : retourne RAG sémantique pur avec disclaimer."""


@dataclass
class PersonaProfile:
    """Profil persona avec tous ses overrides."""

    persona: Persona

    # Verbosity & style
    verbosity: str = "standard"
    """'concise' | 'standard' | 'detailed'."""

    synthesis_style: str = "factual"
    """'factual' | 'exploratory' | 'executive'."""

    # Fallback
    fallback_policy: FallbackPolicy = FallbackPolicy.PERMISSIVE

    # Trust thresholds (overrides des défauts si non None)
    trust_threshold_authoritative: Optional[float] = None
    trust_threshold_reliable: Optional[float] = None
    trust_threshold_partial: Optional[float] = None

    # Drill-down config
    enable_drill_down: bool = True
    max_drill_down_items: int = 10

    # KG_LED preferences
    kg_traversal_depth_bonus: int = 0
    """Ajoute N hops à la traversée KG (compliance_officer = +1)."""

    use_derived_relations: bool = True
    """Inclure les relations transitives (compliance_officer peut préférer false)."""

    # Citation / evidence
    require_evidence_lock: bool = True
    """Si True, refuse synthèse sans citations verbatim."""

    show_uncertainty_explicitly: bool = True
    """Si True, mentionne explicitement les incertitudes/contradictions."""


# ============================================================================
# Profils par défaut
# ============================================================================

PERSONA_PROFILES: dict[Persona, PersonaProfile] = {
    Persona.COMPLIANCE_OFFICER: PersonaProfile(
        persona=Persona.COMPLIANCE_OFFICER,
        verbosity="detailed",
        synthesis_style="factual",
        fallback_policy=FallbackPolicy.STRICT,
        # Seuils plus exigeants
        trust_threshold_authoritative=0.90,
        trust_threshold_reliable=0.75,
        trust_threshold_partial=0.55,
        enable_drill_down=True,
        max_drill_down_items=20,
        kg_traversal_depth_bonus=1,
        use_derived_relations=False,  # privilégie inférence directe
        require_evidence_lock=True,
        show_uncertainty_explicitly=True,
    ),
    Persona.EXPLORER: PersonaProfile(
        persona=Persona.EXPLORER,
        verbosity="detailed",
        synthesis_style="exploratory",
        fallback_policy=FallbackPolicy.PERMISSIVE,
        enable_drill_down=True,
        max_drill_down_items=15,
        kg_traversal_depth_bonus=0,
        use_derived_relations=True,
        require_evidence_lock=False,
        show_uncertainty_explicitly=True,
    ),
    Persona.READER: PersonaProfile(
        persona=Persona.READER,
        verbosity="concise",
        synthesis_style="executive",
        fallback_policy=FallbackPolicy.PERMISSIVE,
        enable_drill_down=False,
        max_drill_down_items=3,
        kg_traversal_depth_bonus=0,
        use_derived_relations=True,
        require_evidence_lock=False,
        show_uncertainty_explicitly=False,
    ),
}


def resolve_persona(persona_hints: Optional[dict]) -> PersonaProfile:
    """
    Résout les persona hints en PersonaProfile.

    Args:
        persona_hints: dict optional avec key 'persona' (str)

    Returns:
        PersonaProfile (default = explorer si non spécifié).
    """
    if not persona_hints:
        return PERSONA_PROFILES[Persona.EXPLORER]

    persona_str = (persona_hints.get("persona") or "").strip().lower()
    try:
        persona = Persona(persona_str)
    except ValueError:
        return PERSONA_PROFILES[Persona.EXPLORER]

    return PERSONA_PROFILES[persona]


__all__ = [
    "Persona",
    "PersonaProfile",
    "FallbackPolicy",
    "PERSONA_PROFILES",
    "resolve_persona",
]
