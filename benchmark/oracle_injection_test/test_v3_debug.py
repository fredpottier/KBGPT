"""Debug case 1 — pourquoi 428/2009 régresse en ABSTAIN"""
import sys, time
sys.path.insert(0, "/app/src")

from knowbase.runtime_v3.synthesis import synthesize, _build_evidence_block
from knowbase.runtime_v3.nli_judge import judge_faithfulness, _split_into_atomic_claims
from knowbase.runtime_v3.retriever import ClaimRetriever
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

qdrant = QdrantClient(url="http://qdrant:6333", timeout=30)
embedder = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
neo4j = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
retriever = ClaimRetriever(qdrant_client=qdrant, embedder=embedder, driver=neo4j,
                            collection_name="knowbase_chunks_v2", tenant_id="default")

q = "Quel règlement a remplacé le règlement 428/2009 ?"
print(f"Q: {q}\n")

claims = retriever.retrieve(question=q, doc_ids=None, top_k=10)
print(f"Retrieved {len(claims)} claims")
for i, c in enumerate(claims[:3]):
    print(f"  [{i+1}] {c.doc_id[:30]} score={c.score:.2f}")
    print(f"      {(c.text or '')[:150]}")
print()

# Sans regen
synth = synthesize(question=q, claims=claims)
print(f"Synthesis decision: {synth.decision}")
print(f"Answer: {synth.answer[:300]}")
print(f"Confidence: {synth.confidence}")
print(f"Doc IDs cited: {synth.doc_ids_cited}")
print()

if synth.decision == "ANSWER":
    # Test NLI
    print("=== NLI Faithfulness ===")
    atomic = _split_into_atomic_claims(synth.answer)
    print(f"Atomic claims: {len(atomic)}")
    for a in atomic:
        print(f"  - {a}")
    print()
    faith = judge_faithfulness(answer=synth.answer, claims=claims)
    print(f"Faith verdict: {faith.overall_verdict} score={faith.overall_score:.2f}")
    print(f"  supported={faith.n_supported} unsupported={faith.n_unsupported} neutral={faith.n_neutral}")
    for cv in faith.claim_verdicts:
        print(f"  [{cv.verdict}] entail={cv.entailment:.2f} contra={cv.contradiction:.2f}")
        print(f"     claim: {cv.claim[:120]}")
