"""
CH-47.1 — Test du module RelationalStructurer en standalone.

Charge les atomic_facts du prototype v2 + collecte les chunks via EvidenceCollector,
puis appelle RelationalStructurer.extract() pour vérifier la cohérence du module
isolé vs prototype unifié (atomic+relational dans 1 call).

Output : data/audit/ch47_1_relational_test.json
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/src")

from knowbase.facts_first.evidence_collector import EvidenceCollector
from knowbase.facts_first.relational_structurer import get_relational_structurer
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings
from neo4j import GraphDatabase

PROTOTYPE = Path("/app/data/audit/ch47_prototype_10q_v2.json")
OUT = Path("/app/data/audit/ch47_1_relational_test.json")


def main():
    proto = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    print(f"Loaded {len(proto)} prototype questions")

    # Setup retrieval
    settings = get_settings()
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
    )
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
    retriever = ClaimRetriever(qdrant_client=qdrant, embedder=embedder, driver=driver,
                               collection_name="knowbase_chunks_v2", tenant_id="default")
    collector = EvidenceCollector(retriever=retriever, neo4j_driver=driver, tenant_id="default", top_k=12)

    rel_struct = get_relational_structurer()
    print(f"RelationalStructurer ready (model_override={rel_struct.model_override})")

    results = []
    for q in proto:
        if "error" in q:
            continue
        qid = q["id"]
        cat = q["category"]
        question = q["question"]
        atomic_facts = q.get("facts_first_v2", {}).get("atomic_facts", [])
        # Original relational from prototype (for comparison)
        prototype_relational = q.get("facts_first_v2", {}).get("relational_facts", [])

        if not atomic_facts:
            print(f"[skip] {qid}: no atomic_facts")
            continue

        print(f"\n[{qid}] ({cat}) — {len(atomic_facts)} atomic_facts")
        print(f"  Q: {question[:140]}")

        # Re-collect chunks
        t_ev = time.time()
        try:
            evidence = collector.collect(question=question, mode="single", top_k=12)
        except Exception as exc:
            print(f"  EVIDENCE FAIL: {exc}")
            continue
        chunks = [
            {"id": c.claim_id or f"C{i}", "doc_id": c.doc_id, "quote": (c.quote or "")[:1500]}
            for i, c in enumerate(evidence.claims[:12])
        ]
        print(f"  retrieved {len(chunks)} chunks in {int((time.time()-t_ev)*1000)}ms")

        # Call RelationalStructurer
        t_rel = time.time()
        rel_result = rel_struct.extract(
            question=question,
            atomic_facts=atomic_facts,
            evidence_chunks=chunks,
            language=q.get("language", "fr"),
        )
        rel_ms = int((time.time() - t_rel) * 1000)

        n_module = len(rel_result.relational_facts)
        n_prototype = len(prototype_relational)
        print(f"  RelationalStructurer: {rel_ms}ms | n_relations={n_module} (prototype={n_prototype})")
        if rel_result.parse_error:
            print(f"  ⚠️ parse_error: {rel_result.parse_error}")

        # Compare relation_types
        types_module = sorted(set(r["relation_type"] for r in rel_result.relational_facts))
        types_proto = sorted(set(r.get("relation_type") for r in prototype_relational))
        print(f"  types module={types_module} | prototype={types_proto}")

        # Print first relation produced
        for r in rel_result.relational_facts[:1]:
            print(f"  [R-module] {r['id']}: {r['relation_type']} | "
                  f"strength={r['inference_strength']} | "
                  f"{r['antecedent_ids']} → {r['consequent_ids']}")
            print(f"    quote: {r['evidence_quote'][:200]}...")

        results.append({
            "qid": qid,
            "category": cat,
            "question": question,
            "atomic_facts_count": len(atomic_facts),
            "module_relational": rel_result.relational_facts,
            "module_reasoning_graph": rel_result.reasoning_graph,
            "module_parse_error": rel_result.parse_error,
            "module_latency_ms": rel_ms,
            "prototype_relational": prototype_relational,
            "comparison": {
                "n_module": n_module,
                "n_prototype": n_prototype,
                "types_module": types_module,
                "types_prototype": types_proto,
            },
        })

    # Aggregated stats
    print(f"\n=== AGREGATE ===")
    n_ok = sum(1 for r in results if r["module_relational"])
    print(f"Module produced relations on {n_ok}/{len(results)} questions")
    if n_ok > 0:
        mean_rel_module = sum(len(r["module_relational"]) for r in results) / max(n_ok, 1)
        mean_rel_proto = sum(len(r["prototype_relational"]) for r in results) / max(len(results), 1)
        print(f"Mean relations/q : module={mean_rel_module:.1f} | prototype={mean_rel_proto:.1f}")
        from collections import Counter
        types_count = Counter()
        strength_count = Counter()
        for r in results:
            for rel in r["module_relational"]:
                types_count[rel["relation_type"]] += 1
                strength_count[rel["inference_strength"]] += 1
        print(f"Relation types distribution: {dict(types_count)}")
        print(f"Inference strength distribution: {dict(strength_count)}")

    # Persist
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT}")


if __name__ == "__main__":
    main()
