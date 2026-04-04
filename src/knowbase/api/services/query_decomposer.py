"""
Query Decomposer — Decompose les questions multi-facettes en sous-queries.

Les questions larges ("Vue complete de X : aspects A, B, C") produisent un seul
embedding qui pointe vers un cluster de chunks. Les aspects secondaires sont perdus.

Ce module detecte les questions multi-facettes et les decompose en sous-queries
independantes pour ameliorer la couverture du retrieval.

Utilise GPT-4o-mini ou Haiku (selon OSMOSIS_SYNTHESIS_PROVIDER) pour la decomposition.
Fallback : pas de decomposition (question originale seule).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("query-decomposer")

# Seuil de longueur minimum pour tenter la decomposition
MIN_QUERY_LENGTH = 60
# Nombre max de sous-queries
MAX_SUB_QUERIES = 4


@dataclass
class QueryDecomposition:
    """Resultat de la decomposition d'une question."""
    original_query: str
    sub_queries: list[str]
    is_decomposed: bool = False
    reasoning: str = ""


def _is_multi_facet_candidate(query: str) -> bool:
    """Heuristique rapide : la question est-elle probablement multi-facettes ?

    Detecte les patterns courants sans appel LLM :
    - Enumerations explicites (virgules, "et", listes)
    - Mots-cles de couverture ("couvrez", "incluez", "comparez", "vue complete")
    - Questions longues avec plusieurs aspects
    """
    query_lower = query.lower()

    if len(query) < MIN_QUERY_LENGTH:
        return False

    # Patterns de couverture multi-facettes
    coverage_patterns = [
        "couvrez", "incluez", "incluant", "vue complète", "vue complete",
        "périmètre", "perimetre", "comparez", "comparaison",
        "les aspects", "les dimensions", "fonctionnalités",
        "cover", "including", "compare", "comprehensive", "complete view",
        "overview", "all aspects",
    ]
    if any(p in query_lower for p in coverage_patterns):
        return True

    # Enumerations : 3+ virgules ou 2+ "et"/"and"
    comma_count = query.count(",")
    if comma_count >= 2:
        return True

    # Question avec "?" et structure longue (>120 chars)
    if len(query) > 120 and "?" in query:
        return True

    return False


def decompose_query(query: str) -> QueryDecomposition:
    """Decompose une question multi-facettes en sous-queries.

    Si la question n'est pas multi-facettes ou si le LLM est indisponible,
    retourne la question originale seule (pas de decomposition).
    """
    result = QueryDecomposition(original_query=query, sub_queries=[query])

    if not _is_multi_facet_candidate(query):
        return result

    provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")

    try:
        if provider == "openai":
            sub_queries = _decompose_openai(query)
        else:
            sub_queries = _decompose_anthropic(query)

        if sub_queries and len(sub_queries) > 1:
            result.sub_queries = [query] + sub_queries[:MAX_SUB_QUERIES]
            result.is_decomposed = True
            result.reasoning = f"Decomposed into {len(sub_queries)} sub-queries"
            logger.info(
                f"[DECOMPOSE] Query decomposed into {len(sub_queries)} sub-queries: "
                f"{[sq[:60] for sq in sub_queries]}"
            )
        else:
            logger.debug("[DECOMPOSE] LLM returned no decomposition — single query")

    except Exception as e:
        logger.warning(f"[DECOMPOSE] Decomposition failed (non-blocking): {e}")

    return result


def _decompose_openai(query: str) -> list[str]:
    """Decomposition via GPT-4o-mini."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=200,
        temperature=0.0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
    )
    return _parse_response(resp.choices[0].message.content)


def _decompose_anthropic(query: str) -> list[str]:
    """Decomposition via Haiku."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        temperature=0.0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
    )
    return _parse_response(resp.content[0].text)


def _parse_response(raw: str) -> list[str]:
    """Parse la reponse du LLM : JSON array de strings."""
    raw = raw.strip()
    # Extraire le JSON si entoure de markdown
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    try:
        queries = json.loads(raw)
        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            # Filtrer les queries vides ou trop courtes
            return [q.strip() for q in queries if len(q.strip()) > 10]
    except json.JSONDecodeError:
        pass

    # Fallback : split par lignes numerotees
    lines = []
    for line in raw.split("\n"):
        line = line.strip().lstrip("0123456789.-) ")
        if len(line) > 10:
            lines.append(line)
    return lines if len(lines) > 1 else []


_SYSTEM_PROMPT = """You are a query decomposer for a document retrieval system.

Given a complex multi-faceted question, break it down into 2-4 focused sub-questions.
Each sub-question should target ONE specific aspect that can be answered independently.

Rules:
- Keep the main subject/entity in each sub-question (e.g., "SAP S/4HANA", "SAP EWM")
- Each sub-question should be self-contained and searchable
- Use the SAME LANGUAGE as the input question
- Return ONLY a JSON array of strings, nothing else
- If the question is already focused on a single aspect, return an empty array []

Example input: "Quelles sont les fonctionnalités de SAP EWM, son intégration avec S/4HANA, et les aspects sécurité ?"
Example output: ["Quelles sont les fonctionnalités principales de SAP EWM ?", "Comment SAP EWM s'intègre-t-il avec SAP S/4HANA ?", "Quels sont les aspects sécurité de SAP EWM ?"]

Example input: "What is TLS 1.3 in SAP?"
Example output: []"""
