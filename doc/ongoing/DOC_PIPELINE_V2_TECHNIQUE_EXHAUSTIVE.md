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
  - [7.0 Vue d'ensemble Pass 0.5](#70-vue-densemble-pass-05)
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

**Fichiers principaux :**
- `src/knowbase/stratified/pass0/adapter.py` — classe `Pass0Adapter` (adapter V2)
- `src/knowbase/stratified/pass0/cache_loader.py` — fonction `load_pass0_from_cache()` (chargement depuis cache)
- `src/knowbase/structural/graph_builder.py` — classe `StructuralGraphBuilder` (constructeur du graphe)
- `src/knowbase/structural/models.py` — modèles Pydantic (`DocItem`, `SectionInfo`, `TypeAwareChunk`, `DocumentVersion`, `PageContext`, `StructuralProfile`)
- `src/knowbase/structural/docitem_builder.py` — classe `DocItemBuilder` (extraction des items Docling)
- `src/knowbase/structural/section_profiler.py` — classe `SectionProfiler` (assignment sections + profils structurels)
- `src/knowbase/structural/type_aware_chunker.py` — classe `TypeAwareChunker` (chunking par type)

**Objectif :** Transformer le `DoclingDocument` (sortie de Docling) en un **graphe structurel Document → Section → DocItem** conforme au schéma V2, puis produire les `TypeAwareChunk` pour le retrieval vectoriel (Qdrant) et les mappings chunk↔DocItem nécessaires à l'Anchor Resolution (Pass 1.3b).

### 6.0 Vue d'ensemble Pass 0 Structural

**Entrant :**

| Entrant | Type | Source |
|---------|------|--------|
| `DoclingDocument` | Objet Docling natif | Pass 0 Extraction (via `extract_to_units_with_docling()`) |
| `tenant_id` | `str` | Contexte multi-tenant |
| `doc_id` | `str` | ID unique du document |
| Ou : fichier cache `.v4cache.json`/`.v5cache.json` | JSON sérialisé | `data/extraction_cache/` (bypass Docling) |

**Séquence d'exécution (4+1 étapes) :**

```
Étape 1: DocItemBuilder — Extraction des DocItems depuis DoclingDocument
  │  texts[], tables[], pictures[] → DocItem[] avec reading_order + charspan
  ↓
Étape 2: SectionProfiler — Assignment hiérarchique des sections
  │  DocItem[] → SectionInfo[] avec structural_profile
  ↓
Étape 3: TypeAwareChunker — Création des chunks type-aware
  │  DocItem[] + SectionInfo[] → TypeAwareChunk[]
  ↓
Étape 4: Pass0Adapter — Adaptation au schéma V2
  │  StructuralGraphBuildResult → Pass0Result
  │  + construction chunk↔DocItem mappings
  │  + construction unit_index (AssertionUnitIndexer)
  ↓
Étape 4b (optionnel): Persistance Neo4j V2
  │  Document, Section, DocItem nodes
```

**Chemin alternatif : CacheLoader** — Si un cache V2/V4/V5 existe, `load_pass0_from_cache()` reconstruit directement un `Pass0Result` depuis le JSON sérialisé, sans re-parser le DoclingDocument. Supporte aussi le format legacy v1.0 (page-based).

---

### 6.1 Adapter Docling → Schema V2

**Fichier :** `src/knowbase/stratified/pass0/adapter.py` — classe `Pass0Adapter`

**Objectif :** Wrapper le `StructuralGraphBuilder` existant et l'adapter au schéma V2 en générant les identifiants composites et les mappings inter-couches.

#### 6.1.1 Architecture Adapter

`Pass0Adapter` encapsule `StructuralGraphBuilder` (pattern Adapter) :

```python
class Pass0Adapter:
    def __init__(self, max_chunk_size=3000, persist_artifacts=False):
        self.builder = StructuralGraphBuilder(
            max_chunk_size=max_chunk_size,
            persist_artifacts=persist_artifacts,
        )
```

Le builder sous-jacent orchestre les 3 composants internes : `DocItemBuilder` → `SectionProfiler` → `TypeAwareChunker`.

#### 6.1.2 Identifiants composites V2 (docitem_id)

Format : `{tenant_id}:{doc_id}:{item_id}`

Exemple : `default:doc_abc123:item_0042`

Ce format assure :
- **Unicité globale** multi-tenant
- **Lookup rapide** par tenant + doc_id
- **Correspondance** avec l'`item_id` Docling original (= `self_ref`)

Fonctions utilitaires :
- `get_docitem_id_v2(tenant_id, doc_id, item_id) → str`
- `parse_docitem_id_v2(docitem_id) → (tenant_id, doc_id, item_id)`

#### 6.1.3 Méthode `process_document()`

Séquence :
1. Appel `self.builder.build_from_docling()` → `StructuralGraphBuildResult`
2. Construction des mappings chunk↔DocItem via `_build_mappings()`
3. Construction de l'index des unités via `_build_unit_index()` (appel `AssertionUnitIndexer`)
4. Assemblage du `Pass0Result` V2

#### 6.1.4 Construction des mappings chunk↔DocItem

La méthode `_build_mappings()` produit deux structures inverses :

| Structure | Type | Utilisation |
|-----------|------|-------------|
| `chunk_to_docitem_map` | `Dict[chunk_id → ChunkToDocItemMapping]` | Anchor Resolution (Pass 1.3b) — trouver le DocItem source d'un chunk |
| `docitem_to_chunks_map` | `Dict[docitem_id → List[chunk_id]]` | Navigation — trouver tous les chunks contenant un DocItem |

Chaque `ChunkToDocItemMapping` contient : `chunk_id`, `docitem_ids` (liste car un chunk peut couvrir plusieurs DocItems), `text`, `char_start`, `char_end`.

Le `TypeAwareChunk` possède déjà `item_ids` (liste des `DocItem.item_id` sources). L'adapter convertit ces `item_id` en `docitem_id` composites V2.

#### 6.1.5 Index des unités (AssertionUnitIndexer)

La méthode `_build_unit_index()` segmente chaque DocItem en **unités d'assertion** pour permettre au LLM (Pass 1.3) de **pointer** vers une unité au lieu de copier le texte verbatim.

- Import lazy : `from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer`
- Filtre : DocItems avec texte > 30 caractères uniquement
- Produit : `Dict[docitem_id → UnitIndexResult]` stocké dans `Pass0Result.unit_index`

---

### 6.2 Construction du graphe (Document, Section, DocItem)

**Fichier :** `src/knowbase/structural/graph_builder.py` — classe `StructuralGraphBuilder`

**Objectif :** Orchestrer les 3 composants d'extraction structurelle (DocItemBuilder, SectionProfiler, TypeAwareChunker) depuis un DoclingDocument natif.

#### 6.2.1 Étape 1 — DocItemBuilder

**Fichier :** `src/knowbase/structural/docitem_builder.py`

**Objectif :** Extraire les items documentaires atomiques depuis le DoclingDocument.

**Sources d'extraction :**

| Source Docling | Items extraits | Type DocItem résultant |
|----------------|----------------|----------------------|
| `doc.texts[]` | Paragraphes, headings, list-items, captions, footnotes | TEXT, HEADING, LIST_ITEM, CAPTION, FOOTNOTE |
| `doc.tables[]` | Tables structurées (Markdown + JSON canonique) | TABLE |
| `doc.pictures[]` | Figures avec captions | FIGURE |

**Mapping DocItemLabel → DocItemType** (`DOCLING_LABEL_MAPPING` dans `models.py`) :

| Label Docling | DocItemType | Catégorie |
|---------------|-------------|-----------|
| `text`, `paragraph`, `handwritten_text` | TEXT | Relation-bearing |
| `title`, `section_header` | HEADING | Relation-bearing |
| `caption` | CAPTION | Relation-bearing |
| `footnote` | FOOTNOTE | Relation-bearing |
| `list_item` | LIST_ITEM | Contextuel (D3.3) |
| `table`, `chart` | TABLE | Structure-bearing |
| `picture` | FIGURE | Structure-bearing |
| `code` | CODE | Structure-bearing |
| `formula` | FORMULA | Structure-bearing |
| `page_header`, `page_footer` | FURNITURE | Structure-bearing |
| `reference` | REFERENCE | Structure-bearing |
| Autres (`form`, `checkbox_*`, etc.) | OTHER | Structure-bearing |

**Distinction fondamentale (ADR D3) :**

- **Relation-bearing** (TEXT, HEADING, CAPTION, FOOTNOTE) — portent des assertions, éligibles à l'extraction de relations
- **Structure-bearing** (TABLE, FIGURE, CODE, FORMULA, etc.) — portent de la structure, traités séparément

**Traitements par type :**
- **HEADING** : Inférence du `heading_level` depuis le texte (patterns `1.`, `1.1.`, `1.1.1.` → levels 1, 2, 3) via `infer_heading_level_from_text()`
- **TABLE** : Conversion en Markdown (`table_to_text()`) et JSON canonique (`table_to_json()`)
- **FIGURE** : Extraction de la caption si disponible

**Post-traitements globaux :**
1. `compute_reading_order()` — Tri déterministe par (page, position_verticale, position_horizontale) → `reading_order_index`
2. `compute_docwide_charspans()` — Calcul des positions de caractères à l'échelle du document entier (`charspan_start_docwide`, `charspan_end_docwide`) avec séparateur `\n`

**Sortie :** `DocItemBuildResult` contenant `doc_items: List[DocItem]`, `doc_version: DocumentVersion`, `page_contexts: List[PageContext]`, `doc_dict: Dict`

#### 6.2.2 Étape 2 — SectionProfiler

**Fichier :** `src/knowbase/structural/section_profiler.py`

**Objectif :** Grouper les DocItems en sections hiérarchiques et calculer le profil structurel de chaque section.

**Deux stratégies :**

| Stratégie | Condition d'activation | Mécanisme |
|-----------|----------------------|-----------|
| **Heading-based** | ≥1 DocItem de type HEADING détecté | Pile de sections (heading stack) — chaque HEADING crée/met à jour une section, les items suivants y sont assignés |
| **Page-based** (fallback) | Aucun HEADING détecté | 1 section par page — `section_p{page_idx:03d}` |

**Heading-based : détail**
- Chaque HEADING crée une section avec `section_id` dérivé du texte (slugifié)
- Le `section_path` est construit hiérarchiquement : `"1. Introduction / 1.1 Overview"`
- Le `section_level` correspond au `heading_level` du DocItem
- Les relations parent→enfant sont établies via `parent_section_id`

**Profil structurel (`StructuralProfile`)** :
Après l'assignment, chaque section est analysée via `StructuralProfile.from_items()` :
- Calcul des ratios par type (text_ratio, table_ratio, figure_ratio, etc.)
- Classification `is_relation_bearing` si ratio relation-types > 50%
- Classification `is_structure_bearing` si ratio structure-types > 50%
- `relation_likelihood` et `relation_likelihood_tier` (HIGH/MEDIUM/LOW/VERY_LOW) via `compute_features()` depuis le module `relation_likelihood`

**Sortie :** `List[SectionInfo]` avec `section_id`, `title`, `section_path`, `section_level`, `parent_section_id`, `item_ids`, `structural_profile`

#### 6.2.3 Étape 3 — TypeAwareChunker

**Fichier :** `src/knowbase/structural/type_aware_chunker.py`

**Objectif :** Créer des chunks séparés par type de contenu pour optimiser le retrieval vectoriel et l'extraction de relations.

**Règles de chunking :**

| Type DocItem | Traitement | ChunkKind | `is_relation_bearing` |
|--------------|-----------|-----------|----------------------|
| TEXT, HEADING, CAPTION, FOOTNOTE | Bufferisés et fusionnés consécutivement | `NARRATIVE_TEXT` | ✅ `True` |
| TABLE | 1 chunk dédié par table | `TABLE_TEXT` | ❌ `False` |
| FIGURE | 1 chunk dédié par figure | `FIGURE_TEXT` | ❌ `False` |
| CODE | 1 chunk dédié par bloc code | `CODE_TEXT` | ❌ `False` |

**Mécanisme de buffering narratif :**
- Les items NARRATIVE sont accumulés dans un buffer
- Quand la taille du buffer dépasse `max_chunk_size` (défaut : 3000 chars), le buffer est flushé → 1 `TypeAwareChunk(kind=NARRATIVE_TEXT)`
- Chaque chunk narratif contient la liste des `item_ids` sources (traçabilité DocItem → Chunk)

**Propriétés des chunks :**
- `chunk_id` : UUID généré automatiquement (`chunk_{uuid4().hex[:12]}`)
- `item_ids` : Liste des DocItem.item_id sources (1-N)
- `section_id` : Section d'appartenance
- `page_no` : Page de début
- `text_origin` : Traçabilité de l'origine du texte (DOCLING, VISION_SEMANTIC, OCR, PLACEHOLDER)

**Sortie :** `List[TypeAwareChunk]` — seuls les chunks `NARRATIVE_TEXT` sont marqués `is_relation_bearing=True`

#### 6.2.4 Résultat global — StructuralGraphBuildResult

```
StructuralGraphBuildResult
  ├── doc_items: List[DocItem]           ← items atomiques
  ├── sections: List[SectionInfo]        ← hiérarchie de sections
  ├── chunks: List[TypeAwareChunk]       ← chunks pour retrieval
  ├── doc_version: DocumentVersion       ← version avec doc_hash
  ├── page_contexts: List[PageContext]   ← contextes de pages
  └── doc_dict: Dict                     ← DoclingDocument sérialisé (D7)
```

#### 6.2.5 Résultat V2 — Pass0Result

```
Pass0Result (produit par Pass0Adapter)
  ├── doc_items: List[DocItem]
  ├── sections: List[SectionInfo]
  ├── chunks: List[TypeAwareChunk]
  ├── chunk_to_docitem_map: Dict[str, ChunkToDocItemMapping]   ← pour Pass 1.3b
  ├── docitem_to_chunks_map: Dict[str, List[str]]              ← index inversé
  ├── unit_index: Dict[str, UnitIndexResult]                   ← pour Pass 1.3 Pointer
  ├── doc_title: Optional[str]
  ├── page_count: int
  └── doc_version_id: str                                      ← hash stable v1:{sha256}
```

#### 6.2.6 Cache Loader — Reconstruction depuis le cache

**Fichier :** `src/knowbase/stratified/pass0/cache_loader.py`

**Objectif :** Reconstruire un `Pass0Result` depuis un fichier cache JSON, évitant de re-parser le DoclingDocument.

**Formats supportés :**

| Format cache | Données disponibles | Limites |
|-------------|---------------------|---------|
| `v2`, `v3`, `v4` | Chunks sérialisés dans `stats.structural_graph.chunks[]` | DocItems non sérialisés |
| `v5` | Chunks + DocItems sérialisés dans `stats.structural_graph.items[]` | Sections non sérialisées |
| `v1_legacy` | Pages brutes dans `extracted_text.pages[]` | 1 chunk/DocItem/section par page (dégradé) |

**Vision Observations (ADR-20260126)** :
Le CacheLoader extrait les `vision_results[]` du cache et les convertit en `VisionObservation` (hors graphe de connaissance). Le paramètre `merge_vision` est **DEPRECATED** — par défaut, les résultats Vision ne sont **PAS** mergés dans les chunks FIGURE_TEXT mais retournés comme observations séparées.

#### 6.2.7 Persistance Neo4j V2

**Mode V2 (via `Pass0Adapter.process_and_persist_v2()`)** :
- Labels : `Document`, `Section`, `DocItem` (labels V2 simplifiés)
- Relations : `(Document)-[:HAS_SECTION]->(Section)`, `(Section)-[:SUBSECTION_OF]->(Section)`, `(Section)-[:CONTAINS_ITEM]->(DocItem)`
- IDs composites V2 pour `section_id` et `docitem_id`

**Mode legacy (via `StructuralGraphBuilder._persist_to_neo4j()`)** :
- Labels : `DocumentVersion`, `SectionContext`, `DocItem`, `PageContext`, `TypeAwareChunk`
- Relations : `(DocumentContext)-[:HAS_VERSION]->(DocumentVersion)`, `(DocumentVersion)-[:HAS_SECTION]->(SectionContext)`, `(SectionContext)-[:CONTAINS]->(DocItem)`, `(DocItem)-[:ON_PAGE]->(PageContext)`, `(TypeAwareChunk)-[:DERIVED_FROM]->(DocItem)`
- Feature flag `stratified_pipeline_v2` : si activé, skip la création de `PageContext` (fusionné dans Document)

**Lazy DocItem Persistence (ADR)** :
La fonction `persist_pass0_to_neo4j_sync()` implémente une stratégie de **persistance lazy** pour les DocItems :
- Seuls `Document` et `Section` sont créés immédiatement
- Les `DocItem` sont créés **à la demande** lors de Pass 1.3 (Anchor Resolution) quand une Information est PROMOTED et nécessite un lien `ANCHORED_IN`
- Raison : ~6700 DocItems/doc → ~50-200 DocItems/doc effectivement ancrés (evidence-first)

#### 6.2.8 Modèle de données — DocItem

**Fichier :** `src/knowbase/structural/models.py` — classe `DocItem` (Pydantic BaseModel)

Champs principaux :

| Catégorie | Champs | Description |
|-----------|--------|-------------|
| **Identifiants (D1)** | `tenant_id`, `doc_id`, `doc_version_id`, `item_id` | Identification multi-tenant + version |
| **Type et contenu (D3)** | `item_type: DocItemType`, `heading_level`, `text`, `table_json` | Type canonique + contenu |
| **Hiérarchie Docling (D4.6)** | `parent_item_id`, `group_id` | Conservés comme metadata (non utilisés pour le graphe V2) |
| **Provenance (D5)** | `page_no`, `bbox_*`, `charspan_start/end`, `charspan_start_docwide/end_docwide` | Position spatiale + textuelle |
| **Ordre (D2)** | `reading_order_index` | Position dans l'ordre de lecture du document |
| **Scope Layer** | `mentioned_concepts: List[str]` | Concepts mentionnés (peuplé par Pass 2) — navigation, pas assertions |
| **Section** | `section_id` | Assigné par SectionProfiler |

**Hash stable du document (D6)** :
- Algorithme : `compute_doc_hash()` dans `models.py`
- Format : `v1:{sha256}`
- Exclut les champs volatiles (`mtime`, `path`, `created_at`, `pipeline_version`, etc.)
- Arrondit les floats (D6.3, précision 2 décimales)
- Trie les listes par `self_ref` pour le déterminisme (D6.4)
- JSON canonique (clés triées, pas d'espaces)

---

### 6.3 Conformité ADR — Pass 0 Structural

| # | Axe ADR | Statut | Analyse |
|---|---------|--------|---------|
| AV2-1 | Séparation structure / sémantique | ✅ | Pass 0 Structural produit **uniquement** la structure documentaire (Document, Section, DocItem). Aucune entité sémantique (Concept, Information, Subject, Theme) n'est créée. La séparation est stricte. |
| AV2-2 | 8 types de nodes maximum | ✅ | Pass 0 Structural crée 3 des 8 types autorisés : Document, Section, DocItem. Pas de prolifération de types intermédiaires. |
| AV2-3 | Ancrage Information sur DocItem | ✅ | Les mappings `chunk_to_docitem_map` et `docitem_to_chunks_map` sont construits pour permettre l'Anchor Resolution en Pass 1.3b. L'ancrage sera `Information -[:ANCHORED_IN]-> DocItem`, pas sur chunk Qdrant. |
| AV2-4 | DocItem atomique | ✅ | Chaque DocItem correspond à un item Docling natif (`paragraph`, `table`, `picture`, `list_item`, `heading`, `caption`, `footnote`). Pas de fusion agressive — les items TEXT consécutifs restent séparés en tant que DocItems, et ne sont fusionnés que dans les chunks (TypeAwareChunker). |
| AV2-8 | Dual Storage | ✅ | Les `TypeAwareChunk` alimentent Qdrant (retrieval vectoriel). Les `DocItem`/`SectionInfo` alimentent Neo4j (graphe structurel navigable). La séparation des responsabilités est respectée. |
| AV2-10 | < 250 nodes/document | ⚠️ | Pass 0 Structural crée potentiellement beaucoup de DocItems (~centaines à ~milliers par document). Cependant, la stratégie Lazy DocItem Persistence réduit les nodes **effectivement créés** en Neo4j à ~50-200 (ceux ancrés par des Informations PROMOTED). Le reste existe uniquement en mémoire dans le `Pass0Result`. |
| NS-3 | Citation exacte obligatoire | ✅ | Chaque DocItem a `charspan_start/end` (per-page) et `charspan_start_docwide/end_docwide` (document-wide), permettant la traçabilité exacte vers le texte source. `reading_order_index` assure l'ordonnancement. |
| NS-4 | Pas de synthèse cross-source | ✅ | Pass 0 Structural traite un seul document à la fois. Le `doc_version_id` (hash stable) identifie la version exacte. |

---

### 6.4 Risques — Pass 0 Structural

| # | Risque | Niveau | Description | Mitigation |
|---|--------|--------|-------------|------------|
| R0S-1 | **Heading level mal inféré** | 🟡 | `infer_heading_level_from_text()` utilise des patterns regex pour déduire le niveau de heading (`1.` → level 1, `1.1.` → level 2). Ces patterns peuvent échouer sur des numérotations non standard ou des headings sans numérotation. Un heading mal classifié impacte la hiérarchie des sections. | Fallback vers page-based si aucun heading détecté. Le profil structurel de chaque section compense partiellement (les sections mal découpées auront un profil atypique). |
| R0S-2 | **DocItems très nombreux** | 🟡 | Un document de 100+ pages peut produire des milliers de DocItems (>6700 observés). En mémoire, ceci est gérable, mais la persistance Neo4j naïve serait coûteuse. | Lazy DocItem Persistence : seuls les DocItems ancrés par des Informations PROMOTED sont créés en Neo4j (~50-200/doc). Le batch de 500 items par transaction Neo4j évite les timeouts. |
| R0S-3 | **Chunks NARRATIVE trop longs** | 🟢 | Le `max_chunk_size` de 3000 chars est un garde-fou. Les items narratifs consécutifs sont fusionnés jusqu'à cette limite. Un paragraphe unique > 3000 chars sera un chunk solo. | Le seuil de 3000 chars est configurable. Les chunks trop longs sont moins performants pour l'embedding mais restent fonctionnels. |
| R0S-4 | **Cache v5 — Sections non sérialisées** | 🟡 | Le CacheLoader reconstruit les chunks et DocItems depuis le cache, mais les `SectionInfo` ne sont **pas** sérialisées. Le `Pass0Result` chargé depuis le cache a `sections=[]`. | Les sections sont recalculées si nécessaire par les passes suivantes (Pass 0.9 Global View utilise le full_text). Pour les cas où les sections sont critiques, un re-build complet via `Pass0Adapter.process_document()` est requis. |
| R0S-5 | **AssertionUnitIndexer import lazy** | 🟢 | L'import de `AssertionUnitIndexer` est fait en lazy (`try/except ImportError`). Si le module n'est pas disponible, l'indexation est silencieusement ignorée et `unit_index` reste vide. | Log warning émis. Le pipeline continue sans unit_index — Pass 1.3 utilisera un mode fallback (copie verbatim au lieu de pointage). |
| R0S-6 | **Deux schémas Neo4j coexistants** | 🟡 | Le code maintient deux chemins de persistance : legacy (`SectionContext`, `DocumentVersion`, `PageContext`) et V2 (`Document`, `Section`, `DocItem`). Le choix dépend du feature flag `stratified_pipeline_v2`. | Le feature flag assure un basculement propre. Le code legacy sera retiré après validation complète du pipeline V2. |
| R0S-7 | **Hash de document non déterministe** | 🟢 | Le `compute_doc_hash()` utilise des mesures de déterminisme (exclusion champs volatiles, tri par self_ref, arrondi floats, JSON canonique). Mais si Docling change la structure de sortie entre versions, le hash changera. | Le préfixe `v1:` du hash permet de versionner l'algorithme. Le `docling_version` est tracé dans `DocumentVersion`. |

---

## 7. Pass 0.5 — Résolution de Coréférence Linguistique

**Fichiers principaux :**
- `src/knowbase/ingestion/pipelines/pass05_coref.py` — classe `Pass05CoreferencePipeline` (orchestrateur)
- `src/knowbase/linguistic/coref_engine.py` — interface `ICorefEngine` + implémentations (spaCy, FastCoref, RuleBased, Coreferee)
- `src/knowbase/linguistic/coref_models.py` — modèles (`MentionSpan`, `CoreferenceChain`, `CorefDecision`, `CorefLink`)
- `src/knowbase/linguistic/coref_gating.py` — classe `CorefGatingPolicy` (politique conservative)
- `src/knowbase/linguistic/coref_named_gating.py` — classe `NamedNamedGatingPolicy` (filtrage Named↔Named)
- `src/knowbase/linguistic/coref_llm_arbiter.py` — classe `CorefLLMArbiter` (arbitrage LLM pour cas ambigus)
- `src/knowbase/linguistic/coref_cache.py` — classe `CorefCache` (cache des décisions)
- `src/knowbase/linguistic/coref_persist.py` — classe `CorefPersistence` (persistance Neo4j)

**Objectif :** Résoudre les coréférences linguistiques (pronoms → antécédents, groupes nominaux → entités nommées) dans le texte du document. La résolution produit une `CorefGraph` (MentionSpan, CoreferenceChain, CorefDecision) persistée en Neo4j.

**⚠️ Statut V2 :** Pass 0.5 est **désactivée** quand le feature flag `stratified_pipeline_v2` est activé (cf. risque R0-8 dans section 5.10). Les modèles `MentionSpan`/`CoreferenceChain` ne font pas partie de l'architecture V2 (8 types de nodes max). La coréférence en V2 sera gérée différemment (à définir).

### 7.0 Vue d'ensemble Pass 0.5

**Entrants :**

| Entrant | Type | Source |
|---------|------|--------|
| DocItems de type narratif | Nodes Neo4j (`NARRATIVE_TEXT`, `PARAGRAPH`, `TEXT`) | Pass 0 Structural (graphe Document → Section → DocItem) |
| TypeAwareChunks | Nodes Neo4j | Pass 0 Structural (chunking type-aware) |
| Langue du document | `str` (propriété `DocumentVersion.language`) | Pass 0 Structural (détection ou défaut `"en"`) |
| `doc_id` | `str` | ID unique du document |
| `doc_version_id` | `str` | ID de version du document |
| `tenant_id` | `str` | Contexte multi-tenant (défaut : `"default"`) |

**Texte reconstitué :** Le pipeline charge les DocItems de type narratif depuis Neo4j, les trie par `reading_order_index`, et les concatène (séparateur `\n`) pour obtenir le `full_text` soumis à l'engine de coréférence. Les chunks sont utilisés pour l'ancrage secondaire des MentionSpan.

**Sorties :**

| Sortie | Type | Destination |
|--------|------|-------------|
| `MentionSpan` | Nodes Neo4j (fait linguistique) | Graphe linguistique — ancrage sur DocItem + chunk |
| `CoreferenceChain` | Nodes Neo4j (groupement) | Graphe linguistique — relie N MentionSpan coréférents |
| `CorefLink` | Relations Neo4j (`COREFERS_TO`) | Graphe linguistique — liens résolus pronom → antécédent |
| `CorefDecision` | Nodes Neo4j (audit) | Trail d'audit — décisions RESOLVED / ABSTAIN / NON_REFERENTIAL |
| `MATCHES_PROTOCONCEPT` | Relations Neo4j (optionnel) | Alignements lexicaux MentionSpan → ProtoConcept |
| `Pass05Result` | Dataclass Python | Métriques retournées à l'orchestrateur (spans, chaînes, liens, taux, timing) |

**Métriques clés (Pass05Result) :**

| Métrique | Description |
|----------|-------------|
| `mention_spans_created` | Nombre total de MentionSpan créés |
| `chains_created` | Nombre de CoreferenceChain (clusters) |
| `links_created` | Nombre de CorefLink (`COREFERS_TO`) résolus |
| `decisions_created` | Nombre de CorefDecision (audit trail) |
| `resolution_rate` | % de pronoms résolus / total pronoms détectés |
| `abstention_rate` | % de pronoms abstention / total pronoms détectés |
| `engine_used` | Nom de l'engine utilisé (FastCoref, Coreferee, RuleBased) |
| `processing_time_ms` | Durée totale du traitement |

**Configuration (Pass05Config) :**

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `confidence_threshold` | 0.85 | Seuil de confiance engine pour accepter un lien pronom |
| `max_sentence_distance` | 2 | Distance max en phrases entre pronom et antécédent |
| `max_char_distance` | 500 | Distance max en caractères |
| `enable_named_gating` | `True` | Activer le filtrage Named↔Named (Jaro-Winkler + LLM) |
| `named_jaro_reject` | 0.55 | Seuil Jaro-Winkler pour REJECT immédiat |
| `named_jaro_accept` | 0.95 | Seuil Jaro-Winkler pour ACCEPT immédiat |
| `named_jaccard_accept` | 0.8 | Seuil Token Jaccard pour ACCEPT |
| `enable_llm_arbitration` | `True` | Activer l'arbitrage LLM pour les paires en REVIEW |
| `skip_if_exists` | `True` | Idempotence — ne pas retraiter si CorefGraph existe |
| `create_protoconcept_links` | `True` | Créer les liens MATCHES_PROTOCONCEPT |
| `persist_decisions` | `True` | Persister les CorefDecision (audit) |
| `fastcoref_batch_size` | 50 000 | Taille max d'un batch (chars) pour éviter OOM |
| `fastcoref_batch_overlap` | 3 000 | Overlap entre batches (chars) pour contexte coréférentiel |

---

### 7.1 Mécanismes de résolution

#### 7.1.1 Architecture en pipeline

```
Étape 1: Idempotence — Vérifier si déjà traité
  ↓
Étape 2: Charger DocItems + Chunks depuis Neo4j
  ↓
Étape 3: Détecter la langue du document
  ↓
Étape 4: Sélectionner l'engine de coréférence
  ↓
Étape 5: Résoudre les coréférences (engine + batching OOM)
  ↓
Étape 5b: Filtrer les faux positifs Named↔Named (gating + LLM)
  ↓
Étape 6: Appliquer la politique de gating (pronoms)
  ↓
Étape 7: Persister la CorefGraph dans Neo4j
  ↓
Étape 8: Créer les liens MATCHES_PROTOCONCEPT (optionnel)
```

#### 7.1.2 Engines de coréférence (multilingue)

| Engine | Langues | Disponibilité | Caractéristiques |
|--------|---------|---------------|-----------------|
| **FastCoref** (spaCy + F-Coref) | EN | `FASTCOREF_AVAILABLE` | Meilleur pour l'anglais, ~800MB mémoire, singleton pour éviter double-chargement |
| **SpaCy CoreferenceResolver** | EN | `SPACY_COREF_AVAILABLE` | Alternative spaCy native |
| **Coreferee** | FR, EN, DE | `COREFEREE_AVAILABLE` | Expérimental, dernier release 2022 — marqué swappable |
| **RuleBasedEngine** | Toutes | Toujours | Fallback universel — heuristiques regex simples |

Sélection automatique via `get_engine_for_language(lang)` — EN préfère FastCoref, FR/DE préfère Coreferee, fallback vers RuleBasedEngine.

#### 7.1.3 Section batching (OOM Fix)

Pour les documents > `fastcoref_batch_size` chars (défaut : 50 000 chars, ~12 pages), le pipeline :
1. Groupe les DocItems par sections jusqu'à `batch_size` chars
2. Ajoute un overlap de `fastcoref_batch_overlap` chars (défaut : 3000) entre batches pour le contexte coréférentiel
3. Résout chaque batch indépendamment via l'engine
4. Ajuste les offsets des clusters au document complet
5. Déduplique les clusters de l'overlap (par signature `(start, end)`)

#### 7.1.4 Politique de gating conservative (pronoms)

**Classe :** `CorefGatingPolicy`

**Invariants :**
- **L3** : Closed-world disambiguation — candidats locaux uniquement
- **L4** : Abstention-first — ambiguïté → ABSTAIN

| Critère | Seuil | Effet |
|---------|-------|-------|
| Confiance engine | ≥ 0.85 | En-dessous → ABSTAIN (LOW_CONFIDENCE) |
| Distance sentences | ≤ 2 | Au-delà → ABSTAIN (LONG_DISTANCE) |
| Distance chars | ≤ 500 | Au-delà → ABSTAIN (LONG_DISTANCE) |
| Candidats multiples | >1 valide | → ABSTAIN (AMBIGUOUS) |
| Pronom non référentiel | Détecté | → NON_REFERENTIAL (IMPERSONAL, EXPLETIVE, GENERIC) |

**Décision types :** `RESOLVED` | `ABSTAIN` | `NON_REFERENTIAL`

#### 7.1.5 Gating Named↔Named (ADR_COREF_NAMED_NAMED_VALIDATION)

**Classe :** `NamedNamedGatingPolicy`

**Objectif :** Filtrer les faux positifs quand l'engine regroupe deux noms propres différents dans un même cluster (ex: "SAP S/4HANA" ↔ "SAP BTP").

**Stratégie 3-tier :**

| Condition | Décision | Seuils |
|-----------|----------|--------|
| Jaro-Winkler < 0.55 | `REJECT` | STRING_SIMILARITY_LOW |
| Jaro-Winkler ≥ 0.95 OU Token Jaccard ≥ 0.8 | `ACCEPT` | HIGH_SIMILARITY |
| Zone intermédiaire | `REVIEW` | Envoyé au LLM Arbiter |

**LLM Arbiter** (`CorefLLMArbiter`) : Arbitrage batch pour les paires en REVIEW. Décisions : `same_entity=True/False` ou `abstain=True`.

**Cache** (`CorefCache`) : Cache des décisions Named↔Named (paire → même entité ou non) pour éviter les appels LLM répétés.

#### 7.1.6 Types de mentions

| Type | Exemples | Traitement |
|------|----------|-----------|
| `PRONOUN` | it, they, il, elle | Gating conservative (L4) |
| `PROPER` | SAP S/4HANA, iPhone 15 | Named↔Named gating |
| `NP` | le système, the device | Named↔Named gating |
| `OTHER` | — | Exclu de la résolution |

#### 7.1.7 Modèles de données CorefGraph

```
MentionSpan (fait linguistique, pas assertion)
  ├── tenant_id, doc_id, doc_version_id
  ├── docitem_id (ancrage principal → DocItem)
  ├── chunk_id (ancrage secondaire → TypeAwareChunk)
  ├── span_start, span_end (offsets exacts — L1)
  ├── surface (texte verbatim)
  ├── mention_type: MentionType (PRONOUN | NP | PROPER | OTHER)
  └── lang, sentence_index

CoreferenceChain
  ├── chain_id, tenant_id, doc_id, doc_version_id
  ├── method (engine utilisé)
  ├── confidence
  ├── mention_ids: List[str]
  └── representative_mention_id

CorefLink
  ├── source_mention_id → target_mention_id
  ├── method, confidence
  ├── scope: CorefScope (SAME_SENTENCE | PREV_SENTENCE | PREV_CHUNK | WINDOW_K)
  └── window_chars

CorefDecision (audit trail)
  ├── decision_type: RESOLVED | ABSTAIN | NON_REFERENTIAL
  ├── reason_code: ReasonCode (UNAMBIGUOUS, AMBIGUOUS, LOW_CONFIDENCE, etc.)
  └── reason_detail
```

#### 7.1.8 Liens MATCHES_PROTOCONCEPT

Si `create_protoconcept_links=True`, le pipeline :
1. Charge les `ProtoConcept` du document depuis Neo4j
2. Pour chaque `MentionSpan` de type PROPER ou NP, cherche une correspondance lexicale avec un ProtoConcept
3. Crée un lien `MATCHES_PROTOCONCEPT` (confidence=0.9, method="lexical_match")

**NOTE GOUVERNANCE** : Ces liens sont des **alignements lexicaux/ancrés**, PAS des identités ontologiques.

---

### 7.2 Conformité ADR — Pass 0.5

| # | Axe ADR | Statut | Analyse |
|---|---------|--------|---------|
| AV2-1 | Séparation structure / sémantique | ⚠️ | Pass 0.5 opère sur la couche **linguistique**, distincte de la structure documentaire ET de la sémantique. Cependant, les `MentionSpan` et `CoreferenceChain` ne font pas partie des 8 types de nodes V2, ce qui crée un conflit avec AV2-2. |
| AV2-2 | 8 types de nodes maximum | ❌ | Pass 0.5 crée des types de nodes supplémentaires (`MentionSpan`, `CoreferenceChain`, `CorefDecision`) qui ne font pas partie du schéma V2 (Document, Section, DocItem, Subject, Theme, Concept, Information, AssertionLog). C'est la raison de la désactivation en mode V2. |
| NS-2 | LLM = Extracteur evidence-locked | ✅ | Le LLM Arbiter est strictement un **arbitre** (même entité ou non ?), pas un extracteur. Il n'invente pas de coréférences — il valide/rejette celles proposées par l'engine. |
| NS-3 | Citation exacte obligatoire | ✅ | Les `MentionSpan` conservent les offsets exacts (`span_start`, `span_end`) et le texte verbatim (`surface`). Invariant L1 (Evidence-preserving) respecté. |

**Invariants linguistiques :**

| Invariant | Description | Statut |
|-----------|-------------|--------|
| L1 | Evidence-preserving (spans exacts) | ✅ Offsets conservés |
| L2 | No generated evidence (pas de texte modifié persisté) | ✅ Le texte original n'est jamais altéré |
| L3 | Closed-world disambiguation | ✅ Candidats locaux (fenêtre courte) uniquement |
| L4 | Abstention-first | ✅ Politique conservative, seuil 0.85, ABSTAIN sur ambiguïté |
| L5 | Linguistic-only | ✅ Pas de relation conceptuelle — fait linguistique pur |

---

### 7.3 Risques — Pass 0.5

| # | Risque | Niveau | Description | Mitigation |
|---|--------|--------|-------------|------------|
| R05-1 | **Désactivée en V2** | 🟡 | Pass 0.5 est entièrement désactivée quand `stratified_pipeline_v2=True`. Les coréférences ne sont pas résolues dans le pipeline V2, ce qui peut dégrader la qualité de l'extraction d'assertions (pronoms non résolus dans le texte source). | Décision architecturale consciente. La coréférence V2 nécessite une refonte pour s'intégrer dans le schéma 8-nodes (potentiellement comme metadata sur DocItem plutôt que nodes séparés). |
| R05-2 | **OOM FastCoref sur gros documents** | 🟡 | FastCoref charge ~800MB (spaCy + modèle). Les documents > 50K chars nécessitent un section batching. Le seuil a été réduit de 100K à 50K après un OOM sur un document de 106K chars. | Section batching avec overlap de 3K chars. Singleton FastCoref pour éviter double chargement. |
| R05-3 | **Coreferee obsolète** | 🟡 | Le moteur Coreferee (utilisé pour FR/DE) a son dernier release en 2022. Il est marqué "swappable sans douleur" mais aucune alternative n'est identifiée. | Fallback vers RuleBasedEngine si Coreferee indisponible. L'interface `ICorefEngine` permet le swap transparent. |
| R05-4 | **Offset lookup simpliste** | 🟡 | `_find_docitem_for_offset()` et `_find_chunk_for_offset()` retournent actuellement le **premier** DocItem/chunk (TODO dans le code). L'ancrage MentionSpan → DocItem est potentiellement incorrect pour les mentions en milieu/fin de document. | Marqué TODO dans le code. En mode V2 désactivé, ce bug n'a pas d'impact. |
| R05-5 | **Named↔Named gating — faux rejets** | 🟢 | Le seuil Jaro-Winkler de 0.55 pour REJECT est agressif. Des variantes légitimes (ex: "SAP S/4HANA 2023" vs "S/4HANA") pourraient être rejetées à tort. | Le LLM Arbiter traite les cas en zone grise (REVIEW). Le cache évite les appels LLM répétés. |
| R05-6 | **Pas d'intégration avec Pass 1.x** | 🟡 | Les résultats de coréférence (CorefGraph) ne sont pas exploités par les passes sémantiques (Pass 1.1-1.4). Le module `coref_assertion_bridge.py` existe mais l'intégration n'est pas documentée. | Le pipeline V2 contournera ce problème en intégrant la coréférence différemment (à concevoir). |

---

## 8. Pass 0.9 — Construction de la Vue Globale

### 8.0 Vue d'ensemble Pass 0.9

**Module :** `src/knowbase/stratified/pass09/` (5 fichiers)
**Orchestrateur :** `global_view_builder.py` — classe `GlobalViewBuilder`
**Modèles :** `models.py` — `GlobalView`, `SectionSummary`, `GlobalViewCoverage`, `Pass09Config`
**Composants :** `SectionSummarizer` (résumé LLM par section), `HierarchicalCompressor` (assemblage meta-document)

**Objectif :** Construire un **meta-document** synthétique (15-30K chars, cible 20K) représentant l'intégralité du document source sous forme compressée. Ce meta-document remplace le `full_text` brut comme entrée pour les passes analytiques (Pass 1.1, Pass 1.2), permettant au LLM de « voir » l'ensemble du document dans une seule fenêtre de contexte.

**Entrants :**

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `sections` | `List[Dict]` | Pass 0 Structural (graphe structurel) | Liste des sections avec `id`, `title`, `level`, `text` ou `chunk_ids` |
| `chunks` | `Dict[str, str]` | Pass 0 Structural | Mapping `chunk_id → texte` pour résoudre les chunk_ids des sections |
| `full_text` | `str` | Pass 0 Extraction | Texte linéarisé complet (fallback si sections sans texte direct) |
| `doc_id` | `str` | Pipeline | Identifiant unique du document |
| `tenant_id` | `str` | Pipeline | Identifiant du tenant (défaut : `"default"`) |
| `doc_title` | `str` | Pass 0 Extraction | Titre du document (optionnel) |

**Séquence d'exécution :**

```
Étape 1: Extraction des textes par section
  → _extract_section_texts() : résolution text direct / chunk_ids / item_ids / positions
  ↓
Étape 2: Résumé de chaque section (SectionSummarizer)
  → Parallèle async avec Semaphore(max_concurrent_summaries=10)
  → Décision par section : skip / verbatim / LLM / truncated
  ↓
Étape 3: Compression en meta-document (HierarchicalCompressor)
  → Assemblage hiérarchique (headings Markdown)
  → Construction TOC enrichie
  → Enforcement des limites de taille
  ↓
Étape 4: Construction GlobalView
  → meta_document + section_summaries + toc_enhanced + coverage + métadonnées
  ↓
Étape 5: Validation
  → coverage_ratio ≥ 95%, taille dans [5000, 30000] chars
```

**Sortie :**

```
GlobalView
  ├── tenant_id: str
  ├── doc_id: str
  ├── meta_document: str  ← SORTIE PRINCIPALE (15-30K chars)
  ├── section_summaries: Dict[str, SectionSummary]
  ├── toc_enhanced: str  ← TOC enrichie avec concepts et types
  ├── coverage: GlobalViewCoverage
  │     ├── sections_total: int
  │     ├── sections_summarized: int
  │     ├── sections_verbatim: int
  │     ├── sections_skipped: int
  │     ├── chars_original: int
  │     ├── chars_meta_document: int
  │     ├── coverage_ratio: float  (propriété calculée)
  │     └── compression_ratio: float  (propriété calculée)
  ├── created_at: datetime
  ├── llm_model_used: str  ("gpt-4o-mini" ou "")
  ├── total_llm_calls: int
  ├── total_tokens_used: int
  ├── build_time_seconds: float
  ├── is_fallback: bool  (True si construit sans LLM)
  └── errors: List[str]
```

---

### 8.1 SectionSummarizer

**Fichier :** `src/knowbase/stratified/pass09/section_summarizer.py` — classe `SectionSummarizer`
**Modèle LLM :** `gpt-4o-mini` (temperature=0.3, max_tokens=500)

**Objectif :** Résumer chaque section du document en un résumé informatif fidèle (max 800 chars par défaut), tout en identifiant les concepts, types d'assertions et valeurs clés présents dans la section.

#### 8.1.1 Stratégie de traitement par section

Le SectionSummarizer applique une **stratégie adaptative** en fonction de la taille de chaque section :

| Condition | Méthode (`method`) | Comportement |
|-----------|-------------------|-------------|
| `char_count < 200` (`section_min_chars_to_summarize`) | `"skipped"` | Copie verbatim du texte (ou `"(section vide)"`) — section trop courte pour mériter un résumé |
| `200 ≤ char_count < 500` (`section_max_chars_for_verbatim`) | `"verbatim"` | Copie verbatim — section suffisamment courte pour être incluse telle quelle |
| `char_count ≥ 500` | `"llm"` | Résumé via appel LLM — section nécessitant compression |
| Erreur LLM | `"truncated"` | Fallback : premiers 1000 chars (`fallback_chars_per_section`) + `"..."` |

#### 8.1.2 Parallélisation des résumés

Les résumés sont exécutés en **parallèle asynchrone** via `asyncio.gather()` avec un `asyncio.Semaphore(max_concurrent_summaries)` (défaut : 10 appels simultanés). Les erreurs individuelles sont capturées via `return_exceptions=True` — un échec d'une section n'empêche pas le traitement des autres.

#### 8.1.3 Prompt LLM

**System prompt :** Directive d'expert en analyse documentaire. Règles :
- Maximum `{max_chars}` caractères (configurable, défaut 800)
- Identifier les **concepts clés** (termes techniques, entités)
- Noter les **types d'assertions** (definitional, prescriptive, factual, procedural)
- Préserver les **valeurs spécifiques** (versions, pourcentages, limites, durées)
- Ne PAS interpréter, seulement résumer fidèlement
- Style neutre et factuel

**User prompt :** Fournit le titre de section, son niveau hiérarchique, et le contenu (tronqué à 8000 chars pour respecter la fenêtre LLM).

**Format de réponse attendu :** JSON strict :
```json
{
  "summary": "Résumé de la section (max {max_chars} chars)",
  "concepts": ["concept1", "concept2", "concept3"],
  "assertion_types": ["definitional", "prescriptive", "factual"],
  "key_values": ["TLS 1.2", "99.95%", "30 days"]
}
```

**Nettoyage de la réponse :** Le parser gère les réponses enveloppées dans des blocs markdown (\`\`\`json...\`\`\`) et, en cas d'échec de parsing JSON, extrait manuellement le résumé (premiers `max_chars` chars de la réponse brute).

#### 8.1.4 Compatibilité multi-client LLM

Le SectionSummarizer supporte trois interfaces LLM :

| Interface | Méthode de détection | Appel |
|-----------|---------------------|-------|
| OpenAI-style | `hasattr(client, "chat")` | `client.chat.completions.create(model="gpt-4o-mini", ...)` |
| vLLM-style | `hasattr(client, "generate")` | `client.generate(prompt=..., max_tokens=500)` |
| Sync fallback | `hasattr(client, "complete")` | `client.complete(prompt=..., max_tokens=500)` |

#### 8.1.5 Sortie `SectionSummary`

```
SectionSummary
  ├── section_id: str
  ├── section_title: str
  ├── level: int  (1=H1, 2=H2, 3=H3...)
  ├── summary: str  (500-1000 chars max)
  ├── concepts_mentioned: List[str]  (termes techniques identifiés)
  ├── assertion_types: List[str]  (definitional, prescriptive, factual, procedural)
  ├── key_values: List[str]  (valeurs spécifiques préservées)
  ├── char_count_original: int
  ├── char_count_summary: int
  ├── method: str  ("llm" | "verbatim" | "truncated" | "skipped")
  └── compression_ratio: float  (propriété calculée : summary/original)
```

#### 8.1.6 Statistiques de traitement

Le SectionSummarizer maintient un dictionnaire `_stats` accessible via la propriété `stats` :
- `sections_processed` : nombre de sections résumées par LLM
- `sections_skipped` : nombre de sections trop courtes
- `sections_verbatim` : nombre de sections copiées verbatim
- `total_tokens_in` / `total_tokens_out` : tokens consommés
- `errors` : liste des erreurs rencontrées

---

### 8.2 HierarchicalCompressor

**Fichier :** `src/knowbase/stratified/pass09/hierarchical_compressor.py` — classe `HierarchicalCompressor`

**Objectif :** Assembler les `SectionSummary` individuels en un **meta-document unique** structuré hiérarchiquement, respectant les contraintes de taille (5K-30K chars) et produisant une TOC enrichie.

#### 8.2.1 Mécanisme de compression

La méthode `compress()` exécute 4 étapes séquentielles :

```
1. _calculate_coverage()     → GlobalViewCoverage (statistiques)
2. _build_meta_document()    → str (meta-document structuré Markdown)
3. _build_enhanced_toc()     → str (table des matières enrichie)
4. _enforce_size_limits()    → str (meta-document ajusté si nécessaire)
```

#### 8.2.2 Calcul de couverture (`_calculate_coverage`)

Itère sur tous les `SectionSummary` et classifie :

| Méthode du résumé | Compteur incrémenté |
|-------------------|---------------------|
| `"llm"` | `sections_summarized` |
| `"verbatim"` | `sections_verbatim` |
| `"truncated"` | `sections_summarized` (troncature = fallback de résumé) |
| `"skipped"` | `sections_skipped` |

**coverage_ratio** = `(sections_summarized + sections_verbatim) / sections_total`

> ⚠️ **Note :** Les sections `"skipped"` ne comptent PAS dans la couverture. Le seuil minimum configurable est `min_coverage_ratio = 0.95` (95%).

#### 8.2.3 Construction du meta-document (`_build_meta_document`)

Format Markdown structuré hiérarchiquement :

```markdown
# Document: [titre]

## [Section niveau 1]
[résumé]
**Concepts:** concept1, concept2
**Types:** definitional, prescriptive
**Valeurs:** TLS 1.2, 99.95%

### [Section niveau 2]
[résumé]
...
```

**Règles de formatage :**
- Le niveau de heading Markdown = `min(level + 1, 4)` — maximum `####` pour éviter la pollution
- Les concepts sont limités à 10 par section
- Les valeurs clés sont limitées à 8 par section
- Les métadonnées enrichies (Concepts, Types, Valeurs) sont ajoutées uniquement si présentes
- Les sections sont assemblées dans l'**ordre original** du document (`sections_order`)

#### 8.2.4 Table des matières enrichie (`_build_enhanced_toc`)

Construit une TOC avec numérotation hiérarchique automatique et métadonnées inline :

```
# Table des Matières Enrichie

1. Architecture Overview [5 concepts, definitional/prescriptive]
  1.1 Components [3 concepts, factual]
  1.2 Deployment Model [2 concepts, procedural]
2. Security Framework [4 concepts, prescriptive]
```

**Mécanisme de numérotation :** Compteurs par niveau (5 niveaux max), reset des niveaux inférieurs à chaque incrémentation d'un niveau supérieur.

#### 8.2.5 Enforcement des limites de taille (`_enforce_size_limits`)

| Condition | Action |
|-----------|--------|
| `len(meta_document) > meta_document_max_chars` (30K) | Troncature intelligente via `_smart_truncate()` |
| `len(meta_document) ≤ meta_document_max_chars` | Aucune action |

**Troncature intelligente (`_smart_truncate`) :**
1. Les **headings** (`#...`) sont **toujours préservés**
2. Les lignes de contenu sont ajoutées tant que le budget le permet (marge de sécurité : 100 chars)
3. Les métadonnées (`**Concepts:**...`) sont supprimées en dernier
4. Un marqueur `[... document tronqué pour respecter limite tokens ...]` est ajouté en fin

#### 8.2.6 Sortie

```
Tuple[str, str, GlobalViewCoverage]
  ├── meta_document: str            ← Document compressé structuré (5K-30K chars)
  ├── toc_enhanced: str             ← TOC enrichie avec concepts/types
  └── coverage: GlobalViewCoverage  ← Statistiques de couverture
```

---

### 8.3 GlobalViewBuilder — Orchestration

**Fichier :** `src/knowbase/stratified/pass09/global_view_builder.py` — classe `GlobalViewBuilder`

**Objectif :** Orchestrer la construction complète de la `GlobalView` en coordonnant `SectionSummarizer` et `HierarchicalCompressor`.

#### 8.3.1 Extraction des textes par section (`_extract_section_texts`)

Résout le texte de chaque section selon **5 stratégies** en cascade :

| Priorité | Condition | Source du texte |
|----------|-----------|----------------|
| 1 | `section.text` existe | Texte direct de la section |
| 2 | `section.chunk_ids` non vide | Concaténation des chunks référencés |
| 3 | `section.item_ids` non vide | Concaténation des items (DocItems) depuis le mapping chunks |
| 4 | `section.start_pos / end_pos` définis | Découpage du `full_text` par positions |
| 5 | Aucune source | Chaîne vide `""` |

#### 8.3.2 Mode LLM (`_build_with_llm`) — async

1. **Résumé** : `SectionSummarizer.summarize_sections()` — parallèle async
2. **Compression** : `HierarchicalCompressor.compress()` — synchrone
3. **Assemblage** : `GlobalView` avec `is_fallback=False`, modèle `"gpt-4o-mini"`

#### 8.3.3 Mode Fallback (`_build_fallback`) — synchrone

Activé quand :
- Aucun `llm_client` n'est fourni
- Appel via `build_sync()` (compatibilité FastAPI synchrone)

**Stratégie :** Pour chaque section, tronque le texte aux premiers `fallback_chars_per_section` (1000) caractères + `"..."`. Toutes les sections obtiennent `method="truncated"`. Pas d'extraction de concepts/types/valeurs.

#### 8.3.4 Validation de la GlobalView

La méthode `GlobalView.is_valid(config)` vérifie :
1. `coverage.coverage_ratio ≥ config.min_coverage_ratio` (95%)
2. `len(meta_document) ≥ config.meta_document_min_chars` (5000)
3. `len(meta_document) ≤ config.meta_document_max_chars` (30000)

Si la validation échoue, l'erreur est loggée et ajoutée à `errors`, mais la `GlobalView` est tout de même retournée.

#### 8.3.5 Fonction utilitaire `build_global_view()`

Fonction de convenance async au niveau module pour usage simplifié :

```python
from knowbase.stratified.pass09 import build_global_view

global_view = await build_global_view(
    doc_id="doc_123",
    tenant_id="default",
    sections=sections,
    chunks=chunks,
    llm_client=openai_client,
)
```

---

### 8.4 Intégration dans le Pipeline (Orchestrateur Pass 1)

**Fichier :** `src/knowbase/stratified/pass1/orchestrator.py` — classe `Pass1OrchestratorV2`

Pass 0.9 est intégré comme **première phase** de l'orchestrateur Pass 1, avant l'analyse documentaire (Pass 1.1).

#### 8.4.1 Activation

- Flag `enable_pass09` (défaut : `True`) dans le constructeur de `Pass1OrchestratorV2`
- Configuration optionnelle via `pass09_config: Pass09Config`
- Le `GlobalViewBuilder` est initialisé dans le constructeur si `enable_pass09=True`

#### 8.4.2 Flux d'exécution dans `process()`

```
1. PHASE 0.9: GlobalView Construction
   ├── Si sections vides : création depuis chunks (fallback)
   ├── Appel build_sync() (mode synchrone FastAPI)
   ├── Si GlobalView valide → analysis_content = global_view.meta_document
   ├── Si GlobalView vide/erreur → analysis_content = content brut (fallback)
   └── Si Pass 0.9 désactivé → analysis_content = content brut
   ↓
2. PHASE 1.1: Document Analysis
   ├── Utilise analysis_content (= meta-document OU content brut)
   ├── Si toc_enhanced disponible → utilise pour l'analyse au lieu de la TOC brute
   └── Produit Subject, Themes, DocumentStructure
   ↓
3. PHASE 1.2: Concept Identification
   ├── Utilise analysis_content (= meta-document OU content brut)
   └── Produit List[Concept]
```

#### 8.4.3 Préparation des sections (router API)

**Fichier :** `src/knowbase/stratified/api/router.py`

Avant d'appeler l'orchestrateur Pass 1, le router API prépare les sections pour Pass 0.9 :

```python
sections_for_pass09 = []
for section in structural_sections:
    sections_for_pass09.append({
        "id": section.id,
        "title": section.title,
        "level": section.level,
        "text": section.text,          # Texte direct si disponible
        "chunk_ids": section.chunk_ids  # IDs de chunks référencés
    })
```

Ces sections sont passées via le paramètre `sections=sections_for_pass09` à l'orchestrateur.

---

### 8.5 Configuration Pass 0.9

**Classe :** `Pass09Config` (dataclass)

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `section_summary_max_chars` | `int` | `800` | Taille max d'un résumé de section |
| `section_summary_min_chars` | `int` | `100` | Taille min d'un résumé |
| `section_min_chars_to_summarize` | `int` | `200` | Seuil sous lequel une section est skip/verbatim |
| `section_max_chars_for_verbatim` | `int` | `500` | Seuil sous lequel une section est copiée verbatim |
| `meta_document_min_chars` | `int` | `5000` | Taille min du meta-document |
| `meta_document_max_chars` | `int` | `30000` | Taille max du meta-document |
| `meta_document_target_chars` | `int` | `20000` | Taille cible du meta-document |
| `min_coverage_ratio` | `float` | `0.95` | Couverture minimum requise (95%) |
| `max_concurrent_summaries` | `int` | `10` | Nombre max de résumés LLM en parallèle |
| `enable_fallback` | `bool` | `True` | Active le mode fallback (troncature) |
| `fallback_chars_per_section` | `int` | `1000` | Chars par section en mode fallback |

---

### 8.6 Conformité ADR — Pass 0.9

| Axe | Exigence | Statut | Implémentation | Commentaire |
|-----|----------|--------|----------------|-------------|
| P09-1 | **Couverture 100% sections** | ⚠️ | Le meta-document itère sur toutes les sections dans `sections_order`, mais les sections `"skipped"` (< 200 chars) ne comptent pas dans le `coverage_ratio`. | Le coverage_ratio exige 95% (`min_coverage_ratio`), pas 100%. Les sections très courtes sont incluses en verbatim ou skip mais toujours présentes dans le meta-document. |
| P09-2 | **Compression hiérarchique** | ✅ | `HierarchicalCompressor._build_meta_document()` préserve la hiérarchie H1 > H2 > H3 via le calcul `"#" * min(level + 1, 4)`. | Limitation à `####` (H4) pour éviter la pollution Markdown. La structure originale est fidèlement reproduite. |
| P09-3 | **Meta-document 15-25K chars** | ⚠️ | Fourchette implémentée : [5000, 30000] chars (config), cible 20000. | La fourchette est plus large que l'ADR (15-25K). Le `_enforce_size_limits` tronque intelligemment si > 30K. Pas de mécanisme d'expansion si < 5K. |
| P09-4 | **95% minimum sections résumées** | ✅ | `min_coverage_ratio = 0.95` dans `Pass09Config`, vérifié par `GlobalView.is_valid()`. | Les sections `"skipped"` ne comptent pas, mais les sections vides sont rares dans un document structuré. |
| P09-5 | **Fallback mode (Option C)** | ✅ | `_build_fallback()` opérationnel : tronque chaque section aux premiers 1000 chars. Mode synchrone, sans appel LLM. Activé automatiquement si `llm_client=None` ou via `build_sync()`. | Le fallback est fonctionnel et produit une GlobalView valide avec `is_fallback=True`. |
| P09-6 | **Intégration dans Pass 1.1 et 1.2** | ✅ | L'orchestrateur Pass 1 utilise `global_view.meta_document` comme `analysis_content` pour Pass 1.1 (DocumentAnalyzer) et Pass 1.2 (ConceptIdentifier). La `toc_enhanced` remplace la TOC brute pour l'analyse. | L'intégration est complète avec fallback automatique sur `content` brut si GlobalView absente ou invalide. |

---

### 8.7 Risques — Pass 0.9

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R09-1 | **Mode sync = toujours fallback** | 🟡 | `build_sync()` utilise systématiquement le mode fallback (troncature), même si un `llm_client` est disponible. Les résumés LLM ne sont accessibles qu'en mode async. | Le router API actuel utilise `build_sync()` dans le contexte FastAPI. Pour bénéficier des résumés LLM, il faudrait refactorer vers `build()` async. |
| R09-2 | **Pas de gestion du budget tokens** | 🟡 | Le texte envoyé au LLM est tronqué à 8000 chars (`text[:8000]`), mais il n'y a pas de calcul de tokens réel (tiktoken). Pour les sections longues en encodage non-ASCII, 8000 chars peut dépasser la fenêtre du modèle. | Ajouter un compteur de tokens réel ou réduire la limite de chars pour les langues non-latines. |
| R09-3 | **Perte d'information dans les sections skip** | 🟢 | Les sections < 200 chars sont `"skipped"` et incluses verbatim. Aucune extraction de concepts/types/valeurs n'est effectuée pour ces sections. | Impact mineur : les sections très courtes contiennent rarement des concepts distincts non couverts par les sections parentes. |
| R09-4 | **Détection de format de réponse LLM fragile** | 🟡 | Le parser JSON nettoie les blocs markdown mais ne gère pas tous les cas de malformation (ex : JSON avec commentaires, trailing commas). | Le fallback vers extraction manuelle (`response[:max_chars]`) garantit qu'un résumé est toujours produit, même si les métadonnées (concepts, types) sont perdues. |
| R09-5 | **Modèle LLM hardcodé** | 🟢 | Le modèle `"gpt-4o-mini"` est hardcodé dans `_call_openai_style()` et dans les métadonnées de `GlobalView`. Pas de routing via `llm_models.yaml`. | Acceptable pour V2 beta. À intégrer au `LLMRouter` pour la production. |
| R09-6 | **Pas de cache des résumés** | 🟡 | Chaque exécution de Pass 0.9 recalcule tous les résumés de section, même pour un document déjà traité. Pas de persistance des `SectionSummary`. | Ajouter un cache basé sur `hash(section_text)` pour éviter les appels LLM redondants lors de re-traitements. |
| R09-7 | **Fourchette de taille plus large que l'ADR** | 🟢 | L'ADR spécifie 15-25K chars, l'implémentation accepte 5K-30K. | La fourchette élargie est pragmatique pour gérer les documents très courts (< 15K) et très longs (> 25K). Le `meta_document_target_chars = 20000` reste dans la cible ADR. |

---

## 9. Pass 1.1 — Analyse Documentaire

**Fichier principal :** `src/knowbase/stratified/pass1/document_analyzer.py` — classe `DocumentAnalyzerV2`
**Orchestration :** `src/knowbase/stratified/pass1/orchestrator.py` — `Pass1OrchestratorV2.process()`, lignes 227-251
**Schema Structured Output :** `src/knowbase/stratified/pass1/llm_schemas.py` — `DocumentAnalysisResponse`

### 9.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `doc_id` | `str` | Pipeline | Identifiant unique du document |
| `doc_title` | `str` | Pass 0 | Titre du document extrait |
| `content` / `analysis_content` | `str` | Pass 0.9 ou Pass 0 | **Changement clé V2 :** si Pass 0.9 actif, le contenu analysé est le `meta-document` (vue globale comprimée 15-25K chars). Sinon, le contenu brut complet est utilisé. |
| `toc` / `toc_for_analysis` | `Optional[str]` | Pass 0 / Pass 0.9 | Table des matières. Si `global_view.toc_enhanced` disponible (depuis Pass 0.9), elle remplace la TOC brute. Sinon, extraction heuristique via `extract_toc_from_content()`. |
| `char_limit` | `int` | Config (défaut: 4000) | Limite de caractères pour le preview envoyé au LLM |

### 9.2 Objectifs

Pass 1.1 réalise l'analyse structurelle de haut niveau du document selon l'approche **top-down** (AV2-7). Les trois sorties principales sont :

1. **Subject** — Résumé du sujet principal en 1 phrase, avec un nom court (5-10 mots) dérivé automatiquement si non fourni par le LLM.
2. **DocumentStructure** — Classification de la structure de dépendance du document selon 3 types universels issus de l'ADR Modèle de Lecture Stratifiée :
   - **CENTRAL** : assertions dépendantes d'un artefact unique (ex : guide produit SAP). Test : « sans X, ce document a-t-il un sens ? » → NON.
   - **TRANSVERSAL** : assertions indépendantes du contexte (ex : réglementation GDPR). Test : remplacer le nom propre → assertion reste vraie.
   - **CONTEXTUAL** : assertions conditionnelles, vraies uniquement sous certaines conditions.
3. **Themes** — Liste des thèmes majeurs (5-10 maximum) identifiés dans le document.

**Sortie annexe :** détection du flag `is_hostile` si le nombre de thèmes dépasse `HOSTILE_SUBJECT_THRESHOLD = 10`, indiquant un document multi-sujet problématique.

### 9.3 Mécanismes

#### 9.3.1 Appel LLM

L'analyse est **entièrement déléguée au LLM** (pas d'algorithme heuristique en mode production) :

1. **Préparation du preview** : `content[:char_limit]` (4000 chars par défaut)
2. **Chargement des prompts** depuis `src/knowbase/stratified/prompts/pass1_prompts.yaml` (clé `document_analysis`), avec fallback sur prompts par défaut intégrés à la classe
3. **Génération** : appel `llm_client.generate(system_prompt, user_prompt, max_tokens=1500)`
4. **Parsing** : extraction du bloc JSON (````json ... ````) ou parsing direct de la réponse

**Schema Structured Output (Volet B) :**

```python
class DocumentAnalysisResponse(BaseModel):
    subject_name: str    # max 50 chars — Nom court (5-10 mots)
    subject: str         # max 200 chars — Résumé 1 phrase
    structure: StructureInfo  # chosen: CENTRAL|TRANSVERSAL|CONTEXTUAL + justification
    themes: List[str]    # max 10 thèmes
    language: LanguageEnum  # fr|en|de
```

Ce schema est utilisable avec vLLM Structured Outputs (`response_format={"type": "json_schema"}`) pour garantir la structure JSON.

#### 9.3.2 Validation et conversion

La méthode `_validate_and_convert()` transforme la réponse LLM en objets Pydantic V2 :

- **Subject** : création avec `subject_id = f"subj_{doc_id}"`, structure de dépendance parsée, justification optionnelle, langue détectée
- **Themes** : chaque thème reçoit un `theme_id = f"theme_{doc_id}_{idx}"`. Le champ `scoped_to_sections` est initialisé vide (sera rempli ultérieurement).
- **Dérivation du nom court** : si le LLM ne fournit pas `subject_name`, il est dérivé du texte du sujet (premiers mots avant la première virgule ou le premier point, tronqué à 80 chars)

#### 9.3.3 Détection de documents HOSTILE

Après l'analyse LLM, un test post-hoc vérifie si le document est "hostile" :

```python
is_hostile = len(themes) > HOSTILE_SUBJECT_THRESHOLD  # seuil = 10
```

Un document hostile est un document multi-sujet qui rend l'identification de concepts difficile. Le flag `is_hostile` est propagé à Pass 1.2 où il **réduit le budget de concepts de moitié**.

#### 9.3.4 Mode fallback (tests uniquement)

Si `allow_fallback=True` et aucun LLM n'est disponible, un mode heuristique est activé :

- **Structure** : détection par mots-clés dans le titre (`guide`, `product` → CENTRAL ; `regulation`, `gdpr` → TRANSVERSAL ; sinon → CONTEXTUAL)
- **Langue** : détection par comptage de stop-words (fr/en/de) sur les 5000 premiers caractères
- **Thèmes** : 3 thèmes génériques (Introduction, Contenu Principal, Conclusion)

**⚠️ Ce mode est réservé aux tests unitaires** — en production, l'absence de LLM provoque une `RuntimeError` explicite.

#### 9.3.5 Extraction de TOC heuristique

La méthode `extract_toc_from_content()` tente d'extraire une table des matières du contenu brut :

- Détection de l'en-tête TOC (regex multilingue : « table of contents », « sommaire », « table des matières »)
- Extraction des lignes de format `N.N.N Titre` après l'en-tête
- Arrêt à la première ligne vide après ≥3 entrées de TOC

### 9.4 Outputs

| Sortie | Type | Description | Consommateur |
|--------|------|-------------|--------------|
| `subject` | `Subject` | Sujet avec `subject_id`, `name`, `text`, `structure`, `language`, `justification` | Pass 1.2 (context pour concepts), Pass1Result |
| `themes` | `List[Theme]` | Liste de thèmes avec `theme_id`, `name`, `scoped_to_sections=[]` | Pass 1.2 (rattachement concepts), Pass1Result |
| `is_hostile` | `bool` | Flag document multi-sujet (>10 thèmes) | Pass 1.2 (réduction budget concepts) |

### 9.5 Conformité ADR — Pass 1.1

| Axe | Exigence | Statut | Implémentation | Commentaire |
|-----|----------|--------|----------------|-------------|
| AV2-7 | **Top-down** | ✅ | Pass 1.1 est la première phase sémantique, établissant Subject et Themes avant toute identification de concepts. | Conforme à l'inversion de flux V1 → V2 (bottom-up → top-down). |
| AV2-1 | **Séparation structure/sémantique** | ✅ | Subject et Themes sont des entités purement sémantiques, sans lien direct avec la structure documentaire (Section, DocItem). | Les Themes ont un champ `scoped_to_sections` mais il est initialisé vide à ce stade. |
| NS-2 | **LLM = Extracteur** | ✅ | Le LLM identifie sujet, structure et thèmes — il n'infère pas de relations causales ni ne résout de contradictions. | L'analyse est descriptive et observationnelle. |
| P09-6 | **Intégration Pass 0.9** | ✅ | Si Pass 0.9 actif, `analysis_content = global_view.meta_document` et `toc_for_analysis = global_view.toc_enhanced`. | Fallback automatique sur contenu brut si GlobalView absente. |

### 9.6 Risques — Pass 1.1

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R11-1 | **Preview tronqué à 4000 chars** | 🟡 | Seuls les 4000 premiers caractères du contenu (ou du meta-document) sont envoyés au LLM. Pour des documents longs, les thèmes en fin de document peuvent être manqués. | Compensé par l'utilisation du meta-document Pass 0.9 qui comprime tout le document en 15-25K chars. La TOC (brute ou enrichie) fournit une vue d'ensemble additionnelle. |
| R11-2 | **Seuil HOSTILE fixe** | 🟢 | Le seuil de 10 thèmes est arbitraire et non adaptatif à la taille du document. Un document de 500 pages avec 11 thèmes est flaggé hostile comme un document de 10 pages. | Impact mineur : le flag hostile réduit le budget concepts (Pass 1.2) mais n'empêche pas le traitement. |
| R11-3 | **Pas de validation croisée structure/contenu** | 🟡 | La classification CENTRAL/TRANSVERSAL/CONTEXTUAL repose uniquement sur le jugement LLM. Aucune vérification algorithmique n'est effectuée. | Le champ `justification` permet un audit humain. L'impact est limité car la structure influence principalement le budget de concepts. |
| R11-4 | **Fallback analyse = données non fiables** | 🟢 | Le mode fallback produit 3 thèmes génériques et un sujet dérivé du titre. | Le fallback est strictement réservé aux tests (`allow_fallback=True`). En production, une `RuntimeError` est levée. |
| R11-5 | **Pas de détection de langue robuste** | 🟡 | La détection heuristique (comptage de stop-words) est utilisée uniquement en fallback. En mode LLM, la langue est déclarée par le modèle sans validation. | Risque faible : les documents sont généralement dans une langue connue (fr/en/de). |

---

## 10. Pass 1.2 — Identification des Concepts

**Fichier principal :** `src/knowbase/stratified/pass1/concept_identifier.py` — classe `ConceptIdentifierV2`
**Raffinement itératif :** `src/knowbase/stratified/pass1/concept_refiner.py` — classe `ConceptRefinerV2` (Pass 1.2b)
**Orchestration :** `src/knowbase/stratified/pass1/orchestrator.py` — `Pass1OrchestratorV2.process()`, lignes 253-275 (Pass 1.2) et 399-533 (Pass 1.2b)
**Schema Structured Output :** `src/knowbase/stratified/pass1/llm_schemas.py` — `ConceptIdentificationResponse`
**Note :** le fichier `trigger_enricher.py` mentionné dans la spec n'existe pas — la validation et l'enrichissement des triggers lexicaux sont intégrés directement dans `ConceptIdentifierV2` (méthodes `_validate_lexical_triggers`, `_validate_role_requirements`, `_get_top_frequent_tokens`).

### 10.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `doc_id` | `str` | Pipeline | Identifiant unique du document |
| `subject_text` | `str` | Pass 1.1 | Texte du sujet identifié |
| `structure` | `str` | Pass 1.1 | Structure de dépendance (`CENTRAL`, `TRANSVERSAL`, `CONTEXTUAL`) |
| `themes` | `List[Theme]` | Pass 1.1 | Thèmes identifiés pour rattachement des concepts |
| `content` / `analysis_content` | `str` | Pass 0.9 ou Pass 0 | Contenu analysé (meta-document ou contenu brut) |
| `is_hostile` | `bool` | Pass 1.1 | Flag document multi-sujet (réduit le budget de moitié) |
| `language` | `str` | Pass 1.1 | Langue du document (`fr`, `en`, `de`) |
| `n_sections` | `Optional[int]` | Pass 0 Structural | Nombre de sections pour le calcul du budget adaptatif |

### 10.2 Objectifs

Pass 1.2 identifie les **ConceptSitués** du document — des unités conceptuelles frugales, spécifiques et ancrées dans le texte. L'objectif est conforme aux principes ARCH V2 :

1. **Frugalité (AV2-6)** — Initialement 5-15 concepts par document, étendu à un **budget adaptatif** (V2.2, 2026-01-27) calculé dynamiquement selon la taille du document.
2. **Rattachement aux thèmes** — Chaque concept est obligatoirement lié à un thème identifié en Pass 1.1.
3. **Rôle typé** — Chaque concept reçoit un rôle : `CENTRAL` (cœur du document), `STANDARD` (important secondaire), `CONTEXTUAL` (contexte).
4. **Lexical triggers obligatoires (C1)** — Chaque concept doit posséder 2-4 tokens discriminants présents dans le texte, vérifiés par un algorithme de validation multi-critères.
5. **Anti-aspirateurs (C1b)** — Validation que les triggers ne sont pas trop fréquents (top 50 tokens du document), empêchant les concepts "aspirateurs" qui captent trop d'assertions.

### 10.3 Mécanismes

#### 10.3.1 Budget adaptatif (V2.2)

Le budget de concepts n'est plus fixe mais calculé dynamiquement :

```python
def compute_concept_budget(n_sections: int, is_hostile: bool = False) -> int:
    # Formule: clamp(20, 40, 15 + sqrt(sections) * 3)
    raw_budget = 15 + math.sqrt(n_sections) * 3
    budget = max(20, min(40, round(raw_budget)))
    if is_hostile:
        budget = max(10, budget // 2)
    return budget
```

**Propriétés clés :**
- Croissance **sub-linéaire** : 4× sections → ~2× concepts
- Plancher 20 concepts (petits documents)
- Plafond 40 concepts (limité par le contexte vLLM à 8192 tokens input+output)
- Documents hostiles : budget divisé par 2 (minimum 10)

| Sections | Budget normal | Budget hostile |
|----------|--------------|----------------|
| 20 | 28 | 14 |
| 50 | 36 | 18 |
| 100 | 45 → 40 (cap) | 20 |
| 200+ | 40 (cap) | 20 |

**Fallback** si `n_sections` non fourni : 30 (normal) ou 10 (hostile).

#### 10.3.2 Appel LLM — Identification initiale

1. **Chargement des prompts** depuis `pass1_prompts.yaml` (clé `concept_identification`)
2. **Formatage** : sujet, structure, thèmes formatés, contenu tronqué à 5000 chars
3. **Génération** : `llm_client.generate(max_tokens=4000)` — limité car vLLM context = 8192 tokens (input + output)
4. **Prompt système compact** (ADR: LLM Contract) : instructions minimalistes pour éviter la génération verbose et les troncatures JSON

**Schema Structured Output (Volet B) :**

```python
class ConceptIdentificationResponse(BaseModel):
    concepts: List[ConceptCompact]     # max 100 (V2.2: adaptatif jusqu'à 80)
    refused_terms: List[RefusedTerm]   # max 20
```

Où chaque `ConceptCompact` contient : `name` (max 50 chars, 2-4 mots), `role` (CENTRAL|STANDARD|CONTEXTUAL), `theme` (rattachement).

#### 10.3.3 Parsing et validation robuste

La méthode `_parse_response()` intègre plusieurs garde-fous :

1. **Détection de troncature JSON** : si le JSON ne se termine pas par `}` ou `]`, une `ValueError` explicite est levée avec le contexte (« LLM Contract Violation: JSON tronqué »)
2. **Nettoyage JSON** (`_clean_json_string`) : suppression des trailing commas, commentaires `//` et `/* */`, remplacement des single quotes — nécessaire pour les modèles locaux (Qwen) qui génèrent parfois du JSON invalide
3. **Déduplication par nom** : élimination des doublons (le LLM peut renvoyer le même concept plusieurs fois), avec réindexation des `concept_id` après déduplication

#### 10.3.4 Validation des lexical triggers (C1, C1b, C1c)

La méthode `_validate_lexical_triggers()` applique un pipeline de validation multi-critères pour chaque trigger :

**Étape 1 — Calcul des tokens fréquents** (`_get_top_frequent_tokens`) :
- Tokenisation simple (mots alphanumériques ≥ 3 chars)
- Comptage par `Counter`, extraction du top 50

**Étape 2 — Validation individuelle de chaque trigger** :

| Critère | Code | Description | Action si échec |
|---------|------|-------------|-----------------|
| **C1b: Longueur minimale** | `len(t) < 3` | Trigger trop court (< 3 chars), sauf patterns valeur (`VALUE_PATTERN`) | Rejet du trigger |
| **C1b: Anti-fréquent** | `t_lower in top_50_tokens` | Trigger dans le top 50 des tokens les plus fréquents du document | Rejet du trigger |
| **C1c: Présence dans le texte** | `re.search(pattern, doc_lower)` | Pour alphanumérique : matching word-boundary (`\b`). Pour valeurs : matching substring. | Rejet du trigger |
| **C1b: Rareté** | `freq_rate < 0.01` | Fréquence d'apparition dans les unités < 1% | Marqué `rare=True` |
| **C1b: Semi-rareté** | `freq_rate < 0.02` | Fréquence < 2% | Marqué `rare='semi-rare'` |
| **C1b: Valeur discriminante** | `VALUE_PATTERN.match(t)` | Patterns numériques (versions, %, °C, ratios) sont considérés discriminants | Marqué `rare='fallback_value'` |

Le `VALUE_PATTERN` reconnaît : `^\d+(\.\d+)*[%°]?[CFc]?$` et `^\d+[:\-]\d+$`.

**Étape 3 — Verdict final** :
- **Concept accepté** si ≥ 2 triggers valides ET au moins 1 trigger rare OU semi-rare
- Sinon → concept ajouté à la liste `refused_terms`

**Étape 4 — Dégradation de rôle** (`_validate_role_requirements`) :

La validation des triggers influence le rôle du concept via des règles de dégradation :

```
CENTRAL demandé + pas de trigger rare → dégradé à STANDARD
CENTRAL demandé + pas de trigger rare ni semi-rare → dégradé à CONTEXTUAL
STANDARD demandé + pas de trigger discriminant → dégradé à CONTEXTUAL
```

Cette mécanique empêche les concepts "aspirateurs" (ex : « infrastructure SAP ») avec des triggers trop génériques de recevoir un rôle CENTRAL.

#### 10.3.5 Garde-fou frugalité

Après la validation des triggers, un dernier garde-fou applique la limite du budget :

```python
if len(concepts) > max_concepts:
    concepts = self._apply_frugality(concepts, max_concepts)
```

La méthode `_apply_frugality()` trie par rôle (`CENTRAL > STANDARD > CONTEXTUAL`) et tronque au budget.

#### 10.3.6 Génération de clé lexicale

Chaque concept reçoit une `lex_key` normalisée pour la déduplication future :

```python
def _generate_lex_key(name: str) -> str:
    lex = name.lower().strip()
    lex = re.sub(r'\s+', '_', lex)
    lex = re.sub(r'[^a-z0-9_]', '', lex)
    return lex
```

### 10.4 Pass 1.2b — Raffinement itératif des concepts (V2.1)

**Fichier :** `src/knowbase/stratified/pass1/concept_refiner.py` — classe `ConceptRefinerV2`
**Activation :** flag `enable_pass12b=True` dans `Pass1OrchestratorV2` (défaut : activé)
**Déclenchement :** après Pass 1.3 (extraction assertions) et Pass 1.4 (promotion), quand le taux de `NO_CONCEPT_MATCH` est trop élevé

#### 10.4.1 Principe

Pass 1.2b est une **boucle de rétroaction** qui analyse les assertions non-liées à un concept (statut `ABSTAINED`, raison `no_concept_match`) pour identifier les concepts manquants. Il opère **sans relire le document**, uniquement à partir du journal d'assertions.

#### 10.4.2 Métriques de saturation

La classe `SaturationMetrics` (dataclass) calcule les indicateurs de décision :

| Métrique | Formule | Description |
|----------|---------|-------------|
| `promotion_rate` | `promoted / total_assertions` | Taux de promotion global |
| `no_concept_match_rate` | `no_concept_match / total_assertions` | **C4 : ratio stable** (vs /abstained dans V1) |
| `coverage_rate` | `promoted / (promoted + no_concept_match)` | Couverture conceptuelle |
| `quality_unlinked_count` | `prescriptive_unlinked + value_bearing_unlinked` | **C2 : assertions de qualité non-liées** |
| `should_iterate` | `rate > 10% AND count > 20` | **C4 : déclencheur stable** |

#### 10.4.3 Critères de qualité (C2, C2b)

Seules les assertions "de qualité" sont considérées pour justifier de nouveaux concepts :

- **C2 — Assertions PRESCRIPTIVE** : type PRESCRIPTIVE explicite
- **C2 — Assertions value-bearing** : contiennent une valeur quantifiable (versions, pourcentages, tailles, températures, durées, montants, ratios) détectée par 7 patterns regex
- **C2b — Obligations sans modal** : détection de 10 patterns d'obligations implicites (juridique/contrats) comme « is required to », « no later than », « within N days », « ne peut pas »

#### 10.4.4 Boucle itérative

L'orchestrateur exécute la boucle suivante (dans `process()`, lignes 399-533) :

```
TANT QUE saturation.should_iterate:
  1. Calculer SaturationMetrics depuis assertion_log
  2. Vérifier C4: rate > 10% ET count > 20
  3. Si rendement décroissant (< 15% réduction) → ARRÊT
  4. Filtrer assertions de qualité (C2, C2b)
  5. Appeler ConceptRefinerV2.refine_concepts()
     → LLM identifie concepts manquants depuis assertions non-liées
  6. Valider C2: chaque concept doit couvrir ≥2 assertions dont ≥1 PRESCRIPTIVE/value
  7. Déduplication vs concepts existants et doublons internes
  8. Ajouter les nouveaux concepts à la liste
  9. Re-linker les assertions non-liées avec tous les concepts (anciens + nouveaux)
  10. Re-résoudre les ancrages (AnchorResolver)
  11. Mettre à jour assertion_log (ABSTAINED → PROMOTED)
```

**Garde-fous de convergence :**

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| `MAX_ITERATIONS` | 3 | Maximum d'itérations |
| `MAX_NEW_CONCEPTS_PER_ITER` | 10 | Concepts ajoutés par itération |
| `MAX_TOTAL_CONCEPTS` | 50 | Surface conceptuelle maximale |
| `MIN_NO_CONCEPT_MATCH` | 20 | Minimum de trous pour déclencher |
| `MIN_REDUCTION_RATE` | 0.15 | Gain minimum pour continuer (15%) |

#### 10.4.5 Validation des concepts raffinés (C2)

Chaque concept proposé par le LLM est validé par `_validate_concept_quality()` :

1. Le concept doit avoir des `lexical_triggers` (≥ 2)
2. Ces triggers doivent matcher ≥ 2 assertions non-liées
3. Parmi ces assertions, ≥ 1 doit être de qualité (PRESCRIPTIVE ou value-bearing)

### 10.5 Outputs

| Sortie | Type | Description | Consommateur |
|--------|------|-------------|--------------|
| `concepts` | `List[Concept]` | Concepts avec `concept_id`, `theme_id`, `name`, `role`, `lex_key`, `lexical_triggers`, `definition`, `variants` | Pass 1.3 (linking assertions), Pass 1.2b (base pour raffinement), Pass1Result |
| `refused_terms` | `List[Dict]` | Termes refusés avec raisons (triggers invalides, trop génériques, etc.) | Audit, Pass1Result |
| `saturation` (via Pass 1.2b) | `SaturationMetrics` | Métriques de couverture conceptuelle finales | Logs, diagnostic |

**Structure d'un Concept :**

```python
Concept(
    concept_id="concept_doc123_0",   # ID unique
    theme_id="theme_doc123_2",       # Rattachement thème
    name="TLS Configuration",        # Nom court (2-4 mots)
    role=ConceptRole.CENTRAL,        # CENTRAL | STANDARD | CONTEXTUAL
    definition=None,                 # Optionnel (enrichi en Pass 2)
    variants=[],                     # Optionnel (enrichi en Pass 2)
    lex_key="tls_configuration",     # Clé normalisée pour dédup
    lexical_triggers=["TLS", "1.3", "cipher suite"]  # 2-4 tokens discriminants
)
```

### 10.6 Conformité ADR — Pass 1.2

| Axe | Exigence | Statut | Implémentation | Commentaire |
|-----|----------|--------|----------------|-------------|
| AV2-6 | **Frugalité concepts (5-15 max)** | ⚠️ | Le budget adaptatif (V2.2) étend la fourchette à [20, 40] pour l'identification initiale, plus jusqu'à 50 via Pass 1.2b. | **Déviation documentée.** L'ADR initiale spécifiait 5-15. L'extension à 20-40 (+ 50 max avec 1.2b) est motivée par la nécessité de couvrir des documents volumineux (>100 sections). La croissance sub-linéaire (`sqrt`) maintient l'esprit de frugalité. |
| AV2-7 | **Top-down** | ✅ | Les concepts sont identifiés APRÈS le sujet et les thèmes (Pass 1.1). Chaque concept est rattaché à un thème existant. | Conforme à l'approche top-down. |
| NS-2 | **LLM = Extracteur** | ✅ | Le LLM identifie les concepts depuis le texte. La validation (C1, C1b, C1c) est algorithmique (post-LLM). | Le LLM extrait, les algorithmes valident. |
| NS-7 | **Addressability-First** | ✅ | Chaque concept est rattaché à au moins un thème (`theme_id`). Les `lexical_triggers` garantissent l'ancrage textuel. | Les concepts sans triggers valides sont rejetés. |
| P09-6 | **Intégration Pass 0.9** | ✅ | L'identification utilise `analysis_content` (meta-document si Pass 0.9 actif). Le budget adaptatif utilise `n_sections` depuis Pass 0 Structural. | Double intégration : contenu comprimé + budget basé sur la structure. |

### 10.7 Risques — Pass 1.2

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R12-1 | **Budget étendu vs frugalité ADR** | 🟡 | Le budget adaptatif [20-40] + raffinement itératif (→50 max) dépasse significativement la fourchette ADR initiale de 5-15 concepts. | La croissance sub-linéaire (`sqrt`) et les garde-fous de convergence (max 3 itérations, min 15% réduction) limitent l'expansion. Le cap à 50 concepts reste bien en-deçà du legacy (~4700 nodes/doc). |
| R12-2 | **Troncature JSON (LLM Contract)** | 🟡 | Le contexte vLLM de 8192 tokens (input+output) peut être insuffisant pour générer 40 concepts avec triggers. Le contenu est tronqué à 5000 chars, les tokens de sortie limités à 4000. | Détection explicite de troncature (`ValueError` levée). Le prompt système compact (ADR: LLM Contract) minimise la verbosité. Les Structured Outputs (Volet B) garantissent la structure JSON côté vLLM. |
| R12-3 | **Triggers trop permissifs pour petits documents** | 🟡 | Pour les documents avec peu d'unités (< 100), le seuil de rareté < 1% devient très strict (< 1 unité). Cela peut rejeter des triggers légitimes. | Le fallback `semi-rare` (< 2%) et le fallback `value` (patterns numériques) assouplissent la validation pour les petits corpus. |
| R12-4 | **Pass 1.2b : risque de concepts de faible valeur** | 🟡 | Le raffinement itératif peut introduire des concepts de faible discriminance, car les assertions restantes (NO_CONCEPT_MATCH) sont par définition les plus difficiles à rattacher. | Le critère C2 (≥2 assertions dont ≥1 PRESCRIPTIVE/value) et la validation de qualité limitent ce risque. Le cap à 50 concepts max et le rendement décroissant (min 15%) assurent la convergence. |
| R12-5 | **Doublons entre LLM et raffinement** | 🟢 | Le LLM (Qwen notamment) peut reproposer des concepts déjà existants lors du raffinement. | Déduplication par nom normalisé implémentée à la fois dans `_validate_and_convert()` (Pass 1.2) et `refine_concepts()` (Pass 1.2b). |
| R12-6 | **Pas de trigger_enricher.py séparé** | 🟢 | L'enrichissement des triggers (TF-IDF, embedding) mentionné dans certains documents de design n'est pas implémenté comme composant séparé. La validation est intégrée dans `ConceptIdentifierV2`. | L'implémentation actuelle (fréquence, rareté, word-boundary) est fonctionnelle. L'enrichissement par TF-IDF/embedding pourrait être ajouté en V3 comme composant séparé. |
| R12-7 | **Nettoyage JSON fragile** | 🟢 | Le nettoyage des trailing commas et single quotes par regex peut échouer sur du JSON fortement malformé. | Le nettoyage couvre les cas les plus fréquents (Qwen). Les Structured Outputs (Volet B) éliminent ce risque quand activés. |

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
