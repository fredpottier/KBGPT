# Knowbase - SAP Knowledge Management System

Knowbase est une plateforme dockerisée de gestion et recherche intelligente de documents SAP, utilisant des technologies d'Intelligence Artificielle pour l'indexation, la structuration et l'interrogation de bases de connaissances multi-formats.

## 🎯 Contexte Fonctionnel

### Stack Technique & Outils

#### 🧠 **Intelligence Artificielle & Machine Learning**
- **Embeddings** : `intfloat/multilingual-e5-base` - Modèle multilingue HuggingFace pour la vectorisation sémantique de 768 dimensions
- **ReRanker** : `cross-encoder/ms-marco-MiniLM-L-6-v2` - Cross-encoder pour l'optimisation et le reranking des résultats de recherche
- **LLM Router** : **Système multi-provider intelligent** - Routage automatique entre OpenAI (GPT-4o, GPT-4o-mini) et Anthropic (Claude-3.5-Sonnet, Claude-3.5-Haiku)
- **Configuration LLM** : **YAML centralisé** - Sélection dynamique des modèles par type de tâche avec paramètres optimisés (température, max_tokens)
- **Cache Modèles** : **HuggingFace Hub** - Téléchargement et mise en cache locale des modèles ML

#### 🗄️ **Stockage & Base de Données**
- **Base Vectorielle** : **Qdrant v1.15.1** - Base de données vectorielle haute performance pour la recherche de similarité
- **Collections Spécialisées** : **Collections dédiées Q/A RFP** - Séparation logique des données avec recherche cascade
- **Queue de Tâches** : **Redis 7.2** - Système de files d'attente avec persistance AOF pour l'orchestration asynchrone
- **Historique d'Imports** : **Redis + Persistance** - Suivi complet des imports avec gestion de l'état en temps réel
- **Stockage Fichiers** : Système de fichiers local avec organisation hiérarchique dans `/data`

#### 🚀 **Backend & API**
- **Framework API** : **FastAPI 0.110+** - Framework Python moderne avec auto-documentation OpenAPI/Swagger
- **Serveur ASGI** : **Uvicorn** - Serveur ASGI haute performance pour applications asynchrones
- **Queue Worker** : **RQ (Redis Queue)** - Traitement asynchrone des tâches d'ingestion en arrière-plan
- **Validation** : **Pydantic 2.8+** - Validation des données et sérialisation avec type hints

#### 🖥️ **Interface Utilisateur**
- **Frontend Moderne** : **Next.js 14 + TypeScript** - Interface web réactive avec Chakra UI
- **Dashboard Legacy** : **Streamlit 1.48+** - Interface web interactive pour la visualisation et recherche
- **Visualisation** : **Pandas + Streamlit** - Tableaux de bord et graphiques pour l'analyse des données
- **UI Components** : Composants React modernes avec gestion d'état avancée

#### 🌐 **Exposition & Tunneling**
- **Tunnel Public** : **Ngrok** - Exposition sécurisée de l'API locale via tunnel HTTPS
- **Domaine Fixe** : Configuration de domaine personnalisé pour intégrations GPT
- **CORS** : Gestion des politiques de partage de ressources cross-origin

#### 🐳 **Conteneurisation & Orchestration**
- **Conteneurs** : **Docker** - Environnement isolé et reproductible pour chaque service
- **Orchestration** : **Docker Compose** - Orchestration multi-services avec networking
- **Volumes** : Persistance des données Qdrant et cache des modèles
- **Networks** : Réseau Docker privé `knowbase_net` pour communication inter-services

#### 📄 **Traitement de Documents**
- **PDF** : **Poppler-utils** + **PyPDF2** - Extraction de texte et conversion PDF vers images
- **PowerPoint** : **python-pptx** - Analyse et extraction de contenu des présentations
- **Excel** : **Pandas + Openpyxl** - Traitement des données tabulaires et métadonnées
- **OCR** : **Tesseract** - Reconnaissance optique de caractères pour images et PDF scannés
- **Images** : **Pillow** - Génération de vignettes et manipulation d'images

#### 🧪 **Tests & Qualité**
- **Framework de Tests** : **Pytest 7.4+** - Tests unitaires et d'intégration
- **Mocking** : **Pytest-mock** - Simulation des dépendances externes
- **Couverture** : **Coverage.py** - Mesure de la couverture de code
- **Client HTTP** : **HTTPX** - Tests des endpoints FastAPI en mode asynchrone

#### ⚙️ **Configuration & Logging**
- **Variables d'Environnement** : **Pydantic Settings** - Gestion centralisée de la configuration
- **Logging** : **Loguru** - Système de logs structurés avec rotation automatique
- **Configuration** : **YAML** - Fichiers de configuration pour prompts et paramètres

### Formats de Documents Supportés
- **Présentations** : PowerPoint (.pptx) avec extraction de texte, métadonnées et génération de vignettes
- **Documents** : PDF avec OCR intégré et extraction de contenu structuré
- **Tableurs** : Excel (.xlsx/.xls) avec traitement des données tabulaires et formules
- **Texte** : Formats Word (.docx) et fichiers texte brut (.txt, .md)

### Capacités de Recherche Avancées
- **Recherche Sémantique** : Basée sur la similarité cosinus des embeddings vectoriels avec Qdrant
- **Recherche Cascade Intelligente** : Q/A RFP prioritaire (seuil 0.85) puis base de connaissances générale (seuil 0.70)
- **Collections Spécialisées** : Séparation Q/A RFP et base de connaissances pour une pertinence optimisée
- **Filtrage Multi-Critères** : Par solution SAP, type de document, dates, auteurs, métadonnées personnalisées
- **ReRanking Intelligent** : Optimisation de la pertinence avec modèles cross-encoder
- **API RESTful** : Interface programmatique complète avec documentation Swagger automatique
- **Recherche Hybride** : Combinaison recherche vectorielle + filtres traditionnels pour une précision maximale

## 🏗️ Architecture du Projet

### Structure des Répertoires

```
knowbase/
├── 📁 app/                          # Application FastAPI conteneurisée
│   ├── main.py                      # Point d'entrée de l'API
│   ├── Dockerfile                   # Configuration conteneur backend
│   └── requirements.txt             # Dépendances Python
│
├── 📁 frontend/                     # Interface Next.js moderne
│   ├── 📁 src/                      # Code source React/TypeScript
│   │   ├── 📁 app/                  # App Router Next.js 14
│   │   │   ├── chat/page.tsx        # Interface de chat intelligent
│   │   │   ├── documents/           # Gestion des documents
│   │   │   │   ├── import/page.tsx  # Import de documents
│   │   │   │   ├── status/page.tsx  # Suivi des imports
│   │   │   │   └── rfp/page.tsx     # Workflows RFP spécialisés
│   │   │   ├── rfp-excel/page.tsx   # Page dédiée RFP Excel
│   │   │   └── admin/page.tsx       # Interface d'administration
│   │   ├── 📁 components/           # Composants React réutilisables
│   │   │   ├── 📁 layout/           # Composants de mise en page
│   │   │   └── 📁 ui/               # Composants d'interface
│   │   └── 📁 lib/                  # Utilitaires et configuration
│   ├── Dockerfile                   # Configuration conteneur frontend
│   ├── package.json                 # Dépendances Node.js
│   └── next.config.js               # Configuration Next.js
│
├── 📁 ui/                           # Interface utilisateur Streamlit (legacy)
│   ├── Dockerfile                   # Configuration conteneur UI
│   ├── requirements.txt             # Dépendances UI
│   └── src/                         # Sources interface
│
├── 📁 src/knowbase/                 # Code source principal (architecture modulaire)
│   ├── 📁 api/                      # Couche API FastAPI
│   │   ├── main.py                  # Configuration FastAPI
│   │   ├── dependencies.py          # Injection de dépendances
│   │   ├── 📁 routers/              # Endpoints API
│   │   │   ├── search.py            # Recherche de documents avec cascade
│   │   │   ├── ingest.py            # Ingestion de contenu multi-format
│   │   │   ├── status.py            # Statut système et monitoring
│   │   │   └── imports.py           # Gestion historique des imports
│   │   ├── 📁 services/             # Logique métier
│   │   │   ├── search.py            # Service de recherche avec cascade
│   │   │   ├── ingestion.py         # Service d'ingestion étendu
│   │   │   ├── status.py            # Service de monitoring avancé
│   │   │   ├── synthesis.py         # Synthèse de réponses intelligente
│   │   │   ├── import_history.py    # Historique des imports
│   │   │   ├── import_history_redis.py # Persistance Redis des imports
│   │   │   └── import_deletion.py   # Suppression complète d'imports
│   │   └── 📁 schemas/              # Modèles de données Pydantic
│   │       └── search.py            # Schémas de requête/réponse
│   │
│   ├── 📁 ingestion/                # Pipeline d'ingestion modulaire
│   │   ├── 📁 pipelines/            # Pipelines de traitement par format
│   │   │   ├── pptx_pipeline.py     # Traitement PowerPoint (filtrage slides amélioré)
│   │   │   ├── pdf_pipeline.py      # Traitement PDF
│   │   │   ├── excel_pipeline.py    # Traitement Excel Q/A pour collection RFP
│   │   │   └── fill_excel_pipeline.py # Remplissage RFP avec recherche cascade
│   │   ├── 📁 processors/           # Processeurs de contenu
│   │   ├── 📁 queue/                # Orchestration RQ (Redis Queue)
│   │   │   ├── dispatcher.py        # Distribution des tâches
│   │   │   ├── worker.py            # Exécution des tâches
│   │   │   └── connection.py        # Configuration Redis
│   │   └── 📁 cli/                  # Utilitaires en ligne de commande
│   │       ├── purge_collection.py  # Nettoyage des collections
│   │       ├── test_search_qdrant.py # Tests de recherche
│   │       └── generate_thumbnails.py # Génération vignettes
│   │
│   ├── 📁 common/                   # Composants partagés
│   │   ├── 📁 clients/              # Clients externes
│   │   │   ├── qdrant_client.py     # Client base vectorielle avec collections Q/A
│   │   │   ├── openai_client.py     # Client OpenAI
│   │   │   ├── anthropic_client.py  # Client Anthropic (Claude)
│   │   │   ├── embeddings.py        # Modèles d'embeddings
│   │   │   ├── reranker.py          # Cross-encoder pour reranking
│   │   │   └── shared_clients.py    # Factory des clients
│   │   ├── llm_router.py            # Routeur intelligent multi-provider
│   │   ├── 📁 sap/                  # Logique métier SAP
│   │   │   ├── normalizer.py        # Normalisation des données
│   │   │   ├── claims.py            # Gestion des assertions
│   │   │   └── solutions_dict.py    # Catalogue solutions SAP
│   │   └── logging.py               # Configuration centralisée des logs
│   │
│   ├── 📁 config/                   # Configuration et paramétrage
│   │   ├── settings.py              # Variables d'environnement
│   │   ├── prompts_loader.py        # Chargeur de prompts LLM
│   │   └── paths.py                 # Gestion des chemins et migration
│   │
│   └── 📁 ui/                       # Interface Streamlit modulaire
│       └── streamlit_app.py         # Application Streamlit
│
├── 📁 config/                       # Configuration externe
│   ├── prompts.yaml                 # Prompts LLM paramétrables par famille
│   └── llm_models.yaml              # Configuration multi-provider des modèles LLM
│
├── 📁 data/                         # Données runtime centralisées
│   ├── 📁 docs_in/                  # Documents en attente d'ingestion
│   ├── 📁 docs_done/                # Documents traités et archivés
│   ├── 📁 logs/                     # Journaux d'application
│   ├── 📁 models/                   # Cache modèles HuggingFace
│   ├── 📁 status/                   # Fichiers de statut système
│   └── 📁 public/                   # Assets publics
│       ├── 📁 slides/               # Slides extraites des PPTX
│       ├── 📁 thumbnails/           # Vignettes générées
│       ├── 📁 pdfs/                 # PDFs traités
│       └── 📁 pdf_slides/           # Slides PDF extraites
│
├── 📁 tests/                        # Suite de tests (pytest)
│   ├── conftest.py                  # Configuration des tests
│   ├── 📁 api/                      # Tests de l'API
│   ├── 📁 common/                   # Tests des composants communs
│   ├── 📁 config/                   # Tests de configuration
│   └── 📁 ingestion/                # Tests d'ingestion
│
├── docker-compose.yml               # Orchestration des services
├── .env                             # Variables d'environnement
├── requirements.txt                 # Dépendances Python globales
├── pytest.ini                      # Configuration des tests
└── ngrok.yml                        # Configuration tunnel ngrok
```

### Services Conteneurisés

#### 🔍 **knowbase-qdrant**
- **Base vectorielle** : Stockage et recherche de vecteurs d'embeddings
- **Port** : 6333
- **Volume** : `qdrant_data` pour la persistance
- **Configuration** : Stockage optimisé pour les performances

#### 📊 **knowbase-redis**
- **Queue de tâches** : Orchestration des pipelines d'ingestion
- **Port** : 6379
- **Usage** : Distribution asynchrone des tâches de traitement

#### 🚀 **knowbase-app** (Backend FastAPI)
- **API principale** : Endpoints de recherche, ingestion et monitoring
- **Port** : 8000 (configurable via `APP_PORT`)
- **Features** : Auto-documentation Swagger, CORS, gestion d'erreurs
- **Nouvelles API** : Historique d'imports, suppression complète, endpoints RFP Excel
- **Volumes** : Code source, données runtime (`/data`)

#### 👨‍💻 **knowbase-worker** (Processeur d'ingestion)
- **Traitement** : Exécution des pipelines d'ingestion en arrière-plan
- **Queue** : Basé sur RQ (Redis Queue)
- **Formats** : PPTX, PDF, Excel, DOCX avec OCR et extraction

#### 🖥️ **knowbase-frontend** (Interface Next.js)
- **Frontend Moderne** : Interface React avec TypeScript et Chakra UI
- **Port** : 3000 (configurable via `FRONTEND_PORT`)
- **Features** : Chat intelligent, gestion imports, workflows RFP Excel, interface admin
- **Architecture** : App Router Next.js 14, composants modulaires, API routes

#### 🖥️ **knowbase-ui** (Interface Streamlit - Legacy)
- **Dashboard** : Visualisation des données indexées (mode hérité)
- **Port** : 8501 (configurable via `APP_UI_PORT`)
- **Features** : Recherche interactive, filtrage, statistiques

#### 🌐 **knowbase-ngrok** (Tunnel Public)
- **Exposition** : Tunnel sécurisé pour accès externe
- **Usage** : Intégration GPT personnalisé, webhooks
- **Domain** : Configuration via `NGROK_DOMAIN`

## 🚀 Démarrage du Projet

### Prérequis
```bash
# Vérifier Docker et Docker Compose
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

# Variables essentielles à configurer :
# OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key (optionnel, pour Claude)
# NGROK_AUTHTOKEN=your-ngrok-token (optionnel)
# NGROK_DOMAIN=your-domain.ngrok.app (optionnel)
```

### Lancement des Services
```bash
# Construction et démarrage de tous les services
docker-compose up --build

# Démarrage en arrière-plan
docker-compose up -d --build

# Suivi des logs
docker-compose logs -f
```

### Accès aux Services
Une fois démarrés, les services sont accessibles via :

- **🌐 Frontend Moderne** : `http://localhost:3000` (Interface Next.js recommandée)
- **📚 API Documentation** : `http://localhost:8000/docs` (Swagger UI)
- **🖥️ Interface Streamlit** : `http://localhost:8501` (Interface legacy)
- **🔍 Base Qdrant** : `http://localhost:6333/dashboard`
- **🌐 Tunnel Ngrok** : Vérifiez les logs pour l'URL publique

## 🛠️ Utilisation

### Ingestion de Documents

#### Via Interface Next.js (Recommandée)
1. Accédez à `http://localhost:3000`
2. Naviguez vers "Documents" → "Import fichier"
3. Utilisez le drag-and-drop pour déposer vos documents
4. Suivez le statut de traitement en temps réel dans "Suivi imports"
5. Gérez les imports avec possibilité de suppression complète

#### Via Workflows RFP Excel Spécialisés
1. Accédez à "RFP Excel" dans la navigation
2. **Import Questions/Réponses** : Uploadez des fichiers Excel Q/A avec configuration des colonnes
3. **Remplir RFP vide** : Uploadez des RFP vides pour remplissage automatique via recherche cascade

#### Via Interface Streamlit (Legacy)
1. Accédez à `http://localhost:8501`
2. Utilisez la section "Upload" pour déposer vos documents
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
python -m knowbase.ingestion.cli.purge_collection --collection sap_kb
python -m knowbase.ingestion.cli.generate_thumbnails --docs-in /data/docs_in
```

### Recherche de Documents

#### Via API
```bash
# Recherche sémantique
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
- Visualisation des résultats avec scores de pertinence

## 🧪 Tests et Qualité

### Exécution des Tests
```bash
# Tests unitaires et d'intégration
docker-compose exec app pytest

# Tests avec couverture
docker-compose exec app pytest --cov=src/knowbase

# Tests spécifiques
docker-compose exec app pytest tests/api/
docker-compose exec app pytest tests/ingestion/ -k "test_pptx"
```

### Qualité du Code
```bash
# Linting
docker-compose exec app ruff check src/

# Formatage
docker-compose exec app ruff format src/

# Vérification des types
docker-compose exec app mypy src/
```

## 🐛 Debug et Développement

### Debug Sélectif des Services

Le projet supporte le debugging ciblé de chaque service indépendamment via VS Code et debugpy.

#### Configuration des Variables Debug

**Variables d'environnement dans `.env` :**
```bash
# Debug sélectif (recommandé)
DEBUG_APP=false      # Debug FastAPI sur port 5678
DEBUG_WORKER=false   # Debug Worker sur port 5679
```

#### Modes de Debug Disponibles

**🚀 Mode Production (par défaut)**
```bash
DEBUG_APP=false
DEBUG_WORKER=false
```
- Les deux services démarrent normalement
- Aucun blocage d'attente de debugger

**🔍 Debug FastAPI seulement**
```bash
DEBUG_APP=true
DEBUG_WORKER=false
```
- Worker démarre normalement
- FastAPI attend connexion debugger sur port 5678

**⚙️ Debug Worker seulement**
```bash
DEBUG_APP=false
DEBUG_WORKER=true
```
- FastAPI démarre normalement
- Worker attend connexion debugger sur port 5679

**🔧 Debug des deux services**
```bash
DEBUG_APP=true
DEBUG_WORKER=true
```
- Les deux services attendent connexion debugger
- Nécessite deux sessions de debug séparées

#### Configuration VS Code

**Ajouter dans `.vscode/launch.json` :**
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "🚀 Attach to FastAPI App",
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
            "name": "🔧 Attach to Worker",
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
3. VS Code → Run & Debug → "🚀 Attach to FastAPI App"
4. Placer breakpoints dans `src/knowbase/api/`
5. Tester l'endpoint via Swagger ou client

**Debug d'un pipeline d'ingestion :**
1. Modifier `.env` : `DEBUG_APP=false`, `DEBUG_WORKER=true`
2. `docker-compose up ingestion-worker`
3. VS Code → Run & Debug → "🔧 Attach to Worker"
4. Placer breakpoints dans `src/knowbase/ingestion/pipelines/`
5. Déclencher un job d'ingestion

**Debug d'un flow complet :**
1. Débugger l'endpoint API (voir ci-dessus)
2. Stopper le debug, modifier `.env` pour activer debug worker
3. Relancer avec debug worker pour suivre le traitement
4. Analyser le flow end-to-end

#### Ports de Debug
- **FastAPI App** : `localhost:5678`
- **Worker RQ** : `localhost:5679`

#### Bonnes Pratiques Debug
- ✅ Utiliser le debug sélectif pour éviter les blocages
- ✅ Placer des breakpoints avant de démarrer les services
- ✅ Utiliser `justMyCode: false` pour débuguer les dépendances
- ✅ Vérifier les path mappings VS Code pour la résolution de fichiers
- ⚠️ Éviter `DEBUG_APP=true` et `DEBUG_WORKER=true` simultanément sauf besoin spécifique

## 🧠 Système LLM Multi-Provider

Knowbase utilise un système intelligent de routage LLM qui optimise automatiquement les coûts et performances selon le type de tâche.

### ⚙️ Configuration YAML Centralisée

Le fichier `config/llm_models.yaml` permet de configurer dynamiquement les modèles sans modification de code :

```yaml
# Mapping tâche -> modèle optimisé
task_models:
  vision: "gpt-4o"                           # Analyse d'images (multimodal)
  metadata: "gpt-4o"                         # Extraction JSON structurée
  long_summary: "claude-3-5-sonnet-20241022" # Résumés longs (qualité)
  enrichment: "claude-3-5-haiku-20241022"    # Enrichissement (économique)
  classification: "gpt-4o-mini"              # Classification binaire
  canonicalization: "gpt-4o-mini"            # Normalisation SAP

# Paramètres optimisés par tâche
task_parameters:
  vision:
    temperature: 0.2    # Cohérence image-texte
    max_tokens: 1024    # Analyses détaillées
  metadata:
    temperature: 0.1    # Déterministe pour JSON
    max_tokens: 2000    # Métadonnées complètes
  classification:
    temperature: 0      # Binaire déterministe
    max_tokens: 5       # Réponses ultra-courtes
  # ... configurations par tâche
```

### 🎯 Types de Tâches Supportées

| Tâche | Modèle Optimisé | Usage | Économies |
|-------|------------------|-------|-----------|
| **Vision** | GPT-4o | Analyse slides PowerPoint, PDF | Baseline |
| **Metadata** | GPT-4o | Extraction métadonnées JSON | Baseline |
| **Long Summary** | Claude-3.5-Sonnet | Résumés de documents longs | Qualité++ |
| **Enrichment** | Claude-3.5-Haiku | Enrichissement de contenu | **80%** |
| **Classification** | GPT-4o-mini | Questions oui/non | **95%** |
| **Canonicalization** | GPT-4o-mini | Normalisation noms SAP | **90%** |

### 🔄 Providers et Fallbacks

```yaml
providers:
  openai:
    models: ["gpt-4o", "gpt-4o-mini", "o1-preview"]
  anthropic:
    models: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]

# Fallbacks automatiques en cas d'indisponibilité
fallback_strategy:
  long_summary:
    - "claude-3-5-sonnet-20241022"  # Préféré
    - "gpt-4o"                      # Fallback 1
    - "gpt-4o-mini"                 # Fallback 2
```

### 💰 Optimisation des Coûts

Le système apporte des **économies de 60-80%** sur les coûts LLM :

```bash
# Avant (tout en GPT-4o)
• Classification: $0.125 par requête
• Canonicalisation: $0.100 par requête
• Enrichissement: $0.080 par requête

# Après (routage optimisé)
• Classification: $0.006 par requête (-95%)
• Canonicalisation: $0.010 par requête (-90%)
• Enrichissement: $0.016 par requête (-80%)
```

### 🚀 Configuration Avancée

```bash
# Variables d'environnement optionnelles pour override
export MODEL_VISION="gpt-4o"
export MODEL_METADATA="claude-3-5-sonnet-20241022"
export MODEL_FAST="gpt-4o-mini"

# Test de la configuration
python -m knowbase.common.llm_router --test-config
```

### ⚙️ Prompts Configurables

Système de prompts paramétrables dans `config/prompts.yaml` :

**Familles disponibles :**
- **default** : Analyse générique
- **technical** : Focus technique
- **functional** : Accent métier

```bash
# Forcer un type de document
python -m knowbase.ingestion.pipelines.pptx_pipeline document.pptx --document-type functional
```

### 📊 Traçabilité et Monitoring

Chaque appel LLM est tracé avec :
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

## 🔧 Administration et Maintenance

### Monitoring
```bash
# Statut des services
docker-compose ps

# Logs en temps réel
docker-compose logs -f app
docker-compose logs -f worker

# Statut système via API
curl http://localhost:8000/status
```

### Nettoyage
```bash
# Purge d'une collection Qdrant
python -m knowbase.ingestion.cli.purge_collection --collection sap_kb --yes

# Nettoyage des logs
docker-compose exec app find /data/logs -name "*.log" -mtime +7 -delete
```

### Sauvegarde
```bash
# Sauvegarde des données
docker-compose exec app tar -czf /data/backup-$(date +%Y%m%d).tar.gz /data

# Sauvegarde Qdrant
docker-compose exec qdrant cp -r /qdrant/storage /qdrant/backup
```

## 🎯 Roadmap et Évolutions

### À Court Terme
- [x] **Interface web moderne (Next.js + TypeScript)** - ✅ Implémentée avec Chakra UI
- [x] **Gestion avancée des imports** - ✅ Historique, tracking, suppression complète
- [x] **Workflows RFP Excel spécialisés** - ✅ Import Q/A et remplissage automatique
- [x] **Collections dédiées Q/A** - ✅ Recherche cascade intelligente
- [ ] Centralisation complète du chargement des modèles ML
- [ ] Système de claims pour la gestion d'incohérences

### À Moyen Terme
- [ ] Support multi-tenant avec isolation des données
- [ ] API de webhooks pour intégrations externes
- [ ] Système de notifications push

### À Long Terme
- [ ] IA conversationnelle intégrée (RAG avancé)
- [ ] Analytics et métriques d'usage avancées
- [ ] Déploiement cloud-native (Kubernetes)

## 📊 Badges & Métriques

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

## 👥 Contribution

Ce projet suit une architecture modulaire permettant l'extensibilité et la maintenance. Les développeurs peuvent :

- Ajouter de nouveaux formats de documents via les pipelines d'ingestion
- Étendre l'API avec de nouveaux endpoints dans `src/knowbase/api/routers/`
- Créer des processeurs personnalisés dans `src/knowbase/ingestion/processors/`
- Implémenter des clients pour de nouveaux services externes
- Développer des composants React personnalisés dans `frontend/src/components/`
- Ajouter des pages Next.js dans `frontend/src/app/`

**Développé avec ❤️ pour optimiser la gestion des connaissances SAP**