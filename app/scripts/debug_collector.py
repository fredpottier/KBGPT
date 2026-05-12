"""Debug le bundle.claims du EvidenceCollector."""
import sys, os
sys.path.insert(0, "/app/src")
from knowbase.config.settings import get_settings
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.facts_first.evidence_collector import EvidenceCollector
from neo4j import GraphDatabase

settings = get_settings()
qdrant = get_qdrant_client()
embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))

retriever = ClaimRetriever(
    qdrant_client=qdrant, embedder=embedder, driver=driver,
    collection_name="knowbase_chunks_v2", tenant_id="default",
)
collector = EvidenceCollector(retriever=retriever, neo4j_driver=driver, tenant_id="default", top_k=15)

q = "Quelle reglementation EU dual-use etait applicable en mars 2020 ?"
bundle = collector.collect(question=q, top_k=15, mode="single")

print(f"Bundle attrs: {[a for a in dir(bundle) if not a.startswith('_')][:25]}")
print(f"n_qdrant_hits: {getattr(bundle, 'n_qdrant_hits', None)}")
print(f"answerability_hint: {getattr(bundle, 'answerability_hint', None)}")
print(f"diagnostic: {getattr(bundle, 'diagnostic', None)}")
claims = getattr(bundle, "claims", None)
print(f"claims type: {type(claims).__name__} | len: {len(claims) if claims else 0}")
if claims:
    c = claims[0]
    print(f"\nclaim[0] type: {type(c).__name__}")
    print(f"claim[0] attrs: {[a for a in dir(c) if not a.startswith('_')][:30]}")
    if hasattr(c, "model_dump"):
        d = c.model_dump()
        for k, v in list(d.items())[:15]:
            v_str = str(v)[:120]
            print(f"  {k}: {v_str}")
    else:
        print(f"  vars: {vars(c)}")
