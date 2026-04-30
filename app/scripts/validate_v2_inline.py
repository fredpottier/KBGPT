#!/usr/bin/env python3
"""Validation V2 end-to-end via Python direct (sans passer par l'API)."""
import sys
sys.path.insert(0, '/app/src')

from neo4j import GraphDatabase
from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings
from knowbase.runtime_v2 import RuntimeV2Pipeline

settings = get_settings()
driver = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'graphiti_neo4j_pass'))
qdrant = get_qdrant_client()
embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
pipeline = RuntimeV2Pipeline(
    driver=driver, qdrant_client=qdrant, embedder=embedder,
    vllm_url='http://18.185.16.189:8000', tenant_id='default',
)

questions = [
    ("CURRENT_DEFAULT", "What is the EU regime for the control of exports of dual-use items?"),
    ("POINT", "What does Regulation (EU) 2021/821 say about brokering services?"),
    ("RANGE", "How did the EU dual-use export control regulation evolve from 2009 to 2024?"),
]

for label, q in questions:
    print(f"\n{'='*70}\n[{label}] {q}\n{'='*70}")
    resp = pipeline.answer(question=q, top_k_claims=5)
    print(f"decision={resp.decision.value}, anchor={resp.anchor.anchor_type.value}, trust={resp.trust_score:.2f}")
    if resp.authoritative_doc_ids:
        print(f"docs: {resp.authoritative_doc_ids[:3]}")
    if resp.synthesized_answer:
        print(f"\n[Synthèse LLM]\n{resp.synthesized_answer}")
    if resp.evolution_points:
        print(f"\n[Evolution timeline] {len(resp.evolution_points)} points")
        for ep in resp.evolution_points[:5]:
            pd = ep.publication_date or "?"
            print(f"  {pd:12s} -> {ep.doc_id} ({len(ep.claims)} claims)")
    if resp.conflicts:
        unresolved = sum(1 for c in resp.conflicts if not c.is_resolved_by_lifecycle)
        print(f"\n[Conflicts] {len(resp.conflicts)} total, {unresolved} unresolved")

driver.close()
