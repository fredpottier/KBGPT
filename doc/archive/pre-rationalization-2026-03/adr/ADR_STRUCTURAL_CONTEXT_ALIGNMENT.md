# ADR: Alignement des Identifiants de Contexte Structurel

**Date**: 2026-01-11
**Statut**: Accepted
**Auteurs**: Claude Code + ChatGPT (analyse collaborative)

## Contexte

Lors de l'analyse des performances du Knowledge Graph OSMOSE, nous avons découvert une explosion des relations `MENTIONED_IN` : **2,048,725 relations** pour seulement **18 documents** et **4,012 CanonicalConcepts**.

Investigation menée le 2026-01-11 avec diagnostic complet du graphe Neo4j.

## Problème

### Symptôme observé

| Métrique | Attendu | Réel | Ratio |
|----------|---------|------|-------|
| MENTIONED_IN relations | ~1,000 | 2,048,725 | **2000x** |
| Sections par concept (moyenne) | 2-5 | 655 | **130x** |
| Sections par concept (minimum) | 1 | 49 | - |

### Cause racine : Confusion de deux notions de "section"

Le système confond deux concepts distincts :

| Notion | Source | Stocké dans | Format | Exemple |
|--------|--------|-------------|--------|---------|
| **Cluster textuel** | `hybrid_anchor_chunker` | `ProtoConcept.section_id` | path + cluster | `"7. Save the configuration. / cluster_0"` |
| **Section structurelle** | Docling headings | `SectionContext.context_id` | hash | `"sec_introduction_157409"` |

Ces deux champs **ne sont pas interchangeables** :
- `section_id` = label de clustering sémantique du texte
- `context_id` = identifiant de section dans la hiérarchie documentaire

### Code bugué (`corpus_promotion.py:795-803`)

```python
# Code actuel - BUG
MATCH (p:ProtoConcept ...)
WITH DISTINCT p.document_id AS doc_id      # Prend le document
MATCH (s:SectionContext {doc_id: doc_id})  # TOUTES les sections du doc !
MERGE (cc)-[:MENTIONED_IN]->(s)            # Lie à TOUTES
```

**Comportement** : Chaque `CanonicalConcept` est lié à **toutes** les sections de tous les documents où il apparaît, au lieu des sections spécifiques où il est réellement mentionné.

### Graphe fragmenté

```
ProtoConcept ──ANCHORED_IN──> DocumentChunk (context_id = NULL)
                                    ↓
                              Pas de lien vers DocItem ou SectionContext

DocItem.section_id ═══════════════> SectionContext.context_id  ✓ (match)
     ↑
     └── CONTAINS ── SectionContext
```

Le chemin `ProtoConcept → SectionContext` n'existe pas dans le graphe actuel.

## Conséquences du bug

1. **MENTIONED_IN inutilisable** : 2M de relations fausses polluent le graphe
2. **Pass 3 (Evidence Quote)** : Impossible de trouver les "shared sections" → LLM reçoit tout le document → quotes hors-sujet
3. **Navigation Layer** : Les chemins Concept → Context → Concept sont faux
4. **Performance** : Requêtes lentes sur 2M de relations inutiles

## Décision

### Option retenue : Ajouter `context_id` structurel au ProtoConcept

Lors de l'ingestion Pass 1, quand on ancre un ProtoConcept :

1. Créer `ANCHORED_IN` vers le **DocItem** (pas DocumentChunk)
2. Stocker `proto.context_id = docitem.section_id`

Ceci permet ensuite :
```cypher
-- Pass 2 : MENTIONED_IN sparse et correct
MATCH (p:ProtoConcept)-[:INSTANCE_OF]->(cc:CanonicalConcept)
MATCH (s:SectionContext {context_id: p.context_id})
MERGE (cc)-[r:MENTIONED_IN]->(s)
ON CREATE SET r.mention_count = 1
ON MATCH SET r.mention_count = r.mention_count + 1
```

### Forme choisie : Propriété (pas relation)

- `ProtoConcept.context_id` = `SectionContext.context_id`

Avantages :
- Jointure simple (`p.context_id = s.context_id`)
- Pas d'explosion de relations
- Compatible avec Pass 2/Pass 3

### Conservation de `section_id`

Le champ `ProtoConcept.section_id` (cluster textuel) est **conservé** :
- Utile pour debug et traçabilité
- Peut servir pour clustering intra-section

## Alternatives rejetées

### A. Migration des données existantes

**Rejeté** car :
- `ANCHORED_IN` pointe vers `DocumentChunk` (pas `DocItem`)
- `DocumentChunk.context_id = NULL`
- Les coordonnées char sont dans des référentiels incompatibles (0% de match)
- Le matching textuel serait imprécis (~70%) et risqué

### B. Corriger uniquement `corpus_promotion.py`

**Rejeté** car :
- Sans `context_id` sur ProtoConcept, on ne peut pas savoir quelle section exacte
- On retomberait dans le même problème (fallback sur document_id)

### C. Créer une relation `EXTRACTED_FROM_SECTION`

**Différé** : Possible en complément mais la propriété suffit pour le cas d'usage actuel.

## Plan d'implémentation

### Phase 1 : Correction de l'ingestion

1. Modifier `hybrid_anchor_chunker.py` ou `osmose_persistence.py` :
   - Lors de l'ancrage, récupérer le `DocItem` parent
   - Stocker `context_id = docitem.section_id`

2. Modifier la cible de `ANCHORED_IN` :
   - Option A : `ANCHORED_IN → DocItem` (au lieu de DocumentChunk)
   - Option B : Conserver `DocumentChunk` mais ajouter `context_id` dessus

### Phase 2 : Ré-ingestion complète

1. Purger le graphe actuel (ou restaurer dump vide)
2. Ré-exécuter Pass 0 (Structural Graph) - déjà correct
3. Ré-exécuter Pass 1 avec code corrigé

### Phase 3 : Correction de Pass 2

Modifier `corpus_promotion.py` :

```python
# Code corrigé
def _create_mentioned_in_for_canonical(self, session, canonical_id, proto_ids):
    query = """
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})
    WHERE p.concept_id IN $proto_ids
      AND p.context_id IS NOT NULL

    WITH DISTINCT p.context_id AS ctx_id

    MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
    MATCH (s:SectionContext {context_id: ctx_id, tenant_id: $tenant_id})

    MERGE (cc)-[r:MENTIONED_IN]->(s)
    ON CREATE SET
        r.created_at = datetime(),
        r.mention_count = 1,
        r.source = 'corpus_promotion'
    ON MATCH SET
        r.mention_count = r.mention_count + 1,
        r.updated_at = datetime()

    RETURN count(r) AS created
    """
    # ...
```

### Phase 4 : Correction de Pass 3

Modifier `semantic_consolidation_pass3.py` :

```python
# CandidateGenerator : utiliser context_id au lieu de section_id
co_presence_query = """
MATCH (p1:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c1:CanonicalConcept)
MATCH (p2:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c2:CanonicalConcept)
WHERE c1.canonical_id < c2.canonical_id
  AND p1.context_id = p2.context_id      -- CHANGEMENT : context_id au lieu de section_id
  AND p1.context_id IS NOT NULL
...
```

## Métriques de succès

Après correction :

| Métrique | Avant | Après (attendu) |
|----------|-------|-----------------|
| MENTIONED_IN relations | 2,048,725 | < 5,000 |
| Sections par concept (moyenne) | 655 | 2-5 |
| Pass 3 evidence_quote pertinente | ~20% | > 80% |

## Risques et mitigation

| Risque | Mitigation |
|--------|------------|
| Ré-ingestion longue | Utiliser le cache extraction (data/extraction_cache/) |
| Perte de données | Conserver le dump actuel en backup |
| Régression Pass 2/3/4 | Tests unitaires avant déploiement |

## Implémentation (2026-01-11)

### Fichiers modifiés

| Fichier | Modification |
|---------|--------------|
| `src/knowbase/ingestion/osmose_persistence.py` | `_create_anchored_in_to_coverage()` stocke `context_id` sur ProtoConcept, nouvelle fonction `_update_proto_context_ids()` |
| `src/knowbase/consolidation/corpus_promotion.py` | `_create_mentioned_in_for_canonical()` et `link_corpus_protos_to_canonical()` utilisent `context_id` au lieu de `document_id` |
| `src/knowbase/relations/semantic_consolidation_pass3.py` | `co_presence_query` utilise `context_id` au lieu de `section_id`, `verify_single_candidate()` filtre par `shared_sections` |

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `app/scripts/migrate_context_id.py` | Script de migration pour les données existantes |
| `tests/consolidation/test_structural_context_alignment.py` | Tests unitaires pour l'ADR |

### Commandes de migration

```bash
# Vérifier l'état actuel
docker-compose exec app python scripts/migrate_context_id.py --verify

# Migrer les données existantes (si possible via ANCHORED_IN)
docker-compose exec app python scripts/migrate_context_id.py

# Dry-run
docker-compose exec app python scripts/migrate_context_id.py --dry-run
```

## Références

- Issue initiale : `doc/ongoing/ISSUE_MENTIONED_IN_COVERS.md`
- ADR lex_key : `doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md`
- ADR Structural Graph : `doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md`

## Annexe : Diagnostic complet du graphe (2026-01-11)

### Nodes (18 documents)

| Type | Count | /Doc |
|------|-------|------|
| DocItem | 107,964 | ~6,000 |
| TypeAwareChunk | 14,395 | ~800 |
| ProtoConcept | 11,692 | ~650 |
| SectionContext | 8,332 | ~460 |
| DocumentChunk | 7,823 | ~435 |
| CanonicalConcept | 4,012 | ~223 |
| PageContext | 3,340 | ~185 |
| **TOTAL** | **158,258** | **~8,800** |

### Relations

| Type | Count | Commentaire |
|------|-------|-------------|
| MENTIONED_IN | 2,048,725 | **BUG - 2000x trop** |
| CONTAINS | 107,964 | OK |
| ON_PAGE | 107,964 | OK |
| DERIVED_FROM | 88,214 | OK |
| ANCHORED_IN | 11,624 | OK mais cible DocumentChunk |
| **TOTAL** | **2,410,763** | |

### Distribution MENTIONED_IN par concept

- Min : 49 sections
- Max : 4,634 sections
- Moyenne : 655 sections
- Médiane : 458 sections
