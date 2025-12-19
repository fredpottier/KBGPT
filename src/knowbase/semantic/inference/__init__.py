"""
🌊 OSMOSE Semantic Intelligence - Inference Engine

Phase 2.3: Découverte de Connaissances Cachées (Hidden Knowledge Discovery)

Killer Feature: Découvrir des insights que l'utilisateur n'aurait jamais trouvés
par recherche traditionnelle RAG.

Composants:
- InferenceEngine: Moteur principal de découverte d'insights
- InsightType: Types d'insights découvrables
- DiscoveredInsight: Structure d'un insight découvert

Types d'insights:
1. TRANSITIVE_INFERENCE - Relations implicites via chaînes (A→B→C donc A→C)
2. BRIDGE_CONCEPT - Concepts qui connectent des clusters sinon isolés
3. HIDDEN_CLUSTER - Communautés thématiques non évidentes
4. WEAK_SIGNAL - Concepts émergents à faible fréquence mais fort potentiel
5. STRUCTURAL_HOLE - Relations manquantes prédites par patterns KG
6. CONTRADICTION - Assertions contradictoires entre documents

Usage:
```python
from knowbase.semantic.inference import InferenceEngine, InsightType

engine = InferenceEngine()

# Découvrir tous les insights
insights = await engine.discover_all_insights(tenant_id="default")

# Découvrir un type spécifique
transitive = await engine.discover_transitive_relations(tenant_id="default")
bridges = await engine.discover_bridge_concepts(tenant_id="default")
```
"""

from .inference_engine import (
    InferenceEngine,
    InsightType,
    DiscoveredInsight,
)

__all__ = [
    "InferenceEngine",
    "InsightType",
    "DiscoveredInsight",
]
