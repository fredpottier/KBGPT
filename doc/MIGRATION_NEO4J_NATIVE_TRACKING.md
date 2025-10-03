# Migration Neo4j Native - Tracking & Planning

**Date début** : 2025-10-03
**Statut** : 🟡 En préparation
**Branche cible** : `feat/neo4j-native` (depuis `main`)

---

## 🎯 Objectif Global

Migrer de l'architecture Graphiti vers une solution **Neo4j Native + Custom Layer** pour implémenter la gouvernance intelligente des facts métier avec détection de conflits fiable.

**Décision stratégique** : Approche "Clean Slate" pour repartir sur une base de code propre et maintenable.

---

## 📊 Vue d'Ensemble des Phases

| Phase | Objectif | Durée | Statut |
|-------|----------|-------|--------|
| **Phase 0** | Clean Slate Setup & Restructuration Infrastructure | 1 jour | ⏳ En attente |
| **Phase 1** | POC Neo4j Facts (Validation Technique) | 2 jours | ⏳ En attente |
| **Phase 2** | Migration APIs & Services Facts | 3 jours | ⏳ En attente |
| **Phase 3** | Pipeline Ingestion & Détection Conflits | 3 jours | ⏳ En attente |
| **Phase 4** | UI Admin Gouvernance Facts | 3 jours | ⏳ En attente |
| **Phase 5** | Tests E2E & Documentation | 2 jours | ⏳ En attente |
| **Phase 6** | Décommission Graphiti & Cleanup | 1 jour | ⏳ En attente |

**Durée totale estimée** : **15 jours** (3 semaines)

---

## 📋 PHASE 0 : Clean Slate Setup & Restructuration Infrastructure

**Durée** : 1 jour
**Statut** : ⏳ En attente
**Responsable** : Architecture & DevOps

### Objectifs

1. ✅ Créer branche propre `feat/neo4j-native` depuis `main`
2. ✅ Restructurer Docker Compose (séparation infra/app)
3. ✅ Migrer sélectivement code réutilisable (modules utilitaires)
4. ✅ Créer structure Neo4j custom (`neo4j_custom/`, `facts/`)
5. ✅ Archiver branches obsolètes (tags)
6. ✅ Mettre à jour documentation North Star

### Critères d'Achèvement

- [ ] Branche `feat/neo4j-native` créée et poussée sur remote
- [ ] Docker séparé en 2 fichiers :
  - `docker-compose.infra.yml` (Qdrant, Redis, Neo4j, Postgres)
  - `docker-compose.app.yml` (App, Frontend, Worker)
- [ ] Modules utilitaires migrés sans dépendances Graphiti
- [ ] Structure `src/knowbase/neo4j_custom/` et `src/knowbase/facts/` créée
- [ ] Tags archive créés : `archive/zep-multiuser`, `archive/graphiti-integration`, `archive/north-star-phase0`
- [ ] Documentation `NORTH_STAR_NEO4J_NATIVE.md` créée
- [ ] Fichier tracking par phase créé (`PHASE0_DETAILS.md`, `PHASE1_DETAILS.md`, etc.)

### Tâches Détaillées

#### 0.1 - Création Branche Clean Slate
**Durée** : 30 min

```bash
# Partir de main propre
git checkout main
git pull origin main

# Créer branche neo4j-native
git checkout -b feat/neo4j-native
git push -u origin feat/neo4j-native
```

**Livrable** : Branche vide prête à recevoir code propre

---

#### 0.2 - Restructuration Docker Compose
**Durée** : 2h

**Objectif** : Séparer infrastructure (stateful) et application (stateless) pour gestion indépendante.

**Ancien modèle** (problème) :
```yaml
# docker-compose.yml (tout mélangé)
services:
  qdrant:     # Infra - jamais touché
  redis:      # Infra - jamais touché
  app:        # App - redémarré souvent
  worker:     # App - redémarré souvent
  frontend:   # App - redémarré souvent
```
→ `docker-compose restart app` redémarre aussi Qdrant/Redis (inutile, lent)

**Nouveau modèle** (solution) :
```yaml
# docker-compose.infra.yml
services:
  qdrant:     # Bases de données
  redis:      # Cache/Queue
  neo4j:      # Knowledge Graph
  postgres:   # Metadata (futur)

# docker-compose.app.yml
services:
  app:        # FastAPI backend
  worker:     # RQ worker
  frontend:   # Next.js UI
```

**Commandes** :
```bash
# Démarrer infra (1 fois au boot machine)
docker-compose -f docker-compose.infra.yml up -d

# Redémarrer app (développement)
docker-compose -f docker-compose.app.yml restart app

# Tout arrêter
docker-compose -f docker-compose.infra.yml down
docker-compose -f docker-compose.app.yml down
```

**Fichiers à créer** :
- `docker-compose.infra.yml` (infrastructure stateful)
- `docker-compose.app.yml` (application stateless)
- `docker-compose.override.yml` (dev local overrides)
- `.env.example` (variables template)
- `scripts/start-infra.sh` (helper script)
- `scripts/start-app.sh` (helper script)
- `scripts/restart-app.sh` (helper script)

**Livrable** : Docker séparé fonctionnel avec scripts helpers

---

#### 0.3 - Migration Sélective Code Réutilisable
**Durée** : 2h

**Modules à migrer** (0 dépendance Graphiti) :

**Common utilities** :
- `src/knowbase/common/logging.py` ✅
- `src/knowbase/common/metrics.py` ✅
- `src/knowbase/common/pagination.py` ✅
- `src/knowbase/common/auth.py` ✅
- `src/knowbase/common/circuit_breaker.py` ✅
- `src/knowbase/common/redis_client_resilient.py` ✅
- `src/knowbase/common/tracing.py` ✅
- `src/knowbase/common/input_validation.py` ✅

**Audit & Observabilité** :
- `src/knowbase/audit/*` (tout) ✅

**Ingestion base** (sans KG) :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py` ✅
- `src/knowbase/ingestion/deduplication.py` ✅
- `src/knowbase/ingestion/queue/jobs.py` ✅

**Configuration** :
- `config/llm_models.yaml` ✅
- `config/prompts.yaml` ✅
- `config/document_types.yaml` ✅

**Modules à NE PAS migrer** (dépendances Graphiti) :
- ❌ `src/knowbase/graphiti/*` (tout)
- ❌ `src/knowbase/search/hybrid_search.py` (utilise GraphitiProxy)
- ❌ `src/knowbase/ingestion/pipelines/pptx_pipeline_kg.py` (à réécrire pour Neo4j)

**Script migration** :
```bash
# Exécuter scripts/migrate_to_neo4j_clean.sh
bash scripts/migrate_to_neo4j_clean.sh
```

**Livrable** : Code utilitaire migré sans dépendances Graphiti

---

#### 0.4 - Création Structure Neo4j Custom
**Durée** : 1h

**Structure cible** :
```
src/knowbase/
├── neo4j_custom/           # Neo4j native layer
│   ├── __init__.py
│   ├── client.py           # Neo4j driver wrapper
│   ├── schemas.py          # Cypher schemas (Facts, Entities)
│   ├── queries.py          # Requêtes Cypher réutilisables
│   └── migrations.py       # Schema migrations
├── facts/                  # Facts governance layer
│   ├── __init__.py
│   ├── service.py          # FactsService (CRUD, gouvernance)
│   ├── conflict_detector.py # Détection conflits
│   ├── schemas.py          # Pydantic models
│   ├── timeline.py         # Timeline temporelle
│   └── validators.py       # Validation facts
├── api/routers/
│   └── facts.py            # Endpoints /api/facts/*
tests/
├── neo4j_custom/           # Tests Neo4j layer
│   ├── test_client.py
│   └── test_queries.py
├── facts/                  # Tests facts service
│   ├── test_service.py
│   ├── test_conflict_detector.py
│   └── test_timeline.py
```

**Commandes** :
```bash
mkdir -p src/knowbase/neo4j_custom
mkdir -p src/knowbase/facts
mkdir -p tests/neo4j_custom
mkdir -p tests/facts

# Créer fichiers __init__.py
touch src/knowbase/neo4j_custom/__init__.py
touch src/knowbase/facts/__init__.py
```

**Livrable** : Structure vide prête à recevoir implémentation

---

#### 0.5 - Archivage Branches Obsolètes
**Durée** : 30 min

**Branches à archiver** :
- `feat/zep-multiuser` (architecture Zep abandonnée)
- `feat/graphiti-integration` (architecture Graphiti abandonnée)
- `feat/north-star-phase0` (code Graphiti à remplacer)

**Stratégie** : Tags Git (préserve code sans polluer branches)

```bash
# Créer tags archive
git tag archive/zep-multiuser feat/zep-multiuser
git tag archive/graphiti-integration feat/graphiti-integration
git tag archive/north-star-phase0 feat/north-star-phase0

# Pousser tags sur remote
git push origin --tags

# Supprimer branches locales
git branch -D feat/zep-multiuser
git branch -D feat/graphiti-integration
git branch -D feat/north-star-phase0

# (Optionnel) Supprimer branches remote après validation
# git push origin --delete feat/zep-multiuser
# git push origin --delete feat/graphiti-integration
# git push origin --delete feat/north-star-phase0
```

**Récupération ultérieure** (si besoin) :
```bash
git checkout archive/graphiti-integration
```

**Livrable** : Branches archivées, projet allégé

---

#### 0.6 - Documentation North Star Neo4j
**Durée** : 2h

**Fichiers à créer** :

1. **`doc/NORTH_STAR_NEO4J_NATIVE.md`** (vision globale)
   - Architecture cible Neo4j custom
   - Séparation responsabilités (Qdrant / Neo4j / Facts)
   - Schémas Cypher Facts
   - Workflows gouvernance
   - Principes non négociables

2. **`doc/MIGRATION_NEO4J_NATIVE_PHASE0_DETAILS.md`** (Phase 0 détaillée)
3. **`doc/MIGRATION_NEO4J_NATIVE_PHASE1_DETAILS.md`** (Phase 1 POC)
4. **`doc/MIGRATION_NEO4J_NATIVE_PHASE2_DETAILS.md`** (Phase 2 APIs)
5. **`doc/MIGRATION_NEO4J_NATIVE_PHASE3_DETAILS.md`** (Phase 3 Ingestion)
6. **`doc/MIGRATION_NEO4J_NATIVE_PHASE4_DETAILS.md`** (Phase 4 UI)
7. **`doc/MIGRATION_NEO4J_NATIVE_PHASE5_DETAILS.md`** (Phase 5 Tests)
8. **`doc/MIGRATION_NEO4J_NATIVE_PHASE6_DETAILS.md`** (Phase 6 Cleanup)

**Template fichier phase** :
```markdown
# Phase X : [Nom Phase]

**Durée** : X jours
**Statut** : ⏳ En attente
**Dépendances** : Phase X-1 complétée

## Objectifs
- Objectif 1
- Objectif 2

## Critères d'Achèvement
- [ ] Critère 1
- [ ] Critère 2

## Tâches Détaillées
### X.1 - Tâche 1
**Durée** : Xh
**Livrable** : ...

## Risques & Mitigation
| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|

## Tests de Validation
- Test 1
- Test 2

## Métriques de Succès
- Métrique 1 : Objectif
- Métrique 2 : Objectif
```

**Livrable** : Documentation complète migration

---

### Impacts sur l'Existant

**Code supprimé** :
- ❌ `src/knowbase/graphiti/*` (tout)
- ❌ `docker-compose.graphiti.yml`
- ❌ Scripts migration Graphiti
- ❌ Documentation Graphiti

**Code créé** :
- ✅ `src/knowbase/neo4j_custom/*`
- ✅ `src/knowbase/facts/*`
- ✅ `docker-compose.infra.yml`
- ✅ `docker-compose.app.yml`
- ✅ Documentation Neo4j native

**Code migré** :
- ♻️ Modules utilitaires (logging, metrics, audit, etc.)
- ♻️ Ingestion pipeline base
- ♻️ Configuration LLM/prompts

---

### Tests de Validation Phase 0

**Test 1 : Branche propre créée**
```bash
git branch --show-current
# Attendu: feat/neo4j-native
```

**Test 2 : Docker infra séparé fonctionne**
```bash
docker-compose -f docker-compose.infra.yml up -d
docker ps | grep -E "qdrant|redis|neo4j"
# Attendu: 3+ containers running (qdrant, redis, neo4j)
```

**Test 3 : Docker app séparé fonctionne**
```bash
docker-compose -f docker-compose.app.yml up -d
docker ps | grep -E "app|worker|frontend"
# Attendu: 3 containers running (app, worker, frontend)
```

**Test 4 : Redémarrage app sans infra**
```bash
docker-compose -f docker-compose.app.yml restart app
docker ps | grep qdrant | grep "Up"
# Attendu: qdrant toujours Up (pas redémarré)
```

**Test 5 : Modules utilitaires importables**
```bash
docker-compose -f docker-compose.app.yml exec app python -c "
from knowbase.common.logging import setup_logging
from knowbase.audit.audit_logger import AuditLogger
print('Imports OK')
"
# Attendu: "Imports OK"
```

**Test 6 : Structure Neo4j créée**
```bash
ls -la src/knowbase/neo4j_custom/
ls -la src/knowbase/facts/
# Attendu: Répertoires existent avec __init__.py
```

**Test 7 : Tags archive créés**
```bash
git tag | grep archive
# Attendu:
# archive/zep-multiuser
# archive/graphiti-integration
# archive/north-star-phase0
```

---

### Risques & Mitigation Phase 0

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Migration code rate fichier utilitaire | Faible (10%) | Moyen | Revue code systématique avant migration |
| Docker séparé casse dépendances inter-services | Moyen (20%) | Élevé | Tester communication app→qdrant, app→redis avant merge |
| Perte code utile lors cleanup | Faible (5%) | Élevé | Tags archive préservent tout l'historique |
| Documentation incomplète | Moyen (20%) | Moyen | Template phase détaillé + review pair |

---

### Métriques de Succès Phase 0

| Métrique | Objectif | Mesure |
|----------|----------|--------|
| **Temps migration** | < 1 jour | Réel: ___h |
| **Tests validation passés** | 7/7 | Réel: ___/7 |
| **Modules utilitaires migrés** | 100% (sans dépendance Graphiti) | Réel: ___% |
| **Docker infra startup time** | < 30s | Réel: ___s |
| **Docker app startup time** | < 20s | Réel: ___s |
| **Taille branche** (commits) | < 10 commits Phase 0 | Réel: ___ commits |

---

## 📅 Timeline Macro

```
Semaine 1 (Jour 1-5)
├── Jour 1: Phase 0 - Clean Slate Setup ✅
├── Jour 2: Phase 1 - POC Neo4j Facts (Jour 1/2)
├── Jour 3: Phase 1 - POC Neo4j Facts (Jour 2/2) + Validation
├── Jour 4: Phase 2 - APIs Facts (Jour 1/3)
└── Jour 5: Phase 2 - APIs Facts (Jour 2/3)

Semaine 2 (Jour 6-10)
├── Jour 6: Phase 2 - APIs Facts (Jour 3/3) + Tests
├── Jour 7: Phase 3 - Pipeline Ingestion (Jour 1/3)
├── Jour 8: Phase 3 - Pipeline Ingestion (Jour 2/3)
├── Jour 9: Phase 3 - Détection Conflits (Jour 3/3)
└── Jour 10: Phase 4 - UI Admin (Jour 1/3)

Semaine 3 (Jour 11-15)
├── Jour 11: Phase 4 - UI Admin (Jour 2/3)
├── Jour 12: Phase 4 - UI Admin (Jour 3/3) + Tests
├── Jour 13: Phase 5 - Tests E2E (Jour 1/2)
├── Jour 14: Phase 5 - Documentation (Jour 2/2)
└── Jour 15: Phase 6 - Cleanup & Décommission Graphiti
```

---

## 🎯 Critères de Passage Entre Phases

**Règle stricte** : Aucune phase n'est validée tant que tous les critères ne sont pas atteints.

**Gate Phase 0 → Phase 1** :
- ✅ Branche `feat/neo4j-native` créée et pushed
- ✅ Docker séparé (infra + app) fonctionnel
- ✅ 7/7 tests validation Phase 0 passés
- ✅ Documentation North Star créée
- ✅ Code review approuvé (pair review)

**Gate Phase 1 → Phase 2** :
- ✅ POC Neo4j Facts fonctionnel (insert, query, conflict detection)
- ✅ Performance < 50ms confirmée
- ✅ Équipe confortable avec Cypher
- ✅ Tests POC passés (insert, query, detect conflicts)

**Gates suivants** : Définis dans fichiers phase détaillés

---

## 📊 Indicateurs Projet Global

| Indicateur | Cible | Actuel |
|------------|-------|--------|
| **% Phases complétées** | 100% (6/6) | 0% (0/6) |
| **Jours écoulés** | 15 jours | 0 jours |
| **Tests validation passés** | 100% | ___% |
| **Performance détection conflits** | < 50ms | ___ ms |
| **Couverture tests** | > 80% | ___% |
| **Dette technique réduite** | -100% (vs Graphiti) | ___% |

---

## 🚀 Prochaines Actions

### Immédiat (Aujourd'hui)
1. ✅ Valider ce plan de migration
2. ⏳ Lancer Phase 0 (Clean Slate Setup)

### Demain
3. ⏳ Finaliser Phase 0
4. ⏳ Démarrer Phase 1 (POC Neo4j)

---

## 📚 Documents Associés

- **Vision globale** : `doc/NORTH_STAR_NEO4J_NATIVE.md` (à créer)
- **Décision migration** : `doc/DECISION_GRAPHITI_ALTERNATIVES_SYNTHESE.md`
- **Analyse alternatives** : `doc/GRAPHITI_ALTERNATIVES_ANALYSIS_RESULTS.md`
- **Phase 0 détails** : `doc/MIGRATION_NEO4J_NATIVE_PHASE0_DETAILS.md` (à créer)
- **Phases suivantes** : `doc/MIGRATION_NEO4J_NATIVE_PHASE{1-6}_DETAILS.md` (à créer)

---

**Créé le** : 2025-10-03
**Dernière mise à jour** : 2025-10-03
**Version** : 1.0
**Statut** : 🟡 En préparation - Attente validation
