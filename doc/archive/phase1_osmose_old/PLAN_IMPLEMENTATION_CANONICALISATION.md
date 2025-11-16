# 🚀 Plan d'Implémentation - Canonicalisation Auto-Apprenante

**Date Début**: 2025-10-17
**Durée Totale**: 11 jours (P0: 7j + P1: 4j)
**Phase**: 1.5 → 2.0
**Responsable**: @fred

---

## 📋 Vue d'Ensemble

### Priorités

| Priorité | Scope | Effort | Dates | Phase |
|----------|-------|--------|-------|-------|
| **P0 - Critique** | Sandbox + Rollback + Decision Trace | 7j | J17-J23 | 1.5 |
| **P1 - Important** | Seuils + Similarité + Surface/Canonical | 4j | J24-J27 | 2.0 |
| **P2 - Future** | Qdrant + Fine-tuning + Drift + Hiérarchie | 11j | Phase 3+ | 3.0 |

### Objectifs Business

- ✅ **Réduire intervention admin de 80%** (3h → 30min/import)
- ✅ **Protéger ontologie** contre pollution auto-learning
- ✅ **Traçabilité complète** des décisions canonicalisation
- ✅ **Corrections réversibles** via mécanisme rollback
- ✅ **Qualité production** : 96-98% concepts correctement canonicalisés

---

##  🔴 P0 : Implémentation Critique (Jours 17-23 - 7 jours)

### Jour 17-18 : Sandbox Auto-Learning (2j)

**Objectif**: Protéger ontologie contre fusions incorrectes auto-learning

**Tâches**:

#### 1. Modifier OntologyEntity Schema (4h)

```cypher
// Ajouter champs status + validation
CREATE (ont:OntologyEntity {
    entity_id: randomUUID(),
    canonical_name: $canonical_name,
    entity_type: $entity_type,

    // ← NOUVEAUX CHAMPS
    status: "auto_learned_pending",  // ou "auto_learned_validated", "manual"
    confidence: $confidence,          // 0.0-1.0
    requires_admin_validation: true,  // Si confidence < 0.95
    created_by: "auto_learning_batch", // ou "manual", "llm_phase_a"
    validated_by: null,               // admin_id si validé manuellement
    validated_at: null,               // timestamp validation

    created_at: datetime(),
    updated_at: datetime()
})
```

**Fichiers**:
- `src/knowbase/ontology/ontology_saver.py` (lignes 13-110)
- `src/knowbase/ontology/neo4j_schema.py` (nouveau fichier, 150 lignes)

#### 2. Modifier EntityNormalizerNeo4j (2h)

```python
# src/knowbase/ontology/entity_normalizer_neo4j.py

def normalize_entity_name(
    self,
    raw_name: str,
    entity_type_hint: Optional[str] = None,
    tenant_id: str = "default",
    include_pending: bool = False  # ← NOUVEAU param
) -> Tuple[Optional[str], str, Optional[str], bool]:
    """
    Lookup ontologie avec filtrage status.

    Par défaut, exclut status="auto_learned_pending" (non validées).
    """

    query = """
    MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias {
        normalized: $normalized,
        tenant_id: $tenant_id
    })
    WHERE ont.status != 'auto_learned_pending' OR $include_pending = true
    """
```

**Fichiers**:
- `src/knowbase/ontology/entity_normalizer_neo4j.py` (lignes 29-148)

#### 3. Auto-Validation Haute Confiance (2h)

```python
# src/knowbase/ontology/ontology_saver.py

def save_ontology_to_neo4j(
    merge_groups: List[Dict],
    entity_type: str,
    tenant_id: str = "default",
    source: str = "auto_learned"
):
    """Sauvegarde avec auto-validation si confiance ≥ 0.95."""

    for group in merge_groups:
        confidence = group.get("confidence", 0.0)

        # Auto-validation haute confiance
        if confidence >= 0.95:
            status = "auto_learned_validated"
            requires_validation = False
        else:
            status = "auto_learned_pending"
            requires_validation = True

            # Notification admin
            notify_admin_validation_required(
                entity_id=entity_id,
                canonical_name=canonical_name,
                confidence=confidence
            )
```

**Fichiers**:
- `src/knowbase/ontology/ontology_saver.py` (lignes 13-110)
- `src/knowbase/api/services/admin_notifications.py` (nouveau, 80 lignes)

#### 4. Tests Sandbox (4h)

```python
# tests/ontology/test_sandbox_auto_learning.py

def test_auto_validation_high_confidence():
    """OntologyEntity auto-validée si confidence ≥ 0.95."""

def test_pending_low_confidence():
    """OntologyEntity pending si confidence < 0.95."""

def test_normalizer_excludes_pending():
    """EntityNormalizerNeo4j exclut pending par défaut."""

def test_admin_notification_sent():
    """Notification admin si validation requise."""
```

**Livrable Jour 18**:
- ✅ OntologyEntity avec status + confidence
- ✅ Auto-validation confiance ≥ 0.95
- ✅ Notification admin pour validation requise
- ✅ Tests passants (10 tests)

---

### Jours 19-21 : Mécanisme Rollback (3j)

**Objectif**: Corrections réversibles d'ontologies avec migration automatique

**Tâches**:

#### 1. Relation DEPRECATED_BY (4h)

```cypher
// Cypher schema
(:OntologyEntity {canonical_name: "SAP S/4HANA Cloud Private", version: "1.0"})
  -[:DEPRECATED_BY {
      reason: "Official naming correction",
      deprecated_by: "admin_fred",
      deprecated_at: datetime(),
      auto_migrate: true
  }]->
(:OntologyEntity {canonical_name: "SAP S/4HANA Cloud, Private Edition", version: "1.1"})
```

**Fichiers**:
- `src/knowbase/ontology/neo4j_schema.py` (mise à jour)
- `src/knowbase/ontology/ontology_deprecation.py` (nouveau, 200 lignes)

#### 2. API Admin Deprecate (6h)

```python
# src/knowbase/api/routers/admin/ontology.py

@router.post("/api/admin/ontology/deprecate")
async def deprecate_ontology_entity(request: DeprecateEntityRequest):
    """
    Déprécier OntologyEntity et créer remplacement.

    Workflow:
    1. Créer nouvelle OntologyEntity (version++)
    2. Lier ancienne → nouvelle via DEPRECATED_BY
    3. Si auto_migrate=true: Migrer CanonicalConcepts
    4. Logger audit trail
    """

    result = await ontology_deprecation_service.deprecate_entity(
        old_entity_id=request.old_entity_id,
        new_canonical_name=request.new_canonical_name,
        reason=request.reason,
        auto_migrate=request.auto_migrate,
        admin_id=current_user.id
    )

    return result
```

**Fichiers**:
- `src/knowbase/api/routers/admin/ontology.py` (nouveau, 250 lignes)
- `src/knowbase/api/services/ontology_deprecation_service.py` (nouveau, 300 lignes)
- `src/knowbase/api/schemas/ontology.py` (nouveau, 100 lignes)

#### 3. Migration Automatique CanonicalConcepts (6h)

```cypher
// Migrer tous CanonicalConcepts liés à ancienne OntologyEntity
MATCH (old:OntologyEntity {entity_id: $old_entity_id})
MATCH (new:OntologyEntity {entity_id: $new_entity_id})

// Trouver tous CanonicalConcepts basés sur ancienne
MATCH (c:CanonicalConcept)-[r:BASED_ON]->(old)

// Créer lien vers nouvelle
MERGE (c)-[:BASED_ON]->(new)

// Supprimer ancien lien
DELETE r

// Mettre à jour canonical_name
SET c.canonical_name = new.canonical_name,
    c.migration_history = coalesce(c.migration_history, []) + [{
        from: old.canonical_name,
        to: new.canonical_name,
        migrated_at: datetime(),
        reason: $reason,
        admin_id: $admin_id
    }],
    c.updated_at = datetime()

RETURN count(c) AS concepts_migrated
```

**Fichiers**:
- `src/knowbase/common/clients/neo4j_client.py` (ajout méthode migrate_concepts)

#### 4. Frontend Admin Deprecate UI (8h)

```typescript
// frontend/src/app/admin/ontology/[entity_id]/page.tsx

<Card title="Ontology Entity Management">
  <Form onSubmit={handleDeprecate}>
    <Input
      label="New Canonical Name"
      value={newName}
      onChange={setNewName}
    />

    <Textarea
      label="Reason for Change"
      value={reason}
      onChange={setReason}
    />

    <Checkbox
      label="Auto-migrate existing CanonicalConcepts"
      checked={autoMigrate}
      onChange={setAutoMigrate}
    />

    <Button type="submit">
      🔄 Deprecate & Replace
    </Button>
  </Form>

  {result && (
    <Alert variant="success">
      ✅ Deprecated successfully
      - {result.concepts_migrated} concepts migrated
      - New entity_id: {result.new_entity_id}
    </Alert>
  )}
</Card>
```

**Fichiers**:
- `frontend/src/app/admin/ontology/[entity_id]/page.tsx` (nouveau, 200 lignes)
- `frontend/src/lib/api/ontology.ts` (nouveau, 80 lignes)

#### 5. Tests Rollback (6h)

```python
# tests/ontology/test_deprecation.py

def test_deprecate_entity():
    """Créer DEPRECATED_BY relation + nouvelle entity."""

def test_auto_migrate_concepts():
    """Migrer CanonicalConcepts automatiquement."""

def test_migration_history():
    """Stocker migration_history dans CanonicalConcepts."""

def test_rollback_deprecation():
    """Rollback possible (supprimer DEPRECATED_BY)."""
```

**Livrable Jour 21**:
- ✅ Relation DEPRECATED_BY fonctionnelle
- ✅ API `/admin/ontology/deprecate` complète
- ✅ Migration automatique CanonicalConcepts
- ✅ Frontend admin deprecate UI
- ✅ Tests passants (15 tests)

---

### Jours 22-23 : Decision Trace (2j)

**Objectif**: Traçabilité complète décisions canonicalisation pour audit/debug

**Tâches**:

#### 1. Schema Decision Trace (2h)

```python
# src/knowbase/agents/gatekeeper/decision_trace.py

from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class StrategyResult(BaseModel):
    """Résultat d'une stratégie de normalisation."""
    method: str  # "ontology_lookup", "fuzzy_matching", "llm_canonicalization", etc.
    timestamp: str
    result: str  # "found", "not_found", "below_threshold", "accepted", "failed"
    details: Dict[str, Any]  # Scores, candidates, etc.

class DecisionTrace(BaseModel):
    """Trace complète décision canonicalisation."""
    concept_name: str
    concept_type: str
    strategies_tested: List[StrategyResult]
    final_decision: Dict[str, Any]
    metadata: Dict[str, Any]

    def to_json(self) -> str:
        return self.model_dump_json()
```

**Fichiers**:
- `src/knowbase/agents/gatekeeper/decision_trace.py` (nouveau, 150 lignes)

#### 2. Modifier Gatekeeper pour Logger Trace (6h)

```python
# src/knowbase/agents/gatekeeper/gatekeeper.py

def _normalize_concept_auto(
    self,
    concept_name: str,
    concept_type: str,
    tenant_id: str
) -> Tuple[str, bool, str, DecisionTrace]:
    """Normalisation avec decision trace complète."""

    trace = DecisionTrace(
        concept_name=concept_name,
        concept_type=concept_type,
        strategies_tested=[],
        final_decision={},
        metadata={"tenant_id": tenant_id}
    )

    # Stratégie 1: Ontology Lookup
    result = self.entity_normalizer.normalize_entity_name(...)
    trace.strategies_tested.append(StrategyResult(
        method="ontology_lookup",
        timestamp=datetime.now().isoformat(),
        result="found" if result.is_cataloged else "not_found",
        details={"entity_id": result.entity_id, "canonical_name": result.canonical_name}
    ))

    if result.is_cataloged:
        trace.final_decision = {
            "canonical_name": result.canonical_name,
            "source": "ontology",
            "confidence": 1.0
        }
        return (result.canonical_name, True, "ontology", trace)

    # Stratégie 2: Fuzzy Matching
    # ...

    # Return avec trace
    return (canonical_name, is_cataloged, source, trace)
```

**Fichiers**:
- `src/knowbase/agents/gatekeeper/gatekeeper.py` (lignes 392-609 modifiées)

#### 3. Stocker Trace dans Neo4j (2h)

```cypher
// Stocker decision_trace_json dans CanonicalConcept
CREATE (c:CanonicalConcept {
    canonical_id: randomUUID(),
    canonical_name: $canonical_name,
    decision_trace_json: $decision_trace_json,  # JSON string
    decision_confidence: $confidence,
    decision_source: $source,
    created_at: datetime()
})
```

**Fichiers**:
- `src/knowbase/common/clients/neo4j_client.py` (ajout field decision_trace_json)

#### 4. Frontend Admin Decision Audit (6h)

```typescript
// frontend/src/app/admin/concepts/[concept_id]/audit/page.tsx

interface DecisionTrace {
  concept_name: string;
  strategies_tested: StrategyResult[];
  final_decision: Decision;
}

<Card title="Decision Audit Trail">
  <Timeline>
    {trace.strategies_tested.map((strategy, i) => (
      <TimelineItem
        key={i}
        status={strategy.result === 'accepted' ? 'success' : 'failed'}
      >
        [{i+1}] {strategy.method}
        → Result: {strategy.result}
        {strategy.details && (
          <Details>{JSON.stringify(strategy.details, null, 2)}</Details>
        )}
      </TimelineItem>
    ))}
  </Timeline>

  <Actions>
    <Button onClick={approveDecision}>✅ Approve</Button>
    <Button onClick={correctName}>✏️ Correct</Button>
    <Button onClick={reprocessWithStrategy}>
      🔄 Reprocess
    </Button>
  </Actions>
</Card>
```

**Fichiers**:
- `frontend/src/app/admin/concepts/[concept_id]/audit/page.tsx` (nouveau, 250 lignes)

#### 5. Tests Decision Trace (4h)

```python
# tests/agents/test_decision_trace.py

def test_trace_all_strategies():
    """Trace contient toutes stratégies testées."""

def test_trace_stored_neo4j():
    """Decision trace stockée dans Neo4j."""

def test_frontend_displays_trace():
    """Frontend affiche trace correctement."""
```

**Livrable Jour 23**:
- ✅ DecisionTrace Pydantic model
- ✅ Gatekeeper logger trace complète
- ✅ Trace stockée dans Neo4j (decision_trace_json)
- ✅ Frontend admin audit UI
- ✅ Tests passants (10 tests)

---

## 🟡 P1 : Améliorations Important (Jours 24-27 - 4 jours)

### Jour 24 : Seuils Adaptatifs (1j)

**Objectif**: Seuils différents par type d'entité (COMPANY vs SOLUTION vs CONCEPT)

**Tâches**:

#### 1. Configuration YAML (1h)

```yaml
# config/canonicalization_thresholds.yaml
adaptive_thresholds:
  COMPANY:
    fuzzy: 0.88
    semantic: 0.92
    llm_required: false

  SOLUTION:
    fuzzy: 0.85
    semantic: 0.88
    llm_required: true

  PRODUCT:
    fuzzy: 0.87
    semantic: 0.90
    llm_required: true

  CONCEPT:
    fuzzy: 0.95  # Plus strict
    semantic: 0.90
    llm_required: false

  default:
    fuzzy: 0.90
    semantic: 0.85
    llm_required: true
```

#### 2. Intégration Gatekeeper (4h)

```python
def _get_thresholds_for_type(self, concept_type: str) -> Dict[str, Any]:
    """Récupère seuils adaptatifs selon type."""
    thresholds_config = load_yaml("config/canonicalization_thresholds.yaml")
    return thresholds_config.get(concept_type, thresholds_config["default"])

# Dans _normalize_concept_auto()
thresholds = self._get_thresholds_for_type(concept_type)

if fuzzy_score >= thresholds["fuzzy"]:
    # Match accepté
```

#### 3. Tests (3h)

**Livrable Jour 24**: Seuils adaptatifs fonctionnels

---

### Jours 25-26 : Similarité Structurelle (2j)

**Objectif**: Exploiter topologie Neo4j pour détecter synonymes

**Tâches**:

#### 1. Compute Jaccard Similarity (6h)

```cypher
// Similarité Jaccard sur voisins communs
MATCH (c1:CanonicalConcept {canonical_id: $concept_a_id})-[:EXTRACTED_FROM]->(d:Document)
MATCH (c2:CanonicalConcept {canonical_id: $concept_b_id})-[:EXTRACTED_FROM]->(d)
WITH c1, c2, count(d) AS shared_docs

MATCH (c1)-[:EXTRACTED_FROM]->(d1:Document)
WITH c1, c2, shared_docs, count(d1) AS c1_total_docs

MATCH (c2)-[:EXTRACTED_FROM]->(d2:Document)
WITH c1, c2, shared_docs, c1_total_docs, count(d2) AS c2_total_docs

RETURN shared_docs * 1.0 / (c1_total_docs + c2_total_docs - shared_docs) AS jaccard
```

#### 2. Intégration Phase B Clustering (6h)

```python
def _cluster_similar_concepts(self, concepts: List[Dict]) -> List[Dict]:
    """Clustering avec score composite (fuzzy + semantic + structural)."""

    for concept_a, concept_b in combinations(concepts, 2):
        fuzzy_score = fuzz.ratio(concept_a["name"], concept_b["name"])
        semantic_score = cosine_similarity(...)
        structural_score = self.neo4j_client.compute_jaccard_similarity(...)

        composite_score = 0.3*fuzzy + 0.4*semantic + 0.3*structural

        if composite_score >= 0.80:
            cluster_together()
```

#### 3. Tests (4h)

**Livrable Jour 26**: Similarité structurelle intégrée

---

### Jour 27 : Séparation Surface/Canonical (1j)

**Objectif**: Stocker 3 noms (original, normalized, canonical)

**Tâches**:

#### 1. Schema Neo4j (2h)

```cypher
CREATE (c:CanonicalConcept {
    original_name: "sap s/4 hana pce",
    normalized_name: "SAP S/4HANA PCE",
    canonical_name: "SAP S/4HANA Cloud, Private Edition"
})

CREATE INDEX normalized_name_idx FOR (c:CanonicalConcept) ON (c.normalized_name)
```

#### 2. Surface Normalization (3h)

```python
def _normalize_surface(self, name: str) -> str:
    """Normalisation orthographique."""
    # Acronymes en CAPS
    name = re.sub(r'\b([A-Z]{2,})\b', lambda m: m.group(1).upper(), name)
    # Title case
    name = name.title()
    # Espaces/tirets
    name = re.sub(r'\s+', ' ', name)
    return name.strip()
```

#### 3. Tests (3h)

**Livrable Jour 27**: Séparation surface/canonical fonctionnelle

---

## 📊 Récapitulatif Planning

### Phase 1.5 (Jours 17-23 - P0)

| Jour | Tâche | Effort | Status |
|------|-------|--------|--------|
| J17-18 | Sandbox Auto-Learning | 2j | ⏳ TODO |
| J19-21 | Mécanisme Rollback | 3j | ⏳ TODO |
| J22-23 | Decision Trace | 2j | ⏳ TODO |

**Total P0**: 7 jours

### Phase 2.0 (Jours 24-27 - P1)

| Jour | Tâche | Effort | Status |
|------|-------|--------|--------|
| J24 | Seuils Adaptatifs | 1j | ⏳ TODO |
| J25-26 | Similarité Structurelle | 2j | ⏳ TODO |
| J27 | Surface/Canonical | 1j | ⏳ TODO |

**Total P1**: 4 jours

### Phase 3.0 (P2 - Future)

| Tâche | Effort | Phase |
|-------|--------|-------|
| Embedding Store Qdrant | 3j | 3.0 |
| Fine-tuning Feedback | 5j | 3.0 |
| Détection Drift LLM | 1j | 3.0 |
| Canoniques Hiérarchiques | 2j | 3.0 |

**Total P2**: 11 jours

---

## ✅ Critères de Validation

### P0 (Phase 1.5)

- ✅ OntologyEntity avec status (pending/validated)
- ✅ Auto-validation confiance ≥ 0.95
- ✅ Notification admin pour validation requise
- ✅ Relation DEPRECATED_BY fonctionnelle
- ✅ Migration automatique CanonicalConcepts
- ✅ API `/admin/ontology/deprecate` complète
- ✅ Decision trace stockée dans Neo4j
- ✅ Frontend admin audit UI
- ✅ 35 tests passants (10 + 15 + 10)

### P1 (Phase 2.0)

- ✅ Seuils adaptatifs par type chargés depuis YAML
- ✅ Jaccard similarity calculée sur voisins Neo4j
- ✅ Score composite dans clustering Phase B
- ✅ 3 noms stockés (original/normalized/canonical)
- ✅ 15 tests passants (5 + 5 + 5)

---

## 📝 Prochaines Étapes

**Immédiat** (Jour 17):
1. ✅ Créer branche `feat/canonicalization-robustness`
2. ⏳ Commencer P0.1: Sandbox Auto-Learning
3. ⏳ Setup tests infrastructure

**Après P0** (Jour 24):
- Validation terrain avec imports réels
- Analyse feedback admin
- Démarrage P1 si validé

**Après P1** (Phase 3.0):
- Planification P2 selon besoins scalabilité
- Qdrant embedding store si >5,000 entités ontologie

---

**Date Création**: 2025-10-17
**Auteur**: Fred (avec assistance Claude)
**Status**: ⏳ TODO - Prêt à démarrer
