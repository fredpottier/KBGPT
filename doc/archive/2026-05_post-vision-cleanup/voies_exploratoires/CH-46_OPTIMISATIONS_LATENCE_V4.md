# CH-46 — Optimisations latence pipeline V4 (Phase A+B+C)

**Date** : 2026-05-07
**Branche** : `feat/contradiction-detection`
**Contexte** : POC DeepInfra Dedicated (CH-45) bloqué (deploy failed `other-error`, support contacté). On reste sur DeepInfra public et on optimise le pipeline pour passer de ~115s mean (V4 list) à 50-70s, idéalement < 40s.

**Cible** : Test Armand demo avec latence runtime 30-40s/q (vs actuel 80-122s).

**Baseline mesurée (CH-44.b, 10q list panel sur DeepInfra public)**

| Stage | mean ms |
|---|---|
| analyzer_ms | 12 700 |
| rerouter_preview_retrieval_ms | 5 000-8 000 |
| main_retrieval_ms | 3 000-5 000 |
| structurer_ms | 40 000 |
| composer_ms | 21 000 |
| verifier_ms | 2 000-3 000 |
| selfcorrector_retry_ms | 63 000 (déclenché 70%) |
| channel2_nli_ms | 1 000 |
| **wall total mean** | **~115 000** |

Source données : `data/router/v4_list_breakdown.json`.

---

## Principe de rollback

Chaque levier est **traçé avec config avant / après / commande rollback**.
- **Leviers env-only** : rollback = retirer la variable du `docker-compose.yml` ou du `.env` + restart `app+worker`.
- **Leviers code** : commit dédié par levier sur la branche → rollback = `git revert <sha>`.

Pour identifier l'origine d'une régression, lancer le bench micro 30q (`scripts/diag_v4_list_breakdown.py`) après chaque levier.

---

## Phase A — Leviers à risque qualité ~nul

### L1 — Analyzer Qwen-72B → modèle plus petit

**Hypothèse** : task simple (classification 7 classes + extraction langue + rationale 25 mots). Un 24B à 7B suffit largement.

**Avant** :
- Fichier : `src/knowbase/facts_first/question_analyzer.py:160`
- `QuestionAnalyzer.__init__()` n'accepte pas `model_override`. Utilise `chat_completion_with_meta` sans surcharge → tombe sur `DEEPINFRA_RUNTIME_MODEL` (Qwen-72B).

**Après** :
- Ajout argument `model_override` au constructeur, lu depuis env `ANALYZER_MODEL` (default = vide → comportement legacy = Qwen-72B).
- Passé à `chat_completion_with_meta(model_override=self.model_override)`.
- Env var prod : `ANALYZER_MODEL=mistralai/Mistral-Small-3.2-24B-Instruct-2506`.

**Rollback** :
- Code : `git revert <sha L1>`
- Env : retirer `ANALYZER_MODEL` du `docker-compose.yml` + restart app.

**Gain attendu** : -7s sur l'Analyzer (12.7s → ~5-6s).

---

### L5 — Structurer Qwen-72B → Mistral-Small-3.2-24B

**Hypothèse** : Mistral-Small-3.2-24B déjà validé en bake-off Levier 4 (mémoire : "-25-38% p50 sur 4/5 types, verifier 100%, 0 abstention").

**Avant** :
- Env actuelle : `FACTS_FIRST_STRUCTURER_MODEL` non set → fallback Qwen-72B.

**Après** :
- Env prod : `FACTS_FIRST_STRUCTURER_MODEL=mistralai/Mistral-Small-3.2-24B-Instruct-2506`.
- Tous les Structurer (list/factual/temporal/comparison/causal) ré-utilisent automatiquement cet env var.

**Rollback** :
- Retirer `FACTS_FIRST_STRUCTURER_MODEL` du `docker-compose.yml` + restart app.

**Gain attendu** : -10-15s sur Structurer (40s → ~25-30s).

---

### L6 — Audit `max_tokens` par stage

**Hypothèse** : les `max_tokens` actuels sont surdimensionnés vs sortie réelle observée. Réduire diminue le `time-to-last-token` de DeepInfra (overhead d'autoregression).

**Avant** :
| Stage | max_tokens actuel |
|---|---|
| QuestionAnalyzer | 250 |
| ListStructurer | 3000 |
| FactualStructurer | 2000 |
| Temporal/Comparison/CausalStructurer | 2500 |
| ListComposer | 1500 |
| FactualComposer | 800 |
| Temporal/Comparison/CausalComposer | 900 |

**Après** (ajustements proposés, à valider en logs) :
| Stage | max_tokens cible | Justification |
|---|---|---|
| QuestionAnalyzer | 250 | Inchangé (déjà serré) |
| ListStructurer | 2000 | Réduction -33% (réponses observées < 1500 tokens) |
| FactualStructurer | 1500 | Réduction -25% |
| Temporal/Comparison/CausalStructurer | 1800 | Réduction -28% |
| ListComposer | 1200 | Réduction -20% |
| FactualComposer | 800 | Inchangé |
| Temporal/Comparison/CausalComposer | 900 | Inchangé |

**Rollback** : `git revert <sha L6>`.

**Gain attendu** : -3-5s en cumul.

---

### L3 — Parallélisation Analyzer ∥ Rerouter preview retrieval

**Hypothèse** : actuellement Analyzer (12.7s) puis rerouter_preview_retrieval (5-8s) sont séquentiels. Le retrieval ne dépend PAS du résultat Analyzer (il se base sur la question brute pour collecter signaux KG). On peut les lancer en parallèle.

**Avant** : `src/knowbase/facts_first/pipeline.py:182-201` — séquentiel.

**Après** : utiliser `concurrent.futures.ThreadPoolExecutor` pour lancer en parallèle, attendre les 2 résultats.

**Rollback** : `git revert <sha L3>`.

**Gain attendu** : -5-8s wall (parallélisation des 2 plus longs avant routing).

---

## Phase B — Leviers à valider qualité

### L4 — top_k_claims 20 → 12 sur V4

**Avant** : runtime_v4 endpoint envoie `top_k_claims=20` par défaut.

**Après** : `top_k_claims=12`. Réduction du contexte → -8-12s sur Structurer.

**Risque qualité** : Moyen. List `coverage_state` peut chuter si le KG a > 12 claims pertinents. Mesurer `item_recall` en bench.

**Rollback** : revert le default dans `runtime_v4.py`.

---

### L2 — Calibration seuil SelfCorrector retry

**Constat** : retry déclenché 70% des cas pour 63s d'overhead. Cible ~30-40% (cas où le NLI Channel 2 + le Verifier Channel 1 convergent vers UNFAITHFUL ou SEVERE).

**Avant** : `src/knowbase/facts_first/self_corrector.py` — `decide()` déclenche retry sur tout `actionable_codes` non vide.

**Après** : ajouter règle "ne retry que si Channel 2 dit UNFAITHFUL OR Verifier severity ≥ HIGH".

**Risque qualité** : Moyen — peut laisser passer des cas borderline. Mesurer en bench `factual_correctness` + structured_metrics.

**Rollback** : `git revert <sha L2>`.

---

## Phase C — Finitions

### L7 — Async pre-fetch retrieval pendant Analyzer

**Hypothèse** : si Analyzer ne change PAS le routing dans 75% des cas, on peut speculative-fetch le retrieval principal pendant que l'Analyzer tourne.

**À cadrer si Phase A+B insuffisants.**

### L8 — Skip Channel 2 NLI sur Composer high-confidence

**Hypothèse** : si Verifier Channel 1 passe ET Composer ne signale aucune erreur de citation, on skip Channel 2.

**Gain marginal** : -1-2s.

---

## Bench plan

Après chaque phase :
- Bench micro 30q list (`scripts/diag_v4_list_breakdown.py`) → vérifier gain wall + qualité (verifier_passed % et structured_metrics non régressés).
- Si Phase B OK → bench global RAGAS+T2T5+Robustness 132q (garder pour la fin).

---

## Journal d'exécution

### 2026-05-07

- 16:19 — Tentative POC DeepInfra Dedicated → fail `other-error` (CH-45 bloqué, support contacté).
- 18:20 — Décision : optimiser sur infra publique, plan CH-46 acté.
- 18:30 — Création doc tracking + démarrage Phase A.
- 18:35 — **L6 fait** : `max_tokens` ajustés (4 fichiers Structurer + ListComposer). Commentaires inline `# CH-46 L6`.
- 18:38 — **L1 fait** : `QuestionAnalyzer` accepte `model_override`. Env var `ANALYZER_MODEL`. Set sur app+worker+worker-2.
- 18:42 — **L5 fait** : env var `FACTS_FIRST_STRUCTURER_MODEL=mistralai/Mistral-Small-3.2-24B-Instruct-2506` set sur les 3 services.
- 18:45 — **L3 fait** : parallélisation Analyzer ∥ rerouter_preview_retrieval via `ThreadPoolExecutor`. Path sans rerouter conservé séquentiel pour compat.
- 18:50 — **L2 fait** : seuil warnings SelfCorrector durci. `SELFCORRECTOR_WARNING_THRESHOLD=2` par défaut (≥ 2 warnings actionnables nécessaires pour trigger retry sur warnings seuls). Errors actionnables continuent de toujours déclencher.
- 18:55 — **L4 fait** : `top_k_claims` V4 : 20 → 12. Implémenté sur les 3 évaluateurs (`ragas_diagnostic.py`, `robustness_diagnostic.py`, `t2t5_diagnostic.py`). Override env `V4_TOP_K_CLAIMS`.
- 18:58 — **L7 et L8 skipped** : gain marginal vs effort+risque. À reprendre seulement si Phase A+B insuffisantes.

---

## Récap modifs ↔ rollback granulaire

| Levier | Type | Fichier(s) | Rollback |
|---|---|---|---|
| L1 | code | `src/knowbase/facts_first/question_analyzer.py` | `git revert <sha L1>` OU `unset ANALYZER_MODEL` |
| L1 | env | `docker-compose.yml` (3 services) | retirer ligne `ANALYZER_MODEL: ...` + restart app/worker |
| L2 | code | `src/knowbase/facts_first/self_corrector.py` | `git revert` OU `SELFCORRECTOR_WARNING_THRESHOLD=1` |
| L3 | code | `src/knowbase/facts_first/pipeline.py` | `git revert <sha L3>` |
| L4 | code | `benchmark/evaluators/{ragas,robustness,t2t5}_diagnostic.py` | `git revert` OU `V4_TOP_K_CLAIMS=20` (env) |
| L5 | env | `docker-compose.yml` (3 services) | retirer ligne `FACTS_FIRST_STRUCTURER_MODEL: ...` + restart |
| L6 | code | `list_structurer.py`, `factual_structurer.py`, `temporal_pipeline.py`, `comparison_pipeline.py`, `causal_pipeline.py`, `list_composer.py` | `git revert <sha L6>` |

**Rollback total Phase A+B** :
```bash
# 1. Code
git revert <sha CH-46>
# 2. Env vars (si commit pas fait, retirer manuellement du docker-compose.yml)
# 3. Restart
./kw.ps1 restart api  # safe pendant import
```

**Rollback levier individuel** : possible via env var (sauf L3 et L6 qui demandent un revert ou patch ciblé).

---

## Plan validation post-modifs

1. **Syntax/import check** : `docker exec knowbase-app python -c "from knowbase.facts_first.pipeline import FactsFirstPipeline"` après restart
2. **Bench micro 30q list** : `python /app/scripts/diag_v4_list_breakdown.py` (à étendre à 30q)
3. **Comparer breakdown** : data/router/v4_list_breakdown.json (avant) vs nouveau snapshot
4. **Critère go Phase B → bench global** : wall mean ≤ 70s, item_recall non régressé > 5pp, verifier_passed % stable
5. **Si OK** → bench global RAGAS+T2T5+Robustness 132q

---

## Garde-fous qualité

- **Métriques structurées (item_recall, exact_match)** doivent rester ≥ baseline V3_S0 (cf `data/benchmark/results/robustness_run_V3_S0_BASELINE_*.json`).
- **judge_metric_disagreement** ne doit pas augmenter (sinon overfitting silencieux).
- **Channel 2 NLI faithfulness_score** ne doit pas chuter > 5pp (sinon L2 trop agressif).
- **coverage_state=complete %** sur list ne doit pas chuter > 5pp (sinon L4 top_k trop bas).

---

## ⚠️ Incident bench parallèle 2026-05-07 21:25

**Symptôme** : Tentative de lancer RAGAS + T2T5 + Robustness en parallèle → saturation DeepInfra publique massive.
- **RAGAS** : 1/132 questions complétée (131 timeout HTTP read=300s côté worker), scores 0.0/1.0/0.0 totalement biaisés
- **T2T5** : ~70 questions traitées mais grosse perte (estimation 30-40 timeout)
- **Robustness** : progress 0/170 après 40min → toutes timeout, killé

**Cause racine** : Concurrency cumulée :
- 3 benchs × `BENCHMARK_CONCURRENCY=3-4` = 9-12 connexions simultanées sur l'app
- Chaque pipeline V4 fait ~5 calls LLM (analyzer + structurer + composer + 2× channel2)
- → ~50-60 calls Mistral-Small simultanés sur DeepInfra publique → rate-limit serveur → timeout client

**Mitigation** : lancer les benchs **séquentiellement, un seul à la fois**. Concurrency interne du bench (workers=3-4) reste OK quand seul.

**Résultats invalidés** :
- `data/benchmark/results/ragas_run_20260507_192159_V4_CH46_POSTOPT.json` ❌ (1 sample)
- `data/benchmark/results/t2t5_run_20260507_184217_V4_CH46_POSTOPT.json` ⚠️ (partial)

**À refaire** : Robust → T2T5 → RAGAS (séquentiel). En cours.

**Leçon retenue** : ne jamais lancer plus d'1 bench concurrent contre DeepInfra publique. Documenter en mémoire (feedback).
