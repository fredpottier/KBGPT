# 🧩 Type Studio — Design Document

## 1. 🎯 Objectif

Créer un **Type Studio** intégré à l’admin React pour permettre à un administrateur :
- de définir des *types de documents* (ex : "technique", "fonctionnel", "architecture", etc.)
- d’associer à chaque type un *ensemble d’entités et de relations prioritaires* pour guider l’analyse LLM lors de l’ingestion.
- d’alimenter dynamiquement la base d’entités Neo4j à partir de documents d’exemple, en mode *proposition/validation humaine*.
- d’apprendre continuellement : chaque ingestion peut proposer de nouvelles entités "pending", que l’administrateur peut approuver ou rejeter.

## 2. 🌍 Contexte d’Intégration

Le backend du projet est en **FastAPI**, l’UI en **React Admin**, et la plateforme repose sur :
- **Qdrant** pour les chunks textuels
- **Neo4j** pour les entités, relations et facts
- **Redis** pour les files de tâches et cache
- **LLM Vision (GPT-4o ou local fallback)** pour l’analyse unifiée des slides

L’objectif est de rendre la couche d’extraction **adaptative au type de document**, sans redéployer de prompt LLM à chaque évolution.

## 3. 🧠 Principe Fonctionnel

### Cas d’usage principal

1. L’administrateur crée un **nouveau type documentaire** (ex : “Technique”).
2. Il charge **un ou plusieurs documents d’exemple** représentatifs.
3. Le backend envoie ces documents à un **LLM d’analyse structurelle** qui propose :
   - une liste d’entités candidates (ex : SOLUTION, COMPONENT, TECHNOLOGY)
   - des relations sémantiques types (ex : "USES", "DEPENDS_ON", "CONNECTS_TO")
4. L’administrateur valide, édite ou rejette ces propositions.
5. Ces entités deviennent la *grammaire canonique* de ce type documentaire.
6. Lorsqu’un nouveau PPTX du même type est ingéré :
   - le LLM reçoit la *grammaire prioritaire* du type
   - il détecte d’abord les entités connues avant d’en proposer de nouvelles
7. Les nouvelles entités détectées sont insérées avec le statut **pending**
   - et visibles dans la section “Pending Entities” du Type Studio
8. L’administrateur peut alors :
   - valider → elles rejoignent la grammaire du type
   - rejeter → suppression et ajout à la liste “ignored_entities”

## 4. 🌿 Architecture Conceptuelle

### Vue d’ensemble

┌───────────────────────────────────────────────┐
│ React Admin                                   │
│ (Type Studio Interface)                       │
└───────────────────────────────────────────────┘
                │
                ▼
        REST API (FastAPI backend)
                │
┌───────────────────────────────────────────────┐
│ TypeStudioService                             │
│ • CRUD Types                                  │
│ • Analyse LLM (propose entités)               │
│ • Validation Pending                          │
│ • Gestion catalogues                          │
└───────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────┐
│ Neo4j (KG)                                   │
│ • Stockage des entités                       │
│ • Relations Type→Entity                      │
│ • Statut (approved/pending)                  │
└───────────────────────────────────────────────┘

---

## 5. 🧩 Structure Technique

### A. Modèle de Données

#### Table/Collection “DocumentType”
- id : UUID
- name : string (“Technique”, “Fonctionnel”)
- description : string
- entity_set : [EntityType] (liste des entités approuvées)
- pending_entities : [EntityType] (en attente de validation)
- ignored_entities : [string] (liste des noms rejetés)
- created_at / updated_at

#### Table/Collection “EntityType”
- id : UUID
- label : string (ex : “COMPONENT”)
- description : string
- examples : [string]
- status : enum (“approved”, “pending”, “ignored”)
- origin_type_id : UUID (DocumentType d’origine)

---

### B. Modules FastAPI

#### `src/knowbase/api/routers/type_studio.py`
Endpoints :
- `POST /api/type-studio/types` → créer un type
- `GET /api/type-studio/types` → lister
- `POST /api/type-studio/{id}/analyze` → lancer analyse LLM sur documents
- `PUT /api/type-studio/{id}/approve` → approuver entités pending
- `PUT /api/type-studio/{id}/reject` → rejeter entités pending
- `GET /api/type-studio/{id}/entities` → liste complète (approved/pending/ignored)

#### `src/knowbase/services/type_studio_service.py`
Fonctions principales :
- `create_type(name, description)`
- `analyze_documents(type_id, files)`  
  → Appel LLM avec `prompt_type_discovery`
- `store_pending_entities(type_id, entities)`
- `approve_entity(type_id, entity_name)`
- `reject_entity(type_id, entity_name)`

---

### C. Prompts LLM

#### `prompt_type_discovery`
Objectif : Identifier les entités structurantes d’un corpus de documents représentatifs d’un type.
Entrée :

You are analyzing one or several PowerPoint or PDF documents representing a new document type.
Extract and list the core business entities and semantic relationships that are most relevant for this type.
Return your result as JSON:
{
"entities": [
{"name": "SOLUTION", "description": "..."},
{"name": "COMPONENT", "description": "..."},
{"name": "TECHNOLOGY", "description": "..."}
],
"relations": [
{"name": "USES", "subject": "COMPONENT", "object": "TECHNOLOGY"},
{"name": "BELONGS_TO", "subject": "COMPONENT", "object": "SOLUTION"}
]
}


#### `prompt_entity_extraction`
Objectif : Utiliser la *grammaire du type* pour guider l’extraction lors de l’ingestion.
Entrée :
You are analyzing a slide of type "Technique".
Entities to prioritize: ["SOLUTION", "COMPONENT", "TECHNOLOGY"]
Extract entities and relations using this grammar first, but if new concepts appear, propose them under "pending_entities".
Return a JSON with fields:
{
"entities": [...],
"relations": [...],
"pending_entities": [...]
}


---

## 6. 🖥️ Interface Admin (React)

### Page : `/admin/type-studio`

Sections :
1. **Liste des Types**
   - Tableau avec name, #entities, #pending, last update
   - Bouton “Créer Type”
   - Bouton “Analyser Documents”

2. **Écran Détail Type**
   - Tabs : [Approved] [Pending] [Ignored]
   - Liste entités + stats d’usage
   - Bouton “Approuver tout”, “Rejeter tout”
   - Upload de documents d’entraînement
   - Bouton “Analyser avec LLM”

3. **Vue Pending**
   - Tableau entités proposées (nom, score, fréquence, exemples)
   - Actions rapides : ✅ / ❌ / ✏️
   - Historique décisions

---

## 7. 🔄 Cycle de Vie d’un Type

Étapes :

1. Création du type
2. Analyse initiale LLM
3. Validation manuelle entités
4. Ingestion de nouveaux documents
5. Nouvelles entités proposées → pending
6. Validation ou rejet
7. Mise à jour du catalogue d’entités du type

---

## 8. ⚙️ Intégration avec le Pipeline d’Ingestion

Lorsqu’un PPTX est importé :
1. Le type est spécifié (ou "default" si non défini)
2. Le backend récupère la liste d’entités connues depuis TypeStudio
3. L’appel au LLM pour la slide inclut cette liste dans le prompt
4. Le LLM retourne les entités trouvées et les “pending”
5. Les entités validées sont ajoutées directement dans Neo4j
6. Les pending sont stockées sous `DocumentType.pending_entities`
7. Le backfill Neo4j n’est exécuté qu’après approbation

---

## 9. 🧱 Avantages de cette Architecture

- **Évolutive** : ajoute de nouveaux types sans toucher au code
- **Contrôlable** : l’humain garde la main sur les entités approuvées
- **Auto-apprenante** : enrichissement progressif via ingestion
- **LLM-agnostique** : fonctionne avec GPT-4o, Claude, ou modèle local
- **Compatible** : intégration naturelle avec Neo4j et Qdrant existants

---

## 10. ⚠️ Points d’Attention / Risques

| Risque | Description | Mitigation |
|--------|--------------|-------------|
| **Bruit initial** | L’analyse LLM d’un document type peut sur-générer des entités non pertinentes | Requérir validation manuelle initiale obligatoire |
| **Explosion des pending** | Trop d’entités en attente sur gros corpus | Implémenter un seuil de fréquence minimale pour proposition |
| **Coût LLM** | Analyse initiale coûteuse sur grands fichiers | Limiter la taille et n’analyser qu’un sous-ensemble de slides |
| **Divergence typologique** | Types mal définis ou trop similaires | Ajouter un système de tags et une vue “similar types” |
| **Mise à jour prompts** | Changements de schéma LLM à gérer | Centraliser prompts dans `config/prompts.yaml` versionnés |

---

## 11. ✅ Prochaines Étapes

1. Créer les tables `document_types` et `entities` (SQLAlchemy)
2. Implémenter `TypeStudioService` (analyse LLM + validation)
3. Créer les routes FastAPI correspondantes
4. Développer la page React Admin `/admin/type-studio`
5. Ajouter intégration dans `pptx_pipeline_neo4j.py` pour inclure `type_id`
6. Gérer le statut `pending` / `approved` côté Neo4j
7. Mettre en place les tests unitaires et d’intégration

---

## 12. 📎 Exemple de Flux Complet

1. L’admin crée un type “Technique”
2. Il charge 3 PPTX (SAP_BTP.pptx, Network_Arch.pptx, HANA_Sizing.pptx)
3. Le backend exécute `prompt_type_discovery`
   → propose `SOLUTION`, `COMPONENT`, `TECHNOLOGY`
4. L’admin valide
5. Plus tard, il ingère `New_Architecture_2025.pptx`
   → LLM détecte `COMPONENT`, `TECHNOLOGY`, et un nouveau terme `SERVICE_MESH`
6. `SERVICE_MESH` ajouté en pending
7. L’admin l’approuve → devient entité officielle du type “Technique”
8. Tous les prochains PPTX peuvent maintenant reconnaître `SERVICE_MESH`

---

**Statut :** Design approuvé pour implémentation pilote (backend + React Admin)
**Auteur :** Fred — 2025-10-05
