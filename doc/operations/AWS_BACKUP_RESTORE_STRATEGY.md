# Stratégie de Sauvegarde/Restauration AWS pour KnowWhere

**Date:** 2025-10-25
**Statut:** Spécification Technique
**Objectif:** Permettre la sauvegarde automatique des données avant destruction de stack, et restauration lors de la création d'une nouvelle stack.

---

## 🎯 Cas d'Usage

### Scénario Principal
Un utilisateur veut détruire une stack CloudFormation EC2 (pour économiser des coûts ou tester une nouvelle version) **sans perdre les données** accumulées dans Neo4j, Qdrant et Redis.

### Besoins Fonctionnels
1. **Avant destruction:** Sauvegarder automatiquement toutes les bases de données sur S3
2. **Lors de création:** Option pour restaurer automatiquement les données sauvegardées
3. **Gestion versionnée:** Plusieurs sauvegardes avec timestamps
4. **Validation:** Vérifier l'intégrité des sauvegardes

---

## 🗄️ Données à Sauvegarder

### 1. Neo4j (Graph Database)
**Volume Docker:** `knowbase_neo4j_data`
**Contenu:**
- Proto-KG (concepts, relations, embeddings)
- Published-KG (graphe validé)
- Indexes et constraints

**Méthodes de Sauvegarde:**

#### Option A: Export Cypher (Recommandé)
```bash
# Avantages: Format texte, versionnable, réimportable
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "CALL apoc.export.cypher.all('/backup/neo4j-backup.cypher', {})"
```

**Taille estimée:** 10-100 MB (texte compressé)

#### Option B: Dump binaire
```bash
# Avantages: Plus rapide pour grandes bases
docker exec knowbase-neo4j neo4j-admin dump \
  --database=neo4j --to=/backup/neo4j-dump.dump
```

**Taille estimée:** 50-500 MB (binaire compressé)

**Recommandation:** Option A (Cypher) pour portabilité, Option B si >10 GB de données.

---

### 2. Qdrant (Vector Database)
**Volume Docker:** `knowbase_qdrant_storage`
**Collections:**
- `knowbase` (vecteurs documents généraux)
- `rfp_qa` (vecteurs Q/A RFP prioritaires)
- `knowwhere_proto` (vecteurs OSMOSE Phase 1)

**Méthodes de Sauvegarde:**

#### Option A: Snapshot API (Recommandé)
```bash
# 1. Créer snapshot pour chaque collection
curl -X POST "http://localhost:6333/collections/knowbase/snapshots"
curl -X POST "http://localhost:6333/collections/rfp_qa/snapshots"
curl -X POST "http://localhost:6333/collections/knowwhere_proto/snapshots"

# 2. Télécharger les snapshots
curl "http://localhost:6333/collections/knowbase/snapshots/{snapshot-name}" \
  -o knowbase-snapshot.tar.gz
```

**Taille estimée:** 100 MB - 5 GB (selon nombre de documents)

#### Option B: Copie volume Docker
```bash
# Moins recommandé (dépendance version Qdrant)
docker run --rm \
  -v knowbase_qdrant_storage:/data \
  -v $(pwd)/backup:/backup \
  busybox tar czf /backup/qdrant-data.tar.gz /data
```

**Recommandation:** Option A (Snapshots) pour compatibilité entre versions Qdrant.

---

### 3. Redis (Cache + Queue)
**Volume Docker:** `knowbase_redis_data`
**Contenu:**
- Quotas par tenant
- Budgets journaliers
- Queue RQ (tâches ingestion en cours)
- Cache temporaire

**Méthodes de Sauvegarde:**

#### Option A: RDB Snapshot (Recommandé)
```bash
# 1. Forcer création snapshot RDB
docker exec knowbase-redis redis-cli SAVE

# 2. Copier le fichier dump.rdb
docker cp knowbase-redis:/data/dump.rdb ./backup/redis-dump.rdb
```

**Taille estimée:** 1-50 MB

#### Option B: Export AOF
```bash
# Si AOF activé (persistence plus granulaire)
docker cp knowbase-redis:/data/appendonly.aof ./backup/redis-aof.aof
```

**Recommandation:** Option A (RDB) suffisant pour cas d'usage (quotas/budgets).

**⚠️ Note Importante:** La queue RQ (tâches en cours) sera perdue. Il faut arrêter l'ingestion avant sauvegarde.

---

## 📦 Architecture de Sauvegarde S3

### Structure des Buckets

```
s3://knowwhere-backups-{account-id}/
├── stacks/
│   ├── {stack-name}/
│   │   ├── 2025-10-25T14-30-00Z/          # Backup timestamp
│   │   │   ├── metadata.json              # Métadonnées backup
│   │   │   ├── neo4j/
│   │   │   │   └── neo4j-backup.cypher.gz
│   │   │   ├── qdrant/
│   │   │   │   ├── knowbase-snapshot.tar.gz
│   │   │   │   ├── rfp_qa-snapshot.tar.gz
│   │   │   │   └── knowwhere_proto-snapshot.tar.gz
│   │   │   └── redis/
│   │   │       └── redis-dump.rdb.gz
│   │   │
│   │   ├── 2025-10-24T10-15-00Z/          # Backup précédent
│   │   │   └── ...
│   │   │
│   │   └── latest -> 2025-10-25T14-30-00Z # Symlink vers dernier backup
│   │
│   └── {autre-stack-name}/
│       └── ...
│
└── retention-policy.json                   # Politique rétention (ex: 7 jours)
```

### Fichier metadata.json
```json
{
  "backup_timestamp": "2025-10-25T14:30:00Z",
  "stack_name": "KnowWhere-Production",
  "instance_id": "i-0123456789abcdef0",
  "region": "eu-west-1",
  "databases": {
    "neo4j": {
      "backup_method": "cypher_export",
      "file": "neo4j/neo4j-backup.cypher.gz",
      "size_bytes": 12458960,
      "checksum_sha256": "abc123...",
      "node_count": 15420,
      "relationship_count": 48320
    },
    "qdrant": {
      "backup_method": "snapshots_api",
      "collections": {
        "knowbase": {
          "file": "qdrant/knowbase-snapshot.tar.gz",
          "size_bytes": 152458960,
          "checksum_sha256": "def456...",
          "vectors_count": 12450
        },
        "rfp_qa": {
          "file": "qdrant/rfp_qa-snapshot.tar.gz",
          "size_bytes": 45821056,
          "vectors_count": 3420
        },
        "knowwhere_proto": {
          "file": "qdrant/knowwhere_proto-snapshot.tar.gz",
          "size_bytes": 98745632,
          "vectors_count": 8920
        }
      }
    },
    "redis": {
      "backup_method": "rdb_snapshot",
      "file": "redis/redis-dump.rdb.gz",
      "size_bytes": 2458960,
      "checksum_sha256": "ghi789...",
      "keys_count": 1240
    }
  },
  "backup_duration_seconds": 185,
  "status": "completed"
}
```

---

## 🔧 Scripts à Développer

### 1. Script de Sauvegarde

**Fichier:** `scripts/aws/backup-stack.ps1`

**Signature:**
```powershell
.\scripts\aws\backup-stack.ps1 `
  -StackName 'KnowWhere-Production' `
  -S3Bucket 'knowwhere-backups-715927975014' `
  -Region 'eu-west-1' `
  [-SkipRedis] `           # Optionnel: ne pas sauvegarder Redis
  [-Compress] `            # Optionnel: compression gzip (défaut: true)
  [-Validate]              # Optionnel: valider intégrité après upload
```

**Workflow:**

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PRÉPARATION                                              │
├─────────────────────────────────────────────────────────────┤
│ • Récupérer IP publique de l'instance EC2                   │
│ • Créer répertoire backup temporaire local                  │
│ • Générer timestamp: 2025-10-25T14-30-00Z                   │
│ • Créer structure S3: s3://.../stacks/{name}/{timestamp}/   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. ARRÊT INGESTION (Sécurité)                              │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker-compose stop worker                          │
│ • Attendre fin des tâches RQ en cours (timeout 60s)        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. SAUVEGARDE NEO4J                                         │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker exec neo4j cypher-shell export               │
│ • SCP: télécharger neo4j-backup.cypher                     │
│ • Compresser: gzip neo4j-backup.cypher                     │
│ • Calculer checksum SHA256                                  │
│ • Upload S3: s3://.../neo4j/neo4j-backup.cypher.gz        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. SAUVEGARDE QDRANT                                        │
├─────────────────────────────────────────────────────────────┤
│ Pour chaque collection (knowbase, rfp_qa, knowwhere_proto):│
│   • SSH: curl POST /collections/{name}/snapshots           │
│   • SSH: curl GET /collections/{name}/snapshots/{id}       │
│   • SCP: télécharger snapshot.tar.gz                       │
│   • Calculer checksum SHA256                                │
│   • Upload S3: s3://.../qdrant/{collection}-snapshot.tar.gz│
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. SAUVEGARDE REDIS                                         │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker exec redis redis-cli SAVE                    │
│ • SCP: docker cp redis:/data/dump.rdb                      │
│ • Compresser: gzip redis-dump.rdb                          │
│ • Calculer checksum SHA256                                  │
│ • Upload S3: s3://.../redis/redis-dump.rdb.gz             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. MÉTADONNÉES & VALIDATION                                 │
├─────────────────────────────────────────────────────────────┤
│ • Générer metadata.json avec checksums                      │
│ • Upload S3: s3://.../metadata.json                        │
│ • Mettre à jour symlink "latest"                           │
│ • Si -Validate: télécharger et vérifier checksums          │
│ • Nettoyer fichiers temporaires locaux                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. REDÉMARRAGE WORKER                                       │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker-compose start worker                         │
└─────────────────────────────────────────────────────────────┘
                          ↓
                   ✅ SUCCÈS
```

**Durée estimée:** 3-5 minutes (selon taille des données)

**Logs de Sortie:**
```
[14:30:00] ========================================
[14:30:00] SAUVEGARDE STACK: KnowWhere-Production
[14:30:00] ========================================
[14:30:01] [1/7] Préparation environnement...
[14:30:02]   ✓ Instance EC2: i-0123456789abcdef0 (54.74.63.248)
[14:30:02]   ✓ Bucket S3: s3://knowwhere-backups-715927975014
[14:30:02]   ✓ Timestamp: 2025-10-25T14-30-00Z
[14:30:03] [2/7] Arrêt worker d'ingestion...
[14:30:05]   ✓ Worker arrêté
[14:30:05] [3/7] Sauvegarde Neo4j...
[14:30:15]   ✓ Export Cypher: 12.5 MB (15,420 nodes, 48,320 relations)
[14:30:18]   ✓ Upload S3: neo4j/neo4j-backup.cypher.gz
[14:30:18] [4/7] Sauvegarde Qdrant...
[14:30:25]   ✓ Collection 'knowbase': 152 MB (12,450 vecteurs)
[14:30:32]   ✓ Collection 'rfp_qa': 45 MB (3,420 vecteurs)
[14:30:38]   ✓ Collection 'knowwhere_proto': 98 MB (8,920 vecteurs)
[14:30:40]   ✓ Upload S3: 3 snapshots
[14:30:40] [5/7] Sauvegarde Redis...
[14:30:42]   ✓ RDB Snapshot: 2.4 MB (1,240 clés)
[14:30:43]   ✓ Upload S3: redis/redis-dump.rdb.gz
[14:30:43] [6/7] Génération métadonnées...
[14:30:44]   ✓ metadata.json créé
[14:30:45]   ✓ Symlink 'latest' mis à jour
[14:30:45] [7/7] Redémarrage worker...
[14:30:47]   ✓ Worker redémarré
[14:30:47] ========================================
[14:30:47] ✅ SAUVEGARDE TERMINÉE AVEC SUCCÈS
[14:30:47] ========================================
[14:30:47] Taille totale: 312 MB
[14:30:47] Durée: 47 secondes
[14:30:47] Location: s3://knowwhere-backups-715927975014/stacks/KnowWhere-Production/2025-10-25T14-30-00Z/
```

---

### 2. Script de Destruction avec Sauvegarde

**Fichier:** `scripts/aws/destroy-cloudformation.ps1` (Mise à jour)

**Nouvelles Options:**
```powershell
.\scripts\aws\destroy-cloudformation.ps1 `
  -StackName 'KnowWhere-Production' `
  [-Backup] `              # Nouveau: faire sauvegarde avant destruction
  [-BackupBucket 'knowwhere-backups-715927975014'] `
  [-SkipConfirmation]      # Existant: pas de prompt interactif
```

**Workflow Mis à Jour:**

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CONFIRMATION UTILISATEUR                                 │
├─────────────────────────────────────────────────────────────┤
│ Si -Backup:                                                 │
│   "La stack sera détruite après sauvegarde sur S3."        │
│   "Continuer? [O/n]"                                        │
│ Sinon:                                                      │
│   "⚠️ ATTENTION: Destruction SANS sauvegarde!"             │
│   "Toutes les données seront PERDUES. Continuer? [o/N]"   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. SAUVEGARDE (Si -Backup)                                  │
├─────────────────────────────────────────────────────────────┤
│ • Appeler backup-stack.ps1                                  │
│ • Attendre complétion (timeout 10 minutes)                  │
│ • Vérifier succès (exit code 0)                            │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. DESTRUCTION STACK (Existant)                            │
├─────────────────────────────────────────────────────────────┤
│ • aws cloudformation delete-stack                           │
│ • Attendre DELETE_COMPLETE                                  │
│ • Supprimer volumes EBS orphelins                           │
└─────────────────────────────────────────────────────────────┘
                          ↓
                   ✅ SUCCÈS
```

---

### 3. Script de Restauration

**Fichier:** `scripts/aws/restore-stack.ps1`

**Signature:**
```powershell
.\scripts\aws\restore-stack.ps1 `
  -StackName 'KnowWhere-Production' `
  -BackupTimestamp '2025-10-25T14-30-00Z' `
  [-S3Bucket 'knowwhere-backups-715927975014'] `
  [-Latest]               # Utiliser dernier backup automatiquement
```

**Workflow:**

```
┌─────────────────────────────────────────────────────────────┐
│ 1. VALIDATION PRÉ-REQUIS                                    │
├─────────────────────────────────────────────────────────────┤
│ • Vérifier que la stack existe et est en état READY         │
│ • Vérifier que les containers sont UP                       │
│ • Télécharger metadata.json depuis S3                       │
│ • Valider checksums des fichiers backup sur S3              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. ARRÊT SERVICES                                           │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker-compose stop worker                          │
│ • SSH: docker-compose stop app                             │
│ • Attendre arrêt complet (timeout 30s)                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. PURGE DONNÉES EXISTANTES                                 │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker exec redis redis-cli FLUSHDB                 │
│ • SSH: curl DELETE /collections/knowbase                   │
│ • SSH: curl DELETE /collections/rfp_qa                     │
│ • SSH: curl DELETE /collections/knowwhere_proto            │
│ • SSH: docker exec neo4j cypher-shell "MATCH (n) DETACH..." │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. TÉLÉCHARGEMENT BACKUPS                                   │
├─────────────────────────────────────────────────────────────┤
│ • Télécharger depuis S3 vers /tmp/ sur EC2:                │
│   - neo4j-backup.cypher.gz                                  │
│   - knowbase-snapshot.tar.gz                                │
│   - rfp_qa-snapshot.tar.gz                                  │
│   - knowwhere_proto-snapshot.tar.gz                         │
│   - redis-dump.rdb.gz                                       │
│ • Décompresser tous les fichiers                            │
│ • Vérifier checksums SHA256                                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. RESTAURATION NEO4J                                       │
├─────────────────────────────────────────────────────────────┤
│ • SSH: cat neo4j-backup.cypher | docker exec -i neo4j \    │
│        cypher-shell -u neo4j -p graphiti_neo4j_pass         │
│ • Vérifier nombre de nodes/relations restaurés              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. RESTAURATION QDRANT                                      │
├─────────────────────────────────────────────────────────────┤
│ Pour chaque collection:                                     │
│   • SSH: curl PUT /collections/{name}/snapshots/recover \   │
│          --data-binary @{collection}-snapshot.tar.gz        │
│   • Vérifier nombre de vecteurs restaurés                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. RESTAURATION REDIS                                       │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker-compose stop redis                           │
│ • SSH: docker cp redis-dump.rdb redis:/data/dump.rdb      │
│ • SSH: docker-compose start redis                          │
│ • Attendre démarrage (healthcheck)                         │
│ • Vérifier nombre de clés restaurées                        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. REDÉMARRAGE SERVICES                                     │
├─────────────────────────────────────────────────────────────┤
│ • SSH: docker-compose start app                            │
│ • SSH: docker-compose start worker                         │
│ • Attendre healthchecks (timeout 60s)                      │
│ • Nettoyer fichiers temporaires                             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 9. VALIDATION POST-RESTAURATION                             │
├─────────────────────────────────────────────────────────────┤
│ • Tester API backend: GET /status                          │
│ • Vérifier Neo4j: count nodes/relations                    │
│ • Vérifier Qdrant: count vectors par collection            │
│ • Vérifier Redis: count keys                               │
│ • Comparer avec metadata.json attendu                       │
└─────────────────────────────────────────────────────────────┘
                          ↓
                   ✅ SUCCÈS
```

**Durée estimée:** 5-10 minutes (selon taille des données)

**Logs de Sortie:**
```
[15:00:00] ========================================
[15:00:00] RESTAURATION STACK: KnowWhere-Production
[15:00:00] Backup: 2025-10-25T14-30-00Z
[15:00:00] ========================================
[15:00:01] [1/9] Validation pré-requis...
[15:00:03]   ✓ Stack prête
[15:00:03]   ✓ metadata.json téléchargé
[15:00:03]   ✓ Checksums validés sur S3
[15:00:03] [2/9] Arrêt services...
[15:00:05]   ✓ Worker et App arrêtés
[15:00:05] [3/9] Purge données existantes...
[15:00:08]   ✓ Redis purgé
[15:00:10]   ✓ Qdrant collections supprimées
[15:00:12]   ✓ Neo4j purgé
[15:00:12] [4/9] Téléchargement backups...
[15:00:45]   ✓ 5 fichiers téléchargés (312 MB)
[15:00:46]   ✓ Checksums validés
[15:00:46] [5/9] Restauration Neo4j...
[15:01:15]   ✓ 15,420 nodes restaurés
[15:01:15]   ✓ 48,320 relations restaurées
[15:01:15] [6/9] Restauration Qdrant...
[15:02:10]   ✓ Collection 'knowbase': 12,450 vecteurs
[15:02:35]   ✓ Collection 'rfp_qa': 3,420 vecteurs
[15:03:05]   ✓ Collection 'knowwhere_proto': 8,920 vecteurs
[15:03:05] [7/9] Restauration Redis...
[15:03:08]   ✓ 1,240 clés restaurées
[15:03:08] [8/9] Redémarrage services...
[15:03:25]   ✓ App démarrée (healthy)
[15:03:27]   ✓ Worker démarré
[15:03:27] [9/9] Validation finale...
[15:03:30]   ✓ API: 200 OK
[15:03:31]   ✓ Neo4j: 15,420 nodes (attendu: 15,420) ✓
[15:03:31]   ✓ Qdrant: 24,790 vecteurs (attendu: 24,790) ✓
[15:03:32]   ✓ Redis: 1,240 clés (attendu: 1,240) ✓
[15:03:32] ========================================
[15:03:32] ✅ RESTAURATION TERMINÉE AVEC SUCCÈS
[15:03:32] ========================================
[15:03:32] Durée: 3 minutes 32 secondes
```

---

### 4. Intégration avec deploy-cloudformation.ps1

**Mise à jour du script de création de stack**

**Nouvelle Option:**
```powershell
.\scripts\aws\deploy-cloudformation.ps1 `
  -StackName 'KnowWhere-Production' `
  -KeyPairName 'Osmose_KeyPair' `
  -KeyPath 'C:\Project\SAP_KB\scripts\aws\Osmose_KeyPair.pem' `
  [-RestoreFromBackup '2025-10-25T14-30-00Z'] `
  [-RestoreLatest]         # Ou restaurer dernier backup automatiquement
```

**Workflow Mis à Jour:**

```diff
  [1/6] Création stack CloudFormation...
  [2/6] Attente création instance EC2...
  [3/6] Configuration Security Group...
  [4/6] Transfert fichiers sur EC2...
  [5/6] Déploiement Docker Compose...
+ [6/6] Restauration backup (si -RestoreFromBackup)...
  [7/6] Vérification finale...
```

---

## 🔐 Sécurité et Permissions IAM

### Permissions S3 Requises

**Pour le bucket de backups:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowBackupOperations",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::knowwhere-backups-*",
        "arn:aws:s3:::knowwhere-backups-*/*"
      ]
    }
  ]
}
```

**Créer le bucket avec versioning:**
```bash
aws s3api create-bucket \
  --bucket knowwhere-backups-715927975014 \
  --region eu-west-1 \
  --create-bucket-configuration LocationConstraint=eu-west-1

aws s3api put-bucket-versioning \
  --bucket knowwhere-backups-715927975014 \
  --versioning-configuration Status=Enabled

# Chiffrement au repos
aws s3api put-bucket-encryption \
  --bucket knowwhere-backups-715927975014 \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### Politique de Rétention

**Lifecycle Policy:**
```json
{
  "Rules": [
    {
      "Id": "DeleteOldBackups",
      "Status": "Enabled",
      "Prefix": "stacks/",
      "Expiration": {
        "Days": 30
      },
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 7
      }
    }
  ]
}
```

**Appliquer la politique:**
```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket knowwhere-backups-715927975014 \
  --lifecycle-configuration file://lifecycle-policy.json
```

---

## 📊 Estimation des Coûts

### Coûts de Stockage S3

**Hypothèses:**
- Taille backup moyenne: **300 MB** (Neo4j 10 MB + Qdrant 280 MB + Redis 10 MB)
- Fréquence: **1 backup par jour** (avant destruction stack)
- Rétention: **30 jours**
- Région: **eu-west-1 (Irlande)**

**Calcul:**
```
Stockage S3 Standard (eu-west-1): $0.023/GB/mois

Backup journalier:
- 1 backup/jour × 30 jours = 30 backups
- 300 MB/backup × 30 = 9 GB stockés
- Coût stockage: 9 GB × $0.023 = $0.21/mois

Transfert réseau (EC2 → S3 dans même région):
- GRATUIT (pas de coût sortie)

Upload API Requests:
- ~50 PUT requests/backup × 30 backups = 1,500 PUT/mois
- Coût PUT: $0.005/1000 requests = $0.008/mois

TOTAL: ~$0.22/mois (~$2.64/an)
```

**⚠️ Coût négligeable comparé au coût EC2 (~$50-100/mois)**

### Coûts de Transfert (Restauration)

**Téléchargement S3 → EC2 (même région):** GRATUIT
**Téléchargement S3 → Local (hors AWS):** $0.09/GB

**Exemple:** Restaurer 300 MB depuis local (Windows)
```
300 MB × $0.09/GB = $0.027 (~3 centimes)
```

---

## 🧪 Plan de Test

### Test 1: Sauvegarde Simple
```powershell
# 1. Créer stack avec quelques données test
.\scripts\aws\deploy-cloudformation.ps1 -StackName 'Test-Backup'

# 2. Ingérer 1 document PDF pour avoir des données
# (via UI ou API)

# 3. Faire sauvegarde
.\scripts\aws\backup-stack.ps1 -StackName 'Test-Backup'

# 4. Vérifier S3
aws s3 ls s3://knowwhere-backups-715927975014/stacks/Test-Backup/ --recursive

# 5. Télécharger metadata.json et valider JSON
aws s3 cp s3://knowwhere-backups-.../metadata.json ./test-metadata.json
cat test-metadata.json | jq .
```

**Résultat attendu:**
- ✅ metadata.json valide avec checksums
- ✅ 3 fichiers Qdrant présents
- ✅ 1 fichier Neo4j présent
- ✅ 1 fichier Redis présent

---

### Test 2: Destruction avec Sauvegarde
```powershell
# 1. Utiliser stack Test-Backup du Test 1
# 2. Détruire avec sauvegarde
.\scripts\aws\destroy-cloudformation.ps1 -StackName 'Test-Backup' -Backup

# 3. Attendre DELETE_COMPLETE
# 4. Vérifier que backup existe toujours sur S3
aws s3 ls s3://knowwhere-backups-715927975014/stacks/Test-Backup/latest/
```

**Résultat attendu:**
- ✅ Stack supprimée
- ✅ Backup présent sur S3
- ✅ Symlink "latest" pointe vers dernier backup

---

### Test 3: Restauration Complète
```powershell
# 1. Recréer stack vide
.\scripts\aws\deploy-cloudformation.ps1 -StackName 'Test-Restore'

# 2. Attendre déploiement complet (tous containers UP)
# 3. Restaurer depuis backup Test-Backup
.\scripts\aws\restore-stack.ps1 `
  -StackName 'Test-Restore' `
  -BackupSource 'Test-Backup' `
  -Latest

# 4. Vérifier données restaurées via API
curl http://<ec2-ip>:8000/status
curl http://<ec2-ip>:8000/search -d '{"query":"test"}'
```

**Résultat attendu:**
- ✅ Document PDF ingéré présent dans résultats recherche
- ✅ Comptes Neo4j/Qdrant/Redis correspondent à metadata.json
- ✅ API répond normalement

---

### Test 4: Création + Restauration en Une Commande
```powershell
# Scénario: Stack neuve avec restauration immédiate
.\scripts\aws\deploy-cloudformation.ps1 `
  -StackName 'Test-OneShot' `
  -RestoreFromBackup 'Test-Backup/latest'

# Attendre fin déploiement (~15 minutes)
# Vérifier données présentes
```

**Résultat attendu:**
- ✅ Stack créée ET restaurée en un seul workflow
- ✅ Données présentes immédiatement après création

---

## 📝 Documentation Utilisateur

### Workflow Typique: Économiser Coûts AWS

**Scénario:** Arrêter la stack EC2 le week-end pour économiser ~$40/mois.

**Vendredi soir:**
```powershell
# Sauvegarder puis détruire
.\scripts\aws\destroy-cloudformation.ps1 `
  -StackName 'KnowWhere-Production' `
  -Backup `
  -BackupBucket 'knowwhere-backups-715927975014'

# Durée: ~5 minutes
# Économie: ~$15/weekend (48h × $0.15/h)
```

**Lundi matin:**
```powershell
# Recréer et restaurer
.\scripts\aws\deploy-cloudformation.ps1 `
  -StackName 'KnowWhere-Production' `
  -RestoreLatest `
  -KeyPairName 'Osmose_KeyPair' `
  -KeyPath 'C:\Project\SAP_KB\scripts\aws\Osmose_KeyPair.pem'

# Durée: ~15 minutes
# Données restaurées à l'identique
```

**Économie annuelle:**
```
52 weekends × $15 = $780/an économisés
Coût backups S3: -$3/an
NET: ~$777/an économisés (50% du coût EC2 annuel)
```

---

## 🚀 Priorités d'Implémentation

### Phase 1: MVP (Semaine 1)
- ✅ Script `backup-stack.ps1` fonctionnel
- ✅ Sauvegarde Neo4j (Cypher export)
- ✅ Sauvegarde Qdrant (Snapshots API)
- ✅ Sauvegarde Redis (RDB)
- ✅ Upload S3 avec metadata.json
- ✅ Intégration avec `destroy-cloudformation.ps1 -Backup`

### Phase 2: Restauration (Semaine 2)
- ✅ Script `restore-stack.ps1` fonctionnel
- ✅ Téléchargement depuis S3
- ✅ Validation checksums
- ✅ Restauration Neo4j, Qdrant, Redis
- ✅ Tests validation post-restauration

### Phase 3: Intégration Complète (Semaine 3)
- ✅ Option `-RestoreFromBackup` dans `deploy-cloudformation.ps1`
- ✅ Gestion symlink "latest"
- ✅ Documentation utilisateur complète
- ✅ Tests E2E automatisés

### Phase 4: Optimisations (Semaine 4)
- 🔄 Compression optimisée (zstd au lieu de gzip)
- 🔄 Upload S3 multipart pour gros fichiers
- 🔄 Backups incrémentaux (delta depuis dernier backup)
- 🔄 Notifications SNS (succès/échec backup)
- 🔄 Dashboard CloudWatch pour monitoring backups

---

## 🔧 Considérations Techniques

### Limitations Connues

1. **Queue RQ (Redis):**
   Les tâches d'ingestion **en cours** seront perdues. L'utilisateur doit attendre la fin des tâches avant backup.

2. **Downtime obligatoire:**
   Le worker doit être arrêté pendant backup (~30s-1min) pour garantir cohérence.

3. **Taille des backups:**
   Si Qdrant > 10 GB, le backup peut prendre >10 minutes. Prévoir timeout ajustable.

4. **Compatibilité versions:**
   Un backup fait avec Neo4j 5.x peut ne pas être compatible avec Neo4j 6.x.
   → Ajouter version des services dans metadata.json

### Améliorations Futures

1. **Snapshots EBS:**
   Alternative: utiliser snapshots EBS des volumes Docker au lieu de backup applicatif.
   **Avantages:** Plus rapide (snapshots incrémentaux)
   **Inconvénients:** Moins portable, coûts EBS snapshots

2. **Backups incrémentaux:**
   Ne sauvegarder que les changements depuis dernier backup.
   **Gain:** Réduction taille backup de ~80% après premier backup complet

3. **Chiffrement côté client:**
   Chiffrer les backups avant upload S3 avec clé KMS.
   **Sécurité:** Protection supplémentaire données sensibles

4. **Multi-région:**
   Répliquer backups dans une seconde région AWS pour disaster recovery.
   **Résilience:** Protection contre panne régionale

---

## 📚 Références

### Documentation AWS
- [S3 Lifecycle Policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [EBS Snapshots](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSSnapshots.html)
- [IAM Policies for S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-policy-language-overview.html)

### Documentation Bases de Données
- [Neo4j Backup/Restore](https://neo4j.com/docs/operations-manual/current/backup-restore/)
- [Qdrant Snapshots](https://qdrant.tech/documentation/concepts/snapshots/)
- [Redis Persistence](https://redis.io/docs/management/persistence/)

### Outils
- [AWS CLI S3 Sync](https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html)
- [jq (JSON processor)](https://stedolan.github.io/jq/)

---

**Dernière mise à jour:** 2025-10-25
**Auteur:** Claude Code
**Statut:** Spécification Prête pour Implémentation
