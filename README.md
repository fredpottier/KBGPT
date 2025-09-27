﻿# Knowbase - SAP Knowledge Management System

Knowbase est une plateforme dockerisÃ©e de gestion et recherche intelligente de documents SAP, utilisant des technologies d'Intelligence Artificielle pour l'indexation, la structuration et l'interrogation de bases de connaissances multi-formats.

## ðŸŽ¯ Contexte Fonctionnel

### Stack Technique & Outils

#### ðŸ§  **Intelligence Artificielle & Machine Learning**
- **Embeddings** : `intfloat/multilingual-e5-base` - ModÃ¨le multilingue HuggingFace pour la vectorisation sÃ©mantique de 768 dimensions
- **ReRanker** : `cross-encoder/ms-marco-MiniLM-L-6-v2` - Cross-encoder pour l'optimisation et le reranking des rÃ©sultats de recherche
- **LLM Router** : **SystÃ¨me multi-provider intelligent** - Routage automatique entre OpenAI (GPT-4o, GPT-4o-mini) et Anthropic (Claude-3.5-Sonnet, Claude-3.5-Haiku)
- **Configuration LLM** : **YAML centralisÃ©** - SÃ©lection dynamique des modÃ¨les par type de tÃ¢che avec paramÃ¨tres optimisÃ©s (tempÃ©rature, max_tokens)
- **Cache ModÃ¨les** : **HuggingFace Hub** - TÃ©lÃ©chargement et mise en cache locale des modÃ¨les ML

#### ðŸ—„ï¸ **Stockage & Base de DonnÃ©es**
- **Base Vectorielle** : **Qdrant v1.15.1** - Base de donnÃ©es vectorielle haute performance pour la recherche de similaritÃ©
- **Collections SpÃ©cialisÃ©es** : **Collections dÃ©diÃ©es Q/A RFP** - SÃ©paration logique des donnÃ©es avec recherche cascade
- **Queue de TÃ¢ches** : **Redis 7.2** - SystÃ¨me de files d'attente avec persistance AOF pour l'orchestration asynchrone
- **Historique d'Imports** : **Redis + Persistance** - Suivi complet des imports avec gestion de l'Ã©tat en temps rÃ©el
- **Stockage Fichiers** : SystÃ¨me de fichiers local avec organisation hiÃ©rarchique dans `/data`

#### ðŸš€ **Backend & API**
- **Framework API** : **FastAPI 0.110+** - Framework Python moderne avec auto-documentation OpenAPI/Swagger
- **Serveur ASGI** : **Uvicorn** - Serveur ASGI haute performance pour applications asynchrones
- **Queue Worker** : **RQ (Redis Queue)** - Traitement asynchrone des tÃ¢ches d'ingestion en arriÃ¨re-plan
- **Validation** : **Pydantic 2.8+** - Validation des donnÃ©es et sÃ©rialisation avec type hints

#### ðŸ–¥ï¸ **Interface Utilisateur**
- **Frontend Moderne** : **Next.js 14 + TypeScript** - Interface web rÃ©active avec Chakra UI
- **Dashboard Legacy** : **Streamlit 1.48+** - Interface web interactive pour la visualisation et recherche
- **Visualisation** : **Pandas + Streamlit** - Tableaux de bord et graphiques pour l'analyse des donnÃ©es
- **UI Components** : Composants React modernes avec gestion d'Ã©tat avancÃ©e

#### ðŸŒ **Exposition & Tunneling**
- **Tunnel Public** : **Ngrok** - Exposition sÃ©curisÃ©e de l'API locale via tunnel HTTPS
- **Domaine Fixe** : Configuration de domaine personnalisÃ© pour intÃ©grations GPT
- **CORS** : Gestion des politiques de partage de ressources cross-origin

#### ðŸ³ **Conteneurisation & Orchestration**
- **Conteneurs** : **Docker** - Environnement isolÃ© et reproductible pour chaque service
- **Orchestration** : **Docker Compose** - Orchestration multi-services avec networking
- **Volumes** : Persistance des donnÃ©es Qdrant et cache des modÃ¨les
- **Networks** : RÃ©seau Docker privÃ© `knowbase_net` pour communication inter-services

#### ðŸ“„ **Traitement de Documents**
- **PDF** : **Poppler-utils** + **PyPDF2** - Extraction de texte et conversion PDF vers images
- **PowerPoint** : **python-pptx** - Analyse et extraction de contenu des prÃ©sentations
- **Excel** : **Pandas + Openpyxl** - Traitement des donnÃ©es tabulaires et mÃ©tadonnÃ©es
- **OCR** : **Tesseract** - Reconnaissance optique de caractÃ¨res pour images et PDF scannÃ©s
- **Images** : **Pillow** - GÃ©nÃ©ration de vignettes et manipulation d'images

#### ðŸ§ª **Tests & QualitÃ©**
- **Framework de Tests** : **Pytest 7.4+** - Tests unitaires et d'intÃ©gration
- **Mocking** : **Pytest-mock** - Simulation des dÃ©pendances externes
- **Couverture** : **Coverage.py** - Mesure de la couverture de code
- **Client HTTP** : **HTTPX** - Tests des endpoints FastAPI en mode asynchrone

#### âš™ï¸ **Configuration & Logging**
- **Variables d'Environnement** : **Pydantic Settings** - Gestion centralisÃ©e de la configuration
- **Logging** : **Loguru** - SystÃ¨me de logs structurÃ©s avec rotation automatique
- **Configuration** : **YAML** - Fichiers de configuration pour prompts et paramÃ¨tres

### Formats de Documents SupportÃ©s
- **PrÃ©sentations** : PowerPoint (.pptx) avec extraction de texte, mÃ©tadonnÃ©es et gÃ©nÃ©ration de vignettes
- **Documents** : PDF avec OCR intÃ©grÃ© et extraction de contenu structurÃ©
- **Tableurs** : Excel (.xlsx/.xls) avec traitement des donnÃ©es tabulaires et formules
- **Texte** : Formats Word (.docx) et fichiers texte brut (.txt, .md)

### CapacitÃ©s de Recherche AvancÃ©es
- **Recherche SÃ©mantique** : BasÃ©e sur la similaritÃ© cosinus des embeddings vectoriels avec Qdrant
- **Recherche Cascade Intelligente** : Q/A RFP prioritaire (seuil 0.85) puis base de connaissances gÃ©nÃ©rale (seuil 0.70)
- **Collections SpÃ©cialisÃ©es** : SÃ©paration Q/A RFP et base de connaissances pour une pertinence optimisÃ©e
- **Filtrage Multi-CritÃ¨res** : Par solution SAP, type de document, dates, auteurs, mÃ©tadonnÃ©es personnalisÃ©es
- **ReRanking Intelligent** : Optimisation de la pertinence avec modÃ¨les cross-encoder
- **API RESTful** : Interface programmatique complÃ¨te avec documentation Swagger automatique
- **Recherche Hybride** : Combinaison recherche vectorielle + filtres traditionnels pour une prÃ©cision maximale

## ðŸ—ï¸ Architecture du Projet

### Structure des RÃ©pertoires

```
knowbase/
â”œâ”€â”€ ðŸ“ app/                          # Application FastAPI conteneurisÃ©e
â”‚   â”œâ”€â”€ main.py                      # Point d'entrÃ©e de l'API
â”‚   â”œâ”€â”€ Dockerfile                   # Configuration conteneur backend
â”‚   â””â”€â”€ requirements.txt             # DÃ©pendances Python
â”‚
â”œâ”€â”€ ðŸ“ frontend/                     # Interface Next.js moderne
â”‚   â”œâ”€â”€ ðŸ“ src/                      # Code source React/TypeScript
â”‚   â”‚   â”œâ”€â”€ ðŸ“ app/                  # App Router Next.js 14
â”‚   â”‚   â”‚   â”œâ”€â”€ chat/page.tsx        # Interface de chat intelligent
â”‚   â”‚   â”‚   â”œâ”€â”€ documents/           # Gestion des documents
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ import/page.tsx  # Import de documents
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ status/page.tsx  # Suivi des imports
â”‚   â”‚   â”‚   â”‚   â””â”€â”€ rfp/page.tsx     # Workflows RFP spÃ©cialisÃ©s
â”‚   â”‚   â”‚   â”œâ”€â”€ rfp-excel/page.tsx   # Page dÃ©diÃ©e RFP Excel
â”‚   â”‚   â”‚   â””â”€â”€ admin/page.tsx       # Interface d'administration
â”‚   â”‚   â”œâ”€â”€ ðŸ“ components/           # Composants React rÃ©utilisables
â”‚   â”‚   â”‚   â”œâ”€â”€ ðŸ“ layout/           # Composants de mise en page
â”‚   â”‚   â”‚   â””â”€â”€ ðŸ“ ui/               # Composants d'interface
â”‚   â”‚   â””â”€â”€ ðŸ“ lib/                  # Utilitaires et configuration
â”‚   â”œâ”€â”€ Dockerfile                   # Configuration conteneur frontend
â”‚   â”œâ”€â”€ package.json                 # DÃ©pendances Node.js
â”‚   â””â”€â”€ next.config.js               # Configuration Next.js
â”‚
â”œâ”€â”€ ðŸ“ ui/                           # Interface utilisateur Streamlit (legacy)
â”‚   â”œâ”€â”€ Dockerfile                   # Configuration conteneur UI
â”‚   â”œâ”€â”€ requirements.txt             # DÃ©pendances UI
â”‚   â””â”€â”€ src/                         # Sources interface
â”‚
â”œâ”€â”€ ðŸ“ src/knowbase/                 # Code source principal (architecture modulaire)
â”‚   â”œâ”€â”€ ðŸ“ api/                      # Couche API FastAPI
â”‚   â”‚   â”œâ”€â”€ main.py                  # Configuration FastAPI
â”‚   â”‚   â”œâ”€â”€ dependencies.py          # Injection de dÃ©pendances
â”‚   â”‚   â”œâ”€â”€ ðŸ“ routers/              # Endpoints API
â”‚   â”‚   â”‚   â”œâ”€â”€ search.py            # Recherche de documents avec cascade
â”‚   â”‚   â”‚   â”œâ”€â”€ ingest.py            # Ingestion de contenu multi-format
â”‚   â”‚   â”‚   â”œâ”€â”€ status.py            # Statut systÃ¨me et monitoring
â”‚   â”‚   â”‚   â””â”€â”€ imports.py           # Gestion historique des imports
â”‚   â”‚   â”œâ”€â”€ ðŸ“ services/             # Logique mÃ©tier
â”‚   â”‚   â”‚   â”œâ”€â”€ search.py            # Service de recherche avec cascade
â”‚   â”‚   â”‚   â”œâ”€â”€ ingestion.py         # Service d'ingestion Ã©tendu
â”‚   â”‚   â”‚   â”œâ”€â”€ status.py            # Service de monitoring avancÃ©
â”‚   â”‚   â”‚   â”œâ”€â”€ synthesis.py         # SynthÃ¨se de rÃ©ponses intelligente
â”‚   â”‚   â”‚   â”œâ”€â”€ import_history.py    # Historique des imports
â”‚   â”‚   â”‚   â”œâ”€â”€ import_history_redis.py # Persistance Redis des imports
â”‚   â”‚   â”‚   â””â”€â”€ import_deletion.py   # Suppression complÃ¨te d'imports
â”‚   â”‚   â””â”€â”€ ðŸ“ schemas/              # ModÃ¨les de donnÃ©es Pydantic
â”‚   â”‚       â””â”€â”€ search.py            # SchÃ©mas de requÃªte/rÃ©ponse
â”‚   â”‚
â”‚   â”œâ”€â”€ ðŸ“ ingestion/                # Pipeline d'ingestion modulaire
â”‚   â”‚   â”œâ”€â”€ ðŸ“ pipelines/            # Pipelines de traitement par format
â”‚   â”‚   â”‚   â”œâ”€â”€ pptx_pipeline.py     # Traitement PowerPoint (filtrage slides amÃ©liorÃ©)
â”‚   â”‚   â”‚   â”œâ”€â”€ pdf_pipeline.py      # Traitement PDF
â”‚   â”‚   â”‚   â”œâ”€â”€ excel_pipeline.py    # Traitement Excel Q/A pour collection RFP
â”‚   â”‚   â”‚   â””â”€â”€ fill_excel_pipeline.py # Remplissage RFP avec recherche cascade
â”‚   â”‚   â”œâ”€â”€ ðŸ“ processors/           # Processeurs de contenu
â”‚   â”‚   â”œâ”€â”€ ðŸ“ queue/                # Orchestration RQ (Redis Queue)
â”‚   â”‚   â”‚   â”œâ”€â”€ dispatcher.py        # Distribution des tÃ¢ches
â”‚   â”‚   â”‚   â”œâ”€â”€ worker.py            # ExÃ©cution des tÃ¢ches
â”‚   â”‚   â”‚   â””â”€â”€ connection.py        # Configuration Redis
â”‚   â”‚   â””â”€â”€ ðŸ“ cli/                  # Utilitaires en ligne de commande
â”‚   â”‚       â”œâ”€â”€ purge_collection.py  # Nettoyage des collections
â”‚   â”‚       â”œâ”€â”€ test_search_qdrant.py # Tests de recherche
â”‚   â”‚       â””â”€â”€ generate_thumbnails.py # GÃ©nÃ©ration vignettes
â”‚   â”‚
â”‚   â”œâ”€â”€ ðŸ“ common/                   # Composants partagÃ©s
â”‚   â”‚   â”œâ”€â”€ ðŸ“ clients/              # Clients externes
â”‚   â”‚   â”‚   â”œâ”€â”€ qdrant_client.py     # Client base vectorielle avec collections Q/A
â”‚   â”‚   â”‚   â”œâ”€â”€ openai_client.py     # Client OpenAI
â”‚   â”‚   â”‚   â”œâ”€â”€ anthropic_client.py  # Client Anthropic (Claude)
â”‚   â”‚   â”‚   â”œâ”€â”€ embeddings.py        # ModÃ¨les d'embeddings
â”‚   â”‚   â”‚   â”œâ”€â”€ reranker.py          # Cross-encoder pour reranking
â”‚   â”‚   â”‚   â””â”€â”€ shared_clients.py    # Factory des clients
â”‚   â”‚   â”œâ”€â”€ llm_router.py            # Routeur intelligent multi-provider
â”‚   â”‚   â”œâ”€â”€ ðŸ“ sap/                  # Logique mÃ©tier SAP
â”‚   â”‚   â”‚   â”œâ”€â”€ normalizer.py        # Normalisation des donnÃ©es
â”‚   â”‚   â”‚   â”œâ”€â”€ claims.py            # Gestion des assertions
â”‚   â”‚   â”‚   â””â”€â”€ solutions_dict.py    # Catalogue solutions SAP
â”‚   â”‚   â””â”€â”€ logging.py               # Configuration centralisÃ©e des logs
â”‚   â”‚
â”‚   â”œâ”€â”€ ðŸ“ config/                   # Configuration et paramÃ©trage
â”‚   â”‚   â”œâ”€â”€ settings.py              # Variables d'environnement
â”‚   â”‚   â”œâ”€â”€ prompts_loader.py        # Chargeur de prompts LLM
â”‚   â”‚   â””â”€â”€ paths.py                 # Gestion des chemins et migration
â”‚   â”‚
â”‚   â””â”€â”€ ðŸ“ ui/                       # Interface Streamlit modulaire
â”‚       â””â”€â”€ streamlit_app.py         # Application Streamlit
â”‚
â”œâ”€â”€ ðŸ“ config/                       # Configuration externe
â”‚   â”œâ”€â”€ prompts.yaml                 # Prompts LLM paramÃ©trables par famille
â”‚   â””â”€â”€ llm_models.yaml              # Configuration multi-provider des modÃ¨les LLM
â”‚
â”œâ”€â”€ ðŸ“ data/                         # DonnÃ©es runtime centralisÃ©es
â”‚   â”œâ”€â”€ ðŸ“ docs_in/                  # Documents en attente d'ingestion
â”‚   â”œâ”€â”€ ðŸ“ docs_done/                # Documents traitÃ©s et archivÃ©s
â”‚   â”œâ”€â”€ ðŸ“ logs/                     # Journaux d'application
â”‚   â”œâ”€â”€ ðŸ“ models/                   # Cache modÃ¨les HuggingFace
â”‚   â”œâ”€â”€ ðŸ“ status/                   # Fichiers de statut systÃ¨me
â”‚   â””â”€â”€ ðŸ“ public/                   # Assets publics
â”‚       â”œâ”€â”€ ðŸ“ slides/               # Slides extraites des PPTX
â”‚       â”œâ”€â”€ ðŸ“ thumbnails/           # Vignettes gÃ©nÃ©rÃ©es
â”‚       â”œâ”€â”€ ðŸ“ pdfs/                 # PDFs traitÃ©s
â”‚       â””â”€â”€ ðŸ“ pdf_slides/           # Slides PDF extraites
â”‚
â”œâ”€â”€ ðŸ“ tests/                        # Suite de tests (pytest)
â”‚   â”œâ”€â”€ conftest.py                  # Configuration des tests
â”‚   â”œâ”€â”€ ðŸ“ api/                      # Tests de l'API
â”‚   â”œâ”€â”€ ðŸ“ common/                   # Tests des composants communs
â”‚   â”œâ”€â”€ ðŸ“ config/                   # Tests de configuration
â”‚   â””â”€â”€ ðŸ“ ingestion/                # Tests d'ingestion
â”‚
â”œâ”€â”€ docker-compose.yml               # Orchestration des services
â”œâ”€â”€ .env                             # Variables d'environnement
â”œâ”€â”€ requirements.txt                 # DÃ©pendances Python globales
â”œâ”€â”€ pytest.ini                      # Configuration des tests
â””â”€â”€ ngrok.yml                        # Configuration tunnel ngrok
```

### Services ConteneurisÃ©s

#### ðŸ” **knowbase-qdrant**
- **Base vectorielle** : Stockage et recherche de vecteurs d'embeddings
- **Port** : 6333
- **Volume** : `qdrant_data` pour la persistance
- **Configuration** : Stockage optimisÃ© pour les performances

#### ðŸ“Š **knowbase-redis**
- **Queue de tÃ¢ches** : Orchestration des pipelines d'ingestion
- **Port** : 6379
- **Usage** : Distribution asynchrone des tÃ¢ches de traitement

#### ðŸš€ **knowbase-app** (Backend FastAPI)
- **API principale** : Endpoints de recherche, ingestion et monitoring
- **Port** : 8000 (configurable via `APP_PORT`)
- **Features** : Auto-documentation Swagger, CORS, gestion d'erreurs
- **Nouvelles API** : Historique d'imports, suppression complÃ¨te, endpoints RFP Excel
- **Volumes** : Code source, donnÃ©es runtime (`/data`)

#### ðŸ‘¨â€ðŸ’» **knowbase-worker** (Processeur d'ingestion)
- **Traitement** : ExÃ©cution des pipelines d'ingestion en arriÃ¨re-plan
- **Queue** : BasÃ© sur RQ (Redis Queue)
- **Formats** : PPTX, PDF, Excel, DOCX avec OCR et extraction

#### ðŸ–¥ï¸ **knowbase-frontend** (Interface Next.js)
- **Frontend Moderne** : Interface React avec TypeScript et Chakra UI
- **Port** : 3000 (configurable via `FRONTEND_PORT`)
- **Features** : Chat intelligent, gestion imports, workflows RFP Excel, interface admin
- **Architecture** : App Router Next.js 14, composants modulaires, API routes

#### ðŸ–¥ï¸ **knowbase-ui** (Interface Streamlit - Legacy)
- **Dashboard** : Visualisation des donnÃ©es indexÃ©es (mode hÃ©ritÃ©)
- **Port** : 8501 (configurable via `APP_UI_PORT`)
- **Features** : Recherche interactive, filtrage, statistiques

#### ðŸŒ **knowbase-ngrok** (Tunnel Public)
- **Exposition** : Tunnel sÃ©curisÃ© pour accÃ¨s externe
- **Usage** : IntÃ©gration GPT personnalisÃ©, webhooks
- **Domain** : Configuration via `NGROK_DOMAIN`

## ðŸš€ DÃ©marrage du Projet

### PrÃ©requis
```bash
# VÃ©rifier Docker et Docker Compose
docker --version
docker-compose --version

# Cloner le projet
git clone <votre-repo>
cd knowbase
```

### Configuration
```bash
# Copier et configurer l'environnement
cp .env.example .env

# Variables essentielles Ã  configurer :
# OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key (optionnel, pour Claude)
# NGROK_AUTHTOKEN=your-ngrok-token (optionnel)
# NGROK_DOMAIN=your-domain.ngrok.app (optionnel)
```

### Lancement des Services
```bash
# Construction et dÃ©marrage de tous les services
docker-compose up --build

# DÃ©marrage en arriÃ¨re-plan
docker-compose up -d --build

# Suivi des logs
docker-compose logs -f
```

### AccÃ¨s aux Services
Une fois dÃ©marrÃ©s, les services sont accessibles via :

- **ðŸŒ Frontend Moderne** : `http://localhost:3000` (Interface Next.js recommandÃ©e)
- **ðŸ“š API Documentation** : `http://localhost:8000/docs` (Swagger UI)
- **ðŸ–¥ï¸ Interface Streamlit** : `http://localhost:8501` (Interface legacy)
- **ðŸ” Base Qdrant** : `http://localhost:6333/dashboard`
- **ðŸŒ Tunnel Ngrok** : VÃ©rifiez les logs pour l'URL publique

## ðŸ› ï¸ Utilisation

### Ingestion de Documents

#### Via Interface Next.js (RecommandÃ©e)
1. AccÃ©dez Ã  `http://localhost:3000`
2. Naviguez vers "Documents" â†’ "Import fichier"
3. Utilisez le drag-and-drop pour dÃ©poser vos documents
4. Suivez le statut de traitement en temps rÃ©el dans "Suivi imports"
5. GÃ©rez les imports avec possibilitÃ© de suppression complÃ¨te

#### Via Workflows RFP Excel SpÃ©cialisÃ©s
1. AccÃ©dez Ã  "RFP Excel" dans la navigation
2. **Import Questions/RÃ©ponses** : Uploadez des fichiers Excel Q/A avec configuration des colonnes
3. **Remplir RFP vide** : Uploadez des RFP vides pour remplissage automatique via recherche cascade

#### Via Interface Streamlit (Legacy)
1. AccÃ©dez Ã  `http://localhost:8501`
2. Utilisez la section "Upload" pour dÃ©poser vos documents
3. Suivez le statut de traitement dans l'interface

#### Via API
```bash
# Upload d'un document
curl -X POST "http://localhost:8000/ingest" \
     -H "Content-Type: application/json" \
     -d '{"file_path": "/data/docs_in/document.pptx", "document_type": "technical"}'
```

#### Via CLI (dans le conteneur)
```bash
# Entrer dans le conteneur
docker-compose exec app bash

# Utiliser les utilitaires CLI
python -m knowbase.ingestion.cli.test_search_qdrant --query "S/4HANA implementation"
python -m knowbase.ingestion.cli.purge_collection --collection knowbase
python -m knowbase.ingestion.cli.generate_thumbnails --docs-in /data/docs_in
```

### Recherche de Documents

#### Via API
```bash
# Recherche sÃ©mantique
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "How to configure S/4HANA Cloud?",
       "solution": "S/4HANA Private Cloud",
       "top_k": 5
     }'
```

#### Via Interface
- Interface de recherche intuitive dans Streamlit
- Filtrage par solution SAP, type de document
- Visualisation des rÃ©sultats avec scores de pertinence

## ðŸ§ª Tests et QualitÃ©

### ExÃ©cution des Tests
```bash
# Tests unitaires et d'intÃ©gration
docker-compose exec app pytest

# Tests avec couverture
docker-compose exec app pytest --cov=src/knowbase


# Tests spÃ©cifiques
docker-compose exec app pytest tests/api/
docker-compose exec app pytest tests/ingestion/ -k "test_pptx"
```

### QualitÃ© du Code
```bash
# Linting
docker-compose exec app ruff check src/

# Formatage
docker-compose exec app ruff format src/

# VÃ©rification des types
docker-compose exec app mypy src/
```

## ðŸ› Debug et DÃ©veloppement

### Debug SÃ©lectif des Services

Le projet supporte le debugging ciblÃ© de chaque service indÃ©pendamment via VS Code et debugpy.

#### Configuration des Variables Debug

**Variables d'environnement dans `.env` :**
```bash
# Debug sÃ©lectif (recommandÃ©)
DEBUG_APP=false      # Debug FastAPI sur port 5678
DEBUG_WORKER=false   # Debug Worker sur port 5679
```

#### Modes de Debug Disponibles

**ðŸš€ Mode Production (par dÃ©faut)**
```bash
DEBUG_APP=false
DEBUG_WORKER=false
```
- Les deux services dÃ©marrent normalement
- Aucun blocage d'attente de debugger

**ðŸ” Debug FastAPI seulement**
```bash
DEBUG_APP=true
DEBUG_WORKER=false
```
- Worker dÃ©marre normalement
- FastAPI attend connexion debugger sur port 5678

**âš™ï¸ Debug Worker seulement**
```bash
DEBUG_APP=false
DEBUG_WORKER=true
```
- FastAPI dÃ©marre normalement
- Worker attend connexion debugger sur port 5679

**ðŸ”§ Debug des deux services**
```bash
DEBUG_APP=true
DEBUG_WORKER=true
```
- Les deux services attendent connexion debugger
- NÃ©cessite deux sessions de debug sÃ©parÃ©es

#### Configuration VS Code

**Ajouter dans `.vscode/launch.json` :**
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "ðŸš€ Attach to FastAPI App",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/src",
                    "remoteRoot": "/app/src"
                },
                {
                    "localRoot": "${workspaceFolder}/app",
                    "remoteRoot": "/app"
                }
            ],
            "justMyCode": false
        },
        {
            "name": "ðŸ”§ Attach to Worker",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5679
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/src",
                    "remoteRoot": "/app/src"
                },
                {
                    "localRoot": "${workspaceFolder}/app",
                    "remoteRoot": "/app"
                }
            ],
            "justMyCode": false
        }
    ]
}
```

#### Workflow de Debug

**Debug d'un endpoint API :**
1. Modifier `.env` : `DEBUG_APP=true`, `DEBUG_WORKER=false`
2. `docker-compose up app`
3. VS Code â†’ Run & Debug â†’ "ðŸš€ Attach to FastAPI App"
4. Placer breakpoints dans `src/knowbase/api/`
5. Tester l'endpoint via Swagger ou client

**Debug d'un pipeline d'ingestion :**
1. Modifier `.env` : `DEBUG_APP=false`, `DEBUG_WORKER=true`
2. `docker-compose up ingestion-worker`
3. VS Code â†’ Run & Debug â†’ "ðŸ”§ Attach to Worker"
4. Placer breakpoints dans `src/knowbase/ingestion/pipelines/`
5. DÃ©clencher un job d'ingestion

**Debug d'un flow complet :**
1. DÃ©bugger l'endpoint API (voir ci-dessus)
2. Stopper le debug, modifier `.env` pour activer debug worker
3. Relancer avec debug worker pour suivre le traitement
4. Analyser le flow end-to-end

#### Ports de Debug
- **FastAPI App** : `localhost:5678`
- **Worker RQ** : `localhost:5679`

#### Bonnes Pratiques Debug
- âœ… Utiliser le debug sÃ©lectif pour Ã©viter les blocages
- âœ… Placer des breakpoints avant de dÃ©marrer les services
- âœ… Utiliser `justMyCode: false` pour dÃ©buguer les dÃ©pendances
- âœ… VÃ©rifier les path mappings VS Code pour la rÃ©solution de fichiers
- âš ï¸ Ã‰viter `DEBUG_APP=true` et `DEBUG_WORKER=true` simultanÃ©ment sauf besoin spÃ©cifique

## ðŸ§  SystÃ¨me LLM Multi-Provider

Knowbase utilise un systÃ¨me intelligent de routage LLM qui optimise automatiquement les coÃ»ts et performances selon le type de tÃ¢che.

### âš™ï¸ Configuration YAML CentralisÃ©e

Le fichier `config/llm_models.yaml` permet de configurer dynamiquement les modÃ¨les sans modification de code :

```yaml
# Mapping tÃ¢che -> modÃ¨le optimisÃ©
task_models:
  vision: "gpt-4o"                           # Analyse d'images (multimodal)
  metadata: "gpt-4o"                         # Extraction JSON structurÃ©e
  long_summary: "claude-3-5-sonnet-20241022" # RÃ©sumÃ©s longs (qualitÃ©)
  enrichment: "claude-3-5-haiku-20241022"    # Enrichissement (Ã©conomique)
  classification: "gpt-4o-mini"              # Classification binaire
  canonicalization: "gpt-4o-mini"            # Normalisation SAP

# ParamÃ¨tres optimisÃ©s par tÃ¢che
task_parameters:
  vision:
    temperature: 0.2    # CohÃ©rence image-texte
    max_tokens: 1024    # Analyses dÃ©taillÃ©es
  metadata:
    temperature: 0.1    # DÃ©terministe pour JSON
    max_tokens: 2000    # MÃ©tadonnÃ©es complÃ¨tes
  classification:
    temperature: 0      # Binaire dÃ©terministe
    max_tokens: 5       # RÃ©ponses ultra-courtes
  # ... configurations par tÃ¢che
```

### ðŸŽ¯ Types de TÃ¢ches SupportÃ©es

| TÃ¢che | ModÃ¨le OptimisÃ© | Usage | Ã‰conomies |
|-------|------------------|-------|-----------|
| **Vision** | GPT-4o | Analyse slides PowerPoint, PDF | Baseline |
| **Metadata** | GPT-4o | Extraction mÃ©tadonnÃ©es JSON | Baseline |
| **Long Summary** | Claude-3.5-Sonnet | RÃ©sumÃ©s de documents longs | QualitÃ©++ |
| **Enrichment** | Claude-3.5-Haiku | Enrichissement de contenu | **80%** |
| **Classification** | GPT-4o-mini | Questions oui/non | **95%** |
| **Canonicalization** | GPT-4o-mini | Normalisation noms SAP | **90%** |

### ðŸ”„ Providers et Fallbacks

```yaml
providers:
  openai:
    models: ["gpt-4o", "gpt-4o-mini", "o1-preview"]
  anthropic:
    models: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]

# Fallbacks automatiques en cas d'indisponibilitÃ©
fallback_strategy:
  long_summary:
    - "claude-3-5-sonnet-20241022"  # PrÃ©fÃ©rÃ©
    - "gpt-4o"                      # Fallback 1
    - "gpt-4o-mini"                 # Fallback 2
```

### ðŸ’° Optimisation des CoÃ»ts

Le systÃ¨me apporte des **Ã©conomies de 60-80%** sur les coÃ»ts LLM :

```bash
# Avant (tout en GPT-4o)
â€¢ Classification: $0.125 par requÃªte
â€¢ Canonicalisation: $0.100 par requÃªte
â€¢ Enrichissement: $0.080 par requÃªte

# AprÃ¨s (routage optimisÃ©)
â€¢ Classification: $0.006 par requÃªte (-95%)
â€¢ Canonicalisation: $0.010 par requÃªte (-90%)
â€¢ Enrichissement: $0.016 par requÃªte (-80%)
```

### ðŸš€ Configuration AvancÃ©e

```bash
# Variables d'environnement optionnelles pour override
export MODEL_VISION="gpt-4o"
export MODEL_METADATA="claude-3-5-sonnet-20241022"
export MODEL_FAST="gpt-4o-mini"

# Test de la configuration
python -m knowbase.common.llm_router --test-config
```

### âš™ï¸ Prompts Configurables

SystÃ¨me de prompts paramÃ©trables dans `config/prompts.yaml` :

**Familles disponibles :**
- **default** : Analyse gÃ©nÃ©rique
- **technical** : Focus technique
- **functional** : Accent mÃ©tier

```bash
# Forcer un type de document
python -m knowbase.ingestion.pipelines.pptx_pipeline document.pptx --document-type functional
```

### ðŸ“Š TraÃ§abilitÃ© et Monitoring

Chaque appel LLM est tracÃ© avec :
```json
{
  "llm_meta": {
    "model_used": "claude-3-5-haiku-20241022",
    "task_type": "enrichment",
    "provider": "anthropic",
    "temperature": 0.3,
    "max_tokens": 1000,
    "cost_estimated": 0.016
  },
  "prompt_meta": {
    "document_type": "functional",
    "prompts_version": "2024-09-18"
  }
}
```

## ðŸ”§ Administration et Maintenance

### Monitoring
```bash
# Statut des services
docker-compose ps

# Logs en temps rÃ©el
docker-compose logs -f app
docker-compose logs -f worker

# Statut systÃ¨me via API
curl http://localhost:8000/status
```

### Nettoyage
```bash
# Purge d'une collection Qdrant
python -m knowbase.ingestion.cli.purge_collection --collection knowbase --yes

# Nettoyage des logs
docker-compose exec app find /data/logs -name "*.log" -mtime +7 -delete
```

### Sauvegarde
```bash
# Sauvegarde des donnÃ©es
docker-compose exec app tar -czf /data/backup-$(date +%Y%m%d).tar.gz /data

# Sauvegarde Qdrant
docker-compose exec qdrant cp -r /qdrant/storage /qdrant/backup
```

## ðŸŽ¯ Roadmap et Ã‰volutions

### Ã€ Court Terme
- [x] **Interface web moderne (Next.js + TypeScript)** - âœ… ImplÃ©mentÃ©e avec Chakra UI
- [x] **Gestion avancÃ©e des imports** - âœ… Historique, tracking, suppression complÃ¨te
- [x] **Workflows RFP Excel spÃ©cialisÃ©s** - âœ… Import Q/A et remplissage automatique
- [x] **Collections dÃ©diÃ©es Q/A** - âœ… Recherche cascade intelligente
- [ ] Centralisation complÃ¨te du chargement des modÃ¨les ML
- [ ] SystÃ¨me de claims pour la gestion d'incohÃ©rences

### Ã€ Moyen Terme
- [ ] Support multi-tenant avec isolation des donnÃ©es
- [ ] API de webhooks pour intÃ©grations externes
- [ ] SystÃ¨me de notifications push

### Ã€ Long Terme
- [ ] IA conversationnelle intÃ©grÃ©e (RAG avancÃ©)
- [ ] Analytics et mÃ©triques d'usage avancÃ©es
- [ ] DÃ©ploiement cloud-native (Kubernetes)

## ðŸ“Š Badges & MÃ©triques

[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14+-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5+-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Chakra UI](https://img.shields.io/badge/Chakra_UI-2.8+-319795?logo=chakraui&logoColor=white)](https://chakra-ui.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.48+-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org/)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.15+-DC382D?logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Redis](https://img.shields.io/badge/Redis-7.2+-DC382D?logo=redis&logoColor=white)](https://redis.io/)

---

## ðŸ‘¥ Contribution

Ce projet suit une architecture modulaire permettant l'extensibilitÃ© et la maintenance. Les dÃ©veloppeurs peuvent :

- Ajouter de nouveaux formats de documents via les pipelines d'ingestion
- Ã‰tendre l'API avec de nouveaux endpoints dans `src/knowbase/api/routers/`
- CrÃ©er des processeurs personnalisÃ©s dans `src/knowbase/ingestion/processors/`
- ImplÃ©menter des clients pour de nouveaux services externes
- DÃ©velopper des composants React personnalisÃ©s dans `frontend/src/components/`
- Ajouter des pages Next.js dans `frontend/src/app/`

**DÃ©veloppÃ© avec â¤ï¸ pour optimiser la gestion des connaissances SAP**
