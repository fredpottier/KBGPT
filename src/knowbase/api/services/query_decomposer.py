"""
Query Decomposer V2 — Decomposition structurelle pour questions complexes.

Deux modes de decomposition :
1. **Comparison/Cross-version** (nouveau) : detecte les questions de comparaison,
   enumeration, chronologie et decompose en sous-queries avec scope_filter
   (release_id, edition, etc.) pour ciblage pre-retrieval Qdrant.
2. **Multi-facettes** (V1 conserve) : questions larges avec plusieurs aspects
   independants, decomposees en sous-queries sans scope_filter.

Principe d'integrite : si une sous-query n'a pas de matiere dans le corpus
(0 chunks apres retrieval), le systeme ne synthetise pas une reponse partielle
mais propose une clarification interactive a l'utilisateur.

Usage depuis search.py :
    from .query_decomposer import try_decompose, QueryPlan
    plan = try_decompose(query, llm_func)
    if plan.plan_type != "simple":
        # ... structured retrieval per sub-query ...
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from knowbase.common.llm_router import get_llm_router, TaskType

logger = logging.getLogger("query-decomposer")

# ── Configuration ─────────────────────────────────────────────────────────────

MIN_QUERY_LENGTH = 40
MAX_SUB_QUERIES = 4

# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class SubQuery:
    """Sous-question avec scope_filter optionnel pour filtrage pre-retrieval."""
    id: str
    text: str
    scope_filter: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    # Rempli apres retrieval
    chunk_count: int = 0
    has_results: bool = True


@dataclass
class QueryPlan:
    """Plan de decomposition d'une question."""
    original_question: str
    plan_type: str = "simple"  # simple | comparison | enumeration | chronological | multi_facet
    sub_queries: list[SubQuery] = field(default_factory=list)
    synthesis_strategy: str = "simple"  # simple | compare | aggregate | chronological
    reasoning: str = ""
    is_decomposed: bool = False

    # Integrite : rempli apres retrieval si certaines sous-queries sont vides
    integrity_issue: str | None = None
    available_axes: dict[str, list[str]] | None = None


# ── V1 compat : ancien QueryDecomposition wrapper ────────────────────────────


@dataclass
class QueryDecomposition:
    """Wrapper retro-compatible avec la V1 pour search.py existant."""
    original_query: str
    sub_queries: list[str]
    is_decomposed: bool = False
    reasoning: str = ""
    # V2 fields
    plan: QueryPlan | None = None


# ── Known axes from KG ────────────────────────────────────────────────────────


def _get_known_axis_values() -> dict[str, list[str]]:
    """Detecte les axes de discrimination connus du corpus.

    Domain-agnostic : les axes sont decouverts dynamiquement, pas hardcodes.
    Exemples selon le domaine :
    - SAP : {"release_id": ["2021","2022","2023"], "edition": ["PCE","RISE"]}
    - Biomedical : {"study_phase": ["Phase I","Phase II"], "population": ["adult","pediatric"]}
    - Legal : {"jurisdiction": ["FR","DE","EU"], "effective_date": ["2020","2023"]}

    Strategie en 2 etapes :
    1. Neo4j ApplicabilityAxis (axis_key + known_values)
    2. Qdrant : echantillon des champs axis_* pour decouvrir des axes non-Neo4j
    """
    axes: dict[str, list[str]] = {}

    # 1. Neo4j ApplicabilityAxis
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        driver = get_neo4j_client().driver
        with driver.session() as session:
            result = session.run(
                "MATCH (a:ApplicabilityAxis) "
                "RETURN a.axis_key AS key, a.known_values AS vals"
            )
            for record in result:
                key = record["key"]
                vals = record["vals"]
                if key and vals:
                    # Filtrer les valeurs nulles/vides
                    clean_vals = sorted([v for v in vals if v and str(v).strip()])
                    if clean_vals:
                        axes[key] = clean_vals
    except Exception as e:
        logger.debug(f"[DECOMPOSE] Neo4j axis query failed: {e}")

    # 2. Qdrant : echantillonner des champs axis_* pour completer
    try:
        from knowbase.retrieval.qdrant_layer_r import get_qdrant_client
        from knowbase.config.settings import get_settings
        settings = get_settings()
        client = get_qdrant_client()
        collection = settings.qdrant_collection

        results, _ = client.scroll(
            collection_name=collection,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )

        from collections import defaultdict
        qdrant_axes: dict[str, set[str]] = defaultdict(set)
        for point in results:
            for key, value in point.payload.items():
                if key.startswith("axis_") and value and str(value).strip():
                    # Retirer le prefixe "axis_" pour avoir la cle brute
                    axis_key = key[5:]  # "axis_release_id" → "release_id"
                    qdrant_axes[axis_key].add(str(value))

        # Fusionner : Qdrant complete Neo4j (valeurs que Neo4j n'a pas)
        for axis_key, vals in qdrant_axes.items():
            if axis_key in axes:
                existing = set(axes[axis_key])
                merged = sorted(existing | vals)
                if len(merged) > len(axes[axis_key]):
                    axes[axis_key] = merged
            else:
                axes[axis_key] = sorted(vals)

    except Exception as e:
        logger.debug(f"[DECOMPOSE] Qdrant axis discovery failed: {e}")

    if axes:
        logger.info(f"[DECOMPOSE] Known axes: {{{', '.join(f'{k}: {len(v)} values' for k, v in axes.items())}}}")

    return axes


# ── Structural detection (no LLM) ────────────────────────────────────────────

# Patterns de comparaison / cross-version — domain-agnostic, multilingue
_COMPARISON_PATTERNS = [
    # FR
    r"diff[eé]ren(?:ce|t)",
    r"compar(?:e[rz]?|aison|ons)",
    r"entre\s+(?:la|le|les|l['']\s*)?\s*version",
    r"(?:version|v\.?)\s*\d+.*(?:et|vs\.?|versus)\s*(?:version|v\.?)?\s*\d+",
    r"[eé]volution\s+(?:entre|de\s+\w+\s+[àa])",
    # EN
    r"differ(?:ence|ent|s between)",
    r"compar(?:e|ison|ing)",
    r"between\s+(?:the\s+)?version",
    r"(?:version|v\.?)\s*\d+.*(?:and|vs\.?|versus)\s*(?:version|v\.?)?\s*\d+",
    r"(?:change|evolv)(?:s|ed|ing)?\s+(?:from|between|since)",
    # Universal
    r"vs\.?\s",
]

_ENUMERATION_PATTERNS = [
    r"list(?:e[rz]?|ing)?\s+(?:tous|toutes|all|every|chaque)",
    r"(?:tous|toutes|all)\s+les\s+\w+\s+(?:li[eé]s|related|concerning)",
    r"(?:quels|quelles|which|what)\s+sont\s+(?:les|tous)",
]

_MULTI_FACET_PATTERNS = [
    r"(?:couvrez|incluez|incluant|vue\s+compl[eè]te|p[eé]rim[eè]tre)",
    r"(?:cover|including|comprehensive|complete\s+view|overview|all\s+aspects)",
    r"(?:les\s+aspects|les\s+dimensions|fonctionnalit[eé]s)",
]


def _detect_question_type(query: str) -> str:
    """Detecte le type structurel de la question (sans LLM).

    Returns: "comparison", "enumeration", "multi_facet", ou "simple"
    """
    if len(query) < MIN_QUERY_LENGTH:
        return "simple"

    q_lower = query.lower()

    # Comparison / cross-version
    for pattern in _COMPARISON_PATTERNS:
        if re.search(pattern, q_lower):
            return "comparison"

    # Enumeration
    for pattern in _ENUMERATION_PATTERNS:
        if re.search(pattern, q_lower):
            return "enumeration"

    # Multi-facet (V1 compat)
    for pattern in _MULTI_FACET_PATTERNS:
        if re.search(pattern, q_lower):
            return "multi_facet"

    # Enumerations implicites : 3+ virgules
    if query.count(",") >= 2:
        return "multi_facet"

    return "simple"


# ── LLM-based decomposition ──────────────────────────────────────────────────

DECOMPOSER_SYSTEM_PROMPT = """You are a query decomposition expert for a document retrieval system.

Your job is to analyze a user question and decide whether it needs to be decomposed
into multiple independent sub-questions for better retrieval coverage.

────────────────────────────────────────
DECOMPOSITION RULES
────────────────────────────────────────

1. DECOMPOSE when the question EXPLICITLY asks to compare, enumerate, or contrast
   multiple identifiable entities (versions, products, options, periods, roles...).
   Examples that SHOULD be decomposed :
   - "Differences between X and Y"
   - "Compare option A, B and C on criterion Z"
   - "How did X change between version N and version N+1"
   - "List all instances of X across the corpus"

2. DO NOT DECOMPOSE when the question asks a single focused thing, even if complex.
   Examples that should stay as "simple" :
   - "What is the security rule for X ?"
   - "How does feature Y work ?"
   - "Explain the process of Z"

3. CONSERVATIVE BY DEFAULT : when in doubt, prefer "simple". Over-decomposing a
   simple question adds cost and latency without benefit.

4. DOMAIN-AGNOSTIC : do not rely on any specific vocabulary. The question might
   be about software, medical studies, legal texts, marketing campaigns, or any
   other domain. Focus on the STRUCTURE of the question, not its content.

5. The sub-questions must be SELF-CONTAINED : each must be answerable by a
   focused retrieval without knowing the others.

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────

Return ONLY a JSON object, no markdown, no explanations outside the JSON :

{
  "plan_type": "simple" | "comparison" | "enumeration" | "chronological",
  "synthesis_strategy": "simple" | "compare" | "aggregate" | "chronological",
  "reasoning": "short sentence explaining the decision",
  "sub_queries": [
    {
      "id": "q1",
      "text": "the self-contained sub-question",
      "scope_filter": { "key": "value" } or {},
      "rationale": "what aspect this sub-query targets"
    }
  ]
}

For "simple" plan_type, sub_queries should contain exactly one entry with the
original question unchanged and empty scope_filter.

For "comparison" plan_type, produce 2+ sub-queries, one per entity being compared.
If the entities correspond to known structured axis values (e.g. version numbers,
dates, regions), add them to scope_filter as appropriate. Otherwise leave
scope_filter empty and rely on semantic matching."""


def _build_user_prompt(question: str, known_axes: dict[str, list[str]]) -> str:
    """Construit le user prompt avec les axes connus du corpus."""
    axes_section = ""
    if known_axes:
        axes_section = (
            "For reference, the following axis values are known in the corpus :\n"
            + json.dumps(known_axes, indent=2)
            + "\nYou may use these in scope_filter when relevant."
        )
    return f"""Analyze this user question and produce a QueryPlan.

Question : "{question}"

{axes_section}

Remember :
- Return ONLY valid JSON matching the schema above
- Be conservative : prefer "simple" when in doubt
- Sub-questions must be self-contained
- Domain-agnostic : no vocabulary assumptions"""


def _parse_plan_json(raw: str, original_question: str) -> QueryPlan:
    """Parse le JSON retourne par le LLM en QueryPlan."""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        logger.debug("[DECOMPOSE] No JSON found in LLM response")
        return QueryPlan(original_question=original_question)

    try:
        data = json.loads(m.group())
    except json.JSONDecodeError as e:
        logger.debug(f"[DECOMPOSE] JSON parse error: {e}")
        return QueryPlan(original_question=original_question)

    sub_queries = []
    for i, sq in enumerate(data.get("sub_queries", [])):
        sub_queries.append(SubQuery(
            id=sq.get("id", f"q{i+1}"),
            text=sq.get("text", ""),
            scope_filter=sq.get("scope_filter") or {},
            rationale=sq.get("rationale", ""),
        ))

    plan_type = data.get("plan_type", "simple")
    is_decomposed = plan_type != "simple" and len(sub_queries) > 1

    return QueryPlan(
        original_question=original_question,
        plan_type=plan_type,
        sub_queries=sub_queries,
        synthesis_strategy=data.get("synthesis_strategy", "simple"),
        reasoning=data.get("reasoning", ""),
        is_decomposed=is_decomposed,
    )


# ── Metriques globales (QD-3) ─────────────────────────────────────────────────

_stats = {
    "total_queries": 0,
    "decomposed": 0,
    "simple": 0,
    "llm_calls": 0,
    "llm_errors": 0,
    "integrity_issues": 0,
    "by_plan_type": {},  # {"comparison": N, "enumeration": N, ...}
}


def get_decomposer_stats() -> dict:
    """Retourne les metriques du decomposeur (pour cockpit/monitoring)."""
    return dict(_stats)


def _decompose_llm(question: str, known_axes: dict[str, list[str]]) -> QueryPlan:
    """Decomposition via LLM (Haiku par defaut, OpenAI en fallback)."""
    import time
    user_prompt = _build_user_prompt(question, known_axes)
    provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")
    model = os.getenv("OSMOSIS_DECOMPOSER_MODEL", "claude-haiku-4-5-20251001" if provider != "openai" else "gpt-4o-mini")

    _stats["llm_calls"] += 1
    t0 = time.time()

    try:
        router = get_llm_router()
        raw = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": DECOMPOSER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=500,
        )

        elapsed = round(time.time() - t0, 2)
        logger.info(
            f"[DECOMPOSE:LLM] elapsed={elapsed}s, "
            f"question_len={len(question)}, response_len={len(raw)}"
        )

        plan = _parse_plan_json(raw, question)

        # Enforce MAX_SUB_QUERIES
        if len(plan.sub_queries) > MAX_SUB_QUERIES:
            logger.warning(
                f"[DECOMPOSE] LLM returned {len(plan.sub_queries)} sub-queries, "
                f"truncating to {MAX_SUB_QUERIES}"
            )
            plan.sub_queries = plan.sub_queries[:MAX_SUB_QUERIES]

        return plan

    except Exception as e:
        _stats["llm_errors"] += 1
        logger.warning(f"[DECOMPOSE] LLM decomposition failed: {e}")
        return QueryPlan(original_question=question)


# ── Integrity check (post-retrieval) ─────────────────────────────────────────


def check_plan_integrity(
    plan: QueryPlan,
    retrievals: dict[str, int],
) -> QueryPlan:
    """Verifie l'integrite du plan apres retrieval.

    Si une sous-query n'a ramene aucun chunk, on ne synthetise pas une reponse
    partielle. On identifie le probleme et propose une clarification interactive.

    Args:
        plan: Le plan de decomposition
        retrievals: {sub_query_id: chunk_count} pour chaque sous-query

    Returns:
        Le plan enrichi avec integrity_issue si applicable
    """
    if not plan.is_decomposed:
        return plan

    empty_sqs = []
    filled_sqs = []
    for sq in plan.sub_queries:
        count = retrievals.get(sq.id, 0)
        sq.chunk_count = count
        sq.has_results = count > 0
        if count == 0:
            empty_sqs.append(sq)
        else:
            filled_sqs.append(sq)

    if not empty_sqs:
        return plan  # Tout est couvert

    _stats["integrity_issues"] += 1

    if not filled_sqs:
        # Aucune sous-query n'a de resultats
        plan.integrity_issue = "no_results_at_all"
        return plan

    # Certaines sous-queries sont vides → clarification interactive
    empty_labels = [
        f"{sq.rationale or sq.text}" + (
            f" (filtre: {sq.scope_filter})" if sq.scope_filter else ""
        )
        for sq in empty_sqs
    ]
    available_labels = [
        f"{sq.rationale or sq.text}" + (
            f" (filtre: {sq.scope_filter})" if sq.scope_filter else ""
        )
        for sq in filled_sqs
    ]

    plan.integrity_issue = "partial_coverage"
    plan.available_axes = {
        "empty": empty_labels,
        "available": available_labels,
    }

    logger.info(
        f"[DECOMPOSE:INTEGRITY] Partial coverage: "
        f"{len(filled_sqs)} sub-queries with results, "
        f"{len(empty_sqs)} empty: {empty_labels}"
    )

    return plan


def build_integrity_message(plan: QueryPlan) -> str:
    """Construit le message de clarification interactive pour l'utilisateur.

    Appele par la synthese quand plan.integrity_issue == "partial_coverage".
    """
    if plan.integrity_issue == "no_results_at_all":
        return (
            "Je n'ai trouvé aucune information pertinente dans ma base de connaissances "
            "pour répondre à cette question. Pouvez-vous la reformuler ou préciser "
            "le périmètre ?"
        )

    if plan.integrity_issue != "partial_coverage" or not plan.available_axes:
        return ""

    empty = plan.available_axes.get("empty", [])
    available = plan.available_axes.get("available", [])

    msg_parts = [
        "**Attention** : je ne dispose pas d'informations suffisantes pour traiter "
        "l'intégralité de votre question.\n"
    ]

    if empty:
        msg_parts.append(
            "**Non couvert** (aucun document trouvé) :\n"
            + "".join(f"- {e}\n" for e in empty)
        )

    if available:
        msg_parts.append(
            "\n**Couvert** (informations disponibles) :\n"
            + "".join(f"- {a}\n" for a in available)
        )

    msg_parts.append(
        "\nSouhaitez-vous que je réponde uniquement sur les éléments pour lesquels "
        "je dispose d'informations ?"
    )

    return "\n".join(msg_parts)


# ── QD-6 : Chainage iteratif (IRCoT / Self-Ask) ──────────────────────────────

MAX_ITERATIONS = 2  # max cycles de refinement apres la premiere passe

ITERATIVE_REFINE_PROMPT = """You are analyzing retrieved document chunks to decide if additional information is needed.

Original question: "{question}"

Current sub-queries and their results:
{sub_query_summary}

Based on the chunks retrieved so far, do you need additional targeted searches to fully answer the original question?

Rules:
- Only request additional searches if there is a CLEAR, SPECIFIC gap
- Do NOT request searches for information that is already covered
- Do NOT request more than 2 additional searches
- If the current chunks are sufficient, return an empty list
- Be CONSERVATIVE: additional searches add latency and cost

Return ONLY a JSON object:
{{
  "needs_more": true/false,
  "reasoning": "short explanation",
  "additional_queries": [
    {{"id": "r1", "text": "specific follow-up question", "scope_filter": {{}}, "rationale": "what gap this fills"}}
  ]
}}"""


def evaluate_retrieval_completeness(
    question: str,
    plan: QueryPlan,
    retrieval_summaries: dict[str, str],
) -> list[SubQuery]:
    """QD-6 : Evalue si le retrieval est complet et propose des sous-queries supplementaires.

    Args:
        question: Question originale
        plan: Plan de decomposition actuel
        retrieval_summaries: {sub_query_id: "N chunks, top topics: X, Y, Z"}

    Returns:
        Liste de SubQuery supplementaires (vide si retrieval suffisant)
    """
    import time

    # Construire le resume des sous-queries
    summary_lines = []
    for sq in plan.sub_queries:
        summary = retrieval_summaries.get(sq.id, "0 chunks")
        scope_info = f" (filter: {sq.scope_filter})" if sq.scope_filter else ""
        summary_lines.append(f"- {sq.id}: {sq.text[:80]}{scope_info} → {summary}")

    sub_query_summary = "\n".join(summary_lines)

    prompt = ITERATIVE_REFINE_PROMPT.format(
        question=question,
        sub_query_summary=sub_query_summary,
    )

    provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")
    model = os.getenv("OSMOSIS_DECOMPOSER_MODEL", "claude-haiku-4-5-20251001" if provider != "openai" else "gpt-4o-mini")

    _stats["llm_calls"] += 1
    t0 = time.time()

    try:
        router = get_llm_router()
        raw = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
        )

        elapsed = round(time.time() - t0, 2)

        # Parse JSON
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return []
        data = json.loads(m.group())

        if not data.get("needs_more", False):
            logger.info(f"[DECOMPOSE:ITERATIVE] Retrieval sufficient ({elapsed}s): {data.get('reasoning','')[:80]}")
            return []

        additional = []
        for sq_data in data.get("additional_queries", [])[:2]:
            additional.append(SubQuery(
                id=sq_data.get("id", f"r{len(additional)+1}"),
                text=sq_data.get("text", ""),
                scope_filter=sq_data.get("scope_filter") or {},
                rationale=sq_data.get("rationale", ""),
            ))

        if additional:
            logger.info(
                f"[DECOMPOSE:ITERATIVE] {len(additional)} follow-up queries requested ({elapsed}s): "
                f"{[(sq.id, sq.text[:50]) for sq in additional]}"
            )

        return additional

    except Exception as e:
        _stats["llm_errors"] += 1
        logger.warning(f"[DECOMPOSE:ITERATIVE] Evaluation failed: {e}")
        return []


# ── Main entry point ─────────────────────────────────────────────────────────


def try_decompose(query: str) -> QueryPlan:
    """Point d'entree principal. Detecte et decompose les questions complexes.

    Returns:
        QueryPlan avec is_decomposed=True si decomposition effectuee,
        ou plan_type="simple" + single sub_query sinon.
    """
    import time
    t0 = time.time()
    _stats["total_queries"] += 1

    question_type = _detect_question_type(query)

    if question_type == "simple":
        _stats["simple"] += 1
        logger.debug(f"[DECOMPOSE] simple ({len(query)} chars)")
        return QueryPlan(
            original_question=query,
            plan_type="simple",
            sub_queries=[SubQuery(id="q1", text=query)],
        )

    # Pour comparison/enumeration/chronological : LLM decomposition avec axes KG
    if question_type in ("comparison", "enumeration"):
        known_axes = _get_known_axis_values()
        plan = _decompose_llm(query, known_axes)

        if plan.is_decomposed:
            _stats["decomposed"] += 1
            _stats["by_plan_type"][plan.plan_type] = _stats["by_plan_type"].get(plan.plan_type, 0) + 1
            elapsed = round(time.time() - t0, 2)
            logger.info(
                f"[DECOMPOSE] {plan.plan_type} plan — {len(plan.sub_queries)} sub-queries, "
                f"axes={list(known_axes.keys())}, elapsed={elapsed}s, "
                f"filters={[sq.scope_filter for sq in plan.sub_queries if sq.scope_filter]}"
            )
            return plan

    # Multi-facet fallback (V1 compat) ou si LLM n'a pas decompose
    if question_type == "multi_facet":
        plan = _decompose_llm(query, {})
        if plan.is_decomposed:
            plan.plan_type = "multi_facet"
            _stats["decomposed"] += 1
            _stats["by_plan_type"]["multi_facet"] = _stats["by_plan_type"].get("multi_facet", 0) + 1
            return plan

    # Fallback : pas de decomposition (LLM n'a pas decompose malgre la detection)
    _stats["simple"] += 1
    logger.info(f"[DECOMPOSE] detected={question_type} but LLM kept simple ({len(query)} chars)")
    return QueryPlan(
        original_question=query,
        plan_type="simple",
        sub_queries=[SubQuery(id="q1", text=query)],
    )


# ── V1 compat wrapper ────────────────────────────────────────────────────────


def decompose_query(query: str) -> QueryDecomposition:
    """Wrapper retro-compatible avec l'API V1 utilisee par search.py.

    search.py appelle actuellement :
        decomposition = decompose_query(enriched_query)
        if decomposition.is_decomposed: ...

    Cette fonction maintient la compatibilite tout en utilisant le nouveau moteur.
    """
    plan = try_decompose(query)

    return QueryDecomposition(
        original_query=query,
        sub_queries=[sq.text for sq in plan.sub_queries],
        is_decomposed=plan.is_decomposed,
        reasoning=plan.reasoning,
        plan=plan,
    )
