# Plan d'Implémentation - LLM Merge Gate V1

## Contexte

### Problème Identifié
L'Entity Resolution (Pass 4a) effectue des fusions incorrectes basées uniquement sur la similarité d'embeddings. 3 erreurs constatées sur 25 merges (12%) :

| Fusion erronée | Problème |
|----------------|----------|
| SAP S/4HANA → SAP HANA | ERP ≠ Base de données |
| Active-passive → Active-active | Architectures opposées |
| HTTPS inbound closed → HTTPS outbound open | Règles firewall opposées |

### Solution Validée
Tests Qwen 14B : **6/6 correct** (100% précision, latence ~1-2s/paire, confiance 0.90-1.0)

### Décisions Architecture
- **LLM Gate toujours actif** : Utilise EC2 burst si actif, sinon fallback OpenAI
- **Scope** : Tous les candidats après pruning
- **Batching** : 10-30 paires par appel LLM

---

## Architecture Cible

### Pipeline ER Modifié (Pass 4a)

```
1. Load active CanonicalConcepts
2. Compute lex_keys
3. Find candidates (blocking)
4. Score candidates (lex, sem, compat)
5. Prune candidates (Top-K + mutual best)
       ↓
   ┌─────────────────────────────────────────────────┐
   │  5.5 LLM MERGE GATE (NOUVEAU)                   │
   │  ├── Batch candidates (10-30 paires/appel)      │
   │  ├── Appel LLM (vLLM si burst, sinon OpenAI)    │
   │  ├── Parse réponses JSON                        │
   │  └── Marquer DISTINCT → forcer REJECT           │
   └─────────────────────────────────────────────────┘
       ↓
6. _decide_v2() (décision finale, respecte LLM verdicts)
7. Cap proposals
8. Execute AUTO_MERGE
9. Store proposals
```

### Flux de Décision avec LLM Gate

```
Candidat après pruning
        ↓
   LLM verdict?
        │
        ├── DISTINCT (conf >= 0.80) → REJECT (bloqué)
        │
        ├── MERGE (conf >= 0.85) → Continuer vers _decide_v2()
        │                          (permet AUTO_MERGE si scores OK)
        │
        └── MERGE (conf < 0.85) → PROPOSE_ONLY (pas d'auto-merge)
            ou DISTINCT (conf < 0.80)
```

---

## Spécifications Techniques

### 1. Nouveau Module : `llm_merge_gate.py`

**Emplacement** : `src/knowbase/entity_resolution/llm_merge_gate.py`

```python
@dataclass
class LLMMergeVerdict:
    """Verdict du LLM pour une paire de concepts."""
    source_id: str
    target_id: str
    decision: str  # "MERGE" | "DISTINCT"
    confidence: float
    reason: str

@dataclass
class LLMGateResult:
    """Résultat global du LLM Gate."""
    verdicts: List[LLMMergeVerdict]
    blocked_pairs: Set[Tuple[str, str]]  # Paires DISTINCT à rejeter
    total_calls: int
    total_latency_ms: float
```

### 2. Prompt LLM (Batch)

```
Tu es un expert en Entity Resolution pour un Knowledge Graph technique.
Pour chaque paire de concepts, détermine s'ils représentent LA MÊME entité (MERGE) ou des entités DISTINCTES.

RÈGLES:
- MERGE: Même entité avec variations (typo, acronyme, ponctuation)
- DISTINCT: Entités différentes même si proches lexicalement

PAIRES À ANALYSER:
{pairs_json}

Réponds UNIQUEMENT en JSON (array):
[
  {"pair_index": 0, "decision": "MERGE"|"DISTINCT", "confidence": 0.0-1.0, "reason": "..."},
  ...
]
```

### 3. Configuration

```python
@dataclass
class LLMGateConfig:
    """Configuration du LLM Merge Gate."""
    enabled: bool = True
    batch_size: int = 20  # Paires par appel LLM

    # Seuils de confiance
    merge_confidence_threshold: float = 0.85  # Auto-merge si MERGE + conf >= 0.85
    distinct_confidence_threshold: float = 0.80  # Bloquer si DISTINCT + conf >= 0.80

    # Provider
    prefer_burst: bool = True  # Utiliser vLLM si EC2 actif
    fallback_model: str = "gpt-4o-mini"  # Fallback si pas de burst

    # Timeouts
    timeout_per_batch: int = 30  # secondes
    max_retries: int = 2
```

### 4. Intégration dans CorpusERPipeline

**Fichier** : `src/knowbase/consolidation/corpus_er_pipeline.py`

```python
# Après pruning, avant _decide_all()

# Step 5.5: LLM Merge Gate
if self.llm_gate_config.enabled:
    gate_result = await self._run_llm_merge_gate(pruned)
    pruned = self._apply_llm_verdicts(pruned, gate_result)
    stats.llm_gate_calls = gate_result.total_calls
    stats.llm_gate_blocked = len(gate_result.blocked_pairs)
```

---

## Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `src/knowbase/entity_resolution/llm_merge_gate.py` | **Créer** | Module LLM Gate |
| `src/knowbase/consolidation/corpus_er_pipeline.py` | Modifier | Intégrer le gate après pruning |
| `src/knowbase/consolidation/types.py` | Modifier | Ajouter stats LLM Gate |
| `src/knowbase/entity_resolution/__init__.py` | Modifier | Exporter le nouveau module |

---

## Détail des Implémentations

### Phase 1 : Module LLM Merge Gate

**`src/knowbase/entity_resolution/llm_merge_gate.py`**

```python
"""
LLM Merge Gate - Validation sémantique des fusions par LLM.

Utilise Qwen 14B (vLLM) si EC2 burst actif, sinon fallback OpenAI.
Traite les candidats par batch de 10-30 paires.
"""

import logging
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Tuple, Optional
from datetime import datetime

from knowbase.common.llm_router import get_llm_router, TaskType

logger = logging.getLogger(__name__)


@dataclass
class LLMGateConfig:
    """Configuration du LLM Merge Gate."""
    enabled: bool = True
    batch_size: int = 20
    merge_confidence_threshold: float = 0.85
    distinct_confidence_threshold: float = 0.80
    timeout_per_batch: int = 30
    max_retries: int = 2


@dataclass
class LLMMergeVerdict:
    """Verdict du LLM pour une paire."""
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    decision: str  # "MERGE" | "DISTINCT"
    confidence: float
    reason: str


@dataclass
class LLMGateResult:
    """Résultat du LLM Gate."""
    verdicts: List[LLMMergeVerdict] = field(default_factory=list)
    blocked_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    low_confidence_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    total_calls: int = 0
    total_latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


class LLMMergeGate:
    """
    LLM Merge Gate pour Entity Resolution.

    Valide les candidats de fusion via un LLM (Qwen 14B ou GPT-4o-mini).
    """

    PROMPT_TEMPLATE = '''Tu es un expert en Entity Resolution pour un Knowledge Graph technique.
Pour chaque paire de concepts ci-dessous, détermine s'ils représentent LA MÊME entité (MERGE) ou des entités DISTINCTES.

RÈGLES DE DÉCISION:
- MERGE: Même entité avec variations mineures (typo, acronyme, ponctuation, casse)
- DISTINCT: Entités différentes même si lexicalement proches. Exemples:
  - Produits différents (SAP S/4HANA ≠ SAP HANA)
  - Configurations opposées (active-passive ≠ active-active)
  - Directions opposées (inbound ≠ outbound)

PAIRES À ANALYSER:
{pairs_json}

Réponds UNIQUEMENT avec un array JSON valide (pas de texte avant/après):
[
  {{"pair_index": 0, "decision": "MERGE", "confidence": 0.95, "reason": "même entité, variation de ponctuation"}},
  {{"pair_index": 1, "decision": "DISTINCT", "confidence": 0.90, "reason": "produits différents"}}
]'''

    def __init__(self, config: Optional[LLMGateConfig] = None):
        self.config = config or LLMGateConfig()
        self.llm_router = get_llm_router()

    def run(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]]
    ) -> LLMGateResult:
        """
        Exécute le LLM Gate sur les candidats.

        Args:
            candidates: Liste de candidats avec (id_a, id_b, scores)
            concepts_cache: Cache des concepts {id: {name, type_fine, ...}}

        Returns:
            LLMGateResult avec verdicts et paires bloquées
        """
        result = LLMGateResult()

        if not self.config.enabled or not candidates:
            return result

        start_time = datetime.utcnow()

        # Batching
        batches = self._create_batches(candidates, concepts_cache)
        logger.info(f"[LLM_GATE] Processing {len(candidates)} candidates in {len(batches)} batches")

        for batch_idx, batch in enumerate(batches):
            try:
                verdicts = self._process_batch(batch, batch_idx)
                result.verdicts.extend(verdicts)
                result.total_calls += 1

                # Classifier les verdicts
                for v in verdicts:
                    pair = (v.source_id, v.target_id)

                    if v.decision == "DISTINCT" and v.confidence >= self.config.distinct_confidence_threshold:
                        result.blocked_pairs.add(pair)
                        logger.info(f"[LLM_GATE] BLOCKED: {v.source_name} ↔ {v.target_name} ({v.reason})")

                    elif v.decision == "MERGE" and v.confidence < self.config.merge_confidence_threshold:
                        result.low_confidence_pairs.add(pair)

            except Exception as e:
                error_msg = f"Batch {batch_idx} failed: {e}"
                result.errors.append(error_msg)
                logger.error(f"[LLM_GATE] {error_msg}")

        result.total_latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        logger.info(
            f"[LLM_GATE] Complete: {len(result.verdicts)} verdicts, "
            f"{len(result.blocked_pairs)} blocked, "
            f"{result.total_calls} calls, {result.total_latency_ms:.0f}ms"
        )

        return result

    def _create_batches(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Crée des batches de paires pour le LLM."""
        enriched = []

        for c in candidates:
            id_a = c.get("id_a") or c[0]
            id_b = c.get("id_b") or c[1]

            concept_a = concepts_cache.get(id_a, {})
            concept_b = concepts_cache.get(id_b, {})

            enriched.append({
                "id_a": id_a,
                "id_b": id_b,
                "name_a": concept_a.get("name", id_a),
                "name_b": concept_b.get("name", id_b),
                "type_a": concept_a.get("type_fine", "unknown"),
                "type_b": concept_b.get("type_fine", "unknown"),
            })

        # Split en batches
        batches = []
        for i in range(0, len(enriched), self.config.batch_size):
            batches.append(enriched[i:i + self.config.batch_size])

        return batches

    def _process_batch(
        self,
        batch: List[Dict[str, Any]],
        batch_idx: int
    ) -> List[LLMMergeVerdict]:
        """Traite un batch via le LLM."""
        # Préparer le JSON des paires
        pairs_for_prompt = [
            {
                "index": i,
                "concept_a": {"name": p["name_a"], "type": p["type_a"]},
                "concept_b": {"name": p["name_b"], "type": p["type_b"]}
            }
            for i, p in enumerate(batch)
        ]

        pairs_json = json.dumps(pairs_for_prompt, indent=2, ensure_ascii=False)
        prompt = self.PROMPT_TEMPLATE.format(pairs_json=pairs_json)

        # Appel LLM via router (utilise burst si actif, sinon OpenAI)
        messages = [{"role": "user", "content": prompt}]

        response = self.llm_router.complete(
            task_type=TaskType.SHORT_ENRICHMENT,  # Utilise le modèle enrichment
            messages=messages,
            temperature=0.1,
            max_tokens=1500
        )

        # Parser la réponse JSON
        return self._parse_llm_response(response, batch)

    def _parse_llm_response(
        self,
        response: str,
        batch: List[Dict[str, Any]]
    ) -> List[LLMMergeVerdict]:
        """Parse la réponse JSON du LLM."""
        verdicts = []

        try:
            # Extraire le JSON de la réponse
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            data = json.loads(response)

            for item in data:
                idx = item.get("pair_index", 0)
                if idx < len(batch):
                    pair = batch[idx]
                    verdicts.append(LLMMergeVerdict(
                        source_id=pair["id_a"],
                        target_id=pair["id_b"],
                        source_name=pair["name_a"],
                        target_name=pair["name_b"],
                        decision=item.get("decision", "DISTINCT").upper(),
                        confidence=float(item.get("confidence", 0.5)),
                        reason=item.get("reason", "")
                    ))

        except json.JSONDecodeError as e:
            logger.error(f"[LLM_GATE] JSON parse error: {e}")
            logger.debug(f"[LLM_GATE] Raw response: {response[:500]}")
            # Fallback: marquer toutes les paires comme low-confidence
            for pair in batch:
                verdicts.append(LLMMergeVerdict(
                    source_id=pair["id_a"],
                    target_id=pair["id_b"],
                    source_name=pair["name_a"],
                    target_name=pair["name_b"],
                    decision="MERGE",
                    confidence=0.5,  # Low confidence = pas d'auto-merge
                    reason="LLM parse error, defaulting to cautious"
                ))

        return verdicts


# Factory function
def get_llm_merge_gate(config: Optional[LLMGateConfig] = None) -> LLMMergeGate:
    """Get LLM Merge Gate instance."""
    return LLMMergeGate(config)
```

### Phase 2 : Intégration dans CorpusERPipeline

**Modifications dans `corpus_er_pipeline.py`** :

```python
# Imports à ajouter
from knowbase.entity_resolution.llm_merge_gate import (
    LLMMergeGate, LLMGateConfig, LLMGateResult, get_llm_merge_gate
)

# Dans __init__
self.llm_gate = get_llm_merge_gate()

# Dans run(), après l'étape 5 (pruning) :

# Step 5.5: LLM Merge Gate
if self.llm_gate.config.enabled and pruned:
    gate_result = self.llm_gate.run(
        candidates=[{"id_a": c.id_a, "id_b": c.id_b} for c in pruned],
        concepts_cache=self._concepts_cache
    )

    # Filtrer les paires bloquées par le LLM
    pruned = [
        c for c in pruned
        if (c.id_a, c.id_b) not in gate_result.blocked_pairs
        and (c.id_b, c.id_a) not in gate_result.blocked_pairs
    ]

    # Marquer les paires low-confidence pour PROPOSE_ONLY
    self._low_confidence_pairs = gate_result.low_confidence_pairs

    stats.llm_gate_calls = gate_result.total_calls
    stats.llm_gate_blocked = len(gate_result.blocked_pairs)
    stats.llm_gate_latency_ms = gate_result.total_latency_ms

    logger.info(
        f"[CorpusER] LLM Gate: {len(gate_result.blocked_pairs)} blocked, "
        f"{len(pruned)} remaining"
    )
```

### Phase 3 : Modification de _decide_v2

```python
def _decide_v2(self, scores: MergeScores, pair_ids: Tuple[str, str]) -> Tuple[DecisionType, str]:
    """
    PATCH-ER-05 + LLM Gate: Decision function v2.
    """
    # Si le LLM a marqué cette paire comme low-confidence, forcer PROPOSE_ONLY
    if hasattr(self, '_low_confidence_pairs') and pair_ids in self._low_confidence_pairs:
        return DecisionType.PROPOSE_ONLY, "llm_low_confidence"

    # ... reste de la logique existante ...
```

---

## Métriques et Observabilité

### Nouvelles Stats à Ajouter

```python
# Dans CorpusERStats
llm_gate_calls: int = 0
llm_gate_blocked: int = 0
llm_gate_low_confidence: int = 0
llm_gate_latency_ms: float = 0.0
```

### Logs Attendus

```
[LLM_GATE] Processing 45 candidates in 3 batches
[LLM_GATE] BLOCKED: SAP S/4HANA ↔ SAP HANA (produits différents)
[LLM_GATE] BLOCKED: Active-passive setup ↔ Active-active setup (configurations opposées)
[LLM_GATE] Complete: 45 verdicts, 2 blocked, 3 calls, 4523ms
[CorpusER] LLM Gate: 2 blocked, 43 remaining
```

---

## Plan d'Exécution

| Étape | Tâche | Effort |
|-------|-------|--------|
| 1 | Créer `llm_merge_gate.py` avec classe LLMMergeGate | 1h |
| 2 | Ajouter stats LLM Gate dans `types.py` | 15min |
| 3 | Intégrer le gate dans `corpus_er_pipeline.py` | 30min |
| 4 | Modifier `_decide_v2()` pour respecter low-confidence | 15min |
| 5 | Tests manuels avec les 3 cas problématiques | 30min |
| 6 | Exporter dans `__init__.py` | 5min |

**Total estimé : ~2h30**

---

## Validation

### Test des 3 Cas Problématiques

Après implémentation, vérifier que :

1. **SAP S/4HANA ↔ SAP HANA** → BLOCKED (DISTINCT)
2. **Active-passive ↔ Active-active** → BLOCKED (DISTINCT)
3. **HTTPS inbound ↔ HTTPS outbound** → BLOCKED (DISTINCT)

### Test des Cas Légitimes

Vérifier que ces merges passent toujours :

1. **Data-at-rest ↔ Data at rest** → MERGE
2. **WAF ↔ Web Application Firewall** → MERGE
3. **Single-tenant ↔ Single Tenant** → MERGE

---

## Évolutions Futures (V2/V3)

| Version | Feature | Quand |
|---------|---------|-------|
| V1.1 | Dashboard des verdicts LLM dans l'admin | Si besoin visibilité |
| V2 | Zone grise explicite + defer | Si trop de PROPOSE_ONLY |
| V2.1 | UI Human Airbag pour cas ciblés | Si taux erreur > 5% |
| V3 | Watchlist + Impact Score + Réévaluation | Si corpus > 10K concepts |
