# 🎨 UI Admin Gestion Ontologies - Documentation

**Date** : 2025-10-05
**Statut** : ✅ Implémentée
**Objectif** : Interface complète pour gérer catalogues d'ontologies Knowledge Graph

---

## 📋 Vue d'Ensemble

Interface web permettant de **visualiser**, **éditer**, et **gérer** les catalogues de normalisation des entités du Knowledge Graph.

### Fonctionnalités Principales

✅ **Visualisation Catalogues** - Vue d'ensemble 6 types d'entités avec statistiques
✅ **CRUD Entités** - Créer, Modifier, Supprimer entités et aliases
✅ **Entités Non Cataloguées** - Liste détectées lors ingestion + workflow approbation
✅ **Workflow Validation** - Approuver (ajouter catalogue) ou Rejeter entités

---

## 🗂️ Structure UI

### Page Principale : `/admin/ontology`

**Affiche 6 cartes interactives** (une par EntityType) :

| Type | Label | Description | Icône |
|------|-------|-------------|-------|
| SOLUTION | Solutions | Solutions logicielles (ERP, CRM, etc.) | Apps |
| COMPONENT | Composants | Composants techniques (Load Balancer, API Gateway) | Memory |
| TECHNOLOGY | Technologies | Technologies/frameworks (Kubernetes, React) | Category |
| ORGANIZATION | Organisations | Entreprises (SAP, Microsoft, AWS) | Business |
| PERSON | Rôles | Rôles/postes (Architect, Developer) | Person |
| CONCEPT | Concepts | Concepts business/techniques (Microservices, DevOps) | Lightbulb |

**Statistiques par carte** :
- Nombre total d'entités cataloguées
- Nombre total d'aliases
- Top 3 catégories
- Vendors (si applicable)

**Actions** :
- Clic sur carte → Page détail catalogue
- Lien "Voir Entités Non Cataloguées" → Page uncataloged

---

### Page Détail Catalogue : `/admin/ontology/[type]`

**Tableau complet entités** avec colonnes :
- **Entity ID** : Identifiant unique (SNAKE_CASE)
- **Nom Canonique** : Nom officiel normalisé
- **Aliases** : Liste variantes (chips, collapse si > 3)
- **Catégorie** : Classification (ERP, Infrastructure, etc.)
- **Vendor** : Éditeur/fournisseur
- **Actions** : Modifier / Supprimer

**Dialog Création/Édition** :
- Champs : entity_id, canonical_name, aliases, category, vendor
- Validation : entity_id requis (création), canonical_name requis
- Hints : Format SNAKE_CASE_MAJUSCULES, aliases séparés virgule

**Exemple** :
```
Entity ID: LOAD_BALANCER
Canonical Name: Load Balancer
Aliases: LB, LoadBalancer, load-balancer
Category: Infrastructure
Vendor: (vide)
```

---

### Page Entités Non Cataloguées : `/admin/ontology/uncataloged`

**Tableau entités détectées** non normalisées :
- **Nom Brut** : Tel qu'extrait par LLM
- **Type** : SOLUTION, COMPONENT, etc.
- **Occurrences** : Nombre détections (alerte si > 5)
- **Première/Dernière Détection** : Timestamps
- **Tenants** : Liste tenants concernés
- **Actions** : Approuver ✅ / Rejeter ❌

**Dialog Approbation** :
- Pré-rempli avec suggestion entity_id (auto-généré)
- Canonical name = raw_name par défaut (éditable)
- raw_name ajouté automatiquement aux aliases
- Champs category, vendor optionnels

**Workflow** :
1. Admin clique **Approuver** sur entité
2. Complète/ajuste formulaire (entity_id, canonical_name, etc.)
3. Valide → Entité ajoutée au catalogue correspondant
4. Ingestions futures normaliseront automatiquement cette entité

**Exemple Workflow** :
```
Détecté: "Custom Load Balancer v2" (COMPONENT, 12 occurrences)

Approbation:
→ Entity ID: CUSTOM_LOAD_BALANCER
→ Canonical Name: Custom Load Balancer
→ Aliases: (auto: "Custom Load Balancer v2") + "CLB, custom-lb"
→ Category: Infrastructure
→ Vendor: (vide)

✅ Approuvé → Ajouté à config/ontologies/components.yaml
```

---

## 🔌 API Endpoints Utilisés

### Catalogues

```typescript
// Liste entités catalogue
GET /api/ontology/catalogs/{entity_type}/entities
Query: ?category=Infrastructure&vendor=SAP

// Récupérer entité
GET /api/ontology/catalogs/{entity_type}/entities/{entity_id}

// Créer entité
POST /api/ontology/catalogs/entities
Body: { entity_type, entity_id, canonical_name, aliases, category, vendor }

// Modifier entité
PUT /api/ontology/catalogs/{entity_type}/entities/{entity_id}
Body: { canonical_name, aliases, category, vendor }

// Supprimer entité
DELETE /api/ontology/catalogs/{entity_type}/entities/{entity_id}

// Statistiques catalogue
GET /api/ontology/catalogs/{entity_type}/statistics
```

### Entités Non Cataloguées

```typescript
// Liste uncataloged
GET /api/ontology/uncataloged
Query: ?entity_type=COMPONENT

// Approuver entité
POST /api/ontology/uncataloged/{entity_type}/approve?raw_name=...
Body: { entity_id, canonical_name, aliases, category, vendor }

// Rejeter entité
DELETE /api/ontology/uncataloged/{entity_type}/reject?raw_name=...
```

---

## 📊 Flux Utilisateur Complet

### Scénario 1 : Ajouter Manuellement une Entité

1. Navigation : `/admin/ontology` → Clic carte "Composants"
2. Page `/admin/ontology/component` s'ouvre
3. Clic bouton **"Nouvelle Entité"**
4. Remplir formulaire :
   - Entity ID: `API_GATEWAY`
   - Canonical Name: `API Gateway`
   - Aliases: `APIGW, api-gateway, gateway`
   - Category: `Integration`
5. Clic **"Créer"** → POST `/api/ontology/catalogs/entities`
6. Tableau rafraîchi → nouvelle entité visible

### Scénario 2 : Approuver Entité Non Cataloguée

1. Navigation : `/admin/ontology` → Clic **"Voir Entités Non Cataloguées"**
2. Page `/admin/ontology/uncataloged` liste entités
3. Sélection entité : "React 18" (TECHNOLOGY, 8 occurrences)
4. Clic icône ✅ Approuver
5. Dialog pré-rempli :
   - Entity ID: `REACT_18` (suggéré)
   - Canonical Name: `React 18`
   - Aliases: `(auto: React 18)` + ajout manuel `React18, react18`
   - Category: `Frontend Framework`
   - Vendor: `Meta`
6. Clic **"Approuver et Ajouter au Catalogue"**
7. POST `/api/ontology/uncataloged/TECHNOLOGY/approve?raw_name=React 18`
8. Success → Entité ajoutée à `config/ontologies/technologies.yaml`
9. Prochaines ingestions normaliseront "React 18" automatiquement

### Scénario 3 : Modifier Entité Existante

1. Navigation : `/admin/ontology/solution` (catalogue Solutions)
2. Recherche entité "SAP S/4HANA Cloud, Public Edition"
3. Clic icône ✏️ Modifier
4. Ajout alias : "S4 Cloud Public" aux aliases existants
5. Modification category: `ERP` → `ERP Cloud`
6. Clic **"Modifier"** → PUT `/api/ontology/catalogs/SOLUTION/entities/S4HANA_PUBLIC`
7. Catalogue YAML mis à jour → normalizer rechargera au prochain accès

---

## 🎨 Composants Frontend

### Fichiers Créés

```
frontend/src/app/admin/ontology/
├── page.tsx                    # Page principale (liste 6 catalogues)
├── [type]/
│   └── page.tsx                # Page détail catalogue (tableau + CRUD)
└── uncataloged/
    └── page.tsx                # Page entités non cataloguées (approbation)
```

### Technologies

- **Framework** : Next.js 14 (App Router)
- **UI** : Material-UI (MUI) v5
- **State** : React Hooks (useState, useEffect)
- **Routing** : next/navigation (useRouter, useParams)
- **API** : Fetch API (http://localhost:8000)

---

## 🚀 Utilisation

### 1. Lancer Services

```bash
# Backend FastAPI
docker-compose up app -d

# Frontend Next.js
cd frontend
npm run dev
```

### 2. Accéder UI Admin

```
http://localhost:3000/admin/ontology
```

### 3. Workflow Typique

**Après ingestion PPTX** :

1. Consulter `/admin/ontology/uncataloged`
2. Vérifier nouvelles entités détectées
3. Approuver entités fréquentes (occurrences > 5)
4. Rejeter entités non pertinentes
5. Vérifier catalogues mis à jour (`/admin/ontology/[type]`)

**Enrichissement manuel** :

1. Identifier entités manquantes dans domaine métier
2. Ajouter via `/admin/ontology/[type]` → Nouvelle Entité
3. Compléter canonical_name + aliases courants
4. Prochaines ingestions normaliseront automatiquement

---

## ✅ Avantages UI Admin

### Transparence
- ✅ Voir exactement quelles entités sont cataloguées
- ✅ Détecter rapidement entités non normalisées
- ✅ Statistiques temps réel par catalogue

### Contrôle
- ✅ Validation humaine avant ajout catalogue
- ✅ Workflow approbation/rejet explicite
- ✅ Édition/suppression facile

### Productivité
- ✅ Pas besoin éditer YAML manuellement
- ✅ Suggestions auto entity_id
- ✅ Interface visuelle vs commandes CLI

### Qualité
- ✅ Évite erreurs syntaxe YAML
- ✅ Validation formulaires (champs requis)
- ✅ Feedback immédiat (succès/erreur)

---

## 🔍 Exemples Visuels

### Page Liste Catalogues

```
┌─────────────────────────────────────────────────┐
│ 📚 Gestion des Catalogues d'Ontologies          │
├─────────────────────────────────────────────────┤
│                                                  │
│ [⚠️  Voir Entités Non Cataloguées]              │
│                                                  │
│ ┌───────────┐ ┌───────────┐ ┌───────────┐      │
│ │ Solutions │ │Components │ │Technologies│      │
│ │   Apps    │ │   Memory  │ │  Category  │      │
│ │           │ │           │ │            │      │
│ │ 54 entités│ │ 4 entités │ │ 6 entités  │      │
│ │ 150 alias │ │ 12 alias  │ │ 18 alias   │      │
│ │           │ │           │ │            │      │
│ │ ERP (20)  │ │Infra (2)  │ │Container(2)│      │
│ │ CRM (15)  │ │Data (1)   │ │Frontend(1) │      │
│ └───────────┘ └───────────┘ └───────────┘      │
└─────────────────────────────────────────────────┘
```

### Page Détail Catalogue (Components)

```
┌─────────────────────────────────────────────────────────┐
│ ← Catalogue : COMPONENT          [Nouvelle Entité +]    │
├─────────────────────────────────────────────────────────┤
│ Entity ID       │ Nom Canonique  │ Aliases             │
├─────────────────┼────────────────┼─────────────────────┤
│ LOAD_BALANCER   │ Load Balancer  │ LB, LoadBalancer,   │
│                 │                │ load-balancer (+0)  │
│                 │                │ [✏️ ][🗑️ ]           │
├─────────────────┼────────────────┼─────────────────────┤
│ API_GATEWAY     │ API Gateway    │ APIGW, api-gateway, │
│                 │                │ gateway (+0)        │
│                 │                │ [✏️ ][🗑️ ]           │
└─────────────────────────────────────────────────────────┘
```

### Page Entités Non Cataloguées

```
┌────────────────────────────────────────────────────────┐
│ ← ⚠️ Entités Non Cataloguées         [Actualiser ↻]  │
├────────────────────────────────────────────────────────┤
│ ℹ️  3 entités non cataloguées détectées.              │
├────────────────────────────────────────────────────────┤
│ Nom Brut              │Type      │Occur │Actions      │
├───────────────────────┼──────────┼──────┼─────────────┤
│ Custom Load Balancer  │COMPONENT │  12  │ [✅][❌]     │
│ Suggestion: CUSTOM_LOAD_BALANCER                      │
├───────────────────────┼──────────┼──────┼─────────────┤
│ React 18              │TECHNOLOGY│   8  │ [✅][❌]     │
│ Suggestion: REACT_18                                  │
└────────────────────────────────────────────────────────┘
```

---

## 📈 Métriques & Monitoring

### Indicateurs Clés

- **Taux Normalisation** : % entités cataloguées vs non cataloguées
  - Objectif : > 80%
  - Calcul : `(total_cataloged / (total_cataloged + total_uncataloged)) * 100`

- **Temps Approbation** : Délai moyen entre détection et approbation
  - Objectif : < 7 jours
  - Amélioration : Alertes automatiques si > 10 occurrences

- **Qualité Catalogues** : Nombre moyen aliases par entité
  - Objectif : ≥ 3 aliases/entité
  - Amélioration : Suggestions auto basées fréquence

### Logs Consultables

```bash
# Logs backend ontology
tail -f data/logs/ontology_service.log
tail -f data/logs/ontology_router.log
tail -f data/logs/entity_normalizer.log

# Logs frontend
# Console navigateur (F12) pour requêtes API
```

---

## 🔮 Évolutions Futures

### Phase 2 - Améliorations UX

- [ ] Recherche/filtrage dans tableaux (nom, category, vendor)
- [ ] Pagination si > 100 entités
- [ ] Export CSV catalogue complet
- [ ] Import CSV en masse (bulk upload)
- [ ] Historique modifications (audit trail)

### Phase 3 - Intelligence

- [ ] Suggestions auto aliases basées ML (fréquence cooccurrences)
- [ ] Détection doublons potentiels (similarité Levenshtein)
- [ ] Clustering entités similaires pour fusion
- [ ] Alertes auto si entité non cataloguée > X occurrences

### Phase 4 - Collaboration

- [ ] Commentaires/notes par entité
- [ ] Workflow validation multi-niveaux (proposer → approuver → publier)
- [ ] Notifications admin (email/Slack) nouveautés uncataloged

---

**Statut** : ✅ **UI Admin Opérationnelle**

**Prochaine Étape** : **Tester import PPTX complet** + vérifier détection entités non cataloguées + workflow approbation
