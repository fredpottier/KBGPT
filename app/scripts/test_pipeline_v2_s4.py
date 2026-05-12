#!/usr/bin/env python3
"""
Test V2-S4 — Pipeline Runtime V2 anchor-driven end-to-end.

Lance N questions cross-domain à travers le pipeline V2 :
  Question → Anchor Extractor → Anchor Filter → Current Resolver → Retrieval → Conflict Detector
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.common.clients.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from knowbase.runtime_v2 import RuntimeV2Pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("test_pipeline_v2")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

FORENSICS_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
FORENSICS_DIR.mkdir(parents=True, exist_ok=True)

# Questions cross-domain ciblant le corpus aerospace_compliance actuel
TEST_QUESTIONS = [
    # CURRENT_DEFAULT — corpus aerospace
    ("What are the main certification requirements for large aeroplanes?", False),
    # POINT — version explicite (CS-25 Amdt 27)
    ("Quelles sont les règles dans CS-25 Amendment 27 ?", False),
    # POINT — Regulation 2021/821
    ("What does Regulation (EU) 2021/821 say about brokering services?", False),
    # RANGE — évolution
    ("How did dual-use export control evolve in EU regulation?", False),
    # CURRENT_DEFAULT avec audit ON
    ("What are the rules for export control of dual-use items?", True),
]


def main() -> int:
    settings = get_settings()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(
        settings.embeddings_model, cache_folder=str(settings.hf_home)
    )

    pipeline = RuntimeV2Pipeline(
        driver=driver,
        qdrant_client=qdrant,
        embedder=embedder,
        vllm_url=VLLM_URL,
        tenant_id=TENANT_ID,
        vllm_model=VLLM_MODEL,
    )

    results = []
    for i, (q, audit) in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i:02d}] Q: {q}")
        print(f"     audit_mode={audit}")
        try:
            resp = pipeline.answer(question=q, audit_mode=audit, top_k_claims=5)
            print(f"     decision={resp.decision.value}")
            print(f"     anchor={resp.anchor.anchor_type.value} (conf={resp.anchor.confidence:.2f})")
            if resp.anchor.scope.extraction_evidence:
                print(f"     anchor_evidence='{resp.anchor.scope.extraction_evidence}'")
            print(f"     authoritative_doc_ids={resp.authoritative_doc_ids[:3]}{'...' if len(resp.authoritative_doc_ids) > 3 else ''}")
            print(f"     n_claims={len(resp.claims)}, trust_score={resp.trust_score:.2f}")
            if resp.claims:
                top = resp.claims[0]
                print(f"     top_claim: doc={top.doc_id} score={top.score:.2f} text={top.text[:100]}")
            if resp.evolution_points:
                print(f"     n_evolution_points={len(resp.evolution_points)}")
                for ep in resp.evolution_points[:3]:
                    print(f"       {ep.publication_date or '?'} → {ep.doc_id} ({len(ep.claims)} claims)")
            if resp.conflicts:
                print(f"     n_conflicts={len(resp.conflicts)} (resolved by lifecycle: {sum(1 for c in resp.conflicts if c.is_resolved_by_lifecycle)})")
            if resp.escalation_message:
                print(f"     escalation: {resp.escalation_message}")
            results.append(
                {
                    "question": q,
                    "audit_mode": audit,
                    "decision": resp.decision.value,
                    "anchor_type": resp.anchor.anchor_type.value,
                    "anchor_confidence": resp.anchor.confidence,
                    "n_authoritative_docs": len(resp.authoritative_doc_ids),
                    "n_claims": len(resp.claims),
                    "n_conflicts": len(resp.conflicts),
                    "trust_score": resp.trust_score,
                    "escalation_message": resp.escalation_message,
                }
            )
        except Exception as exc:
            logger.error("Question %d failed: %s", i, exc, exc_info=True)
            results.append({"question": q, "error": str(exc)})

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = FORENSICS_DIR / f"pipeline_v2_s4_test_{ts}.json"
    with out_path.open("w") as f:
        json.dump({"results": results, "ts": ts}, f, indent=2, default=str)
    print(f"\nForensics saved to {out_path}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
