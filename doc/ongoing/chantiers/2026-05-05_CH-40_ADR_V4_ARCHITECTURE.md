# ADR — OSMOSIS V4 Pipeline Architecture

**Status** : Proposed (2026-05-05)
**Decision owner** : Fred
**Predecessors** : runtime_v3 (CH-39), refonte minimaliste 5 stages

---

## 1. Contexte

### 1.1 État actuel V3 (run V3_FINAL3, 2026-05-05)

Pipeline V3 = refonte minimaliste, 5 stages, 250 lignes (vs 951 V2), 1 LLM call agentic + NLI judge mDeBERTa multilingue. Suppression des 70+ entrées hardcoded (keywords lifecycle, regex hallucination_guard, factual_shapes).

**Scores benchmarks** :

| Bench | V2 ABC1 | V3 FINAL3 | Cible | Δ |
|-------|---------|-----------|-------|---|
| Robustness global (170q) | 0.495 | 0.545 | 0.75 | -21pp |
| RAGAS faithfulness (80q) | 0.677 | 0.631 | 0.80 | -17pp |
| RAGAS context_relevance | 0.788 | 0.822 | — | +3pp |

**Diagnostic** : pattern « retrieved right, answered wrong ». Le retrieval livre les chunks pertinents (context_relevance 0.822) mais la synthèse perd ~17pp en faithfulness.

**Régressions par catégorie Robustness** : `set_list` 0.243, `lifecycle_vs_conflict` 0.431, `false_premise` 0.450, `causal_why` 0.588 (régression -15pp vs V2 ABC1).

### 1.2 Audit externe (3 retours experts indépendants)

3 analyses externes (Claude web, ChatGPT, modèle d'analyse spécialisé) ont été sollicitées sur l'état des lieux V3. Convergences fortes (3/3) :

1. Le problème n'est pas dans le retrieval mais dans la **synthèse + vérification**
2. Le prompt 140 lignes / 11 règles est en surcharge cognitive (instruction-following collapse)
3. mDeBERTa-xnli (278M) est obsolète comme verifier de production
4. Le scoring keyword fallback fausse les benchs et doit disparaître
5. Question routing par type est essentiel (factual/list/causal/temporal/comparison)
6. Retrieval adaptatif requis (top-K vs exhaustif vs multi-version)
7. Verifier spécialisé grounding requis
8. Régénération ciblée phrase-level
9. Gold-set humain 100-250 questions stratifié obligatoire
10. Stack d'évaluation hybride (RAGAS FactualCorrectness + métriques structurées)

Critiques convergentes contre la première synthèse V4 :

- Le **gap multilingue** des verifiers candidats (MiniCheck/Lynx/HHEM tous English-trained) n'avait pas été pris en compte
- L'**Evidence Structurer** était sur-vendu en chemin critique (latence 5-8s réelle, F1 60-75% projeté sur Qwen-14B AWQ vLLM ; en pratique tournera sur Qwen-72B DeepInfra tant que vLLM EC2 inactif → F1 attendu plus haut, mais à mesurer)
- Les **chiffres projetés** (-40% coût, p50 19s, faithfulness 0.78) étaient aspirationnels, non mesurés
- Le **citation grounding déterministe** ne prouve pas le support sémantique
- Le **sparse retrieval natif** Qdrant/BGE-M3 était une amélioration manquée
- Les **threshold de routing** doivent être appris depuis le gold-set, pas assumés
- Le **Decision Gate rule-based** risque de devenir une nouvelle dette V2-style

### 1.3 Contrainte produit non négociable

OSMOSIS doit rester **domain-agnostic**. Le corpus aerospace régulatoire (CS-25 + EU 2021/821) est le 1er domaine cible (test client Armand) mais l'architecture doit s'appliquer également à : software docs, médical, juridique, produit, RH. Les patterns régulatoire-spécifiques (lifecycle, supersession, scope hierarchy) sont reformulés en patterns universels (versioning, semantic relations, scope graph).

Toute pattern domain-spécifique passe par les **Domain Packs** (architecture V3.3 §3.G.4) sous forme de hints sémantiques prose, jamais via regex/keywords hardcodés dans le pipeline.

---

## 2. Décisions (1 à N)

### Décision D1 — Architecture cible V4 = pipeline modulaire 6 stages

V3 reste ; V4 est une évolution incrémentale avec feature flags. Pipeline cible :

```
[A] Question Analyzer (multi-label top-2)
[B] Adaptive Retrieval (default | list | versioning | comparison)
[C] Evidence Structurer (CONDITIONNEL hard routes uniquement)
[D] Routed Synthesis (14B vLLM ou 72B DeepInfra selon type)
[E] Cascaded Multilingual Verifier (3 channels)
[F] Decision Gate (rule-based, charte limitative)
```

Justifications :
- Modularité = chaque stage upgradable indépendamment (retour modular RAG / ComposeRAG)
- Chemin court préservé pour 70% du trafic (factual simples)
- Structure intermédiaire (Evidence Structurer) réservée aux hard routes pour limiter latence + SPOF

### Décision D2 — Verifier multilingue cascadé, pas swap dogmatique

Rejet du swap mDeBERTa → MiniCheck/Lynx/HHEM en bloc. Adoption d'une cascade :

- **Channel 1** : citation presence (déterministe, 0ms) — filtre minimal
- **Channel 2** : mDeBERTa multilingue (cheap pre-screen, ~1s)
- **Channel 3** : verifier specialist sentence-level (~2-3s) — choix tranché par bake-off A/B/C

Bake-off A/B/C en début S1 sur 200 questions FR/EN du gold-set, critères :
- F1 par langue (FR / EN séparément)
- Latence GPU L4
- Coût (local vs DeepInfra)

Candidats C3 :
- MiniCheck-7B (Bespoke) — sur branche EN-normalisée seulement
- HHEM-2.1-Open — sur branche EN-normalisée seulement
- Lynx-8B (Patronus) — secondaire/offline judge
- Évaluateur multilingue fine-tuné maison (moyen terme, sur corruption synthétique + gold-set)

C3 est activé uniquement sur les phrases que C2 marque PARTIAL/UNFAITHFUL.

### Décision D3 — Evidence Structurer conditionnel, schéma minimal

Pas d'Evidence Structurer sur le chemin critique de tous les requests. Activé seulement quand :

- `type ∈ {temporal, contradiction, comparison, causal}`
- `confidence_router > seuil` (à mesurer en S0)

Schéma minimal de démarrage :
```json
{
  "atom_id": "...",
  "subject": "<entité>",
  "predicate": "<action ou relation>",
  "object": "<valeur>",
  "source_chunk_id": "..."
}
```

Enrichissement progressif des qualifiers (`unit`, `condition`, `time_anchor`, `lifecycle_status`, `publication_date`) APRÈS validation F1 ≥ 0.75 sur gold-set d'atomes humainement annoté.

Activation derrière feature flag `EVIDENCE_STRUCTURER_ENABLED`. Si A/B montre delta ≥ +5pp sur hard routes, on déploie ; sinon on reste V4 sans Structurer.

### Décision D4 — Sparse retrieval = Qdrant native, pas heuristique fait-main

Le `_extract_keywords_for_bm25()` actuel est un préprocesseur lossy fait-main, brittle multilingue. Remplacement par :

- Qdrant native sparse vectors (server-side IDF) ou
- BGE-M3 unified (dense + sparse + multi-vector dans 1 modèle multilingue)

Tranchage en S0.5 par bake-off rapide. Ajout de payload indexes Qdrant sur :
- `doc_id`
- `lifecycle_status`
- `publication_date`
- `tenant_id`
- `applicability_axis_*` (clés v3.3)

### Décision D5 — Question Router multi-label top-2, types restreints

Démarrage avec **4 types disjoints** (pas 6-8) :
- `factual` (lookup unique)
- `list` (énumération exhaustive)
- `temporal` (versioning, cross-version)
- `causal_why` (explication, conditional)

Multi-label top-2 dès le départ pour gérer les non-disjoints (ex « quels articles ont changé entre EU 428 et 2021/821 » = list + temporal).

Bench accuracy router obligatoire avant déploiement S2 :
- Top-1 ≥ 90%
- Top-2 ≥ 95%
- Sur 100 questions humainement annotées par type, FR + EN

### Décision D6 — Routing modèle (14B vLLM vs 72B DeepInfra) appris, pas assumé

> ⚠️ Note Sprint S0 (06/05/2026) : la politique RuntimeLLMClient `vLLM-first / DeepInfra-fallback` est en place dans le code mais vLLM EC2 est inactif par défaut. État effectif du pipeline V3 = Qwen2.5-72B systématique. La distinction « 14B simple / 72B complexe » est une cible architecturale, pas un état actuel.

Pas de split 70/30 hardcodé. Politique conservative au démarrage :
- 14B vLLM par défaut (factual, list simples)
- 72B DeepInfra escalade sur `temporal | comparison | causal | high_uncertainty`

Distribution réelle mesurée sur gold-set après S0. Seuil optimisé après mesure latence + coût + qualité par catégorie.

### Décision D7 — Régénération phrase-level, pas réponse entière

Le regen V3 actuel régénère la réponse complète. V4 :
- C3 marque les phrases UNSUPPORTED individuellement
- Régen ciblée sur ces phrases uniquement (1× max)
- Si après régen toujours UNSUPPORTED → marque la phrase `confidence_warning`
- Si > 50% de la réponse est UNSUPPORTED → ABSTAIN total

### Décision D8 — Decision Gate rule-based avec charte limitative

Le Decision Gate est **rule-based**, pas LLM. Charte invariante :
- Max 5 règles totales dans le gate
- Toute nouvelle règle = ablation +Xpp prouvée sur sous-bench
- Sinon refusée par le code review / linter

Règles de démarrage :
1. Si aucun atom/chunk supporte → ABSTAIN
2. Si presupposition contredite par evidence → REJECT_FALSE_PREMISE
3. Si grounding score (C2 ou C3) ≥ 0.75 → ANSWER
4. Si grounding score 0.5-0.75 → ANSWER + `confidence_warning`
5. Sinon → ABSTAIN

### Décision D9 — Schéma de sortie enrichi avec coverage_state

Le JSON output du synthesizer ajoute des champs first-class :
```json
{
  "decision": "ANSWER | REJECT_FALSE_PREMISE | ABSTAIN",
  "answer": "<prose avec citations chunk_id par phrase>",
  "coverage_state": "complete | partial | unknown",
  "exact_match_validation": true,
  "atoms_used": ["chunk_id_1", "chunk_id_2", ...],
  "temporal_basis": {"doc_id": "...", "publication_date": "..."},
  "confidence": 0.0..1.0,
  "subject": "...",
  "presupposition_check": "..."
}
```

`coverage_state` est essentiel pour les list routes (le système doit savoir s'il a énuméré tout ou seulement une partie). `exact_match_validation` est un check déterministe sur les identifiants critiques (numéros de règlement, dates, codes) du synthesizer.

### Décision D10 — Suppression complète du keyword scorer fallback

Le `KEYWORD_EVALUATORS` du `robustness_diagnostic.py` est supprimé. Si LLM-judge échoue : retry, jamais fallback sur token-matching. Toutes les catégories en `LLM_JUDGE_CATEGORIES` (déjà 16/16). Métriques structurées par type ajoutées :
- `item_level_recall` pour list
- `exact_match_identifiers` pour T1 / T2 (numéros de règlement, valeurs numériques)
- `citation_presence_rate` pour provenance
- `coverage_state_accuracy` (le système prédit-il correctement complete/partial ?)

### Décision D11 — Gold-set humain 150-200 questions multilingues

Construction obligatoire en S0. Critères :
- Stratifié par catégorie (10 par sous-type minimum)
- Multilingue natif (FR + EN minimum, DE/ES/IT optionnel)
- Annotation criterion-level (pas juste un score global) :
  - `answerability` (true/false/partial)
  - `false_premise` (présent/absent + correction attendue)
  - `active_version_required` (oui/non + version attendue)
  - `exact_identifier_preservation` (oui/non + identifiants attendus)
  - `supporting_doc_ids` (liste)
  - `contradiction_vs_supersession` (label)
  - `list_completeness` (items attendus)
  - `causal_explanation_support` (oui/non + chunks attendus)

Calibration Llama-3.3-70B juge contre gold-set : Pearson ≥ 0.7 obligatoire avant utilisation pour bench production. Référence : MEMERAG (multilingual native annotation).

### Décision D12 — Charte anti-V2 explicite (linter d'architecture)

Invariants formalisés et vérifiés en CI :

| Invariant | Vérification | Justification |
|-----------|--------------|---------------|
| Aucun listing métier hardcodé dans le pipeline | grep CI sur `runtime_v4/**` | Anti-V2 |
| Décompositions sémantiques par Domain Pack uniquement | Pattern review | V3.3 §3.G.4 |
| Max 5 règles dans Decision Gate | Test unitaire counter | Anti-dérive V2 |
| Max 50 lignes par prompt synthesis | Linter wc | Mesurable |
| Toute nouvelle métrique de bench justifiée par failure mode observé | ADR par métrique | Anti-sur-mesurage |
| Toute claim de gain mesurée AVANT annonce | PR description requirement | Anti-aspirational |
| Tout swap de modèle = bake-off A/B/C sur gold-set | ADR par swap | Anti-dogmatique |
| Pipeline shippable à tout moment | Feature flags par stage | Continuité |

### Décision D13 — Sprints à gates quantifiés go/no-go

Chaque sprint a un critère mesurable. Si non atteint → no-merge, diagnostic obligatoire avant poursuite.

---

## 3. Plan d'exécution V4

### Sprint S0 — Calibration & gold-set (1 semaine)

**Livrables** :
- Gold-set 150-200 questions stratifié multilingue, annotation criterion-level
- RAGAS FactualCorrectness ajouté au bench
- Métriques structurées par type (item_level_recall, exact_match, citation_presence, coverage_state)
- Suppression complète keyword scorer fallback
- Calibration juge Llama-3.3-70B vs gold-set (Pearson ≥ 0.7)

**Gate S0 (infra-only)** :
- Gold-set construit et committed
- Pearson juge ≥ 0.7 sur gold-set
- Métriques structurées en place

### Sprint S0.5 — Retrieval cleanup (1 semaine)

**Livrables** :
- Remplacement `_extract_keywords_for_bm25()` par Qdrant native sparse OU BGE-M3
- Création payload indexes Qdrant (doc_id, lifecycle_status, publication_date, tenant_id, applicability_axis_*)
- Bake-off rapide native sparse vs BGE-M3 sur 100 questions

**Gate S0.5** :
- context_relevance ≥ niveau actuel V3 (0.822)
- Recall sur sous-bench multilingue ≥ +5pp vs heuristique actuelle
- Latence retrieval ≤ niveau actuel

### Sprint S1 — Verifier upgrade + bi-channel (2 semaines)

**Livrables** :
- Bake-off A/B/C verifier (3 jours) : mDeBERTa vs MiniCheck-7B vs HHEM-2.1 vs Lynx-8B
  - 200 questions FR/EN du gold-set
  - F1 par langue, latence GPU L4, coût
- Cascade multilingue implémentée : C1 déterministe + C2 mDeBERTa + C3 specialist
- Régen ciblée phrase-level (pas réponse entière)

**Gate S1** :
- Faithfulness gold-set ≥ +5pp vs V3
- Regen rate -30%
- p95 latence ≤ niveau actuel V3
- Pas de régression multilingue (delta FR-EN ≤ 5pp)

### Sprint S2 — Question Router + Adaptive Retrieval (1.5 semaines)

**Livrables** :
- Router multi-label top-2 sur 4 types (factual / list / temporal / causal_why)
- Bench router accuracy (100 questions humainement annotées)
- Retrieval mode `list` (doc-scoped scroll Qdrant K=30-50)
- Retrieval mode `versioning` (Neo4j 2-hop sur LOGICAL_RELATION, conditionnel)

**Gate S2** :
- Router accuracy ≥ 90% top-1 ET ≥ 95% top-2
- Set_list ≥ 0.50 (vs 0.243 actuel)
- T7 lifecycle global ≥ +8pp
- Pas de régression sur factual

### Sprint S3 — Evidence Structurer EN A/B (2-3 semaines, hors critical path)

**Livrables** :
- Schéma minimal (subject, predicate, object, source_chunk_id)
- Activé conditionnellement sur hard routes uniquement
- Gold-set d'atomes humainement annoté (50 questions × ~5 atomes)
- A/B sur 200 questions : structurer ON vs OFF

**Gate S3** :
- F1 extraction atomes ≥ 0.75
- Delta hard routes (temporal / contradiction / comparison / causal) ≥ +5pp
- Latence p95 hard routes ≤ 35s

**Si gate non atteint → V4 reste sans Structurer**, on shippe la V4 light.

### Sprint S4 — Bench complet + ablation

**Livrables** :
- Bench complet V4 vs V3 sur tous les onglets (RAGAS / Robustness / T1 / T2T5 / T7)
- Ablation par stage : désactiver Router / Structurer / Verifier C3 indépendamment
- Documentation des contributions par stage

**Gate S4** :
- Robustness global ≥ 0.65 (vs 0.545 V3)
- RAGAS FactualCorrectness ≥ 0.75
- p50 latence ≤ 25s, p95 ≤ 40s
- Coût LLM/question mesuré et documenté

---

## 4. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|-----------|
| Verifier multilingue specialist (C3) inexistant en open-weights satisfaisant | Élevée | Élevé | Cascade C2 mDeBERTa + C3 EN-only sur branche normalisée. Long terme : fine-tune custom. |
| Evidence Structurer F1 < 0.75 sur Qwen-14B | Moyenne | Moyen | A/B parallèle, gate quantifié, pipeline shippable sans Structurer |
| Router multi-label précision < 90% | Moyenne | Élevé | Démarrage 4 types (pas 6-8), bench obligatoire, escalade humain sur ambiguïtés |
| Régression multilingue sur swap retrieval natif | Faible | Élevé | Bake-off rapide S0.5, gate sur recall multilingue |
| Decision Gate dérive vers V2 (15+ règles) | Élevée à terme | Élevé | Charte limitative max 5 règles, ablation obligatoire |
| Gold-set humain coût/temps sous-estimé | Moyenne | Moyen | Démarrage 100 questions FR + 50 EN, extension progressive |
| Latence p95 dépasse 40s | Moyenne | Moyen | Régen phrase-level (pas globale), Structurer conditionnel, monitoring p95 par stage |

---

## 5. Hypothèses à valider (pas des décisions)

Ces points sont marqués comme **hypothèses** et non comme acquis :

- H1 — Le faithfulness « vrai » sur RAGAS FactualCorrectness sera ≥ 0.75 (vs 0.631 NLI-based actuel). À mesurer en S0.
- H2 — La distribution de trafic factual / hard routes sera ~70/30. À mesurer sur le gold-set après labeling.
- H3 — MiniCheck-7B ou HHEM-2.1 sur branche EN-normalisée sera meilleur que mDeBERTa sur sous-set EN. À valider par bake-off S1.
- H4 — Le prompt scindé (40 lignes max par route) suivra mieux les instructions que le prompt 140 lignes monolithique. À valider par A/B en S2.
- H5 — L'Evidence Structurer apportera ≥ +5pp sur hard routes. À valider par A/B S3.

Aucune de ces hypothèses n'est annoncée comme gain garanti dans la communication produit.

---

## 6. Alternatives rejetées

- **Retour à V2 multi-stage avec regex/keywords** : rejeté, anti-pattern documenté, multilingue cassé
- **Swap dogmatique mDeBERTa → MiniCheck/Lynx/HHEM** : rejeté, gap multilingue
- **Evidence Structurer always-on** : rejeté, latence + SPOF + F1 incertain sur 14B
- **Decision Gate LLM** : rejeté, anti-pattern (le V2 le faisait), variance + coût
- **Single number scoring (RAGAS FactualCorrectness uniquement)** : rejeté, list / temporal / contradiction nécessitent métriques structurées dédiées
- **Always-on question decomposition (CRAG / Self-RAG style)** : rejeté, latence prohibitive sur 100% du trafic ; selective decomposition via router est préféré

---

## 7. Glossaire

- **Hard route** : type de question parmi `temporal | contradiction | comparison | causal_why`. Active Evidence Structurer + escalade Qwen-72B.
- **Soft route** : type de question parmi `factual | list`. Reste sur Qwen-14B vLLM, pas de Structurer.
- **Cascade verifier** : 3 channels successifs (citation déterministe → mDeBERTa multilingue cheap → specialist sentence-level), C3 activé seulement si C2 marque PARTIAL/UNFAITHFUL.
- **Coverage state** : champ first-class du JSON output, valeurs `complete | partial | unknown`. Essentiel pour list routes.
- **Bake-off A/B/C** : comparaison empirique de 2-3 modèles candidats sur gold-set avec critères mesurés (qualité, latence, coût). Pas de swap dogmatique.
- **Charte anti-V2** : ensemble d'invariants vérifiés en CI pour empêcher la dérive vers les anti-patterns documentés (regex métier, listings hardcodés, prompts monolithiques, règles non-justifiées).

---

## 8. Statut et next steps

**Status** : Proposed — à valider par Fred avant implémentation.

**Si validé** :
1. Passage en mode plan pour le Sprint S0 (calibration + gold-set)
2. Création des tâches CH-40 / CH-40.0 / CH-40.0.5 / CH-40.1 ... CH-40.4
3. Implémentation incrémentale avec gates quantifiés
4. ADRs spécifiques par décision majeure (verifier choice, retrieval choice, Structurer go/no-go)

**Modifications à cet ADR** : par addendum daté en bas, pas par réécriture. L'historique des décisions doit rester traçable.

---

## 9. Addendum 2026-05-07 — Pivot routing distribué (gate S2 amendé)

**Trigger** : audit empirique Phase 0 (54 fails router classifiés sur gold_set_v4) + triangulation
externe convergente (ChatGPT + Claude Web + Phase 0 quantifié).

### 9.1 Constat empirique

Sprint S2 a tenté un fine-tune classifier 7-classes sur 14767q multi-source (Mintaka + SQuAD2 +
HotpotQA + FalseQA + 490q humaines + 3900 traductions FR Qwen-72B). Résultats sur hold-outs :

| Hold-out | DeBERTa run 1 (490q) | DeBERTa run 2 (14767q) | LLM zero-shot Qwen-72B |
|----------|:---:|:---:|:---:|
| gold_set_v4 | 43% | 59% | **82%** (baseline pré-existante) |
| panel_stress_test | 42% | 55% | n/a |

Le LLM zero-shot **bat le fine-tune** malgré 30× plus de données.

### 9.2 Cause racine identifiée (Phase 0 audit)

Classification manuelle des 54 fails du DeBERTa run 2 sur gold_set_v4 :

| Catégorie | n | % |
|-----------|--:|--:|
| `linguistic_pattern` (formulation suffit) | 18 | 33% |
| `intrinsically_ambiguous` (multi-label légitime) | 19 | 35% |
| **`corpus_dependent` (label nécessite KG)** | **17** | **31%** |

Sous-types `corpus_dependent` :
- C.1 `comparison émergent du KG` (4 cas) — ex T2_AERO_0001 « énergie d'impact CS-25 » est tagué
  comparison à cause d'une SUPERSESSION 21J vs 3.5J dans le KG. Question seule = factual évident.
- C.2 `unanswerable hors corpus` (4 cas) — ex « commissaire signataire 2024/2547 » : factual en forme,
  unanswerable parce que info pas dans corpus tenant.
- C.3 `false_premise corpus-validé` (3 cas) — ex « Pourquoi 2021/821 requiert l'unanimité… » : causal
  en forme, false_premise parce que « unanimité » contredit corpus.
- C.4 `meta-KG questions` (6 cas) — ex « Combien de SUPERSEDES dans le KG aerospace ? ».

**Plafond mécanique** : 17/122 = 86% max théorique pré-retrieval. Le gate D5 original (90% top-1)
est **mathématiquement non atteignable** par un classifier pur sur cette taxonomie.

### 9.3 Décision amendée

**Décision D5 amendée** — Le routing devient une **décision distribuée** sur le pipeline, pas
une décision unique pré-retrieval. La taxonomie est splittée en 2 axes :

**Axe A — `answer_shape`** (5 classes, **décidable depuis la question seule**) :
- `scalar_factual` (ex-`factual`)
- `list`
- `temporal`
- `comparison_explicit` (formulation explicitement comparative : « X vs Y », « différence entre… »)
- `causal_explicit` (formulation explicitement causale : « pourquoi… », « pour quelle raison… »)

**Axe B — `epistemic_status`** (3 classes, **partiellement post-retrieval**) :
- `answerable`
- `unanswerable`
- `false_premise`

**Promotions corpus-aware** gérées par `EvidenceRerouter` (CH-42.3 livré) :
- `scalar_factual → comparison` quand `LOGICAL_RELATION:CONTRADICTS` détecté ≥ 2 fois
- `* → temporal` quand chaîne `LIFECYCLE_RELATION:SUPERSEDES` ≥ 2 hops détectée
- `* → unanswerable` quand `evidence.answerability_hint == "unanswerable"`
- `* → false_premise` quand `premise_validator` détecte présupposition contredisant le corpus

### 9.4 Gate S2 révisé

| Métrique | Cible | Mesure sur |
|----------|:---:|------------|
| `answer_shape` top-1 | **≥ 90%** | gold_set_v4 + panel_stress |
| `answer_shape` top-2 | ≥ 95% | idem |
| `epistemic_status` (post-retrieval inclus) | ≥ 90% | idem |
| **Routing final effective** (après EvidenceRerouter) | **≥ 90%** | idem |

L'ancien gate « 90% top-1 sur 7 classes pré-retrieval » est **abandonné** comme structurellement
non atteignable.

### 9.5 Garde-fous (validation ChatGPT)

**Garde-fou #1 — Rerouter explicable, pas opaque**

Toutes les promotions du `EvidenceRerouter` doivent être **déclaratives, evidence-based,
benchmarkables séparément**. Risque interdit : recréer un IntentResolver V2 caché derrière
un score sémantique magique.

```python
# OK : règle déterministe explicable
if contradiction_count >= 2 and distinct_values >= 2:
    promote("scalar_factual", "comparison_emergent")

# INTERDIT : magic threshold
if semantic_conflict_score > 0.73:
    promote(...)
```

Bench du rerouter doit être **séparé** du bench du classifier `answer_shape`.

**Garde-fou #2 — Re-tag gold_set_v4 avec nouvelle taxonomie**

Avant Phase 1 (SetFit baseline), ajouter au gold_set_v4 :
- `gold_answer_shape` ∈ {scalar_factual, list, temporal, comparison_explicit, causal_explicit}
- `gold_epistemic_status` ∈ {answerable, unanswerable, false_premise}
- `gold_corpus_signal_required` ∈ {none, contradiction, supersession, missing_info, premise_check, kg_meta}
- `primary_type` conservé pour rétro-compatibilité benchs antérieurs

Sans ce re-tag, les métriques continuent à mesurer la mauvaise chose.

### 9.6 Plan d'exécution révisé Sprint S2

| Phase | Livrable | Gate |
|-------|----------|------|
| Phase 0 ✅ | Audit taxonomique 54 fails | 31% corpus_dependent confirmé |
| Phase 1 | Re-tag gold_set_v4 (3 nouveaux champs) | manuel + spot-check |
| Phase 2 | SetFit baseline sur `answer_shape` (5 classes) | top-1 ≥ 80% sur hold-out → poursuivre |
| Phase 3 | Active learning ciblé + génération régulatoire 500-800q | fail patterns réduits |
| Phase 4 | Cascade calibrée (Platt scaling) + fallback LLM | seuil calibré sur hold-out dédié |
| Phase 5 | EvidenceRerouter étendu (4 promotions) + bench séparé | promotion accuracy ≥ 80% sur cas C.1-C.4 |
| Phase 6 | Bench global S2 final | gate révisé §9.4 atteint |

### 9.7 Justification finale

Le pivot conceptuel « routing distribué pré + post retrieval » est :
1. **Empiriquement nécessaire** : 31% des fails sont prouvés non-décidables pré-retrieval.
2. **Architecturalement aligné** : la brique post-retrieval (`EvidenceRerouter` CH-42.3) est
   déjà livrée et fonctionne sur les signaux KG.
3. **Conforme à l'état de l'art RAG 2025-2026** : adaptive routing, evidence-conditioned
   reasoning, modular RAG.
4. **Plus honnête** : le gate révisé est mesurable et atteignable sans triche, l'ancien gate
   strict aurait nécessité de masquer le plafond mécanique.

**Validation triangulée** : ChatGPT + Claude Web + audit Phase 0 + analyse interne convergent.

---

## 10. Addendum 2026-05-08 — Evidence-Grounded Reasoning (CH-47)

**Trigger** : régression qualité massive observée sur le bench Robust V4_CH46_POSTOPT (170q, mêmes
questions que V3_S0). 16 catégories sur 17 régressent vs V3_S0, dont 9 perdent ≥ 20pp. La cible
produit Robust ≥ 0.55 est plus loin qu'avec V3.

### 10.1 Constat empirique

Comparaison directe V3_S0_BASELINE vs V4_CH46_POSTOPT (170q identiques, mêmes outils d'évaluation) :

| Catégorie | V3_S0 | V4_CH46 | Δ |
|---|---:|---:|---:|
| **global** | **0.531** | **0.351** | **-18pp** |
| hypothetical | 0.63 | 0.27 | **-36pp** |
| lifecycle_supersedes | 0.58 | 0.28 | -30pp |
| causal_why | 0.66 | 0.37 | -30pp |
| lifecycle_evolves_from | 0.69 | 0.40 | -29pp |
| multi_hop | 0.62 | 0.34 | -28pp |
| synthesis_large | 0.58 | 0.32 | -26pp |
| anchor_scope_hierarchy | 0.54 | 0.30 | -24pp |
| conditional | 0.60 | 0.38 | -23pp |
| lifecycle_filtering_active | 0.47 | 0.26 | -20pp |
| (… 6 autres entre -18pp et -3pp) | | | |
| negation | 0.50 | **0.56** | +6pp |

**1 seule catégorie améliorée**, 16 régressées. CH-46 (optims latence) n'explique qu'une partie
mineure ; le pivot V3 → V4 lui-même est la cause principale.

### 10.2 Diagnostic Phase 0 (audit ciblé)

**Phase 0.A** — sur les 23 questions à régression ≥ 0.20 (catégories cibles) :
- 48% `b_composer_short` — V4 répond ABSTAIN ou réponse très courte alors que V3 répondait
- 39% `unknown` (autres patterns)
- 13% `a_structurer_extraction`

**Phase 0.B** — capture `facts_first` complet sur 5 top-deltas via API V4 :

| Question | answerability V4 | items extraits | decision V4 | Hypothèse |
|---|---|---:|---|---|
| q_37 (causal_why) "Pourquoi Annex I mise à jour ?" | unanswerable | 0 | ABSTAIN | (1) Structurer abdique |
| q_52 (hypothetical) "Si État membre... quel mécanisme ?" | unanswerable | 0 | ABSTAIN | (1) Structurer abdique |
| q_88 (multi_hop) "Valeur énergie + pourquoi écart ?" | answerable | 2 | ANSWER court | (2b) Composer short |
| q_117 (conditional) "Si info... délai prolongeable ?" | unanswerable | 0 | ABSTAIN | (1) Structurer abdique |
| q_36 (causal_why) "Pourquoi 2021/821 a abrogé 428/2009 ?" | answerable | 2 | ANSWER court | (2b) Composer short |

**Ratio confirmé** : 60% Structurer abdique / 40% Composer short.

**Découverte additionnelle** : 4/5 questions sont **mal classifiées par l'Analyzer**
(q_52 hypothetical → factual ; q_88 multi_hop → factual ; q_117 conditional → factual ;
q_36 causal_why → temporal). 3 niveaux de problème simultanés.

### 10.3 Cause racine

V4 Facts-First a, sans le formaliser, identifié `fact = assertion explicite littérale` extractive.
Or les questions de raisonnement (causal, hypothetical, conditional, multi_hop) requièrent :

| Type | Exemple |
|---|---|
| explicit fact | « Regulation 2021/821 repeals 428/2009 » |
| **inferred relation** | « done to harmonize export controls » |
| **causal synthesis** | « therefore, modernization + harmonization » |

V4 capture **bien** le 1er niveau, **rate** les niveaux 2 et 3. Sur les chunks retrieved par V4
(12 chunks, identiques à V3), les marqueurs causaux explicites (`therefore`, `in order to ensure`,
`because`) sont **présents** mais le Mistral-Small Structurer ne les extrait pas comme **facts
relationnels** ; le Composer Gemma-12B « presentation-only » ne sait pas synthétiser au-delà des
facts atomiques.

V3 Qwen-72B agentic réussissait précisément parce qu'il pouvait raisonner librement à partir
des chunks bruts — au prix de la faithfulness mesurable.

### 10.4 Décision amendée

**Décision D-CH47.1** — Architecture V4.1 = **Evidence-Grounded Reasoning** (extension, pas
remplacement de V4 Facts-First) :

| V4 actuel | V4.1 cible |
|---|---|
| `facts_first.facts` (atomic only) | `facts_first.atomic_facts` + `facts_first.relational_facts` + `facts_first.reasoning_graph` |
| Composer "presentation-only" Gemma-12B | Composer "constrained reasoner" Qwen2.5-72B avec `reasoning_chain` typée |
| Channel 2 NLI seuil unique 0.85 | Channel 2 seuils différenciés par `inference_strength` |

**Décision D-CH47.2** — Le `relational_facts` est l'innovation centrale. Taxonomie de démarrage
P0 limitée aux **5 types validés empiriquement** ou directement requis par les catégories Robust
qui régressent :

- `causal` (validé Mock 1 r1, q_37)
- `purpose` (validé Mock 1 r2, q_37)
- `distinction` (validé Mock 2 r1, q_88)
- `conditional` (requis catégorie `conditional` Robust, q_117)
- `hypothetical` (requis catégorie `hypothetical` Robust, q_52)

**Extensions futures empiriquement déclenchées** (à ajouter UNIQUEMENT quand un cas gold-set le
démontre nécessaire, pas a priori) : `enabling`, `temporal_succession`, `comparison_explicit`,
`exception`.

Principe : pas de taxonomie théorique préemptive. Toute extension passe par un cas concret +
revue.

Tous concepts logico-linguistiques universels (FR/EN/DE/ES/IT), **aucun keyword métier**.

**Décision D-CH47.3** — Le `inference_strength` 3 niveaux (`direct | probable | speculative`)
permet la synthèse contrôlée sans tomber dans le LLM-libre. Channel 2 NLI applique des seuils
par niveau :

**Seuils CALIBRÉS EMPIRIQUEMENT** (post-prototype CH-47.1+47.2 sur 25 steps réels,
vs valeurs ADR initiales théoriques 0.85/0.70/0.55) :

| Niveau | Définition | Seuil rejet | Seuil warning |
|---|---|---:|---:|
| `direct` | Paraphrase littérale d'un atomic_fact OU relation marquée `direct` (marqueur dans evidence_quote) | **0.50** | < 0.70 |
| `probable` | Combine plusieurs facts OU généralise OU infère sans marqueur explicite | **0.20** | < 0.40 |
| `speculative` | Hypothèse faible — réserve explicite dans la réponse | warning only | < 0.10 |

**Justification empirique des seuils calibrés** (cf `data/audit/ch47_3_nli_calibration_compared.json`) :

- mDeBERTa-v3-base sur 25 steps réels du prototype CH-47 :
  - direct (n=20) : mean=0.712, p20=0.488, distribution bimodale (10× ≥0.9, 6× [0.5-0.9], 4× <0.1)
  - probable (n=5) : mean=0.157, distribution faible (NLI strict pénalise les compositions)
- Les 4 cas direct < 0.1 incluent **1 vraie hallucination** (q_88 step 2 "safety factor 2.0"
  non sourcé) et **1 contradiction NLI** (q_36 step 1 contra=0.91) — le NLI les détecte correctement.
- **Test upgrade XLM-V-base (0.8B params) abandonné** : mean direct chute à 0.621 (vs 0.712
  v3-base), p20 chute à 0.044 (vs 0.488). XLM-V n'améliore pas et dégrade 2/4 cas critiques.
- **Seuil 0.85 ADR initial = trop strict** : rejetterait 50% des steps `direct` légitimes
  (paraphrases entailées modérément). mDeBERTa-v3-base est conservateur, marque souvent
  NEUTRAL au lieu de ENTAILMENT pour des paraphrases valides.

**Trade-off assumé** : le seuil 0.50 sur `direct` accepte ~10-15% faux positifs (paraphrases
légitimes rejetées) mais capture les **vrais cas critiques** (hallucinations factuelles,
contradictions). Acceptable car les rejets sont surfacés au Composer pour retry/abstention
constructive, pas masqués.

**Modèle NLI** : `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (0.28B, multilingue
FR/EN/DE/...) confirmé. Pas d'upgrade. Cascade LLM-judge auxiliaire (option C) reste un
plan de secours si bench global révèle trop de faux positifs (>20%).

**4e niveau `compositional` abandonné** : la calibration empirique a confirmé que le LLM
Composer Qwen-72B utilise spontanément `direct` et `probable`, jamais `compositional`. Ajout
inutile, simplification confirmée (cf retour Claude Web).

**Décision D-CH47.4** — Le Composer **trace chaque step** par `evidence_ids` et/ou `relation_id`.
Le Channel 1 Verifier applique 3 conditions de rejet et autorise les synthèses traçables :

**Conditions de rejet d'un reasoning_step** :
1. Aucun `evidence_ids` NI `relation_id` référencé
2. Les IDs référencés n'existent pas dans `facts_first`
3. Step marquée `inference_strength: direct` sans `evidence_quote` confirmant le marqueur
   linguistique explicite

**Synthèses autorisées** si :
- Step référence un `relation_id` qui trace lui-même vers `evidence_quote`, OU
- Step combine plusieurs `evidence_ids` avec `inference_strength ≥ probable`

**Décision D-CH47.5** — Routing CH-47.4 reste P1 conditionnel. Bascule P0 dynamique si bench
intermédiaire (post-CH-47.1+47.2) montre `Robust global < 0.50` OU `routing fail rate > 30%`.

### 10.5 Charte additionnelle (anti-dérive)

1. **Anti-LLM-libre** : output `reasoning_steps` typé + cité par construction. Ne pas accepter de
   step sans citation, jamais de raisonnement narratif libre.
2. **Anti-graphe global** : les `relational_facts` sont **ancrés au corpus local de la question**.

   **Définition précise du scope** :
   - **Autorisé** : relations à l'intérieur d'un chunk retrieved
   - **Autorisé** : relations entre facts de **plusieurs chunks différents** SI tous ces chunks
     ont été retrieved pour la question courante ET la relation est supportée par un
     `evidence_quote` explicite (potentiellement composé de fragments de plusieurs chunks)
   - **Interdit** : relations vers des facts de chunks NON retrieved pour cette question
   - **Interdit** : propagation transitive multi-sauts (A→B→C) sans evidence directe pour
     chaque maillon
   - **Interdit** : raisonnement sur le KG global en dehors du retrieval scope (recréerait
     le problème du KG narratif ou les dérives V3 agentic)
3. **Anti-règles métier** : les marqueurs linguistiques (`therefore`, `because`, `if/then`,
   `in order to`...) sont des **signaux d'aide universels**, jamais des conditions nécessaires
   d'extraction. Un Relational Structurer doit pouvoir extraire des relations probables sans
   marqueur explicite quand le contexte l'impose.
4. **Domain-agnostic** : la spec doit fonctionner identiquement sur médical, juridique, finance,
   IT. Test de transposabilité **différé** car un seul corpus au format KG actuellement
   (réglementaire). À valider dès qu'un 2e corpus sera ingéré.

### 10.6 Gates go-prod V4.1 (8 critères)

| # | Critère | Cible | Mesure sur |
|---|---|---|---|
| 1 | Robust global | ≥ 0.55 | bench Robust 170q |
| 2 | Aucune catégorie ne perd | > 5pp vs V3_S0 | par-catégorie |
| 3 | Hypothetical / causal_why / multi_hop / conditional | ≥ 0.50 chacune (≥ 60% delta récupéré) | par-catégorie |
| 4 | Faithfulness Channel 2 | ≥ 0.85 | maintenir acquis V4 |
| 5 | Hallucination rate | ≤ 8% | sentences sans citation valide |
| 6 | Reasoning chain validity | ≥ 80% | steps NLI-entailed (seuils calibrés) |
| 7 | Abstention rate sur reasoning questions | ≤ 15% (vs 60% V4 actuel) | rate ABSTAIN sur causal/hyp/cond/multi_hop |
| 8 | Circuit-breaker Analyzer | si #1 fail ET routing fail > 30% → CH-47.4 P1→P0 | bench intermédiaire |

### 10.7 Plan d'exécution CH-47

| Sous-chantier | Description | Priorité | Effort |
|---|---|---|---|
| **CH-47.1** Relational Structurer | Schéma `facts_first_v2` (atomic + relational + reasoning_graph). Prompts étendus pour les 5 Structurers (list, factual, temporal, comparison, causal) extraction `relational_facts` avec `inference_strength`. | **P0** | 5-7j + 1j buffer |
| **CH-47.2** Constrained Reasoning Composer | Nouveau Composer Qwen2.5-72B avec output `reasoning_steps` typé + `inference_strength` + citations forcées par step. Routing `presentation_only` (factual/list simple) vs `reasoning_mode` (causal/hypothetical/conditional/multi_hop). | **P0** | 3-4j + 1j buffer |
| **CH-47.3** Channel 2 NLI calibration | Seuils différenciés par `inference_strength` (0.85/0.75/0.70/0.55). Dataset 50 steps annotés pour calibration. Fallback mDeBERTa-v3-large si v3-base insuffisant. **Couplé à CH-47.1**. | **P0** | 1-2j + 1j buffer |
| **CH-47.4** Analyzer robustness | Réutiliser DeBERTa Sprint S2 (taxonomie answer_shape) en cascade avec Mistral-Small Analyzer. | **P1 conditionnel** | 2-3j |

**Effort P0 total** : 12-16 jours (buffer inclus).

**Ordre d'exécution P0 (révisé post-feedback ChatGPT)** :

L'ordre initial était `CH-47.3 NLI calibration → CH-47.1 Structurer → CH-47.2 Composer`, justifié
par "lever l'inconnue NLI en premier". **Réservation ChatGPT validée** : calibrer le NLI sur des
reasoning_steps rédigés à la main n'est pas représentatif des steps que produira le pipeline
réel. Risque de calibrer sur un proxy biaisé.

**Ordre révisé** :

1. **Prototype CH-47.1 + CH-47.2 sur 10 questions** (3-4j) — implémentation minimale Relational
   Structurer + Constrained Reasoning Composer, sortie de vrais `reasoning_steps` typés
2. **CH-47.3 calibration NLI sur sorties réelles** (1-2j) — annoter ≈50 steps issus du prototype
   selon `inference_strength` réel, calibrer seuils mDeBERTa sur vraies distributions
3. **CH-47.1 + CH-47.2 finalisation** (5-7j) — extension aux 5 Structurers + edge cases + tests
4. **Bench intermédiaire** (1j) — 60 questions catégories régressées → décision circuit-breaker
   CH-47.4
5. **CH-47.4 si circuit-breaker activé** (2-3j) — DeBERTa S2 cascade Analyzer
6. **Bench global** (1-2j) — Robust + T2T5 + RAGAS gold_v4 → validation 8 gates

### 10.8 Hypothèses validées par Phase 0.B (Mocks)

Mocks manuels rédigés sur q_37 et q_88 (cf `CH-47_PHASE0B_MOCKS.md`) avec test NLI Channel 2
manuel :

- **Mock 1 — q_37 (Hypothèse 1)** : Relational Structurer mocké extrait 3 atomic_facts + 2
  relational_facts (causal + purpose). Composer mocké génère 3 reasoning_steps. **3/3 ENTAILMENT
  direct** sur Channel 2 NLI manuel. Aurait restauré le score V3 0.90.

- **Mock 2 — q_88 (Hypothèse 2b)** : atomic_facts existants conservés (F1=21J, F2=80J).
  Relational_fact `purpose_distinction` ajouté. Composer mocké génère 3 reasoning_steps dont 1
  synthèse `compositional`. **2/3 ENTAILMENT direct + 1/3 BORDERLINE** (synthèse, marquée
  `inference_strength: probable`). Validé sous condition de seuil NLI à 0.70 pour `probable`.

→ **R3b VALIDÉ** sur les 2 hypothèses.

### 10.9 Alternatives rejetées

- **R1 Rollback V3** : régression latence (~80-100s vs ~60s), perd les acquis Facts-First
  (faithfulness mesurable, citation forcée). Anti-pivot par rapport à l'ADR principal.
- **R3a Composer agentic seul** : ne couvre que 2/5 cas Phase 0.B (Hypothèse 2b). Insuffisant —
  Hypothèse 1 (Structurer abdique) demande aussi un Relational Structurer.
- **R4 Fix V4 ciblé** : effort 2-4 semaines, ROI incertain. Evidence-locked RAG a des limites
  fondamentales documentées sur multi-hop / causal — un fix dispersé ne lève pas la limite
  architecturale.
- **DeepSeek-R1-Distill comme Composer** : risque "thinking tokens" non contrôlés + latence,
  contrôle moins prévisible que Qwen-72B. À reconsidérer en bake-off optionnel post-merge si gain
  réel attendu.

### 10.10 Validation triangulée

3 retours externes indépendants convergent vers R3b :
- **ChatGPT** : R3 en cible, R2 garde-fou. Souligne l'importance de **Relational Structurer**
  (vrai pivot architectural, pas Composer seul). Renomme `Reasoning` → `Constrained Reasoning`
  pour anti-dérive. Recommande P0 = Structurer + Composer, P1 = Analyzer.
- **Claude Web** : confirme R3b optimal. Apporte le template `reasoning_steps` structuré et la
  distinction relations explicites / probables. Suggère circuit-breaker Analyzer.
- **Audit Phase 0** : 3/5 Hypothèse 1 + 2/5 Hypothèse 2b. Mocks manuels passent NLI.

### 10.11 Statut et next steps

**Status** : **Decided** (2026-05-08, amendé post-feedback ChatGPT/Claude Web).

**Prochaines étapes** :
1. ✅ Tâches créées : #189 CH-47 + #190 CH-47.3 + #191 CH-47.1 + #192 CH-47.2 + #193 CH-47.4
2. **Démarrage P0 par prototype CH-47.1+47.2 sur 10 questions** (ordre révisé — pas calibration
   NLI seule sur mocks)
3. Calibration NLI CH-47.3 sur **sorties réelles** du prototype, pas sur mocks
4. Finalisation CH-47.1+47.2 + bench intermédiaire à mi-parcours → décision circuit-breaker
   CH-47.4
5. Bench global Robust + T2T5 + RAGAS gold_v4 → validation 8 gates
6. CH-46 (optims latence) reste **gelé** jusqu'à validation qualité CH-47

**Modifications à cet ADR** : par addendum daté en bas, pas par réécriture.

**Références** :
- `doc/ongoing/CH-47_PHASE0B_MOCKS.md` (mocks détaillés q_37 + q_88, test NLI manuel)
- `doc/ongoing/CH-47_PHASE1_SPEC.md` (spec implémentation P0 + prompts + schémas)
- `data/audit/ch47_audit_30q.json` (audit Phase 0.A automatique)
- `data/audit/ch47_phase0b_facts_first.json` (capture API V4 Phase 0.B)
- `data/benchmark/results/robustness_run_20260505_163544_V3_S0_BASELINE.json` (référence V3)
- `data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json` (mesure V4)

---

*Dernière mise à jour : 2026-05-07 (addendum §9 — pivot routing distribué)*
