# État des lieux Phase A3 — 22/05/2026

> Document de cadrage stratégique post-A3.11 + tentative A3.10 rollback.
> **Objectif** : faire le point sur la valeur livrée, les hypothèses validées/invalidées, et décider d'amender ou non la roadmap avant d'investir plus.

---

## 1. Plan initial Phase A3

La Phase A3 (runtime Parse → Plan → Execute → Evaluate → Synthesize) est née du **pivot V4 Facts-First** (CH-49, 10/05/2026) et a été rédigée dans `ADR_PARSE_EVALUATE_RUNTIME.md` (A3.0, 19/05).

**Hypothèse fondatrice du pivot** :
> Une architecture LLM-orchestrée stricte (Parse→Plan→Exec→Eval→Synth) avec **traçabilité fait→claim_id obligatoire** sera supérieure à V5.1 (Reading Agent libre) à la fois en qualité (verbatim citations, ConflictPending détection) et en gouvernance (audit trail strict).

**Gates ADR** :
- GA3-5 : C1 ≥ 0.75 sur 50q SAP stratifiées
- GA3-6 : C3 ≥ 0.50 sur sous-set lifecycle
- GA3-7 : latence p50 < 30s, p95 < 60s
- GA3-9 : conflict_exposure_rate ≥ 5% sur 30q CP

---

## 2. Livré sur Phase A3 (29 sprints completed)

| Sprint | Status | Sortie |
|---|---|---|
| A3.0 ADR rédigé | ✅ | `doc/architecture/ADR_PARSE_EVALUATE_RUNTIME.md` |
| A3.1 Parse | ✅ | LLM #1 décomposition sub-goals |
| A3.2 Plan | ✅ | Mapping déterministe sub_goal → tool |
| A3.3 Execute | ✅ | Cypher + Qdrant + bitemporel |
| A3.4 Evaluate | ✅ | LLM #2 verdict 4-classes (réduit à 3) |
| A3.4-bis Bench evaluator | ✅ | Verdict CORRECT/AMBIGUOUS/INSUFFICIENT |
| A3.5 Synthesize | ✅ | LLM #3 rédaction + citations |
| A3.6 Suppressions V5.1 | ✅ | Deprecated 5 modules legacy |
| A3.7 Endpoint API | ✅ | `/api/runtime_v6/answer` actif |
| A3.8 Bench A3 final | ✅ | Gold-set 50q+30q construit |
| A3.9 Subject Resolver | ✅ | 5-step EKX, +35 tests unit |
| A3.9-bis Predicate Resolver | ✅ | Embeddings cosine, +25 tests |
| A3.11 Claim Filter | ✅ | Sémantique stratifié sub_goal, +19 tests |
| A3.10 Retrieval Cascade | ❌ ROLLBACK | Régression -0.025pp C1, +133% p95 |

**Code livré** : 3 modules resolvers + 1 claim_filter, 301 tests A3 verts, 4 commits propres (f3b1d23, 3410609, 27a165b + rollback).

---

## 3. Mesures actuelles vs cible

### Bench 20q SAP A3.11 (post-resolvers + filter, pre-cascade)

| Métrique | Mesuré | Cible GA3 | Écart |
|---|---|---|---|
| **C1 global (LLM-judge)** | **0.175** | 0.75 | **-0.575pp** |
| C1 factual (n=15) | 0.233 | — | — |
| C1 comparison (n=5) | 0.000 | — | — |
| Coverage non-empty | 100% | — | ✅ (vs A3.8 baseline ~0%) |
| Verdict Evaluate CORRECT | 65% | — | ✅ |
| Latence p50 | 23s | 30s | ✅ |
| Latence p95 | 41s | 60s | ✅ |
| Citation coverage | 100% | — | ✅ |

### Audit fails (verbatim 15 cas judge=0.0)

| Catégorie | Count | Cause |
|---|---|---|
| **A — Claim hors-sujet retenu** | 6/15 | Subject OK mais Synthesize cite mauvais claim |
| **B — KG manque l'info précise** | 6/15 | Abstention honnête, judge pénalise |
| **C — Subject non extrait / hallucination** | 3/15 | Parse rate ou Synthesize hallucine |

### Référence V5.1 sur autre bench (non apples-to-apples)

- V5.1 A3 (parity) = 0.450 sur `gold_set_sap_v2` 50q
- V5.1 A6 (topics) = 0.540
- V5.1 A7 (find_in TF-IDF) = **0.620**
- V5.1 Sonnet (plafond LLM) = 0.710

**Ordre de grandeur** : runtime_v6 actuel (0.175) est **vraisemblablement inférieur** à V5.1 (0.45-0.62), même en tenant compte des différences de gold-set (le `gold_set_a38_50q` est plus stratifié-difficile).

---

## 4. Hypothèses du pivot — Status

| Hypothèse pivot V4 | Validée ? | Évidence |
|---|---|---|
| H1. Pipeline structuré > Reading Agent libre | ❌ Non validée | C1 0.175 vs 0.62 V5.1 (ordres de grandeur) |
| H2. Traçabilité fait→claim_id obligatoire | ✅ Atteint | 100% citation coverage, claim_id partout |
| H3. ConflictPending détection automatique | ⚠️ Non testé sur bench (30q CP skip) | À mesurer |
| H4. Latence dans cible | ✅ p50/p95 OK | Mais avec EC2 burst spécifique |
| H5. Domain-agnostic strict | ✅ Atteint | Resolvers + filter sans token corpus-spécifique |
| H6. KG-first élimine hallucinations | ⚠️ Partiel | Cat A montre que LLM cite quand même claims hors-sujet |

**Bilan** : la traçabilité et la latence sont atteintes (atouts techniques). La **qualité de réponse** (cible primaire utilisateur) est en-dessous de V5.1.

---

## 5. Causes structurelles diagnostiquées

### 5.1 Limite architecturale KG-only

Runtime_v6 ne peut citer **que des claims pré-extraits du KG**. Si l'info précise n'est pas dans un claim :
- soit elle existe en texte source PDF (V5.1 peut la lire, runtime_v6 non)
- soit elle n'a pas été extraite par le pipeline d'ingestion (claim manquant)

**Conséquence** : 6/15 cat B = abstention honnête au lieu de réponse. Le judge LLM pénalise (sous-évaluation systématique cf mémoire `feedback_prometheus_underjudges_2026`).

### 5.2 Sélection claim ≠ pertinence sémantique fine

A3.11 a réduit (de 30 à 5) les claims envoyés au Synthesize. Mais l'embedding e5-large sur claim_text ne discrimine pas suffisamment finement (scores serrés [0.85-0.93]). Le LLM choisit parfois un claim générique au lieu du spécifique attendu.

**Conséquence** : 6/15 cat A = mauvais claim retenu.

### 5.3 Tentative A3.10 (cascade Qdrant) → échec mesuré

Ajouter les sections Qdrant au prompt Synthesize a :
- ✅ aidé 2 cas (+1.5 points)
- ❌ régressé 2 cas (abstention juste → fausse réponse, -2 points)
- ❌ explosé p95 latence (+133%)

**Raison** : le LLM voit plus de contexte → tendance à répondre avec des sections approximatives au lieu d'abstenir. Pas une amélioration nette.

### 5.4 KG actuel sous-équipé pour les questions du gold-set

Le KG résulte de la réingestion post-Phase A2 (commit b9161db). Possiblement :
- Pas tous les codes transaction extraits (cat B Q3, Q8)
- Pas toutes les options Azure connectivity listées comme claims (cat B Q1)
- SAP Notes pas en claims (cat B Q10 "client 066")

**Question ouverte** : enrichir le KG (re-extraction avec prompts plus poussés) avant d'investir plus dans le runtime ?

---

## 6. Options pour la suite

### Option A — Continuer A3 en l'état, viser quick wins

- Tuner les seuils MIN_SCORE claim_filter
- Améliorer prompts Parse pour mieux extraire subjects rares
- Recalibrer judge LLM (gold_truth en référence → moins de FP)
- **Gain estimé** : C1 0.175 → 0.20-0.25
- **Coût** : 2-3j
- **Risque** : ne ferme pas l'écart vs V5.1, gains marginaux

### Option B — Enrichir le KG via re-extraction

- Audit des claims manquants (cat B)
- Re-run du pipeline ingestion avec prompts plus précis (transactions, codes, identifiants)
- **Gain estimé** : C1 +0.10-0.20pp si KG enrichi
- **Coût** : 1-2 semaines (re-ingestion 38 docs + validation)
- **Risque** : on ne sait pas avant si l'info est dans les PDFs ou pas

### Option C — Architecture hybride V5.1 + runtime_v6

- Garder runtime_v6 pour questions factuelles strictes (traçabilité)
- Router vers V5.1 quand abstention probable (lecture libre PDF)
- **Gain estimé** : C1 monte au niveau V5.1 (0.45-0.62) + traçabilité préservée
- **Coût** : 1-2 semaines (router + fallback orchestration)
- **Risque** : complexité (2 architectures en parallèle, judgment call à automatiser)

### Option D — Bench apples-to-apples d'abord

- Re-runner V5.1 sur `gold_set_a38_50q` pour mesurer l'écart REEL
- Re-runner runtime_v6 sur `gold_set_sap_v2` pour la même raison
- **Gain** : décision informée (et non pas estimation)
- **Coût** : ~2h de bench
- **Risque** : aucun

### Option E — Pause Phase A3, retour V5.1 prod

- Reconnaître que le pivot V6 n'est pas encore au niveau
- Réactiver V5.1 comme runtime principal
- Reprendre Phase A3 après enrichissement KG (ou jamais)
- **Coût** : 1j (config endpoint)
- **Risque** : effort déjà investi semble "perdu" mais l'apprentissage reste

---

## 7. Recommandation

**Option D + B en cascade** :

1. **D** d'abord (~2h) : faire le bench apples-to-apples pour quantifier l'écart **réel** V5.1 vs runtime_v6. Évite de décider sur estimations.
2. Si écart confirmé > 0.20pp : **B** (enrichir KG) avant tout autre chantier runtime. Sans KG riche, runtime_v6 ne peut pas dépasser V5.1 par construction.
3. Si écart < 0.10pp : runtime_v6 est compétitif, on peut continuer Option A (tuning) avec confiance.

**Anti-pattern à éviter** (vu déjà aujourd'hui sur A3.10) :
- Ajouter une feature, mesurer un delta sur 20q (n trop petit), conclure, dériver
- Multiplier les sous-chantiers en réponse à des résultats bruyants

**Principe directeur** : **bench rigoureux > intuition** sur des n≥50.

---

## 8. Garde-fous décidés (cf mémoires session)

- ✅ Ne plus dépriécier V5.1 tant que runtime_v6 ne le dépasse pas en bench rigoureux (mémoire `project_runtime_v6_below_v51_alert`)
- ✅ Smoke 2-5q avant bench complet (mémoire `feedback_smoke_first_avoid_useless_full_bench`)
- ✅ Toujours cible complète, jamais MVP (mémoire `feedback_always_target_never_minimal`)
- ✅ Domain-agnostic strict (mémoire `feedback_domain_agnostic_strict`)

---

## Décision attendue de Fred

- [ ] Option choisie : ___
- [ ] Pas de nouveau chantier runtime avant que cette décision soit prise
- [ ] A3.10 reste en `pending` (rollback effectué)
- [ ] Tasks Phase A3 → état stable sur A3.11

---

## 9. ⚠️ ADDENDUM (22/05/2026 après-midi) — Découverte critique : 61% des claims sont muets

### Audit KG révélateur

Question de Fred : « avec les infos dans le système, est-ce que le système mobilise les bonnes infos pour répondre ? » a déclenché un audit du KG :

```cypher
MATCH (c:Claim {tenant_id:'default'})
RETURN count(c) AS total,
       count(CASE WHEN c.subject_canonical IS NULL THEN 1 END) AS n_null
// → total=11622, n_null=7134 (61.4%)
```

**61% des claims du KG n'ont PAS de `subject_canonical`** → ils sont **structurellement invisibles** au retrieval `MATCH (c:Claim {subject_canonical:X})` du runtime_v6.

### Vérification que l'info attendue EST en KG

Audit verbatim sur 5 cas cat B (présumés "KG manque info") :

| Q | Info attendue | En KG ? |
|---|---|---|
| Q1 RISE Azure | ExpressRoute, VPN | ✅ sous subject="AWS Direct Connect" |
| Q3 /SAPAPO/OM13 | livecache control | ⚠️ 11 claims livecache mais 0 OM13 |
| Q4 codes WWI | AA, ZS, ZD | ❌ probable absence réelle |
| Q6 CG5Z WWI Monitor | transaction CG5Z | ✅ **claim_5bebb77ee026** avec subject_canonical=NULL |
| Q8 CGSADM | Expert cache transaction | ✅ multiple claims |

**Conclusion** : 4/5 cas dits "KG manque info" étaient en réalité des **fails de retrieval** liés à `subject_canonical=NULL` ou subject indexé sous nom différent. **Mon Option B initiale (enrichir KG via re-extraction) traitait un faux problème.**

### Cause architecturale

- `subject_canonical` est dérivé de `structured_form_json` (StructuredExtractor)
- Pipeline ClaimFirst de base **n'appelle pas** systématiquement StructuredExtractor
- Backfill A3.8 (`b9161db`) a dénormalisé seulement les 4488 claims qui AVAIENT déjà `structured_form_json`
- Conséquence : 7134 claims orphelins, **muets** au retrieval principal

### Règle de gouvernance posée par Fred

> « Un claim doit avoir un subject_canonical et si ce n'est pas le cas (claim bruité, autre motifs), alors cela doit rester marginal car sinon, cela revient à dire, selon moi, que le claim en lui-même a peu de valeur. »

Seuil acceptable de NULL : **< 5%** (claims authentiquement bruités). Au-delà → bug pipeline.

### Roadmap adaptée — Phase A4 prioritaire

**Phase A4 — Subject Canonical Coverage** (bloquant tout autre tuning runtime) :

| Task | Description | Durée | Status |
|---|---|---|---|
| **A4.1** | Audit racine pipeline ClaimFirst (où subject_canonical est perdu) | 0.5j | #349 pending |
| **A4.2** | Brancher extraction systématique dans pipeline ClaimFirst + flag `marginal=true` si échec | 2-3j | #350 pending (blocked by A4.1) |
| **A4.3** | Backfill 7134 claims orphelins via LLM Qwen2.5-14B vLLM burst | 1-2j + run | #351 pending (blocked by A4.2) |
| **A4.4** | Validation coverage ≥ 95% + re-bench 20q sans toucher runtime | 0.5j | #352 pending (blocked by A4.3) |

### Gain attendu Phase A4

- Resolver A3.9 (subject grounding) trouvera plus de claims (Entity.normalized_name mieux peuplé via plus de claims structurés)
- Runtime aura accès à **95%+** du KG au lieu de 38%
- **Gain C1 estimé : +0.15 à +0.30pp** (à valider par re-bench A4.4)

### Anti-pattern à éviter (rappel)

- ❌ Continuer à tuner le runtime sur 38% du KG sans corriger la racine
- ❌ Optimiser claim_filter / predicate_resolver / cascade Qdrant sans accès aux 7134 claims muets
- ❌ Lancer A3.10 ou autres chantiers runtime avant A4

### Recommandation révisée

**A4 → re-bench A4.4 → décision sur options A/B/C/D/E initiales** (la majorité deviendront probablement caduques).

Le **bench apples-to-apples (Option D)** ne deviendra pertinent qu'**APRÈS** A4 livré : avant cela, il mesurerait un runtime amputé de 62% du KG.

### Lien avec l'alerte runtime_v6 < V5.1

Cette découverte **explique partiellement** pourquoi runtime_v6 < V5.1 :
- V5.1 lit le **texte source PDF** → accède à 100% du contenu
- Runtime_v6 actuel lit les claims **subject-indexed** → 38% du KG
- **Post-A4** : runtime_v6 accédera à 95%+ du KG. La vraie question pour la suite : suffit-il d'avoir tous les claims subject-indexed, ou faut-il aussi la lecture libre texte ?

Lié : `project_subject_canonical_must_be_quasi_mandatory.md` (mémoire), `project_runtime_v6_below_v51_alert.md`.

