# Phase 2.8 - Architecture RawAssertion + CanonicalRelation

**Date de création:** 2025-12-21
**Status:** EN COURS - Spécification validée, implémentation à faire
**Priorité:** CRITIQUE (qualité KG domain-agnostic)
**Collaboration:** Claude Code + ChatGPT (validation croisée)

---

## 1. Contexte et Motivation

### 1.1 Problème Actuel

Notre architecture actuelle utilise des **edges Neo4j avec MERGE** :

```cypher
MERGE (source)-[r:REQUIRES]->(target)
SET r = $metadata
```

**Problèmes identifiés :**
- MERGE écrase les occurrences multiples → perte d'information
- Pas d'historique de provenance (quel doc, quel chunk, quel extracteur)
- Fallback `RELATED_TO` détruit le prédicat brut
- Impossible de reconsolider sans ré-ingestion
- Pas d'audit trail

### 1.2 Solution Adoptée

Architecture 2-layer avec **nodes** au lieu d'edges :

1. **RawAssertion** : Journal immuable (append-only) des assertions extraites
2. **CanonicalRelation** : Vue agrégée reconstruite par consolidation batch

---

## 2. Schéma Neo4j

### 2.1 Nodes

#### RawAssertion (append-only, immuable)

```cypher
(:RawAssertion {
  -- Identité
  raw_assertion_id: "ra_01HZYK7P8D3J6Q0V1KX9Y2A3BC",  -- ULID unique
  tenant_id: "default",

  -- Fingerprint pour dédup/idempotence (AJOUT ChatGPT review)
  raw_fingerprint: "sha1:abc123...",  -- hash(tenant|doc|chunk|subject|object|predicate|evidence)

  -- Extraction
  predicate_raw: "requires",  -- Prédicat brut extrait
  predicate_norm: "requires",  -- Normalisé à l'ingestion (AJOUT ChatGPT v2)

  -- Dénormalisation pour ETL perf (AJOUT ChatGPT v2)
  -- Source of truth = edges HAS_SUBJECT/HAS_OBJECT, mais dénormalisé pour queries
  subject_concept_id: "cc_123",
  object_concept_id: "cc_456",
  evidence_text: "NIS2 requires essential entities to implement...",
  evidence_span_start: 0,
  evidence_span_end: 92,
  cross_sentence: false,

  -- Scores
  confidence_extractor: 0.82,
  quality_penalty: 0.0,
  confidence_final: 0.82,

  -- Flags sémantiques
  is_negated: false,
  is_hedged: false,
  is_conditional: false,

  -- Source
  source_doc_id: "enisa_risk_2022",
  source_chunk_id: "qdrant:8b6b0c7e...",
  source_segment_id: "slide_7",
  source_language: "en",

  -- Traçabilité
  extractor_name: "llm_relation_extractor",
  extractor_version: "v0.9.3",
  prompt_hash: "sha256:abc123...",
  model_used: "gpt-4o-mini",
  schema_version: "2.8.0",
  created_at: datetime()
})
```

#### CanonicalRelation (vue reconstruite)

```cypher
(:CanonicalRelation {
  -- Identité (hash stable)
  canonical_relation_id: "cr_a1b2c3d4e5f6",  -- sha1(tenant|subject|type|object)[:16]
  tenant_id: "default",

  -- Relation normalisée
  relation_type: "REQUIRES",  -- Type du vocabulaire contrôlé

  -- IDs concepts (CACHE pour lookups rapides - source of truth = edges RELATES_*)
  -- Ces champs sont écrits UNIQUEMENT par la consolidation batch
  subject_concept_id: "cc_123",
  object_concept_id: "cc_456",

  -- Agrégation
  distinct_documents: 3,
  distinct_chunks: 7,
  total_assertions: 9,
  first_seen_utc: datetime(),
  last_seen_utc: datetime(),
  extractor_versions: ["v0.9.2", "v0.9.3"],

  -- Profil prédicats
  predicate_cluster_id: "pred_cluster_07",
  cluster_label_confidence: 0.88,
  top_predicates_raw: ["requires", "needs", "demands"],

  -- Scores agrégés
  confidence_mean: 0.78,
  confidence_p50: 0.80,
  quality_score: 0.74,

  -- Maturité
  maturity: "CANDIDATE",  -- CANDIDATE | VALIDATED | REJECTED | CONFLICTED
  status: "ACTIVE",  -- ACTIVE | DEPRECATED

  -- Versioning
  mapping_version: "v1.0",
  last_rebuilt_at: datetime()
})
```

### 2.2 Relations (Edges)

```cypher
-- RawAssertion → Concepts
(ra:RawAssertion)-[:HAS_SUBJECT]->(s:CanonicalConcept)
(ra:RawAssertion)-[:HAS_OBJECT]->(o:CanonicalConcept)

-- RawAssertion → CanonicalRelation
(ra:RawAssertion)-[:CONSOLIDATED_INTO]->(cr:CanonicalRelation)

-- CanonicalRelation → Concepts (pour requêtes directes)
(cr:CanonicalRelation)-[:RELATES_FROM]->(s:CanonicalConcept)
(cr:CanonicalRelation)-[:RELATES_TO]->(o:CanonicalConcept)
```

### 2.3 Contraintes et Index

```cypher
-- Contraintes d'unicité
CREATE CONSTRAINT raw_assertion_unique IF NOT EXISTS
FOR (ra:RawAssertion)
REQUIRE (ra.tenant_id, ra.raw_assertion_id) IS UNIQUE;

CREATE CONSTRAINT canonical_relation_unique IF NOT EXISTS
FOR (cr:CanonicalRelation)
REQUIRE (cr.tenant_id, cr.canonical_relation_id) IS UNIQUE;

-- Index pour dédup/idempotence (AJOUT ChatGPT review)
CREATE INDEX raw_assertion_fingerprint_idx IF NOT EXISTS
FOR (ra:RawAssertion) ON (ra.tenant_id, ra.raw_fingerprint);

-- Index composite pour consolidation (AJOUT ChatGPT v2 - CRITIQUE PERF)
CREATE INDEX ra_group_key_idx IF NOT EXISTS
FOR (ra:RawAssertion) ON (ra.tenant_id, ra.subject_concept_id, ra.object_concept_id, ra.predicate_norm);

-- Index de recherche
CREATE INDEX raw_assertion_subject_idx IF NOT EXISTS
FOR (ra:RawAssertion) ON (ra.tenant_id, ra.source_doc_id);

CREATE INDEX raw_assertion_predicate_idx IF NOT EXISTS
FOR (ra:RawAssertion) ON (ra.tenant_id, ra.predicate_norm);

CREATE INDEX canonical_relation_type_idx IF NOT EXISTS
FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.relation_type);

CREATE INDEX canonical_relation_maturity_idx IF NOT EXISTS
FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.maturity);

CREATE INDEX canonical_relation_concepts_idx IF NOT EXISTS
FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.subject_concept_id, cr.object_concept_id);
```

---

## 3. Types de Relations (Vocabulaire Contrôlé)

### 3.1 Types Core (14)

| Type | Description | Usage |
|------|-------------|-------|
| `SUBTYPE_OF` | Hiérarchie taxonomique (is-a) | Ontologie |
| `PART_OF` | Composition, inclusion | Structure |
| `REQUIRES` | Dépendance fonctionnelle | Technique |
| `USES` | Utilisation | Technique |
| `INTEGRATES_WITH` | Intégration système | Technique |
| `EXTENDS` | Extension fonctionnelle | Technique |
| `ENABLES` | Activation de capacité | Capacité |
| `VERSION_OF` | Versionnage | Temporel |
| `PRECEDES` | Séquence temporelle | Temporel |
| `REPLACES` | Remplacement | Temporel |
| `DEPRECATES` | Dépréciation | Temporel |
| `ALTERNATIVE_TO` | Alternative | Variante |
| `APPLIES_TO` | Scope, gouvernance | Réglementaire |
| `CAUSES` | Causalité | Causal |

### 3.2 Types Spéciaux

| Type | Description | Quand |
|------|-------------|-------|
| `UNKNOWN` | Non mappable | Prédicat brut non reconnu |
| `ASSOCIATED_WITH` | Lien faible confirmé | Relation neutre validée |
| `CONFLICTS_WITH` | Contradiction | Assertions opposées |

**IMPORTANT:** `RELATED_TO` n'existe plus comme fallback. Utiliser `UNKNOWN` et conserver `predicate_raw`.

---

## 4. Règles de Consolidation v1

### R1 - Déduplication Raw

Deux RawAssertions sont des doublons si :
- Même `tenant_id`, `source_doc_id`, `source_chunk_id`
- Même `subject_concept_id`, `object_concept_id`
- Même `predicate_raw` normalisé (trim/lower)
- Même `evidence_text` hash

→ Garder 1 seule, log doublon.

### R2 - Grouping Key (2 Niveaux - CLARIFIÉ ChatGPT v2)

**Niveau A (pré-mapping, stable, pour clustering & stats par prédicat)**

Grouper les RawAssertions par :
> `(tenant_id, subject_concept_id, object_concept_id, predicate_norm)`

Objectif :
- Conserver les statistiques et exemples **par prédicat** (debug)
- Permettre clustering/labeling sur `predicate_in_context`
- Éviter de mélanger trop tôt des verbes différents ("requires", "mandates", "imposes")

**Niveau B (post-mapping, pour CanonicalRelation)**

Après mapping `predicate_cluster → relation_type`, faire un rollup par :
> `(tenant_id, subject_concept_id, object_concept_id, relation_type)`

Objectif :
- Obtenir **1 CanonicalRelation** par paire (subject, object) et type normalisé
- Conserver dans la CR un **predicate_profile** (top predicates, cluster IDs)

### R3 - Normalisation Prédicat (Light)

```python
def normalize_predicate(raw: str) -> str:
    return raw.strip().lower().replace("-", " ").replace("_", " ")
```

Ne PAS traduire, ne PAS synonymiser à ce stade.

### R4 - Mapping Type (2 Étages)

**Étape A : Clustering**
- Embedding de `predicate_raw` (e5-base)
- Cluster HDBSCAN ou cosine > 0.85

**Étape B : Labeling**
- LLM labeling par cluster (pas par assertion)
- Cluster → `relation_type` ou `UNKNOWN`

### R5 - Quality Penalties

```python
PENALTIES = {
    "evidence_short": (lambda e: len(e) < 20, -0.20),
    "pronoun_heavy": (lambda e: count_pronouns(e) > 3, -0.15),
    "predicate_generic": (lambda p: p in ["is", "has", "related"], -0.15),
    "cross_sentence": (lambda f: f.get("cross_sentence"), -0.10),
    "negated": (lambda f: f.get("is_negated"), -0.10),
    "concept_generic": (lambda c: is_generic(c), -0.10),
}

GENERIC_TERMS = {
    "en": {"system", "process", "management", "solution", "platform"},
    "fr": {"système", "processus", "gestion", "solution", "plateforme"},
}
```

### R6 - Agrégation Scores

Pour chaque groupe :
- `confidence_mean` = mean(confidence_final)
- `confidence_p50` = percentile(confidence_final, 50)
- `quality_score` = clip(mean(1 + quality_penalty), 0, 1)  # CLIPPING ajouté (ChatGPT review)

### R7 - Diversité Sources

Calculer :
- `distinct_documents` = count(distinct source_doc_id)
- `distinct_chunks` = count(distinct source_chunk_id)

### R8 - Règle Maturité

```python
def compute_maturity(group) -> str:
    # VALIDATED si diversité + confidence
    if group.distinct_documents >= 2 and group.confidence_p50 >= 0.70:
        return "VALIDATED"

    if group.distinct_chunks >= 3 and group.confidence_p50 >= 0.75:
        return "VALIDATED"

    # STRONG_SINGLE : définition explicite
    if (group.total_assertions == 1
        and group.confidence_p50 >= 0.95
        and not group.cross_sentence
        and not group.is_negated
        and not group.is_hedged
        and has_definitional_cue(group.evidence)):
        return "VALIDATED"

    # REJECTED si trop faible
    if group.total_assertions == 1 and group.confidence_final < 0.45:
        return "REJECTED"

    return "CANDIDATE"

DEFINITIONAL_CUES = [
    r"is defined as", r"means", r"refers to", r"désigne", r"définit",
    r"is a type of", r"est un type de", r"consiste en"
]
```

### R9 - Conflits

Si proportion `is_negated > 0.4` pour même groupe :
- `maturity = "CONFLICTED"`
- Créer relation `CONFLICTS_WITH` si types opposés

### R10 - Upsert CanonicalRelation

```cypher
MERGE (cr:CanonicalRelation {
  canonical_relation_id: $cr_id,
  tenant_id: $tenant_id
})
SET cr += {
  relation_type: $type,
  distinct_documents: $distinct_docs,
  distinct_chunks: $distinct_chunks,
  total_assertions: $total,
  confidence_mean: $mean,
  confidence_p50: $p50,
  maturity: $maturity,
  last_rebuilt_at: datetime()
}
```

---

## 5. Migration Progressive

### Phase 1 : Nouveaux Documents (Semaine 1)

1. Implémenter modèles Pydantic `RawAssertion`, `CanonicalRelation`
2. Modifier `llm_relation_extractor.py` pour extraire `predicate_raw` + flags
3. Créer `raw_assertion_writer.py` pour écriture nodes
4. Nouveaux docs → nouveau pipeline

### Phase 2 : Consolidation Batch (Semaine 2)

5. Implémenter `consolidate_relations.py` (R1-R10)
6. Créer contraintes/index Neo4j
7. Tester sur corpus existant

### Phase 3 : Migration Legacy (Optionnel)

8. Script conversion edges → RawAssertions (si besoin historique)
9. Suppression edges legacy après validation

---

## 6. Fichiers à Créer/Modifier

| Fichier | Action | Priorité |
|---------|--------|----------|
| `relations/models.py` | NOUVEAU - RawAssertion, CanonicalRelation | P0 |
| `relations/types.py` | MODIFIER - Ajouter UNKNOWN, APPLIES_TO, CAUSES | P0 |
| `relations/raw_assertion_writer.py` | NOUVEAU - Écriture Neo4j nodes | P0 |
| `relations/llm_relation_extractor.py` | MODIFIER - predicate_raw, flags | P0 |
| `semantic/extraction/prompts.py` | MODIFIER - Prompt extraction élargi | P0 |
| `scripts/consolidate_relations.py` | NOUVEAU - Batch consolidation | P1 |
| `scripts/setup_relation_schema.py` | NOUVEAU - Contraintes/index Neo4j | P1 |
| `api/services/knowledge_graph_service.py` | MODIFIER - Supprimer fallback RELATED_TO | P1 |

---

## 7. Requêtes de Consolidation (v2 - CLARIFIÉ ChatGPT)

### 7.0 IMPORTANT : Pattern Anti-OOM

**RÈGLES STRICTES :**
1. **NE JAMAIS** utiliser `collect(ra)` sur de gros ensembles
2. **NE JAMAIS** utiliser `SKIP` à grande échelle (devient cher)
3. **TOUJOURS** utiliser keyset pagination
4. **TOUJOURS** relier RA→CR par micro-batches

### 7.1 LIST GROUPS (Keyset Pagination) — Niveau A

**But** : Itérer sur tous les groupes (subject_id, object_id, predicate_norm) **sans SKIP**.

**Principe keyset** : Garder un curseur composé (last_subject_id, last_object_id, last_predicate_norm).

```cypher
// 7.1 - LIST GROUPS (keyset, no collect, no SKIP)
// Utilise les champs dénormalisés dans RawAssertion pour perf
MATCH (ra:RawAssertion {tenant_id: $tenant_id})
WITH
  ra.subject_concept_id AS subject_id,
  ra.object_concept_id AS object_id,
  ra.predicate_norm AS predicate_norm
WHERE
  // keyset filter: fetch "after" the last cursor
  (
    $last_subject_id IS NULL OR
    subject_id > $last_subject_id OR
    (subject_id = $last_subject_id AND object_id > $last_object_id) OR
    (subject_id = $last_subject_id AND object_id = $last_object_id AND predicate_norm > $last_predicate_norm)
  )
RETURN DISTINCT subject_id, object_id, predicate_norm
ORDER BY subject_id, object_id, predicate_norm
LIMIT $batch_size
```

**Retour** : liste de groupes + **dernier tuple** comme prochain curseur.

### 7.2 STATS SCALAIRES par Groupe (Niveau A)

**But** : Calculer stats, qualité, diversité pour **un groupe**.

```cypher
// 7.2 - STATS (scalars only) for ONE group
MATCH (ra:RawAssertion {tenant_id: $tenant_id})
WHERE ra.subject_concept_id = $subject_id
  AND ra.object_concept_id = $object_id
  AND ra.predicate_norm = $predicate_norm
RETURN
  count(ra) AS total_assertions,
  count(DISTINCT ra.source_doc_id) AS distinct_docs,
  count(DISTINCT ra.source_chunk_id) AS distinct_chunks,
  avg(ra.confidence_final) AS conf_mean,
  percentileCont(ra.confidence_final, 0.5) AS conf_p50,
  min(ra.created_at) AS first_seen_utc,
  max(ra.created_at) AS last_seen_utc,
  avg(1.0 + ra.quality_penalty) AS quality_mean
```

### 7.3 ASSIGN CLUSTER + LABEL (Python, hors Cypher)

Cette étape est faite **côté Python** :

1. **Construire** `predicate_in_context` :
   ```python
   context = f"{predicate_norm} | subj={subject_name} | obj={object_name}"
   ```

2. **Embedding** de `predicate_in_context` (e5-base ou autre)

3. **Clustering** → `predicate_cluster_id`

4. **Labeling cluster** → `relation_type` (MVP: 5-6 types + UNKNOWN)

5. **Cache** : `mapping_version + predicate_cluster_id → relation_type`

**Sortie** : `predicate_cluster_id`, `relation_type`, `cluster_label_confidence`

### 7.4 ROLLUP (Niveau B) + Upsert CanonicalRelation

#### 7.4a - Upsert CR + edges vers concepts

```cypher
// 7.4a - UPSERT CanonicalRelation + RELATES edges
MATCH (s:CanonicalConcept {tenant_id: $tenant_id, concept_id: $subject_id})
MATCH (o:CanonicalConcept {tenant_id: $tenant_id, concept_id: $object_id})
MERGE (cr:CanonicalRelation {tenant_id: $tenant_id, canonical_relation_id: $cr_id})
SET cr += $cr_props
MERGE (cr)-[:RELATES_FROM]->(s)
MERGE (cr)-[:RELATES_TO]->(o)
```

`$cr_props` contient :
- `relation_type`, `maturity`, `mapping_version`
- `distinct_documents`, `distinct_chunks`, `total_assertions`
- `first_seen_utc`, `last_seen_utc`
- `predicate_cluster_id`, `top_predicates_raw`
- `confidence_mean`, `confidence_p50`, `quality_score`
- `last_rebuilt_at`

#### 7.4b - Link RA → CR (Micro-batches d'IDs)

**RÈGLE** : Ne jamais relier d'un coup toutes les RA. Utiliser micro-batches.

**Étape 1 : Fetch RA ids (keyset)**
```cypher
// Fetch RA ids for one predicate group
MATCH (ra:RawAssertion {tenant_id: $tenant_id})
WHERE ra.subject_concept_id = $subject_id
  AND ra.object_concept_id = $object_id
  AND ra.predicate_norm = $predicate_norm
  AND ($last_ra_id IS NULL OR ra.raw_assertion_id > $last_ra_id)
RETURN ra.raw_assertion_id AS ra_id
ORDER BY ra.raw_assertion_id
LIMIT $micro_batch_size
```

**Étape 2 : Link avec UNWIND**
```cypher
// Link micro-batch RA -> CR
MATCH (cr:CanonicalRelation {tenant_id: $tenant_id, canonical_relation_id: $cr_id})
UNWIND $ra_ids AS ra_id
MATCH (ra:RawAssertion {tenant_id: $tenant_id, raw_assertion_id: ra_id})
MERGE (ra)-[:CONSOLIDATED_INTO]->(cr)
```

### 7.5 Récupérer Exemples d'Evidence (Top 3)

```cypher
// Top 3 evidences pour une CR (après linking)
MATCH (cr:CanonicalRelation {tenant_id: $tenant_id, canonical_relation_id: $cr_id})
      <-[:CONSOLIDATED_INTO]-(ra:RawAssertion)
RETURN ra.raw_assertion_id, ra.evidence_text, ra.source_doc_id, ra.confidence_final
ORDER BY ra.confidence_final DESC
LIMIT 3
```

---

## 8. Flow de Consolidation (Pseudo-code Python)

```python
def consolidate_relations(tenant_id: str, batch_size: int = 100):
    """Flow de consolidation v1 - 6 étapes."""

    # 1. SCAN GROUPS (keyset)
    cursor = (None, None, None)
    while True:
        groups = query_7_1_list_groups(tenant_id, cursor, batch_size)
        if not groups:
            break

        for group in groups:
            # 2. STATS SCALAIRES
            stats = query_7_2_stats(tenant_id, group)

            # 3. ASSIGN CLUSTER (embedding)
            context = f"{group.predicate_norm} | {group.subject_name} | {group.object_name}"
            cluster_id = get_or_assign_cluster(context)

            # 4. LABEL CLUSTER → relation_type
            relation_type = get_cluster_label(cluster_id, mapping_version)

            # Store enriched group for rollup
            enriched_groups.append({**group, **stats, cluster_id, relation_type})

        cursor = (groups[-1].subject_id, groups[-1].object_id, groups[-1].predicate_norm)

    # 5. ROLLUP par (subject, object, relation_type)
    canonical_relations = rollup_by_type(enriched_groups)

    for cr in canonical_relations:
        # 6a. UPSERT CR
        query_7_4a_upsert_cr(tenant_id, cr)

        # 6b. LINK RA → CR (micro-batches)
        for predicate_group in cr.predicate_groups:
            ra_cursor = None
            while True:
                ra_ids = query_7_4b1_fetch_ra_ids(tenant_id, predicate_group, ra_cursor)
                if not ra_ids:
                    break
                query_7_4b2_link_ra_cr(tenant_id, cr.id, ra_ids)
                ra_cursor = ra_ids[-1]
```

---

## 9. Références

- **Discussion technique:** Sessions Claude Code + ChatGPT 2025-12-21
- **Phase parente:** Phase 2.7 - Concept Matching Engine
- **Code actuel:** `src/knowbase/relations/`

---

**Version:** 2.0 (Clarifiée avec keyset pagination + micro-batches)
**Dernière MAJ:** 2025-12-21
**Auteurs:** Claude Code + ChatGPT (validation croisée itérative)
