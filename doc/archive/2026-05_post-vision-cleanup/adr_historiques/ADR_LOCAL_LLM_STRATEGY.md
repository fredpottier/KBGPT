# ADR : Stratégie LLM Local — Réduction dépendance cloud

*Date : 14 avril 2026*
*Statut : Validé par tests*
*Hardware local : AMD Ryzen 9 9950X3D (32 cores) + RTX 5070 Ti (15.9 GB VRAM) + 61.7 GB RAM*

## Contexte

OSMOSIS dépend actuellement de 3 fournisseurs LLM externes :
- **Anthropic Haiku** : synthèse search (~$0.005/requête)
- **OpenAI gpt-4o-mini** : juge benchmark RAGAS + T2/T5 (~$0.003/eval)
- **EC2 Spot vLLM** : burst extraction ClaimFirst (~$0.40/h, evictions fréquentes)

Coût constaté : $15 Anthropic + $10 OpenAI épuisés en <24h de benchmarks + import.

## Découverte : tout peut tourner en local

Tests LlmFit + benchmarks manuels validés le 14 avril 2026 :

### Modèles validés sur RTX 5070 Ti (15.9 GB VRAM)

| Modèle | VRAM | tok/s | Score | Fit | Usage OSMOSIS |
|--------|------|-------|-------|-----|---------------|
| **Qwen2.5-14B-Instruct-AWQ** | 7.4 GB (56%) | 66.7 | 92 | Perfect | Synthèse search, ClaimFirst |
| **Qwen2.5-14B-Instruct-GPTQ-Int4** | 7.4 GB (56%) | 66.7 | 92 | Perfect | Alternative AWQ |
| **M-Prometheus-14B (Q4_K_M)** | 9.1 GB | ~15* | N/A | Perfect | Juge benchmark T2/T5 |
| **Qwen3.5-9B (Q8_0)** | 10.7 GB | ~10* | N/A | OK | Synthèse alternative |
| **apolo13x/Qwen3.5-27B-NVFP4** | 13.4 GB (94%) | 39.3 | 84 | Perfect | Synthèse haute qualité |
| **QuantTrio/Qwen3.5-27B-AWQ** | ~14 GB | ~50** | ~90 | Tight | vLLM local uniquement |

*tok/s Ollama (séquentiel). **Estimé vLLM local.

### Comparaison avec les services cloud actuels

| Usage | Cloud actuel | Alternative locale | Gain |
|-------|-------------|-------------------|------|
| Synthèse search | Haiku ($0.005/req) | Qwen2.5-14B-AWQ (66 tok/s) | **$0/req, plus rapide** |
| Juge T2/T5 | gpt-4o-mini ($0.003/eval) | M-Prometheus-14B (local) | **$0/eval, validé** |
| Juge RAGAS | gpt-4o-mini | M-Prometheus-14B | **$0/eval** |
| Burst ClaimFirst | EC2 vLLM ($0.40/h) | vLLM local (Qwen2.5-14B) | **$0/h** |
| Résumés tensions | Haiku | Qwen2.5-14B ou skip | **$0** |

## Architecture cible : 100% local

### Profil 1 — Synthèse search (usage quotidien)

```
Ollama local → Qwen2.5-14B-AWQ (7.4 GB, 66 tok/s)
  OU
Ollama local → Qwen3.5-27B-NVFP4 (13.4 GB, 39 tok/s) [meilleure qualité]
```

Le llm_router d'OSMOSIS utilise déjà Ollama comme fallback. Il suffit de le configurer comme provider **principal** (pas fallback).

### Profil 2 — Benchmark (ponctuel)

```
Ollama local → M-Prometheus-14B (9.1 GB) [juge T2/T5]
  swap automatique avec
Ollama local → Qwen2.5-14B-AWQ [synthèse des réponses à évaluer]
```

Ollama swap les modèles automatiquement — chargement ~5-10s entre les deux.

Configuration : `T2T5_JUDGE_PROVIDER=ollama`, `T2T5_JUDGE_MODEL_NAME=m-prometheus-14b`

Prompt evidence-based (implémenté) : le juge vérifie YES/NO par claim, le code calcule le score de manière déterministe.

### Profil 3 — Burst ClaimFirst (import massif)

**Option A — vLLM local (recommandé)** :
```bash
# Lancer vLLM local sur RTX 5070 Ti
docker run --gpus all -p 8000:8000 \
  vllm/vllm-openai:v0.9.2 \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --quantization awq_marlin \
  --gpu-memory-utilization 0.85 \
  --max-model-len 16384 \
  --max-num-seqs 16
```
- Débit batch : 66 tok/s × 16 séquences = ~1000 tok/s agrégé
- Estimation 82 docs : ~1h30-2h
- GPU local 100% occupé pendant le burst

**Option B — EC2 Spot (si GPU local occupé)** :
- Garder le stack CloudFormation comme backup
- Utile si burst pendant la journée de travail (GPU partagé)

**Option C — Ollama séquentiel (lent mais simple)** :
- Qwen2.5-14B via Ollama, 1 requête à la fois
- Estimation 82 docs : ~5-8h (acceptable en nuit/weekend)

### Profil 4 — Post-import (canonicalisation, perspectives, facettes)

```
Ollama local → Qwen2.5-14B-AWQ (canonicalisation LLM, labellisation perspectives)
  OU
Ollama local → Qwen3.5-27B-NVFP4 (meilleure qualité pour les labels)
```

Le post-import fait ~500 appels LLM (canonicalisation) + ~60 (perspectives) + ~70 (facettes). Avec Qwen2.5-14B à 66 tok/s, c'est ~10-15 min.

## Qwen3.5-27B vs Qwen2.5-14B : quand utiliser lequel ?

| Critère | Qwen2.5-14B-AWQ | Qwen3.5-27B-NVFP4 |
|---------|-----------------|-------------------|
| Vitesse | **66.7 tok/s** | 39.3 tok/s |
| Qualité synthèse | Bonne | **Meilleure** (27B + Qwen3.5) |
| Français | Bon | **Excellent** (201 langues) |
| VRAM restante | 8.5 GB (cohabitation possible) | 2.5 GB (pas de cohabitation) |
| Batch/parallélisme | **16 séquences vLLM** | ~4 séquences max |
| Usage recommandé | **Burst, batch, défaut** | **Synthèse premium, questions complexes** |

### Recommandation

- **Par défaut** : Qwen2.5-14B-AWQ (rapide, léger, permet cohabitation)
- **Questions complexes / synthèse publique** : Qwen3.5-27B-NVFP4 (meilleure qualité, plus lent)
- **Juge** : M-Prometheus-14B (spécialisé évaluation, multilingue)
- **EC2** : uniquement si burst + utilisation PC simultanée nécessaire

## Impact financier

| Scénario | Coût cloud/mois | Coût local/mois | Économie |
|----------|----------------|----------------|----------|
| 10 benchmarks complets | ~$50 (OpenAI + Anthropic) | **$0** | 100% |
| 5 imports corpus (burst) | ~$20 (EC2 spot × 10h) | **~$5 électricité** | 75% |
| Usage search quotidien | ~$30 (Haiku × 6000 req) | **$0** | 100% |
| **Total mensuel** | **~$100** | **~$5** | **95%** |

## Migration progressive

1. ✅ **M-Prometheus-14B** comme juge T2/T5 (implémenté, validé)
2. 🔜 **Qwen2.5-14B-AWQ sur Ollama** comme synthétiseur principal (remplace Haiku)
3. 🔜 **vLLM local** pour le burst ClaimFirst (remplace EC2)
4. 📋 **M-Prometheus** comme juge RAGAS (remplace gpt-4o-mini pour l'évaluation)
5. 📋 **Qwen3.5-27B** comme synthétiseur premium (questions complexes)

## Mode "100% Local" — Spécification fonctionnelle

### Besoin

Un paramètre dans la page admin d'OSMOSIS qui, lorsqu'il est activé, bascule **toutes** les tâches LLM sur des modèles locaux (Ollama / vLLM local). Seule exception : **GPT-4o vision** pour l'analyse d'images pendant le burst (extraction des caches depuis les PDF/PPTX avec éléments visuels).

Quand ce mode est activé :
- Aucun appel Anthropic (Haiku)
- Aucun appel OpenAI (gpt-4o-mini)
- Aucun appel vers une EC2 distante
- Tout passe par le GPU local (RTX 5070 Ti, 16 GB VRAM)
- Exception unique : GPT-4o vision pour le burst image (si activé)

### Inventaire des tâches LLM et leur mapping local

| Tâche | Provider actuel | Modèle local | VRAM | Moment |
|-------|----------------|-------------|------|--------|
| **Synthèse search** | Haiku (Anthropic) | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Temps réel (chaque requête) |
| **Résumé tensions** | Haiku (Anthropic) | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Temps réel (skip si benchmark) |
| **Extraction claims (ClaimFirst)** | vLLM EC2 (Qwen2.5-14B) | Qwen2.5-14B-AWQ via vLLM local | 7.4 GB | Batch (import) |
| **Embeddings (TEI)** | TEI EC2 (e5-large GPU) | e5-large CPU local (SentenceTransformers) | 0 GB GPU | Batch (import) |
| **Canonicalisation** | vLLM EC2 ou Ollama | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Post-import |
| **Facettes (extraction)** | gpt-4o (OpenAI) | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Post-import |
| **Facettes (consolidation)** | gpt-4o (OpenAI) | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Post-import |
| **Perspectives (labelling)** | Haiku ou Ollama | Qwen2.5-14B-AWQ via Ollama | 7.4 GB | Post-import |
| **Atlas (content)** | Haiku (Anthropic) | Qwen3.5-27B-NVFP4 via Ollama | 13.4 GB | Post-import (ponctuel) |
| **Juge T2/T5** | gpt-4o-mini (OpenAI) | M-Prometheus-14B via Ollama | 9.1 GB | Benchmark |
| **Juge RAGAS** | gpt-4o-mini (OpenAI) | M-Prometheus-14B via Ollama | 9.1 GB | Benchmark |
| **Analyse images burst** | GPT-4o vision | **GPT-4o vision (exception)** | 0 local | Burst |
| **NER Domain Pack** | GLiNER sidecar Docker | GLiNER sidecar Docker (inchangé) | ~1 GB CPU | Post-import |

### Le problème de la VRAM partagée (16 GB)

Contrairement à l'EC2 (24 GB L4 = vLLM + TEI en parallèle), la RTX 5070 Ti a 16 GB et ne peut pas tout garder en VRAM simultanément.

**Modèles en compétition :**

| Modèle | VRAM | Quand |
|--------|------|-------|
| Qwen2.5-14B-AWQ | 7.4 GB | Search, ClaimFirst, post-import |
| M-Prometheus-14B | 9.1 GB | Benchmarks uniquement |
| Qwen3.5-27B-NVFP4 | 13.4 GB | Synthèse premium, Atlas |
| e5-large (embeddings) | ~2 GB GPU (ou CPU) | Import, bridge |

**Combinaisons possibles en VRAM (16 GB) :**

| Combo | VRAM totale | Faisable ? |
|-------|-----------|-----------|
| Qwen2.5-14B + e5-large GPU | 9.4 GB | ✅ Confortable |
| Qwen2.5-14B seul | 7.4 GB | ✅ e5-large en CPU |
| M-Prometheus seul | 9.1 GB | ✅ Benchmark mode |
| Qwen3.5-27B seul | 13.4 GB | ✅ Synthèse premium |
| Qwen2.5-14B + M-Prometheus | 16.5 GB | ❌ Dépasse |
| Qwen3.5-27B + n'importe quoi | >15 GB | ❌ |

### Les 4 cas d'usage et leur modèle unique

Chaque cas d'usage n'utilise qu'**un seul LLM à la fois**. Pas de cohabitation nécessaire, pas de swap en cours de phase. Le chargement/déchargement ne se fait qu'**entre** les phases, pas pendant.

#### 1. SEARCH + Atlas (usage quotidien)
```
GPU : Qwen2.5-14B-AWQ (7.4 GB) via Ollama — synthèse, tensions, Atlas labels
  OU Qwen3.5-27B-NVFP4 (13.4 GB) via Ollama — synthèse premium / Atlas content
```
- **Un seul modèle chargé**, pas de swap pendant la session
- L'utilisateur choisit le modèle dans les settings (défaut = 14B, premium = 27B)
- Les embeddings (e5-large) tournent en CPU (SentenceTransformers), pas de conflit VRAM
- Pas de parallélisation nécessaire : 1 question → 1 réponse séquentielle

#### 2. IMPORT (burst + ClaimFirst + post-import)
```
GPU : Qwen2.5-14B-AWQ via vLLM local (7.4 GB)
CPU : e5-large via SentenceTransformers (embeddings)
```
- **Parallélisation nécessaire** : vLLM gère 16 séquences concurrentes pour le ClaimFirst
- Un seul modèle LLM chargé pendant tout l'import (Qwen2.5-14B)
- Les embeddings sont séparés du LLM (CPU vs GPU) → pas de conflit
- GPT-4o vision = seul appel cloud (analyse d'images, non parallélisable avec le LLM local)
- Post-import (canonicalisation, facettes, perspectives) : même modèle, même GPU, séquentiel
- **Pas de swap** pendant toute la phase import+post-import

#### 3. BENCHMARK
```
Phase 1 — Collecte : Qwen2.5-14B via Ollama (synthèse des réponses)
  → swap (~10s)
Phase 2 — Évaluation : M-Prometheus-14B via Ollama (juge)
```
- Le benchmark a 2 phases distinctes avec 2 modèles différents
- **Un seul swap** entre la collecte et l'évaluation
- Chaque phase est parallélisée (15 concurrents pour la collecte, séquentiel pour le juge)
- Le swap de 10s est négligeable sur un benchmark de 10-20 min

#### 4. ATLAS (génération narrative)
```
GPU : Qwen3.5-27B-NVFP4 (13.4 GB) via Ollama — meilleure qualité narrative
  OU Qwen2.5-14B-AWQ (7.4 GB) — plus rapide
```
- Séquentiel : 1 appel LLM par section, 12 topics × 2-3 sections = ~36 appels
- **Pas de parallélisation**, pas de swap
- Le 27B est préférable ici pour la qualité du texte narratif

### Résumé : pas de problème de cohabitation

| Cas d'usage | Modèle GPU | Parallélisme | Swap pendant phase ? |
|-------------|-----------|-------------|---------------------|
| Search | Qwen 14B ou 27B | Non | Non |
| Import | Qwen 14B (vLLM) | Oui (16 séq.) | Non |
| Benchmark | Qwen 14B → M-Prometheus | Oui (collecte) | **1 seul swap** entre phases |
| Atlas | Qwen 27B ou 14B | Non | Non |

**Conclusion** : le seul moment où un swap est nécessaire est entre les phases du benchmark (collecte → évaluation). Tous les autres cas n'utilisent qu'un modèle du début à la fin. La contrainte VRAM (16 GB) n'est PAS un problème car on ne charge jamais 2 modèles en même temps.

### vLLM local vs Ollama : quand utiliser quoi ?

| Critère | Ollama | vLLM local |
|---------|--------|-----------|
| **Concurrence** | 1 requête à la fois | 16+ séquences parallèles |
| **Setup** | Déjà installé, `ollama run` | Docker + config |
| **Swap modèles** | Automatique (5-10s) | Restart container nécessaire |
| **Usage** | Search (1 req), post-import (séquentiel) | **Burst ClaimFirst (batch)** |
| **tok/s** | ~66 tok/s (séquentiel) | ~66 tok/s × 16 séquences |

**Recommandation** :
- **Ollama** pour tout sauf le burst : plus simple, swap auto, pas de config
- **vLLM local** uniquement pour le burst ClaimFirst (batch parallèle)
- Pas besoin de TEI Docker local : les embeddings passent en CPU (SentenceTransformers)

### Implémentation : le "Mode Local" dans l'admin

#### Paramètre

```python
# Stocké en base PostgreSQL (table settings) ou Redis
OSMOSIS_LOCAL_MODE = True/False
```

Accessible depuis : **Admin > Settings > LLM Configuration**

Toggle : "Mode 100% local (GPU RTX)"
- Description : "Toutes les tâches LLM utilisent le GPU local. Aucun appel cloud sauf GPT-4o vision pour l'analyse d'images."

#### Impact sur le LLM Router

Le `llm_router.py` doit vérifier ce paramètre avant chaque appel :

```python
def complete(self, task_type, messages, ...):
    if get_setting("OSMOSIS_LOCAL_MODE"):
        # Forcer Ollama local pour TOUT sauf vision
        if task_type != TaskType.VISION_ANALYSIS:
            return self._call_ollama(model="qwen2.5:14b", messages=messages, ...)
    
    # Sinon, routing normal (burst > ollama > openai > anthropic)
    ...
```

#### Impact sur les benchmarks

```python
# t2t5_diagnostic.py
if get_setting("OSMOSIS_LOCAL_MODE"):
    LLM_JUDGE_PROVIDER = "ollama"
    LLM_JUDGE_MODEL = "m-prometheus-14b"

# ragas_diagnostic.py  
if get_setting("OSMOSIS_LOCAL_MODE"):
    # Utiliser M-Prometheus au lieu de gpt-4o-mini pour RAGAS eval
    os.environ["OPENAI_API_KEY"] = ""  # Forcer le skip OpenAI
    # OU adapter run_ragas_evaluation pour supporter Ollama
```

#### Impact sur le burst

```python
if get_setting("OSMOSIS_LOCAL_MODE"):
    # Démarrer vLLM local au lieu de provisionner EC2
    subprocess.run([
        "docker", "run", "-d", "--gpus", "all", 
        "-p", "8000:8000",
        "vllm/vllm-openai:v0.9.2",
        "--model", "Qwen/Qwen2.5-14B-Instruct-AWQ",
        "--quantization", "awq_marlin",
        ...
    ])
    # Le burst_orchestrator pointe vers localhost:8000
```

### Scénario de cohabitation : une journée type

```
08:00 — L'utilisateur démarre OSMOSIS
  → Ollama charge Qwen2.5-14B-AWQ (7.4 GB)
  → Mode SEARCH actif

09:00 — L'utilisateur pose des questions
  → Qwen2.5-14B répond via Ollama (66 tok/s)
  → Embeddings via CPU (SentenceTransformers)

10:00 — L'utilisateur lance un import (20 docs)
  → Le système bascule en mode IMPORT
  → Ollama garde Qwen2.5-14B (même modèle)
  → Si burst activé : lance vLLM local (Ollama s'arrête temporairement)
  → GPT-4o vision pour les images (seul appel cloud)
  → ClaimFirst : ~30 min pour 20 docs

10:30 — Import terminé, post-import auto
  → Qwen2.5-14B via Ollama (canonicalisation, facettes, perspectives)
  → ~15 min

10:45 — Retour en mode SEARCH
  → L'utilisateur reprend ses questions

18:00 — L'utilisateur lance les benchmarks (fin de journée)
  → Ollama swap vers M-Prometheus-14B (~10s)
  → T2/T5 benchmark (~3 min)
  → Ollama swap vers Qwen2.5-14B pour collecte RAGAS (~10s)
  → Ollama swap vers M-Prometheus pour évaluation RAGAS (~10s)
  → Total swaps : 3 × 10s = 30s de overhead sur ~20 min de benchmark

19:00 — Benchmarks terminés, swap retour vers Qwen2.5-14B
```

### Points d'attention

1. **Le swap Ollama prend 5-10s** — acceptable pour les transitions ponctuelles (search → benchmark), pas pour du swap à chaque requête

2. **vLLM local et Ollama ne peuvent pas cohabiter sur le même GPU** — si vLLM est lancé (burst), Ollama doit être arrêté ou le modèle déchargé

3. **Les embeddings en CPU sont 10x plus lents** qu'en GPU (TEI) — acceptable pour le post-import (<200s) mais pas pour un burst massif si les embeddings sont dans le chemin critique

4. **Le mode local n'empêche pas d'utiliser le cloud** — c'est un toggle, pas un verrouillage. L'utilisateur peut le désactiver à tout moment pour revenir sur Haiku/gpt-4o-mini

5. **GPT-4o vision reste nécessaire** car aucun modèle local open-source n'égale GPT-4o pour l'extraction de contenu depuis des images/diagrammes complexes dans les PDF. C'est la seule dépendance cloud incompressible.

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `src/knowbase/common/llm_router.py` | Ollama comme provider principal (pas fallback) |
| `src/knowbase/api/services/search.py` | `OSMOSIS_SYNTHESIS_PROVIDER=ollama` |
| `benchmark/evaluators/t2t5_diagnostic.py` | ✅ Fait (M-Prometheus support) |
| `benchmark/evaluators/ragas_diagnostic.py` | Remplacer gpt-4o-mini par M-Prometheus local |
| `docker-compose.yml` | ✅ Fait (T2T5_JUDGE_PROVIDER, OLLAMA_URL) |
| `.env` | `OSMOSIS_SYNTHESIS_PROVIDER=ollama`, `OSMOSIS_SYNTHESIS_MODEL=qwen2.5:14b` |
