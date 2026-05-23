# ADR A4 — Choix 2 : Vector-First Retrieval (DRAFT)

**Statut** : DRAFT — préparation pivot. À activer si Étape 1 (Piste A Hybrid BM25+Vector+RRF dans Execute) plafonne à C1 < 0.50 sur 20q.
**Date** : 2026-05-22
**Contexte** : post-A4.7 audit Oracle (retrieval=0% recall sur 18/18 questions).

---

## Cadre domain-agnostic (rappel)

OSMOSE doit fonctionner identiquement sur médical, réglementaire, juridique, aerospace, etc. Cet ADR doit produire un pattern de retrieval qui ne dépend d'aucun vocabulaire spécifique au corpus actuel.

---

## 1. Décision proposée

Remplacer le pattern actuel `Parse → SubjectResolver → PredicateResolver → kg_claims Cypher avec filtre exact subject_canonical` par un **vector-first retrieval direct** sur `claim.embedding`, avec filtres bitemporels post-hoc.

**Inspiration littérature** :
- *Direct Fact Retrieval from Knowledge Graphs without Entity Linking* (arxiv 2305.12416)
- *LightRAG* (1/100ème coût GraphRAG, flat graph dual-level retrieval)
- *LeanRAG* (-46% retrieval redundancy via semantic aggregation)

## 2. Architecture cible

```
Question utilisateur
     │
     ▼
  [Parse]          Décomposition en sub_goals (kind, hint sémantique LIBRE — pas subject_canonical strict)
     │
     ▼
  [Plan]           Mapping sub_goal → tool (déterministe)
     │
     ▼
  [Retrieve]       Vector cosine direct sur claim.embedding via Neo4j Vector Index
     │             (top-K=50, query = embedding de la question OU du sub_goal)
     │             + filtres bitemporels en post-hoc Cypher
     │             ⚠ Plus de SubjectResolver/PredicateResolver bridés à top-1
     │
     ▼
  [ClaimFilter]    Top-5 sur top-50 (mécanisme A3.11 conservé)
     │
     ▼
  [Evaluate]       Verdict 4-classes (inchangé)
     │
     ▼
  [Synthesize]     Rédaction + citations (inchangé)
     │
     ▼
  [GroundingVerifier] mDeBERTa NLI (inchangé)
```

## 3. Composants à modifier

### 3.1 Schéma Neo4j

- **Créer Neo4j Vector Index** sur `Claim.embedding` (Neo4j ≥ 5.18, déjà dispo dans notre version) :
  ```cypher
  CREATE VECTOR INDEX claim_embedding_idx IF NOT EXISTS
  FOR (c:Claim) ON (c.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}
  ```
- Coverage `claim.embedding` à vérifier (probable 100% car ClaimFilter A3.11 l'utilise déjà via lookup).

### 3.2 Module `runtime_a3/execute.py`

- **Supprimer ou rendre optionnel** `_resolve_subject_for_call(tc, "subject")` au profit de :
- **Nouveau `_call_vector_retrieval(tc, parse_input)`** : Cypher vector search + filtres bitemporels.

### 3.3 Module `runtime_a3/subject_resolver.py` et `predicate_resolver.py`

- **Mode déprécié par défaut** (env `V6_VECTOR_FIRST=1`). Pas de suppression immédiate : on garde comme fallback A/B test.

### 3.4 Schéma `runtime_a3/schemas.py`

- `SubGoal.subject_canonical` devient pleinement optionnel (déjà `Optional[str]` mais usage repensé).
- `ToolName` : nouveau `"vector_search"` ajouté à l'énum.

## 4. Avantages attendus

1. **Élimine 2 maillons fragiles** : SubjectResolver et PredicateResolver bridés à top-1 disparaissent. Le claim correct n'est plus filtré par un seul subject canonical exact qui peut ne pas matcher.
2. **Coverage retrieval théorique = 100%** : `claim.embedding` couvre tous les claims, le filtre devient sémantique pur.
3. **Domain-agnostic strict** : embedding cosine fonctionne identiquement sur médical/réglementaire/aerospace.
4. **Performance** : Neo4j Vector Index HNSW, latence ~10-50ms pour top-50 sur 11k claims.

## 5. Risques et garde-fous

| Risque | Mitigation |
|---|---|
| Perte de la bitemporalité explicite (filtre Cypher post-hoc plus coûteux) | Post-filter sur `valid_from/valid_until/invalidated_at` après vector ; latence reste OK car top-K=50 |
| Top-50 dilue le ClaimFilter A3.11 (signal/bruit) | ClaimFilter conserve top-5 final, donc cap raisonnable |
| Identifiants littéraux (codes, références) mal capturés par embedding pur | Hybrid à terme (Piste A) : ajouter BM25 en complément. Vector-first n'exclut PAS Hybrid. |
| Régression sur questions traitées correctement avant | Toggle env A/B : `V6_VECTOR_FIRST=0` (legacy) vs `=1` (vector-first) |

## 6. Validation

- Smoke test 5 questions étalon (HUM_0028/0031/0014/0080/0063 du gold-set actuel)
- Re-bench 20q avec `audit_oracle_step4` rich trace → comparer `retr_recall` avant/après
- Gate : C1 ≥ 0.45 ET retr_recall ≥ 0.50 sur questions ayant oracle

## 7. Estimation effort

- ~3j dev (vector index Neo4j + refactor Execute + tests + smoke)
- ~1j bench + analyse
- Total : ~4j (vs ~5j Piste A Choix 1)

## 8. Critère d'activation depuis Choix 1

- Si A4.9 (Piste A Hybrid BM25+Vector+RRF) C1 < 0.50 : bascule directe ici
- Si A4.9 C1 ≥ 0.50 mais < 0.65 (cible ADR Phase 1) : combiner avec Piste A (Hybrid + Vector-first) puis itérer

## 9. Hors scope de cet ADR

- Pattern Mindful-RAG (sufficiency check + textual recovery) — séparé ADR Choix 3
- Multi-formulation query (HyDE/MQRF) — extension orthogonale, peut s'ajouter sur Choix 2
- Refonte complète ADR_PARSE_EVALUATE_RUNTIME — Choix 3

---

**Statut** : DRAFT, à finaliser quand bascule activée. Reste à : (a) vérifier coverage claim.embedding ; (b) confirmer Neo4j version supporte Vector Index ; (c) prototype Cypher vector search avec filtres bitemporels.
