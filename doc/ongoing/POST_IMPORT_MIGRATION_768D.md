# ⚠️ MIGRATION POST-IMPORT : Qdrant 1024D → 768D

**Date**: 2025-11-22
**Statut**: IMPORT EN COURS - NE PAS EXÉCUTER MAINTENANT
**Action required**: Après fin de l'import actuel

---

## 🎯 Objectif

Migrer les collections Qdrant de **1024D** (multilingual-e5-large) vers **768D** (text-multilingual-embedding-002 Vertex AI) pour :
- ✅ **Réduire coûts embeddings de 80.8%** (Vertex AI vs OpenAI)
- ✅ **Optimiser stockage** (-25%)
- ✅ **Améliorer performance recherche** (-20% latence)

---

## ⚠️ IMPORTANT - ATTENDEZ FIN DE L'IMPORT

**NE PAS EXÉCUTER CES COMMANDES MAINTENANT**

L'import actuel utilise encore les collections 1024D. La migration vers 768D nécessite :
1. Purge complète des collections Qdrant
2. Modification config dimensions
3. Re-embedding de tout le corpus

**Timing** :
- ✅ Modifications code : FAITES (sans impact import actuel)
- ⏸️ Migration dimensions : **APRÈS l'import** en cours
- ⏸️ Re-embedding : **APRÈS l'import** en cours

---

## 📋 Procédure de Migration (Post-Import)

### Étape 1 : Vérifier Fin de l'Import

```bash
# Vérifier qu'aucun worker n'est actif
docker exec knowbase-worker rq info

# Vérifier statut import
curl http://localhost:8000/documents/status

# Attendre que tous les jobs soient "completed"
```

### Étape 2 : Backup (Optionnel mais Recommandé)

```bash
# Snapshot Qdrant avant purge (au cas où)
curl -X POST "http://localhost:6333/collections/knowbase/snapshots"
curl -X POST "http://localhost:6333/collections/concepts_proto/snapshots"

# Les snapshots seront dans /qdrant/storage/snapshots/
```

### Étape 3 : Configuration Vertex AI

**A. Créer Service Account Google Cloud**

1. Aller sur [Google Cloud Console](https://console.cloud.google.com)
2. Créer projet ou utiliser existant
3. Activer Vertex AI API
4. Créer Service Account avec rôle "Vertex AI User"
5. Télécharger clé JSON

**B. Configurer credentials**

```bash
# Copier clé JSON dans le projet
cp ~/Downloads/service-account-key.json C:/Projects/SAP_KB/config/gcp-service-account.json

# Ajouter au .env
echo "GCP_PROJECT_ID=your-project-id" >> .env
echo "GOOGLE_APPLICATION_CREDENTIALS=/app/config/gcp-service-account.json" >> .env
```

**C. Ajouter volume Docker pour credentials**

Modifier `docker-compose.yml` :

```yaml
services:
  app:
    volumes:
      - ./config:/app/config  # Ajouter si pas déjà présent
```

### Étape 4 : Modifier Configuration Dimensions

**A. Modifier `src/knowbase/semantic/config.py`** (ligne 139)

```python
# AVANT
vector_size: int = 1024  # multilingual-e5-large

# APRÈS
vector_size: int = 768  # text-multilingual-embedding-002 (Vertex AI)
```

**B. Installer SDK Vertex AI**

```bash
# Depuis le conteneur app
docker exec knowbase-app pip install google-cloud-aiplatform
```

### Étape 5 : Purger Collections Qdrant

```bash
# Purge complète (collections 1024D incompatibles avec 768D)
docker exec knowbase-app python scripts/purge_system.py --yes
```

Vérifier purge :
```bash
curl "http://localhost:6333/collections/knowbase"
# Devrait retourner: {"status":"error","message":"collection not found"}
```

### Étape 6 : Recréer Infrastructure 768D

```bash
# Recréer collections Qdrant + indexes Neo4j
docker exec knowbase-app python scripts/reset_proto_kg.py --full

# Vérifier nouvelles dimensions
curl "http://localhost:6333/collections/knowbase" | jq '.result.config.params.vectors.size'
# Devrait retourner: 768
```

### Étape 7 : Re-importer Documents

**Option A : Re-import complet** (recommandé)

```bash
# Les fichiers .knowcache.json sont préservés
# Seuls les embeddings seront régénérés (via Vertex AI)

# 1. Vérifier que cache extraction existe
ls data/extraction_cache/*.knowcache.json

# 2. Relancer import
# Les documents utiliseront le cache pour extraction LLM
# Embeddings seront générés via Vertex AI (768D)
```

**Option B : Migration manuelle via script**

```python
# scripts/migrate_to_768d.py (à créer si besoin)
# Lit cache extraction existant
# Régénère embeddings 768D via Vertex AI
# Réinjecte dans Qdrant + Neo4j
```

### Étape 8 : Validation

**A. Vérifier dimensions Qdrant**

```bash
curl "http://localhost:6333/collections/knowbase" | jq '.result.config.params.vectors'

# Attendu:
# {
#   "size": 768,
#   "distance": "Cosine"
# }
```

**B. Tester recherche sémantique**

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SAP S/4HANA Cloud authentication mechanisms",
    "top_k": 5
  }'

# Vérifier que résultats sont cohérents
```

**C. Vérifier embeddings Vertex AI**

```bash
# Chercher dans logs app
docker logs knowbase-app --tail 100 | grep "VertexAIEmbedder"

# Devrait voir:
# [OSMOSE:VertexAIEmbedder] ✅ Encoded 450 texts → (450, 768)
```

**D. Comparer qualité recherche**

```bash
# Tester quelques requêtes types
# Comparer recall@5 vs baseline OpenAI 1024D (si data dispo)
```

---

## 🔄 Rollback (Si Problème)

**Si migration 768D pose problème** :

```bash
# 1. Revenir config 1024D
# src/knowbase/semantic/config.py : vector_size = 1024

# 2. Purge + recréation
docker exec knowbase-app python scripts/purge_system.py --yes
docker exec knowbase-app python scripts/reset_proto_kg.py --full

# 3. Re-import avec OpenAI embeddings
# Modifier cloud_embeddings.py pour réutiliser OpenAI text-embedding-3-large

# 4. Re-importer documents
# Temps: ~1-2h selon volume
```

---

## 📊 Estimations Temps et Coûts

### Temps Migration

| Étape | Durée |
|-------|-------|
| Backup Qdrant | 5 min |
| Config + purge | 5 min |
| Recréation infra | 2 min |
| Re-import 1000 docs | 15 min (embeddings Vertex AI) |
| Validation | 10 min |
| **TOTAL** | **~40 min** |

### Coûts Re-embedding

**Pour 1000 documents (13M chunks)** :

| Provider | Coût |
|----------|------|
| OpenAI text-embedding-3-large | $715 |
| Vertex AI text-multilingual-embedding-002 | **$138** |
| **Économie one-time** | **-$577 (-80.8%)** |

**ROI** : Break-even dès 8 documents post-migration

---

## ✅ Checklist Migration

**Avant de commencer** :
- [ ] Import actuel terminé (vérifier `docker logs knowbase-worker`)
- [ ] Service Account GCP créé + clé JSON téléchargée
- [ ] GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS dans .env
- [ ] SDK Vertex AI installé (`pip install google-cloud-aiplatform`)
- [ ] Backup Qdrant effectué (optionnel)

**Modifications config** :
- [ ] `src/knowbase/semantic/config.py` : `vector_size = 768`
- [ ] Vertex AI credentials montées dans Docker

**Migration** :
- [ ] Purge Qdrant (`scripts/purge_system.py --yes`)
- [ ] Recréation infra 768D (`scripts/reset_proto_kg.py --full`)
- [ ] Vérification dimensions (`curl collections/knowbase`)
- [ ] Re-import documents (utilise cache extraction)

**Validation** :
- [ ] Dimensions Qdrant = 768
- [ ] Recherche sémantique fonctionne
- [ ] Logs montrent Vertex AI embeddings
- [ ] Qualité recherche acceptable (tests manuels)

---

## 📚 Ressources

- [Vertex AI Text Embeddings Docs](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
- [Vertex AI Pricing](https://cloud.google.com/vertex-ai/pricing)
- [Analyse Complète 768D vs 3072D](./GEMINI_MIGRATION_AND_EMBEDDINGS_DIMENSIONS_ANALYSIS.md)
- [Qdrant Migration Guide](https://qdrant.tech/documentation/guides/migrate/)

---

**🚨 RAPPEL : NE PAS EXÉCUTER MAINTENANT - ATTENDEZ FIN DE L'IMPORT EN COURS**

Une fois l'import terminé, suivre cette procédure étape par étape pour migrer vers 768D Vertex AI.
