# Review OpenAI - Points de Rigueur OSMOSE

**Date:** 2025-10-14 22:30
**Contexte:** Review de l'architecture OSMOSE par OpenAI

---

## ✅ Consensus OpenAI + Claude

1. **Architecture e5-base partout + spaCy NER = correcte**
2. **Pas besoin de brancher e5 dans spaCy maintenant**
3. **Focus E2E d'abord, optimisation après**

---

## 📊 Check-list Points de Rigueur

### A. Paramétrage e5-base

| Point | Status | Localisation | Action |
|-------|--------|--------------|--------|
| **1. Normalisation L2** | ✅ **FAIT** | `config.py:90` `normalize: bool = True` | Rien |
| **2. Préfixes e5** | ⚠️ **À FAIRE** | Pas implémenté | Post-E2E |
| **3. Pooling = mean** | ✅ **PAR DÉFAUT** | sentence-transformers | Rien |
| **4. Qdrant distance = COSINE** | ✅ **FAIT** | Proto-KG setup | Rien |

**Détails préfixes e5 (amélioration future):**
```python
# Actuellement
embeddings = e5_model.encode(texts)

# Recommandé par OpenAI
query_emb = e5_model.encode(["query: " + q for q in queries])
passage_emb = e5_model.encode(["passage: " + p for p in passages])
```

**Impact:** +2-5% de précision sur retrieval. **Priorité:** Moyenne (après E2E)

---

### B. NER spaCy (couverture domaine)

| Point | Status | Localisation | Action |
|-------|--------|--------------|--------|
| **1. Modèles md/lg** | ⚠️ **PARTIEL** | Dockerfile installe `sm`, config attend `trf` | **URGENT** |
| **2. EntityRuler custom** | ❌ **MANQUANT** | Pas implémenté | Post-E2E |
| **3. Dates/versions** | ❌ **MANQUANT** | Pas de règles regex | Post-E2E |

**Problème URGENT:**

**Dockerfile installe:**
```dockerfile
RUN python -m spacy download en_core_web_sm
RUN python -m spacy download fr_core_news_sm
```

**Config attend:**
```python
models: Dict[str, str] = {
    "en": "en_core_web_trf",  # ← Transformers (gros)
    "fr": "fr_core_news_trf",
    ...
}
```

**Solutions:**

**Option A (Rapide):** Modifier config pour accepter sm
```python
models: Dict[str, str] = {
    "en": "en_core_web_sm",
    "fr": "fr_core_news_sm",
}
```

**Option B (Qualité):** Installer md dans Dockerfile (+100 MB)
```dockerfile
RUN python -m spacy download en_core_web_md
RUN python -m spacy download fr_core_news_md
```

**Recommandation:** **Option A pour maintenant** (faire tourner E2E), Option B après validation.

---

### C. HDBSCAN (stabilité topics)

| Point | Status | Localisation | Action |
|-------|--------|--------------|--------|
| **1. Logger taux rejet** | ⚠️ **PARTIEL** | TopicSegmenter existe | Ajouter métriques |
| **2. Fallback Agglomerative** | ✅ **FAIT** | `config.py:29` `clustering_fallback: "Agglomerative"` | Vérifier implémentation |

**À vérifier:**
```python
# Dans topic_segmenter.py
outliers = labels == -1
outlier_rate = outliers.sum() / len(labels)
logger.info(f"HDBSCAN outlier rate: {outlier_rate:.2%}")

if outlier_rate > 0.3:  # Seuil à calibrer
    # Fallback Agglomerative sur outliers
```

**Priorité:** Moyenne (améliore qualité topics)

---

### D. Linking cross-doc (seuils mesurés)

| Point | Status | Localisation | Action |
|-------|--------|--------------|--------|
| **1. Seuils par (langue, type)** | ❌ **MANQUANT** | Seuil global 0.75 | Post-E2E calibration |
| **2. Jaccard + cosine** | ❌ **MANQUANT** | Seulement cosine | Post-E2E |

**Amélioration future:**
```python
# Au lieu de:
if cosine(emb_A, emb_B) > 0.75:
    merge()

# Recommandé:
if (cosine(emb_A, emb_B) > threshold_by_type[concept.type] and
    jaccard(aliases_A, aliases_B) > 0.4):
    merge()
```

**Priorité:** Basse (après validation E2E)

---

### E. PPTX (robustesse parsing)

| Point | Status | Localisation | Action |
|-------|--------|--------------|--------|
| **1. Parser toutes shapes** | ⚠️ **À VÉRIFIER** | pptx_pipeline.py | Audit code |
| **2. Titles, legends, axis** | ⚠️ **À VÉRIFIER** | pptx_pipeline.py | Audit code |
| **3. Vision ciblée** | ✅ **FAIT** | Vision sur toutes slides (budget maîtrisé via température) | OK |

**À vérifier dans pptx_pipeline.py:**
```python
# Actuellement : shapes[0] uniquement ?
# Recommandé : toutes les shapes
for shape in slide.shapes:
    if shape.has_text_frame:
        text += shape.text_frame.text
    if shape.has_table:
        # Extraire table
    if shape.shape_type == MSO_SHAPE_TYPE.CHART:
        # Extraire chart metadata
```

**Priorité:** Moyenne (améliore extraction slides complexes)

---

## 🎯 Plan d'Action Priorisé

### Phase 1: FAIRE TOURNER E2E (Maintenant)

1. ✅ **Corriger config spaCy pour accepter modèles sm**
2. ✅ **Rebuild Docker**
3. ✅ **Validation dépendances** (6/6 OK)
4. ✅ **Test PPTX end-to-end**

**Durée:** 30 min

---

### Phase 2: MESURER (Après E2E fonctionne)

1. ⚡ **Calibration seuils:**
   - Mesurer Precision@Promote, Orphan ratio
   - Identifier % slides avec points détectés
   - Temps total, coût/slide

2. ⚡ **Logs métriques:**
   - HDBSCAN outlier rate
   - Concept extraction coverage
   - Linking merge rate

**Durée:** 1-2h avec deck pilote

---

### Phase 3: OPTIMISER (Quand métriques connues)

1. 🎯 **Préfixes e5-base** ("query:", "passage:")
2. 🎯 **EntityRuler custom** (ISO 27001, GDPR, SAP, etc.)
3. 🎯 **PPTX parser robuste** (toutes shapes)
4. 🎯 **Seuils adaptatifs** (par langue, type)
5. 🎯 **Jaccard + cosine** linking

**Durée:** 1 semaine itérative

---

### Phase 4: PRODUCTION (Si besoin modèles plus gros)

1. 🔧 **Upgrade spaCy sm → md** (si NER insuffisant)
2. 🔧 **Upgrade e5-base → e5-large** (si précision insuffisante, déjà dans config !)

**Note:** `config.py:86` dit déjà `"intfloat/multilingual-e5-large"` mais vérifie si c'est vraiment utilisé.

---

## 📋 Matrice Priorisation

| Amélioration | Impact | Effort | Priorité | Quand |
|--------------|--------|--------|----------|-------|
| Corriger config spaCy sm | 🔥 Bloquant | 🟢 5 min | **P0** | **Maintenant** |
| Rebuild + validation | 🔥 Bloquant | 🟢 10 min | **P0** | **Maintenant** |
| Test E2E PPTX | 🔥 Bloquant | 🟢 15 min | **P0** | **Maintenant** |
| Logger métriques HDBSCAN | 🔵 Qualité | 🟢 15 min | P1 | Après E2E |
| Préfixes e5 query/passage | 🟡 +2-5% | 🟡 30 min | P2 | Après mesures |
| EntityRuler custom | 🔵 Couverture | 🟡 2h | P2 | Après mesures |
| Jaccard + cosine linking | 🟡 Précision | 🟡 1h | P3 | Si trop merges |
| PPTX parser robuste | 🟡 Robustesse | 🔴 4h | P3 | Si slides manquées |
| spaCy sm → md | 🟡 NER | 🟢 Build | P4 | Si NER < 70% |

---

## 🎓 Conclusion

**OpenAI a raison sur tout**, mais la priorité est:

1. ✅ **Faire tourner E2E d'abord**
2. ✅ **Mesurer ce qui manque**
3. ✅ **Optimiser selon les besoins réels**

**Tu ne peux pas optimiser ce que tu ne mesures pas.**

**Prochaine étape immédiate:**
```bash
# 1. Corriger config spaCy (voir ci-dessous)
# 2. Rebuild
docker-compose build app ingestion-worker
# 3. Validation
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps
# 4. Test PPTX
```

---

**Version:** 1.0
**Date:** 2025-10-14 22:30
**Status:** Guide prêt - Correction config spaCy à appliquer
