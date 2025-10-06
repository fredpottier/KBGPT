# 🧹 Scripts de Nettoyage des Bases de Données

Scripts pour nettoyer complètement toutes les bases de données du projet SAP KB et repartir avec une base propre.

## 🎯 Objectif

Ces scripts suppriment **TOUTES** les données de :
- ✅ **Qdrant** : toutes les collections vectorielles
- ✅ **Redis** : DB 0 (imports metadata) et DB 1 (jobs queue)
- ✅ **Neo4j** : tous les nodes et relations du Knowledge Graph
- ✅ **Historique** : fichiers status des imports

## 📋 Scripts Disponibles

### Windows (recommandé)
```cmd
scripts\clean_all_databases.cmd --confirm
```

### Linux/Mac (Bash)
```bash
./scripts/clean_all_databases.sh --confirm
```

### PowerShell (Windows alternatif)
```powershell
.\scripts\clean_all_databases.ps1 -Confirm
```

## 🔧 Usage

### Mode Interactif (avec confirmation)
```bash
# Windows
scripts\clean_all_databases.cmd

# Linux/Mac
./scripts/clean_all_databases.sh
```

Le script vous demandera de confirmer avant de supprimer les données.

### Mode Automatique (sans confirmation)
```bash
# Windows
scripts\clean_all_databases.cmd --confirm

# Linux/Mac
./scripts/clean_all_databases.sh --confirm

# PowerShell
.\scripts\clean_all_databases.ps1 -Confirm
```

## 📊 Détails des Opérations

### 1. Qdrant (Collections Vectorielles)
- Supprime toutes les collections : `knowbase`, `rfp_qa`, etc.
- Utilisé pour : recherche sémantique, embeddings

### 2. Redis (Queue & Metadata)
- **DB 0** : Métadonnées des imports (historique, status)
- **DB 1** : Queue des jobs d'ingestion (RQ)

### 3. Neo4j (Knowledge Graph)
- Supprime tous les nodes (entités)
- Supprime toutes les relations
- Utilisé pour : graphe de connaissances, relations entre entités

### 4. Historique Imports
- Supprime : `data/status/*.json`
- Fichiers de suivi des imports PPTX/PDF/Excel

## ⚠️ Important

### ⚠️ **Action Irréversible**
- Les données supprimées **ne peuvent pas être récupérées**
- Assurez-vous d'avoir une sauvegarde si nécessaire

### ✅ **Conservé (Non Supprimé)**
- Fichiers sources : `data/docs_in/`, `data/docs_done/`
- Slides PNG : `data/public/slides/`
- Configuration : `config/`, `.env`
- Catalogues d'ontologies : `config/ontologies/`
- Code source : `src/`, `frontend/`

## 🚀 Cas d'Usage Typiques

### 1. Après Modifications du Pipeline d'Ingestion
```bash
# Nettoyer pour re-tester l'ingestion complète
scripts\clean_all_databases.cmd --confirm
```

### 2. Avant Import d'un Nouveau Jeu de Données
```bash
# Repartir avec une base propre
./scripts/clean_all_databases.sh --confirm
```

### 3. Résolution de Problèmes de Cohérence
```bash
# Nettoyer en cas de données corrompues ou incohérentes
scripts\clean_all_databases.cmd --confirm
```

### 4. Tests Automatisés
```bash
# Intégrer dans scripts de test
./scripts/clean_all_databases.sh --confirm
pytest tests/
```

## 🔍 Vérification Post-Nettoyage

### Qdrant
```bash
curl http://localhost:6333/collections
# Devrait retourner: {"result": {"collections": []}}
```

### Redis
```bash
docker exec knowbase-redis redis-cli -n 0 DBSIZE
# Devrait retourner: 0

docker exec knowbase-redis redis-cli -n 1 DBSIZE
# Devrait retourner: 0
```

### Neo4j
```bash
docker exec graphiti-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (n) RETURN count(n) as count"
# Devrait retourner: count = 0
```

### Historique
```bash
ls -la data/status/*.json
# Devrait retourner: No such file or directory
```

## 📝 Logs et Debug

Les scripts affichent des logs détaillés pour chaque étape :
- ℹ️ **Bleu** : Informations
- ✅ **Vert** : Succès
- ⚠️ **Jaune** : Avertissements
- ❌ **Rouge** : Erreurs

## 🔐 Credentials

Les scripts utilisent automatiquement les credentials du fichier `.env` :

```env
# Neo4j
NEO4J_URI=bolt://graphiti-neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=graphiti_neo4j_pass
```

## 🛠️ Dépannage

### Script ne trouve pas Neo4j
```bash
# Vérifier que le conteneur tourne
docker ps | grep neo4j

# Vérifier les credentials
grep NEO4J .env
```

### Erreur de permissions Redis
```bash
# Redémarrer Redis
docker restart knowbase-redis
```

### Erreur Qdrant
```bash
# Vérifier que Qdrant est accessible
curl http://localhost:6333/health
```

## 📚 Workflow Complet Recommandé

```bash
# 1. Nettoyer toutes les bases
scripts\clean_all_databases.cmd --confirm

# 2. Vérifier l'état
curl http://localhost:6333/collections
docker exec knowbase-redis redis-cli -n 0 DBSIZE

# 3. Importer de nouvelles données
# Via UI: http://localhost:3000/documents/import
# Ou via API: POST http://localhost:8000/ingest

# 4. Vérifier les résultats
# UI: http://localhost:3000/documents/status
# API: GET http://localhost:8000/api/imports
```

## 🔗 Voir Aussi

- [Documentation Import](../doc/import-status-system-analysis.md)
- [Architecture RAG/KG](../doc/ARCHITECTURE_RAG_KG_NORTH_STAR.md)
- [Configuration LLM](../config/llm_models.yaml)
