# Routes API Frontend - Documentation Complète

*Dernière mise à jour : 2025-10-08*

Ce document liste toutes les routes API proxy du frontend Next.js qui redirigent vers le backend FastAPI.

## 📋 Table des matières

- [Admin & Système](#admin--système)
- [Document Types](#document-types)
- [Entity Types](#entity-types)
- [Entities](#entities)
- [Documents & Imports](#documents--imports)
- [SAP Solutions](#sap-solutions)
- [Jobs & Status](#jobs--status)
- [Search](#search)

---

## Admin & Système

### GET /api/health
**Description:** Health check du système
**Backend:** `GET /api/health`
**Authentification:** Aucune
**Réponse:** Statut de santé du backend

### GET /api/admin/health
**Description:** Health check détaillé des composants (Qdrant, Neo4j, Redis)
**Backend:** `GET /api/admin/health`
**Authentification:** Header `X-Admin-Key`
**Réponse:** Statut de chaque composant avec métriques

### POST /api/admin/purge-data
**Description:** Purge complète des données d'ingestion (Qdrant, Neo4j, Redis)
**Backend:** `POST /api/admin/purge-data`
**Authentification:** Header `X-Admin-Key`
**Body:** Aucun
**Réponse:** Résultats de purge par composant (points/nodes/jobs supprimés)

---

## Document Types

### GET /api/document-types
**Description:** Liste tous les types de documents
**Backend:** `GET /api/document-types`
**Query params:** `is_active=true` (optionnel)
**Réponse:** Liste des document types

### GET /api/document-types/templates
**Description:** Liste les templates de types de documents
**Backend:** `GET /api/document-types/templates`
**Réponse:** Templates disponibles pour création rapide

### POST /api/document-types/analyze
**Description:** Analyse un document sample pour suggérer entity types
**Backend:** `POST /api/document-types/analyze-sample`
**Body:** `{ file: File, existing_types?: string[] }`
**Réponse:** Types d'entités suggérés

### GET /api/document-types/[id]
**Description:** Récupère un type de document par ID
**Backend:** `GET /api/document-types/{id}`
**Réponse:** Détails du document type

### GET /api/document-types/[id]/entity-types
**Description:** Liste les entity types associés à un document type
**Backend:** `GET /api/document-types/{id}/entity-types`
**Réponse:** Liste des entity types liés

### GET /api/document-types/[id]/entity-types/[entityType]
**Description:** Vérifie l'association entre document type et entity type
**Backend:** `GET /api/document-types/{id}/entity-types/{entityType}`
**Réponse:** Détails de l'association

### PUT /api/document-types/[id]
**Description:** Met à jour un type de document
**Backend:** `PUT /api/document-types/{id}`
**Authentification:** Header `X-Admin-Key`
**Body:** `{ name?: string, slug?: string, description?: string, context_prompt?: string, is_active?: boolean }`
**Réponse:** Type de document mis à jour

### DELETE /api/document-types/[id]
**Description:** Supprime un type de document
**Backend:** `DELETE /api/document-types/{id}`
**Authentification:** Header `X-Admin-Key`
**Réponse:** 204 No Content

### POST /api/document-types/[id]/entity-types
**Description:** Ajoute des types d'entités suggérés à un type de document
**Backend:** `POST /api/document-types/{id}/entity-types`
**Authentification:** Header `X-Admin-Key`
**Body:** `{ entity_types: string[], source?: string }`
**Réponse:** Associations créées

---

## Entity Types

### GET /api/entity-types
**Description:** Liste tous les types d'entités
**Backend:** `GET /api/entity-types`
**Query params:** `status`, `tenant`, `limit`, `offset`
**Réponse:** Liste des entity types avec compteurs

### GET /api/entity-types/[typeName]
**Description:** Récupère les infos d'un type d'entité
**Backend:** `GET /api/entity-types/{typeName}`
**Réponse:** Détails du type (status, entity_count, pending_entity_count, etc.)

### GET /api/entity-types/[typeName]/snapshots
**Description:** Liste les snapshots (versions) d'un entity type
**Backend:** `GET /api/entity-types/{typeName}/snapshots`
**Réponse:** Historique des snapshots pour rollback

### POST /api/entity-types/[typeName]/generate-ontology
**Description:** Génère des propositions de normalisation (ontologie canonique)
**Backend:** `POST /api/entity-types/{typeName}/generate-ontology`
**Authentification:** Header `X-Admin-Key`
**Query params:** `include_validated=true/false`
**Body:** `{ model_preference: 'claude-sonnet' | 'gpt-4o' }`
**Réponse:** Job ID pour polling

### POST /api/entity-types/[typeName]/normalize-entities
**Description:** Lance la normalisation des entités vers leurs formes canoniques
**Backend:** `POST /api/entity-types/{typeName}/normalize-entities`
**Authentification:** Header `X-Admin-Key`
**Body:** `{ normalization_job_id: string }`
**Réponse:** Résultat de la normalisation

### POST /api/entity-types/[typeName]/undo-normalization
**Description:** Annule la dernière normalisation
**Backend:** `POST /api/entity-types/{typeName}/undo-normalization`
**Authentification:** Header `X-Admin-Key`
**Réponse:** Confirmation de l'annulation

### POST /api/entity-types/[typeName]/merge-into/[targetType]
**Description:** Fusionne un type d'entité dans un autre
**Backend:** `POST /api/entity-types/{typeName}/merge-into/{targetType}`
**Authentification:** Header `X-Admin-Key`
**Réponse:** Résultat de la fusion

### POST /api/entity-types/[typeName]/approve
**Description:** Approuve un type d'entité découvert
**Backend:** `POST /api/entity-types/{typeName}/approve`
**Authentification:** Header `X-Admin-Key`
**Body:** `{ admin_email: string, admin_key?: string }`
**Réponse:** Confirmation d'approbation

### POST /api/entity-types/[typeName]/reject
**Description:** Rejette un type d'entité découvert
**Backend:** `POST /api/entity-types/{typeName}/reject`
**Authentification:** Header `X-Admin-Key`
**Body:** `{ admin_email: string, rejection_reason: string, admin_key?: string }`
**Réponse:** Confirmation de rejet

### POST /api/entity-types/import-yaml
**Description:** Importe une ontologie YAML de types d'entités
**Backend:** `POST /api/entity-types/import-yaml`
**Authentification:** Header `X-Admin-Key`
**Body:** FormData avec `file` (fichier YAML)
**Réponse:** Nombre de types importés

### GET /api/entity-types/export-yaml
**Description:** Exporte les types d'entités en YAML
**Backend:** `GET /api/entity-types/export-yaml`
**Query params:** `status=approved|pending|all`
**Réponse:** Fichier YAML en téléchargement

---

## Entities

### GET /api/entities
**Description:** Liste les entités d'un type spécifique
**Backend:** `GET /api/entities`
**Query params:** `entity_type=TYPE_NAME`, `status=pending|approved`
**Réponse:** Liste des entités avec leurs valeurs et statuts

### POST /api/entities/[uuid]/approve
**Description:** Approuve une entité individuelle
**Backend:** `POST /api/entities/{uuid}/approve`
**Authentification:** Header `X-Admin-Key` (via body)
**Body:** `{ admin_email: string, admin_key?: string }`
**Réponse:** Confirmation d'approbation

### PATCH /api/entities/[uuid]/change-type
**Description:** Change le type d'une entité (déplacement vers un autre type)
**Backend:** `PATCH /api/entities/{uuid}/change-type`
**Authentification:** Header `X-Admin-Key` (via body)
**Body:** `{ new_entity_type: string, admin_key?: string }`
**Réponse:** Confirmation du changement

---

## Documents & Imports

### POST /api/dispatch
**Description:** Dispatch un document vers le pipeline approprié (PPTX, PDF, Excel)
**Backend:** `POST /api/dispatch`
**Body:** FormData avec `file`, `document_type_id` (optionnel), `meta` (optionnel)
**Réponse:** Job ID et informations de dispatch

### POST /api/documents/upload-excel-qa
**Description:** Upload et ingestion d'un fichier Excel Q/A
**Backend:** `POST /api/ingest/excel-qa`
**Body:** FormData avec `file` et `meta` (client, topic, solution, etc.)
**Réponse:** Job ID

### POST /api/documents/analyze-excel
**Description:** Analyse un fichier Excel pour extraction de métadonnées
**Backend:** `POST /api/ingest/analyze-excel`
**Body:** FormData avec `file`
**Réponse:** Métadonnées extraites (client, topic, solution, date)

### POST /api/documents/fill-rfp-excel
**Description:** Remplit un fichier Excel RFP avec des réponses de la base
**Backend:** `POST /api/ingest/rfp-fill`
**Body:** FormData avec `file` et `meta`
**Réponse:** Job ID

### GET /api/downloads/filled-rfp/[uid]
**Description:** Télécharge un fichier RFP rempli
**Backend:** `GET /api/downloads/filled-rfp/{uid}`
**Réponse:** Fichier Excel en stream

### GET /api/imports/active
**Description:** Liste les imports en cours
**Backend:** `GET /api/imports/active`
**Réponse:** Liste des imports actifs avec progression

### GET /api/imports/history
**Description:** Liste l'historique des imports
**Backend:** `GET /api/imports/history`
**Query params:** `limit`, `offset`
**Réponse:** Historique paginé des imports

### DELETE /api/imports/[uid]/delete
**Description:** Supprime complètement un import (chunks Qdrant + historique)
**Backend:** `DELETE /api/imports/{uid}/delete`
**Réponse:** Confirmation de suppression avec nombre de chunks supprimés

### POST /api/imports/sync
**Description:** Synchronise les imports orphelins (récupère imports Redis non trackés)
**Backend:** `POST /api/imports/sync`
**Authentification:** Header `X-Admin-Key`
**Réponse:** Nombre d'imports synchronisés

### GET /api/status/[uid]
**Description:** Récupère le statut détaillé d'un import
**Backend:** `GET /api/status/{uid}`
**Réponse:** Progression détaillée, étape courante, logs

---

## SAP Solutions

### GET /api/sap-solutions
**Description:** Liste toutes les solutions SAP du catalogue
**Backend:** `GET /api/sap-solutions`
**Réponse:** Liste des solutions avec détails

### POST /api/sap-solutions/resolve
**Description:** Résout une solution SAP à partir d'un nom partiel
**Backend:** `POST /api/sap-solutions/resolve`
**Body:** `{ solution_name: string }`
**Réponse:** Solution complète avec détails

### GET /api/sap-solutions/with-chunks
**Description:** Liste les solutions SAP qui ont des chunks dans Qdrant
**Backend:** `GET /api/sap-solutions/with-chunks`
**Réponse:** Solutions avec nombre de chunks associés

---

## Jobs & Status

### GET /api/jobs/[id]
**Description:** Récupère le statut d'un job RQ
**Backend:** `GET /api/jobs/{id}`
**Réponse:** Statut du job (queued, started, finished, failed) avec métadonnées

---

## Search

### POST /api/search
**Description:** Recherche vectorielle dans la base de connaissances
**Backend:** `POST /api/search`
**Body:** `{ query: string, collection?: string, limit?: number }`
**Réponse:** Résultats de recherche avec scores de similarité

---

## 🔑 Authentification

Certaines routes requièrent une authentification admin via le header `X-Admin-Key`.

**Clé par défaut (dev):** `admin-dev-key-change-in-production`

**Routes nécessitant l'authentification:**
- `/api/admin/*` (toutes les routes admin)
- Actions sur entity types (generate-ontology, normalize, merge, undo)
- Actions sur entities (approve, change-type)

---

## 🏗️ Architecture

Toutes ces routes sont des **proxies Next.js** qui :
1. Reçoivent la requête du frontend
2. La transmettent au backend FastAPI (`BACKEND_URL` = `http://app:8000`)
3. Retournent la réponse au client

**Avantages:**
- CORS simplifié (même origine pour le frontend)
- Possibilité d'ajouter de la logique middleware
- Headers d'authentification gérés côté serveur
- Streaming de fichiers supporté

---

## 📝 Notes importantes

1. **Routes manquantes récurrentes:** Si une route API retourne une erreur HTML au lieu de JSON, vérifier que la route proxy existe bien dans `frontend/src/app/api/`

2. **Hot reload:** Next.js en mode dev devrait détecter les nouvelles routes automatiquement, mais un restart du frontend peut être nécessaire (`docker compose restart frontend`)

3. **Paramètres dynamiques:** Les routes avec `[param]` utilisent la syntaxe Next.js App Router

4. **FormData vs JSON:**
   - Upload de fichiers → FormData
   - Données structurées → JSON

5. **Error handling:** Toutes les routes incluent un try/catch avec logs d'erreur et réponses HTTP appropriées

---

## 🔍 Debugging

Pour vérifier qu'une route proxy fonctionne:

```bash
# Tester directement le backend
curl http://localhost:8000/api/entity-types/SOLUTION

# Tester via le proxy frontend
curl http://localhost:3000/api/entity-types/SOLUTION

# Vérifier les logs
docker compose logs --tail 50 frontend | grep "Compiling"
docker compose logs --tail 50 app | grep "GET /api"
```

---

**Maintenance:** Ce fichier doit être mis à jour lors de l'ajout de nouvelles routes API.
