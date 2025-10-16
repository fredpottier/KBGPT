# ⚠️ Limites et Évolutions - Stratégie Canonicalisation

**Date**: 2025-10-16
**Source**: Peer Review OpenAI + Analyse Architecture
**Contexte**: Enrichissement STRATEGIE_CANONICALISATION_AUTO_APPRENTISSAGE.md

---

## 🎯 Objectif de ce Document

Documenter les **limitations identifiées** dans la stratégie proposée et les **pistes d'amélioration** pour garantir robustesse et scalabilité en production.

---

## 🔴 P0 : Risques Critiques à Adresser (Phase 1.5)

### 1. Pollution Ontologique par Auto-Learning Non Supervisé

**Problème** :
```
Phase B (auto-learning) → LLM batch fusion → OntologySaver automatique
                                                    ↓
                                    Si fusion incorrecte (ex: 2 produits distincts)
                                                    ↓
                              Pollution ontologie → Propagation erreurs futurs imports
```

**Exemple Risque** :
```
Cluster détecté:
├─> "SAP Business One" (ERP PME)
├─> "SAP Business ByDesign" (ERP Cloud PME)
└─> LLM fusionne incorrectement → "SAP Business Solutions"
    ↓
Prochains imports: Tous mappés vers "SAP Business Solutions" (incorrect)
```

**Solution P0** :
```python
# Étape 1: Créer OntologyEntity en mode "pending"
session.run("""
    CREATE (ont:OntologyEntity {
        entity_id: $entity_id,
        canonical_name: $canonical_name,
        status: "auto_learned_pending",  # ← NOUVEAU
        confidence: $confidence,
        created_at: datetime(),
        requires_admin_validation: true
    })
""")

# Étape 2: Utiliser seulement si confiance ≥ 0.95
if confidence >= 0.95:
    ont.status = "auto_learned_validated"
    ont.requires_admin_validation = false
else:
    # Notification admin pour validation
    notify_admin_review_required(ont.entity_id)
```

**Impact** :
- ✅ Ontologie protégée contre fusions hasardeuses
- ✅ Admin valide seulement ~5-10% cas ambigus
- ✅ Historique traçable (audit trail)

**Effort** : 2 jours

---

### 2. Absence de Mécanisme de Correction/Rollback

**Problème** :
Une fois `OntologyEntity` créée et utilisée par 100+ imports, impossible de corriger sans casser la cohérence.

**Exemple** :
```
Import J1-J7: "S/4HANA PCE" → "SAP S/4HANA Cloud Private" (correct)
J8: Admin découvre erreur → Doit corriger en "SAP S/4HANA Cloud, Private Edition"
     ↓
Problème: 200 CanonicalConcepts existants pointent vers ancien nom
```

**Solution P0** :
```cypher
// Relation de versioning
(:OntologyEntity {canonical_name: "SAP S/4HANA Cloud Private", version: "1.0"})
  -[:DEPRECATED_BY {reason: "Official naming", admin: "fred", date: "2025-10-18"}]->
(:OntologyEntity {canonical_name: "SAP S/4HANA Cloud, Private Edition", version: "1.1"})

// Requête avec fallback automatique
MATCH (ont:OntologyEntity {entity_id: $entity_id})
OPTIONAL MATCH (ont)-[:DEPRECATED_BY]->(replacement:OntologyEntity)
RETURN coalesce(replacement.canonical_name, ont.canonical_name) AS canonical_name
```

**API Admin** :
```python
POST /api/admin/ontology/deprecate
{
    "old_entity_id": "S4HANA_CLOUD_PRIVATE",
    "new_canonical_name": "SAP S/4HANA Cloud, Private Edition",
    "reason": "Official naming correction",
    "auto_migrate_concepts": true  # Mettre à jour CanonicalConcepts existants
}
```

**Workflow Migration** :
```cypher
// 1. Créer nouvelle OntologyEntity
CREATE (new:OntologyEntity {
    entity_id: randomUUID(),
    canonical_name: $new_canonical_name,
    version: "1.1",
    created_from_deprecation: true
})

// 2. Lier ancienne → nouvelle
MATCH (old:OntologyEntity {entity_id: $old_entity_id})
CREATE (old)-[:DEPRECATED_BY {
    reason: $reason,
    admin_id: $admin_id,
    deprecated_at: datetime()
}]->(new)

// 3. Migrer tous CanonicalConcepts (si auto_migrate = true)
MATCH (c:CanonicalConcept)-[:BASED_ON]->(old)
MERGE (c)-[:BASED_ON]->(new)
DELETE (c)-[:BASED_ON]->(old)
SET c.canonical_name = $new_canonical_name,
    c.migration_history = c.migration_history + [{
        from: old.canonical_name,
        to: new.canonical_name,
        migrated_at: datetime()
    }]
```

**Impact** :
- ✅ Corrections réversibles
- ✅ Audit trail complet
- ✅ Migration automatique concepts existants
- ✅ Aucune perte de données

**Effort** : 3 jours

---

### 3. Explicabilité et Traçabilité des Décisions

**Problème Actuel** :
```python
# Gatekeeper stocke seulement:
metadata = {
    "normalization_source": "llm:gpt-4o-mini"  # Insuffisant pour audit
}
```

**Besoin** :
Admin voit concept mal canonicalisé → Doit comprendre **pourquoi** cette décision a été prise.

**Solution P0** :
```python
# Stocker score composite et détails décision
decision_trace = {
    "concept_name": "S/4HANA PCE",
    "concept_type": "SOLUTION",
    "strategies_tested": [
        {
            "method": "ontology_lookup",
            "result": "not_found",
            "timestamp": "2025-10-16T14:32:15Z"
        },
        {
            "method": "fuzzy_matching",
            "candidates": [
                {"name": "SAP S/4HANA Cloud Private", "score": 0.87}
            ],
            "best_score": 0.87,
            "threshold": 0.90,
            "result": "below_threshold"
        },
        {
            "method": "llm_canonicalization",
            "model": "gpt-4o-mini",
            "input": "S/4HANA PCE",
            "output": "SAP S/4HANA Cloud, Private Edition",
            "confidence": 0.92,
            "prompt_hash": "a3f5c2...",
            "result": "accepted"
        }
    ],
    "final_decision": {
        "canonical_name": "SAP S/4HANA Cloud, Private Edition",
        "source": "llm:gpt-4o-mini",
        "confidence": 0.92,
        "requires_review": false
    },
    "metadata": {
        "segment_id": "seg_123",
        "document_id": "doc_456",
        "tenant_id": "default"
    }
}

# Stocker dans CanonicalConcept
CREATE (c:CanonicalConcept {
    canonical_id: randomUUID(),
    canonical_name: $canonical_name,
    decision_trace_json: $decision_trace,  # Audit complet
    decision_confidence: 0.92,
    created_at: datetime()
})
```

**Frontend Admin** :
```typescript
// Page: /admin/concepts/:concept_id/audit

interface DecisionTrace {
  concept_name: string;
  strategies_tested: Strategy[];
  final_decision: Decision;
}

<Card title="Decision Audit Trail">
  <Timeline>
    <TimelineItem status="failed">
      [1] Ontology Lookup
      → Result: not_found
    </TimelineItem>
    <TimelineItem status="failed">
      [2] Fuzzy Matching
      → Best: "SAP S/4HANA Cloud Private" (0.87 < 0.90)
    </TimelineItem>
    <TimelineItem status="success">
      [3] LLM Canonicalization (GPT-4o-mini)
      → Output: "SAP S/4HANA Cloud, Private Edition"
      → Confidence: 0.92
    </TimelineItem>
  </Timeline>

  <Actions>
    <Button onClick={approveDecision}>✅ Approve</Button>
    <Button onClick={correctName}>✏️ Correct</Button>
    <Button onClick={reprocessWithDifferentStrategy}>
      🔄 Reprocess
    </Button>
  </Actions>
</Card>
```

**Impact** :
- ✅ Débogage facilité
- ✅ Amélioration continue des seuils
- ✅ Conformité audit/gouvernance
- ✅ Transparence pour admin

**Effort** : 2 jours

---

## 🟡 P1 : Améliorations Recommandées (Phase 2)

### 4. Seuils Adaptatifs par Type d'Entité

**Problème** :
Seuils statiques (`fuzzy ≥ 90`, `embeddings ≥ 0.85`) ne conviennent pas à tous les types.

**Exemple** :
```
Type COMPANY: "Microsoft" vs "Micro Soft" → Fuzzy 0.88 (DOIT matcher)
Type SOLUTION: "S/4HANA" vs "S4 HANA" → Fuzzy 0.88 (DOIT matcher)
Type CONCEPT: "management" vs "manager" → Fuzzy 0.92 (NE DOIT PAS matcher)
```

**Solution P1** :
```python
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

  TECHNOLOGY:
    fuzzy: 0.90
    semantic: 0.85
    llm_required: false

  CONCEPT:
    fuzzy: 0.95  # Plus strict
    semantic: 0.90
    llm_required: false

  default:
    fuzzy: 0.90
    semantic: 0.85
    llm_required: true
```

```python
# Utilisation dans Gatekeeper
def _get_thresholds_for_type(self, concept_type: str) -> Dict[str, float]:
    """Récupère seuils adaptatifs selon type."""
    thresholds = load_yaml("config/canonicalization_thresholds.yaml")
    return thresholds.get(concept_type, thresholds["default"])

# Dans _normalize_concept_auto()
thresholds = self._get_thresholds_for_type(concept_type)

if fuzzy_score >= thresholds["fuzzy"]:
    # Match
```

**Évolution Phase 3** : Apprentissage automatique des seuils via feedback admin.
```python
# Après 100+ validations admin, ajuster seuils automatiquement
feedback_stats = {
    "SOLUTION": {
        "fuzzy_accepted": [0.87, 0.89, 0.91, ...],  # Scores acceptés
        "fuzzy_rejected": [0.82, 0.84, ...]         # Scores rejetés
    }
}

# Calculer seuil optimal (midpoint entre min_accepted et max_rejected)
optimal_threshold = (min(fuzzy_accepted) + max(fuzzy_rejected)) / 2
```

**Impact** : +5-10% précision, moins faux positifs

**Effort** : 1 jour

---

### 5. Similarité Structurelle (Graph Features)

**Problème** :
On n'exploite pas la topologie Neo4j pour détecter synonymes.

**Intuition** :
Si 2 concepts partagent 80% des mêmes documents/segments/topics → Forte probabilité synonymes.

**Exemple** :
```cypher
// Deux concepts avec 80% voisins communs = Probablement synonymes
MATCH (c1:CanonicalConcept {canonical_name: "S/4HANA PCE"})-[:EXTRACTED_FROM]->(d:Document)
MATCH (c2:CanonicalConcept {canonical_name: "SAP S/4HANA Cloud Private"})-[:EXTRACTED_FROM]->(d)
WITH c1, c2, count(d) AS shared_docs

MATCH (c1)-[:EXTRACTED_FROM]->(d1:Document)
WITH c1, c2, shared_docs, count(d1) AS c1_total_docs

MATCH (c2)-[:EXTRACTED_FROM]->(d2:Document)
WITH c1, c2, shared_docs, c1_total_docs, count(d2) AS c2_total_docs

// Jaccard similarity
RETURN c1.canonical_name, c2.canonical_name,
       shared_docs * 1.0 / (c1_total_docs + c2_total_docs - shared_docs) AS jaccard

// Si jaccard ≥ 0.75 → Forte probabilité synonyme
```

**Intégration Phase B (Clustering)** :
```python
def _cluster_similar_concepts(self, concepts: List[Dict]) -> List[Dict]:
    """Clustering via fuzzy + embeddings + graph similarity."""

    clusters = []

    for i, concept_a in enumerate(concepts):
        for concept_b in concepts[i+1:]:
            # Signal 1: Fuzzy textuel
            fuzzy_score = fuzz.ratio(concept_a["name"], concept_b["name"])

            # Signal 2: Semantic embeddings
            semantic_score = cosine_similarity(
                concept_a["embedding"],
                concept_b["embedding"]
            )

            # Signal 3: Structural (graph neighbors)
            structural_score = self.neo4j_client.compute_jaccard_similarity(
                concept_a_id=concept_a["concept_id"],
                concept_b_id=concept_b["concept_id"]
            )

            # Score composite pondéré
            composite_score = (
                0.3 * fuzzy_score +
                0.4 * semantic_score +
                0.3 * structural_score
            )

            if composite_score >= 0.80:
                # Cluster ensemble
                clusters.append({
                    "concepts": [concept_a, concept_b],
                    "scores": {
                        "fuzzy": fuzzy_score,
                        "semantic": semantic_score,
                        "structural": structural_score,
                        "composite": composite_score
                    }
                })

    return clusters
```

**Impact** : +5-10% précision détection synonymes (surtout cas où fuzzy/semantic faibles mais même contexte)

**Effort** : 2 jours

---

### 6. Séparation Normalisation Surface vs Canonicalisation

**Problème** :
On mélange correction orthographique et mapping ontologique.

**Exemple** :
```
Input: "sap s/4 hana pce"
├─ Étape 1 (surface): "sap s/4 hana pce" → "SAP S/4HANA PCE"
└─ Étape 2 (canonical): "SAP S/4HANA PCE" → "SAP S/4HANA Cloud, Private Edition"
```

**Solution P1** :
```python
# Neo4j: Stocker 3 noms distincts
CREATE (c:CanonicalConcept {
    original_name: "sap s/4 hana pce",                    # Brut extraction
    normalized_name: "SAP S/4HANA PCE",                   # Surface normalisé
    canonical_name: "SAP S/4HANA Cloud, Private Edition"  # Ontologie
})

// Index pour matching rapide
CREATE INDEX normalized_name_idx FOR (c:CanonicalConcept) ON (c.normalized_name)
```

**Workflow 2-étapes** :
```python
def canonicalize_concept(self, concept_name: str, concept_type: str):
    """Canonicalisation 2-étapes."""

    # Étape 1: Surface normalization (rapide, règles)
    normalized_name = self._normalize_surface(concept_name)
    # Ex: "sap s/4 hana pce" → "SAP S/4HANA PCE"

    # Étape 2: Canonical lookup (ontologie)
    canonical_name = self._lookup_ontology(normalized_name, concept_type)
    # Ex: "SAP S/4HANA PCE" → "SAP S/4HANA Cloud, Private Edition"

    return {
        "original_name": concept_name,
        "normalized_name": normalized_name,
        "canonical_name": canonical_name
    }

def _normalize_surface(self, name: str) -> str:
    """Normalisation surface (orthographe, casse, accents)."""

    # Règle 1: Acronymes en CAPS
    name = re.sub(r'\b([A-Z]{2,})\b', lambda m: m.group(1).upper(), name)

    # Règle 2: Noms propres (SAP, S/4HANA)
    name = name.title()  # Mais préserver acronymes

    # Règle 3: Normaliser espaces/tirets
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[-_]+', '-', name)

    return name.strip()
```

**Avantages** :
- ✅ Matching lexical rapide sans LLM (index normalized_name)
- ✅ Traçabilité transformations
- ✅ Possibilité rollback surface sans toucher ontologie
- ✅ Séparation concerns (syntaxe vs sémantique)

**Effort** : 1 jour

---

## 🟢 P2 : Évolutions Futures (Phase 3+)

### 7. Embedding Store Dédié (Qdrant Ontology)

**Concept** :
Pré-calculer embeddings de toutes les `OntologyEntity` + aliases dans Qdrant.

**Avantage** :
```python
# Lookup sémantique O(log N) au lieu de O(N)
similar_entities = qdrant_client.search(
    collection_name="ontology_embeddings",
    query_vector=embedding_of_concept,
    limit=5,
    score_threshold=0.85
)

# Résultat: <10ms pour 10,000 entités ontologie
```

**Workflow** :
```
1. OntologySaver → Créer OntologyEntity
2. Async job → Calculer embedding → Stocker dans Qdrant
   Collection: "ontology_embeddings"
   Payload: {entity_id, canonical_name, entity_type, tenant_id}
3. EntityNormalizerNeo4j → Lookup Qdrant AVANT fuzzy matching
```

**Architecture** :
```python
class EntityNormalizerNeo4j:
    def __init__(self, neo4j_driver, qdrant_client):
        self.neo4j_driver = neo4j_driver
        self.qdrant_client = qdrant_client

    def normalize_entity_name(self, raw_name: str, entity_type: str):
        """Normalisation avec Qdrant semantic search."""

        # Étape 1: Calcul embedding
        embedding = self.embedding_model.encode(raw_name)

        # Étape 2: Qdrant semantic search
        qdrant_results = self.qdrant_client.search(
            collection_name="ontology_embeddings",
            query_vector=embedding,
            limit=5,
            score_threshold=0.85,
            query_filter={
                "must": [{"key": "entity_type", "match": {"value": entity_type}}]
            }
        )

        if len(qdrant_results) > 0:
            # Trouvé via sémantique
            best_match = qdrant_results[0]
            entity_id = best_match.payload["entity_id"]

            # Fetch details depuis Neo4j
            return self._get_ontology_entity(entity_id)

        # Étape 3: Fallback Neo4j exact/fuzzy
        return self._neo4j_lookup(raw_name, entity_type)
```

**ROI** :
- ✅ Scalabilité 10,000+ entités ontologie sans ralentissement
- ✅ Lookup <10ms vs 100ms+ (fuzzy O(N))
- ✅ Multilingue native (embeddings)

**Effort** : 3 jours

---

### 8. Reinforcement Learning via Feedback Admin

**Concept** :
Chaque validation/correction admin = Training pair pour fine-tuning modèle embeddings.

**Workflow** :
```python
# Admin corrige canonicalisation
feedback = {
    "input": "S/4HANA PCE",
    "predicted": "SAP S/4HANA Cloud Private",
    "corrected": "SAP S/4HANA Cloud, Private Edition",
    "feedback_type": "incorrect"
}

# Stocker training pair
training_pairs.append({
    "query": "S/4HANA PCE",
    "positive": "SAP S/4HANA Cloud, Private Edition",  # Correct
    "negative": "SAP S/4HANA Cloud Private"           # Incorrect
})

# Fine-tune sentence-transformers tous les 100 feedbacks
if len(training_pairs) >= 100:
    model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    # Triplet loss (query, positive, negative)
    train_dataloader = DataLoader(training_pairs, batch_size=16)

    model.fit(
        train_objectives=[(train_dataloader, losses.TripletLoss(model))],
        epochs=3
    )

    model.save("models/canonicalization-finetuned-v2")

    # Update Qdrant embeddings avec nouveau modèle
    recompute_ontology_embeddings(model)
```

**Impact** :
- ✅ Modèle apprend domaine-specific
- ✅ Réduit dépendance LLM externe (GPT-4o-mini)
- ✅ Amélioration continue qualité

**Effort** : 5 jours

---

### 9. Détection Drift LLM

**Problème** :
LLM peut "dériver" avec le temps (updates OpenAI, hallucinations).

**Solution** :
```python
# config/llm_canonicalization_tests.yaml
canonicalization_tests:
  - input: "S/4HANA PCE"
    expected: "SAP S/4HANA Cloud, Private Edition"
    entity_type: "SOLUTION"

  - input: "ERP"
    expected: "ERP"
    entity_type: "ACRONYM"

  - input: "CRM"
    expected: "CRM"
    entity_type: "ACRONYM"

  - input: "management"
    expected: "UNKNOWN"
    entity_type: "CONCEPT"

# Cron job hebdomadaire
async def test_llm_stability():
    """Test stabilité LLM canonicalization."""

    tests = load_yaml("config/llm_canonicalization_tests.yaml")
    failures = []

    for test in tests:
        result = await llm_canonicalize_single(
            concept_name=test["input"],
            concept_type=test["entity_type"]
        )

        if result != test["expected"]:
            failures.append({
                "input": test["input"],
                "expected": test["expected"],
                "actual": result,
                "drift": "detected"
            })

    if len(failures) > 0:
        # Alerte admin
        send_alert(
            title="⚠️ LLM Drift Detected",
            message=f"{len(failures)}/{len(tests)} tests failed",
            details=failures
        )

        # Logger pour analyse
        logger.error(f"[LLM-DRIFT] {len(failures)} failures: {failures}")
```

**Impact** :
- ✅ Détection précoce dégradation qualité LLM
- ✅ Possibilité rollback vers modèle précédent
- ✅ Conformité qualité production

**Effort** : 1 jour

---

### 10. Gestion Canoniques Hiérarchiques

**Problème** :
Certains concepts ont granularité multiple.

**Exemple** :
```
SAP S/4HANA Cloud (parent)
├─ SAP S/4HANA Cloud, Public Edition (child)
└─ SAP S/4HANA Cloud, Private Edition (child)
    └─ SAP S/4HANA Cloud, Private Edition for Manufacturing (grandchild)
```

**Solution P2** :
```cypher
// Structure hiérarchique
CREATE (parent:OntologyEntity {
    entity_id: "S4HANA_CLOUD",
    canonical_name: "SAP S/4HANA Cloud",
    level: 1
})

CREATE (child_public:OntologyEntity {
    entity_id: "S4HANA_CLOUD_PUBLIC",
    canonical_name: "SAP S/4HANA Cloud, Public Edition",
    level: 2
})

CREATE (child_private:OntologyEntity {
    entity_id: "S4HANA_CLOUD_PRIVATE",
    canonical_name: "SAP S/4HANA Cloud, Private Edition",
    level: 2
})

CREATE (grandchild:OntologyEntity {
    entity_id: "S4HANA_CLOUD_PRIVATE_MFG",
    canonical_name: "SAP S/4HANA Cloud, Private Edition for Manufacturing",
    level: 3
})

// Relations hiérarchiques
CREATE (child_public)-[:IS_VARIANT_OF]->(parent)
CREATE (child_private)-[:IS_VARIANT_OF]->(parent)
CREATE (grandchild)-[:IS_VARIANT_OF]->(child_private)
```

**Query intelligent avec fallback parent** :
```cypher
// Si exact match non trouvé, chercher parent
MATCH (alias:OntologyAlias {normalized: $query})<-[:HAS_ALIAS]-(ont:OntologyEntity)
OPTIONAL MATCH (ont)-[:IS_VARIANT_OF*1..3]->(parent:OntologyEntity)

RETURN
    coalesce(ont.canonical_name, parent.canonical_name) AS canonical_name,
    ont.level AS specificity_level,
    parent.canonical_name AS parent_canonical_name
```

**Impact** :
- ✅ Gestion granularité multiple
- ✅ Requêtes hiérarchiques (parent/child)
- ✅ Compatibilité versions produits

**Effort** : 2 jours

---

## 📋 Matrice Priorisation

| Amélioration | Impact | Effort | Priorité | Phase |
|--------------|--------|--------|----------|-------|
| **Sandbox auto-learning** | 🔴 Critique | 2j | P0 | 1.5 |
| **Mécanisme rollback** | 🔴 Critique | 3j | P0 | 1.5 |
| **Decision trace** | 🔴 Haute | 2j | P0 | 1.5 |
| **Seuils adaptatifs** | 🟡 Moyenne | 1j | P1 | 2.0 |
| **Similarité structurelle** | 🟡 Moyenne | 2j | P1 | 2.0 |
| **Surface vs canonical** | 🟡 Moyenne | 1j | P1 | 2.0 |
| **Embedding store Qdrant** | 🟢 Scalabilité | 3j | P2 | 3.0 |
| **Fine-tuning feedback** | 🟢 Qualité | 5j | P2 | 3.0 |
| **Détection drift LLM** | 🟢 Robustesse | 1j | P2 | 3.0 |
| **Canoniques hiérarchiques** | 🟢 Richesse | 2j | P2 | 3.0 |

---

## ✅ Actions Recommandées Immédiates

### Pour Phase 1.5 (avant prod) :

**Total effort P0** : 7 jours → **Critique pour robustesse production**

1. **Sandbox auto-learning** (2j) - @fred
   - Status `auto_learned_pending` pour OntologyEntity
   - Validation admin pour confiance <0.95
   - Notification admin review required

2. **Mécanisme rollback** (3j) - @fred
   - Relation `DEPRECATED_BY` entre OntologyEntity
   - API admin `/ontology/deprecate`
   - Migration automatique CanonicalConcepts
   - Frontend admin rollback UI

3. **Decision trace enrichie** (2j) - @fred
   - Stocker JSON complet stratégies testées
   - Frontend admin visualiser décisions
   - Alertes canonicalisations low-confidence
   - Actions admin (approve/correct/reprocess)

---

### Pour Phase 2 (post-MVP) :

**Total effort P1** : 4 jours

- Seuils adaptatifs par type (1j)
- Similarité structurelle Neo4j (2j)
- Séparation surface/canonical (1j)

---

### Pour Phase 3 (scaling) :

**Total effort P2** : 11 jours

- Embedding store Qdrant (3j)
- Fine-tuning feedback loop (5j)
- Détection drift LLM (1j)
- Canoniques hiérarchiques (2j)

---

## 🎓 Conclusion

Cette analyse a identifié **3 risques critiques (P0)** à adresser avant production :

1. **Pollution ontologique** → Sandbox + validation différée
2. **Absence correction** → Mécanisme rollback + versioning
3. **Manque explicabilité** → Decision trace + audit trail

**Effort P0 total** : 7 jours développement + 2 jours tests = **9 jours avant prod**

Les améliorations P1/P2 sont **nice-to-have** mais non-bloquantes. Elles peuvent être implémentées progressivement selon retours terrain.

---

**Date création** : 2025-10-16
**Source** : Peer Review OpenAI + Analyse Architecture
**Auteur** : Fred (avec assistance Claude)
**Révision** : -
