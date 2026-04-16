# ADR : Configuration LLM par usage — Version challengee

*Date : 16 avril 2026*
*Statut : Propose (v2 — apres review ChatGPT + Claude)*
*Base : ADR v1 du 16/04 + analyse critique 9 points ChatGPT*

## 1. Objectif

Remplacer la configuration globale des LLM par un systeme **deterministe, tracable et robuste**, base sur :

```
Usage logique → Contrat d'usage → Runtime eligible → Binding actif
```

Ce systeme doit garantir :
- Aucune regression silencieuse
- Reproductibilite benchmark parfaite
- Isolation stricte entre batch et temps reel
- Compatibilite avec les invariants OSMOSIS (Graph-first, evidence-first)

---

## 2. Les 4 couches

### 2.1 Couche 1 — Usage logique (granularite reelle)

On abandonne les usages trop larges.

**Search (temps reel)**
- `search_simple` (Q&A direct)
- `search_crossdoc` (comparaison multi-doc)
- `search_tension` (detection contradictions)
- `search_verify` (validation stricte)

**Ingestion / post-import (batch)**
- `claim_extraction`
- `entity_resolution` (canonicalisation)
- `relation_extraction` (C4)
- `crossdoc_reasoning` (C6)
- `perspective_generation`

**Benchmark**
- `judge_primary` (M-Prometheus)
- `ragas_eval`

**Autres**
- `classification` (oui/non rapide)
- `vision_analysis` (images PDF/PPTX)
- `atlas_generation` (contenu narratif)
- `enrichment` (facettes, slots)

Regle : un usage = une responsabilite homogene + un contrat stable.

### 2.2 Couche 2 — Contrat d'usage

Chaque usage definit ses contraintes explicitement :

```yaml
search_simple:
  latency: "<3s"
  deterministic: false
  structured_output: false
  fallback_allowed: true
  critical: true
  batch: false

search_tension:
  latency: "<5s"
  deterministic: medium
  structured_output: true
  fallback_allowed: false
  critical: true
  batch: false

claim_extraction:
  latency: "batch"
  deterministic: high
  structured_output: true (JSON claims)
  fallback_allowed: false
  critical: true
  batch: true

perspective_generation:
  latency: "batch"
  deterministic: low
  structured_output: false
  fallback_allowed: true
  critical: false
  batch: true

judge_primary:
  latency: "<10s"
  deterministic: high
  structured_output: true (YES/NO per claim)
  fallback_allowed: false
  critical: true
  batch: false
  note: "Doit etre le MEME modele entre runs pour comparaison"
```

### 2.3 Couche 3 — Runtime eligible (capabilities)

Matrice de compatibilite obligatoire (corrigee apres tests reels 14-16 avril) :

| Runtime | JSON strict | Long context | Parallel | Stable | Latence |
|---------|-------------|-------------|----------|--------|---------|
| Ollama local | ⚠️ (degenere parfois) | ⚠️ (512 tok embeddings) | ❌ (sequentiel) | ✅ | lent |
| vLLM local | ✅ (sans chunked prefill) | ✅ | ✅ (16 seq) | ✅ | rapide |
| vLLM EC2 Spot | ✅ | ✅ | ✅ (16 seq) | ⚠️ (evictions) | rapide |
| DeepInfra | ✅ | ✅ | ✅ (200 concurrent) | ✅ | rapide |
| OpenAI | ✅ | ✅ | ⚠️ (rate limits) | ✅ | rapide |

Regle : un runtime est selectionnable uniquement si compatible avec le contrat.

### 2.4 Couche 4 — Binding actif

Ce que l'utilisateur configure dans l'UI admin :

```yaml
search_simple:
  runtime: deepinfra
  model: Qwen/Qwen3-235B-A22B-Instruct-2507

claim_extraction:
  runtime: deepinfra
  model: Qwen/Qwen2.5-72B-Instruct

judge_primary:
  runtime: ollama
  model: m-prometheus-14b

embeddings:
  runtime: local_gpu
  model: intfloat/multilingual-e5-large
  version: v3
```

---

## 3. Politique de degradation (remplace les fallbacks implicites)

| Type | Description |
|------|-------------|
| **fail-fast** | Erreur immediate, message explicite |
| **retry** | Tentative alternative meme runtime (3x max) |
| **fallback autorise** | Autre runtime, explicitement configure |
| **fallback interdit** | Strict, pas de substitution |

Exemples :
```yaml
search_simple:
  fallback_allowed: true
  fallback_order: [deepinfra, ollama]

search_tension:
  fallback_allowed: false

claim_extraction:
  fallback_allowed: false

perspective_generation:
  fallback_allowed: true
  fallback_order: [ollama]
```

Regle : aucun fallback implicite. Tout est explicite.

---

## 4. Politique Burst (corrigee)

Le burst ne s'applique JAMAIS aux usages temps reel.

```yaml
burst_policy:
  enabled: true
  applies_to:
    - claim_extraction
    - entity_resolution
    - relation_extraction
    - crossdoc_reasoning
    - perspective_generation
    - embeddings (si TEI EC2)
  excludes:
    - search_simple
    - search_crossdoc
    - search_tension
    - search_verify
    - judge_primary
    - atlas_generation
```

Regle : le burst est un override batch-only, opt-in par usage.

---

## 5. Gestion des embeddings (verrou critique)

### 5.1 Versioning obligatoire

```yaml
embedding_config:
  model: intfloat/multilingual-e5-large
  version: v3
  dimensions: 1024
  runtime: local_gpu
  status: active | pending_reindex
```

### 5.2 Regles

- Interdiction de melanger embeddings anciens et nouveaux dans la meme collection
- Changement de modele → etat `pending_reindex` → alerte UI bloquante
- Re-indexation = chunks Qdrant + claim embeddings Neo4j
- L'etat `pending_reindex` bloque le search (incoherence vecteurs)

### 5.3 Modeles candidats futurs

| Modele | Params | MTEB multilingual | Dimensions | Context |
|--------|--------|-------------------|------------|---------|
| e5-large (actuel) | 560M | ~58 | 1024 | 512 |
| Jina v3 | 570M | ~62 | 1024 | 8192 |
| BGE-M3 | 568M | ~62 | 1024 | 8192 |
| Qwen3-Embedding-8B (DeepInfra) | 8B | 70.58 | flexible | 32K |

---

## 6. Isolation batch vs temps reel

- Usages `batch: true` et `batch: false` ne partagent pas le meme pool d'execution
- Config independante par usage
- Un job batch en cours ne degrade jamais le search live

---

## 7. Snapshot obligatoire (benchmark & jobs)

### 7.1 A chaque run benchmark

```json
{
  "timestamp": "2026-04-16T10:11:11Z",
  "llm_config_snapshot": {
    "search_simple": {"runtime": "deepinfra", "model": "Qwen/Qwen3-235B-A22B-Instruct-2507"},
    "judge_primary": {"runtime": "ollama", "model": "m-prometheus-14b"},
    "embeddings": {"runtime": "local_gpu", "model": "e5-large", "version": "v3"}
  },
  "scores": {...}
}
```

### 7.2 Regle

Un benchmark sans snapshot = invalide. La comparaison entre runs n'est valide que si les snapshots sont identiques pour les usages evalues.

---

## 8. Migration

1. Creer table PostgreSQL `llm_usage_config` (1 ligne par usage)
2. Migrer la config YAML existante vers PostgreSQL
3. Creer la page admin frontend (bindings + contrats + alertes)
4. Refactorer le llm_router pour lire le mapping PostgreSQL
5. Supprimer les modes globaux (NORMAL, PARTIAL_LOCAL, FULL_LOCAL)
6. Supprimer les fallbacks implicites OpenAI/Anthropic
7. Ajouter le snapshot config dans les rapports benchmark
8. Tests end-to-end par usage

---

## 9. Presets (simplification UX)

Pour eviter la complexite, proposer des presets pre-configures :

| Preset | Description | Cout estime |
|--------|-------------|-------------|
| **Eco** | Tout local (Ollama qwen2.5:14b), lent | $0/mois |
| **Balanced** | DeepInfra pour batch/synthese, local pour juge/embeddings | ~$15-30/mois |
| **Max Quality** | DeepInfra 235B partout + GPT-4o vision | ~$50/mois |

L'utilisateur choisit un preset puis ajuste individuellement si besoin.

---

## 10. Points de vigilance

1. **Contention GPU local** : scheduler a prevoir (hors scope ADR)
2. **Latence variable cloud** : monitoring cockpit
3. **Chemins de code non migres** : audit grep exhaustif avant migration
4. **Jobs longs** : snapshot config fige au lancement du job, pas de changement a chaud
