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

### B — RRF only (COMPLÉTÉE, run_20260524_110245)

**Toggle** : `V6_HYBRID_RETRIEVAL=rrf`, autres OFF.

**Statut** : bench complet 50q + 30q CP malgré rate limit DeepInfra (retry storm fini par passer). Durée totale 10241s = 2h50min (vs ~30-50 min habituels) — toute la latence est gonflée par les 429.

| Métrique | Valeur |
|---|---|
| C1 global | **0.420** |
| C3 lifecycle (n=3) | 0.667 ✅ |
| Multi_hop (n=10) | **0.200** |
| Factual (n=15) | 0.400 |
| Comparison (n=10) | 0.300 |
| Contextual (n=5) | 0.600 |
| False_premise (n=5) | 0.600 |
| Unanswerable (n=2) | 1.000 |
| Latence p50 | 40.5s |
| Latence p95 | 590s (gonflé par retry storm, non représentatif) |
| Judge failed | **0%** ✅ (6 fallback DeepSeek utilisés) |
| Conflict exposure (30q) | 0% |

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

## 3. Tableau pivot par type de question (avec contribution propre par levier)

> Config E **non disponible** (budget temps + rate limit). Configs A + B + C dispo permettent d'isoler R2 RRF vs (R1+R3) cumulés.

| Type | n | **A4.14 raw** (biaisé 29% judge_failed) | **A** Rollback v3 (recalibré P0.1) | **B** RRF only | **C** Complet R1+R2+R3 | **ΔB-A** (R2 RRF) | **ΔC-B** (R1+R3) | **ΔC-A** (cumulé) | **Δ vs A4.14 raw** |
|---|---|---|---|---|---|---|---|---|---|
| **factual** | 15 | 0.600 | 0.600 | 0.400 | **0.367** | **-0.20** ⚠ | -0.033 | -0.233 | **-0.233** ⚠ |
| **multi_hop** | 10 | 0.100 | 0.000 | 0.200 | **0.400** | **+0.20** ✅ | **+0.20** ✅ | **+0.40** ✅ | **+0.300** ✅ |
| **comparison** | 10 | 0.500 | 0.300 | 0.300 | 0.250 | 0 | -0.05 | -0.05 | -0.250 |
| **contextual** | 5 | 0.600 | 0.800 | 0.600 | 0.800 | -0.20 ⚠ | +0.20 ✅ | 0 | +0.200 |
| **lifecycle** | 3 | 0.667 | 0.333 | 0.667 | **0.833** | **+0.333** ✅ | +0.167 | **+0.50** ✅ | +0.167 ✅ |
| **false_premise** | 5 | 1.000 | 0.800 | 0.600 | 0.700 | -0.20 ⚠ | +0.10 | -0.10 | -0.300 |
| **unanswerable** | 2 | 0.000 | 0.500 | 1.000 | 1.000 | +0.50 | 0 | +0.50 | +1.000 |
| **C3 lifecycle** | 3 | 0.667 | 0.333 | 0.667 | **0.833** | +0.333 ✅ | +0.167 | +0.500 ✅ | +0.167 ✅ |
| **Global C1** | 50 | 0.500 | 0.440 | **0.420** | **0.480** | -0.02 | +0.06 | +0.04 | -0.020 |
| Latence p50 | | 30s | 44s | 40.5s | 61s | -8% | +51% | +39% | +103% |
| Latence p95 | | 85s | 91s | 590s* | 195s | (retry storm) | — | — | +129% |
| Judge failed | | ~29% | ~29% | **0%** ✅ | **0%** ✅ | -29pp | = | -29pp | -29pp |

\* p95 590s Config B = gonflé par retry storm DeepInfra (rate limit 11h-12h GMT+1), pas représentatif

### Findings critiques de l'ablation

**RRF (R2) seul** :
- ✅ Gain massif sur multi_hop (+0.20), lifecycle (+0.333), unanswerable (+0.50)
- ⚠ **Dégrade factual (-0.20), contextual (-0.20), false_premise (-0.20)** — pattern cohérent avec A4.15 (RRF -0.14pp seul) et littérature 2026 (dense retrieval dégrade exact-match)
- Bilan net global : **-0.02pp** (neutralité, gain/perte se compensent)

**R1 cross-encoder + R3 DeepSeek Parse cumulés** :
- ✅ Améliorent encore multi_hop (+0.20), contextual (+0.20), lifecycle (+0.167), false_premise (+0.10)
- Dégradent légèrement factual (-0.033), comparison (-0.05)
- Bilan net global : **+0.06pp**

### Réinterprétation cruciale

**Mon audit factual matinal était partiellement faux** : j'avais attribué la régression factual au cross-encoder. Les données montrent que **RRF est responsable de la majorité** (-0.20 sur -0.233). Le cross-encoder n'aggrave que de -0.033.

C'est cohérent avec :
- A4.15 du 23/05 (RRF isolé → factual -0.333pp)
- Littérature 2026 : "Pure dense retrieval fails silently on exact identifiers" (TianPan), "BM25 outperforms dense on financial/structured docs"

**Implication majeure pour le fix P2.5** :
- α=0.7 (CE dominant) **ne va pas suffire** car le problème est en amont (RRF dilue déjà)
- α=0.3 (RRF dominant) **probablement plus utile**, mais alors le cross-encoder devient marginal
- **OU** : toggle conditionnel par `sub_goal.kind` (factual → bypass RRF/garder retrieval legacy exact-match ; multi_hop/lifecycle → RRF+CE)
- **OU** : revenir à un retrieval hybride conditionnel (BM25 dominant pour identifiants, dense pour sémantique)

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

## 5. Contribution propre par levier — MESURÉE

Décomposition obtenue avec Configs A + B + C (E manquante mais R1+R3 sont mesurés cumulés) :

```
ΔC1(R2 RRF seul)              = B - A = 0.420 - 0.440 = -0.02
ΔC1(R1 + R3 cumulé)           = C - B = 0.480 - 0.420 = +0.06
ΔC1(R1+R2+R3 cumulé)          = C - A = 0.480 - 0.440 = +0.04
```

**Par type** :

| Type | ΔR2 (RRF) | ΔR1+R3 (CE + DeepSeek Parse) |
|---|---|---|
| multi_hop | +0.20 ✅ | +0.20 ✅ |
| lifecycle | +0.333 ✅ | +0.167 |
| unanswerable | +0.50 ✅ | 0 |
| **factual** | **-0.20** ⚠ | -0.033 |
| **contextual** | -0.20 ⚠ | +0.20 ✅ (compensation) |
| **false_premise** | -0.20 ⚠ | +0.10 |
| comparison | 0 | -0.05 |

**Reste à mesurer** : Config E (RRF + DeepSeek Parse, no CE) permettrait d'isoler R1 cross-encoder vs R3 DeepSeek Parse pris séparément. Mais on a déjà l'essentiel : RRF est le levier dominant en gain ET en régression.

---

## 6. Options décisionnelles (révisées après Config B)

### Option α-revised — Score fusion RRF + Cross-encoder avec α=0.3 (RRF dominant)

- **Justification révisée** : RRF est l'origine de la régression factual (-0.20pp), pas le cross-encoder. Le fix doit pondérer **RRF dominant** (α=0.3 → CE en simple tie-breaker) au lieu de CE-dominant.
- **Effort** : 2-2.5j (idem spec P2.5, juste paramètre α différent au défaut)
- **Gain attendu** : récupérer +0.10pp factual (vers 0.45-0.50), préserver gain multi_hop +0.20 (RRF apport propre)
- **Risque** : avec α=0.3, le cross-encoder devient marginal. Le gain +0.20 multi_hop de R1+R3 vient surtout de DeepSeek Parse + contextes Synthesize. À mesurer en bench.

### Option δ (NOUVELLE, recommandée) — Routing conditionnel par sub_goal.kind

- **Justification** : RRF a un compromis franc (gain sémantique vs perte exact-match). Toggle conditionnel résout :
  - `fact_lookup` / `definition_lookup` → **retrieval legacy exact-match** (filtre Cypher `subject_canonical = $subject`) OU BM25 dominant pur (pas RRF)
  - `comparison` / `lifecycle_trace` / `multi_hop` / `contradiction_check` → **RRF + cross-encoder** (gain mesuré)
- **Domain-agnostic** : `sub_goal.kind` est un classifier neutre (déjà existant en sortie de Parse), pas corpus-spécifique
- **Effort** : 1-1.5j (modifier Plan pour router selon kind)
- **Gain attendu** : récupérer **toute** la régression factual (-0.233 → ~0) + préserver gain multi_hop/lifecycle
- **Risque** : sub_goal.kind doit être fiable (mesurer accuracy classification Parse)

### Option β — Aller directement Phase 3 (tools dédiés)

- **Justification** : tools `compare_by_axis` + `procedure_chain` exploiteront RRF + cross-encoder où ils brillent (multi-hop, comparison structurée). Laisser factual avec retrieval actuel.
- **Effort** : 4-6j Phase 3
- **Gain attendu** : +0.10-0.15pp comparison/multi_hop
- **Risque** : factual reste sous baseline tant qu'on n'a pas Option α-revised ou δ

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

## 9. Recommandation finale (RÉVISÉE post-Config B)

**Reco : Option δ (routing conditionnel par sub_goal.kind)** est la plus prometteuse à la lumière des Configs A+B+C.

Raison : on dispose d'un classifier neutre (`sub_goal.kind` sortie de Parse) qui permet d'utiliser :
- Le **bon retrieval** pour chaque type de question (RRF pour sémantique, exact-match/BM25 pour identifiants)
- Sans tuning de poids fragile (α du score fusion)
- Sans risque domain-specific (kind est universel : fact_lookup / list_enumeration / comparison / lifecycle_trace / contradiction_check / definition_lookup)

**Hiérarchie des options** :
1. **Option δ** (routing par kind) — 1-1.5j, gain attendu max, simple
2. **Option α-revised** (score fusion α=0.3) — 2-2.5j, gain attendu modéré, paramétrable
3. **Option β** (direct Phase 3) — 4-6j, laisse factual en régression

Si tu valides Option δ, je peux démarrer immédiatement P2.5-bis (1.5j) et bencher demain.

---

*Document produit en autonomie 24/05/2026 par Claude pendant absence Fred (~5h).*
*Configs A + B + C disponibles. Config E (RRF + DeepSeek Parse, no CE) reportée pour isoler R1 vs R3.*
*Référence audit factual : [P2_DIAGNOSTIC_FACTUAL_REGRESSION.md](P2_DIAGNOSTIC_FACTUAL_REGRESSION.md) — note : audit révisé par les données Config B, RRF est le coupable principal de la régression factual.*
*Référence spec P2.5 : [P2_5_SPEC_SCORE_FUSION.md](P2_5_SPEC_SCORE_FUSION.md) — à compléter avec Option δ.*
