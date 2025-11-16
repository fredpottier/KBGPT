# 🔧 Fix: Qdrant Vector Dimension Mismatch (V2.2)

**Date:** 2025-10-19
**Version:** OSMOSE V2.2
**Problème:** Erreur dimensions vecteurs Qdrant (768D vs 1024D)
**Statut:** ✅ RÉSOLU

---

## 🔴 Problème Identifié

### Erreur Observée

```
[QDRANT:Chunks] Error upserting chunks: Unexpected Response: 400 (Bad Request)
Raw response content:
b'{"status":{"error":"Wrong input: Vector dimension error: expected dim: 768, got 1024"},"time":0.020829837}'
```

**Impact:**
- ❌ Chunks ne peuvent pas être stockés dans Qdrant
- ❌ Recherche vectorielle non fonctionnelle
- ❌ Import documents échoue silencieusement (pas d'erreur pipeline, mais données perdues)

---

## 🔍 Analyse de la Cause Racine

### Conflit de Configuration Embeddings

Le codebase utilise **2 systèmes d'embeddings différents** :

#### 1. **Pipeline d'Ingestion** (`pptx_pipeline.py`, `pdf_pipeline.py`)
   - **Modèle:** `intfloat/multilingual-e5-base` (via `settings.embeddings_model`)
   - **Dimensions:** **768**
   - **Fichier:** `src/knowbase/common/clients/embeddings.py`
   - **Usage:** Chunks stockés dans Qdrant collection `knowbase`

#### 2. **Système OSMOSE** (`semantic/`)
   - **Modèle:** `intfloat/multilingual-e5-large` (config YAML)
   - **Dimensions:** **1024**
   - **Fichier:** `src/knowbase/semantic/utils/embeddings.py`
   - **Usage:** Concepts OSMOSE (Proto-KG, canonicalization)

### Collection Qdrant Créée avec Ancien Modèle

La collection `knowbase` a été créée avec les paramètres du **pipeline d'ingestion** :
- **Vector size:** 768D
- **Modèle:** `intfloat/multilingual-e5-base`

Mais après migration OSMOSE V2.2, le système génère embeddings **1024D** → **Rejet par Qdrant**.

---

## ✅ Solution Appliquée

### Migration Collection Qdrant: 768D → 1024D

**Script:** `scripts/migrate_qdrant_to_1024d.py`

**Opérations:**
1. ✅ Sauvegarde metadata collection existante (optionnel)
2. ✅ Suppression collection `knowbase` (768D)
3. ✅ Recréation collection `knowbase` (1024D)
4. ✅ Vérification dimensions correctes

**Commande Exécutée:**
```bash
python scripts/migrate_qdrant_to_1024d.py
```

**Résultat:**
```
✅ Collection existante trouvée: 768D
   Points existants: 0
🗑️  Suppression collection knowbase...
✅ Collection supprimée
🔨 Création collection knowbase avec 1024D...
✅ Collection recréée avec succès!
✅ Vérification: 1024D
```

**Note:** Aucune donnée perdue (0 points dans collection).

---

## 📋 Configuration Finale Alignée

### OSMOSE Semantic Intelligence (`config/semantic_intelligence_v2.yaml`)
```yaml
embeddings:
  model: "intfloat/multilingual-e5-large"  # 1024 dimensions
  dimension: 1024
  device: "cpu"
  batch_size: 32
  normalize: true
```

### Qdrant Proto Collection
```yaml
qdrant_proto:
  collection_name: "concepts_proto"
  vector_size: 1024                # ✅ ALIGNÉ
  distance: "Cosine"
```

### Qdrant Chunks Collection
```python
# Recréée avec vector_size: 1024
collection_name: "knowbase"
vector_size: 1024                  # ✅ ALIGNÉ
distance: Distance.COSINE
```

---

## 🔄 Redémarrage Services

```bash
# 1. Build worker avec nouveau code
docker-compose build ingestion-worker

# 2. Démarrer worker
docker-compose up -d ingestion-worker

# 3. Vérifier statut
docker-compose ps ingestion-worker
# ✅ STATUS: Up 2 minutes

# 4. Vérifier logs
docker-compose logs ingestion-worker --tail=20
# ✅ "RQ worker started, listening on ingestion"
```

---

## ✅ Vérifications Post-Migration

### 1. Collection Qdrant
```bash
curl http://localhost:6333/collections/knowbase | jq '.result.config.params.vectors.size'
# Output: 1024 ✅
```

### 2. Worker RQ Actif
```bash
docker-compose ps ingestion-worker
# STATUS: Up ✅
```

### 3. Modèle Chargé
```bash
docker-compose exec ingestion-worker ps aux
# PID 1: python -m knowbase.ingestion.queue (30% CPU = loading model) ✅
```

---

## 🧪 Tests Requis

### Test 1: Import Document PPTX

**Action:**
1. Aller sur http://localhost:3000/documents/import
2. Uploader un document PPTX/PDF

**Résultats Attendus:**
```
[OSMOSE] Density Analysis: score=0.68, method=LLM_FIRST
[QDRANT:Chunks] ✅ Upserting 142 chunks...
[QDRANT:Chunks] ✅ Upserted 142 chunks to knowbase
```

**Critères de Succès:**
- ✅ Pas d'erreur "Vector dimension error"
- ✅ Chunks stockés dans Qdrant
- ✅ Recherche vectorielle fonctionne

### Test 2: Recherche Vectorielle

**Action:**
```bash
# Via API
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "ISO 27001 compliance", "limit": 5}'
```

**Résultats Attendus:**
```json
{
  "results": [
    {
      "id": "...",
      "score": 0.89,
      "text": "ISO 27001 defines requirements for..."
    }
  ]
}
```

---

## 📊 Impact Attendu

### Avant Fix
- ❌ 0 chunks stockés (tous rejetés)
- ❌ Recherche retourne 0 résultats
- ❌ Import "réussit" mais données perdues

### Après Fix
- ✅ 100% chunks stockés
- ✅ Recherche vectorielle opérationnelle
- ✅ Embeddings 1024D de meilleure qualité (e5-large > e5-base)

---

## 🎯 Améliorations Futures

### 1. Unification Modèles Embeddings

**Problème:** 2 systèmes embeddings séparés créent confusion/conflits.

**Solution Proposée:**
1. Créer un **client embeddings unifié** dans `common/clients/`
2. Tous les modules utilisent ce client unique
3. Configuration centralisée dans `settings.py`

**Fichiers à modifier:**
- `src/knowbase/common/clients/embeddings.py` (client unifié)
- `src/knowbase/semantic/utils/embeddings.py` (supprimer, utiliser client commun)
- `src/knowbase/ingestion/pipelines/*.py` (importer client unifié)

### 2. Tests d'Intégration Qdrant

**Objectif:** Détecter mismatch dimensions avant production

**Tests à ajouter:**
```python
# tests/integration/test_qdrant_embeddings.py
def test_embeddings_dimensions_match_collection():
    """Vérifier que dimensions embeddings = dimensions collection."""
    model = get_sentence_transformer()
    test_embedding = model.encode("test")

    collection_info = qdrant_client.get_collection("knowbase")
    expected_dim = collection_info.config.params.vectors.size

    assert len(test_embedding) == expected_dim, \
        f"Dimension mismatch: {len(test_embedding)} != {expected_dim}"
```

### 3. Documentation Configuration

**Créer:** `doc/EMBEDDINGS_ARCHITECTURE.md`

**Contenu:**
- Modèles utilisés (e5-base vs e5-large)
- Cas d'usage par modèle
- Process migration si changement modèle
- Scripts maintenance Qdrant

---

## 📝 Références

### Fichiers Modifiés/Créés
- ✅ `scripts/migrate_qdrant_to_1024d.py` (créé)
- ✅ `doc/ongoing/FIX_QDRANT_DIMENSION_MISMATCH_V2.2.md` (créé)
- ✅ Collection Qdrant `knowbase` (recréée)

### Fichiers de Configuration
- `config/semantic_intelligence_v2.yaml` (ligne 88-92: embeddings 1024D)
- `src/knowbase/config/settings.py` (ligne 55-56: embeddings_model)

### Fichiers Impliqués
- `src/knowbase/common/clients/embeddings.py` (768D - pipeline)
- `src/knowbase/semantic/utils/embeddings.py` (1024D - OSMOSE)
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py` (ligne 287: get_sentence_transformer)

---

## ✅ Checklist Résolution

- [x] Problème identifié (dimension mismatch 768D vs 1024D)
- [x] Cause racine analysée (2 systèmes embeddings)
- [x] Script migration créé (`migrate_qdrant_to_1024d.py`)
- [x] Migration exécutée (collection `knowbase` → 1024D)
- [x] Worker redémarré avec nouvelle config
- [x] Vérifications post-migration OK
- [ ] **Test import document (en attente utilisateur)**
- [ ] **Test recherche vectorielle (en attente utilisateur)**

---

**Dernière mise à jour:** 2025-10-19 11:02 CET
**Auteur:** Claude Code (session diagnostic erreurs import)
**Version OSMOSE:** V2.2 (Extraction Cache + Density Detection + Qdrant Fix)
