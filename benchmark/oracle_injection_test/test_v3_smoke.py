"""Test fumée pipeline V3 sur 5 cas représentatifs."""
import sys
import os
import time
sys.path.insert(0, "/app/src")

from knowbase.runtime_v3.pipeline import RuntimeV3Pipeline
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

print("Loading clients...")
qdrant = QdrantClient(url="http://qdrant:6333", timeout=30)
embedder = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
neo4j = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))

pipe = RuntimeV3Pipeline(
    qdrant_client=qdrant, embedder=embedder, driver=neo4j,
    collection_name="knowbase_chunks_v2", tenant_id="default",
)

cases = [
    # (question, expected_decision, expected_keyword_in_answer)
    ("Quel règlement a remplacé le règlement 428/2009 ?", "ANSWER", "2021/821"),
    ("Le règlement 428/2009 est-il toujours en vigueur ?", "ANSWER", "2021/821"),
    ("Pourquoi CS-25 Amendment 28 prescrit-il une énergie d'impact de 50 J pour les grands items en verre ?", "REJECT_FALSE_PREMISE", "21"),
    ("Quel est le numéro de série de l'avion Airbus A350 utilisé comme référence dans CS-25 Amendment 28 ?", "ABSTAIN", None),
    ("Quels CS-25 amdt s'applique à un dossier ouvert le 31 décembre 2023 ?", "ANSWER", "28"),
]

print(f"\nRunning {len(cases)} smoke tests...\n")
for i, (q, expected_dec, expected_kw) in enumerate(cases, 1):
    print(f"=== [{i}/{len(cases)}] {q[:80]} ===")
    print(f"  Expected decision={expected_dec}, keyword={expected_kw}")
    t = time.time()
    try:
        resp = pipe.answer(q)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        continue
    elapsed = time.time() - t
    print(f"  Got decision={resp.decision} confidence={resp.confidence:.2f} faith={resp.faithfulness_score:.2f} ({resp.faithfulness_verdict})")
    print(f"  Answer: {resp.answer[:200]}")
    if expected_kw:
        match_kw = expected_kw.lower() in (resp.answer or "").lower()
        match_dec = resp.decision == expected_dec
        status = "✅ OK" if match_kw and match_dec else "⚠️ check"
        print(f"  {status} (kw_match={match_kw} dec_match={match_dec})")
    else:
        match_dec = resp.decision == expected_dec
        print(f"  {'✅ OK' if match_dec else '⚠️ check'} (dec_match={match_dec})")
    print(f"  Latency: {elapsed:.1f}s | breakdown: {resp.latency_breakdown_ms}")
    print()

print("Smoke test complete.")
