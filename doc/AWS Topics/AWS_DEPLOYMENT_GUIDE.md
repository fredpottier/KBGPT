# Guide de Déploiement AWS - KnowWhere OSMOSE

**Documentation complète pour déployer KnowWhere OSMOSE sur AWS EC2 depuis Windows**

Version: 1.0
Date: 2025-10-13
Auteur: Infrastructure OSMOSE

---

## 📋 Table des Matières

1. [Vue d'ensemble](#vue-densemble)
2. [Prérequis](#prérequis)
3. [Architecture AWS](#architecture-aws)
4. [Étapes de déploiement](#étapes-de-déploiement)
5. [Workflows de déploiement](#workflows-de-déploiement)
6. [Maintenance et monitoring](#maintenance-et-monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Coûts estimés](#coûts-estimés)

---

## 🎯 Vue d'ensemble

### Objectif

Déployer l'infrastructure complète KnowWhere OSMOSE sur une instance EC2 AWS en utilisant :
- **Build local** (Windows) des images Docker
- **AWS ECR** pour le stockage des images
- **EC2** pour l'exécution des conteneurs
- **Docker Compose** pour l'orchestration

### Architecture Déployée

```
┌─────────────────────────────────────────────────────────────┐
│                     Instance EC2                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Docker Compose Stack                                │   │
│  │                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────┐         │   │
│  │  │  Neo4j   │  │  Qdrant  │  │   Redis   │         │   │
│  │  │  (KG)    │  │ (Vector) │  │  (Queue)  │         │   │
│  │  └──────────┘  └──────────┘  └───────────┘         │   │
│  │                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────┐         │   │
│  │  │   App    │  │  Worker  │  │    UI     │         │   │
│  │  │ (FastAPI)│  │ (Ingest) │  │(Streamlit)│         │   │
│  │  └──────────┘  └──────────┘  └───────────┘         │   │
│  │                                                       │   │
│  │  ┌──────────────────────────────────┐               │   │
│  │  │        Frontend (Next.js)        │               │   │
│  │  └──────────────────────────────────┘               │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Images pull depuis
                          ▼
                  ┌───────────────┐
                  │   AWS ECR     │
                  │   (Registry)  │
                  └───────────────┘
                          ▲
                          │ Images push depuis
                          │
                  ┌───────────────┐
                  │  Windows PC   │
                  │  (Build local)│
                  └───────────────┘
```

### Services Déployés

| Service | Port | Description | RAM | CPU |
|---------|------|-------------|-----|-----|
| **Neo4j** | 7474, 7687 | Knowledge Graph | 4-6 GB | 1-2 |
| **Qdrant** | 6333, 6334 | Vector Database | 2-4 GB | 1 |
| **Redis** | 6379 | Queue & Cache | 2 GB | 0.5 |
| **App (FastAPI)** | 8000 | API Backend | 2-4 GB | 1-2 |
| **Worker** | - | Ingestion Worker | 4-6 GB | 2-3 |
| **Frontend** | 3000 | Next.js UI | 1-2 GB | 0.5-1 |
| **Streamlit UI** | 8501 | Legacy UI | 1 GB | 0.5 |
| **TOTAL** | - | - | **16-25 GB** | **8-12 vCPU** |

---

## ✅ Prérequis

### 1. Compte AWS

- [ ] Compte AWS actif
- [ ] AWS CLI installé et configuré
- [ ] Credentials AWS configurées (`aws configure`)
- [ ] Permissions IAM nécessaires :
  - `AmazonEC2FullAccess` (ou EC2 Read/Write)
  - `AmazonEC2ContainerRegistryFullAccess` (ECR Push/Pull)
  - `IAMReadOnlyAccess` (pour STS)

**Vérification :**
```powershell
aws sts get-caller-identity
# Doit retourner votre Account ID et ARN
```

### 2. Outils Locaux (Windows)

- [ ] **Docker Desktop** installé et fonctionnel
  - Download: https://www.docker.com/products/docker-desktop/
  - Vérification: `docker --version`

- [ ] **PowerShell 5.1+** ou **PowerShell Core 7+**
  - Vérification: `$PSVersionTable.PSVersion`

- [ ] **AWS CLI v2**
  - Download: https://aws.amazon.com/cli/
  - Vérification: `aws --version`

- [ ] **OpenSSH Client** (inclus dans Windows 10/11)
  - Settings > Apps > Optional Features > OpenSSH Client
  - Vérification: `ssh -V`

- [ ] **Git** (pour tag automatique des images)
  - Download: https://git-scm.com/
  - Vérification: `git --version`

### 3. Clés API

- [ ] **OpenAI API Key** (https://platform.openai.com/api-keys)
- [ ] **Anthropic API Key** (https://console.anthropic.com/)

### 4. Configuration Projet

- [ ] Repository cloné localement
- [ ] Fichier `.env.production` créé (basé sur `.env.ecr.example`)

---

## 🏗️ Architecture AWS

### Ressources AWS Nécessaires

#### 1. AWS ECR (Elastic Container Registry)

**Repositories créés automatiquement par le script :**
- `sap-kb-app` (Backend FastAPI)
- `sap-kb-worker` (Ingestion Worker)
- `sap-kb-frontend` (Next.js Frontend)
- `sap-kb-ui` (Streamlit UI)
- `sap-kb-neo4j` (Neo4j mirror)
- `sap-kb-redis` (Redis mirror)
- `sap-kb-qdrant` (Qdrant mirror)
- `sap-kb-ngrok` (Ngrok mirror)

**Région :** eu-west-1 (par défaut, configurable)

#### 2. Instance EC2

**Recommandations selon charge :**

| Type Instance | vCPU | RAM | Prix/mois* | Usage Recommandé |
|---------------|------|-----|------------|------------------|
| **t3.xlarge** | 4 | 16 GB | ~$60 | Tests, 10-50 docs/jour |
| **t3.2xlarge** | 8 | 32 GB | ~$120 | Production légère, 50-200 docs/jour |
| **m5.2xlarge** | 8 | 32 GB | ~$140 | Production intensive, 200-500 docs/jour |
| **c5.4xlarge** | 16 | 32 GB | ~$250 | Production lourde, 500+ docs/jour |

*Prix approximatifs région eu-west-1, on-demand

**Système d'exploitation :** Ubuntu 22.04 LTS (recommandé) ou Amazon Linux 2

**Stockage :**
- Root volume : 30 GB minimum (gp3)
- Data volume : 100-500 GB selon volume documentaire (gp3)

**Security Group (Ports à ouvrir) :**

| Port | Service | Source | Description |
|------|---------|--------|-------------|
| 22 | SSH | Votre IP | Administration |
| 8000 | API Backend | 0.0.0.0/0 ou votre IP | API REST |
| 3000 | Frontend | 0.0.0.0/0 ou votre IP | Interface utilisateur |
| 8501 | Streamlit | Votre IP | UI Legacy |
| 7474 | Neo4j Browser | Votre IP | Admin Graph DB |
| 6333 | Qdrant UI | Votre IP | Admin Vector DB |

**⚠️ SÉCURITÉ :**
- **JAMAIS** ouvrir les ports 7474, 6333 en 0.0.0.0/0 (risque intrusion)
- Limiter SSH (22) à votre IP uniquement
- Utiliser des Security Groups stricts

#### 3. Elastic IP (Recommandé)

Associez une **Elastic IP** à votre instance pour :
- Adresse IP fixe (évite changement à chaque redémarrage)
- Configuration DNS simplifiée
- Coût : Gratuit tant que l'IP est associée à une instance active

---

## 🚀 Étapes de Déploiement

### Phase 1 : Préparation Locale

#### 1.1 Cloner le Repository

```powershell
git clone https://github.com/votre-org/knowbase-osmose.git
cd knowbase-osmose
```

#### 1.2 Créer le Fichier .env.production

```powershell
# Copier le template
Copy-Item .env.ecr.example .env.production

# Éditer avec vos valeurs
notepad .env.production
```

**Variables critiques à configurer :**

```env
# AWS
AWS_ACCOUNT_ID=715927975014
AWS_REGION=eu-west-1

# API Keys
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx

# Neo4j
NEO4J_PASSWORD=VotreMotDePasseTresSecurise123!

# Frontend (à ajuster après création EC2)
FRONTEND_API_BASE_URL=http://localhost:8000  # Changez après déploiement EC2
```

#### 1.3 Vérifier la Configuration AWS CLI

```powershell
# Vérifier credentials
aws sts get-caller-identity

# Vérifier région par défaut
aws configure get region

# Si nécessaire, reconfigurer
aws configure
```

---

### Phase 2 : Build et Push des Images vers ECR

#### 2.1 Exécuter le Script de Build

```powershell
# Build complet (première fois)
.\scripts\build-and-push-ecr.ps1

# Options disponibles :
.\scripts\build-and-push-ecr.ps1 -NoCache              # Build from scratch
.\scripts\build-and-push-ecr.ps1 -SkipThirdParty       # Seulement images custom
.\scripts\build-and-push-ecr.ps1 -Tag "v1.0.0"         # Tag spécifique
.\scripts\build-and-push-ecr.ps1 -Region "us-east-1"   # Autre région
```

**Durée estimée :** 15-30 minutes (première fois, selon connexion Internet)

**Output attendu :**
```
✅ Build et push terminés avec succès !

Images disponibles dans ECR:
  - 715927975014.dkr.ecr.eu-west-1.amazonaws.com/sap-kb-app:abc123
  - 715927975014.dkr.ecr.eu-west-1.amazonaws.com/sap-kb-worker:abc123
  - 715927975014.dkr.ecr.eu-west-1.amazonaws.com/sap-kb-frontend:abc123
  - ...
```

#### 2.2 Vérifier les Images dans ECR

```powershell
# Lister les repositories
aws ecr describe-repositories --region eu-west-1

# Vérifier les images d'un repo
aws ecr list-images --repository-name sap-kb-app --region eu-west-1
```

---

### Phase 3 : Création de l'Instance EC2

#### 3.1 Créer l'Instance via AWS Console

**Via AWS Console :**

1. Aller sur EC2 Dashboard > Launch Instance

2. **Name and tags :**
   - Name : `knowbase-osmose-prod`

3. **Application and OS Images :**
   - AMI : Ubuntu Server 22.04 LTS
   - Architecture : 64-bit (x86)

4. **Instance type :**
   - Choisir : `t3.xlarge` (minimum recommandé)

5. **Key pair :**
   - Créer ou sélectionner une clé SSH
   - **IMPORTANT :** Téléchargez et sauvegardez le fichier `.pem`
   - Exemple : `knowbase-ec2-key.pem`

6. **Network settings :**
   - Créer un Security Group avec les ports ci-dessus
   - Ou utiliser un SG existant

7. **Configure storage :**
   - Root volume : 30 GB gp3
   - Ajouter volume data : 100 GB gp3 (optionnel)

8. **Advanced details :**
   - IAM instance profile : Créer un role avec `AmazonEC2ContainerRegistryReadOnly` (pour pull ECR)

9. **Launch instance**

**Via AWS CLI (alternatif) :**

```powershell
# Variables
$AMI_ID = "ami-0c55b159cbfafe1f0"  # Ubuntu 22.04 LTS eu-west-1
$INSTANCE_TYPE = "t3.xlarge"
$KEY_NAME = "knowbase-ec2-key"
$SECURITY_GROUP_ID = "sg-xxxxxxxxx"  # Votre SG

# Lancer l'instance
aws ec2 run-instances `
  --image-id $AMI_ID `
  --instance-type $INSTANCE_TYPE `
  --key-name $KEY_NAME `
  --security-group-ids $SECURITY_GROUP_ID `
  --block-device-mappings DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3} `
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=knowbase-osmose-prod}]" `
  --region eu-west-1
```

#### 3.2 Associer une Elastic IP (Recommandé)

```powershell
# Allouer une nouvelle Elastic IP
aws ec2 allocate-address --region eu-west-1

# Noter l'AllocationId retourné
$ALLOCATION_ID = "eipalloc-xxxxxxxxx"
$INSTANCE_ID = "i-xxxxxxxxx"  # ID de votre instance

# Associer l'Elastic IP à l'instance
aws ec2 associate-address `
  --instance-id $INSTANCE_ID `
  --allocation-id $ALLOCATION_ID `
  --region eu-west-1
```

#### 3.3 Récupérer l'IP Publique

```powershell
# Via CLI
aws ec2 describe-instances `
  --instance-ids i-xxxxxxxxx `
  --query "Reservations[0].Instances[0].PublicIpAddress" `
  --output text

# Ou via Console EC2 > Instances > Sélectionner instance > Public IPv4 address
```

**Notez l'IP publique :** Exemple : `18.203.45.67`

---

### Phase 4 : Déploiement sur EC2

#### 4.1 Mettre à Jour .env.production avec l'IP EC2

```powershell
# Éditer .env.production
notepad .env.production

# Modifier cette ligne :
FRONTEND_API_BASE_URL=http://18.203.45.67:8000  # Remplacer par votre IP EC2
```

#### 4.2 Exécuter le Script de Déploiement

```powershell
# Déploiement complet (première fois)
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\Users\VotreNom\.ssh\knowbase-ec2-key.pem"

# Options disponibles :
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\keys\my-key.pem" `
  -Username "ubuntu"              # ou "ec2-user" pour Amazon Linux

# Update déploiement (sans refaire le setup)
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\keys\my-key.pem" `
  -SkipSetup                      # Skip installation Docker/AWS CLI
```

**Le script effectue automatiquement :**
1. ✅ Test de connexion SSH
2. ✅ Installation Docker, Docker Compose, AWS CLI (si pas `-SkipSetup`)
3. ✅ Configuration des credentials AWS temporaires
4. ✅ Transfert docker-compose.ecr.yml et .env.production
5. ✅ Transfert des fichiers config/ (YAML)
6. ✅ Login ECR
7. ✅ Pull des images depuis ECR
8. ✅ Démarrage des conteneurs
9. ✅ Healthcheck des services

**Durée estimée :** 10-20 minutes (setup initial) ou 3-5 minutes (update)

#### 4.3 Vérifier le Déploiement

**Automatiquement par le script :**
```
=== Healthcheck des services ===
Backend API: 200
Frontend: 200
Neo4j: 200
Qdrant: 200
Redis: PONG
```

**Manuellement via navigateur :**
- API Backend : http://18.203.45.67:8000/docs
- Frontend : http://18.203.45.67:3000
- Neo4j Browser : http://18.203.45.67:7474
- Qdrant UI : http://18.203.45.67:6333/dashboard

---

## 🔄 Workflows de Déploiement

### Workflow 1 : Déploiement Initial (Première Fois)

```powershell
# 1. Préparation
git clone <repo>
cd knowbase-osmose
Copy-Item .env.ecr.example .env.production
notepad .env.production  # Configurer clés API

# 2. Build et push images
.\scripts\build-and-push-ecr.ps1

# 3. Créer instance EC2 (via Console ou CLI)
# Récupérer IP publique : 18.203.45.67

# 4. Mettre à jour .env.production avec IP EC2
notepad .env.production  # FRONTEND_API_BASE_URL=http://18.203.45.67:8000

# 5. Déployer
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem"

# 6. Vérifier
# Ouvrir http://18.203.45.67:3000
```

**Durée totale :** 45-60 minutes

---

### Workflow 2 : Update du Code (Après Modifications)

```powershell
# 1. Faire vos modifications de code
git add .
git commit -m "feat: nouvelle fonctionnalité"

# 2. Rebuilder et push seulement les images custom
.\scripts\build-and-push-ecr.ps1 -SkipThirdParty

# 3. Redéployer sans refaire le setup
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem" `
  -SkipSetup

# 4. Vérifier
```

**Durée totale :** 10-15 minutes

---

### Workflow 3 : Build via CodeBuild (CI/CD Automatique)

**Setup CodeBuild (une fois) :**

1. Créer un projet CodeBuild :
   - Source : GitHub (votre repo)
   - Buildspec : `buildspec.yml` (déjà configuré)
   - Environment : Ubuntu Standard 5.0
   - Service role : Avec permissions ECR

2. Configurer le webhook GitHub :
   - Trigger sur push vers `main` ou tags

3. CodeBuild build automatiquement sur chaque push

**Workflow avec CodeBuild :**

```powershell
# 1. Faire vos modifications
git add .
git commit -m "feat: nouvelle fonctionnalité"
git push origin main

# 2. CodeBuild build automatiquement (5-10 min)

# 3. Une fois build terminé, redéployer
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem" `
  -SkipSetup
```

**Avantages :**
- ✅ CI/CD automatique
- ✅ Build logs centralisés
- ✅ Pas de dépendance machine locale

**Coûts :** ~$0.005/minute build (~$10-15/mois usage modéré)

---

## 🔧 Maintenance et Monitoring

### Se Connecter à l'Instance EC2

```powershell
# SSH direct
ssh -i "C:\path\to\key.pem" ubuntu@18.203.45.67

# Une fois connecté
cd /home/ubuntu/knowbase
```

### Commandes Utiles

#### Gestion des Conteneurs

```bash
# Statut des services
docker-compose ps

# Logs en temps réel
docker-compose logs -f

# Logs d'un service spécifique
docker-compose logs -f app
docker-compose logs -f worker

# Redémarrer un service
docker-compose restart app

# Arrêter tout
docker-compose down

# Redémarrer tout
docker-compose up -d
```

#### Monitoring Ressources

```bash
# Utilisation CPU/RAM par conteneur
docker stats

# Espace disque
df -h

# Logs système
sudo journalctl -u docker -f
```

#### Mise à Jour des Images

```bash
# Pull dernières images
docker-compose pull

# Recreate conteneurs avec nouvelles images
docker-compose up -d --force-recreate
```

### Backup & Restore

#### Backup Neo4j

```bash
# Backup manuel
docker exec knowbase-neo4j neo4j-admin dump \
  --database=neo4j --to=/data/backups/neo4j-$(date +%Y%m%d).dump

# Copier backup vers local
scp -i "C:\path\to\key.pem" ubuntu@18.203.45.67:/data/backups/neo4j-*.dump .
```

#### Backup Qdrant

```bash
# Backup via API
curl -X POST http://localhost:6333/collections/knowbase/snapshots

# Télécharger snapshot
# Voir doc Qdrant : https://qdrant.tech/documentation/snapshots/
```

#### Backup Redis

```bash
# Redis fait des backups automatiques (appendonly.aof, dump.rdb)
docker exec knowbase-redis redis-cli BGSAVE

# Copier backup
scp -i "key.pem" ubuntu@18.203.45.67:/data/redis/dump.rdb .
```

---

## 🐛 Troubleshooting

### Problème 1 : Impossible de se connecter en SSH

**Symptômes :**
```
Connection timed out
```

**Solutions :**
1. Vérifier Security Group autorise port 22 depuis votre IP
2. Vérifier l'instance est bien "running"
3. Vérifier la clé SSH correspond à l'instance
4. Essayer avec l'Elastic IP si associée

```powershell
# Vérifier Security Group
aws ec2 describe-security-groups --group-ids sg-xxxxxxxxx
```

---

### Problème 2 : Conteneurs n'arrivent pas à pull les images ECR

**Symptômes :**
```
Error response from daemon: pull access denied
```

**Solutions :**
1. Vérifier credentials AWS sur EC2 sont valides
2. Re-login ECR sur l'instance

```bash
# Sur l'instance EC2
aws ecr get-login-password --region eu-west-1 | \
  docker login --username AWS --password-stdin \
  715927975014.dkr.ecr.eu-west-1.amazonaws.com
```

---

### Problème 3 : Service unhealthy après démarrage

**Symptômes :**
```
docker-compose ps
# Status: unhealthy
```

**Solutions :**

```bash
# Vérifier logs du service
docker-compose logs <service>

# Cas courant : Neo4j mémoire insuffisante
docker-compose logs neo4j
# Solution : Augmenter instance EC2 ou réduire heap Neo4j

# Cas courant : API Backend manque API keys
docker-compose logs app
# Solution : Vérifier .env contient OPENAI_API_KEY et ANTHROPIC_API_KEY
```

---

### Problème 4 : Frontend affiche "Failed to fetch API"

**Symptômes :**
Frontend charge mais ne peut pas appeler l'API.

**Solutions :**

1. Vérifier `FRONTEND_API_BASE_URL` dans `.env` pointe vers l'IP EC2
2. Vérifier Security Group autorise port 8000
3. Vérifier backend est bien accessible

```bash
# Tester depuis l'instance EC2
curl http://localhost:8000/status

# Tester depuis votre PC
curl http://18.203.45.67:8000/status
```

---

### Problème 5 : Espace disque plein

**Symptômes :**
```
No space left on device
```

**Solutions :**

```bash
# Vérifier espace
df -h

# Nettoyer images Docker inutilisées
docker system prune -a --volumes

# Augmenter volume EBS si nécessaire (via AWS Console)
```

---

## 💰 Coûts Estimés

### Coûts AWS Mensuels (eu-west-1)

#### Compute (EC2)

| Instance | Type | vCPU | RAM | Prix/mois* | Usage |
|----------|------|------|-----|------------|-------|
| Dev/Test | t3.xlarge | 4 | 16 GB | **$60** | 10-50 docs/jour |
| Production | t3.2xlarge | 8 | 32 GB | **$120** | 50-200 docs/jour |
| Production+ | m5.2xlarge | 8 | 32 GB | **$140** | 200-500 docs/jour |

*Prix on-demand, non-stop (730h/mois). Économies possibles avec Reserved Instances (-30-40%)

#### Stockage

- **EBS gp3** : $0.08/GB/mois
  - 30 GB root : ~$2.40/mois
  - 100 GB data : ~$8/mois

- **ECR Storage** : $0.10/GB/mois
  - ~15 GB images : ~$1.50/mois

#### Réseau

- **Data Transfer OUT** : $0.09/GB (premiers 10 TB)
  - 100 GB/mois : ~$9/mois
  - 500 GB/mois : ~$45/mois

#### Elastic IP

- Gratuit si associée à instance active
- $0.005/heure si non-associée (~$3.60/mois)

### Exemple Configurations

#### Configuration Test/Dev ($75-85/mois)
```
- Instance : t3.xlarge           $60
- EBS : 30 GB root + 100 GB data $10
- ECR Storage : 15 GB            $1.50
- Data Transfer : 100 GB/mois    $9
- Elastic IP                     $0
--------------------------------------------
TOTAL                            ~$80/mois
```

#### Configuration Production ($180-200/mois)
```
- Instance : t3.2xlarge          $120
- EBS : 30 GB root + 200 GB data $18
- ECR Storage : 15 GB            $1.50
- Data Transfer : 500 GB/mois    $45
- Elastic IP                     $0
- CloudWatch monitoring          $5
--------------------------------------------
TOTAL                            ~$190/mois
```

### Coûts LLM (Variables)

**⚠️ ATTENTION :** Les coûts LLM représentent **80-90%** des coûts opérationnels totaux.

Voir `doc/etudes/ARCHITECTURE_AGENTIQUE_OSMOSE.md` pour :
- Modèle de coûts détaillé par scénario
- Optimisations routing LLM
- Budget Governor configuration

**Estimation rapide :**
- 100 docs/jour, Scénario A (mostly SMALL) : ~$25/mois ($0.25/doc)
- 100 docs/jour, Scénario B (complexes) : ~$77/mois ($0.77/doc)
- 100 docs/jour, Scénario C (PPT-heavy) : ~$197/mois ($1.97/doc)

---

## 📚 Références

### Documentation Interne

- `README.md` : Overview projet
- `CLAUDE.md` : Configuration Claude Code
- `doc/OSMOSE_PROJECT_OVERVIEW.md` : Vue d'ensemble OSMOSE
- `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md` : Spécifications techniques
- `doc/etudes/ARCHITECTURE_AGENTIQUE_OSMOSE.md` : Architecture agentique (coûts)

### Documentation AWS

- [AWS ECR Documentation](https://docs.aws.amazon.com/ecr/)
- [AWS EC2 Pricing](https://aws.amazon.com/ec2/pricing/)
- [Docker Compose on EC2](https://docs.docker.com/cloud/ecs-integration/)

### Scripts Disponibles

- `scripts/build-and-push-ecr.ps1` : Build local + push ECR
- `scripts/deploy-ec2.ps1` : Déploiement sur EC2
- `buildspec.yml` : Configuration CodeBuild (CI/CD)
- `docker-compose.ecr.yml` : Stack production EC2

---

## ✅ Checklist de Déploiement

### Avant le Déploiement

- [ ] Compte AWS configuré avec credentials valides
- [ ] Docker Desktop installé et fonctionnel
- [ ] PowerShell disponible
- [ ] Clés API OpenAI et Anthropic obtenues
- [ ] Fichier `.env.production` créé et configuré
- [ ] Repository cloné localement

### Création Infrastructure AWS

- [ ] Repositories ECR créés (automatique via script)
- [ ] Instance EC2 créée (t3.xlarge minimum)
- [ ] Security Group configuré avec ports nécessaires
- [ ] Elastic IP associée (recommandé)
- [ ] Clé SSH (.pem) téléchargée et sauvegardée

### Build et Déploiement

- [ ] Images buildées et pushées vers ECR (`build-and-push-ecr.ps1`)
- [ ] `.env.production` mis à jour avec IP EC2
- [ ] Déploiement exécuté (`deploy-ec2.ps1`)
- [ ] Tous les services healthy (healthcheck OK)

### Vérification Post-Déploiement

- [ ] API Backend accessible : http://<IP>:8000/docs
- [ ] Frontend accessible : http://<IP>:3000
- [ ] Neo4j Browser accessible : http://<IP>:7474
- [ ] Qdrant UI accessible : http://<IP>:6333/dashboard
- [ ] Test upload d'un document via l'interface
- [ ] Test recherche via le chat

---

**Documentation maintenue par :** Équipe Infrastructure OSMOSE
**Dernière mise à jour :** 2025-10-13
**Version :** 1.0

Pour toute question ou problème, consulter le troubleshooting ci-dessus ou ouvrir une issue GitHub.
