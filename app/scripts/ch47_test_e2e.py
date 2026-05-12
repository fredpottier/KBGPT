"""
CH-47 — Test end-to-end via API runtime_v4/answer avec V4_REASONING_MODE_ENABLED.

Teste les 5 top-deltas causal_why du Robust (q_36, q_37, q_38, q_39, q_46) plus
quelques questions hypothetical/conditional/multi_hop pour voir le routage.

Output : data/audit/ch47_e2e_test.json
"""
from __future__ import annotations
import json
import time
from pathlib import Path
import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"

QUESTIONS = [
    ("q_37", "causal_why", "Pourquoi l'Annex I du règlement 2021/821 doit-elle être régulièrement mise à jour ?"),
    ("q_36", "causal_why", "Pourquoi le règlement 2021/821 a-t-il abrogé le 428/2009 ?"),
    ("q_46", "causal_why", "Pourquoi un compliance officer pourrait-il s'appuyer sur le règlement 428/2009 pour une transaction de 2020 ?"),
    ("q_38", "causal_why", "Pourquoi les listes de contrôle Wassenaar doivent-elles être intégrées au règlement EU dual-use ?"),
    ("q_39", "causal_why", "Pourquoi le règlement 2021/821 prévoit-il des autorisations générales d'exportation distinctes ?"),
    ("q_52", "hypothetical", "Si un État membre voulait restreindre une autorisation générale Union, quel mécanisme du règlement 2021/821 le permettrait ?"),
    ("q_117", "conditional", "Si plus d'informations sont nécessaires pour évaluer une transaction, les autorités compétentes peuvent-elles prolonger le délai d'évaluation ?"),
    ("q_88", "multi_hop", "Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre, et pourquoi une valeur plus faible apparaît-elle dans les documents ?"),
]


def main():
    results = []
    for qid, cat, question in QUESTIONS:
        print(f"\n[{qid}] ({cat})")
        print(f"  Q: {question[:140]}")
        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 12}, timeout=300)
            wall = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
        except Exception as exc:
            print(f"  EXC {exc}")
            continue

        primary_type = data.get("primary_type")
        routing = data.get("routing_decision")
        decision = data.get("decision")
        answer = data.get("answer", "")[:300]
        ff = data.get("facts_first") or {}
        n_atomic = len(ff.get("atomic_facts") or [])
        n_rel = len(ff.get("relational_facts") or [])
        n_steps = (data.get("latency_breakdown_ms") or {}).get("structurer_ms")
        is_reasoning = routing == "reasoning_path"

        print(f"  wall={wall}ms | primary={primary_type} | routing={routing} | decision={decision}")
        if is_reasoning:
            print(f"  ✓ REASONING MODE | atomic={n_atomic} relational={n_rel}")
        else:
            print(f"  → V4 path standard (atomic={n_atomic} relational={n_rel})")
        print(f"  Answer: {answer}")
        results.append({
            "qid": qid, "category": cat, "question": question,
            "wall_ms": wall, "primary_type": primary_type,
            "routing_decision": routing, "decision": decision,
            "is_reasoning": is_reasoning,
            "n_atomic": n_atomic, "n_relational": n_rel,
            "answer": data.get("answer"),
            "doc_ids_cited": data.get("doc_ids_cited"),
            "facts_first_keys": list(ff.keys()) if ff else [],
        })

    print(f"\n=== STATS ===")
    n_ok = sum(1 for r in results if r.get("decision") == "ANSWER")
    n_reasoning = sum(1 for r in results if r.get("is_reasoning"))
    n_abst = sum(1 for r in results if r.get("decision") == "ABSTAIN")
    print(f"ANSWER: {n_ok}/{len(results)}")
    print(f"REASONING_PATH activé: {n_reasoning}/{len(results)}")
    print(f"ABSTAIN: {n_abst}/{len(results)}")

    out = Path("/app/data/audit/ch47_e2e_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    main()
