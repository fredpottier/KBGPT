# Architecture Pipeline Stratifié OSMOSIS

> **Niveau de fiabilité** : Code-verified (Mars 2026). Décrit le pipeline tel qu'implémenté dans le code. Les sections sur les passes non encore actives sont marquées explicitement.

*Document consolidé — Mars 2026*
*Vérifié contre le code source (`src/knowbase/stratified/`, `src/knowbase/extraction_v2/`, `src/knowbase/structural/`)*

---

## 1. Vue d'ensemble

### 1.1 Philosophie : lire comme un humain

Le pipeline stratifié OSMOSIS repose sur un principe fondamental :

> **Comprendre la structure d'abord, extraire les détails ensuite.**

Un humain qui lit un document procède en 4 temps :
1. Comprendre le sujet global ("ce document parle de...")
2. Identifier la structure et les axes de raisonnement
3. Repérer les quelques concepts structurants (pas des milliers)
4. Attacher de l'information à ces concepts

Le pipeline reproduit cette séquence à travers une cascade de passes numérotées (Pass 0 → Pass 3), chacune s'appuyant sur les résultats de la précédente.

### 1.2 Anti-pattern : l'extraction exhaustive bottom-up (V1)

OSMOSIS V1 procédait chunk-par-chunk, puis tentait de valider des relations entre concepts fragmentés. Résultat mesuré :

| Métrique | V1 | Cible V2 |
|----------|------|----------|
| Concepts par document | ~4 000 | 20-50 |
| Information par concept | ~1 | 5-15 |
| Relations navigables | ~2% | >80% |
| Assertions hors-sujet | ~70% | <10% |
| Nodes pour 19 docs | 90 000+ | ~1 000-3 000 |

**Diagnostic** : le LLM était utilisé pour *valider des liens entre artefacts fragmentés* au lieu d'être utilisé pour *comprendre et structurer*.

### 1.3 Deux échecs symétriques (V1 vs V2.1)

| | V1 (bottom-up pur) | V2.1 (top-down pur) |
|---|---|---|
| **Approche** | Chunk → Concepts → Relations | GlobalView → Themes → Concepts → Assertions |
| **Échec** | Milliers d'orphelins, 2% relations | Concepts "hors-sol" inventés par le LLM |
| **Cause** | Extraction sans compréhension | Classification avant extraction |
| **Symptôme** | ~4 700 nodes/doc | SINK 34%, 37% concepts vides |

La V2.2 actuelle adopte une approche hybride "Extract-then-Structure" qui évite les deux pièges.

### 1.4 Architecture en passes

```
Pass 0    Parsing & Cache          Docling → DocItems, Sections, TypeAwareChunks
├ 0.5     Coréférence linguistique  Résolution pronominale (spaCy/coreferee)
├ 0.9     Global View              Meta-document 15-25K chars, couverture 100%

Pass 1    Extraction & Indexation
├ 1.1     Document Analysis         Subject + Structure + Themes
├ 1.2     Concept Identification    20-50 concepts frugaux
├ 1.2b    Concept Refinement        Saturation itérative (V2.1)
├ 1.2c    Trigger Enrichment        TF-IDF + Embedding
├ 1.3     Assertion Extraction      Pointer-Based, per-chunk
├ 1.3b    Anchor Resolution         chunk_id → docitem_id (CRITIQUE)
├ 1.4     Promotion & Linking       Information + AssertionLog

Pass 1.v22 (alternatif)            Extract-then-Structure (V2.2)
├ 1.A     Extraction locale         Assertions brutes par zone
├ 1.B     Clustering zone-first     HDBSCAN intra-zone + fusion inter-zones
├ 1.C     Structuration             Nommage + thèmes a posteriori
├ 1.D     Validation                Purity Gate + Budget Gate

Pass 2    Enrichissement            Relations inter-concepts
Pass 3    Consolidation corpus      Entity resolution → CanonicalConcept
```

**Fichiers d'orchestration** :
- `src/knowbase/extraction_v2/pipeline.py` — `ExtractionPipelineV2` (Pass 0)
- `src/knowbase/stratified/pass1/orchestrator.py` — `Pass1OrchestratorV2` (Pass 1 V2.1)
- `src/knowbase/stratified/pass1_v22/orchestrator.py` — `Pass1OrchestratorV22` (Pass 1 V2.2)
- `src/knowbase/stratified/pass2/orchestrator.py` — `Pass2OrchestratorV2`
- `src/knowbase/stratified/pass3/orchestrator.py` — `Pass3OrchestratorV2`

---

## 2. Pass 0 — Parsing & Cache

### 2.1 Docling : extracteur unifié

Depuis janvier 2026, Docling remplace MegaParse comme moteur d'extraction unique. Il gère nativement tous les formats Office.

**Classe** : `DoclingExtractor` (`src/knowbase/extraction_v2/extractors/docling_extractor.py`)

```
Formats supportés : PDF, DOCX, PPTX, XLSX, HTML, Markdown, images (PNG/JPG/TIFF/BMP/WebP)
```

| Configuration | Valeur |
|---------------|--------|
| `ocr_enabled` | `True` (actif par défaut) |
| `table_mode` | `"accurate"` |
| `image_resolution_scale` | `2.0` |

Le flux d'extraction par page produit des `VisionUnit` normalisées :
- `text_blocks[]` — blocs texte avec bbox
- `tables[]` — tables structurées (headers + cells)
- `visual_elements[]` — images raster, dessins vectoriels
- `page_dimensions` — largeur/hauteur en points

### 2.2 Structural Graph (Option C)

Le Structural Graph consomme la structure native de `DoclingDocument` au lieu de réinférer depuis le texte linéarisé (anti-pattern V1 : Linearizer → marqueurs → heuristiques).

**Constructeur** : `StructuralGraphBuilder` (`src/knowbase/structural/`)
**Modèles** : `src/knowbase/structural/models.py`
**Builder** : `src/knowbase/structural/docitem_builder.py`

#### Modèle DocItem

Atome structurel du document. Chaque élément Docling devient un `DocItem` avec :

| Champ | Type | Description |
|-------|------|-------------|
| `tenant_id` | str | Identifiant tenant |
| `doc_id` | str | Identifiant document |
| `doc_version_id` | str | Hash SHA-256 du DoclingDocument |
| `item_id` | str | = `self_ref` Docling (unique par version) |
| `item_type` | `DocItemType` | TEXT, HEADING, TABLE, FIGURE, LIST_ITEM, etc. |
| `text` | str | Texte brut ou Markdown normalisé pour TABLE |
| `page_no` | int | Page source |
| `reading_order_index` | int | Ordre de lecture déterministe |
| `charspan_start_docwide` | int | Position document-wide (Charspan Contract) |
| `charspan_end_docwide` | int | Fin document-wide |
| `bbox_x0..y1` | float | Bounding box (optional) |
| `section_id` | str | Section assignée |

#### Classification des types (ADR D3)

Les types de DocItems se répartissent en deux familles :

**Relation-bearing** (porteurs de sens extractible) :
```python
RELATION_BEARING_TYPES = {TEXT, HEADING, CAPTION, FOOTNOTE}
```

**Structure-bearing** (porteurs de structure, pas de relations) :
```python
STRUCTURE_BEARING_TYPES = {TABLE, FIGURE, CODE, FORMULA, FURNITURE, REFERENCE, OTHER}
```

**Cas spécial** — `LIST_ITEM` est relation-bearing si et seulement si la section a `is_relation_bearing == True` ET `list_ratio < 0.5`.

#### Ordre de lecture (ADR D2)

L'ordre de lecture est calculé par tri déterministe, pas par ordre des listes Python :

```
Règle de tri : page_no ASC → bbox.top ASC → bbox.left ASC → self_ref ASC (tie-breaker)
```

#### Assignment DocItem → Section (ADR D4)

Les sections sont créées depuis les `HEADING` dans l'ordre de lecture :
- Un HEADING de niveau N ouvre une section qui se termine au prochain HEADING de niveau ≤ N
- Tous les DocItems entre deux HEADING sont assignés à la section ouverte par le premier
- Fallback : section par page si aucun HEADING détecté
- La hiérarchie Docling native (`parent_item_id`, `group_id`) est conservée comme metadata mais non utilisée pour le modèle section

**Modèle SectionInfo** (`src/knowbase/structural/models.py`) :

| Champ | Type | Description |
|-------|------|-------------|
| `section_id` | str | Identifiant unique |
| `section_path` | str | "1. Introduction / 1.1 Overview" |
| `section_level` | int | Niveau hiérarchique |
| `structural_profile` | `StructuralProfile` | Profil calculé (ratios par type) |

#### StructuralProfile (ADR D10)

Calculé par nombre d'items (pas par volume texte ou surface) :

```python
is_relation_bearing = (text_count + heading_count + caption_count + footnote_count) / total > 0.5
is_structure_bearing = (table_count + figure_count + list_count) / total > 0.5
```

Les deux flags peuvent être simultanément `True` (section mixte texte + tableaux). Inclut un `relation_likelihood` et un `relation_likelihood_tier` (HIGH/MEDIUM/LOW/VERY_LOW) calculés par heuristiques sur le texte concaténé.

#### Conversion TABLE → texte (ADR D11)

Les tables sont converties en Markdown normalisé pour les embeddings :
- Maximum 50 lignes, 10 colonnes
- `table_json` stocké séparément comme source de vérité
- Si conversion échoue : `"[TABLE: parsing error]"` + log warning

Pour les FIGURE : `text = caption` si disponible, sinon chaîne vide `""`.

#### Versioning (ADR D1, D6)

```
DocumentContext (stable)
  └── DocumentVersion (doc_hash = SHA-256 canonisé)
        ├── PageContext
        ├── SectionContext
        └── DocItem[]
```

Le hash exclut les champs volatiles (`mtime`, `path`, `pipeline_version`, etc.) et arrondit les floats à 2 décimales. Format : `v1:{sha256}`.

### 2.3 TypeAwareChunks

Le chunking respecte les types de DocItems (`src/knowbase/structural/models.py: TypeAwareChunk`) :

| ChunkKind | Source | Propriété |
|-----------|--------|-----------|
| `NARRATIVE_TEXT` | TEXT, HEADING, CAPTION, FOOTNOTE | Divisible |
| `TABLE_TEXT` | TABLE | Atomique (ne jamais couper) |
| `FIGURE_TEXT` | FIGURE, VISION_PAGE | Atomique |
| `CODE_TEXT` | CODE | Atomique |

Chaque chunk porte :
- `kind: ChunkKind`
- `text: str`
- `item_ids: List[str]` — DocItems sources
- `page_no: int`
- `is_relation_bearing: bool`
- `text_origin: TextOrigin` — traçabilité (docling, vision_semantic, ocr, placeholder)

**Données empiriques** (corpus 28 docs) :
- Médiane TypeAwareChunks : 102 chars
- 20% des chunks > 1 000 chars
- vs DocItems atomiques : médiane 11 chars (70% < 100 chars)

### 2.4 Cache .knowcache.json

Le cache évite de re-parser les documents à chaque import. Il est stocké dans `data/extraction_cache/`.

**Classe** : `VersionedCache` (`src/knowbase/extraction_v2/cache/versioned_cache.py`)
**Loader** : `src/knowbase/stratified/pass0/cache_loader.py`

| Version | Contenu | Statut |
|---------|---------|--------|
| v1.0 (legacy) | pages[{slide_index, text}] + full_text | Rétrocompatible |
| v4 | full_text + pages + VisionUnits + GatingDecisions | Actif |
| v5 | v4 + DocItems sérialisés + TypeAwareChunks + VisionObservations | **Actuel** |

**Configuration** dans `PipelineConfig` :
```python
use_cache: bool = True
cache_version: str = "v5"
```

**Règle vitale** : les fichiers `.knowcache.json` dans `data/extraction_cache/` ne doivent JAMAIS être supprimés lors d'une purge système. Ils permettent de rejouer les imports sans re-extraction.

Le `CacheLoadResult` retourné contient :
- `pass0_result` — sections, chunks, doc_items
- `full_text` — contenu textuel complet
- `vision_observations` — observations Vision séparées (ADR-20260126)
- `retrieval_embeddings` / `retrieval_embeddings_path` — sidecar NPZ pour Layer R

### 2.5 Vision Gating V4

Décision déterministe et explicable par page/slide : faut-il appeler GPT-4o Vision ?

**Moteur** : `GatingEngine` (`src/knowbase/extraction_v2/gating/engine.py`)
**Signaux** : `src/knowbase/extraction_v2/gating/signals.py`
**Poids** : `src/knowbase/extraction_v2/gating/weights.py`

#### Les 5 signaux structurels

Chaque signal est mesurable, local, sans LLM :

| Signal | Code | Description | Score max |
|--------|------|-------------|-----------|
| **RIS** — Raster Image Signal | `compute_raster_image_score()` | Détecte images raster (area ratio ≥ 0.30 → 1.0) | 1.0 |
| **VDS** — Vector Drawing Signal | `compute_vector_drawing_score()` | Détecte diagrammes shapes (≥3 connecteurs → 1.0) | 1.0 |
| **TFS** — Text Fragmentation Signal | `compute_text_fragmentation_score()` | Texte dispersé en petits blocs (short_ratio ≥ 0.75 → 1.0) | 1.0 |
| **SDS** — Spatial Dispersion Signal | `compute_spatial_dispersion_score()` | Layout non linéaire (entropie spatiale) | 1.0 |
| **VTS** — Visual Table Signal | `compute_visual_table_score()` | Tables dessinées non reconnues | 1.0 |

#### Calcul du VNS (Vision Need Score)

```
VNS = 0.30*RIS + 0.30*VDS + 0.15*TFS + 0.15*SDS + 0.10*VTS
```

Le Domain Context peut ajuster les poids ±10% mais jamais les seuils absolus.

#### Seuils de décision

```
VNS ≥ 0.60  →  VISION_REQUIRED
0.40 ≤ VNS < 0.60  →  VISION_RECOMMENDED
VNS < 0.40  →  NO_VISION
```

**Règle de sécurité** : `RIS = 1.0` ou `VDS = 1.0` → force VISION_REQUIRED.

**Configuration pipeline** :
```python
vision_required_threshold: float = 0.60
vision_recommended_threshold: float = 0.40
include_recommended_in_vision: bool = True  # Par défaut, traite aussi RECOMMENDED
```

### 2.6 Vision Analyzer

Quand le Gating décide VISION_REQUIRED ou VISION_RECOMMENDED, le `VisionAnalyzer` est invoqué.

**Classe** : `VisionAnalyzer` (`src/knowbase/extraction_v2/vision/analyzer.py`)

Principes :
- Vision OBSERVE et DÉCRIT, ne raisonne pas
- Toute relation doit avoir une évidence visuelle
- Les ambiguïtés sont déclarées, jamais résolues implicitement
- Sortie JSON stricte conforme au schéma `VisionExtraction`

Le `VisionSemanticReader` (`src/knowbase/extraction_v2/vision/semantic_reader.py`) produit des `VisionSemanticResult` pour les pages FIGURE_TEXT.

**Routing adaptatif** (DiagramInterpreter) :
- `SKIP` : pas de contenu visuel
- `TEXT_ONLY` : texte OCR suffit
- `VISION_LITE` : prompt court, `detail=low` (VNS < 0.60)
- `VISION_FULL` : extraction structurée complète, `detail=high` (VNS ≥ 0.60)

**Quality Gate** : si `confidence < 0.70` → fallback prose (résumé texte classique).

### 2.7 Pass 0.5 — Coréférence linguistique

Résolution de coréférence pronominale avant les passes sémantiques.

**Pipeline** : `Pass05CoreferencePipeline` (`src/knowbase/ingestion/pipelines/pass05_coref.py`)

| Paramètre | Valeur par défaut |
|-----------|-------------------|
| `confidence_threshold` | 0.85 |
| `max_sentence_distance` | 2 |
| `skip_if_exists` | True (idempotent) |

### 2.8 Primitives Reducto-like (complètes depuis janvier 2026)

Quatre primitives inspirées de Reducto ont été intégrées sans abandonner l'architecture sémantique :

| Primitive | Fichier principal | Statut |
|-----------|------------------|--------|
| **QW-1 : Table Summaries** | `extraction_v2/tables/table_summarizer.py` | Complet |
| **QW-2 : Confidence Scores** | `extraction_v2/confidence/confidence_scorer.py` | Complet |
| **QW-3 : Diagram Interpreter** | `extraction_v2/vision/diagram_interpreter.py` | Complet |
| **MT-1 : Layout-Aware Chunking** | `extraction_v2/layout/layout_detector.py` | Complet |

**Table Summaries** — Le `TableSummarizer` génère des résumés en langage naturel pour chaque table. Format Linearizer enrichi : `[TABLE_SUMMARY]...[TABLE_RAW]...[TABLE_END]`. Intégré en ÉTAPE 4.5 du pipeline (après Merge, avant Linearisation). Batch processing avec concurrence limitée à 5 appels parallèles.

**Confidence Scores** — Deux niveaux :
- `parse_confidence` (heuristique, `ConfidenceScorer`) : 5 signaux (length, structure, ocr_quality, coherence, markers)
- `extract_confidence` (LLM, 0.0-1.0) : demandé dans le prompt d'extraction
- Filtrage automatique : concepts avec confidence < 0.4 rejetés

**Layout-Aware Chunking** — `LayoutDetector` détecte les régions structurelles :
- `RegionType.TABLE` et `RegionType.VISION` sont **atomiques** (ne jamais couper)
- `RegionType.PARAGRAPH`, `TITLE`, `TEXT` sont divisibles
- Validation `validate_no_cut_tables()` garantit 0 tableaux coupés

### 2.9 DocContext Extraction (ADR Assertion-Aware KG)

Enrichissement contextuel des documents pour le raisonnement comparatif.

**Composants** :
- `DocContextExtractor` (`src/knowbase/extraction_v2/context/doc_context_extractor.py`)
- `CandidateMiner` + `CandidateGate` (`extraction_v2/context/candidate_mining.py`)
- `AnchorContextAnalyzer` (`extraction_v2/context/anchor_context_analyzer.py`)
- `InheritanceEngine` (`extraction_v2/context/inheritance.py`)

**Processus en 2 étapes** :

1. **Candidate Mining (déterministe)** — Extraction de candidats markers depuis filename, premières pages, headers/footers, blocs revision. Patterns génériques (codes alphanumériques, versions, dates). `CandidateGate` avec 10+ filtres universels (dates, copyright, trimestres, etc.).

2. **LLM Validation** — Le LLM reçoit les candidats + texte et retourne :
   - `strong_markers` / `weak_markers` (sélectionnés parmi les candidats)
   - `doc_scope` : `GENERAL | VARIANT_SPECIFIC | MIXED`
   - `scope_confidence` + 5 signaux (marker_position, repeat, scope_language, diversity, conflict)

**Héritage conservatif** :
- `VARIANT_SPECIFIC` : héritage des strong_markers sauf override local
- `MIXED` : aucun héritage par défaut (risque contamination)
- `GENERAL` : scope = general, sauf markers locaux explicites

---

## 3. Pass 0.9 — Global View Construction

### 3.1 Problème résolu

Le pipeline V2 était "conceptuellement top-down mais opérationnellement myope" : Pass 1.1 ne voyait que les 2 premières pages (0.85% de couverture sur un document de 230 pages).

**Données mesurées** (document 020, 468K chars, 230 pages) :

| Phase | Chars passés au LLM | Couverture |
|-------|---------------------|------------|
| Pass 1.1 (avant) | 4 000 | 0.85% |
| Pass 1.2 (avant) | 5 000 | 1.07% |
| Pass 0.9 (après) | 15-25K | ~100% |

**Impact mesuré** :

| Métrique | Avant Pass 0.9 | Après | Amélioration |
|----------|----------------|-------|--------------|
| Thèmes | 7 | 15-25 | +200% |
| Concepts | 5 | 20-40 | +400% |
| Informations | 53 | 150-300 | +300% |

### 3.2 Architecture

**Fichiers** : `src/knowbase/stratified/pass09/`
- `global_view_builder.py` — `GlobalViewBuilder` (orchestrateur)
- `section_summarizer.py` — `SectionSummarizer` (résumé LLM par section)
- `hierarchical_compressor.py` — `HierarchicalCompressor` (compression en meta-document)
- `models.py` — `GlobalView`, `SectionSummary`, `GlobalViewCoverage`, `Pass09Config`, `Zone`

#### Étape 1 : Section Summarization (parallèle)

Pour chaque section du document :
- Input : texte de la section (ou chunks de la section)
- Output : résumé 500-1 000 chars (JSON : summary + concepts + assertion_types + key_values)
- Sections < 200 chars : skip
- Sections < 500 chars : copie verbatim
- Sections ≥ 500 chars : résumé LLM

**Budget LLM** (document 230 pages, ~432 sections) :
- ~50-100 appels (sections vides/courtes skippées)
- ~500 tokens input + 200 output par appel
- Temps estimé : 30-60s (parallélisé, `max_concurrent_summaries = 20`)

#### Étape 2 : Hierarchical Compression

- Concaténation structurée des résumés en respectant la hiérarchie (H1 > H2 > H3)
- Cible : meta-document 15-25K chars
- Limites : min 5K, max 30K

#### Output : GlobalView

```python
@dataclass
class GlobalView:
    tenant_id: str
    doc_id: str
    meta_document: str          # 15-25K chars, pour Pass 1.1/1.2
    section_summaries: Dict[str, SectionSummary]
    toc_enhanced: str           # TOC + résumés inline
    coverage: GlobalViewCoverage
    zones: List[Zone]           # Macro-sections (pour V2.2)
```

### 3.3 Rôle dans le pipeline

Le GlobalView est une **carte de navigation**, pas une taxonomie prescriptive.

> **Ligne rouge** : le GlobalView n'a pas le droit de produire des entités destinées à être persistées dans le KG (Themes, Concepts, Subjects). Toute structure persistée doit émerger exclusivement de Pass 1. Le moindre glissement vers "suggested themes" rouvre la porte à V2.1.

**Intégration** (`Pass1OrchestratorV2.process()`) :
```python
global_view = self.global_view_builder.build_sync(...)
analysis_content = global_view.meta_document  # Remplace les 4000 chars initiaux
```

### 3.4 Fallback

Si le budget LLM est dépassé ou en cas d'erreur : TOC + premiers 1 000 chars de chaque section (couverture garantie, précision dégradée).

**Couverture minimum** : 95% des sections doivent être traitées (`min_coverage_ratio = 0.95`).

---

## 4. Pass 1 — Extraction & Indexation

Deux implémentations coexistent :
- **V2.1** (`src/knowbase/stratified/pass1/`) — top-down guidé, production actuelle
- **V2.2** (`src/knowbase/stratified/pass1_v22/`) — extract-then-structure, expérimental

### 4.1 V2.1 : Pipeline top-down guidé

#### Phase 1.1 — Document Analysis

**Classe** : `DocumentAnalyzerV2` (`src/knowbase/stratified/pass1/document_analyzer.py`)

Depuis le meta-document (GlobalView) + TOC enrichie, le LLM identifie :
- **Subject** : sujet principal (1 par document)
- **Structure** : `CENTRAL | TRANSVERSAL | CONTEXTUAL`
- **Themes** : axes de raisonnement (5-18 selon budget)
- **Language** : détection automatique
- **is_hostile** : flag pour documents adverses

Le `char_limit` est adapté : 12 000 chars si GlobalView disponible, 4 000 sinon.

La langue est détectée sur le contenu original (avant GlobalView) pour éviter les biais du résumé.

#### Phase 1.2 — Concept Identification

**Classe** : `ConceptIdentifierV2` (`src/knowbase/stratified/pass1/concept_identifier.py`)

Identification frugale de 20-50 concepts par document. Un concept n'est créé que s'il porte plusieurs Information (règle anti-explosion).

**Trois rôles** (structures de dépendance des assertions) :

| Rôle | Définition | Test |
|------|------------|------|
| **CENTRAL** | Assertions dépendantes d'un artefact unique | "Sans X, ce document a-t-il un sens ?" → NON |
| **TRANSVERSAL** | Assertions indépendantes | "Si je remplace le nom propre, l'assertion reste vraie ?" → OUI |
| **CONTEXTUAL** | Assertions conditionnelles | "L'assertion commence par 'Si...', 'Quand...' ?" → OUI |

**Budget adaptatif** (invariant I3) :

| Taille document | Budget concepts | Budget thèmes |
|-----------------|----------------|---------------|
| < 50 pages | 10-20 | 3-7 |
| 50-150 pages | 20-40 | 5-12 |
| > 150 pages | 40-60 | 8-18 |

Le budget est une **contrainte épistémique**, pas une optimisation de performance.

**Critères de création ConceptSitué** (garde-fous) :
- ≥ 3 Information rattachées distinctes
- ≥ 2 types d'Information différents
- ≥ 2 sections/sous-thèmes couverts

Un concept hors budget n'est pas "faux" — il est "non admis dans la vérité courante du KG".

#### Phase 1.2b — Concept Refinement (V2.1)

**Classe** : `ConceptRefinerV2` (`src/knowbase/stratified/pass1/concept_refiner.py`)

Raffinement itératif : saturation des concepts par passes successives. Métriques de saturation calculées pour décider de la convergence.

#### Phase 1.2c — Trigger Enrichment

**Fonction** : `enrich_triggers()` (`src/knowbase/stratified/pass1/trigger_enricher.py`)

Enrichissement des triggers de détection par TF-IDF sur le corpus de chunks + embeddings.

#### Phase 1.3 — Assertion Extraction (Pointer-Based)

**Classe** : `AssertionExtractorV2` (`src/knowbase/stratified/pass1/assertion_extractor.py`)

Mode **Pointer-Based** (anti-reformulation) : le LLM doit citer le texte verbatim.

```
Tu lis un extrait d'un document technique. Extrais les affirmations factuelles,
prescriptions, définitions et procédures. Pour chaque assertion :
- Cite le texte original (ou paraphrase minimale)
- Indique le type (FACTUAL/PRESCRIPTIVE/DEFINITIONAL/PROCEDURAL)
```

**Types d'assertions** :
- `FACTUAL` — fait vérifiable
- `PRESCRIPTIVE` — règle, obligation
- `DEFINITIONAL` — définition
- `PROCEDURAL` — procédure, étape

**Performance observée** : taux ABSTAIN ~8.5% (le LLM s'abstient quand il ne trouve rien d'extractif).

Volume attendu : 300-1 000 assertions par document.

#### Phase 1.3b — Anchor Resolution

**Classe** : `AnchorResolverV2` (`src/knowbase/stratified/pass1/anchor_resolver.py`)

Phase **critique** : résolution chunk_id → docitem_id. Le mapping `build_chunk_to_docitem_mapping()` est construit depuis les TypeAwareChunks.

#### Phase 1.4 — Promotion & Linking

**Classes** :
- `PromotionEngine` (`src/knowbase/stratified/pass1/promotion_engine.py`)
- `PromotionPolicy` (`src/knowbase/stratified/pass1/promotion_policy.py`)

Les assertions brutes deviennent des `Information` ancrées ou sont classées UNLINKED.

**Invariant I6** (Abstention normale) :
> UNLINKED est un état de haute intégrité : il signifie que le système refuse de mentir. Un taux UNLINKED de 20% est infiniment préférable à un taux de 0% avec 30% d'associations fausses.

### 4.2 Charspan Contract v1

**Spécification** : `ADR_CHARSPAN_CONTRACT_V1.md`
**Implémenté dans** : `src/knowbase/structural/models.py`, `src/knowbase/structural/docitem_builder.py`

Le contrat définit la **Source of Truth** pour les positions textuelles :

**SoT = relation `ANCHORED_IN`** :
```
(ProtoConcept)-[r:ANCHORED_IN]->(DocItem)
```

Propriétés obligatoires sur l'edge :

| Propriété | Type | Description |
|-----------|------|-------------|
| `span_start` | int ≥ 0 | Relatif à `DocItem.text` |
| `span_end` | int > span_start | Relatif à `DocItem.text` |
| `anchor_quality` | enum | PRIMARY, DERIVED, APPROX, AMBIGUOUS |
| `anchor_method` | str | spacy_ner, llm, indexOf_fallback, regex |
| `anchor_id` | str | Clé unique `{proto_id}:{docitem_id}:{span_start}:{span_end}` |
| `surface_form` | str (opt) | Texte exact matché |

**Convention** : intervalles demi-ouverts `[start, end)`.

**Calcul docwide** :
```
anchor_start_docwide = DocItem.charspan_start_docwide + edge.span_start
```

**Qualité d'ancrage** :

| Valeur | Usage |
|--------|-------|
| `PRIMARY` | Spans extracteur primaire (NER/spaCy/LLM) |
| `DERIVED` | Transformation fiable et déterministe |
| `APPROX` | indexOf/fuzzy match — navigation only |
| `AMBIGUOUS` | Plusieurs matches — require disambiguation |

Les opérations de preuve stricte **doivent refuser** APPROX et AMBIGUOUS.

**Interdictions** :
- Ne jamais faire `p.char_start_docwide = d.charspan_start` (per-page !)
- Ne jamais stocker des spans docwide sur l'edge si l'edge pointe vers DocItem
- Ne jamais "réparer" silencieusement un anchor : tout fallback doit être tagué APPROX

### 4.3 V2.2 : Pipeline Extract-then-Structure

**Orchestrateur** : `Pass1OrchestratorV22` (`src/knowbase/stratified/pass1_v22/orchestrator.py`)

Le V2.2 inverse le flux : extraire les assertions d'abord, structurer ensuite. Il produit un `Pass1Result` compatible V2.1 pour que le Persister, Pass 2 et l'API fonctionnent sans modification.

#### Les 6 invariants

| Invariant | Nom | Protège contre |
|-----------|-----|----------------|
| **I1** | Set-before-Name | V2 : concepts inventés avant observations |
| **I2** | Zone-First | V1 : clustering global plat |
| **I3** | Budget adaptatif | V1 : explosion combinatoire |
| **I4** | No Empty Nodes | V1+V2 : concepts sans support |
| **I5** | Purity Gate | V2.2 : clusters pollués |
| **I6** | Abstention normale | V2 : routage forcé |

> **Ligne rouge I2** : aucun clustering global plat sur l'ensemble des assertions du document n'est autorisé. Toute similarité inter-zones doit passer par une étape explicite de fusion contrôlée.

#### Phase 1.A — Extraction locale d'assertions

**Classe** : `LocalAssertionExtractor` (`src/knowbase/stratified/pass1_v22/local_extractor.py`)

Pour chaque zone de la GlobalView, extraction section par section. Chaque assertion est ancrée (zone_id, section_id, page_no, docitem_id) mais pas classifiée.

#### Phase 1.B — Clustering zone-first

**Classe** : `ZoneFirstClusterer` (`src/knowbase/stratified/pass1_v22/zone_clusterer.py`)

1. **Intra-zone** : clustering sémantique par embeddings (HDBSCAN ou agglomératif)
   - Cluster de 1 assertion → UNLINKED (sauf fusion inter-zone)
   - Cluster de 2 assertions → draft
   - Cluster de 3+ assertions → candidate

2. **Inter-zones** : fusion par centroïdes
   - Cosinus > 0.85 → fusion automatique
   - 0.70-0.85 → fusion si keywords zone se recoupent
   - < 0.70 → pas de fusion

#### Phase 1.C — Structuration a posteriori

**Classe** : `StructureBuilder` (`src/knowbase/stratified/pass1_v22/structure_builder.py`)

Le LLM structure ce qui existe, il n'invente pas :
1. **Nommage** des clusters (max 5 mots + rôle CENTRAL/TRANSVERSAL/CONTEXTUAL)
2. **Regroupement** en thèmes par proximité sémantique + localité
3. **Identification** du sujet (1-3 sujets de haut niveau)

**Invariant I1** : le nom vient du contenu, pas d'un sommaire.

#### Phase 1.D — Validation

**Classe** : `ValidationGate` (`src/knowbase/stratified/pass1_v22/validation_gate.py`)

1. **Purity Check** : pour chaque concept avec 5+ assertions, échantillonnage de 5 assertions → "parlent-elles de la même chose ?". 3+ hors-sujet → split ou reject.

2. **Budget Gate** :
   - Trier concepts par `support_count` décroissant
   - Garder top-K selon budget (`compute_budget()`)
   - Reste → draft (consultable, hors KG actif)

**Statuts des concepts** (`ConceptStatus`) :
- `candidate` → peut devenir actif
- `draft` → hors KG, consultable
- `rejected` → purity check échoué

**Preuve par l'absurde** (cas SAC↔EDR) : dans V2.1, le LLM inventait "SAP Analytics Cloud" comme thème et des triggers larges matchaient des assertions EDR/sécurité. Dans V2.2, le concept ne peut pas émerger car aucun cluster d'assertions ne le supporte (I1 : set-before-name).

### 4.4 Linking et couverture

**Données empiriques** (V2.1 → V2.2) :

| Métrique | V2.1 | Cible V2.2 |
|----------|------|------------|
| Couverture (linking) | 11.7% → 81.9% | >85% |
| Concepts vides | 37% | < 5% |
| UNLINKED | 34% (considéré échec) | 15-25% (considéré normal) |
| Associations fausses | ~30% | < 5% |
| Precision concept→assertion (sondage humain) | non mesuré | > 85% |

---

## 5. Pass 2 — Enrichissement

### 5.1 Relations inter-concepts

**Orchestrateur** : `Pass2OrchestratorV2` (`src/knowbase/stratified/pass2/orchestrator.py`)
**Extracteur** : `RelationExtractorV2` (`src/knowbase/stratified/pass2/relation_extractor.py`)
**Persister** : `Pass2PersisterV2` (`src/knowbase/stratified/pass2/persister.py`)

Pass 2 enrichit le graphe sémantique avec les relations entre concepts identifiés en Pass 1.

**Principe** : les relations sont **médiées par l'Information**, pas par la co-occurrence textuelle.

**Taxonomie bornée des relations** :

| Relation | Sémantique | Exemple |
|----------|------------|---------|
| `PRECEDES` | Séquence temporelle/logique | IPSec → FWaaS |
| `REQUIRES` | Dépendance technique | FWaaS requires Network Config |
| `CONFIGURES` | Paramétrage | Admin configures FWaaS |
| `ENABLES` | Activation fonctionnelle | License enables Feature |
| `CONSTRAINS` | Limitation/restriction | Policy constrains Access |
| `EXCLUDES` | Incompatibilité | Option A excludes Option B |
| `IMPLEMENTS` | Réalisation concrète | FWaaS implements Firewall |
| `PART_OF` | Composition | Module part_of System |

**Règle** : toute relation hors taxonomie reste implicite (non matérialisée). Le graphe reste navigable, pas exhaustif.

**Relations structurelles** (certaines, hiérarchiques) :
```
FWaaS --[BELONGS_TO]--> Theme:Network Security
IPSec --[BELONGS_TO]--> Theme:Network Security
```
Ce n'est PAS une relation FWaaS↔IPSec. C'est deux relations indépendantes vers le même thème.

**Relations directes** (médiées par Information) :
```
Information: "Le trafic est chiffré via IPSec avant inspection par FWaaS"
→ IPSec --[PRECEDES_IN_FLOW]--> FWaaS
```
Le type de relation est inféré du contenu de l'Information.

### 5.2 Composants futurs (conçus, non implémentés)

- **Corpus Promotion (Pass 2.0)** — promotion tardive de concepts au niveau corpus
- **Structural Topics** — extraction de thèmes structurels depuis les sections
- **Normative Extraction** — extraction de règles normatives (MUST/SHOULD/MAY)
- **Semantic Consolidation** — fusion sémantique des Information redondantes

---

## 6. Pass 3 — Consolidation corpus

### 6.1 Entity Resolution

**Orchestrateur** : `Pass3OrchestratorV2` (`src/knowbase/stratified/pass3/orchestrator.py`)
**Résolveur** : `EntityResolverV2` (`src/knowbase/stratified/pass3/entity_resolver.py`)
**Persister** : `Pass3PersisterV2` (`src/knowbase/stratified/pass3/persister.py`)

**Deux modes** :
- `BATCH` — traitement complet du corpus
- `INCREMENTAL` — intégration d'un nouveau document

### 6.2 Clustering de concepts similaires

Les `ConceptSitué` (doc-level) de différents documents sont regroupés en `CanonicalConcept` (corpus-level).

**Processus** :
1. Calcul de similarité par embeddings
2. Clustering (seuil 0.85 cosinus)
3. Validation LLM des cas ambigus
4. Création `CanonicalConcept` avec relation `SAME_AS`

**Modèles** (`src/knowbase/stratified/pass3/entity_resolver.py`) :
- `ConceptCluster` — cluster de concepts similaires (concept_ids, similarity_scores)
- `ThemeCluster` — cluster de thèmes alignés
- `Pass3Result` — canonical_concepts, canonical_themes, stats

### 6.3 Règles anti-fusion naïve

> "Security" dans doc A ≠ "Security" dans doc B, sauf si meaning_signature et scope compatibles.

**Invariant meaning_signature** : une similarité embedding élevée ne suffit JAMAIS à justifier une fusion. Il faut concordance sur au moins 2 composantes structurées :
- Co-termes fréquents
- Verbes/actions
- Objets manipulés

En cas de doute, l'état `UNDECIDED` est explicitement accepté.

### 6.4 Volumétrie cible

| Entité | Par document | Pour 20 documents |
|--------|-------------|-------------------|
| Information (N0) | 200-500 | 5 000-10 000 |
| ConceptSitué (N1) | 20-50 | 400-800 |
| CanonicalConcept (N3) | — | 50-150 |

---

## 7. Modèles de données

### 7.1 Couche structurelle (preuve et audit)

Définis dans `src/knowbase/structural/models.py` :

| Modèle | Description | Champs clés |
|--------|-------------|-------------|
| `DocItem` | Atome documentaire | item_type, text, page_no, reading_order_index, charspan_*_docwide |
| `SectionInfo` | Section avec profil structurel | section_path, section_level, structural_profile |
| `PageContext` | Contexte de page | page_no, page_width, page_height |
| `DocumentVersion` | Version hashée | doc_version_id, is_current |
| `TypeAwareChunk` | Chunk typé | kind (NARRATIVE/TABLE/FIGURE/CODE), text, item_ids |
| `StructuralProfile` | Profil de section | ratios par type, is_relation/structure_bearing |
| `VisionObservation` | Observation Vision (hors KG) | description, diagram_type, key_entities |

### 7.2 Couche sémantique (compréhension et navigation)

Définis dans `src/knowbase/stratified/models/` :

| Modèle | Description | Champs clés |
|--------|-------------|-------------|
| `Subject` | Sujet principal | text, structure (CENTRAL/TRANSVERSAL/CONTEXTUAL) |
| `Theme` | Axe de raisonnement | label, description, parent_theme_id |
| `Concept` | Concept doc-level (20-50/doc) | name, role, triggers, theme_id |
| `Information` | Assertion ancrée | type, text, concept_id, anchor |
| `InformationMVP` | Assertion candidate | type, rhetorical_role, span_info, value_info |
| `Anchor` | Ancrage dans un DocItem | docitem_id, span_start, span_end, quality |
| `CanonicalConcept` | Concept corpus-level | merged_from, meaning_signature |
| `CanonicalTheme` | Thème corpus-level | aligned_themes |

### 7.3 Types d'Information

```python
class InformationType(str, Enum):
    DEFINITIONAL = "definitional"
    FACTUAL = "factual"
    PRESCRIPTIVE = "prescriptive"
    PROCEDURAL = "procedural"
    CAUSAL = "causal"
    CONDITIONAL = "conditional"
    COMPARATIVE = "comparative"
```

### 7.4 Types d'assertions (V1)

```python
class AssertionTypeV1(str, Enum):
    DEFINITION = "DEFINITION"
    CAPABILITY = "CAPABILITY"
    CONSTRAINT = "CONSTRAINT"
    LIMITATION = "LIMITATION"
    OPTION = "OPTION"
    FACT = "FACT"
    PROCESS = "PROCESS"
    CONDITION = "CONDITION"
```

### 7.5 Modèles contextuels (ADR Assertion-Aware KG)

| Modèle | Fichier | Description |
|--------|---------|-------------|
| `DocContextFrame` | `extraction_v2/context/models.py` | strong/weak markers, doc_scope, signals |
| `AnchorContext` | `extraction_v2/context/anchor_models.py` | polarity, scope, local_markers, is_override |
| `DocumentContext` | `extraction_v2/context/models.py` | Contexte documentaire complet |

**Polarity** : `positive | negative | future | deprecated | conditional | unknown`
**Scope** : `general | constrained | unknown`
**Override types** : `switch | range | generalization | null`

---

## 8. Vision — Décision architecturale

### 8.1 "Text is the Only Source of Truth for Knowledge Units"

**ADR** : ADR-20260126 — Vision Out of the Knowledge Path

**Axiome** :
> Pas d'assertion sans preuve localisable.

**Définition Knowledge Unit** : une assertion extraite textuellement (verbatim), transportable hors de son contexte narratif, ancrable de manière déterministe à un DocItem.

### 8.2 Données expérimentales

| Test | Configuration | InformationMVP | Ancrées | Anchor Rate |
|------|---------------|----------------|---------|-------------|
| Run 1 | Vision ON (prompt FR) | 831 | 149 | 17.9% |
| Run 2 | Vision ON (prompt EN) | 1 040 | 125 | 12.0% |
| Run 3 | Vision "Extractive Only" v3.0 | 1 066 | 151 | 14.2% |
| **Run 4** | **TEXT-ONLY (Vision OFF)** | **316** | **179** | **56.6%** |

**Cause racine** : mismatch de représentation. Vision produit des descriptions interprétatives ("The slide presents a Shared Security Responsibility Model...") alors que l'ancrage exige du texte extractif localisable. Même en demandant "verbatim only", Vision opère dans un espace différent de celui des DocItems.

**Preuve causale** : le test TEXT-ONLY prouve que Vision injecte ~750 assertions supplémentaires (1 066 - 316) qui sont majoritairement non-ancrables et dégradent mécaniquement le taux d'ancrage.

### 8.3 Séparation ontologique

**A) Knowledge Units (ancrables)** :
```
ExtractiveAssertion → InformationMVP → (si ancrée) Information
```
Contrat : `exact_quote` (verbatim) + ancre DocItem résolue.

**B) VisionObservation (non-ancrables)** :
```python
class VisionObservation(BaseModel):
    observation_id: str
    page_no: int
    diagram_type: Optional[str]   # "slide" | "table" | "diagram" | "form"
    description: str              # Texte descriptif (GPT-4o)
    key_entities: List[str]       # Entités détectées visuellement
    confidence: float
    model: str
```

**Restriction critique** : les VisionObservation ne participent PAS aux mécanismes de raisonnement, justification ou décision. Elles sont strictement informatives. Elles ne peuvent PAS être reliées à Concept ou Information.

### 8.4 Invariants système

| # | Invariant | Conséquence |
|---|-----------|-------------|
| **I1** | Toute Information doit être ancrée sur un DocItem | Pas d'Information "flottante" |
| **I2** | Aucun contenu non-extractif ne peut produire une InformationMVP | Vision exclu du flux Knowledge |
| **I3** | Toute amélioration du taux d'ancrage ne doit pas réduire la défendabilité de la preuve | Pas de fuzzy permissif |

### 8.5 Leviers d'amélioration de l'ancrage (sans fuzzy permissif)

Cible : 56.6% → ~65-75% (ordre de grandeur, jamais au détriment de la défendabilité).

| Levier | Description |
|--------|-------------|
| **A — Granularité DocItems** | DocItems atomiques, normalisation artefacts |
| **B — Renforcer l'extractif** | Exiger `exact_quote` verbatim, sinon ABSTAIN |
| **C — OCR ciblé** | Pages "non-textual dominant" → OCR → DocItems ancrables |
| **D — Ancrage déterministe** | Matching exact/near-exact après normalisation |
| **E — Réduire faux candidats** | Filtre interrogatif, boilerplate, fragments isolés |

---

## 9. Décisions clés & pistes écartées

### 9.1 Décisions retenues

| Décision | Date | Pourquoi |
|----------|------|----------|
| **Docling remplace MegaParse** | Jan 2026 | Extraction unifiée tous formats, tables structurées natives |
| **Structural Graph (Option C)** | Jan 2026 | Consomme la structure Docling directement, élimine réinférence |
| **Vision hors du chemin de connaissance** | Jan 2026 | Anchor rate 12-17% vs 56.6% TEXT-ONLY |
| **Charspan Contract v1** | Jan 2026 | Trois notions de position mélangées → contrat strict |
| **Lecture stratifiée top-down** | Jan 2025 | Mimétisme humain vs extraction bottom-up aveugle |
| **Extract-then-Structure (V2.2)** | Fév 2026 | Évite V2.1 "concepts inventés avant observations" |
| **GlobalView (Pass 0.9)** | Jan 2026 | 0.85% couverture → 100% couverture |
| **Assertion-Aware KG** | Jan 2026 | Raisonnement comparatif "what changed between A and B" |
| **6 invariants V2.2** | Fév 2026 | Garde-fous formels contre retour V1 ou V2.1 |

### 9.2 Pistes écartées

| Piste écartée | Pourquoi rejetée |
|---------------|------------------|
| **Schema-based extraction (Reducto)** | Philosophie incompatible : Reducto extrait des *champs*, OSMOSIS découvre des *concepts + relations* |
| **Full Reducto replacement** | Lock-in, coût, données sensibles, perte de contrôle |
| **LayoutLMv3 / DocTR** | Complexité excessive, heuristiques suffisent pour 80% des cas |
| **Baisser seuil fuzzy matching** | Augmente artificiellement l'anchor rate au prix de faux positifs. Casse invariant I3 |
| **Forcer Vision à être verbatim via prompt** | Test A/B : GPT-4o ne respecte pas "verbatim only". Gain marginal (+2.2 pts) |
| **Map/Reduce concepts (Option B pour Pass 0.9)** | Retour masqué au bottom-up (V1) |
| **Vision multi-page (Option D pour Pass 0.9)** | Hors-scope, coûteux |
| **Clustering global plat** | Explosion combinatoire (V1), violates I2 |
| **Co-occurrence = relation** | Proximité structurelle ≠ relation. FWaaS et IPSec dans le même thème mais jamais co-mentionnés → pas de relation directe |
| **Fusion par label** | "Security" dans doc A ≠ "Security" dans doc B |
| **Modèle Vision plus discipliné** | Le problème est structural (mismatch représentation), pas un problème de compliance |

---

## 10. Travaux non terminés

### 10.1 Implémentés mais en maturation

| Composant | Statut | Notes |
|-----------|--------|-------|
| Pass 1 V2.2 (Extract-then-Structure) | Code présent, expérimental | Compatible V2.1, même Pass1Result |
| Entity Resolution (Pass 3) | Code présent, non optimisé | Seuil 0.85 cosinus, LLM validation |
| Normative Extraction | Conçu | MUST/SHOULD/MAY détection |
| Evidence Bundle extended mode | Conçu | Multi-span evidence |

### 10.2 Conçus, non implémentés

| Composant | Description | Référence |
|-----------|-------------|-----------|
| **Corpus Promotion (Pass 2.0)** | Promotion tardive cross-doc | ADR Stratified Reading Model |
| **Coref Named-Named** | Résolution coréférence entre entités nommées | Au-delà de Pass 0.5 |
| **NormativeRules** | Extraction et stockage de règles normatives | ADR KG Quality Pipeline V3 |
| **Meaning Signature complète** | Embedding + co-termes + verbes/actions + objets | ADR Stratified, question ouverte |
| **Multi-Pass Verification (MT-2)** | LLM relit et corrige extractions Pass 1 | ADR Reducto (+30% LLM, -40% erreurs) |
| **Chart Extraction Pipeline (MT-3)** | Pipeline 3 stages pour graphiques | ADR Reducto |
| **Projection contextuelle (N2)** | Fermeture informationnelle au query-time | ADR Stratified §Niveau 2 |

### 10.3 Métriques à établir

| Métrique | Cible | Actuel |
|----------|-------|--------|
| Anchor Rate TEXT-ONLY | >65% | 56.6% |
| Purity check pass rate | >90% | Non mesuré |
| Precision concept→assertion | >85% | Non mesuré |
| Assertions extractives vs non | >95% | Non mesuré |

---

## 11. Stockage et flux de requête

### 11.1 Architecture bi-couche

```
QDRANT (texte + embeddings)              NEO4J (structure + références)
┌──────────────────────────────┐         ┌──────────────────────────────────┐
│  TypeAwareChunks             │         │  Information (N0) — LÉGER        │
│  - embedding (TEI)           │◄─anchor─│  - type (FACT, CONSTRAINT...)    │
│  - text                      │         │  - anchor {docitem_id, span}     │
│  - metadata (page, kind)     │         │  - concept_refs []               │
│                              │         │                                  │
│  Collections:                │         │  ConceptSitué (N1) — 20-50/doc  │
│  - knowbase (général)        │         │  ConceptCanonique (N3) — 50-150 │
│  - rfp_qa (Q/A prioritaire)  │         │  Theme, Subject                  │
│                              │         │  DocItem, SectionContext          │
│  Sub-chunks rechunked        │         │  VisionObservation (hors KG)     │
│  (target 1500, overlap 200)  │         │                                  │
└──────────────────────────────┘         └──────────────────────────────────┘
```

### 11.2 Flux de requête

```
Question utilisateur
       │
       ▼
Recherche vectorielle (Qdrant) → Chunks pertinents
       │
       ▼
Pour chaque chunk → récupérer Information ancrées (Neo4j via chunk_id)
       │
       ▼
Depuis Information → naviguer vers Concepts liés
       │
       ▼
Depuis Concepts → récupérer toutes leurs Information
       │
       ▼
Récupérer textes via anchors → Synthèse LLM
```

L'Information n'est pas cherchée par embedding. Elle est **atteinte** via :
- **Anchors** des chunks trouvés (vector search → Information)
- **Liens conceptuels** (Concept → Information)

### 11.3 Nœud Information (overlay, pas copie)

| Champ | Stocké | Description |
|-------|--------|-------------|
| `type` | Oui | FACT, CONSTRAINT, OPTION, CAPABILITY, etc. |
| `anchor` | Oui | Référence `{docitem_id, span_start, span_end}` |
| `concept_refs` | Oui | Liens vers ConceptSitué concernés |
| `theme_ref` | Oui | Lien vers le Theme parent |
| `text` | **NON** | Récupéré à la demande via anchor |

Le texte n'est jamais dupliqué. Il vit dans Qdrant. L'Information est un pointeur typé.

---

## 12. Références archive

Les documents sources de cet ADR consolidé sont archivés dans `doc/archive/pre-rationalization-2026-03/` :

| Document | Chemin archive | Contenu principal |
|----------|---------------|-------------------|
| Modèle de Lecture Stratifiée v2 | `adr/ADR_STRATIFIED_READING_MODEL.md` | Philosophie top-down, 3 structures de dépendance |
| Extract-then-Structure V2.2 | `ongoing/ADR_HYBRID_EXTRACT_THEN_STRUCTURE_2026-02-01.md` | 6 invariants, pipeline hybride |
| Structural Graph (Option C) | `adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` | DocItem, SectionContext, versioning |
| Reducto Parsing Primitives | `adr/ADR-20241230-reducto-parsing-primitives.md` | QW-1/2/3, MT-1, Vision Gating V4 |
| Assertion-Aware KG | `adr/ADR-20260104-assertion-aware-kg.md` | DocContextFrame, AnchorContext, Markers |
| Charspan Contract v1 | `adr/ADR_CHARSPAN_CONTRACT_V1.md` | Source of Truth = ANCHORED_IN |
| Vision Out of Knowledge Path | `ongoing/ADR-20260126-vision-out-of-knowledge-path.md` | Anchor rate 12-17% vs 56.6% |
| Pass 0.9 GlobalView | `ongoing/ADR_PASS09_GLOBAL_VIEW_CONSTRUCTION.md` | 0.85% → 100% couverture |
| Extraction Pipeline Architecture | `specs/extraction/SPEC-EXTRACTION_PIPELINE_ARCHITECTURE.md` | Flux PDF/PPTX complet |
| Vision Gating V4 | `specs/extraction/SPEC-VISION_GATING_V4.md` | 5 signaux, VNS, seuils |

---

*Dernière mise à jour : 2026-03-29*
*Vérifié contre le code source en branche `feat/wiki-concept-assembly-engine`*
