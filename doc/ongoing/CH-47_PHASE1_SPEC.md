# CH-47 Phase 1 — Spec consolidée "Evidence-Grounded Reasoning"

**Date** : 2026-05-08 (amendé post-feedback ChatGPT/Claude Web)
**Statut** : Spec ready-to-implement (post-Phase 0.B mocks validés)
**Référence** : `CH-47_PHASE0B_MOCKS.md` (Mocks q_37 + q_88 validés)
**Pivot** : V4 Facts-First → V4.1 **Evidence-Grounded Reasoning** (paradigme atomic+relational)

## ⚠️ Amendements post-feedback (2026-05-08, soir)

Suite à la review ChatGPT/Claude Web sur l'ADR §10, **3 amendements** s'appliquent à cette spec :

1. **`inference_strength` 3 niveaux** (`direct | probable | speculative`) au lieu de 4. Le niveau
   `compositional` est **différé** — sera ajouté UNIQUEMENT si la calibration NLI empirique
   révèle un besoin de seuil intermédiaire 0.75. Voir ADR §10.4 D-CH47.3.
2. **Taxonomie relations P0 limitée à 5 types validés ou requis par catégories Robust** :
   `causal | purpose | distinction | conditional | hypothetical`. Les 4 autres
   (`enabling | temporal_succession | comparison_explicit | exception`) sont reportés en
   extensions empiriques (ajout déclenché par cas concret, pas a priori). Voir ADR §10.4 D-CH47.2.
3. **Ordre P0 révisé** : prototype CH-47.1+47.2 sur 10 questions D'ABORD (3-4j) → vraies sorties
   reasoning_steps → calibration CH-47.3 NLI sur sorties RÉELLES (1-2j), pas sur mocks. Voir
   ADR §10.7 "Ordre d'exécution P0 révisé".

Les sections détaillées ci-dessous reflètent ces amendements. Les seuils NLI 0.85/0.70/0.55
remplacent 0.85/0.75/0.70/0.55. La taxonomie 5 types remplace 9 types dans le schéma.

## TL;DR

Le pipeline V4 actuel régresse de **-18pp à -36pp vs V3_S0** sur les questions de raisonnement (causal, hypothetical, multi_hop, conditional). Diagnostic Phase 0 :

- 60% des échecs = **Structurer abdique** (`answerability=unanswerable`) alors que les chunks contiennent l'information
- 40% des échecs = **Composer "presentation-only"** ne synthétise pas

CH-47 introduit une **deuxième couche de représentation** dans `facts_first` : **`relational_facts`** (causal, conditional, purpose, hypothetical, comparison, exception) à côté des `atomic_facts` existants. Le Composer devient un **reasoner contraint** qui produit une `reasoning_chain` traçable et NLI-vérifiable.

**Effort** : 12-16 jours P0 (CH-47.1 + 47.2 + 47.3) + 2-3j P1 conditionnel (47.4).

## Amendement ADR V4 §10 — Evidence-Grounded Reasoning

### Décision

L'architecture V4 est **enrichie** (pas remplacée) :

| V4 actuel (Facts-First) | V4.1 cible (Evidence-Grounded Reasoning) |
|---|---|
| `facts_first.facts` (atomic only) | `facts_first.atomic_facts` + `facts_first.relational_facts` + `facts_first.reasoning_graph` |
| Composer "presentation-only" | Composer "constrained reasoner" avec `reasoning_chain` |
| Channel 2 NLI seuil unique | Channel 2 NLI seuils **différenciés par `inference_strength`** |
| Analyzer 5-types ou abstain | inchangé (P1 conditionnel) |

### Charte (anti-dérive)

1. **Anti-LLM-libre** : le Composer produit des `reasoning_steps` typés et cités, pas de raisonnement narratif libre.
2. **Anti-graphe global** : les relations sont **ancrées au corpus local de la question** (chunks récupérés). Pas de propagation multi-hop sur l'ensemble du KG.
3. **Anti-règles métier** : les marqueurs linguistiques (causal, conditional, etc.) sont des **signaux d'aide universels** (FR/EN/DE/ES/IT), jamais des conditions nécessaires d'extraction. Aucun keyword sectoriel.
4. **Anti-overfit corpus** : la spec doit fonctionner identiquement sur médical, juridique, finance, IT — testée sur ≥ 2 corpus différents avant merge.

## CH-47.1 — Relational Structurer (P0, 5-7j + 1j buffer)

### Mission

Étendre le Structurer existant pour produire **deux niveaux de facts** :
- `atomic_facts` : assertions directes (V4 actuel, conservé tel quel)
- `relational_facts` : relations entre facts ou phénomènes (NOUVEAU)

### Schéma `facts_first_v2`

```json
{
  "schema_version": "facts_first_v2",
  "primary_type": "causal | factual | list | temporal | comparison | hypothetical | conditional | unanswerable | false_premise",
  "answerability": "answerable | answerable_with_reasoning | unanswerable | false_premise",
  "coverage_state": "complete | partial | unknown",
  "atomic_facts": [
    {
      "id": "f1",
      "text": "...",
      "subject": "...",
      "predicate": "...",
      "object": {"raw": "...", "normalized": "...", "kind": "number|date|text|entity", "unit": "..."},
      "qualifiers": {"condition": "...", "scope": "...", "time_anchor": "...", "lifecycle_status": "..."},
      "source": {"doc_id": "...", "claim_id": "...", "page_no": 0, "quote": "..."},
      "confidence": 0.0
    }
  ],
  "relational_facts": [
    {
      "id": "r1",
      "relation_type": "causal | purpose | conditional | hypothetical | enabling | temporal_succession | comparison | distinction | exception",
      "marker": "therefore | because | in_order_to | if_then | unless | when | ... | null",
      "antecedent_ids": ["f1", "f2"],
      "consequent_ids": ["f3"],
      "evidence_quote": "verbatim source quote ≥ 10 chars",
      "evidence_doc_id": "doc_id",
      "inference_strength": "direct | compositional | probable | speculative",
      "confidence": 0.0
    }
  ],
  "reasoning_graph": {
    "nodes": ["f1", "f2", "f3"],
    "edges": [{"from": "f1", "to": "f3", "via": "r1"}]
  }
}
```

### `inference_strength` — règles

| Niveau | Description | Exemple | Channel 2 NLI seuil |
|---|---|---|---|
| `direct` | Marqueur explicite ET evidence_quote contient le marqueur | "have been changed... therefore Annex I should be amended" | 0.85 |
| `compositional` | Combinaison explicite de plusieurs atomic_facts (chaque sous-fact direct) | F1 (21J single impact) + F2 (80J until destruction) → r1 distinction | 0.75 |
| `probable` | Inférence raisonnable depuis facts adjacents, pas de marqueur unique | "If A occurs, B follows" déduit de contexte sans "if" explicite | 0.70 |
| `speculative` | Hypothèse faible, à mentionner avec réserve dans la réponse | déduction par analogie ou par défaut | 0.55 (warning) |

### Prompt Relational Structurer (template)

```
You are a Relational Structurer. Extract two levels of facts from evidence:

1. ATOMIC FACTS: directly stated assertions (subject, predicate, object).
2. RELATIONAL FACTS: relationships between facts that are anchored in the evidence.

Relation types (universal, multilingual):
- causal: A causes / leads to / necessitates / results in B
- purpose: A is done in order to / so as to achieve B
- conditional: if A then B / B provided that A / unless A
- hypothetical: in case of A, B would occur / assuming A
- enabling: A allows / enables / facilitates B
- temporal_succession: A precedes / follows / supersedes B
- comparison: A vs B (similar / different / equivalent)
- distinction: A and B differ in purpose/scope/role
- exception: A applies except when B

For EACH relational_fact, set inference_strength:
- "direct": linguistic marker present in evidence_quote (because, donc, therefore, if/then, in order to, etc.)
- "compositional": combination of multiple atomic_facts each direct, no single marker
- "probable": inference from adjacent context without explicit marker
- "speculative": weak inference, hypothesis only

CRITICAL CONSTRAINTS:
- Every relation MUST have evidence_quote ≥ 10 chars from the chunks
- Linguistic markers are HELPFUL SIGNALS, not necessary conditions
- Do NOT propagate inferences beyond the local question corpus
- Do NOT invent relations not anchored in evidence

Output JSON conforming to facts_first_v2 schema.
```

### Few-shot examples (à inclure dans le prompt système)

**Example 1 — Direct causal (q_37 type)** :
```
Evidence: "...have been changed during 2021, and therefore Annex I should be amended..."
Output:
{
  "atomic_facts": [{"id": "f1", "text": "Control lists changed in 2021", ...}, {"id": "f2", "text": "Annex I should be amended", ...}],
  "relational_facts": [{"id": "r1", "relation_type": "causal", "marker": "therefore", "antecedent_ids": ["f1"], "consequent_ids": ["f2"], "evidence_quote": "...have been changed during 2021, and therefore Annex I should be amended...", "inference_strength": "direct"}]
}
```

**Example 2 — Compositional distinction (q_88 type)** :
```
Evidence: "subjected to a single impact... 21 J" + "testing... should be performed until destruction, or until... 80 J"
Output:
{
  "atomic_facts": [{"id": "F1", "text": "Single impact = 21 J"}, {"id": "F2", "text": "Until destruction = 80 J"}],
  "relational_facts": [{"id": "r1", "relation_type": "distinction", "marker": null, "antecedent_ids": ["F1"], "consequent_ids": ["F2"], "evidence_quote": "subjected to a single impact... testing... until destruction", "inference_strength": "compositional", "confidence": 0.80}]
}
```

### Files à créer/modifier

- NEW : `src/knowbase/facts_first/relational_structurer.py` (extension `causal_pipeline.py`, `comparison_pipeline.py`, etc.)
- EDIT : `src/knowbase/facts_first/list_structurer.py`, `factual_structurer.py`, `temporal_pipeline.py`, `comparison_pipeline.py`, `causal_pipeline.py` — ajout extraction `relational_facts`
- NEW : `schemas/facts_first/facts_first_v2.json` (schéma JSON validation)
- EDIT : `src/knowbase/facts_first/list_verifier.py`, `factual_verifier.py`, etc. — validation `relational_facts`

### Tests

- Unit tests : 20 questions stratifiées par `relation_type` (couvrant 9 types)
- Integration : Mock 1 + Mock 2 doivent passer NLI Channel 2 (cf Phase 0.B)
- Regression : `list/factual/temporal` simples doivent garder leur comportement V4 (atomic_facts produits comme avant)

## CH-47.2 — Constrained Reasoning Composer (P0, 3-4j + 1j buffer)

### Mission

Remplacer le Composer "presentation-only" Gemma-12B par un **Reasoner contraint** qui produit une `reasoning_chain` typée et tracée.

### Modèle

**Qwen2.5-72B-Instruct** (DeepInfra) par défaut. **Pas DeepSeek-R1-Distill** sauf bake-off explicite — risque de "thinking tokens" non contrôlés et latence.

### Output schéma

```json
{
  "reasoning_steps": [
    {
      "step": 1,
      "type": "evidence_identification | causal_inference | conditional_projection | purpose_synthesis | distinction | exception_handling | composition",
      "inference": "natural language statement",
      "evidence_ids": ["f1", "f2"],
      "relation_id": "r1 | null",
      "inference_strength": "direct | compositional | probable | speculative",
      "confidence": 0.0
    }
  ],
  "answer": "user-facing prose with citations [doc=...] inline",
  "citations": ["f1", "f2", "r1"],
  "reasoning_confidence": 0.0,
  "abstention_reason": "null | provide_string_if_truly_unanswerable"
}
```

### Prompt Constrained Reasoning Composer

```
You are a Constrained Reasoning Composer. Generate a structured answer using ONLY the provided facts and relations.

Question (type={primary_type}): {question}

Evidence:
- atomic_facts: {atomic_facts}
- relational_facts: {relational_facts}
- reasoning_graph: {reasoning_graph}

CRITICAL CONSTRAINTS:
1. Every reasoning_step MUST cite evidence_ids OR a relation_id. No exception.
2. Mark inference_strength on each step:
   - "direct" if step rephrases a single fact or follows a relation marked "direct"
   - "compositional" if step combines multiple direct facts
   - "probable" if step infers from context without explicit marker
   - "speculative" only as last resort, mark caveat in answer
3. For causal/conditional/hypothetical questions: USE relational_facts. If absent or insufficient, set abstention_reason and answer should explain WHAT is missing.
4. Do NOT introduce knowledge outside provided evidence.
5. The final answer field is the user-facing prose. Include doc citations inline.

If reasoning_graph is non-empty: traverse it to build the reasoning_chain.
If only atomic_facts available (no relations): build "compositional" steps with explicit combinations.
If neither: emit abstention with constructive reason (e.g., "Found facts X and Y but no relation between them in the corpus").
```

### Logique d'abstention raisonnée (vs ABSTAIN brutal V4)

V4 actuel émet `"La réponse n'a pas été trouvée"` même quand des facts existent.
V4.1 doit distinguer :

- **`answer_provided`** : question répondable avec reasoning_chain
- **`partial_answer`** : reasoning_chain incomplète, mention "ce qui est établi / ce qui manque"
- **`abstention_with_explanation`** : impossibilité avec explication ("Found X but no causal link to Y in the corpus")
- **`abstention_unanswerable`** : vraiment aucune information

→ Gate go-prod #7 : abstention rate sur reasoning ≤ 15% (vs 60% actuel V4).

### Files à créer/modifier

- NEW : `src/knowbase/facts_first/reasoning_composer.py` (nouveau Composer agentic)
- EDIT : `src/knowbase/facts_first/pipeline.py` — orchestrer entre `presentation_composer` (factual/list simple) et `reasoning_composer` (causal/hypothetical/conditional/multi_hop)
- EDIT : `src/knowbase/api/routers/runtime_v4.py` — exposer `reasoning_steps` et `citations` dans response

## CH-47.3 — Channel 2 NLI seuils calibrés (P0, 1-2j + 1j buffer)

### Mission

Étendre le Channel 2 NLI mDeBERTa pour valider chaque `reasoning_step` avec des **seuils différenciés par `inference_strength`**.

### Logique

```python
def validate_reasoning_step(step, facts_first):
    premise = build_premise_from_evidence_ids(step.evidence_ids, facts_first)
    if step.relation_id:
        premise += build_premise_from_relation(step.relation_id, facts_first)
    hypothesis = step.inference

    entailment_score = mdeberta_nli(premise, hypothesis)

    threshold = {
        "direct": 0.85,
        "compositional": 0.75,
        "probable": 0.70,
        "speculative": 0.55,
    }[step.inference_strength]

    if entailment_score < threshold:
        return Issue(severity="error" if step.inference_strength == "direct" else "warning",
                     code="reasoning.step.not_entailed",
                     message=f"Step {step.step} ({step.inference_strength}) NLI={entailment_score:.2f} < {threshold}")
    return None
```

### Calibration

- Dataset test : 50 reasoning_steps annotés manuellement (10 par niveau × 5 = 50)
- Mesure : recall (vrais positifs) et precision (faux positifs)
- Cible : recall ≥ 0.80 sur `direct`, ≥ 0.70 sur `compositional/probable`, ≥ 0.50 sur `speculative`
- Si mDeBERTa-v3-base trop sévère sur `compositional` → tester `nli-deberta-v3-large` ou Auto-GDA domain adaptation (mentionné par ChatGPT, à étudier si calibration insuffisante)

### Files à modifier

- EDIT : `src/knowbase/facts_first/nli_channel2.py` — méthode `validate_reasoning_chain(steps, facts_first)`
- NEW : `tests/facts_first/test_nli_calibration.py` — dataset 50 steps annotés

## CH-47.4 — Analyzer robustness (P1 conditionnel, 2-3j)

### Statut

**P1 par défaut**. Bascule **P0 dynamiquement** si :
- Bench intermédiaire post-CH-47.1+47.2 montre `Robust global < 0.50`
- OU `routing fail rate > 30%` sur les 5 types

### Approche

Réutiliser le **DeBERTa déjà entraîné Sprint S2** (taxonomie answer_shape 5 classes, sur 14767q).
Si checkpoint dispo : intégrer comme **classifier auxiliaire de l'Analyzer LLM** (cascade : DeBERTa rapide → si confidence < 0.7 → fallback Mistral-Small Analyzer).

### Files

- NEW : `src/knowbase/facts_first/analyzer_cascade.py` (DeBERTa + LLM fallback)
- EDIT : `src/knowbase/facts_first/question_analyzer.py` — intégration cascade

## Gates go-prod consolidés (8 critères)

1. **Robust global ≥ 0.55** (cible produit, vs 0.351 V4)
2. **Aucune catégorie ne perd > 5pp vs V3_S0**
3. **Hypothetical / causal_why / multi_hop / conditional ≥ 0.50** (≥ 60% du delta perdu)
4. **Faithfulness Channel 2 ≥ 0.85** (maintenir acquis V4)
5. **Hallucination rate ≤ 8%** (sentences sans citation valide)
6. **Reasoning chain validity ≥ 80%** (steps NLI-entailed selon seuils calibrés)
7. **Abstention rate sur questions reasoning ≤ 15%** (vs 60% V4)
8. **Circuit-breaker Analyzer** : si gate 1 échoué ET routing fail > 30% → upgrade CH-47.4 P1 → P0

## Plan d'implémentation P0

| Jour | Chantier | Livrable |
|---|---|---|
| 1-2 | CH-47.3 calibration NLI (seuils) | dataset 50 steps + thresholds calibrés |
| 3-7 | CH-47.1 Relational Structurer | prompt + schéma v2 + 5 Structurers étendus + tests unit |
| 6-9 | CH-47.2 Reasoning Composer | nouveau composer + integration pipeline + tests |
| 10-11 | Integration + edge cases | bench micro 30q stratifié, debug |
| 12 | Bench intermédiaire | 60 questions sur catégories régressées (causal/hypothetical/multi_hop/conditional) → décision circuit-breaker |
| 13-15 | CH-47.4 si circuit-breaker activé | DeBERTa cascade Analyzer |
| 14-16 | Bench global Robust + T2T5 + RAGAS | validation 8 gates |

**Total P0 réaliste : 12-16 jours** (incluant 2-3j buffer intégration).

## Charte domain-agnostic (vérification finale)

| Composant | Domain-agnostic ? | Justification |
|---|---|---|
| Relations universelles (causal, conditional, purpose...) | ✓ | Concepts logico-linguistiques universels |
| Marqueurs (`therefore, donc, because, if/then, in order to`) | ✓ | Multilingues, non-sectoriels |
| `inference_strength` (direct/compositional/probable/speculative) | ✓ | Niveau de certitude logique, pas métier |
| Prompts Relational Structurer + Composer | ✓ | Aucun keyword métier, exemples diversifiés (réglementaire / médical / finance) à inclure |
| Channel 2 NLI seuils | ✓ | Métrique entailment universelle |
| `relational_facts.relation_type` | ✓ | Taxonomie logique, applicable à tout domaine |

**Test de transposabilité** : un seul corpus au format KG actuellement (réglementaire). Le test sur un 2e corpus est **différé** jusqu'à ingestion d'un nouveau corpus. La charte domain-agnostic reste un invariant de design (pas de regex/keywords métier dans les prompts), validable par revue de code en attendant le 2e corpus.

## Risques et mitigations

| Risque | Probabilité | Mitigation |
|---|---|---|
| Relational Structurer extrait trop de relations spurious (low-quality) | Moyenne | Validation Channel 1 stricte sur `evidence_quote ≥ 10 chars`, filtre confidence < 0.6 |
| Channel 2 NLI sur synthèses (`compositional/probable`) trop sévère | **Élevée** | Calibration dataset 50 steps + fallback mDeBERTa-large si v3-base insuffisant |
| Composer Qwen-72B latence élevée (+5-15s vs Gemma-12B) | Moyenne | Acceptable si gain qualité Robust > 0.55. Optim latence post-stabilisation (CH-46 gelé jusqu'à validation) |
| Routing Analyzer reste fragile | Moyenne | Circuit-breaker P1 → P0, DeBERTa cascade |
| Reasoning graph dérive vers KG narratif | Faible (mais grave) | Charte explicite "ancrée corpus local", pas de propagation multi-hop graph-wide |
| Régression sur factual/list/temporal simples | Moyenne | Composer routing : `presentation_only` mode pour ces types (V4 actuel inchangé), `reasoning_mode` uniquement sur reasoning types |

## Décisions actées (2026-05-08)

1. ✅ **Modèle Composer** : **Qwen2.5-72B-Instruct** confirmé. Pas de bake-off DeepSeek-R1-Distill au démarrage (à reconsidérer post-merge si gain réel attendu sur reasoning natif).
2. ⏳ **Test domain-agnostic** : différé tant qu'un 2e corpus au format KG n'est pas ingéré. La charte domain-agnostic reste un invariant de design (vérifiable par code review).
3. ✅ **ADR amendement §10** rédigé dans `doc/ongoing/chantiers/2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md`.
4. **Démarrage P0** : à valider par Fred. Premier livrable proposé = CH-47.3 (calibration NLI seuils — l'inconnue la plus risquée à lever en premier).
