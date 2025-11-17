# 🌊 OSMOSE Phase 2 - Tracking Opérationnel

**Version:** 1.0
**Date Création:** 2025-11-16
**Dernière MAJ:** 2025-11-16 22:55
**Status Global:** 🟢 IN PROGRESS - Semaine 14 (25%)

---

## 📊 Vue d'Ensemble

```
Phase 2 : Intelligence Relationnelle Avancée
════════════════════════════════════════════

Durée : 11 semaines (Semaines 14-24)
Progress Global : [█████░░░░░░░░░░░░░░░] 25%

Composants :
├─ 🟢 POC Concept Explainer         : ✅ COMPLÉTÉ (100%)
├─ 🟡 DomainContextPersonalizer     : ⏸️ NOT STARTED (Fondation)
├─ 🟢 RelationExtractionEngine      : 🔄 IN PROGRESS (30%)
├─ 🟡 TaxonomyBuilder               : ⏸️ NOT STARTED
├─ 🟡 TemporalDiffEngine            : ⏸️ NOT STARTED
├─ 🟡 RelationInferenceEngine       : ⏸️ NOT STARTED
└─ 🟡 CrossDocRelationMerger        : ⏸️ NOT STARTED
```

---

## 🎯 KPIs Critiques (GO/NO-GO Phase 3)

| KPI | Target | Actuel | Status |
|-----|--------|--------|--------|
| **Relations typées / concept** | ≥ 1.5 moyenne | - | 🟡 |
| **Coverage taxonomy** | ≥ 80% concepts | - | 🟡 |
| **Precision relation extraction** | ≥ 80% | - | 🟡 |
| **Recall relation extraction** | ≥ 65% | - | 🟡 |
| **Temporal relations** | ≥ 90% versioned concepts | - | 🟡 |
| **Relations inférées** | ≥ 30% total relations | - | 🟡 |
| **Conflict rate** | < 8% | - | 🟡 |
| **Cycles détectés** | 0 | - | 🟡 |

---

## 📅 COMPOSANT 0 : POC Concept Explainer (BONUS)

**Période :** 2025-11-15 → 2025-11-16
**Status :** ✅ **COMPLÉTÉ** (100%)

### Objectif
Valider l'architecture de cross-référencement Neo4j ↔ Qdrant avant la Phase 2 complète.

### Checklist

#### Phase POC
- [x] **Schemas Pydantic** (concepts.py)
  - [x] SourceChunk model
  - [x] RelatedConcept model
  - [x] ConceptExplanation model
  - [x] ConceptExplanationRequest model

- [x] **Service Layer** (concept_explainer_service.py)
  - [x] explain_concept() method
  - [x] Neo4j query for CanonicalConcept
  - [x] Qdrant query via get_chunks_by_concept()
  - [x] Neo4j query for relations

- [x] **API Router** (concepts.py)
  - [x] GET /api/concepts/{id}/explain endpoint
  - [x] JWT authentication integration
  - [x] OpenAPI documentation

- [x] **Integration**
  - [x] Enregistrement router dans main.py
  - [x] Tests Postman validés

#### Bug Fix Gatekeeper
- [x] **Identification bug**
  - [x] CanonicalConcept sans propriétés name/summary
  - [x] Localisation code (neo4j_client.py)

- [x] **Correction code**
  - [x] Ajout name/summary lors création (ligne 553, 557)
  - [x] Backfill COALESCE pour déduplication (ligne 483-485)

- [x] **Migration données**
  - [x] Script migration (migrate_canonical_concepts_names.py)
  - [x] Migration 408 concepts existants
  - [x] Vérification 0 concepts NULL restants

- [x] **Documentation**
  - [x] OSMOSE_PHASE2_POC_CONCEPT_EXPLAINER.md créé
  - [x] Options 3 & 4 documentées (extensions futures)

- [x] **Git Commit**
  - [x] Commit c6f581a créé
  - [x] 7 fichiers (4 nouveaux, 2 modifiés, 1 script)

### Résultats Validés
- ✅ Endpoint testé : GET /api/concepts/{id}/explain
- ✅ Exemple concept "Security" : 12,729 chunks + 10 relations
- ✅ Cross-référence Neo4j ↔ Qdrant fonctionnelle
- ✅ 408 concepts migrés (name/summary backfilled)

### Livrables
- `src/knowbase/api/schemas/concepts.py` (61 lignes)
- `src/knowbase/api/services/concept_explainer_service.py` (308 lignes)
- `src/knowbase/api/routers/concepts.py` (193 lignes)
- `scripts/migrate_canonical_concepts_names.py` (211 lignes)
- `doc/ongoing/OSMOSE_PHASE2_POC_CONCEPT_EXPLAINER.md` (448 lignes)
- `src/knowbase/common/clients/neo4j_client.py` (modifié)
- `src/knowbase/api/main.py` (modifié)

---

## 📅 COMPOSANT 0 bis : DomainContextPersonalizer (FONDATION)

**Période :** Semaine 15 bis (5 jours) - Entre Semaine 15 et 16
**Status :** 🟡 **NOT STARTED**
**Référence :** `doc/ongoing/OSMOSE_PHASE2_DOMAIN_CONTEXT_PERSONALIZER.md`

### Objectif

Permettre aux utilisateurs de **personnaliser le contexte métier** sans compromettre la généricité du moteur.

**Principe :**
- ✅ Code moteur : Domain-agnostic (aucun biais hardcodé)
- ✅ Contexte utilisateur : Domain-specific (personnalisé par tenant)
- ✅ Injection dynamique : Contexte injecté dans prompts LLM

### Checklist Complète

#### ⏸️ Jour 1-2 : Backend Core
- [ ] **DomainContextProfile Pydantic model**
  - [ ] Schema complet (tenant_id, industry, acronyms, etc.)
  - [ ] Validation constraints
  - [ ] JSON schema examples

- [ ] **DomainContextExtractor (LLM-powered)**
  - [ ] Extraction texte libre → profil structuré
  - [ ] Prompt engineering spécialisé
  - [ ] Integration LLMRouter
  - [ ] Tests unitaires extraction

- [ ] **Checkpoint J2**
  - [ ] Tests extraction 3 domaines (SAP, Pharma, Generic)
  - [ ] Validation profils générés

#### ⏸️ Jour 3 : Persistence
- [ ] **DomainContextStore (Neo4j)**
  - [ ] Schema Neo4j (:DomainContextProfile)
  - [ ] Constraints (tenant_id UNIQUE)
  - [ ] Indexes (industry)
  - [ ] CRUD methods (save, get, delete)
  - [ ] Tests persistence

- [ ] **Checkpoint J3**
  - [ ] Tests CRUD Neo4j
  - [ ] Tenant isolation validée

#### ⏸️ Jour 4 : Injection Middleware
- [ ] **DomainContextInjector**
  - [ ] inject_context() method
  - [ ] Format prompt enrichi
  - [ ] Priority handling (low/medium/high)

- [ ] **Integration Composants Existants**
  - [ ] LLMCanonicalizer (Phase 1.5)
  - [ ] LLMRelationExtractor (Phase 2)
  - [ ] Tests injection E2E

- [ ] **Checkpoint J4**
  - [ ] Injection validée dans 2+ composants
  - [ ] Tests avec/sans contexte

#### ⏸️ Jour 5 : API + Frontend
- [ ] **API Routers**
  - [ ] POST /api/domain-context/extract
  - [ ] POST /api/domain-context/save
  - [ ] GET /api/domain-context?tenant_id=xxx
  - [ ] DELETE /api/domain-context?tenant_id=xxx
  - [ ] OpenAPI documentation

- [ ] **Frontend Page `/settings/domain-context`**
  - [ ] Textarea description métier
  - [ ] Button "Générer Profil"
  - [ ] Preview panel profil structuré
  - [ ] Button "Enregistrer"
  - [ ] Tests E2E

- [ ] **Checkpoint J5 (Livrable Semaine 15 bis)**
  - [ ] Feature complète fonctionnelle
  - [ ] Tests E2E 2 scénarios (SAP + Pharma)
  - [ ] Documentation utilisateur

### KPIs Target
- Precision acronyms (avec contexte) : ≥ 95%
- Precision acronyms (sans contexte) : ≥ 70% (baseline)
- Amélioration canonicalization : +15%
- Tenant adoption : ≥ 60% (objectif Phase 3)

### Cas d'Usage Validation

**UC1 : Contexte SAP**
- Input : Description SAP ecosystem
- Test : Import "SAC Overview" → Concept "SAP Analytics Cloud" créé
- Validation : Alias "SAC" présent

**UC2 : Contexte Pharma**
- Input : Description pharma R&D
- Test : Import "API Guidelines" → Concept "Active Pharmaceutical Ingredient" (pas "Application Programming Interface")

**UC3 : Sans Contexte**
- Input : Vide/skip
- Test : Comportement domain-agnostic pur (baseline)

---

## 📅 COMPOSANT 1 : RelationExtractionEngine

**Période :** Semaines 14-15 (10 jours)
**Status :** 🟢 **IN PROGRESS** (30%)
**Référence :** `doc/phases/PHASE2_INTELLIGENCE.md` lignes 486-874

### Objectif
Détecter automatiquement **9 types de relations core** entre concepts canoniques.

**Types relations :**
- **STRUCTURELLES** : PART_OF, SUBTYPE_OF
- **DÉPENDANCES** : REQUIRES, USES
- **INTÉGRATIONS** : INTEGRATES_WITH
- **TEMPORELLES** : VERSION_OF, PRECEDES, REPLACES, DEPRECATES

### Checklist Complète

#### ✅ Jour 1-2 : LLM-First Implementation (FAIT)
- [x] **LLMRelationExtractor** (530 lignes)
  - [x] Extraction LLM avec gpt-4o-mini
  - [x] Co-occurrence pre-filtering
  - [x] 9 types relations supportés
  - [x] Gestion multilingue (EN, FR)
  - [x] Output TypedRelation Pydantic

- [x] **Neo4jRelationshipWriter** (522 lignes)
  - [x] Upsert relations entre CanonicalConcepts
  - [x] Confidence-based update logic
  - [x] Metadata complète (confidence, source_doc, extraction_method)
  - [x] Utility methods (get_relations, delete_relations)

- [x] **Tests Fonctionnels**
  - [x] test_llm_extraction.py (14 tests)
  - [x] test_neo4j_writer.py
  - [x] 20/20 tests passing (100%)

- [x] **Integration Pipeline**
  - [x] Nouvel état FSM : EXTRACT_RELATIONS
  - [x] Lazy loading components
  - [x] Graceful error handling
  - [x] Commits : 5c07333, 6900b7c

- [x] **Optimisations Cache**
  - [x] Hash-based cache (SHA256)
  - [x] Early cache check avant PDF conversion
  - [x] Économies : ~90% temps, $0.15-0.50 par re-import
  - [x] Commit : 2ce2170

#### ⏳ Jour 3 : Architecture & Design (EN COURS)
- [ ] **Design RelationExtractionEngine class**
  - [ ] API methods définies
  - [ ] Output schema TypedRelation finalisé
  - [ ] Neo4j relation properties schema documenté

- [ ] **Corpus Test Setup**
  - [ ] Sélection 100 docs multi-domaines
    - [ ] 40% Software (SAP)
    - [ ] 20% Pharma
    - [ ] 20% Retail
    - [ ] 10% Manufacturing
    - [ ] 10% Other
  - [ ] Annotation manuelle Gold Standard
    - [ ] 50 relations × 9 types = 450 relations totales

- [ ] **Checkpoint J3**
  - [ ] Design validé et documenté
  - [ ] Corpus test prêt
  - [ ] Gold standard annoté

#### ⏸️ Jour 4-7 : Pattern-Based Extraction
- [ ] **J4 : Règles regex multilingues**
  - [ ] Patterns PART_OF (EN, FR, DE, ES)
  - [ ] Patterns SUBTYPE_OF
  - [ ] Patterns REQUIRES
  - [ ] Patterns USES
  - [ ] Patterns INTEGRATES_WITH
  - [ ] Patterns VERSION_OF
  - [ ] Patterns PRECEDES
  - [ ] Patterns REPLACES
  - [ ] Patterns DEPRECATES
  - [ ] **Référence :** `doc/ongoing/PHASE2_RELATION_TYPES_REFERENCE.md`

- [ ] **J5 : spaCy Dependency Parsing**
  - [ ] Extraction triplets Sujet-Verbe-Objet
  - [ ] Mapping verbes → relation types (9 familles)
  - [ ] Tests parsing multilingue

- [ ] **J6 : Tests Unitaires Patterns**
  - [ ] Precision ≥ 70% (pattern-based seul)
  - [ ] Recall ≥ 50%
  - [ ] Tests par type relation

- [ ] **J7 : Decision Trees**
  - [ ] PART_OF vs SUBTYPE_OF disambiguation
  - [ ] REQUIRES vs USES disambiguation
  - [ ] Gestion négations
  - [ ] Support multi-langues

- [ ] **Checkpoint J7**
  - [ ] Pattern-based extractor functional
  - [ ] KPIs atteints (Precision ≥ 70%, Recall ≥ 50%)

#### ⏸️ Jour 8-10 : Hybrid Extraction (Patterns + LLM)
- [ ] **J8 : Prompt Engineering**
  - [ ] Input schema (Concept A, Concept B, Context)
  - [ ] Output schema (relation_type, confidence, evidence, directionality)
  - [ ] Temperature 0.0 (déterministe)
  - [ ] Tests prompt variations

- [ ] **J9 : LLMRouter Integration**
  - [ ] TaskType.RELATION_CLASSIFICATION
  - [ ] Model gpt-4o-mini
  - [ ] Circuit breaker configuration
  - [ ] Fallback pattern-based

- [ ] **J10 : Tests E2E Hybrid**
  - [ ] Precision ≥ 80%
  - [ ] Recall ≥ 65%
  - [ ] Cost validation ≤ $0.05 per 100 relations
  - [ ] Tests sur corpus 100 docs

- [ ] **Checkpoint J10 (Livrable Semaine 15)**
  - [ ] RelationExtractionEngine opérationnel
  - [ ] KPIs techniques atteints
  - [ ] Documentation technique complète
  - [ ] Code review + optimisations

### Métriques Actuelles
- ✅ Code produit : 1,052 lignes (extractor + writer)
- ✅ Tests : 20 tests (100% passing)
- ✅ Types relations : 9 core supportés
- ✅ Model LLM : gpt-4o-mini
- ⏳ Precision : À mesurer sur corpus test
- ⏳ Recall : À mesurer sur corpus test
- ⏳ Cost : À mesurer

### Décisions Techniques
1. **LLM-First approach** : Meilleure précision (+30-40% vs patterns seuls)
2. **Co-occurrence pre-filtering** : Réduction 70% calls LLM
3. **Upsert confidence-based** : Permet consolidation multi-sources futures
4. **Integration non-bloquante** : Erreur extraction n'arrête pas pipeline

---

## 📅 COMPOSANT 2 : TaxonomyBuilder

**Période :** Semaines 16-17 (10 jours)
**Status :** 🟡 **NOT STARTED**
**Référence :** `doc/phases/PHASE2_INTELLIGENCE.md` lignes 876-939

### Objectif
Organiser concepts en hiérarchies produit (Product → Component → Sub-component).

### Checklist Complète

#### ⏸️ Jour 1-4 : Hierarchy Detection
- [ ] **J1 : Clustering domaines**
  - [ ] Modèle embeddings : sentence-transformers/all-MiniLM-L6-v2
  - [ ] K-means : K=10 (ERP, HCM, CRM, Platform, etc.)
  - [ ] Validation silhouette score ≥ 0.5

- [ ] **J2 : Détection PART_OF hiérarchiques**
  - [ ] Regex patterns : "component of", "module of"
  - [ ] LLM classification (A PART_OF B ?)

- [ ] **J3 : Construction arbre taxonomy**
  - [ ] Algorithme bottom-up clustering
  - [ ] Max depth : 5 niveaux
  - [ ] Ratio feuilles/noeuds : 60/40

- [ ] **J4 : Tests hiérarchies SAP Cloud**
  - [ ] Validation coverage domaines
  - [ ] Vérification cohérence (pas cycles)

- [ ] **Checkpoint J4**
  - [ ] Hiérarchies SAP détectées
  - [ ] Coverage ≥ 80% concepts

#### ⏸️ Jour 5-7 : Validation & Visualization
- [ ] **J5 : Cycle detection**
  - [ ] Query Neo4j : MATCH (a)-[:PART_OF*]->(a)
  - [ ] Auto-correction : Supprimer edge plus faible confidence

- [ ] **J6 : Profondeur max validation**
  - [ ] Alert si depth > 5
  - [ ] Suggest flattening sur-hiérarchies

- [ ] **J7 : Grafana dashboard**
  - [ ] Graphe interactif (Cytoscape.js)
  - [ ] Drill-down par domaine
  - [ ] Stats : depth, width, coverage

- [ ] **Checkpoint J7**
  - [ ] Validation automatique functional
  - [ ] Grafana viz opérationnelle

#### ⏸️ Jour 8-10 : Integration Testing
- [ ] **J8-J9 : Tests E2E corpus SAP Cloud**
  - [ ] 500 concepts testés
  - [ ] Validation hiérarchies ERP, HCM, CRM, Platform
  - [ ] Vérification PART_OF transitive inférées

- [ ] **J10 : Documentation & démo**
  - [ ] Use case : "All components of SAP S/4HANA Cloud"
  - [ ] Code review + optimization

- [ ] **Checkpoint J10 (Livrable Semaine 17)**
  - [ ] TaxonomyBuilder production-ready
  - [ ] Grafana dashboard déployé
  - [ ] Tests E2E passés

### KPIs Target
- ≥ 80% concepts organisés en taxonomy
- Hiérarchies cohérentes (0 cycles)
- Profondeur moyenne : 2-4 niveaux
- Coverage domaines SAP : ERP, HCM, CRM, Platform

---

## 📅 COMPOSANT 3 : TemporalDiffEngine

**Période :** Semaines 18-19 (10 jours)
**Status :** 🟡 **NOT STARTED**
**Référence :** `doc/phases/PHASE2_INTELLIGENCE.md` lignes 941-1005

### Objectif
**Killer Feature : CRR Evolution Tracker Enhanced**
Détection automatique changements structurels entre versions.

### Checklist Complète

#### ⏸️ Jour 1-3 : Version Detection
- [ ] **J1 : Regex patterns**
  - [ ] Patterns : "CCR 2020", "v1.5", "Release 2023"
  - [ ] NER temporal entities (spaCy)

- [ ] **J2 : Timeline reconstruction**
  - [ ] Clustering mentions par version
  - [ ] Ordering temporel (2020 < 2021 < 2023)

- [ ] **J3 : Tests détection versions**
  - [ ] Corpus CCR 2020-2025
  - [ ] Validation 5 versions détectées

- [ ] **Checkpoint J3**
  - [ ] Version detection ≥ 90% accuracy

#### ⏸️ Jour 4-7 : Feature Diff Analysis
- [ ] **J4 : LLM prompt feature extraction**
  - [ ] Input : Chunks liés à version X
  - [ ] Output : List[Feature] avec descriptions

- [ ] **J5 : Diff algorithm**
  - [ ] Compute : ADDED, REMOVED, UNCHANGED
  - [ ] Semantic similarity (embeddings) pour matching

- [ ] **J6 : Change severity classifier**
  - [ ] MAJOR : Breaking changes
  - [ ] MINOR : Additive changes
  - [ ] PATCH : Bug fixes

- [ ] **J7 : Migration effort estimator**
  - [ ] Heuristique : MAJOR=HIGH, MINOR=MEDIUM, PATCH=LOW
  - [ ] Facteur : nombre features removed × complexity

- [ ] **Checkpoint J7**
  - [ ] Feature diff ≥ 75% precision
  - [ ] Severity classification validée

#### ⏸️ Jour 8-10 : CRR Evolution Tracker Demo
- [ ] **J8 : Pipeline E2E CCR 2020→2025**
  - [ ] Ingestion 5 documents (1 par version)
  - [ ] Extraction features per version
  - [ ] Diff computation

- [ ] **J9 : Validation breaking changes**
  - [ ] "XML deprecated" détecté (2020→2021)
  - [ ] "Manual validation removed" (2021→2023)

- [ ] **J10 : Documentation use case**
  - [ ] Query : "Breaking changes CCR 2020→2025 ?"
  - [ ] Response : Delta structuré + migration effort
  - [ ] Démo slides pitch-ready

- [ ] **Checkpoint J10 (Livrable Semaine 19)**
  - [ ] CRR Evolution Tracker functional
  - [ ] Démo validée
  - [ ] Documentation complète

### KPIs Target
- Temporal relations détectées ≥ 90% concepts versionnés
- Precision delta detection ≥ 75%
- Breaking changes identifiés confidence ≥ 0.80

---

## 📅 COMPOSANT 4 : RelationInferenceEngine

**Période :** Semaines 20-21 (10 jours)
**Status :** 🟡 **NOT STARTED**
**Référence :** `doc/phases/PHASE2_INTELLIGENCE.md` lignes 1007-1069

### Objectif
Inférer relations implicites via raisonnement logique (transitive, cohérence).

### Checklist Complète

#### ⏸️ Jour 1-4 : Transitive Inference
- [ ] **J1 : Règles Cypher PART_OF transitive**
  - [ ] Query : MATCH (a)-[:PART_OF]->(b)-[:PART_OF]->(c)
  - [ ] CREATE inferred relation avec metadata

- [ ] **J2 : Règles Cypher REQUIRES transitive**
  - [ ] Query similaire pour REQUIRES
  - [ ] Flagging indirect dependencies

- [ ] **J3 : Tests inférence SAP**
  - [ ] SAP Fiori → S/4HANA Cloud
  - [ ] Validation path justification

- [ ] **J4 : Optimization performance**
  - [ ] Index Neo4j sur relation_type
  - [ ] Batch inference (éviter N² queries)

- [ ] **Checkpoint J4**
  - [ ] Transitive inference functional
  - [ ] Performance ≤ 5s pour 10k concepts

#### ⏸️ Jour 5-7 : Coherence Validation
- [ ] **J5 : Détection cycles**
  - [ ] Query : MATCH (a)-[:PART_OF*]->(a)
  - [ ] Alert + auto-correction (remove weakest edge)

- [ ] **J6 : Détection conflits temporels**
  - [ ] INVALID : (A REPLACES B) AND (B REPLACES A)

- [ ] **J7 : Contradictions hiérarchiques**
  - [ ] INVALID : (A PART_OF B) AND (A PART_OF C) si B, C même niveau

- [ ] **Checkpoint J7**
  - [ ] 0 incohérences détectées sur corpus test
  - [ ] Auto-correction validée

#### ⏸️ Jour 8-10 : Explainability
- [ ] **J8 : API explain_relation(A, C)**
  - [ ] Return justification chain (A→B→C)
  - [ ] Include confidence per edge, sources

- [ ] **J9 : Frontend integration (optional)**
  - [ ] UI afficher path inférence
  - [ ] Tooltip evidence chunks

- [ ] **J10 : Documentation + tests E2E**
  - [ ] Tests exhaustifs
  - [ ] Documentation API

- [ ] **Checkpoint J10 (Livrable Semaine 21)**
  - [ ] Explainability API functional
  - [ ] Tests E2E passés
  - [ ] ≥ 30% relations inférées
  - [ ] 0 incohérences logiques

### KPIs Target
- ≥ 30% relations inférées (complément extraction directe)
- 0 incohérences logiques
- Validation cohérence < 5s pour 10k concepts

---

## 📅 COMPOSANT 5 : CrossDocRelationMerger

**Période :** Semaines 22-24 (15 jours)
**Status :** 🟡 **NOT STARTED**
**Référence :** `doc/phases/PHASE2_INTELLIGENCE.md` lignes 1071-1156

### Objectif
Consolidation relations multi-sources + **Validation finale Phase 2**.

### Checklist Complète

#### ⏸️ Jour 1-4 : Aggregation Multi-Sources
- [ ] **J1 : Relation similarity detector**
  - [ ] Critères : même (source, target, relation_type_semantic)
  - [ ] Embeddings similarity pour variants

- [ ] **J2 : Confidence aggregation**
  - [ ] Weighted average (recency + credibility)
  - [ ] Formula : conf_final = Σ(conf_i × weight_i) / Σ(weight_i)

- [ ] **J3 : Metadata merger**
  - [ ] sources : List[doc_id]
  - [ ] first_mentioned, last_mentioned : timestamps
  - [ ] mention_count : int
  - [ ] consensus_strength : "LOW|MEDIUM|HIGH"

- [ ] **J4 : Tests multi-doc**
  - [ ] 3 docs mentionnent même relation
  - [ ] Validation consensus_strength = "HIGH"

- [ ] **Checkpoint J4**
  - [ ] Aggregation multi-sources functional
  - [ ] Tests unitaires passés

#### ⏸️ Jour 5-7 : Conflict Resolution
- [ ] **J5 : Divergent relation_type handler**
  - [ ] Exemple : Doc A "USES", Doc B "REQUIRES"
  - [ ] Strategy : Garder les deux si confidence similaire
  - [ ] Flag conflicting=true

- [ ] **J6 : Recency vs confidence arbitrage**
  - [ ] Si delta confidence > 0.15 → plus confident
  - [ ] Sinon → plus récent

- [ ] **J7 : Human validation flagging**
  - [ ] Critères : conflicting=true AND delta < 0.10
  - [ ] Export CSV pour review manuel

- [ ] **Checkpoint J7**
  - [ ] Conflict resolution logic validée
  - [ ] Conflict rate ≤ 8%

#### ⏸️ Jour 8-15 : Tests E2E & Validation Finale Phase 2
- [ ] **J8-J10 : Pipeline complet Phase 1.5 + Phase 2**
  - [ ] Ingestion 500 docs SAP (corpus varié)
  - [ ] Extraction concepts (Phase 1.5)
  - [ ] Extraction relations (Phase 2)
  - [ ] Construction taxonomy
  - [ ] Temporal diff
  - [ ] Inference
  - [ ] Cross-doc merge

- [ ] **J11-J12 : Validation KPIs**
  - [ ] Relations typées / concept ≥ 1.5
  - [ ] Precision ≥ 80%
  - [ ] Coverage taxonomy ≥ 80%
  - [ ] Temporal relations ≥ 90%
  - [ ] Cycles = 0
  - [ ] Conflict rate < 8%

- [ ] **J13-J14 : Démos use cases**
  - [ ] UC1 : SAP Product Dependencies
  - [ ] UC2 : CRR Evolution Tracker
  - [ ] UC3 : Taxonomy Navigation

- [ ] **J15 : Documentation finale**
  - [ ] Architecture documentation
  - [ ] API reference
  - [ ] User guides (query examples)
  - [ ] Performance benchmarks

- [ ] **Checkpoint J15 (CRITIQUE - GO/NO-GO Phase 3)**
  - [ ] Tous KPIs techniques atteints
  - [ ] 3 use cases démontrables
  - [ ] Documentation complète
  - [ ] Performance validation (<5s queries, <$0.20/doc)

### KPIs Target
- ≥ 60% relations consolidées multi-docs
- Conflict rate < 8%
- Consensus strength "HIGH" pour ≥ 70% relations fréquentes

---

## 📝 Journal des Accomplissements

### 2025-11-16 : POC Concept Explainer + Gatekeeper Fix
**Status :** ✅ COMPLÉTÉ

#### Travail Réalisé
1. **POC Concept Explainer créé**
   - Schemas Pydantic (concepts.py)
   - Service layer (concept_explainer_service.py)
   - API router (concepts.py)
   - Integration main.py
   - Tests Postman validés

2. **Bug Gatekeeper corrigé**
   - Identification : CanonicalConcept sans name/summary
   - Code fix : neo4j_client.py (lignes 553, 557, 483-485)
   - Migration : 408 concepts backfilled

3. **Documentation complète**
   - OSMOSE_PHASE2_POC_CONCEPT_EXPLAINER.md (448 lignes)
   - Options 3 & 4 documentées (extensions futures)

4. **Git Commit**
   - Commit c6f581a
   - 7 fichiers (4 nouveaux, 2 modifiés, 1 script)

#### Métriques
- Endpoint : GET /api/concepts/{id}/explain ✅
- Exemple "Security" : 12,729 chunks + 10 relations ✅
- Cross-référence Neo4j ↔ Qdrant : ✅ Fonctionnelle
- Migration concepts : 408 → 0 NULL ✅

---

### 2025-10-19 : Démarrage Phase 2 - LLM Relation Extraction
**Status :** ✅ COMPLÉTÉ (Jour 1-2)

#### Composants Créés
1. **LLMRelationExtractor** (530 lignes)
   - LLM-first extraction avec gpt-4o-mini
   - Co-occurrence pre-filtering (économie coûts)
   - 9 types relations core
   - Gestion multilingue (EN, FR)

2. **Neo4jRelationshipWriter** (522 lignes)
   - Upsert relations confidence-based
   - Metadata complète
   - Utility methods

3. **Tests Fonctionnels**
   - 20/20 tests passing (100%)

#### Intégration Pipeline
- Supervisor FSM : nouvel état EXTRACT_RELATIONS
- Position : après PROMOTE, avant completion
- Lazy loading + graceful error handling
- Commits : 5c07333, 6900b7c

#### Optimisations Cache
- Hash-based cache (SHA256 contenu)
- Early cache check avant PDF conversion
- Économies : ~90% temps, $0.15-0.50 par re-import
- Commit : 2ce2170

#### Métriques
- Code produit : 1,052 lignes
- Tests : 20 tests (100% passing)
- Types relations : 9 core supportés
- Model : gpt-4o-mini (cost optimized)

---

## 🎯 Prochaines Étapes Immédiates

### Priorité 0 : DomainContextPersonalizer (FONDATION - 5 jours)
**Raison :** Module fondation utilisé par TOUS les composants Phase 2
**Impact :** +15% precision canonicalization, meilleure détection relations

- [ ] Jour 1-2 : Backend Core (DomainContextProfile + Extractor)
- [ ] Jour 3 : Persistence (Neo4j store)
- [ ] Jour 4 : Injection Middleware (integration LLMCanonicalizer + RelationExtractor)
- [ ] Jour 5 : API + Frontend (/settings/domain-context)

**Référence :** `doc/ongoing/OSMOSE_PHASE2_DOMAIN_CONTEXT_PERSONALIZER.md`

### Priorité 1 : RelationExtractionEngine Jour 3
- [ ] Finaliser design RelationExtractionEngine class
- [ ] Définir schema Neo4j relations (documentation)
- [ ] Sélectionner corpus test 100 docs multi-domaines
- [ ] Créer script annotation Gold Standard (450 relations)

### Priorité 2 : RelationExtractionEngine Jour 4-7
- [ ] Implémenter pattern-based extraction (regex + spaCy)
- [ ] Tester sur corpus avec KPIs (Precision ≥ 70%, Recall ≥ 50%)

### Quick Wins
- Réutiliser GraphCentralityScorer Phase 1.5 pour co-occurrences
- Adapter prompts LLMCanonicalizer pour relation classification
- Exploiter LLMRouter existant (TaskType.RELATION_CLASSIFICATION)
- Patterns multilingues depuis `PHASE2_RELATION_TYPES_REFERENCE.md`

---

## 📊 Métriques Temps Réel

### Dashboard KPIs Phase 2

| Métrique | Target | Actuel | Trend | Last Update |
|----------|--------|--------|-------|-------------|
| **Relations typées extraites** | - | 0 | - | - |
| **Concepts avec ≥1 relation** | ≥70% | - | - | - |
| **Precision relation extraction** | ≥80% | - | - | 2025-10-19 |
| **Recall relation extraction** | ≥65% | - | - | - |
| **Coverage taxonomy** | ≥80% | - | - | - |
| **Profondeur moyenne taxonomy** | 2-4 | - | - | - |
| **Temporal relations (versioned)** | ≥90% | - | - | - |
| **Relations inférées** | ≥30% total | - | - | - |
| **Cycles détectés** | 0 | - | - | - |
| **Conflict rate** | <8% | - | - | - |
| **Processing cost per doc** | <$0.20 | - | - | - |
| **Query latency (avg)** | <5s | - | - | - |

---

## 🚨 Risques & Mitigation

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|-----------|
| **Precision extraction < 80%** | MEDIUM | HIGH | Tuning prompts LLM + enrichir patterns |
| **Coverage taxonomy < 80%** | LOW | MEDIUM | Clustering adaptatif + LLM fallback |
| **Performance queries > 5s** | LOW | HIGH | Indexation Neo4j + caching |
| **Conflict rate > 8%** | MEDIUM | MEDIUM | Améliorer recency weighting |
| **Cycles non détectés** | LOW | CRITICAL | Tests exhaustifs + validation continue |
| **Budget LLM dépassé** | LOW | MEDIUM | Circuit breaker + quotas stricts |

---

## 📎 Ressources Clés

### Documentation Principale
- `doc/phases/PHASE2_INTELLIGENCE.md` : Spécification complète Phase 2
- `doc/ongoing/PHASE2_RELATION_TYPES_REFERENCE.md` : Taxonomie 12 types relations + patterns
- `doc/ongoing/OSMOSE_PHASE2_POC_CONCEPT_EXPLAINER.md` : Documentation POC

### Corpus Test SAP
- SAP S/4HANA Cloud Overview (230 slides)
- SAP BTP Architecture (120 slides)
- SAP CCR Evolution 2020-2025 (5 documents)
- SAP Ariba Product Guide (80 pages)
- SAP SuccessFactors Integration (60 pages)

### Benchmarks Cibles
- Precision relation extraction : Google Knowledge Graph (~85%)
- Coverage taxonomy : WordNet (~90%)
- Temporal diff accuracy : ChangeLog parsers (~80%)

---

**FIN Tracking Phase 2 - v1.0**

**Prochaine MAJ :** Après Jour 3 RelationExtractionEngine (corpus test ready)
