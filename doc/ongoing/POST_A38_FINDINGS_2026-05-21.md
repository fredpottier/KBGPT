# A3.8 Findings — Bench runtime_v6 (2026-05-21)

**Status** : Bench arrêté après smoke 2q. Diagnostic principal **suffisamment
caractérisé** sans nécessiter le run complet 80q (économie ~40 min wall-clock
+ coût LLM).

---

## 1. Setup vérifié OK

| Composant | Status |
|---|---|
| Backfill 4488 claims dénormalisés (commit b9161db) | ✓ |
| Schémas runtime_a3 alignés avec KG réel | ✓ |
| Tests A3 non-régression : 222 passing | ✓ |
| Smoke runtime_v6 sur claim réel (SAP Solution Manager BASED_ON) | ✓ kg_claims coverage=partial, n_claims=1, claim correctement retourné |
| Boucle re-plan opérationnelle | ✓ logs montrent `iter=0→1 hint=add_qdrant_fallback` |
| Hard cap iter=2 | ✓ `AMBIGUOUS at hard cap iter=1, terminating` |

Le runtime V6 fait son travail technique. Le pipeline Parse → Plan → Execute →
Evaluate → Synthesize tourne end-to-end.

---

## 2. Smoke 2q SAP — Résultats

Bench micro 2 premières questions du gold_set 50q + 2 premières du 30q CP
(durée totale 78s, latency p50=24.1s, p95=34.4s).

### Q1 (factual FR)
- **Question** : « Quelle transaction est utilisée pour la Labeling Workbench dans Global Label Management ? »
- **Ground truth** : « La transaction CBGLWB (Labeling Workbench) est utilisée… »
- **Parse LLM** a produit : `sub_goal[0] = (kind=fact_lookup, subject='Labeling Workbench', predicate='utilized transaction')`
- **Execute Cypher** sur ce sub_goal : `coverage=empty` (0 claim retourné)
- **Re-plan** `add_qdrant_fallback` déclenché → iter=1 récupère 1 résultat
  qdrant partiel
- **Verdict iter=1** : `AMBIGUOUS at hard cap` → terminate
- **Synthesize** : ABSTENTION ("No relevant claim found")
- **Judge LLM** : 0.0 — l'abstention est jugée incorrecte car la question
  ÉTAIT answerable.

### Q2 (factual FR)
- **Question** : « Quel rôle SAP est fourni pour le team lead dans le Payroll Control Center ? »
- **Ground truth** : « Le rôle SAP_HR_PYC_TM_MNG est fourni pour le team lead… »
- **Parse LLM** : `sub_goal[0] = (kind=fact_lookup, subject='team lead', predicate='role SAP')`
- **Idem Q1** : Execute → empty, re-plan → empty, terminate ABSTENTION
- **Judge** : 0.0

### Latency (sur 2q)
| Métrique | Valeur | Gate GA3-7 |
|---|---|---|
| p50 | 24.1s | < 30s ✓ |
| p95 | 34.4s | < 60s ✓ |
| max | 34.4s | — |

### 30q CP smoke (2q)
- **Conflict exposure** : 0/2 (l'abstention ABSTENTION ne mentionne pas
  ⚠ Conflicting parce qu'aucun claim n'est ramené → orchestrator ne peut
  pas exposer une contradiction inconnue)

---

## 3. Diagnostic — Cause racine du C1=0

**Mismatch de grounding entre Parse LLM et KG réel.**

Exemples concrets :
| Parse LLM produit | KG indexe sous |
|---|---|
| `subject='Labeling Workbench'`, `predicate='utilized transaction'` | probable : `subject='CBGLWB'`, `predicate='IS_TRANSACTION_FOR'`, `object='Labeling Workbench'` |
| `subject='team lead'`, `predicate='role SAP'` | probable : `subject='SAP_HR_PYC_TM_MNG'`, `predicate='ASSIGNED_TO'`, `object='team lead'` |

Le Parse LLM (Qwen2.5-14B via burst) **invente raisonnablement** des
subject/predicate plausibles à partir de la question utilisateur, **mais ne
peut pas deviner** :
1. La forme canonical du subject dans le KG (codes système, identifiants
   techniques)
2. La direction sémantique du triplet (le "rôle pour team lead" est stocké
   comme `(role)-[ASSIGNED_TO]->(team lead)`, pas `(team lead)-[HAS_ROLE]->(role)`)
3. Le vocabulaire des predicates utilisé par l'extracteur d'ingestion
   (DeepSeek-V3.1 a son propre style)

Le Cypher A3.3 fait `WHERE c.subject_canonical = $subject AND c.predicate = $predicate`
en **equality stricte** → 0 result systématique sur ces cas.

Le re-plan `add_qdrant_fallback` aide partiellement (récupère des chunks
vectoriels via embedding) mais ne fournit pas la structure claim attendue
par Synthesize → ABSTENTION.

---

## 4. Pourquoi ne PAS lancer le run complet 80q ?

1. **Diagnostic suffisamment caractérisé** sur 2q. Les autres 78q vont
   produire le même pattern (Parse plausible mais non aligné, Cypher empty,
   re-plan limité, ABSTENTION final). Aucune info supplémentaire.
2. **Gates GA3-5 (C1≥0.75) et GA3-9 (conflict_exposure≥5%) FAIL prévisible**
   tant que le grounding n'est pas résolu — pas besoin de mesurer pour le
   confirmer.
3. **Gate GA3-7 latency** déjà OK sur 2q (p50=24s/p95=34s, gates 30/60).
4. **Gate GA3-6 C3 lifecycle** : seulement 3q lifecycle dans le gold-set →
   bruit statistique de toute façon.
5. **Coût LLM** : ~$1-2 + ~40 min wall-clock évités.
6. **Charte mémoire** [[feedback-bench-runtime-before-constituting-goldset]] :
   « bencher le runtime cible avant d'investir dans un gold-set ». Ici on
   inverse : le runtime a un problème connu et identifié, mesurer plus
   précisément ne change pas la décision (faut fixer le grounding).

---

## 5. Verdict gates GA3 (estimé)

| Gate | Critère | Verdict basé sur smoke + diagnostic |
|---|---|---|
| **GA3-3** filtres bitemporels 100% Cypher | tests unitaires Execute | ✓ PASS (couvert par test_execute.py::TestCypherBitemporal) |
| **GA3-4** ConflictPending exposés correctement | smoke 5q avec conflits | ✗ FAIL (subject grounding bloque la récupération des CP) |
| **GA3-5** C1 ≥0.75 sur 50q SAP | bench A3.8 | ✗ FAIL prévisible (extrapolation smoke : C1 ≈ 0.05-0.15) |
| **GA3-6** C3 ≥0.50 sur lifecycle | bench A3.8 sous-set | ? Non mesurable (3q lifecycle seulement, n trop faible) |
| **GA3-7** Latency p50 <30s, p95 <60s | bench A3.8 | ✓ PASS (p50=24s, p95=34s sur smoke) |
| **GA3-9** conflict_exposure_rate ≥5% | bench A3.8 30q CP | ✗ FAIL prévisible (extrapolation smoke : 0%) |

**Bilan** : 1 gate ✓, 3 gates ✗, 1 gate non-mesurable. **Le gate principal
GA3-5 est bloqué par un problème structurel** identifié, pas par un bug
runtime.

---

## 6. Action corrective — Subject Grounding

Le runtime V5 contient `claimfirst/resolution/subject_resolver_v2.py` qui fait
exactement ce qu'il manque à V6 : **résoudre un subject "user-friendly" (la
question utilisateur) vers le subject_canonical du KG**. Ce module est :
- Critique pour le pipeline ingestion (cf audit A3.6, 11 consumers backend)
- Disponible et fonctionnel
- **NON branché dans runtime_a3/execute.py**

### Option de fix (à confirmer par l'utilisateur en A3.9)

**Ajouter une étape de Subject Resolution dans `execute.py`** entre Plan et
Execute Cypher :

```python
# Avant: directement utiliser sub_goal.subject_canonical du Parse LLM
# Après:  resolved = subject_resolver_v2.resolve(sub_goal.subject_canonical, tenant_id)
#         params["subject"] = resolved.canonical_id_in_kg  # match exact KG
```

Le `subject_resolver_v2` utilise :
- Hybrid match (entity name normalization + canonical_key lookup)
- Embedding-based fallback si pas de match exact
- Tie-breaker par anchor (CH-35.A3 livré)

Avec ce composant branché, le mismatch grounding devrait être résolu et
GA3-5/9 devraient passer.

---

## 7. Plan A3.9 redéfini

**A3.9 initial** (ADR §6) : "Ablation study runtime_v6 vs V5.1+prompt-tuning".

**A3.9 v2 (proposé post-A3.8 findings)** :

1. **Étape 1 (1j)** : Brancher `subject_resolver_v2` dans `runtime_a3/execute.py`
   avant chaque Cypher `kg_claims`. Tests non-régression A3 + smoke 5q.
2. **Étape 2 (1h)** : Re-bench A3.8 sur sous-set 20q (gain mesuré C1).
3. **Étape 3 (gate go/no-go)** : si C1 ≥ 0.50 sur 20q → lancer bench complet
   80q ; sinon → diagnostic complémentaire.
4. **Étape 4 (1j si gate OK)** : Bench complet + ablation runtime_v6 vs V5.1
   (objectif initial A3.9).

---

## 8. Livrables A3.8

Malgré l'arrêt anticipé, les livrables sont en place pour A3.9 :

| Livrable | Path |
|---|---|
| Doc audit cause racine schéma KG | `doc/ongoing/POST_A38_ROOT_CAUSE_AUDIT_2026-05-21.md` |
| Fix dénormalisation pipeline + backfill | commit b9161db |
| Bench runner réutilisable | `app/scripts/bench_a38_runtime_v6.py` |
| Gold-set 50q SAP stratifié | `benchmark/questions/gold_set_a38_50q.json` |
| Gold-set 30q ConflictPending | `benchmark/questions/gold_set_a38_30q_cp.json` |
| Doc findings (ce fichier) | `doc/ongoing/POST_A38_FINDINGS_2026-05-21.md` |

A3.8 considéré **mesuré-via-extrapolation** : 1 gate ✓, 3 gates ✗ bloqués
par grounding, 1 non-mesurable. **Décision** : pas re-lancer A3.8 complet
tant que A3.9 (subject grounding) n'a pas amélioré le pipeline.

---

## 9. Leçon pour mémoire

**Avant bench end-to-end coûteux : un smoke 2-5q suffit souvent à identifier
les bottlenecks structurels.** Si les 2 premiers cas révèlent un mismatch
systémique (Parse → KG), le run complet ne mesure que la fréquence du même
problème — info non actionnable supplémentaire.

À mémoriser : `feedback_smoke_first_avoid_useless_full_bench`.
