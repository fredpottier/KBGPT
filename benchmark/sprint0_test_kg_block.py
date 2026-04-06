#!/usr/bin/env python3
"""Sprint 0 — Test 1 : Le bloc KG change-t-il la qualite des reponses ?

Compare les reponses avec et sans bloc KG, sur les MEMES chunks Qdrant.
Si delta < 5%, la strategie KG-enriched synthesis est remise en question.
"""

import json
import logging
import os
import time

import requests
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("sprint0-test1")

VLLM_URL = os.environ.get("VLLM_URL", "http://18.194.28.167:8000")
TEI_URL = os.environ.get("TEI_URL", "http://18.194.28.167:8001")
QDRANT_URL = "http://localhost:6333"
COLLECTION = "knowbase_chunks_v2"

SYSTEM_PROMPT = """You are a precise assistant. Answer questions using ONLY the provided sources.
MANDATORY RULES:
1. Every factual statement MUST be followed by [Source N]
2. Be specific: include names, numbers, values when available
3. If the information is partially available, answer with what you have - do NOT refuse
4. ONLY say "information not available" if NONE of the sources contain ANY relevant information
5. If sources contain contradictions or divergences, mention them explicitly
Answer in the SAME LANGUAGE as the question."""


def embed(text):
    r = requests.post(f"{TEI_URL}/embed", json={"inputs": f"query: {text}"}, timeout=10)
    return r.json()[0]


def qdrant_search(embedding, top_k=10):
    r = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/query",
        json={"query": embedding, "limit": top_k, "with_payload": True},
        timeout=10,
    )
    return r.json().get("result", {}).get("points", [])


def build_context(chunks):
    parts = []
    for i, p in enumerate(chunks):
        doc = p.get("payload", {}).get("doc_id", "unknown")
        text = p.get("payload", {}).get("text", "")[:800]
        parts.append(f"[Source {i+1}: {doc}]\n{text}")
    return "\n\n".join(parts)


def build_kg_block(chunks, question=""):
    """Construit un bloc KG RICHE a partir des chunks retournes.

    3 sources d'information que les chunks NE contiennent PAS :
    1. Triples SPO structures (sujet-predicat-objet) des claims liees
    2. Tensions cross-doc avec le contenu des deux cotes
    3. Valeurs comparees des QuestionSignatures

    Matching elargi : chunk_ids directs + fallback par doc_id + embedding similarity.
    """
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "graphiti_neo4j_pass")
    )

    chunk_ids = [
        p.get("payload", {}).get("chunk_id", "")
        for p in chunks
        if p.get("payload", {}).get("chunk_id")
    ]
    doc_ids = list(set(
        p.get("payload", {}).get("doc_id", "")
        for p in chunks
        if p.get("payload", {}).get("doc_id")
    ))

    spo_triples = []
    tensions = []
    qs_values = []
    doc_coverage = set()

    with driver.session() as session:
        # 1. Trouver les claims via chunk_ids OU doc_ids (fallback elargi)
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: "default"})
            WHERE ANY(cid IN c.chunk_ids WHERE cid IN $chunk_ids)
               OR c.doc_id IN $doc_ids
            WITH c LIMIT 30

            // Extraire les triples SPO
            OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)

            // Trouver les tensions cross-doc
            OPTIONAL MATCH (c)-[t:REFINES|QUALIFIES|CONTRADICTS]-(other:Claim)
            WHERE other.doc_id <> c.doc_id

            RETURN c.claim_id AS claim_id,
                   c.doc_id AS doc_id,
                   c.structured_form_json AS spo,
                   left(c.text, 100) AS claim_text,
                   collect(DISTINCT e.name)[..3] AS entities,
                   collect(DISTINCT {
                       type: type(t),
                       this_text: left(c.text, 80),
                       this_doc: c.doc_id,
                       other_text: left(other.text, 80),
                       other_doc: other.doc_id
                   })[..2] AS claim_tensions
            """,
            chunk_ids=chunk_ids,
            doc_ids=doc_ids,
        )

        seen_spo = set()
        seen_tensions = set()
        for r in result:
            doc_coverage.add((r["doc_id"] or "")[:40])

            # SPO triples
            if r["spo"]:
                try:
                    import json as _json
                    spo = _json.loads(r["spo"])
                    subj = spo.get("subject", "")
                    pred = spo.get("predicate", "")
                    obj = spo.get("object", "")
                    if subj and pred and obj:
                        key = f"{subj}|{pred}|{obj}"
                        if key not in seen_spo:
                            seen_spo.add(key)
                            spo_triples.append({
                                "subject": subj, "predicate": pred, "object": obj,
                                "doc": (r["doc_id"] or "")[:40]
                            })
                except Exception:
                    pass

            # Tensions
            for t in r["claim_tensions"]:
                if t and t.get("type"):
                    tkey = f"{t.get('this_text', '')[:30]}|{t.get('other_text', '')[:30]}"
                    if tkey not in seen_tensions:
                        seen_tensions.add(tkey)
                        tensions.append(t)

        # 2. QuestionSignatures pertinentes (valeurs comparees cross-doc)
        if doc_ids:
            qs_result = session.run(
                """
                MATCH (qs:QuestionSignature)-[:ANSWERS]->(qd:QuestionDimension)
                WHERE qs.doc_id IN $doc_ids AND qs.tenant_id = "default"
                WITH qd, collect({
                    value: qs.extracted_value,
                    doc: qs.doc_id,
                    question: qs.question
                }) AS answers
                WHERE size(answers) >= 1
                RETURN qd.canonical_question AS question,
                       qd.dimension_key AS dimension,
                       answers[..4] AS values
                LIMIT 5
                """,
                doc_ids=doc_ids,
            )
            for r in qs_result:
                if r["values"]:
                    qs_values.append({
                        "question": r["question"],
                        "dimension": r["dimension"],
                        "values": r["values"],
                    })

    driver.close()

    # Construire le bloc KG structure
    if not spo_triples and not tensions and not qs_values:
        return ""

    lines = ["[Knowledge Graph Context — verified facts from document analysis]"]

    # SPO triples (max 5, les plus informatifs)
    if spo_triples:
        lines.append("")
        lines.append("Structured facts extracted from the corpus:")
        for spo in spo_triples[:5]:
            lines.append(f'  - {spo["subject"]} {spo["predicate"]} {spo["object"]} [from {spo["doc"]}]')

    # Tensions cross-doc (max 3)
    if tensions:
        lines.append("")
        lines.append("CROSS-DOCUMENT DIVERGENCES DETECTED (mention these in your answer):")
        for t in tensions[:3]:
            ttype = t.get("type", "?")
            this_text = t.get("this_text", "")
            this_doc = (t.get("this_doc") or "")[:35]
            other_text = t.get("other_text", "")
            other_doc = (t.get("other_doc") or "")[:35]
            lines.append(f'  - {ttype}:')
            lines.append(f'    Document A ({this_doc}): "{this_text}"')
            lines.append(f'    Document B ({other_doc}): "{other_text}"')

    # Valeurs comparees QS (max 3)
    if qs_values:
        lines.append("")
        lines.append("Comparable values across documents:")
        for qs in qs_values[:3]:
            lines.append(f'  Question: {qs["question"]}')
            for v in qs["values"][:3]:
                doc = (v.get("doc") or "")[:35]
                val = v.get("value", "?")
                lines.append(f'    - {doc}: {val}')

    # Couverture documentaire
    if len(doc_coverage) > 1:
        lines.append("")
        lines.append(f"This topic is covered by {len(doc_coverage)} documents in the corpus.")

    return "\n".join(lines)


def synthesize(question, context, kg_block=""):
    qwen = OpenAI(api_key="EMPTY", base_url=f"{VLLM_URL}/v1")

    if kg_block:
        user_prompt = f"{kg_block}\n\nSources:\n\n{context}\n\nQuestion: {question}\n\nAnswer (cite [Source N]):"
    else:
        user_prompt = f"Sources:\n\n{context}\n\nQuestion: {question}\n\nAnswer (cite [Source N]):"

    resp = qwen.chat.completions.create(
        model="Qwen/Qwen2.5-14B-Instruct-AWQ",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1200,
        temperature=0,
    )
    return resp.choices[0].message.content or ""


def main():
    # Load 50 questions
    with open("benchmark/questions/task1_provenance_kg.json", encoding="utf-8") as f:
        kg_q = json.load(f)["questions"][:20]
    with open("benchmark/questions/task1_provenance_human.json", encoding="utf-8") as f:
        hum_q = json.load(f)["questions"][:30]
    questions = kg_q + hum_q
    logger.info(f"Loaded {len(questions)} questions")

    results_without = []
    results_with = []

    for i, q in enumerate(questions):
        question = q["question"]
        logger.info(f"[{i+1}/{len(questions)}] {question[:50]}...")

        # Retrieve (same for both)
        emb = embed(question)
        chunks = qdrant_search(emb)
        context = build_context(chunks)

        # Build chunk list for source_map (judge needs this)
        chunk_list = [
            {"source_file": p.get("payload", {}).get("doc_id", ""),
             "doc_id": p.get("payload", {}).get("doc_id", ""),
             "chunk_id": p.get("payload", {}).get("chunk_id", ""),
             "text": p.get("payload", {}).get("text", "")[:200]}
            for p in chunks
        ]

        # Without KG
        answer_no = synthesize(question, context)

        # With KG (enriched block)
        kg_block = build_kg_block(chunks, question=question)
        answer_with = synthesize(question, context, kg_block=kg_block)

        results_without.append({
            "question_id": q["question_id"],
            "task": "T1_provenance",
            "question": question,
            "system": "rag_no_kg",
            "response": {"answer": answer_no, "results": chunk_list},
            "ground_truth": q["ground_truth"],
            "grading_rules": q.get("grading_rules", {}),
        })
        results_with.append({
            "question_id": q["question_id"],
            "task": "T1_provenance",
            "question": question,
            "system": "rag_with_kg_block",
            "response": {
                "answer": answer_with,
                "results": chunk_list,
                "kg_block": kg_block,
                "kg_block_tokens": len(kg_block.split()),
            },
            "ground_truth": q["ground_truth"],
            "grading_rules": q.get("grading_rules", {}),
        })

    # Save
    out_dir = "benchmark/results/sprint0_kg_block_test"
    os.makedirs(out_dir, exist_ok=True)
    for name, results in [("without_kg", results_without), ("with_kg", results_with)]:
        path = f"{out_dir}/{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            system = "rag_no_kg" if "without" in name else "rag_with_kg_block"
            json.dump(
                {"metadata": {
                    "test": "kg_block_contribution_v2",
                    "system": system,
                    "task": "T1",
                    "corpus": "SAP Enterprise Documentation",
                    "count": len(results),
                },
                 "results": results},
                f, ensure_ascii=False, indent=2,
            )

    logger.info(f"Done. Saved {len(results_without)} + {len(results_with)} results")

    # Quick stats
    same = sum(
        1
        for a, b in zip(results_without, results_with)
        if a["response"]["answer"][:50] == b["response"]["answer"][:50]
    )
    logger.info(f"Identical first 50 chars: {same}/{len(questions)}")

    kg_sizes = [r["response"].get("kg_block_tokens", 0) for r in results_with]
    kg_non_empty = sum(1 for s in kg_sizes if s > 0)
    avg_size = sum(kg_sizes) / max(len(kg_sizes), 1)
    logger.info(f"KG block non-empty: {kg_non_empty}/{len(questions)}, avg size: {avg_size:.0f} tokens")


if __name__ == "__main__":
    main()
