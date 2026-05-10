"""
CH-47 Phase 1 Prototype — Relational Structurer + Constrained Reasoning Composer.

Prototype standalone (n'altère PAS le pipeline V4 actuel).
Pour 10 questions stratifiées sur catégories régressées :
  1. Récupère les chunks via EvidenceCollector existant
  2. Appelle DeepInfra Mistral-Small avec prompt Relational Structurer prototype
  3. Appelle DeepInfra Qwen2.5-72B avec prompt Constrained Reasoning Composer prototype
  4. Sauvegarde atomic_facts + relational_facts + reasoning_steps réels

Output : data/audit/ch47_prototype_10q.json
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, "/app/src")
from knowbase.facts_first.evidence_collector import EvidenceCollector
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings
from neo4j import GraphDatabase

# === Config ===
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY")
STRUCTURER_MODEL = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
COMPOSER_MODEL = "Qwen/Qwen2.5-72B-Instruct"
TIMEOUT = 180.0


# === Sélection 10 questions stratifiées (catégories régressées) ===
TEST_QUESTIONS = [
    # 5 causal_why
    {"id": "q_37", "category": "causal_why", "question": "Pourquoi l'Annex I du règlement 2021/821 doit-elle être régulièrement mise à jour ?"},
    {"id": "q_36", "category": "causal_why", "question": "Pourquoi le règlement 2021/821 a-t-il abrogé le 428/2009 ?"},
    {"id": "q_46", "category": "causal_why", "question": "Pourquoi un compliance officer pourrait-il s'appuyer sur le règlement 428/2009 pour une transaction de 2020 ?"},
    {"id": "q_38", "category": "causal_why", "question": "Pourquoi les listes de contrôle Wassenaar doivent-elles être intégrées au règlement EU dual-use ?"},
    {"id": "q_39", "category": "causal_why", "question": "Pourquoi le règlement 2021/821 prévoit-il des autorisations générales d'exportation distinctes ?"},
    # 2 hypothetical
    {"id": "q_52", "category": "hypothetical", "question": "Si un État membre voulait restreindre une autorisation générale Union, quel mécanisme du règlement 2021/821 le permettrait ?"},
    {"id": "q_53", "category": "hypothetical", "question": "Si CS-25 Amendment 28 était abrogé demain, quelle version d'amendment s'appliquerait ?"},
    # 1 conditional
    {"id": "q_117", "category": "conditional", "question": "Si plus d'informations sont nécessaires pour évaluer une transaction, les autorités compétentes peuvent-elles prolonger le délai d'évaluation ?"},
    # 1 multi_hop
    {"id": "q_88", "category": "multi_hop", "question": "Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre, et pourquoi une valeur plus faible apparaît-elle dans les documents ?"},
    # 1 conditional / lifecycle
    {"id": "q_120", "category": "conditional", "question": "Sous quelles conditions une autorisation individuelle d'exportation peut-elle être suspendue par les autorités compétentes ?"},
]


# === Prompt Relational Structurer prototype ===
RELATIONAL_STRUCTURER_SYSTEM = """You are a Relational Structurer for a multi-domain Q&A system. Extract two levels of facts from evidence chunks to answer a reasoning question.

OUTPUT JSON ONLY conforming to this schema:
{
  "answerability": "answerable_with_reasoning | answerable | unanswerable",
  "atomic_facts": [
    {
      "id": "f1",
      "text": "<verbatim or near-verbatim assertion from evidence>",
      "source": {"doc_id": "...", "quote": "<verbatim quote ≥ 10 chars>"}
    }
  ],
  "relational_facts": [
    {
      "id": "r1",
      "relation_type": "causal | purpose | distinction | conditional | hypothetical",
      "marker": "<linguistic marker if present, else null>",
      "antecedent_ids": ["f1"],
      "consequent_ids": ["f2"],
      "evidence_quote": "<verbatim quote supporting the relation>",
      "inference_strength": "direct | probable | speculative",
      "confidence": 0.0-1.0
    }
  ]
}

RELATION TYPES (universal, multilingual):
- causal: A causes / leads to / necessitates / results in B
- purpose: A is done in order to / so as to achieve B
- distinction: A and B differ in purpose/scope/role/timing
- conditional: if A then B / when A, B / B provided A / unless A
- hypothetical: in case of A, B would occur / assuming A

INFERENCE_STRENGTH:
- "direct": linguistic marker explicitly present in evidence_quote (because, donc, therefore, if/then, in order to, par conséquent, etc.)
- "probable": inference reasonable from adjacent context, no single explicit marker
- "speculative": weak inference, hypothesis only, mention with reservation

CRITICAL CONSTRAINTS:
1. Linguistic markers are HELPFUL SIGNALS, not necessary conditions. Extract relations from context even without explicit marker.
2. Every relational_fact MUST have evidence_quote ≥ 10 chars from the chunks provided.
3. Do NOT propagate inferences beyond the local question corpus (only the chunks given).
4. Do NOT invent relations not anchored in evidence.
5. Set answerability="answerable_with_reasoning" if relational_facts are needed to answer; "answerable" if atomic_facts suffice; "unanswerable" if even relational analysis cannot answer.

Output the JSON object only. No prose."""


# === Prompt Constrained Reasoning Composer prototype (v2 — calibration direct/probable) ===
REASONING_COMPOSER_SYSTEM = """You are a Constrained Reasoning Composer. Generate a structured answer using ONLY the provided atomic_facts and relational_facts.

OUTPUT JSON ONLY conforming to this schema:
{
  "reasoning_steps": [
    {
      "step": 1,
      "type": "evidence_identification | causal_inference | purpose_synthesis | distinction | conditional_projection | hypothetical_projection",
      "inference": "<natural language statement of the reasoning step>",
      "evidence_ids": ["f1"],
      "relation_id": "r1 | null",
      "inference_strength": "direct | probable | speculative",
      "confidence": 0.0-1.0
    }
  ],
  "answer": "<user-facing prose answer in the question language, with [doc=...] inline citations>",
  "citations": ["f1", "r1"],
  "reasoning_confidence": 0.0-1.0,
  "abstention_reason": "<null or constructive explanation if cannot answer>"
}

CRITICAL CONSTRAINTS:
1. Every reasoning_step MUST cite at least one evidence_ids OR a relation_id. No exception.
2. Mark inference_strength STRICTLY according to these rules:

   "direct" = step is a literal paraphrase of ONE atomic_fact OR follows ONE relational_fact
              marked "direct" without combining or generalizing.
              The inference text must be entailable by a SINGLE evidence_quote alone.
              ABSTRACT PATTERN: if atomic_fact f_a states "<P>", a direct step rephrases it
              minimally without adding scope, qualifier, or combining with another fact.

   "probable" = step COMBINES multiple atomic_facts OR multiple relational_facts,
                OR generalizes/reformulates beyond a single evidence_quote,
                OR infers a relation between facts not explicitly marked by a linguistic marker.
                The inference is grounded in evidence but requires composition.
                ABSTRACT PATTERNS:
                  - combine f_a + f_b → joint statement covering both
                  - reformulate "<X marker Y>" into "<Y is consequence of X>" without quoting marker
                  - infer purpose/distinction/condition not stated with explicit marker

   "speculative" = inference goes beyond what evidence directly supports,
                   used as last resort with explicit caveat in answer.
                   Should be RARE.

3. SELF-CHECK before marking direct: "Is my inference text fully supported by ONE single
   evidence_quote, without paraphrase that adds words/concepts?" If no → use probable.
4. For causal/conditional/hypothetical questions: USE relational_facts when present.
5. Do NOT introduce knowledge outside provided evidence. Any specific value, numeric quantity,
   named entity, or technical qualifier mentioned in your inference MUST appear in at least
   one evidence_quote. If you cannot find it in the evidence, do not state it.
6. The "answer" field is user-facing prose. Include doc citations inline.
7. If reasoning_graph empty AND atomic_facts insufficient: emit abstention WITH constructive reason
   (e.g., "Found facts about X but no relation to Y in the corpus"), NOT a generic "not found".

Output the JSON object only. No prose."""


def call_deepinfra(model: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.1) -> dict:
    """Single call DeepInfra OpenAI-compatible avec json_object."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {DEEPINFRA_KEY}"}
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(f"{DEEPINFRA_URL}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
        }


def run_prototype():
    settings = get_settings()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pwd = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pwd))
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
    retriever = ClaimRetriever(qdrant_client=qdrant, embedder=embedder, driver=driver,
                               collection_name="knowbase_chunks_v2", tenant_id=tenant_id)
    collector = EvidenceCollector(retriever=retriever, neo4j_driver=driver, tenant_id=tenant_id, top_k=12)

    results = []

    for i, q in enumerate(TEST_QUESTIONS, 1):
        qid = q["id"]
        cat = q["category"]
        question = q["question"]
        print(f"\n[{i}/{len(TEST_QUESTIONS)}] {qid} ({cat})")
        print(f"  Q: {question[:140]}")

        # 1. Retrieval
        t0 = time.time()
        try:
            evidence = collector.collect(question=question, mode="single", top_k=12)
        except Exception as exc:
            print(f"  RETRIEVAL FAIL: {exc}")
            results.append({"id": qid, "category": cat, "question": question, "error": f"retrieval: {exc}"})
            continue
        retrieval_ms = int((time.time() - t0) * 1000)
        chunks = []
        for c in evidence.claims[:12]:
            chunks.append({
                "id": c.claim_id or f"chunk_{len(chunks)}",
                "doc_id": c.doc_id,
                "quote": (c.quote or "")[:1500],
            })
        print(f"  retrieved {len(chunks)} chunks in {retrieval_ms}ms")

        # 2. Relational Structurer
        chunks_str = "\n".join([f"[{c['id']}] doc={c['doc_id']}: {c['quote']}" for c in chunks])
        structurer_user = f"QUESTION: {question}\n\nEVIDENCE CHUNKS:\n{chunks_str}\n\nExtract atomic_facts and relational_facts as JSON."
        t1 = time.time()
        try:
            struct_resp = call_deepinfra(STRUCTURER_MODEL, RELATIONAL_STRUCTURER_SYSTEM, structurer_user, max_tokens=2500)
            structurer_ms = int((time.time() - t1) * 1000)
            facts_first_v2 = json.loads(struct_resp["content"])
            n_atomic = len(facts_first_v2.get("atomic_facts", []))
            n_rel = len(facts_first_v2.get("relational_facts", []))
            print(f"  Structurer: {structurer_ms}ms | atomic={n_atomic} relational={n_rel} answerability={facts_first_v2.get('answerability')}")
        except Exception as exc:
            print(f"  STRUCTURER FAIL: {exc}")
            results.append({"id": qid, "category": cat, "question": question, "error": f"structurer: {exc}",
                            "chunks_count": len(chunks)})
            continue

        # 3. Constrained Reasoning Composer
        composer_user = f"QUESTION: {question}\n\nFACTS_FIRST_V2:\n{json.dumps(facts_first_v2, ensure_ascii=False, indent=2)}\n\nGenerate reasoning_steps + answer as JSON."
        t2 = time.time()
        try:
            comp_resp = call_deepinfra(COMPOSER_MODEL, REASONING_COMPOSER_SYSTEM, composer_user, max_tokens=2000)
            composer_ms = int((time.time() - t2) * 1000)
            reasoning_output = json.loads(comp_resp["content"])
            n_steps = len(reasoning_output.get("reasoning_steps", []))
            answer_preview = (reasoning_output.get("answer") or "")[:200]
            print(f"  Composer: {composer_ms}ms | steps={n_steps}")
            print(f"  Answer: {answer_preview}")
        except Exception as exc:
            print(f"  COMPOSER FAIL: {exc}")
            results.append({"id": qid, "category": cat, "question": question,
                            "facts_first_v2": facts_first_v2, "error": f"composer: {exc}"})
            continue

        results.append({
            "id": qid, "category": cat, "question": question,
            "chunks_count": len(chunks),
            "facts_first_v2": facts_first_v2,
            "reasoning_output": reasoning_output,
            "timing_ms": {"retrieval": retrieval_ms, "structurer": structurer_ms, "composer": composer_ms},
            "models": {"structurer": STRUCTURER_MODEL, "composer": COMPOSER_MODEL},
        })

    # Stats
    print(f"\n=== STATS ===")
    n_ok = sum(1 for r in results if "error" not in r)
    print(f"OK: {n_ok}/{len(results)}")
    if n_ok > 0:
        n_atomic = sum(len(r["facts_first_v2"].get("atomic_facts", [])) for r in results if "error" not in r)
        n_rel = sum(len(r["facts_first_v2"].get("relational_facts", [])) for r in results if "error" not in r)
        n_steps = sum(len(r["reasoning_output"].get("reasoning_steps", [])) for r in results if "error" not in r)
        print(f"Mean atomic_facts/q: {n_atomic / n_ok:.1f}")
        print(f"Mean relational_facts/q: {n_rel / n_ok:.1f}")
        print(f"Mean reasoning_steps/q: {n_steps / n_ok:.1f}")
        # Distribution inference_strength
        from collections import Counter
        rel_strengths = Counter()
        step_strengths = Counter()
        for r in results:
            if "error" in r:
                continue
            for rel in r["facts_first_v2"].get("relational_facts", []):
                rel_strengths[rel.get("inference_strength", "?")] += 1
            for step in r["reasoning_output"].get("reasoning_steps", []):
                step_strengths[step.get("inference_strength", "?")] += 1
        print(f"Inference_strength relational_facts: {dict(rel_strengths)}")
        print(f"Inference_strength reasoning_steps: {dict(step_strengths)}")

    out = Path("/app/data/audit/ch47_prototype_10q_v2.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    run_prototype()
