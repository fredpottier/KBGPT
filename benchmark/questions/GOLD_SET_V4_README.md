# Gold-set v4 — OSMOSIS V4 Sprint S0

Construit par `scripts/build_gold_set_v4.py` (CH-40.0).

## Source
Brownfield depuis les 5 fichiers `aero_t1-t7` (290 questions sources).
Bootstrap automatique via DeepInfra `Qwen/Qwen2.5-72B-Instruct`.
Review humaine : Claude (assistant), à compléter dans `annotation_meta.reviewed_at`.

## Stratification
| Stratum | Count |
|---------|-------|
| ambiguous_hypothetical | 3 |
| ambiguous_multi_hop | 5 |
| causal_T6_why | 10 |
| comparison_T2_real_tension | 6 |
| factual_T1_en | 6 |
| factual_T1_fr | 14 |
| false_premise_T6 | 5 |
| kg_over_apparent_tension | 1 |
| kg_over_complementary | 2 |
| kg_over_disjoint | 1 |
| kg_over_lifecycle_not_conflict | 2 |
| kg_over_nuance_not_conflict | 1 |
| list_T6_set_list | 12 |
| list_T6_synthesis_large | 3 |
| temporal_T6_evolution | 5 |
| temporal_T7_evolves_from | 5 |
| temporal_T7_supersedes | 5 |
| trap_classifier_false_positive | 1 |
| trap_conditional | 2 |
| trap_negation | 3 |
| unanswerable_T6 | 5 |

Total : 97 questions
Bootstrap success rate : 100.0%

## Schéma
Chaque item suit le schéma défini dans ADR_OSMOSIS_V4_ARCHITECTURE.md décision D11.
Champs critiques :
- `ground_truth.ground_truth_answer` : référence pour RAGAS FactualCorrectness
- `ground_truth.exact_identifiers` : IDs/dates/valeurs critiques pour exact_match metric
- `ground_truth.supporting_doc_ids` : doc_ids pour citation_presence_rate metric
- `ground_truth.list_items_expected` : items pour item_level_recall metric

## Validation
```bash
python scripts/build_gold_set_v4.py --validate-only
```

## Régénération
Seed fixe (RANDOM_SEED=20260505) — la sélection est reproductible.
