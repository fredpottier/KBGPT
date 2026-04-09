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
    """Interroge Neo4j pour les AxisValues connus du corpus."""
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        driver = get_neo4j_client().driver
        axes: dict[str, list[str]] = {}
        with driver.session() as session:
            result = session.run(
                "MATCH (av:AxisValue) "
                "RETURN av.discriminating_role AS role, collect(DISTINCT av.value) AS vals"
            )
            for record in result:
                role = record["role"]
                vals = sorted(record["vals"])
                if role and vals:
                    axes[role] = vals
        if axes:
            logger.debug(f"[DECOMPOSE] Known axes from KG: {axes}")
        return axes
    except Exception as e:
        logger.debug(f"[DECOMPOSE] Failed to load axes from KG: {e}")
        return {}


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


def _decompose_llm(question: str, known_axes: dict[str, list[str]]) -> QueryPlan:
    """Decomposition via LLM (Haiku par defaut, OpenAI en fallback)."""
    user_prompt = _build_user_prompt(question, known_axes)
    provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")

    try:
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=500,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": DECOMPOSER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = resp.choices[0].message.content
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                temperature=0.0,
                system=DECOMPOSER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = resp.content[0].text

        return _parse_plan_json(raw, question)

    except Exception as e:
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


# ── Main entry point ─────────────────────────────────────────────────────────


def try_decompose(query: str) -> QueryPlan:
    """Point d'entree principal. Detecte et decompose les questions complexes.

    Returns:
        QueryPlan avec is_decomposed=True si decomposition effectuee,
        ou plan_type="simple" + single sub_query sinon.
    """
    question_type = _detect_question_type(query)

    if question_type == "simple":
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
            logger.info(
                f"[DECOMPOSE] {plan.plan_type} plan with {len(plan.sub_queries)} sub-queries: "
                f"{[(sq.id, sq.scope_filter) for sq in plan.sub_queries]}"
            )
            return plan

    # Multi-facet fallback (V1 compat) ou si LLM n'a pas decompose
    if question_type == "multi_facet":
        plan = _decompose_llm(query, {})
        if plan.is_decomposed:
            plan.plan_type = "multi_facet"
            return plan

    # Fallback : pas de decomposition
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
