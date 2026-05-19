# Plan C4 — Relations Evidence-First

**Date** : 31 mars 2026
**Statut** : VALIDE (consensus Claude + Codex + ChatGPT)

---

## Objectif

Passer de 584 relations (3.7% des claims) a 750+ (5%+) avec :
- Augmentation significative des CONTRADICTS/QUALIFIES/REFINES
- Chaque relation a une preuve obligatoire (evidence spans)
- Ameliorer le recall contradictions sans augmenter les faux positifs
- Rester 100% domain-agnostic

## Etat actuel

| Metrique | Valeur |
|---|---|
| Claims | 15566 |
| Relations totales | 584 (3.7%) |
| CONTRADICTS | 20 |
| QUALIFIES | 287 |
| REFINES | 277 |
| Proactive detection T5 | 0% |
| Detection method | Entity matching uniquement |

## Architecture — 3 stages

```
Stage 1: Candidate Pair Mining
  QD grouping (primaire) + embedding fallback (v2)
  → ~5000-15000 candidate pairs (cross-doc)

Stage 2: NLI Adjudication (LLM)
  Haiku avec structured output
  → {relation_type, confidence, evidence_spans}
  Seuils: CONTRADICTS >= 0.85, QUALIFIES/REFINES >= 0.75

Stage 3: Relation Persist + Audit Trail
  Neo4j MERGE avec evidence properties
  Invariant: pas de relation sans evidence_a + evidence_b
```

## Plan d'execution

### Phase 0 — QS Comparison deterministe (1 jour) — QUICK WIN

Comparer les `extracted_value` des QuestionSignatures pour la meme QuestionDimension cross-doc.
- Si deux QS repondent a la meme QD mais avec des valeurs differentes → CONTRADICTS candidat
- 100% deterministe, 0 appel LLM, 0 faux positif
- Exemple : QD "Quel est le SLA minimum ?" → QS doc A "99.7%" vs QS doc B "99.9%" → tension detectee

### Phase 1 — CandidateMiner QD-based (2 jours)

```python
class CandidateMiner:
    """
    Strategy 1 (primaire) : QD grouping
      Claims partageant la meme QD → paires cross-doc
      Cap 50 paires par QD group (ranking par distance au centroide)

    Strategy 2 (v2, pas v1) : Embedding neighborhood
      Pour claims sans QD, Neo4j vector index k=10 (cosine > 0.82)
      Cross-doc filter
    """
```

Metriques :
- Pair coverage : % claims dans au moins une paire (cible > 60%)
- Cross-doc ratio : % paires cross-doc (cible > 80%)
- Timing : < 60s pour le corpus complet

### Phase 2 — NLI Adjudicator Haiku (2-3 jours)

Prompt NLI avec :
- **Contexte documentaire** (titre + version du doc de chaque claim)
- Instructions explicites : "similar is NOT contradiction", "version differences are evolutions not contradictions"
- Structured output JSON : relation, confidence, evidence_a, evidence_b, reasoning

```python
class NLIAdjudicator:
    THRESHOLDS = {
        "CONTRADICTS": 0.85,  # Asymetrique — faux positif pire que faux negatif
        "QUALIFIES": 0.75,
        "REFINES": 0.75,
    }
```

Validation automatique : `evidence_a` doit etre substring de `claim_a.text`. Rejet sinon.

Cout estime : ~$6 pour le corpus complet (15000 paires × $0.0004/call Haiku).

### Phase 3 — Persistence + Backfill (1 jour)

Neo4j MERGE avec properties :
- confidence, evidence_a, evidence_b, reasoning
- detection_method ("qs_structural" | "qd_nli" | "embedding_nli" | "entity_match")
- pipeline_version "c4_v1"
- detected_at datetime

Script backfill pour le corpus existant + hook post-import pour les nouveaux docs.

### Phase 4 — Gold Standard + Benchmark (1 jour)

- Annoter 20-30 contradictions connues dans le corpus (a partir des T5 questions)
- Mesurer recall + precision
- Integrer dans le benchmark RAGAS comme metrique supplementaire

## Metriques cibles

| Metrique | Avant | Cible |
|---|---|---|
| Relations totales | 584 (3.7%) | > 750 (5%) |
| CONTRADICTS | 20 | > 50 |
| Contradiction recall (gold) | 0% | > 50% |
| Contradiction precision | ? | > 85% |
| Evidence validity | ~50% | 100% |
| Proactive detection T5 | 0% | > 30% |

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Faux CONTRADICTS sur version-scoped claims | Contexte documentaire dans le prompt NLI (titre + version) |
| QD group explosion (500+ claims) | Cap 50 paires par group, ranking par distance |
| Evidence non-verbatim | Validation automatique substring check |
| Cout LLM a grande echelle | $6 pour 23 docs. DeBERTa NLI en pre-filtre si 200+ docs |
| Faible QD coverage | Embedding fallback (v2) pour claims sans QD |

## Fichiers a creer

```
src/knowbase/relations/
├── __init__.py
├── candidate_miner.py       # Stage 1
├── nli_adjudicator.py       # Stage 2
├── relation_persister.py    # Stage 3
└── pipeline.py              # Orchestration

app/scripts/
└── backfill_relations_c4.py # Backfill corpus

benchmark/gold/
└── contradictions.json      # Gold standard
```

## Enrichissements post-review ChatGPT (31 mars)

### 1. Candidate pool adaptatif par signal (pas un top_k fixe)

Au lieu d'un top_k=30 global, le pool de candidats pre-reranking doit etre **conditionnel** :
- Silence KG → pool standard (top_k=10, comportement actuel)
- Signal tension/evolution → pool elargi (top_k=20) pour augmenter la probabilite que les deux cotes de la divergence remontent
- Signal coverage_gap → fetch supplementaire Phase C light (deja implemente)

Cela s'integre dans la `SignalPolicy` existante comme un nouveau champ `expand_retrieval_pool: bool`.

### 2. Diversite documentaire forcee en mode signal

Quand un signal multi-doc est actif (tension, evolution, coverage) :
- Max 50% chunks du meme document dans le top final
- Min 2 documents dans les resultats si possible
- NE PAS appliquer aux questions simples (silence KG = RAG pur, invariant Type A)

Implementation : post-filtre dans `retrieve_chunks()` conditionne par `signal_policy.force_doc_diversity`.

### 3. Benchmark bicephale (RAGAS + T2/T5)

Le "production gate" OSMOSIS doit etre double :
- **Gate RAGAS** : faithfulness >= 0.80, context_relevance >= 0.70 (non-regression socle)
- **Gate T2/T5** : contradiction_recall >= 30%, both_sides_surfaced >= 40% (differenciation)

Les deux gates doivent etre mesures a chaque changement significatif.

### 4. Tableau de decision C4

| Hypothese C4 | Metrique a regarder | Signe de succes | Signe d'echec |
|---|---|---|---|
| QS comparison detecte des tensions structurelles | Nouvelles CONTRADICTS via QS | > 10 nouvelles | 0 (QS trop sparse) |
| QD grouping produit des candidats pertinents | Pair coverage | > 60% claims dans 1+ paire | < 30% (QD coverage insuffisante) |
| NLI Haiku distingue contradiction vs evolution | Precision CONTRADICTS | > 85% sur echantillon 50 | < 70% (prompt insuffisant) |
| Pipeline augmente le total relations | Relations count | > 750 (5%+) | < 650 (pipeline inefficace) |
| Contradictions remontent dans les reponses | Proactive detection T5 | > 30% | 0% (ContradictionEnvelope pas branche) |
| Pas de regression RAG | RAGAS faithfulness | >= 0.80 | < 0.78 (regression) |

## Effort total estime : 6-7 jours
