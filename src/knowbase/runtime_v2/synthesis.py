"""
Synthèse LLM finale — V2-P2.1.

Transforme une liste de claims top-K + contexte en réponse en prose,
en langue de la question, citant les sources et signalant les conflicts
non résolus.

Domain-agnostic, evidence-locked (le LLM doit citer les claim_ids fournis,
pas inventer).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


SYNTHESIS_SYSTEM_PROMPT = """You are a documentary synthesis assistant. Given a user question and a list of evidence claims extracted from authoritative documents, produce a concise, accurate answer.

## Critical rules

1. **Answer in the SAME LANGUAGE as the question** (English/French/etc — detect automatically).

2. **Use ONLY the provided evidence claims**. Do not invent facts. If the claims do not contain the answer, say so explicitly: "The provided sources do not directly address this question."

3. **Cite the source documents** at the end of relevant sentences as [doc_id]. Multiple citations [doc_id_1; doc_id_2] are OK.

4. **Length: 2-4 sentences maximum** for normal questions. The user wants a clear answer, not a paraphrase of all the claims.

5. **If unresolved conflicts are flagged**, explicitly mention them at the end: "Note: the corpus contains conflicting statements on this point — see [docX] vs [docY]."

6. **For ambiguous questions where multiple authoritative sources cover the same scope**, summarize the consensus and flag the divergences.

7. **Tone: neutral, factual, no hedging** unless the evidence itself is hedged.

## Output format

Just the prose answer. No headers, no bullet points unless the answer is intrinsically a list (then keep it minimal). No commentary about your process."""


class ResponseSynthesizer:
    """LLM synthétiseur evidence-locked.

    Args:
        vllm_url: URL vLLM
        model_id: modèle
        timeout: timeout HTTP
    """

    def __init__(
        self,
        vllm_url: str,
        model_id: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 30.0,
        temperature: float = 0.2,
        max_tokens: int = 350,
    ) -> None:
        self.vllm_url = vllm_url.rstrip("/")
        self.model_id = model_id
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def synthesize(
        self,
        question: str,
        claims: list[dict],
        unresolved_conflicts: Optional[list[dict]] = None,
        max_claims_in_prompt: int = 8,
    ) -> str:
        """Génère une réponse prose 2-4 phrases.

        Args:
            question: question utilisateur
            claims: liste de {claim_id, doc_id, text, score}
            unresolved_conflicts: liste de {doc_a_id, doc_b_id, claim_a_id, claim_b_id} si applicable
            max_claims_in_prompt: borne supérieure de claims envoyés au LLM

        Returns:
            Réponse prose. Si LLM échoue, retombe sur "claim 1: ..." brute.
        """
        if not claims:
            return "Le corpus ne contient pas d'information directement applicable à cette question."

        used_claims = claims[:max_claims_in_prompt]
        evidence_block = "\n".join(
            f"[{i + 1}] doc={c.get('doc_id', 'unknown')} score={c.get('score', 0.0):.2f}\n    text: {c.get('text', '')[:500]}"
            for i, c in enumerate(used_claims)
        )

        conflicts_block = ""
        if unresolved_conflicts:
            conflicts_block = "\n\nUnresolved conflicts in the same scope:\n"
            for cf in unresolved_conflicts[:3]:
                conflicts_block += (
                    f"  - {cf.get('doc_a_id')} (claim {cf.get('claim_a_id', '?')[:20]}) "
                    f"vs {cf.get('doc_b_id')} (claim {cf.get('claim_b_id', '?')[:20]})\n"
                )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Evidence claims (use claim numbers [1] [2] ... for citation, but cite by doc_id):\n"
            f"{evidence_block}"
            f"{conflicts_block}\n\n"
            f"Now write the synthesized answer (2-4 sentences max):"
        )

        try:
            from knowbase.runtime_v2.llm_client import get_runtime_llm_client
            client = get_runtime_llm_client()
            content = client.chat_completion(
                messages=[
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=False,
                timeout=self.timeout,
            ).strip()
            return content or _fallback_response(claims)
        except Exception as exc:
            logger.error("Synthesis LLM call failed: %s", exc)
            return _fallback_response(claims)


def _fallback_response(claims: list[dict]) -> str:
    """Si LLM down → retourne le top claim brut (pas idéal mais préserve la mission primaire)."""
    if not claims:
        return "Aucune information disponible."
    top = claims[0]
    text = top.get("text", "")[:300]
    doc_id = top.get("doc_id", "unknown")
    return f"[Synthèse LLM indisponible — extrait brut depuis {doc_id}] {text}"


EVOLUTION_SYNTHESIS_PROMPT = """You are a documentary synthesis assistant for an evolution timeline. Given a user question asking how something evolved, and a chronological list of evidence claims grouped by document version/date, produce a concise narrative of the evolution.

## Critical rules

1. **Answer in the SAME LANGUAGE as the question**.

2. **Use ONLY the provided timeline points and their claims**. Do not invent facts.

3. **Highlight what CHANGED between timeline points** (new rules, removed obligations, modified thresholds, replaced entities). If two points contain identical info, note it as "remained unchanged".

4. **Cite the source documents** for each evolution step using [doc_id].

5. **Length: 3-6 sentences**. Structure narrative chronologique : "Initially [doc_old]... Then [doc_mid] introduced... Most recently [doc_new] established...".

6. **If the timeline points have very few claims or no clear changes**, say so honestly: "The timeline shows X versions but the available evidence does not detail specific changes between them."

## Output format

Just the prose narrative. No headers, no bullet points. No commentary about your process."""


class EvolutionSynthesizer:
    """LLM synthétiseur pour mode RANGE — narration chronologique multi-doc.

    Diffère du ResponseSynthesizer en input (timeline points par doc avec claims)
    et en sortie (narration des changements vs réponse factuelle ponctuelle).
    """

    def __init__(
        self,
        vllm_url: str,
        model_id: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 30.0,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> None:
        self.vllm_url = vllm_url.rstrip("/")
        self.model_id = model_id
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def synthesize(
        self,
        question: str,
        evolution_points: list[dict],
        max_points: int = 8,
    ) -> str:
        """Génère une narration prose de l'évolution.

        Args:
            question: question utilisateur
            evolution_points: liste de {doc_id, publication_date, claims: [{text}]}, triée chronologiquement
            max_points: borne supérieure de points envoyés au LLM
        """
        if not evolution_points:
            return "Aucune évolution détectable dans le corpus pour cette question."

        used = evolution_points[:max_points]
        timeline_block = "\n\n".join(
            f"[Point {i + 1}] doc={p.get('doc_id', '?')} date={p.get('publication_date') or '?'}\n"
            + "\n".join(
                f"  - {(c.get('text') or '')[:300]}"
                for c in (p.get("claims") or [])[:3]
            )
            for i, p in enumerate(used)
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Timeline (chronological):\n{timeline_block}\n\n"
            f"Now write a 3-6 sentence narrative of the evolution, citing each step by doc_id:"
        )

        try:
            from knowbase.runtime_v2.llm_client import get_runtime_llm_client
            client = get_runtime_llm_client()
            content = client.chat_completion(
                messages=[
                    {"role": "system", "content": EVOLUTION_SYNTHESIS_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=False,
                timeout=self.timeout,
            ).strip()
            if not content:
                return _evolution_fallback(used)
            return content
        except Exception as exc:
            logger.error(f"EvolutionSynthesizer LLM call failed: {exc}")
            return _evolution_fallback(used)


def _evolution_fallback(evolution_points: list[dict]) -> str:
    """Fallback chronologique brut si LLM down."""
    if not evolution_points:
        return "Aucune évolution disponible."
    parts = []
    for p in evolution_points[:5]:
        date = p.get("publication_date") or "?"
        doc = p.get("doc_id") or "unknown"
        n_claims = len(p.get("claims") or [])
        parts.append(f"{date} — {doc} ({n_claims} claims)")
    return "[Synthèse LLM indisponible — timeline brute]\n" + "\n".join(parts)
