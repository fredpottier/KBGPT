# OSMOSE - Corrections Runtime (Erreurs d'Exécution)

**Date:** 2025-10-14 23:15
**Contexte:** Corrections erreurs découvertes lors du premier test OSMOSE Pure

---

## ✅ Corrections Appliquées (Runtime)

### Erreur 1: `ConceptExtractor` → `MultilingualConceptExtractor`

**Fichier:** `osmose_integration.py:170`

**Erreur:**
```python
from knowbase.semantic.extraction.concept_extractor import ConceptExtractor
# ImportError: cannot import name 'ConceptExtractor'
```

**Cause:** Le nom de la classe est `MultilingualConceptExtractor`, pas `ConceptExtractor`

**Fix:** ✅ Corrigé
```python
# AVANT
from knowbase.semantic.extraction.concept_extractor import ConceptExtractor

# APRÈS
from knowbase.semantic.extraction.concept_extractor import MultilingualConceptExtractor
```

---

### Erreur 2: Initialisation incorrecte de `SemanticPipelineV2`

**Fichier:** `osmose_integration.py:166-185`

**Erreur:**
```python
self.semantic_pipeline = SemanticPipelineV2(
    topic_segmenter=TopicSegmenter(llm_router),  # Mauvais
    concept_extractor=ConceptExtractor(llm_router),  # N'existe pas
    ...
)
```

**Cause:** `SemanticPipelineV2` crée ses propres composants en interne, pas besoin de les passer

**Fix:** ✅ Corrigé
```python
# AVANT (incorrect)
self.semantic_pipeline = SemanticPipelineV2(
    topic_segmenter=TopicSegmenter(llm_router),
    concept_extractor=ConceptExtractor(llm_router),
    semantic_indexer=SemanticIndexer(llm_router),
    concept_linker=ConceptLinker()
)

# APRÈS (correct)
from knowbase.semantic.config import get_semantic_config

llm_router = get_llm_router()
semantic_config = get_semantic_config()

self.semantic_pipeline = SemanticPipelineV2(
    llm_router=llm_router,
    config=semantic_config
)
```

---

### Erreur 3: Signature incohérente de `MultilingualConceptExtractor`

**Fichier:** `concept_extractor.py:41`

**Erreur:**
```python
def __init__(self, config, llm_router=None):  # Ordre inversé
```

**Cause:** Les autres classes prennent `(llm_router, config)` mais `MultilingualConceptExtractor` prenait `(config, llm_router)`

**Fix:** ✅ Corrigé
```python
# AVANT
def __init__(self, config, llm_router=None):

# APRÈS
def __init__(self, llm_router, config):
```

---

### Erreur 4: `EmbeddingsConfig` object has no attribute 'embeddings'

**Fichier:** `semantic_indexer.py:78` et `concept_linker.py:71`

**Erreur:**
```python
self.embedder = MultilingualEmbedder(config.embeddings)
# AttributeError: 'EmbeddingsConfig' object has no attribute 'embeddings'
```

**Cause:** `MultilingualEmbedder` s'attend à recevoir un `SemanticConfig` (qui a `.embeddings`), mais on lui passait `config.embeddings` qui est déjà un `EmbeddingsConfig`

**Fix:** ✅ Corrigé - Utiliser factory `get_embedder()`

**Dans `semantic_indexer.py`:**
```python
# AVANT
from src.knowbase.semantic.utils.embeddings import MultilingualEmbedder
...
self.embedder = MultilingualEmbedder(config.embeddings)

# APRÈS
from src.knowbase.semantic.utils.embeddings import get_embedder
...
self.embedder = get_embedder(config)
```

**Dans `concept_linker.py`:**
```python
# AVANT
from src.knowbase.semantic.utils.embeddings import MultilingualEmbedder
...
self.embedder = MultilingualEmbedder(config.embeddings)

# APRÈS
from src.knowbase.semantic.utils.embeddings import get_embedder
...
self.embedder = get_embedder(config)
```

---

### Erreur 5: `status_file` non défini

**Fichier:** `pptx_pipeline.py:2288`

**Erreur:**
```python
except Exception as e:
    ...
    status_file.write_text("error")  # NameError: name 'status_file' is not defined
```

**Cause:** Dans le gestionnaire d'exception OSMOSE Pure, référence à une variable non définie dans ce contexte

**Fix:** ✅ Corrigé - Supprimé la ligne
```python
# AVANT
except Exception as e:
    logger.error(f"[OSMOSE PURE] ❌ Erreur traitement sémantique: {e}", exc_info=True)
    if progress_callback:
        progress_callback("Erreur OSMOSE", 0, 100, str(e))
    status_file.write_text("error")  # ← Erreur
    raise

# APRÈS
except Exception as e:
    logger.error(f"[OSMOSE PURE] ❌ Erreur traitement sémantique: {e}", exc_info=True)
    if progress_callback:
        progress_callback("Erreur OSMOSE", 0, 100, str(e))
    raise
```

---

### Warning 6: Language detection model non trouvé

**Fichier:** `language_detector.py:40-46`

**Warning:**
```
ERROR: [OSMOSE] ❌ Language detection model not found: models/lid.176.bin
Download with:
  wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
  mv lid.176.bin models/lid.176.bin
```

**Cause:** Modèle fasttext `lid.176.bin` non inclus dans l'image Docker

**Fix:** ✅ Ajouté au Dockerfile

**Dockerfile (après ligne 59):**
```dockerfile
# Téléchargement modèle fasttext pour détection langue OSMOSE
RUN mkdir -p /app/models && \
    curl -L https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -o /app/models/lid.176.bin || \
    echo "fasttext language model download failed (will use fallback)"
```

**Note:** Le système a déjà un fallback (utilise `config.language_detection.fallback_language = "en"`), donc ce warning n'est pas bloquant. Le téléchargement améliore juste la précision de détection.

**Taille:** ~126 MB

---

## 📊 Résumé Corrections Runtime

| Problème | Fichier | Type | Status |
|----------|---------|------|--------|
| Import `ConceptExtractor` | `osmose_integration.py:170` | ImportError | ✅ Corrigé |
| Init `SemanticPipelineV2` | `osmose_integration.py:166-185` | Logique | ✅ Corrigé |
| Signature `MultilingualConceptExtractor` | `concept_extractor.py:41` | Signature | ✅ Corrigé |
| Embedder `EmbeddingsConfig` | `semantic_indexer.py:78`, `concept_linker.py:71` | AttributeError | ✅ Corrigé |
| `status_file` non défini | `pptx_pipeline.py:2288` | NameError | ✅ Corrigé |
| Modèle fasttext manquant | Dockerfile | Warning | ✅ Ajouté |

**Total corrections:** 6 fichiers modifiés

---

## 🚀 Prochaine Étape

Worker redémarré avec corrections appliquées (sauf fasttext qui nécessite rebuild).

**Pour le moment :**
- System fonctionnel avec fallback language detection (utilise "en" par défaut)
- Prêt pour test PPTX E2E

**Pour rebuild complet avec fasttext :**
```bash
docker-compose down
docker-compose build app ingestion-worker
docker-compose up -d
```

**Durée rebuild:** ~5-10 min (téléchargement fasttext ~126 MB)

---

## 🎯 Test OSMOSE Pure

Le système est maintenant opérationnel pour un test E2E.

**Commandes:**
```bash
# Copier PPTX test
cp votre_deck.pptx data/docs_in/

# Observer logs
docker-compose logs -f ingestion-worker
```

**Logs attendus si succès:**
```
[OSMOSE] SemanticPipelineV2 initialized
[OSMOSE] TopicSegmenter initialisé
[OSMOSE] MultilingualConceptExtractor initialisé
[OSMOSE] SemanticIndexer V2.1 initialized
[OSMOSE] ConceptLinker V2.1 initialized
[OSMOSE] Language detected: en (confidence: 0.98)  # Ou fallback: "en"
[OSMOSE] HDBSCAN metrics: outlier_rate=15.2%
[OSMOSE PURE] ✅ Traitement réussi:
  - 42 concepts canoniques
  - Proto-KG: 42 concepts + 35 relations
```

---

**Version:** 1.0
**Date:** 2025-10-14 23:15
**Status:** Corrections appliquées - Système opérationnel avec fallback langue
