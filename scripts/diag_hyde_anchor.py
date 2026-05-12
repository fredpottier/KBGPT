#!/usr/bin/env python3
"""Diag : pourquoi HyDE-inversé retourne 1A005 pour 2021/821 ?"""
import sys
sys.path.insert(0, "/app/src")

import httpx
from neo4j import GraphDatabase
from qdrant_client.models import FieldCondition, Filter, MatchValue

from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

VLLM_URL = "http://3.79.236.241:8000"
VLLM_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"

settings = get_settings()
qdrant = get_qdrant_client()
embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))

doc_id = "dualuse_reg_2021_821_original_65eef5dc"

# 1. Que produit le LLM HyDE ?
prompt = f"""You will receive a document identifier from a regulatory or normative corpus. Imagine the single most representative sentence of that document — the kind of sentence one would find in its Article 1 / Subject matter / Scope clause, that states what the document is fundamentally about and what regime/framework/standard it establishes.

Write only that sentence (1-2 sentences max), in English, in the natural style of an Article 1 or Subject Matter clause. Do not add commentary, quotation marks, or preamble.

Document identifier: {doc_id}

Most representative scope sentence:"""

r = httpx.post(
    f"{VLLM_URL}/v1/chat/completions",
    json={"model": VLLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 150},
    timeout=30.0,
)
hyde_text = r.json()["choices"][0]["message"]["content"].strip()
print(f"=== HyDE query LLM produit ===")
print(f"  '{hyde_text}'\n")

# 2. Embed et search Qdrant
vec = embedder.encode(f"passage: {hyde_text}").tolist()
results = qdrant.search(
    collection_name="knowbase_chunks_v2",
    query_vector=vec,
    limit=10,
    query_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
    with_payload=True,
)

print(f"=== Top 10 claims dans {doc_id} pour cette query ===")
for i, r in enumerate(results, 1):
    p = dict(r.payload or {})
    text = (p.get("text") or "")[:140].replace("\n", " ")
    print(f"  {i}. score={r.score:.3f} cid={p.get('claim_id', '?')[:25]:25s} | {text}")

# 3. Pour comparaison : voir les claims du doc qui contiennent "Union regime" ou "control"
driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
with driver.session() as s:
    print(f"\n=== Claims du doc qui contiennent 'Union regime' ===")
    rows = s.run("""
        MATCH (c:Claim)
        WHERE c.tenant_id = 'default' AND c.doc_id = $doc
          AND c.text CONTAINS 'Union regime'
        RETURN c.claim_id AS cid, c.text AS text
        LIMIT 5
    """, doc=doc_id).data()
    for r in rows:
        print(f"  {r['cid'][:25]} | {r['text'][:200]}")
driver.close()
