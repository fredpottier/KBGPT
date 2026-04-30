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
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json={
                        "model": self.model_id,
                        "messages": [
                            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                return content or _fallback_response(claims)
        except (httpx.HTTPError, KeyError, IndexError) as exc:
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
