"""
R1 — Evidence Planner V1.1.

Reçoit le ResolvedQuery (avec mode), choisit le **régime d'exploitation** (1 sur 3),
planifie la stratégie de retrieval (Qdrant + Cypher + TemporalRetriever), et
applique l'**auto-escalation** RAG_LED → KG_LED si signaux structurels détectés.

3 régimes V1.1 (cf. RUNTIME_EXPLOITATION §3 bis) :
- **RAG_LED**  : Qdrant dirige le retrieval, le KG annote les résultats
                 (lifecycle, supersession, exceptions). Pour questions simples
                 où le RAG fait mieux que le KG en termes de pertinence.
- **KG_LED**   : KG dirige (Cypher traversal sur relations typées), le RAG
                 fournit les passages source pour évidence. Pour questions
                 structurelles (temporel, contradiction, scope).
- **HYBRID**   : RAG et KG en parallèle, fusion downstream. Pour couverture
                 maximale (typiquement SYNTHESIS_SUMMARY).

Mapping mode → régime initial (cf. plan §V1.1 §3 bis) :
- LOOKUP_FACTUAL          → RAG_LED (RAG meilleur sur questions simples — fact empirique)
- APPLICABILITY_QUERY     → KG_LED (besoin du graph typé pour scope filtering)
- SNAPSHOT_TEMPORAL       → KG_LED (besoin TemporalRetriever)
- DIFF_EVOLUTION          → KG_LED (idem + SUPERSEDES traversal)
- CONFLICT_RISK           → KG_LED (CONFLICT edges typées)
- EXPLORATION_RELATIONAL  → KG_LED (navigation par type)
- SYNTHESIS_SUMMARY       → HYBRID (couverture maximale + KG annotations)

Auto-escalation RAG_LED → KG_LED : déclenché si pendant le retrieval RAG_LED on
détecte un des signaux suivants (cf. RUNTIME_EXPLOITATION §3 bis Annexe B) :
- WITHDRAWN/REPEALED dans les top results (lifecycle change détecté)
- Ambiguïté temporelle (claims avec validity_start/end qui se contredisent)
- Conflit non résolu détecté (LOGICAL_RELATION CONFLICT touchant un top result)
- Multi-version du même sujet (≥2 supersedes pour le même claim)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from knowbase.runtime.query_resolver import ResolvedQuery, ResponseMode

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    """Régime d'exploitation V1.1."""

    RAG_LED = "RAG_LED"
    KG_LED = "KG_LED"
    HYBRID = "HYBRID"


# Mapping initial mode → régime (V1.1 §3 bis Annexe B)
MODE_TO_INITIAL_REGIME: dict[ResponseMode, Regime] = {
    ResponseMode.LOOKUP_FACTUAL: Regime.RAG_LED,
    ResponseMode.APPLICABILITY_QUERY: Regime.KG_LED,
    ResponseMode.SNAPSHOT_TEMPORAL: Regime.KG_LED,
    ResponseMode.DIFF_EVOLUTION: Regime.KG_LED,
    ResponseMode.CONFLICT_RISK: Regime.KG_LED,
    ResponseMode.EXPLORATION_RELATIONAL: Regime.KG_LED,
    ResponseMode.SYNTHESIS_SUMMARY: Regime.HYBRID,
}


@dataclass
class RetrievalPlan:
    """Plan de retrieval produit par EvidencePlanner."""

    mode: ResponseMode
    regime: Regime
    initial_regime: Regime
    """Pour audit : régime décidé avant escalation éventuelle."""

    # Paramètres de retrieval
    qdrant_top_k: int = 20
    """Nombre de chunks à récupérer via Qdrant."""

    kg_traversal_depth: int = 2
    """Profondeur de traversée KG (1 hop = direct relations only)."""

    use_derived: bool = True
    """Inclure les relations dérivées (transitive_inference) ou directes only."""

    relation_types_filter: Optional[list[str]] = None
    """Filtrer sur certains types LOGICAL_RELATION (ex: ['CONFLICT'] pour CONFLICT_RISK)."""

    temporal_filter: Optional[dict] = None
    """Pour SNAPSHOT/DIFF : { mode, as_of_date, period_start, period_end }."""

    # Auto-escalation (V1.1)
    escalation_triggered: bool = False
    escalation_reason: Optional[str] = None

    # Metadata
    persona_overrides: dict = field(default_factory=dict)
    """Persona-specific overrides (verbosity, fallback policy, etc.)."""


@dataclass
class EscalationSignal:
    """Signal détecté pendant retrieval RAG_LED qui force passage en KG_LED."""

    signal_type: str
    """'WITHDRAWN' | 'TEMPORAL_AMBIGUITY' | 'UNRESOLVED_CONFLICT' | 'MULTI_VERSION'"""

    evidence: list[str] = field(default_factory=list)
    """Claim IDs ou autres preuves du signal."""

    severity: float = 0.5
    """0-1, contribution au déclenchement."""


class EvidencePlanner:
    """
    Évidence Planner V1.1 — décide du régime + plan de retrieval.

    Pattern V1.1 :
    1. Mode → régime initial via MODE_TO_INITIAL_REGIME
    2. Auto-escalation RAG_LED → KG_LED si signaux détectés au runtime
    3. Construit RetrievalPlan avec params adaptés
    """

    def plan(self, resolved: ResolvedQuery) -> RetrievalPlan:
        """Plan initial (avant retrieval). L'escalation se fait via maybe_escalate."""
        initial_regime = MODE_TO_INITIAL_REGIME.get(resolved.mode, Regime.HYBRID)

        plan = RetrievalPlan(
            mode=resolved.mode,
            regime=initial_regime,
            initial_regime=initial_regime,
        )

        # Mode-specific config
        if resolved.mode == ResponseMode.LOOKUP_FACTUAL:
            plan.qdrant_top_k = 10
            plan.kg_traversal_depth = 1
            plan.use_derived = False  # On garde simple pour les lookups directs

        elif resolved.mode == ResponseMode.APPLICABILITY_QUERY:
            plan.qdrant_top_k = 20
            plan.kg_traversal_depth = 2
            plan.use_derived = True
            # On n'exclut pas EXCEPTION car c'est important pour applicability

        elif resolved.mode == ResponseMode.SNAPSHOT_TEMPORAL:
            plan.qdrant_top_k = 15
            plan.kg_traversal_depth = 1
            plan.temporal_filter = {
                "mode": "SNAPSHOT",
                "as_of_date": resolved.temporal_anchor.isoformat() if resolved.temporal_anchor else None,
            }

        elif resolved.mode == ResponseMode.DIFF_EVOLUTION:
            plan.qdrant_top_k = 30
            plan.kg_traversal_depth = 2
            plan.relation_types_filter = ["SUPERSEDES", "EVOLVES_FROM", "REAFFIRMS"]
            plan.temporal_filter = {
                "mode": "DIFF",
                "period_start": resolved.temporal_range[0].isoformat() if resolved.temporal_range else None,
                "period_end": resolved.temporal_range[1].isoformat() if resolved.temporal_range else None,
            }

        elif resolved.mode == ResponseMode.CONFLICT_RISK:
            plan.qdrant_top_k = 10
            plan.kg_traversal_depth = 1
            plan.relation_types_filter = ["CONFLICT"]

        elif resolved.mode == ResponseMode.EXPLORATION_RELATIONAL:
            plan.qdrant_top_k = 5
            plan.kg_traversal_depth = 3
            plan.use_derived = True

        elif resolved.mode == ResponseMode.SYNTHESIS_SUMMARY:
            plan.qdrant_top_k = 50
            plan.kg_traversal_depth = 2
            plan.use_derived = True

        # Persona overrides
        if resolved.persona_hints:
            plan.persona_overrides = dict(resolved.persona_hints)
            # Ex: compliance_officer → kg_traversal_depth +1 pour plus de drill-down
            if resolved.persona_hints.get("persona") == "compliance_officer":
                plan.kg_traversal_depth = max(plan.kg_traversal_depth, 2)

        return plan

    def maybe_escalate(
        self,
        plan: RetrievalPlan,
        rag_results: list[dict],
        signals: Optional[list[EscalationSignal]] = None,
    ) -> RetrievalPlan:
        """
        Auto-escalation RAG_LED → KG_LED si signaux structurels détectés.

        Args:
            plan: Plan initial (régime RAG_LED)
            rag_results: Résultats du retrieval Qdrant (top-k chunks)
            signals: Signaux détectés explicitement (optionnel — sinon détection auto)

        Returns:
            Plan modifié si escalation, sinon plan inchangé.
        """
        if plan.regime != Regime.RAG_LED:
            # Pas d'escalation depuis KG_LED ou HYBRID
            return plan

        # Détection auto si signals non fourni
        if signals is None:
            signals = self._detect_signals(rag_results)

        if not signals:
            return plan

        # Décision d'escalation : score cumulé des signaux >= 0.5
        total_severity = sum(s.severity for s in signals)
        if total_severity < 0.5:
            return plan

        plan.regime = Regime.KG_LED
        plan.escalation_triggered = True
        plan.escalation_reason = "; ".join(
            f"{s.signal_type} (sev={s.severity:.2f}, evidence={len(s.evidence)})"
            for s in signals
        )
        plan.kg_traversal_depth = max(plan.kg_traversal_depth, 2)
        plan.use_derived = True

        logger.info(
            f"[EvidencePlanner] ESCALATION RAG_LED → KG_LED : {plan.escalation_reason}"
        )
        return plan

    def _detect_signals(self, rag_results: list[dict]) -> list[EscalationSignal]:
        """
        Détecte les 4 types de signaux V1.1 dans les rag_results.

        Implémentation R3+R4 :
        - WITHDRAWN/REPEALED : lifecycle_status sur top results
        - TEMPORAL_AMBIGUITY : ≥2 publication_dates très différentes
        - UNRESOLVED_CONFLICT : claim_ids des top results impliqués dans CONFLICT
        - MULTI_VERSION : ≥2 SUPERSEDES depuis/vers le même claim
        """
        signals = []

        # WITHDRAWN/REPEALED detection
        withdrawn_evidence = []
        for r in rag_results:
            lifecycle = (r.get("lifecycle_status") or "").upper()
            if lifecycle in ("WITHDRAWN", "REPEALED", "DEPRECATED", "SUPERSEDED"):
                withdrawn_evidence.append(r.get("claim_id", "unknown"))

        if withdrawn_evidence:
            signals.append(EscalationSignal(
                signal_type="WITHDRAWN",
                evidence=withdrawn_evidence,
                severity=min(0.7, 0.2 + 0.1 * len(withdrawn_evidence)),
            ))

        # TEMPORAL_AMBIGUITY: 2 claims avec validity_start très différents pour le même sujet
        # → simple proxy : 2+ publication_dates différentes parmi top-3
        if len(rag_results) >= 2:
            top_pubs = [r.get("publication_date") for r in rag_results[:3] if r.get("publication_date")]
            distinct_pubs = set(top_pubs)
            if len(distinct_pubs) >= 2:
                # Si l'écart est > 2 ans, on flag
                try:
                    sorted_pubs = sorted(distinct_pubs)
                    earliest = int(str(sorted_pubs[0])[:4])
                    latest = int(str(sorted_pubs[-1])[:4])
                    if latest - earliest >= 2:
                        signals.append(EscalationSignal(
                            signal_type="TEMPORAL_AMBIGUITY",
                            evidence=list(distinct_pubs),
                            severity=0.4,
                        ))
                except (ValueError, IndexError):
                    pass

        return signals

    def detect_kg_signals(
        self,
        claim_ids: list[str],
        kg_lookup_fn,
    ) -> list[EscalationSignal]:
        """
        Signaux nécessitant un round-trip KG : UNRESOLVED_CONFLICT + MULTI_VERSION.

        Args:
            claim_ids: claim_ids extraits des top RAG results
            kg_lookup_fn: callable(claim_ids: list[str]) -> dict avec keys:
                - 'conflicts': list of dicts {claim_id, conflict_count}
                - 'supersedes_in': list of dicts {claim_id, n_in}
                - 'supersedes_out': list of dicts {claim_id, n_out}

        Returns:
            Liste EscalationSignal supplémentaires.
        """
        signals = []
        if not claim_ids or kg_lookup_fn is None:
            return signals

        try:
            kg_data = kg_lookup_fn(claim_ids)
        except Exception as e:
            logger.warning(f"[EvidencePlanner] kg_lookup failed: {e}")
            return signals

        # UNRESOLVED_CONFLICT : ≥1 top claim impliqué dans un CONFLICT
        conflicts = kg_data.get("conflicts", [])
        if conflicts:
            evidence = [str(c.get("claim_id")) for c in conflicts]
            severity = min(0.9, 0.3 + 0.15 * len(conflicts))
            signals.append(EscalationSignal(
                signal_type="UNRESOLVED_CONFLICT",
                evidence=evidence,
                severity=severity,
            ))

        # MULTI_VERSION : ≥2 SUPERSEDES sur le même claim (in OR out)
        sup_in = kg_data.get("supersedes_in", [])
        sup_out = kg_data.get("supersedes_out", [])
        multi_evidence = []
        for entry in sup_in + sup_out:
            count = int(entry.get("n_in") or entry.get("n_out") or 0)
            if count >= 2:
                multi_evidence.append(str(entry.get("claim_id")))
        if multi_evidence:
            signals.append(EscalationSignal(
                signal_type="MULTI_VERSION",
                evidence=multi_evidence,
                severity=min(0.8, 0.3 + 0.1 * len(multi_evidence)),
            ))

        return signals


__all__ = ["EvidencePlanner", "Regime", "RetrievalPlan", "EscalationSignal", "MODE_TO_INITIAL_REGIME"]
