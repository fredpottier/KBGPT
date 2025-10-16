# Documentation de Référence - Projet Knowbase SAP KB

*Document de référence pour Claude Code - Version générée le 2025-09-22*

## 🎯 Résumé Exécutif

**Knowbase** est une plateforme dockerisée de gestion et recherche intelligente de documents SAP utilisant l'IA pour l'indexation et l'interrogation de bases de connaissances multi-formats.

**Technologies principales** : FastAPI + Next.js 14 + TypeScript + Qdrant + Redis + Docker
**Architecture** : Microservices conteneurisés avec interface moderne React et API REST
**Objectif** : Optimiser la gestion des connaissances SAP avec recherche sémantique avancée

## 🏗️ Architecture Technique

### Services Docker Principaux
```yaml
# docker-compose.yml - 7 services principaux
knowbase-qdrant:     # Base vectorielle (port 6333)
knowbase-redis:      # Queue de tâches (port 6379)
knowbase-app:        # API FastAPI (port 8000)
knowbase-worker:     # Processeur d'ingestion
knowbase-frontend:   # Interface Next.js (port 3000)
knowbase-ui:         # Interface Streamlit legacy (port 8501)
knowbase-ngrok:      # Tunnel public
```

### Structure Répertoires Critiques
```
C:\Project\SAP_KB\
├── src/knowbase/              # Code source principal Python
│   ├── api/                   # API FastAPI (routers, services, schemas)
│   ├── ingestion/             # Pipelines de traitement documents
│   ├── common/                # Clients externes (Qdrant, OpenAI, Anthropic)
│   └── config/                # Configuration centralisée
├── frontend/src/              # Interface Next.js moderne
│   ├── app/                   # App Router Next.js 14
│   ├── components/            # Composants React réutilisables
│   └── lib/                   # Utilitaires TypeScript
├── config/                    # Configuration YAML externe
│   ├── llm_models.yaml        # Configuration LLM multi-provider
│   ├── prompts.yaml           # Prompts configurables
│   └── sap_solutions.yaml     # Catalogue solutions SAP
├── data/                      # Données runtime
│   ├── docs_in/               # Documents à traiter
│   ├── docs_done/             # Documents traités
│   └── public/                # Assets publics (slides, thumbnails)
└── app/                       # Point d'entrée Docker FastAPI
```

## 🔧 Commandes Essentielles

### Démarrage/Arrêt
```bash
# Démarrage complet (SANS rebuild automatique)
docker-compose up -d

# Arrêt propre
docker-compose down

# Rebuild manuel si nécessaire (utilisateur décide)
docker-compose build
docker-compose up -d --build

# Logs monitoring
docker-compose logs -f [service_name]
```

### Tests et Qualité
```bash
# Tests dans le conteneur
docker-compose exec app pytest
docker-compose exec app pytest --cov=src/knowbase

# Linting et formatting
docker-compose exec app ruff check src/
docker-compose exec app ruff format src/
docker-compose exec app mypy src/
```

### Debug (Configurations dans .env)
```bash
# Debug sélectif FastAPI
DEBUG_APP=true DEBUG_WORKER=false

# Debug sélectif Worker
DEBUG_APP=false DEBUG_WORKER=true

# Ports debug : FastAPI=5678, Worker=5679
```

## 🌐 Endpoints Principaux

### API Backend (port 8000)
```
GET  /docs                    # Documentation Swagger
POST /search                  # Recherche sémantique
POST /ingest                  # Ingestion documents
GET  /status                  # Statut système
GET  /imports/history         # Historique imports
DELETE /imports/{uid}         # Suppression import
```

### Frontend (port 3000)
```
/                            # Accueil
/chat                        # Interface chat intelligent
/documents/import            # Import de documents
/documents/status            # Suivi des imports
/rfp-excel                   # Workflows RFP Excel
/admin                       # Interface administration
```

## 📁 Fichiers de Configuration Clés

### Variables d'Environnement (.env)
```bash
# API Keys obligatoires
OPENAI_API_KEY=your-key
ANTHROPIC_API_KEY=your-key

# Ports configurables
APP_PORT=8000
FRONTEND_PORT=3000
APP_UI_PORT=8501

# Debug
DEBUG_APP=false
DEBUG_WORKER=false

# Ngrok (optionnel)
NGROK_AUTHTOKEN=your-token
NGROK_DOMAIN=your-domain.ngrok.app
```

### LLM Multi-Provider (config/llm_models.yaml)
```yaml
# Routage intelligent par tâche
task_models:
  vision: "gpt-4o"                           # Analyse images
  metadata: "gpt-4o"                         # Extraction JSON
  long_summary: "claude-3-5-sonnet-20241022" # Résumés longs
  enrichment: "claude-3-5-haiku-20241022"    # Enrichissement
  classification: "gpt-4o-mini"              # Classification
```

## 🔍 Formats Documents Supportés

### Pipelines d'Ingestion
```python
# src/knowbase/ingestion/pipelines/
pptx_pipeline.py      # PowerPoint (.pptx)
pdf_pipeline.py       # PDF avec OCR
excel_pipeline.py     # Excel Q/A pour RFP
fill_excel_pipeline.py # Remplissage RFP automatique
```

### Collections Qdrant
```
rfp_qa               # Questions/Réponses RFP (seuil 0.85)
knowbase             # Base connaissances générale (seuil 0.70)
```

## 🧠 Intelligence Artificielle

### Modèles Embeddings
```python
# intfloat/multilingual-e5-base - 768 dimensions
# cross-encoder/ms-marco-MiniLM-L-6-v2 - ReRanker
```

### Recherche Cascade
```
1. Recherche prioritaire dans rfp_qa (seuil 0.85)
2. Fallback sur knowbase général (seuil 0.70)
3. ReRanking intelligent des résultats
```

## 🚀 Workflows Typiques

### Import de Documents
```
1. Frontend : Drag-and-drop dans /documents/import
2. API : POST /ingest → Queue Redis → Worker
3. Processing : Pipeline selon format → Qdrant
4. Monitoring : Statut temps réel dans /documents/status
```

### Recherche Sémantique
```
1. Frontend : Interface chat ou recherche
2. API : POST /search avec query + filtres
3. Qdrant : Recherche vectorielle cascade
4. LLM : Synthèse et enrichissement réponse
```

### RFP Excel Workflows
```
# Import Q/A
1. Upload Excel Q/A → /rfp-excel
2. Configuration colonnes → excel_pipeline.py
3. Indexation dans collection rfp_qa

# Remplissage RFP
1. Upload RFP vide → /rfp-excel
2. Recherche cascade automatique
3. Génération réponses via LLM
4. Export Excel complété
```

## 🔧 Points d'Attention Maintenance

### Performance
- Collections Qdrant séparées pour optimiser la recherche
- Cache modèles HuggingFace dans /data/models
- Routage LLM intelligent pour réduire coûts (60-80% économies)

### Monitoring
- Logs structurés avec Loguru dans /data/logs
- Statut système via endpoint /status
- Historique complet imports avec Redis persistance

### Sécurité
- Variables d'environnement pour API keys
- CORS configuré pour frontend
- Tunnel Ngrok sécurisé pour accès externe

## 🎯 Développement

### Ajout Nouveaux Formats
```python
# 1. Créer pipeline : src/knowbase/ingestion/pipelines/new_format_pipeline.py
# 2. Ajouter processeur : src/knowbase/ingestion/processors/
# 3. Configurer router : src/knowbase/api/routers/ingest.py
# 4. Tests : tests/ingestion/test_new_format.py
```

### Extension Frontend
```typescript
// 1. Composant : frontend/src/components/features/
// 2. Page : frontend/src/app/new-feature/page.tsx
// 3. API route : frontend/src/app/api/new-endpoint/
// 4. Types : frontend/src/types/
```

### Configuration LLM
```yaml
# Modifier config/llm_models.yaml pour nouveaux modèles
# Ajouter prompts dans config/prompts.yaml
# Tester avec src/knowbase/common/llm_router.py
```

## ⚡ Optimisations Récentes

- ✅ Interface Next.js 14 moderne avec TypeScript
- ✅ Collections dédiées Q/A RFP
- ✅ Workflows Excel spécialisés
- ✅ Système LLM multi-provider avec routage intelligent
- ✅ Historique complet des imports avec suppression
- ✅ Monitoring temps réel avec heartbeat
- ✅ Debug sélectif par service

## 📊 Métriques Performance

### Recherche
- Recherche vectorielle < 100ms
- Cascade Q/A → General < 200ms
- Synthèse LLM 1-3s selon modèle

### Ingestion
- PPTX : 2-5s par document
- PDF avec OCR : 5-15s selon taille
- Excel Q/A : 10-30s selon lignes

### Coûts LLM (optimisés)
- Classification : $0.006/requête (-95%)
- Canonicalisation : $0.010/requête (-90%)
- Enrichissement : $0.016/requête (-80%)

---

*Cette documentation sert de référence rapide pour comprendre le projet sans exploration extensive. Dernière mise à jour : 2025-09-22*