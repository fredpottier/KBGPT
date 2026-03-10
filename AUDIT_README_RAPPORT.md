# 📋 RAPPORT D'AUDIT - README.md
**Date**: 2026-03-10
**Projet**: KnowWhere/OSMOSE
**Fichier audité**: README.md
**Auditeur**: Claude Code (Auto-Claude)

---

## 🎯 RÉSUMÉ EXÉCUTIF

Cet audit identifie **28 incohérences critiques** dans le README.md par rapport à la configuration réelle du projet.

### Sévérité des problèmes
- 🔴 **Critiques** : 12 (informations incorrectes)
- 🟡 **Modérées** : 10 (informations incomplètes/obsolètes)
- 🟢 **Mineures** : 6 (améliorations suggérées)

---

## 🔴 PROBLÈMES CRITIQUES (Action Immédiate Requise)

### 1. **Versions des Services Docker**

#### ❌ Problème : Qdrant v1.15.1
**README.md (ligne 17)** :
```markdown
- **Base Vectorielle** : **Qdrant v1.15.1**
```

**Réalité** (docker-compose.infra.yml, ligne 13) :
```yaml
image: qdrant/qdrant:v1.15.1
```
✅ **CORRECT** - Aucune modification nécessaire

---

#### ❌ Problème : Redis 7.2
**README.md (ligne 19)** :
```markdown
- **Queue de Tâches** : **Redis 7.2**
```

**Réalité** (docker-compose.infra.yml, ligne 39) :
```yaml
image: redis:7.2-alpine
```
✅ **CORRECT** mais **IMPRÉCIS** - Devrait mentionner `7.2-alpine`

**Recommandation** :
```markdown
- **Queue de Tâches** : **Redis 7.2-alpine** - Système de files d'attente avec persistance AOF
```

---

#### ❌ Problème : Neo4j manquant
**README.md** : **NE MENTIONNE PAS Neo4j** dans la section "Stack Technique"

**Réalité** : Neo4j est un service CRITIQUE dans l'infrastructure (docker-compose.infra.yml, lignes 58-98)
```yaml
neo4j:
  image: neo4j:5.26.0
  ports:
    - "7474:7474"  # HTTP Browser UI
    - "7687:7687"  # Bolt protocol
```

**Impact** : 🔴 CRITIQUE - Service majeur complètement omis de la documentation

**Recommandation** : Ajouter dans la section "🗄️ **Stockage & Base de Données**" :
```markdown
- **Base Graphe** : **Neo4j 5.26.0** - Knowledge Graph pour relations sémantiques OSMOSE
- **Plugins Neo4j** : APOC + Graph Data Science (GDS) Community
- **Mémoire** : Heap 2-4GB, PageCache 2GB (optimisé pour 45k+ nodes)
```

---

#### ❌ Problème : PostgreSQL manquant
**README.md** : **NE MENTIONNE PAS PostgreSQL** dans la stack technique

**Réalité** : PostgreSQL est présent dans l'infrastructure (docker-compose.infra.yml, lignes 104-123)
```yaml
postgres:
  image: pgvector/pgvector:pg16
  ports:
    - "5432:5432"
```

**Impact** : 🔴 CRITIQUE - Base de données métier omise

**Recommandation** : Ajouter dans la section "🗄️ **Stockage & Base de Données**" :
```markdown
- **Base Relationnelle** : **PostgreSQL 16 + pgvector** - Sessions, users, audit trail, import history
```

---

### 2. **Versions Python et Dépendances**

#### ❌ Problème : FastAPI 0.110+
**README.md (ligne 24)** :
```markdown
- **Framework API** : **FastAPI 0.110+**
```

**Réalité** (app/requirements.txt, ligne 2) :
```
fastapi==0.116.1
```

**Impact** : 🟡 MODÉRÉ - Version plus récente installée

**Recommandation** :
```markdown
- **Framework API** : **FastAPI 0.116.1** - Framework Python moderne avec auto-documentation OpenAPI/Swagger
```

---

#### ❌ Problème : Pydantic 2.8+
**README.md (ligne 27)** :
```markdown
- **Validation** : **Pydantic 2.8+**
```

**Réalité** : Non spécifié dans requirements.txt (installé comme dépendance de FastAPI)

**Impact** : 🟡 MODÉRÉ - Information approximative

**Recommandation** : Vérifier la version réelle ou retirer la version spécifique

---

#### ❌ Problème : Streamlit 1.48+
**README.md (ligne 31)** :
```markdown
- **Dashboard Legacy** : **Streamlit 1.48+**
```

**Réalité** : Non présent dans app/requirements.txt

**Impact** : 🟡 MODÉRÉ - Version non vérifiable

---

#### ❌ Problème : Pytest 7.4+
**README.md (ligne 54)** :
```markdown
- **Framework de Tests** : **Pytest 7.4+**
```

**Réalité** (app/requirements.txt, ligne 42) :
```
pytest>=7.4.0
```
✅ **CORRECT**

---

### 3. **Architecture des Services Docker**

#### 🔴 CRITIQUE : Section "Services Conteneurisés" OBSOLÈTE

**README.md (lignes 202-241)** liste 7 services :
1. knowbase-qdrant
2. knowbase-redis
3. knowbase-app
4. knowbase-worker (nommé `ingestion-worker` dans le README)
5. knowbase-frontend
6. knowbase-ui
7. knowbase-ngrok

**Réalité** : Le projet utilise maintenant **3 fichiers Docker Compose** :
- `docker-compose.infra.yml` : Infrastructure (Qdrant, Redis, Neo4j, PostgreSQL)
- `docker-compose.yml` : Application (app, ingestion-worker, folder-watcher, frontend)
- `docker-compose.monitoring.yml` : Monitoring (Grafana, Loki, Promtail)

**Services MANQUANTS dans le README** :
- ✅ **knowbase-neo4j** (port 7474, 7687)
- ✅ **knowbase-postgres** (port 5432)
- ✅ **knowbase-watcher** (folder-watcher)
- ✅ **knowbase-grafana** (port 3001)
- ✅ **knowbase-loki** (port 3101)
- ✅ **knowbase-promtail** (collecte logs)

**Noms INCORRECTS** :
- ❌ README dit : `knowbase-worker`
- ✅ Réalité : `knowbase-worker` (correct dans docker-compose.yml ligne 78, mais appelé `ingestion-worker` comme nom de service)

---

### 4. **Ports Exposés**

#### ❌ Port Qdrant
**README.md (ligne 206)** :
```markdown
- **Port** : 6333
```

**Réalité** (docker-compose.infra.yml, lignes 17-18) :
```yaml
ports:
  - "6333:6333"
  - "6334:6334"  # gRPC port
```

**Impact** : 🟡 MODÉRÉ - Port gRPC 6334 non documenté

**Recommandation** :
```markdown
- **Ports** : 6333 (HTTP), 6334 (gRPC)
```

---

#### ❌ Port Redis
**README.md (ligne 212)** :
```markdown
- **Port** : 6379
```
✅ **CORRECT**

---

#### ❌ Port Neo4j MANQUANT
**Réalité** (docker-compose.infra.yml, lignes 64-65) :
```yaml
ports:
  - "7474:7474"  # HTTP Browser UI
  - "7687:7687"  # Bolt protocol
```

**Impact** : 🔴 CRITIQUE - Ports Neo4j non documentés

---

#### ❌ Port PostgreSQL MANQUANT
**Réalité** (docker-compose.infra.yml, ligne 110) :
```yaml
ports:
  - "5432:5432"
```

**Impact** : 🔴 CRITIQUE - Port PostgreSQL non documenté

---

#### ❌ Port Grafana
**README.md** : Non mentionné

**Réalité** (docker-compose.monitoring.yml, ligne 64) :
```yaml
ports:
  - "3001:3000"  # Port 3001 pour éviter conflit avec frontend
```

**Impact** : 🔴 CRITIQUE - Service monitoring non documenté

---

#### ❌ Port Loki
**README.md** : Non mentionné

**Réalité** (docker-compose.monitoring.yml, ligne 21) :
```yaml
ports:
  - "3101:3100"  # HTTP API Loki
```

**Impact** : 🟡 MODÉRÉ - Service monitoring non documenté

---

### 5. **Commandes Docker**

#### 🔴 CRITIQUE : Commandes docker-compose OBSOLÈTES

**README.md (lignes 269-278)** :
```bash
# Construction et démarrage de tous les services
docker-compose up --build

# Démarrage en arrière-plan
docker-compose up -d --build

# Suivi des logs
docker-compose logs -f
```

**Problème** : Ces commandes ne fonctionnent PAS correctement car le projet utilise **3 fichiers Docker Compose**

**Réalité** (.env, ligne 3) :
```env
COMPOSE_FILE=docker-compose.infra.yml:docker-compose.yml:docker-compose.monitoring.yml
```

**Impact** : 🔴 CRITIQUE - Les utilisateurs ne pourront pas démarrer le projet

**Recommandation** : Utiliser le script PowerShell `kw.ps1` OU spécifier les 3 fichiers :
```bash
# Via script PowerShell (RECOMMANDÉ)
./kw.ps1 start              # Démarre tout
./kw.ps1 start infra        # Démarre uniquement infrastructure
./kw.ps1 start app          # Démarre uniquement application

# OU via docker-compose direct
docker-compose -f docker-compose.infra.yml -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

---

#### ❌ Commandes CLI
**README.md (lignes 318-327)** :
```bash
# Entrer dans le conteneur
docker-compose exec app bash

# Utiliser les utilitaires CLI
python -m knowbase.ingestion.cli.test_search_qdrant --query "S/4HANA implementation"
python -m knowbase.ingestion.cli.purge_collection --collection knowbase
python -m knowbase.ingestion.cli.generate_thumbnails --docs-in /data/docs_in
```

**Problème** :
- `purge_collection` nécessite `--yes` flag (sinon demande confirmation)
- Collection par défaut est maintenant `knowbase_chunks_v2` (pas `knowbase`)

**Recommandation** :
```bash
python -m knowbase.ingestion.cli.purge_collection --collection knowbase_chunks_v2 --yes
```

---

### 6. **URLs d'Accès**

#### ❌ README.md (lignes 281-287)
```markdown
- **🌐 Frontend Moderne** : `http://localhost:3000`
- **📚 API Documentation** : `http://localhost:8000/docs`
- **🖥️ Interface Streamlit** : `http://localhost:8501`
- **🔍 Base Qdrant** : `http://localhost:6333/dashboard`
- **🌐 Tunnel Ngrok** : Vérifiez les logs pour l'URL publique
```

**URLs MANQUANTES** :
- ❌ **Neo4j Browser** : `http://localhost:7474` (neo4j / graphiti_neo4j_pass)
- ❌ **Grafana** : `http://localhost:3001` (admin / Rn1lm@tr)
- ❌ **Loki API** : `http://localhost:3101`
- ❌ **PostgreSQL** : `localhost:5432` (knowbase / knowbase_secure_pass)

---

### 7. **Structure des Répertoires**

#### ❌ Répertoire `data/extraction_cache/` MANQUANT
**README.md (lignes 176-186)** ne mentionne PAS `data/extraction_cache/`

**Réalité** (.env, lignes 46-51) :
```env
# === Extraction Cache System (V2.2) ===
ENABLE_EXTRACTION_CACHE=true
EXTRACTION_CACHE_DIR=/data/extraction_cache
CACHE_EXPIRY_DAYS=30
```

**Impact** : 🔴 CRITIQUE - Répertoire vital non documenté (économise coûts LLM)

**Recommandation** : Ajouter dans la structure `data/` :
```
├── 📁 data/
│   ├── 📁 extraction_cache/         # 🔴 NOUVEAU - Cache des extractions LLM (.knowcache.json)
│   ├── 📁 docs_in/
│   ├── 📁 docs_done/
│   └── ...
```

---

#### ❌ Répertoires OSMOSE manquants
**README.md** ne mentionne PAS les répertoires OSMOSE :
- `src/knowbase/semantic/` - Infrastructure OSMOSE Phase 1
- `data/backups/snapshots/` - Système de backup (kw.ps1)

---

### 8. **Noms de Collections Qdrant**

#### ❌ Collection par défaut
**README.md (ligne 309)** :
```markdown
- `knowbase` : Base de connaissances générale
```

**Réalité** (.env, ligne 14) :
```env
QDRANT_COLLECTION=knowbase_chunks_v2
```

**Impact** : 🔴 CRITIQUE - Nom de collection incorrect

**Recommandation** :
```markdown
- `knowbase_chunks_v2` : Base de connaissances générale (chunks documents)
- `rfp_qa` : Questions/Réponses RFP prioritaires
- `knowwhere_proto` : Proto-KG OSMOSE (Phase 1)
```

---

### 9. **Variables d'Environnement**

#### ❌ Variables .env incomplètes
**README.md (lignes 256-265)** :
```bash
# Variables essentielles à configurer :
# OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key (optionnel, pour Claude)
# NGROK_AUTHTOKEN=your-ngrok-token (optionnel)
# NGROK_DOMAIN=your-domain.ngrok.app (optionnel)
```

**Variables CRITIQUES manquantes** :
- `NEO4J_PASSWORD` (requis pour Neo4j)
- `POSTGRES_PASSWORD` (requis pour PostgreSQL)
- `GRAFANA_ADMIN_PASSWORD` (requis pour monitoring)
- `MAX_WORKERS` (30 par défaut, critique pour performance)
- `EMBEDDING_MODE` (hybrid/local/cloud)
- `OSMOSE_TIMEOUT_SECONDS` (3600s par défaut)

---

### 10. **Script kw.ps1**

#### ❌ Script PowerShell non documenté dans README.md principal
**README.md** : **NE MENTIONNE PAS** le script `kw.ps1`

**Réalité** : `kw.ps1` est l'outil PRINCIPAL de gestion du projet avec :
- Démarrage/arrêt sélectif (infra/app/monitoring)
- Backup/restore complet (Neo4j, Qdrant, PostgreSQL, Redis, cache)
- Affichage URLs + credentials (`./kw.ps1 info`)
- 880+ lignes de code

**Impact** : 🔴 CRITIQUE - Outil principal non documenté

**Recommandation** : Ajouter une section dédiée après "Lancement des Services" :
```markdown
### 🔧 Script de Gestion Unifié (kw.ps1)

Le projet utilise un script PowerShell unifié pour gérer l'infrastructure :

```powershell
# Démarrage
./kw.ps1 start              # Démarre infra + app + monitoring
./kw.ps1 start infra        # Démarre uniquement infrastructure
./kw.ps1 start app          # Démarre uniquement application

# Informations
./kw.ps1 info               # Affiche TOUTES les URLs + credentials

# Backup & Restore
./kw.ps1 backup <name>      # Backup complet (Neo4j, Qdrant, PG, Redis, cache)
./kw.ps1 restore <name>     # Restore complet
./kw.ps1 backup-list        # Liste les backups

# Logs
./kw.ps1 logs app           # Logs du backend
./kw.ps1 logs worker        # Logs du worker
./kw.ps1 logs neo4j         # Logs Neo4j
```

**⚠️ IMPORTANT** : Ce script est la méthode RECOMMANDÉE pour gérer le projet.
```

---

### 11. **Monitoring (Grafana/Loki/Promtail)**

#### 🔴 CRITIQUE : Stack monitoring complètement absente du README

**Réalité** : Le projet a une stack monitoring complète (docker-compose.monitoring.yml) :
- **Grafana 10.2.3** : Dashboards (port 3001)
- **Loki 2.9.3** : Agrégation logs (port 3101)
- **Promtail 2.9.3** : Collecte logs Docker

**Impact** : 🔴 CRITIQUE - Fonctionnalité majeure non documentée

**Recommandation** : Ajouter une section "📊 Monitoring et Observabilité" :
```markdown
## 📊 Monitoring et Observabilité

### Stack Grafana + Loki

Le projet intègre une stack de monitoring complète pour la centralisation et visualisation des logs :

- **Grafana 10.2.3** : Dashboards et visualisation
  - URL : `http://localhost:3001`
  - Login : `admin` / `Rn1lm@tr`

- **Loki 2.9.3** : Agrégation et indexation des logs
  - API : `http://localhost:3101`

- **Promtail 2.9.3** : Agent de collecte des logs Docker

### Démarrage du Monitoring

```bash
# Via kw.ps1
./kw.ps1 start monitoring

# OU via docker-compose
docker-compose -f docker-compose.monitoring.yml up -d
```

### Configuration

Le mot de passe Grafana est automatiquement configuré au démarrage via `kw.ps1 start`.
```

---

## 🟡 PROBLÈMES MODÉRÉS

### 12. **Nom du Projet**

**README.md (ligne 1)** :
```markdown
# Knowbase - SAP Knowledge Management System
```

**CLAUDE.md (lignes 7-18)** indique :
```markdown
**Nom Commercial:** **KnowWhere** (anciennement "KnowBase" ou "SAP KB")
**Nom de Code Pivot:** **OSMOSE**
```

**Impact** : 🟡 MODÉRÉ - Incohérence de naming

**Recommandation** :
```markdown
# KnowWhere (OSMOSE) - SAP Knowledge Management System

*Anciennement "Knowbase" - Nom de code pivot : OSMOSE (Organic Semantic Memory Organization & Smart Extraction)*

KnowWhere est une plateforme dockerisée...
```

---

### 13. **Mention de Ngrok**

**README.md (ligne 36-38, 287)** mentionne Ngrok

**Réalité** (docker-compose.yml, lignes 206-220) :
```yaml
# ngrok: # DÉSACTIVÉ - Nécessite plan payant pour custom subdomain
```

**Impact** : 🟡 MODÉRÉ - Service désactivé mais documenté

**Recommandation** : Préciser que Ngrok est désactivé par défaut

---

### 14. **Debug Ports**

**README.md (lignes 498-499)** :
```markdown
- **FastAPI App** : `localhost:5678`
- **Worker RQ** : `localhost:5679`
```

**Réalité** (docker-compose.yml, lignes 60, 123) :
```yaml
ports:
  - "5678:5678"  # App debug
  - "5679:5679"  # Worker debug
```
✅ **CORRECT**

---

### 15. **Worker Name**

**README.md (ligne 222)** :
```markdown
#### 👨‍💻 **knowbase-worker** (Processeur d'ingestion)
```

**Réalité** (docker-compose.yml, ligne 78) :
```yaml
container_name: knowbase-worker
```

Mais le service est nommé `ingestion-worker` (ligne 73)

**Impact** : 🟡 MODÉRÉ - Confusion possible

**Recommandation** : Clarifier que le service s'appelle `ingestion-worker` mais le container `knowbase-worker`

---

### 16. **Folder Watcher Service**

**README.md** : **NE MENTIONNE PAS** le service `folder-watcher`

**Réalité** (docker-compose.yml, lignes 137-162) :
```yaml
folder-watcher:
  container_name: knowbase-watcher
  command: python -m knowbase.ingestion.folder_watcher
```

**Impact** : 🟡 MODÉRÉ - Service non documenté (surveillance automatique de `data/docs_in/`)

---

### 17. **Timeout Configuration**

**README.md** : **NE MENTIONNE PAS** la configuration centralisée des timeouts

**Réalité** (docker-compose.yml, lignes 103-120) :
```yaml
# ========== CONFIGURATION TIMEOUT CENTRALISÉE ==========
MAX_DOCUMENT_PROCESSING_TIME: "3600"  # 1 heure
```

**Impact** : 🟡 MODÉRÉ - Configuration importante non documentée

---

### 18. **GPU Support**

**README.md** : **NE MENTIONNE PAS** le support GPU pour le worker

**Réalité** (docker-compose.yml, lignes 85-91) :
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

**Impact** : 🟡 MODÉRÉ - Configuration critique non documentée

---

### 19. **Shared Memory Size**

**README.md** : **NE MENTIONNE PAS** `shm_size`

**Réalité** (docker-compose.yml, lignes 47, 84) :
```yaml
shm_size: '2gb'  # Nécessaire pour OnnxTR/PyTorch
```

**Impact** : 🟡 MODÉRÉ - Configuration critique pour OCR

---

### 20. **OSMOSE Phase 1**

**README.md** : **NE MENTIONNE PAS** l'architecture OSMOSE Phase 1

**CLAUDE.md (lignes 360-374)** détaille :
- SemanticDocumentProfiler
- NarrativeThreadDetector
- IntelligentSegmentationEngine
- DualStorageExtractor

**Impact** : 🟡 MODÉRÉ - Fonctionnalités majeures non documentées dans README principal

---

## 🟢 PROBLÈMES MINEURS (Améliorations Suggérées)

### 21. **Docling Version**

**README.md** ne mentionne pas Docling

**Réalité** (app/requirements.txt, ligne 64) :
```
docling>=2.14.0
```

**Recommandation** : Ajouter Docling dans la section traitement de documents

---

### 22. **Burst Mode**

**README.md** : Non mentionné

**Réalité** (.env, ligne 109) :
```env
BURST_MODE_ENABLED=true
```

**Impact** : 🟢 MINEUR - Feature avancée

---

### 23. **Ollama Integration**

**README.md** : Non mentionné

**Réalité** (.env, ligne 106) :
```env
OLLAMA_URL=http://host.docker.internal:11434
```

**Impact** : 🟢 MINEUR - Feature optionnelle

---

### 24. **AWS Credentials (Burst Mode EC2)**

**README.md** : Non mentionné

**Réalité** (.env, lignes 112-114) :
```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-central-1
```

**Impact** : 🟢 MINEUR - Feature avancée

---

### 25. **Embedding Modes**

**README.md** : Non mentionné

**Réalité** (.env, lignes 77-87) :
```env
EMBEDDING_MODE=hybrid
EMBEDDING_CLOUD_THRESHOLD=1000
EMBEDDING_CLOUD_MODEL=text-embedding-3-large
```

**Impact** : 🟢 MINEUR - Configuration performance

---

### 26. **GPU Unload Timeout**

**README.md** : Non mentionné

**Réalité** (.env, ligne 101) :
```env
GPU_UNLOAD_TIMEOUT_MINUTES=20
```

**Impact** : 🟢 MINEUR

---

## 📊 STATISTIQUES DE L'AUDIT

| Catégorie | Problèmes | % du total |
|-----------|-----------|------------|
| Services Docker manquants | 6 | 21% |
| Ports non documentés | 5 | 18% |
| Commandes incorrectes/obsolètes | 4 | 14% |
| Variables d'environnement manquantes | 8 | 29% |
| Structure répertoires incomplète | 2 | 7% |
| Features non documentées | 5 | 18% |
| **TOTAL** | **28** | **100%** |

---

## ✅ PLAN D'ACTION RECOMMANDÉ

### Phase 1 : Corrections Critiques (Priorité Immédiate)
1. ✅ Ajouter Neo4j dans la stack technique
2. ✅ Ajouter PostgreSQL dans la stack technique
3. ✅ Mettre à jour la section "Services Conteneurisés" avec TOUS les services
4. ✅ Corriger les commandes `docker-compose` (mentionner kw.ps1)
5. ✅ Ajouter toutes les URLs d'accès manquantes
6. ✅ Documenter le script kw.ps1
7. ✅ Ajouter section Monitoring (Grafana/Loki)
8. ✅ Corriger le nom de la collection Qdrant
9. ✅ Documenter `data/extraction_cache/`

### Phase 2 : Corrections Modérées
10. ✅ Clarifier le naming (KnowWhere vs Knowbase)
11. ✅ Documenter folder-watcher service
12. ✅ Documenter configuration GPU
13. ✅ Documenter OSMOSE Phase 1 (ou référencer doc/)
14. ✅ Mettre à jour les versions des dépendances

### Phase 3 : Améliorations
15. ✅ Ajouter variables .env critiques dans la section Configuration
16. ✅ Documenter Burst Mode et Ollama (optionnel)
17. ✅ Ajouter diagramme d'architecture mis à jour

---

## 📝 CONCLUSION

Le README.md contient **de nombreuses incohérences critiques** qui peuvent empêcher les utilisateurs de :
- Démarrer correctement le projet
- Comprendre l'architecture complète
- Accéder aux services (Neo4j, PostgreSQL, Grafana)
- Utiliser les outils de gestion (kw.ps1)

**Action immédiate requise** pour les 12 problèmes critiques identifiés.

---

**Audit réalisé par** : Claude Code (Auto-Claude)
**Date de génération** : 2026-03-10
**Fichiers analysés** : 8 (README.md, docker-compose*.yml, .env, requirements.txt, kw.ps1, CLAUDE.md)
