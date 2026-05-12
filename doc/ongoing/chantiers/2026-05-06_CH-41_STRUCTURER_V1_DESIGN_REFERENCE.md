# Structurer V1 cible — Design Reference

> **Source** : Réponse ChatGPT 2026-05-06 sur demande Fred (« design détaillé Structurer V1 cible, pas MVP »).
> **Statut** : Référence intégrée dans `ADR_V4_FACTS_FIRST.md`. Ajustements C1-C8 documentés dans l'ADR §4.1 — ce document est la version brute du design avant ajustements.
> **Usage** : référence pour implémentation des tranches verticales 1-5 (list, factual, temporal, comparison, causal, unanswerable/false_premise).

---

## 1. Principe architectural

Le Structurer devient le cœur du runtime V4.

```
Question
 → Retrieval Qdrant + Claims Neo4j
 → Question Type Detection
 → Type-Adaptive Structurer
 → Structured Evidence Package
 → Composition contrôlée
 → Verifier JSON→prose
 → Réponse utilisateur
```

Le LLM ne doit plus transformer directement des chunks en réponse. Il transforme des preuves en **objets structurés vérifiables**, puis un second passage formate ces objets.

Le diagnostic S0 justifie cette bascule : retrieval trouve souvent le bon contexte, mais factual_correctness tombe à 0.368 et item_recall à 0.07 sur les listes — perte d'information pendant la synthèse libre.

---

## 2. Composants cible

### 2.1 QuestionAnalyzer

Sortie :
```json
{
  "primary_type": "list",
  "secondary_type": "temporal",
  "language": "fr",
  "requires_exhaustive_enumeration": true,
  "requires_versioning": false,
  "requires_comparison": false,
  "requires_causal_chain": false,
  "confidence": 0.87
}
```

Types supportés : `factual`, `list`, `temporal`, `comparison`, `causal`, `unanswerable`, `false_premise`.

Important : ce n'est pas un IntentResolver façon V2. Il choisit seulement le **schéma d'extraction**, pas la réponse.

### 2.2 EvidenceCollector

Source primaire : **Claims Neo4j**. Source secondaire : chunks Qdrant.

Flux :
```
Qdrant top chunks
 → récupérer claim_ids liés via chunk_ids
 → enrichir depuis Neo4j
 → ajouter DocumentContext
 → ajouter LOGICAL_RELATION pertinentes
 → fallback chunk text si claims insuffisantes
```

Contrat d'entrée du Structurer :
```json
{
  "question": "...",
  "question_analysis": {},
  "claims": [
    {
      "claim_id": "C123",
      "doc_id": "DOC_A",
      "text": "verbatim claim text",
      "quote": "exact source quote",
      "chunk_ids": ["CH1"],
      "page_no": 12,
      "document_context": {
        "lifecycle_status": "ACTIVE",
        "publication_date": "2024-01-12"
      },
      "relations": [
        {"type": "SUPERSEDES", "target_claim_id": "C456", "target_doc_id": "DOC_B"}
      ]
    }
  ],
  "chunks": [
    {"chunk_id": "CH1", "doc_id": "DOC_A", "text": "chunk text", "page_no": 12}
  ]
}
```

---

## 3. Structurer par type

### 3.1 ListStructurer

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "list",
  "answerability": "answerable",
  "coverage_state": "partial",
  "list_subject": "controlled items",
  "list_scope": {
    "scope_description": "Items explicitly listed in the provided evidence",
    "doc_id": "DOC_A",
    "section_id": null,
    "confidence": 0.82
  },
  "items": [
    {
      "item_id": "I1",
      "label": "Category 3",
      "normalized_label": "category 3",
      "item_type": "category",
      "attributes": [],
      "source": {
        "doc_id": "DOC_A", "claim_id": "C123", "chunk_id": "CH1",
        "page_no": 42, "quote": "exact quote"
      },
      "confidence": 0.91
    }
  ],
  "enumeration_quality": {
    "expected_exhaustive": true,
    "coverage_state": "partial",
    "evidence_count": 17,
    "deduped_count": 14,
    "deduplication_notes": "3 duplicate labels merged"
  }
}
```

Gate : `item_recall ≥ 0.65`, `item_precision ≥ 0.80`, `p95 latency ≤ 35s`.

### 3.2 FactualStructurer

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "factual",
  "answerability": "answerable",
  "coverage_state": "not_applicable",
  "facts": [
    {
      "fact_id": "F1",
      "subject": "Regulation (EU) 2021/821",
      "predicate": "was adopted on",
      "object": {"raw": "20 May 2021", "normalized": "2021-05-20", "kind": "date", "unit": null},
      "qualifiers": {
        "condition": null, "scope": null,
        "time_anchor": "20 May 2021", "lifecycle_status": "ACTIVE"
      },
      "source": {
        "doc_id": "DOC_A", "claim_id": "C123", "chunk_id": "CH1",
        "page_no": 1, "quote": "exact quote"
      },
      "confidence": 0.94
    }
  ],
  "direct_answer_fact_ids": ["F1"]
}
```

Gate : `fact_tuple_f1 ≥ 0.75`, `exact_identifier_match ≥ 0.80`.

### 3.3 TemporalStructurer

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "temporal",
  "answerability": "answerable",
  "coverage_state": "partial",
  "subject": "impact energy requirement",
  "timeline": [
    {
      "event_id": "T1",
      "time_anchor": {"raw": "Amendment 26", "normalized": null, "kind": "amendment"},
      "state": {"status": "DEPRECATED", "predicate": "required impact energy", "value": "3.5 J"},
      "change_type": "replaced",
      "source": {"doc_id": "CS25_AMDT26", "claim_id": "C1", "chunk_id": "CH1", "quote": "exact quote"},
      "confidence": 0.82
    },
    {
      "event_id": "T2",
      "time_anchor": {"raw": "Amendment 28", "normalized": null, "kind": "amendment"},
      "state": {"status": "ACTIVE", "predicate": "required impact energy", "value": "21 J"},
      "change_type": "modified",
      "source": {"doc_id": "CS25_AMDT28", "claim_id": "C2", "chunk_id": "CH2", "quote": "exact quote"},
      "confidence": 0.88
    }
  ],
  "current_basis": {
    "event_id": "T2",
    "reason": "The source is marked ACTIVE and supersedes the earlier version."
  }
}
```

Gate : `event_f1 ≥ 0.70`, `lifecycle_status_accuracy ≥ 0.80`.

### 3.4 ComparisonStructurer

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "comparison",
  "answerability": "answerable",
  "coverage_state": "partial",
  "comparison_subject": "impact energy requirement",
  "compared_facts": [
    {
      "side_id": "A",
      "label": "Older source",
      "fact": {
        "subject": "CS-25 Amendment 26",
        "predicate": "requires impact energy",
        "object_raw": "3.5 J",
        "qualifiers": {"scope": "Amendment 26", "time_anchor": "Amendment 26", "lifecycle_status": "DEPRECATED"}
      },
      "source": {"doc_id": "CS25_AMDT26", "claim_id": "C1", "chunk_id": "CH1", "quote": "exact quote"}
    },
    {
      "side_id": "B",
      "label": "Current source",
      "fact": {
        "subject": "CS-25 Amendment 28",
        "predicate": "requires impact energy",
        "object_raw": "21 J",
        "qualifiers": {"scope": "Amendment 28", "time_anchor": "Amendment 28", "lifecycle_status": "ACTIVE"}
      },
      "source": {"doc_id": "CS25_AMDT28", "claim_id": "C2", "chunk_id": "CH2", "quote": "exact quote"}
    }
  ],
  "relation": {
    "type": "supersession",
    "basis": "time",
    "explanation": "The two values differ because the later active source replaces the older deprecated one.",
    "confidence": 0.86
  },
  "preferred_answer_basis": {"side_id": "B", "reason": "active_source"}
}
```

Gate : `side_fact_f1 ≥ 0.75`, `relation_accuracy ≥ 0.70`.

### 3.5 CausalStructurer

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "causal",
  "answerability": "partial",
  "coverage_state": "partial",
  "causal_question": "Why is X required?",
  "causal_chains": [
    {
      "chain_id": "C1",
      "steps": [
        {
          "step_id": "C1_S1",
          "role": "cause",
          "statement": "The regulation identifies a specific risk.",
          "source": {"doc_id": "DOC_A", "claim_id": "C1", "chunk_id": "CH1", "quote": "exact quote"},
          "confidence": 0.78
        },
        {
          "step_id": "C1_S2",
          "role": "mechanism",
          "statement": "The requirement mitigates that risk by imposing a constraint.",
          "source": {"doc_id": "DOC_A", "claim_id": "C2", "chunk_id": "CH2", "quote": "exact quote"},
          "confidence": 0.74
        }
      ],
      "chain_confidence": 0.72,
      "missing_links": [
        {
          "position": "after_last",
          "description": "The evidence does not explicitly state the final operational consequence."
        }
      ]
    }
  ],
  "answer_mode": "partial_explanation"
}
```

Gate : `causal_step_f1 ≥ 0.65`, `chain_order_accuracy ≥ 0.70`, `unsupported_mechanism_rate ≤ 10%`.

### 3.6 AnswerabilityStructurer (unanswerable + false_premise)

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "false_premise",
  "answerability": "false_premise",
  "coverage_state": "not_applicable",
  "question_assumption": "The question assumes that document A is currently applicable.",
  "decision": "false_premise",
  "detected_issue": {
    "type": "wrong_time",
    "description": "The evidence indicates that the assumed source is deprecated or superseded."
  },
  "supporting_negative_evidence": [
    {
      "evidence_id": "N1",
      "what_was_found_instead": "A later active source provides a different applicable rule.",
      "source": {"doc_id": "DOC_B", "claim_id": "C9", "chunk_id": "CH9", "quote": "exact quote"},
      "why_it_matters": "It invalidates the premise that the older value is current."
    }
  ],
  "correction": {
    "corrected_question": "What is the currently applicable value?",
    "corrected_answer_basis": "Use the active source DOC_B."
  },
  "abstention_reason": null
}
```

Gate : `decision_accuracy ≥ 0.80`, `negative_evidence_recall ≥ 0.65`, `false_rejection_rate ≤ 10%`.

---

## 4. Orchestration runtime

```python
def answer_v4(question: str) -> Answer:
    qa = question_analyzer.analyze(question)

    evidence = evidence_collector.collect(
        question=question, analysis=qa,
        top_k_chunks=30 if qa.primary_type == "list" else 10,
        include_claims=True, include_relations=True, include_document_context=True,
    )

    structured = structurer.route(
        primary_type=qa.primary_type, question=question, evidence=evidence,
    )

    composition = composer.compose(question=question, structured_json=structured)

    verification = json_to_prose_verifier.verify(
        structured_json=structured, composed_answer=composition,
    )

    if verification.status == "pass":
        return composition

    repaired = composer.repair(
        question=question, structured_json=structured,
        verification_feedback=verification,
    )

    verification2 = json_to_prose_verifier.verify(structured, repaired)

    if verification2.status == "pass":
        return repaired

    return deterministic_fallback(structured)
```

---

## 5. Stockage Neo4j cible

Nouveaux nœuds runtime/persistable (ne pas polluer les Claim existants) :

```cypher
(:StructuredFact {fact_id, schema_version, primary_type, subject, predicate,
                   object_raw, object_normalized, object_kind, confidence,
                   created_at, extraction_model, source_runtime_id})

(StructuredFact)-[:DERIVED_FROM]->(Claim)
(StructuredFact)-[:SUPPORTED_BY]->(Passage)
(StructuredFact)-[:FROM_DOCUMENT]->(Document)
(StructuredFact)-[:USES_CHUNK]->(RetrievalChunk)
```

Pour list :
```cypher
(:StructuredList {list_id, subject, coverage_state, scope_description, confidence})
(:StructuredListItem {item_id, label, normalized_label, item_type, confidence})
(StructuredList)-[:HAS_ITEM]->(StructuredListItem)
(StructuredListItem)-[:DERIVED_FROM]->(Claim)
```

Pour temporal / comparison / causal : nœuds dédiés similaires.

**Persist policy** : runtime → toujours JSON. Persistance Neo4j → uniquement si `confidence ≥ threshold` ET utile audit/benchmark/cache.

---

## 6. Prompts structurants

### 6.1 Prompt commun système

```
You are the OSMOSIS Structured Evidence Extractor.
You transform documentary evidence into strict JSON.
You are domain-agnostic and multilingual.
Use only provided evidence.
Never use external knowledge.
Never infer missing facts.
Preserve identifiers, dates, numbers, units and names exactly.
Every extracted object must cite a source quote.
If evidence is incomplete, mark coverage_state accordingly.
Return JSON only.
```

### 6.2 Prompts spécifiques par type

**list** :
```
Extract an exhaustive list from the evidence.
Identify the list subject and list scope.
Extract each explicitly supported item.
Deduplicate only when two items clearly refer to the same thing.
Each item must have a label, optional normalized_label, item_type, source and confidence.
If evidence does not cover the whole expected scope, set coverage_state to partial or unknown.
Do not invent missing items.
```

**factual** :
```
Extract the minimal facts needed to answer the question.
Each fact must include subject, predicate, object, qualifiers and source.
Object must preserve raw value exactly.
Normalize only when safe, otherwise use null.
Use qualifiers for condition, scope, time anchor and lifecycle status.
```

**temporal** :
```
Extract temporal states and changes.
Distinguish publication date, effective date, version, amendment and unknown.
Use document metadata when provided.
Do not mark ACTIVE, DEPRECATED or SUPERSEDED unless supported by metadata or evidence.
Build a timeline ordered when possible.
```

**comparison** :
```
Extract the compared facts and classify their relation.
Relation type must be one of:
equivalent, different, conflict, supersession, subset, superset, complementary, unknown.
Relation basis must be one of:
value, scope, time, method, definition, unknown.
If a newer active source replaces an older source, classify as supersession, not conflict.
```

**causal** :
```
Extract supported causal chains.
Each step must be cause, condition, mechanism, effect, exception or context.
Every step must cite an exact quote.
If a causal link is not explicitly supported, declare it in missing_links.
Do not invent mechanisms.
```

**unanswerable / false_premise** :
```
Identify the assumption behind the question.
Decide whether the question is answerable, unanswerable or based on a false premise.
Use supporting_negative_evidence to show what the documents contain instead.
A false premise requires contradicted or unsupported assumption.
Unanswerable requires insufficient evidence.
```

---

## 7. Composition cible

Entrée :
```json
{"question": "...", "structured_json": {}}
```

Sortie :
```json
{
  "answer": "...",
  "sentence_support": [
    {"sentence": "...", "support_ids": ["F1", "I2"]}
  ],
  "coverage_note": "..."
}
```

Prompt Composer :
```
You write user-facing answers from structured JSON.
The JSON is the only source of truth.
Do not add facts not present in JSON.
Preserve identifiers, dates, numbers and units exactly.
Answer in the same language as the question.
Every sentence must cite support_ids from the JSON.
For list questions, include all items.
For comparison, present both sides before the relation.
For temporal, state the current basis when available.
For causal, explain only the supported chain.
For false premise or unanswerable, explain the issue and what the documents show instead.
Return JSON only.
```

---

## 8. Verifier cible

### 8.1 Channel 1 : deterministic JSON grounding (toujours actif)

```
1. every sentence has support_ids
2. every support_id exists
3. all numbers/dates/identifiers in answer exist in supported JSON objects
4. list answers contain all item labels
5. comparison answers mention both sides
6. temporal answers do not use deprecated source as current basis unless explicit
7. causal answers do not add unsupported mechanism
```

### 8.2 Channel 2 : targeted NLI (déclenché conditionnellement)

```
sentence contains number/date/identifier
sentence expresses comparison relation
sentence expresses causal relation
sentence is unsupported by deterministic check
```

### 8.3 Repair policy

```
identifier mismatch → retry composition
missing list item → retry composition
unsupported causal mechanism → drop phrase or abstain
unsupported comparison relation → downgrade relation to unknown
two failed repairs → deterministic fallback from JSON
```

---

## 9. Evaluation plan

### 9.1 Première tranche cible : list

Dataset :
```
50 questions list annotées
minimum 500 expected items cumulés si possible
FR/EN mix
documents courts + longs
single-doc + multi-doc
```

Metrics :
```
item_precision, item_recall, item_f1
coverage_state_accuracy, source_accuracy
latency p50/p95
```

Gate :
```
item_f1 ≥ 0.70, item_recall ≥ 0.65
source_accuracy ≥ 0.80, p95 ≤ 35s
```

### 9.2 Suites par type

```
factual: 50 questions
temporal: 40 questions
comparison: 40 questions
causal: 40 questions
unanswerable/false_premise: 50 questions
```

Chaque type a son propre gate. Pas de moyenne globale autorisant un type.

---

## 10. Latence cible (basée S0 V3 : p50 17s, p95 33s, synthesis 13.3s, regen 50% trafic)

| Type | p50 | p95 |
|------|----:|----:|
| list | ≤ 23 s | ≤ 35 s |
| factual | ≤ 15 s | ≤ 25 s |
| temporal | ≤ 22 s | ≤ 35 s |
| comparison | ≤ 22 s | ≤ 35 s |
| causal | ≤ 25 s | ≤ 40 s |
| false_premise/unanswerable | ≤ 18 s | ≤ 30 s |

---

## 11. Décisions ADR proposées par ChatGPT (intégrées dans ADR_V4_FACTS_FIRST)

- **D1** : Runtime V4 facts-first. Aucune réponse user-facing produite directement depuis chunks sans Structured Evidence Package.
- **D2** : Claims Neo4j source primaire. Chunks Qdrant secondaires.
- **D3** : Type-adaptive. Pas de schéma EAV universel pour tous les types.
- **D4** : Composition LLM bornée au JSON structuré. Aucun fait nouveau.
- **D5** : Verifier final vérifie JSON → prose, pas corpus → prose.
- **D6** : Chaque primary_type a son propre gate. Pas de score global.
- **D7** : Tranches verticales = pas MVP. Chaque tranche implémente l'architecture cible complète sur un type.

---

## 12. Ordre de livraison cible

```
Tranche 1 : list
  - QuestionAnalyzer limité à list detection
  - EvidenceCollector claims+chunks
  - ListStructurer + ListComposer + JSON verifier
  - benchmark item_recall

Tranche 2 : factual
  - FactualStructurer + exact identifier verification

Tranche 3 : temporal + comparison
  - lifecycle metadata + LOGICAL_RELATION exploitation

Tranche 4 : causal
  - causal chain extraction + missing_links

Tranche 5 : unanswerable / false_premise
  - correction gold-set + negative evidence structuring
```

V3 reste fallback pour types non encore migrés, puis disparaît type par type.

---

## 13. Le point clé du design

Le Structurer V1 n'est pas « un extracteur JSON ». C'est le nouveau **contrat de vérité runtime** :

```
Claim / chunk evidence
 → Structured Evidence Package
 → Answer
```

Tant que cette couche n'existe pas, le LLM reste libre de compresser, oublier ou reformuler. Avec cette couche, la réponse devient vérifiable phrase par phrase.

---

*Fin du document de référence. Ajustements appliqués dans `ADR_V4_FACTS_FIRST.md` §4.1 (C1-C8) avant intégration.*
