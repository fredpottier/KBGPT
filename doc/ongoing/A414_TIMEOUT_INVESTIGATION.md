# A4.14 — Investigation wall-clock timeout runtime_v6

**Date** : 2026-05-23
**Source** : analyse code orchestrator.py + bench 50q `run_20260523_070724.json`

## ⚠️ Cadre domain-agnostic
Tous les fixes proposés touchent à l'infrastructure pipeline (timeouts, retries, modèles LLM) — pas au contenu corpus.

---

## TL;DR — Root cause

**`MAX_WALL_CLOCK_S = 60.0`** (orchestrator.py:63) est **trop bas** pour le pipeline runtime_v6 actuel.

| Étape | Durée typique |
|---|---|
| Parse Qwen3-235B (1 call) | 5-15s |
| Parse Qwen3-235B (1 retry sur JSON empty) | +5-30s |
| Plan (déterministe) | <1ms |
| Execute RRF Cypher | 15-50ms |
| Evaluate Qwen3-235B | 5-15s |
| Synthesize DeepSeek-V3.1 sur 50 claims | 30-90s |
| **Total nominal chemin** | **60-150s** |

→ Largement au-dessus du timeout 60s. Sur bench 50q, ~22% des questions terminent en `wall_clock_timeout`.

## Pourquoi 20q sample passait sous le radar

- Questions 1-20 du gold-set = mix factual + comparison "simple" → Parse réussit du 1er coup ~80% des cas
- Questions 21-50 = multi_hop, false_premise, comparison cross-doc → questions plus longues + Parse Qwen3-235B échoue plus souvent → 2e retry → +30s → timeout

C'est la **stratification du gold-set** qui rend le bottleneck timeout visible.

## Configuration actuelle observée

```python
# orchestrator.py
MAX_WALL_CLOCK_S = 60.0  # ← BOTTLENECK
MAX_ITERATIONS = 3       # mais quasiment jamais > 1 sur 50q (timeout avant)

# parse.py
for attempt in range(2):  # 2 attempts si Qwen3-235B JSON empty
    raw = self._invoke_llm(...)  # 5-30s par call
```

## Distribution des timeouts (basée sur audit A4.13)

| Pattern | Fréquence sur 50q | Conséquence |
|---|---|---|
| `terminated_reason=wall_clock_timeout` (iter 0 dépasse 60s) | ~22% (11/50) | ABSTENTION sans réponse |
| `verdict_insufficient_evidence` + sub_goal "(no subject)" | ~14% (7/50) | ABSTENTION, Parse fallback déterministe |
| `Mode=ABSTENTION` total | ~70% (35/50) | gros pourcentage en abstention |

---

## 🚀 Fixes recommandés (par ordre de risque/gain)

### Fix #1 — Augmenter MAX_WALL_CLOCK_S à 180s (5 min effort, faible risque)

**Effort** : 1 ligne (`orchestrator.py:63`)
**Gain attendu** : -10pp questions en timeout, +0.03-0.05pp C1
**Risque** : latence p95 monte à ~200s (déjà 140s en bench RRF). En presales = acceptable.

```python
MAX_WALL_CLOCK_S = 180.0  # de 60 à 180s pour absorber Parse retries + Synthesize 50 claims
```

### Fix #2 — Réduire Parse retries de 2 à 1 (5 min effort, faible risque)

**Effort** : 1 ligne (`parse.py:202`)
**Gain attendu** : -15-30s sur questions où Qwen3-235B retourne empty (35% des cas)
**Risque** : perte de qualité Parse sur 5-10% des questions où retry sauvait (rare avec Qwen3-235B-Instruct-2507 no-thinking mode).

```python
for attempt in range(1):  # un seul attempt — fallback déterministe direct si JSON empty
```

### Fix #3 — Switch Parse vers DeepSeek-V3.1 (1-2j effort, risque moyen)

**Pourquoi maintenant ça devrait marcher** : A4.8 avait régressé car DeepSeek-V3.1 sur Parse produit un `subject_canonical` précis qui sabotait le retrieval LEGACY (filtre exact Cypher `subject_canonical = $subject`). Avec **RRF activé**, le retrieval bypass `subject_canonical` → la régression A4.8 ne s'applique plus.

**Effort** : config llm_models.yaml + revert du rollback A4.8
**Gain attendu** : Parse JSON empty → 0% (vs 30% Qwen3-235B). +0.05-0.10pp C1.
**Risque** : DeepSeek-V3.1 est lent (8-15s par call) vs Qwen3-235B (5-10s). Marginal.

### Fix #4 — Auditer si Parse retries servent vraiment (0.5j effort)

Avant fix #2 ou #3, mesurer : combien de fois le retry Parse 2/2 a sauvé un Parse en succès vs juste consommé 30s pour rien ?
Si retry sauve <5% des questions, l'enlever ne coûte rien.

### Fix #5 — Paralléliser Plan + Execute (1-2j effort, risque moyen)

Actuellement séquentiel : Plan → Execute. Plan est déterministe (ms), pas un goulot.
Mais on pourrait paralléliser **Synthesize avec un GroundingVerifier préparé** pour gagner ~5-10s.
**Probablement pas le gain le plus rentable.**

---

## 🎯 Plan d'action recommandé

**Étape 1 (rapide, 30 min total)** : Appliquer Fix #1 (timeout 180s) + Fix #2 (Parse retries=1).
- Bench 50q post-fix
- Gate : si timeouts <10% ET C1 ≥ 0.32 → Étape 2. Sinon analyser.

**Étape 2 (1-2j)** : Si Étape 1 OK mais C1 toujours < 0.35 → Fix #3 (DeepSeek-V3.1 Parse).
- Bench 50q post-fix.
- Gate : C1 ≥ 0.40 → on a un vrai gain.

**Étape 3 (si Étape 2 OK)** : Re-considérer cross-encoder re-rank ou false_premise detector (P3).

**STOP rule** : à chaque étape, si pas de gain mesurable → STOP runtime_v6, retour roadmap.

---

## Fichiers concernés

- `src/knowbase/runtime_a3/orchestrator.py` : `MAX_WALL_CLOCK_S`
- `src/knowbase/runtime_a3/parse.py` : `range(2)` retries
- `config/llm_models.yaml` : task `knowledge_extraction` (si Fix #3)
- `src/knowbase/runtime_a3/parse.py` : `TaskType.KNOWLEDGE_EXTRACTION` (si Fix #3, revert rollback A4.8 sur Parse uniquement, garder Evaluate sur Qwen3)

## Domain-agnostic check

Tous les fixes sont **infrastructure-level**, sans dépendance corpus :
- Timeout : universel
- Retries : universel
- LLM Parse : universel (DeepSeek-V3.1 multilingue, fonctionne sur médical/réglementaire/aerospace)
