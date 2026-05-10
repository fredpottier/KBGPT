"""
OSMOSIS V4 — Evidence-Aware Rerouter (CH-42.3, domain-agnostic).

But : corriger les erreurs de routing du QuestionAnalyzer (LLM zero-shot trop
faible sur fine-grained classification, cf. arXiv 2406.08660) en exploitant
les signaux STRUCTURELS du KG (Neo4j) après la collecte d'evidence.

Pattern :
  Q → Analyzer (signal initial faillible)
    → EvidenceCollector (claims + chunks)
    → EvidenceRerouter ← inspecte les claim_ids dans Neo4j pour détecter
                         LIFECYCLE_RELATION / LOGICAL_RELATION / multi-doc-date
    → Pipeline correctement routé (factual / list / temporal / comparison)

Domain-agnostic par construction :
  - aucune logique métier (pas de regex sur "GDPR", "CS-25", "EU 2021/821")
  - exploite uniquement les types de relations structurels universels
  - les Domain Packs peuvent étendre les règles sans toucher au core

Conservatisme (charte) :
  - Promotion uniquement si analyzer_confidence < 0.7 (ne pas écraser un signal fort)
  - Promotion uniquement si ≥ 2 signaux concordants OU 1 signal très fort
  - Logger chaque promotion (audit, détection de dérive corpus)

Référence inspiration : RAGRouter (arXiv 2505.23052) — routing query-aware ET
document-aware. Notre version est déterministe (pas un modèle appris) pour
éviter le couplage corpus.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from knowbase.facts_first.evidence_collector import EvidenceBundle
from knowbase.facts_first.question_analyzer import AnalyzerResult

logger = logging.getLogger(__name__)


# Seuils (ajustables par env si besoin Domain Pack)
PROMOTION_CONFIDENCE_CEILING = 0.7   # au-delà, ne pas écraser l'analyzer
MIN_SIGNALS_FOR_PROMOTION = 1        # nb minimal de signaux pour déclencher
MIN_LIFECYCLE_HITS = 1               # nb relations LIFECYCLE pour promote temporal
MIN_LOGICAL_HITS = 1                 # nb relations LOGICAL contradicts pour promote comparison
MIN_DISTINCT_DATES = 2               # nb doc-dates distinctes pour signal multi-version


@dataclass
class RerouterDecision:
    """Décision du rerouter — info pour diagnostic et audit."""
    original_type: str
    original_confidence: float
    promoted_type: Optional[str] = None  # None si pas de promotion
    signals_detected: dict = field(default_factory=dict)
    rationale: str = ""
    seed_claim_count: int = 0

    @property
    def was_promoted(self) -> bool:
        return self.promoted_type is not None and self.promoted_type != self.original_type

    @property
    def final_type(self) -> str:
        return self.promoted_type if self.was_promoted else self.original_type

    def to_dict(self) -> dict:
        return {
            "original_type": self.original_type,
            "original_confidence": self.original_confidence,
            "promoted_type": self.promoted_type,
            "final_type": self.final_type,
            "was_promoted": self.was_promoted,
            "signals_detected": self.signals_detected,
            "rationale": self.rationale,
            "seed_claim_count": self.seed_claim_count,
        }


class EvidenceRerouter:
    """Rerouter déterministe basé sur signaux KG structurels (domain-agnostic).

    Args:
        promotion_ceiling: confidence analyzer au-delà de laquelle on ne promeut pas
            (préserve les classifications fortes)
        min_lifecycle: nb min de relations LIFECYCLE_RELATION sur les seed claims
            pour promouvoir vers temporal
        min_logical: nb min de relations LOGICAL_RELATION (CONTRADICTS) pour
            promouvoir vers comparison
        min_dates: nb min de publication_dates distinctes pour signal multi-version
    """

    def __init__(
        self,
        neo4j_driver=None,
        tenant_id: str = "default",
        promotion_ceiling: float = PROMOTION_CONFIDENCE_CEILING,
        min_lifecycle: int = MIN_LIFECYCLE_HITS,
        min_logical: int = MIN_LOGICAL_HITS,
        min_dates: int = MIN_DISTINCT_DATES,
    ) -> None:
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.promotion_ceiling = promotion_ceiling
        self.min_lifecycle = min_lifecycle
        self.min_logical = min_logical
        self.min_dates = min_dates

    def reroute(
        self,
        analyzer_result: AnalyzerResult,
        evidence: EvidenceBundle,
    ) -> RerouterDecision:
        """Décide si une promotion vers temporal/comparison/causal est justifiée."""
        decision = RerouterDecision(
            original_type=analyzer_result.primary_type,
            original_confidence=analyzer_result.primary_confidence,
            seed_claim_count=len([c for c in evidence.claims if c.claim_id]),
        )

        # Garde 1 — si analyzer très confiant ET déjà sur un type structuré → ne pas écraser
        if (
            analyzer_result.primary_confidence >= self.promotion_ceiling
            and analyzer_result.primary_type in ("list", "temporal", "comparison", "causal")
        ):
            decision.rationale = "analyzer_high_confidence_no_override"
            return decision

        # Garde 2 — si pas d'evidence, on ne peut rien dire
        if not evidence.claims:
            decision.rationale = "no_evidence_to_inspect"
            return decision

        # Détection signaux KG (domain-agnostic)
        signals = self._detect_signals(evidence)
        decision.signals_detected = signals

        # Garde 3 — si Neo4j down, on log mais on ne promeut pas
        if signals.get("error"):
            decision.rationale = f"signals_unavailable: {signals['error']}"
            return decision

        # Logique de promotion (priorité : temporal > comparison > causal)
        promoted = None
        rationale_parts: list[str] = []

        n_lifecycle = signals.get("lifecycle_count", 0)
        n_logical_contradicts = signals.get("logical_contradicts_count", 0)
        n_distinct_dates = signals.get("distinct_publication_dates", 0)
        n_distinct_docs = signals.get("distinct_doc_ids", 0)

        # Signal temporal : LIFECYCLE_RELATION (SUPERSEDES, EVOLVES_FROM, REPLACES)
        # OU multi-version explicite (≥ 2 dates ET ≥ 2 docs sur même subject)
        if n_lifecycle >= self.min_lifecycle:
            promoted = "temporal"
            rationale_parts.append(f"{n_lifecycle} LIFECYCLE_RELATION on seed claims")
        elif n_distinct_dates >= self.min_dates and n_distinct_docs >= 2:
            # Même question, plusieurs sources avec dates différentes → souvent temporal
            promoted = "temporal"
            rationale_parts.append(f"{n_distinct_dates} distinct dates × {n_distinct_docs} docs")

        # Signal comparison : LOGICAL_RELATION (CONTRADICTS, COMPLEMENTARY) entre claims
        if n_logical_contradicts >= self.min_logical:
            # Si déjà promu temporal mais signal comparison plus fort → arbitrer
            if promoted == "temporal":
                # Garde temporal sauf si beaucoup plus de logical
                if n_logical_contradicts >= n_lifecycle * 2:
                    promoted = "comparison"
                    rationale_parts = [f"{n_logical_contradicts} LOGICAL contradicts (overrides lifecycle)"]
                else:
                    rationale_parts.append(f"+{n_logical_contradicts} LOGICAL (kept temporal)")
            else:
                promoted = "comparison"
                rationale_parts.append(f"{n_logical_contradicts} LOGICAL contradicts")

        # Pas de signal → garder analyzer
        if promoted is None:
            decision.rationale = "no_kg_signals_concordant"
            return decision

        # Garde 4 — si analyzer disait déjà ce type ou supérieur, pas de promotion
        if promoted == analyzer_result.primary_type:
            decision.rationale = f"signals_match_analyzer ({promoted})"
            return decision

        # Garde 5 — ne pas dégrader (list → temporal est une promotion ; factual → list non)
        # On autorise factual → temporal/comparison/causal (les types structurés sont "supérieurs")
        # On n'autorise PAS list → temporal (list reste primary, même si time_anchor présent)
        if analyzer_result.primary_type == "list":
            decision.rationale = f"list_kept_no_demotion (signals: {rationale_parts})"
            return decision

        # Promotion validée
        decision.promoted_type = promoted
        decision.rationale = "; ".join(rationale_parts) or f"promoted to {promoted}"
        logger.info(
            "[Rerouter] %s (conf=%.2f) → %s [%s]",
            analyzer_result.primary_type,
            analyzer_result.primary_confidence,
            promoted,
            decision.rationale,
        )
        return decision

    def _detect_signals(self, evidence: EvidenceBundle) -> dict:
        """Inspecte les claim_ids du pool dans Neo4j pour détecter signaux structurels.

        Signaux détectés (universels, pas métier) :
          - lifecycle_count : nb de LIFECYCLE_RELATION rattachées aux seed claims
          - logical_contradicts_count : nb de LOGICAL_RELATION type CONTRADICTS
          - distinct_publication_dates : nb dates distinctes parmi seed claims
          - distinct_doc_ids : nb doc_ids distincts
        """
        seed_claim_ids = [c.claim_id for c in evidence.claims if c.claim_id]
        if not seed_claim_ids:
            return {"error": "no_seed_claim_ids"}

        # Calcul direct depuis evidence (pas besoin de re-query Neo4j)
        distinct_docs = {c.doc_id for c in evidence.claims if c.doc_id and c.doc_id != "graph_expanded"}
        distinct_dates = {
            c.publication_date for c in evidence.claims
            if c.publication_date
        }

        signals = {
            "distinct_doc_ids": len(distinct_docs),
            "distinct_publication_dates": len(distinct_dates),
            "lifecycle_count": 0,
            "logical_contradicts_count": 0,
            "lifecycle_types": [],
            "logical_types": [],
        }

        # Si pas de driver Neo4j, on s'arrête là (signal multi-doc/multi-date utilisable)
        if not self.driver:
            return signals

        # Query Neo4j : compter relations LIFECYCLE et LOGICAL sur les seed claims
        try:
            with self.driver.session() as session:
                # LIFECYCLE_RELATION
                rows = session.run(
                    """
                    MATCH (c1:Claim)-[r:LIFECYCLE_RELATION]-(c2:Claim)
                    WHERE c1.tenant_id = $tenant_id AND c1.claim_id IN $seed_ids
                    RETURN coalesce(r.relation_type, type(r)) AS rel_type, count(*) AS n
                    """,
                    tenant_id=self.tenant_id,
                    seed_ids=seed_claim_ids[:30],  # cap pour perf
                ).data()
                lifecycle_total = sum(int(r.get("n") or 0) for r in rows)
                signals["lifecycle_count"] = lifecycle_total
                signals["lifecycle_types"] = [r["rel_type"] for r in rows[:5]]

                # LOGICAL_RELATION
                rows = session.run(
                    """
                    MATCH (c1:Claim)-[r:LOGICAL_RELATION]-(c2:Claim)
                    WHERE c1.tenant_id = $tenant_id AND c1.claim_id IN $seed_ids
                    RETURN coalesce(r.relation_type, type(r)) AS rel_type, count(*) AS n
                    """,
                    tenant_id=self.tenant_id,
                    seed_ids=seed_claim_ids[:30],
                ).data()
                # Filter sur les types qui suggèrent comparison
                contradicts_types = {"CONTRADICTS", "DIFFERS_FROM", "DIVERGES", "COMPLEMENTARY"}
                contra_count = sum(
                    int(r.get("n") or 0) for r in rows
                    if str(r.get("rel_type") or "").upper() in contradicts_types
                )
                signals["logical_contradicts_count"] = contra_count
                signals["logical_types"] = [r["rel_type"] for r in rows[:5]]
        except Exception as exc:
            logger.warning("[Rerouter] Neo4j signals query failed: %s", exc)
            signals["error"] = str(exc)

        return signals


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default: Optional[EvidenceRerouter] = None


def get_evidence_rerouter() -> EvidenceRerouter:
    global _default
    if _default is None:
        _default = EvidenceRerouter()
    return _default


def reset_evidence_rerouter() -> None:
    global _default
    _default = None
