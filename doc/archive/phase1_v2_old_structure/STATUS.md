# 🌊 OSMOSE Semantic Intelligence Layer V2.1

**Status:** 🔄 **RESET IN PROGRESS** - Architecture V2.1 (Concept-First, Language-Agnostic)

---

## ⚠️ État Actuel du Code

### Fichiers Obsolètes (Supprimés)
- ❌ `narrative_detector.py` (420 lignes) - Supprimé (approche narrative abandonnée)
- ❌ `extractor.py` (stub) - Supprimé
- ❌ `segmentation.py` (stub) - Supprimé

### Fichiers Conservés (À Refactoriser)
- ⚠️ `models.py` (4772 octets) - **À REFACTORISER** pour V2.1 (Concepts, pas narratives)
- ⚠️ `config.py` (5171 octets) - **À ADAPTER** pour config V2.1
- ⚠️ `profiler.py` (13217 octets) - **CONSERVER PARTIEL** (complexity analysis utile)
- ⚠️ `setup_infrastructure.py` (6287 octets) - **À ADAPTER** pour schéma V2.1
- ✅ `__init__.py` - OK

---

## 🎯 Architecture V2.1 - À Implémenter

### Pipeline V2.1 (4 composants)

```
Document → TopicSegmenter → MultilingualConceptExtractor
         → SemanticIndexer → ConceptLinker → Proto-KG
```

### Structure Modules à Créer

```
src/knowbase/semantic/
├── __init__.py                          ✅ Existant
├── models.py                            ⚠️ À refactoriser (Concept, CanonicalConcept, Topic)
├── config.py                            ⚠️ À adapter (semantic_intelligence_v2.yaml)
│
├── segmentation/
│   ├── __init__.py                      📝 À créer
│   └── topic_segmenter.py               📝 À créer (Semaines 3-4)
│
├── extraction/
│   ├── __init__.py                      📝 À créer
│   └── concept_extractor.py             📝 À créer (Semaines 5-7) ⚠️ CRITIQUE
│
├── indexing/
│   ├── __init__.py                      📝 À créer
│   └── semantic_indexer.py              📝 À créer (Semaines 8-9)
│
├── linking/
│   ├── __init__.py                      📝 À créer
│   └── concept_linker.py                📝 À créer (Semaine 10)
│
└── utils/
    ├── __init__.py                      📝 À créer
    ├── ner_manager.py                   📝 À créer (NER multilingue)
    ├── embeddings.py                    📝 À créer (multilingual-e5-large)
    └── language_detector.py             📝 À créer (fasttext)
```

---

## 📋 Prochaines Actions (Phase 1 V2.1 Semaines 1-2)

### Semaine 1 (Immédiat)

**T1.1: Créer Structure Modules**
```bash
mkdir -p segmentation extraction indexing linking utils
touch segmentation/__init__.py extraction/__init__.py indexing/__init__.py linking/__init__.py utils/__init__.py
```

**T1.2: Refactoriser models.py**
- Supprimer models narratives (NarrativeThread, etc.)
- Créer ConceptType enum (ENTITY, PRACTICE, STANDARD, TOOL, ROLE)
- Créer Concept model (name, type, language, confidence)
- Créer CanonicalConcept model (canonical_name, aliases, languages)
- Créer Topic model (topic_id, windows, anchors, cohesion_score)

**T1.3: Adapter config.py**
- Charger `config/semantic_intelligence_v2.yaml`
- Classes config: SegmentationConfig, ExtractionConfig, IndexingConfig, LinkingConfig

**T1.4: Setup NER Multilingue**
```bash
pip install spacy
python -m spacy download en_core_web_trf
python -m spacy download fr_core_news_trf
python -m spacy download de_core_news_trf
python -m spacy download xx_ent_wiki_sm
```
- Créer `utils/ner_manager.py` (MultilingualNER class)

**T1.5: Setup Embeddings Multilingues**
```bash
pip install sentence-transformers
```
- Créer `utils/embeddings.py` (MultilingualEmbedder class)
- Télécharger multilingual-e5-large (~500MB)

**T1.6: Setup Détection Langue**
```bash
pip install fasttext
wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
mv lid.176.bin models/
```
- Créer `utils/language_detector.py` (LanguageDetector class)

**T1.7: Adapter setup_infrastructure.py**
- Schéma Neo4j V2.1 (Concepts, pas narratives)
- Qdrant collection `concepts_proto` (1024 dims)

---

## 🔍 Références

**Documentation:**
- Plan implémentation: `doc/phase1_v2/PHASE1_IMPLEMENTATION_PLAN.md`
- Tracking: `doc/phase1_v2/PHASE1_TRACKING.md`
- Checkpoints: `doc/phase1_v2/PHASE1_CHECKPOINTS.md`

**Architecture:**
- Spécification V2.1: `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- Roadmap produit: `doc/OSMOSE_AMBITION_PRODUIT_ROADMAP.md`

**Archive Approche Narrative:**
- Explication pivot: `doc/archive/feat-neo4j-native/narrative-approach/PIVOT_EXPLANATION.md`

---

## ⚙️ Configuration Requise (V2.1)

**Python Packages:**
```txt
# NLP / Semantic (Multilingue)
spacy==3.7.2
sentence-transformers==2.2.2
transformers==4.35.2
fasttext==0.9.2

# Clustering
hdbscan==0.8.33
scikit-learn==1.3.2

# LLM Clients
openai==1.3.0

# Storage
neo4j==5.14.0
qdrant-client==1.7.0
```

**Models à Télécharger:**
- spaCy: en_core_web_trf, fr_core_news_trf, de_core_news_trf, xx_ent_wiki_sm (~2GB total)
- Sentence Transformers: multilingual-e5-large (~500MB)
- FastText: lid.176.bin (~130MB)

**Total Disk:** ~2.6GB models

---

## 🚀 Status Phase 1 V2.1

| Semaine | Composant | Status |
|---------|-----------|--------|
| **1-2** | Setup Infrastructure | ✅ **COMPLETE** |
| **3-4** | TopicSegmenter | ✅ **CODE COMPLETE** |
| **5-7** | MultilingualConceptExtractor | 🟡 **NOT STARTED** ⚠️ CRITIQUE |
| **8-9** | SemanticIndexer | 🟡 **NOT STARTED** |
| **10** | ConceptLinker + Integration | 🟡 **NOT STARTED** |

**Progrès Global:** 40% (4/10 semaines)

### ✅ Semaines 1-2 : Setup Infrastructure (COMPLETE)

**Réalisations:**
- ✅ Structure modules créée (segmentation, extraction, indexing, linking, utils)
- ✅ models.py refactorisé (Concept, CanonicalConcept, Topic models)
- ✅ Configuration YAML V2.1 créée (semantic_intelligence_v2.yaml)
- ✅ config.py adapté pour V2.1 (10 classes configuration)
- ✅ profiler.py adapté (suppression code narratif)
- ✅ utils/ner_manager.py créé (MultilingualNER avec spaCy)
- ✅ utils/embeddings.py créé (MultilingualEmbedder avec multilingual-e5-large)
- ✅ utils/language_detector.py créé (LanguageDetector avec fasttext)
- ✅ setup_infrastructure.py adapté (Neo4j + Qdrant V2.1)

**À faire avant production:**
- ⚠️ Installer modèles spaCy dans Docker (en/fr/de/xx) - ~2GB
- ⚠️ Télécharger multilingual-e5-large - ~500MB
- ⚠️ Télécharger fasttext lid.176.bin - ~130MB
- ⚠️ Exécuter setup_infrastructure.py dans Docker

### ✅ Semaines 3-4 : TopicSegmenter (CODE COMPLETE)

**Réalisations:**
- ✅ TopicSegmenter créé (650 lignes) avec pipeline complet
- ✅ Structural segmentation (Markdown headers + numérotation)
- ✅ Semantic windowing (3000 chars, 25% overlap)
- ✅ Clustering robuste (HDBSCAN primary + Agglomerative fallback)
- ✅ Anchor extraction multilingue (NER + TF-IDF)
- ✅ Cohesion validation (threshold 0.65)
- ✅ Tests complets (9 test cases, 280 lignes)

**Features:**
- 🌍 Support multilingue automatique (EN/FR/DE/+)
- 🎯 Triple stratégie clustering (HDBSCAN → Agglomerative → Fallback 1 cluster)
- 📊 Cohesion score intra-topic (cosine similarity)
- 🔍 Anchor extraction hybride (NER entities + TF-IDF keywords)
- 📐 Windowing configurable (size + overlap)

**À faire:**
- ⚠️ Installer HDBSCAN dans requirements.txt
- ⚠️ Exécuter tests dans Docker avec modèles NER

---

**Version:** 2.1
**Date:** 2025-10-14
**Status:** Reset en cours, prêt à démarrer Semaines 1-2

---

> **🌊 OSMOSE V2.1 : "Concept-First, Language-Agnostic, Production-Ready"**
