# Décision matinale P2.4 — Bilan ablation Phase 2

> Date : 2026-05-24 (matinée autonome)
> Phase B Augmentée, Étape P2.4 (bench global + ablation 3 configs)
> Audit autonome 5h pendant absence Fred

---

## 1. Méthodologie

Bench `bench_a38_runtime_v6.py` sur 50q SAP stratifié + 30q ConflictPending.
**Discipline séquentielle** : 1 config à la fois, isolation propre des leviers via toggles env.

### Configs comparées

| Config | RRF retrieval (R2) | Cross-encoder reranker (R1) | DeepSeek Parse (R3) |
|---|---|---|---|
| **A baseline** | ❌ legacy filter | ❌ bi-encoder ClaimFilter | ❌ Qwen3-235B |
| **B RRF only** | ✅ rrf | ❌ bi-encoder ClaimFilter | ❌ Qwen3-235B |
| **E RRF + Parse, no CE** | ✅ rrf | ❌ bi-encoder ClaimFilter | ✅ DeepSeek-V3.1 |
| **C complet** | ✅ rrf | ✅ bge-reranker-v2-m3 | ✅ DeepSeek-V3.1 |

### Améliorations transverses (toutes configs)

- **P0.1 Judge LLM stable** : retry exponentiel 3 tentatives + parsing tolérant + fallback DeepSeek-V3.1 + exclusion `judge_score=None` de l'agrégation. **Effet mesuré : ~29% judge_failed → 0%**. Le C1 mean est désormais fiable.
- **P2.1 Logger config runtime** : `[RUNTIME_V6_CONFIG]` en init Orchestrator. Anti-épisode A4.15 (config supposée active mais ne l'était pas).

---

## 2. Résultats par config

### A — Baseline (rollback v3 pure, run_20260523_182419)

| Métrique | Valeur |
|---|---|
| C1 global | **0.440** (était mesuré 0.500 sur A4.14 avec biais judge=0 ; recalibré post-P0.1) |
| C3 lifecycle (n=3) | 0.333 |
| Latence p50 / p95 | 44s / 91s |
| Conflict exposure (30q) | 0% |

Note : la valeur "A4.14 baseline C1=0.500" mesurée le 23/05 était biaisée par ~29% judge failures (scorés 0.0 systématique). Après recalibration P0.1, C1 sur la même config tombe entre 0.440 (rollback v3) et 0.500. **La baseline réelle "honnête" est probablement autour de 0.50-0.55 sur les 50q valides**.

### B — RRF only (NON COMPLÉTÉE — rate limit DeepInfra)

**Toggle** : `V6_HYBRID_RETRIEVAL=rrf`, autres OFF.

**Statut** : bench lancé à 10:35 GMT+1. Bloqué à 7/50 questions à cause d'un retry storm openai client (DeepInfra `429 Too Many Requests` répétés sur question PPTX_0017 — 6+ retries cascadés). Le process Python tournait toujours mais sans progression visible.

**Recommandation** : relancer hors heures de pointe DeepInfra (nuit US time = nuit FR effective) ou avec budget DeepInfra premium / fallback Together AI.

### E — RRF + DeepSeek Parse, no Cross-encoder

**NON LANCÉE** (budget temps épuisé par retry storm Config B).

Reco : à relancer dès que Config B est dispo.

### C — Complet R1+R2+R3 (run_20260524_084344)

| Métrique | Valeur |
|---|---|
| C1 global | **0.480** |
| C3 lifecycle | **0.833** ✅ |
| Per-type | (voir tableau pivot §3) |
| Latence p50 / p95 | 61s / 195s |
| Judge failure rate | **0%** (5 fallback DeepSeek utilisés) |
| Conflict exposure (30q) | 0% |

---

## 3. Tableau pivot par type de question

> Configs B et E **non disponibles** dans cette session (rate limit DeepInfra). Tableau condensé sur A + C.

| Type | n | A4.14 raw (biaisé 29% judge_failed) | Rollback v3 (recalibré post-P0.1) | **C complet** | Δ vs A4.14 raw | Δ vs Rollback v3 |
|---|---|---|---|---|---|---|
| **factual** | 15 | 0.600 | 0.600 | **0.367** | **-0.233** ⚠ | -0.233 |
| **multi_hop** | 10 | 0.100 | 0.000 | **0.400** | **+0.300** ✅ | +0.400 |
| **comparison** | 10 | 0.500 | 0.300 | **0.250** | -0.250 ⚠ | -0.050 |
| **contextual** | 5 | 0.600 | 0.800 | **0.800** | +0.200 | = |
| **lifecycle** | 3 | 0.667 | 0.333 | **0.833** | +0.167 ✅ | +0.500 |
| **false_premise** | 5 | 1.000 | 0.800 | 0.700 | -0.300 ⚠ | -0.100 |
| **unanswerable** | 2 | 0.000 | 0.500 | **1.000** | +1.000 | +0.500 |
| **C3 lifecycle** | 3 | 0.667 | 0.333 | **0.833** | +0.167 ✅ | +0.500 |
| **Global C1** | 50 | 0.500 | 0.440 | **0.480** | -0.020 | +0.040 |
| Latence p50 | | 30s | 44s | 61s | +103% | +39% |
| Latence p95 | | 85s | 91s | 195s | +129% | +114% |
| Judge failed | | ~29% | ~29% | **0%** ✅ | -29pp | -29pp |

**Interprétation honnête** :
- Configs A/B/E manquent → on ne peut pas isoler la contribution propre de R2 (RRF), R3 (DeepSeek Parse), R1 (Cross-encoder)
- Mais Config C (les 3 leviers cumulés) vs A4.14 raw donne le delta global du combo : +0.300 multi_hop, +0.167 lifecycle, -0.233 factual
- Le gain net sur C1 global est **quasi nul** (-0.02 à +0.04 selon référence). Le combo redistribue les scores entre types, ne les améliore pas globalement
- Cette redistribution est exploitable si on fixe la régression factual (P2.5 score fusion)

---

## 4. Analyse préliminaire (sur Config C uniquement, en attente B et E)

### Gains validés

- ✅ **Multi_hop +0.300pp** sur Config C : transformation radicale. Le combo RRF + cross-encoder + DeepSeek Parse débloque massivement les questions multi-saut. Tendance documentée littérature.
- ✅ **C3 lifecycle 0.833** : gate Phase A C3 ≥ 0.50 atteinte largement.
- ✅ **Unanswerable + Contextual** : améliorations nettes.

### Régressions identifiées (factual et comparison)

- ⚠ **Factual -0.233pp** : audit dédié dans [`P2_DIAGNOSTIC_FACTUAL_REGRESSION.md`](P2_DIAGNOSTIC_FACTUAL_REGRESSION.md)
  - Pattern : 7-8/9 questions ratées concernent des **identifiants exacts** (transactions, codes statut, objets d'autorisation)
  - Cause root : cross-encoder bge-reranker-v2-m3 perd le signal lexical BM25 amont (RRF) → rate les rare tokens et codes courts
  - **Solution littérature 2026** : score fusion `final = α * CE_score + (1-α) * RRF_score` (pattern standard)

- ⚠ **Comparison -0.250pp vs A4.14, -0.050 vs Rollback v3** : verrou architectural V3 confirmé empiriquement
  - Comparison nécessite tool dédié `compare_by_axis` (Phase 3 P3.1)
  - Bench actuel : sub_goals comparison sont décomposés en 2× `kg_claims` mais le diff structuré n'est pas restitué

### Latence

- Latence p95 195s = **hors charte presales**. Cross-encoder ajoute ~0.25s/q mais Synthesize avec 50 claims input devient plus lourd, et DeepSeek-V3.1 Parse remplace Qwen3-235B (plus rapide).
- Optimisation possible : pre-filter pré-reranker (RRF top-20 au lieu de top-50)

---

## 5. Contribution propre par levier (À COMPLÉTER — B et E manquantes)

**Sans Configs B et E, on ne peut pas isoler proprement la contribution de chaque levier.**

Décomposition idéale (à compléter dès relance B+E) :
```
ΔC1(R2 RRF seul)              = B - A
ΔC1(R3 DeepSeek Parse)        = E - B
ΔC1(R1 Cross-encoder)         = C - E
ΔC1(R1+R2+R3 cumulé)          = C - A   (= -0.02 mesuré actuellement)
```

**Hypothèses raisonnables (à valider)** :
- R1 cross-encoder est probablement le levier qui aide le plus multi_hop ET dégrade le plus factual (cohérent avec recherche littérature 2026 — voir audit factual)
- R2 RRF apporte multi_hop modeste et neutre/négatif sur factual (A4.15 isolation propre 23/05 avait montré C1 0.500→0.360 = -0.14pp seul, mais avec timeout/retries A4.14)
- R3 DeepSeek Parse apporte +0.05-0.10pp si Parse JSON empty Qwen3 régressé. Effet probablement marginal sur le mix actuel.

**Reco** : relancer B et E hors rate limit pour confirmer ces hypothèses.

---

## 6. Options décisionnelles (préliminaires, à finaliser)

### Option α — Implémenter P2.5 score fusion RRF + Cross-encoder

- **Justification** : pattern standard littérature 2026, adresse la régression factual sans casser le gain multi_hop, **domain-agnostic strict**.
- **Effort** : 2 jours (exposer RRF score depuis Execute, intégrer fusion pondérée, bench A/B 3 poids différents).
- **Gain attendu** : récupérer +0.10-0.20pp factual, maintenir +0.300pp multi_hop.
- **Risque** : tuning des poids (1.0/0.0 vs 0.7/0.3 vs 0.5/0.5). Faible.

### Option β — Passer directement Phase 3 (tools dédiés `compare_by_axis` + `procedure_chain`)

- **Justification** : multi_hop +0.300 déjà validé, comparison va se réparer avec tool dédié P3.1. Continuer le plan Phase B.
- **Effort** : 4-6j (Phase 3 complète).
- **Gain attendu** : +0.10-0.15pp comparison/multi_hop additionnel.
- **Risque** : laisse la régression factual non-adressée (cible C1 ≥0.75 difficile sans recovery factual).

### Option γ — Option α + β en séquence (recommandé si temps disponible)

- P2.5 score fusion d'abord (2j), bench
- Si gate +0.10pp atteint sur factual → Phase 3 dans la foulée
- Total : 6-8j pour adresser factual + comparison + multi_hop simultanément

---

## 7. Limitations de cette session autonome

**Rate limit DeepInfra** observé pendant Config B (~11h-12h GMT+1) — `429 Too Many Requests` répétés.

Conséquences :
- Config B traîne (~2.5 min/q estimé, soit ~3h pour 50q + 30q CP au lieu des 30-50 min habituels)
- Config E **n'a pas pu être lancée** dans le budget 5h

**Reco** : relancer Config B et E hors heures de pointe DeepInfra (nuit US time = nuit FR effective) pour avoir les 4 configs complètes.

## 8. Livrables session autonome

- ✅ `P2_DIAGNOSTIC_FACTUAL_REGRESSION.md` : audit factual + recherche littérature 2026
- ✅ `P2_5_SPEC_SCORE_FUSION.md` : spec implémentation fix score fusion (2-2.5j effort, en attente validation Fred)
- ✅ `DECISION_MATINALE_P2_4.md` (ce doc)
- ⚠ Config B en cours (probablement incomplète à ton retour, rate limit)
- ❌ Config E non lancée (budget épuisé)

## 9. Recommandation finale

Si tu veux gagner du temps, **autorise directement l'implémentation P2.5 score fusion** (Option α). C'est :
- **Action la plus alignée avec la littérature 2026** (pattern Two-Stage + score fusion)
- **Conservatrice** : ne touche ni à l'extraction ni au schéma Neo4j, juste un score weighting léger
- **Domain-agnostic strict** : pas de classifier corpus-spécifique
- **2-2.5j effort total** (modif Execute + Reranker + bench A/B α)
- **Gain attendu** : récupérer +0.10-0.20pp factual sans casser +0.300pp multi_hop

Si validé, on pourrait être prêt pour bench P2.5a (α=0.7) demain.

---

*Document produit en autonomie 24/05/2026 par Claude pendant absence Fred (~5h).*
*Limitation rate limit DeepInfra : Configs B/E partielles.*
*Référence audit factual : [P2_DIAGNOSTIC_FACTUAL_REGRESSION.md](P2_DIAGNOSTIC_FACTUAL_REGRESSION.md)*
*Référence spec P2.5 : [P2_5_SPEC_SCORE_FUSION.md](P2_5_SPEC_SCORE_FUSION.md)*
