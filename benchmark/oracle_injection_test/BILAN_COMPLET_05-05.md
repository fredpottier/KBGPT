# Bilan complet 3 benches — Sprint A+B+C.1 — 2026-05-05 02:21

## Vue d'ensemble

| Bench | Baseline 04/05 | Post Sprint A+B+C.1 | Δ | Cible | Gap |
|---|---|---|---|---|---|
| RAGAS faithfulness_total | 0.607 | **0.759** | **+15.2pp** | 0.80 | -4.1pp |
| Robust global (Llama-70B) | 0.455 | **0.495** | **+4.1pp** | 0.75 | -25.5pp |
| T2T5 composite | 0.367 | 0.382 | +1.5pp | 0.80 | -41.8pp |

## RAGAS détail

| Métrique | Baseline | Post | Δ |
|---|---|---|---|
| faithfulness | 0.590 | 0.677 | **+8.7pp** ✅ |
| context_relevance | 0.754 | 0.788 | +3.4pp ✅ |
| faithfulness_total | 0.607 | **0.759** | **+15.2pp** ✅✅ |

C'est la métrique la plus probante : **+15.2pp sur faithfulness_total** (avec KG context).
Confirme l'efficacité des fixes B.1+B.2+B.3 (cross-lingual + skip-regen).

## Robust détail (apples-to-apples Llama-70B)

### ✅ Gains majeurs (+10pp ou plus)

| Catégorie | Baseline | Post | Δ |
|---|---|---|---|
| causal_why | 0.433 | 0.742 | **+30.8pp** ✅✅ |
| multi_hop | 0.408 | 0.600 | **+19.2pp** ✅ |
| conditional | 0.207 | 0.336 | +12.9pp ✅ |
| anchor_applicability_temporal | 0.346 | 0.467 | +12.1pp ✅ |
| temporal_evolution | 0.375 | 0.475 | +10.0pp ✅ |

Ces catégories étaient explicitement ciblées par Sprint A (retrieval) + B (synthèse/cross-lingual) + C.1 (lifecycle).

### ❌ Régressions (-5pp ou plus)

| Catégorie | Baseline | Post | Δ |
|---|---|---|---|
| false_premise | 0.637 | 0.508 | **-12.9pp** ❌ |
| unanswerable | 0.708 | 0.617 | -9.2pp ❌ |
| negation | 0.640 | 0.560 | -8.0pp ❌ |
| set_list | 0.179 | 0.121 | -5.7pp ❌ |

**Hypothèse** : le filter bypass (A.2) + skip-regen (B.3) rendent la pipeline plus "active" — elle tente plus souvent de répondre. Conséquence : sur les cas où l'abstention est correcte, la pipeline répond avec hallucination ou réponse partielle.

C'est un trade-off à corriger en Sprint D : ajouter des "abstention guards" qui forcent l'abstention sur signaux clairs (fausse prémisse détectée par premise validator, question hors corpus, etc.).

### ≈ Catégories stables

| Catégorie | Baseline | Post | Δ |
|---|---|---|---|
| hypothetical | 0.580 | 0.650 | +7.0pp |
| anchor_scope_hierarchy | 0.333 | 0.367 | +3.3pp |
| lifecycle_supersedes | 0.420 | 0.460 | +4.0pp |
| lifecycle_vs_conflict | 0.475 | 0.469 | -0.6pp |
| synthesis_large | 0.533 | 0.521 | -1.2pp |
| lifecycle_evolves_from | 0.629 | 0.614 | -1.4pp |
| lifecycle_filtering_active | 0.567 | 0.544 | -2.2pp |

## T2T5 détail

| Métrique | Baseline | Post | Δ |
|---|---|---|---|
| tension_mentioned | 0.125 | 0.225 | **+10.0pp** ✅ |
| chain_coverage | 0.302 | 0.377 | +7.6pp ✅ |
| both_sources_cited | 0.550 | 0.575 | +2.5pp ✅ |
| both_sides_surfaced | 0.225 | 0.215 | -1.0pp ≈ |
| multi_doc_cited | 0.633 | 0.518 | **-11.5pp** ❌ |
| **Composite** | **0.367** | **0.382** | **+1.5pp** |

## Diagnostic des régressions

### false_premise -12.9pp (le plus inquiétant)

Le pipeline détecte moins bien les fausses prémisses car la skip-regen logic (B.3) skip parfois la régénération même quand premise est CONTRADICTS faiblement.

**Fix Sprint D** : skip-regen seulement quand premise CONTRADICTS confidence < 0.5. Si CONTRADICTS confidence ≥ 0.5 → toujours adopter regen (= abstention).

### unanswerable -9.2pp

Les questions hors corpus reçoivent maintenant des réponses partielles (synthèse + faithfulness PARTIAL préservée). Avant, faithfulness UNFAITHFUL forçait abstention.

**Fix Sprint D** : si retrieval retourne 0 chunks de docs autoritaires OU si premise indicates "question hors scope" → forcer abstention sans synthèse.

### negation -8.0pp

Probablement une régression liée à la détection des "qu'est-ce qui N'EST PAS". Le bypass filter sur factual_value laisse passer trop de chunks → synthèse confuse.

### set_list -5.7pp

Le rerank GPU favorise les chunks pertinents mais peut casser les listes (qui demandent souvent plusieurs chunks complémentaires de docs différents). Lié à la régression -11.5pp multi_doc_cited sur T2T5.

## Plan Sprint D

| ID | Levier | Effort | Impact attendu |
|---|---|---|---|
| D.1 | Synthesis prompt v3 — détection prémisses fausses quantitatives | ✅ implémenté nuit | récupère ~+10pp false_premise |
| D.2 | Domain Pack hints aerospace_compliance (NPA, ED, EU Articles) | 4j | +3-5pp anchor_scope, set_list |
| D.3 | Confidence-based final abstention (entropy + faith + hallu_guard composite) | 2j | -50% hallucinations résiduelles |
| D.4 | Re-bench complet final post Sprint D | 2j | mesure |

## D.1 implémenté (2026-05-05 02:25)

Modification du prompt synthesis dans `src/knowbase/runtime_v2/synthesis.py` :

- **Règle 10** : détecter quand la question affirme une valeur spécifique (60 jours, 50 J, "tous les transferts", "seul l'EASA") qui contredit l'évidence. Forcer la mention de la contradiction au lieu de valider la prémisse.
- **Règle 11** : pour questions "Pourquoi X...", vérifier d'abord que X est supporté par l'évidence avant de construire une justification.

**Cible bench** : récupérer les régressions sur false_premise (-12.9pp), unanswerable (-9.2pp), negation (-8.0pp).

**Test** : nécessite un restart de l'app + re-bench (à faire au réveil).

## Estimation gain Sprint D total

- RAGAS : 0.759 → 0.80 (+4pp)
- Robust : 0.495 → 0.55-0.58 (+5-9pp dont récupération régressions D.1)
- T2T5 : 0.382 → 0.42 (+4pp)

Encore loin de 80/80/75 mais trajectoire positive.

## Récap de la nuit

- 3 benches lancés vs baseline 04/05
- T2T5 fini en 5min, RAGAS en 1h10, Robust solo en 2h17 (170 q × 27s + judge)
- Modifications cumulées Sprint A+B+C.1+D.1 : 14 fichiers modifiés/créés
- Documentation : `SPRINT_AB_STATUS.md` + ce fichier
- Prochaine action proposée : restart app + re-bench Robust+RAGAS pour valider gain D.1
