# Guide des Requêtes Grafana / Loki pour KnowWhere

Guide pratique pour filtrer et rechercher dans les logs avec Grafana et Loki.

## 🔍 Filtrer par Conteneur / Service

### Via le Dashboard

Le dashboard **"KnowWhere / OSMOSE - Logs Conteneurs"** a un dropdown **Service** en haut qui permet de filtrer facilement.

1. Ouvrir : http://localhost:3001/d/osmose-container-logs
2. Cliquer sur le dropdown **Service**
3. Sélectionner un ou plusieurs services :
   - `app` - Backend FastAPI
   - `ingestion-worker` - Worker d'ingestion
   - `frontend` - Interface Next.js
   - `ui` - Interface Streamlit (legacy)
   - `neo4j` - Base de données graphe
   - `qdrant` - Base vectorielle
   - `redis` - Queue de tâches
   - `file_logs` - Logs des fichiers (ingest_debug.log, app_debug.log)

### Via Requêtes LogQL

#### Logs d'un service spécifique

```logql
# Worker d'ingestion uniquement
{compose_project="sap_kb", service="ingestion-worker"}

# Backend FastAPI uniquement
{compose_project="sap_kb", service="app"}

# Frontend Next.js uniquement
{compose_project="sap_kb", service="frontend"}

# Neo4j uniquement
{compose_project="sap_kb", service="neo4j"}
```

#### Logs de plusieurs services

```logql
# Worker + Backend
{compose_project="sap_kb", service=~"app|ingestion-worker"}

# Tous les services sauf Neo4j
{compose_project="sap_kb", service!="neo4j"}
```

## 📁 Filtrer par Fichier Log

### Voir les logs d'un fichier spécifique

```logql
# Logs du fichier ingest_debug.log
{log_file="ingest_debug.log"}

# Logs du fichier app_debug.log
{log_file="app_debug.log"}

# Tous les fichiers logs
{service="file_logs"}
```

### Combiner fichier + recherche

```logql
# Rechercher "ERROR" dans ingest_debug.log
{log_file="ingest_debug.log"} |~ "ERROR"

# Rechercher "OSMOSE" dans ingest_debug.log
{log_file="ingest_debug.log"} |~ "OSMOSE"

# Logs d'un tenant dans ingest_debug.log
{log_file="ingest_debug.log"} | tenant_id = "default"
```

## 🎯 Filtrer par Niveau de Log

### Via le Dashboard

Utiliser le dropdown **Niveau** en haut du dashboard pour sélectionner :
- `DEBUG` - Logs de debug détaillés
- `INFO` - Logs informatifs
- `WARNING` - Avertissements
- `ERROR` - Erreurs
- `CRITICAL` - Erreurs critiques

### Via Requêtes LogQL

```logql
# Erreurs uniquement
{compose_project="sap_kb"} | level = "ERROR"

# Erreurs + Critiques
{compose_project="sap_kb"} | level =~ "ERROR|CRITICAL"

# Avertissements du worker
{compose_project="sap_kb", service="ingestion-worker"} | level = "WARNING"

# Erreurs dans ingest_debug.log
{log_file="ingest_debug.log"} | level = "ERROR"
```

## 🔎 Recherche Textuelle

### Recherche simple (case-insensitive par défaut)

```logql
# Rechercher "authentication"
{compose_project="sap_kb"} |~ "authentication"

# Rechercher "document" dans le worker
{compose_project="sap_kb", service="ingestion-worker"} |~ "document"

# Rechercher "OSMOSE" dans tous les logs
{compose_project="sap_kb"} |~ "OSMOSE"
```

### Recherche case-sensitive

```logql
# Rechercher exactement "ERROR" (case-sensitive)
{compose_project="sap_kb"} |= "ERROR"
```

### Exclure un pattern

```logql
# Tous les logs SAUF ceux contenant "health"
{compose_project="sap_kb"} !~ "health"
```

### Recherche avec regex avancée

```logql
# Logs contenant un UUID
{compose_project="sap_kb"} |~ "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# Logs avec une URL
{compose_project="sap_kb"} |~ "http[s]?://[^\\s]+"

# Logs avec une adresse email
{compose_project="sap_kb"} |~ "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"
```

## 🏷️ Filtrer par Métadonnées

### Par Tenant ID

```logql
# Logs du tenant "default"
{compose_project="sap_kb"} | tenant_id = "default"

# Erreurs d'un tenant spécifique
{compose_project="sap_kb"} | tenant_id = "default" | level = "ERROR"
```

### Par Request ID

```logql
# Suivre une requête spécifique
{compose_project="sap_kb"} | request_id = "abc-123-def"

# Tous les logs d'une requête (fichiers + conteneurs)
{compose_project="sap_kb"} | request_id = "abc-123-def"
```

### Par Logger Python

```logql
# Logs d'un logger spécifique
{compose_project="sap_kb"} | logger = "knowbase.api.routers.auth"

# Logs de tous les routers API
{compose_project="sap_kb"} | logger =~ "knowbase.api.routers.*"
```

## 📊 Requêtes d'Agrégation

### Compter les logs

```logql
# Nombre de logs par service (dernière heure)
sum by (service) (count_over_time({compose_project="sap_kb"} [1h]))

# Nombre d'erreurs par service
sum by (service) (count_over_time({compose_project="sap_kb"} | level = "ERROR" [1h]))

# Nombre de logs par fichier
sum by (log_file) (count_over_time({service="file_logs"} [1h]))
```

### Taux de logs

```logql
# Taux de logs par seconde
rate({compose_project="sap_kb"} [5m])

# Taux d'erreurs par seconde
rate({compose_project="sap_kb"} | level = "ERROR" [5m])
```

## 🔗 Combinaisons Avancées

### Logs d'ingestion avec erreurs

```logql
{compose_project="sap_kb", service="ingestion-worker"} | level = "ERROR" |~ "pipeline"
```

### Logs d'authentification

```logql
{compose_project="sap_kb", service="app"} |~ "auth|login|token" | level =~ "ERROR|WARNING"
```

### Logs liés aux documents

```logql
# Tous les logs mentionnant "document" dans le worker
{compose_project="sap_kb", service="ingestion-worker"} |~ "document"

# Dans ingest_debug.log
{log_file="ingest_debug.log"} |~ "document"
```

### Logs de performance

```logql
# Logs avec des durées
{compose_project="sap_kb"} |~ "duration|took|elapsed|ms|seconds"

# Logs lents (plus de 1000ms)
{compose_project="sap_kb"} |~ "duration.*[1-9][0-9]{3,}.*ms"
```

## 🎨 Utilisation dans Grafana

### Explore View

1. Ouvrir Grafana : http://localhost:3001
2. Cliquer sur **Explore** dans le menu gauche (icône boussole)
3. Sélectionner la datasource **Loki**
4. Entrer une requête LogQL dans le champ
5. Ajuster la période de temps en haut à droite
6. Cliquer sur **Run query**

### Filtres dynamiques dans le Dashboard

Le dashboard inclut 3 variables (filtres en haut) :

1. **Service** : Filtre par conteneur/service
   - Sélection multiple autorisée
   - "All" pour tous les services

2. **Niveau** : Filtre par niveau de log
   - Sélection multiple autorisée
   - "All" pour tous les niveaux

3. **Recherche** : Recherche textuelle libre
   - Tapez n'importe quel mot-clé
   - Case-insensitive par défaut

### Liens Rapides depuis les Logs

Le dashboard inclut des **derived fields** qui créent des liens cliquables :

- **Request ID** : Cliquer sur un request_id filtre tous les logs de cette requête
- **Tenant ID** : Cliquer sur un tenant_id filtre tous les logs de ce tenant
- **Error Details** : Cliquer sur ERROR/CRITICAL filtre toutes les erreurs

## 📝 Exemples Pratiques

### Cas d'usage 1 : Débugger une erreur d'ingestion

```logql
# 1. Voir toutes les erreurs récentes du worker
{compose_project="sap_kb", service="ingestion-worker"} | level = "ERROR"

# 2. Trouver le request_id dans un log d'erreur
# 3. Suivre toute la requête avec ce request_id
{compose_project="sap_kb"} | request_id = "abc-123-def"
```

### Cas d'usage 2 : Analyser les logs d'ingestion

```logql
# Voir tous les logs d'ingestion dans le fichier
{log_file="ingest_debug.log"}

# Filtrer sur un type de document
{log_file="ingest_debug.log"} |~ "PPTX|PDF|DOCX"

# Voir les erreurs uniquement
{log_file="ingest_debug.log"} | level = "ERROR"
```

### Cas d'usage 3 : Problèmes d'authentification

```logql
# Tous les logs liés à l'auth
{compose_project="sap_kb", service="app"} |~ "auth|login|token"

# Erreurs d'auth uniquement
{compose_project="sap_kb", service="app"} |~ "auth|login|token" | level = "ERROR"
```

### Cas d'usage 4 : Surveiller un tenant spécifique

```logql
# Tous les logs d'un tenant
{compose_project="sap_kb"} | tenant_id = "my-tenant"

# Erreurs d'un tenant
{compose_project="sap_kb"} | tenant_id = "my-tenant" | level = "ERROR"
```

## 🚀 Astuces Grafana

### Rafraîchissement Automatique

En haut à droite du dashboard :
- Cliquer sur l'icône d'actualisation
- Choisir un intervalle (5s, 10s, 30s, 1m)
- Le dashboard se rafraîchit automatiquement

### Période de Temps

En haut à droite :
- **Last 5 minutes** : Logs des 5 dernières minutes
- **Last 1 hour** : Logs de la dernière heure
- **Last 24 hours** : Logs des dernières 24h
- **Custom** : Période personnalisée

### Contexte autour d'un Log

Dans le panel de logs :
1. Cliquer sur une ligne de log
2. Cliquer sur **Show context**
3. Voir les logs avant et après

### Copier une Requête

Dans Explore :
1. Écrire votre requête
2. Cliquer sur **Copy link** (icône lien)
3. Partager le lien avec votre équipe

## 📚 Documentation LogQL

Documentation officielle : https://grafana.com/docs/loki/latest/logql/

### Opérateurs de Filtre

- `|=` : Contient (case-sensitive)
- `!=` : Ne contient pas (case-sensitive)
- `|~` : Regex match (case-insensitive par défaut)
- `!~` : Regex ne match pas

### Opérateurs de Parsing

- `| json` : Parser JSON
- `| logfmt` : Parser format logfmt
- `| regex "pattern"` : Extraire avec regex
- `| line_format` : Reformater la ligne

### Agrégations

- `count_over_time()` : Compter les logs
- `rate()` : Taux par seconde
- `sum()`, `avg()`, `min()`, `max()` : Agrégations mathématiques
- `topk()`, `bottomk()` : Top/Bottom K valeurs

---

**💡 Astuce** : Pour apprendre LogQL, utilisez la vue **Explore** de Grafana avec l'auto-complétion (Ctrl+Space).
