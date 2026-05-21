"""V5.1 Voie A — Multi-formulation query (pattern EKX P1).

⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

Ce module sera supprimé une fois :
- Bench A3.8 validé (gates GA3-5/6/7 atteints)
- Phase B cross-domain validée
- V5.1 retiré comme endpoint de référence

Remplacé par : décomposition `sub_goals` du module Parse (runtime_a3/parse.py).

⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/.

---

Génère N reformulations alternatives d'une question utilisateur pour
maximiser la couverture du retrieval (entity expansion, synonymes,
langue cible).

Le pattern est PASSIF : on injecte les reformulations dans le user_prompt,
l'agent ReadingAgent V5.1 décide librement de s'en servir comme paramètres
de `find_in()` pour explorer davantage.

Charte respectée :
- Universel (pas de vocabulaire SAP spécifique)
- Aucune liste corpus-spécifique
- Le LLM décide des reformulations en se basant uniquement sur la question

Toggle : env var V5_MULTIFORM_ENABLED=1 active la feature.
"""
from __future__ import annotations

import logging
import os
import re
import time
from functools import lru_cache
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Warning DEPRECATED (A3.6, 2026-05-21) — émis une fois par import
if not globals().get("_DEPRECATED_WARNED", False):
    logger.warning(
        "⚠️ DEPRECATED module loaded: runtime_v5.query_reformulator. "
        "Replaced by runtime_a3 Parse sub_goals. Removal scheduled post-A3.8. "
        "See doc/ongoing/POST_A36_V51_SUPPRESSIONS_AUDIT_2026-05-21.md"
    )
    _DEPRECATED_WARNED = True

# ─── Config ──────────────────────────────────────────────────────────────────

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
MODEL = os.getenv("V5_REFORMULATOR_MODEL", "deepseek-ai/DeepSeek-V3.1")
N_REFORMULATIONS = int(os.getenv("V5_MULTIFORM_N", "5"))
TIMEOUT_S = float(os.getenv("V5_MULTIFORM_TIMEOUT_S", "20"))


def _endpoint_key() -> tuple[str, str]:
    if TOGETHER_KEY:
        return ("https://api.together.xyz/v1/chat/completions", TOGETHER_KEY)
    return ("https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY)


SYSTEM_PROMPT = (
    "You are a query reformulation expert. Given a question, you produce "
    "alternative phrasings that preserve the original intent but use different "
    "vocabulary, structure, or language. These alternatives are used as additional "
    "search queries to increase recall in a document retrieval system.\n\n"
    "RULES:\n"
    "- Generate exactly N alternative phrasings, one per line.\n"
    "- Mix languages : include at least 1 phrasing in English AND 1 in French "
    "(if the original is FR, add EN variants; if EN, add FR variants).\n"
    "- Use varied vocabulary : synonyms, technical aliases, acronyms expanded "
    "or abbreviated, related concepts.\n"
    "- Each phrasing must be a complete, well-formed question or query.\n"
    "- Do NOT add explanations, numbering, bullets, or markdown.\n"
    "- Output ONLY the N lines, no preamble, no commentary."
)


def _build_user_prompt(question: str, n: int) -> str:
    return f"Original question:\n{question}\n\nGenerate {n} alternative phrasings (one per line):"


def _parse_reformulations(content: str, n_expected: int) -> list[str]:
    """Parse l'output LLM : 1 reformulation par ligne, drop bullets/numbers."""
    lines = [ln.strip() for ln in (content or "").split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln:
            continue
        # Strip leading bullet/number
        ln = re.sub(r"^[\-\*•‣◦⁃∙]?\s*", "", ln)
        ln = re.sub(r"^\d+[.\)]\s+", "", ln)
        ln = ln.strip().strip('"').strip("'")
        if ln and len(ln) > 5:
            out.append(ln)
    # Cap at n_expected (LLM may over-generate)
    return out[:n_expected]


_REFORM_CACHE: dict[str, list[str]] = {}


async def reformulate_async(
    question: str,
    n: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Génère N reformulations de la question via LLM rapide.

    Returns:
        list[str] : N reformulations (peut être [] si erreur LLM)
    """
    if not question or not question.strip():
        return []
    n = n if n is not None else N_REFORMULATIONS

    cache_key = f"{n}::{question.strip().lower()[:200]}"
    if cache_key in _REFORM_CACHE:
        return _REFORM_CACHE[cache_key]

    endpoint, key = _endpoint_key()
    if not key:
        logger.warning("[V51_multiform] no API key available")
        return []

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(question, n)},
        ],
        "temperature": 0.3,  # un peu de diversité dans les variantes
        "max_tokens": 600,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        t0 = time.time()
        resp = await client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        reformulations = _parse_reformulations(content, n)
        logger.info(
            "[V51_multiform] generated %d reformulations in %.1fs (cache miss)",
            len(reformulations), time.time() - t0,
        )
        _REFORM_CACHE[cache_key] = reformulations
        return reformulations
    except Exception as exc:
        logger.warning("[V51_multiform] reformulation failed: %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()


def reformulate(question: str, n: Optional[int] = None) -> list[str]:
    """Sync wrapper. Use only outside async context."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # Already inside event loop : caller must use reformulate_async directly
        raise RuntimeError("reformulate() called from async context — use reformulate_async()")
    except RuntimeError:
        # No running loop : safe to use asyncio.run
        return asyncio.run(reformulate_async(question, n))


def format_reformulations_block(reformulations: list[str]) -> str:
    """Format le block à injecter dans le user_prompt.

    Vide si liste vide. Sinon block clair pour l'agent.
    """
    if not reformulations:
        return ""
    lines = [f"  - {r}" for r in reformulations]
    return (
        "Alternative phrasings (use these as additional `find_in()` queries if helpful "
        "to broaden recall):\n" + "\n".join(lines)
    )


def is_enabled() -> bool:
    return os.getenv("V5_MULTIFORM_ENABLED", "0").lower() in ("1", "true", "yes")
