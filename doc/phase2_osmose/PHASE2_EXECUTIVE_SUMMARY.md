# 🌊 Phase 2 OSMOSE - Intelligence Relationnelle Avancée

**Version:** 1.0
**Date Début:** 2025-10-19 (Semaine 14)
**Durée:** 11 semaines (Semaines 14-24)
**Status:** 🟡 NOT STARTED

---

## 📋 Executive Summary

### Vision Phase 2

> **"De l'extraction intelligente à la compréhension structurée : Transformer le graphe de concepts en tissu sémantique vivant."**

**Objectif Stratégique :**
Enrichir le graphe de connaissances avec des **relations sémantiques typées** et introduire une **intelligence relationnelle** qui dépasse largement les capacités de RAG simple (Microsoft Copilot, Google Gemini).

---

## 🎯 Objectifs Clés

### 1. Relations Sémantiques Typées (Semaines 14-17)

**Problème Actuel :**
- Phase 1.5 génère des concepts canoniques de haute qualité
- Mais relations limitées : principalement co-occurrences basiques
- Graphe Neo4j sous-exploité (peu de edges typés)

**Solution Phase 2 :**

#### 1.1 Relation Extraction Engine

**Taxonomie Finalisée : 12 Types (Validé Claude + OpenAI)**

📐 **STRUCTURELLES** (Hiérarchies & Taxonomies)
- `PART_OF` : Composant → Système parent | *"SAP Fiori" PART_OF "SAP S/4HANA"*
- `SUBTYPE_OF` : Sous-catégorie → Catégorie | *"Cloud ERP" SUBTYPE_OF "ERP System"*

🔗 **DÉPENDANCES** (Fonctionnelles & Techniques)
- `REQUIRES` : Prérequis obligatoire | *"SAP BTP" REQUIRES "SAP Cloud Identity"*
- `USES` : Utilisation optionnelle | *"Dashboard" USES "Analytics SDK"*

🔌 **INTÉGRATIONS** (Connexions Systèmes)
- `INTEGRATES_WITH` : Intégration bidirectionnelle | *"SAP SuccessFactors" INTEGRATES_WITH "SAP S/4HANA"*
- `EXTENDS` ⚠️ **(Phase 2.5 optionnel)** : Extension/Add-on | *"Advanced Analytics" EXTENDS "Base CRM"*

⚡ **CAPACITÉS** (Fonctionnalités Activées)
- `ENABLES` ⚠️ **(Phase 2.5 optionnel)** : Débloque capacité | *"API Platform" ENABLES "Third-Party Ecosystem"*

⏱️ **TEMPORELLES** (Évolution & Cycles de Vie)
- `VERSION_OF` : Relation versionnage | *"CRM v5.2" VERSION_OF "CRM Platform"*
- `PRECEDES` : Succession chronologique | *"Beta Phase" PRECEDES "General Availability"*
- `REPLACES` : Remplacement obsolescence | *"SAP S/4HANA" REPLACES "SAP ECC"*
- `DEPRECATES` : Dépréciation sans remplaçant | *"Roadmap 2025" DEPRECATES "Legacy API v1.x"*

🔄 **VARIANTES** (Alternatives & Compétition)
- `ALTERNATIVE_TO` ⚠️ **(Phase 2.5 optionnel)** : Alternative fonctionnelle | *"SQL Database" ALTERNATIVE_TO "NoSQL Database"*

**Stratégie Implémentation Phasée :**
- **Phase 2 Initial (S14-21)** : 9 types core (⭐⭐ à ⭐⭐⭐ difficulté)
- **Phase 2.5 Optionnel (S22-24)** : 3 types expérimentaux (⭐⭐⭐⭐ difficulté) - **GO si ressources disponibles**

**Référence Complète :** Voir `PHASE2_RELATION_TYPES_REFERENCE.md` (patterns multilingues, exemples 6 domaines, decision trees)

**Méthode d'extraction :**

```python
# Approche hybride : Pattern-based + LLM-assisted

1. Pattern-Based Extraction (Règles linguistiques)
   - Regex patterns : "X is part of Y", "Y includes X"
   - Dependency parsing (spaCy) : Sujet-Verbe-Objet
   - Keyword triggers : "replaces", "requires", "integrates"

2. LLM-Assisted Relation Classification
   - Input : (Concept A, Concept B, Context snippet)
   - Output : {
       "relation_type": "USES|PART_OF|REQUIRES|...",
       "confidence": 0.0-1.0,
       "evidence": "Text snippet justification",
       "directionality": "A→B|B→A|bidirectional"
     }

3. Validation & Confidence Scoring
   - Cross-reference avec ontologie SAP (si disponible)
   - Vérification cohérence (pas de cycles PART_OF)
   - Seuil confidence : 0.75 minimum pour promotion Neo4j
```

**Métriques de Succès :**
- ✅ ≥ 70% concepts ont au moins 1 relation typée
- ✅ Precision relation extraction ≥ 80%
- ✅ Recall relation extraction ≥ 65%
- ✅ < 5% relations incohérentes (cycles, contradictions)

---

### 2. Hierarchical Concept Organization (Semaines 16-18)

**Problème Actuel :**
- Concepts stockés "flat" dans Neo4j
- Pas de hiérarchie Product → Component → Sub-component

**Solution : Taxonomy Builder**

#### 2.1 Auto-Detection Hiérarchies

**Méthode :**

```python
# Exemple : Construire taxonomy SAP Cloud

1. Clustering par domaine (embeddings + K-means)
   → Clusters : [Cloud ERP], [Cloud HCM], [Cloud CRM], [Platform]

2. Détection relations PART_OF hiérarchiques
   - "SAP S/4HANA Cloud" PART_OF "SAP Cloud ERP"
   - "SAP Fiori" PART_OF "SAP S/4HANA Cloud"
   - "SAP Fiori Launchpad" PART_OF "SAP Fiori"

3. Construction arbre taxonomy
   SAP Solutions
   ├── SAP Cloud ERP
   │   └── SAP S/4HANA Cloud
   │       ├── SAP Fiori
   │       │   └── SAP Fiori Launchpad
   │       └── SAP Analytics Cloud
   ├── SAP Cloud HCM
   │   └── SAP SuccessFactors
   └── SAP Business Technology Platform
       ├── SAP HANA Cloud
       └── SAP Integration Suite

4. Validation cohérence
   - Détection cycles (A PART_OF B, B PART_OF A → erreur)
   - Profondeur max hiérarchie : 5 niveaux
   - Ratio feuilles/noeuds intermédiaires : 60/40
```

**Stockage Neo4j :**

```cypher
// Propriétés hiérarchiques sur CanonicalConcept

(:CanonicalConcept {
  canonical_name: "SAP Fiori",
  taxonomy_path: "SAP Solutions > SAP Cloud ERP > SAP S/4HANA Cloud > SAP Fiori",
  hierarchy_level: 3,
  parent_id: "sap-s4hana-cloud",
  children_count: 5
})

// Relations hiérarchiques typées
(child:CanonicalConcept)-[:PART_OF {
  confidence: 0.92,
  source: "extracted|ontology|manual",
  hierarchy_type: "product_component"
}]->(parent:CanonicalConcept)
```

**Métriques de Succès :**
- ✅ ≥ 80% concepts organisés en taxonomy
- ✅ Hiérarchies cohérentes (0 cycles)
- ✅ Profondeur moyenne : 2-4 niveaux
- ✅ Coverage domaines SAP : ERP, HCM, CRM, Platform

---

### 3. Temporal Relation Detection (Semaines 18-20)

**Killer Feature : CRR Evolution Tracker Enhanced**

#### 3.1 Problème Actuel

Phase 1.5 détecte patterns temporels basiques :
- "CCR 2020", "CCR 2021", "CCR 2023" détectés
- Mais relations `EVOLVES_TO` manuelles/basiques

**Limitation :**
Pas de détection automatique **changements structurels** (features ajoutées/supprimées, breaking changes).

#### 3.2 Solution : Temporal Diff Engine

**Fonctionnalités :**

```python
# Détection automatique deltas entre versions

Input:
  - Concept A : "SAP CCR 2020"
  - Concept B : "SAP CCR 2023"
  - Chunks sources : [chunk_ids liés à A, chunk_ids liés à B]

Process:
  1. Extract feature lists (LLM-assisted)
     CCR 2020 features: ["XML format", "Manual validation", "Email submission"]
     CCR 2023 features: ["JSON format", "Auto-validation AI", "API submission", "Email submission"]

  2. Compute diff
     ADDED: ["JSON format", "Auto-validation AI", "API submission"]
     REMOVED: ["XML format", "Manual validation"]
     UNCHANGED: ["Email submission"]

  3. Classify change severity
     - MAJOR: Breaking changes (removed features, API changes)
     - MINOR: Additive changes (new features, no breaking)
     - PATCH: Bug fixes, minor improvements

  4. Create temporal relation
     (CCR_2020)-[:EVOLVES_TO {
       version_delta: "2020→2023",
       change_severity: "MAJOR",
       added_features: ["JSON format", "Auto-validation AI", "API submission"],
       removed_features: ["XML format", "Manual validation"],
       breaking_changes: true,
       migration_effort: "HIGH"
     }]->(CCR_2023)
```

**Use Case Killer :**

**Question Business :**
*"Quels sont les breaking changes entre SAP CCR 2020 et 2025 ?"*

**Réponse OSMOSE :**

```json
{
  "evolution_path": ["CCR_2020", "CCR_2021", "CCR_2023", "CCR_2025"],
  "breaking_changes": [
    {
      "version": "2020→2021",
      "change": "XML format deprecated",
      "impact": "Migration to JSON required",
      "migration_guide_chunk_id": "chunk-456"
    },
    {
      "version": "2021→2023",
      "change": "Manual validation removed",
      "impact": "AI auto-validation mandatory",
      "migration_guide_chunk_id": "chunk-789"
    }
  ],
  "additive_features": [
    {
      "version": "2023→2025",
      "feature": "Blockchain verification",
      "benefit": "Enhanced compliance",
      "documentation_chunk_id": "chunk-1012"
    }
  ],
  "migration_effort_total": "HIGH",
  "estimated_hours": "40-60h developer time"
}
```

**Différenciation vs Copilot :**

| Capability | Microsoft Copilot | OSMOSE Phase 2 |
|------------|-------------------|----------------|
| **Détection versions** | ⚠️ RAG simple (liste mentions) | ✅ Graphe temporel structuré |
| **Delta features** | ❌ Non (réponse générative) | ✅ Diff automatique LLM-assisted |
| **Breaking changes** | ❌ Non détecté | ✅ Classification MAJOR/MINOR/PATCH |
| **Migration effort** | ❌ Non estimé | ✅ Estimation automatique (chunks liés) |
| **Chunks justificatifs** | ⚠️ Citations basiques | ✅ Cross-référence Neo4j ↔ Qdrant |

**Métriques de Succès :**
- ✅ Temporal relations détectées pour ≥ 90% concepts versionnés
- ✅ Precision delta detection ≥ 75%
- ✅ Breaking changes identifiés avec confidence ≥ 0.80

---

### 4. Relation Inference Engine (Semaines 20-22)

**Objectif :** Inférer relations implicites via raisonnement logique

#### 4.1 Transitive Relations

**Règles d'inférence :**

```cypher
// Exemple 1 : PART_OF transitive

SI (A)-[:PART_OF]->(B) ET (B)-[:PART_OF]->(C)
ALORS INFÉRER (A)-[:PART_OF {inferred: true, path: "A→B→C"}]->(C)

Exemple SAP :
  "SAP Fiori Launchpad" PART_OF "SAP Fiori"
  "SAP Fiori" PART_OF "SAP S/4HANA Cloud"
  → INFÉRÉ : "SAP Fiori Launchpad" PART_OF "SAP S/4HANA Cloud"

// Exemple 2 : REQUIRES transitive

SI (A)-[:REQUIRES]->(B) ET (B)-[:REQUIRES]->(C)
ALORS INFÉRER (A)-[:REQUIRES {inferred: true, indirect: true}]->(C)

Exemple SAP :
  "SAP Ariba" REQUIRES "SAP BTP"
  "SAP BTP" REQUIRES "SAP HANA Cloud"
  → INFÉRÉ : "SAP Ariba" REQUIRES "SAP HANA Cloud" (indirect)
```

#### 4.2 Contraintes de Cohérence

**Validation automatique :**

```python
# Détection incohérences logiques

1. Cycles interdits (PART_OF, REQUIRES)
   INVALID: (A)-[:PART_OF]->(B)-[:PART_OF]->(A)

2. Conflits temporels
   INVALID: (A)-[:REPLACES]->(B) ET (B)-[:REPLACES]->(A)

3. Contradictions hiérarchiques
   INVALID: (A)-[:PART_OF]->(B) ET (A)-[:PART_OF]->(C) où B et C même niveau

4. Auto-références
   INVALID: (A)-[:USES]->(A)
```

**Métriques de Succès :**
- ✅ ≥ 30% relations inférées (complément extraction directe)
- ✅ 0 incohérences logiques détectées
- ✅ Validation cohérence exécutée en < 5s pour graphe 10k concepts

---

### 5. Multi-Document Relation Synthesis (Semaines 22-24)

**Problème :** Relations extraites document par document → fragmentation

**Solution : Cross-Document Relation Merger**

#### 5.1 Agrégation Relations Multi-Sources

**Scénario :**

```
Document A (2023) : "SAP S/4HANA uses SAP HANA Database"
  → Relation : (S/4HANA)-[:USES {confidence: 0.85, source_doc: "doc-A"}]->(HANA)

Document B (2024) : "SAP S/4HANA Cloud requires HANA Cloud"
  → Relation : (S/4HANA Cloud)-[:REQUIRES {confidence: 0.90, source_doc: "doc-B"}]->(HANA Cloud)

Document C (2025) : "All S/4HANA deployments depend on HANA"
  → Relation : (S/4HANA)-[:REQUIRES {confidence: 0.92, source_doc: "doc-C"}]->(HANA)
```

**Merger Logic :**

```python
# Consolidation multi-sources

1. Détection relations similaires
   Critères : même (source_concept, target_concept, relation_type_semantic_similar)

2. Agrégation confidence
   - Méthode : Weighted average (docs récents > anciens)
   - Poids : recency_weight = 1.0 / (1 + age_years * 0.2)

3. Merge metadata
   Final relation : (S/4HANA)-[:USES {
     confidence: 0.89,  # Aggregated
     sources: ["doc-A", "doc-B", "doc-C"],
     first_mentioned: "2023-01-15",
     last_mentioned: "2025-10-19",
     mention_count: 3,
     consensus_strength: "HIGH"  # 3 sources concordantes
   }]->(HANA)

4. Conflict resolution
   SI relation_type divergent (USES vs REQUIRES) :
     - Garder les deux avec flag "conflicting: true"
     - Proposer humain validation si confidence proche
     - Favoriser source plus récente si delta confidence > 0.15
```

**Métriques de Succès :**
- ✅ ≥ 60% relations consolidées multi-docs
- ✅ Conflict rate < 8% (relations contradictoires)
- ✅ Consensus strength "HIGH" pour ≥ 70% relations fréquentes

---

## 🏗️ Architecture Technique Phase 2

### Nouveaux Composants

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2 : Relation Intelligence Layer                       │
└─────────────────────────────────────────────────────────────┘
         │
         ├─ RelationExtractionEngine (S14-17)
         │  ├─ PatternBasedExtractor (spaCy dependency parsing)
         │  ├─ LLMRelationClassifier (GPT-4o-mini)
         │  └─ RelationValidator (coherence checks)
         │
         ├─ TaxonomyBuilder (S16-18)
         │  ├─ HierarchyDetector (clustering + PART_OF inference)
         │  ├─ TaxonomyValidator (cycle detection)
         │  └─ TaxonomyVisualizer (Grafana graph view)
         │
         ├─ TemporalDiffEngine (S18-20)
         │  ├─ VersionDetector (regex + NER)
         │  ├─ FeatureDiffAnalyzer (LLM-assisted)
         │  └─ BreakingChangeClassifier (MAJOR/MINOR/PATCH)
         │
         ├─ RelationInferenceEngine (S20-22)
         │  ├─ TransitiveInferencer (Neo4j Cypher rules)
         │  ├─ CoherenceValidator (cycle/conflict detection)
         │  └─ InferenceExplainer (justification chains)
         │
         └─ CrossDocRelationMerger (S22-24)
            ├─ RelationAggregator (multi-source consensus)
            ├─ ConflictResolver (recency + confidence)
            └─ MetadataEnricher (sources, timestamps)
```

### Intégration avec Phase 1.5

**Flux Complet Ingestion + Relations :**

```
Phase 1.5 (OSMOSE Agentique)
  ↓
  Concepts Canoniques dans Neo4j Published
  ↓
Phase 2 (Relation Intelligence)
  ↓
  ┌─ RelationExtractionEngine
  │  → Détecte relations typées (USES, PART_OF, etc.)
  ↓
  ┌─ TaxonomyBuilder
  │  → Organise hiérarchies (Product → Component)
  ↓
  ┌─ TemporalDiffEngine
  │  → Détecte évolutions (EVOLVES_TO + deltas)
  ↓
  ┌─ RelationInferenceEngine
  │  → Infère relations transitives
  ↓
  ┌─ CrossDocRelationMerger
  │  → Consolide multi-sources
  ↓
Neo4j Published KG Enrichi
  - Concepts canoniques (Phase 1.5)
  - Relations typées (Phase 2)
  - Hiérarchies (Phase 2)
  - Timeline évolutions (Phase 2)
  - Relations inférées (Phase 2)
```

---

## 📊 Métriques de Succès Phase 2

### KPIs Techniques

| Métrique | Target | Critique |
|----------|--------|----------|
| **Relations typées / concept** | ≥ 1.5 moyenne | ✅ OUI |
| **Coverage taxonomy** | ≥ 80% concepts | ✅ OUI |
| **Precision relation extraction** | ≥ 80% | ✅ OUI |
| **Recall relation extraction** | ≥ 65% | ⚠️ Nice-to-have |
| **Temporal relations (versioned concepts)** | ≥ 90% | ✅ OUI |
| **Relations inférées** | ≥ 30% total relations | ⚠️ Nice-to-have |
| **Conflict rate** | < 8% | ✅ OUI |
| **Cycles détectés** | 0 | ✅ OUI |

### KPIs Business

| Métrique | Target | Mesure |
|----------|--------|--------|
| **Query "Product dependencies"** | Réponse complète avec hiérarchie | Démo CRR Tracker |
| **Query "Breaking changes X→Y"** | Delta structuré + migration effort | Démo SAP CCR Evolution |
| **Query "All components of X"** | Liste exhaustive via PART_OF transitive | Démo SAP S/4HANA Cloud |
| **Différenciation vs Copilot** | 3+ features uniques démontrables | Slides pitch |

---

## 🚀 Planning Détaillé (11 Semaines)

### Semaines 14-15 : Setup & Relation Extraction Engine

**J1-J3 : Architecture & Design**
- [ ] Design RelationExtractionEngine (API, storage)
- [ ] Définir schema relations Neo4j (propriétés, types)
- [ ] Setup environnement test (corpus 100 docs SAP)

**J4-J7 : Pattern-Based Extraction**
- [ ] Implémenter règles regex (8 types relations)
- [ ] Intégrer spaCy dependency parsing
- [ ] Tests unitaires (precision/recall patterns)

**J8-J10 : LLM-Assisted Classification**
- [ ] Prompt engineering relation classifier
- [ ] Intégration LLMRouter (GPT-4o-mini)
- [ ] Circuit breaker + fallback

**Livrable S15 :**
- ✅ RelationExtractionEngine opérationnel
- ✅ 8 types relations détectés
- ✅ Tests sur corpus 100 docs SAP

---

### Semaines 16-17 : Taxonomy Builder

**J1-J4 : Hierarchy Detection**
- [ ] Clustering domaines (embeddings K-means)
- [ ] Détection PART_OF via patterns + LLM
- [ ] Construction arbre taxonomy

**J5-J7 : Validation & Visualization**
- [ ] Cycle detection (Neo4j Cypher)
- [ ] Profondeur max validation
- [ ] Grafana dashboard taxonomy view

**J8-J10 : Integration Testing**
- [ ] Tests E2E sur corpus SAP Cloud
- [ ] Validation coverage domaines (ERP, HCM, etc.)

**Livrable S17 :**
- ✅ TaxonomyBuilder opérationnel
- ✅ Hiérarchies SAP détectées (ERP, HCM, CRM, Platform)
- ✅ Grafana viz interactive

---

### Semaines 18-19 : Temporal Diff Engine

**J1-J3 : Version Detection**
- [ ] Regex patterns version extraction
- [ ] NER temporal entities
- [ ] Tests détection versions (CCR 2020-2025)

**J4-J7 : Feature Diff Analysis**
- [ ] LLM prompt feature extraction
- [ ] Diff algorithm (added/removed/unchanged)
- [ ] Change severity classifier (MAJOR/MINOR/PATCH)

**J8-J10 : CRR Evolution Tracker Demo**
- [ ] Pipeline E2E CCR 2020→2025
- [ ] Validation breaking changes détectés
- [ ] Documentation use case

**Livrable S19 :**
- ✅ TemporalDiffEngine opérationnel
- ✅ CRR Evolution Tracker fonctionnel
- ✅ Démo breaking changes SAP CCR

---

### Semaines 20-21 : Relation Inference Engine

**J1-J4 : Transitive Inference**
- [ ] Règles Cypher PART_OF transitive
- [ ] Règles Cypher REQUIRES transitive
- [ ] Tests inférence (SAP Fiori → S/4HANA Cloud)

**J5-J7 : Coherence Validation**
- [ ] Détection cycles
- [ ] Détection conflits temporels
- [ ] Auto-correction suggestions

**J8-J10 : Explainability**
- [ ] Justification chains (A→B→C)
- [ ] API explain_relation(A, C)

**Livrable S21 :**
- ✅ RelationInferenceEngine opérationnel
- ✅ ≥ 30% relations inférées
- ✅ 0 incohérences logiques

---

### Semaines 22-24 : Cross-Document Relation Merger & Tests E2E

**J1-J4 : Aggregation Multi-Sources**
- [ ] Relation similarity detector
- [ ] Confidence aggregation (weighted avg)
- [ ] Metadata merger (sources, timestamps)

**J5-J7 : Conflict Resolution**
- [ ] Divergent relation_type handler
- [ ] Recency vs confidence arbitrage
- [ ] Human validation flagging

**J8-J15 : Tests E2E & Validation**
- [ ] Pipeline complet Phase 1.5 + Phase 2
- [ ] Tests sur corpus 500 docs SAP
- [ ] Validation métriques KPIs
- [ ] Démos use cases (CRR, dependencies, taxonomy)

**Livrable S24 (Checkpoint Phase 2) :**
- ✅ CrossDocRelationMerger opérationnel
- ✅ Tous KPIs techniques atteints
- ✅ Démos use cases validées
- ✅ Documentation complète

---

## 🎯 Critères GO/NO-GO Phase 3

**Validation obligatoire Semaine 24 :**

| Critère | Target | Status |
|---------|--------|--------|
| **Relations typées / concept** | ≥ 1.5 | 🟡 |
| **Precision relation extraction** | ≥ 80% | 🟡 |
| **Coverage taxonomy** | ≥ 80% | 🟡 |
| **Temporal relations** | ≥ 90% versioned concepts | 🟡 |
| **Cycles détectés** | 0 | 🟡 |
| **Conflict rate** | < 8% | 🟡 |
| **Démos use cases** | CRR + Taxonomy + Dependencies | 🟡 |

**SI GO :** Passage Phase 3 (Multi-Source & Enrichment)
**SI NO-GO :** Tuning 1-2 semaines + re-test

---

## 💡 Différenciation Competitive Renforcée

### vs Microsoft Copilot

| Feature | Copilot | OSMOSE Phase 2 |
|---------|---------|----------------|
| **Relations typées** | ❌ Non (RAG flat) | ✅ 8+ types (USES, PART_OF, etc.) |
| **Hiérarchies produit** | ❌ Non | ✅ Taxonomy auto-construite |
| **Évolution temporelle** | ⚠️ Mentions basiques | ✅ Delta structuré + breaking changes |
| **Relations inférées** | ❌ Non | ✅ Transitive + coherence validation |
| **Multi-doc synthesis** | ⚠️ RAG simple | ✅ Consensus multi-sources |

### vs Google Gemini

| Feature | Gemini | OSMOSE Phase 2 |
|---------|--------|----------------|
| **Graphe sémantique** | ❌ Non (embeddings only) | ✅ Neo4j structuré |
| **Relation justification** | ⚠️ Générative (hallucinations) | ✅ Chunks sources cross-référencés |
| **Cohérence logique** | ❌ Non garantie | ✅ Validation cycles/conflits |
| **Timeline produit** | ❌ Non | ✅ EVOLVES_TO + migration effort |

---

## 📎 Annexes

### Use Cases Détaillés

#### UC1 : SAP Product Dependencies

**Question :** *"Quelles sont toutes les dépendances de SAP Ariba ?"*

**Réponse OSMOSE Phase 2 :**

```json
{
  "product": "SAP Ariba",
  "dependencies": {
    "direct": [
      {
        "name": "SAP Business Technology Platform",
        "relation_type": "REQUIRES",
        "confidence": 0.92,
        "sources": ["doc-123", "doc-456"]
      },
      {
        "name": "SAP Cloud Identity",
        "relation_type": "REQUIRES",
        "confidence": 0.88,
        "sources": ["doc-789"]
      }
    ],
    "indirect": [
      {
        "name": "SAP HANA Cloud",
        "relation_type": "REQUIRES",
        "confidence": 0.85,
        "inference_path": "SAP Ariba → SAP BTP → SAP HANA Cloud",
        "inferred": true
      }
    ]
  },
  "hierarchy": {
    "parent": "SAP Procurement Solutions",
    "taxonomy_path": "SAP Solutions > SAP Procurement > SAP Ariba"
  }
}
```

#### UC2 : SAP CCR Breaking Changes

**Question :** *"Quels breaking changes entre CCR 2020 et 2025 ?"*

**Réponse OSMOSE Phase 2 :**

```json
{
  "evolution_path": ["CCR_2020", "CCR_2021", "CCR_2023", "CCR_2025"],
  "breaking_changes": [
    {
      "version_from": "CCR_2020",
      "version_to": "CCR_2021",
      "change": "XML format deprecated → JSON required",
      "severity": "MAJOR",
      "migration_effort": "MEDIUM",
      "documentation_chunk_id": "chunk-456",
      "evidence": "All CCR submissions must use JSON format starting Q2 2021..."
    },
    {
      "version_from": "CCR_2021",
      "version_to": "CCR_2023",
      "change": "Manual validation removed → AI auto-validation mandatory",
      "severity": "MAJOR",
      "migration_effort": "HIGH",
      "documentation_chunk_id": "chunk-789",
      "evidence": "AI-powered validation engine replaces manual approval workflow..."
    }
  ],
  "additive_features": [
    {
      "version": "CCR_2023",
      "feature": "Blockchain verification",
      "benefit": "Enhanced compliance",
      "documentation_chunk_id": "chunk-1012"
    }
  ],
  "total_migration_effort": "HIGH (40-60h estimated)",
  "recommendation": "Plan phased migration Q1 2026"
}
```

---

**FIN Phase 2 Executive Summary**
