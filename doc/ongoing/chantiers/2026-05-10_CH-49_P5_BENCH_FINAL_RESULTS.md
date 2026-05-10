# CH-49 P5 — Bench final 120q architecture complète OSMOSIS V4.2

**Date** : 2026-05-10
**Bench** : `aero_t6_robustness.json` (120 questions, 10 catégories)
**Endpoint** : `/api/runtime_v4_2/answer` avec **toute l'architecture cible activée** :
- Layer 0 (Cheap Certainty + Q↔A Verifier DeepSeek anti-biais)
- 5 operators Cap2.A/B/C/D/E
- UnifiedIntentRouter
- Verifier veto post-operator
- Layer 2 Adaptive Orchestrator (DeepSeek tool use, 5 iters max)
- Multi-view scorer + abstain reward + telemetry QuestionTrace

**Workers** : 4 parallèles
**Wall total** : 1063s (17min42s)
**Output** : `data/audit/runtime_v4_2_p5_final_bench_robust.json`

---

## Résultats globaux

| Métrique | Valeur |
|---|---:|
| score_best mean | **0.858** |
| p50 latency | 28.9s |
| p95 latency | **87.7s** |
| Layer 0 | 114/120 (95%) |
| Layer 1 | 4/120 (temporal 2 + set_reasoning 2) |
| Layer 2 visible | 1/120 |
| false_abstain rate | 52.9% |

---

## Comparatif progression Robust 120q

| Phase | Architecture | n | score_best | p50 | p95 | Wall |
|---|---|---:|---:|---:|---:|---:|
| V4.1 baseline | Pipeline V4.1 facts-first | 120 | 0.403 | — | — | — |
| P1 | Layer 0 + Cap2.A only | 120 | 0.867 | 8.6s | 19.9s | 301s |
| P2 (no veto) | P1 + Cap2.B/C/D | 120 | 0.861 | 15.4s | 23.1s | 438s |
| P2 + veto | P2 + verifier veto critical | 120 | 0.859 | 19.7s | 37.7s | 630s |
| P3 smoke | P2 + Layer 2 | 30 | 0.911 | 36.6s | 53.8s | 270s |
| P4 smoke | P3 + UnifiedIntentRouter | 30 | 0.905 | 29.9s | 57.3s | 253s |
| **P5 final** | **P4 + Cap2.E (full archi)** | 120 | **0.858** | **28.9s** | **87.7s** | **1063s** |

### Observations

1. **Score plateau ~0.86** sur ce corpus indépendamment de la complexité ajoutée. Layer 2 + Cap2.E + router unifié n'apportent **pas de gain qualité visible** sur le bench Robust aérospace.

2. **Latence cumule de manière prévisible** :
   - +110% p95 entre P2 simple (37s) et P5 full (88s)
   - Cause : cascade verifier veto sur 4-5 operators + Layer 2 sur abstain

3. **Distribution layer en mode "everything works as expected"** :
   - 95% Layer 0 (la majorité des questions ne matchent pas les patterns Cap2)
   - 4 Layer 1 trigger (sur 4 LIFECYCLE_RELATION + claims diversity limitées)
   - 1 Layer 2 réussi (verifier accepte la composition)

---

## Diagnostic cause du plateau qualité

**Hypothèse principale** : la qualité Layer 0 est déjà élevée pour les questions où le retrieval donne la bonne réponse. Layer 1 ne s'active que sur questions structurelles très précises (rare sur ce corpus). Layer 2 est rejeté par le verifier (anti-Goodhart strict).

**Conséquence** : le score score_best mean ≈ score Layer 0 seul, parce que Layer 1+2 n'attrappent que ~4 questions sur 120.

**Pour vraiment voir un gain qualité**, il faudrait :
1. Un corpus avec plus de **LIFECYCLE_RELATION** (déclarations explicites comme "X repealed by Y")
2. Plus de **claims diversifiés** sur les mêmes (subject, predicate) pour Cap2.E
3. Plus de questions **structurellement complexes** (CHAIN, COUNT) où le KG est riche
4. Un **verifier moins strict** sur Layer 2 (mais ça réintroduit le risque Goodhart)

→ Le **Test Armand corpus** (CS-25 + dual-use enrichis) sera le vrai révélateur.

---

## Verdict

🟢 **Architecture cible OSMOSIS V4.2 livrée ET fonctionnellement complète** :
- ✅ Tous les composants ADR §1 livrés (Cap1-5)
- ✅ Charte respectée (audit grep 0 référence corpus)
- ✅ Modèles open-source uniquement (no Sonnet/GPT-4o)
- ✅ Anti-biais auto-juge (Verifier ≠ Composer)
- ✅ Anti-Goodhart (verifier veto strict)
- ✅ Pas de promotion endpoint principal (V4.1 reste actif en parallèle)

🟡 **Latence haute** sur ce corpus (p95 88s) — optimisations futures :
- Coupler router-operator pour params extraction (gain ~6s p50 estimé)
- Parallélisation calls intent detection (gain ~3s p50 estimé)
- Layer 2 budget compute serré (current 5 iters, peut être 3 max)

🟡 **Gain qualité non démontrable** sur ce corpus — attendre Test Armand.

---

## Prochaines étapes

1. **Pause / consolidation** : 4 commits poussés, MEMORY/TRACKING à jour
2. **Phase suivante** (à décider en session future) :
   - Option A : optimisations latence Phase 4+ (coupler router-operator)
   - Option B : préparer Test Armand (KG enrichment via documents officiels avec déclarations explicites)
   - Option C : audit dette charte historique (`list_verifier.py` regex prefixes corpus-spécifiques — task #226)
