# Analyse de la Vision Stratégique - Transition vers KB Hybride Gouvernée

**Date**: 30 septembre 2025
**Auteur**: Claude Code
**Contexte**: Analyse du document de vision stratégique pour passer d'un POC Graphiti à une plateforme KB industrielle

---

## 📋 RÉSUMÉ EXÉCUTIF

### Situation Actuelle (État des Lieux)

**Ce qui fonctionne** ✅:
- Ingestion multi-format (PPTX, PDF, Excel) opérationnelle
- Recherche sémantique dans Qdrant fonctionnelle
- Pipeline LLM avec multi-provider (OpenAI, Anthropic)
- Interface utilisateur Next.js moderne
- Phase 0 Graphiti validée (5/5 critères)

**Problèmes identifiés** ❌:
1. **Schéma Qdrant mélangé**: Métadonnées SAP couplées au core → non généralisable
2. **Knowledge Graph sous-exploité**: Alimenté manuellement, peu d'entités/relations
3. **Pas de gouvernance des facts**: Impossible de prioriser validé vs proposé
4. **Pas de Query Understanding**: Routage basique, pas d'analyse d'intent
5. **Canonicalisation tardive**: Scripts post-ingestion (ex: fix SAP solutions)
6. **Pas de related_node_ids**: Qdrant et KG découplés (pas de RAG hybride)

### Vision Cible (Ambition)

**Plateforme KB hybride** avec:
- **Qdrant**: Mémoire textuelle (chunks + métadonnées universelles)
- **Graphiti/Neo4j**: Mémoire métier (entités, relations, temporalité, conflits)
- **Extraction automatique**: Entités & relations candidates à l'ingestion
- **Gouvernance humaine**: Cycle proposed → approved → exploité
- **RAG graph-aware**: Priorisation facts validés + complément contexte

**Valeur attendue**:
- **Pertinence**: Réponses graph-aware meilleures
- **Traçabilité**: Origine des infos + statut de confiance
- **Multi-domaine**: SAP aujourd'hui, Retail/Pharma demain
- **Time-to-value**: Onboarding nouveau domaine ≤ 1 semaine

---

## 🎯 GAP ANALYSIS - État Actuel vs Cible

### 1. Architecture Données

| Composant | État Actuel | Cible | Gap |
|-----------|-------------|-------|-----|
| **Schéma Qdrant** | Flat payload mélangé SAP+core | `core` + `custom_metadata` + `sys` + `related_node_ids` | 🔴 Refactor majeur |
| **Knowledge Graph** | Manuel, peu alimenté | Auto-extraction + gouvernance | 🔴 Pipeline complet à créer |
| **Liens Qdrant↔KG** | Aucun (`related_node_ids` absents) | Bi-directionnel avec related_node_ids | 🔴 Schéma + logique |
| **Dates** | Format mixte (source_date non-ISO) | ISO 8601 systématique | 🟡 Migration script |
| **Types** | Hétérogènes (arrays/strings mixtes) | Pydantic strict | 🟡 Validation + migration |

### 2. Ingestion & Extraction

| Fonctionnalité | État Actuel | Cible | Gap |
|----------------|-------------|-------|-----|
| **Extraction entités** | Manuelle (config SAP hardcodée) | Auto NER/LLM → proposed facts | 🔴 Pipeline multi-agent |
| **Canonicalisation** | Post-ingestion (scripts correctifs) | En amont avec fuzzy matching | 🟡 Déplacement logique |
| **Gouvernance facts** | Aucune | Admin Studio (approve/reject/merge) | 🔴 UI + workflow complet |
| **Provenance** | Basique (source_name) | Chunk_id + confidence + timestamp | 🟡 Extension métadonnées |

### 3. Recherche & Génération

| Fonctionnalité | État Actuel | Cible | Gap |
|----------------|-------------|-------|-----|
| **Query Understanding** | Aucun (recherche directe) | Intent + filtres + plan d'exécution | 🔴 Nouveau module |
| **Routage** | Qdrant uniquement | KG / Qdrant / Hybride selon intent | 🔴 Router intelligent |
| **Ranking** | Vector similarity seule | α*vector + β*graph + γ*metadata | 🔴 Graph-aware ranking |
| **Génération** | Chunks bruts | Facts approved first + disclaimer | 🟡 Prompt engineering |

### 4. Gouvernance & UX

| Fonctionnalité | État Actuel | Cible | Gap |
|----------------|-------------|-------|-----|
| **Admin Studio** | Aucun | File entities, canonicalisation, conflicts, ontologies | 🔴 Interface complète |
| **Validation workflow** | Aucun | proposed → review → approved/rejected | 🔴 Backend + frontend |
| **Ontologies assistées** | Config YAML manuelle | LLM-assisted + validation | 🔴 Wizard LLM |
| **Observabilité** | Logs basiques | Métriques KG, qualité extraction, couverture | 🟡 Dashboard monitoring |

---

## 📊 ALIGNEMENT AVEC PHASE 0-3 GRAPHITI

### Ce qui a été fait (Phase 0-3)

✅ **Phase 0 - Infrastructure**:
- Docker Compose Graphiti fonctionnel
- SDK graphiti-core opérationnel
- Multi-tenant avec group_id
- Health checks complets

✅ **Phase 2 - Knowledge Graph Multi-Tenant**:
- Création tenants
- Isolation par group_id
- API CRUD facts/entities/relations

✅ **Phase 3 - Facts Gouvernance**:
- Workflow `proposed → approved`
- Timeline facts avec bi-temporalité
- Détection conflits (CONTRADICTS)

### Ce qui manque (Phases 4-5 + Roadmap stratégique)

🔴 **Intégration Qdrant ↔ Graphiti**:
- `related_node_ids` dans payload Qdrant
- Création automatique facts à l'ingestion
- Graph-aware ranking

🔴 **Query Understanding**:
- Analyse intent (get_metadata / graph_query / informational)
- Routage intelligent KG/Qdrant/hybride

🔴 **Admin Studio UI**:
- File d'attente entities proposed
- Canonicalisation avec suggestions
- Conflicts center
- Ontologies wizard

🔴 **Multi-domaine**:
- Abstraction SAP dans `custom_metadata`
- Ontologies par domaine (SAP, Retail, Pharma)
- Time-to-onboard ≤ 1 semaine

---

## 🚀 ROADMAP STRATÉGIQUE - COURT TERME (2-4 semaines)

### Sprint 1-2: Core Schema & Ingestion Refactor

**Objectif**: Stabiliser le schéma Qdrant et préparer l'intégration KG

#### Tâches

1. **Créer `schema.py` (Pydantic)**
   - `CoreMetadata`: document.* (source_name, source_type, source_date_iso, etc.), chunk.*, language, ingested_at
   - `CustomMetadata`: Dict libre pour domaine (SAP, Retail, etc.)
   - `SysMetadata`: tags_tech, prompt_meta, versions, parse_status
   - **`related_node_ids: list[str]`** (init vide [])
   - Validation stricte Pydantic

   **Fichier**: `src/knowbase/ingestion/schema.py`

2. **Refactor pipelines ingestion**
   - PPTX pipeline: pptx_pipeline.py:1023-1056
   - PDF pipeline: utiliser schema.py
   - Excel pipeline: utiliser schema.py
   - Déplacer solution.* → custom_metadata.sap.*
   - Ajouter related_node_ids: []
   - Normaliser dates en ISO 8601

   **Fichiers**: `pptx_pipeline.py`, `pdf_pipeline.py`, `excel_pipeline.py`

3. **Script migration Qdrant**
   - Scanner collection existante
   - Restructurer payload: core + custom + sys + related_node_ids
   - Valider types et dates
   - Mode dry-run + rollback

   **Fichier**: `scripts/migrate_qdrant_schema_v2.py`

4. **Tests validation**
   - pytest sur schema.py (validation stricte)
   - Tests ingestion avec nouveau schéma
   - Vérifier backward compatibility lecture

   **Fichiers**: `tests/ingestion/test_schema.py`

**KPIs Sprint 1-2**:
- ≥95% conformité schéma (CI check)
- Migration 100% collection sans perte
- Tests ingestion passent

---

### Sprint 3: Query Understanding (MVP)

**Objectif**: Analyser intent et router intelligemment

#### Tâches

1. **Endpoint `/api/parse_query`**
   - Input: `{"query": "string"}`
   - Output: `{"intent": "graph_query|get_metadata|informational", "filters": {...}, "keywords": [...]}`
   - Logique: patterns regex + LLM léger (gpt-4o-mini)

   **Fichier**: `src/knowbase/api/routers/query_understanding.py`

2. **Router intelligent**
   - `get_metadata` / `locate_slide` → Qdrant (filtres core)
   - `graph_query` / `compare` / `verify_claim` → Graphiti + Qdrant contexte
   - `informational` → Hybride (ranking multi-source)

   **Fichier**: `src/knowbase/api/services/query_router.py`

3. **Tests intent detection**
   - Dataset queries annotées (20-30 exemples)
   - Précision ≥85% sur intent

   **Fichier**: `tests/api/test_query_understanding.py`

**KPIs Sprint 3**:
- Intent correct ≥85% cas
- Latence parse_query <200ms

---

### Sprint 4-5: Extraction Auto & Facts-First Generation

**Objectif**: Peupler KG automatiquement + génération facts-first

#### Tâches

1. **Pipeline extraction entités**
   - À l'ingestion: LLM extrait entités candidates du chunk
   - Format: `{"name": "...", "type": "...", "confidence": 0.XX}`
   - Écriture facts `status="proposed"` dans Graphiti
   - Lien: ajouter `fact_id` dans `related_node_ids` du chunk Qdrant

   **Fichier**: `src/knowbase/ingestion/extractors/entity_extractor.py`

2. **Pipeline extraction relations**
   - LLM extrait triplets: (entity1, relation, entity2)
   - Confidence + provenance (chunk_id)
   - Écriture relations `status="proposed"`

   **Fichier**: `src/knowbase/ingestion/extractors/relation_extractor.py`

3. **Génération facts-first**
   - Query Understanding détecte intent `informational`
   - Recherche facts APPROVED dans Graphiti
   - Si trouvé: afficher avec source + date + ⭐ badge "Validé"
   - Complément: chunks Qdrant contextuels avec disclaimer "Non validé"

   **Fichier**: `src/knowbase/api/services/generation.py`

4. **Tests end-to-end**
   - Ingérer doc → vérifier facts proposed créés
   - Query facts-first → vérifier priorisation approved

   **Fichier**: `tests/integration/test_facts_first.py`

**KPIs Sprint 4-5**:
- ≥80% requêtes factuelles résolues par facts approved
- Latence ingestion stable (+20% max)
- Extraction entities ≥70% rappel (sur échantillon annoté)

---

## 🎯 ROADMAP STRATÉGIQUE - MOYEN TERME (6-12 semaines)

### Sprint 6-8: Admin Studio UI

**Objectif**: Interface gouvernance facts

#### Fonctionnalités

1. **File d'attente entities proposed**
   - Liste paginée entities status="proposed"
   - Tri par confidence, source, domaine
   - Actions: Approve / Reject / Merge

2. **Canonicalisation assistée**
   - Pour chaque entity, suggérer top-3 canons existants (fuzzy matching)
   - Merge 1-clic avec feedback
   - Historique merge (traçabilité)

3. **Conflicts center**
   - Liste facts CONTRADICTS/OVERRIDES
   - Timeline bi-temporelle
   - Résolution manuelle

4. **Ontologies wizard**
   - Import doc "seed" → LLM propose classes/relations
   - Validation par domaine expert
   - Export dictionnaire YAML

**Fichiers**:
- `frontend/src/app/governance/*` (pages React)
- `src/knowbase/api/routers/governance.py` (backend)

**KPIs Sprint 6-8**:
- −40% faux positifs entities
- −50% temps revue/100 entities
- Onboarding domaine ≤ 2 semaines

---

### Sprint 9-12: Graph-Aware Ranking & Event-Driven

**Objectif**: RAG hybride performant + scalabilité

#### Fonctionnalités

1. **Graph-aware ranking**
   - Score = α*vector + β*graph_proximity + γ*metadata_boost
   - Graph proximity: Personalized PageRank sur sous-graphe (entities détectées)
   - Reranking final avec LLM si ambiguïté

2. **Event-driven pipeline**
   - Événements: `chunk.ingested`, `entities.proposed`, `entity.approved`, `kg.updated`
   - Broker: Redis Streams (léger) ou Kafka (volume)
   - Workers: extraction async, validation batch, réindexation

3. **Active learning**
   - Dataset reject/merge → entraîner classifieur léger
   - Fine-tuning prompts extraction sur erreurs récurrentes

**Fichiers**:
- `src/knowbase/rag/graph_ranker.py`
- `src/knowbase/events/broker.py`
- `src/knowbase/ml/active_learner.py`

**KPIs Sprint 9-12**:
- +20-30% NDCG@10 grâce graph-aware
- Latence extraction async (non-blocking)
- Onboarding domaine ≤ 1 semaine

---

## 🔄 PLAN DE TRANSITION - PRIORISATION

### Principe directeur

**"Stabiliser → Valider → Industrialiser"**

1. **Court terme (2-4 semaines)**: Poser les fondations solides
   - Schéma Qdrant universel
   - Migration collection
   - Query Understanding MVP
   - Extraction auto + facts-first

2. **Moyen terme (6-12 semaines)**: Prouver la valeur
   - Admin Studio UI
   - Graph-aware ranking
   - Multi-domaine (2ème domaine test)

3. **Long terme (3-6 mois)**: Scaler
   - Event-driven
   - Active learning
   - Observabilité avancée

### Pré-requis immédiats

🔴 **CRITIQUE** - À faire AVANT tout développement:

1. **Geler la branche `feat/graphiti-integration`**
   - Commit final Phase 3
   - Tag `v0.3.0-graphiti-phase3`
   - NE PAS merger dans main encore

2. **Créer branche `feat/kb-hybrid-v2`**
   - Partir de main (avec fix SAP)
   - Intégrer Phase 0-3 Graphiti (cherry-pick sélectif)
   - Appliquer refactor schéma

3. **Documenter architecture cible**
   - ADR (Architecture Decision Record) pour schema.py
   - Diagrammes Qdrant ↔ Graphiti
   - Migration plan détaillé

### Risques & Mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| Rigidification schéma trop SAP | 🔴 Élevé | Moyenne | Core minimal universel + custom |
| Bruit extraction entities | 🟡 Moyen | Élevée | Multi-agent + validation humaine |
| Dette migration Qdrant | 🔴 Élevé | Faible | Script unique, test échantillon, rollback |
| Sur-complexité infra | 🟡 Moyen | Moyenne | Feature-flags, event-driven phase 2 |

---

## 📝 ACTIONS IMMÉDIATES RECOMMANDÉES

### Étape 1: Validation de la vision (2h)

1. **Reviewer ce document** avec stakeholders
2. **Prioriser les sprints** selon business value
3. **Valider les KPIs** (réalistes ?)

### Étape 2: Setup branche & architecture (1 jour)

1. **Créer `feat/kb-hybrid-v2`** depuis main
2. **Rédiger ADR** `doc/adr/001-qdrant-schema-refactor.md`
3. **Designer schema.py** (draft Pydantic)

### Étape 3: POC schema migration (2-3 jours)

1. **Implémenter schema.py** avec tests
2. **Refactor 1 pipeline** (PPTX) comme référence
3. **Script migration** sur échantillon (10% collection)
4. **Valider** aucune perte de données

### Étape 4: Planning Sprint 1 (1 jour)

1. **Décomposer Sprint 1** en issues GitHub
2. **Estimer** effort (story points)
3. **Assigner** priorités P0/P1/P2

---

## 🎯 ALIGNEMENT AVEC PHASES GRAPHITI

### Phase 0-3: ACQUIS ✅

Ce qui a été validé et reste utilisable:
- Infrastructure Docker Graphiti
- SDK graphiti-core fonctionnel
- Multi-tenant avec group_id
- Workflow facts gouvernance (proposed → approved)
- API CRUD facts/entities/relations

### Phase 4-5: À RÉORIENTER 🔄

**Phase 4 originale** (Ingestion → KG):
- ✅ Garder: Extraction auto entities à l'ingestion
- 🔄 Adapter: Intégrer avec nouveau schema.py
- ➕ Ajouter: related_node_ids Qdrant ↔ Graphiti

**Phase 5 originale** (RAG hybride):
- ✅ Garder: Graph-aware ranking
- 🔄 Adapter: Intégrer Query Understanding
- ➕ Ajouter: Facts-first generation

### Roadmap stratégique: EXTENSION 🚀

Au-delà Phase 0-5, la roadmap stratégique ajoute:
- Multi-domaine (ontologies assistées)
- Admin Studio complet
- Event-driven (scalabilité)
- Active learning

---

## 📊 MÉTRIQUES DE SUCCÈS

### Court Terme (2-4 semaines)

- ✅ Schéma Qdrant universel déployé (≥95% conformité CI)
- ✅ Migration collection 100% sans perte
- ✅ Query Understanding ≥85% précision intent
- ✅ ≥80% requêtes factuelles résolues par facts approved
- ✅ Latence ingestion stable (+20% max acceptable)

### Moyen Terme (6-12 semaines)

- ✅ Admin Studio opérationnel (−50% temps revue)
- ✅ Graph-aware ranking (+20% NDCG@10)
- ✅ 2ème domaine onboardé (≤ 2 semaines)
- ✅ −40% faux positifs extraction

### Long Terme (3-6 mois)

- ✅ Event-driven en production
- ✅ Active learning actif (fine-tuning continu)
- ✅ Onboarding domaine ≤ 1 semaine
- ✅ Satisfaction utilisateur ≥85% (survey)

---

## 🚀 CONCLUSION

### Vision réaliste et ambitieuse

La roadmap stratégique proposée est **alignée** avec:
- ✅ Les acquis Phase 0-3 Graphiti (infrastructure solide)
- ✅ Les besoins business (multi-domaine, time-to-value)
- ✅ Les bonnes pratiques (human-in-the-loop, observabilité)

**Mais elle nécessite**:
- 🔴 Refactor majeur schéma Qdrant (dette technique)
- 🔴 Développements significatifs (Query Understanding, Admin Studio)
- 🟡 Effort soutenu 2-4 mois (sprints réguliers)

### Recommandation finale

**GO** avec conditions:
1. **Valider la vision** avec stakeholders (priorisation business)
2. **Commencer par les fondations** (schema.py + migration)
3. **Itérer en sprints courts** (2 semaines) avec démos régulières
4. **Mesurer la valeur** dès Sprint 3 (Query Understanding + facts-first)
5. **Pivoter si nécessaire** selon feedback utilisateurs

**Next step**: Créer branche `feat/kb-hybrid-v2` et démarrer Sprint 1 (schema.py) ? 🚀

---

**Document vivant** - À mettre à jour après chaque sprint.
