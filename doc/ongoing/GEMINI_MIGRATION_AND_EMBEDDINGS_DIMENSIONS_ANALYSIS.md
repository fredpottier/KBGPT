# 🌊 OSMOSE - Migration Gemini + Analyse Dimensions Embeddings

**Date**: 2025-11-22
**Objectif**: Migrer vers Gemini pour LLM et Vertex AI pour embeddings
**Question clé**: 768D ou 3072D pour les embeddings ?

---

## 📋 Table des Matières

1. [Migration Gemini (LLM)](#1-migration-gemini-llm)
2. [Analyse Dimensions Embeddings (768D vs 3072D)](#2-analyse-dimensions-embeddings-768d-vs-3072d)
3. [Impact sur le Code Existant](#3-impact-sur-le-code-existant)
4. [Recommandations Finales](#4-recommandations-finales)
5. [Plan de Migration](#5-plan-de-migration)

---

## 1. Migration Gemini (LLM)

### 1.1 Configuration Proposée

```yaml
# config/llm_models.yaml
providers:
  google:
    api_key_env: "GOOGLE_API_KEY"
    base_url: null
    models:
      - "gemini-1.5-flash"
      - "gemini-1.5-flash-8b"
      - "gemini-1.5-pro"
      - "gemini-2.0-flash-exp"

task_models:
  # Extraction de concepts structurés
  knowledge_extraction: "gemini-1.5-flash-8b"

  # Vision: résumé riche et narratif
  vision: "gemini-1.5-flash"

  # Extraction structurée (concepts, facts, entities, relations)
  metadata: "gemini-1.5-pro"

fallback_strategy:
  knowledge_extraction:
    - "gemini-1.5-flash-8b"
    - "gemini-1.5-pro"
    - "gpt-4o-mini"  # Fallback OpenAI si Gemini down

  vision:
    - "gemini-1.5-flash"
    - "gemini-1.5-pro"
    - "gpt-4o"  # Fallback OpenAI pour vision critique

  metadata:
    - "gemini-1.5-pro"
    - "gemini-2.0-flash-exp"  # Expérimental GRATUIT
    - "gpt-4o"  # Fallback si JSON non réparable
```

### 1.2 Modifications Code Requises

**A. Créer nouveau client Gemini** (`src/knowbase/common/clients/gemini_client.py`)

```python
"""Client Google Gemini pour appels LLM."""
import os
import logging
import google.generativeai as genai
from typing import Optional

logger = logging.getLogger(__name__)

def get_gemini_client():
    """Initialise le client Google Gemini."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment")

    genai.configure(api_key=api_key)
    logger.info("[GEMINI] Client configured")
    return genai

def is_gemini_available() -> bool:
    """Vérifie si Gemini est disponible."""
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        return api_key is not None and len(api_key) > 0
    except Exception:
        return False
```

**B. Ajouter provider dans `llm_router.py`**

Ajouter méthodes :
- `_call_gemini()` : Appel synchrone Gemini
- `_call_gemini_async()` : Appel async Gemini
- Détection provider pour modèles `gemini-*`

**Format conversion requis** :
- OpenAI messages → Gemini parts format
- Support vision (base64 images)
- Gestion `response_format` pour JSON structuré

**C. Token tracking**

Gemini fournit `usage_metadata` :
```python
response.usage_metadata.prompt_token_count
response.usage_metadata.candidates_token_count
```

### 1.3 Avantages Migration Gemini

✅ **Coûts réduits de 75%** (voir `COST_ANALYSIS_OPENAI_VS_GEMINI.md`)
✅ **Context caching** : -75% supplémentaire sur input tokens
✅ **Gemini 2.0 Flash Exp** : GRATUIT pendant preview
✅ **Qualité équivalente** selon benchmarks Google
✅ **Résilience multi-provider** : Gemini + OpenAI fallback

---

## 2. Analyse Dimensions Embeddings (768D vs 3072D)

### 2.1 Modèles Vertex AI Disponibles

| Modèle | Dimensions | Langues | Use Case |
|--------|-----------|---------|----------|
| **gemini-embedding-001** | **3072** | Multilingue + Code | Recommandé Google (performances pointe) |
| text-embedding-005 | 768 | Anglais + Code | Spécialisé anglais |
| text-multilingual-embedding-002 | 768 | Multilingue | Optimisé multilingue |

**Note**: Les anciens modèles `text-embedding-gecko@002/003` ont été remplacés par les modèles ci-dessus.

**Recommandation Google**: `gemini-embedding-001` (3072D) unifie les modèles précédents et offre les meilleures performances.

### 2.2 Comparaison 768D vs 3072D

#### **Stockage Qdrant**

**Calcul pour 1 document (230 slides, ~13,763 chunks)**

| Dimension | Taille/Vecteur | Taille Totale (13,763 chunks) | Facteur |
|-----------|----------------|------------------------------|---------|
| **768D** | 3,072 bytes (768 × 4) | **42.3 MB** | 1× |
| **1024D (actuel)** | 4,096 bytes (1024 × 4) | **56.4 MB** | 1.33× |
| **3072D** | 12,288 bytes (3072 × 4) | **169.1 MB** | **4×** |

**Pour 1,000 documents** :
- 768D : **42.3 GB**
- 1024D : **56.4 GB** (actuel)
- 3072D : **169.1 GB** (⚠️ +200% vs actuel)

**Impact stockage** :
- ✅ 768D : Réduit stockage de -25% vs actuel
- ⚠️ 3072D : Augmente stockage de +200% vs actuel

#### **Performance Recherche**

**Distance cosine avec HNSW** :

| Dimension | Calculs/recherche | Latence estimée | vs Actuel |
|-----------|------------------|----------------|-----------|
| 768D | 768 multiplications | ~80ms | **-20%** ✅ |
| 1024D | 1024 multiplications | ~100ms | Baseline |
| 3072D | 3072 multiplications | ~150ms | **+50%** ⚠️ |

**Note** : Avec index HNSW bien configuré, l'impact latence est partiellement atténué.

**Impact performance** :
- ✅ 768D : Recherches légèrement plus rapides
- ⚠️ 3072D : Recherches plus lentes (+50%)

#### **Qualité Sémantique**

**Dimensions ≠ Qualité automatique**

📊 **Études académiques** ([MTEB benchmarks](https://huggingface.co/spaces/mteb/leaderboard)) :
- Dimensions élevées (3072) peuvent améliorer la **précision fine** (nuances sémantiques)
- **MAIS** : Qualité dépend surtout du **modèle pré-entraîné**, pas juste des dimensions
- 768D bien entraîné > 3072D mal entraîné

**Comparaison modèles Vertex AI** (selon Google) :
- `gemini-embedding-001` (3072D) : Performances pointe (⭐ recommandé)
- `text-multilingual-embedding-002` (768D) : Optimisé multilingue (bon compromis)

**Impact qualité** :
- ✅ 3072D (`gemini-embedding-001`) : Meilleure précision théorique
- ✅ 768D (`text-multilingual-embedding-002`) : Bon compromis qualité/coût

**USP OSMOSE** (cross-lingual) :
- Les 2 modèles supportent multilingue
- `gemini-embedding-001` (3072D) : Légèrement meilleur sur nuances
- `text-multilingual-embedding-002` (768D) : Déjà excellent pour cross-lingual

#### **Coûts Vertex AI**

**Tarifs Vertex AI Embeddings** ([pricing](https://cloud.google.com/vertex-ai/pricing)) :

| Service | Tarif | vs OpenAI |
|---------|-------|-----------|
| Vertex AI Text Embeddings | $0.025 / 1M tokens | **-80.8%** ✅ |
| OpenAI text-embedding-3-large | $0.130 / 1M tokens | Baseline |

**Coût identique** entre 768D et 3072D sur Vertex AI (tarif au token, pas à la dimension).

**Impact coûts** :
- ✅ 768D : **-80.8%** vs OpenAI actuel
- ✅ 3072D : **-80.8%** vs OpenAI actuel (même tarif)

#### **Complexité Migration**

**768D** :
- ⚠️ Changement dimension : Nécessite re-embedding de TOUT le corpus existant
- ⚠️ Incompatibilité : Vectors 768D ≠ 1024D actuels → Pas de recherche mixte
- ✅ Migration plus légère (moins de stockage)

**3072D** :
- ⚠️ Changement dimension : Re-embedding total requis aussi
- ⚠️ Impact stockage : +200% (besoin de vérifier capacité infrastructure)
- ⚠️ Impact performance : +50% latence recherche

**Conclusion** : Les deux nécessitent migration complète (re-embedding).

---

## 3. Impact sur le Code Existant

### 3.1 Fichiers à Modifier (Dimensions Embeddings)

**A. Configuration centrale** :

```python
# src/knowbase/semantic/config.py (ligne 139)
class QdrantProtoConfig(BaseModel):
    vector_size: int = 768  # OU 3072 selon choix
```

**B. Embedder wrapper** :

```python
# src/knowbase/semantic/utils/embeddings.py
def get_embedder(config: SemanticConfig):
    """Retourne l'embedder configuré (Vertex AI)."""
    # Implémenter VertexAIEmbedder
    return VertexAIEmbedder(
        model="gemini-embedding-001",  # ou text-multilingual-embedding-002
        dimensions=config.qdrant.vector_size
    )
```

**C. Cloud embeddings** :

```python
# src/knowbase/semantic/utils/cloud_embeddings.py
class VertexAIEmbedder:
    """Embeddings via Vertex AI (Google Cloud)."""

    def __init__(self, model: str, dimensions: int):
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        # Init Vertex AI
        vertexai.init(project=os.getenv("GCP_PROJECT_ID"))

        self.model = TextEmbeddingModel.from_pretrained(model)
        self.dimensions = dimensions

    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode texts via Vertex AI."""
        embeddings = self.model.get_embeddings(
            texts,
            output_dimensionality=self.dimensions  # Optionnel si réduction dims
        )

        return np.array([e.values for e in embeddings], dtype=np.float32)
```

**D. Création collections Qdrant** :

Tous les fichiers qui appellent `ensure_qdrant_collection()` ou `create_collection()` vont utiliser automatiquement `config.qdrant.vector_size`.

**Fichiers affectés** :
- `src/knowbase/semantic/setup_infrastructure.py` (ligne 212-214)
- `src/knowbase/common/clients/qdrant_client.py` (ligne 47)
- `src/knowbase/common/clients/shared_clients.py` (ligne 95)
- `scripts/reset_proto_kg.py`

**Impact** : Changement transparent si on met à jour `config.qdrant.vector_size`.

### 3.2 Migration du Corpus Existant

**Procédure complète** :

1. **Purge collections Qdrant** (vectors 1024D incompatibles)
```bash
curl -X DELETE "http://localhost:6333/collections/knowbase"
curl -X DELETE "http://localhost:6333/collections/concepts_proto"
```

2. **Recréer collections avec nouvelles dimensions**
```bash
docker exec knowbase-app python scripts/reset_proto_kg.py --full
```
→ Utilise automatiquement `config.qdrant.vector_size` (768 ou 3072)

3. **Re-importer tous les documents**
- Les fichiers `.knowcache.json` contiennent extraction text/concepts
- Réutilisables pour éviter appels LLM coûteux
- Seuls les embeddings seront régénérés

**Temps estimé** (1000 documents, 13M chunks) :
- Avec Vertex AI batch : ~10-15 min (vs 15h local)
- Coût : $325 (13M tokens × $0.025/1M)

### 3.3 Compatibilité Descendante

**Collections existantes** :
- ⚠️ **Incompatible** : Qdrant ne permet PAS de rechercher vectors 768D dans collection 1024D
- ❌ Migration = Purge + Re-embedding complet

**Stratégie Zero-Downtime** (si critique) :
1. Créer nouvelles collections `knowbase_v2`, `concepts_proto_v2` (nouvelles dims)
2. Re-importer en parallèle (collections coexistent)
3. Basculer l'API vers v2 quand prêt
4. Supprimer anciennes collections

**Durée** : +2-3h pour setup dual, mais service disponible pendant migration.

---

## 4. Recommandations Finales

### 🎯 Recommandation #1 : **768D** (`text-multilingual-embedding-002`)

**Pourquoi** :
✅ **Compromis optimal** qualité/performance/coût
✅ **Stockage réduit** : -25% vs actuel (42 GB vs 56 GB pour 1000 docs)
✅ **Performance** : -20% latence recherche
✅ **Qualité cross-lingual** : Excellent (optimisé multilingue)
✅ **Coûts Vertex AI** : -80.8% vs OpenAI
✅ **Infrastructure** : Pas de pression sur stockage/RAM

**Inconvénients** :
⚠️ Légèrement moins précis que 3072D sur nuances fines (marginal)

### 🔬 Option #2 : **3072D** (`gemini-embedding-001`)

**Pourquoi** :
✅ **Qualité maximale** : Performances pointe selon Google
✅ **Future-proof** : Modèle flagship de Google
✅ **Coûts Vertex AI** : Identiques à 768D (-80.8% vs OpenAI)

**Inconvénients** :
⚠️ **Stockage +200%** : 169 GB pour 1000 docs (vs 56 GB actuel)
⚠️ **Performance -50%** : Latence recherche augmentée
⚠️ **Infrastructure** : Besoin de vérifier capacité RAM/disque Qdrant

**Quand choisir 3072D** :
- Cas d'usage ultra-précis (recherche de brevets, analyse juridique fine)
- Infrastructure scalable (K8s avec auto-scaling)
- Corpus < 10,000 documents (impact stockage gérable)

### 🚀 Recommandation Finale

**Phase 1.8** : **768D** (`text-multilingual-embedding-002`)

**Raison** :
1. **USP OSMOSE** = Cross-lingual intelligence → 768D déjà excellent
2. **Performance** : Recherches plus rapides critiques pour UX
3. **Coûts** : -80.8% vs OpenAI suffit largement
4. **Infrastructure** : Pas de pression sur ressources
5. **Scalabilité** : 10,000 docs = 420 GB (gérable), vs 1.69 TB avec 3072D

**Si besoin futur de 3072D** :
- Re-migration facile (même process)
- Tester sur corpus échantillon d'abord (100 docs)
- Comparer qualité recherche 768D vs 3072D empiriquement

---

## 5. Plan de Migration

### 5.1 Étape 1 : Support Gemini (LLM)

**Durée** : 1-2h

```bash
# 1. Créer client Gemini
touch src/knowbase/common/clients/gemini_client.py

# 2. Modifier llm_router.py
# - Ajouter _call_gemini()
# - Ajouter _call_gemini_async()
# - Ajouter détection provider "google"

# 3. Mettre à jour config/llm_models.yaml
# - Ajouter section providers.google
# - Configurer task_models avec Gemini
# - Ajouter fallback_strategy

# 4. Tester
docker exec knowbase-app pytest tests/common/test_llm_router.py -k gemini
```

### 5.2 Étape 2 : Migration Embeddings 768D

**Durée** : 2-3h (dont 15 min embeddings batch)

```bash
# 1. Installer SDK Vertex AI
pip install google-cloud-aiplatform

# 2. Configurer GCP credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GCP_PROJECT_ID="your-project-id"

# 3. Créer VertexAIEmbedder
# Implémenter dans src/knowbase/semantic/utils/cloud_embeddings.py

# 4. Modifier config
# src/knowbase/semantic/config.py : vector_size = 768

# 5. Purge + recréation infrastructure
docker exec knowbase-app python scripts/purge_system.py --yes
docker exec knowbase-app python scripts/reset_proto_kg.py --full

# 6. Re-import corpus
# Utilise cache extraction (.knowcache.json)
# Seuls embeddings régénérés
```

### 5.3 Étape 3 : Validation

**Tests critiques** :

```bash
# 1. Vérifier dimensions Qdrant
curl "http://localhost:6333/collections/knowbase" | jq '.result.config.params.vectors.size'
# Attendu: 768

# 2. Tester recherche sémantique
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "SAP S/4HANA Cloud authentication", "top_k": 5}'

# 3. Comparer qualité vs baseline OpenAI
# Mesurer recall@5, recall@10 sur échantillon test

# 4. Mesurer performance
# Latence recherche moyenne < 100ms
```

### 5.4 Rollback Plan

**Si problème détecté** :

```bash
# 1. Revenir config 1024D
# src/knowbase/semantic/config.py : vector_size = 1024

# 2. Purge + recréation
docker exec knowbase-app python scripts/purge_system.py --yes
docker exec knowbase-app python scripts/reset_proto_kg.py --full

# 3. Re-import avec OpenAI embeddings
# Modifier cloud_embeddings.py pour réutiliser OpenAI

# Temps: ~1h
```

---

## 6. Checklist de Décision

### ✅ Migration Gemini (LLM) : **OUI**

- [x] Économie 75% coûts LLM
- [x] Context caching (-75% supplémentaire)
- [x] Gemini 2.0 Flash Exp GRATUIT
- [x] Fallback OpenAI préservé (résilience)
- [x] Modification code modérée (llm_router + client)

**Verdict** : **GO** - ROI évident, risque faible avec fallbacks

### ✅ Migration Embeddings : **OUI (768D)**

- [x] Économie 80.8% coûts embeddings
- [x] Performance +20% (latence réduite)
- [x] Stockage -25% (optimisation infrastructure)
- [x] Qualité cross-lingual excellente
- [x] Scalabilité 10,000 docs sans pression

**Verdict** : **GO 768D** - Compromis optimal

### ⚠️ Alternative 3072D : **TESTER PLUS TARD**

- [ ] Qualité marginalement supérieure (à valider empiriquement)
- [ ] Stockage +200% (besoin infra scalable)
- [ ] Performance -50% (acceptable si qualité justifie)

**Verdict** : **WAIT** - Tester sur échantillon 100 docs d'abord, comparer qualité

---

## 7. Estimations Coûts Migration

### 7.1 Coûts One-Time (Migration)

**Re-embedding corpus existant** (estimation 1,000 docs, 13M chunks) :

| Provider | Tokens | Tarif | Coût |
|----------|--------|-------|------|
| OpenAI text-embedding-3-large | 5.5M | $0.130/1M | $715 |
| Vertex AI (768D ou 3072D) | 5.5M | $0.025/1M | **$138** |

**Économie migration** : -$577 (-80.8%)

### 7.2 Coûts Récurrents (Par Document)

**Scénario OSMOSE Pure** (Vision + Extraction + Embeddings) :

| Composant | OpenAI | Gemini + Vertex | Économie |
|-----------|--------|-----------------|----------|
| Vision Summary | $22.78 | $5.70 | -$17.08 |
| Concept Extraction | $0.30 | $0.08 | -$0.22 |
| Embeddings | $0.72 | $0.14 | -$0.58 |
| **TOTAL/DOC** | **$23.80** | **$5.92** | **-$17.88 (-75.1%)** |

**Pour 5,000 docs/an** :
- OpenAI : $119,000
- Gemini + Vertex AI : **$29,600**
- **Économie annuelle** : **-$89,400 (-75.1%)**

### 7.3 ROI Migration

**Investissement** :
- Développement : 3-4h dev (négligeable)
- Migration corpus : $138 (one-time)

**Retour** :
- Économie dès le 1er document post-migration
- Break-even : 8 documents ($138 / $17.88)
- ROI 1 an (5000 docs) : **64,700%**

**Verdict** : ROI immédiat et massif.

---

## 📚 Ressources

- [Google Vertex AI Embeddings Docs](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
- [Gemini API Pricing](https://ai.google.dev/pricing)
- [Context Caching Gemini](https://ai.google.dev/gemini-api/docs/caching)
- [MTEB Embeddings Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [Qdrant Vector Storage Optimization](https://qdrant.tech/documentation/guides/optimize/)

---

**Prochaine étape** : Validation choix dimensions (768D recommandé) → Implémentation migration
