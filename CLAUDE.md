# Configuration Claude Code - Projet Knowbase SAP KB

*Instructions et préférences pour les sessions Claude Code*

## 🇫🇷 Préférences Linguistiques

**IMPORTANT : Toujours répondre en français** sauf demande explicite contraire.
- Communication en français pour toutes les interactions
- Documentation en français
- Commentaires de code en français si ajoutés
- Messages de commit en français

## 🤖 MODE AUTONOMIE - PHASE 2 ZEP

### ✅ AUTORISATIONS AUTONOMES ACCORDÉES
Pendant l'implémentation de la Phase 2 Zep, Claude Code est autorisé à :

**Infrastructure Docker :**
- ✅ Créer nouveaux services (zep, postgres) dans docker-compose.yml
- ✅ Rebuilder containers automatiquement si nécessaire
- ✅ Arrêter/redémarrer services pour intégration Zep
- ✅ Modifier configurations réseau Docker
- ✅ Gérer volumes persistants Postgres/Zep

**Développement Code :**
- ✅ Créer nouveaux fichiers Python pour intégration Zep
- ✅ Modifier APIs existantes pour ajout endpoints Facts/Memory
- ✅ Installer nouvelles dépendances Python (zep-python, etc.)
- ✅ Exécuter tests automatiquement après modifications
- ✅ Corriger erreurs et bugs détectés automatiquement

**Base de Données :**
- ✅ Créer schémas Postgres pour Facts/Relations/Conflicts
- ✅ Exécuter migrations de base de données
- ✅ Configurer connexions Zep ↔ Postgres ↔ FastAPI
- ✅ Tester intégrité données entre Qdrant et Zep

**Git et Versioning :**
- ✅ Commits automatiques avec messages descriptifs
- ✅ Push des changements vers repository
- ✅ Création branches feat/zep-* si nécessaire

### 🎯 OBJECTIF AUTONOMIE
Implémenter complètement la Phase 2 sans interruption :
1. Setup Zep + Postgres (3 jours)
2. Client Zep intégration (2 jours)
3. Facts CRUD API (5 jours)

## 🐳 Gestion Docker - RÈGLES STRICTES

### ❌ INTERDICTIONS (SUSPENDUES EN MODE AUTONOMIE ZEP)
- ~~NE JAMAIS rebuilder automatiquement les containers Docker~~ ✅ **AUTORISÉ Phase 2**
- ~~NE JAMAIS exécuter `docker-compose up --build` sans demande explicite~~ ✅ **AUTORISÉ Phase 2**
- ~~NE JAMAIS arrêter/redémarrer les services Docker sans autorisation~~ ✅ **AUTORISÉ Phase 2**
- **NE JAMAIS purger un élément ou une queue entière Redis sans autorisation** ⚠️ **TOUJOURS INTERDIT**

### ✅ AUTORISATIONS
```bash
# Consultation uniquement
docker-compose ps              # Vérifier statut des services
docker-compose logs -f [service]  # Consulter les logs

# Actions autorisées seulement si demandé explicitement
docker-compose up -d          # Démarrage sans rebuild
docker-compose down           # Arrêt si demandé
docker-compose build          # Rebuild manuel si explicitement demandé
```

### 🚨 Processus en Cours

- **Instruction** : Ne jamais purger toute la queue sans une autorisation claire
Avant toute action Docker, TOUJOURS :
1. Vérifier `docker-compose ps` pour voir les services actifs
2. Demander confirmation utilisateur pour rebuild/restart
3. Expliquer pourquoi l'action est nécessaire
4. Attendre accord explicite avant d'agir

**Raison** : Des processus d'ingestion peuvent être en cours et nécessitent une finalisation avant arrêt.

## 📚 Documentation de Référence

### Architecture Projet (Lecture Obligatoire)
- **Documentation complète** : `doc/projet-reference-documentation.md`
- **README principal** : `README.md`
- **Configuration import** : `doc/import-status-system-analysis.md`

### Structure Connue (Éviter le Rescan)
```
src/knowbase/              # Code Python principal
├── api/                   # FastAPI (routers, services, schemas)
├── ingestion/             # Pipelines traitement documents
├── common/                # Clients externes (Qdrant, OpenAI, etc.)
└── config/                # Configuration centralisée

frontend/src/              # Interface Next.js TypeScript
├── app/                   # App Router Next.js 14
├── components/            # Composants React
└── lib/                   # Utilitaires

config/                    # Configuration YAML
├── llm_models.yaml        # Configuration LLM multi-provider
├── prompts.yaml           # Prompts configurables
└── sap_solutions.yaml     # Catalogue SAP

data/                      # Données runtime
├── docs_in/               # Documents à traiter
├── docs_done/             # Documents traités
└── public/                # Assets (slides, thumbnails)
```

## 🛠️ Commandes Projet

### Tests et Qualité
```bash
# Tests
docker-compose exec app pytest
docker-compose exec app pytest --cov=src/knowbase

# Linting
docker-compose exec app ruff check src/
docker-compose exec app ruff format src/
docker-compose exec app mypy src/

# Frontend
cd frontend && npm run lint
cd frontend && npm run build
```

### Développement
```bash
# Logs en temps réel
docker-compose logs -f app
docker-compose logs -f worker
docker-compose logs -f frontend

# Accès conteneur pour debug
docker-compose exec app bash
docker-compose exec frontend bash
```

### URLs d'Accès
- **Frontend moderne** : http://localhost:3000 (interface principale)
- **API Documentation** : http://localhost:8000/docs (Swagger)
- **Interface legacy** : http://localhost:8501 (Streamlit)
- **Base Qdrant** : http://localhost:6333/dashboard

## 🔧 Variables d'Environnement

### Configuration Debug (.env)
```bash
# Debug sélectif (par défaut : false)
DEBUG_APP=false      # Debug FastAPI sur port 5678
DEBUG_WORKER=false   # Debug Worker sur port 5679

# Ports services
APP_PORT=8000        # FastAPI
FRONTEND_PORT=3000   # Next.js
APP_UI_PORT=8501     # Streamlit

# API Keys (nécessaires)
OPENAI_API_KEY=your-key
ANTHROPIC_API_KEY=your-key
```

## 📁 Fichiers de Configuration Critiques

### LLM et IA
- `config/llm_models.yaml` : Configuration modèles LLM multi-provider
- `config/prompts.yaml` : Prompts personnalisables par famille
- `config/sap_solutions.yaml` : Catalogue solutions SAP

### Docker et Orchestration
- `docker-compose.yml` : Configuration 7 services
- `.env` : Variables d'environnement
- `app/Dockerfile` : Backend FastAPI
- `frontend/Dockerfile` : Interface Next.js

### Code Principal
- `src/knowbase/api/main.py` : Point d'entrée API
- `src/knowbase/ingestion/pipelines/` : Traitement documents
- `frontend/src/app/layout.tsx` : Layout Next.js principal

## 🎯 Workflows Typiques

### Import Documents
1. Interface : http://localhost:3000/documents/import
2. Suivi : http://localhost:3000/documents/status
3. Pipeline automatique : docs_in → traitement → Qdrant → docs_done

### Recherche
1. Interface chat : http://localhost:3000/chat
2. API directe : POST http://localhost:8000/search
3. Recherche cascade : Q/A RFP (seuil 0.85) → général (seuil 0.70)

### RFP Excel
1. Import Q/A : http://localhost:3000/rfp-excel
2. Remplissage automatique RFP vides
3. Export Excel complété

## 🔍 Debugging et Troubleshooting

### Logs Importants
```bash
# Vérifier statut général
curl http://localhost:8000/status

# Logs par service
docker-compose logs app      # API backend
docker-compose logs worker   # Processeur ingestion
docker-compose logs frontend # Interface Next.js
docker-compose logs qdrant   # Base vectorielle
docker-compose logs redis    # Queue tâches
```

### Problèmes Courants
1. **Ports occupés** : Vérifier dans .env et docker-compose.yml
2. **API Keys manquantes** : Vérifier .env
3. **Modèles non téléchargés** : Premier démarrage peut prendre 5-10min
4. **Queue bloquée** : Redémarrer service redis si nécessaire

## 📊 Performance et Monitoring

### Métriques Attendues
- Recherche vectorielle : < 100ms
- Ingestion PPTX : 2-5s/document
- Ingestion PDF avec OCR : 5-15s/document
- Synthèse LLM : 1-3s selon modèle

### Collections Qdrant
- `rfp_qa` : Questions/Réponses RFP prioritaires
- `knowbase` : Base de connaissances générale

## 🚀 Extensions et Développement

### Ajout Nouveau Format Document
1. Créer pipeline : `src/knowbase/ingestion/pipelines/new_format_pipeline.py`
2. Ajouter router : `src/knowbase/api/routers/ingest.py`
3. Tests : `tests/ingestion/test_new_format.py`

### Extension Frontend
1. Composant : `frontend/src/components/features/`
2. Page : `frontend/src/app/new-feature/page.tsx`
3. API route : `frontend/src/app/api/new-endpoint/`

### Configuration LLM
1. Modifier : `config/llm_models.yaml`
2. Ajouter prompts : `config/prompts.yaml`
3. Tester : `src/knowbase/common/llm_router.py`

## 🔒 Sécurité et Bonnes Pratiques

- Variables sensibles dans .env (jamais dans le code)
- API Keys en variables d'environnement
- CORS configuré pour frontend uniquement
- Logs sans informations sensibles
- Validation Pydantic sur tous les endpoints

## 📝 Git et Versioning

### Messages de Commit (Français)
```bash
feat: ajouter support format DOCX
fix: corriger recherche cascade RFP
refactor: optimiser pipeline PDF
docs: mettre à jour documentation API
```

### Branches
- `main` : Production stable
- `feat/*` : Nouvelles fonctionnalités
- `fix/*` : Corrections de bugs
- `refactor/*` : Refactoring code

---

**💡 Principe Claude Code** : Utiliser cette documentation comme référence pour éviter l'exploration extensive du projet à chaque session. Toujours consulter ces instructions avant toute action Docker ou modification majeure.

*Dernière mise à jour : 2025-09-28 - Mode Autonomie Phase 2 ZEP activé*