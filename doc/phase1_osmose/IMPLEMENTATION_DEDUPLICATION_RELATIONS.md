# Implémentation Déduplication & Relations Sémantiques

**Phase:** OSMOSE Phase 1.5 - Canonicalisation Robuste
**Date:** 2025-10-16
**Statut:** ✅ Implémentation Complète - En attente de validation E2E

---

## 📋 Contexte

Ce document récapitule l'implémentation des **Problèmes 1 et 2** identifiés dans `ANALYSE_PROBLEMES_NEO4J_CONCEPTS.md`:

- **Problème 2 (P0 - Élevé)**: Concepts dupliqués
- **Problème 1 (P1 - Moyen)**: Relations sémantiques non persistées

---

## ✅ Problème 2 - Déduplication CanonicalConcept

### Symptôme Initial
```cypher
MATCH (c:CanonicalConcept {canonical_name: "Sap"}) RETURN count(c)
-- Résultat: 5 occurrences (DOUBLON!)
```

### Cause Racine
La méthode `promote_to_published()` créait systématiquement un nouveau `CanonicalConcept` sans vérifier l'existence d'un concept avec le même `canonical_name`.

### Solution Implémentée

#### 1. Nouvelle méthode `find_canonical_concept()`

**Fichier:** `src/knowbase/common/clients/neo4j_client.py` (lignes 263-309)

```python
def find_canonical_concept(
    self,
    tenant_id: str,
    canonical_name: str
) -> Optional[str]:
    """
    Chercher un CanonicalConcept existant par nom canonique et tenant.

    Returns:
        canonical_id si trouvé, None sinon
    """
    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id, canonical_name: $canonical_name})
    RETURN c.canonical_id AS canonical_id
    LIMIT 1
    """
    # ... implémentation
```

#### 2. Modification de `promote_to_published()`

**Fichier:** `src/knowbase/common/clients/neo4j_client.py` (lignes 311-464)

**Changements:**
- Nouveau paramètre: `deduplicate: bool = True` (activé par défaut)
- Logique de déduplication:

```python
def promote_to_published(
    self,
    tenant_id: str,
    proto_concept_id: str,
    canonical_name: str,
    unified_definition: str,
    quality_score: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
    decision_trace_json: Optional[str] = None,
    surface_form: Optional[str] = None,
    deduplicate: bool = True  # ⬅️ NOUVEAU
) -> str:
    """
    Problème 2 (Déduplication): Si deduplicate=True (défaut), vérifie si
    un CanonicalConcept existe déjà avec ce canonical_name. Si oui, lie
    le ProtoConcept à l'existant au lieu de créer un doublon.
    """
    # Problème 2: Déduplication - chercher concept existant
    if deduplicate:
        existing_canonical_id = self.find_canonical_concept(tenant_id, canonical_name)

        if existing_canonical_id:
            # Lier ProtoConcept à CanonicalConcept existant
            link_query = """
            MATCH (proto:ProtoConcept {concept_id: $proto_concept_id, tenant_id: $tenant_id})
            MATCH (canonical:CanonicalConcept {canonical_id: $existing_canonical_id, tenant_id: $tenant_id})

            MERGE (proto)-[:PROMOTED_TO {
                promoted_at: datetime(),
                deduplication: true  # ⬅️ Marqueur de déduplication
            }]->(canonical)

            RETURN canonical.canonical_id AS canonical_id
            """
            # Retourner l'ID existant (pas de création)
            return existing_canonical_id

    # Sinon, créer nouveau CanonicalConcept (comportement original)
    # ...
```

### Résultat Attendu

Après rebuild et ingestion d'un nouveau document:

```cypher
-- Avant (avec doublons)
MATCH (c:CanonicalConcept {canonical_name: "Sap"}) RETURN count(c)
-- Résultat: 5

-- Après (dédupliqué)
MATCH (c:CanonicalConcept {canonical_name: "Sap"}) RETURN count(c)
-- Résultat: 1 ✅

-- Vérifier les relations PROMOTED_TO avec deduplication:true
MATCH (proto:ProtoConcept)-[r:PROMOTED_TO]->(canonical:CanonicalConcept {canonical_name: "Sap"})
WHERE r.deduplication = true
RETURN count(proto) AS deduplicated_protos
-- Résultat: >= 4 (les 4 doublons ont été liés à l'existant)
```

---

## ✅ Problème 1 - Persistance Relations Sémantiques

### Symptôme Initial
```cypher
MATCH (c1:CanonicalConcept)-[r:RELATED_TO]->(c2:CanonicalConcept)
RETURN count(r)
-- Résultat: 0 (AUCUNE RELATION!)
```

**Cause:** Le `PatternMiner` détectait les co-occurrences mais ne les persistait jamais dans Neo4j.

### Solution Implémentée

#### 1. Ajout champ `relations` dans `AgentState`

**Fichier:** `src/knowbase/agents/base.py` (ligne 48)

```python
class AgentState(BaseModel):
    # ...
    relations: List[Dict[str, Any]] = Field(default_factory=list)  # ⬅️ NOUVEAU
```

#### 2. PatternMiner stocke les relations

**Fichier:** `src/knowbase/agents/miner/miner.py` (lignes 151-153)

```python
# Problème 1: Stocker relations dans state pour persistance ultérieure
state.relations = link_output.relations
logger.debug(f"[MINER] Stored {len(state.relations)} relations in state for Gatekeeper persistence")
```

**Format des relations:**
```python
{
    "source": "SAP",
    "target": "ERP",
    "type": "CO_OCCURRENCE",
    "segment_id": "segment-1",
    "confidence": 0.7
}
```

#### 3. Gatekeeper construit le mapping `concept_name → canonical_id`

**Fichier:** `src/knowbase/agents/gatekeeper/gatekeeper.py`

**Changements:**

a) **Ligne 519**: Initialisation du mapping
```python
concept_name_to_canonical_id = {}  # Problème 1: Map pour relations
```

b) **Ligne 630**: Stockage du mapping pendant promotion
```python
# Problème 1: Stocker mapping concept_name → canonical_id
concept_name_to_canonical_id[concept_name] = canonical_id
```

c) **Lignes 652-663**: Retour du mapping dans l'output
```python
return PromoteConceptsOutput(
    success=True,
    message=f"Promoted {promoted_count}/{len(concepts)} concepts to Published-KG",
    promoted_count=promoted_count,
    data={
        "promoted_count": promoted_count,
        "failed_count": failed_count,
        "canonical_ids": canonical_ids,
        "concept_name_to_canonical_id": concept_name_to_canonical_id  # ⬅️ NOUVEAU
    }
)
```

#### 4. Gatekeeper persiste les relations dans Neo4j

**Fichier:** `src/knowbase/agents/gatekeeper/gatekeeper.py` (lignes 296-359)

**Logique:**

```python
# Problème 1: Persister relations sémantiques dans Neo4j
if state.relations:
    concept_mapping = promote_result.data.get("concept_name_to_canonical_id", {})
    persisted_count = 0
    skipped_count = 0

    for relation in state.relations:
        source_name = relation.get("source")
        target_name = relation.get("target")

        # Map concept names to canonical_ids
        source_id = concept_mapping.get(source_name)
        target_id = concept_mapping.get(target_name)

        if source_id and target_id:
            # Persister la relation dans Neo4j
            success = self.neo4j_client.create_concept_link(
                tenant_id=state.tenant_id,
                source_concept_id=source_id,
                target_concept_id=target_id,
                relationship_type=relation.get("type", "RELATED_TO"),
                confidence=relation.get("confidence", 0.7),
                metadata={
                    "segment_id": relation.get("segment_id"),
                    "created_by": "pattern_miner"
                }
            )
            if success:
                persisted_count += 1
        else:
            skipped_count += 1  # Concepts non promus

    logger.info(
        f"[GATEKEEPER:Relations] Persistence complete: {persisted_count} relations persisted, "
        f"{skipped_count} skipped"
    )
```

**Gestion des cas limites:**
- ✅ Relations avec concepts non promus → skippées (pas dans le mapping)
- ✅ Erreurs Neo4j → capturées, loggées, mais n'arrêtent pas l'exécution
- ✅ Absence de relations → pas d'appel à `create_concept_link`

### Résultat Attendu

Après rebuild et ingestion:

```cypher
-- Relations créées par PatternMiner
MATCH (c1:CanonicalConcept)-[r:RELATED_TO]->(c2:CanonicalConcept)
RETURN count(r)
-- Résultat: >= 1 ✅

-- Détail des relations
MATCH (c1:CanonicalConcept)-[r:RELATED_TO]->(c2:CanonicalConcept)
RETURN
    c1.canonical_name AS source,
    c2.canonical_name AS target,
    r.type AS type,
    r.confidence AS confidence,
    r.metadata.segment_id AS segment
LIMIT 10
```

**Exemple de résultat:**
| source | target | type | confidence | segment |
|--------|--------|------|------------|---------|
| SAP    | ERP    | CO_OCCURRENCE | 0.7 | segment-1 |
| SAP    | Cloud  | CO_OCCURRENCE | 0.6 | segment-1 |

---

## 🧪 Tests Unitaires

**Fichier:** `tests/agents/test_neo4j_deduplication_relations.py`

**Tests créés:**

### Classe `TestNeo4jDeduplicationLogic`
1. ✅ `test_promote_concepts_tool_creates_mapping` - Vérifie création du mapping
2. ✅ `test_deduplication_calls_find_canonical_concept` - Vérifie appel déduplication
3. ✅ `test_mapping_persists_across_multiple_concepts` - Vérifie accumulation mapping

### Classe `TestSemanticRelationsPersistence`
4. ✅ `test_relations_are_persisted_when_concepts_promoted` - Vérifie persistance
5. ✅ `test_relations_skipped_when_concepts_not_promoted` - Vérifie skip si non promu
6. ✅ `test_relations_persistence_handles_errors_gracefully` - Vérifie gestion erreurs
7. ✅ `test_no_relations_no_error` - Vérifie absence de crash si pas de relations

### Classe `TestRelationsMetadata`
8. ✅ `test_relations_have_required_fields` - Vérifie champs obligatoires
9. ✅ `test_relations_confidence_in_valid_range` - Vérifie confidence ∈ [0, 1]
10. ✅ `test_relations_type_is_valid` - Vérifie types valides

### Classe `TestIntegration`
11. ✅ `test_end_to_end_workflow` - Test E2E complet

**Note:** Les tests utilisent des mocks pour isoler la logique métier de Neo4j. Les tests d'intégration réels valideront le comportement après rebuild.

---

## 📋 Plan de Validation E2E

### Étape 1: Rebuild Worker
```bash
docker-compose build ingestion-worker
docker-compose restart ingestion-worker
```

### Étape 2: Purger Neo4j (optional - reset complet)
```cypher
// Supprimer tous les concepts (DEV seulement!)
MATCH (n:ProtoConcept) DETACH DELETE n;
MATCH (n:CanonicalConcept) DETACH DELETE n;
```

### Étape 3: Ingérer un nouveau document
```bash
# Via interface web ou API
curl -X POST http://localhost:8000/api/ingest/document \
  -H "Content-Type: application/json" \
  -d '{"document_id": "test-dedup", "file_path": "/path/to/doc.pdf"}'
```

### Étape 4: Vérifier les logs

**Logs attendus (Gatekeeper):**

```
[GATEKEEPER:PromoteConcepts] Promotion complete: 15 promoted, 0 failed
[GATEKEEPER:Relations] Starting persistence of 8 relations with 15 canonical concepts
[GATEKEEPER:Relations] Persisted CO_OCCURRENCE relation: SAP → ERP
[GATEKEEPER:Relations] Persisted CO_OCCURRENCE relation: SAP → Cloud
[GATEKEEPER:Relations] Persistence complete: 8 relations persisted, 0 skipped
```

### Étape 5: Vérifier Neo4j

#### Déduplication
```cypher
// Vérifier qu'aucun concept n'a de doublons
MATCH (c:CanonicalConcept)
WITH c.canonical_name AS name, c.tenant_id AS tenant, count(*) AS count
WHERE count > 1
RETURN name, tenant, count
-- Résultat attendu: 0 lignes (aucun doublon)
```

#### Relations
```cypher
// Compter les relations
MATCH (c1:CanonicalConcept)-[r:RELATED_TO]->(c2:CanonicalConcept)
WHERE c1.tenant_id = 'default'
RETURN count(r) AS total_relations
-- Résultat attendu: >= 1
```

```cypher
// Examiner les relations
MATCH (c1:CanonicalConcept)-[r:RELATED_TO]->(c2:CanonicalConcept)
WHERE c1.tenant_id = 'default'
RETURN
    c1.canonical_name AS source,
    c2.canonical_name AS target,
    r.type AS type,
    r.confidence AS confidence,
    r.metadata.created_by AS creator
LIMIT 10
```

**Exemple de résultat attendu:**
| source | target | type | confidence | creator |
|--------|--------|------|------------|---------|
| Sap    | Erp    | CO_OCCURRENCE | 0.7 | pattern_miner |

---

## 📊 Métriques de Succès

| Métrique | Avant | Après (Attendu) |
|----------|-------|-----------------|
| **Doublons CanonicalConcept** | 5 × "Sap" | 1 × "Sap" |
| **Relations RELATED_TO** | 0 | >= 1 (selon document) |
| **Liens PROMOTED_TO avec deduplication:true** | 0 | >= 4 (doublons liés) |
| **Log "[GATEKEEPER:Relations]"** | Absent | Présent avec compteur |

---

## 🔧 Fichiers Modifiés

### Production
1. **`src/knowbase/common/clients/neo4j_client.py`**
   - Lignes 263-309: `find_canonical_concept()`
   - Lignes 311-464: `promote_to_published()` (déduplication)

2. **`src/knowbase/agents/base.py`**
   - Ligne 48: Champ `relations` dans `AgentState`

3. **`src/knowbase/agents/miner/miner.py`**
   - Lignes 151-153: Stockage relations dans state
   - Lignes 282-287: Log persistence

4. **`src/knowbase/agents/gatekeeper/gatekeeper.py`**
   - Ligne 519: Initialisation mapping
   - Ligne 630: Stockage mapping
   - Lignes 652-663: Retour mapping dans output
   - Lignes 296-359: Persistance relations Neo4j

### Tests
5. **`tests/agents/test_neo4j_deduplication_relations.py`** (NOUVEAU)
   - 11 tests unitaires couvrant déduplication + relations

---

## 🚀 Prochaines Étapes

1. ✅ **Implémentation complète** (fait)
2. ✅ **Tests unitaires créés** (fait)
3. ⏳ **Rebuild Worker** (en attente)
4. ⏳ **Validation E2E** (en attente)
5. ⏳ **Analyse métriques Neo4j** (en attente)

---

## 📝 Notes Techniques

### Problème 3 (Canonicalisation naïve)
**Statut:** Déjà résolu par P1.2 (Similarité Structurelle) et P1.3 (Surface/Canonical)
**Pas de travail supplémentaire nécessaire**

### Déduplication vs Merge
- La déduplication **lie** les ProtoConcepts à un CanonicalConcept existant
- Elle **ne fusionne pas** les metadata (conserve la trace de chaque extraction)
- Permet de tracer l'historique: "combien de fois ce concept a été extrait?"

### Relations CO_OCCURRENCE
- Type par défaut: `RELATED_TO` (peut être `CO_OCCURRENCE`, `PART_OF`, etc.)
- Confidence: Score du PatternMiner (par défaut 0.7)
- Metadata: `segment_id` + `created_by: "pattern_miner"`

---

**Auteur:** Claude Code
**Date:** 2025-10-16
**Version:** 1.0
**Statut:** ✅ Implémentation Complète
