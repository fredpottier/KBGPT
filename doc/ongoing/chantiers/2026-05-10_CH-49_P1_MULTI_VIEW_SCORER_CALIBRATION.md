# CH-49 Phase 1 — Calibration multi-view scorer (P1.6)

**Date** : 2026-05-10
**Statut** : 🟢 v1 — pack synthétique 50q validé
**Référence ADR** : `2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md` Cap5 (Amendments 7, 9)

---

## Pack de validation synthétique

50 paires (answer, gold) couvrant 5 catégories, conformes Amendment 9 ADR :

| Catégorie | n | But |
|---|---:|---|
| `exact_match_expected` | 10 | answer cite verbatim les identifiers/passages clés → exact ≥ 0.85 |
| `fuzzy_valid` | 10 | reformulation acceptable conservant key facts → fuzzy ≥ 0.75 |
| `semantic_valid` | 10 | paraphrase profonde sémantiquement équivalente → semantic ≥ 0.65 |
| `false_positives` | 10 | answer plausible mais factuellement fausse → toutes vues capées |
| `mixed` | 10 | abstain corrects + partial answers + lists |

Source : `benchmark/evaluators/multi_view_validation_pack.py`
Résultats : `data/benchmark/calibration/multi_view_scorer_validation.json`

---

## Résultats v1.0 (avant garde-fous)

| Catégorie | dominant_accuracy | score_accuracy |
|---|---:|---:|
| exact | 70% | 100% |
| fuzzy | 10% | 100% |
| semantic | 100% | 100% |
| **false_positive** | **0%** ❌ | **0%** ❌ |
| mixed | 70% | 90% |
| **Global** | **50%** | **78%** |

Diagnostic : le scorer laissait passer 100% des false_positives parce que la similarité sémantique (e5-large) reste élevée (>0.75) entre 2 phrases qui partagent le sujet général mais opposent les valeurs (« GDPR adopté par UN en 2010 » vs « EU en 2016 »).

---

## Garde-fou implémenté (semantic + fuzzy penalty)

Logique ajoutée dans `multi_view_score()` :

```python
if expected_identifiers:
    id_coverage = sum(i in answer for i in expected_identifiers) / n_id
    if id_coverage < 0.4:
        # Cap les vues permissives quand les identifiers attendus manquent
        s = min(s, 0.6)
        f = min(f, 0.7)
```

**Rationale** : si le gold annote des identifiers critiques (numéros de règlement, dates, codes) et que la réponse en couvre < 40%, la réponse est suspecte indépendamment de la similarité textuelle. Cela évite à la fois :
- Les faux positifs sémantiques (sujet partagé, valeurs opposées)
- Les faux positifs fuzzy (`partial_ratio` qui matche quand les tokens identiques se réordonnent : « CS-25 small <5700 kg » vs « large >5700 kg »).

---

## Résultats v1.1 (après garde-fous)

| Catégorie | dominant_accuracy | score_accuracy |
|---|---:|---:|
| exact | 70% | 100% |
| fuzzy | 10% (*) | 100% |
| semantic | 100% | 100% |
| **false_positive** | **90%** ✅ | **90%** |
| mixed | 70% | 90% |
| **Global** | **68%** | **96%** ✅ |

**(*)** La métrique `dominant_accuracy` sur `fuzzy` est artificiellement basse à cause du labeling pédagogique : 9/10 cas fuzzy sortent en `semantic` (sim > 0.95) ou `exact` parce que les paraphrases sont très proches. Le `score_accuracy` à 100% confirme que ces cas sont correctement validés (la "meilleure vue" passe le seuil attendu).

**False positives résiduels (1/10) :** un seul cas où l'identifier coverage atteint 40% (FP_09 — exact=0.333) glisse en fuzzy. Acceptable, le seuil 0.4 est calibrable (env override possible).

---

## Décisions de calibration

| Paramètre | Valeur | Source |
|---|---:|---|
| Seuil `exact` (dominant) | 0.95 | ADR Cap5 |
| Seuil `fuzzy` (dominant) | 0.85 | ADR Cap5 |
| Seuil `semantic` (dominant) | 0.75 | ADR Cap5 |
| Cap `semantic` (id_coverage<40%) | 0.6 | P1.6 calibration |
| Cap `fuzzy` (id_coverage<40%) | 0.7 | P1.6 calibration |
| Threshold id_coverage | 0.4 | P1.6 calibration |

Toutes calibrables via `thresholds` parameter sur `multi_view_score()`.

---

## Limites reconnues

1. **Pack synthétique 50q ≠ 100q ADR**. Décision Fred 2026-05-10 : 50q suffisent pour calibrer les seuils + détecter faux positifs grossiers. La validation à grande échelle se fera de fait via P1.7 (bench non-régression Robust 170q+).

2. **Embedder e5-large produit des sims génériques élevées** sur les phrases courtes/factuelles. Les vrais bénéfices du scorer multi-view se mesureront sur les questions complexes (multi-hop, causal) où la diversité de formulation est plus grande.

3. **Pas encore testé en mode unifié** (Amendment 7). Le bake-off A/B mode séparé vs unifié reste à faire en P1.7 avec scorer en place.

---

## Prochaines étapes

- **P1.7 — Bench non-régression Phase 1** : Robust 170q + T2T5 70q sur `/api/runtime_v4_2/answer` avec scorer multi-view branché. Mesurer gates ADR :
  - Robust ≥ 0.45 (vs V4.1 0.403)
  - false_abstain_rate ≤ 5%
  - p95 latency ≤ 12s
  - Pas de régression > 0.05pp factual/list/unanswerable

- **Post Phase 1** : validation 100q complète sur réponses runtime_v4_2 réelles (pas synthétiques). Donnera les seuils empiriques définitifs.
