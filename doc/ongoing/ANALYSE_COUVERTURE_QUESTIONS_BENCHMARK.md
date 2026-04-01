# Analyse de couverture des questions benchmark OSMOSIS

**Date** : 1er avril 2026
**Contexte** : Apres Phase 3 complete, les scores sont bons sur les types de questions testes mais la couverture typologique est insuffisante pour garantir la robustesse en production.

---

## 1. Probleme identifie

Les 275+ questions de benchmark couvrent principalement 3 types sur les 12 recommandes par la litterature academique. Le systeme pourrait s'effondrer sur des typologies non testees (false premise, unanswerable, temporal, causale, hypothetique).

**Contrainte critique** : OSMOSIS est domain-agnostic (INV-6). Les questions de test utilisent actuellement du contenu SAP mais la meme taxonomie s'applique a tout corpus (medical, juridique, technique).

---

## 2. Taxonomie de reference (composite CRAG + RAGEval + RGB + MultiHop-RAG)

| # | Type | Description | Teste quoi | Couverture actuelle |
|---|------|------------|-----------|-------------------|
| 1 | Factuel simple | "Quel est X ?" | Extraction directe | ✅ 75% des T1 |
| 2 | Factuel conditionnel | "Quel est X quand Y ?" | Filtrage + extraction | ~10% |
| 3 | Set/liste | "Quels sont les N elements de X ?" | Completude enumeration | ~5% |
| 4 | Comparison | "Comparer X et Y" | Raisonnement inter-entites | ✅ Couvert (T2) |
| 5 | Aggregation numerique | "Combien de X ont Y ?" | Calcul, comptage | 0% |
| 6 | Multi-hop | "X utilise Y, Y necessite Z, quel est Z ?" | Chainage multi-sources | ~5% (T5) |
| 7 | Temporal | "Comment X a evolue entre 2022 et 2023 ?" | Sequencage versions/dates | ~5% |
| 8 | Synthese/resume | "Vue complete de X" | Integration large multi-doc | ~5% (T5) |
| 9 | False premise | "Pourquoi X supporte Z ?" (alors que X ne supporte PAS Z) | Robustesse premisses fausses | **0%** |
| 10 | Unanswerable/null | Question dont la reponse n'est pas dans le corpus | Negative rejection ("je ne sais pas") | **~5%** |
| 11 | Counterfactual/bruit | Question avec contexte trompeur | Robustesse au bruit | **0%** |
| 12 | Cross-document integration | Fusion d'informations de 3+ docs | Synthese multi-source | ~10% (T5) |

---

## 3. Sources academiques

### Benchmarks de reference

- **CRAG** (Meta, KDD Cup 2024) — 8 types de questions × 3 axes de difficulte (dynamisme, popularite, domaine). Le plus complet. [arxiv.org/pdf/2406.04744](https://arxiv.org/pdf/2406.04744)

- **RAGEval** (ACL 2025) — 7 types dont Information Integration (22%), Unanswerable (7.5%), Temporal Sequence (7.2%). [aclanthology.org/2025.acl-long.418.pdf](https://aclanthology.org/2025.acl-long.418.pdf)

- **RGB** (AAAI 2024) — Teste 4 capacites fondamentales. Constat : les LLM echouent massivement sur Negative Rejection et Counterfactual Robustness. [arxiv.org/abs/2309.01431](https://arxiv.org/abs/2309.01431)

- **MultiHop-RAG** — 4 types multi-hop : inference, comparison, temporal, null. [arxiv.org/pdf/2401.15391](https://arxiv.org/pdf/2401.15391)

### Mesure de complexite

- **Retrieval Complexity** (2024) — Metrique continue de difficulte. Multi-hop, compositional, temporal. [arxiv.org/html/2406.03592v1](https://arxiv.org/html/2406.03592v1)

- **GRADE** (EMNLP 2025) — 2 dimensions : profondeur de raisonnement × distance semantique. [arxiv.org/abs/2508.16994](https://arxiv.org/abs/2508.16994)

### Evaluation fine

- **RAGChecker** (Amazon, NeurIPS 2024) — Evaluation au niveau des claims (pas reponse globale). Meilleure correlation humaine que RAGAS. [arxiv.org/abs/2408.08067](https://arxiv.org/abs/2408.08067)

### Modes de defaillance RAG

- **Mindful-RAG** (2024) — 8 points de defaillance dans les RAG+KG. [arxiv.org/pdf/2407.12216](https://arxiv.org/pdf/2407.12216)

- **PromptQL** — 4 modes fondamentaux : extraction errors, context size, inexhaustive computation, reasoning failures. [promptql.io/blog/fundamental-failure-modes-in-rag-systems](https://promptql.io/blog/fundamental-failure-modes-in-rag-systems)

### Limites de RAGAS

- Pas de taxonomie de questions (mesure globale, pas par type)
- Focus reponses factuelles courtes (mal adapte aux syntheses longues)
- Pas d'adversarial testing (false premises, negations)
- Meta AI rapporte 25-30% de surestimation quand on utilise uniquement des questions simples
- [RAGAS paper](https://arxiv.org/abs/2309.15217), [Evidently AI guide](https://www.evidentlyai.com/llm-guide/rag-evaluation)

---

## 4. Plan d'action : elargir la couverture

Ajouter 50-100 questions couvrant les types manquants, reparties en :

### Priorite 1 — Risque eleve (types 9, 10, 11)
- **10 questions False Premise** : questions basees sur des affirmations fausses
- **10 questions Unanswerable** : reponse absente du corpus
- **5 questions Counterfactual** : informations contradictoires dans la question

### Priorite 2 — Risque moyen (types 5, 6, 7, 8)
- **10 questions Temporales** : evolution entre versions de documents
- **10 questions Synthese large** : vue complete d'un sujet cross-doc
- **5 questions Multi-hop** : chainage 3+ sources
- **5 questions Causales** : "Pourquoi faut-il X ?"

### Priorite 3 — Completude (types 2, 3)
- **5 questions Conditionnelles** : "Quel X quand Y ?"
- **5 questions Set/liste** : "Quels sont les N elements de X ?"
- **5 questions Hypothetiques** : "Si X alors ?"
- **5 questions Negation** : "Qu'est-ce qui n'est PAS X ?"

**Total** : 75 questions supplementaires

### Criteres de qualite
- Chaque question doit etre domain-agnostic dans sa structure (meme si le contenu est SAP)
- Chaque question doit avoir un ground_truth verifiable
- Les questions false_premise et unanswerable doivent avoir une reponse attendue explicite ("le systeme devrait dire qu'il ne sait pas" ou "le systeme devrait corriger la premisse")

---

*Document genere pour analyse complementaire par d'autres IA et pour guider la generation des nouvelles questions.*
