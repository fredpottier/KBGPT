# Audit — Listes de mots hardcodees dans le code OSMOSIS

**Date** : 4 avril 2026
**Statut** : Audit realise, chantier de cleaning a planifier
**Priorite** : MOYENNE — dette technique, pas bloquant mais fragilite croissante

---

## Constat

**55 listes de mots** identifiees dans **20 fichiers Python**, directement dans le code source.
Ces listes servent a la detection de patterns (tension, contradiction, stopwords, types d'entites, etc.)
et sont en francais, anglais, ou les deux.

**Problemes** :
- Non multilingue (ajout d'une langue = modifier le code)
- Non domain-agnostic (ajout d'un domaine = modifier le code)
- Doublons (CANONICAL_PREDICATES defini 3 fois)
- Difficile a maintenir et tester

---

## Classification par priorite

### CRITIQUE — Impact cross-codebase

| # | Fichier | Variable | Items | Langue | Usage |
|---|---------|----------|-------|--------|-------|
| 1 | `claimfirst/models/entity.py:241` | `ENTITY_STOPLIST` | 326 | EN+FR | Filtrage entites generiques |
| 2 | `api/services/kg_signal_detector.py:248` | `_STOPWORDS` | 267 | EN+FR | Tokenisation signal gap |
| 3 | `api/services/retriever.py:161` | `_BM25_STOPWORDS` | 176 | EN+FR | Filtrage BM25 |
| 4 | `api/services/signal_policy.py` | `GENERIC_ENTITIES` | 12 | EN | Filtrage entites generiques (paired evidence) |

### HAUTE — Listes de detection linguistique

| # | Fichier | Variable | Items | Langue | Usage |
|---|---------|----------|-------|--------|-------|
| 5 | `benchmark/evaluators/t2t5_diagnostic.py:219` | `TENSION_KEYWORDS` | 23 | EN+FR | Detection divergences T2 |
| 6 | `benchmark/evaluators/robustness_diagnostic.py:43` | `IGNORANCE_KEYWORDS` | 23 | EN+FR | Detection "je ne sais pas" |
| 7 | `benchmark/evaluators/robustness_diagnostic.py:67` | `CORRECTION_KEYWORDS` | 19 | EN+FR | Detection correction premisse |
| 8 | `benchmark/evaluators/robustness_diagnostic.py:89` | `TEMPORAL_KEYWORDS` | 15 | EN+FR | Detection temporelle |
| 9 | `api/services/synthesis.py:258` | `tension_keywords` | 13 | EN+FR | Validation tension dans reponse |
| 10 | `api/services/assertion_classifier.py:206` | `negation_patterns` | 10 | EN+FR | Detection negation |
| 11 | `api/services/assertion_classifier.py:235` | `contradiction_markers` | 6 | EN+FR | Marqueurs contradiction |
| 12 | `benchmark/evaluators/primary_metrics.py:141` | `contradiction_keywords` | 8 | EN+FR | Detection contradiction |
| 13 | `benchmark/evaluators/primary_metrics.py:281` | `idk_phrases` | 9 | EN+FR | Detection abstention |
| 14 | `benchmark/evaluators/rule_based_judge.py:59` | `idk_patterns` | 6 | EN+FR | Detection abstention |

### MOYENNE — Types et relations KG

| # | Fichier | Variable | Items | Usage |
|---|---------|----------|-------|-------|
| 15 | `api/services/graph_guided_search.py:43` | `EXCLUDED_RELATION_TYPES` | 10 | Filtrage relations pathfinding |
| 16 | `api/services/graph_guided_search.py:59` | `SEMANTIC_RELATION_TYPES` | 24 | Relations semantiques |
| 17 | `api/services/graph_data_transformer.py:49` | `SEMANTIC_RELATION_TYPES` | 19 | Relations pour visualisation |
| 18 | `api/services/proof_subgraph_builder.py:40` | `WEAK_LINK_TYPES` | 7 | Liens faibles exclus |
| 19 | `claimfirst/extractors/claim_extractor.py:47` | `CANONICAL_PREDICATES` | 12 | Predicats autorises |
| 20 | `claimfirst/composition/slot_enricher.py:29` | `_CANONICAL_PREDICATES` | 12 | **DOUBLON** du #19 |
| 21 | `claimfirst/composition/chain_detector.py:41` | `_CANONICAL_PREDICATES` | 12 | **DOUBLON** du #19 |

### BASSE — Patterns specifiques

| # | Fichier | Variable | Items | Usage |
|---|---------|----------|-------|-------|
| 22-26 | `claimfirst/extractors/entity_extractor.py` | Standards/Actor/Service/Feature/Legal keywords | 4-5 chacun | Classification type entite |
| 27-32 | `relations/discursive_pattern_extractor.py` | ALTERNATIVE/DEFAULT/EXCEPTION patterns + markers | 2-20 chacun | Detection patterns discursifs |
| 33 | `claimfirst/applicability/validators.py:259` | `SLA_KEYWORDS` | 9 | Detection metriques SLA |
| 34-37 | `claimfirst/models/question_dimension.py` | VALID_VALUE_TYPES/OPERATORS/COMPARABILITY/STATUSES | 3-8 chacun | Enums pour QD |
| 38 | `claimfirst/models/entity.py:329` | `PHRASE_FRAGMENT_INDICATORS` | 16 | Filtrage noms entites |
| 39 | `claimfirst/models/entity.py:343` | `_FUNCTION_WORDS` | 48 | Mots-outils FR+EN |
| 40 | `claimfirst/models/applicability_axis.py:322` | `NEUTRAL_AXIS_KEYS` | 12 | Axes d'applicabilite |

---

## Doublons identifies

| Variable | Fichier 1 | Fichier 2 | Fichier 3 |
|---|---|---|---|
| `CANONICAL_PREDICATES` | claim_extractor.py:47 | slot_enricher.py:29 | chain_detector.py:41 |
| `SEMANTIC_RELATION_TYPES` | graph_guided_search.py:59 | graph_data_transformer.py:49 | — |

---

## Plan de cleaning propose

### Sprint 1 — Consolidation doublons
- Creer `src/knowbase/claimfirst/constants.py` avec `CANONICAL_PREDICATES`
- Les 3 fichiers importent depuis ce module unique

### Sprint 2 — Externalisation stopwords
- Creer `config/stopwords/` avec `en.txt`, `fr.txt`, `entity_stoplist.txt`
- `_STOPWORDS`, `_BM25_STOPWORDS`, `ENTITY_STOPLIST` chargent depuis ces fichiers
- Ajouter d'autres langues = ajouter un fichier, zero code

### Sprint 3 — Externalisation listes de detection
- Creer `config/detection_keywords.yaml` :
  ```yaml
  tension: [divergen, contradict, however, cependant, ...]
  ignorance: [no information, aucune information, ...]
  temporal: [2021, 2022, 2023, version, release, ...]
  negation: [not, never, ne pas, jamais, ...]
  ```
- Les evaluateurs benchmark + services chargent depuis YAML

### Sprint 4 — Externalisation relations KG
- Creer `config/kg_relations.yaml` avec SEMANTIC/NAVIGATION/EXCLUDED/WEAK
- Les services graph_guided, graph_data, proof_subgraph chargent depuis YAML

---

## Fichiers concernes (20 fichiers, ~55 listes)

```
src/knowbase/api/services/kg_signal_detector.py
src/knowbase/api/services/retriever.py
src/knowbase/api/services/signal_policy.py
src/knowbase/api/services/graph_guided_search.py
src/knowbase/api/services/graph_data_transformer.py
src/knowbase/api/services/proof_subgraph_builder.py
src/knowbase/api/services/assertion_classifier.py
src/knowbase/api/services/assertion_generator.py
src/knowbase/api/services/synthesis.py
src/knowbase/claimfirst/models/entity.py
src/knowbase/claimfirst/models/question_dimension.py
src/knowbase/claimfirst/models/applicability_axis.py
src/knowbase/claimfirst/models/resolved_scope.py
src/knowbase/claimfirst/extractors/entity_extractor.py
src/knowbase/claimfirst/extractors/claim_extractor.py
src/knowbase/claimfirst/composition/slot_enricher.py
src/knowbase/claimfirst/composition/chain_detector.py
src/knowbase/claimfirst/applicability/validators.py
src/knowbase/relations/discursive_pattern_extractor.py
src/knowbase/relations/structure_parser.py
benchmark/evaluators/robustness_diagnostic.py
benchmark/evaluators/rule_based_judge.py
benchmark/evaluators/primary_metrics.py
benchmark/evaluators/t2t5_diagnostic.py
```
