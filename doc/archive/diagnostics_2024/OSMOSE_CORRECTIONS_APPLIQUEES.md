# OSMOSE - Corrections Appliquées (Review OpenAI)

**Date:** 2025-10-14 23:00
**Contexte:** Application des recommandations OpenAI pour OSMOSE Pure

---

## ✅ Corrections Appliquées

### P0: Config spaCy - URGENT (FAIT)

**Fichier:** `src/knowbase/semantic/config.py:73-79`

**Problème:** Config attendait modèles `trf` (transformers) mais Dockerfile installe `sm` (small)

**Correction:**
```python
# AVANT
models: Dict[str, str] = {
    "en": "en_core_web_trf",
    "fr": "fr_core_news_trf",
    "de": "de_core_news_trf",
    "xx": "xx_ent_wiki_sm"
}

# APRÈS
models: Dict[str, str] = {
    "en": "en_core_web_sm",
    "fr": "fr_core_news_sm",
    "xx": "xx_ent_wiki_sm"
}
```

**Impact:** Bloquant → débloqué. NER peut maintenant fonctionner.

---

### P1: Logging Métriques HDBSCAN (FAIT)

**Fichier:** `src/knowbase/semantic/segmentation/topic_segmenter.py:334-357`

**Amélioration:** Ajout logging taux outliers + warning si > 30%

**Correction:**
```python
# Calculer et logger le taux d'outliers (recommandation OpenAI)
outliers = cluster_labels == -1
outlier_count = outliers.sum()
outlier_rate = outlier_count / len(cluster_labels) if len(cluster_labels) > 0 else 0.0

logger.info(
    f"[OSMOSE] HDBSCAN metrics: outlier_rate={outlier_rate:.2%} "
    f"({outlier_count}/{len(cluster_labels)} windows)"
)

# Warning si taux d'outliers élevé (calibration à ajuster)
if outlier_rate > 0.3:
    logger.warning(
        f"[OSMOSE] High HDBSCAN outlier rate ({outlier_rate:.2%}). "
        "Consider adjusting min_cluster_size or using Agglomerative on outliers."
    )
```

**Impact:** Qualité topics. Permet de détecter si HDBSCAN rejette trop de windows en bruit.

---

### P2: PPTX Parser Robuste (FAIT)

**Fichier:** `src/knowbase/ingestion/pipelines/pptx_pipeline.py:710-750`

**Amélioration:** Extraction tables + chart metadata (recommandation OpenAI)

**Correction:**
```python
for shape in slide.shapes:
    # Extraction texte standard (text_frame)
    txt = getattr(shape, "text", None)
    if isinstance(txt, str) and txt.strip():
        texts.append(txt.strip())

    # Extraction tables (recommandation OpenAI)
    if shape.has_table:
        try:
            table = shape.table
            table_text = []
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    cell_text = cell.text_frame.text.strip() if cell.text_frame else ""
                    if cell_text:
                        row_text.append(cell_text)
                if row_text:
                    table_text.append(" | ".join(row_text))
            if table_text:
                texts.append("[TABLE]\n" + "\n".join(table_text))
        except Exception as e:
            logger.debug(f"Erreur extraction table slide {i}: {e}")

    # Extraction chart metadata (recommandation OpenAI)
    if shape.shape_type == 3:  # MSO_SHAPE_TYPE.CHART = 3
        try:
            chart_info = []
            if hasattr(shape, "chart") and shape.chart:
                chart = shape.chart
                if hasattr(chart, "chart_title") and chart.chart_title:
                    title_text = chart.chart_title.text_frame.text if hasattr(chart.chart_title, "text_frame") else ""
                    if title_text:
                        chart_info.append(f"Chart Title: {title_text}")
            if chart_info:
                texts.append("[CHART]\n" + "\n".join(chart_info))
        except Exception as e:
            logger.debug(f"Erreur extraction chart slide {i}: {e}")
```

**Impact:** Robustesse extraction slides complexes (tables, charts).

---

### P2: Préfixes e5 query/passage (FAIT)

**Fichier:** `src/knowbase/semantic/utils/embeddings.py:68-101, 193-229`

**Amélioration:** Support préfixes e5 "query:" et "passage:" (+2-5% précision retrieval)

**Corrections:**

**1. Méthode `encode()`:**
```python
def encode(self, texts: List[str], prefix_type: Optional[str] = None) -> np.ndarray:
    """
    Args:
        prefix_type: Type de préfixe e5 ("query", "passage", ou None)
                    Recommandation OpenAI: +2-5% précision retrieval
    """
    # Ajouter préfixes e5 si demandé (recommandation OpenAI)
    if prefix_type == "query":
        texts = [f"query: {text}" for text in texts]
    elif prefix_type == "passage":
        texts = [f"passage: {text}" for text in texts]

    embeddings = self.model.encode(...)
```

**2. Méthode `find_similar()`:**
```python
def find_similar(
    self,
    query_text: str,
    candidate_texts: List[str],
    use_e5_prefixes: bool = False  # Nouveau paramètre
) -> List[tuple]:
    """
    Args:
        use_e5_prefixes: Utiliser préfixes e5 "query:" et "passage:" (+2-5% précision)
    """
    # Utiliser préfixes e5 si demandé (recommandation OpenAI)
    if use_e5_prefixes:
        query_emb = self.model.encode(
            f"query: {query_text}",
            convert_to_numpy=True,
            normalize_embeddings=self.config.embeddings.normalize
        )
        candidate_embs = self.encode(candidate_texts, prefix_type="passage")
    else:
        query_emb = self.encode_cached(query_text)
        candidate_embs = self.encode(candidate_texts)
```

**Impact:** +2-5% précision retrieval. Désactivé par défaut (`use_e5_prefixes=False`), à activer après validation E2E.

---

## 📊 Corrections NON Appliquées (Post-E2E)

### P2: EntityRuler custom (Post-E2E)

**Priorité:** Moyenne
**Quand:** Après mesures qualité NER
**Effort:** 2h
**Impact:** Meilleure couverture domaine (ISO 27001, GDPR, SAP modules)

### P3: Jaccard + Cosine Linking (Post-E2E)

**Priorité:** Basse
**Quand:** Si trop de merges incorrects
**Effort:** 1h
**Impact:** Précision linking

### P3: Seuils Adaptatifs par (langue, type) (Post-E2E)

**Priorité:** Basse
**Quand:** Après calibration avec deck pilote
**Effort:** 1h
**Impact:** Précision canonicalization

### P4: Upgrade spaCy sm → md (Production)

**Priorité:** Basse
**Quand:** Si NER < 70% de couverture
**Effort:** Rebuild Docker (+100 MB)
**Impact:** Qualité NER

---

## 🎯 Prochaines Étapes

### 1. Rebuild Docker (Maintenant)

```bash
docker-compose down
docker-compose build app ingestion-worker
docker-compose up -d
```

**Durée:** 5-10 min (avec cache Docker)

---

### 2. Validation Dépendances (Maintenant)

```bash
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps
```

**Attendu:** 6/6 ✅ OK

**Critères:**
- Imports Python : ✅ OK
- spaCy : ✅ OK (modèles sm maintenant matching)
- Neo4j : ✅ OK
- Qdrant : ✅ OK
- LLM Config : ✅ OK
- OSMOSE Config : ✅ OK

---

### 3. Test PPTX E2E (Maintenant)

```bash
# Copier deck test
cp votre_deck.pptx data/docs_in/

# Observer logs
docker-compose logs -f ingestion-worker
```

**Logs attendus:**
```
📊 [OSMOSE PURE] use_vision = True
📊 [OSMOSE PURE] image_paths count = 25
Slide 1 [VISION SUMMARY]: 847 chars generated
✅ [OSMOSE PURE] 25 résumés Vision collectés
[OSMOSE PURE] Texte enrichi construit: 18543 chars
[OSMOSE] SemanticPipelineV2 initialized
[OSMOSE] HDBSCAN metrics: outlier_rate=15.2% (3/20 windows)
[OSMOSE PURE] ✅ Traitement réussi:
  - 42 concepts canoniques
  - Proto-KG: 42 concepts + 35 relations + 42 embeddings
```

---

### 4. Mesurer (Après E2E fonctionne)

**Métriques à collecter:**
- HDBSCAN outlier rate (maintenant loggé)
- Concept extraction coverage (% concepts extraits vs attendus)
- Linking merge rate (combien de concepts mergés)
- Temps total traitement
- Coût/slide Vision

**Durée:** 1-2h avec deck pilote

---

### 5. Activer Optimisations (Si besoin)

**Préfixes e5:** Activer `use_e5_prefixes=True` dans find_similar() si précision retrieval < 90%

**EntityRuler custom:** Ajouter patterns domaine (ISO 27001, GDPR, etc.) si NER < 70%

**spaCy md:** Upgrade modèles si NER insuffisant

---

## 📋 Récapitulatif Changements

| Fichier | Lignes | Type | Impact |
|---------|--------|------|--------|
| `semantic/config.py` | 73-79 | Fix | 🔥 Bloquant |
| `semantic/segmentation/topic_segmenter.py` | 334-357 | Amélioration | 🔵 Qualité |
| `ingestion/pipelines/pptx_pipeline.py` | 710-750 | Amélioration | 🟡 Robustesse |
| `semantic/utils/embeddings.py` | 68-101, 193-229 | Amélioration | 🟡 Précision (+2-5%) |

**Total changements:** 4 fichiers, ~100 lignes modifiées

---

## 🎓 Conclusion

✅ **Toutes les corrections P0 (bloquantes) appliquées**
✅ **Corrections P1-P2 (qualité/robustesse) appliquées**
⏸️ **Optimisations P3-P4 reportées post-E2E (correct par design)**

**Philosophie OpenAI validée:**
> "Tu ne peux pas optimiser ce que tu ne mesures pas."

**Prochaine étape immédiate:**
```bash
docker-compose down
docker-compose build app ingestion-worker
docker-compose up -d
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps
```

---

**Version:** 1.0
**Date:** 2025-10-14 23:00
**Status:** Corrections appliquées - Prêt pour rebuild + validation
