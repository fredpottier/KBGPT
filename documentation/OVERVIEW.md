# Architecture Overview

Knowbase est une plateforme de gestion de connaissances SAP combinant ingestion documentaire, recherche vectorielle, gouvernance de facts et graph de connaissances multi-tenant. Cette vue d’ensemble synthétise l’architecture applicative et le rôle de chaque dossier clé.

## Composants principaux

| Composant | Description | Technologies | Dossiers associés |
| --- | --- | --- | --- |
| **API Backend** | Application FastAPI orchestrant les endpoints publics et internes. Monte les ressources statiques et instancie les dépendances (clients LLM, Qdrant, Redis). | FastAPI, Pydantic, Uvicorn | `src/knowbase/api`, `app/main.py` |
| **Pipelines d’ingestion** | Détectent le type de document (PPTX/PDF/Excel), extraient le texte et les métadonnées, génèrent des embeddings et écrivent dans Qdrant. Lancement asynchrone via Redis Queue. | Python, RQ, PyMuPDF, python-pptx, pandas, SentenceTransformers | `src/knowbase/ingestion` |
| **Recherche vectorielle** | Encapsule la recherche et le reranking sur Qdrant avec synthèse de réponse LLM. | Qdrant, SentenceTransformers, OpenAI/Anthropic via `LLMRouter` | `src/knowbase/api/services/search.py`, `src/knowbase/common/clients` |
| **Gouvernance des facts** | API et services pour créer/valider/rejeter des facts, détecter les conflits et suivre les métriques de gouvernance. | Graphiti store, LLMRouter, Redis, JSON stores | `src/knowbase/api/routers/facts_*`, `src/knowbase/api/services/facts_*` |
| **Knowledge Graph** | Couche multi-tenant sur Graphiti (Neo4j + services auxiliaires) pour les entités/relations corporate et personnelles. | Graphiti, Neo4j, PostgreSQL (Graphiti), FastAPI | `src/knowbase/api/routers/knowledge_graph.py`, `src/knowbase/api/services/user_knowledge_graph.py`, `src/knowbase/common/graphiti` |
| **Gestion multi-tenant & utilisateurs** | Services persistant la hiérarchie de tenants (fichiers JSON) et la configuration utilisateur (fichiers + mémoire). Fournit endpoints de gestion. | Pydantic, fichiers JSON, FastAPI | `src/knowbase/api/routers/tenants.py`, `src/knowbase/api/services/tenant.py`, `src/knowbase/api/routers/users.py` |
| **Tracking des coûts LLM** | Endpoints de suivi/estimation des tokens et coûts, comparaison de providers et scénarios de migration. | TokenTracker, OpenAI/Anthropic tarifs, calculs Python | `src/knowbase/api/routers/token_analysis.py`, `src/knowbase/common/token_tracker.py` |
| **Interfaces utilisateur** | Frontend Next.js pour la recherche/chat, UI Streamlit historique pour les usages internes, scripts CLI. | Next.js, Chakra UI, Streamlit | `frontend/`, `ui/`, `src/knowbase/ui/` |

## Cartographie des dossiers

- `app/` – image Docker légère exposant FastAPI via `app/main.py` (réutilise `src/knowbase/api`).
- `src/knowbase/api/` – points d’entrée HTTP (`routers`), dépendances globales (`dependencies.py`), modèles Pydantic (`schemas`), logique métier (`services`), middleware (`middleware`).
- `src/knowbase/common/` – clients externes (OpenAI, Anthropic, Qdrant), routeur LLM, outils de logging, normalisation SAP, intégration Graphiti.
- `src/knowbase/config/` – settings Pydantic, gestion des chemins, chargement des prompts.
- `src/knowbase/ingestion/` – pipelines et workers RQ (dispatcher, jobs, worker), CLI utilitaires pour gérer Qdrant et générer des vignettes.
- `src/knowbase/ui/` – application Streamlit alternative reposant sur les mêmes services backend.
- `frontend/` et `ui/` – clients web (Next.js) et Streamlit packagés séparément.
- `scripts/` – scripts ponctuels d’import/export, validation Graphiti et Qdrant.
- `tests/`, `app/tests/` – suites de tests unitaires et d’intégration (identiques pour l’application packagée et le module source).

## Topologie runtime

```text
┌───────────┐     ┌───────────────┐     ┌────────────┐
│ Frontends │ --> │ FastAPI / RQ  │ --> │ Pipelines  │
└───────────┘     │  (Docker)    │     │ ingestion  │
      │           └─────┬────────┘     └────┬───────┘
      │                 │                  │
      ▼                 ▼                  ▼
┌─────────────┐   ┌──────────────┐   ┌────────────┐
│ Redis (RQ)  │   │ Qdrant       │   │ Graphiti   │
└─────────────┘   │ Vector store │   │ (Neo4j+DB) │
                  └──────────────┘   └────────────┘
```

- Les requêtes HTTP atteignent FastAPI (`create_app`) qui configure CORS, middleware `UserContext`, et instancie les clients partagés (`warm_clients`).
- Les imports volumineux sont insérés dans une queue Redis (`enqueue_*`) afin d’être traités par les workers RQ (`ingestion.queue.worker`).
- Qdrant stocke les embeddings (collections principale et `rfp_qa`), Graphiti gère les entités/relations, Redis DB1 conserve l’historique des imports, et le stockage disque (`/data`) accueille les fichiers normalisés, slides, thumbnails et exports.

## Interactions notables

- **LLMRouter** sélectionne dynamiquement le modèle LLM selon la tâche (vision, résumé, canonicalisation). Il trace les coûts via `TokenTracker`.
- **GraphitiTenantManager** assure l’isolation des données Knowledge Graph : endpoints `graphiti` et `knowledge-graph` passent par un gestionnaire singleton qui crée/configure les groupes Neo4j.
- **Import History** : `RedisImportHistoryService` suit l’état des jobs et expose des endpoints d’observabilité (`/api/imports/*`, `/api/status/{uid}`).
- **SAP Solutions** : un gestionnaire YAML enrichi par LLM maintient le dictionnaire des solutions et expose des API de recherche/résolution.
- **Facts Governance/Intelligence** : les endpoints `/api/facts` et `/api/facts/intelligence` combinent validations métiers, détection de conflits et recommandations IA.

Cette architecture découple clairement la couche API, les pipelines batch, les stores de connaissances (Qdrant, Graphiti) et les interfaces clients, facilitant l’extension de chaque sous-système.
