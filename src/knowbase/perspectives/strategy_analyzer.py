# src/knowbase/perspectives/strategy_analyzer.py
"""
Analyseur de strategie de restitution (direct vs structured).

Principe (voie 5, valide par 3 rounds ChatGPT) :
- Les Perspectives sont consultees systematiquement des qu'un sujet est resolu.
- Un LLM informe prend la decision de restitution a partir :
  * de la question (forme rhetorique)
  * d'un resume structurel des preuves deja recuperees
- Le LLM ne voit JAMAIS du contenu textuel (claims bruts, chunks).
- Il ne voit QUE des metriques structurelles et topologiques.
- `direct` est le safe default ; `structured` necessite un signal clair.

AUCUNE heuristique lexicale, AUCUNE liste de mots, AUCUN pattern domaine.
Domain-agnostic et multilingue par construction.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import ScoredPerspective

logger = logging.getLogger(__name__)


# ============================================================================
# Resultat de l'analyse
# ============================================================================

@dataclass
class StrategyDecision:
    """Decision de strategie de restitution."""

    strategy: str  # "direct" | "structured"
    confidence: str  # "high" | "medium" | "low"
    reasoning: str

    # Metadonnees de cout et trace
    llm_latency_ms: int = 0
    summary_size_chars: int = 0
    downgraded: bool = False  # True si on a force direct malgre structured
    veto_reason: Optional[str] = None  # Raison du veto minimal si applicable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "llm_latency_ms": self.llm_latency_ms,
            "summary_size_chars": self.summary_size_chars,
            "downgraded": self.downgraded,
            "veto_reason": self.veto_reason,
        }


# ============================================================================
# Evidence summary (strictement structurel)
# ============================================================================

def build_evidence_summary(
    question: str,
    kg_claims: List[Dict],
    reranked_chunks: List[Dict],
    scored_perspectives: List[ScoredPerspective],
    subject_ids: List[str],
    subject_resolution_mode: str,
    include_derived_hints: bool = True,
) -> Dict[str, Any]:
    """
    Construit un resume strictement structurel de la topologie des preuves.

    Principes :
    - Aucun contenu textuel de claim ou chunk.
    - Uniquement des metriques numeriques et des identifiants structurels.
    - Les labels de Perspectives sont isoles dans `derived_hints` (signal derive,
      pas preuve brute) et peuvent etre desactives via `include_derived_hints`.

    Args:
        question: Question utilisateur (copiee telle quelle, pas analysee)
        kg_claims: Claims KG recuperes en Phase A
        reranked_chunks: Chunks apres reranking
        scored_perspectives: Perspectives deja chargees et scorees
        subject_ids: IDs des sujets resolus
        subject_resolution_mode: "single" | "multi" | "fallback"
        include_derived_hints: Si True, inclut les labels de Perspectives

    Returns:
        Dict structurel (serialisable JSON) a passer au LLM decisionnel.
    """
    # ── Retrieval topology ──────────────────────────────────────────
    distinct_docs = set()
    scores = []
    for chunk in (reranked_chunks or []):
        doc_id = chunk.get("doc_id") or chunk.get("source_file", "")
        if doc_id:
            distinct_docs.add(doc_id)
        score = chunk.get("score", 0) or chunk.get("_dense_score", 0)
        if score:
            scores.append(float(score))

    scores.sort(reverse=True)
    top_score = scores[0] if scores else 0.0
    top_gap = (scores[0] - scores[1]) if len(scores) >= 2 else 0.0

    # Dispersion des scores : si les top scores sont proches (gap relatif < 20%),
    # c'est dispersed. Sinon concentrated.
    if top_score > 0 and scores:
        relative_gap = top_gap / top_score if top_score > 0 else 0
        concentration = "concentrated" if relative_gap > 0.2 else "dispersed"
    else:
        concentration = "unknown"

    retrieval_topology = {
        "n_chunks": len(reranked_chunks or []),
        "n_distinct_docs": len(distinct_docs),
        "top_score": round(top_score, 3),
        "top_gap": round(top_gap, 3),
        "score_concentration": concentration,
    }

    # ── Subjects topology ───────────────────────────────────────────
    subjects_topology = {
        "resolved_count": len(subject_ids),
        "resolution_mode": subject_resolution_mode,  # single|multi|fallback
    }

    # ── Perspectives topology ───────────────────────────────────────
    perspectives_topology: Dict[str, Any] = {
        "loaded_count": len(scored_perspectives),
    }

    if scored_perspectives:
        semantic_scores = [sp.semantic_score for sp in scored_perspectives]
        semantic_scores.sort(reverse=True)
        top_scores = semantic_scores[:5]

        mean_score = sum(semantic_scores) / len(semantic_scores)
        scored_above_mean = sum(1 for s in semantic_scores if s > mean_score)

        dominance_gap = (
            semantic_scores[0] - semantic_scores[1]
            if len(semantic_scores) >= 2 else 0.0
        )

        coverage_cumulative = sum(
            sp.perspective.coverage_ratio for sp in scored_perspectives[:5]
        )

        perspectives_topology.update({
            "top_semantic_scores": [round(s, 3) for s in top_scores],
            "scored_above_mean": scored_above_mean,
            "dominance_gap": round(dominance_gap, 3),
            "coverage_cumulative": round(coverage_cumulative, 2),
        })

    summary: Dict[str, Any] = {
        "question": question,
        "retrieval_topology": retrieval_topology,
        "subjects_topology": subjects_topology,
        "perspectives_topology": perspectives_topology,
    }

    # ── Derived hints (isoles, desactivables) ───────────────────────
    if include_derived_hints and scored_perspectives:
        top_labels = [
            sp.perspective.label
            for sp in scored_perspectives[:5]
            if sp.perspective.label
        ]
        if top_labels:
            summary["derived_hints"] = {
                "top_perspective_labels": top_labels,
                "note": "Labels are LLM-generated thematic interpretations from the corpus, not raw evidence.",
            }

    return summary


# ============================================================================
# Veto minimal cote code (garde-fou integrite)
# ============================================================================

def _check_minimal_veto(
    summary: Dict[str, Any],
    scored_perspectives: List[ScoredPerspective],
) -> Optional[str]:
    """
    Veto structurel minimal : meme si le LLM dit "structured",
    le code refuse dans certains cas ou la matiere est objectivement insuffisante.

    Returns:
        Raison du veto si applicable, None sinon.
    """
    # Pas assez de Perspectives scorees
    if len(scored_perspectives) < 2:
        return f"too_few_perspectives_loaded ({len(scored_perspectives)})"

    # Resolution sujet en fallback
    if summary.get("subjects_topology", {}).get("resolution_mode") == "fallback":
        return "subject_resolution_failed"

    # Zero sujet resolu
    if summary.get("subjects_topology", {}).get("resolved_count", 0) == 0:
        return "no_subject_resolved"

    return None


# ============================================================================
# LLM decisionnel
# ============================================================================

STRATEGY_PROMPT = """You decide between two response strategies for a user question:

- "direct": atomic answer based on retrieved chunks alone (RAG default, safe)
- "structured": answer organized by multiple thematic axes (Perspectives injected)

CORE PRINCIPLE: prefer "direct" by default. Only choose "structured" when the
question CLEARLY asks for a synthesis across multiple distinct dimensions of a
broad topic. The evidence topology is a secondary signal — the primary signal
is the question's rhetorical scope.

DIRECT — choose this when the question asks for:
- A specific value, threshold, version, name, identifier, or code
- A yes/no answer
- The definition or function of a single component, tool, report, or concept
- "What does X do?" / "What is X for?" / "What is X?" — even if X is broad
- A single fact, even if it requires combining a few sources to reconstruct
- An identification or lookup ("which X handles Y?")
- A procedure or "how to use X" for a single component

STRUCTURED — choose this ONLY when the question asks for:
- An overview/summary of an entire broad topic ("overview of X", "what does X bring", "key points of X")
- A comparison between multiple aspects, versions, or approaches
- An impact analysis touching multiple distinct dimensions
- The "main aspects/dimensions/concerns" of a broad topic
- A panoramic exploration that explicitly covers multiple angles

KEY DISCRIMINATOR: a question about a single component/tool/concept is DIRECT
even if the evidence is dispersed. Dispersion alone does not justify structuring
— it may just mean the corpus stores the information across multiple files.

QUESTION:
{question}

EVIDENCE SUMMARY (structural topology only, no raw content):
{evidence_summary_json}

Respond in strict JSON only (no surrounding text, no markdown, no explanation outside JSON):
{{
  "strategy": "direct" | "structured",
  "confidence": "high" | "medium" | "low",
  "reasoning": "one sentence citing primarily the question's scope"
}}

IMPORTANT:
- Default to "direct". Only choose "structured" if the question explicitly seeks multi-dimensional synthesis.
- A question asking "what does X do" or "what is X for" is ALWAYS direct, regardless of evidence dispersion.
- Your answer must be valid JSON, nothing else."""


async def analyze_response_strategy(
    question: str,
    kg_claims: List[Dict],
    reranked_chunks: List[Dict],
    scored_perspectives: List[ScoredPerspective],
    subject_ids: List[str],
    subject_resolution_mode: str,
) -> StrategyDecision:
    """
    Analyse informee de la strategie de restitution.

    Le LLM recoit :
    - la question (forme rhetorique)
    - un resume structurel des preuves (topologie, pas contenu)

    Retourne une decision avec confidence et reasoning.

    Le code applique ensuite :
    - un veto minimal si la matiere est objectivement insuffisante
    - un downgrade "low confidence structured" -> "direct" (safe default)
    """
    start = time.time()

    # 1. Construire le summary structurel
    summary = build_evidence_summary(
        question=question,
        kg_claims=kg_claims,
        reranked_chunks=reranked_chunks,
        scored_perspectives=scored_perspectives,
        subject_ids=subject_ids,
        subject_resolution_mode=subject_resolution_mode,
    )
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2)
    summary_size = len(summary_json)

    # 2. Veto minimal pre-LLM (economie d'appel si materiel insuffisant)
    veto = _check_minimal_veto(summary, scored_perspectives)
    if veto:
        logger.info(f"[PERSPECTIVE:VETO] Pre-LLM veto: {veto}")
        return StrategyDecision(
            strategy="direct",
            confidence="high",
            reasoning=f"Veto: {veto}",
            llm_latency_ms=0,
            summary_size_chars=summary_size,
            downgraded=False,
            veto_reason=veto,
        )

    # 3. Appel LLM decisionnel
    # On utilise Haiku directement (comme verification_service / synthesis)
    # car cette decision necessite un raisonnement nuance que Qwen local
    # ne fournit pas avec assez de fiabilite (observe empiriquement).
    prompt = STRATEGY_PROMPT.format(
        question=question,
        evidence_summary_json=summary_json,
    )

    response = ""
    llm_latency_ms = 0
    try:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            haiku_model = os.environ.get(
                "OSMOSIS_SYNTHESIS_MODEL", "claude-haiku-4-5-20251001"
            )
            llm_start = time.time()
            api_response = client.messages.create(
                model=haiku_model,
                max_tokens=300,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            response = api_response.content[0].text if api_response.content else ""
            llm_latency_ms = int((time.time() - llm_start) * 1000)
        else:
            # Fallback : llm_router (Qwen local) si pas de cle Anthropic
            from knowbase.common.llm_router import get_llm_router, TaskType
            router = get_llm_router()
            llm_start = time.time()
            response = await router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )
            llm_latency_ms = int((time.time() - llm_start) * 1000)
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:STRATEGY] LLM call failed: {e}")
        return StrategyDecision(
            strategy="direct",
            confidence="high",
            reasoning=f"LLM call failed: {e}",
            llm_latency_ms=0,
            summary_size_chars=summary_size,
            downgraded=False,
            veto_reason="llm_error",
        )

    # 4. Parser le JSON strict
    decision_data = _parse_strategy_response(response)
    if not decision_data:
        logger.warning(f"[PERSPECTIVE:STRATEGY] Failed to parse LLM response: {response[:200]}")
        return StrategyDecision(
            strategy="direct",
            confidence="high",
            reasoning="LLM response parsing failed",
            llm_latency_ms=llm_latency_ms,
            summary_size_chars=summary_size,
            downgraded=False,
            veto_reason="parse_error",
        )

    raw_strategy = decision_data.get("strategy", "direct")
    confidence = decision_data.get("confidence", "low")
    reasoning = decision_data.get("reasoning", "")[:300]

    # 5. Veto post-LLM : downgrade low-confidence structured -> direct
    final_strategy = raw_strategy
    downgraded = False
    if raw_strategy == "structured" and confidence == "low":
        final_strategy = "direct"
        downgraded = True
        logger.info(
            "[PERSPECTIVE:STRATEGY] Downgraded low-confidence structured -> direct"
        )

    # 6. Veto minimal post-LLM (si structured mais conditions plancher non remplies)
    if final_strategy == "structured":
        veto = _check_minimal_veto(summary, scored_perspectives)
        if veto:
            final_strategy = "direct"
            logger.info(f"[PERSPECTIVE:VETO] Post-LLM veto: {veto}")
            return StrategyDecision(
                strategy="direct",
                confidence=confidence,
                reasoning=f"LLM said structured but veto: {veto}",
                llm_latency_ms=llm_latency_ms,
                summary_size_chars=summary_size,
                downgraded=True,
                veto_reason=veto,
            )

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        f"[PERSPECTIVE:STRATEGY] strategy={final_strategy} confidence={confidence} "
        f"llm_ms={llm_latency_ms} total_ms={total_ms} downgraded={downgraded} "
        f"reasoning=\"{reasoning[:120]}\""
    )

    return StrategyDecision(
        strategy=final_strategy,
        confidence=confidence,
        reasoning=reasoning,
        llm_latency_ms=llm_latency_ms,
        summary_size_chars=summary_size,
        downgraded=downgraded,
        veto_reason=None,
    )


def _parse_strategy_response(response: str) -> Optional[Dict[str, Any]]:
    """Parse la reponse JSON du LLM decisionnel."""
    if not response:
        return None

    # Tenter parsing direct
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # Tenter extraction du premier bloc JSON
    json_match = re.search(r'\{[\s\S]*?\}', response)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

    return None
