"""
CH-47.2 — Test du module ReasoningComposer en isolation.

Charge atomic_facts + relational_facts produits par RelationalStructurer (test 47.1),
puis appelle ReasoningComposer.compose() pour vérifier que le module produit des
reasoning_steps cohérents et tracés.

Output : data/audit/ch47_2_composer_test.json
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/src")

from knowbase.facts_first.reasoning_composer import get_reasoning_composer

INPUT = Path("/app/data/audit/ch47_1_relational_test.json")
PROTO_FACTS = Path("/app/data/audit/ch47_prototype_10q_v2.json")  # for atomic_facts
OUT = Path("/app/data/audit/ch47_2_composer_test.json")


def main():
    rel_results = json.loads(INPUT.read_text(encoding="utf-8"))
    proto = json.loads(PROTO_FACTS.read_text(encoding="utf-8"))
    proto_by_id = {q["id"]: q for q in proto}
    print(f"Loaded {len(rel_results)} relational test results")

    composer = get_reasoning_composer()
    print(f"ReasoningComposer ready (model_override={composer.model_override})")

    results = []
    for r in rel_results:
        qid = r["qid"]
        cat = r["category"]
        question = r["question"]
        proto_q = proto_by_id.get(qid, {})
        atomic_facts = (proto_q.get("facts_first_v2") or {}).get("atomic_facts") or []
        relational_facts = r.get("module_relational") or []
        reasoning_graph = r.get("module_reasoning_graph") or {"nodes": [], "edges": []}

        if not atomic_facts:
            print(f"[skip] {qid}: no atomic_facts")
            continue

        print(f"\n[{qid}] ({cat}) — {len(atomic_facts)} atomic, {len(relational_facts)} relational")

        # Map cat to primary_type
        type_map = {
            "causal_why": "causal", "hypothetical": "hypothetical",
            "conditional": "conditional", "multi_hop": "factual",
        }
        primary_type = type_map.get(cat, "factual")

        t0 = time.time()
        comp = composer.compose(
            question=question, atomic_facts=atomic_facts,
            relational_facts=relational_facts,
            reasoning_graph=reasoning_graph,
            primary_type=primary_type,
        )
        wall = int((time.time() - t0) * 1000)

        n_steps = comp.n_steps
        n_rejected = comp.n_steps_rejected
        print(f"  Composer: {wall}ms | steps_valid={n_steps} steps_rejected={n_rejected}")
        if comp.parse_error:
            print(f"  ⚠️ parse_error: {comp.parse_error}")
        if comp.abstention_reason:
            print(f"  → abstention_reason: {comp.abstention_reason[:200]}")
        # Show steps
        for s in comp.reasoning_steps[:3]:
            ev = ",".join(s.get("evidence_ids", []) or [])
            rid = s.get("relation_id") or "-"
            print(f"  Step {s['step']} [{s['type']}] strength={s['inference_strength']} "
                  f"ev={ev} rel={rid}: {s['inference'][:100]}")
        if comp.answer:
            print(f"  ANSWER preview: {comp.answer[:200]}")

        results.append({
            "qid": qid, "category": cat, "primary_type": primary_type,
            "atomic_facts_count": len(atomic_facts),
            "relational_facts_count": len(relational_facts),
            "composer_result": comp.to_dict(),
            "composer_latency_ms": wall,
            "answer_full": comp.answer,
            "parse_error": comp.parse_error,
        })

    # Aggregate
    print(f"\n=== AGGREGATE ===")
    n_ok = sum(1 for r in results if r["composer_result"]["reasoning_steps"])
    print(f"Composer produced steps: {n_ok}/{len(results)}")
    if n_ok > 0:
        total_steps = sum(r["composer_result"]["n_steps"] for r in results)
        total_rejected = sum(r["composer_result"]["n_steps_rejected"] for r in results)
        print(f"Total steps valid : {total_steps} | rejected: {total_rejected}")
        # Distribution strengths
        from collections import Counter
        strengths = Counter()
        types_ = Counter()
        for r in results:
            for s in r["composer_result"]["reasoning_steps"]:
                strengths[s.get("inference_strength")] += 1
                types_[s.get("type")] += 1
        print(f"Strength distribution: {dict(strengths)}")
        print(f"Type distribution: {dict(types_)}")
        # Abstention rate
        n_abst = sum(1 for r in results if r["composer_result"].get("abstention_reason"))
        print(f"Abstention with constructive reason: {n_abst}/{len(results)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT}")


if __name__ == "__main__":
    main()
