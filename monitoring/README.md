# Stack de Monitoring KnowWhere / OSMOSE

Stack complète de monitoring et visualisation des logs basée sur **Grafana + Loki + Promtail**.

## 📦 Composants

- **Loki** (port 3100) : Système d'agrégation et d'indexation des logs
- **Promtail** : Agent de collecte des logs Docker
- **Grafana** (port 3001) : Interface de visualisation et dashboards

## 🚀 Démarrage Rapide (Local)

### 1. Démarrer la stack complète

```bash
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

### 2. Accéder à Grafana

- **URL** : http://localhost:3001
- **Identifiants par défaut** :
  - Username : `admin`
  - Password : `admin` (ou valeur de `GRAFANA_ADMIN_PASSWORD` dans `.env`)

### 3. Explorer les logs

Le dashboard "KnowWhere / OSMOSE - Logs Conteneurs" est automatiquement provisionné :

1. Ouvrir Grafana : http://localhost:3001
2. Naviguer vers **Dashboards** → **KnowWhere** → **KnowWhere / OSMOSE - Logs Conteneurs**
3. Utiliser les filtres pour explorer les logs :
   - **Service** : Filtrer par service (app, worker, frontend, etc.)
   - **Niveau** : Filtrer par niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - **Recherche** : Recherche textuelle dans les logs

## 📊 Dashboard Principal

Le dashboard inclut :

- **📄 Logs en temps réel** : Vue des logs avec filtres dynamiques
- **📊 Distribution par niveau** : Graphique des logs par niveau (ERROR, WARNING, INFO, DEBUG)
- **🐳 Volume par service** : Graphique des logs par conteneur
- **🔴 Compteur d'erreurs** : Nombre total d'erreurs
- **🟠 Compteur de warnings** : Nombre total de warnings
- **🔵 Compteur d'infos** : Nombre total d'infos
- **📊 Total des logs** : Nombre total de lignes de log
- **🚨 Erreurs critiques** : Vue dédiée aux erreurs et critiques des dernières 24h

## 🔍 Requêtes Loki Utiles

**📘 Voir le guide complet : [GRAFANA_QUERIES.md](./GRAFANA_QUERIES.md)**

### Logs d'un conteneur spécifique

```logql
# Worker d'ingestion
{compose_project="sap_kb", service="ingestion-worker"}

# Backend FastAPI
{compose_project="sap_kb", service="app"}

# Frontend Next.js
{compose_project="sap_kb", service="frontend"}
```

### Logs d'un fichier spécifique

```logql
# Fichier ingest_debug.log
{log_file="ingest_debug.log"}

# Fichier app_debug.log
{log_file="app_debug.log"}

# Tous les fichiers logs
{service="file_logs"}
```

### Logs par niveau

```logql
# Erreurs uniquement
{compose_project="sap_kb"} | level = "ERROR"

# Erreurs dans un fichier
{log_file="ingest_debug.log"} | level = "ERROR"
```

### Recherche textuelle

```logql
# Recherche simple
{compose_project="sap_kb"} |~ "authentication"

# Recherche dans un fichier
{log_file="ingest_debug.log"} |~ "OSMOSE"
```

### Logs d'un tenant ou requête spécifique

```logql
# Par tenant
{compose_project="sap_kb"} | tenant_id = "default"

# Par request_id
{compose_project="sap_kb"} | request_id = "abc-123-def"
```

**💡 Pour plus d'exemples et de cas d'usage avancés, consultez [GRAFANA_QUERIES.md](./GRAFANA_QUERIES.md)**

## 🔧 Configuration

### Fichiers de configuration

- **monitoring/loki-config.yml** : Configuration Loki (rétention, limites, stockage)
- **monitoring/promtail-config.yml** : Configuration Promtail (scraping, labels, pipelines)
- **monitoring/grafana-datasources.yml** : Provisioning automatique datasource Loki
- **monitoring/grafana-dashboards.yml** : Provisioning automatique dashboards
- **monitoring/dashboards/** : Dashboards JSON

### Modifier la rétention des logs

Éditer `monitoring/loki-config.yml` :

```yaml
limits_config:
  retention_period: 744h  # 31 jours (modifiable)
```

### Changer le mot de passe Grafana

Ajouter dans `.env` :

```bash
GRAFANA_ADMIN_PASSWORD=votre-mot-de-passe
```

Puis redémarrer :

```bash
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml restart grafana
```

## 🛠️ Commandes Utiles

### Vérifier l'état des services

```bash
docker-compose ps | grep -E "(loki|promtail|grafana)"
```

### Voir les logs d'un service

```bash
docker logs knowbase-loki -f
docker logs knowbase-promtail -f
docker logs knowbase-grafana -f
```

### Tester Loki directement

```bash
# Vérifier la disponibilité
curl http://localhost:3100/ready

# Lister les labels
curl -s "http://localhost:3100/loki/api/v1/label" | jq

# Requête de logs
curl -s -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={compose_project="sap_kb"}' \
  --data-urlencode 'limit=10' | jq
```

### Redémarrer la stack monitoring

```bash
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml restart loki promtail grafana
```

### Arrêter la stack monitoring

```bash
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml down loki promtail grafana
```

### Purger les données (logs + dashboards)

```bash
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml down loki promtail grafana
docker volume rm knowbase_loki_data knowbase_grafana_data
```

## 📈 Volumes Persistants

Les données sont stockées dans les volumes Docker :

- **knowbase_loki_data** : Logs indexés par Loki
- **knowbase_grafana_data** : Configuration Grafana (datasources, dashboards, users)

## 🔐 Sécurité

### Changer les credentials Grafana

1. Se connecter avec `admin/admin`
2. Grafana forcera le changement de mot de passe au premier login
3. Ou définir `GRAFANA_ADMIN_PASSWORD` dans `.env`

### Désactiver l'enregistrement public

Déjà configuré dans `docker-compose.monitoring.yml` :

```yaml
environment:
  - GF_USERS_ALLOW_SIGN_UP=false
```

## 📚 Labels Extraits par Promtail

Tous les logs Docker sont enrichis avec ces labels :

- **compose_project** : Nom du projet (`sap_kb`)
- **service** : Nom du service (app, worker, frontend, etc.)
- **container_name** : Nom du conteneur
- **container_id** : ID du conteneur (court)
- **image** : Image Docker utilisée
- **level** : Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- **tenant_id** : ID du tenant (extrait des logs)
- **request_id** : ID de la requête (extrait des logs)
- **logger** : Nom du logger Python
- **module** : Module Python source

Ces labels permettent des requêtes très précises dans Grafana.

## 🐛 Troubleshooting

### Loki ne démarre pas

Vérifier les logs :

```bash
docker logs knowbase-loki --tail=50
```

Erreurs communes :
- **Permission denied** : Vérifier les permissions des volumes
- **Config parse error** : Valider `monitoring/loki-config.yml`

### Promtail ne collecte pas les logs

Vérifier :

```bash
# Logs Promtail
docker logs knowbase-promtail --tail=50

# Vérifier que le socket Docker est accessible
ls -la /var/run/docker.sock
```

### Grafana ne se connecte pas à Loki

1. Vérifier que Loki est accessible depuis Grafana :

```bash
docker exec knowbase-grafana wget -O- http://loki:3100/ready
```

2. Vérifier la datasource dans Grafana :
   - **Configuration** → **Data Sources** → **Loki**
   - Tester la connexion

### Pas de logs dans le dashboard

1. Vérifier que Promtail collecte bien les logs :

```bash
curl -s "http://localhost:3100/loki/api/v1/label/service/values" | jq
```

2. Vérifier les requêtes du dashboard :
   - Les labels `compose_project="sap_kb"` doivent matcher
   - Ajuster la période de temps dans Grafana (en haut à droite)

## 🌐 URLs de Référence

- **Grafana** : http://localhost:3001
- **Loki API** : http://localhost:3100
- **Loki Metrics** : http://localhost:3100/metrics
- **Documentation Loki** : https://grafana.com/docs/loki/latest/
- **Documentation Promtail** : https://grafana.com/docs/loki/latest/clients/promtail/
- **Documentation Grafana** : https://grafana.com/docs/grafana/latest/

## 🚀 Déploiement AWS (À venir)

Les instructions pour déployer cette stack sur AWS EC2 seront ajoutées prochainement. Cela inclura :

- Images ECR pour Loki, Promtail, Grafana
- Configuration CloudFormation
- Security Groups et IAM roles
- Configuration HTTPS avec certificats
- Backup automatique des volumes

---

**💡 Astuce** : Pour une meilleure expérience, installez le plugin Grafana "Logs Panel" pour des fonctionnalités avancées de recherche dans les logs.
