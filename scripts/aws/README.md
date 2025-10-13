# Scripts AWS - KnowWhere OSMOSE

**Scripts PowerShell pour gérer l'infrastructure AWS**

---

## 📋 Liste des Scripts

### 🏗️ Déploiement

#### **`build-and-push-ecr.ps1`**
Build les images Docker localement et les push vers AWS ECR.

**Usage :**
```powershell
.\scripts\aws\build-and-push-ecr.ps1

# Options
.\scripts\aws\build-and-push-ecr.ps1 -NoCache              # Build from scratch
.\scripts\aws\build-and-push-ecr.ps1 -SkipThirdParty       # Seulement images custom
.\scripts\aws\build-and-push-ecr.ps1 -Tag "v1.0.0"         # Tag spécifique
.\scripts\aws\build-and-push-ecr.ps1 -Region "us-east-1"   # Autre région
```

**Durée :** 15-30 minutes (première fois)

---

#### **`deploy-ec2.ps1`**
Déploie KnowWhere OSMOSE sur une instance EC2 via SSH.

**Usage :**
```powershell
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem"

# Options
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem" `
  -SkipSetup                    # Sans réinstaller Docker/AWS CLI

.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem" `
  -Username "ec2-user"          # Pour Amazon Linux
```

**Durée :** 10-20 minutes (setup initial) ou 3-5 minutes (update)

**Important :** Le script met à jour automatiquement l'IP EC2 dans le `.env`

---

### 💰 Gestion Lifecycle (Économies)

#### **`aws-stop-instance.ps1`**
Arrête l'instance EC2 pour économiser les coûts compute.

**Usage :**
```powershell
# Par nom
.\scripts\aws\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Par ID
.\scripts\aws\aws-stop-instance.ps1 -InstanceId "i-0123456789abcdef"
```

**Résultat :**
- ✅ Instance stopped (coût compute = $0/mois)
- ✅ Données CONSERVÉES
- ✅ Coût storage = $10/mois
- ⚠️ IP publique libérée

**Économies :** ~$60-120/mois

---

#### **`aws-start-instance.ps1`**
Redémarre une instance EC2 arrêtée.

**Usage :**
```powershell
.\scripts\aws\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"
```

**Résultat :**
- ✅ Instance running
- ✅ Conteneurs redémarrent automatiquement
- ✅ Données intactes
- ⚠️ Nouvelle IP publique (généralement)

**Note :** Si l'IP a changé, redéployer avec `-SkipSetup`

---

#### **`aws-terminate-all.ps1`**
🔴 DÉTRUIT COMPLÈTEMENT l'infrastructure AWS (DANGEREUX)

**Usage :**
```powershell
# Instance seulement
.\scripts\aws\aws-terminate-all.ps1 -InstanceName "knowbase-osmose-prod"

# Instance + Images ECR
.\scripts\aws\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages

# Instance + ECR + Security Group
.\scripts\aws\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages `
  -DeleteSecurityGroup
```

**⚠️ ATTENTION :**
- 🔴 Instance terminée DÉFINITIVEMENT
- 🔴 Toutes les données PERDUES
- 🔴 Confirmations requises (tapez "DELETE" puis "YES")

**Économies :** 100% des coûts AWS (sauf ECR si non supprimé)

---

## 🎯 Workflows Typiques

### Workflow 1 : Déploiement Initial

```powershell
# 1. Préparer .env.production avec vos clés API
Copy-Item .env.ecr.example .env.production
notepad .env.production

# 2. Build et push images vers ECR
.\scripts\aws\build-and-push-ecr.ps1

# 3. Créer instance EC2 via AWS Console (t3.xlarge)
# Récupérer IP publique : 18.203.45.67

# 4. Déployer
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\Users\VotreNom\.ssh\key.pem"

# 5. Accéder à http://18.203.45.67:3000
```

---

### Workflow 2 : Tests Quotidiens (Économie $60/mois)

```powershell
# Matin : Démarrer
.\scripts\aws\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"
# Attendre 3-4 minutes

# Journée : Tester/développer

# Soir : Arrêter
.\scripts\aws\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Coût mensuel : ~$19/mois au lieu de $80
```

---

### Workflow 3 : Update du Code

```powershell
# 1. Modifier le code localement
git add .
git commit -m "feat: nouvelle fonctionnalité"

# 2. Rebuild images (sans third-party)
.\scripts\aws\build-and-push-ecr.ps1 -SkipThirdParty

# 3. Redéployer (sans setup)
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\path\to\key.pem" `
  -SkipSetup

# Durée : 10-15 minutes
```

---

### Workflow 4 : Fin de Projet (Tout Supprimer)

```powershell
# Backup des données importantes (si nécessaire)
ssh -i "key.pem" ubuntu@<ip>
cd /home/ubuntu/knowbase
docker exec knowbase-neo4j neo4j-admin dump --database=neo4j --to=/data/backup.dump
# Télécharger backup en local...

# Détruire tout
.\scripts\aws\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages

# Coût après destruction : $0/mois
```

---

## 📊 Comparaison des Coûts

| Action | Coût/mois | Données | Quand utiliser |
|--------|-----------|---------|----------------|
| **Running 24/7** | $80-176 | Conservées | Production continue |
| **Stop/Start quotidien** | $19 | Conservées | Tests réguliers |
| **Terminate** | $0 | Perdues | Fin de projet |

---

## 🔧 Prérequis

### Outils Nécessaires (Windows)

- [ ] **Docker Desktop** (https://www.docker.com/products/docker-desktop/)
- [ ] **AWS CLI** (https://aws.amazon.com/cli/)
- [ ] **PowerShell 5.1+** (inclus dans Windows)
- [ ] **OpenSSH Client** (Windows 10/11 : Settings > Apps > Optional Features)

### Configuration AWS

- [ ] Compte AWS avec credentials configurées
- [ ] `aws configure` exécuté
- [ ] Permissions IAM : EC2, ECR

**Test :**
```powershell
aws sts get-caller-identity
docker --version
```

---

## 📚 Documentation Complète

- **Quick Start** : `doc/QUICK_START_DEPLOY.md`
- **Guide complet** : `doc/AWS_DEPLOYMENT_GUIDE.md`
- **Gestion coûts** : `doc/AWS_COST_MANAGEMENT.md`

---

## 🆘 Aide Rapide

### Problème : "Connection timed out" (SSH)

**Solution :**
1. Vérifier Security Group autorise port 22 depuis votre IP
2. Vérifier instance est "running"
3. Vérifier clé SSH correcte

### Problème : "Access Denied" (ECR)

**Solution :**
```powershell
# Re-login ECR
aws ecr get-login-password --region eu-west-1 | `
  docker login --username AWS --password-stdin `
  715927975014.dkr.ecr.eu-west-1.amazonaws.com
```

### Problème : IP a changé après Start

**Solution :**
```powershell
# Redéployer avec la nouvelle IP
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "nouvelle-ip" `
  -KeyPath "key.pem" `
  -SkipSetup
```

---

## 🔗 Liens Utiles

- **AWS Console EC2** : https://console.aws.amazon.com/ec2/
- **AWS Console ECR** : https://console.aws.amazon.com/ecr/
- **AWS Pricing Calculator** : https://calculator.aws/

---

**Dernière mise à jour :** 2025-10-13
**Version :** 1.0
