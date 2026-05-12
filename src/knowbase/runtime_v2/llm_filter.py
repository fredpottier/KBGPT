"""
LLM Filter post-retrieval — CH-31.C + CH-35.A2.

Domain-agnostic relevance filter on retrieved claims, using a light sub-LLM
via RuntimeLLMClient (vLLM-first Qwen2.5-14B-AWQ, DeepInfra Qwen2.5-72B fallback).

Pas Prometheus — Prometheus est réservé au juge de benchmark uniquement.

Input  : question + answer_shape + must_contain + list of claims
Output : claims annotated with {relevance, keep_flag}, sorted by relevance desc,
         filtered with a min_keep guard pour éviter de tout supprimer.

CH-35.A2 — depuis l'analyse oracle injection :
- 70% des ABSTENTION_FAUX_NEG sont causés par le filtre rejetant les chunks corrects
- Sur les questions factuelles (factual_value, list, definition, boolean), le filtre
  doit être très permissif : meilleur de garder du bruit que de perdre le signal,
  car la synthèse a son propre jugement evidence-locked
- Toggle via env var `RUNTIME_V2_FILTER_BYPASS_FACTUAL=true` (default: true) → skip LLM
  entièrement sur ces shapes, retourne tous les claims tels quels

Strictement domain-agnostic : aucun vocabulaire métier, 7 answer_shapes génériques,
must_contain extrait depuis la question (par le decomposer V2, CH-31.B).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

FAST_MODEL = "mistralai/Mistral-Small-3.1-24B-Instruct-2503"

# CH-35.A2 — bypass complet du filtre LLM sur shapes factuels (default: true)
# La synthèse evidence-locked se charge de discriminer les claims.
# Inclut TOUS les shapes du decomposer V2 sauf "narrative" qui peut bénéficier
# d'un filtre de pertinence (réponses longues, plus de bruit utile à éliminer).
# Les 7 shapes : factual_value, definition, entity_lookup, relationship,
# enumeration, narrative, boolean.
BYPASS_FACTUAL_SHAPES = os.getenv("RUNTIME_V2_FILTER_BYPASS_FACTUAL", "true").lower() == "true"
FACTUAL_SHAPES = {
    "factual_value",      # valeur précise (date, chiffre)
    "definition",         # définition d'un terme
    "entity_lookup",      # identification d'une entité (ex: "qui a remplacé X ?")
    "boolean",            # oui/non
    "list",               # legacy
    "enumeration",        # listage d'éléments
    "relationship",       # relation entre 2 entités (X est-il abrogé par Y ?)
}


LLM_FILTER_SYSTEM = """You grade evidence claims for relevance to a user question.

Score each claim 0.0 to 1.0 :
- 0.8+ : claim directly answers the question (cites the value, defines the entity, states yes/no)
- 0.5-0.7 : claim is on-topic but not the exact answer (adjacent context, partial info)
- 0.0-0.4 : claim is off-topic or only mentions the keywords in passing

`must_contain` tokens are HINTS (not hard filter). Paraphrased claims with the right answer score high even without exact tokens. Be domain-agnostic.

Return STRICT JSON ONLY :
{"graded":[{"id":"<claim_id>","score":0.0,"keep":true,"reason":"short"}]}

Rules :
- keep=true if score >= 0.5, else false
- Grade EVERY claim. Use claim_id from the [bracketed_id] in the input.
- Keep "reason" under 12 words.
"""


def _build_user_prompt(
    question: str,
    claims: list[Any],
    answer_shape: str,
    must_contain: Optional[list[str]],
) -> str:
    """Prompt utilisateur compact pour Mistral-Small (CH-33).

    Tronque chaque claim à 350 chars (était 500) pour rester sous une fenêtre
    de contexte courte qui aide Mistral à produire un JSON stable.
    """
    block_lines = []
    for c in claims:
        cid = getattr(c, "claim_id", None) or ""
        text = (getattr(c, "text", None) or "")[:350]
        text = re.sub(r"\s+", " ", text).strip()
        block_lines.append(f"[{cid}] {text}")
    claim_block = "\n".join(block_lines) if block_lines else "(none)"
    must_block = ", ".join(must_contain or []) if must_contain else "(none)"
    return (
        f"QUESTION: {question}\n"
        f"ANSWER_SHAPE: {answer_shape}\n"
        f"MUST_CONTAIN: {must_block}\n\n"
        f"CLAIMS:\n{claim_block}\n\n"
        f"Return JSON now."
    )


def filter_claims(
    question: str,
    claims: list[Any],
    answer_shape: str = "narrative",
    must_contain: Optional[list[str]] = None,
    min_keep: int = 3,
    max_input_claims: int = 12,
    timeout: float = 60.0,
) -> dict:
    """Filter retrieved claims by LLM relevance grading.

    Args:
        question: original user question
        claims: list of EvidenceClaim-like objects (must have .claim_id, .text, .score)
        answer_shape: one of 7 generic answer shapes (CH-31.B)
        must_contain: optional list of tokens that the answer should cite
        min_keep: minimum claims to keep even if LLM says drop all (safety guard)
        max_input_claims: cap input to LLM for cost/latency control

    Returns:
        {
          "kept": [<claim>],          # ordered by LLM score desc
          "dropped": [<claim>],        # for diagnostic
          "grades": {<claim_id>: {"score", "keep", "reason"}},
          "llm_called": bool,
          "fallback_reason": str | None,
          "n_input": int,
          "n_kept": int,
          "n_dropped": int,
        }
    """
    n_in = len(claims)
    if n_in == 0:
        return {
            "kept": [],
            "dropped": [],
            "grades": {},
            "llm_called": False,
            "fallback_reason": "no_claims",
            "n_input": 0,
            "n_kept": 0,
            "n_dropped": 0,
        }

    # CH-35.A2 — bypass complet sur shapes factuels.
    # Évite que le filtre rejette le chunk-clé sur questions à valeur précise
    # (date, article, valeur numérique, oui/non). La synthèse evidence-locked
    # discrimine déjà avec son propre prompt.
    if BYPASS_FACTUAL_SHAPES and answer_shape in FACTUAL_SHAPES:
        logger.info(
            f"[LLM_FILTER] BYPASS factual shape={answer_shape} (n={n_in}) — passthrough"
        )
        return {
            "kept": list(claims),
            "dropped": [],
            "grades": {},
            "llm_called": False,
            "fallback_reason": f"bypass_factual_shape:{answer_shape}",
            "n_input": n_in,
            "n_kept": n_in,
            "n_dropped": 0,
        }

    # Skip uniquement quand le filtre n'a rien à filtrer :
    # ≤ 3 claims (déjà sous le min_keep) → passthrough.
    if n_in <= min_keep:
        return {
            "kept": list(claims),
            "dropped": [],
            "grades": {},
            "llm_called": False,
            "fallback_reason": "skip_below_min_keep",
            "n_input": n_in,
            "n_kept": n_in,
            "n_dropped": 0,
        }

    used = claims[:max_input_claims]
    user_prompt = _build_user_prompt(question, used, answer_shape, must_contain)

    grades: dict[str, dict] = {}
    llm_called = False
    fallback_reason: str | None = None
    try:
        from knowbase.runtime_v2.llm_client import get_runtime_llm_client
        client = get_runtime_llm_client()
        llm_called = True
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": LLM_FILTER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=500,
            json_mode=True,
            timeout=timeout,
            model_override=FAST_MODEL,
        )
        m = re.search(r"\{[\s\S]*\}", raw or "")
        data = json.loads(m.group()) if m else {}
        for g in data.get("graded", []) or []:
            cid = g.get("id")
            if not cid:
                continue
            try:
                score = float(g.get("score", 0.5))
            except Exception:
                score = 0.5
            score = max(0.0, min(1.0, score))
            keep = g.get("keep")
            if not isinstance(keep, bool):
                keep = score >= 0.5
            grades[str(cid)] = {
                "score": score,
                "keep": keep,
                "reason": str(g.get("reason", ""))[:200],
            }
    except Exception as e:
        logger.warning(f"[LLM_FILTER] LLM call failed: {e} — passthrough all claims")
        fallback_reason = f"llm_error:{type(e).__name__}"
        return {
            "kept": list(used),
            "dropped": [],
            "grades": {},
            "llm_called": llm_called,
            "fallback_reason": fallback_reason,
            "n_input": n_in,
            "n_kept": len(used),
            "n_dropped": 0,
        }

    # Apply grading + sort
    kept_with_score: list[tuple[float, Any]] = []
    dropped_with_score: list[tuple[float, Any]] = []
    for c in used:
        cid = str(getattr(c, "claim_id", None) or "")
        g = grades.get(cid)
        if g is None:
            # ungraded by LLM → neutral keep
            kept_with_score.append((0.5, c))
            continue
        if g["keep"]:
            kept_with_score.append((g["score"], c))
        else:
            dropped_with_score.append((g["score"], c))

    kept_with_score.sort(key=lambda t: t[0], reverse=True)
    dropped_with_score.sort(key=lambda t: t[0], reverse=True)

    # Min-keep safety guard : ne pas tout supprimer si LLM est trop strict
    if len(kept_with_score) < min_keep and dropped_with_score:
        deficit = min_keep - len(kept_with_score)
        for entry in dropped_with_score[:deficit]:
            kept_with_score.append(entry)
        dropped_with_score = dropped_with_score[deficit:]
        kept_with_score.sort(key=lambda t: t[0], reverse=True)
        if fallback_reason is None:
            fallback_reason = "min_keep_guard"

    kept_claims = [c for _, c in kept_with_score]
    dropped_claims = [c for _, c in dropped_with_score]

    logger.info(
        f"[LLM_FILTER] in={n_in} graded={len(grades)} "
        f"kept={len(kept_claims)} dropped={len(dropped_claims)} "
        f"shape={answer_shape} must_n={len(must_contain or [])}"
    )

    return {
        "kept": kept_claims,
        "dropped": dropped_claims,
        "grades": grades,
        "llm_called": llm_called,
        "fallback_reason": fallback_reason,
        "n_input": n_in,
        "n_kept": len(kept_claims),
        "n_dropped": len(dropped_claims),
    }
