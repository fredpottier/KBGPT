# 🌊 OSMOSE - Flux d'Ingestion Visuel Complet avec Architecture Agentique

**Version:** Phase 1.5 V2.0 - Architecture Agentique
**Date:** 2025-10-15
**Objectif:** Documentation visuelle du processus d'ingestion OSMOSE + orchestration agentique pour génération d'images

---

## 📋 Table des Matières

1. [Vue d'Ensemble](#vue-densemble)
2. [Architecture Agentique](#architecture-agentique)
3. [Graphe ASCII Complet](#graphe-ascii-complet)
4. [Description des Briques Logiques](#description-des-briques-logiques)
5. [Description des Agents](#description-des-agents)
6. [Flux de Données Détaillé](#flux-de-données-détaillé)
7. [Prompt pour IA Génératrice d'Image](#prompt-pour-ia-génératrice-dimage)

---

## 🎯 Vue d'Ensemble

**Architecture OSMOSE Pure avec Orchestration Agentique** : Le pipeline d'ingestion transforme un document (PPTX/PDF) en un **Cortex Sémantique** composé de concepts canoniques multilingues stockés dans le **Proto-KG** (Neo4j + Qdrant). L'orchestration est assurée par une **architecture agentique** avec 6 agents spécialisés pour maîtrise des coûts LLM et scalabilité production.

**Différenciation vs Copilot/Gemini:**
- ✅ **Cross-lingual unification automatique** : FR "authentification" = EN "authentication" = DE "Authentifizierung"
- ✅ **Language-agnostic Knowledge Graph** : Concepts unifiés indépendamment de la langue
- ✅ **Triple extraction method** : NER + Clustering + LLM (complémentaires)
- ✅ **DocumentRole classification** : Typologie automatique des documents
- ✅ **Architecture Agentique** : 6 agents spécialisés avec FSM, budget control, quality gates
- ✅ **Smart Routing** : NO_LLM/SMALL/BIG selon densité entities (cost optimization)

**Types de documents supportés:** PPTX, PDF
**Langues supportées:** Multilingue automatique (EN/FR/DE/+)
**Performance cible:** < 30s/document (timeout: 5 min)
**Budget caps:** SMALL 120/doc, BIG 8/doc, VISION 2/doc

---

## 🤖 Architecture Agentique

### 6 Agents Spécialisés (Phase 1.5 V1.1)

1. **Supervisor Agent** - FSM Master
   - Orchestre tous les agents via FSM (Finite State Machine)
   - 10 états : INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS → GATE_CHECK → PROMOTE → FINALIZE → DONE/ERROR
   - Timeout enforcement (5 min/doc)
   - Max steps protection (50 steps)
   - Retry logic automatique si qualité insuffisante

2. **Extractor Orchestrator Agent**
   - Routing intelligent : NO_LLM / SMALL / BIG
   - Règles : NO_LLM (<3 entities), SMALL (3-8), BIG (>8)
   - Budget awareness avec fallback graceful
   - PrepassAnalyzer tool (NER density)

3. **Pattern Miner Agent**
   - Cross-segment reasoning
   - Détection patterns récurrents
   - Enrichissement concepts

4. **Gatekeeper Delegate Agent**
   - Quality control avec 3 profils (STRICT/BALANCED/PERMISSIVE)
   - Promotion Proto→Published (Neo4j)
   - Rejet fragments, stopwords, PII
   - Retry recommendation

5. **Budget Manager Agent**
   - Caps durs par document (120 SMALL, 8 BIG, 2 VISION)
   - Quotas tenant/jour (10k SMALL, 500 BIG, 100 VISION)
   - Tracking Redis temps-réel
   - Refund logic pour retry failed

6. **LLM Dispatcher Agent**
   - Rate limits : 500/100/50 RPM
   - Concurrency control
   - Priority queue

---

## 📊 Graphe ASCII Complet

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                    🌊 OSMOSE INGESTION PIPELINE V2.1                     ┃
┃                        "Le Cortex Documentaire"                          ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

                              📄 DOCUMENT SOURCE
                          (PPTX, PDF, DOCX, etc.)
                                     │
                                     │ Upload via API/UI
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  🎯 PHASE 1: EXTRACTION VISUELLE & TEXTUELLE                               │
│  Pipeline: pptx_pipeline.py / pdf_pipeline.py                             │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
                    ▼                                 ▼
        ┌────────────────────┐          ┌─────────────────────┐
        │  📸 EXTRACTION      │          │  📝 EXTRACTION      │
        │     IMAGES          │          │     TEXTE           │
        ├────────────────────┤          ├─────────────────────┤
        │ • Slides → PNG     │          │ • Raw text          │
        │ • Tables → Images  │          │ • Notes speakers    │
        │ • Charts → Images  │          │ • Megaparse (OCR)   │
        └────────────────────┘          └─────────────────────┘
                    │                                 │
                    └────────────────┬────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │  🤖 GPT-4 VISION ANALYSIS        │
                    │  ask_gpt_vision_summary()        │
                    ├──────────────────────────────────┤
                    │ Génère résumé visuel enrichi     │
                    │ pour chaque slide/page:          │
                    │ • Description visuelle           │
                    │ • Éléments clés (tables, etc)    │
                    │ • Contexte sémantique            │
                    └──────────────────────────────────┘
                                     │
                                     │ Résumés riches
                                     ▼
                    ┌──────────────────────────────────┐
                    │  📦 CONSTRUCTION FULL TEXT        │
                    │  full_text_enriched               │
                    ├──────────────────────────────────┤
                    │ Concaténation de tous les        │
                    │ résumés Vision enrichis          │
                    │ Format: "--- Slide N ---\n..."   │
                    └──────────────────────────────────┘
                                     │
                                     │ Text complet (~10k-100k chars)
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  🌊 PHASE 2: OSMOSE SEMANTIC PIPELINE V2.1                                 │
│  osmose_integration.py → semantic_pipeline_v2.py                           │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────┐
                │                                         │
                ▼                                         ▼
    ┌─────────────────────┐               ┌──────────────────────┐
    │  🔍 PRE-FILTERING   │               │  🌍 LANGUAGE         │
    │  OsmoseIntegration  │               │     DETECTION        │
    ├─────────────────────┤               ├──────────────────────┤
    │ • Min length: 500   │               │ • fasttext (lid.176) │
    │ • Max length: 1M    │               │ • Confidence: 0.8    │
    │ • Feature flags     │               │ • Multi-langue auto  │
    └─────────────────────┘               └──────────────────────┘
                │                                         │
                └────────────────────┬────────────────────┘
                                     │
                                     │ Text validated + language
                                     ▼
        ╔════════════════════════════════════════════════════════════╗
        ║  🌊 OSMOSE CORE PIPELINE - 4 ÉTAPES SÉQUENTIELLES          ║
        ╚════════════════════════════════════════════════════════════╝

┌───────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 1: 📐 TOPIC SEGMENTATION                                           │
│  Component: TopicSegmenter (~650 lignes)                                  │
│  File: src/knowbase/semantic/segmentation/topic_segmenter.py             │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: full_text_enriched
    │
    ├──► 1.1 Structural Segmentation (H1-H3 headers)
    │
    ├──► 1.2 Semantic Windowing (3000 chars, 25% overlap)
    │
    ├──► 1.3 Embeddings Generation (multilingual-e5-large, cached)
    │
    ├──► 1.4 Clustering (HDBSCAN → Agglomerative → Fallback)
    │         - Triple stratégie pour robustesse
    │
    ├──► 1.5 Anchor Extraction (NER entities + TF-IDF keywords)
    │
    └──► 1.6 Cohesion Validation (threshold: 0.65)
    │
    │ OUTPUT: List[Topic] (2-10 topics typiquement)
    │         - topic_id, section_path, windows, anchors, cohesion_score
    ▼

┌───────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 2: 🔎 CONCEPT EXTRACTION (TRIPLE METHOD) ⚠️ CRITIQUE              │
│  Component: MultilingualConceptExtractor (~750 lignes)                    │
│  File: src/knowbase/semantic/extraction/concept_extractor.py             │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: List[Topic]
    │
    │ Pour chaque topic:
    │
    ├──► 2.1 METHOD 1: NER Multilingue (spaCy)
    │         - Models: en_core_web_trf, fr_core_news_trf, de_core_news_trf
    │         - Confidence: 0.85
    │         - Types: PERSON, ORG, GPE, PRODUCT, TECH, etc.
    │         - Extraction: Entities haute précision, rapide
    │
    ├──► 2.2 METHOD 2: Semantic Clustering (HDBSCAN)
    │         - Embeddings similarity grouping
    │         - Confidence: 0.75
    │         - Extraction: Concepts sémantiques groupés
    │
    ├──► 2.3 METHOD 3: LLM Extraction (gpt-4o-mini)
    │         - Triggered si concepts < min_concepts_per_topic (default: 2)
    │         - Confidence: 0.80
    │         - Prompts multilingues (EN/FR/DE + fallback)
    │         - Extraction: Contexte riche, concepts complexes
    │
    ├──► 2.4 Déduplication (exact + similarity 0.90)
    │
    ├──► 2.5 Typage Automatique (5 types ConceptType)
    │         - ENTITY (organisations, personnes, lieux)
    │         - PRACTICE (pratiques, processus, méthodes)
    │         - STANDARD (normes, certifications, frameworks)
    │         - TOOL (outils, technologies, logiciels)
    │         - ROLE (rôles, responsabilités, fonctions)
    │
    └──► 2.6 Quality Scoring (confidence + extraction_method)
    │
    │ OUTPUT: List[Concept] (10-100 concepts bruts)
    │         - concept_id, name, type, language, confidence, extraction_method
    ▼

┌───────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 3: 🌐 SEMANTIC INDEXING (CANONICALIZATION) ⚠️ USP CRITIQUE         │
│  Component: SemanticIndexer (~600 lignes)                                 │
│  File: src/knowbase/semantic/indexing/semantic_indexer.py                │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: List[Concept] (tous les concepts bruts)
    │
    ├──► 3.1 Cross-lingual Embeddings Similarity
    │         - Matrice cosine similarity (multilingual-e5-large)
    │         - Détection concepts similaires cross-linguals
    │         - Ex: FR "authentification" ≈ EN "authentication" (0.92)
    │
    ├──► 3.2 Clustering Canonique (threshold: 0.85)
    │         - Grouping concepts identiques/similaires
    │         - Unification cross-lingual automatique
    │
    ├──► 3.3 Canonical Name Selection
    │         - Priorité 1: Anglais (si présent)
    │         - Priorité 2: Plus fréquent dans le cluster
    │         - Priorité 3: Première occurrence
    │
    ├──► 3.4 Unified Definition Generation (LLM)
    │         - Fusion de toutes les définitions du cluster
    │         - Génération définition unifiée en anglais
    │         - Température: 0.3 (déterministe)
    │
    ├──► 3.5 Hierarchy Construction (LLM, max depth: 3)
    │         - Détection relations parent-child
    │         - Ex: "OAuth 2.0" → parent: "Authentication Protocol"
    │         - Validation hiérarchie cohérente
    │
    ├──► 3.6 Relations Extraction (top-5 similaires)
    │         - Relations sémantiques via embeddings
    │         - RELATED_TO, PART_OF, IMPLEMENTS, etc.
    │
    └──► 3.7 Quality Scoring (gatekeeper Proto-KG)
    │         - Score basé sur: support, confidence, hierarchy
    │         - Threshold: 0.60 pour stockage Proto-KG
    │
    │ OUTPUT: List[CanonicalConcept] (5-30 concepts canoniques)
    │         - canonical_id, canonical_name, aliases, languages,
    │           unified_definition, hierarchy_parent, related_concepts
    ▼

┌───────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 4: 🔗 CONCEPT LINKING                                              │
│  Component: ConceptLinker (~450 lignes)                                   │
│  File: src/knowbase/semantic/linking/concept_linker.py                   │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: List[CanonicalConcept], document_id, document_text
    │
    ├──► 4.1 DocumentRole Classification (5 types)
    │         - DEFINES: Standards, guidelines, architecture docs
    │         - IMPLEMENTS: Projects, solutions, implementations
    │         - AUDITS: Audit reports, compliance checks
    │         - PROVES: Certificates, attestations, proofs
    │         - REFERENCES: General mentions, references
    │         - Classification via heuristiques + keywords
    │
    ├──► 4.2 Context Extraction
    │         - Pour chaque mention de concept dans le document
    │         - Extrait contexte (±200 chars)
    │         - Détection aliases/variations
    │
    ├──► 4.3 Similarity Scoring
    │         - Calcul embeddings similarity concept ↔ document
    │         - Threshold: 0.70 pour création connexion
    │
    └──► 4.4 Graph Construction
    │         - Connexions bidirectionnelles concept ↔ document
    │         - Métriques: similarity, context, role
    │
    │ OUTPUT: List[ConceptConnection] (5-50 connexions)
    │         - connection_id, document_id, canonical_concept_name,
    │           document_role, similarity, context
    ▼

┌───────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 5: 📋 SEMANTIC PROFILE GENERATION                                  │
│  Component: SemanticPipelineV2._build_result()                            │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: Tous les résultats des 4 étapes précédentes
    │
    ├──► 5.1 Métriques Globales
    │         - topics_count, concepts_count, canonical_concepts_count
    │         - connections_count, languages_detected
    │         - average_topic_cohesion, overall_complexity
    │
    ├──► 5.2 Timing & Performance
    │         - processing_time_ms (par composant + total)
    │         - Performance monitoring
    │
    └──► 5.3 Data Serialization
    │         - Sérialisation JSON complète
    │         - Tous les topics, concepts, canonicals, connections
    │
    │ OUTPUT: SemanticProfile + Dict[str, Any] complet
    ▼

┌───────────────────────────────────────────────────────────────────────────┐
│  🎯 PHASE 3: STORAGE PROTO-KG (DUAL STORAGE)                              │
│  Component: OsmoseIntegrationService._store_osmose_results()              │
│  File: src/knowbase/ingestion/osmose_integration.py                      │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ INPUT: osmose_result (SemanticProfile complet)
    │
    ├─────────────────────┬────────────────────┐
    │                     │                    │
    ▼                     ▼                    ▼
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│  🗄️ NEO4J       │ │  📊 QDRANT       │ │  📈 METRICS     │
│  (GRAPH)        │ │  (VECTORS)       │ │  TRACKING       │
├─────────────────┤ ├──────────────────┤ ├─────────────────┤
│ • Concepts      │ │ Collection:      │ │ • concepts_     │
│   nodes         │ │ concepts_proto   │ │   stored        │
│                 │ │                  │ │ • relations_    │
│ • Relations     │ │ Embeddings:      │ │   stored        │
│   edges         │ │ 1024D            │ │ • embeddings_   │
│                 │ │ (multilingual-   │ │   stored        │
│ • Hierarchy     │ │  e5-large)       │ │                 │
│   parent-child  │ │                  │ │ • duration_     │
│                 │ │ Metadata:        │ │   seconds       │
│ • DocumentRole  │ │ • canonical_name │ │                 │
│   links         │ │ • type           │ │ • quality_score │
│                 │ │ • definition     │ │                 │
│ Schema:         │ │ • aliases        │ │                 │
│ • 6 constraints │ │ • languages      │ │                 │
│ • 11 indexes    │ │ • tenant_id      │ │                 │
│                 │ │ • neo4j_id (ref) │ │                 │
└─────────────────┘ └──────────────────┘ └─────────────────┘
    │                     │                    │
    └─────────────────────┴────────────────────┘
                          │
                          │ Storage completed
                          ▼
        ┌──────────────────────────────────────┐
        │  ✅ OSMOSE INGESTION COMPLETE         │
        ├──────────────────────────────────────┤
        │ • Document moved to docs_done/       │
        │ • Status: "success"                  │
        │ • Métriques logged                   │
        │ • Proto-KG enrichi                   │
        └──────────────────────────────────────┘
                          │
                          ▼
        ╔══════════════════════════════════════╗
        ║  🌊 PROTO-KG (CORTEX DOCUMENTAIRE)   ║
        ║                                      ║
        ║  Concepts Canoniques Multilingues    ║
        ║  Cross-lingual Unified               ║
        ║  DocumentRole Classified             ║
        ║  Hiérarchie Sémantique               ║
        ║  Relations Contextuelles             ║
        ╚══════════════════════════════════════╝
```

---

## 🧩 Description des Briques Logiques

### 🎯 Phase 1: Extraction Visuelle & Textuelle

#### 1. **Pipeline PPTX/PDF** (`pptx_pipeline.py` / `pdf_pipeline.py`)

**Rôle:** Point d'entrée pour l'ingestion de documents. Extraction du contenu visuel et textuel.

**Responsabilités:**
- Parsing du fichier source (PPTX/PDF)
- Extraction images (slides, charts, tables)
- Extraction texte (raw text, notes speakers, OCR via Megaparse)
- Génération thumbnails

**Entrées:**
- Fichier document (PPTX/PDF) dans `data/docs_in/`

**Sorties:**
- Images PNG par slide/page → `data/public/slides/`
- Texte brut extrait

---

#### 2. **GPT-4 Vision Analysis** (`ask_gpt_vision_summary()`)

**Rôle:** Analyse visuelle enrichie de chaque slide/page pour générer résumés sémantiques.

**Responsabilités:**
- Analyse visuelle des images (charts, tables, diagrammes)
- Génération résumé textuel enrichi
- Intégration contexte visuel + texte brut + notes

**Entrées:**
- Image PNG du slide/page
- Texte brut extrait
- Notes speakers

**Sorties:**
- Résumé visuel enrichi (~200-500 chars/slide)
- Format: Description visuelle + éléments clés + contexte

**Modèle LLM:** gpt-4o (vision-capable)

---

### 🌊 Phase 2: OSMOSE Semantic Pipeline V2.1

#### 3. **OsmoseIntegrationService** (`osmose_integration.py`)

**Rôle:** Orchestration et pré-filtering avant traitement sémantique.

**Responsabilités:**
- Feature flags (enable_osmose, osmose_for_pptx, osmose_for_pdf)
- Filtrage texte (min 500 chars, max 1M chars)
- Orchestration du pipeline sémantique
- Stockage résultats dans Proto-KG

**Entrées:**
- `full_text_enriched` (résumés Vision concaténés)
- `document_id`, `document_title`, `document_path`

**Sorties:**
- `OsmoseIntegrationResult` (métriques + success/error)

---

#### 4. **TopicSegmenter** (`topic_segmenter.py` ~650 lignes)

**Rôle:** Segmentation sémantique du document en topics cohérents.

**Pipeline interne:**
1. **Structural segmentation** : Headers H1-H3 (si présents)
2. **Semantic windowing** : 3000 chars, 25% overlap
3. **Embeddings** : multilingual-e5-large (1024D), cached
4. **Clustering** : HDBSCAN → Agglomerative → Fallback (robustesse)
5. **Anchor extraction** : NER entities + TF-IDF keywords
6. **Cohesion validation** : Threshold 0.65

**Entrées:**
- `text_content` (full text enrichi, 10k-100k chars)
- `document_id`

**Sorties:**
- `List[Topic]` (typiquement 2-10 topics)
  - `topic_id`, `section_path`, `windows`, `anchors`, `cohesion_score`

**Technologies:**
- **Embeddings:** multilingual-e5-large (Sentence Transformers)
- **Clustering:** HDBSCAN + Agglomerative (sklearn)
- **NER:** spaCy (multilingue)
- **TF-IDF:** sklearn TfidfVectorizer

---

#### 5. **MultilingualConceptExtractor** (`concept_extractor.py` ~750 lignes) ⚠️ CRITIQUE

**Rôle:** Extraction concepts via triple méthode complémentaire (NER + Clustering + LLM).

**Pipeline interne:**
1. **METHOD 1: NER Multilingue** (spaCy)
   - Models: `en_core_web_trf`, `fr_core_news_trf`, `de_core_news_trf`, `xx_ent_wiki_sm`
   - Confidence: 0.85
   - Extraction: Entities haute précision (PERSON, ORG, GPE, PRODUCT, etc.)

2. **METHOD 2: Semantic Clustering** (HDBSCAN embeddings)
   - Confidence: 0.75
   - Extraction: Grouping sémantique via embeddings similarity

3. **METHOD 3: LLM Extraction** (gpt-4o-mini)
   - Triggered si `concepts < min_concepts_per_topic` (default: 2)
   - Confidence: 0.80
   - Prompts multilingues (EN/FR/DE + fallback)
   - Extraction: Concepts complexes avec contexte

4. **Déduplication** : Exact + similarity 0.90

5. **Typage Automatique** : 5 types ConceptType
   - `ENTITY` : Organisations, personnes, lieux
   - `PRACTICE` : Pratiques, processus, méthodes
   - `STANDARD` : Normes, certifications, frameworks
   - `TOOL` : Outils, technologies, logiciels
   - `ROLE` : Rôles, responsabilités, fonctions

**Entrées:**
- `List[Topic]` (depuis TopicSegmenter)

**Sorties:**
- `List[Concept]` (10-100 concepts bruts)
  - `concept_id`, `name`, `type`, `language`, `confidence`, `extraction_method`, `source_topic_id`

**Technologies:**
- **NER:** spaCy transformer models (600MB-900MB each)
- **Embeddings:** multilingual-e5-large
- **Clustering:** HDBSCAN
- **LLM:** gpt-4o-mini (structured outputs, JSON)

**USP KnowWhere:**
- Triple méthode = robustesse + coverage
- NER = précision haute pour entities
- Clustering = découverte concepts sémantiques
- LLM = contexte riche, fallback intelligent

---

#### 6. **SemanticIndexer** (`semantic_indexer.py` ~600 lignes) ⚠️ USP CRITIQUE

**Rôle:** Canonicalisation cross-lingual des concepts + construction hiérarchies.

**Pipeline interne:**
1. **Cross-lingual Embeddings Similarity**
   - Matrice cosine similarity (multilingual-e5-large)
   - Détection concepts similaires cross-linguals
   - Exemple: FR "authentification" ≈ EN "authentication" (0.92)

2. **Clustering Canonique** (threshold: 0.85)
   - Grouping concepts identiques/similaires
   - Unification automatique cross-lingual

3. **Canonical Name Selection**
   - Priorité 1: Anglais (si présent dans cluster)
   - Priorité 2: Concept le plus fréquent
   - Priorité 3: Première occurrence

4. **Unified Definition Generation** (LLM)
   - Fusion de toutes les définitions du cluster
   - Génération définition unifiée en anglais
   - Température: 0.3 (déterministe)

5. **Hierarchy Construction** (LLM, max depth: 3)
   - Détection relations parent-child
   - Exemple: "OAuth 2.0" → parent: "Authentication Protocol"
   - Validation cohérence hiérarchique

6. **Relations Extraction** (top-5 similaires)
   - Relations sémantiques via embeddings
   - Types: RELATED_TO, PART_OF, IMPLEMENTS, etc.

7. **Quality Scoring** (gatekeeper Proto-KG)
   - Score basé sur: support, confidence, hierarchy
   - Threshold: 0.60 pour stockage Proto-KG

**Entrées:**
- `List[Concept]` (tous les concepts bruts, 10-100)

**Sorties:**
- `List[CanonicalConcept]` (5-30 concepts canoniques)
  - `canonical_id`, `canonical_name`, `aliases`, `languages`, `unified_definition`
  - `hierarchy_parent`, `hierarchy_children`, `related_concepts`
  - `quality_score`, `support`, `confidence`

**Technologies:**
- **Embeddings:** multilingual-e5-large (cross-lingual)
- **Clustering:** Agglomerative (sklearn)
- **LLM:** gpt-4o-mini (definition fusion, hierarchy)

**USP KnowWhere:**
- ✅ **Canonicalization cross-lingual automatique** (FR/EN/DE unifiés)
- ✅ **Language-agnostic** : Concepts indépendants de la langue
- ✅ **Meilleur que Copilot/Gemini** : Unification automatique concepts multilingues

---

#### 7. **ConceptLinker** (`concept_linker.py` ~450 lignes)

**Rôle:** Linking concepts cross-documents + classification DocumentRole.

**Pipeline interne:**
1. **DocumentRole Classification** (5 types)
   - `DEFINES` : Standards, guidelines, architecture docs
   - `IMPLEMENTS` : Projects, solutions, implementations
   - `AUDITS` : Audit reports, compliance checks
   - `PROVES` : Certificates, attestations, proofs
   - `REFERENCES` : General mentions, references
   - Classification via heuristiques + keywords

2. **Context Extraction**
   - Pour chaque mention de concept dans le document
   - Extrait contexte (±200 chars autour)
   - Détection aliases/variations

3. **Similarity Scoring**
   - Calcul embeddings similarity concept ↔ document
   - Threshold: 0.70 pour création connexion

4. **Graph Construction**
   - Connexions bidirectionnelles concept ↔ document
   - Métriques: similarity, context, role

**Entrées:**
- `List[CanonicalConcept]` (depuis SemanticIndexer)
- `document_id`, `document_title`, `document_text`

**Sorties:**
- `List[ConceptConnection]` (5-50 connexions)
  - `connection_id`, `document_id`, `canonical_concept_name`
  - `document_role`, `similarity`, `context`

**Technologies:**
- **Embeddings:** multilingual-e5-large (similarity)
- **NER:** spaCy (context extraction)
- **Heuristiques:** Keywords matching pour DocumentRole

---

#### 8. **SemanticPipelineV2** (`semantic_pipeline_v2.py` ~300 lignes)

**Rôle:** Orchestration end-to-end des 4 composants OSMOSE.

**Responsabilités:**
- Orchestration séquentielle des 4 étapes
- Génération SemanticProfile avec métriques
- Error handling et fallbacks
- Performance monitoring
- Sérialisation résultats (JSON)

**Entrées:**
- `document_id`, `document_title`, `document_path`, `text_content`
- `llm_router`, `tenant_id`

**Sorties:**
- `Dict[str, Any]` complet avec:
  - `success`, `processing_time_ms`
  - `metrics`: topics_count, concepts_count, canonical_concepts_count, connections_count
  - `data`: topics, concepts, canonical_concepts, connections (JSON)
  - `semantic_profile`: complexity, languages, domain

---

### 🎯 Phase 3: Storage Proto-KG

#### 9. **Proto-KG Storage** (`_store_osmose_results()`)

**Rôle:** Stockage dual (Neo4j + Qdrant) des résultats OSMOSE.

**Architecture Proto-KG:**

**A. Neo4j (Graph Structure)**
- **Nœuds Concept** : Concepts canoniques
  - Properties: canonical_name, type, definition, aliases, languages, quality_score
  - Constraints: UNIQUE sur canonical_name + tenant_id
  - Indexes: Full-text search sur canonical_name, definition

- **Relations Sémantiques** :
  - `RELATED_TO` : Relations sémantiques top-5
  - `PARENT_OF` : Hiérarchie parent-child
  - `MENTIONED_IN` : Concept ↔ Document (avec DocumentRole)

**B. Qdrant (Vector Storage)**
- **Collection:** `concepts_proto`
- **Dimensions:** 1024 (multilingual-e5-large)
- **Metric:** Cosine
- **Payload:**
  - canonical_name, type, definition, aliases, languages
  - quality_score, tenant_id, neo4j_concept_id (référence)

**Entrées:**
- `osmose_result` (Dict depuis SemanticPipelineV2)
- `document_id`, `tenant_id`

**Sorties:**
- `storage_stats`:
  - `concepts_stored` (Neo4j nœuds)
  - `relations_stored` (Neo4j edges)
  - `embeddings_stored` (Qdrant vectors)

---

## 📈 Flux de Données Détaillé

### Entrée: Document Source

```
Document: SAP_HANA_Security_Guide.pptx
Size: 5MB
Slides: 50
Language: Mixed (EN + FR + DE)
```

### Extraction Phase

```
Résultat Extraction:
- 50 images PNG → data/public/slides/SAP_HANA_Security_Guide/
- Texte brut: ~15,000 chars (raw text + notes)
- Vision résumés: ~25,000 chars (enrichis)
- full_text_enriched: 40,000 chars TOTAL
```

### OSMOSE Phase

#### Étape 1: Topic Segmentation

```
Input: 40,000 chars
Output:
- 5 topics identifiés
  1. "Introduction to SAP HANA Security" (cohesion: 0.78)
     - Anchors: ["SAP HANA", "security", "authentication", "encryption"]
  2. "User Management & Authorization" (cohesion: 0.82)
     - Anchors: ["users", "roles", "privileges", "LDAP"]
  3. "Data Encryption & SSL" (cohesion: 0.75)
     - Anchors: ["encryption", "SSL/TLS", "certificates", "key management"]
  4. "Audit & Compliance" (cohesion: 0.80)
     - Anchors: ["audit", "logging", "compliance", "GDPR", "ISO 27001"]
  5. "Best Practices & Recommendations" (cohesion: 0.72)
     - Anchors: ["best practices", "recommendations", "security hardening"]
```

#### Étape 2: Concept Extraction

```
Input: 5 topics
Output: 45 concepts bruts

Exemples:
- Concept 1:
  - name: "authentification" (FR)
  - type: PRACTICE
  - language: fr
  - confidence: 0.85
  - extraction_method: "ner_spacy"

- Concept 2:
  - name: "authentication" (EN)
  - type: PRACTICE
  - language: en
  - confidence: 0.88
  - extraction_method: "ner_spacy"

- Concept 3:
  - name: "Authentifizierung" (DE)
  - type: PRACTICE
  - language: de
  - confidence: 0.83
  - extraction_method: "ner_spacy"

- Concept 4:
  - name: "LDAP"
  - type: TOOL
  - language: en
  - confidence: 0.92
  - extraction_method: "ner_spacy"

- Concept 5:
  - name: "ISO 27001"
  - type: STANDARD
  - language: en
  - confidence: 0.95
  - extraction_method: "ner_spacy"
```

#### Étape 3: Semantic Indexing (Canonicalization)

```
Input: 45 concepts bruts (FR/EN/DE mixed)
Output: 18 concepts canoniques

Exemple de canonicalization:

CLUSTER 1 (similarity > 0.85):
- "authentification" (FR, conf: 0.85)
- "authentication" (EN, conf: 0.88)
- "Authentifizierung" (DE, conf: 0.83)
↓ CANONICAL CONCEPT 1:
- canonical_name: "authentication" (EN priorité)
- aliases: ["authentification", "Authentifizierung", "auth"]
- languages: ["en", "fr", "de"]
- type: PRACTICE
- unified_definition: "Process of verifying the identity of a user or system..."
- quality_score: 0.87
- hierarchy_parent: "Security Practice"

CLUSTER 2 (similarity > 0.85):
- "LDAP" (EN, conf: 0.92)
- "Lightweight Directory Access Protocol" (EN, conf: 0.90)
↓ CANONICAL CONCEPT 2:
- canonical_name: "LDAP"
- aliases: ["Lightweight Directory Access Protocol"]
- languages: ["en"]
- type: TOOL
- unified_definition: "Protocol for accessing and maintaining directory services..."
- quality_score: 0.91
- hierarchy_parent: "Authentication Tool"
- related_concepts: ["authentication", "Active Directory"]

CLUSTER 3 (no similar concepts):
- "ISO 27001" (EN, conf: 0.95)
↓ CANONICAL CONCEPT 3:
- canonical_name: "ISO 27001"
- aliases: ["ISO/IEC 27001"]
- languages: ["en"]
- type: STANDARD
- unified_definition: "International standard for information security management..."
- quality_score: 0.95
- hierarchy_parent: "Security Standard"
- related_concepts: ["compliance", "audit", "GDPR"]
```

#### Étape 4: Concept Linking

```
Input: 18 canonical concepts + document
Output: 32 connexions

Exemples:

CONNECTION 1:
- document_id: "SAP_HANA_Security_Guide"
- canonical_concept_name: "authentication"
- document_role: DEFINES (car guide/standard)
- similarity: 0.92
- context: "...authentication mechanisms including LDAP, Kerberos, and SAML..."

CONNECTION 2:
- document_id: "SAP_HANA_Security_Guide"
- canonical_concept_name: "ISO 27001"
- document_role: REFERENCES
- similarity: 0.78
- context: "...compliance with ISO 27001 security standards is recommended..."

CONNECTION 3:
- document_id: "SAP_HANA_Security_Guide"
- canonical_concept_name: "encryption"
- document_role: DEFINES
- similarity: 0.89
- context: "...data encryption at rest and in transit using SSL/TLS..."
```

#### Étape 5: Semantic Profile

```
SemanticProfile:
- document_id: "SAP_HANA_Security_Guide"
- overall_complexity: 0.68 (medium-high)
- domain: "security"
- total_topics: 5
- total_concepts: 45
- total_canonical_concepts: 18
- languages_detected: ["en", "fr", "de"]
- processing_time_ms: 18,500 (18.5s)
```

### Storage Phase

#### Neo4j Storage

```
Nœuds créés: 18 concepts
Relations créées: 45
- 12 RELATED_TO (top-5 similaires pour chaque concept)
- 8 PARENT_OF (hiérarchie)
- 25 MENTIONED_IN (concept ↔ document)

Exemple nœud Neo4j:
CREATE (c:Concept {
  canonical_name: "authentication",
  type: "PRACTICE",
  definition: "Process of verifying the identity...",
  aliases: ["authentification", "Authentifizierung", "auth"],
  languages: ["en", "fr", "de"],
  quality_score: 0.87,
  tenant_id: "default",
  created_at: "2025-10-15T10:30:00Z"
})

Exemple relation Neo4j:
CREATE (doc)-[:MENTIONED_IN {
  role: "DEFINES",
  similarity: 0.92,
  context: "...authentication mechanisms including..."
}]->(concept)
```

#### Qdrant Storage

```
Collection: concepts_proto
Vectors stockés: 18

Exemple point Qdrant:
{
  "id": "uuid-1234",
  "vector": [0.023, -0.145, 0.089, ...],  # 1024 dimensions
  "payload": {
    "canonical_name": "authentication",
    "concept_type": "PRACTICE",
    "unified_definition": "Process of verifying...",
    "aliases": ["authentification", "Authentifizierung", "auth"],
    "languages": ["en", "fr", "de"],
    "quality_score": 0.87,
    "tenant_id": "default",
    "neo4j_concept_id": "neo4j-node-id-123"
  }
}
```

### Résultat Final

```
OsmoseIntegrationResult:
- osmose_success: True
- concepts_extracted: 45
- canonical_concepts: 18
- topics_segmented: 5
- concept_connections: 32
- proto_kg_concepts_stored: 18 (Neo4j)
- proto_kg_relations_stored: 45 (Neo4j)
- proto_kg_embeddings_stored: 18 (Qdrant)
- osmose_duration_seconds: 18.5
- total_duration_seconds: 22.3

Status: ✅ COMPLETE
Document moved to: data/docs_done/SAP_HANA_Security_Guide.pptx
```

---

## 🎨 Prompt pour IA Génératrice d'Image

### Context pour l'IA

Vous devez créer une **infographie technique professionnelle** représentant le **pipeline d'ingestion OSMOSE** pour le produit **KnowWhere** (Le Cortex Documentaire des Organisations).

### Style Visuel

- **Type:** Diagramme de flux technique avec style moderne et épuré
- **Couleurs:**
  - Bleu océan (#0A7AFF) pour OSMOSE / composants principaux
  - Vert émeraude (#10B981) pour succès / outputs
  - Violet (#8B5CF6) pour IA/LLM
  - Gris slate (#64748B) pour infrastructure
  - Orange (#F59E0B) pour alertes / points critiques
- **Typographie:** Sans-serif moderne (Inter, Roboto, ou similaire)
- **Icônes:** Modernes, minimalistes, ligne fine

### Layout Principal

**Format:** Vertical (portrait), scroll adapté
**Sections:** 3 phases principales séparées visuellement

```
┌─────────────────────────────────────────────┐
│  HEADER: Logo KnowWhere + Titre Pipeline   │
├─────────────────────────────────────────────┤
│  PHASE 1: Extraction (Bleu clair)          │
│  - Document source                          │
│  - Vision AI analysis                       │
│  - Text enrichment                          │
├─────────────────────────────────────────────┤
│  PHASE 2: OSMOSE Core (Bleu océan)         │
│  - 4 composants en séquence verticale       │
│  - Icônes distinctes par composant          │
│  - Flèches avec métriques                   │
├─────────────────────────────────────────────┤
│  PHASE 3: Proto-KG Storage (Vert)          │
│  - Dual storage Neo4j + Qdrant              │
│  - Outputs métriques                        │
├─────────────────────────────────────────────┤
│  FOOTER: USP KnowWhere vs Copilot/Gemini   │
└─────────────────────────────────────────────┘
```

### Éléments Visuels Clés

#### 1. Document Source (Top)

- **Icône:** Document avec logo PPTX/PDF
- **Label:** "Document Source (PPTX, PDF)"
- **Sous-texte:** "Multilingue (EN/FR/DE/+)"
- **Flèche descendante** vers Phase 1

#### 2. Phase 1: Extraction (Bloc 1)

**Background:** Dégradé bleu clair (#E0F2FE → #BAE6FD)

**Composants:**

- **A. Images + Text Extraction**
  - **Icône:** Camera + Document
  - **Labels:** "50 slides → PNG", "Raw text + Notes"

- **B. GPT-4 Vision**
  - **Icône:** Eye + Brain (IA)
  - **Badge:** "GPT-4 Vision" (violet)
  - **Label:** "Visual Summaries Generation"
  - **Output:** "25k chars enriched"

- **C. Full Text Enriched**
  - **Icône:** Document empilé
  - **Label:** "40k chars TOTAL"

**Flèche épaisse** (bleu océan) vers Phase 2

#### 3. Phase 2: OSMOSE Core (Bloc Central - PRINCIPAL)

**Background:** Dégradé bleu océan (#0A7AFF → #0369A1)
**Badge en haut:** "🌊 OSMOSE V2.1 - Semantic Intelligence"

**4 composants verticaux avec cartes distinctes:**

##### Composant 1: Topic Segmentation 📐

**Carte:** Fond blanc, border bleu
- **Icône:** Grid/Segments
- **Titre:** "1. TopicSegmenter"
- **Sous-titre:** "Semantic windowing + clustering"
- **Technologies (badges):**
  - "multilingual-e5-large" (badge gris)
  - "HDBSCAN" (badge gris)
  - "spaCy NER" (badge gris)
- **Output métrique:** "5 topics" (badge vert)
- **Visual:** Mini graphique de segments colorés

##### Composant 2: Concept Extraction 🔎 ⚠️ CRITIQUE

**Carte:** Fond blanc, border orange (critique)
- **Icône:** Magnifying glass + 3 nodes
- **Titre:** "2. ConceptExtractor"
- **Badge:** "⚠️ CRITIQUE" (orange)
- **Sous-titre:** "Triple method: NER + Clustering + LLM"
- **3 méthodes (mini-badges horizontaux):**
  - "NER (0.85)" (bleu)
  - "Clustering (0.75)" (bleu)
  - "LLM (0.80)" (violet)
- **Technologies:**
  - "spaCy Transformers" (badge gris)
  - "gpt-4o-mini" (badge violet)
- **Output métrique:** "45 concepts" (badge vert)
- **Visual:** 3 cercles interconnectés (NER, Clustering, LLM)

##### Composant 3: Semantic Indexing 🌐 ⚠️ USP CRITIQUE

**Carte:** Fond dégradé or (#FEF3C7 → #FDE68A), border orange épais
- **Icône:** Globe + Merge/Unify symbol
- **Titre:** "3. SemanticIndexer"
- **Badge:** "✨ USP KnowWhere" (or)
- **Sous-titre:** "Cross-lingual canonicalization"
- **Visual clé:**
  - 3 concepts (FR/EN/DE) → 1 concept canonique
  - Flèches convergentes
  - Labels: "authentification (FR)" → "authentication (EN)" ← "Authentifizierung (DE)"
- **Features (mini-liste):**
  - ✓ Similarity 0.85
  - ✓ Hierarchy construction
  - ✓ Unified definition (LLM)
- **Technologies:**
  - "multilingual-e5-large" (badge gris)
  - "gpt-4o-mini" (badge violet)
- **Output métrique:** "18 canonical concepts" (badge vert)

##### Composant 4: Concept Linking 🔗

**Carte:** Fond blanc, border bleu
- **Icône:** Link/Chain + Document
- **Titre:** "4. ConceptLinker"
- **Sous-titre:** "DocumentRole classification + context"
- **5 DocumentRoles (badges horizontaux):**
  - "DEFINES" (vert)
  - "IMPLEMENTS" (bleu)
  - "AUDITS" (orange)
  - "PROVES" (violet)
  - "REFERENCES" (gris)
- **Output métrique:** "32 connections" (badge vert)
- **Visual:** Graph mini concept ↔ document

**Flèche épaisse** (vert) vers Phase 3

#### 4. Phase 3: Proto-KG Storage (Bloc 3)

**Background:** Dégradé vert (#D1FAE5 → #A7F3D0)

**Dual Storage (2 colonnes):**

##### Colonne A: Neo4j

- **Icône:** Graph nodes
- **Titre:** "Neo4j (Graph)"
- **Métriques:**
  - "18 concepts" (nœuds)
  - "45 relations" (edges)
- **Visual:** Mini graph avec nœuds et edges

##### Colonne B: Qdrant

- **Icône:** Vector/Dimensions
- **Titre:** "Qdrant (Vectors)"
- **Métriques:**
  - "18 embeddings (1024D)"
  - "Collection: concepts_proto"
- **Visual:** Représentation vectorielle (points dans espace)

**Center bottom:**
- **Badge final:** "✅ OSMOSE COMPLETE" (vert, large)
- **Métriques finales:**
  - "18.5s processing"
  - "18 canonical concepts"
  - "Proto-KG enriched"

#### 5. Footer: USP Banner

**Background:** Dégradé or (#FDE68A → #FCD34D)
**Titre:** "🌟 KnowWhere USP vs Microsoft Copilot / Google Gemini"

**3 colonnes comparatives:**

| **KnowWhere (OSMOSE)** | **Copilot** | **Gemini** |
|------------------------|-------------|------------|
| ✅ Cross-lingual unification AUTO | ❌ Mono-lingual | ❌ Mono-lingual |
| ✅ Language-agnostic KG | ❌ No unified KG | ❌ No unified KG |
| ✅ Triple extraction (NER+Cluster+LLM) | ⚠️ LLM only | ⚠️ LLM only |
| ✅ DocumentRole classification | ❌ Not available | ❌ Not available |
| ✅ Concept ↔ Document Graph | ❌ Not available | ❌ Not available |

**Icône KnowWhere:** Logo + tagline "Le Cortex Documentaire des Organisations"

---

### Annotations Techniques

**Sur chaque flèche de connexion entre composants:**
- Afficher le format de données transmis
- Exemples:
  - "full_text_enriched (40k chars)" entre Phase 1 → Phase 2
  - "List[Topic] (5 topics)" entre TopicSegmenter → ConceptExtractor
  - "List[Concept] (45 concepts)" entre ConceptExtractor → SemanticIndexer
  - "List[CanonicalConcept] (18 concepts)" entre SemanticIndexer → ConceptLinker
  - "Proto-KG Data" entre ConceptLinker → Storage

**Légende des badges de technologies:**
- Gris: Technologies infrastructure (spaCy, HDBSCAN, etc.)
- Violet: IA/LLM (GPT-4, gpt-4o-mini)
- Vert: Outputs/Success
- Orange: Critique/Important

---

### Prompt Final pour IA Génératrice

**Prompt complet à fournir à DALL-E, Midjourney, ou similaire:**

```
Create a professional technical infographic diagram showing the OSMOSE ingestion pipeline for KnowWhere (corporate knowledge management system).

STYLE:
- Modern, clean technical diagram
- Vertical layout (portrait orientation)
- Color scheme: Ocean blue (#0A7AFF) for main components, emerald green (#10B981) for outputs, purple (#8B5CF6) for AI/LLM, orange (#F59E0B) for critical sections
- Sans-serif typography (Inter or Roboto style)
- Minimalist line icons

LAYOUT (3 main phases):

1. HEADER:
- Logo "KnowWhere" with tagline "Le Cortex Documentaire"
- Title: "🌊 OSMOSE Ingestion Pipeline V2.1"

2. PHASE 1 - EXTRACTION (light blue gradient background):
- Document icon (PPTX/PDF) at top
- Arrow down to:
  - Camera + document icon: "Images + Text Extraction"
  - Eye + brain icon with purple badge "GPT-4 Vision": "Visual Summaries"
  - Stacked document icon: "Full Text Enriched (40k chars)"
- Thick blue arrow down labeled "full_text_enriched"

3. PHASE 2 - OSMOSE CORE (ocean blue gradient, main section):
- Large badge at top: "🌊 OSMOSE V2.1 - Semantic Intelligence"
- 4 white cards in vertical sequence:

  CARD 1 - TopicSegmenter:
  - Grid/segments icon
  - Title: "1. TopicSegmenter"
  - Subtitle: "Semantic windowing + clustering"
  - Tech badges: "multilingual-e5-large", "HDBSCAN", "spaCy"
  - Green output badge: "5 topics"
  - Mini visual: colored segment bars

  CARD 2 - ConceptExtractor (orange border - CRITICAL):
  - Magnifying glass + 3 nodes icon
  - Orange badge: "⚠️ CRITICAL"
  - Title: "2. ConceptExtractor"
  - Subtitle: "Triple method: NER + Clustering + LLM"
  - 3 method badges: "NER (0.85)" "Clustering (0.75)" "LLM (0.80)"
  - Tech badges: "spaCy Transformers", "gpt-4o-mini" (purple)
  - Green output badge: "45 concepts"
  - Mini visual: 3 interconnected circles labeled NER, Clustering, LLM

  CARD 3 - SemanticIndexer (gold gradient, thick orange border - USP):
  - Globe + merge icon
  - Gold badge: "✨ USP KnowWhere"
  - Title: "3. SemanticIndexer"
  - Subtitle: "Cross-lingual canonicalization"
  - KEY VISUAL: 3 concepts converging:
    "authentification (FR)" → "authentication (EN)" ← "Authentifizierung (DE)"
    with arrows merging into single concept
  - Feature checkmarks: "✓ Similarity 0.85", "✓ Hierarchy", "✓ Unified definition"
  - Tech badges: "multilingual-e5-large", "gpt-4o-mini"
  - Green output badge: "18 canonical concepts"

  CARD 4 - ConceptLinker:
  - Link/chain + document icon
  - Title: "4. ConceptLinker"
  - Subtitle: "DocumentRole classification"
  - 5 small badges: "DEFINES" "IMPLEMENTS" "AUDITS" "PROVES" "REFERENCES"
  - Green output badge: "32 connections"
  - Mini visual: graph showing concept-document connections

- Thick green arrow down labeled "Proto-KG Data"

4. PHASE 3 - STORAGE (green gradient background):
- Title: "Proto-KG Dual Storage"
- Two columns:

  LEFT - Neo4j:
  - Graph nodes icon
  - "Neo4j (Graph)"
  - Metrics: "18 concepts" "45 relations"
  - Mini graph visual with nodes and edges

  RIGHT - Qdrant:
  - Vector/dimensions icon
  - "Qdrant (Vectors)"
  - Metrics: "18 embeddings (1024D)" "Collection: concepts_proto"
  - Vector space visual with points

- Center bottom: Large green badge "✅ OSMOSE COMPLETE"
- Metrics: "18.5s processing | 18 canonical concepts | Proto-KG enriched"

5. FOOTER - USP BANNER (gold gradient):
- Title: "🌟 KnowWhere USP vs Microsoft Copilot / Google Gemini"
- 3-column comparison table:
  - Column 1 "KnowWhere": All green checkmarks (✅)
  - Column 2 "Copilot": Red X marks (❌) and warning symbols (⚠️)
  - Column 3 "Gemini": Red X marks (❌) and warning symbols (⚠️)
- Key differences:
  - Cross-lingual unification: ✅ vs ❌ ❌
  - Language-agnostic KG: ✅ vs ❌ ❌
  - Triple extraction: ✅ vs ⚠️ ⚠️
  - DocumentRole classification: ✅ vs ❌ ❌
  - Concept-Document Graph: ✅ vs ❌ ❌

TECHNICAL DETAILS:
- Show data flow annotations on all arrows (e.g., "List[Topic] (5 topics)")
- Include technology badges throughout (gray for infrastructure, purple for AI/LLM)
- Use consistent iconography (minimalist line style)
- Ensure text is readable at various sizes
- Maintain clear visual hierarchy with the OSMOSE Core phase as focal point
- Use the gold gradient + thick border to highlight the SemanticIndexer USP section
- Professional corporate tech aesthetic, suitable for technical documentation

Make it visually striking but information-dense, suitable for technical presentations to CTOs and engineering teams.
```

---

## 📚 Références

### Fichiers Source

- **Pipeline PPTX:** `src/knowbase/ingestion/pipelines/pptx_pipeline_osmose_pure.py`
- **Integration:** `src/knowbase/ingestion/osmose_integration.py`
- **Semantic Pipeline:** `src/knowbase/semantic/semantic_pipeline_v2.py`
- **TopicSegmenter:** `src/knowbase/semantic/segmentation/topic_segmenter.py`
- **ConceptExtractor:** `src/knowbase/semantic/extraction/concept_extractor.py`
- **SemanticIndexer:** `src/knowbase/semantic/indexing/semantic_indexer.py`
- **ConceptLinker:** `src/knowbase/semantic/linking/concept_linker.py`

### Documentation

- **Phase 1 Complete:** `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **Architecture OSMOSE:** `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- **Roadmap:** `doc/OSMOSE_ROADMAP_INTEGREE.md`

---

**Version:** 1.0
**Auteur:** OSMOSE Phase 1.5 Team
**Date:** 2025-10-15
**Usage:** Documentation technique + prompt IA génératrice d'image