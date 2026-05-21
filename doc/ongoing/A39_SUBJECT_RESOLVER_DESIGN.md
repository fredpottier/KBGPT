# A3.9 — Subject Resolver Runtime (Design Doc)

**Status** : ✅ LIVRÉ (22/05/2026)
**Branche** : `feat/phase-a-bitemporel`
**Phase** : A3 — Runtime Parse → Plan → Execute → Evaluate → Synthesize
**Cause racine** : A3.8 finding — Mismatch entre `subject_canonical` produit par Parse LLM (user-friendly) et indexation effective dans le KG.

## 1. Problème (cause racine A3.8)

Bench A3.8 (50q SAP stratifiées) : coverage `empty` sur 60% des questions factual/list. Diagnostic post-bench :

```
Question → Parse LLM produit subject_canonical="Labeling Workbench"
KG contient                      subject_canonical="CBGLWB - Labeling Workbench" (transaction-prefixed)
                              OU subject_canonical="Global Label Management - Labeling Workbench" (path-prefixed)

→ MATCH (c:Claim {subject_canonical: "Labeling Workbench"}) ⇒ 0 hits ⇒ coverage=empty
```

Idem pour "team lead role" → KG indexe via codes activité (`P_PYD_IAUT`) ou rôles SAP standards (`SAP_HR_LEAD`).

**Pas un problème d'extraction** : les claims existent. **Problème d'adressage** : on cherche un subject qui n'a pas la même graphie côté KG.

## 2. Inspiration EKX (échange 21/05/2026)

EKX (SAP RAG+KG interne) gère le même problème avec un pipeline 5 étapes :
1. **Normalisation** : lowercase, strip, NFKC, collapse spaces
2. **Exact match** sur attribut `normalized_name` indexé
3. **Full-text search** Neo4j sur `name` (index FTS)
4. **Embedding fallback** via collection vectorielle si étapes 2-3 ne donnent rien de fort
5. **Re-ranking grapho-sensitif** : suivre `:ABOUT` vers les Claims, scorer par cohérence avec le `predicate_hint`

Pattern domain-agnostic : aucun token corpus-spécifique, repose sur des heuristiques lexicales + sémantiques + graphe.

## 3. Architecture livrée

### 3.1 Modules

```
src/knowbase/runtime_a3/
├── subject_resolver.py     # NEW (~430 LOC) — pipeline 5 étapes
├── schemas.py              # +30 LOC — ResolverCandidate, ResolverResult, ResolverSource
├── execute.py              # +60 LOC — branchement opt-in via env var
└── plan.py                 # +4 LOC — as_of.date().isoformat() pour Cypher date()

tests/runtime_a3/
├── test_subject_resolver.py    # NEW (35 tests, mocks complets)
└── test_execute.py             # +30 LOC patch (subject_resolver_enabled=False)
```

### 3.2 Pipeline `SubjectResolver.resolve(user_subject, tenant_id, predicate_hint)`

```
INPUT  user_subject (str), tenant_id, predicate_hint (Optional[str])
  │
  ├─ Step 1 : normalize_canonical_key(user_subject)
  │           ↓ lowercase + NFKC + strip ponctuation + collapse spaces
  │
  ├─ Step 2 : MATCH (e:Entity {tenant_id, normalized_name}) RETURN ... LIMIT 1
  │           ↓ si HIT : enrich via :ABOUT → return ResolverResult(method="exact_normalized", confidence=1.0)
  │           ↓ si MISS : étape 3
  │
  ├─ Step 3 : CALL db.index.fulltext.queryNodes('entity_name_search', $q)
  │           ↓ top-K candidats, score normalisé /max
  │           ↓ si TOP raw_score ≥ FTS_SCORE_THRESHOLD (2.0) : skip étape 4
  │           ↓ sinon : étape 4
  │
  ├─ Step 4 : Qdrant embedding search → top chunks
  │           ↓ pour chaque chunk : MATCH (cl:Claim) WHERE passage_id IN chunks
  │             MATCH (cl)-[:ABOUT]-(e:Entity) → entities mentionnées
  │           ↓ merge candidates FTS + embedding (dedup par entity_id, max score)
  │
  ├─ Step 5 : Re-ranking grapho-sensitif
  │           Pour chaque candidate (avec entity_id) :
  │             enrich via :ABOUT → subject_canonical + n_supporting_claims
  │             si predicate_hint donné et matché : score *= PREDICATE_BOOST (1.2)
  │             si aucun claim trouvé même sans filtre pred : score *= NO_CLAIM_PENALTY (0.3)
  │
  └─ OUTPUT  ResolverResult
              ├ resolved (Optional[str]) — subject_canonical à utiliser dans Cypher
              ├ confidence (float [0,1])
              ├ method ∈ {"exact_normalized", "fts", "fts+rerank", "embedding", "embedding+rerank", "low_confidence", "no_candidates", "empty_input"}
              ├ candidates (List[ResolverCandidate]) — top-5 pour transparence
              ├ abstain_reason (Optional[str])
              └ duration_s (float)
```

### 3.3 Décision finale

```python
if not ranked:                            # aucun candidat après 4 étapes
    method = "no_candidates"
elif top.score < MIN_CONFIDENCE (0.5)     # candidat le mieux scoré reste sous seuil
   or top.subject_canonical is None:      # ou pas de subject_canonical via :ABOUT
    method = "low_confidence"             # → resolved=None (orchestrator abstient ou fallback)
else:
    return resolved = top.subject_canonical
```

## 4. Sub-grounding via `_enrich_with_subject_canonical`

Pour traduire une `:Entity` du KG en `subject_canonical` exploitable par `kg_claims`, on suit `:ABOUT` :

```cypher
MATCH (e:Entity {tenant_id: $tid, entity_id: $eid})-[:ABOUT]-(cl:Claim)
WHERE cl.subject_canonical IS NOT NULL
  AND cl.predicate = $pred              -- optionnel si predicate_hint
WITH e, cl.subject_canonical AS sc, count(cl) AS n
WITH e, sc, n, CASE
  WHEN toLower(sc) = toLower(e.name) THEN 2
  WHEN toLower(sc) CONTAINS toLower(e.name)
    OR toLower(e.name) CONTAINS toLower(sc) THEN 1
  ELSE 0
END AS match_score
ORDER BY match_score DESC, n DESC
LIMIT 1
RETURN sc, n
```

**Critère décisif** : `match_score DESC, n DESC`. Pour l'`:Entity` "SAP Solution Manager", on préfère le `subject_canonical="SAP Solution Manager"` (exact match) à un `subject_canonical="SAP DVM Work Center"` qui aurait `n` plus élevé mais ne nomme pas l'entité.

Fallback : si filtre `predicate` ne donne rien, retry sans filtre et marque `predicate_match=False`.

## 5. Branchement dans `execute.py`

### 5.1 Toggle env var

```python
SUBJECT_RESOLVER_ENABLED = os.getenv("V6_SUBJECT_RESOLVER_ENABLED", "1") == "1"
```

Default ON. Rollback safe en posant la var à `"0"` (pipeline retombe sur le `subject_canonical` brut du Parse, comportement A3.8).

### 5.2 Helper graceful fallback

```python
def _resolve_subject_for_call(tc: ToolCall, subject_param_key: str) -> Optional[str]:
    if not self.subject_resolver_enabled:
        return tc.params.get(subject_param_key)
    user_subj = tc.params.get(subject_param_key)
    if not user_subj:
        return user_subj
    predicate = tc.params.get("predicate")
    result = self._get_subject_resolver().resolve(
        user_subj, tenant_id=tc.params.get("tenant_id", "default"),
        predicate_hint=predicate,
    )
    if result.resolved is not None and result.confidence >= MIN_CONFIDENCE:
        return result.resolved
    # Fallback graceful : on garde le subject brut si résolution échoue
    logger.debug("resolver abstain (%s) — fallback to raw subject %r",
                 result.method, user_subj)
    return user_subj
```

### 5.3 Tools branchés

Resolver appelé avant ces handlers (param remplacé en-place si résolution OK) :
- `kg_claims` (param `subject`)
- `kg_claims_list` (param `subject_filter`)
- `lifecycle_query` (param `subject`)
- `contradiction_surface` (param `subject`)
- `comparison_query` (param `subject`)

## 6. Fix bitemporal collateral : `date()` Cypher function

A3.7-A3.8 utilisaient `datetime(c.valid_from) <= datetime($as_of)`. Or `valid_from` est stocké en string `'2022-01-01'` (date pure, pas ISO datetime) → `datetime()` Cypher raise. Solution :

```cypher
-- AVANT (cassé sur claims réels) :
WHERE c.valid_from IS NULL OR c.valid_from <= datetime($as_of)

-- APRÈS :
WHERE c.valid_from IS NULL OR date(c.valid_from) <= date($as_of)
```

Et côté plan.py, `as_of` passe d'`isoformat()` (datetime) à `date().isoformat()` (`YYYY-MM-DD`) — sinon `date('2026-05-22T00:00:00+00:00')` raise CypherSyntaxError.

Sites patchés (plan.py) : 4 builders (`_build_kg_claims`, `_build_kg_claims_list`, `_build_contradiction_surface`, `_build_comparison_query`).
Sites patchés (execute.py) : 3 templates Cypher (`CYPHER_KG_CLAIMS`, `CYPHER_KG_CLAIMS_LIST`, `CYPHER_CONTRADICTION_SURFACE`).

## 7. Validation

### 7.1 Tests unitaires (35 nouveaux)

`tests/runtime_a3/test_subject_resolver.py` :
- `TestEdgeCases` (3) — empty input, whitespace, no candidates
- `TestExactMatch` (4) — résolution exacte, predicate hint, enrich empty, exception
- `TestFTS` (4) — high score skips embedding, low score triggers, exception, normalization
- `TestEmbedding` (3) — chunk→entity bridge, empty hits, Qdrant exception
- `TestMergeCandidates` (3) — dedup max score, distinct entities, empty
- `TestRerankWithPredicate` (6) — boost, penalty, retry, no-entity-id passthrough, empty, sort
- `TestEnrich` (5) — subject_canonical, predicate filter, retry, fully empty, exception
- `TestResolveEndToEnd` (5) — low_confidence, rerank method, duration, tenant, schema_version
- `TestTopLevelAPI` (1) — `resolve_subject()` injection
- `TestConstants` (1) — sanity

### 7.2 Tests non-régression A3

`tests/runtime_a3/` : **257 passent** (222 existants + 35 nouveaux).

### 7.3 Smoke end-to-end (KG live)

```
Q1 "Labeling Workbench"
  AVANT A3.9 : empty 0 claims, abstention
  APRÈS A3.9 : partial 1 claim
    claim_bfd032f55092 : subj=Labeling Workbench pred=PROCESSES
      val="print requests generated in Global Label Management"

Q2 "team lead role"
  AVANT A3.9 : empty 0 claims, abstention
  APRÈS A3.9 : partial 1 claim
    claim_38338d7cca8d : subj=P_PYD_IAUT (Activity) pred=ENABLES
      val="Team Management application"
```

### 7.4 Bench complet (à venir)

Re-bench A3.8 sous-set 20q post-fix pour mesurer le gain effectif sur les métriques GA3 :
- Coverage `partial+full` (vs `empty`)
- Faithfulness verdict
- Coût latence ajouté (steps 2-5 sur Neo4j+Qdrant)

À planifier comme **bench post-A3.9** dans le sprint Phase A3 final.

## 8. Domain-agnostic check (charte)

✅ Aucun token SAP/médical/légal hardcodé dans le module.
✅ Heuristiques universelles : normalisation lexicale, FTS, embeddings, graphe `:ABOUT`.
✅ Aucun mapping métier (acronymes SAP, codes ESA, etc.) — la normalisation est purement lexicale.
✅ Constants paramétrables (`MIN_CONFIDENCE`, `FTS_SCORE_THRESHOLD`, `NO_CLAIM_PENALTY`, `PREDICATE_BOOST`).
✅ Index Neo4j `entity_name_search` est domain-agnostic (FTS sur nom).

## 9. Limitations connues

1. **Latence** : ajout de 1-4 round-trips Neo4j par tool call (selon étape atteinte). Steps 2-3 typiques < 50ms ; step 4 (embedding) ajoute ~100-300ms.
2. **Dépendance index FTS** : l'index `entity_name_search` doit exister. Création :
   ```cypher
   CREATE FULLTEXT INDEX entity_name_search IF NOT EXISTS
   FOR (e:Entity) ON EACH [e.name, e.aliases]
   ```
3. **`:ABOUT` doit être peuplé** : sans cette relation, l'enrich step 5 ne fonctionne pas. Garanti par le pipeline d'ingestion claim-first.
4. **Pas de cache** : chaque appel `resolve()` exécute le pipeline complet. Cache LRU envisageable en A3.10+ si profiling le justifie.

## 10. Suite

- **Bench post-A3.9** sur 20q sous-set A3.8 — mesure coverage gain
- **A3.10** — Cheap Path déterministe (bypass LLM pour cas simples post-EKX Q3+Q5)
- **Hypothétique A3.11** : cache LRU sur `resolve()` (clé = `normalize_canonical_key(user_subject) + predicate_hint`)

## Références

- `doc/ongoing/POST_A38_FINDINGS_2026-05-21.md` — cause racine A3.8
- `doc/ongoing/EKX_EXCHANGE_2026-05-21.md` — pattern inspirant
- ADR : `doc/architecture/ADR_PARSE_EVALUATE_RUNTIME.md` §6 (subject grounding)
