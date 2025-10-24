# CloudFormation - Déploiement KnowWhere OSMOSE sur AWS

Infrastructure complète pour déployer KnowWhere OSMOSE sur EC2 avec auto-destruction programmable.

## 🚀 Déploiement Rapide

```powershell
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "knowbase-test" `
    -KeyPairName "votre-cle-ec2" `
    -KeyPath "C:\path\to\votre-cle.pem"
```

**Par défaut** : Le stack sera **automatiquement détruit après 4 heures** pour éviter les coûts imprévus.

## ⏰ Auto-Destruction Programmable

### Pourquoi ?

Pour éviter des factures AWS imprévues si vous oubliez de détruire votre stack de test. Une instance `t3.2xlarge` coûte **~$0.33/heure** (~$240/mois si elle tourne 24/7).

### Comment ça fonctionne ?

1. **Lambda Function** : Une fonction Lambda est créée avec le stack
2. **EventBridge Timer** : Un timer déclenche la Lambda après X heures
3. **Auto-Deletion** : La Lambda supprime automatiquement le stack CloudFormation

### Configuration

**Option 1 : Auto-destruction par défaut (4h)**
```powershell
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "test" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem"
```
→ Stack détruit automatiquement dans 4 heures

**Option 2 : Personnaliser la durée**
```powershell
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "test" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem" `
    -AutoDestroyAfterHours 8
```
→ Stack détruit automatiquement dans 8 heures

**Option 3 : Désactiver l'auto-destruction**
```powershell
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "prod" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem" `
    -AutoDestroyAfterHours 0
```
→ Vous devrez détruire le stack **manuellement**

### Vérifier le statut

Après le déploiement, l'output affichera :
```
⏰ AUTO-DESTRUCTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ ACTIVÉE - Stack sera automatiquement détruit dans 4h
```

Vous pouvez aussi vérifier dans la console AWS :
- **Lambda** : `<StackName>-auto-destroy`
- **EventBridge** : `<StackName>-auto-destroy-timer`

### Destruction manuelle (annuler le timer)

Si vous voulez détruire avant le timer :
```powershell
.\scripts\aws\destroy-cloudformation.ps1 -StackName "votre-stack"
```

## 📋 Ressources Créées

### Infrastructure principale
- ✅ **EC2 Instance** (t3.2xlarge par défaut)
- ✅ **Elastic IP** (IP fixe)
- ✅ **Security Group** (ports 22, 3000, 8000, 7474, 6333, 8501)
- ✅ **IAM Role** (pour ECR pull)
- ✅ **2 Volumes EBS** (root 30GB + data 100GB)

### Auto-destruction (si activée)
- ⏰ **Lambda Function** (auto-destroy)
- ⏰ **IAM Role Lambda** (permissions CloudFormation)
- ⏰ **EventBridge Rule** (timer)

## 💰 Coûts Estimés

### Instance t3.2xlarge (8 vCPU, 32 GB RAM)
- **24/7 pendant 1 mois** : ~$240
- **8 heures** : ~$2.64
- **4 heures** : ~$1.32
- **1 heure** : ~$0.33

### Coûts additionnels
- Storage 130GB (root + data) : ~$10/mois (~$0.01/heure)
- Elastic IP associé : $0 (gratuit si attaché)
- **Lambda + EventBridge** : $0 (sous free tier)

### Recommandations
- ✅ Tests courts (2-4h) : **Utiliser l'auto-destruction**
- ✅ Tests longs (1-2 jours) : Augmenter le timer (12-24h)
- ⚠️ Déploiement durable : Désactiver l'auto-destruction (0)

## 🔧 Paramètres Disponibles

| Paramètre | Default | Description |
|-----------|---------|-------------|
| `StackName` | *Requis* | Nom du stack CloudFormation |
| `KeyPairName` | *Requis* | Nom de la clé SSH EC2 |
| `KeyPath` | *Requis* | Chemin vers fichier .pem |
| `InstanceType` | `t3.2xlarge` | Type d'instance EC2 |
| `Region` | `eu-west-1` | Région AWS |
| `AutoDestroyAfterHours` | `4` | Auto-destruction (0 = désactivé) |
| `RootVolumeSize` | `30` | Taille volume root (GB) |
| `DataVolumeSize` | `100` | Taille volume data (GB) |

## 🛡️ Sécurité

### Permissions IAM requises

L'utilisateur AWS doit avoir :
- `cloudformation:*` (créer/supprimer stacks)
- `ec2:*` (créer instances, security groups, EIPs)
- `iam:*` (créer roles pour EC2 et Lambda)
- `lambda:*` (créer fonction auto-destroy)
- `events:*` (créer timer EventBridge)

Utilisez le script de setup :
```powershell
.\scripts\aws\setup-iam-permissions.ps1
```

### Security Group

Ports ouverts :
- **22 (SSH)** : Limité à votre IP
- **3000 (Frontend)** : Ouvert à tous
- **8000 (API)** : Ouvert à tous
- **7474 (Neo4j)** : Limité à votre IP
- **6333 (Qdrant)** : Limité à votre IP
- **8501 (Streamlit)** : Limité à votre IP

## 📝 Notes

### Lambda Auto-Destroy

La Lambda est **non-récurrente** : elle se déclenche **une seule fois** après X heures.

Si vous voulez prolonger :
1. Détruisez le stack actuel
2. Relancez avec un timer plus long

### Cas d'usage recommandés

**Tests de performance** (recommandé : 4h)
```powershell
-AutoDestroyAfterHours 4
```

**Session de développement** (recommandé : 8h)
```powershell
-AutoDestroyAfterHours 8
```

**Démo client** (recommandé : 12h)
```powershell
-AutoDestroyAfterHours 12
```

**Environnement staging** (recommandé : désactivé)
```powershell
-AutoDestroyAfterHours 0
```

## 🔍 Dépannage

### "Lambda ne se déclenche pas"

Vérifiez les logs CloudWatch :
```bash
aws logs tail /aws/lambda/<StackName>-auto-destroy --follow
```

### "Stack toujours actif après X heures"

1. Vérifiez EventBridge Rule :
```bash
aws events list-rules --name-prefix <StackName>
```

2. Vérifiez les invocations Lambda :
```bash
aws lambda get-function --function-name <StackName>-auto-destroy
```

### "AccessDenied lors de l'auto-destruction"

Le rôle Lambda n'a pas les permissions CloudFormation. Cela ne devrait pas arriver si vous utilisez le template fourni.

## 📚 Fichiers

- `knowbase-stack.yaml` : Template CloudFormation complet
- `iam-policy-cloudformation.json` : Policy IAM pour l'utilisateur
- `../scripts/aws/deploy-cloudformation.ps1` : Script de déploiement
- `../scripts/aws/destroy-cloudformation.ps1` : Script de destruction manuelle
- `../scripts/aws/setup-iam-permissions.ps1` : Setup permissions IAM

## ⚠️ Avertissement

**L'auto-destruction est une sécurité, pas une garantie absolue.**

Vérifiez toujours dans la console AWS que vos ressources ont bien été supprimées après vos tests.

---

**Dernière mise à jour** : 2025-10-23
**Version template** : 2.0 (avec auto-destruction)
