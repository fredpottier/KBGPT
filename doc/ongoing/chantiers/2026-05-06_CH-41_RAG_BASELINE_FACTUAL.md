# CH-41.0 livrable E — RAG baseline factual_correctness

**Date** : 2026-05-06
**Owner** : CH-41 (V4 Facts-First, gate D-FF13)
**Statut** : ✅ DONE 2026-05-06 (mesure exécutée, baseline persisté)

## Objectif

Mesurer la performance du pipeline V3 actuel sur les questions factual du gold-set v4. Ce baseline sert de seuil-plancher pour l'activation du **D-FF13 chunk-extractive fallback** (tranche V4 Facts-First) :

```
Gate ship D-FF13 :
  factual_correctness(facts-first + D-FF13) ≥ factual_correctness(V3 baseline)
  sur ≥ 30 questions factual
```

## Périmètre mesure

- **Source** : `benchmark/questions/gold_set_v4.json`
- **Filtre** : `primary_type == "factual"` → **25 questions** (6 EN + 19 FR)
- **Pipeline mesuré** : V3 actuel (`/api/runtime_v3/answer`) — 5 stages : retrieve hybrid → BGE rerank → agentic synthesis → mDeBERTa NLI → conditional regen
- **Métrique** : RAGAS `FactualCorrectness` (reference-based, ne nécessite que `response` + `reference` — pas `user_input`)
- **Juge** : Llama-3.3-70B-Instruct via DeepInfra (cohérent S0)

## Note sur la dénomination « RAG baseline »

Le pipeline V3 n'est pas un « RAG pur » au sens strict (chunks → LLM → réponse sans étapes intermédiaires). Il contient un agentic synthesis et un verifier NLI conditionnel. Cependant, dans le contexte du pivot V4 :
- V3 = état de l'art OSMOSIS pré-pivot
- D-FF13 ne doit pas régresser par rapport à V3 sur factual simple

Donc « RAG baseline » dans D-FF13 = baseline V3 actuel sur factual.

Si plus tard on veut un baseline RAG pur strict (single-shot LLM sur top-K chunks sans NLI), il faudrait un endpoint dédié. Pas en S0.

## Distribution gold-set factual (25 questions)

| Stratum | Nombre | Langue |
|---------|-------:|--------|
| Total | 25 | 6 EN / 19 FR |

(distribution détaillée par anchor à compléter post-mesure)

## Référence — baseline V3 historique (V3_S0_GOLD2)

Mesure du 2026-05-05 sur 100 questions originales gold-set (avant ajout des 35 list manuelles) :
- factual_correctness moyen : **0.368** (sur 97 questions reference-equipped, tous types)

## Résultat mesure E (2026-05-06)

Mesure dédiée **factual uniquement** sur les 25 questions factual du gold-set v4 :

| Métrique | Valeur |
|----------|-------:|
| n_total | 25 |
| n_valid | 25 |
| **mean factual_correctness** | **0.361** |
| min | 0.000 |
| max | 1.000 |

Cohérence avec V3_S0_GOLD2 : delta -0.007 (variance LLM-judge ±5-8pp acceptée).

**Distribution per_sample** : voir `data/benchmark/calibration/rag_baseline_factual.json` champ `factual_correctness_baseline.per_sample`.

## Gate D-FF13 (à appliquer en CH-41.5)

| Seuil | Valeur | Justification |
|-------|-------:|---------------|
| **Cible (gate strict)** | ≥ 0.361 | mean baseline V3 sur factual |
| **Variance acceptée** | ±0.050 | variance LLM-judge inter-runs (cf `feedback_judge_variance_5_8pp.md`) |
| **Plancher (gate souple)** | ≥ 0.311 | baseline - variance |
| **Cible idéale** | ≥ 0.500 | progrès net sur factual |

Décision proposée : **gate strict ≥ 0.361** sur ≥ 30 questions factual. Si on reste à n=25, accepter ≥ 0.361 sur les 25 disponibles + ajouter 5 factual lors de la mise en production de D-FF13 (CH-41.5).

## Procédure d'exécution

```powershell
# 1. Collect : appels V3 + persistance
python scripts/measure_rag_baseline_factual.py --collect

# 2. Score : calcul RAGAS factual_correctness
python scripts/measure_rag_baseline_factual.py --score

# 3. Output
data/benchmark/calibration/rag_baseline_factual.json
```

Format `rag_baseline_factual.json` :
```json
{
  "samples": [{"id": "...", "question": "...", "answer": "...", "reference": "...", "contexts": [...]}],
  "factual_correctness_baseline": {
    "n_total": 25,
    "n_valid": N,
    "mean": X.XX,   ← BASELINE (gate D-FF13)
    "min": X.XX,
    "max": X.XX,
    "per_sample": [...]
  },
  "collected_at": "2026-05-06T..."
}
```

## Limitations connues

1. **n=25 < 30 (cible D-FF13)** : le gate D-FF13 demande ≥30 questions. Le gold-set v4 n'a actuellement que 25 factual. Action : ajouter 5 factual via formulation manuelle (idéalement aerospace + dual-use, pour cohérence corpus). Reportable à CH-41.5 (où le D-FF13 sera implémenté).

2. **Variance LLM-judge ±5-8pp** (cf `feedback_judge_variance_5_8pp.md`) : le score baseline est ±0.04-0.08 absolu. Le gate D-FF13 doit donc être pris comme « facts-first ≥ baseline - 0.05 » pour être robuste à la variance.

3. **Lien V3 → facts-first** : le gate compare facts-first (Tranche 5 V4) à V3 (5 stages, dont LLM synthesis). Ce n'est pas une comparaison « RAG vs facts-first pure ». Le D-FF13 est un fallback, pas le mode principal facts-first.

## Action post-mesure

Une fois le score baseline obtenu :
1. Mettre à jour `2026-05-06_CH-41_ADR_FACTS_FIRST.md` D-FF13 avec la valeur baseline mesurée
2. Décider du seuil de tolérance variance (-0.05 vs +0.00)
3. Ajouter 5 questions factual au gold-set si on veut atteindre n=30
