"""POC Layer 0 — smoke test 5 questions (1 par type)."""
import json
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_poc/answer"

QUESTIONS = [
    ("factual_simple", "Quel règlement de l'Union européenne établit le régime communautaire de contrôle des exportations dual-use ?"),
    ("factual_negative_NEG_006", "Selon le règlement 2021/821, qu'est-ce qui N'EST PAS requis pour qu'une transaction de produit dual-use de l'Annex I soit légale ?"),
    ("unanswerable_off_topic_UNA_006", "Quelle est la position de la Russie sur le règlement 2021/821 ?"),
    ("unanswerable_correct_UNA_003", "Combien d'autorisations d'export ont été délivrées par la France en 2023 selon le règlement 2021/821 ?"),
    ("list_off_target_SET_009", "Liste les références EU externes citées dans le règlement 2021/821."),
]

print("=== POC Layer 0 smoke test — 5 questions ===\n")
results = []
for label, q in QUESTIONS:
    print(f"--- [{label}] ---")
    print(f"Q: {q[:160]}")
    t0 = time.time()
    try:
        r = requests.post(API, json={"question": q, "top_k_claims": 12}, timeout=60)
        wall = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            continue
        d = r.json()
    except requests.Timeout:
        print(f"  TIMEOUT after {int((time.time()-t0)*1000)}ms")
        continue
    except Exception as exc:
        print(f"  EXC {exc}")
        continue

    print(f"  decision={d['decision']} | qa_alignment={d.get('qa_alignment')} | wall={wall}ms")
    print(f"  latency_breakdown: {d.get('latency_breakdown_ms')}")
    print(f"  answer: {(d.get('answer') or '')[:200]}")
    if d.get("abstention_reason"):
        print(f"  abstention_reason: {d['abstention_reason']}")
    print()
    results.append({"label": label, "decision": d["decision"], "wall_ms": wall,
                    "qa_alignment": d.get("qa_alignment"),
                    "latency_breakdown": d.get("latency_breakdown_ms")})

walls = [r["wall_ms"] for r in results]
if walls:
    print(f"=== STATS ===")
    print(f"  Mean latency: {sum(walls)//len(walls)}ms")
    print(f"  Min/Max: {min(walls)}ms / {max(walls)}ms")
    decs = [r["decision"] for r in results]
    print(f"  ANSWER: {decs.count('ANSWER')} | ABSTAIN: {decs.count('ABSTAIN')}")
