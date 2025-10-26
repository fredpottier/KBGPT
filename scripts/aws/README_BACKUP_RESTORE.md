# Scripts Backup & Restore KnowBase

Documentation pour la sauvegarde et la restauration complète de KnowBase sur AWS.

## 📦 Contenu des Backups

Les backups incluent **TOUTES** les données du système :

### 🔹 Qdrant (Base vectorielle)
- Collections : `knowbase` et `rfp_qa`
- Snapshots via API + volume complet
- Format : `qdrant_snapshots/` + `qdrant_volume.tar.gz`

### 🔹 Redis (Cache & Queue)
- Dump RDB complet (BGSAVE)
- Inclut les jobs en queue et le cache
- Format : `redis_dump.rdb`

### 🔹 Neo4j (Knowledge Graph)
- Volumes data et logs complets
- Export cypher optionnel (pour inspection)
- Format : `neo4j_data.tar.gz` + `neo4j_logs.tar.gz` + `neo4j_export.cypher`

### 🔹 Data (Documents & Modèles)
- Volume `app_data` : documents uploadés, docs traités, thumbnails
- Volume `app_logs` : logs fichiers (ingest_debug.log, etc.)
- Volume `app_models` : modèles ML (HuggingFace, embeddings)
- Format : `app_data.tar.gz` + `app_logs.tar.gz` + `app_models.tar.gz`

### 📋 Manifeste
- Métadonnées du backup (timestamp, source EC2, tailles)
- Format : `backup_manifest.json` + `backup_manifest.txt`

---

## 🔄 Backup - Créer une sauvegarde

### Script : `backup-to-s3.ps1`

Crée un backup horodaté complet et l'upload sur S3.

### Utilisation

```powershell
# Backup de base (bucket auto-créé)
.\backup-to-s3.ps1 -EC2Host 63.32.164.133

# Backup avec bucket personnalisé
.\backup-to-s3.ps1 -EC2Host 63.32.164.133 -S3BucketName "mon-bucket-backups"

# Backup avec clé SSH personnalisée
.\backup-to-s3.ps1 -EC2Host 63.32.164.133 -KeyPath "C:\keys\ma-cle.pem"
```

### Paramètres

| Paramètre | Obligatoire | Description |
|-----------|-------------|-------------|
| `-EC2Host` | ✅ | IP ou hostname de l'instance EC2 KnowBase |
| `-KeyPath` | ❌ | Chemin vers la clé SSH PEM (défaut: `.\Osmose_KeyPair.pem`) |
| `-S3BucketName` | ❌ | Nom du bucket S3 (défaut: `knowbase-backups-{AWS_ACCOUNT_ID}`) |

### Durée estimée
- **Backup complet** : 2-10 minutes selon la taille des données
- **Upload S3** : 1-5 minutes selon la connexion

### Bucket S3 par défaut

Si vous ne spécifiez pas de bucket, il sera créé automatiquement :
- **Nom** : `knowbase-backups-{AWS_ACCOUNT_ID}`
- **Région** : `eu-west-1`
- **Versioning** : Activé (recommandé pour backups)
- **Exemple** : `knowbase-backups-715927975014`

### Output

```
🔄 Backup KnowBase vers S3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 Bucket S3 auto: knowbase-backups-715927975014

🪣 Vérification du bucket S3...
   ✅ Bucket créé avec versioning activé

📁 Création du répertoire de backup sur EC2...
🔹 Backup Qdrant...
   ✅ Qdrant backupé
🔹 Backup Redis...
   ✅ Redis backupé
🔹 Backup Neo4j...
   ✅ Neo4j backupé
🔹 Backup dossier Data...
   ✅ Data backupé
📋 Création du manifeste...
   ✅ Manifeste créé
⬇️  Téléchargement du backup en local...
   ✅ Backup téléchargé: .\backups\20251026_143052
☁️  Upload vers S3...
   ✅ Upload S3 terminé
🧹 Nettoyage du backup temporaire sur EC2...
   ✅ Nettoyage terminé

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Backup terminé avec succès !

📦 Bucket S3    : knowbase-backups-715927975014
📂 Chemin S3    : s3://knowbase-backups-715927975014/backups/20251026_143052/
🕐 Timestamp    : 20251026_143052
💾 Local        : .\backups\20251026_143052

Pour restaurer ce backup :
.\restore-from-s3.ps1 -StackName 'Osmos' -BackupTimestamp '20251026_143052' -S3BucketName 'knowbase-backups-715927975014'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ⚡ Restore - Restaurer depuis S3

### Script : `restore-from-s3.ps1`

Restaure un backup sur une **nouvelle** instance EC2 déployée via CloudFormation.

### Utilisation

```powershell
# Restauration de base
.\restore-from-s3.ps1 `
    -StackName "Osmos" `
    -BackupTimestamp "20251026_143052" `
    -S3BucketName "knowbase-backups-715927975014"

# Restauration sans redémarrer les services (pour vérification)
.\restore-from-s3.ps1 `
    -StackName "Osmos" `
    -BackupTimestamp "20251026_143052" `
    -S3BucketName "knowbase-backups-715927975014" `
    -RestartServices $false

# Restauration avec clé SSH personnalisée
.\restore-from-s3.ps1 `
    -StackName "Osmos" `
    -BackupTimestamp "20251026_143052" `
    -S3BucketName "knowbase-backups-715927975014" `
    -KeyPath "C:\keys\ma-cle.pem"
```

### Paramètres

| Paramètre | Obligatoire | Description |
|-----------|-------------|-------------|
| `-StackName` | ✅ | Nom de la stack CloudFormation (ex: "Osmos") |
| `-BackupTimestamp` | ✅ | Timestamp du backup (format: yyyyMMdd_HHmmss) |
| `-S3BucketName` | ✅ | Nom du bucket S3 contenant les backups |
| `-KeyPath` | ❌ | Chemin vers la clé SSH PEM (défaut: `.\Osmose_KeyPair.pem`) |
| `-RestartServices` | ❌ | Redémarrer les services après restauration (défaut: `$true`) |

### Durée estimée
- **Download S3** : 1-5 minutes
- **Upload vers EC2** : 1-5 minutes
- **Restauration** : 2-5 minutes
- **Total** : ~5-15 minutes

### Workflow complet

1. **Récupère l'IP EC2** depuis le nom de la stack CloudFormation
2. **Télécharge le backup** depuis S3 vers votre PC local
3. **Upload vers l'EC2** via SCP
4. **Arrête les services** Docker (si `-RestartServices $true`)
5. **Restaure les volumes** Docker pour chaque service
6. **Redémarre les services** (si `-RestartServices $true`)
7. **Nettoie** les fichiers temporaires

### Output

```
🔄 Restauration KnowBase depuis S3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 Récupération de l'IP EC2 depuis la stack 'Osmos'...
   ✅ EC2 trouvé: 34.245.89.123 (Instance: i-0a1b2c3d4e5f67890)

🔍 Vérification du backup sur S3...
   ✅ Backup trouvé: s3://knowbase-backups-715927975014/backups/20251026_143052/

⬇️  Téléchargement du backup depuis S3...
   ✅ Backup téléchargé: 847.52 MB

📁 Préparation de l'EC2 pour la restauration...
⬆️  Upload du backup vers EC2...
   ✅ Upload terminé

⏸️  Arrêt des services pour restauration...
   ✅ Services arrêtés

🔹 Restauration Qdrant...
   ✅ Qdrant restauré
🔹 Restauration Redis...
   ✅ Redis restauré
🔹 Restauration Neo4j...
   ✅ Neo4j restauré
🔹 Restauration dossier Data...
   ✅ Data restauré

▶️  Redémarrage des services...
   ✅ Services redémarrés

⏳ Attente de la disponibilité des services (30s)...

🔍 Vérification des services...
Services en cours d'exécution :
NAME                   STATUS    PORTS
knowbase-neo4j        running   0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
knowbase-qdrant       running   0.0.0.0:6333-6334->6333-6334/tcp
knowbase-redis        running   0.0.0.0:6379->6379/tcp
knowbase-app          running   0.0.0.0:8000->8000/tcp
knowbase-worker       running

🧹 Nettoyage du backup temporaire sur EC2...
   ✅ Nettoyage terminé

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Restauration terminée avec succès !

🖥️  EC2 Instance : 34.245.89.123 (i-0a1b2c3d4e5f67890)
📦 Backup Source : s3://knowbase-backups-715927975014/backups/20251026_143052/
🕐 Timestamp     : 20251026_143052

🌐 Accès KnowBase :
   Frontend      : http://34.245.89.123:3000
   API           : http://34.245.89.123:8000/docs
   Grafana       : http://34.245.89.123:3001 (admin / Rn1lm@tr)
   Neo4j Browser : http://34.245.89.123:7474 (neo4j / graphiti_neo4j_pass)

⚠️  Les services ont été redémarrés. Vérifiez les logs :
   ssh -i .\Osmose_KeyPair.pem ubuntu@34.245.89.123 'docker-compose -f docker-compose.ecr.yml logs -f'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🔁 Workflow Complet : Backup → Nouveau Déploiement → Restore

### Scénario : Migration vers une nouvelle instance

```powershell
# 1. Backup de l'instance actuelle
.\backup-to-s3.ps1 -EC2Host 63.32.164.133
# Note le timestamp : 20251026_143052

# 2. Supprimer l'ancienne stack (optionnel)
.\delete-stack.ps1 -StackName "Osmos"

# 3. Déployer nouvelle stack CloudFormation
.\deploy-cloudformation.ps1 `
    -StackName "Osmos" `
    -KeyPairName "Osmose_KeyPair" `
    -KeyPath ".\Osmose_KeyPair.pem"

# 4. Restaurer le backup sur la nouvelle instance
.\restore-from-s3.ps1 `
    -StackName "Osmos" `
    -BackupTimestamp "20251026_143052" `
    -S3BucketName "knowbase-backups-715927975014"

# ✅ Système restauré et opérationnel !
```

---

## 📋 Gestion des Backups S3

### Lister les backups disponibles

```powershell
aws s3 ls s3://knowbase-backups-715927975014/backups/ --recursive --human-readable
```

### Supprimer un vieux backup

```powershell
# Supprimer un backup spécifique
aws s3 rm s3://knowbase-backups-715927975014/backups/20251020_120000/ --recursive

# Supprimer tous les backups avant une date
# (à faire manuellement ou via lifecycle policy)
```

### Activer lifecycle policy (rétention automatique)

```bash
# Garder les backups 30 jours puis archiver vers Glacier
aws s3api put-bucket-lifecycle-configuration \
    --bucket knowbase-backups-715927975014 \
    --lifecycle-configuration file://lifecycle-policy.json
```

**Fichier `lifecycle-policy.json`** :
```json
{
  "Rules": [
    {
      "Id": "ArchiveOldBackups",
      "Status": "Enabled",
      "Prefix": "backups/",
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "GLACIER"
        }
      ],
      "Expiration": {
        "Days": 90
      }
    }
  ]
}
```

---

## ⚠️ Notes Importantes

### Sécurité
- ✅ Bucket S3 privé par défaut (pas d'accès public)
- ✅ Versioning activé (protection contre suppressions accidentelles)
- ⚠️ **Les backups contiennent des données sensibles** :
  - Clés API (OpenAI, Anthropic) dans Redis
  - Documents clients dans app_data
  - Ne jamais rendre le bucket public

### Performance
- Les backups sont **compressés** (.tar.gz) pour économiser l'espace S3
- Taille backup typique : **200 MB - 2 GB** selon les données
- Coût S3 estimé : **~0.02€/GB/mois** (Standard) ou **~0.004€/GB/mois** (Glacier)

### Durée de rétention recommandée
- **7 derniers jours** : backups quotidiens (S3 Standard)
- **30 derniers jours** : backups hebdomadaires (S3 Standard)
- **90+ jours** : backups mensuels (Glacier)

### Stratégie 3-2-1
Pour une protection maximale :
- **3** copies des données (production + 2 backups)
- **2** supports différents (EC2 + S3)
- **1** copie offsite (S3 = offsite par nature)

---

## 🆘 Dépannage

### Erreur : "Bucket already exists"
Le bucket S3 existe déjà avec ce nom. Options :
1. Utiliser un autre nom : `-S3BucketName "mon-bucket-unique"`
2. Utiliser le bucket existant (le script détecte automatiquement)

### Erreur : "Stack not found"
Vérifiez que la stack CloudFormation existe :
```powershell
aws cloudformation describe-stacks --stack-name "Osmos"
```

### Erreur : "Permission denied (publickey)"
Vérifiez que la clé SSH est correcte :
```powershell
ssh -i .\Osmose_KeyPair.pem ubuntu@{EC2_IP} "echo 'Connection OK'"
```

### Services ne redémarrent pas
Vérifiez les logs Docker après restauration :
```powershell
ssh -i .\Osmose_KeyPair.pem ubuntu@{EC2_IP} "docker-compose -f docker-compose.ecr.yml -f docker-compose.monitoring.yml logs --tail 50"
```

### Backup incomplet
Vérifiez le manifeste :
```powershell
cat .\backups\{timestamp}\backup_manifest.txt
```

---

## 📞 Support

Pour toute question sur les backups/restore, consultez :
- Documentation principale : `README.md`
- CloudFormation : `cloudformation/README.md`
- Scripts AWS : `scripts/aws/README.md`
