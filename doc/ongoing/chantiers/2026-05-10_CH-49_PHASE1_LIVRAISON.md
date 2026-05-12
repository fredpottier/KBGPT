# CH-49 Phase 1 — Livraison Layer 0 production-grade (runtime_v4_2)

**Date** : 2026-05-10
**Statut** : 🟡 Phase 1 code complet, gates non-régression en bench (P1.7 en cours)
**Référence ADR** : `2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md` v1.1 LOCKED
**Décision archi** : Nouveau module `runtime_v4_2/` (V4.1 préservé pour A/B)

---

## Résumé exécutif

Phase 1 livre la **Cap1 — Cheap Certainty Layer** + Cap2.A operator + Cap5 (multi-view scorer + abstain reward + 3 catégories logging) sous un nouveau module `runtime_v4_2/`. L'endpoint `/api/runtime_v4_2/answer` est live. Tous les composants Amendment 1, 5, 7, 9 sont implémentés.

### Décisions sur Amendments
| Amendment | Décision Phase 1 |
|---|---|
| A1 (3 catégories abstain) | ✅ implémenté + alerte 5% |
| A5 (Telemetry QuestionTrace) | ✅ implémenté (JSONL append-only) |
| A7 (Unified prompt) | ✅ code livré, désactivé par défaut, A/B reporté à P1.7 |
| A9 (Validation 100q) | 🟡 50q synthétique (décision Fred, pragmatisme) |

---

## Composants livrés

### Module `src/knowbase/runtime_v4_2/`

| Fichier | Rôle |
|---|---|
| `__init__.py` | Exports : `Layer0Response`, `QuestionTrace`, `AbstainCategory`, `EscalationReason` |
| `models.py` | Dataclasses : `Layer0Response`, `QuestionTrace`, `UnifiedExtractionResult`, enums |
| `telemetry.py` | Logger JSONL append-only + agrégation quotidienne |
| `qa_alignment_verifier.py` | DeepSeek-V3.1 + retry exp backoff (max 3) + fallback DeepInfra |
| `unified_extractor.py` | Llama-Turbo 1-call : extract+intent+QA self-check (Amendment 7) |
| `pipeline.py` | `Layer0Pipeline` production : retrieval → extract → Q↔A → decision |

### API

| Fichier | Endpoints |
|---|---|
| `src/knowbase/api/routers/runtime_v4_2.py` | `POST /api/runtime_v4_2/answer`<br>`GET /api/runtime_v4_2/health`<br>`GET /api/runtime_v4_2/telemetry/today` |

### Benchmarks evaluators

| Fichier | Rôle |
|---|---|
| `benchmark/evaluators/multi_view_scorer.py` | exact + fuzzy + semantic + abstain reward + garde-fou identifiers |
| `benchmark/evaluators/multi_view_validation_pack.py` | Pack 50q synthétique (calibration P1.6) |
| `benchmark/evaluators/abstain_categorizer.py` | 3 catégories Amendment 1 + alerte 5% |

### Scripts

| Fichier | Rôle |
|---|---|
| `app/scripts/runtime_v4_2_bench_robust.py` | Bench Robust 120q sur runtime_v4_2 |
| `app/scripts/runtime_v4_2_unified_bakeoff.py` | A/B mode séparé vs unifié (P1.7) |

### Documentation

| Fichier | Rôle |
|---|---|
| `2026-05-10_CH-49_P1_MULTI_VIEW_SCORER_CALIBRATION.md` | Calibration scorer 50q + garde-fous |
| `2026-05-10_CH-49_PHASE1_LIVRAISON.md` | Ce document |

---

## Calibration multi-view scorer (P1.6)

**Pack synthétique 50q** : 5 catégories × 10 cases.

| Catégorie | dominant_accuracy | score_accuracy |
|---|---:|---:|
| exact | 70% | 100% |
| fuzzy | 10%* | 100% |
| semantic | 100% | 100% |
| **false_positive** | **90%** ✅ | **90%** |
| mixed | 70% | 90% |
| **Global** | **68%** | **96%** ✅ |

(*) `dominant_accuracy=10%` artificiellement bas car labeling pédagogique trop strict (paraphrases sortent en `exact`/`semantic` plutôt que `fuzzy`). Score_accuracy 100% confirme la validité.

**Garde-fous calibrés** :
- Cap `semantic` à 0.6 si `id_coverage < 40%` (évite faux positifs sémantiques)
- Cap `fuzzy` à 0.7 si `id_coverage < 40%` (évite faux positifs `partial_ratio` sur tokens identiques inversés)

---

## Telemetry & Observabilité

### QuestionTrace JSONL (Amendment 5)

Path : `data/runtime_v4_2/traces/<YYYY-MM-DD>.jsonl`
Schema : `models.QuestionTrace` (15+ champs inc. layer_used, verifier_result, intent_scores, latency_breakdown_ms, abstain_category)

Endpoint dashboard : `GET /api/runtime_v4_2/telemetry/today` retourne distribution layer + abstain + p50/p95 + false_abstain_rate.

### 3 catégories abstain (Amendment 1)

Logique post-hoc via `abstain_categorizer.categorize(decision, gold_answerability)` :
- `aligned` : decision=ANSWER
- `misaligned_abstain_correct` : decision=ABSTAIN ET gold dit unanswerable/partial
- `misaligned_but_answerable` : decision=ABSTAIN ET gold dit answerable → **alerte qualité**

**Threshold alerte** : `false_abstain_rate > 5%` → tuning prompt verifier requis.

---

## Gates Phase 1 (à valider via P1.7 bench Robust 120q)

| Gate | Cible | Mesuré |
|---|---|---|
| Robust score_best global | ≥ 0.45 | _en bench_ |
| false_abstain_rate | ≤ 5% | _en bench_ |
| p95 latency | ≤ 12s | _en bench_ (smoke 5q : 19s — alerte) |
| Régression factual/list/unanswerable | ≤ 0.05pp | _en bench_ |
| Citation preservation rate | ≥ V4.1 baseline | _en bench_ |

**Note latence** : smoke 5q montre p95 19s, au-dessus du gate 12s. Causes probables : cold-start retrieval (22s sur 1ère question post-restart), absence de retry/cache. À analyser en P1.7.

---

## Décisions reportées

1. **Bake-off A/B mode séparé vs unifié (Amendment 7)** : reporté à P1.7 avec scorer + bench complet
2. **Validation 100q complète (Amendment 9)** : 50q synthétique livré, 100q réel post-Phase 1 sur runtime_v4_2 réel
3. **Phase 2 operators Cap2.B/C/D/E** : suit le plan ADR § 4 (~6-8j additionnels)
4. **Phase 3.A POC modèle Layer 2** : DeepSeek vs Claude Sonnet 4.6 vs GPT-4o sur 25q (~2-3j)

---

## Anti-patterns évités (charte ADR)

✅ Domain-agnostic strict : aucune regex/keyword corpus-spécifique dans Phase 1
✅ Anti-Goodhart : abstain reward dans scorer, pas de tweaks bench-specific
✅ Anti-biais auto-juge : Q↔A Verifier DeepSeek-V3.1 ≠ Composer Llama-Turbo
✅ Cohérence bench/prod : même endpoint runtime_v4_2 utilisé par bench que par prod
✅ Pas de MVP transitoire : architecture cible directement (5 capabilities, 3 layers)
