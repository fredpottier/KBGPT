# WIKI OSMOSIS — Document de Prescription Complète

**Version:** 1.0
**Date:** 2026-03-11
**Statut:** Document de référence pour transformation Wikipedia
**Auteur:** Équipe OSMOSIS

---

## Table des Matières

1. [Vision et Contexte du Projet](#1-vision-et-contexte-du-projet)
2. [Problématiques Clés et Principes Fondamentaux](#2-problématiques-clés-et-principes-fondamentaux)
3. [Architecture Technique](#3-architecture-technique)
4. [Stratégie Git et Workflow](#4-stratégie-git-et-workflow)
5. [Plan de Tâches Détaillé](#5-plan-de-tâches-détaillé)
6. [Planning et Ordonnancement](#6-planning-et-ordonnancement)
7. [Recommandations Techniques](#7-recommandations-techniques)
8. [Critères de Succès](#8-critères-de-succès)
9. [Risques et Mitigations](#9-risques-et-mitigations)
10. [Gouvernance et Qualité](#10-gouvernance-et-qualité)
11. [Annexes](#11-annexes)

---

## 1. Vision et Contexte du Projet

### 1.1 Problématique Initiale

Les entreprises accumulent des connaissances dans des documents fragmentés (PDF, PPTX, DOCX), mais cette connaissance reste **inaccessible et incohérente** :

- ❌ Pas de structure navigable (contrairement à Wikipedia)
- ❌ Contradictions entre documents non détectées
- ❌ Évolutions temporelles non tracées
- ❌ Absence de vision unifiée et contextuelle

**Constat** : Les outils actuels (SharePoint, Confluence, Notion) offrent du stockage et de la recherche, mais pas d'**intelligence structurelle**.

### 1.2 Vision Wikipedia Osmosis

> **Transformer OSMOSIS en Wikipedia Interne Structuré**

**Objectif** : Créer une plateforme où la connaissance documentaire est :
- **Structurée** : Organisation hiérarchique comme Wikipedia (articles, catégories, portails)
- **Vivante** : Détection automatique des évolutions et contradictions
- **Traçable** : Chaque fait lié à sa source documentaire (provenance complète)
- **Collaborative** : Capacité d'enrichissement et annotation par les utilisateurs

### 1.3 Différenciation vs Wikipedia Classique

| Aspect | Wikipedia Public | Wikipedia Osmosis |
|--------|------------------|-------------------|
| **Source** | Édition manuelle | **Extraction automatique depuis documents** |
| **Mise à jour** | Contributeurs humains | **Pipeline d'ingestion + détection de changements** |
| **Cohérence** | Modération humaine | **Détection automatique contradictions (5 couches)** |
| **Provenance** | Citations manuelles | **Evidence locking sur DocItem + bbox** |
| **Multilingue** | Articles séparés par langue | **Cross-lingual unification (FR ↔ EN ↔ DE)** |
| **Temporalité** | Historique versions | **Timeline bi-temporelle (valid_time + transaction_time)** |

### 1.4 Use Case KILLER

**Scénario** : Recherche "Data Retention Policy"

**Wikipedia classique donnerait** :
- Un article générique sur les politiques de rétention

**Wikipedia Osmosis donne** :
- **Page unifiée** "Data Retention Policy"
- **Sources** : 5 documents mentionnent ce concept (GDPR Guide, Internal Policy v2, Security Runbook...)
- **Évolution** : Changement détecté entre Policy v1 (30 jours) et v2 (90 jours) le 2025-06-15
- **Contradictions** : Security Runbook mentionne 60 jours (conflit détecté)
- **Liens sémantiques** : Relié à "Personal Data", "Backup Policy", "Compliance Framework"
- **Traçabilité** : Chaque affirmation cliquable vers la page source + bbox

---

## 2. Problématiques Clés et Principes Fondamentaux

### 2.1 Problématiques Techniques

| Problématique | Description | Complexité |
|---------------|-------------|------------|
| **P1 - Structure Wikipedia** | Générer automatiquement des "articles" Wikipedia depuis le KG | ⚠️ ÉLEVÉE |
| **P2 - Navigation Hiérarchique** | Catégories, portails, index comme Wikipedia | 🟡 MOYENNE |
| **P3 - Rendu Unifié** | Template visuel cohérent (infobox, sections, références) | 🟡 MOYENNE |
| **P4 - Édition Collaborative** | Permettre annotations/corrections sans casser la provenance | ⚠️ ÉLEVÉE |
| **P5 - Versionning Hybride** | Versions documentaires + versions Wikipedia (historique éditions) | ⚠️ ÉLEVÉE |
| **P6 - Multilingue** | Affichage unifié concepts cross-lingual | 🟢 FAIBLE (déjà géré) |
| **P7 - Recherche Sémantique** | Recherche Wikipedia-style avec suggestions | 🟡 MOYENNE |
| **P8 - Export/Citation** | Citation académique + export PDF | 🟢 FAIBLE |

### 2.2 Principes Architecturaux Non-Négociables

#### Principe 1 : Graph-First Architecture
> **Le Knowledge Graph est la source de vérité, Wikipedia est une vue**

```
Documents → KG (Neo4j) → Wikipedia View (dynamique)
                ↓
            Qdrant (preuves textuelles)
```

**Conséquence** : Les "articles" Wikipedia ne sont PAS stockés comme texte figé mais **générés dynamiquement** depuis le KG.

#### Principe 2 : Evidence-Locked Content
> **Chaque affirmation dans Wikipedia doit être traçable à un DocItem source**

**Interdit** : Générer du contenu LLM non ancré ("L'authentification est un processus de vérification...").

**Autorisé** : "L'authentification utilise OAuth 2.0 [doc_id=SAP_AUTH_GUIDE, page=12, bbox=(100,200,400,250)]"

#### Principe 3 : Dual Source of Truth
> **Documents = Vérité immuable | Wikipedia = Vérité éditable**

**Modèle** :
- **Couche 1** : Contenu extrait des documents (read-only, provenance verrouillée)
- **Couche 2** : Annotations utilisateurs (éditable, versionnée, auteur tracé)

#### Principe 4 : Temporal Awareness
> **Afficher QUAND une information était valide, pas seulement CE QUI est dit**

**Exemple** :
```
Data Retention Policy
├─ 2024-01-01 → 2025-06-15 : 30 days [source: Policy v1]
└─ 2025-06-15 → present    : 90 days [source: Policy v2]
```

### 2.3 Invariants du Projet

| ID | Invariant | Vérification |
|----|-----------|-------------|
| **INV-W1** | Tout article Wikipedia correspond à un CanonicalConcept dans Neo4j | Query Cypher validation |
| **INV-W2** | Toute section d'article a ≥1 DocItem source | Evidence count > 0 |
| **INV-W3** | Les éditions utilisateurs ne modifient jamais le contenu source | Audit log séparé |
| **INV-W4** | L'historique Wikipedia conserve toutes les versions (soft delete) | Temporal table |
| **INV-W5** | Chaque lien inter-articles reflète une relation Neo4j existante | Relation validation |

---

## 3. Architecture Technique

### 3.1 Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WIKIPEDIA OSMOSIS ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    INGESTION LAYER                           │  │
│  │  Documents → Docling → Proto-KG → CanonicalConcept          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    KNOWLEDGE GRAPH (Neo4j)                    │  │
│  │  - CanonicalConcept (articles sources)                       │  │
│  │  - WikiArticle (metadata + structure)                        │  │
│  │  - WikiSection (sections d'articles)                         │  │
│  │  - WikiRevision (historique éditions)                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  WIKIPEDIA VIEW LAYER                         │  │
│  │  - Article Generator (KG → HTML Wikipedia)                   │  │
│  │  - Navigation Builder (categories, portails)                 │  │
│  │  - Search Engine (semantic + full-text)                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    FRONTEND LAYER                             │  │
│  │  - Next.js 14 (App Router)                                   │  │
│  │  - Wikipedia UI Components                                   │  │
│  │  - Editor (WYSIWYG for annotations)                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Backend Architecture

#### 3.2.1 Nouveau Modèle Neo4j

**Extension du schéma existant** :

```cypher
// --- WIKIPEDIA LAYER (nouveau) ---

// Article Wikipedia (généré depuis CanonicalConcept)
(:WikiArticle {
  article_id: string,           // UUID
  canonical_id: string,          // Référence au CanonicalConcept source
  slug: string,                  // URL-friendly (ex: "data_retention_policy")
  title: string,                 // "Data Retention Policy"
  namespace: string,             // "Main", "Category", "Portal"
  status: string,                // "published", "draft", "archived"
  quality_score: float,          // 0-1 (complétude, cohérence)
  view_count: int,               // Statistiques consultation
  created_at: datetime,
  updated_at: datetime
})

// Section d'article (table des matières)
(:WikiSection {
  section_id: string,
  article_id: string,
  parent_section_id: string,     // null si section racine
  section_type: string,          // "definition", "properties", "usage", "contradictions", "history"
  title: string,                 // "Technical Specifications"
  order_index: int,              // Position dans l'article
  content_hash: string           // Détection changements
})

// Révision (historique éditions)
(:WikiRevision {
  revision_id: string,
  article_id: string,
  author_id: string,             // Utilisateur ou "system" (auto-generated)
  revision_type: string,         // "create", "update", "annotation", "correction"
  content_diff: jsonb,           // Changements appliqués
  comment: string,               // Raison de l'édition
  created_at: datetime
})

// Catégorie (taxonomie Wikipedia)
(:WikiCategory {
  category_id: string,
  name: string,                  // "Data Protection"
  parent_category_id: string,    // Hiérarchie
  description: string
})

// Relations
(:WikiArticle)-[:BASED_ON]->(:CanonicalConcept)
(:WikiArticle)-[:HAS_SECTION]->(:WikiSection)
(:WikiSection)-[:HAS_SUBSECTION]->(:WikiSection)
(:WikiSection)-[:CITES]->(:DocItem)              // Provenance
(:WikiArticle)-[:IN_CATEGORY]->(:WikiCategory)
(:WikiArticle)-[:RELATED_TO]->(:WikiArticle)     // Voir aussi
(:WikiArticle)-[:HAS_REVISION]->(:WikiRevision)
(:WikiRevision)-[:MODIFIED_BY]->(:User)
```

#### 3.2.2 Article Generation Pipeline

**Étapes de génération d'un article** :

```python
# Pseudo-code
def generate_wiki_article(canonical_id: str) -> WikiArticle:
    """
    Génère un article Wikipedia depuis un CanonicalConcept
    """

    # 1. Récupérer le concept et ses relations
    concept = neo4j.get_canonical_concept(canonical_id)
    relations = neo4j.get_concept_relations(canonical_id)
    mentions = neo4j.get_concept_mentions(canonical_id)

    # 2. Générer la structure (sections standard)
    sections = [
        WikiSection(type="definition", title="Définition"),
        WikiSection(type="properties", title="Caractéristiques"),
        WikiSection(type="mentions", title="Occurrences Documentaires"),
        WikiSection(type="contradictions", title="Contradictions Détectées"),
        WikiSection(type="evolution", title="Historique et Évolutions"),
        WikiSection(type="related", title="Concepts Liés"),
        WikiSection(type="references", title="Références")
    ]

    # 3. Remplir chaque section avec données KG
    for section in sections:
        section.content = populate_section(
            section_type=section.type,
            concept=concept,
            relations=relations,
            mentions=mentions
        )
        # Chaque élément de contenu doit avoir evidence_ids

    # 4. Calculer quality_score
    quality = calculate_article_quality(
        concept=concept,
        sections=sections,
        evidence_count=len(mentions)
    )

    # 5. Créer WikiArticle
    article = WikiArticle(
        canonical_id=canonical_id,
        slug=slugify(concept.label),
        title=concept.label,
        quality_score=quality
    )

    return article
```

#### 3.2.3 API Endpoints (nouveaux)

**Backend FastAPI** (`src/knowbase/api/routers/wiki.py`)

```python
# Endpoints principaux

GET  /api/wiki/articles                    # Liste articles (paginé)
GET  /api/wiki/articles/{slug}             # Article complet
GET  /api/wiki/articles/{slug}/history     # Historique révisions
POST /api/wiki/articles/{slug}/edit        # Créer révision (annotation)
GET  /api/wiki/categories                  # Arbre catégories
GET  /api/wiki/search?q={query}            # Recherche Wikipedia
GET  /api/wiki/random                      # Article aléatoire
GET  /api/wiki/recent-changes              # Changements récents
POST /api/wiki/articles/generate           # Générer article depuis canonical_id

# Endpoints métadata
GET  /api/wiki/stats                       # Statistiques globales
GET  /api/wiki/portals                     # Portails thématiques
GET  /api/wiki/articles/{slug}/graph       # Graph view pour l'article
```

### 3.3 Frontend Architecture

#### 3.3.1 Pages Next.js

```
frontend/src/app/
├── wiki/
│   ├── layout.tsx                    # Layout Wikipedia (sidebar, search)
│   ├── page.tsx                      # Page d'accueil Wikipedia
│   ├── [slug]/
│   │   ├── page.tsx                  # Article view
│   │   ├── edit/page.tsx             # Édition (annotations)
│   │   └── history/page.tsx          # Historique révisions
│   ├── category/
│   │   └── [category]/page.tsx       # Liste articles par catégorie
│   ├── portal/
│   │   └── [portal]/page.tsx         # Portail thématique
│   ├── search/
│   │   └── page.tsx                  # Recherche Wikipedia
│   └── special/
│       ├── recent-changes/page.tsx   # Changements récents
│       ├── random/page.tsx           # Article aléatoire
│       └── stats/page.tsx            # Statistiques
```

#### 3.3.2 Composants React Clés

```typescript
// frontend/src/components/wiki/

// WikiArticle.tsx - Affichage article complet
<WikiArticle>
  <WikiInfobox />          // Encart info (droite)
  <WikiTableOfContents />  // Sommaire
  <WikiContent>
    <WikiSection />        // Sections avec anchors
    <WikiCitation />       // Citations sources (provenance)
  </WikiContent>
  <WikiFooter>
    <WikiCategories />     // Tags catégories
    <WikiReferences />     // Références documentaires
  </WikiFooter>
</WikiArticle>

// WikiNavigation.tsx - Sidebar navigation
<WikiNavigation>
  <WikiSearch />           // Barre recherche
  <WikiCategoryTree />     // Arbre catégories
  <WikiPortals />          // Portails thématiques
  <WikiRecentChanges />    // Activité récente
</WikiNavigation>

// WikiEditor.tsx - Éditeur annotations
<WikiEditor>
  <WysiwygEditor />        // TipTap ou Slate.js
  <AnnotationPanel />      // Panel annotations (ne modifie pas le contenu source)
  <PreviewPane />          // Aperçu temps réel
</WikiEditor>

// WikiEvolutionTimeline.tsx - Timeline évolutions
<WikiEvolutionTimeline>
  <TimelineEvent />        // Événement (document ajouté, modifié)
  <ContradictionMarker />  // Marqueur contradiction
</WikiEvolutionTimeline>

// WikiCitationPopover.tsx - Popover provenance
<WikiCitationPopover>
  <DocumentPreview />      // Aperçu document source
  <BboxHighlight />        // Highlight bbox
  <MetadataPanel />        // Metadata (page, date, auteur)
</WikiCitationPopover>
```

### 3.4 Data Flow

**Cycle de vie d'un article Wikipedia** :

```
1. INGESTION
   Document → Proto-KG → CanonicalConcept (label="Data Retention Policy")

2. GENERATION (déclenchée par cron ou manuellement)
   CanonicalConcept → WikiArticle (auto-generated)

3. PUBLICATION
   WikiArticle.status = "published"

4. CONSULTATION
   User → GET /wiki/data_retention_policy
   Backend → Génère HTML depuis KG (pas de cache texte)

5. ANNOTATION (optionnel)
   User → Edit mode → Ajoute commentaire/correction
   Backend → Crée WikiRevision (ne modifie pas CanonicalConcept)

6. MISE À JOUR (nouveau document ingéré)
   Document v2 → Pipeline détecte changement
   WikiArticle.updated_at mis à jour
   WikiRevision créée (type="system", author="auto")
```

---

## 4. Stratégie Git et Workflow

### 4.1 Modèle de Branches

**Stratégie** : Git Flow adapté avec branches feature courtes

```
main (production)
  ├── develop (intégration continue)
  │   ├── feature/wiki-core-backend        # Phase 1
  │   ├── feature/wiki-article-view        # Phase 2
  │   ├── feature/wiki-navigation          # Phase 3
  │   ├── feature/wiki-editor              # Phase 4
  │   └── feature/wiki-search              # Phase 5
  ├── release/wiki-v1.0                    # Stabilisation release
  └── hotfix/wiki-citation-bug             # Correctifs urgents
```

### 4.2 Conventions de Commits

**Format** : Conventional Commits (en français)

```bash
# Préfixes
feat(wiki):     # Nouvelle fonctionnalité Wikipedia
fix(wiki):      # Correction bug Wikipedia
refactor(wiki): # Refactoring sans changement fonctionnel
docs(wiki):     # Documentation Wikipedia
test(wiki):     # Tests Wikipedia
chore(wiki):    # Tâches maintenance

# Exemples
git commit -m "feat(wiki): ajouter génération automatique articles"
git commit -m "fix(wiki): corriger provenance citations dans WikiSection"
git commit -m "refactor(wiki): optimiser requête Neo4j pour article generation"
git commit -m "test(wiki): ajouter tests E2E pour article view"
```

### 4.3 Workflow de Développement

**Cycle de développement d'une feature** :

```bash
# 1. Créer branche depuis develop
git checkout develop
git pull origin develop
git checkout -b feature/wiki-article-view

# 2. Développement itératif
# ... code ...
git add .
git commit -m "feat(wiki): implémenter WikiArticle component"

# 3. Tests locaux
docker-compose exec app pytest tests/wiki/
npm run test

# 4. Push et Pull Request
git push origin feature/wiki-article-view
# → Créer PR vers develop sur GitHub

# 5. Code Review + CI/CD
# → Tests automatiques, linting, coverage
# → Review par ≥1 développeur

# 6. Merge vers develop
# → Squash merge pour historique propre

# 7. Déploiement staging
# → Auto-deploy develop → environnement staging

# 8. Release vers main
# → Merge develop → release/wiki-v1.0
# → Tests validation finale
# → Merge release → main
# → Tag v1.0.0
```

### 4.4 Protection des Branches

**GitHub Branch Protection Rules** :

```yaml
main:
  - Require pull request reviews (≥2 approvals)
  - Require status checks to pass
  - Require branches to be up to date
  - No force push
  - No deletion

develop:
  - Require pull request reviews (≥1 approval)
  - Require status checks to pass
  - No force push

feature/*:
  - Aucune restriction (liberté développement)
```

### 4.5 CI/CD Pipeline

**GitHub Actions** (`.github/workflows/wiki-ci.yml`)

```yaml
name: Wikipedia Osmosis CI

on:
  pull_request:
    branches: [develop, main]
    paths:
      - 'src/knowbase/wiki/**'
      - 'frontend/src/app/wiki/**'
      - 'tests/wiki/**'

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run pytest
        run: pytest tests/wiki/ --cov=src/knowbase/wiki --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      - name: Install dependencies
        run: cd frontend && npm ci
      - name: Run tests
        run: cd frontend && npm test
      - name: Build
        run: cd frontend && npm run build

  integration-tests:
    runs-on: ubuntu-latest
    needs: [backend-tests, frontend-tests]
    steps:
      - uses: actions/checkout@v3
      - name: Start services
        run: docker-compose up -d
      - name: Wait for services
        run: sleep 30
      - name: Run E2E tests
        run: npm run test:e2e
```

---

## 5. Plan de Tâches Détaillé

### 5.1 Vue d'Ensemble

**47 tâches organisées en 8 phases sur 12 semaines**

| Phase | Nom | Tâches | Durée | Dépendances |
|-------|-----|--------|-------|-------------|
| **Phase 0** | Setup Infrastructure | 5 | Semaine 1 | Aucune |
| **Phase 1** | Backend Core | 8 | Semaines 2-3 | Phase 0 |
| **Phase 2** | Article Generation | 7 | Semaines 4-5 | Phase 1 |
| **Phase 3** | Frontend Foundation | 6 | Semaines 6-7 | Phase 2 |
| **Phase 4** | Navigation & Search | 6 | Semaines 8-9 | Phase 3 |
| **Phase 5** | Editor & Annotations | 5 | Semaine 10 | Phase 4 |
| **Phase 6** | Advanced Features | 6 | Semaine 11 | Phase 5 |
| **Phase 7** | Polish & Launch | 4 | Semaine 12 | Phase 6 |

### 5.2 Phase 0 : Setup Infrastructure (Semaine 1)

| ID | Tâche | Description | Estimation | Assigné |
|----|-------|-------------|------------|---------|
| **T0.1** | Schéma Neo4j Wikipedia | Créer nodes WikiArticle, WikiSection, WikiRevision, WikiCategory + relations | 1j | Backend |
| **T0.2** | Migration Neo4j | Script migration pour ajouter contraintes et indexes | 0.5j | Backend |
| **T0.3** | Models Pydantic | WikiArticleModel, WikiSectionModel, WikiRevisionModel | 0.5j | Backend |
| **T0.4** | Setup Routes API | Créer `/api/wiki/*` router structure | 0.5j | Backend |
| **T0.5** | Setup Frontend Pages | Créer `/wiki/*` page structure Next.js | 0.5j | Frontend |

**Livrables Phase 0** :
- ✅ Schéma Neo4j déployé
- ✅ Structure API /api/wiki/ fonctionnelle
- ✅ Structure frontend /wiki/ accessible

---

### 5.3 Phase 1 : Backend Core (Semaines 2-3)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T1.1** | WikiArticleService | CRUD operations pour WikiArticle (create, read, update, delete) | 1j | T0.1 |
| **T1.2** | Neo4j Queries - Articles | Requêtes optimisées pour fetch article + sections + relations | 1j | T1.1 |
| **T1.3** | Article Generator Core | Logique génération article depuis CanonicalConcept | 2j | T1.2 |
| **T1.4** | Section Population | Remplissage automatique sections (definition, properties, mentions...) | 1.5j | T1.3 |
| **T1.5** | Quality Score Calculator | Calcul qualité article (complétude, cohérence, evidence count) | 1j | T1.4 |
| **T1.6** | Slug Generator | Génération slugs URL-friendly avec gestion collisions | 0.5j | T1.1 |
| **T1.7** | Article Caching | Cache Redis pour articles générés (invalidation sur update KG) | 1j | T1.5 |
| **T1.8** | Tests Unitaires Backend | Tests pour services + generators (≥80% coverage) | 1j | T1.7 |

**Livrables Phase 1** :
- ✅ API génération articles fonctionnelle
- ✅ Tests backend passants
- ✅ Performance génération <500ms par article

---

### 5.4 Phase 2 : Article Generation Pipeline (Semaines 4-5)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T2.1** | Batch Article Generator | Génération en masse (tous CanonicalConcepts → WikiArticles) | 1j | T1.8 |
| **T2.2** | Update Detection | Détection changements KG → trigger re-génération article | 1.5j | T2.1 |
| **T2.3** | Contradiction Section | Génération section "Contradictions Détectées" depuis relations CONTRADICTS | 1j | T2.1 |
| **T2.4** | Evolution Timeline Section | Génération section "Historique" depuis temporal data | 1.5j | T2.3 |
| **T2.5** | Related Concepts Section | Génération section "Concepts Liés" depuis relations sémantiques | 1j | T2.1 |
| **T2.6** | References Section | Génération section "Références" avec provenance complète | 1j | T2.5 |
| **T2.7** | Tests E2E Generation | Tests génération complète article avec données réelles | 1j | T2.6 |

**Livrables Phase 2** :
- ✅ Pipeline génération complète
- ✅ Sections auto-peuplées avec evidence
- ✅ Tests E2E passants

---

### 5.5 Phase 3 : Frontend Foundation (Semaines 6-7)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T3.1** | WikiArticle Component | Composant affichage article (layout Wikipedia) | 1.5j | T0.5 |
| **T3.2** | WikiSection Component | Composant section avec anchors + citations | 1j | T3.1 |
| **T3.3** | WikiInfobox Component | Encart info (metadata, stats, catégories) | 1j | T3.1 |
| **T3.4** | WikiTableOfContents | Sommaire généré dynamiquement avec scroll spy | 0.5j | T3.2 |
| **T3.5** | WikiCitation Component | Popover citation avec provenance (document, page, bbox) | 1.5j | T3.2 |
| **T3.6** | Responsive Design | Adaptation mobile/tablet (sidebar collapsible) | 1j | T3.5 |

**Livrables Phase 3** :
- ✅ Article view fonctionnelle
- ✅ Citations cliquables avec provenance
- ✅ Design responsive

---

### 5.6 Phase 4 : Navigation & Search (Semaines 8-9)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T4.1** | Category System Backend | CRUD catégories + arbre hiérarchique | 1j | T1.8 |
| **T4.2** | Auto-Categorization | Assignation automatique catégories depuis type_bucket | 1j | T4.1 |
| **T4.3** | WikiNavigation Component | Sidebar navigation (search, categories, portals) | 1.5j | T3.6 |
| **T4.4** | WikiSearch Component | Barre recherche avec suggestions (debounced) | 1j | T4.3 |
| **T4.5** | Search Backend | Endpoint /api/wiki/search avec ranking sémantique | 1.5j | T4.4 |
| **T4.6** | Category Pages | Page liste articles par catégorie | 1j | T4.2 |

**Livrables Phase 4** :
- ✅ Navigation sidebar complète
- ✅ Recherche fonctionnelle
- ✅ Catégories assignées automatiquement

---

### 5.7 Phase 5 : Editor & Annotations (Semaine 10)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T5.1** | WikiEditor Component | Éditeur WYSIWYG (TipTap) pour annotations | 2j | T3.6 |
| **T5.2** | Revision System Backend | CRUD WikiRevision + diff calculation | 1j | T1.8 |
| **T5.3** | Annotation Storage | Stockage annotations séparées du contenu source | 1j | T5.2 |
| **T5.4** | History View | Page historique révisions avec diff view | 1.5j | T5.2 |
| **T5.5** | User Permissions | Système permissions (read-only, annotator, editor) | 1j | T5.3 |

**Livrables Phase 5** :
- ✅ Éditeur annotations fonctionnel
- ✅ Historique révisions consultable
- ✅ Permissions gérées

---

### 5.8 Phase 6 : Advanced Features (Semaine 11)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T6.1** | WikiEvolutionTimeline | Composant timeline évolutions temporelles | 1.5j | T2.4 |
| **T6.2** | Portals System | Pages portails thématiques (agrégation catégories) | 1j | T4.6 |
| **T6.3** | Random Article | Page article aléatoire (discovery) | 0.5j | T4.6 |
| **T6.4** | Recent Changes | Page changements récents (activité) | 1j | T5.4 |
| **T6.5** | Export PDF | Export article en PDF (citations préservées) | 1.5j | T3.6 |
| **T6.6** | Graph View | Visualisation graph relations pour un article | 2j | T4.1 |

**Livrables Phase 6** :
- ✅ Features avancées fonctionnelles
- ✅ Export PDF opérationnel
- ✅ Graph view interactive

---

### 5.9 Phase 7 : Polish & Launch (Semaine 12)

| ID | Tâche | Description | Estimation | Dépendances |
|----|-------|-------------|------------|-------------|
| **T7.1** | Performance Optimization | Optimisation requêtes + caching + lazy loading | 1.5j | T6.6 |
| **T7.2** | Documentation Utilisateur | Guide utilisateur Wikipedia (FR + EN) | 1j | T7.1 |
| **T7.3** | Tests E2E Complets | Suite tests E2E complète (Playwright) | 1.5j | T7.1 |
| **T7.4** | Deployment Production | Déploiement environnement production + monitoring | 1j | T7.3 |

**Livrables Phase 7** :
- ✅ Plateforme optimisée
- ✅ Documentation complète
- ✅ Environnement production opérationnel

---

## 6. Planning et Ordonnancement

### 6.1 Timeline 12 Semaines

```
Semaine 1  : ████ Phase 0 - Setup Infrastructure
Semaine 2-3: ████████ Phase 1 - Backend Core
Semaine 4-5: ████████ Phase 2 - Article Generation
Semaine 6-7: ████████ Phase 3 - Frontend Foundation
Semaine 8-9: ████████ Phase 4 - Navigation & Search
Semaine 10 : ████ Phase 5 - Editor & Annotations
Semaine 11 : ████ Phase 6 - Advanced Features
Semaine 12 : ████ Phase 7 - Polish & Launch

Milestones:
  M1 - Semaine 5  : Backend complet + génération articles
  M2 - Semaine 9  : Frontend complet + navigation
  M3 - Semaine 12 : Launch production
```

### 6.2 Milestones Détaillés

#### Milestone 1 : Backend Complet (Semaine 5)

**Date cible** : 2026-04-11

**Critères de validation** :
- ✅ Tous les endpoints `/api/wiki/*` implémentés et testés
- ✅ Génération automatique articles depuis CanonicalConcepts fonctionnelle
- ✅ Sections auto-peuplées avec provenance
- ✅ Tests backend ≥80% coverage
- ✅ Performance génération <500ms par article

**Démo** :
```bash
# Générer article pour un concept
POST /api/wiki/articles/generate
{
  "canonical_id": "uuid-auth-concept"
}

# Récupérer article généré
GET /api/wiki/articles/authentication
→ Retourne article complet avec sections, citations, relations
```

#### Milestone 2 : Frontend Complet (Semaine 9)

**Date cible** : 2026-05-09

**Critères de validation** :
- ✅ Interface Wikipedia complète (article view, navigation, search)
- ✅ Citations cliquables avec provenance (document, page, bbox)
- ✅ Recherche sémantique fonctionnelle
- ✅ Catégories assignées automatiquement
- ✅ Design responsive (mobile, tablet, desktop)

**Démo** :
1. Ouvrir http://localhost:3000/wiki/authentication
2. Voir article complet avec sections, infobox, table of contents
3. Cliquer sur citation → Popover affiche document source + bbox
4. Rechercher "data retention" → Suggestions + résultats pertinents
5. Naviguer via catégories → Arbre hiérarchique fonctionnel

#### Milestone 3 : Production Launch (Semaine 12)

**Date cible** : 2026-05-30

**Critères de validation** :
- ✅ Tous les tests E2E passants
- ✅ Documentation utilisateur complète (FR + EN)
- ✅ Performance optimisée (PageSpeed >90)
- ✅ Déploiement production opérationnel
- ✅ Monitoring configuré (Grafana dashboards)

**Go/No-Go Checklist** :
```
[ ] Tests E2E 100% passants
[ ] Performance tests validés (<2s page load)
[ ] Sécurité audit passé (OWASP Top 10)
[ ] Documentation utilisateur validée
[ ] Plan rollback défini
[ ] Monitoring alertes configurées
[ ] Backup/restore testé
```

### 6.3 Ressources

**Équipe requise** :

| Rôle | FTE | Phases | Responsabilités |
|------|-----|--------|-----------------|
| **Backend Lead** | 1.0 | Toutes | Architecture backend, Neo4j, API design |
| **Backend Dev** | 1.0 | 1-2, 5 | Implémentation services, tests |
| **Frontend Lead** | 1.0 | Toutes | Architecture frontend, composants React |
| **Frontend Dev** | 1.0 | 3-6 | Implémentation UI, intégration API |
| **QA Engineer** | 0.5 | 7 | Tests E2E, validation |
| **DevOps** | 0.5 | 0, 7 | Infrastructure, CI/CD, déploiement |
| **Product Owner** | 0.25 | Toutes | Vision produit, priorisation, validation |

**Total** : 5.25 FTE

### 6.4 Dépendances Externes

| Dépendance | Impact | Mitigation |
|------------|--------|------------|
| **Neo4j v5+** | Schéma Wikipedia nécessite Neo4j ≥5.0 | Upgrade prévu Phase 0 |
| **Next.js 14** | App Router requis pour structure /wiki/* | Déjà en place |
| **TipTap Editor** | Librairie WYSIWYG pour annotations | Évaluation alternatives (Slate, ProseMirror) |
| **Qdrant** | Provenance evidence (pas de changement requis) | Aucune |

---

## 7. Recommandations Techniques

### 7.1 Stack Technique Recommandée

#### Backend

| Composant | Choix | Raison |
|-----------|-------|--------|
| **Framework** | FastAPI 0.110+ | Déjà en place, async natif, Pydantic v2 |
| **Database** | Neo4j 5.15+ | Graph-first architecture, temporal queries |
| **Cache** | Redis 7+ | Cache articles générés, sessions |
| **Vector DB** | Qdrant 1.7+ | Provenance evidence (existant) |
| **ORM Graph** | Neo4j Python Driver 5+ | Driver officiel, performances optimales |
| **Validation** | Pydantic v2 | Type safety, validation automatique |

#### Frontend

| Composant | Choix | Raison |
|-----------|-------|--------|
| **Framework** | Next.js 14 | SSR, App Router, optimisations image |
| **UI Library** | Tailwind CSS + shadcn/ui | Design system cohérent, composants réutilisables |
| **Rich Text Editor** | TipTap | WYSIWYG flexible, extensible, bien maintenu |
| **State Management** | Zustand | Lightweight, TypeScript natif, simple |
| **Data Fetching** | TanStack Query (React Query) | Cache intelligent, optimistic updates |
| **Testing** | Playwright | E2E cross-browser, stable |

#### DevOps

| Composant | Choix | Raison |
|-----------|-------|--------|
| **CI/CD** | GitHub Actions | Intégration native, marketplace riche |
| **Containers** | Docker Compose (dev), Kubernetes (prod) | Isolation, scalabilité |
| **Monitoring** | Grafana + Loki + Prometheus | Déjà en place |
| **Logging** | Structlog (Python) + Winston (Node) | Logs structurés, traçabilité |

### 7.2 Patterns de Développement

#### Pattern 1 : Repository Pattern (Backend)

**Objectif** : Séparer logique métier et accès données

```python
# src/knowbase/wiki/repositories/article_repository.py

class WikiArticleRepository:
    """
    Gère l'accès données pour WikiArticle (abstraction Neo4j)
    """

    def __init__(self, neo4j_client: Neo4jClient):
        self.neo4j = neo4j_client

    async def get_by_slug(self, slug: str) -> Optional[WikiArticle]:
        query = """
        MATCH (wa:WikiArticle {slug: $slug})
        OPTIONAL MATCH (wa)-[:HAS_SECTION]->(ws:WikiSection)
        RETURN wa, collect(ws) as sections
        """
        result = await self.neo4j.execute(query, {"slug": slug})
        return self._map_to_model(result)

    async def create(self, article: WikiArticle) -> WikiArticle:
        # ...

    async def update(self, article_id: str, updates: dict) -> WikiArticle:
        # ...
```

#### Pattern 2 : Service Layer (Backend)

**Objectif** : Encapsuler logique métier complexe

```python
# src/knowbase/wiki/services/article_service.py

class WikiArticleService:
    """
    Logique métier génération et gestion articles
    """

    def __init__(
        self,
        article_repo: WikiArticleRepository,
        concept_repo: ConceptRepository,
        generator: ArticleGenerator
    ):
        self.articles = article_repo
        self.concepts = concept_repo
        self.generator = generator

    async def generate_article(self, canonical_id: str) -> WikiArticle:
        """
        Génère article depuis CanonicalConcept
        """
        concept = await self.concepts.get(canonical_id)
        if not concept:
            raise ConceptNotFoundError(canonical_id)

        article = await self.generator.generate(concept)
        await self.articles.create(article)

        return article

    async def get_article(self, slug: str) -> WikiArticle:
        """
        Récupère article (avec cache)
        """
        # Check cache
        cached = await cache.get(f"wiki:article:{slug}")
        if cached:
            return WikiArticle.parse_raw(cached)

        # Fetch from DB
        article = await self.articles.get_by_slug(slug)
        if not article:
            raise ArticleNotFoundError(slug)

        # Cache for 1 hour
        await cache.set(f"wiki:article:{slug}", article.json(), ex=3600)

        return article
```

#### Pattern 3 : Component Composition (Frontend)

**Objectif** : Composants réutilisables et maintenables

```typescript
// frontend/src/components/wiki/WikiArticle.tsx

export function WikiArticle({ slug }: { slug: string }) {
  const { data: article, isLoading } = useWikiArticle(slug)

  if (isLoading) return <WikiArticleSkeleton />
  if (!article) return <WikiArticleNotFound />

  return (
    <div className="wiki-article">
      <WikiHeader article={article} />

      <div className="flex gap-8">
        <aside className="w-64">
          <WikiTableOfContents sections={article.sections} />
        </aside>

        <main className="flex-1">
          <WikiContent sections={article.sections} />
        </main>

        <aside className="w-80">
          <WikiInfobox article={article} />
        </aside>
      </div>

      <WikiFooter article={article} />
    </div>
  )
}

// Hook custom pour data fetching
function useWikiArticle(slug: string) {
  return useQuery({
    queryKey: ['wiki', 'article', slug],
    queryFn: () => fetch(`/api/wiki/articles/${slug}`).then(r => r.json()),
    staleTime: 1000 * 60 * 5, // 5 minutes
  })
}
```

### 7.3 Optimisations Performance

#### Backend

| Optimisation | Description | Impact |
|--------------|-------------|--------|
| **Article Caching** | Cache Redis articles générés (TTL 1h) | -80% latence lecture |
| **Query Optimization** | Indexes Neo4j sur slug, canonical_id, article_id | -60% temps requête |
| **Batch Generation** | Génération articles en parallèle (asyncio.gather) | -70% temps batch |
| **Connection Pooling** | Pool Neo4j (max 50 connections) | -30% overhead connection |
| **Response Compression** | Gzip/Brotli pour API responses | -50% bande passante |

#### Frontend

| Optimisation | Description | Impact |
|--------------|-------------|--------|
| **Code Splitting** | Dynamic imports pour composants lourds (Editor, Graph) | -40% bundle initial |
| **Image Optimization** | Next.js Image component (WebP, lazy load) | -60% poids images |
| **Prefetching** | Prefetch articles liés (hover intent) | -50% perceived latency |
| **Virtual Scrolling** | Virtualisation listes longues (catégories, history) | -80% DOM nodes |
| **Debounced Search** | Debounce 300ms recherche | -90% requêtes search |

### 7.4 Sécurité

| Mesure | Description | Priorité |
|--------|-------------|----------|
| **Input Validation** | Pydantic validation + sanitization HTML (bleach) | 🔴 CRITIQUE |
| **CSRF Protection** | Tokens CSRF pour éditions | 🔴 CRITIQUE |
| **Rate Limiting** | 100 req/min par IP (génération articles), 1000 req/min (lecture) | 🟡 MOYENNE |
| **Content Security Policy** | CSP headers (no inline scripts) | 🟡 MOYENNE |
| **Audit Logging** | Log toutes éditions/annotations (auteur + timestamp) | 🔴 CRITIQUE |
| **SQL Injection** | Parameterized queries (driver Neo4j) | 🔴 CRITIQUE |

---

## 8. Critères de Succès

### 8.1 Critères Techniques

| Critère | Métrique | Objectif | Mesure |
|---------|----------|----------|--------|
| **Performance Génération** | Temps génération article | <500ms | Prometheus histogram |
| **Performance Lecture** | TTFB (Time To First Byte) | <200ms | Lighthouse |
| **Disponibilité** | Uptime | ≥99.5% | Monitoring Grafana |
| **Scalabilité** | Articles générables simultanément | ≥50 | Load testing (Locust) |
| **Coverage Tests** | Code coverage | ≥80% | pytest-cov |
| **SEO** | PageSpeed Insights score | ≥90 | PageSpeed API |

### 8.2 Critères Fonctionnels

| Critère | Description | Validation |
|---------|-------------|------------|
| **F1 - Génération Articles** | Tous les CanonicalConcepts (≥100) ont un WikiArticle généré | Query Neo4j |
| **F2 - Provenance Complète** | Chaque affirmation tracée à ≥1 DocItem | Validation evidence_ids |
| **F3 - Contradictions Visibles** | Section "Contradictions" affichée si ≥1 CONTRADICTS | Test E2E |
| **F4 - Évolution Temporelle** | Timeline affiche changements entre versions documentaires | Test E2E |
| **F5 - Recherche Pertinente** | Top-3 résultats pertinents pour 90% des queries test | Benchmark queries |
| **F6 - Annotations Fonctionnelles** | Utilisateurs peuvent ajouter commentaires sans casser provenance | Test E2E |
| **F7 - Export PDF** | PDF exporté conserve citations + mise en page | Test E2E |

### 8.3 Critères Business

| Critère | Métrique | Objectif | Horizon |
|---------|----------|----------|---------|
| **Adoption Interne** | Utilisateurs actifs mensuels | ≥50 | M+3 |
| **Engagement** | Pages vues par session | ≥5 | M+3 |
| **Rétention** | Utilisateurs revenant ≥1x/semaine | ≥30% | M+6 |
| **Time to Answer** | Temps moyen trouver information | <2min | M+3 |
| **Satisfaction** | NPS (Net Promoter Score) | ≥40 | M+6 |

### 8.4 Scénarios de Validation

#### Scénario 1 : Utilisateur Consulte Article

**Acteur** : Utilisateur interne (lecture seule)

**Étapes** :
1. Accéder à http://localhost:3000/wiki
2. Rechercher "authentication" dans barre recherche
3. Cliquer sur résultat "Authentication Mechanisms"
4. **Valider** :
   - ✅ Article affiché avec sections complètes
   - ✅ Table of contents navigable
   - ✅ Infobox affiche metadata (catégories, stats)
   - ✅ Section "Contradictions" affichée (si applicable)
   - ✅ Citations cliquables → Popover provenance
5. Cliquer sur citation
6. **Valider** :
   - ✅ Popover affiche document source, page, bbox
   - ✅ Aperçu texte source visible
7. Naviguer vers "Concepts Liés"
8. Cliquer sur concept lié "OAuth 2.0"
9. **Valider** :
   - ✅ Navigation vers article OAuth 2.0
   - ✅ Article chargé en <500ms

**Critère succès** : Tous les ✅ validés sans erreur

#### Scénario 2 : Utilisateur Annote Article

**Acteur** : Utilisateur avec permissions "annotator"

**Étapes** :
1. Accéder à article "Data Retention Policy"
2. Cliquer sur bouton "Annoter"
3. Mode édition activé
4. Ajouter commentaire "Cette politique a changé le 2025-Q2"
5. Sauvegarder
6. **Valider** :
   - ✅ Annotation affichée (highlight distinct du contenu source)
   - ✅ WikiRevision créée (type="annotation", author=user_id)
   - ✅ Contenu source non modifié (CanonicalConcept intact)
7. Accéder à page "Historique"
8. **Valider** :
   - ✅ Révision listée avec timestamp, auteur, commentaire
   - ✅ Diff view affiche ajout annotation

**Critère succès** : Tous les ✅ validés, provenance préservée

#### Scénario 3 : Système Détecte Changement Document

**Acteur** : Pipeline ingestion

**Étapes** :
1. Ingérer nouveau document "Data Retention Policy v3.pdf"
2. Pipeline extrait nouveau concept "Data Retention : 120 days"
3. Update Detection détecte changement (90 days → 120 days)
4. **Valider** :
   - ✅ WikiArticle "Data Retention Policy" updated_at mis à jour
   - ✅ WikiRevision créée (type="system", author="auto")
   - ✅ Section "Évolutions" affiche timeline :
     - 2024-01-01 → 2025-06-15 : 30 days
     - 2025-06-15 → 2026-01-10 : 90 days
     - 2026-01-10 → present : 120 days
5. Utilisateur accède à article
6. **Valider** :
   - ✅ Badge "Mis à jour récemment" affiché
   - ✅ Changement visible dans timeline

**Critère succès** : Tous les ✅ validés, changement détecté automatiquement

---

## 9. Risques et Mitigations

### 9.1 Risques Techniques

| ID | Risque | Probabilité | Impact | Mitigation |
|----|--------|-------------|--------|------------|
| **R1** | **Performance dégradée** pour corpus large (>1000 articles) | 🟡 MOYENNE | 🔴 ÉLEVÉ | - Caching agressif (Redis)<br>- Lazy loading sections<br>- Pagination listes<br>- Indexes Neo4j optimisés |
| **R2** | **Explosion schéma Neo4j** (WikiRevision illimité) | 🟢 FAIBLE | 🟡 MOYEN | - Archivage révisions >1 an<br>- Soft delete avec retention policy<br>- Monitoring taille DB |
| **R3** | **Qualité articles variable** (concepts peu documentés) | 🔴 ÉLEVÉE | 🟡 MOYEN | - Quality score visible (0-1)<br>- Filtrage articles quality <0.3<br>- Amélioration itérative via annotations |
| **R4** | **Incohérence cache** (article cached vs KG updated) | 🟡 MOYENNE | 🔴 ÉLEVÉ | - Cache invalidation sur update KG<br>- TTL court (1h)<br>- Version tracking (ETag) |
| **R5** | **Conflits éditions concurrentes** | 🟢 FAIBLE | 🟡 MOYEN | - Optimistic locking (version field)<br>- Conflict resolution UI<br>- Merge automatique si non-overlapping |

### 9.2 Risques Fonctionnels

| ID | Risque | Probabilité | Impact | Mitigation |
|----|--------|-------------|--------|------------|
| **R6** | **Adoption faible** (utilisateurs préfèrent outil existant) | 🟡 MOYENNE | 🔴 ÉLEVÉ | - Onboarding guidé<br>- Demos internes<br>- Valeur différenciante visible (contradictions)<br>- Export vers outils existants |
| **R7** | **Surcharge cognitive** (trop d'informations par article) | 🟡 MOYENNE | 🟡 MOYEN | - Sections collapsibles<br>- Mode "Vue simplifiée"<br>- Progressive disclosure |
| **R8** | **Provenance cassée** (éditions utilisateurs non tracées) | 🟢 FAIBLE | 🔴 ÉLEVÉ | - Invariant INV-W3 appliqué<br>- Tests automatiques provenance<br>- Audit log complet |
| **R9** | **Contradictions non détectées** (false negatives) | 🟡 MOYENNE | 🟡 MOYEN | - Amélioration continue détection<br>- Feedback utilisateurs ("Signaler contradiction")<br>- Métriques precision/recall |

### 9.3 Risques Projet

| ID | Risque | Probabilité | Impact | Mitigation |
|----|--------|-------------|--------|------------|
| **R10** | **Dérive scope** (features non planifiées) | 🔴 ÉLEVÉE | 🔴 ÉLEVÉ | - Backlog priorisé strict<br>- Product Owner validation<br>- "Nice-to-have" post-v1.0 |
| **R11** | **Dépendance clé bloquante** (ex: TipTap breaking change) | 🟢 FAIBLE | 🟡 MOYEN | - Lock versions dependencies<br>- Veille techno active<br>- Alternatives évaluées (Slate, ProseMirror) |
| **R12** | **Ressources insuffisantes** (maladie, départ) | 🟡 MOYENNE | 🔴 ÉLEVÉ | - Documentation continue<br>- Pair programming<br>- Knowledge sharing sessions<br>- Bus factor ≥2 par composant |
| **R13** | **Migration Neo4j échouée** (corruption données) | 🟢 FAIBLE | 🔴 ÉLEVÉ | - Backup avant migration<br>- Migration testée sur staging<br>- Rollback script préparé |

### 9.4 Plan de Contingence

**Si R1 (Performance dégradée) se matérialise** :

```
Plan A (court terme) :
- Activer caching Redis agressif (TTL 6h)
- Lazy load sections (fetch on-demand)
- Pagination stricte (20 articles/page max)

Plan B (moyen terme) :
- Pré-génération articles en background (cron)
- Materialized views Neo4j pour queries fréquentes
- CDN pour assets statiques

Plan C (long terme) :
- Sharding Neo4j par tenant_id
- Read replicas Neo4j
- Migration vers Kubernetes (horizontal scaling)
```

**Si R6 (Adoption faible) se matérialise** :

```
Plan A (semaine 1-2 post-launch) :
- Sessions démo internes (lunch & learn)
- Champions identifiés par département
- Quick wins communiqués (contradictions détectées)

Plan B (semaine 3-4) :
- Interviews utilisateurs (feedback)
- Ajustements UI/UX basés feedback
- Intégration outils existants (Slack notifications)

Plan C (semaine 5+) :
- Pivot fonctionnel (focus features demandées)
- Partenariat avec équipes early adopters
- Gamification (badges, leaderboard contributions)
```

---

## 10. Gouvernance et Qualité

### 10.1 Définition of Done (DoD)

**Une tâche est "Done" si** :

```
[ ] Code implémenté selon spec
[ ] Tests unitaires écrits (coverage ≥80%)
[ ] Tests E2E ajoutés (si applicable)
[ ] Code review approuvé (≥1 reviewer)
[ ] Documentation technique mise à jour
[ ] CI/CD pipeline passant (green)
[ ] Déployé sur staging et validé
[ ] Product Owner a validé fonctionnalité
```

### 10.2 Code Review Checklist

**Backend (Python)** :

```
[ ] Respect conventions PEP 8
[ ] Type hints présents (mypy strict)
[ ] Docstrings complètes (Google style)
[ ] Error handling approprié
[ ] Logging structuré (pas de print())
[ ] Pas de secrets hardcodés
[ ] Tests couvrent edge cases
[ ] Requêtes Neo4j optimisées (EXPLAIN PLAN validé)
```

**Frontend (TypeScript)** :

```
[ ] TypeScript strict mode
[ ] Composants typés (no any)
[ ] Accessibility (ARIA labels, keyboard nav)
[ ] Responsive design (mobile, tablet, desktop)
[ ] Error boundaries React
[ ] Loading states gérés
[ ] Tests unitaires (Vitest) + E2E (Playwright)
[ ] Performance (bundle size, lazy loading)
```

### 10.3 Quality Gates

**Pre-Merge** :

| Gate | Outil | Critère |
|------|-------|---------|
| **Linting** | Ruff (Python), ESLint (TS) | Aucune erreur |
| **Type Checking** | MyPy (Python), TSC (TS) | Aucune erreur strict mode |
| **Tests Unitaires** | Pytest, Vitest | ≥80% coverage, tous passants |
| **Security Scan** | Bandit (Python), npm audit (Node) | Aucune vulnérabilité HIGH/CRITICAL |

**Pre-Deploy** :

| Gate | Outil | Critère |
|------|-------|---------|
| **Tests E2E** | Playwright | Tous scénarios passants |
| **Performance** | Lighthouse CI | Score ≥90 |
| **Smoke Tests** | Postman/Newman | Endpoints critiques OK |
| **Database Migration** | Neo4j migration scripts | Rollback testé |

### 10.4 Monitoring et Alertes

**Métriques Clés** (Grafana dashboards) :

```
# Performance
- wiki_article_generation_duration_seconds (histogram)
- wiki_api_request_duration_seconds (histogram)
- wiki_cache_hit_rate (gauge)

# Business
- wiki_articles_total (counter)
- wiki_articles_views_total (counter)
- wiki_search_queries_total (counter)
- wiki_annotations_total (counter)

# Errors
- wiki_api_errors_total (counter, labels: endpoint, status_code)
- wiki_generation_failures_total (counter)
```

**Alertes Critiques** :

| Alerte | Condition | Action |
|--------|-----------|--------|
| **API Down** | wiki_api_request_duration_seconds > 5s (p95) | Page ops team |
| **High Error Rate** | wiki_api_errors_total > 10% requests | Investigate immediately |
| **Cache Miss Spike** | wiki_cache_hit_rate < 50% | Check Redis health |
| **Generation Failures** | wiki_generation_failures_total > 5/hour | Check Neo4j connectivity |

---

## 11. Annexes

### 11.1 Exemples de Données

#### Exemple 1 : WikiArticle JSON

```json
{
  "article_id": "uuid-article-auth",
  "canonical_id": "uuid-canonical-auth",
  "slug": "authentication",
  "title": "Authentication",
  "namespace": "Main",
  "status": "published",
  "quality_score": 0.87,
  "view_count": 142,
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-10T15:30:00Z",
  "sections": [
    {
      "section_id": "uuid-section-def",
      "section_type": "definition",
      "title": "Définition",
      "order_index": 1,
      "content": {
        "text": "L'authentification est le processus de vérification de l'identité d'un utilisateur.",
        "evidence_ids": ["uuid-docitem-1", "uuid-docitem-2"]
      }
    },
    {
      "section_id": "uuid-section-props",
      "section_type": "properties",
      "title": "Méthodes d'Authentification",
      "order_index": 2,
      "content": {
        "items": [
          {
            "label": "OAuth 2.0",
            "description": "Protocole d'autorisation...",
            "evidence_ids": ["uuid-docitem-3"]
          },
          {
            "label": "SAML",
            "description": "Security Assertion Markup Language...",
            "evidence_ids": ["uuid-docitem-4"]
          }
        ]
      }
    },
    {
      "section_id": "uuid-section-contradictions",
      "section_type": "contradictions",
      "title": "Contradictions Détectées",
      "order_index": 3,
      "content": {
        "contradictions": [
          {
            "claim_a": {
              "text": "Session timeout: 30 minutes",
              "source": "Security Guide v1",
              "evidence_ids": ["uuid-docitem-5"]
            },
            "claim_b": {
              "text": "Session timeout: 60 minutes",
              "source": "Admin Manual v2",
              "evidence_ids": ["uuid-docitem-6"]
            },
            "conflict_type": "VALUE_MISMATCH",
            "detected_at": "2026-03-08T12:00:00Z"
          }
        ]
      }
    }
  ],
  "categories": ["Security", "Identity Management"],
  "related_articles": [
    {"slug": "oauth", "title": "OAuth 2.0"},
    {"slug": "authorization", "title": "Authorization"}
  ]
}
```

#### Exemple 2 : WikiRevision JSON

```json
{
  "revision_id": "uuid-revision-1",
  "article_id": "uuid-article-auth",
  "author_id": "user-john-doe",
  "revision_type": "annotation",
  "content_diff": {
    "added": [
      {
        "section_id": "uuid-section-def",
        "annotation": {
          "text": "Note: Cette définition s'applique spécifiquement aux systèmes SAP S/4HANA Cloud.",
          "position": "after_paragraph_1"
        }
      }
    ],
    "modified": [],
    "removed": []
  },
  "comment": "Ajout contexte SAP S/4HANA",
  "created_at": "2026-03-10T15:30:00Z"
}
```

### 11.2 Taxonomie Categories

**Arbre hiérarchique proposé** :

```
Root
├── Technology
│   ├── Cloud Computing
│   ├── Security
│   │   ├── Authentication
│   │   ├── Authorization
│   │   └── Encryption
│   ├── Databases
│   └── APIs
├── Business Processes
│   ├── Finance
│   ├── Supply Chain
│   ├── Human Resources
│   └── Sales
├── Compliance
│   ├── Data Protection (GDPR)
│   ├── Security Standards (ISO 27001)
│   └── Industry Regulations
├── Products
│   ├── SAP S/4HANA
│   ├── SAP SuccessFactors
│   └── Third-party Integrations
└── Concepts
    ├── Definitions
    ├── Methodologies
    └── Best Practices
```

**Auto-categorization logic** :

```python
# Mapping type_bucket → category
TYPE_BUCKET_TO_CATEGORY = {
    "technical_architecture": "Technology",
    "security": "Technology/Security",
    "business_process": "Business Processes",
    "product": "Products",
    "regulation": "Compliance",
    "definition": "Concepts/Definitions"
}

def auto_categorize(canonical_concept: CanonicalConcept) -> List[str]:
    """
    Assigne automatiquement catégories depuis type_bucket
    """
    categories = []

    # Category principale depuis type_bucket
    if canonical_concept.type_bucket in TYPE_BUCKET_TO_CATEGORY:
        categories.append(TYPE_BUCKET_TO_CATEGORY[canonical_concept.type_bucket])

    # Categories additionnelles depuis relations
    # Ex: si IMPLEMENTS(concept, "SAP S/4HANA") → ajouter "Products/SAP S/4HANA"

    return categories
```

### 11.3 Glossaire

| Terme | Définition |
|-------|------------|
| **WikiArticle** | Page Wikipedia générée depuis un CanonicalConcept, affichant définition, propriétés, contradictions, évolutions |
| **WikiSection** | Section d'un article (ex: "Définition", "Contradictions"), contient contenu + evidence_ids |
| **WikiRevision** | Version historique d'un article, capture éditions utilisateurs ou changements système |
| **WikiCategory** | Catégorie taxonomique pour organiser articles (hiérarchie) |
| **CanonicalConcept** | Entité sémantique dans Neo4j (source de vérité pour génération articles) |
| **DocItem** | Élément atomique document Docling (provenance granulaire avec bbox) |
| **Evidence-Locking** | Principe : chaque affirmation doit être traçable à ≥1 DocItem source |
| **Quality Score** | Métrique 0-1 évaluant complétude et cohérence d'un article |
| **Slug** | Identifiant URL-friendly d'un article (ex: "data_retention_policy") |
| **Annotation** | Commentaire/correction utilisateur ajoutée à un article (n'altère pas contenu source) |

### 11.4 Références Externes

**Documentation Technique** :

- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/current/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js App Router](https://nextjs.org/docs/app)
- [TipTap Editor](https://tiptap.dev/introduction)
- [Wikipedia MediaWiki Architecture](https://www.mediawiki.org/wiki/Manual:Architecture)

**Inspirations Design** :

- [Wikipedia Main Page](https://en.wikipedia.org/wiki/Main_Page)
- [Notion Knowledge Base](https://www.notion.so/help/guides/knowledge-base)
- [GitBook Documentation](https://docs.gitbook.com/)

**Standards & Best Practices** :

- [W3C Web Content Accessibility Guidelines (WCAG)](https://www.w3.org/WAI/WCAG21/quickref/)
- [Google Web Vitals](https://web.dev/vitals/)
- [Conventional Commits](https://www.conventionalcommits.org/)

---

## Changelog

| Date | Version | Changements |
|------|---------|-------------|
| 2026-03-11 | 1.0 | Création initiale - Document de prescription complet |

---

**Document généré pour OSMOSIS — Wikipedia Interne Structuré**
*Projet OSMOSE - Organic Semantic Memory Organization & Smart Extraction*
