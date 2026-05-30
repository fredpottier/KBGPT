"""Probe diagnostic comparison : valeurs distinctives présentes dans corpus/KG ?"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from knowbase.common.clients.embeddings import EmbeddingModelManager
from knowbase.common.clients.qdrant_client import search_with_tenant_filter

mgr = EmbeddingModelManager()
for note in ["3145277", "3307222"]:
    v = mgr.encode([f"SAP Note {note} Release Information Note"])[0].tolist()
    hits = search_with_tenant_filter(collection_name="knowbase_chunks_v2",
                                     query_vector=v, tenant_id="default", limit=5)
    found = any(note in (h.get("payload", {}).get("text") or "") for h in hits)
    top = hits[0].get("score") if hits else 0.0
    print(f"note {note}: in_top5_chunks={found}  topscore={top:.3f}")
