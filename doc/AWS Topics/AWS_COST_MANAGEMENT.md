# Gestion des Coûts AWS - KnowWhere OSMOSE

**Guide complet pour optimiser et contrôler vos coûts AWS**

Version: 1.0
Date: 2025-10-13

---

## 💰 Vue d'Ensemble des Coûts

### Coûts Mensuels par Composant

| Composant | État Running | État Stopped | État Terminated |
|-----------|--------------|--------------|-----------------|
| **EC2 Compute** | $60-120/mois | **$0** ✅ | **$0** ✅ |
| **EBS Storage** | $10/mois | $10/mois | **$0** ✅ |
| **ECR Storage** | $1.50/mois | $1.50/mois | $1.50/mois* |
| **Data Transfer** | $9-45/mois | **$0** ✅ | **$0** ✅ |
| **TOTAL AWS** | **$80.50-176.50** | **$11.50** | **$1.50*** |

*\*Sauf si images ECR supprimées*

### Coûts API LLM (Variables)

| Usage | OpenAI + Anthropic | Scénario |
|-------|-------------------|----------|
| 100 docs/jour simples | ~$25/mois | PDF textuels |
| 100 docs/jour complexes | ~$77/mois | PDF avec tableaux |
| 100 docs/jour graphiques | ~$197/mois | PPTX avec charts |

**⚠️ Les coûts LLM représentent 80-90% des coûts totaux d'exploitation !**

---

## 🎯 Stratégies d'Optimisation des Coûts

### Stratégie 1 : Stop/Start (Tests & Dev)

**Cas d'usage :** Vous testez occasionnellement (2-3h/jour)

**Workflow :**
```powershell
# Démarrer pour travailler
.\scripts\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Travailler pendant 2-3 heures
# Tester, développer, etc.

# Arrêter à la fin de la journée
.\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"
```

**Économies :**
- Instance running 3h/jour (90h/mois) au lieu de 730h/mois
- Coût compute : $60 × (90/730) = **~$7.40/mois** au lieu de $60
- **Économie : $52.60/mois (87%)**

**Coût total mensuel avec cette stratégie :**
- Compute : $7.40
- Storage EBS : $10
- ECR : $1.50
- **TOTAL : ~$19/mois** (vs $80 running 24/7)

---

### Stratégie 2 : Terminate/Recreate (Très Occasionnel)

**Cas d'usage :** Vous testez 1-2 fois par mois seulement

**Workflow :**
```powershell
# Quand vous avez besoin de tester
# 1. Créer instance EC2 via console (5 min)
# 2. Déployer
.\scripts\deploy-ec2.ps1 -InstanceIP "nouvelle-ip" -KeyPath "key.pem"

# 3. Tester pendant quelques heures

# 4. Sauvegarder les données importantes (backup Neo4j, etc.)

# 5. Détruire tout
.\scripts\aws-terminate-all.ps1 -InstanceName "knowbase-osmose-prod" -DeleteECRImages
```

**Économies :**
- Coût seulement pendant les heures d'utilisation
- Exemple : 2 tests de 3h/mois = 6h/mois
- Coût compute : $60 × (6/730) = **~$0.50/mois**
- Storage : $0 (rien n'existe entre les tests)
- **TOTAL : ~$0.50/mois** (si vous rebuilder les images à chaque fois)

**⚠️ Inconvénients :**
- Perte des données entre les tests
- Temps de setup à chaque fois (15-20 min)

---

### Stratégie 3 : Reserved Instances (Production 24/7)

**Cas d'usage :** Vous utilisez en production continue

**Économies avec Reserved Instances (engagement 1 an) :**
- t3.xlarge on-demand : $60/mois
- t3.xlarge reserved 1 an : **$40/mois** (-33%)
- t3.xlarge reserved 3 ans : **$25/mois** (-58%)

**Comment acheter :**
```powershell
# Via AWS Console
# EC2 > Reserved Instances > Purchase Reserved Instances
# Sélectionner: t3.xlarge, eu-west-1, 1 year, All Upfront
```

---

## 📊 Calcul de Coûts selon Usage

### Scénario A : Tests Occasionnels (Stop/Start)

```
Usage : 3h/jour, 5 jours/semaine = 60h/mois

EC2 Compute (t3.xlarge) : $60 × (60/730) = $4.93
EBS Storage (130 GB)    : $10.40
ECR Storage (15 GB)     : $1.50
Data Transfer (minimal) : $2.00

TOTAL Infrastructure : ~$19/mois

API LLM (10 docs/jour) :
- OpenAI/Anthropic     : ~$7.50/mois

TOTAL MENSUEL : ~$27/mois
```

---

### Scénario B : Dev/Test Quotidien (Running 24/7)

```
Usage : 24/7 pour développement

EC2 Compute (t3.xlarge) : $60
EBS Storage (130 GB)    : $10.40
ECR Storage (15 GB)     : $1.50
Data Transfer (100 GB)  : $9.00

TOTAL Infrastructure : ~$81/mois

API LLM (50 docs/jour) :
- OpenAI/Anthropic     : ~$38/mois

TOTAL MENSUEL : ~$119/mois
```

---

### Scénario C : Production (Running 24/7 + Volume)

```
Usage : 24/7 production avec clients

EC2 Compute (t3.2xlarge Reserved 1yr) : $80 (vs $120 on-demand)
EBS Storage (300 GB)                  : $24
ECR Storage (15 GB)                   : $1.50
Data Transfer (500 GB)                : $45
CloudWatch Monitoring                 : $5

TOTAL Infrastructure : ~$155/mois

API LLM (200 docs/jour complexes) :
- OpenAI/Anthropic                   : ~$154/mois

TOTAL MENSUEL : ~$309/mois
```

---

## 🛠️ Scripts de Gestion Lifecycle

### Script 1 : Arrêter l'Instance (Stop)

**Utilisation :**
```powershell
# Par nom
.\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Par ID
.\scripts\aws-stop-instance.ps1 -InstanceId "i-0123456789abcdef"
```

**Ce qui se passe :**
- ✅ Arrête gracieusement les conteneurs Docker (optionnel)
- ✅ Arrête l'instance EC2
- ✅ Conserve les volumes EBS (données intactes)
- ⚠️ L'IP publique est libérée (sauf si Elastic IP)

**Résultat :**
- État : **stopped**
- Coût compute : **$0/mois** ✅
- Coût storage : **$10/mois** (EBS conservé)
- Données : **CONSERVÉES**

---

### Script 2 : Démarrer l'Instance (Start)

**Utilisation :**
```powershell
.\scripts\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"
```

**Ce qui se passe :**
- ✅ Démarre l'instance EC2
- ✅ Nouvelle IP publique assignée (généralement)
- ✅ Conteneurs Docker redémarrent automatiquement
- ⚠️ Vous devez redéployer si l'IP a changé

**Résultat :**
- État : **running**
- Coût compute : **$60-120/mois**
- Nouvelle IP : **Oui** (sauf Elastic IP)

**Si l'IP a changé :**
```powershell
# Mettre à jour le .env avec la nouvelle IP
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "nouvelle-ip" `
  -KeyPath "key.pem" `
  -SkipSetup  # Ne réinstalle pas Docker/etc.
```

---

### Script 3 : Détruire Tout (Terminate)

**Utilisation :**
```powershell
# Instance seulement
.\scripts\aws-terminate-all.ps1 -InstanceName "knowbase-osmose-prod"

# Instance + ECR images
.\scripts\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages

# Instance + ECR + Security Group
.\scripts\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages `
  -DeleteSecurityGroup

# Mode force (sans confirmations) - DANGER !
.\scripts\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -Force
```

**⚠️ ATTENTION : Confirmations requises**

Le script demande deux confirmations :
1. Tapez `DELETE` (en majuscules)
2. Tapez `YES` pour confirmer

**Ce qui se passe :**
- 🔴 Termine l'instance EC2 (DÉFINITIF)
- 🔴 Supprime les volumes EBS automatiquement
- 🔴 Toutes les données sont PERDUES
- 🔴 Supprime les images ECR si `-DeleteECRImages`
- 🔴 Supprime le Security Group si `-DeleteSecurityGroup`

**Résultat :**
- État : **terminated**
- Coût compute : **$0/mois** ✅
- Coût storage : **$0/mois** ✅
- Coût ECR : **$0/mois** si `-DeleteECRImages` ✅
- Données : **PERDUES DÉFINITIVEMENT** ❌

---

## 📅 Workflows Recommandés par Cas d'Usage

### Cas 1 : Tests Ponctuels (1-2h par jour)

**Routine quotidienne :**

```powershell
# Matin : Démarrer
.\scripts\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"
# Attendre 3-4 minutes que les conteneurs démarrent

# Journée : Travailler
# Accéder via http://<nouvelle-ip>:3000

# Soir : Arrêter
.\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"
```

**Coût mensuel estimé : ~$19/mois**

---

### Cas 2 : Tests Hebdomadaires (1 jour/semaine)

**Routine hebdomadaire :**

```powershell
# Lundi matin : Démarrer
.\scripts\aws-start-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Lundi toute la journée : Travailler

# Lundi soir : Arrêter
.\scripts\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"

# Mardi-Dimanche : Instance stopped, coûte seulement storage
```

**Coût mensuel estimé : ~$13/mois**

---

### Cas 3 : Tests Mensuels (Très occasionnel)

**Routine mensuelle :**

```powershell
# Début du mois : Créer + Déployer
# 1. Créer instance EC2 via console
# 2. Déployer
.\scripts\deploy-ec2.ps1 -InstanceIP "ip" -KeyPath "key.pem"

# Milieu du mois : Tester quelques heures

# Fin du mois : Détruire tout
.\scripts\aws-terminate-all.ps1 `
  -InstanceName "knowbase-osmose-prod" `
  -DeleteECRImages
```

**Coût mensuel estimé : ~$2-5/mois** (seulement les heures d'utilisation)

---

### Cas 4 : Production Continue (24/7)

**Setup initial :**

```powershell
# 1. Acheter Reserved Instance (économie -33%)
# Via AWS Console : EC2 > Reserved Instances

# 2. Associer Elastic IP (IP fixe)
aws ec2 allocate-address --region eu-west-1
aws ec2 associate-address --instance-id i-xxx --allocation-id eipalloc-xxx

# 3. Setup monitoring
# Via AWS Console : CloudWatch > Alarms
# - CPU > 80% pendant 5 min → Notification
# - Disk > 90% → Notification

# 4. Setup backup automatique
# Via AWS Console : EC2 > Elastic Block Store > Lifecycle Manager
# - Snapshot daily à 2h du matin
# - Rétention 7 jours
```

**Coût mensuel estimé : ~$270-310/mois** (infrastructure + API selon volume)

---

## 🎓 Bonnes Pratiques

### 1. Toujours Utiliser Elastic IP en Production

```powershell
# Allouer Elastic IP
aws ec2 allocate-address --region eu-west-1

# Associer à l'instance
aws ec2 associate-address `
  --instance-id i-0123456789abcdef `
  --allocation-id eipalloc-xxxxxxxxx
```

**Avantages :**
- IP fixe (ne change pas au stop/start)
- Pas besoin de redéployer après chaque start
- Gratuit tant que l'IP est associée à une instance active

---

### 2. Backup Avant Stop/Terminate

```powershell
# Se connecter à l'instance
ssh -i "key.pem" ubuntu@<ip>

# Backup Neo4j
cd /home/ubuntu/knowbase
docker exec knowbase-neo4j neo4j-admin dump \
  --database=neo4j --to=/data/backups/neo4j-$(date +%Y%m%d).dump

# Télécharger backup en local
scp -i "key.pem" ubuntu@<ip>:/data/backups/*.dump ./backups/

# Maintenant vous pouvez arrêter/terminer sans risque
```

---

### 3. Monitoring des Coûts AWS

**Setup Cost Anomaly Detection :**

1. AWS Console > Billing > Cost Anomaly Detection
2. Créer un monitor pour EC2
3. Alertes si coût > 150% de la normale

**Setup Budget Alerts :**

1. AWS Console > Billing > Budgets
2. Créer budget : $100/mois
3. Alertes à 80% ($80) et 100% ($100)

---

### 4. Tagging des Ressources

Toujours tagger vos ressources pour tracking des coûts :

```powershell
# Tagger l'instance
aws ec2 create-tags `
  --resources i-0123456789abcdef `
  --tags Key=Project,Value=KnowWhere Key=Environment,Value=Production Key=Owner,Value=VotreNom
```

**Puis voir les coûts par tag :**
AWS Console > Cost Explorer > Group by > Tag > Project

---

## 📋 Checklist Gestion des Coûts

### Hebdomadaire
- [ ] Vérifier les alertes CloudWatch
- [ ] Vérifier l'utilisation API OpenAI/Anthropic
- [ ] Arrêter l'instance si pas utilisée pendant le weekend

### Mensuelle
- [ ] Revoir AWS Cost Explorer
- [ ] Vérifier si Reserved Instances seraient rentables
- [ ] Nettoyer les snapshots EBS anciens (>30 jours)
- [ ] Nettoyer les images ECR non utilisées

### Avant Longue Période d'Inactivité (vacances, etc.)
- [ ] Backup toutes les données
- [ ] Arrêter l'instance (`aws-stop-instance.ps1`)
- [ ] Ou terminer si pas besoin des données (`aws-terminate-all.ps1`)

---

## 💡 Astuces Supplémentaires

### Astuce 1 : Spot Instances pour Dev/Test

Pour économiser jusqu'à 70% sur les instances de test :

```powershell
# Créer instance Spot via CLI (non couvert par mes scripts actuels)
aws ec2 request-spot-instances `
  --spot-price "0.02" `
  --instance-count 1 `
  --type "one-time" `
  --launch-specification file://spot-spec.json
```

**⚠️ Limitation :** Peut être interrompu par AWS (si prix monte)

---

### Astuce 2 : Compression des Images ECR

Réduire la taille des images Docker = économies storage ECR :

```dockerfile
# Dans vos Dockerfiles, utiliser multi-stage builds
FROM node:18 AS builder
# ... build ...

FROM node:18-alpine  # Image finale plus petite
COPY --from=builder /app/dist /app/dist
```

---

### Astuce 3 : Limitation Budget LLM

Dans votre `.env.production`, ajoutez :

```env
# Limiter le coût LLM par document
MAX_COST_PER_DOCUMENT=0.50  # $0.50 max par document

# Désactiver les appels LLM coûteux en dev/test
DISABLE_VISION_MODELS=true  # Pas de gpt-4o-vision
USE_SMALL_MODELS_ONLY=true  # Seulement gpt-4o-mini
```

---

## 🆘 FAQ Coûts

### Q: Pourquoi l'IP change à chaque start ?

**R:** Les IP publiques AWS sont dynamiques par défaut. Solution : Associer une **Elastic IP** (gratuit).

### Q: Comment éviter les coûts de Data Transfer ?

**R:**
- Limiter les téléchargements depuis EC2
- Les premiers 100 GB/mois sont gratuits
- Data Transfer IN est toujours gratuit

### Q: Les images ECR coûtent combien exactement ?

**R:** $0.10/GB/mois. Vos 8 images totalisent ~15 GB = $1.50/mois.

### Q: Peut-on tester gratuitement ?

**R:** AWS Free Tier offre 750h/mois de t2.micro (trop petit pour KnowWhere). Utilisez stratégie Stop/Start pour minimiser.

---

## 📚 Références

- **AWS Pricing Calculator** : https://calculator.aws/
- **EC2 Pricing** : https://aws.amazon.com/ec2/pricing/
- **ECR Pricing** : https://aws.amazon.com/ecr/pricing/
- **Scripts de gestion** :
  - `scripts/aws-stop-instance.ps1`
  - `scripts/aws-start-instance.ps1`
  - `scripts/aws-terminate-all.ps1`

---

**Dernière mise à jour :** 2025-10-13
**Version :** 1.0
