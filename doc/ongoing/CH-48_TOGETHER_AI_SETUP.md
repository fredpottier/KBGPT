# CH-48 — Setup Together AI serverless (procédure 2026-05-09)

**Date** : 2026-05-08 (préparation, lancement prévu 2026-05-09 matin)
**Objectif** : Bake-off Together AI Qwen2.5-72B-Instruct-Turbo vs DeepInfra public.
Cible latence : 132s/q → ~17-25s/q (×6 plus rapide). Valider que la qualité ne régresse pas.

## Pourquoi Together AI

- **DeepInfra Custom LLMs** désactivé temporairement côté provider (cf §10.x ADR)
- **DeepInfra public** trop lent pour Test Armand (132s/q)
- **Together AI serverless** = Qwen2.5-72B-Instruct-Turbo en catalogue, $1.20/M tokens, drop-in OpenAI-compatible
- **3.2× plus cher au token** que DeepInfra public mais **6× plus rapide** + pas de saturation file d'attente publique
- Coût bench global ~$8-10 (vs ~$5 sur DeepInfra public, mais avec 372 questions traitées en 2h vs 4h)

## État du code (préparé 2026-05-08, prêt à activer)

### Modifs déjà commitées

1. **`src/knowbase/runtime_v3/llm_client.py`** :
   - Ajout `TOGETHER_BASE_URL = "https://api.together.xyz/v1"`
   - Ajout `TOGETHER_DEFAULT_MODEL = "Qwen/Qwen2.5-72B-Instruct-Turbo"`
   - `_resolve_endpoint()` étendu : si `TOGETHER_API_KEY` défini → priorité Together AI (avant vLLM/DeepInfra)
   - `model_override` accepté pour Together AI (pas seulement DeepInfra)

2. **`docker-compose.yml`** :
   - Ajout (commenté) des env vars `TOGETHER_API_KEY` + `TOGETHER_RUNTIME_MODEL` sur le service `app`
   - Tant que non décommenté, fallback automatique sur DeepInfra (rétrocompat 100%)

### Scripts préparés

- **`app/scripts/ch48_smoke_together.py`** — smoke test 5q (~1 min, ~$0.05)
- **`app/scripts/diag_v4_stratified_breakdown.py`** — bench micro 30q stratifié existant
- **`logs/bench_payload_robustness.json`** + `_t2t5_v41.json` + `_ragas_v41.json` — payloads bench global

## Procédure d'activation (à faire demain matin)

### Étape 1 — Récupérer une API Key Together AI

1. Aller sur https://together.ai et créer un compte (sign-up gratuit, $5 free credit)
2. Settings → API Keys → Create new key
3. Copier la clé (format `tgp_v1_...`)

### Étape 2 — Configurer l'environnement

Dans `C:\Projects\SAP_KB\.env` (créer la variable si absente) :

```bash
TOGETHER_API_KEY=tgp_v1_xxxxxxxxxxxxxxxxxxxx
```

Dans `docker-compose.yml`, **décommenter** les 2 lignes du service `app` :

```yaml
      TOGETHER_API_KEY: ${TOGETHER_API_KEY}
      TOGETHER_RUNTIME_MODEL: Qwen/Qwen2.5-72B-Instruct-Turbo
```

### Étape 3 — Recreate l'app pour charger les env vars

```powershell
docker compose -f docker-compose.infra.yml -f docker-compose.yml -f docker-compose.monitoring.yml up -d --force-recreate app
```

Attendre health OK (~25s) :

```bash
until curl -s http://localhost:8000/api/runtime_v4/health | grep -q "ok"; do sleep 3; done
```

### Étape 4 — Smoke test (1-2 min, ~$0.05)

```powershell
docker exec knowbase-app python /app/scripts/ch48_smoke_together.py
```

**Critères go/no-go** :
- ✅ 5/5 questions retournent `decision=ANSWER`
- ✅ `wall mean < 35s` (cible Test Armand 30-40s)
- ✅ reasoning_path activé sur causal/hypothetical/multi_hop

Si KO → vérifier logs `docker logs knowbase-app` pour message `RuntimeLLMClient → Together AI serverless`.

### Étape 5 — Bench micro 30q stratifié (optionnel, ~10 min, ~$0.50)

Pour confirmer la latence sur un échantillon plus large avant de payer le bench global :

```powershell
docker exec knowbase-app python /app/scripts/diag_v4_stratified_breakdown.py --n_per_type 6 --out /app/data/audit/ch48_stratified_together.json
```

### Étape 6 — Bench global complet (~2h, ~$10)

Restart worker pour qu'il charge le code patché :

```powershell
docker compose -f docker-compose.infra.yml -f docker-compose.yml -f docker-compose.monitoring.yml restart ingestion-worker
```

Lancer Robust :

```powershell
curl.exe -s -X POST "http://localhost:8000/api/benchmarks/robustness/run" -H "Content-Type: application/json" -d "@C:\Projects\SAP_KB\logs\bench_payload_robustness.json"
```

Quand Robust completed (~50min) → lancer T2T5 :

```powershell
curl.exe -s -X POST "http://localhost:8000/api/benchmarks/t2t5/run" -H "Content-Type: application/json" -d "@C:\Projects\SAP_KB\logs\bench_payload_t2t5_v41.json"
```

Quand T2T5 completed (~15min) → lancer RAGAS :

```powershell
curl.exe -s -X POST "http://localhost:8000/api/benchmarks/ragas/run" -H "Content-Type: application/json" -d "@C:\Projects\SAP_KB\logs\bench_payload_ragas_v41.json"
```

Ou utiliser l'orchestrateur Monitor existant (cf bench global précédent).

### Étape 7 — Analyse résultats vs gates go-prod

Comparer :
- `data/benchmark/results/robustness_run_*_V4_1_CH47*.json` vs V3_S0_BASELINE
- Métriques : Robust global, hypothetical/causal/multi_hop/conditional, faithfulness Channel 2, abstention rate
- Vérifier les **8 gates go-prod** de l'ADR §10.6

## Rollback (si quelque chose casse)

Pour revenir à DeepInfra public :

1. Retirer/commenter `TOGETHER_API_KEY` dans `.env`
2. `docker compose ... up -d --force-recreate app`
3. Le code détecte automatiquement l'absence de TOGETHER_API_KEY → fallback DeepInfra

Pas de modif code à rollback (le fallback est dans `_resolve_endpoint()`).

## Coût total estimé pour la session de demain

| Phase | Coût |
|---|---:|
| Smoke test 5q | ~$0.05 |
| Bench micro 30q stratifié (optionnel) | ~$0.50 |
| Bench global complet (Robust + T2T5 + RAGAS) | **~$8-10** |
| **TOTAL session** | **~$10-12** |

(+ coût LLM-judge Llama-3.3-70B sur DeepInfra : ~$3-5, déjà inclus dans le calcul global)

## Variables d'environnement référence

| Variable | Default | Description |
|---|---|---|
| `TOGETHER_API_KEY` | (vide) | API key Together AI. Si défini → priorité Together AI sur tout le pipeline V4 |
| `TOGETHER_RUNTIME_MODEL` | `Qwen/Qwen2.5-72B-Instruct-Turbo` | Modèle Together AI à utiliser |
| `DEEPINFRA_API_KEY` | (existant) | Fallback DeepInfra si Together AI absent |
| `V4_REASONING_MODE_ENABLED` | `true` | Active le path reasoning V4.1 (causal/comparison/temporal) |
| `BENCHMARK_CONCURRENCY` | `2` | Concurrence interne bench (à monter à 4 si Together AI le supporte) |

## Trace bench attendu

| Métrique | Cible (vs V3_S0) | V4_CH46 actuel |
|---|---:|---:|
| Robust global | ≥ 0.55 | 0.351 ❌ |
| Causal/Hypothetical/Multi_hop / Conditional | ≥ 0.50 chacun | < 0.40 |
| Faithfulness Channel 2 | ≥ 0.85 | OK |
| Abstention rate sur reasoning | ≤ 15% | 60% ❌ |
| Latence mean/q end-to-end | 17-25s (cible) | 132s ❌ |
