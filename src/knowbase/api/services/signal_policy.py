"""
OSMOSIS Signal Policy — Transforme un SignalReport en instructions concretes.

Regles deterministes : signal → action.
Si aucun signal (silence) → passthrough = RAG pur, zero modification.

Le guard-rail Sprint 0 s'applique : max ~150 tokens de contexte KG injecte.
Au-dela, le LLM degrade (-8pp factual avec 144 tokens de bloc KG).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .kg_signal_detector import SignalReport

logger = logging.getLogger(__name__)

# Limite de tokens KG injectes dans le prompt (lecon Sprint 0 test v2)
MAX_KG_INJECTION_TOKENS = 150


@dataclass
class SignalPolicy:
    """Instructions concretes pour le pipeline, derivees des signaux KG."""

    # Chunk manipulation
    fetch_missing_tension_docs: bool = False
    tension_doc_ids: set[str] = field(default_factory=set)
    reorder_by_tensions: bool = False

    # Context injection (pour le prompt de synthese)
    inject_kg_enrichment: bool = False
    inject_kg_traversal: bool = False
    inject_qs_crossdoc: bool = False

    # Instructions supplementaires pour le prompt LLM
    synthesis_additions: list[str] = field(default_factory=list)

    # Negative rejection (question-context gap)
    unanswerable: bool = False
    unanswerable_reason: str = ""
    unanswerable_missing_terms: list[str] = field(default_factory=list)

    @property
    def is_passthrough(self) -> bool:
        """Si True, RAG pur sans aucune modification."""
        return not any([
            self.fetch_missing_tension_docs,
            self.reorder_by_tensions,
            self.inject_kg_enrichment,
            self.inject_kg_traversal,
            self.inject_qs_crossdoc,
            self.unanswerable,
        ])


def build_policy(report: SignalReport) -> SignalPolicy:
    """
    Construit une SignalPolicy a partir d'un SignalReport.

    Regles deterministes, zero appel externe.

    Hard constraint : si report.is_silent → passthrough (RAG pur).
    """
    if report.is_silent:
        logger.info("[POLICY] Passthrough — no signals, RAG pure")
        return SignalPolicy()

    policy = SignalPolicy()

    # Signal tension → chercher chunks des docs en tension + enrichir + reordonner
    tension = report.get_signal("tension")
    if tension:
        tension_doc_ids = tension.evidence.get("tension_doc_ids", set())
        policy.fetch_missing_tension_docs = bool(tension_doc_ids)
        policy.tension_doc_ids = tension_doc_ids if isinstance(tension_doc_ids, set) else set(tension_doc_ids)
        policy.reorder_by_tensions = True
        policy.inject_kg_enrichment = True
        policy.inject_kg_traversal = True
        policy.synthesis_additions.append(
            "IMPORTANT: Sources contain DIVERGENCES on this topic. "
            "Present BOTH positions with their sources. Do NOT silently pick one side."
        )

    # Signal evolution temporelle → activer le traversal pour les chains temporelles
    evolution = report.get_signal("temporal_evolution")
    if evolution:
        policy.inject_kg_traversal = True
        entity_names = list(evolution.evidence.get("multi_doc_entities", {}).keys())[:3]
        if entity_names:
            policy.synthesis_additions.append(
                f"NOTE: The topic '{', '.join(entity_names)}' appears across multiple document versions. "
                "Distinguish what was true in earlier versions vs what is current."
            )

    # Signal couverture → elargir le retrieval aux docs manquants
    coverage = report.get_signal("coverage_gap")
    if coverage:
        missing = coverage.evidence.get("missing_doc_ids", set())
        if missing:
            policy.fetch_missing_tension_docs = True  # reutilise le meme mecanisme
            policy.tension_doc_ids = policy.tension_doc_ids | (missing if isinstance(missing, set) else set(missing))

    # Signal exactitude → injecter les QS cross-doc
    exactness = report.get_signal("exactness")
    if exactness:
        policy.inject_qs_crossdoc = True
        matches = exactness.evidence.get("matches", [])
        if matches:
            first = matches[0]
            policy.synthesis_additions.append(
                f"A structured value is available: {first.get('canonical_question', '')} "
                f"= {first.get('extracted_value', '')} (source: {first.get('doc_id', '')}). "
                "Lead with this exact value in your answer."
            )

    # Signal 5 — Question-Context Gap (negative rejection)
    gap = report.get_signal("question_context_gap")
    if gap:
        gap_score = gap.evidence.get("gap_score", 0)
        max_chunk_score = gap.evidence.get("max_chunk_score", 0)
        missing_terms = gap.evidence.get("missing_terms", [])

        # Hard reject : gap total ET pas de signal exactness
        # (exactness = QD match precis, seul signal fiable de pertinence)
        has_exactness = report.has_signal("exactness")
        if gap_score >= 1.0 and not has_exactness:
            policy.unanswerable = True
            policy.unanswerable_reason = (
                f"Les termes specifiques de la question ({', '.join(missing_terms)}) "
                f"sont absents des documents disponibles."
            )
            policy.unanswerable_missing_terms = missing_terms
            logger.info(f"[POLICY] UNANSWERABLE — gap={gap_score:.2f}, max_score={max_chunk_score:.3f}")

        # Soft signal : gap eleve mais chunks proches → prevenir le LLM
        elif gap_score >= 0.6:
            policy.synthesis_additions.append(
                "NOTE: Some specific aspects of this question may not be covered by the available sources. "
                "Answer with what the sources contain, and clearly state if specific information is missing."
            )

    # Guard-rail : limiter le nombre d'instructions ajoutees
    if len(policy.synthesis_additions) > 3:
        policy.synthesis_additions = policy.synthesis_additions[:3]

    active = []
    if policy.fetch_missing_tension_docs:
        active.append("fetch_missing_docs")
    if policy.reorder_by_tensions:
        active.append("reorder_tensions")
    if policy.inject_kg_enrichment:
        active.append("kg_enrichment")
    if policy.inject_kg_traversal:
        active.append("kg_traversal")
    if policy.inject_qs_crossdoc:
        active.append("qs_crossdoc")

    logger.info(f"[POLICY] Active: {active}, additions: {len(policy.synthesis_additions)}")

    return policy
