# Documentation Technique Exhaustive du Pipeline d'Ingestion V2

**Projet:** OSMOSE (Organic Semantic Memory Organization & Smart Extraction)
**Produit:** OSMOSIS
**Statut:** EN COURS DE RÉDACTION
**Date de création:** 2026-01-29
**Dernière MAJ:** 2026-01-29
**Branche:** `pivot/stratified-pipeline-v2`

---

## 1. Introduction

### 1.1 Objet du document

Ce document constitue la **référence technique exhaustive** du Pipeline d'Ingestion V2 (Pipeline Stratifié) d'OSMOSIS. Il décrit, pour chaque phase du pipeline, les entrants, objectifs, mécanismes/algorithmes retenus et sorties produites.

L'analyse croise systématiquement l'implémentation réelle avec les décisions architecturales (ADR) normatives pour identifier les déviations et risques par phase.

### 1.2 Périmètre

Ce document couvre l'intégralité du pipeline V2, du fichier source jusqu'au graphe sémantique consolidé :

- **Pass 0** — Extraction (Docling + Vision Gating V4)
- **Pass 0 Structural** — Construction du graphe structurel (Document → Section → DocItem)
- **Pass 0.5** — Résolution de coréférence linguistique
- **Pass 0.9** — Construction de la Vue Globale (meta-document)
- **Pass 1.1** — Analyse documentaire (Subject, Structure, Themes)
- **Pass 1.2** — Identification des concepts frugaux
- **Pass 1.3** — Extraction d'assertions typées
- **Pass 1.3b** — Résolution d'ancrage (chunk → DocItem)
- **Pass 1.4** — Promotion (Assertion → Information) + Value Contract + ClaimKey
- **Pass 2** — Enrichissement sémantique (relations inter-concepts)
- **Pass 3** — Consolidation corpus (entity resolution cross-document)

### 1.3 Hors périmètre

- Code du pipeline legacy (V1)
- Documentation frontend / UI V2
- Documentation des API endpoints V2
- Correction des déviations identifiées (seulement documentation)

### 1.4 Conventions

| Convention | Signification |
|------------|---------------|
| ✅ | Conforme à l'ADR/ARCH de référence |
| ⚠️ | Partiellement conforme ou déviation mineure |
| ❌ | Non conforme ou non implémenté |
| 🔴 | Risque critique |
| 🟡 | Risque modéré |
| 🟢 | Risque faible ou maîtrisé |

---

## 2. Références normatives

Cette section synthétise les axes de vérification extraits des 8 documents ADR/ARCH normatifs. Ces axes sont appliqués systématiquement à chaque phase du pipeline.

### 2.1 ADR North Star — Vérité Documentaire Contextualisée

**Document source :** `doc/ongoing/ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md`
**Statut :** ✅ VALIDÉ COMME NORTH STAR

**Principe fondateur :**

> OSMOSIS est le Knowledge Graph documentaire de l'entreprise et l'arbitre de sa vérité documentaire : il capture, structure et expose la connaissance telle qu'elle est exprimée dans le corpus documentaire, sans jamais extrapoler au-delà de ce corpus.

**10 axes de vérification North Star :**

| # | Axe | Description | Amendement |
|---|-----|-------------|------------|
| NS-1 | **Information-First** | L'Information est l'entité primaire, le Concept est optionnel. Zéro rejet pour `no_concept_match`. | Amdt 1 révisé |
| NS-2 | **LLM = Extracteur evidence-locked** | Le LLM extrait, il ne décide pas, n'infère pas, ne résout pas les contradictions. | Amdt 4 |
| NS-3 | **Citation exacte obligatoire** | Toute Information doit inclure `exact_quote` (verbatim) + `span` (page, paragraphe, ligne). | Amdt 4 |
| NS-4 | **Pas de synthèse cross-source** | Une Information = un document source. Pas de fusion multi-documents dans une Information. | Amdt 4 |
| NS-5 | **ClaimKey comme pivot** | Question factuelle canonique, indépendante du wording, pour comparaison cross-doc. Inférence en 2 niveaux (patterns + LLM assisté). | Amdt 3 + 5d |
| NS-6 | **Value Contract** | Extraction de valeurs normalisées (`raw`, `normalized`, `unit`, `operator`) pour comparaison machine. Statut `comparable: strict\|loose\|non_comparable`. | Amdt 5 |
| NS-7 | **Addressability-First** | Toute Information PROMOTED doit avoir ≥1 pivot navigable (Concept, Theme, ClaimKey, SectionPath, Facet). Orphelin total interdit. | Amdt 1 révisé |
| NS-8 | **Rhetorical Role** | Distinction fait/exemple/analogie/définition/instruction/claim/caution. Exemples et analogies ne génèrent pas de ClaimKey comparatif. | Amdt 6 |
| NS-9 | **Promotion Policy par type** | ALWAYS (DEFINITIONAL, PRESCRIPTIVE, CAUSAL), CONDITIONAL (FACTUAL, CONDITIONAL, PERMISSIVE), RARELY (COMPARATIVE), NEVER (PROCEDURAL). | §4 |
| NS-10 | **Déduplication par fingerprint** | `hash(claimkey + value.normalized + context_key + span_bucket)`. Même fait répété = merge evidence, pas 2 nodes. | Amdt 5c |

### 2.2 ADR Pass 0.9 — Global View Construction

**Document source :** `doc/ongoing/ADR_PASS09_GLOBAL_VIEW_CONSTRUCTION.md`
**Statut :** Référencé dans le plan d'implémentation (fichier absent du worktree actuel — axes extraits depuis ARCH V2 et spec)

**6 axes de vérification Pass 0.9 :**

| # | Axe | Description |
|---|-----|-------------|
| P09-1 | **Couverture 100% sections** | Le meta-document doit couvrir toutes les sections du document source |
| P09-2 | **Compression hiérarchique** | Préservation de la structure H1 > H2 > H3 dans la compression |
| P09-3 | **Meta-document 15-25K chars** | Taille cible pour tenir dans le contexte LLM des passes suivantes |
| P09-4 | **95% minimum sections résumées** | Seuil de couverture minimale acceptable |
| P09-5 | **Fallback mode (Option C)** | Mode dégradé opérationnel si résumé échoue |
| P09-6 | **Intégration dans Pass 1.1 et 1.2** | Le meta-document alimente l'analyse documentaire et l'identification de concepts |

### 2.3 ARCH Stratified Pipeline V2

**Document source :** `doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md`
**Statut :** EN CONCEPTION (validé par POC)

**Principes fondateurs :**
1. **Frugalité** — Moins de nodes, plus de valeur par node (~195 nodes/doc vs ~4700 legacy)
2. **Top-Down** — Structure → Concepts → Informations (inversion du flux V1 bottom-up)
3. **Promotion Policy** — Seules les assertions défendables deviennent Information
4. **Overlay** — Information = pointeur vers source, pas copie
5. **Indépendance** — Pipeline V2 coexiste avec legacy jusqu'à validation

**10 axes de vérification ARCH V2 :**

| # | Axe | Description |
|---|-----|-------------|
| AV2-1 | **Séparation structure documentaire / sémantique** | Structure documentaire (Document, Section, DocItem) ≠ Structure sémantique (Subject, Theme, Concept, Information) |
| AV2-2 | **8 types de nodes maximum** | Document, Section, DocItem, Subject, Theme, Concept, Information, AssertionLog |
| AV2-3 | **Ancrage Information sur DocItem** | Information `-[:ANCHORED_IN]->` DocItem. PAS sur chunk Qdrant. |
| AV2-4 | **DocItem atomique** | DocItem = item Docling natif (paragraph, table-row, list-item, heading, figure-caption). Pas de fusion agressive. |
| AV2-5 | **AssertionLog avec statut enum** | `PROMOTED \| ABSTAINED \| REJECTED` avec `AssertionLogReason` standardisé (10+ raisons) |
| AV2-6 | **Frugalité concepts (5-15 max)** | Garde-fou max 15 concepts par document, refus termes génériques et mentions uniques |
| AV2-7 | **Top-down** | Document Analysis (1.1) → Concept Identification (1.2) → Assertion Extraction (1.3) → Linking (1.4) |
| AV2-8 | **Dual storage** | Neo4j (graphe sémantique navigable) + Qdrant (TypeAwareChunks retrieval vectoriel) |
| AV2-9 | **Pass 3 mode manuel + batch** | Résolution d'entités en mode batch ou incrémental, pas automatique inline |
| AV2-10 | **< 250 nodes/document** | Estimation ~195 nodes/doc, soit ~4% du legacy |

### 2.4 ADR complémentaires

#### 2.4.1 ADR Modèle de Lecture Stratifiée

**Document source :** `doc/ongoing/ADR_STRATIFIED_READING_MODEL.md`

Formalise l'inversion du flux V1 → V2 (bottom-up → top-down). Définit les 3 structures universelles de dépendance des assertions :

| Structure | Définition | Test |
|-----------|------------|------|
| **CENTRAL** | Assertions dépendantes d'un artefact unique | "Sans X, ce document a-t-il un sens ?" → NON |
| **TRANSVERSAL** | Assertions indépendantes | Remplacer le nom propre → assertion reste vraie |
| **CONTEXTUAL** | Assertions conditionnelles | Vraies uniquement sous certaines conditions |

Définit les critères de création de ConceptSitué : ≥3 informations distinctes, ≥2 types différents, ≥2 sections/sous-thèmes.

#### 2.4.2 ADR Scope vs Assertion Separation

**Document source :** `doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md`
**Statut :** ✅ APPROVED — ARCHITECTURAL FOUNDATION — BLOCKING

Séparation fondamentale entre :
- **Scope Layer** (dense) : Ce que le document couvre → Navigation, non traversable
- **Assertion Layer** (sparse) : Ce que le document affirme → Raisonnement, traversable

Le Scope mining est un filtre de candidats, pas un générateur d'assertions. Le contexte documentaire (titre, section) ne constitue pas une preuve locale.

#### 2.4.3 ADR Relations Discursivement Déterminées

**Document source :** `doc/ongoing/ADR_DISCURSIVE_RELATIONS.md`
**Statut :** ACCEPTED

Extension pour les relations reconstructibles par un lecteur rigoureux sans connaissance externe :
- `AssertionKind` : EXPLICIT / DISCURSIVE
- `DiscursiveBasis` : ALTERNATIVE, DEFAULT, EXCEPTION, SCOPE, COREF, ENUMERATION
- Whitelist stricte des `RelationType` autorisés pour DISCURSIVE (V1)
- Promotion via `DefensibilityTier` : STRICT / EXTENDED

#### 2.4.4 ADR NormativeRule & SpecFact

**Document source :** `doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md`
**Statut :** ✅ APPROVED — V1

Capture des informations "high-value" non-relationnelles :
- **NormativeRule** : obligations/interdictions avec marqueur modal (MUST, SHOULD, MAY)
- **SpecFact** : valeurs structurées issues de tables/listes clé-valeur

Extraction pattern-first, preuve locale obligatoire, non-traversable, scope-only applicability.

---

## 3. Table des matières détaillée

- [1. Introduction](#1-introduction)
- [2. Références normatives](#2-références-normatives)
  - [2.1 ADR North Star](#21-adr-north-star--vérité-documentaire-contextualisée)
  - [2.2 ADR Pass 0.9](#22-adr-pass-09--global-view-construction)
  - [2.3 ARCH Stratified Pipeline V2](#23-arch-stratified-pipeline-v2)
  - [2.4 ADR complémentaires](#24-adr-complémentaires)
- [4. Vue d'ensemble du Pipeline V2](#4-vue-densemble-du-pipeline-v2)
- [5. Pass 0 — Extraction](#5-pass-0--extraction)
  - [5.1 Docling Extraction](#51-docling-extraction)
  - [5.2 Vision Gating V4](#52-vision-gating-v4)
  - [5.3 Vision Path (GPT-4o)](#53-vision-path-gpt-4o)
  - [5.4 Structured Merge](#54-structured-merge)
  - [5.5 Linéarisation](#55-linéarisation)
  - [5.6 Extraction de Contexte Documentaire](#56-extraction-de-contexte-documentaire)
  - [5.7 Table Summarizer](#57-table-summarizer)
  - [5.8 Cache Versionné](#58-cache-versionné)
  - [5.9 Conformité ADR — Pass 0 Extraction](#59-conformité-adr--pass-0-extraction)
  - [5.10 Risques — Pass 0 Extraction](#510-risques--pass-0-extraction)
- [6. Pass 0 Structural — Graphe Structurel](#6-pass-0-structural--graphe-structurel)
  - [6.1 Adapter Docling → Schema V2](#61-adapter-docling--schema-v2)
  - [6.2 Construction du graphe (Document, Section, DocItem)](#62-construction-du-graphe-document-section-docitem)
  - [6.3 Conformité ADR — Pass 0 Structural](#63-conformité-adr--pass-0-structural)
  - [6.4 Risques — Pass 0 Structural](#64-risques--pass-0-structural)
- [7. Pass 0.5 — Résolution de Coréférence Linguistique](#7-pass-05--résolution-de-coréférence-linguistique)
  - [7.1 Mécanismes de résolution](#71-mécanismes-de-résolution)
  - [7.2 Conformité ADR — Pass 0.5](#72-conformité-adr--pass-05)
  - [7.3 Risques — Pass 0.5](#73-risques--pass-05)
- [8. Pass 0.9 — Construction de la Vue Globale](#8-pass-09--construction-de-la-vue-globale)
  - [8.1 SectionSummarizer](#81-sectionsummarizer)
  - [8.2 HierarchicalCompressor](#82-hierarchicalcompressor)
  - [8.3 GlobalView (meta-document)](#83-globalview-meta-document)
  - [8.4 Conformité ADR — Pass 0.9](#84-conformité-adr--pass-09)
  - [8.5 Risques — Pass 0.9](#85-risques--pass-09)
- [9. Pass 1.1 — Analyse Documentaire](#9-pass-11--analyse-documentaire)
  - [9.1 Détection de structure (CENTRAL/TRANSVERSAL/CONTEXTUAL)](#91-détection-de-structure)
  - [9.2 Identification Subject et Themes](#92-identification-subject-et-themes)
  - [9.3 Conformité ADR — Pass 1.1](#93-conformité-adr--pass-11)
  - [9.4 Risques — Pass 1.1](#94-risques--pass-11)
- [10. Pass 1.2 — Identification des Concepts](#10-pass-12--identification-des-concepts)
  - [10.1 Extraction LLM de concepts frugaux](#101-extraction-llm-de-concepts-frugaux)
  - [10.2 Concept Refinement (Pass 1.2b)](#102-concept-refinement-pass-12b)
  - [10.3 Trigger Enrichment TF-IDF + Embedding (Pass 1.2c)](#103-trigger-enrichment-tf-idf--embedding-pass-12c)
  - [10.4 SINK Concept Injection (Pass 1.2d)](#104-sink-concept-injection-pass-12d)
  - [10.5 Conformité ADR — Pass 1.2](#105-conformité-adr--pass-12)
  - [10.6 Risques — Pass 1.2](#106-risques--pass-12)
- [11. Pass 1.3 — Extraction d'Assertions](#11-pass-13--extraction-dassertions)
  - [11.1 Mode pointeur et extraction par chunk](#111-mode-pointeur-et-extraction-par-chunk)
  - [11.2 Validation verbatim](#112-validation-verbatim)
  - [11.3 Indexation des unités d'assertion](#113-indexation-des-unités-dassertion)
  - [11.4 Conformité ADR — Pass 1.3](#114-conformité-adr--pass-13)
  - [11.5 Risques — Pass 1.3](#115-risques--pass-13)
- [12. Pass 1.3b — Résolution d'Ancrage](#12-pass-13b--résolution-dancrage)
  - [12.1 Mapping chunk_id → docitem_id](#121-mapping-chunk_id--docitem_id)
  - [12.2 Conformité ADR — Pass 1.3b](#122-conformité-adr--pass-13b)
  - [12.3 Risques — Pass 1.3b](#123-risques--pass-13b)
- [13. Pass 1.4 — Promotion et Value Contract](#13-pass-14--promotion-et-value-contract)
  - [13.1 Promotion Engine (Assertion → Information)](#131-promotion-engine-assertion--information)
  - [13.2 Promotion Policy par type d'assertion](#132-promotion-policy-par-type-dassertion)
  - [13.3 Value Extractor (Value Contract)](#133-value-extractor-value-contract)
  - [13.4 ClaimKey — Patterns et gestion de statut](#134-claimkey--patterns-et-gestion-de-statut)
  - [13.5 AssertionLog et gouvernance](#135-assertionlog-et-gouvernance)
  - [13.6 Theme Lint (gouvernance thématique)](#136-theme-lint-gouvernance-thématique)
  - [13.7 Conformité ADR — Pass 1.4](#137-conformité-adr--pass-14)
  - [13.8 Risques — Pass 1.4](#138-risques--pass-14)
- [14. Pass 2 — Enrichissement Sémantique](#14-pass-2--enrichissement-sémantique)
  - [14.1 Extraction de relations inter-concepts](#141-extraction-de-relations-inter-concepts)
  - [14.2 Types de relations et garde-fous](#142-types-de-relations-et-garde-fous)
  - [14.3 Conformité ADR — Pass 2](#143-conformité-adr--pass-2)
  - [14.4 Risques — Pass 2](#144-risques--pass-2)
- [15. Pass 3 — Consolidation Corpus](#15-pass-3--consolidation-corpus)
  - [15.1 Entity Resolution (embedding + clustering)](#151-entity-resolution-embedding--clustering)
  - [15.2 Theme Alignment cross-document](#152-theme-alignment-cross-document)
  - [15.3 Détection de contradictions](#153-détection-de-contradictions)
  - [15.4 Modes batch et incrémental](#154-modes-batch-et-incrémental)
  - [15.5 Conformité ADR — Pass 3](#155-conformité-adr--pass-3)
  - [15.6 Risques — Pass 3](#156-risques--pass-3)
- [16. Orchestration Pipeline](#16-orchestration-pipeline)
  - [16.1 Séquencement global (watcher → dispatcher → pipeline)](#161-séquencement-global)
  - [16.2 Feature flag routing V1/V2](#162-feature-flag-routing-v1v2)
  - [16.3 Burst Mode](#163-burst-mode)
  - [16.4 Conformité ADR — Orchestration](#164-conformité-adr--orchestration)
- [17. Modèle de données complet](#17-modèle-de-données-complet)
  - [17.1 Hiérarchie des 8 types de nodes](#171-hiérarchie-des-8-types-de-nodes)
  - [17.2 Schéma Neo4j V2](#172-schéma-neo4j-v2)
  - [17.3 Dual Storage (Neo4j + Qdrant)](#173-dual-storage-neo4j--qdrant)
- [18. Synthèse globale des risques](#18-synthèse-globale-des-risques)
  - [18.1 Risques critiques (🔴)](#181-risques-critiques-)
  - [18.2 Risques modérés (🟡)](#182-risques-modérés-)
  - [18.3 Risques faibles (🟢)](#183-risques-faibles-)
  - [18.4 Matrice de priorisation](#184-matrice-de-priorisation)
- [19. Diagramme d'architecture global](#19-diagramme-darchitecture-global)
- [20. Conclusion](#20-conclusion)

---

## 4. Vue d'ensemble du Pipeline V2

<!-- À compléter : diagramme ASCII du flux global Pass 0 → 0.5 → 0.9 → 1.x → 2 → 3 -->

---

## 5. Pass 0 — Extraction

### 5.0 Vue d'ensemble Pass 0

**Fichier orchestrateur :** `src/knowbase/extraction_v2/pipeline.py` — classe `ExtractionPipelineV2`

**Objectif :** Transformer un fichier source (PDF, DOCX, PPTX, XLSX, Image) en un `ExtractionResult` structuré contenant :
- `full_text` linéarisé avec marqueurs sémantiques (pour les passes suivantes)
- `structure` complète (pages, blocs, tables, enrichissements Vision)
- `doc_context` (DocContextFrame — marqueurs de version, scope documentaire)
- `page_index` (mapping offsets → pages pour traçabilité)
- `gating_decisions` et `vision_results` (audit du path Vision)

**Entrants :**

| Entrant | Type | Description |
|---------|------|-------------|
| `file_path` | `str` | Chemin vers le fichier source |
| `document_id` | `str` (optionnel) | ID unique du document (généré via SHA256 si absent) |
| `tenant_id` | `str` (optionnel) | Tenant pour Domain Context (défaut : `"default"`) |

**Séquence d'exécution (8 étapes) :**

```
Étape 1: Cache Check (VersionedCache)
  ↓ miss
Étape 2: Extraction Docling → List[VisionUnit]
  ↓
Étape 3: Vision Gating V4 → List[GatingDecision]
  ↓
Étape 4: Vision Path GPT-4o (parallèle, semaphore) → Dict[int, VisionExtraction]
  ↓
Étape 4.5: Vision Semantic Reader (parallèle) → Dict[int, VisionSemanticResult]
  ↓
Étape 5: Structured Merge → List[MergedPageOutput]
  ↓
Étape 5.5: Table Summaries (QW-1, batch) → summaries attachées aux TableData
  ↓
Étape 6: Linéarisation → (full_text, page_index)
  ↓
Étape 7: DocContext Extraction (6a: DocumentContext + 6b: DocContextFrame)
  ↓
Étape 8: Structural Graph (Option C) → StructuralGraphBuildResult
  ↓
Étape 8.25: Enrichissement FIGURE_TEXT avec Vision Semantic
  ↓
Étape 8.5: Pass 0.5 Linguistic Coref (si non-V2)
  ↓
Construction ExtractionResult + Cache Save
```

**Configuration :** `PipelineConfig` (dataclass avec ~20 paramètres) — tous les composants sont activables/désactivables via flags booléens.

**Métriques :** `PipelineMetrics` (dataclass) — temps par étape, compteurs de pages, taux de succès Vision, etc.

---

### 5.1 Docling Extraction

**Fichier :** `src/knowbase/extraction_v2/extractors/docling_extractor.py` — classe `DoclingExtractor`

**Objectif :** Convertir tout fichier source en une liste normalisée de `VisionUnit` (une par page/slide) via la bibliothèque Docling (>= 2.14.0).

#### 5.1.1 Formats supportés

| Extension | Format interne | Dimensions par défaut |
|-----------|---------------|----------------------|
| `.pdf` | PDF | 612 × 792 (Letter, en points) |
| `.docx` | DOCX | 612 × 792 |
| `.pptx` | PPTX | 960 × 540 (16:9 HD) |
| `.xlsx` | XLSX | 612 × 792 |
| `.html` | HTML | 612 × 792 |
| `.md` | Markdown | 612 × 792 |
| `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp` | Image | 1920 × 1080 (HD) |

#### 5.1.2 Configuration Docling

```python
DoclingExtractor(
    ocr_enabled=True,       # OCR activé pour images/scans
    table_mode="accurate",  # Extraction précise des tables
    image_resolution_scale=2.0  # Facteur de résolution images
)
```

Le pipeline PDF utilise `PyPdfiumDocumentBackend` avec `PdfPipelineOptions(do_ocr=True, do_table_structure=True)`.

#### 5.1.3 Mécanisme d'extraction

1. **Détection format** : Extension → format interne via `SUPPORTED_FORMATS`
2. **Conversion Docling** : `self._converter.convert(path)` → `DoclingResult`
3. **Itération pages** : Parcours du dict `doc.pages` (clés 1-indexed dans Docling ≥ 2.66)
4. **Pour chaque page**, extraction de :

| Composant | Méthode | Sortie |
|-----------|---------|--------|
| Blocs de texte | `_extract_text_blocks()` | `List[TextBlock]` — type (paragraph, heading, list_item, caption), bbox, level |
| Tables | `_extract_tables()` | `List[TableData]` — headers, cells, bbox, num_rows/cols, `is_structured=True` |
| Éléments visuels | `_extract_visual_elements()` | `List[VisualElement]` — kind="raster_image", bbox (via `doc.pictures`) |
| Titre de page | `_detect_title()` | Premier heading de level ≤ 2 (limité à 200 chars) |

5. **Construction VisionUnit** : Chaque page produit un objet `VisionUnit(id, format, index, dimensions, blocks, tables, visual_elements, title)`

#### 5.1.4 Variante `extract_to_units_with_docling()`

Retourne aussi le `DoclingDocument` brut, nécessaire pour le Structural Graph Builder (Option C) qui accède à la structure native Docling sans re-parser.

#### 5.1.5 Sortie

```
List[VisionUnit] — une VisionUnit par page/slide
  ├── id: "PDF_PAGE_0", "PPTX_PAGE_5"...
  ├── format: "PDF", "PPTX"...
  ├── index: 0, 1, 2... (0-based)
  ├── dimensions: (width, height)
  ├── blocks: List[TextBlock]
  ├── tables: List[TableData]
  ├── visual_elements: List[VisualElement]
  └── title: Optional[str]
```

---

### 5.2 Vision Gating V4

**Fichiers :** `src/knowbase/extraction_v2/gating/engine.py`, `signals.py`, `weights.py`
**Classe principale :** `GatingEngine`
**Spécification :** `VISION_GATING_V4_SPEC.md`

**Objectif :** Décider, pour chaque page/slide, si l'analyse Vision (GPT-4o) est nécessaire, recommandée, ou inutile. Ceci optimise les coûts en évitant les appels Vision sur des pages purement textuelles.

#### 5.2.1 Les 5 signaux

Le système calcule 5 signaux indépendants, chacun entre 0.0 et 1.0 :

| Signal | Nom complet | Ce qu'il détecte | Formule | Poids |
|--------|------------|-------------------|---------|-------|
| **RIS** | Raster Image Signal | Images raster significatives | `largest_image_ratio ≥ 0.30 → 1.0`, `≥ 0.20 → 0.7`, `≥ 0.10 → 0.4`, sinon 0.0 | **0.30** |
| **VDS** | Vector Drawing Signal | Shapes vectoriels, connecteurs | `connectors ≥ 3 OU drawing_area ≥ 35% → 1.0`, `drawings ≥ 15 → 0.7`, `≥ 8 → 0.4` | **0.30** |
| **TFS** | Text Fragmentation Signal | Fragmentation texte (indicateur diagramme) | `short_ratio ≥ 0.75 ET blocks ≥ 12 → 1.0`, `ratio ≥ 0.60 → 0.6` (short = < 200 chars) | **0.15** |
| **SDS** | Spatial Dispersion Signal | Dispersion spatiale du texte | `variance ≥ 0.08 → 1.0`, `≥ 0.04 → 0.5` (variance des centres normalisés x+y) | **0.15** |
| **VTS** | Visual Table Signal | Pseudo-tables non structurées | `H_lines ≥ 3 ET V_lines ≥ 2 → 1.0`, ou text grid pattern. `0.0 si table structurée déjà détectée` | **0.10** |

**Calcul détaillé de chaque signal :**

- **RIS** (`compute_raster_image_signal`) : Filtre les `VisualElement` de kind `"raster_image"`, calcule le ratio surface_image/surface_page pour la plus grande image. Seuils par paliers : `RIS_THRESHOLD_HIGH=0.30`, `MEDIUM=0.20`, `LOW=0.10`.

- **VDS** (`compute_vector_drawing_signal`) : Compte les connecteurs (kind in `connector, line, arrow`), les shapes (kind in `vector_shape, drawing, rectangle, oval, shape`), et le ratio de surface cumulée. Seuils : `VDS_CONNECTOR_THRESHOLD=3`, `VDS_AREA_THRESHOLD=0.35`, `VDS_DRAWINGS_HIGH=15`, `VDS_DRAWINGS_MEDIUM=8`.

- **TFS** (`compute_text_fragmentation_signal`) : Compte les blocs de texte < 200 caractères. Si ratio court ≥ 75% avec ≥ 12 blocs → signal maximal (indique un diagramme avec labels). Seuils : `TFS_SHORT_CHAR_LIMIT=200`, `TFS_MIN_BLOCKS=12`, `TFS_HIGH_SHORT_RATIO=0.75`, `TFS_MEDIUM_SHORT_RATIO=0.60`.

- **SDS** (`compute_spatial_dispersion_signal`) : Calcule la variance des centres des blocs de texte (normalisés par les dimensions de la page). Minimum 3 blocs requis. Variance = var(x) + var(y). Seuils : `SDS_HIGH_VARIANCE=0.08`, `SDS_MEDIUM_VARIANCE=0.04`.

- **VTS** (`compute_visual_table_signal`) : Si des tables structurées existent déjà → `0.0` (pas besoin de Vision). Sinon, cherche un pattern de grille (lignes horizontales/verticales) ou un pattern de texte en grille (clustering de positions via `_find_aligned_clusters` avec tolérance 0.05).

#### 5.2.2 Calcul du VNS (Vision Need Score)

```
VNS = Σ(weight_i × signal_i) = 0.30×RIS + 0.30×VDS + 0.15×TFS + 0.15×SDS + 0.10×VTS
```

**Ajustement par Domain Context :** Si un `VisionDomainContext` est fourni, les poids peuvent être ajustés de **±10% maximum**. Trois domaines prédéfinis :

| Domaine | Ajustement |
|---------|------------|
| `SAP` | VDS=0.35 (↑), RIS=0.25 (↓) — plus de diagrammes d'architecture |
| `pharmaceutical` | VTS=0.20 (↑), TFS=0.10 (↓) — tables réglementaires complexes |
| `retail` | RIS=0.40 (↑), VDS=0.20 (↓) — images marketing |

Les poids ajustés sont renormalisés pour que leur somme = 1.0.

#### 5.2.3 Décision de gating

| Condition | Action | Description |
|-----------|--------|-------------|
| `RIS == 1.0 OU VDS == 1.0` | `VISION_REQUIRED` | **Règle de sécurité** — bypass du VNS |
| `VNS ≥ 0.60` | `VISION_REQUIRED` | Vision obligatoire |
| `0.40 ≤ VNS < 0.60` | `VISION_RECOMMENDED` | Vision recommandée (incluse par défaut) |
| `VNS < 0.40` | `NONE` | Pas de Vision nécessaire |

Le `GatingDecision` produit contient : `index`, `unit_id`, `action`, `vision_need_score`, `signals` (les 5 valeurs), et `reasons` (liste explicative textuelle).

#### 5.2.4 Seuils expérimentaux

Le module `weights.py` définit aussi des `EXPERIMENTAL_THRESHOLDS` (à calibrer sur corpus réel en Phase 7) avec des seuils alternatifs plus agressifs pour les signaux individuels (ex : `RIS_HIGH=0.15`, `VDS_CONNECTOR_MIN=1`).

#### 5.2.5 Budget Vision

Le pipeline supporte un `vision_budget` optionnel (nombre max de pages avec Vision). Si le nombre de candidats dépasse le budget, les pages `VISION_REQUIRED` sont prioritaires, puis `VISION_RECOMMENDED` triées par VNS décroissant.

---

### 5.3 Vision Path (GPT-4o)

**Fichiers :** `src/knowbase/extraction_v2/vision/analyzer.py`, `semantic_reader.py`, `diagram_interpreter.py`

Le Vision Path se compose de **trois composants** aux rôles distincts :

#### 5.3.1 VisionAnalyzer — Extraction structurée de diagrammes

**Classe :** `VisionAnalyzer`
**Modèle :** GPT-4o (temperature=0.0, max_tokens=4096)

**Objectif :** Extraire les éléments structurels (boxes, labels, arrows) et les relations visuelles depuis les diagrammes. Vision **OBSERVE et DÉCRIT**, ne raisonne pas.

**Principes directeurs :**
- Toute relation doit avoir une **evidence visuelle**
- Les ambiguïtés sont **déclarées**, jamais résolues implicitement
- Sortie JSON stricte conforme au schéma `VisionExtraction`

**Mécanisme :**
1. Encode l'image en base64
2. Construit les messages via `get_vision_messages()` (prompt system + user avec image + domain context + snippets locaux)
3. Appel API Vision avec `response_format={"type": "json_object"}`
4. Parse la réponse JSON → `VisionExtraction`

**Sortie `VisionExtraction` :**
```
VisionExtraction
  ├── kind: str (type de diagramme)
  ├── elements: List[VisionElement] — boxes, labels détectés
  ├── relations: List[VisionRelation] — flèches, connexions
  ├── ambiguities: List[VisionAmbiguity] — zones ambiguës
  ├── uncertainties: List[VisionUncertainty] — incertitudes
  ├── page_index: int
  └── confidence: float (0.0-1.0)
```

**Traitement parallèle :** Les pages Vision sont traitées en parallèle via `asyncio.gather()` avec un `asyncio.Semaphore(max_concurrent)`. La concurrence est configurable via `MAX_WORKERS` env var (défaut : 30). Pour les très gros documents (>400 pages), elle est réduite automatiquement à 5.

**Gestion d'erreurs :** En cas d'échec d'un appel Vision, l'erreur est loggée mais le pipeline continue — la page n'aura simplement pas d'enrichissement Vision.

#### 5.3.2 VisionSemanticReader — Lecture sémantique textuelle

**Classe :** `VisionSemanticReader`
**Modèle :** GPT-4o (temperature=0.0, max_tokens=1024, timeout=30s)
**Spec :** `SPEC_VISION_SEMANTIC_INTEGRATION.md`

**Objectif :** Produire du **TEXTE exploitable** pour les passes suivantes (Pass 1) au lieu d'éléments géométriques. Ce texte enrichit les chunks `FIGURE_TEXT` du graphe structurel.

**Invariants :**
- **I1** : Jamais de texte vide en sortie
- **I4** : Traçabilité origine obligatoire (`TextOrigin`)
- **I5** : Texte descriptif uniquement, pas d'assertions pré-promues

**Stratégie de fallback 3-tier :**

| Tier | Méthode | TextOrigin résultant |
|------|---------|---------------------|
| 1 | GPT-4o Vision → texte sémantique | `VISION_SEMANTIC` |
| 2 | Retry (1x) si timeout/rate limit | `VISION_SEMANTIC` |
| 3 | OCR basique si Vision échoue | `OCR` |
| 4 | Placeholder (jamais vide) | `PLACEHOLDER` |

**Prompt système :** Décrit le contenu visuel de manière FACTUELLE et OBSERVABLE (2-8 phrases), identifie entités principales et relations visuelles. Réponse JSON : `{diagram_type, description, key_entities, confidence}`.

**Sortie `VisionSemanticResult` :**
```
VisionSemanticResult
  ├── page_no: int
  ├── semantic_text: str (jamais vide — Invariant I1)
  ├── text_origin: TextOrigin (VISION_SEMANTIC | OCR | PLACEHOLDER)
  ├── diagram_type: Optional[str]
  ├── confidence: float
  ├── key_entities: List[str]
  ├── model: str
  ├── prompt_version: str ("v1.0")
  ├── image_hash: str (SHA256[:16] pour cache/replay)
  └── candidate_hints: Optional[List[str]] (jamais promues — I5)
```

#### 5.3.3 DiagramInterpreter — Routing adaptatif LITE/FULL

**Classe :** `DiagramInterpreter`
**Spec :** `ADR_REDUCTO_PARSING_PRIMITIVES` (QW-3)

**Objectif :** Optimiser les coûts Vision via un routing adaptatif basé sur le score VNS du gating.

**Routing :**

| Condition | Méthode | Modèle | Coût estimé |
|-----------|---------|--------|-------------|
| `NONE` + TFS < 0.3 | `SKIP` | — | 0 tokens |
| `NONE` + TFS ≥ 0.3 | `TEXT_ONLY` | — | 0 tokens (OCR existant) |
| `VISION_RECOMMENDED` | `VISION_LITE` | gpt-4o-mini | ~500 tokens |
| `VISION_REQUIRED` | `VISION_FULL` | gpt-4o | ~2000 tokens |

**Quality Gate :** Après extraction, si `confidence < 0.70` → fallback vers `FALLBACK_PROSE` (résumé en prose au lieu d'éléments structurés).

---

### 5.4 Structured Merge

**Fichier :** `src/knowbase/extraction_v2/merge/merger.py` — classe `StructuredMerger`
**Spécification :** `OSMOSIS_EXTRACTION_V2_DECISIONS.md` — Décision 9

**Objectif :** Fusionner les résultats Docling (socle) et Vision (enrichissement) **sans écrasement**.

#### 5.4.1 Règle d'or

> **Vision n'écrase JAMAIS Docling.**

Docling fournit le **SOCLE** (blocs texte, tables structurées). Vision fournit l'**ENRICHISSEMENT** (éléments visuels, relations). L'enrichissement est **ATTACHÉ** au socle, jamais fusionné.

#### 5.4.2 Stratégie d'attachement

1. Par `page_index` / `slide_index` (obligatoire)
2. Par bbox overlap (optionnel, pour précision)
3. Marquage explicite source : `"docling"` | `"vision"`

#### 5.4.3 Mécanisme

Pour chaque page (`merge_page()`), le merger :
1. Copie les blocs de base (Docling = socle intouchable)
2. Copie les tables de base
3. Attache l'enrichissement Vision (si disponible)
4. Attache la décision de gating
5. Ajoute la provenance (version Docling, modèle Vision, score gating, timestamp)

Pour un document complet (`merge_document()`), construit un dict `{page_index → GatingDecision}` et itère sur toutes les VisionUnits.

#### 5.4.4 Sortie

```
MergedPageOutput
  ├── page_index: int
  ├── base_blocks: List[TextBlock]     ← Docling (socle)
  ├── base_tables: List[TableData]     ← Docling (socle)
  ├── vision_enrichment: Optional[VisionExtraction]  ← Vision (attaché)
  ├── gating_decision: Optional[GatingDecision]
  ├── provenance: MergeProvenance
  │     ├── docling_version: str
  │     ├── vision_model: Optional[str]
  │     ├── gating_score: Optional[float]
  │     └── merge_timestamp: str
  ├── title: Optional[str]
  └── format: str ("PDF", "PPTX"...)
```

---

### 5.5 Linéarisation

**Fichier :** `src/knowbase/extraction_v2/merge/linearizer.py` — classe `Linearizer`
**Spécification :** `OSMOSIS_EXTRACTION_V2_DECISIONS.md` — Décision 1

**Objectif :** Générer le `full_text` linéarisé avec marqueurs sémantiques explicites. Ce `full_text` est la représentation canonique du document pour toutes les passes suivantes (Pass 0.9, 1.x).

#### 5.5.1 Grammaire des marqueurs (BNF)

```bnf
marker       ::= '[' marker_type attributes? ']'
marker_type  ::= 'PAGE' | 'TITLE' | 'PARAGRAPH' | 'TABLE_START' | 'TABLE_END'
               | 'TABLE_SUMMARY' | 'TABLE_RAW'
               | 'VISUAL_ENRICHMENT' | 'END_VISUAL_ENRICHMENT'
attributes   ::= (key '=' value)+
key          ::= [a-z_]+
value        ::= [a-zA-Z0-9_.-]+
```

#### 5.5.2 Marqueurs produits

| Marqueur | Signification | Exemple |
|----------|---------------|---------|
| `[PAGE n \| TYPE=xxx]` | Début de page | `[PAGE 6 \| TYPE=ARCHITECTURE_DIAGRAM]` |
| `[TITLE level=n]` | Titre (heading) | `[TITLE level=1] Target Architecture Overview` |
| `[PARAGRAPH]` | Paragraphe de contenu | `[PARAGRAPH]\nThis architecture enables...` |
| `[TABLE_START id=x]` | Début table (sans résumé) | `[TABLE_START id=tbl_1]` |
| `[TABLE_SUMMARY id=x]` | Début table avec résumé LLM (QW-1) | `[TABLE_SUMMARY id=tbl_1]` |
| `[TABLE_RAW]` | Séparateur résumé/markdown brut | — |
| `[TABLE_END]` | Fin de table | — |
| `[VISUAL_ENRICHMENT id=x confidence=y]` | Début enrichissement Vision | `[VISUAL_ENRICHMENT id=vision_6_1 confidence=0.82]` |
| `[END_VISUAL_ENRICHMENT]` | Fin enrichissement Vision | — |

#### 5.5.3 Algorithme de linéarisation

Pour chaque `MergedPageOutput` :
1. **Marqueur de page** : `[PAGE n | TYPE=xxx]` — le type est détecté depuis l'enrichissement Vision (`kind`) ou `None`
2. **Titre** : `[TITLE level=1] ...` si présent
3. **Blocs de texte** : Chaque bloc formaté selon son type (heading → `[TITLE]`, sinon → `[PARAGRAPH]`)
4. **Tables** : Si résumé LLM disponible → format enrichi `[TABLE_SUMMARY]...[TABLE_RAW]...[TABLE_END]` ; sinon → format standard `[TABLE_START]...[TABLE_END]`
5. **Enrichissement Vision** : `[VISUAL_ENRICHMENT]...[END_VISUAL_ENRICHMENT]` avec `to_vision_text()`

Les pages sont jointes par `\n\n`. Un `PageIndex` (mapping offset → page) est construit en parallèle.

#### 5.5.4 Sortie

```
Tuple[str, List[PageIndex]]
  ├── full_text: str — texte linéarisé complet avec marqueurs
  └── page_index: List[PageIndex]
        ├── page_index: int
        ├── start_offset: int
        └── end_offset: int
```

---

### 5.6 Extraction de Contexte Documentaire

**Fichiers :** `src/knowbase/extraction_v2/context/` (13 fichiers)
**Classe orchestrateur :** `DocContextExtractor` (`doc_context_extractor.py`)
**Spec :** `ADR_ASSERTION_AWARE_KG.md` — Section 3.1, `ADR_DOCUMENT_STRUCTURAL_AWARENESS.md`

**Objectif :** Déterminer le **scope documentaire** (version-specific, general, mixed) et extraire les **marqueurs de contexte** (versions, éditions) pour qualifier les assertions en aval (Pass 1.3/1.4).

#### 5.6.1 Architecture en 3 étapes

```
Étape 1: Candidate Mining (déterministe, sans LLM)
  ↓
Étape 2: Structural Analysis (PR6 — analyse zones + templates)
  ↓
Étape 3: LLM Validation (PR7 — arbitre, pas extracteur)
```

#### 5.6.2 Étape 1 — Candidate Mining (`candidate_mining.py`)

**Objectif :** Extraction déterministe (regex/patterns) de candidats marqueurs depuis :
- Nom de fichier
- Premières pages (couverture/titre)
- Headers/footers
- Blocs revision/history

**Filtres universels (CandidateGate)** — Élimination de faux positifs AVANT scoring :

| Catégorie | Patterns éliminés | Exemples |
|-----------|-------------------|----------|
| Dates explicites | `MM/DD/YYYY`, `YYYY-MM-DD` | `05/23/2019` |
| Trimestres | `Q1-Q4 + année` | `Q4,2023` |
| Copyright | `© + année` | `© 2023 SAP SE` |
| Mois + année | `January 2023` | `Dec. 2025` |
| Fiscal years | `FY2023` | — |
| Références temporelles | `since 2019`, `2019-present` | — |
| Unités de mesure | `nombre + unité` | `500 MB`, `15%` |
| Exemples | `e.g. ...` | — |
| Références ID | `Note 123456`, `JIRA-1234` | — |
| Pages/slides | `Page 23`, `Slide 5` | — |

**Patterns positifs** (marqueurs légitimes) :

| Pattern | Exemples |
|---------|----------|
| SemVer | `v1.2.3-beta`, `v1.2` |
| Entity + Numeral | `S/4HANA 2023`, `iPhone 15` |
| Release forms | `Release 3.0`, `Edition 2`, `Phase 2` |
| Structured codes | `AB12`, `XY2023` |

**Structure Numbering Gate :** Détection agnostique de numérotation de sections (ex : "PUBLIC 3:" en position de titre → candidat rejeté, c'est un numéro de section, pas un marqueur de version).

**Filtrage par DocumentContext** (`decide_marker()`) :
- Si `structure_hint.has_numbered_sections` → rejette `WORD+SMALL_NUMBER` en position heading
- Si `entity_hints` → booste confiance si prefix correspond à une entité dominante
- **Safe-by-default** : en cas de doute, rejeter le candidat

#### 5.6.3 Étape 2 — Structural Analysis (`context/structural/`)

Trois composants travaillent en pipeline :

**a) ZoneSegmenter** (`zone_segmenter.py`)
- Segmente chaque page en 3 zones : **TOP** (headers, titres), **MAIN** (corps), **BOTTOM** (footers, legal)
- Basé sur les lignes significatives (filtrage des lignes vides/courtes)
- Confiance structurelle basée sur le nombre de pages : `HIGH` (≥10 pages), `MEDIUM` (3-9), `LOW` (<3)

**b) TemplateDetector** (`template_detector.py`)
- Identifie les fragments de texte répétitifs (boilerplate) par clustering
- Critères : apparaît sur ≥30% des pages, ≥2 occurrences, zone consistency ≥60%
- Les fragments MAIN avec haute consistance ont leur `template_likelihood` réduit de 50% (peut être du contenu sémantique répété)
- Produit un `StructuralAnalysis` avec fragments, couverture, statistiques

**c) LinguisticCueDetector** (`linguistic_cue_detector.py`)
- Score les patterns linguistiques autour d'un candidat :
  - **Scope language** (version, release, available in) → indique marqueur de contexte
  - **Legal language** (©, confidential, trademark) → indique boilerplate
  - **Contrast language** (vs, unlike, whereas) → indique comparaison (scope MIXED)
- Scores normalisés 0.0-1.0, multilingue (EN, FR, DE)

#### 5.6.4 Étape 3 — LLM Validation

Le LLM agit comme **ARBITRE** (pas extracteur) :
- Input : candidats enrichis avec signaux structurels
- Output : classification CONTEXT_SETTING vs TEMPLATE_NOISE
- Le LLM ne peut pas inventer de nouveaux marqueurs

#### 5.6.5 Modules complémentaires du contexte

**AnchorContextAnalyzer** (`anchor_context_analyzer.py`) — Analyse le contexte de chaque assertion (utilisé en Pass 1.3/1.4) :
- Stratégie : heuristiques d'abord, LLM si ambigu
- Détecte : polarité (positive, negative, future, deprecated, conditional), marqueurs locaux, patterns d'override

**PassageHeuristics** (`heuristics.py`) — Détection déterministe par regex de :
- Négation : `not, cannot, unavailable, removed` (EN/FR/DE)
- Futur : `will be, coming soon, planned for` (EN/FR/DE)
- Deprecated : `deprecated, obsolete, legacy, end-of-life` (EN/FR/DE)
- Conditionnel : `if, when, unless, depending on` (EN/FR/DE)
- Override : `unlike, in contrast, different from` (avec type : SWITCH, RANGE, GENERALIZATION)

**InheritanceEngine** (`inheritance.py`) — Matrice d'héritage DocContext → AnchorContext :

| DocScope | Strong markers | Weak markers | Result Scope | Source | Confiance |
|----------|---------------|--------------|--------------|--------|-----------|
| `VARIANT_SPECIFIC` | ✅ | — | `CONSTRAINED` | `INHERITED_STRONG` | 0.95 |
| `VARIANT_SPECIFIC` | ✅ | ✅ | `CONSTRAINED` | `INHERITED_STRONG` | 0.90 |
| `VARIANT_SPECIFIC` | — | ✅ | `CONSTRAINED` | `INHERITED_WEAK` | 0.85 |
| `VARIANT_SPECIFIC` | — | — | `UNKNOWN` | `NONE` | 0.70 |
| `MIXED` | any | any | `UNKNOWN` | `NONE` | 0.50 |
| `GENERAL` | — | — | `GENERAL` | `NONE` | 0.80 |

Règle clé : **Override local détecté → toujours prioritaire** sur l'héritage documentaire.

#### 5.6.6 Sortie

```
DocContextFrame
  ├── doc_scope: DocScope (VARIANT_SPECIFIC | GENERAL | MIXED)
  ├── strong_markers: List[str] — marqueurs à haute confiance
  ├── weak_markers: List[str] — marqueurs à confiance modérée
  ├── evidence: List[MarkerEvidence]
  ├── scope_signals: ScopeSignals
  └── document_context: Optional[DocumentContext] — contraintes structurelles
```

---

### 5.7 Table Summarizer

**Fichier :** `src/knowbase/extraction_v2/tables/table_summarizer.py` — classe `TableSummarizer`
**Spec :** `ADR_REDUCTO_PARSING_PRIMITIVES` — QW-1

**Objectif :** Transformer les tableaux structurés en **résumés en langage naturel** pour améliorer le RAG (+50% hit-rate estimé sur questions impliquant des tableaux).

#### 5.7.1 Principe

Un résumé sémantique est beaucoup plus efficace pour l'embedding qu'un Markdown brut. Le résumé (2-4 phrases) est stocké dans `[TABLE_SUMMARY]` AVANT le Markdown brut `[TABLE_RAW]`, optimisant ainsi l'embedding.

#### 5.7.2 Configuration

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `min_cells` | 4 | Minimum de cellules pour déclencher le résumé |
| `max_cells` | 500 | Maximum avant troncature |
| `skip_empty` | `True` | Ignorer les tables vides |

#### 5.7.3 Mécanisme

1. **Filtre** : `_should_summarize()` — vérifie min/max cellules
2. **Troncature** : Si table > `max_cells`, garde les premières lignes
3. **Conversion Markdown** : `table.to_markdown()` — génère le Markdown de la table
4. **Appel LLM** : Via `LLMRouter` (singleton, TaskType approprié) avec prompt spécifique
5. **Prompt** : « Summarize this table in natural language... Be factual, concise (2-4 sentences), describe key insights. »
6. **Batch** : `summarize_batch()` traite plusieurs tables en parallèle (max_concurrent=5)

#### 5.7.4 Sortie

```
TableSummaryResult
  ├── table_id: str
  ├── summary: str — résumé en langage naturel
  ├── raw_markdown: str — Markdown original
  ├── success: bool
  ├── error: Optional[str]
  ├── input_tokens: int
  └── output_tokens: int
```

---

### 5.8 Cache Versionné

**Fichier :** `src/knowbase/extraction_v2/cache/versioned_cache.py` — classe `VersionedCache`
**Spécification :** `OSMOSIS_EXTRACTION_V2_DECISIONS.md` — Décision 10

**Objectif :** Éviter de refaire les appels Vision coûteux en cachant les résultats d'extraction complets.

#### 5.8.1 Version actuelle

`CURRENT_CACHE_VERSION = "v5"` — v5 inclut les DocItems sérialisés pour Pipeline V2 Pass 1 Anchor Resolution.

#### 5.8.2 Clé de cache

La clé de cache est le **SHA256 du fichier source** (pas le document_id). Ainsi, le même fichier (même contenu) sera toujours retrouvé, peu importe son nom ou chemin.

**Format de fichier cache :** `{sha256_hash}.v5cache.json`

#### 5.8.3 Invalidation

- Si `cache_version != CURRENT_CACHE_VERSION` → invalide (migration de version)
- Le hash du fichier source assure l'invalidation automatique si le contenu change

#### 5.8.4 Enrichissement à la volée

Si le cache HIT mais que `doc_context` est `None` (ancien cache), le pipeline extrait le DocContext à la volée et met à jour le cache — transparent pour l'appelant.

#### 5.8.5 Structure du cache

```json
{
  "cache_version": "v5",
  "created_at": "2026-01-29T14:30:00Z",
  "source_file_hash": "abc123...",
  "document_id": "doc_xyz",
  "extraction": {
    "full_text": "...",
    "structure": { ... },
    "page_index": [ ... ],
    "gating_decisions": [ ... ],
    "vision_results": [ ... ],
    "doc_context": { ... }
  }
}
```

---

### 5.8b Confidence Scorer

**Fichier :** `src/knowbase/extraction_v2/confidence/confidence_scorer.py` — classe `ConfidenceScorer`
**Spec :** `ADR_REDUCTO_PARSING_PRIMITIVES` — QW-2

**Objectif :** Calculer un score heuristique de `parse_confidence` (0.0-1.0) sur la qualité du parsing (pas de l'extraction). Un texte bien parsé (clair, structuré, sans artefacts OCR) a un score élevé.

#### 5.8b.1 Les 5 signaux de confiance

| Signal | Poids | Ce qu'il mesure | Score bas | Score haut |
|--------|-------|-----------------|-----------|------------|
| `length` | 0.20 | Longueur suffisante | < 50 chars → 0.0 | ≥ 500 chars → 1.0 |
| `structure` | 0.25 | Présence de structure (headings, listes, tables) | Aucune → 0.3 | ≥ 3 types → 1.0 |
| `ocr_quality` | 0.20 | Absence de patterns OCR suspects | Beaucoup de suspects → 0.0 | Aucun → 1.0 |
| `coherence` | 0.20 | Ratio mots/caractères normaux | Mots très courts/longs → 0.5 | Normal → 1.0 |
| `markers` | 0.15 | Présence de marqueurs OSMOSE | Aucun → 0.5 (neutre) | ≥ 4 types → 1.0 |

**Floor/Ceiling :** Score final clampé entre `min_score=0.1` et `max_score=1.0`.

---

### 5.8c Layout Detector

**Fichier :** `src/knowbase/extraction_v2/layout/layout_detector.py` — classe `LayoutDetector`
**Spec :** `ADR_REDUCTO_PARSING_PRIMITIVES` — MT-1

**Objectif :** Détecter les régions structurelles dans le `full_text` linéarisé pour informer le chunker (HybridAnchorChunker) des zones atomiques **à ne jamais couper**.

#### 5.8c.1 Types de régions

| Type | Atomique | Description |
|------|----------|-------------|
| `TABLE` | ✅ | Entre `[TABLE_START]`/`[TABLE_SUMMARY]` et `[TABLE_END]` |
| `VISION` | ✅ | Entre `[VISUAL_ENRICHMENT]` et `[END_VISUAL_ENRICHMENT]` |
| `PAGE_MARKER` | ❌ | Marqueur `[PAGE n]` |
| `TITLE` | ❌ | Marqueur `[TITLE level=n]` |
| `PARAGRAPH` | ❌ | Bloc `[PARAGRAPH]` + contenu |
| `TEXT` | ❌ | Texte libre entre les marqueurs |

#### 5.8c.2 Règle non-négociable

> **Ne jamais couper un tableau.**

Les régions atomiques (TABLE, VISION) ne peuvent **JAMAIS** être coupées par le chunking.

#### 5.8c.3 Algorithme de détection

1. Détection des régions atomiques (tables via regex `TABLE_START_PATTERN`/`TABLE_END_PATTERN`, vision via `VISION_START_PATTERN`/`VISION_END_PATTERN`)
2. Détection des régions non-atomiques (pages, titres, paragraphes via regex)
3. Fusion : priorité aux régions atomiques (les non-atomiques qui chevauchent une atomique sont exclues)
4. Remplissage des trous : les gaps entre régions sont comblés par des régions `TEXT`

**Validation :** `validate_no_cut_tables()` — vérifie post-chunking qu'aucun tableau n'a été coupé (utilisé pour tests et monitoring).

---

### 5.9 Conformité ADR — Pass 0 Extraction

| # | Axe ADR | Statut | Analyse |
|---|---------|--------|---------|
| AV2-1 | Séparation structure / sémantique | ✅ | Pass 0 produit uniquement la structure documentaire (VisionUnit, MergedPageOutput). Aucune entité sémantique (Concept, Information) n'est créée. |
| AV2-4 | DocItem atomique | ✅ | Les blocs extraits par Docling correspondent aux items natifs (paragraph, heading, list-item, caption). La conversion en DocItem se fait en Pass 0 Structural. |
| AV2-8 | Dual Storage | ⚠️ | Pass 0 produit le `full_text` pour Qdrant et la structure pour Neo4j. Le dual storage n'est effectif qu'après Pass 0 Structural (TypeAwareChunks → Qdrant). |
| NS-2 | LLM = Extracteur evidence-locked | ✅ | Vision observe et décrit factuellement. Le VisionSemanticReader a l'invariant I5 (pas d'assertions pré-promues). Le TableSummarizer décrit les insights observables. |
| NS-3 | Citation exacte obligatoire | ✅ | Le `PageIndex` permet de tracer chaque portion du `full_text` vers sa page d'origine. Les marqueurs `[PAGE n]` assurent la traçabilité dans le texte. |
| NS-4 | Pas de synthèse cross-source | ✅ | Pass 0 traite un seul document à la fois. Pas de fusion multi-documents. |
| AV2-10 | < 250 nodes/document | 🟢 | Pass 0 ne crée aucun node Neo4j directement (c'est Pass 0 Structural qui les crée). |

---

### 5.10 Risques — Pass 0 Extraction

| # | Risque | Niveau | Description | Mitigation |
|---|--------|--------|-------------|------------|
| R0-1 | **Shapes vectoriels non détectés** | 🟡 | `_extract_visual_elements()` n'extrait que les `pictures` (raster). Les shapes vectoriels dépendent de la version Docling et du format. Le commentaire dans le code mentionne « Fallback VDS sera utilisé si nécessaire (Phase 2.6) ». | Le signal VDS peut être sous-évalué pour les PPTX avec shapes sans images raster. Signal TFS et SDS compensent partiellement. |
| R0-2 | **Concurrence Vision non bornée** | 🟢 | Le semaphore limite la concurrence (défaut 30, réduit à 5 pour >400 pages). Risk de rate limiting OpenAI sur très gros batches. | Le semaphore et la réduction automatique pour gros documents atténuent ce risque. Le budget Vision optionnel ajoute un contrôle supplémentaire. |
| R0-3 | **Cache version mismatch silencieux** | 🟢 | Le passage de v4 à v5 invalide les anciens caches automatiquement. Le pipeline ré-extrait transparemment. | Invalidation automatique par version. L'enrichissement DocContext à la volée sur anciens caches fonctionne correctement. |
| R0-4 | **Seuils de gating non calibrés** | 🟡 | Les `EXPERIMENTAL_THRESHOLDS` sont marqués « à calibrer sur corpus réel (Phase 7) ». Les seuils actuels sont des valeurs par défaut raisonnables mais non validées empiriquement. | Les seuils par défaut (`VISION_GATING_V4_SPEC.md`) sont conservatifs. L'ajustement par Domain Context permet une adaptation au cas par cas. |
| R0-5 | **Table Summarizer — hallucination LLM** | 🟡 | Le LLM peut halluciner des insights non présents dans la table. Le prompt demande de ne décrire que « ce qui est explicitement présent » mais aucune validation automatique n'est effectuée. | Le Markdown brut est conservé dans `[TABLE_RAW]` pour vérification. Le prompt est strict (« Describe ONLY what is explicitly present »). |
| R0-6 | **DocContext faux positifs résiduels** | 🟡 | Malgré le CandidateGate robuste (>10 catégories de filtres) et le filtrage par DocumentContext (`decide_marker`), certains faux positifs de marqueurs de version pourraient passer, surtout dans des domaines inhabituels. | Le principe safe-by-default (rejeter en cas de doute) et la validation LLM réduisent ce risque. La matrice d'héritage traite `MIXED` de façon conservatrice (pas d'héritage). |
| R0-7 | **VisionSemanticReader — placeholder texte** | 🟢 | L'invariant I1 (jamais vide) peut produire un placeholder `[VISUAL_CONTENT: Page X - interpretation unavailable]` si toutes les stratégies échouent. Ce placeholder est informationnellement pauvre. | Le fallback 3-tier minimise les cas de placeholder. Les métriques `vision_semantic_fallback_placeholder` permettent le monitoring. |
| R0-8 | **Pass 0.5 désactivée en mode V2** | ⚠️ | Quand `stratified_pipeline_v2` feature flag est activé, la coréférence linguistique (Pass 0.5) est explicitement désactivée car `MentionSpan/CoreferenceChain` ne font pas partie de l'architecture V2. | Décision architecturale consciente documentée dans le code. La résolution de coréférence en V2 sera gérée différemment (à définir). |

---

## 6. Pass 0 Structural — Graphe Structurel

<!-- À compléter : analyse détaillée de stratified/pass0/ et structural/ -->

---

## 7. Pass 0.5 — Résolution de Coréférence Linguistique

<!-- À compléter : analyse détaillée de pass05_coref.py -->

---

## 8. Pass 0.9 — Construction de la Vue Globale

<!-- À compléter : analyse détaillée de stratified/pass09/ -->

---

## 9. Pass 1.1 — Analyse Documentaire

<!-- À compléter : analyse détaillée de document_analyzer.py -->

---

## 10. Pass 1.2 — Identification des Concepts

<!-- À compléter : analyse détaillée de concept_identifier.py, concept_refiner.py, trigger_enricher.py -->

---

## 11. Pass 1.3 — Extraction d'Assertions

<!-- À compléter : analyse détaillée de assertion_extractor.py, verbatim_validator.py -->

---

## 12. Pass 1.3b — Résolution d'Ancrage

<!-- À compléter : analyse détaillée de anchor_resolver.py -->

---

## 13. Pass 1.4 — Promotion et Value Contract

<!-- À compléter : analyse détaillée de promotion_engine.py, value_extractor.py, claimkey/ -->

---

## 14. Pass 2 — Enrichissement Sémantique

<!-- À compléter : analyse détaillée de pass2/ -->

---

## 15. Pass 3 — Consolidation Corpus

<!-- À compléter : analyse détaillée de pass3/ -->

---

## 16. Orchestration Pipeline

<!-- À compléter : analyse détaillée de queue/jobs_v2.py, dispatcher.py, burst/orchestrator.py -->

---

## 17. Modèle de données complet

<!-- À compléter : synthèse du schéma Neo4j V2 et modèles Pydantic -->

---

## 18. Synthèse globale des risques

<!-- À compléter : tableau récapitulatif de tous les risques identifiés -->

---

## 19. Diagramme d'architecture global

<!-- À compléter : diagramme ASCII complet -->

---

## 20. Conclusion

<!-- À compléter : synthèse finale -->
