"""
Runtime V3 — Refonte minimaliste (CH-39).

5 stages clean, ~1500 lignes max, vraiment domain-agnostic :

1. Hybrid retrieve (BM25 + vector) — top 30
2. Cross-encoder rerank GPU (BGE-v2-m3 multilingue) — top 10
3. Agentic synthesis — 1 LLM call avec output JSON structuré
4. NLI faithfulness judge — mDeBERTa-v3 multilingue (specialized model > LLM-as-judge)
5. Régen conditionnelle — 1× max si faithfulness < 0.5

Différences vs runtime_v2 :
- Pas de hardcoded lists/regex (50+ supprimés)
- Pas de modules séparés pour premise/lifecycle/hallucination (intégrés au prompt synthesis)
- Specialized model NLI judge (cf. SOTA Lynx/Galileo Luna/HHEM)
- Output JSON structuré pour faciliter validation downstream
"""
from knowbase.runtime_v3.pipeline import RuntimeV3Pipeline

__all__ = ["RuntimeV3Pipeline"]
