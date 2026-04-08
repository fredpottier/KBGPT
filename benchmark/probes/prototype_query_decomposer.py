"""
Prototype de validation — Query Decomposition pour les questions comparatives.

Objectif : valider empiriquement que le pattern "decompose + retrieve-per-subquery
+ reconcile" repond correctement aux questions cross-version la ou le retrieval
mono-requete actuel echoue (cf. investigation du 08/04 sur temporal_evolution).

Approche :
1. Prend une question en input (hardcoded ici pour l'exemple, 5-6 questions test)
2. Appelle le LLM via llm_router (vLLM si disponible, Haiku sinon) avec un prompt
   de decomposition domain-agnostic
3. Parse le QueryPlan (comparison / enumeration / simple)
4. Pour chaque sub_query, appelle l'API /api/search actuelle avec un scope_filter
   optionnel (si le decomposer en produit un)
5. Assemble les chunks en un contexte structure
6. Appelle un LLM de synthese avec le contexte structure et un prompt conscient
   de la structure (pas le prompt OSMOSIS actuel, un prompt prototype)
7. Compare la reponse avec ce qu'on aurait obtenu via l'API standard (mono-query)

Aucune modification du pipeline OSMOSIS. C'est un script de validation de
principe. Si ca marche, on integrera proprement dans un second temps.

USAGE
─────
    docker exec -e OSMOSIS_API_URL=http://app:8000 knowbase-app \\
        python //app/benchmark/probes/prototype_query_decomposer.py

Le script affiche :
- Le QueryPlan produit par le decomposer
- La distribution des axis_release_id des chunks retrouves par sub-query
- La reponse synthetisee
- Une comparaison avec la reponse mono-query de l'API actuelle
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

API_BASE = os.getenv("OSMOSIS_API_URL", "http://app:8000")

# ══════════════════════════════════════════════════════════════════════════
# Test questions
# ══════════════════════════════════════════════════════════════════════════

TEST_QUESTIONS = [
    # Comparison cross-version — le cas qui foire actuellement
    "Quelles sont les principales differences dans la description des permissions "
    "d'acces entre la version 2022 et 2023 du Guide de Securite SAP ?",

    # Comparison non-version (variantes produit)
    "Compare SAP S/4HANA et SAP S/4HANA Cloud Private Edition sur les aspects "
    "de gouvernance des donnees.",

    # Question simple (ne devrait PAS etre decomposee)
    "Quelle est la regle de securite pour les logon tickets dans SAP S/4HANA ?",

    # Enumeration
    "Liste tous les objets d'autorisation lies a la gestion des donnees personnelles "
    "dans SAP S/4HANA.",
]

# ══════════════════════════════════════════════════════════════════════════
# QueryPlan model
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class SubQuery:
    id: str
    text: str
    scope_filter: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class QueryPlan:
    original_question: str
    plan_type: str  # "simple" | "comparison" | "enumeration" | "chronological"
    sub_queries: List[SubQuery] = field(default_factory=list)
    synthesis_strategy: str = "simple"  # "simple" | "compare" | "aggregate" | "chronological"
    reasoning: str = ""


# ══════════════════════════════════════════════════════════════════════════
# Decomposer prompt
# ══════════════════════════════════════════════════════════════════════════

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


DECOMPOSER_USER_TEMPLATE = """Analyze this user question and produce a QueryPlan.

Question : "{question}"

{known_axes_section}

Remember :
- Return ONLY valid JSON matching the schema above
- Be conservative : prefer "simple" when in doubt
- Sub-questions must be self-contained
- Domain-agnostic : no vocabulary assumptions"""


# ══════════════════════════════════════════════════════════════════════════
# Synthesis prompt
# ══════════════════════════════════════════════════════════════════════════

SYNTHESIS_PROMPT = """You are a document analysis expert. You have been given
structured context grouped by sub-question. Your job is to synthesize a clear
answer to the original question based on the grouped chunks.

Original question : "{question}"

Synthesis strategy : {strategy}

Structured context :
{grouped_context}

Instructions :
- Answer the original question based ONLY on the chunks provided
- If the strategy is "compare", explicitly structure your answer to compare the
  groups point by point
- If the strategy is "aggregate", merge information from all groups into a
  single coherent answer
- Cite the source document for each claim using the format *(Document name, p.X)*
- If information is missing for one of the groups, say it explicitly
- Answer in the same language as the question"""


# ══════════════════════════════════════════════════════════════════════════
# Pipeline functions
# ══════════════════════════════════════════════════════════════════════════


def get_auth_token() -> str:
    r = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_known_axis_values() -> Dict[str, List[str]]:
    """Interroge Neo4j via l'API OSMOSIS pour les axes connus.

    Pour le prototype : on utilise une liste hardcodee basee sur ce qu'on a
    constate en soiree (release_id 2021/2022/2023/2025, editions PCE/RISE).
    En production, ce serait une query Cypher sur les DocumentContext.qualifiers_json.
    """
    return {
        "release_id": ["1809", "2021", "2022", "2023", "2023 FPS03", "2023 SPS04", "2025"],
        "edition": ["PCE", "RISE", "On-Premise"],
    }


def decompose_query(question: str, llm_call_func) -> QueryPlan:
    """Appelle le decomposer LLM et parse le resultat."""
    known_axes = get_known_axis_values()
    known_axes_section = ""
    if known_axes:
        known_axes_section = (
            "For reference, the following axis values are known in the corpus :\n"
            + json.dumps(known_axes, indent=2)
            + "\nYou may use these in scope_filter when relevant."
        )

    user_prompt = DECOMPOSER_USER_TEMPLATE.format(
        question=question,
        known_axes_section=known_axes_section,
    )

    raw = llm_call_func(DECOMPOSER_SYSTEM_PROMPT, user_prompt)

    # Extraire le JSON
    import re
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        print(f"  [DECOMPOSER] No JSON in response, falling back to simple")
        return QueryPlan(
            original_question=question,
            plan_type="simple",
            sub_queries=[SubQuery(id="q1", text=question)],
            synthesis_strategy="simple",
            reasoning="parse_error_fallback",
        )

    try:
        data = json.loads(m.group())
    except json.JSONDecodeError as e:
        print(f"  [DECOMPOSER] JSON decode error : {e}, falling back to simple")
        return QueryPlan(
            original_question=question,
            plan_type="simple",
            sub_queries=[SubQuery(id="q1", text=question)],
            synthesis_strategy="simple",
            reasoning="json_error_fallback",
        )

    plan = QueryPlan(
        original_question=question,
        plan_type=data.get("plan_type", "simple"),
        synthesis_strategy=data.get("synthesis_strategy", "simple"),
        reasoning=data.get("reasoning", ""),
        sub_queries=[
            SubQuery(
                id=sq.get("id", f"q{i+1}"),
                text=sq.get("text", ""),
                scope_filter=sq.get("scope_filter", {}) or {},
                rationale=sq.get("rationale", ""),
            )
            for i, sq in enumerate(data.get("sub_queries", []))
        ],
    )
    return plan


def retrieve_for_subquery(
    sub_query: SubQuery, token: str, use_latest: bool = False
) -> Dict[str, Any]:
    """Appelle l'API /api/search pour une sub-query, en passant release_id en
    filtre PRE-retrieval a Qdrant via le parametre natif de SearchRequest.

    Le `scope_filter` de la sub-query est mappe vers le parametre release_id
    de l'API /api/search, qui est propage jusqu'au retriever Qdrant comme
    FieldCondition (cf. src/knowbase/api/services/retriever.py).
    C'est un VRAI filtre pre-retrieval, pas un filtrage post-hoc.
    """
    query_text = sub_query.text

    # Extraire release_id du scope_filter si present
    # Accepter plusieurs cles possibles : axis_release_id, release_id
    release_id = None
    if sub_query.scope_filter:
        release_id = (
            sub_query.scope_filter.get("axis_release_id")
            or sub_query.scope_filter.get("release_id")
        )

    payload = {
        "question": query_text,
        "use_graph_context": True,
        "graph_enrichment_level": "standard",
        "use_graph_first": True,
        "use_kg_traversal": True,
        "use_latest": use_latest,
    }
    if release_id:
        payload["release_id"] = release_id

    r = requests.post(
        f"{API_BASE}/api/search",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()

    return {
        "chunks": data.get("results", []),
        "mode": data.get("response_mode"),
        "original_synthesis": data.get("synthesis", {}).get("synthesized_answer", ""),
    }


def assemble_context(
    plan: QueryPlan, retrievals: Dict[str, Dict[str, Any]], max_chunks_per_group: int = 10
) -> str:
    """Assemble les chunks en un contexte structure par sub-query."""
    sections = []
    for sq in plan.sub_queries:
        r = retrievals.get(sq.id, {})
        chunks = r.get("chunks", [])[:max_chunks_per_group]
        if not chunks:
            sections.append(f"=== {sq.id} ({sq.rationale or sq.text}) ===\n(no chunks found)\n")
            continue

        chunk_lines = []
        for i, c in enumerate(chunks, 1):
            text = (c.get("text") or "")[:500]
            doc = c.get("source_file") or c.get("doc_id", "?")
            rel = c.get("axis_release_id") or "?"
            chunk_lines.append(f"  [{i}] (doc={doc}, release={rel}) {text}")

        sections.append(
            f"=== {sq.id} ({sq.rationale or sq.text}) ===\n"
            + "\n".join(chunk_lines)
            + "\n"
        )

    return "\n".join(sections)


def synthesize_answer(
    question: str, strategy: str, grouped_context: str, llm_call_func
) -> str:
    """Appelle le LLM de synthese avec le contexte structure."""
    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        strategy=strategy,
        grouped_context=grouped_context[:8000],  # cap pour rester raisonnable
    )
    return llm_call_func("", prompt)


# ══════════════════════════════════════════════════════════════════════════
# LLM interface
# ══════════════════════════════════════════════════════════════════════════


def make_llm_call_func():
    """Cree un closure llm_call_func(system, user) -> str utilisant llm_router."""
    sys.path.insert(0, "/app/src")
    from knowbase.common.llm_router import get_llm_router, TaskType
    router = get_llm_router()

    def call(system_prompt: str, user_prompt: str) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
        )

    return call


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════


def process_question(question: str, token: str, llm_call_func):
    print("=" * 100)
    print(f"QUESTION : {question}")
    print("=" * 100)

    # 1. Decompose
    print("\n[1] Decomposing...")
    plan = decompose_query(question, llm_call_func)
    print(f"  plan_type           : {plan.plan_type}")
    print(f"  synthesis_strategy  : {plan.synthesis_strategy}")
    print(f"  reasoning           : {plan.reasoning}")
    print(f"  sub_queries         : {len(plan.sub_queries)}")
    for sq in plan.sub_queries:
        print(f"    - {sq.id}: {sq.text[:80]}")
        if sq.scope_filter:
            print(f"      scope_filter: {sq.scope_filter}")

    # 2. Retrieve per sub-query
    print(f"\n[2] Retrieving ({len(plan.sub_queries)} sub-queries)...")
    retrievals = {}
    for sq in plan.sub_queries:
        print(f"  -> {sq.id}")
        r = retrieve_for_subquery(sq, token)
        retrievals[sq.id] = r
        chunks = r["chunks"]
        from collections import Counter
        rels = Counter(c.get("axis_release_id", "None") for c in chunks)
        print(f"     {len(chunks)} chunks, release_id distribution: {dict(rels)}")

    # 3. Assemble context
    print("\n[3] Assembling context...")
    context = assemble_context(plan, retrievals)
    print(f"  context length : {len(context)} chars")

    # 4. Synthesize
    print("\n[4] Synthesizing...")
    answer = synthesize_answer(
        question, plan.synthesis_strategy, context, llm_call_func
    )
    print("\n" + "─" * 100)
    print("DECOMPOSED ANSWER:")
    print("─" * 100)
    print(answer[:3000])
    if len(answer) > 3000:
        print(f"\n[...{len(answer)-3000} chars omitted]")

    # 5. Compare with mono-query (for the simple case, it's the same)
    if plan.plan_type != "simple":
        print("\n" + "─" * 100)
        print("MONO-QUERY ANSWER (current API baseline):")
        print("─" * 100)
        # Re-call API with the original question for comparison
        mono = retrieve_for_subquery(SubQuery(id="mono", text=question), token)
        mono_answer = mono.get("original_synthesis", "")
        print(mono_answer[:3000])
        if len(mono_answer) > 3000:
            print(f"\n[...{len(mono_answer)-3000} chars omitted]")

    print("\n")


def main():
    print("Prototype Query Decomposer — validation du pattern")
    print(f"API base : {API_BASE}")
    print()

    token = get_auth_token()
    print(f"Auth OK (token len {len(token)})")
    print()

    llm_call = make_llm_call_func()

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-idx", type=int, default=-1,
                        help="Process only this question index (default: all)")
    args = parser.parse_args()

    questions_to_run = TEST_QUESTIONS
    if args.question_idx >= 0:
        questions_to_run = [TEST_QUESTIONS[args.question_idx]]

    for q in questions_to_run:
        try:
            process_question(q, token, llm_call)
        except Exception as e:
            print(f"\nERROR on question: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
