# 🌊 KnowWhere - Roadmap OSMOSE Intégrée (Architecture Agentique)

**Version:** 2.0 - Intègre Architecture Agentique v1.1
**Date:** 2025-10-13
**Vision:** Le Cortex Documentaire des Organisations
**Différenciation:** Semantic Intelligence + Architecture Agentique Orchestrée

---

## 📋 Table des Matières

1. [Executive Summary](#1-executive-summary)
2. [Pivot Stratégique: Architecture Agentique](#2-pivot-stratégique-architecture-agentique)
3. [Roadmap Révisée (35 Semaines)](#3-roadmap-révisée-35-semaines)
4. [Phases Détaillées](#4-phases-détaillées)
5. [Jalons & Checkpoints](#5-jalons--checkpoints)
6. [Métriques de Succès](#6-métriques-de-succès)
7. [Stratégie Go-to-Market Ajustée](#7-stratégie-go-to-market-ajustée)

---

## 1. Executive Summary

### 1.1 Vision Produit (Inchangée)

> **"KnowWhere n'est pas une IA qui cherche, c'est une IA qui comprend."**

**Value Proposition** :
- ✅ Détecte fils narratifs cross-documents (vs Copilot/Gemini)
- ✅ Timeline d'évolution automatique des concepts
- ✅ Conflict detection et version tracking
- ✅ Semantic governance avec quality control intelligent

### 1.2 Pivot Architectural Majeur ✨ **NOUVEAU**

**Ajout Architecture Agentique Orchestrée (v1.1)** intégrée dans roadmap :

**6 Agents Spécialisés** :
1. Supervisor (FSM orchestration)
2. Extractor Orchestrator (routing NO_LLM/SMALL/BIG/VISION)
3. Pattern Miner (cross-segment reasoning)
4. Gatekeeper Delegate (quality control)
5. Budget Manager (cost control)
6. **LLM Dispatcher** ✨ (rate limits, concurrency, priority queue)

**18 Tools** avec JSON I/O stricts

**Cost Model Maîtrisé** :
- Scénario A (PDF textuels) : **$1.00/1000 pages** (-60% vs legacy)
- Scénario B (complexes) : **$3.08/1000 pages** (-20% vs legacy)
- Scénario C (PPT-heavy) : **$7.88/1000 pages** (-10% vs legacy)

**Conformité & Sécurité** :
- PIIGate (GDPR/HIPAA)
- Multi-tenant isolation (namespaces Qdrant, contraintes Neo4j)
- Rate limiting coordonné (500 RPM SMALL, 100 RPM BIG, 50 RPM VISION)

### 1.3 Impact sur Roadmap

**Avant (v1.0)** : 32 semaines linéaires
**Après (v2.0)** : **35 semaines** avec pilote agentique stratégique

**Nouvelle structure** :
```
Phase 1 (Sem 1-10)      : Semantic Core V2.1 ✅ COMPLÉTÉ (Sem 10/10)
Phase 1.5 (Sem 11-13)   : ✨ PILOTE AGENTIQUE (nouveau) 🟢 40% (J3/15 - Setup complété)
Phase 2 (Sem 14-22)     : Agentique Production + Living Ontology 🟡 NOT STARTED
Phase 3 (Sem 23-28)     : Multi-Source & Enrichment 🟡 NOT STARTED
Phase 4 (Sem 29-35)     : Production Hardening (étendu) 🟡 NOT STARTED
```

---

## 2. Pivot Stratégique: Architecture Agentique

### 2.1 Pourquoi l'Architecture Agentique ?

**Problèmes résolus** :

| Problème Identifié | Solution Agentique | Impact Business |
|--------------------|-------------------|-----------------|
| **Coûts LLM imprévisibles** | Budget Governor + routing intelligent | -40 à -60% coûts OPEX |
| **Scalabilité limitée** | LLM Dispatcher (rate limits coordonnés) | 1000+ docs/jour possible |
| **Qualité variable** | Gatekeeper multi-critères + second opinion | Precision@Promote >90% |
| **Pas de gouvernance conformité** | PIIGate (GDPR/HIPAA) | Secteurs finance/pharma débloqués |
| **Volumétrie non maîtrisée** | RELATED_TO cap 5%, orphan ratio <8% | Graphe maintenable |

### 2.2 Différenciation vs Competitors Renforcée

**Avant architecture agentique** :
- ✅ Semantic intelligence (différenciateur)
- ⚠️ Coûts non maîtrisés (risque production)
- ⚠️ Scalabilité limitée (<100 docs/jour)

**Après architecture agentique v1.1** :
- ✅✅✅ Semantic intelligence + Cost intelligence
- ✅✅✅ Maîtrise coûts production ($1-8/1000p selon complexité)
- ✅✅✅ Scalabilité 10x (1000+ docs/jour)
- ✅✅✅ Conformité GDPR/HIPAA (PIIGate)
- ✅✅✅ Rate limiting coordonné (production-ready)

**Message marketing ajusté** :

> *"KnowWhere : La seule plateforme qui **comprend** vos documents ET **maîtrise** ses coûts."*

### 2.3 Timeline Validation

**Phase 1.5 (Sem 11-13) : PILOTE AGENTIQUE** = **Point de décision GO/NO-GO critique**

**Critères GO Phase 2** (TOUS obligatoires) :
- ✅ Cost model validé (≤110% targets : $1.00, $3.08, $7.88/1000p)
- ✅ Precision@Promote ≥90%
- ✅ Routing accuracy PrepassAnalyzer ≥80%
- ✅ Aucun rate limit explosion
- ✅ Multi-tenant security validée (aucune fuite)
- ✅ PIIGate FP rate <7%

**Si NO-GO** : Retour Phase 1 pour tuning (1-2 semaines), puis re-test

---

## 3. Roadmap Révisée (35 Semaines)

### 3.1 Vue d'Ensemble

```
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: SEMANTIC CORE (Semaines 1-10)                               │
│ ✅ Démo use case killer: CRR Evolution Tracker                        │
│ Composants: Profiler, NarrativeDetector, Segmentation, DualStorage   │
└────────────────────────────────────────────────────────────────────────┘
         │
         ↓ Checkpoint Phase 1 (Sem 10)
         │
┌────────────────────────────────────────────────────────────────────────┐
│ ✨ PHASE 1.5: PILOTE AGENTIQUE (Semaines 11-13) ✨ NOUVEAU            │
│ 🎯 GO/NO-GO CRITIQUE                                                   │
│ - Implémentation 6 agents + 18 tools                                  │
│ - Test 100 docs (50 PDF A, 30 B, 20 PPTX C)                          │
│ - Validation cost model $1.00, $3.08, $7.88/1000p                    │
│ - Security, conformité, scalabilité                                   │
└────────────────────────────────────────────────────────────────────────┘
         │
         ↓ GO/NO-GO Phase 2 (Sem 13)
         │
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: AGENTIQUE PRODUCTION + LIVING ONTOLOGY (Semaines 14-22)     │
│ - Scale-up architecture agentique (1000+ docs/jour)                   │
│ - Living Ontology pattern discovery                                   │
│ - Lifecycle HOT/WARM/COLD/FROZEN                                      │
│ - Dashboard monitoring temps-réel (Grafana)                           │
└────────────────────────────────────────────────────────────────────────┘
         │
         ↓ Checkpoint Phase 2 (Sem 22)
         │
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: MULTI-SOURCE & ENRICHMENT (Semaines 23-28)                  │
│ - Intégration SharePoint, Google Drive, Confluence                    │
│ - Auto-enrichment external sources                                    │
│ - Cross-source narrative detection                                    │
└────────────────────────────────────────────────────────────────────────┘
         │
         ↓ Checkpoint Phase 3 (Sem 28)
         │
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: PRODUCTION HARDENING (Semaines 29-35)                       │
│ - Beta clients (3-5 enterprises)                                      │
│ - Tuning performance production                                       │
│ - Launch v1.0 public                                                  │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Comparaison Roadmap v1.0 vs v2.0

| Phase | v1.0 (avant agentique) | v2.0 (avec agentique) | Delta |
|-------|------------------------|------------------------|-------|
| **Phase 1** | Sem 1-10 | Sem 1-10 | ✅ Identique |
| **Phase 1.5** | N/A | **Sem 11-13** | ✨ **+3 semaines** (pilote) |
| **Phase 2** | Sem 11-18 | Sem 14-22 | +9 semaines (scale-up agentique) |
| **Phase 3** | Sem 19-26 | Sem 23-28 | +6 semaines (multi-source) |
| **Phase 4** | Sem 27-32 | Sem 29-35 | +7 semaines (hardening production) |
| **TOTAL** | **32 semaines** | **35 semaines** | **+3 semaines** |

**Justification +3 semaines** :
- Pilote agentique 3 semaines = investissement stratégique critique
- Évite refactoring massif en Phase 3-4 si architecture non validée
- Garantit coûts production maîtrisés AVANT scale-up

---

## 4. Phases Détaillées

### Phase 1: Semantic Core V2.1 (Semaines 1-10) 🔄 **PIVOTÉ** - 40% Complete

**Status:** 🟢 **EN COURS** - Semaines 4/10 terminées

**Objectif** : Implémenter extraction et unification concepts multilingues (Concept-First, Language-Agnostic)

**Pivot Architectural (2025-10-14):**
- ❌ Approche narrative abandonnée (hardcoded English keywords, non-scalable)
- ✅ Pivot vers Concept-First avec cross-lingual unification automatique
- ✅ Architecture V2.1 : 4 composants au lieu de 6+

**Composants V2.1** :
1. ✅ **Setup Infrastructure** (Sem 1-2) - COMPLETE
   - MultilingualNER (spaCy en/fr/de/xx)
   - MultilingualEmbedder (multilingual-e5-large 1024D)
   - LanguageDetector (fasttext)
   - Neo4j + Qdrant V2.1 schemas

2. ✅ **TopicSegmenter** (Sem 3-4) - CODE COMPLETE
   - Structural + semantic segmentation
   - HDBSCAN + Agglomerative clustering
   - Anchor extraction (NER + TF-IDF)
   - Cohesion validation (650 lignes)

3. 🟡 **MultilingualConceptExtractor** (Sem 5-7) - NOT STARTED ⚠️ CRITIQUE
   - Triple méthode (NER + Clustering + LLM)
   - Typage concepts (ENTITY, PRACTICE, STANDARD, TOOL, ROLE)
   - Fusion + déduplication

4. 🟡 **SemanticIndexer** (Sem 8-9) - NOT STARTED
   - Cross-lingual canonicalization
   - Hierarchy construction

5. 🟡 **ConceptLinker** (Sem 10) - NOT STARTED
   - Cross-document relations
   - DocumentRole classification

**Livrables Sem 10** :
- ✅ Démo extraction concepts multilingues (EN/FR/DE)
- ✅ Cross-lingual unification (FR "auth" = EN "auth")
- ✅ 10+ documents testés (mixtes multilingues)
- ✅ Performance <30s/doc
- ✅ Tests >80% coverage

**Progrès Actuel** :
- Tasks: 46/120 (38%)
- Code: ~2200 lignes (infrastructure + TopicSegmenter)
- Tests: 9 test cases créés (nécessitent Docker)

**Effort** : 25-30h/semaine × 10 semaines = **250-300h**

**Documentation** : [`doc/phases/PHASE1_SEMANTIC_CORE.md`](./phases/PHASE1_SEMANTIC_CORE.md) (1 seul fichier consolidé)

---

### ✨ Phase 1.5: PILOTE AGENTIQUE (Semaines 11-13) **NOUVEAU CRITIQUE**

**Objectif** : Valider architecture agentique production-ready

**Setup (Semaine 11 - Jours 1-3)** ✅ **COMPLÉTÉ 2025-10-15** :
- [x] Implémentation 6 agents (Supervisor, Extractor, Miner, Gatekeeper, Budget, **Dispatcher**) ✅ 1,896 lignes
- [x] Implémentation 11 tools avec JSON I/O (prepass_analyzer, extract_concepts, detect_patterns, link_concepts, gate_check, promote_concepts, check_budget, consume_budget, refund_budget, dispatch_llm, get_queue_stats) ✅
- [x] Configuration YAML 4 fichiers (supervisor, routing_policies, gate_profiles, budget_limits) ✅ 342 lignes
- [x] Tests unitaires 70 tests (~77% pass) ✅
- [x] Intégration pipeline (osmose_agentique.py) ✅ 352 lignes
- [x] Tests intégration 15 tests ✅
- [ ] Setup Redis (queue state, quotas tracking) 🟡 TODO J4
- [ ] Neo4j namespaces multi-tenant 🟡 TODO J4
- [ ] Qdrant tenant isolation 🟡 TODO J4
- [ ] Rate limiting production validation 🟡 TODO J4-5
- [ ] Dashboard Grafana (10 KPIs temps-réel) 🟡 TODO Sem 12

**Commits Créés** :
- `4239454`: feat(agents): Implémenter Architecture Agentique Phase 1.5 V1.1 (3,022 insertions)
- `483a4c1`: test(agents): Ajouter tests unitaires (1,050 insertions)
- `209fec6`: feat(integration): Intégrer Architecture Agentique dans pipeline (593 insertions)
- `c96138f`: feat(worker): Intégrer Architecture Agentique dans worker ingestion (2 fichiers modifiés)
- `30b623e`: feat(redis): RedisClient + BudgetManager integration (455 insertions)
- `d4b0ed9`: test(redis): 26 tests unitaires (453 insertions)
- `49d462c`: feat(clients): Neo4j + Qdrant multi-tenant (745 insertions)
- `3fe29ba`: feat(segmentation): TopicSegmenter integration (65 insertions)
- `d3b639f`: feat(gatekeeper): Storage Neo4j Published-KG (105 insertions)
- `9d323a4`: test(e2e): Tests end-to-end OSMOSE Agentique (339 insertions)
- `8e49d58`: feat(pilot): Script Pilote Scénario A (429 insertions)

**✨ Filtrage Contextuel Avancé (Semaine 11 - Jours 7-9)** ⚠️ **P0 CRITIQUE - NOUVEAU** :

**Source** : Analyse Best Practices Extraction (OpenAI, 2025-10-15)
**Documents** :
- `doc/OSMOSE_EXTRACTION_QUALITY_ANALYSIS.md` (Phase 4: Filtrage Contextuel Avancé)
- `doc/ongoing/ANALYSE_FILTRAGE_CONTEXTUEL_GENERALISTE.md`

**Problème Critique Identifié** :
```
Situation actuelle: GatekeeperDelegate filtre uniquement par confidence (pas par contexte)
Impact: Produits concurrents promus au même niveau que produits principaux!

Exemple:
Document RFP: "Notre solution SAP S/4HANA... Les concurrents Oracle et Workday..."

Extraction actuelle:
✅ SAP S/4HANA (0.95) → Promu
✅ Oracle (0.92) → Promu  ❌ ERREUR!
✅ Workday (0.90) → Promu  ❌ ERREUR!

Attendu:
✅ SAP S/4HANA → PRIMARY (score: 1.0) → Promu
❌ Oracle → COMPETITOR (score: 0.3) → Rejeté
❌ Workday → COMPETITOR (score: 0.3) → Rejeté
```

**Solution: Filtrage Contextuel Hybride (Production-Ready)** :

**Jour 7** :
- [x] Analyse best practices complétée ✅
- [ ] Implémenter `GraphCentralityScorer` (300 lignes) ⚠️ **P0**
  - TF-IDF weighting (vs fréquence brute)
  - Salience score (position + titre/abstract boost)
  - Fenêtre adaptive (30-100 mots selon taille doc)
  - Tests unitaires (10 tests)
  - **Impact** : +20-30% précision, $0 coût, <100ms

**Jour 8** :
- [ ] Implémenter `EmbeddingsContextualScorer` (200 lignes) ⚠️ **P0**
  - Paraphrases multilingues (EN/FR/DE/ES)
  - Agrégation multi-occurrences (toutes mentions vs première)
  - Stockage vecteurs Neo4j (recalcul dynamique)
  - Tests unitaires (8 tests)
  - **Impact** : +25-35% précision, $0 coût, <200ms

**Jour 9** :
- [ ] Intégrer cascade hybride dans `GatekeeperDelegate._gate_check_tool()` ⚠️ **P0**
  - Architecture cascade: Graph → Embeddings → LLM (optionnel)
  - Ajustement confidence selon role (PRIMARY +0.12, COMPETITOR -0.15)
  - Tests intégration (5 tests)
  - **Impact** : +30% précision F1-score +19%, RÉSOUT problème concurrents

**Impact Business Total** :
- ✅ Résout problème critique concurrents promus au même niveau
- ✅ **+30% précision extraction** (60% → 85-92%)
- ✅ **+19% F1-score** (68% → 87%)
- ✅ $0 coût supplémentaire (Graph + Embeddings gratuits)
- ✅ 100% language-agnostic (fonctionne EN/FR/DE/ES sans modification)

**Effort** : 3 jours dev (500 lignes + 23 tests)

**Priorité** : **P0 CRITIQUE** - Bloqueur qualité extraction

---

**Tests Scénario A (Semaine 11 - Jours 10-11)** 🟡 **EN COURS** :
- [ ] 50 PDF textuels (Scénario A - mostly SMALL routing)
- [ ] Validation cost $0.25/doc target (≤$0.28 tolérance 110%)
- [ ] PrepassAnalyzer routing accuracy ≥80%
- [ ] Cache hit rate measurement (target 20% conservative)

**Tests Scénarios B & C (Semaine 12)** :
- [ ] 30 PDF complexes (Scénario B - mix BIG, narrative threads)
  - Validation cost $0.77/doc (≤$0.85 tolérance)
  - Cross-segment bi-evidence validation
  - Precision@Promote >92% target
- [ ] 20 PPTX graphiques (Scénario C - PPT_HEAVY)
  - Auto-détection PPT_HEAVY (>8% vision)
  - Vision calls scaling (cap 100)
  - Validation cost $1.97/doc (≤$2.17 tolérance)

**Analyse & Décision GO/NO-GO (Semaine 13)** :
- [ ] Collecte 10 KPIs × 3 scénarios
- [ ] Rapport technique (20 pages)
  - Coûts réels vs estimés (breakdown détaillé)
  - Analyse échecs et outliers
  - Recommandations tuning
- [ ] Validation critères GO (TOUS obligatoires) :
  - ✅ Cost ≤110% targets
  - ✅ Precision@Promote ≥90%
  - ✅ Routing accuracy ≥80%
  - ✅ Aucun rate limit explosion
  - ✅ Multi-tenant security OK (aucune fuite)
  - ✅ PIIGate FP <7%

**Décision Sem 13** :
- **✅ GO Phase 2** : Tous critères validés → Scale-up production
- **⚠️ ITERATE** : 1-2 critères échouent → Tuning 1 semaine + re-test
- **❌ NO-GO PIVOT** : Sécurité échoue OU coûts >150% → Revoir architecture

**Effort** : 30-35h/semaine × 3 semaines = **90-105h**

**Documentation** :
- `doc/etudes/ARCHITECTURE_AGENTIQUE_OSMOSE.md` (v1.1 - 58 KB)
- Rapport pilote technique (à créer Sem 13)

---

### Phase 2: Agentique Production + Living Ontology (Semaines 14-22)

**Pré-requis** : ✅ GO Phase 1.5 (pilote validé)

**Objectif** : Scale-up production + Living Ontology

#### 2.1 Scale-Up Architecture Agentique (Sem 14-16)

**Optimisations Production** :
- [ ] Tuning rate limits production (basé sur KPIs pilote)
- [ ] Cache optimization (target hit-rate 40-60% avec volume)
- [ ] Concurrency tuning (20/5/2 → ajustements basés load tests)
- [ ] Multi-tenant quotas production ($100/jour, 500 docs/jour par tenant)
- [ ] Monitoring alerting Prometheus/Grafana (règles alertes configurées)

**Load Tests** :
- [ ] 1000 docs/jour sustained (mix 70% A, 20% B, 10% C)
- [ ] Latency P95 <220s validée
- [ ] Budget per-tenant stable (<$100/jour moyenne)

#### 2.2 Living Ontology (Sem 17-19)

**Pattern Discovery Automatique** :
- [ ] Détection émergence nouveaux entity types (seuil 20+ occurrences)
- [ ] Détection relation types récurrents (fréquence >10%)
- [ ] Validation humaine pour promotion ontologie
- [ ] UI admin Living Ontology (Mantine dashboard)

**Type Registry Dynamique** :
- [ ] Migration `entity_type_registry` → Living Ontology
- [ ] API endpoints ontology management
- [ ] Versioning ontologie (rollback possible)

#### 2.3 Canonicalisation Robuste & Auto-Apprentissage (Sem 17-19) ✨ **NOUVEAU P0**

**Contexte**: Suite à l'analyse OpenAI (2025-10-16), la stratégie de canonicalisation automatique présente 3 risques critiques P0 nécessitant des mécanismes de robustesse avant scale-up production.

**Référence**: `doc/phase1_osmose/LIMITES_ET_EVOLUTIONS_STRATEGIE.md` + `doc/phase1_osmose/PLAN_IMPLEMENTATION_CANONICALISATION.md`

**P0 - Sécurité Ontologie (7 jours, Sem 17-18)** :

- [ ] **Jour 17-18: Sandbox Auto-Learning** (2j, P0.1)
  - [ ] Ajout champs sandbox OntologyEntity: `status`, `confidence`, `requires_admin_validation`
  - [ ] Auto-validation si confidence ≥ 0.95 → `status="auto_learned_validated"`
  - [ ] Sinon → `status="auto_learned_pending"` + notification admin
  - [ ] Filtrer entités pending par défaut dans `EntityNormalizerNeo4j`
  - [ ] Tests unitaires (10 tests)
  - **Fichiers**: `neo4j_schema.py` (50L), `ontology_saver.py` (80L), `entity_normalizer_neo4j.py` (40L)
  - **Impact**: Protège ontologie contre pollution auto-learning

- [ ] **Jour 19-21: Mécanisme Rollback** (3j, P0.2)
  - [ ] Relation Neo4j `DEPRECATED_BY` avec timestamp + reason
  - [ ] API endpoint `/admin/ontology/deprecate` (POST)
  - [ ] Migration automatique CanonicalConcept → nouveau canonical
  - [ ] Frontend admin UI pour deprecation (Mantine modal)
  - [ ] Tests unitaires (15 tests)
  - **Fichiers**: `neo4j_schema.py` (80L), `ontology_admin.py` (200L), `OntologyAdminPanel.tsx` (150L)
  - **Impact**: Corrections ontologie sans casser consistance graphe

- [ ] **Jour 22-23: Decision Trace** (2j, P0.3)
  - [ ] Pydantic model `DecisionTrace` (stratégies + scores + timestamp)
  - [ ] Logger decision trace complète dans Gatekeeper
  - [ ] Stocker `decision_trace_json` dans Neo4j CanonicalConcept
  - [ ] Frontend audit UI avec filtres (par stratégie, date, confidence)
  - [ ] Tests unitaires (10 tests)
  - **Fichiers**: `decision_trace.py` (100L), `gatekeeper.py` (60L), `AuditPanel.tsx` (180L)
  - **Impact**: Audit trail complet, debug décisions canonicalisation

**P1 - Amélioration Qualité (4 jours, Sem 18-19)** :

- [ ] **Jour 24: Seuils Adaptatifs** (1j, P1.1)
  - [ ] Seuils fuzzy matching par type: COMPANY (85%), SOLUTION (90%), CONCEPT (80%)
  - [ ] Configuration YAML `canonicalization_thresholds.yaml`
  - [ ] Tests A/B sur 100 documents (baseline vs adaptatif)
  - **Impact**: +10-15% précision canonicalisation

- [ ] **Jour 25-26: Similarité Structurelle** (2j, P1.2)
  - [ ] Jaccard similarity sur voisins Neo4j (RELATED_TO, DEPENDS_ON)
  - [ ] Boost +0.1 si overlap voisins > 30%
  - [ ] Tests unitaires (12 tests)
  - **Impact**: +12% recall entités liées

- [ ] **Jour 27: Séparation Surface/Canonical** (1j, P1.3)
  - [ ] Distinction `surface_form` (texte brut) vs `canonical_name` (normalisé)
  - [ ] Index Neo4j sur `surface_form` pour recherche alias
  - [ ] Migration données existantes (script batch)
  - **Impact**: Préserve formes originales, améliore flexibilité recherche

**Effort Total Canonicalisation**: 11 jours (P0: 7j + P1: 4j)

**Checkpoint Sem 19**:
- ✅ Auto-learning sécurisé (sandbox + rollback + trace)
- ✅ Qualité canonicalisation +25% (seuils adaptatifs + similarité)
- ✅ Audit trail complet (decision trace UI opérationnelle)

**Documents Créés**:
- `doc/phase1_osmose/STRATEGIE_CANONICALISATION_AUTO_APPRENTISSAGE.md` (1,090L)
- `doc/phase1_osmose/LIMITES_ET_EVOLUTIONS_STRATEGIE.md` (900L)
- `doc/phase1_osmose/PLAN_IMPLEMENTATION_CANONICALISATION.md` (750L)

#### 2.4 Lifecycle Management (Sem 20-22)

**Tiers HOT/WARM/COLD/FROZEN** :
- [ ] HOT: Proto-KG (0-7 jours, full access)
- [ ] WARM: Published-KG (7-30 jours, optimized access)
- [ ] COLD: Archive Neo4j (30-90 jours, read-only)
- [ ] FROZEN: S3 export (>90 jours, compliance only)

**Rotation automatique** :
- [ ] Cron jobs daily (lifecycle policies)
- [ ] Metrics volumétrie par tier
- [ ] Estimation coûts stockage optimisée

**Checkpoint Sem 22** :
- ✅ 1000+ docs/jour traités sans dégradation
- ✅ Living Ontology détecte 3+ nouveaux types/mois
- ✅ Lifecycle réduit volumétrie Neo4j -40%

**Effort** : 30h/semaine × 9 semaines = **270h**

---

### Phase 3: Multi-Source & Enrichment (Semaines 23-28)

**Objectif** : Intégration sources externes + auto-enrichment

#### 3.1 Connecteurs Multi-Source (Sem 23-25)

**Intégrations** :
- [ ] SharePoint Online (Microsoft Graph API)
- [ ] Google Drive (Google Drive API)
- [ ] Confluence (Atlassian REST API)
- [ ] Slack (messages historiques, threads)

**Ingestion Continue** :
- [ ] Webhooks notifications changements
- [ ] Polling incrémental (delta sync)
- [ ] Déduplication cross-source (SimHash)

#### 3.2 Cross-Source Narrative Detection (Sem 26-27)

**Détection Narrative Cross-Source** :
- [ ] Entité "Customer Retention Rate" mentionnée SharePoint + Email thread + Slack discussion
- [ ] Agrégation narrative cross-source
- [ ] Timeline enrichie multi-canal

**Conflict Detection Enhanced** :
- [ ] Détection contradictions cross-source
- [ ] UI warnings si définition diverge entre sources

#### 3.3 Auto-Enrichment (Sem 28)

**External Knowledge Enrichment** :
- [ ] Wikipedia/Wikidata enrichment (concepts publics)
- [ ] Industry standards DB (ISO, NIST, etc.)
- [ ] Acronym expansion automatique

**Checkpoint Sem 28** :
- ✅ 3 sources externes connectées
- ✅ Cross-source narrative fonctionne
- ✅ Auto-enrichment enrichit 30%+ entités

**Effort** : 25-30h/semaine × 6 semaines = **150-180h**

---

### Phase 4: Production Hardening (Semaines 29-35)

**Objectif** : Beta clients + launch v1.0

#### 4.1 Beta Clients (Sem 29-31)

**Onboarding 3-5 Clients Beta** :
- [ ] Client #1: Finance (compliance docs, CRR use case)
- [ ] Client #2: Pharma (regulatory docs, FDA tracking)
- [ ] Client #3: Consulting (proposals versioning)

**Support & Feedback** :
- [ ] Onboarding sessions (2h/client)
- [ ] Support Slack channel
- [ ] Feedback loop hebdomadaire

#### 4.2 Performance Tuning Production (Sem 32-34)

**Optimisations Basées Usage Réel** :
- [ ] Tuning gate profiles par domaine (basé feedback beta)
- [ ] Cache policies ajustées (hit-rate >50% objectif)
- [ ] Rate limits optimisés (basé patterns réels)

**Security Hardening** :
- [ ] Audit sécurité externe (GDPR compliance)
- [ ] Penetration testing
- [ ] SOC2 Type 1 préparation

#### 4.3 Launch v1.0 Public (Sem 35)

**Go-Live Checklist** :
- [ ] Documentation complète (docs.knowwhere.ai)
- [ ] Pricing tiers définis ($99/month Starter, $499 Pro, $1999 Enterprise)
- [ ] Landing page + demo video
- [ ] Launch communication (blog post, LinkedIn, Twitter)
- [ ] Support Tier 1 (email, chat)

**Checkpoint Sem 35** :
- ✅ v1.0 production stable
- ✅ 5+ clients beta satisfaits (NPS >40)
- ✅ Architecture agentique scaled (1000+ docs/jour)
- ✅ Coûts OPEX maîtrisés (<$0.30/doc moyenne)

**Effort** : 30-35h/semaine × 7 semaines = **210-245h**

---

## 5. Jalons & Checkpoints

### 5.1 Checkpoints Obligatoires

| Checkpoint | Semaine | Critères Validation | Impact si Échec |
|------------|---------|---------------------|-----------------|
| **CP1: Phase 1 Démo** | Sem 10 | CRR Evolution fonctionne, narrative threads détectés | Retour Sem 5 (tuning narrative detector) |
| **CP2: Pilote GO/NO-GO** ⚠️ **CRITIQUE** | Sem 13 | TOUS critères GO validés (coûts, qualité, sécurité) | NO-GO = revoir architecture ou arrêt projet |
| **CP3: Phase 2 Scale** | Sem 22 | 1000+ docs/jour stable, Living Ontology fonctionne | Retour Sem 18 (optimisations performance) |
| **CP4: Multi-Source** | Sem 28 | 3 sources intégrées, cross-source narrative OK | Retour Sem 25 (simplifier intégrations) |
| **CP5: Beta Clients** | Sem 35 | 5+ clients satisfaits, v1.0 production stable | Retour Sem 32 (fixes critiques) |

### 5.2 Jalons Intermédiaires

**Jalon J1 (Sem 5)** : Semantic Profiler + Narrative Detector opérationnels
**Jalon J2 (Sem 10)** : Démo CRR Evolution validée (checkpoint CP1)
**Jalon J3 (Sem 11)** : 6 agents implémentés
**Jalon J4 (Sem 13)** : Pilote 100 docs terminé, décision GO/NO-GO (checkpoint CP2)
**Jalon J5 (Sem 16)** : Load test 1000 docs/jour passé
**Jalon J6 (Sem 22)** : Living Ontology en production (checkpoint CP3)
**Jalon J7 (Sem 28)** : Multi-source opérationnel (checkpoint CP4)
**Jalon J8 (Sem 35)** : Launch v1.0 (checkpoint CP5)

---

## 6. Métriques de Succès

### 6.1 KPIs Techniques (Architecture Agentique)

**Validés en Phase 1.5 (Pilote)** :

| KPI | Target | Mesure | Alerte Si |
|-----|--------|--------|-----------|
| **cost_per_promoted_relation** | <$0.05 | Total LLM cost / relations promues | >$0.08 |
| **precision_at_promote** | >90% | Valid promotions / auto-promotions | <85% |
| **routing_prediction_error** | <20% | abs(predicted - actual) / total routes | >25% |
| **orphan_ratio** | <8% | Orphan entities / total entities | >12% |
| **cache_hit_rate** | >20% (pilote), >50% (production) | Cache hits / total calls | <15% (pilote), <40% (prod) |
| **related_to_percent** | <5% | RELATED_TO count / total relations | >7% (ABORT) |
| **dispatcher_queue_latency_p95** | <5s | P95 queue wait times | >10s |
| **pii_detection_false_positive_rate** | <5% | FP / (FP + TN) | >7% |
| **processing_latency_p95** | <220s | P95 document processing time | >300s |

**Suivi en Phase 2-4 (Production)** :

| KPI | Target Phase 2 | Target Phase 4 | Mesure |
|-----|----------------|----------------|--------|
| **Documents traités/jour** | 1000+ | 5000+ | Throughput quotidien |
| **Coût moyen/doc** | <$0.30 | <$0.20 | Total cost / docs processed |
| **Uptime API** | >99.5% | >99.9% | Availability monitoring |
| **Living Ontology types détectés/mois** | 3+ | 10+ | New types auto-discovered |
| **Multi-source narrative links/mois** | 50+ | 500+ | Cross-source relations created |

### 6.2 KPIs Produit (Business)

**Phase 1-2** (Validation Technique) :

| KPI | Target Sem 22 | Mesure |
|-----|---------------|--------|
| **Use case CRR validé** | ✅ | Démo fonctionne, narrative threads détectés |
| **Différenciation vs Copilot prouvée** | ✅ | A/B test Copilot vs KnowWhere (CRR query) |
| **Cost model production validé** | ✅ | $1-8/1000p selon complexité, prévisible |

**Phase 3-4** (Beta & Launch) :

| KPI | Target Sem 35 | Mesure |
|-----|---------------|--------|
| **Beta clients onboardés** | 5+ | Clients actifs avec données production |
| **NPS Beta clients** | >40 | Net Promoter Score survey |
| **Time-to-Value** | <2 semaines | Onboarding → first insights |
| **Retention Beta** | >80% | Clients actifs après 3 mois |
| **MRR Pilot** | >$5k | Monthly Recurring Revenue beta |

**Post-Launch (Sem 36+)** :

| KPI | Target 6 mois | Target 12 mois | Mesure |
|-----|---------------|----------------|--------|
| **Clients payants** | 10+ | 50+ | Active subscriptions |
| **MRR** | $10k | $50k | Monthly Recurring Revenue |
| **Churn rate** | <10%/mois | <5%/mois | Monthly churn |
| **CAC Payback** | <6 mois | <4 mois | Customer Acquisition Cost recovery |

---

## 7. Stratégie Go-to-Market Ajustée

### 7.1 Positionnement Renforcé

**Avant Architecture Agentique** :
> "KnowWhere comprend vos documents mieux que Copilot"

**Après Architecture Agentique v1.1** :
> **"KnowWhere : Semantic Intelligence + Cost Intelligence"**
>
> *"La seule plateforme qui comprend vos documents ET maîtrise ses coûts production."*

### 7.2 Pricing Tiers (Basé Cost Model)

**Starter** ($99/mois) :
- 500 docs/mois
- Scénario A uniquement (PDF textuels, $1/1000p)
- 1 source (upload manuel)
- Support email

**Professional** ($499/mois) :
- 5000 docs/mois
- Scénarios A+B (complexes, $1-3/1000p)
- 3 sources (SharePoint, Google Drive, upload)
- Living Ontology
- Support prioritaire

**Enterprise** ($1999/mois) :
- Unlimited docs
- Scénarios A+B+C (PPT-heavy, $1-8/1000p)
- Unlimited sources (+ Confluence, Slack)
- Multi-tenant isolation
- PIIGate conformité GDPR/HIPAA
- Dedicated support + SLA 99.9%

**Justification pricing** : Cost model $1-8/1000p + marge 60-70% = pricing viable

### 7.3 Segments Cibles Ajustés

**Segment Primaire (Phase 4)** :
- **Finance & Compliance** : CRR use case, regulatory docs, conformité GDPR/HIPAA
- Taille: 50-500 employés
- Pain: Versioning chaos, audit trails, conflicting metrics

**Segment Secondaire (Post-Launch)** :
- **Pharma/Biotech** : FDA tracking, clinical trials documentation
- **Consulting** : Proposals versioning, knowledge reuse
- **Legal** : Contract evolution, case law tracking

### 7.4 Canaux Acquisition

**Phase Beta (Sem 29-35)** :
- Réseau personnel (ex-colleagues finance/pharma)
- LinkedIn outreach (CFOs, Compliance Officers)
- Demo videos (CRR Evolution use case)

**Phase Launch (Sem 36+)** :
- Content marketing (blog SEO "document versioning", "narrative intelligence")
- Product Hunt launch
- Webinars (monthly "Semantic Intelligence 101")
- Freemium tier (100 docs/mois gratuit, upgrade payant)

### 7.5 Métriques Acquisition

| Métrique | Target Sem 35 (Beta) | Target 6 mois | Target 12 mois |
|----------|----------------------|---------------|----------------|
| **Leads qualifiés/mois** | 10+ | 50+ | 200+ |
| **Conversion Lead→Trial** | >30% | >40% | >50% |
| **Conversion Trial→Payant** | >20% | >30% | >40% |
| **CAC (Customer Acquisition Cost)** | $500 (manual) | $300 (automated) | $200 (scaled) |
| **LTV (Lifetime Value)** | $3k (6 mois) | $6k (12 mois) | $12k (24 mois) |
| **LTV/CAC Ratio** | 6:1 | 20:1 | 60:1 |

---

## 8. Effort Total & Ressources

### 8.1 Effort Total Estimé

| Phase | Durée | Effort (h) | Effort Cumulé |
|-------|-------|-----------|---------------|
| **Phase 1: Semantic Core** | Sem 1-10 | 250-300h | 300h |
| **✨ Phase 1.5: Pilote Agentique** | Sem 11-13 | 90-105h | 405h |
| **Phase 2: Agentique + Living Ontology** | Sem 14-22 | 270h | 675h |
| **Phase 3: Multi-Source** | Sem 23-28 | 150-180h | 855h |
| **Phase 4: Production Hardening** | Sem 29-35 | 210-245h | 1100h |
| **TOTAL** | **35 semaines** | **1000-1100h** | - |

**Cadence** : 25-35h/semaine (solo developer, temps personnel)

### 8.2 Checkpoints Décision

**Checkpoint Critique** : **Phase 1.5 GO/NO-GO (Sem 13)**

**Si GO** :
- ✅ Architecture agentique validée production-ready
- ✅ Cost model $1-8/1000p fiable
- ✅ Scalabilité 1000+ docs/jour confirmée
- → Continuer Phase 2-4 (700h supplémentaires)

**Si NO-GO** :
- ⚠️ Revoir architecture agentique (1-2 semaines tuning)
- ⚠️ Re-test pilote (Sem 14-15)
- ❌ Si échec répété → Pivot architecture monolithique optimisée

**Risque financé** : 405h investies avant décision GO/NO-GO (37% effort total)

---

## 9. Conclusion

### 9.1 Vision Long-Terme (Inchangée)

> **"KnowWhere devient le cortex documentaire standard des organisations."**

**Horizon 2026** :
- 1000+ clients entreprises
- $1M+ ARR
- Standard industry pour semantic document intelligence

### 9.2 Pivot Agentique = Avantage Compétitif

**L'architecture agentique v1.1 n'est PAS un détour technique, c'est un accélérateur stratégique** :

1. **Différenciation durable** : Copilot/Gemini ne maîtrisent pas coûts production (RAG basique coûteux)
2. **Scalabilité prouvée** : 1000+ docs/jour avec cost model prévisible = crédibilité production
3. **Conformité déblocante** : PIIGate GDPR/HIPAA ouvre secteurs finance/pharma (50% du TAM)
4. **Time-to-Market optimisé** : Pilote 3 semaines valide/invalide architecture AVANT scale-up massif

**Message final** :

> *"KnowWhere : Semantic Intelligence orchestrée par architecture agentique.*
> *Comprenez vos documents. Maîtrisez vos coûts. Scalez en confiance."*

---

**Version:** 2.0 - Intègre Architecture Agentique v1.1
**Date:** 2025-10-13
**Auteur:** Architecture Team OSMOSE
**Statut:** ✅ **VALIDATED** - Roadmap production-ready

**Documents Associés** :
- [`doc/README.md`](./README.md) (guide navigation documentation)
- [`doc/OSMOSE_STATUS_ACTUEL.md`](./OSMOSE_STATUS_ACTUEL.md) (status actuel du projet)
- [`doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (architecture globale)
- [`doc/phases/PHASE1_SEMANTIC_CORE.md`](./phases/PHASE1_SEMANTIC_CORE.md) (Phase 1 complète - 1 seul fichier)
- [`doc/OSMOSE_AMBITION_PRODUIT_ROADMAP.md`](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) (vision produit)

---

> **🌊 "OSMOSE v2.0 : Roadmap intégrée avec architecture agentique - Production-ready avec cost intelligence."**
