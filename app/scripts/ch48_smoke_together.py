"""
CH-48 — Smoke test 5q via Together AI Qwen-72B Turbo (validation rapide).

Vérifie en 1-2 min :
  - L'env TOGETHER_API_KEY est bien chargée
  - Le client RuntimeLLMClient route vers Together AI (provider=together)
  - Une question end-to-end V4.1 répond avec atomic_facts + relational_facts
  - Latence par question < 35s (cible Test Armand)

Si OK → enchaîner sur bench micro 30q stratifié + bench global complet.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"

# 5 questions diverses (causal, factual, list, hypothetical) pour valider routing + reasoning_mode
QUESTIONS = [
    ("smoke_1", "factual", "Quelle est la capitale de la France ?"),
    ("smoke_2", "causal_why", "Pourquoi le règlement 2021/821 a-t-il abrogé le 428/2009 ?"),
    ("smoke_3", "list", "List the four types of export authorisations established by Regulation (EU) 2021/821."),
    ("smoke_4", "hypothetical", "Si un État membre voulait restreindre une autorisation générale Union, quel mécanisme du règlement 2021/821 le permettrait ?"),
    ("smoke_5", "multi_hop", "Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre ?"),
]


def main():
    print("=== CH-48 SMOKE TEST Together AI ===\n")

    # 1. Check health endpoint pour voir le provider actif
    try:
        h = requests.get(API.replace("/answer", "/health"), timeout=10).json()
        print(f"Health: {h.get('status')} | config={h.get('config')}\n")
    except Exception as exc:
        print(f"Health check failed: {exc}")
        sys.exit(1)

    # 2. Run 5 questions séquentiel
    results = []
    for qid, cat, question in QUESTIONS:
        print(f"[{qid}] ({cat})")
        print(f"  Q: {question[:140]}")
        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 12}, timeout=120)
            wall = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
        except requests.Timeout:
            print(f"  TIMEOUT after {int((time.time()-t0)*1000)}ms")
            results.append({"qid": qid, "error": "timeout"})
            continue
        except Exception as exc:
            print(f"  EXC {exc}")
            results.append({"qid": qid, "error": str(exc)})
            continue

        primary = data.get("primary_type")
        routing = data.get("routing_decision")
        decision = data.get("decision")
        ff = data.get("facts_first") or {}
        n_atomic = len(ff.get("atomic_facts") or [])
        n_rel = len(ff.get("relational_facts") or [])
        is_reasoning = routing == "reasoning_path"
        flag = "✓R" if is_reasoning else " ·"
        print(f"  {flag} primary={primary} routing={routing} decision={decision}"
              f" | atomic={n_atomic} rel={n_rel} | wall={wall}ms")
        answer = (data.get("answer") or "")[:200]
        print(f"  Answer: {answer}")
        print()
        results.append({"qid": qid, "wall_ms": wall, "primary_type": primary,
                        "routing": routing, "decision": decision,
                        "n_atomic": n_atomic, "n_rel": n_rel,
                        "is_reasoning": is_reasoning})

    # 3. Stats
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("=== TOUS LES APPELS ONT ÉCHOUÉ — config Together AI à vérifier ===")
        sys.exit(1)
    walls = [r["wall_ms"] for r in valid]
    print(f"\n=== STATS ({len(valid)}/{len(results)} valid) ===")
    print(f"Latence (ms): min={min(walls)} mean={sum(walls)//len(walls)} max={max(walls)}")
    n_reasoning = sum(1 for r in valid if r.get("is_reasoning"))
    print(f"Reasoning_path activé: {n_reasoning}/{len(valid)}")
    n_answer = sum(1 for r in valid if r.get("decision") == "ANSWER")
    print(f"ANSWER: {n_answer}/{len(valid)}")

    # Verdict latence
    mean_s = sum(walls) / len(walls) / 1000
    if mean_s < 35:
        print(f"\n✓ Latence mean {mean_s:.1f}s — DANS LA CIBLE Test Armand (30-40s)")
    elif mean_s < 60:
        print(f"\n⚠️ Latence mean {mean_s:.1f}s — au-dessus cible Test Armand (30-40s)")
    else:
        print(f"\n❌ Latence mean {mean_s:.1f}s — TROP LENT")

    out = Path("/app/data/audit/ch48_smoke_together.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    main()
