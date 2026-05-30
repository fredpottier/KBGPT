"""Probe : les entités focales des questions false_premise qui confabulent sont-elles
réellement absentes du corpus (vs raté de retrieval) ? Cherche dans Qdrant chunks +
Neo4j claims (full-text). Read-only.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from knowbase.common.clients.embeddings import EmbeddingModelManager
from knowbase.common.clients.qdrant_client import search_with_tenant_filter

PROBES = [
    ("Embedded Reporting Studio", "entité supposée inexistante (Q1_1)"),
    ("Oracle Database native support in SAP S/4HANA", "présupposé faux : Oracle natif (FP_002)"),
    ("direct migration SAP Business One to S/4HANA Cloud Private Edition", "migration directe inexistante (Q1_2)"),
    ("SAP S/4HANA requires SAP HANA database", "CONTRÔLE — doit exister"),
]

mgr = EmbeddingModelManager()
for q, note in PROBES:
    v = mgr.encode([q])[0].tolist()
    hits = search_with_tenant_filter(
        collection_name="knowbase_chunks_v2", query_vector=v, tenant_id="default", limit=3,
    )
    print(f"\n### {q}  [{note}]")
    for h in hits:
        p = h.get("payload", {}) or {}
        txt = (p.get("text") or p.get("content") or "")[:160].replace("\n", " ")
        score = h.get("score")
        print(f"  score={score:.3f} | {txt}")
