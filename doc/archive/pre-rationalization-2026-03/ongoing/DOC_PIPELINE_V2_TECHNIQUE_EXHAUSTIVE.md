# Documentation Technique Exhaustive du Pipeline d'Ingestion V2

**Projet:** OSMOSE (Organic Semantic Memory Organization & Smart Extraction)
**Produit:** OSMOSIS
**Statut:** EN COURS DE RÉDACTION
**Date de création:** 2026-01-29
**Dernière MAJ:** 2026-02-02
**Branche:** `feat/pass1-hybrid-extract-then-structure`

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
  - [16.1 Séquencement global](#161-séquencement-global)
  - [16.2 Folder Watcher](#162-folder-watcher)
  - [16.3 Dispatcher](#163-dispatcher)
  - [16.4 Modes d'exécution](#164-modes-dexécution)
  - [16.5 Feature Flags et configuration](#165-feature-flags-et-configuration)
  - [16.6 Burst Mode (EC2 Spot)](#166-burst-mode-ec2-spot)
  - [16.7 Jobs spécialisés](#167-jobs-spécialisés)
  - [16.8 Conformité ADR — Orchestration](#168-conformité-adr--orchestration)
  - [16.9 Risques — Orchestration](#169-risques--orchestration)
- [17. Modèle de données complet](#17-modèle-de-données-complet)
- [18. Synthèse globale des risques](#18-synthèse-globale-des-risques)
  - [18.1 Risques critiques (🔴)](#181-risques-critiques-)
  - [18.2 Risques modérés (🟡)](#182-risques-modérés-)
  - [18.3 Risques faibles (🟢)](#183-risques-faibles-)
  - [18.4 Avertissements architecturaux (⚠️)](#184-avertissements-architecturaux-)
  - [18.5 Statistiques consolidées](#185-statistiques-consolidées)
- [19. Diagramme d'architecture global](#19-diagramme-darchitecture-global)
- [20. Conclusion](#20-conclusion)
  - [20.1 Synthèse](#201-synthèse)
  - [20.2 Maturité du pipeline](#202-maturité-du-pipeline)
  - [20.3 Points d'attention prioritaires](#203-points-dattention-prioritaires)
  - [20.4 Prochaines étapes](#204-prochaines-étapes)

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

### 8.8 Pipeline V2.2 — Extract-then-Structure (2026-02-02)

**ADR de référence :** `doc/ongoing/ADR_PASS1_V22_HYBRID_EXTRACT_THEN_STRUCTURE.md`
**Feature flag :** `stratified_pipeline_v2.pass1_v22` (défaut: `false`)

Le pipeline V2.2 introduit une approche **Extract-then-Structure** qui s'appuie sur les zones de la GlobalView construite en Pass 0.9. Au lieu du flux V2.1 (analyse documentaire → concepts → assertions linéaire), le V2.2 :

1. **Construit la GlobalView avec zones** — La GlobalView identifie des zones thématiques cohérentes dans le document
2. **Extrait par zone** — Chaque zone est traitée indépendamment par un orchestrateur `Pass1OrchestratorV22`
3. **Structure a posteriori** — Les concepts et informations sont structurés après extraction, pas avant

**Fichiers clés :**

| Fichier | Rôle |
|---------|------|
| `src/knowbase/stratified/pass1_v22/orchestrator.py` | `Pass1OrchestratorV22` — orchestrateur zone-aware |
| `src/knowbase/stratified/pass09/global_view_builder.py` | `GlobalViewBuilder.build_sync()` — construction GlobalView avec zones |
| `src/knowbase/stratified/pass09/models.py` | Modèle `GlobalView` avec `zones: List[Zone]` |

**Fallback :** Si la GlobalView ne produit pas de zones, le pipeline retombe sur V2.1 automatiquement.

**Activation dans le reprocess :**

```python
use_v22 = get_stratified_v2_config("pass1_v22", tenant_id)
if use_v22:
    gv_builder = GlobalViewBuilder(llm_client=llm_client)
    global_view = gv_builder.build_sync(...)
    orchestrator_v22 = Pass1OrchestratorV22(...)
    pass1_result = orchestrator_v22.process(global_view=global_view, ...)
```

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

**Fichier principal :** `src/knowbase/stratified/pass1/assertion_extractor.py` — classe `AssertionExtractorV2`
**Validation verbatim :** `src/knowbase/stratified/pass1/verbatim_validator.py` — fonctions `validate_raw_assertions`, `BatchValidationStats`
**Indexation unitaire (mode pointer) :** `src/knowbase/stratified/pass1/assertion_unit_indexer.py` — classe `AssertionUnitIndexer`
**Schémas pointer :** `src/knowbase/stratified/pass1/pointer_schemas.py` — modèles Pydantic `PointerConcept`, `PointerExtractionResponse`
**Validation pointer :** `src/knowbase/stratified/pass1/pointer_validator.py` — classe `PointerValidator`

### 11.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `chunks` | `Dict[str, str]` | Pass 0 / Qdrant | Dictionnaire `chunk_id → texte`, segments issus de la segmentation documentaire |
| `concepts` | `List[Concept]` | Pass 1.2 | Concepts identifiés pour le linking sémantique (avec `lexical_triggers`) |
| `doc_language` | `Optional[str]` | Pass 1.1 | Langue du document (`fr`, `en`, etc.) |
| `docitems` | `Dict[str, DocItem]` | Pass 0 Structural | DocItems pour le mode pointer (segmentation en unités) |
| `global_view` (indirect) | `str` | Pass 0.9 | Le meta-document influence les concepts fournis en entrée |

### 11.2 Objectifs

Pass 1.3 extrait les **assertions sémantiques typées** du texte et les lie aux concepts identifiés en Pass 1.2. L'objectif est triple :

1. **Extraction** — Identifier les assertions (phrases porteuses de connaissance) dans chaque chunk, les classifier par type (`DEFINITIONAL`, `PRESCRIPTIVE`, `FACTUAL`, `PERMISSIVE`, `CONDITIONAL`, `CAUSAL`, `COMPARATIVE`, `PROCEDURAL`).
2. **Filtrage par Promotion Policy** — Appliquer une politique de promotion par type pour séparer les assertions promotionnables de celles qui seront ABSTAINED. Filtrer les méta-descriptions et fragments.
3. **Liaison sémantique** — Relier chaque assertion aux concepts par raisonnement sémantique (pas matching lexical).

**Sortie principale :** `List[RawAssertion]` — assertions brutes typées avec `chunk_id` (avant résolution d'ancrage en 1.3b).

### 11.3 Mécanismes

#### 11.3.1 Deux modes d'extraction

L'extracteur supporte deux modes fondamentalement différents :

**Mode classique** (`extract_assertions`) :
- Le LLM extrait les assertions en **copiant** le texte source
- Vulnérable à la reformulation (le LLM peut réécrire le texte au lieu de le citer)
- Nécessite la validation verbatim (Volet A) en post-traitement

**Mode pointer** (`extract_assertions_pointer_mode`) :
- Les DocItems sont pré-segmentés en **unités numérotées** (U1, U2, U3...) par `AssertionUnitIndexer`
- Le LLM **pointe** vers une unité au lieu de copier → élimine structurellement la reformulation
- Le texte verbatim est reconstruit côté code depuis l'index des unités → **garanti exact**

Le mode pointer est le mode cible pour la conformité North Star NS-3 (citation exacte obligatoire).

#### 11.3.2 Extraction parallèle (mode classique)

L'extraction opère en parallèle via `ThreadPoolExecutor` :

```python
# Configuration
max_workers = int(os.environ.get("OSMOSE_LLM_WORKERS", 8))
# Filtrage: chunks < 50 chars ignorés
# Texte tronqué à 2000 chars par chunk pour le prompt LLM
```

**Pipeline par chunk :**
1. Envoi du chunk au LLM avec prompt d'extraction (`pass1_prompts.yaml`, clé `assertion_extraction`)
2. Parse de la réponse JSON → liste de `RawAssertion`
3. Fallback heuristique si le LLM échoue (`_extract_heuristic`)

**Structure de `RawAssertion` :**

```python
RawAssertion(
    assertion_id="assert_a1b2c3d4",   # UUID tronqué
    text="TLS 1.2 is required...",     # Texte extrait (copie ou verbatim)
    assertion_type=AssertionType.PRESCRIPTIVE,
    chunk_id="chunk_42",               # Référence chunk source (PAS docitem_id)
    start_char=145,                    # Position dans le chunk
    end_char=287,
    confidence=0.9,                    # Confiance LLM (debug uniquement)
    language="en"
)
```

#### 11.3.3 Extraction heuristique (fallback)

Si le LLM est indisponible et `allow_fallback=True` (tests uniquement) :

1. Découpage par regex `(?<=[.!?])\s+` (fin de phrase)
2. Phrases < 20 chars ignorées
3. Détection du type par patterns lexicaux :
   - `must/shall/required/doit/obligatoire` → PRESCRIPTIVE
   - `is defined as/refers to/est défini` → DEFINITIONAL
   - `may/can/possible/peut` → PERMISSIVE
   - `if/when/unless/si/lorsque` → CONDITIONAL
   - `because/therefore/car/donc` → CAUSAL
   - `step/first/then/étape` → PROCEDURAL
   - Par défaut → FACTUAL
4. Détection de la langue par comptage de mots-clés FR vs EN

#### 11.3.4 Validation verbatim (Volet A — mode classique)

La méthode `extract_and_validate_assertions()` combine extraction + validation :

1. Extraction classique des assertions via LLM
2. Appel à `validate_raw_assertions()` (module `verbatim_validator`)
3. Vérification que chaque assertion est une **copie exacte** du texte source (substring match dans le chunk)
4. Les assertions reformulées par le LLM sont rejetées avec raison `ABSTAIN(reformulation)`
5. **Alerte** si taux de reformulation > 10% : le LLM ne respecte pas l'instruction « texte EXACT »

Cette validation est conforme à NS-2 (LLM = extracteur evidence-locked) et NS-3 (citation exacte).

#### 11.3.5 Assertion Unit Indexer (mode pointer)

**Fichier :** `assertion_unit_indexer.py` — classe `AssertionUnitIndexer`

Segmente les DocItems en **unités d'assertion** atomiques pour le mode pointer :

**Stratégie de segmentation :**

| Cas | Entrée | Comportement |
|-----|--------|--------------|
| Type atomique | `list_item`, `bullet`, `table_cell` | → une seule unité U1 |
| Paragraphe/autre | Texte libre | → segmentation intelligente (phrases + clauses) |
| Segment trop long | > `max_unit_length` (500 chars) | → re-découpage sur virgules |
| Segment trop court | < `min_unit_length` (30 chars) | → ignoré |

**Segmentation intelligente :**

1. **Découpage en phrases** (`_split_sentences`) avec protection des abréviations :
   - Points précédés d'un mot court (1-3 lettres) → probablement abréviation (sauf si suivi de majuscule)
   - Points internes à un token (i.e., e.g.) → abréviation
   - Versions (1.2, 2.0.1) → pas de coupure
   - Acronymes pointés (U.S.) → pas de coupure

2. **Découpage en clauses** (`_split_clauses`) — conditionnel :
   - Split sur `;` uniquement en contexte prescriptif (marqueurs : must, shall, doit, obligatoire...)
   - Split sur `:` uniquement si suivi d'une liste (bullets ou ≥2 virgules), PAS si suivi d'une valeur courte (version, taille, protocole)

3. **Re-découpage** des segments > 500 chars sur virgules

**Structure de `AssertionUnit` :**

```python
AssertionUnit(
    unit_local_id="U1",                    # ID local au DocItem
    docitem_id="tenant:doc:item_42",       # Référence DocItem parent
    text="TLS 1.2 is required...",         # Texte verbatim (readonly)
    char_start=0,                          # Position dans DocItem.text
    char_end=42,
    unit_type="sentence"                   # sentence | clause | bullet | segment | table_row
)
# unit_global_id → "tenant:doc:item_42#U1" (calculé, jamais stocké)
```

**Indexation des tables** (`index_table_rows`) : chaque row devient une unité avec format canonique trié alphabétiquement : `"Header1: Cell1 | Header2: Cell2 | ..."`.

**Helpers :**
- `format_units_for_llm(units)` → formate en `"U1: text\nU2: text\n..."` pour le prompt LLM
- `lookup_unit_text(index, docitem_id, unit_local_id)` → retrouve le texte verbatim depuis l'index

#### 11.3.6 Schémas Pointer (Pydantic)

**Fichier :** `pointer_schemas.py`

Modèles Pydantic pour structurer l'output LLM en mode pointer :

**`PointerConcept`** — Concept pointé par le LLM :

```python
class PointerConcept(BaseModel):
    label: str       # max 100 chars, "2-5 mots"
    type: Literal["PRESCRIPTIVE", "DEFINITIONAL", "FACTUAL", "PERMISSIVE"]
    unit_id: str     # Validé par regex "^U\d+$"
    confidence: float  # [0.0, 1.0] — IGNORÉE pour la promotion, debug uniquement
    value_kind: Optional[str]  # version, percentage, size, number, duration, etc.
```

**`PointerExtractionResponse`** — Réponse complète : `{ "concepts": [PointerConcept, ...] }`

**Progression du modèle de données :**

```
ConceptCandidate (top-down, sans preuve)
    ↓ extraction pointer + validation 3 niveaux
ConceptAnchored (avec preuve validée, exploitable dans le KG)
    ├── exact_quote: str          # Texte verbatim GARANTI (depuis index)
    ├── anchor: Anchor            # docitem_id + unit_id + char_start/end
    ├── validation_status: str    # "VALID" ou "DOWNGRADED"
    └── validation_score: float   # Score lexical
```

**Fonctions helpers :**
- `get_pointer_extraction_schema()` → JSON Schema pour vLLM structured outputs
- `parse_pointer_response(json_str)` → Validation Pydantic de la réponse
- `pointer_to_anchored(pointer, unit_text, anchor, ...)` → Conversion PointerConcept → ConceptAnchored

#### 11.3.7 Pointer Validator — Validation 3 niveaux

**Fichier :** `pointer_validator.py` — classe `PointerValidator`

Valide chaque concept pointé par le LLM avec 3 niveaux de vérification **déterministes** (la confidence LLM n'est JAMAIS utilisée pour la décision) :

**Niveau 1 — Support Lexical (score pondéré ≥ 1.5) :**

| Composante | Score | Condition |
|------------|-------|-----------|
| Token exact du label (word boundary) | +1.0 par token | Matching `\b{token}\b`, ignorer tokens < 3 chars, max 2 tokens scorés |
| Motif valeur dans l'unité | +1.0 | Si `value_kind` spécifié : vérifier le pattern exact. Sinon : vérifier pattern générique (`\d+(\.\d+)*\s*(%|GB|...)?`) |

→ Si score < 1.5 → **ABSTAIN** (raison : `no_lexical_support`)

**Niveau 2 — Type Markers (cohérence type/contenu) :**

- Si type = `PRESCRIPTIVE` mais absence de marqueurs prescriptifs (must, shall, required, doit, obligatoire...) → **DOWNGRADE** vers `DEFINITIONAL`
- Configurable via `strict_type_markers` (défaut : activé)

**Niveau 3 — Value Patterns (si kind spécifié) :**

| Kind | Pattern regex | Exemples |
|------|---------------|----------|
| `version` | `\d+(\.\d+)+` | 1.2, 3.0.1 |
| `percentage` | `\d+\s*%` | 99.9% |
| `size` | `\d+\s*(GB\|TB\|MB\|TiB\|GiB\|KB\|KiB)` | 256 GB |
| `number` | `\d+` | 42 |
| `boolean` | `\b(true\|false\|yes\|no\|enabled\|disabled)\b` | enabled |
| `duration` | `\d+\s*(ms\|s\|sec\|min\|hour\|h\|day\|d\|week\|month\|year)` | 30 min |

→ Si kind spécifié mais pattern absent → **ABSTAIN** (raison : `value_pattern_mismatch`)

**Résultat final :**

| Statut | Signification |
|--------|---------------|
| `VALID` | Concept validé, peut être promu |
| `DOWNGRADE` | Type modifié (ex: PRESCRIPTIVE → DEFINITIONAL), concept conservé |
| `ABSTAIN` | Concept rejeté — ne sera pas promu |

**Reconstruction du texte verbatim :**

La fonction `reconstruct_exact_quote(unit_index, docitem_id, unit_id)` est LA garantie anti-reformulation : le texte vient TOUJOURS de l'index, JAMAIS du LLM. C'est le mécanisme central de conformité NS-3.

#### 11.3.8 Filtrage par Promotion Policy

La méthode `filter_by_promotion_policy()` filtre les assertions **avant** le linking :

**Pré-filtres :**
1. **Méta-descriptions** : détection via `promotion_engine.is_meta_pattern()` — filtre les assertions qui décrivent la page au lieu d'informer (ex: « La page présente un modèle de déploiement »)
2. **Fragments** : détection via `promotion_engine.is_fragment()` — filtre les non-assertions (noms seuls, texte sans verbe)

**Politique de promotion par type :**

| Type d'assertion | Tier | Condition de promotion |
|-----------------|------|----------------------|
| `DEFINITIONAL` | ALWAYS | Toujours promu si lié à un concept |
| `PRESCRIPTIVE` | ALWAYS | Toujours promu si lié à un concept |
| `CAUSAL` | ALWAYS | Toujours promu si lié à un concept |
| `FACTUAL` | CONDITIONAL | Promu si `strict_promotion=False` ET `confidence ≥ 0.7` |
| `CONDITIONAL` | CONDITIONAL | Promu si `strict_promotion=False` ET `confidence ≥ 0.7` |
| `PERMISSIVE` | CONDITIONAL | Promu si `strict_promotion=False` ET `confidence ≥ 0.7` |
| `COMPARATIVE` | RARELY | Promu si `strict_promotion=False` ET `confidence ≥ 0.9` |
| `PROCEDURAL` | NEVER | Jamais promu en Information |

Cette politique est conforme à NS-9 (Promotion Policy par type).

#### 11.3.9 Liaison sémantique assertions ↔ concepts

La méthode `link_to_concepts()` établit les liens entre assertions et concepts :

**Par LLM** (`_link_via_llm`) :
- Batching parallèle : si > 30 assertions, découpage en batches de 30
- Chaque batch traité en parallèle via `ThreadPoolExecutor`
- Le LLM raisonne **sémantiquement** (pas matching lexical) — une assertion peut concerner un concept sans le mentionner, cross-langue FR/EN
- Types de liens : `defines`, `describes`, `constrains`, `enables`, `conditions`, `causes`

**Format multi-concept (V2.1)** :
- Une assertion peut être liée à 1-5 concepts via `MultiConceptLink`
- Filtrage C3 v2 anti "spray & pray" avec soft gate + hard gate :
  - **Soft gate** : pas de trigger lexical dans l'assertion → `confidence -= 0.20`
  - **Hard gate** : pas de trigger ET pas de token du nom du concept ET `confidence_adj < 0.55` → rejet
  - Seuils : `MIN_LINK_CONFIDENCE = 0.70`, `MAX_LINKS_PER_ASSERTION = 5`
  - Règle top-k : si écart entre top-1 et top-2 ≤ 0.10, garder les deux

**Par heuristique** (fallback) :
- Matching lexical des variantes du concept (nom, variants, acronyme) dans le texte de l'assertion
- Génération d'acronymes à partir du nom multi-mots
- Confiance fixée à 0.6

#### 11.3.10 Enrichissement MVP V1 (Information-First)

La méthode `enrich_with_mvp_v1()` enrichit les assertions avec les capacités Information-First :

1. **Extraction de valeurs** via `ValueExtractor` : percent, version, number, boolean, enum
2. **Inférence ClaimKey Level A** via `ClaimKeyPatterns` : patterns sans LLM
3. **Évaluation promotion MVP V1** via `PromotionPolicy` : statuts `PROMOTED_LINKED`, `PROMOTED_UNLINKED`, rejet

**Invariant 1 :** alerte si assertions UNLINKED > 10% du total (indicateur de patterns ClaimKey insuffisants).

### 11.4 Outputs

| Sortie | Type | Description | Consommateur |
|--------|------|-------------|--------------|
| `assertions` | `List[RawAssertion]` | Assertions brutes avec `chunk_id`, type, positions | Pass 1.3b (ancrage), Pass 1.4 (promotion) |
| `links` | `List[ConceptLink]` | Liens assertion → concept avec type, justification, confiance | Pass 1.3b (ancrage), Pass 1.4 (promotion) |
| `promotion_result` | `PromotionResult` | Assertions promotionnables + abstenues avec raisons | Pass 1.4 |
| `verbatim_stats` | `BatchValidationStats` | Statistiques de validation verbatim (mode classique) | Diagnostic, logs |
| `unit_index` (mode pointer) | `Dict[str, UnitIndexResult]` | Index des unités par DocItem | Pointer Validator, reconstruction verbatim |
| `enriched` (MVP V1) | `List[EnrichedAssertion]` | Assertions avec valeurs, ClaimKey, statut promotion | Pass 1.4 (Value Contract) |

### 11.5 Conformité ADR — Pass 1.3

| Axe | Exigence | Statut | Implémentation | Commentaire |
|-----|----------|--------|----------------|-------------|
| NS-2 | **LLM = Extracteur evidence-locked** | ✅ | Le LLM extrait les assertions, la validation (verbatim, pointer, promotion policy) est algorithmique post-LLM. La confidence LLM est explicitement ignorée pour les décisions de promotion dans le mode pointer. | Conforme. La séparation extraction/validation est claire et implémentée. |
| NS-3 | **Citation exacte obligatoire** | ✅ | Deux mécanismes complémentaires : (1) validation verbatim post-extraction (mode classique), (2) reconstruction depuis index (mode pointer). Le mode pointer **garantit structurellement** le verbatim. | Le mode pointer est la solution cible. Le mode classique reste vulnérable si la validation est contournée. |
| NS-9 | **Promotion Policy par type** | ✅ | Politique `ALWAYS/CONDITIONAL/RARELY/NEVER` conforme à la spécification NS-9. Les types ALWAYS sont : DEFINITIONAL, PRESCRIPTIVE, CAUSAL. PROCEDURAL est NEVER. | Implémentation fidèle à l'ADR. |
| AV2-7 | **Top-down** | ✅ | L'extraction d'assertions (1.3) arrive APRÈS l'identification des concepts (1.2). Le linking est guidé par les concepts existants. | Séquence top-down respectée. |
| NS-7 | **Addressability-First** | ⚠️ | Les assertions sont liées aux concepts, mais le linking multi-concept V2.1 peut créer des liens de faible confiance. Le filtrage C3 v2 (soft/hard gate) mitigue ce risque mais n'est pas parfait. | Le hard gate à 0.55 pourrait laisser passer des liens faibles. |
| NS-1 | **Information-First** | ⚠️ | L'enrichissement MVP V1 (`enrich_with_mvp_v1`) permet la promotion UNLINKED (sans concept). Cependant, la méthode `filter_by_promotion_policy()` rejette les assertions PROCEDURAL inconditionnellement. | La promotion UNLINKED adresse NS-1 mais n'est pas systématiquement activée (dépend du flag `strict_promotion`). |

### 11.6 Risques — Pass 1.3

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R13-1 | **Reformulation LLM (mode classique)** | 🟡 | Le LLM (Qwen notamment) reformule au lieu de citer verbatim. La validation verbatim rejette ces assertions, ce qui réduit le yield. | Le mode pointer élimine structurellement ce risque. La validation verbatim détecte et rejette les reformulations avec alerte si taux > 10%. |
| R13-2 | **Coexistence de deux modes d'extraction** | 🟡 | Le mode classique et le mode pointer coexistent, créant une dette architecturale. Les outputs ne sont pas strictement identiques (RawAssertion vs PointerConcept). | Convergence progressive vers le mode pointer uniquement. Les deux modes partagent la même Promotion Policy. |
| R13-3 | **Seuil lexical du Pointer Validator** | 🟡 | Le seuil de 1.5 pour le score lexical peut être trop strict pour des concepts avec des labels courts (2 tokens significatifs = score max 2.0 + value pattern). Un concept pertinent mais avec un label peu discriminant pourrait être rejeté. | Le score value pattern (+1.0) compense pour les assertions avec des valeurs numériques. Les labels de 2-5 mots (contrainte PointerConcept) donnent généralement 2 tokens significatifs. |
| R13-4 | **Spray & Pray malgré le filtre C3 v2** | 🟢 | Le LLM peut proposer des liens multiples de faible qualité pour une assertion. Le hard gate (pas de signal lexical + conf_adj < 0.55) peut laisser passer des faux positifs. | Le soft gate (-0.20 sans trigger) + le cap à 5 liens max + le seuil 0.70 sur confidence ajustée limitent l'inflation. Le filtrage est documenté et ajustable. |
| R13-5 | **Troncature du texte à 2000 chars** | 🟢 | Les chunks > 2000 chars sont tronqués pour le prompt LLM, ce qui peut couper des assertions en fin de chunk. | La segmentation en chunks devrait produire des segments < 2000 chars en général. Les assertions tronquées seraient détectées par la validation verbatim (position incorrecte). |
| R13-6 | **Fallback heuristique en production** | 🔴 | Si `allow_fallback=True` est activé en production, les assertions heuristiques (confiance fixe 0.5, types approximatifs) polluent le graphe. | Le flag `allow_fallback` est documenté comme « test only ». Un garde-fou `RuntimeError` bloque l'extraction sans LLM si fallback désactivé. |
| R13-7 | **Pré-filtres méta-descriptions et fragments** | 🟢 | Les pré-filtres (`is_meta_pattern`, `is_fragment`) dépendent du module `promotion_engine` qui est importé dynamiquement. Si les patterns sont incomplets, des méta-descriptions passent le filtre. | Les patterns couvrent EN + FR. L'import dynamique permet de mettre à jour les patterns sans modifier l'extracteur. |

---

## 12. Pass 1.3b — Résolution d'Ancrage

**Fichier principal :** `src/knowbase/stratified/pass1/anchor_resolver.py` — classe `AnchorResolverV2`
**Utilitaire :** `anchor_resolver.py` — fonction `build_chunk_to_docitem_mapping()`
**Modèles :** `src/knowbase/stratified/models/` — `Anchor`, `DocItem`, `AssertionLogReason`

### 12.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `assertions` | `List[RawAssertion]` | Pass 1.3 | Assertions brutes avec `chunk_id` |
| `links` | `List[ConceptLink]` | Pass 1.3 | Liens assertion → concept (seules les assertions liées sont ancrées) |
| `chunk_to_docitem_map` | `Dict[str, List[str]]` | Construit dynamiquement | Mapping `chunk_id → [docitem_ids]` |
| `docitems` | `Dict[str, DocItem]` | Pass 0 Structural | Dictionnaire des DocItems avec leur texte |
| `chunks` | `Dict[str, str]` | Pass 0 | Dictionnaire `chunk_id → texte du chunk` |

### 12.2 Objectifs

Pass 1.3b est une **phase critique** qui convertit les ancrages `chunk_id → docitem_id`. Cette conversion est nécessaire car :

1. **Les assertions sont extraites depuis des chunks** (segments Qdrant, compatibilité vectorielle)
2. **Le graphe sémantique ancre sur des DocItems** (surface de preuve atomique, grain Docling natif)
3. **L'invariant V2-001** impose : « Chaque Information DOIT avoir `ANCHORED_IN → DocItem` »
4. **L'invariant V2-002** impose : « `ANCHORED_IN` ne doit JAMAIS viser autre chose que `DocItem` »

**Sortie principale :** Pour chaque assertion liée à un concept, un `Anchor` contenant `docitem_id`, `span_start`, `span_end`, ou un échec typé (`NO_DOCITEM_ANCHOR`, `CROSS_DOCITEM`, `AMBIGUOUS_SPAN`).

### 12.3 Mécanismes

#### 12.3.1 Construction du mapping chunk → DocItem

La fonction `build_chunk_to_docitem_mapping()` construit le mapping initial :

**Stratégie 1 — Convention de nommage :**
- Si `chunk_id` contient un `docitem_id` (ex: `"chunk_docitem_123_0"`) → mapping direct

**Stratégie 2 — Matching par texte :**
- Si le texte du chunk est contenu dans un DocItem (ou vice versa) → mapping par inclusion
- Si le ratio de similarité (`SequenceMatcher`) > 0.8 → mapping par fuzzy

Un chunk peut correspondre à **plusieurs** DocItems (cas de chunks agrégés).

#### 12.3.2 Résolution par assertion

La méthode `resolve_all()` traite toutes les assertions :

1. **Filtrage** : seules les assertions **liées à un concept** (présentes dans `links`) sont traitées
2. **Assertions non liées** → échec avec raison `NO_CONCEPT_MATCH` (utilisé par Pass 1.2b pour le raffinement itératif)
3. Pour chaque assertion liée → `resolve_single()`

#### 12.3.3 Stratégies de résolution (resolve_single)

La résolution procède par escalade :

```
Stratégie 1: Mapping direct chunk → DocItem
    → Si mapping existe ET 1 seul DocItem → résolution directe
    → Si mapping existe ET plusieurs DocItems → resolve_in_multiple_docitems

Stratégie 2: Si pas de mapping → recherche texte dans TOUS les DocItems
    → resolve_by_text_search
```

**Résolution dans un DocItem unique** (`_resolve_in_single_docitem`) :

1. Recherche **exacte** du texte de l'assertion dans le texte du DocItem (`str.find()`)
2. Si échec → recherche avec **normalisation des espaces** (collapse whitespace)
3. Si échec → vérification de l'**overlap** (similarité ≥ 0.5) avec positions approximatives
4. Si échec → `AMBIGUOUS_SPAN`

**Résolution dans plusieurs DocItems** (`_resolve_in_multiple_docitems`) :

1. Pour chaque DocItem candidat → recherche exacte du span
2. Si match exact trouvé → résolution immédiate
3. Si aucun match exact → calcul de similarité fuzzy (`SequenceMatcher`) pour chaque candidat
4. Si meilleur score ≥ `FUZZY_THRESHOLD` (0.85) → résolution avec span approximatif
5. Si score > 0.3 mais < 0.85 → `CROSS_DOCITEM` (l'assertion chevauche plusieurs DocItems)
6. Sinon → `NO_DOCITEM_ANCHOR`

**Recherche globale** (`_resolve_by_text_search`) :

- Parcours de TOUS les DocItems
- Match exact prioritaire
- Fallback fuzzy si seuil ≥ 0.85
- Dernière option → `NO_DOCITEM_ANCHOR` avec détail du meilleur score

#### 12.3.4 Mapping de position normalisée

La méthode `_map_normalized_position()` convertit les positions du texte normalisé (espaces collapsés) vers le texte original par **ratio linéaire** :

```python
ratio_start = norm_start / len(normalized)
orig_start = int(ratio_start * len(original))
```

⚠️ **Approximation** : cette heuristique est imprécise pour les textes avec des séquences d'espaces variables. Le span résultant est indicatif.

### 12.4 Outputs

| Sortie | Type | Description | Consommateur |
|--------|------|-------------|--------------|
| `resolved` | `List[Tuple[RawAssertion, Anchor, concept_id]]` | Assertions ancrées avec succès | Pass 1.4 (promotion → Information) |
| `failed` | `List[Tuple[RawAssertion, AssertionLogReason, details]]` | Assertions en échec d'ancrage | AssertionLog (audit), Pass 1.2b (raffinement) |
| `stats` | `AnchorResolverStats` | Statistiques : total, resolved, no_docitem, cross_docitem, ambiguous_span | Diagnostic, logs |

**Structure de `Anchor` :**

```python
Anchor(
    docitem_id="tenant:doc:item_42",  # ID composite du DocItem
    span_start=145,                    # Position début dans DocItem.text
    span_end=287                       # Position fin dans DocItem.text
)
```

**Raisons d'échec :**

| Raison | Description | Conséquence |
|--------|-------------|-------------|
| `NO_DOCITEM_ANCHOR` | Aucun DocItem correspondant trouvé | L'assertion ne peut pas devenir Information (pas de preuve) |
| `CROSS_DOCITEM` | L'assertion chevauche plusieurs DocItems | Violation potentielle d'AV2-4 (DocItem atomique) |
| `AMBIGUOUS_SPAN` | DocItem trouvé mais position exacte indéterminée | Span approximatif, preuve faible |
| `NO_CONCEPT_MATCH` | Assertion non liée à aucun concept | Non traitée par l'ancrage (filtrée en amont) |

### 12.5 Conformité ADR — Pass 1.3b

| Axe | Exigence | Statut | Implémentation | Commentaire |
|-----|----------|--------|----------------|-------------|
| AV2-3 | **Ancrage Information sur DocItem** | ✅ | L'invariant V2-001 est le cœur de cette phase. Chaque assertion résolue obtient un `Anchor` avec `docitem_id`. Les échecs sont loggués mais jamais contournés (pas de fallback sur chunk). | Conforme. Aucune Information ne peut exister sans ancrage DocItem. |
| AV2-4 | **DocItem atomique** | ⚠️ | Les cas `CROSS_DOCITEM` sont détectés et rejetés. Cependant, le fuzzy matching (seuil 0.85) peut créer des ancrages approximatifs sur un DocItem qui ne contient pas exactement l'assertion. | Le seuil fuzzy est un compromis pragmatique. Les assertions reformulées (qui ne matchent pas exactement) sont les plus vulnérables. |
| NS-3 | **Citation exacte obligatoire** | ⚠️ | La recherche exacte (`str.find`) garantit la citation verbatim. Mais le fallback fuzzy (SequenceMatcher ≥ 0.85) et le mapping par ratio linéaire (`_map_normalized_position`) créent des spans approximatifs. | Le span exact n'est garanti que pour les matchs `str.find()`. Les résolutions fuzzy produisent un span indicatif. |
| AV2-5 | **AssertionLog avec statut enum** | ✅ | Les échecs utilisent `AssertionLogReason` standardisé (`NO_DOCITEM_ANCHOR`, `CROSS_DOCITEM`, `NO_CONCEPT_MATCH`). | Conforme. Les raisons sont des enum typés avec description détaillée. |
| NS-2 | **LLM = Extracteur, pas arbitre** | ✅ | La résolution d'ancrage est **100% algorithmique** — aucun appel LLM. Le LLM a extrait en 1.3, le code résout les ancrages en 1.3b. | Séparation parfaite extraction/résolution. |

### 12.6 Risques — Pass 1.3b

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R13b-1 | **Mapping chunk → DocItem fragile** | 🟡 | Le mapping repose sur la convention de nommage (`docitem_id in chunk_id`) ou sur le matching texte. Si les chunks sont segmentés différemment des DocItems (ce qui est courant), le mapping est incomplet. | Le fuzzy matching (seuil 0.8 pour le mapping, 0.85 pour la résolution) couvre les cas approximatifs. Mais l'absence de mapping déterministe est une dette technique. |
| R13b-2 | **Perte d'assertions au CROSS_DOCITEM** | 🟡 | Les assertions qui chevauchent plusieurs DocItems sont rejetées (`CROSS_DOCITEM`). Cela peut représenter une perte significative pour les chunks agrégés (plusieurs paragraphes dans un chunk). | Le grain DocItem (Docling natif = paragraph, table-row, list-item) devrait minimiser les cas de chevauchement. Pass 1.2b peut récupérer ces assertions via raffinement. |
| R13b-3 | **Span approximatif via ratio linéaire** | 🟡 | La méthode `_map_normalized_position()` utilise un ratio linéaire pour mapper les positions, ce qui est imprécis pour les textes avec des distributions irrégulières d'espaces. | La recherche exacte (`str.find`) est prioritaire. Le ratio n'est utilisé qu'en fallback pour les matchs normalisés. |
| R13b-4 | **Performance O(n×m) sur le text search** | 🟢 | La recherche globale (`_resolve_by_text_search`) parcourt TOUS les DocItems pour chaque assertion sans mapping. Avec des documents volumineux (>1000 DocItems), cela peut être lent. | Le mapping chunk → DocItem réduit le périmètre de recherche dans la majorité des cas. La recherche globale est un fallback de dernier recours. |
| R13b-5 | **Assertions non liées exclues de l'ancrage** | 🟢 | Les assertions sans `ConceptLink` sont marquées `NO_CONCEPT_MATCH` et non ancrées. Cela est cohérent avec le flux top-down mais signifie que Pass 1.2b est nécessaire pour les récupérer. | Conforme au design : l'ancrage ne sert que pour la promotion en Information. Les assertions orphelines sont traitées par le raffinement itératif. |
| R13b-6 | **Mode pointer rend 1.3b moins critique** | 🟢 | En mode pointer, l'ancrage est intégré à l'extraction (le LLM pointe directement vers un DocItem/unité). Pass 1.3b n'est alors nécessaire que pour le mode classique. | La convergence vers le mode pointer uniquement réduira progressivement le rôle de 1.3b. |

---

## 13. Pass 1.4 — Promotion et Value Contract

### 13.0 Vue d'ensemble Pass 1.4

**Fichiers source :**

| Fichier | Rôle |
|---------|------|
| `src/knowbase/stratified/pass1/promotion_engine.py` | Moteur de décision PROMOTE / ABSTAIN / REJECT |
| `src/knowbase/stratified/pass1/promotion_policy.py` | Politique Information-First MVP V1 (PromotionPolicy) |
| `src/knowbase/stratified/pass1/value_extractor.py` | Extracteur de valeurs bornées (Value Contract) |
| `src/knowbase/stratified/claimkey/patterns.py` | Patterns ClaimKey Niveau A (inférence déterministe) |
| `src/knowbase/stratified/claimkey/status_manager.py` | Gestion du cycle de vie ClaimKey dans Neo4j |
| `src/knowbase/stratified/models/information.py` | Modèle `InformationMVP` (assertion promue) |
| `src/knowbase/stratified/models/claimkey.py` | Modèle `ClaimKey` (question factuelle canonique) |
| `src/knowbase/stratified/models/schemas.py` | Schémas Pydantic V2 (`Information`, `AssertionLogEntry`) |
| `config/meta_patterns/structural_patterns.yaml` | Patterns META structurels externalisés (2026-01-27) |
| `config/meta_patterns/domain_extensions.yaml` | Extensions domaine optionnelles |

**Référence spec :** ChatGPT "Two-pass Vision Evidence Contract" (2026-01-26)

**Fonction dans le pipeline :**

Pass 1.4 est la **phase de promotion** : elle transforme les `ResolvedAssertionV1` (assertions ancrées sur DocItem, issues de Pass 1.3b) en `Information[]` navigables dans le graphe sémantique. C'est le **garde-fou central** du pipeline — elle décide ce qui mérite d'être stocké comme connaissance structurée et ce qui est rejeté ou abstenu.

```
Pass 1.3b (ResolvedAssertionV1[])
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│               PASS 1.4 — PROMOTION ENGINE                │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Meta-Pattern  │  │  Fragment    │  │  Promotion    │  │
│  │   Filter      │→│  Detector    │→│  Policy       │  │
│  │ (YAML+regex)  │  │ (verbs,len) │  │ (Tier-based)  │  │
│  └──────────────┘  └──────────────┘  └───────┬───────┘  │
│                                               │          │
│         ┌─────────────────────────────────────┘          │
│         ▼                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   Value       │  │  ClaimKey    │  │  ClaimKey     │  │
│  │  Extractor    │  │  Patterns   │  │  Status Mgr   │  │
│  │ (%, ver, nb)  │  │ (Level A)   │  │ (Neo4j CRUD)  │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │   InformationMVP + AssertionLogEntry (audit)     │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
         │
         ▼
    Information[] + AssertionLog[] (Neo4j)
```

### 13.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `AssertionBatchV1` | Batch | Pass 1.3b | Lot d'assertions résolues avec ancrage DocItem |
| `ResolvedAssertionV1[]` | Liste | Pass 1.3b | Assertions typées avec `PromotionDecision`, `AnchorV1`, `PivotsV1` |
| `chunk_to_docitem_map` | Dict | Pass 1.3b | Mapping chunk_id → docitem_id pour résolution d'ancrage |
| `concept_ids` | List[str] | Pass 1.2 | IDs des concepts identifiés (pour vérification addressability) |
| `theme_ids` | List[str] | Pass 1.1 | IDs des thèmes identifiés (pour vérification addressability) |
| Meta-patterns YAML | Config | `config/meta_patterns/` | Patterns structurels et domaine pour le filtrage META |

**Structure des entrants clés :**

```python
# ResolvedAssertionV1 (issue de Pass 1.3b)
@dataclass
class ResolvedAssertionV1:
    assertion_id: str
    text: str
    type: AssertionTypeV1           # DEFINITIONAL, PRESCRIPTIVE, CAUSAL, etc.
    confidence: float               # 0.0 → 1.0
    support_tier: SupportTier       # ALWAYS, CONDITIONAL, RARELY, NEVER
    chunk_id: str
    span: dict                      # {page, paragraph, line}
    anchor: Optional[AnchorV1]      # Ancrage DocItem résolu
    pivots: PivotsV1                # concept_ids, theme_ids, section_path
    promotion: PromotionDecision    # statut, raison, rule_used
```

### 13.2 Objectifs

1. **Filtrer les assertions non-exploitables** — Rejeter les patterns META (navigation, copyright, TOC), les fragments sans prédicat, les textes trop courts
2. **Appliquer la Promotion Policy par tier** — Décider PROMOTE / ABSTAIN / REJECT selon le type d'assertion et le seuil de confiance
3. **Vérifier l'addressability** — Garantir que toute assertion promue a ≥1 pivot navigable (Concept, Theme, ClaimKey, SectionPath)
4. **Extraire les valeurs bornées (Value Contract)** — Identifier et normaliser les valeurs (`raw`, `normalized`, `unit`, `operator`, `comparable`) pour comparaison machine
5. **Inférer les ClaimKeys (Niveau A)** — Générer des questions factuelles canoniques par patterns déterministes (sans LLM)
6. **Gérer le cycle de vie ClaimKey** — Créer/mettre à jour les ClaimKeys dans Neo4j avec statuts (EMERGENT → COMPARABLE)
7. **Produire le journal d'audit** — Générer un `AssertionLogEntry` pour chaque assertion (PROMOTED / ABSTAINED / REJECTED) avec la raison standardisée
8. **Calculer le fingerprint de déduplication** — `SHA256(claimkey_id + value.normalized + context_key + span_bucket)` pour éviter les doublons

### 13.3 Mécanismes

#### 13.3.1 Promotion Engine — Moteur de décision principal

**Classe :** `PromotionEngine` (`promotion_engine.py`)

**Initialisation :**

```python
class PromotionEngine:
    def __init__(self, strict_promotion: bool = True, tenant_id: str = "default"):
        self.strict_promotion = strict_promotion  # Mode strict ou permissif
        self.tenant_id = tenant_id
```

**Workflow principal — `process_batch()`:**

Le moteur traite chaque assertion en séquence selon un pipeline de 5 étapes :

```
Pour chaque AssertionV0 dans le batch :
│
├─ Étape 1 : Filtre META-PATTERN
│   ├─ _is_meta_pattern(text) → regex compilés depuis YAML
│   └─ Si match → REJECTED (rule: "meta_pattern")
│
├─ Étape 1b : Détection FRAGMENT
│   ├─ is_fragment(text) → vérifie longueur, présence de verbes
│   └─ Si fragment → REJECTED (rule: "fragment_no_predicate")
│
├─ Étape 2 : Vérification longueur minimale
│   ├─ len(text) < MIN_TEXT_LENGTH (15 chars)
│   └─ Si trop court → REJECTED (rule: "text_too_short")
│
├─ Étape 3 : Résolution d'ancrage DocItem
│   ├─ _resolve_anchor(chunk_id, span, chunk_to_docitem_map)
│   └─ Si échec ancrage → ABSTAINED (rule: "no_docitem_anchor")
│
├─ Étape 4 : Application Promotion Policy (par tier)
│   ├─ TYPE_TO_TIER[assertion_type] → SupportTier
│   ├─ ALWAYS → PROMOTED (confiance quelconque)
│   ├─ CONDITIONAL → PROMOTED si confidence ≥ 0.7
│   ├─ RARELY → PROMOTED si confidence ≥ 0.9
│   └─ NEVER → REJECTED
│
├─ Étape 5 : Vérification Addressability
│   ├─ Au moins 1 pivot parmi : concept_id, theme_id, section_path
│   └─ Si aucun pivot → statut PROMOTED_UNLINKED (pas de rejet)
│
├─ Génération ResolvedAssertionV1 avec PromotionDecision
└─ Génération AssertionLogEntry (journal d'audit)
```

**Point clé — Philosophie « Information-First » :** Le système ne rejette JAMAIS silencieusement une assertion. Chaque décision est auditée dans l'`AssertionLog` avec une raison standardisée (`AssertionLogReason` enum : 10+ raisons possibles).

#### 13.3.2 Meta-Pattern Filter — Chargement YAML externalisé

**Architecture patterns META (2026-01-27) :**

Les patterns de rejet sont externalisés dans des fichiers YAML pour être agnostiques au domaine :

```
config/meta_patterns/
├── structural_patterns.yaml   # Patterns structurels par langue (toujours chargés)
└── domain_extensions.yaml     # Extensions domaine (optionnelles, désactivées par défaut)
```

**Chargement au démarrage du module (`_load_meta_patterns()`) :**

1. **Charger `structural_patterns.yaml`** (obligatoire) — Patterns organisés par langue et catégorie
2. **Charger `domain_extensions.yaml`** (optionnel) — Si `active_domain` est défini, ajouter les patterns du domaine
3. **Compiler en regex** — Chaque pattern est compilé avec `re.IGNORECASE`, les patterns invalides sont comptés et ignorés

**Fallback si YAML absent :**

```python
META_REJECT_PATTERNS_FALLBACK = [
    r"^this\s+(page|section)\s+(describes|shows)",
    r"^see\s+also\b",
    r"^refer\s+to\b",
    r"^copyright\b",
    r"^disclaimer\s*:",
    r"^note\s*:",
    r"^\d+\.\s*$",
]
```

Les patterns sont compilés une seule fois au chargement du module (`_COMPILED_META_PATTERNS`), ce qui évite la recompilation à chaque assertion.

#### 13.3.3 Détection de fragments (non-assertions)

**Fonction :** `is_fragment(text)` dans `promotion_engine.py`

Un fragment est un texte qui ne constitue pas une assertion factuelle exploitable :

| Critère | Patterns | Exemples rejetés |
|---------|----------|------------------|
| Acronyme seul | `^[A-Z]{2,6}$` | "VPC", "ISO" |
| Nom propre seul | `^[A-Z][A-Za-z0-9\s\-]{0,20}$` | "ISO 27001" |
| Glossaire/définition | `^[A-Z]...{0,30}\.$` | "VPC Peering." |
| Titre/header | `^(section|chapter)...` | "Section 3" |
| Numérotation seule | `^\d+(\.\d+)*\s*$` | "3.2.1" |
| Puce incomplète | `^[-•]\s*\w+$` | "- Item" |

**Vérification de présence de verbe :** Si aucun pattern fragment ne matche, le système vérifie que le texte contient au moins un verbe (EN ou FR) parmi une liste de ~40 patterns verbaux (`ASSERTION_VERB_PATTERNS`). Un texte sans verbe détecté et de moins de 3 mots est un fragment.

#### 13.3.4 Promotion Policy — Politique par tier

**Deux implémentations coexistent :**

| Classe | Fichier | Usage |
|--------|---------|-------|
| `PromotionEngine._apply_promotion_policy()` | `promotion_engine.py` | Pipeline V2 principal (tier-based) |
| `PromotionPolicy.evaluate()` | `promotion_policy.py` | MVP V1 autonome (role-based, Information-First) |

**Promotion Engine — Mapping TYPE_TO_TIER :**

| Tier | Types d'assertion | Seuil confiance | Décision |
|------|-------------------|-----------------|----------|
| **ALWAYS** | DEFINITIONAL, PRESCRIPTIVE | Aucun | Toujours PROMOTED |
| **CONDITIONAL** | FACTUAL, CONDITIONAL, PERMISSIVE | ≥ 0.7 | PROMOTED si seuil atteint |
| **RARELY** | COMPARATIVE | ≥ 0.9 | PROMOTED si seuil élevé |
| **NEVER** | PROCEDURAL | N/A | Toujours REJECTED |

**PromotionPolicy MVP V1 — Logique en 6 étapes :**

L'évaluateur MVP V1 suit une logique Information-First avec priorité au rôle rhétorique :

1. **Rejet par meta-pattern** — Patterns internes (navigation, copyright, TOC)
2. **Rejet si texte < 15 chars** — `REJECTED` / `"text_too_short"`
3. **Promotion par type** — `PRESCRIPTIVE` ou `DEFINITIONAL` → `PROMOTED_LINKED`
4. **Promotion par rôle rhétorique** :
   - `FACT`, `DEFINITION`, `INSTRUCTION` → `PROMOTED_LINKED` (avec ClaimKey)
   - `EXAMPLE`, `CAUTION` → `PROMOTED_UNLINKED` (sans ClaimKey)
5. **Promotion si valeur présente** — `has_value = True` → `PROMOTED_LINKED`
6. **Défaut** — `PROMOTED_UNLINKED` / `"no_clear_category"` (jamais de rejet silencieux)

**Point clé :** La PromotionPolicy MVP V1 est plus permissive que le Promotion Engine V2 — elle ne rejette quasiment jamais (sauf meta-patterns et texte trop court). Cela reflète la philosophie Information-First de l'ADR North Star (NS-1).

#### 13.3.5 Value Extractor — Value Contract

**Classe :** `ValueExtractor` (`value_extractor.py`)

**Objectif :** Extraire et normaliser les valeurs bornées depuis le texte des assertions, conformément au Value Contract de l'ADR North Star (NS-6).

**Chaîne d'extraction (ordre de spécificité décroissante) :**

| # | Extracteur | Types détectés | Exemples | Normalisation |
|---|-----------|---------------|----------|---------------|
| 1 | `_extract_percent()` | `PERCENT` | "99.95%", "95 percent" | `float / 100.0` → `0.9995` |
| 2 | `_extract_version()` | `VERSION` | "TLS 1.2", "v3.14.1" | Tronqué à 3 niveaux max |
| 3 | `_extract_number_with_unit()` | `NUMBER` | "30 days", "100 GB", "5 TiB" | `float × multiplier` |
| 4 | `_extract_boolean()` | `BOOLEAN` | "enabled", "not required" | `True` / `False` |
| 5 | `_extract_enum()` | `ENUM` | "daily", "customer", "critical" | `str.lower()` |

**Structure de sortie — `ValueInfo` :**

```python
@dataclass
class ValueInfo:
    kind: Optional[ValueKind]          # NUMBER, PERCENT, VERSION, ENUM, BOOLEAN, STRING
    raw: Optional[str]                 # Texte source : "99.95%"
    normalized: Optional[float|str|bool]  # Valeur normalisée : 0.9995
    unit: Optional[str]                # Unité : "%", "days", "GB", "version"
    operator: str = "="               # Opérateur : =, >=, <=, >, <, approx, in
    comparable: ValueComparable = NON_COMPARABLE  # STRICT, LOOSE, NON_COMPARABLE
```

**Détection d'opérateur (`_detect_operator()`) :**

| Pattern | Opérateur résultant |
|---------|--------------------|
| `at least`, `minimum`, `≥` | `>=` |
| `at most`, `maximum`, `≤` | `<=` |
| `more than`, `above`, `>` | `>` |
| `less than`, `below`, `<` | `<` |
| `approximately`, `around`, `~` | `approx` |
| (défaut) | `=` |

**Point important — Ordre des booléens :** Les patterns négatifs (`not required`, `not supported`, `disabled`) sont vérifiés EN PREMIER pour éviter que "not required" ne matche d'abord "required" avec `True`.

**Familles d'enum supportées :**

| Famille | Valeurs |
|---------|---------|
| `frequency` | daily, weekly, monthly, hourly, yearly, continuous, quarterly |
| `responsibility` | customer, sap, vendor, shared, third-party |
| `severity` | critical, high, medium, low |
| `edition` | private, public, enterprise, standard |
| `environment` | production, development, staging, test |

**Singleton :** `get_value_extractor()` retourne une instance unique réutilisable.

#### 13.3.6 ClaimKey — Patterns Niveau A (inférence déterministe)

**Classe :** `ClaimKeyPatterns` (`claimkey/patterns.py`)

**Objectif :** Inférer un ClaimKey (question factuelle canonique) depuis le texte d'une assertion, sans LLM, par patterns regex déterministes. Conforme à l'ADR North Star (NS-5) — Niveau A d'inférence.

**Couverture des 15+ patterns :**

| Domaine | Pattern | ClaimKey généré | Type valeur |
|---------|---------|-----------------|-------------|
| SLA / Availability | `(\d+\.?\d*)%\s*(sla\|availability\|uptime)` | `sla_{context}_availability` | percent |
| Security / TLS | `tls\s*(\d+\.?\d*)` | `tls_min_version` | version |
| Security / Encryption | `(encryption\|encrypted)\s*(at\s*rest)` | `encryption_at_rest` | boolean |
| Security / Encryption | `(encryption\|encrypted)\s*(in\s*transit)` | `encryption_in_transit` | boolean |
| Backup | `backup.*?(daily\|weekly\|hourly)` | `backup_frequency` | enum |
| Retention | `retention.*?(\d+)\s*(days?\|months?)` | `data_retention_period` | number |
| Data Residency | `data.*?(remain\|stay\|stored?).*?(\w+)` | `data_residency_{country}` | boolean |
| Sizing | `(above\|over\|exceeds?).*?(\d+)\s*(tib\|tb\|gb)` | `{context}_size_threshold` | number |
| Responsibility | `(customer\|sap\|vendor).*?(responsible)` | `{topic}_responsibility` | enum |
| Compatibility | `(minimum\|required).*?version.*?(\d+\.?\d*)` | `{product}_min_version` | version |
| Patching | `(patch\|update).*?(daily\|weekly\|monthly)` | `patch_frequency` | enum |
| Recovery / RTO | `rto.*?(\d+)\s*(hours?\|minutes?)` | `rto_target` | number |
| Recovery / RPO | `rpo.*?(\d+)\s*(hours?\|minutes?)` | `rpo_target` | number |

**Résolution de templates :**

Les clés de ClaimKey utilisent des templates avec placeholders :
- `{context}` → contexte documentaire (product, topic)
- `{country}` → pays détecté dans le texte
- `{topic}` → sujet du document
- `{product}` → produit mentionné

**Structure de sortie — `PatternMatch` :**

```python
@dataclass
class PatternMatch:
    claimkey_id: str             # "ck_tls_min_version"
    key: str                     # "tls_min_version"
    domain: str                  # "security.encryption"
    canonical_question: str      # "What is the minimum TLS version required?"
    value_kind: str              # "version"
    match_text: str              # Texte matché
    inference_method: str = "pattern_level_a"
```

**Questions canoniques prédéfinies :** Le système maintient un dictionnaire `CANONICAL_QUESTIONS` de 10+ questions factuelles prédéfinies pour les ClaimKeys les plus courants (TLS, SLA, backup, retention, RTO/RPO, encryption).

**Singleton :** `get_claimkey_patterns()` retourne une instance unique.

#### 13.3.7 ClaimKey Status Manager — Gestion du cycle de vie

**Classe :** `ClaimKeyStatusManager` (`claimkey/status_manager.py`)

**Objectif :** Gérer la persistance et le cycle de vie des ClaimKeys dans Neo4j.

**Opérations CRUD :**

| Méthode | Opération Neo4j | Description |
|---------|-----------------|-------------|
| `get_or_create()` | `MATCH` ou `CREATE` | Récupère un ClaimKey existant ou en crée un nouveau |
| `link_information()` | `MERGE (i)-[:ANSWERS]->(ck)` | Crée la relation ANSWERS entre Information et ClaimKey |
| `update_metrics()` | `MATCH + COUNT + SET` | Recalcule info_count, doc_count et statut |
| `get_claimkey()` | `MATCH` | Récupère par ID |
| `find_by_key()` | `MATCH` | Recherche par clé machine |

**Cycle de vie ClaimKey — Statuts :**

```
Création → EMERGENT (< 2 docs)
                │
         (≥ 2 docs avec valeurs)
                │
                ▼
          COMPARABLE (comparaison cross-doc possible)
                │
         (remplacement)
                │
                ▼
          DEPRECATED

         (aucune info récente)
                │
                ▼
            ORPHAN
```

| Statut | Condition | Signification |
|--------|-----------|---------------|
| `EMERGENT` | `doc_count < 2` | Pas encore assez de sources pour comparaison |
| `COMPARABLE` | `doc_count ≥ 2` | Comparaison cross-document activée |
| `DEPRECATED` | Manuellement marqué | Remplacé par un autre ClaimKey |
| `ORPHAN` | `info_count = 0` | Aucune Information liée |

**Logique `update_metrics()` :**

```cypher
MATCH (ck:ClaimKey {claimkey_id: $ck_id})
OPTIONAL MATCH (i:InformationMVP)-[:ANSWERS]->(ck)
  WHERE i.promotion_status = 'PROMOTED_LINKED'
OPTIONAL MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
WITH ck, count(DISTINCT i) as info_count, count(DISTINCT d) as doc_count
-- Recalcul statut: ORPHAN si 0, EMERGENT si < 2 docs, COMPARABLE sinon
```

**Multi-tenancy :** Toutes les opérations sont filtrées par `tenant_id` pour garantir l'isolation des données.

#### 13.3.8 Modèle Information MVP — Assertion promue

**Classe :** `InformationMVP` (`models/information.py`)

**Objectif :** Représenter une assertion factuelle promue, stockée dans Neo4j comme noeud `InformationMVP`.

**Champs obligatoires :**

| Champ | Type | Conformité NS | Description |
|-------|------|---------------|-------------|
| `information_id` | str | — | Identifiant unique |
| `tenant_id` | str | — | Multi-tenancy |
| `document_id` | str | NS-4 | Source unique (pas de fusion cross-doc) |
| `text` | str | — | Texte normalisé de l'assertion |
| `exact_quote` | str | NS-3 | **OBLIGATOIRE** — Verbatim du texte source |
| `type` | InformationType | NS-9 | PRESCRIPTIVE, DEFINITIONAL, CAUSAL, COMPARATIVE |
| `rhetorical_role` | RhetoricalRole | NS-8 | FACT, EXAMPLE, DEFINITION, INSTRUCTION, CLAIM, CAUTION |
| `span` | SpanInfo | NS-3 | Position : page, paragraphe, ligne |

**Champs de promotion et liaison :**

| Champ | Type | Conformité NS | Description |
|-------|------|---------------|-------------|
| `promotion_status` | PromotionStatus | NS-9 | PROMOTED_LINKED, PROMOTED_UNLINKED, REJECTED |
| `promotion_reason` | str | — | Raison textuelle de la décision |
| `claimkey_id` | Optional[str] | NS-5 | Lien vers ClaimKey (si inféré) |
| `theme_id` | Optional[str] | NS-7 | Lien vers Theme (addressability) |
| `value` | ValueInfo | NS-6 | Valeur extraite (Value Contract) |
| `context` | ContextInfo | — | Contexte documentaire (edition, region, version, product) |
| `confidence` | float | — | Score de confiance 0.0 → 1.0 |
| `fingerprint` | str | NS-10 | Hash de déduplication |

**Fingerprint de déduplication (NS-10) :**

```python
def compute_fingerprint(self) -> str:
    """SHA256(claimkey_id:value_normalized:context_key:span_bucket)"""
    ck = self.claimkey_id or "no_claimkey"
    val = str(self.value.normalized) if self.value.normalized is not None else "no_value"
    ctx = self.context.to_context_key()  # "edition:version:region"
    page = str(self.span.page)  # Page, pas ligne exacte
    raw = f"{ck}:{val}:{ctx}:{page}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

**Point clé :** Le fingerprint utilise la PAGE et non la ligne exacte comme granularité de déduplication, ce qui permet de fusionner les reformulations d'un même fait sur la même page.

**Aplatissement Neo4j (`to_neo4j_properties()`) :**

Les objets imbriqués sont aplatis avec des préfixes pour le stockage Neo4j :
- `span.page` → `span_page`, `span_paragraph`, `span_line`
- `value.kind` → `value_kind`, `value_raw`, `value_normalized`, `value_unit`, `value_operator`, `value_comparable`
- `context.edition` → `context_edition`, `context_region`, `context_version`, `context_product`, `context_deployment`, `context_inheritance_mode`

**Héritage de contexte (`InheritanceMode`) :**

| Mode | Signification |
|------|---------------|
| `INHERITED` | Contexte hérité du titre/section parent |
| `ASSERTED` | Contexte explicitement mentionné dans le texte |
| `MIXED` | Partiellement hérité, partiellement asserté |
| `UNKNOWN` | Contexte non déterminé |

#### 13.3.9 Journal d'audit — AssertionLog

Chaque assertion traitée par le Promotion Engine génère un `AssertionLogEntry` dans le journal d'audit :

**Schéma V2 (`schemas.py`) :**

```python
class AssertionLogEntry(BaseModel):
    assertion_id: str
    text: str
    type: AssertionType
    confidence: Optional[float]
    status: AssertionStatus           # PROMOTED | ABSTAINED | REJECTED
    reason: AssertionLogReason        # 10+ raisons standardisées
    concept_id: Optional[str]
    anchor: Optional[Anchor]
    created_at: datetime
```

**Raisons standardisées (`AssertionLogReason`) :**

| Raison | Catégorie | Description |
|--------|-----------|-------------|
| `PROMOTED` | Promotion réussie | Assertion transformée en Information |
| `LOW_CONFIDENCE` | Promotion Policy | Confiance en dessous du seuil du tier |
| `POLICY_REJECTED` | Promotion Policy | Rejeté par la politique (tier NEVER, meta-pattern) |
| `NO_CONCEPT_MATCH` | Concept Linking | Aucun concept ne correspond |
| `AMBIGUOUS_LINKING` | Concept Linking | Lien concept ambigu |
| `NO_DOCITEM_ANCHOR` | Anchor Resolution | Ancrage DocItem impossible |
| `AMBIGUOUS_SPAN` | Anchor Resolution | Span ambigu (multiples DocItems candidats) |
| `CROSS_DOCITEM` | Anchor Resolution | Assertion chevauche plusieurs DocItems |
| `GENERIC_TERM` | Qualité | Terme trop générique |
| `SINGLE_MENTION` | Qualité | Mention unique dans le document |
| `CONTRADICTS_EXISTING` | Cross-doc (Pass 3) | Contradiction avec assertion existante |

#### 13.3.10 Theme Lint — Gouvernance thématique

**Statut :** ❌ **NON IMPLÉMENTÉ** — Le fichier `governance/theme_lint.py` est référencé dans la spec mais n'existe pas encore dans le code source.

**Objectif prévu :** Vérifier la cohérence entre les thèmes inférés par Pass 1.1 et les thèmes référencés dans les assertions promues. Détecter les thèmes orphelins (aucune Information liée) et les assertions avec des thèmes non reconnus.

### 13.4 Outputs

| Output | Type | Destination | Description |
|--------|------|-------------|-------------|
| `Information[]` | Liste de nœuds | Neo4j (`:InformationMVP`) | Assertions promues avec valeur, contexte, span, fingerprint |
| `AssertionLogEntry[]` | Liste d'entrées | Neo4j (`:AssertionLog`) | Journal d'audit de chaque décision |
| `ClaimKey[]` | Nœuds créés/mis à jour | Neo4j (`:ClaimKey`) | Questions factuelles canoniques |
| Relations `[:ANSWERS]` | Relations | Neo4j | Information → ClaimKey |
| Relations `[:EXTRACTED_FROM]` | Relations | Neo4j | Information → Document |

**Relations Neo4j générées :**

```
(:InformationMVP)-[:ANSWERS]->(:ClaimKey)          # Si ClaimKey inféré
(:InformationMVP)-[:EXTRACTED_FROM]->(:Document)    # Toujours
(:InformationMVP)-[:ANCHORED_IN]->(:DocItem)        # Via anchor_docitem_ids
(:InformationMVP)-[:BELONGS_TO]->(:Theme)           # Si theme_id disponible
```

**Métriques de sortie attendues :**

| Métrique | Cible |
|----------|-------|
| Taux de promotion LINKED | > 40% des assertions |
| Taux de promotion UNLINKED | 20-40% des assertions |
| Taux de rejet META + fragment | 10-30% des assertions |
| Taux d'abstention (confidence) | 5-15% des assertions |
| ClaimKeys inférés Niveau A | ~10-30% des assertions promues |

### 13.5 Conformité ADR — Pass 1.4

| Axe | Statut | Détail |
|-----|--------|--------|
| **NS-1 Information-First** | ✅ | L'Information est l'entité primaire. Zéro rejet pour `no_concept_match` — les assertions sans concept restent `PROMOTED_UNLINKED`. La PromotionPolicy MVP V1 ne rejette quasiment jamais. |
| **NS-3 Citation exacte obligatoire** | ✅ | `exact_quote` est un champ OBLIGATOIRE de `InformationMVP`. `SpanInfo` capture page/paragraphe/ligne. |
| **NS-4 Pas de synthèse cross-source** | ✅ | Chaque `InformationMVP` est liée à un seul `document_id`. Pas de fusion multi-documents. |
| **NS-5 ClaimKey comme pivot** | ⚠️ | ClaimKey Niveau A (patterns) implémenté. **Niveau B (LLM assisté) non implémenté** — seule l'inférence déterministe est opérationnelle. |
| **NS-6 Value Contract** | ✅ | `ValueExtractor` produit `ValueInfo` avec `raw`, `normalized`, `unit`, `operator`, `comparable`. 5 types supportés (NUMBER, PERCENT, VERSION, ENUM, BOOLEAN). |
| **NS-7 Addressability-First** | ⚠️ | Le système vérifie la présence de pivots mais **ne force pas le rejet** des orphelins totaux. Les assertions sans aucun pivot sont marquées `PROMOTED_UNLINKED` plutôt que rejetées. |
| **NS-8 Rhetorical Role** | ✅ | `RhetoricalRole` enum avec 6 rôles (FACT, EXAMPLE, DEFINITION, INSTRUCTION, CLAIM, CAUTION). La PromotionPolicy différencie : EXAMPLE/CAUTION → pas de ClaimKey. |
| **NS-9 Promotion Policy par type** | ✅ | `TYPE_TO_TIER` mapping implémenté : ALWAYS (DEFINITIONAL, PRESCRIPTIVE), CONDITIONAL (FACTUAL, CONDITIONAL, PERMISSIVE), RARELY (COMPARATIVE), NEVER (PROCEDURAL). |
| **NS-10 Déduplication fingerprint** | ✅ | `compute_fingerprint()` = `SHA256(claimkey_id:value_normalized:context_key:page)`. Granularité page pour fusionner les reformulations. |
| **AV2-3 Ancrage sur DocItem** | ✅ | `anchor_docitem_ids` stocke les IDs DocItem. Pas d'ancrage sur chunk Qdrant. |
| **AV2-5 AssertionLog** | ✅ | `AssertionLogEntry` avec `AssertionStatus` (PROMOTED/ABSTAINED/REJECTED) et `AssertionLogReason` (10+ raisons standardisées). |

### 13.6 Risques — Pass 1.4

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R14-1 | **ClaimKey Niveau B (LLM) absent** | 🟡 | L'inférence ClaimKey est limitée aux 15 patterns regex déterministes. Les assertions sans pattern reconnu n'ont pas de ClaimKey, ce qui réduit la comparabilité cross-doc. Le Niveau B (LLM assisté, NS-5) n'est pas implémenté. | Les patterns couvrent les domaines les plus fréquents (SLA, sécurité, backup, compliance). L'ajout de nouveaux patterns est simple (YAML). Le Niveau B est prévu dans une itération future. |
| R14-2 | **Coexistence PromotionEngine V2 / PromotionPolicy MVP V1** | 🟡 | Deux systèmes de promotion coexistent avec des logiques différentes. Le Pipeline V2 utilise `PromotionEngine` (tier-based), le MVP V1 utilise `PromotionPolicy` (role-based). Les résultats peuvent diverger pour les mêmes assertions. | La `PromotionPolicy` est un singleton stateless utilisé par le MVP V1 uniquement. La convergence vers le `PromotionEngine` V2 est planifiée à la fin du MVP. |
| R14-3 | **Addressability non stricte** | 🟡 | L'ADR NS-7 prescrit "orphelin total interdit" mais l'implémentation ne rejette pas les assertions sans pivot. Elles sont marquées `PROMOTED_UNLINKED`. Cela peut créer des nœuds Information inaccessibles dans le graphe. | La philosophie Information-First (NS-1) prime : mieux vaut une Information sans pivot qu'une perte. Pass 1.2b (raffinement itératif des concepts) peut récupérer ces orphelins a posteriori. |
| R14-4 | **Theme Lint non implémenté** | 🟢 | Le fichier `governance/theme_lint.py` n'existe pas. Aucune vérification de cohérence thématique entre les assertions promues et les thèmes identifiés en Pass 1.1. | La gouvernance thématique est une fonctionnalité de qualité, pas critique pour le fonctionnement du pipeline. Elle est planifiée comme amélioration post-MVP. |
| R14-5 | **Fingerprint sensible au claimkey_id** | 🟡 | Le fingerprint de déduplication inclut `claimkey_id`. Si le même fait est formulé différemment et matche un pattern différent (ou aucun pattern), il produira un fingerprint différent. Risque de doublons non détectés. | Le fingerprint est un mécanisme de déduplication de premier niveau. La résolution d'entités cross-doc (Pass 3) est le mécanisme de déduplication de second niveau. |
| R14-6 | **Détection de fragments limité aux verbes connus** | 🟢 | La détection de fragments repose sur ~40 patterns verbaux EN/FR. Les assertions dans d'autres langues ou avec des verbes rares peuvent être faussement rejetées comme fragments. | Le `language` du document est disponible dans le contexte. Une extension multilingue des patterns verbaux est possible. |
| R14-7 | **Value Extractor limité à 5 types** | 🟢 | MVP V1 supporte NUMBER, PERCENT, VERSION, ENUM, BOOLEAN. Les valeurs complexes (plages, listes, expressions temporelles composites) ne sont pas extraites. | Les 5 types couvrent les cas les plus fréquents en documentation technique. Le type `STRING` est défini dans l'enum mais pas extrait automatiquement. Extension prévue post-MVP. |
| R14-8 | **Patterns META externalisés en YAML — risque de désynchronisation** | 🟢 | Si les fichiers YAML de patterns sont absents ou corrompus, le système tombe sur un fallback minimal de 7 patterns. Le déploiement doit garantir la présence des fichiers de configuration. | Le système log un warning explicite si le fallback est utilisé. Les patterns invalides sont comptés et ignorés individuellement sans crash. |

---

## 14. Pass 2 — Enrichissement Sémantique

**Fichier principal :** `src/knowbase/stratified/pass2/relation_extractor.py` — classe `RelationExtractorV2`
**Orchestration :** `src/knowbase/stratified/pass2/orchestrator.py` — classe `Pass2OrchestratorV2`
**Persistence :** `src/knowbase/stratified/pass2/persister.py` — classe `Pass2PersisterV2`
**Prompts :** `src/knowbase/stratified/prompts/pass2_prompts.yaml` (si présent)
**ADR de référence :** `doc/ongoing/ADR_DISCURSIVE_RELATIONS.md`, `doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md`

### 14.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| `pass1_result` | `Pass1Result` | Pass 1 | Résultat complet de Pass 1 contenant `doc`, `concepts`, `informations` |
| `pass1_result.concepts` | `List[Concept]` | Pass 1.2 | Concepts identifiés avec `concept_id`, `name`, `role`, `variants`, `lex_key`, `theme_id` |
| `pass1_result.informations` | `List[Information]` | Pass 1.4 | Informations promues avec `info_id`, `concept_id`, `text`, `type`, `confidence`, `anchor` |
| `doc_id` | `str` | Pass 1 | Identifiant du document (extrait de `pass1_result.doc.doc_id`) |

**Mode alternatif — chargement depuis Neo4j :** `Pass2OrchestratorV2.process_from_neo4j(doc_id)` charge les concepts et informations directement depuis le graphe Neo4j via des requêtes Cypher (utile pour retraiter un document déjà persisté en Pass 1).

### 14.2 Objectifs

Pass 2 enrichit le graphe sémantique créé par Pass 1 en ajoutant les **relations inter-concepts**. Il s'agit de la phase de densification du graphe :

1. **Extraction de relations typées** — Identifier les liens sémantiques entre les concepts du document (ex: A REQUIRES B, A ENABLES B).
2. **Evidence-based** — Chaque relation est justifiée par au moins une Information du Pass 1 (`evidence_info_ids`).
3. **Frugalité relationnelle** — Garde-fou strict : maximum 3 relations par concept source pour éviter l'explosion combinatoire.
4. **Persistence dans le graphe** — Créer les arêtes `CONCEPT_RELATION` dans Neo4j entre les nœuds `Concept` existants.

### 14.3 Mécanismes

#### 14.3.1 Orchestration (`Pass2OrchestratorV2`)

L'orchestrateur enchaîne deux étapes principales :

```
Pass1Result → RelationExtractorV2.extract_relations() → Pass2Result
                                                            ↓
                                                   Pass2PersisterV2.persist()
                                                            ↓
                                                      Neo4j (arêtes)
```

**Deux points d'entrée :**

| Méthode | Usage | Source des données |
|---------|-------|--------------------|
| `process(pass1_result)` | Pipeline inline | `Pass1Result` en mémoire |
| `process_from_neo4j(doc_id)` | Retraitement | Chargement depuis Neo4j via Cypher |

Le flag `persist: bool = True` contrôle la persistence dans Neo4j (désactivable pour tests ou dry-run).

**Chargement depuis Neo4j (`_load_from_neo4j`) :**

Les requêtes Cypher traversent le graphe structurel complet :

```cypher
-- Concepts
MATCH (d:Document {doc_id, tenant_id})
      -[:HAS_SUBJECT]->(:Subject)
      -[:HAS_THEME]->(t:Theme)
      -[:HAS_CONCEPT]->(c:Concept)
RETURN c.concept_id, c.name, c.role, c.variants, c.lex_key, t.theme_id

-- Informations
MATCH (d:Document {doc_id, tenant_id})
      -[:HAS_SUBJECT]->(:Subject)
      -[:HAS_THEME]->(:Theme)
      -[:HAS_CONCEPT]->(c:Concept)
      -[:HAS_INFORMATION]->(i:Information)
      -[a:ANCHORED_IN]->(di:DocItem)
RETURN i.info_id, i.text, i.type, i.confidence, c.concept_id,
       di.docitem_id, a.span_start, a.span_end
```

#### 14.3.2 Types de relations (`RelationType`)

Pass 2 définit 8 types de relations entre concepts :

| Type | Sémantique | Exemple |
|------|-----------|---------|
| `REQUIRES` | A nécessite B | "S/4HANA requires SAP BTP" |
| `ENABLES` | A permet/rend possible B | "ABAP Cloud enables extension development" |
| `CONSTRAINS` | A limite/contraint B | "License constrains module usage" |
| `DEPENDS_ON` | A dépend de B | "Fiori depends on Gateway" |
| `RELATED_TO` | Relation générique | Lien sémantique non classifiable |
| `SPECIALIZES` | A est une spécialisation de B | "SAP BTP ABAP Environment specializes ABAP" |
| `PART_OF` | A fait partie de B | "Module A is part of Suite B" |
| `CONTRADICTS` | A contredit B | Assertions contradictoires entre concepts |

La liste `VALID_RELATION_TYPES` est utilisée pour valider les réponses LLM. Tout type invalide est rétrogradé en `RELATED_TO`.

#### 14.3.3 Extraction via LLM (`_extract_via_llm`)

**Flux d'extraction LLM :**

1. **Construction de l'index** `concept_id → List[Information]` via `_build_concept_info_index()` — rattache chaque information à son concept parent.
2. **Formatage du prompt** — Chaque concept est présenté avec son ID, nom, rôle, variantes et les 3 premières informations associées (tronquées à 150 caractères).
3. **Appel LLM** — `llm_client.generate()` avec `max_tokens=3000`.
4. **Parsing JSON** — Extraction du bloc ````json ... ````, désérialisation et validation.

**Prompts (configurables via YAML ou défauts intégrés) :**

- **System prompt** : rôle d'expert en extraction de relations, liste des types valides, règles (justification obligatoire, seuils de confiance, maximum 3 relations/concept).
- **User prompt** : template `{concepts}` + `{relation_types}`, réponse attendue en JSON structuré.

**Seuils de confiance dans le prompt :**

| Catégorie | Confiance |
|-----------|-----------|
| Relation explicite | ≥ 0.7 |
| Relation implicite | 0.5 – 0.7 |

**Validation de la réponse LLM (`_parse_relations_response`) :**

- Validation que `source_concept_id` et `target_concept_id` existent dans la liste des concepts
- Validation que `relation_type` est dans `VALID_RELATION_TYPES` (sinon fallback `RELATED_TO`)
- Filtrage des `evidence_info_ids` : seuls les IDs d'informations existantes sont conservés

**Fallback automatique :** si l'appel LLM échoue (exception), le système bascule sur l'extraction heuristique.

#### 14.3.4 Extraction heuristique (`_extract_heuristic`)

Mode dégradé activable via `allow_fallback=True` ou en cas d'échec LLM :

1. **Pour chaque concept** → pour chaque information associée → pour chaque autre concept :
   - Vérifier si l'autre concept est **mentionné dans le texte** de l'information (nom ou variantes, case-insensitive)
   - Si oui, **inférer le type de relation** par pattern matching sur des mots-clés textuels

2. **Patterns d'inférence de type (`_infer_relation_type`) :**

| Type inféré | Mots-clés détectés |
|-------------|-------------------|
| `REQUIRES` | `requires`, `nécessite`, `need`, `must have` |
| `ENABLES` | `enables`, `permet`, `allows`, `makes possible` |
| `CONSTRAINS` | `constrains`, `limits`, `restricts`, `contraint` |
| `DEPENDS_ON` | `depends on`, `relies on`, `dépend de` |
| `PART_OF` | `part of`, `component of`, `partie de` |
| `SPECIALIZES` | `type of`, `kind of`, `specialization`, `spécialisation` |
| `CONTRADICTS` | `contradicts`, `conflicts with`, `contredit` |
| `RELATED_TO` | Aucun pattern matché (défaut) |

3. **Confiance fixe** : toutes les relations heuristiques reçoivent `confidence=0.6`.
4. **Justification** : co-occurrence avec extrait de texte (100 premiers caractères).

#### 14.3.5 Garde-fou frugalité — Limite de relations (`_apply_relation_limit`)

Mécanisme anti-explosion combinatoire, constante de classe :

```python
MAX_RELATIONS_PER_CONCEPT = 3
```

**Algorithme :**
1. Grouper les relations par `source_concept_id`
2. Trier chaque groupe par `confidence` décroissante
3. Conserver les 3 premières relations (plus haute confiance)
4. Comptabiliser les relations rejetées dans `Pass2Stats.relations_filtered`

Ce garde-fou s'applique uniformément sur les résultats LLM et heuristiques.

#### 14.3.6 Persistence Neo4j (`Pass2PersisterV2`)

**Modèle de relation Neo4j :**

```cypher
MATCH (source:Concept {concept_id: $source_id, tenant_id: $tenant_id})
MATCH (target:Concept {concept_id: $target_id, tenant_id: $tenant_id})
MERGE (source)-[r:CONCEPT_RELATION {relation_id: $relation_id}]->(target)
SET r.type = $relation_type,
    r.confidence = $confidence,
    r.evidence_info_ids = $evidence,
    r.justification = $justification,
    r.created_at = datetime()
```

**Points notables :**

- Le label de relation est **générique** (`CONCEPT_RELATION`) avec le type sémantique stocké en **propriété** (`r.type`). Pas de labels dynamiques (pas d'APOC requis).
- `MERGE` sur `relation_id` : idempotent, re-exécuter Pass 2 met à jour sans dupliquer.
- `evidence_info_ids` est stocké comme liste de strings — référence les `info_id` des informations-preuves.
- Multi-tenant via `tenant_id` sur les nœuds source et cible.

**Suppression des données Pass 2 (`delete_pass2_data`) :**

Traverse le graphe `Document → Subject → Theme → Concept` puis supprime toutes les relations `CONCEPT_RELATION` sortantes. Utilisé pour retraitement.

**Fonction utilitaire :** `persist_pass2_result(result, neo4j_driver, tenant_id)` — wrapper stateless pour usage ponctuel.

### 14.4 Outputs

**Dataclass principale :**

```python
@dataclass
class Pass2Result:
    doc_id: str
    relations: List[ConceptRelation]  # Relations extraites et filtrées
    stats: Pass2Stats                 # Métriques d'exécution
```

**Structure d'une relation (`ConceptRelation`) :**

```python
@dataclass
class ConceptRelation:
    relation_id: str           # Identifiant unique (format "rel_{uuid8}")
    source_concept_id: str     # ID du concept source
    target_concept_id: str     # ID du concept cible
    relation_type: str         # Un des 8 types RelationType
    confidence: float          # Score de confiance [0.0, 1.0]
    evidence_info_ids: List[str]  # IDs des informations-preuves
    justification: str         # Explication textuelle de la relation
```

**Statistiques (`Pass2Stats`) :**

```python
@dataclass
class Pass2Stats:
    concepts_processed: int        # Nombre de concepts analysés
    relations_extracted: int       # Relations conservées après garde-fou
    relations_filtered: int        # Relations rejetées par le garde-fou
    avg_relations_per_concept: float  # Ratio relations / concepts
```

**Sortie Neo4j :**

| Élément | Détail |
|---------|--------|
| Arêtes créées | `(Concept)-[:CONCEPT_RELATION]->(Concept)` |
| Propriétés | `relation_id`, `type`, `confidence`, `evidence_info_ids`, `justification`, `created_at` |
| Compteur retourné | `{"relations_created": N}` |

### 14.5 Conformité ADR — Pass 2

| # | Axe ADR | Statut | Détail |
|---|---------|--------|--------|
| AV2-1 | Séparation structure / sémantique | ✅ | Les relations sont entre nœuds `Concept` (couche sémantique), pas entre `DocItem` (couche structurelle) |
| AV2-2 | 8 types de nodes maximum | ✅ | Pass 2 ne crée aucun nouveau type de nœud — uniquement des arêtes entre nœuds existants |
| AV2-8 | Dual storage (Neo4j + Qdrant) | ⚠️ | Pass 2 ne persiste que dans Neo4j. Pas de mise à jour Qdrant (les relations ne sont pas vectorisées). Conforme à l'esprit (relations = graphe navigable) |
| NS-2 | LLM = Extracteur evidence-locked | ✅ | Le LLM extrait des relations, il ne décide pas du type final (validation post-extraction). Chaque relation doit avoir `evidence_info_ids` |
| NS-4 | Pas de synthèse cross-source | ✅ | Les relations sont intra-document : entre concepts d'un même document. Pas de relations cross-doc en Pass 2 |
| NS-7 | Addressability-First | ✅ | Les relations sont navigables via les concepts, eux-mêmes rattachés aux thèmes et au sujet |
| SCOPE | Scope vs Assertion separation | ⚠️ | L'implémentation actuelle ne distingue pas explicitement les relations de scope (dense) vs. les relations d'assertion (sparse). Toutes les relations sont traitées uniformément comme `CONCEPT_RELATION`. Voir § 14.6 R2-4 |
| DR-C1 | Pas de nouvelle couche (ADR Discursive) | ✅ | Pass 2 ne crée pas de nouvelle couche — les relations sont des arêtes, pas des nœuds |
| DR-C2 | Evidence-first (ADR Discursive) | ⚠️ | Les relations ont `evidence_info_ids` mais pas de `EvidenceBundle` formel. La justification est un texte libre, pas un span multi-source structuré |
| DR-C3 | Pas de contamination par inférence | ⚠️ | Le mode heuristique infère des relations par co-occurrence de noms. C'est une heuristique lexicale, pas une inférence sémantique profonde, mais le risque de faux positifs existe |
| DR-C3bis | ExtractionMethod autorisé | ❌ | L'implémentation ne trace pas la méthode d'extraction (`PATTERN`, `LLM`, `HYBRID`). Impossible de distinguer assertions EXPLICIT vs DISCURSIVE |
| DR-C4 | Whitelist RelationType par AssertionKind | ❌ | Les 8 types de relations sont utilisés uniformément. Pas de distinction EXPLICIT/DISCURSIVE ni de whitelist restrictive pour les relations discursives |

### 14.6 Risques — Pass 2

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R2-1 | **Label générique `CONCEPT_RELATION`** | 🟡 | Toutes les relations utilisent un label unique (`CONCEPT_RELATION`) avec le type en propriété. Cela empêche les traversées Cypher typées (ex: `MATCH -[:REQUIRES]->`) et oblige un filtre `WHERE r.type = ...` sur chaque requête. | Acceptable en MVP. Migration possible vers labels dynamiques via APOC si les performances de traversée deviennent un problème. Le commentaire dans le code mentionne cette évolution. |
| R2-2 | **Garde-fou à 3 relations arbitraire** | 🟡 | La limite de 3 relations par concept source est un choix pragmatique. Pour des documents très denses, cela pourrait masquer des relations significatives. Le tri par confiance atténue le risque mais ne l'élimine pas. | Constante de classe `MAX_RELATIONS_PER_CONCEPT` facilement ajustable. Monitoring via `Pass2Stats.relations_filtered` pour détecter les cas de filtrage excessif. |
| R2-3 | **Heuristique de fallback peu fiable** | 🟡 | Le mode heuristique repose sur la co-occurrence lexicale simple (présence du nom/variante dans le texte). Cela génère des faux positifs (deux concepts mentionnés dans la même phrase ne sont pas nécessairement en relation). Confiance fixe à 0.6 sans discrimination. | Le mode heuristique est explicitement marqué comme non fiable (`logger.warning`). Flag `allow_fallback` désactivé par défaut. |
| R2-4 | **Pas de distinction Scope vs Assertion pour les relations** | 🟡 | L'ADR Scope vs Assertion Separation établit que le Scope Layer (ce que le document couvre) est distinct de l'Assertion Layer (ce que le document affirme). Les relations Pass 2 ne portent pas cette distinction — une relation `RELATED_TO` par co-occurrence est fondamentalement un lien de scope, pas d'assertion. | Évolution nécessaire pour taguer `assertion_kind` (EXPLICIT/DISCURSIVE) sur les relations. Non bloquant en MVP mais requis pour la conformité ADR Discursive Relations. |
| R2-5 | **Absence de `DefensibilityTier` et `EvidenceBundle`** | 🟡 | L'ADR Relations Discursivement Déterminées prévoit un pipeline `RawAssertion → CanonicalRelation → SemanticRelation` avec `DefensibilityTier` (STRICT/EXTENDED). L'implémentation actuelle crée directement des `CONCEPT_RELATION` sans passer par ce pipeline à trois couches. | L'ADR est un objectif architectural. L'implémentation actuelle est un MVP fonctionnel. La migration vers le modèle ADR complet est une tâche dédiée. |
| R2-6 | **Pas de déduplication des relations** | 🟢 | Le `MERGE` Neo4j sur `relation_id` prévient les doublons exacts. Cependant, si Pass 2 est exécuté plusieurs fois avec des UUID différents, des relations sémantiquement identiques mais avec des `relation_id` distincts pourraient coexister. | `delete_pass2_data()` permet de purger avant retraitement. L'idempotence est garantie au niveau du `relation_id`, pas au niveau sémantique. |
| R2-7 | **Persistance relation par relation (pas de batch)** | 🟢 | Le persister itère sur les relations et exécute une transaction par relation. Pour des documents avec beaucoup de relations, cela pourrait être lent. | Optimisation possible via `UNWIND` Cypher pour batch insert. Non critique en MVP vu le garde-fou à 3 relations/concept (max ~45 relations pour 15 concepts). |

---

## 15. Pass 3 — Consolidation Corpus (Entity Resolution Cross-Document)

**Fichier principal :** `src/knowbase/stratified/pass3/entity_resolver.py` — classe `EntityResolverV2`
**Orchestration :** `src/knowbase/stratified/pass3/orchestrator.py` — classe `Pass3OrchestratorV2`
**Persistence :** `src/knowbase/stratified/pass3/persister.py` — classe `Pass3PersisterV2`
**Modèle transverse :** `src/knowbase/stratified/models/contradiction.py` — classe `Contradiction`
**ADR de référence :** `doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md` (AV2-9), `doc/ongoing/ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md` (NS-4, NS-5, NS-10)

> **Positionnement dans le pipeline :** Pass 3 est la seule phase opérant au **niveau corpus** (multi-documents). Toutes les passes précédentes (0 → 2) traitent un document unique. Pass 3 consolide le graphe sémantique en résolvant les entités identiques provenant de documents différents.

### 15.1 Entrants

| Entrant | Type | Source | Description |
|---------|------|--------|-------------|
| Concepts du corpus | `List[Concept]` | Neo4j (mode batch) | Tous les concepts persistés dans le graphe, chargés via requête Cypher sur `tenant_id` |
| Thèmes du corpus | `List[Theme]` | Neo4j (mode batch) | Tous les thèmes persistés dans le graphe |
| Nouveaux concepts | `List[Concept]` | Pass 1 (mode incrémental) | Concepts d'un nouveau document à intégrer |
| CanonicalConcept existants | `List[CanonicalConcept]` | Neo4j (mode incrémental) | Concepts canoniques déjà créés par des exécutions précédentes |

**Chargement depuis Neo4j (`_load_all_from_neo4j`) :**

```cypher
-- Concepts
MATCH (c:Concept {tenant_id: $tenant_id})
OPTIONAL MATCH (t:Theme)-[:HAS_CONCEPT]->(c)
RETURN c.concept_id, c.name, c.role, c.variants, c.lex_key,
       t.theme_id

-- Thèmes
MATCH (t:Theme {tenant_id: $tenant_id})
RETURN t.theme_id, t.name

-- CanonicalConcept existants (mode incrémental)
MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
OPTIONAL MATCH (cc)-[:SAME_AS]->(c:Concept)
RETURN cc.canonical_id, cc.name, collect(c.concept_id) AS merged_from
```

### 15.2 Objectifs

Pass 3 réalise la **consolidation au niveau corpus** du graphe sémantique en :

1. **Résolution d'entités cross-documents** — Identifier les concepts identiques provenant de documents différents et les fusionner en `CanonicalConcept`.
2. **Alignement de thèmes cross-documents** — Regrouper les thèmes similaires provenant de documents différents en `CanonicalTheme`.
3. **Création de la couche canonique** — Établir les relations `SAME_AS` (concepts) et `ALIGNED_TO` (thèmes) entre entités canoniques et entités sources.
4. **Support dual mode** — Fonctionner en mode **batch** (traitement complet du corpus) ou **incrémental** (intégration d'un nouveau document).

### 15.3 Mécanismes

#### 15.3.1 Orchestration (`Pass3OrchestratorV2`)

L'orchestrateur expose deux modes d'exécution définis par l'enum `Pass3Mode` :

```
┌──────────────────────────────────────────────────────────┐
│ Mode BATCH                                               │
│   Neo4j (all Concepts+Themes)                            │
│     → EntityResolverV2.resolve()                         │
│       → _cluster_concepts() → _create_canonical_concepts │
│       → _cluster_themes()   → _create_canonical_themes   │
│     → Pass3PersisterV2.persist()                         │
│       → Neo4j (CanonicalConcept, CanonicalTheme)         │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ Mode INCREMENTAL                                         │
│   new_concepts (Pass 1) + existing_canonical (Neo4j)     │
│     → EntityResolverV2.resolve_incremental()             │
│       → Matching par nom/variantes                       │
│       → Fusion ou création de nouveaux canoniques        │
│     → Pass3PersisterV2.persist() (si nouveaux canoniques)│
└──────────────────────────────────────────────────────────┘
```

**Points d'entrée :**

| Méthode | Mode | Source des données | Usage |
|---------|------|--------------------|-------|
| `process_batch(persist=True)` | BATCH | Neo4j (tout le corpus) | Reconsolidation complète |
| `process_incremental(new_concepts, persist=True)` | INCREMENTAL | `List[Concept]` en mémoire + Neo4j | Ajout d'un document |
| `run_pass3_batch(neo4j_driver, ...)` | BATCH | Wrapper utilitaire stateless | Script / CLI |
| `run_pass3_incremental(new_concepts, ...)` | INCREMENTAL | Wrapper utilitaire stateless | Script / CLI |

**Préconditions :**

- Mode batch : `neo4j_driver` obligatoire (sinon `RuntimeError`)
- Mode incrémental : les CanonicalConcept existants sont chargés via `_load_canonical_concepts()`
- Dépendances injectées : `llm_client`, `embedding_client`, `neo4j_driver` (tous optionnels sauf Neo4j en batch)

#### 15.3.2 Clustering de concepts (`EntityResolverV2`)

Le cœur de Pass 3 est le **clustering de concepts** similaires provenant de documents différents. L'algorithme utilise une stratégie en 3 niveaux de priorité décroissante :

**Stratégie 1 — Matching exact par `lex_key` :**

```python
# Index par lex_key
by_lex_key: Dict[str, List[Concept]] = {}
for concept in concepts:
    if concept.lex_key:
        by_lex_key[concept.lex_key].append(concept)
```

Tous les concepts partageant la même `lex_key` (clé lexicale normalisée) sont regroupés dans un même `ConceptCluster`. Cette stratégie produit des clusters de haute confiance car la `lex_key` est une forme canonique calculée en Pass 1.2.

**Stratégie 2 — Matching par variantes :**

Pour les concepts non assignés par la stratégie 1, le système cherche une intersection entre les ensembles `{name, variants}` de chaque concept et ceux des concepts déjà clusterisés :

```python
concept_names = {concept.name.lower()} | {v.lower() for v in concept.variants}
other_names = {other.name.lower()} | {v.lower() for v in other.variants}
if concept_names & other_names:  # Intersection non vide
    → merge dans le cluster existant
```

**Stratégie 3 — Similarité par embeddings (prévue, non implémentée) :**

Le paramètre `embedding_client` est accepté par le constructeur mais la stratégie de clustering par similarité sémantique (cosine similarity sur embeddings) n'est **pas encore implémentée**. Le seuil `SIMILARITY_THRESHOLD = 0.85` est défini comme constante de classe mais non utilisé dans le code actuel.

**Concepts orphelins :** Les concepts qui ne matchent aucun cluster existant sont placés dans des **clusters singletons** (un concept = un cluster). Ces singletons ne génèrent pas de `CanonicalConcept` (voir §15.3.3).

#### 15.3.3 Création des CanonicalConcept

Un `CanonicalConcept` est créé **uniquement si le cluster contient ≥ 2 concepts** (fusion effective) :

```python
for cluster in clusters:
    if len(cluster.concept_ids) > 1:  # Seulement si fusion
        cc = CanonicalConcept(
            canonical_id=f"canonical_{cluster.cluster_id}",
            name=cluster.representative_name,    # Nom du premier concept
            merged_from=cluster.concept_ids       # IDs de tous les concepts fusionnés
        )
```

Le nom représentatif est celui du **premier concept du cluster** (ordre d'insertion). Pas de sélection heuristique du meilleur nom.

#### 15.3.4 Clustering de thèmes (`_cluster_themes`)

Les thèmes sont clusterisés par **nom normalisé exact** (lowercase + strip) :

```python
norm_name = theme.name.lower().strip()
by_name[norm_name].append(theme)
```

Création de `CanonicalTheme` uniquement si ≥ 2 thèmes partagent le même nom normalisé.

**⚠️ Déviation notable :** Contrairement au clustering de concepts (qui utilise `lex_key` + variantes), le clustering de thèmes ne dispose d'aucun mécanisme de matching sémantique. Seule la correspondance exacte de noms (après normalisation) est utilisée.

#### 15.3.5 Résolution incrémentale (`resolve_incremental`)

Le mode incrémental traite un nouvel ensemble de concepts par rapport aux `CanonicalConcept` existants :

1. **Construction d'un index** `nom_normalisé → CanonicalConcept` à partir des canoniques existants.
2. **Pour chaque nouveau concept :**
   - Match par nom exact (`concept.name.lower()` dans l'index)
   - Match par variantes (`variant.lower()` dans l'index)
   - Si match : fusion (`concept_id` ajouté à `merged_from` du canonique existant)
   - Si pas de match : **aucune action** (pas de création de singleton en mode incrémental — attente du prochain batch)
3. **Retour** : `(updated_canonical, mapping)` où `mapping` associe chaque `concept_id` au `canonical_id` correspondant.

**Point notable :** Le mode incrémental est **conservateur** — il ne crée jamais de nouveau `CanonicalConcept`. Les concepts sans match restent isolés jusqu'au prochain batch. Cette stratégie évite la prolifération de canoniques singletons.

#### 15.3.6 Persistence Neo4j (`Pass3PersisterV2`)

**Modèle de persistance :**

```
CanonicalConcept -[:SAME_AS]-> Concept     (pour chaque concept fusionné)
CanonicalTheme   -[:ALIGNED_TO]-> Theme    (pour chaque thème aligné)
```

**Transaction CanonicalConcept (`_create_canonical_concept_tx`) :**

```cypher
-- Créer/mettre à jour le nœud CanonicalConcept
MERGE (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
SET cc.name = $name, cc.created_at = datetime()

-- Pour chaque concept fusionné, créer la relation SAME_AS
MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
MATCH (c:Concept {concept_id: $concept_id, tenant_id: $tenant_id})
MERGE (cc)-[:SAME_AS]->(c)
```

**Transaction CanonicalTheme (`_create_canonical_theme_tx`) :**

```cypher
MERGE (ct:CanonicalTheme {canonical_id: $canonical_id, tenant_id: $tenant_id})
SET ct.name = $name, ct.created_at = datetime()

MATCH (ct:CanonicalTheme {canonical_id: $canonical_id, tenant_id: $tenant_id})
MATCH (t:Theme {theme_id: $theme_id, tenant_id: $tenant_id})
MERGE (ct)-[:ALIGNED_TO]->(t)
```

**Points notables :**

- `MERGE` sur `canonical_id + tenant_id` : idempotent, re-exécuter Pass 3 met à jour sans dupliquer.
- Multi-tenant intégré via `tenant_id` sur tous les nœuds et MATCH.
- Les relations `SAME_AS` et `ALIGNED_TO` sont créées **une par une** (itération, pas de batch `UNWIND`).
- Aucun mécanisme de suppression des données Pass 3 existantes avant retraitement (contrairement à Pass 2 qui dispose de `delete_pass2_data()`).

**Fonction utilitaire :** `persist_pass3_result(result, neo4j_driver, tenant_id)` — wrapper stateless pour usage ponctuel.

**Compteurs retournés (`persist`) :**

```python
stats = {
    "canonical_concepts": int,      # Nombre de CanonicalConcept créés
    "canonical_themes": int,        # Nombre de CanonicalTheme créés
    "same_as_relations": int,       # Nombre de relations SAME_AS
    "aligned_to_relations": int,    # Nombre de relations ALIGNED_TO
}
```

### 15.4 Modèle de données transverse — Contradiction

**Fichier :** `src/knowbase/stratified/models/contradiction.py`
**Usage :** OSMOSE MVP V1 — Usage B (Challenge de Texte)
**Référence :** `SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md`

Le modèle `Contradiction` représente une **tension détectée entre deux Informations** partageant le même `ClaimKey`. Il opère au niveau cross-document et constitue un des résultats attendus de la consolidation corpus.

#### 15.4.1 Structure de données

```python
@dataclass
class Contradiction:
    # Identifiants
    contradiction_id: str        # Identifiant unique
    claimkey_id: str             # ClaimKey partagée (pivot de comparaison)

    # Information A
    info_a_id: str               # ID de la première Information
    info_a_document: str         # Document source de A
    info_a_value_raw: Optional[str]   # Valeur brute de A
    info_a_context: dict         # Contexte de A

    # Information B
    info_b_id: str               # ID de la seconde Information
    info_b_document: str         # Document source de B
    info_b_value_raw: Optional[str]   # Valeur brute de B
    info_b_context: dict         # Contexte de B

    # Classification
    nature: ContradictionNature  # Type de contradiction
    tension_level: TensionLevel  # Niveau de tension
    explanation: str             # Explication textuelle

    # Métadonnées
    detected_at: datetime        # Horodatage de détection (UTC)
    detection_method: str        # Méthode de détection (défaut: "value_normalized_comparison")
```

#### 15.4.2 Taxonomie des contradictions (`ContradictionNature`)

| Valeur | Sémantique | Type |
|--------|-----------|------|
| `VALUE_CONFLICT` | Conflit de valeurs (A affirme X, B affirme Y pour la même ClaimKey) | Hard |
| `VALUE_EXCEEDS_MINIMUM` | Valeur au-dessus d'un minimum déclaré | Soft |
| `VALUE_BELOW_MAXIMUM` | Valeur en dessous d'un maximum déclaré | Soft |
| `SCOPE_CONFLICT` | Conflit de périmètre (applicable dans des contextes différents) | Variable |
| `TEMPORAL_CONFLICT` | Conflit temporel (vrai à des moments différents) | Variable |
| `MISSING_CLAIM` | Absence d'affirmation attendue (un document ne mentionne pas ce que l'autre affirme) | Soft |

#### 15.4.3 Niveaux de tension (`TensionLevel`)

| Niveau | Signification |
|--------|---------------|
| `NONE` | Pas de tension réelle (faux positif résolu) |
| `SOFT` | Compatible mais différent — les deux valeurs peuvent coexister |
| `HARD` | Incompatible — les deux valeurs sont mutuellement exclusives |
| `UNKNOWN` | Tension non classifiable |

#### 15.4.4 Sérialisation Neo4j

La classe fournit deux méthodes de sérialisation/désérialisation Neo4j :

- `to_neo4j_properties()` → `dict` : convertit toutes les propriétés en types Neo4j-compatibles (enums → `.value`, datetime → `.isoformat()`)
- `from_neo4j_record(record)` → `Contradiction` : reconstruit depuis un record Cypher, avec gestion des champs optionnels et valeurs par défaut

**⚠️ Statut d'implémentation :** Le modèle `Contradiction` est défini et prêt à l'emploi, mais le **détecteur de contradictions** (composant qui comparerait les Informations via ClaimKey + Value Contract pour créer des instances `Contradiction`) n'est **pas encore implémenté** dans le pipeline. La détection de contradictions est un objectif du MVP V1 Usage B.

### 15.5 Outputs

**Dataclass principale :**

```python
@dataclass
class Pass3Result:
    canonical_concepts: List[CanonicalConcept]   # Concepts canoniques créés
    canonical_themes: List[CanonicalTheme]        # Thèmes canoniques créés
    concept_clusters: List[ConceptCluster]        # Clusters de concepts
    theme_clusters: List[ThemeCluster]            # Clusters de thèmes
    stats: Pass3Stats                             # Métriques d'exécution
```

**Structure d'un cluster de concepts (`ConceptCluster`) :**

```python
@dataclass
class ConceptCluster:
    cluster_id: str                          # Identifiant unique (format "cluster_{uuid8}")
    concept_ids: List[str]                   # IDs des concepts regroupés
    representative_name: str                 # Nom représentatif du cluster
    similarity_scores: Dict[str, float]      # Scores de similarité (non utilisé actuellement)
```

**Structure d'un cluster de thèmes (`ThemeCluster`) :**

```python
@dataclass
class ThemeCluster:
    cluster_id: str                          # Identifiant unique (format "theme_cluster_{uuid8}")
    theme_ids: List[str]                     # IDs des thèmes regroupés
    representative_name: str                 # Nom représentatif du cluster
```

**Statistiques (`Pass3Stats`) :**

```python
@dataclass
class Pass3Stats:
    concepts_processed: int            # Nombre de concepts analysés
    themes_processed: int              # Nombre de thèmes analysés
    concept_clusters: int              # Nombre de clusters de concepts formés
    theme_clusters: int                # Nombre de clusters de thèmes formés
    canonical_concepts_created: int    # Nombre de CanonicalConcept créés
    canonical_themes_created: int      # Nombre de CanonicalTheme créés
```

**Sortie Neo4j :**

| Élément | Détail |
|---------|--------|
| Nœuds créés | `CanonicalConcept` avec `canonical_id`, `name`, `tenant_id`, `created_at` |
| Nœuds créés | `CanonicalTheme` avec `canonical_id`, `name`, `tenant_id`, `created_at` |
| Relations créées | `(CanonicalConcept)-[:SAME_AS]->(Concept)` |
| Relations créées | `(CanonicalTheme)-[:ALIGNED_TO]->(Theme)` |
| Compteurs retournés | `canonical_concepts`, `canonical_themes`, `same_as_relations`, `aligned_to_relations` |

### 15.6 Conformité ADR — Pass 3

| # | Axe ADR | Statut | Détail |
|---|---------|--------|--------|
| AV2-2 | 8 types de nodes maximum | ⚠️ | Pass 3 crée deux nouveaux types de nœuds (`CanonicalConcept`, `CanonicalTheme`) qui s'ajoutent aux 8 types V2 de base. Cela porte le total à 10 types. Acceptable car ces nœuds sont des **superpositions** (couche canonique au-dessus de la couche document), mais dépasse la règle stricte des 8 types |
| AV2-9 | Pass 3 mode manuel + batch | ✅ | L'implémentation supporte les deux modes prévus : **BATCH** (reconsolidation complète) et **INCREMENTAL** (ajout d'un document). Pas d'exécution automatique inline — Pass 3 est explicitement déclenché |
| AV2-10 | < 250 nodes/document | ✅ | Pass 3 ne crée pas de nœuds par document — les `CanonicalConcept` et `CanonicalTheme` sont des nœuds corpus-level. Le budget node/document n'est pas impacté |
| NS-4 | Pas de synthèse cross-source | ✅ | Les `CanonicalConcept` sont des **pointeurs de regroupement** (`SAME_AS`), pas des synthèses. Chaque Information conserve son document source unique. La fusion ne crée pas de nouvelle information |
| NS-5 | ClaimKey comme pivot | ⚠️ | Le modèle `Contradiction` est conçu autour du `ClaimKey` comme pivot de comparaison cross-doc. Cependant, le détecteur de contradictions n'est pas encore implémenté |
| NS-10 | Déduplication par fingerprint | ⚠️ | La résolution d'entités par `lex_key` + variantes est une forme de déduplication, mais ne suit pas le mécanisme de fingerprint `hash(claimkey + value.normalized + context_key + span_bucket)` prévu par NS-10. La déduplication actuelle opère au niveau concept, pas au niveau Information |
| AV2-1 | Séparation structure / sémantique | ✅ | Les entités canoniques appartiennent à la couche sémantique. Aucune interaction avec la couche structurelle (Document, Section, DocItem) |
| AV2-8 | Dual storage (Neo4j + Qdrant) | ⚠️ | Pass 3 persiste uniquement dans Neo4j. Pas de mise à jour des embeddings Qdrant pour refléter la fusion de concepts. Les recherches vectorielles retourneront les concepts individuels, pas les canoniques |

### 15.7 Risques — Pass 3

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| R3-1 | **Clustering par `lex_key` uniquement — pas d'embeddings** | 🟡 | Le paramètre `embedding_client` est accepté mais jamais utilisé. Le seuil `SIMILARITY_THRESHOLD = 0.85` est défini mais non exploité. Le clustering repose exclusivement sur le matching lexical (`lex_key` exact + variantes). Les concepts sémantiquement similaires mais lexicalement différents (ex: "SAP S/4HANA" vs "S4H") ne seront pas fusionnés si `lex_key` et variantes diffèrent. | Implémenter la stratégie 3 (cosine similarity sur embeddings) pour compléter les stratégies lexicales. Le paramétrage est déjà en place. |
| R3-2 | **Nom représentatif = premier concept (arbitraire)** | 🟢 | Le nom du `CanonicalConcept` est celui du premier concept du cluster (ordre d'insertion dans la boucle). Pas de sélection heuristique (ex: nom le plus court, le plus fréquent, ou le plus canonique). | Acceptable en MVP. Évolution possible : sélection par fréquence d'apparition ou longueur optimale. |
| R3-3 | **Pas de purge avant retraitement batch** | 🟡 | Contrairement à Pass 2 (`delete_pass2_data()`), Pass 3 n'a pas de mécanisme de suppression des `CanonicalConcept` et `CanonicalTheme` existants avant un retraitement batch. Le `MERGE` sur `canonical_id` prévient les doublons exacts, mais les clusters peuvent évoluer entre deux exécutions, laissant des canoniques obsolètes. | Ajouter une fonction `delete_pass3_data()` pour purger la couche canonique avant retraitement. Critique pour la fiabilité en production. |
| R3-4 | **Clustering de thèmes trop strict (nom exact uniquement)** | 🟡 | Le clustering de thèmes ne repose que sur le matching exact de noms normalisés. Des thèmes sémantiquement identiques mais avec des formulations légèrement différentes (ex: "Architecture Cloud" vs "Cloud Architecture") ne seront pas alignés. | Aligner la stratégie de clustering thèmes sur celle des concepts (variantes + embeddings). |
| R3-5 | **Mode incrémental ne crée jamais de nouveaux canoniques** | 🟡 | Le mode incrémental ne crée pas de `CanonicalConcept` pour les concepts sans match. Ces concepts restent isolés jusqu'au prochain batch. Si le batch n'est jamais exécuté, le graphe canonique sera incomplet. | Le mode batch doit être exécuté périodiquement (cron ou déclenchement après N documents). Documenter cette contrainte opérationnelle. |
| R3-6 | **Persistance relation par relation (pas de batch)** | 🟢 | Le persister itère sur chaque `CanonicalConcept` et chaque `merged_from`, exécutant une transaction par relation `SAME_AS`. Pour un corpus avec beaucoup de concepts fusionnés, cela pourrait être lent. | Optimisation possible via `UNWIND` Cypher. Non critique si Pass 3 est exécuté en batch hors-ligne. |
| R3-7 | **Détecteur de contradictions non implémenté** | 🔴 | Le modèle `Contradiction` est défini (6 natures, 4 niveaux de tension, sérialisation Neo4j) mais aucun composant du pipeline ne l'instancie. La détection de contradictions cross-documents via ClaimKey + Value Contract est un objectif clé du MVP V1 Usage B ("Challenge de Texte") mais n'est pas encore codé. | Implémenter un `ContradictionDetector` qui parcourt les Informations par ClaimKey, compare les Value Contracts normalisés et crée des nœuds `Contradiction` dans Neo4j. Priorité haute pour le MVP. |
| R3-8 | **Pas de validation LLM des cas ambigus** | 🟡 | Le paramètre `llm_client` est injecté dans `EntityResolverV2` mais jamais utilisé pour valider les cas de clustering ambigus. L'ADR prévoit une validation LLM pour les fusions incertaines (confidence entre 0.7 et 0.85). | Implémenter la validation LLM pour les clusters dont la similarité est entre le seuil heuristique et le seuil d'acceptation automatique. |

---

## 16. Orchestration Pipeline

Cette section décrit les mécanismes d'orchestration qui pilotent l'exécution du Pipeline V2, depuis la détection de nouveaux fichiers jusqu'à la finalisation du traitement. L'orchestration est transverse à toutes les passes documentées précédemment.

### 16.1 Séquencement global

Le pipeline V2 suit un séquencement linéaire en 5 étapes principales, piloté par le système de jobs RQ (Redis Queue) :

```
                         ┌─────────────────┐
                         │  POINT D'ENTRÉE │
                         └────────┬────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                             │
              ┌─────┴──────┐              ┌──────┴──────┐
              │ API Upload │              │ Folder      │
              │ (FastAPI)  │              │ Watcher     │
              └─────┬──────┘              └──────┬──────┘
                    │                             │
                    │  POST /ingest               │  on_created / on_moved
                    │                             │  wait_for_file_stability()
                    │                             │  copy → docs_in/
                    └─────────────┬───────────────┘
                                  │
                         ┌────────┴────────┐
                         │   Dispatcher    │
                         │  (dispatcher.py)│
                         └────────┬────────┘
                                  │
                    enqueue_document_v2()
                    enqueue_excel_ingestion()
                                  │
                         ┌────────┴────────┐
                         │   Redis Queue   │
                         │   (RQ Worker)   │
                         └────────┬────────┘
                                  │
                         ┌────────┴────────┐
                         │   jobs_v2.py    │
                         │ ingest_doc_v2   │
                         └────────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
     ┌────────┴────────┐ ┌───────┴────────┐ ┌────────┴────────┐
     │ 1. Extraction   │ │ 2. OSMOSE      │ │ 3. Déduplication│
     │ V2 (Pass 0)     │ │ Agentique      │ │ Auto            │
     │ Docling+Vision  │ │ (Pass 0S-3)    │ │                 │
     └────────┬────────┘ └───────┬────────┘ └────────┬────────┘
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
     ┌────────┴────────┐ ┌───────┴────────┐ ┌────────┴────────┐
     │ 4. Move to      │ │ 5. Notifier    │ │ Rollback si     │
     │ docs_done/      │ │ Historique     │ │ Erreur          │
     └─────────────────┘ └────────────────┘ └─────────────────┘
```

**Détail du séquencement dans `ingest_document_v2_job()` :**

| Étape | Nom | Progression | Détail |
|-------|-----|-------------|--------|
| 0 | Initialisation | 0/5 | Vérification existence fichier, détection type, check mode Burst |
| 1 | Extraction V2 | 1/5 | `_run_extraction_v2()` — ExtractionPipelineV2 (Docling + Vision Gating V4) |
| 2 | OSMOSE Agentique | 2/5 | `_run_osmose_processing()` — OsmoseAgentiqueService (Pass 0S → Pass 3) |
| 3 | Déduplication | 3/5 | `auto_deduplicate_entities()` — KnowledgeGraphService.deduplicate_entities_by_name |
| 4 | Finalisation | 4/5 | `shutil.move()` — Déplacement fichier de `docs_in/` vers `docs_done/` |
| 5 | Complété | 5/5 | Notification historique Redis — statut "completed" |

### 16.2 Folder Watcher

**Fichier :** `src/knowbase/ingestion/folder_watcher.py`
**Classe principale :** `WatchHandler(FileSystemEventHandler)`

Le Folder Watcher est un processus autonome qui surveille le répertoire `/data/watch/` via un `PollingObserver` (watchdog). Il constitue le point d'entrée alternatif à l'upload API.

**Flux détaillé :**

1. **Détection** : `on_created()` ou `on_moved()` déclenché par la présence d'un nouveau fichier
2. **Stabilisation** : `wait_for_file_stability()` — attente de 2 secondes pour s'assurer que le fichier est complètement écrit
3. **Copie** : Le fichier est copié vers `/data/docs_in/` (répertoire d'entrée officiel du pipeline)
4. **Routage** : `enqueue_file()` détermine le type de fichier et appelle la fonction dispatcher appropriée
5. **Job ID** : Génération d'un identifiant unique au format `watch-{filename}-{uuid}`

**Types supportés :**

| Extension | Fonction dispatcher | Job cible |
|-----------|-------------------|-----------|
| `.pdf` | `enqueue_pdf_ingestion()` | `ingest_document_v2_job` |
| `.pptx` | `enqueue_pptx_ingestion()` | `ingest_document_v2_job` |
| `.docx` | `enqueue_document_v2()` | `ingest_document_v2_job` |
| `.xlsx` | `enqueue_excel_ingestion()` | `ingest_excel_job` |

### 16.3 Dispatcher

**Fichier :** `src/knowbase/ingestion/queue/dispatcher.py`
**Statut :** Pipeline V2 unifié — Legacy V1 supprimé (cleanup 2025-01-05)

Le dispatcher est le point central de routage des documents vers les jobs RQ. Depuis le cleanup de janvier 2025, **tous les formats** sont routés vers le pipeline V2 unifié.

#### 16.3.1 Architecture post-cleanup

```
 enqueue_pptx_ingestion() ──┐
                             ├──→ enqueue_document_v2() ──→ jobs_v2.ingest_document_v2_job
 enqueue_pdf_ingestion()  ──┘

 enqueue_excel_ingestion() ──→ jobs_v2.ingest_excel_job  (chemin séparé)
 enqueue_fill_excel()      ──→ jobs_v2.fill_excel_job    (remplissage RFP)
```

**Points clés :**

- **Unification V2** : `enqueue_pptx_ingestion()` et `enqueue_pdf_ingestion()` sont désormais de simples wrappers qui délèguent à `enqueue_document_v2()`. Les paramètres legacy (`meta_path`, `use_vision`) sont acceptés mais ignorés.
- **Excel séparé** : L'ingestion Excel reste sur un chemin dédié (`ingest_excel_job`) car le format Q/A RFP n'est pas encore dans ExtractionPipelineV2.
- **Metadata RQ** : Chaque job est enrichi avec des métadonnées (`job_type`, `pipeline_version`, `document_type`, `source`) via `_register_meta()` pour le suivi.

#### 16.3.2 Configuration RQ

**Fichier :** `src/knowbase/ingestion/queue/connection.py`

| Paramètre | Source | Valeur |
|-----------|--------|--------|
| `REDIS_URL` | Variable d'environnement | `redis://knowbase-redis:6379/0` (par défaut) |
| `DEFAULT_QUEUE_NAME` | Env `INGESTION_QUEUE` ou `"ingestion"` | Queue principale d'ingestion |
| `DEFAULT_JOB_TIMEOUT` | `settings.ingestion_job_timeout` | Configurable |
| `result_ttl` | `DEFAULT_JOB_TIMEOUT` | Même valeur que le timeout |
| `failure_ttl` | `DEFAULT_JOB_TIMEOUT` | Même valeur que le timeout |

#### 16.3.3 Cycle de vie d'un job

```
 ENQUEUED → PROCESSING → [EXTRACTION → OSMOSE → DEDUP → MOVE] → COMPLETED
                    │                                                  │
                    └──────── ERREUR → ROLLBACK → FAILED ──────────────┘
```

**Suivi de progression :**

- `mark_job_as_processing()` — Enregistre le statut "processing" dans l'historique Redis
- `update_job_progress(step, progress, total_steps, message)` — Met à jour les métadonnées du job RQ
- `send_worker_heartbeat()` — Heartbeat périodique avec `worker_id` (hostname:pid) et timestamp

**Gestion d'erreur et rollback :**

En cas d'exception dans `ingest_document_v2_job()` :

1. **Log** de l'erreur
2. **Suppression** des chunks partiels via `delete_import_completely(job.id)`
3. **Notification** historique Redis avec statut "failed" et message d'erreur
4. **Re-raise** de l'exception pour que RQ la marque comme échouée

### 16.4 Modes d'exécution

Le pipeline V2 supporte plusieurs modes d'exécution, principalement pour la **Pass 2** (enrichissement sémantique) qui est la plus coûteuse en temps.

#### 16.4.1 Modes configurables (Pass 2)

**Configuration :** `config/feature_flags.yaml` → `phase_2_hybrid_anchor.pass2_config.mode`

| Mode | Description | Usage typique |
|------|-------------|---------------|
| `inline` | Pass 2 exécutée immédiatement après Pass 1, dans le même job | Mode Burst GPU — latence faible, infrastructure dédiée |
| `background` | Pass 2 enqueued comme job RQ asynchrone séparé | **Mode par défaut** — ne bloque pas l'ingestion principale |
| `scheduled` | Pass 2 exécutée en batch périodique (cron) | Corpus stable — consolidation nocturne |
| `disabled` | Pass 2 non exécutée | Debug/test — extraction only |

**Valeur actuelle :** `"background"` (configuré dans `feature_flags.yaml`)

#### 16.4.2 Phases Pass 2 activables

Chaque phase de Pass 2 peut être activée/désactivée individuellement via `pass2_config.enabled_phases` :

```yaml
enabled_phases:
  - "corpus_promotion"       # Pass 2.0: Promotion unifiée
  - "structural_topics"      # Pass 2a: Topics + HAS_TOPIC + COVERS
  - "classify_fine"          # Pass 2b-1: Classification fine concepts
  - "enrich_relations"       # Pass 2b-2: Extraction relations ADR-compliant
  - "normative_extraction"   # Pass 2c: NormativeRule + SpecFact
  - "semantic_consolidation" # Pass 3: Consolidation sémantique
  - "cross_doc"              # Linking cross-document (Entity Resolution)
```

### 16.5 Feature Flags et configuration

**Fichier YAML :** `config/feature_flags.yaml`
**Module Python :** `src/knowbase/config/feature_flags.py`

#### 16.5.1 Flags principaux du pipeline

| Flag | Section | Valeur | Impact |
|------|---------|--------|--------|
| `extraction_v2.enabled` | Extraction | `true` | Active le pipeline Docling + Vision Gating V4 |
| `stratified_pipeline_v2.enabled` | Pipeline V2 | `true` | Active le pipeline stratifié (lecture top-down) |
| `stratified_pipeline_v2.use_v2_endpoints` | API | `false` | Les endpoints V2 ne sont pas encore les principaux |
| `phase_2_hybrid_anchor.enabled` | Pass 2 | `true` | Active le modèle Hybrid Anchor |
| `phase_2_hybrid_anchor.pass2_mode` | Exécution | `"background"` | Mode d'exécution de Pass 2 |
| `phase_1_8.enable_llm_relation_enrichment` | Relations | `false` | Désactivé — unifié sur Pass 2 ENRICH_RELATIONS |

#### 16.5.2 Gardes de frugalité

```yaml
stratified_pipeline_v2:
  max_concepts_per_document: 15     # Budget concept normal
  max_concepts_hostile: 5           # Budget concept réduit (doc hostile)
  max_relations_per_concept: 3      # Cap relations par concept
  strict_promotion: false           # CONDITIONAL + RARELY promues
  promotion_threshold: 0.7          # Seuil confidence minimum
  consolidation_similarity_threshold: 0.85  # Seuil Pass 3
```

#### 16.5.3 Architecture de déploiement

OSMOSE utilise une architecture **"1 instance = 1 client"** :
- Chaque client a sa propre instance dédiée (Neo4j, Qdrant, Redis)
- Le `tenant_id` reste `"default"` sur chaque instance
- Pas de multi-tenancy logique — isolation totale des données

### 16.6 Burst Mode (EC2 Spot)

**Fichier :** `src/knowbase/ingestion/burst/orchestrator.py`
**Classe principale :** `BurstOrchestrator`

Le mode Burst est un mécanisme d'accélération pour le traitement de gros volumes de documents. Il provisionne dynamiquement une instance EC2 Spot avec GPU pour exécuter les modèles LLM et d'embeddings localement, réduisant les coûts API.

#### 16.6.1 Architecture Burst

```
 ┌─────────────────────────────────────────────────────────┐
 │                    Container Local                       │
 │                                                         │
 │  BurstOrchestrator                                      │
 │  ├── prepare_batch(document_paths)                      │
 │  ├── start_infrastructure()                             │
 │  │     ├── CloudFormation deploy (ou scale-up fleet)    │
 │  │     ├── Wait for instance                            │
 │  │     ├── Wait for services (healthcheck)              │
 │  │     └── Switch providers (LLM + Embeddings)          │
 │  ├── process_batch(callback)                            │
 │  │     ├── Process pending documents                    │
 │  │     ├── Check Spot interruption (toutes 30s)         │
 │  │     └── Handle interruption → resume                 │
 │  └── teardown (scale-down fleet ou delete stack)        │
 │                                                         │
 └──────────────────────┬──────────────────────────────────┘
                        │
                  Provider Switch
                  (activate_burst_providers)
                        │
 ┌──────────────────────┴──────────────────────────────────┐
 │              Instance EC2 Spot (GPU)                     │
 │                                                         │
 │  ┌─────────────────┐  ┌──────────────────────────┐      │
 │  │ vLLM Server     │  │ Embeddings Server         │     │
 │  │ Qwen 2.5 7B    │  │ multilingual-e5-large     │     │
 │  │ Port 8000       │  │ Port 8001                 │     │
 │  └─────────────────┘  └──────────────────────────┘      │
 │                                                         │
 └─────────────────────────────────────────────────────────┘
```

#### 16.6.2 Cycle de vie du Burst

| Phase | Statut | Description |
|-------|--------|-------------|
| Préparation | `PREPARING` | Validation des documents, création de l'état initial |
| Infrastructure | `REQUESTING_SPOT` → `WAITING_CAPACITY` → `INSTANCE_STARTING` | Provisioning EC2 via CloudFormation |
| Services | `INSTANCE_STARTING` | Healthcheck vLLM + Embeddings (polling) |
| Prêt | `READY` | Providers basculés, prêt pour traitement |
| Traitement | `PROCESSING` | Documents traités via callback, monitoring Spot |
| Interruption | `INTERRUPTED` → `RESUMING` | Interruption Spot détectée, reprise automatique |
| Terminé | `COMPLETED` | Providers restaurés, infrastructure teardown |

#### 16.6.3 Gestion des interruptions Spot

Le Burst Orchestrator implémente une résilience complète aux interruptions Spot :

1. **Détection proactive** : `_check_for_spot_interruption()` vérifie le health endpoint toutes les 30 secondes
2. **Arrêt gracieux** : `initiate_graceful_shutdown()` sauvegarde l'état dans `data/burst_state/burst_state_{batch_id}.json`
3. **Reprise automatique** : Le Spot Fleet maintient `TargetCapacity=1`, une nouvelle instance est provisionnée automatiquement
4. **Retry limité** : `max_interruption_retries` contrôle le nombre maximum de tentatives de reprise
5. **État par document** : Chaque document a un statut individuel (`pending`, `processing`, `completed`, `failed`), les documents en cours sont remis en `pending` lors d'une interruption

#### 16.6.4 Optimisations

- **Fast Start** : Réutilisation d'un Spot Fleet existant en veille (capacity=0 → scale up à 1). Réduction du temps de démarrage de ~5-7 min à ~1-2 min
- **Keep Fleet** : Teardown par défaut réduit la capacity à 0 au lieu de supprimer la stack, conservant Security Group, IAM Roles et Fleet pour le prochain batch
- **Dual Logging** : Mode optionnel qui log les résultats via OpenAI ET vLLM pour comparaison de qualité
- **Reconnexion** : `reconnect_to_stack()` permet de reprendre après un redémarrage container

#### 16.6.5 Configuration Burst

**Source :** `BurstConfig.from_env()` (variables d'environnement)

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `vllm_model` | `Qwen/Qwen2.5-7B-Instruct` | Modèle LLM sur EC2 |
| `embeddings_model` | `intfloat/multilingual-e5-large` | Modèle d'embeddings |
| `spot_max_price` | `0.80` | Prix maximum Spot ($/h) |
| `vllm_port` | `8000` | Port du serveur vLLM |
| `embeddings_port` | `8001` | Port du serveur Embeddings |
| `instance_boot_timeout` | Configurable | Timeout attente instance |
| `healthcheck_interval` | Configurable | Intervalle de healthcheck |
| `healthcheck_timeout` | Configurable | Timeout par healthcheck |
| `max_interruption_retries` | Configurable | Max tentatives de reprise |

### 16.7 Jobs spécialisés

Outre le job principal `ingest_document_v2_job`, `jobs_v2.py` expose deux jobs spécialisés :

#### 16.7.1 `ingest_excel_job`

**Usage :** Import de Q/A RFP depuis fichier Excel
**Pipeline :** `excel_pipeline.process_excel_rfp()` — chemin séparé du pipeline V2 unifié
**Particularités :**
- Pas d'ExtractionPipelineV2 (format Q/A structuré)
- Déduplication automatique après import
- Notification historique Redis avec `chunks_inserted`

#### 16.7.2 `fill_excel_job`

**Usage :** Remplissage automatique d'un Excel RFP vide
**Pipeline :** `smart_fill_excel_pipeline.main()` avec callback de progression
**Particularités :**
- Génère un fichier `{stem}_{uid}_filled.xlsx` dans le répertoire de présentations
- Supprime le fichier meta après traitement
- Progression UI via callback (`pipeline_progress_callback`)

### 16.8 Reprocess Batch — Isolation dans le Worker RQ (2026-02-02)

**Fichier job :** `src/knowbase/ingestion/queue/reprocess_job.py` — fonction `reprocess_batch_job()`
**Endpoint API :** `POST /v2/reprocess/start` (dans `src/knowbase/stratified/api/router.py`)
**Worker :** `src/knowbase/ingestion/queue/worker.py` — SimpleWorker écoute les queues `ingestion` + `reprocess`

#### 16.8.1 Problème résolu

Avant le 2026-02-02, le reprocess batch utilisait `FastAPI BackgroundTasks` dans le même process Uvicorn que l'API. Les appels LLM bloquants + Neo4j + Qdrant saturaient les threads, rendant l'API totalement unresponsive pendant 30-120 minutes.

#### 16.8.2 Architecture actuelle

```
POST /v2/reprocess/start
  → Validation + liste des documents depuis cache
  → Initialise l'état dans Redis (clé osmose:v2:reprocess:state)
  → Enqueue dans la queue RQ "reprocess" (job_timeout=7200s)
  → Retourne immédiatement (API libre)

Worker RQ (knowbase-worker, SimpleWorker):
  → Écoute les queues: ["ingestion", "reprocess"]
  → Exécute reprocess_batch_job() séquentiellement
  → Tracking de progression via Redis (cross-container)
```

#### 16.8.3 Job `reprocess_batch_job()`

**Arguments sérialisables (pas d'objets Pydantic) :**

| Argument | Type | Description |
|----------|------|-------------|
| `documents` | `List[dict]` | Liste de dicts `{document_id, cache_path, ...}` |
| `run_pass1` | `bool` | Exécuter Pass 1 |
| `run_pass2` | `bool` | Exécuter Pass 2 |
| `run_pass3` | `bool` | Exécuter Pass 3 (consolidation) |
| `tenant_id` | `str` | Tenant ID |

**Séquence par document :**

1. `LOADING_CACHE` — Charge le Pass0Result depuis le cache d'extraction
2. `PERSIST_PASS0` — Persiste Pass 0 dans Neo4j (Document, Section, DocItem)
3. `LAYER_R_UPSERT` ou `LAYER_R_RECOMPUTE` — Upsert des sub-chunks dans Qdrant (knowbase_chunks_v2)
4. `PASS_1` — Lecture Stratifiée (V2.1 ou V2.2 selon feature flag)
5. `PASS_2` — Enrichissement sémantique (relations inter-concepts)
6. `PASS_3` — Consolidation corpus (si demandé)

**Tracking de progression :**
- Redis clé `osmose:v2:reprocess:state` (TTL 1h)
- Polled par `GET /v2/reprocess/status` (non-bloquant)
- Annulation via `POST /v2/reprocess/cancel` (écrit `status=cancelled` dans Redis, vérifié à chaque document)

**Ce qui ne change pas :** Les endpoints status/cancel lisent/écrivent Redis directement, fonctionnant cross-container sans modification.

### 16.9 Conformité ADR — Orchestration

| # | Axe ADR | Statut | Détail |
|---|---------|--------|--------|
| AV2-5 | Pipeline V2 coexiste avec legacy | ✅ | Le dispatcher a été simplifié : legacy V1 supprimé (cleanup 2025-01-05). Tous les formats passent par V2. |
| AV2-8 | Dual storage (Neo4j + Qdrant) | ✅ | Le job V2 orchestre extraction → OSMOSE Agentique, qui persiste dans les deux stores. |
| AV2-9 | Pass 3 mode manuel + batch | ✅ | Pass 3 n'est pas inline dans le job principal — exécutée via `enabled_phases` en mode background/scheduled. |
| NS-2 | LLM = Extracteur evidence-locked | ⚠️ | Le mode Burst permet d'utiliser un modèle local (Qwen 2.5 7B) potentiellement moins strict que les modèles cloud. La qualité doit être validée. |
| — | Reprocess isolé du process API | ✅ | Le reprocess batch est exécuté dans le worker RQ dédié (queue `reprocess`), libérant l'API. (2026-02-02) |

### 16.10 Risques — Orchestration

| ID | Risque | Sévérité | Description | Mitigation |
|----|--------|----------|-------------|------------|
| RO-1 | **`asyncio.run()` dans job synchrone** | 🟡 | `ingest_document_v2_job` est une fonction synchrone qui appelle `asyncio.run()` deux fois (extraction puis OSMOSE). Si un event loop est déjà actif dans le worker, cela lèvera une `RuntimeError`. | Les workers RQ sont des processus isolés sans event loop pré-existant. Le risque n'existe que si le worker est intégré dans un contexte async (ex: tests pytest-asyncio). |
| RO-2 | **Rollback partiel possible** | 🟡 | `delete_import_completely(job.id)` tente de supprimer les chunks Qdrant mais si le rollback échoue lui-même, des données partielles persistent sans signalement clair (simple `logger.error`). | Monitoring des logs d'erreur de rollback. Un mécanisme de garbage collection périodique pourrait détecter les documents partiels. |
| RO-3 | **Burst Mode — modèle local vs cloud** | 🟡 | Le Qwen 2.5 7B instruct utilisé en mode Burst peut produire des résultats de qualité inférieure aux modèles cloud (GPT-4o, Claude) pour les tâches d'extraction fine (assertions, concepts). | Le mode dual-logging permet la comparaison qualitative. Les gardes de frugalité et la validation verbatim restent actifs quel que soit le modèle. |
| RO-4 | **Spot interruption pendant écriture Neo4j** | 🟡 | Si une interruption Spot survient pendant la persistance Neo4j d'un document, les données peuvent être dans un état incohérent (nœuds créés sans relations, ou inversement). | La reprise remet le document en `pending`. Le retraitement complet crée les nœuds avec `MERGE` (idempotent). Les données orphelines sont tolérées. |
| RO-5 | **Excel pas dans ExtractionPipelineV2** | 🟢 | L'ingestion Excel utilise toujours un pipeline séparé (`excel_pipeline`). Le format Q/A structuré ne bénéficie pas des améliorations Vision/Docling. | Le format Q/A Excel est structuré par nature (colonnes = champs). L'extraction visuelle n'apporte pas de valeur ajoutée. |
| RO-6 | **Watcher sans retry** | 🟢 | Si l'enqueue échoue (Redis indisponible), le watcher ne réessaye pas. Le fichier reste dans `docs_in/` sans être traité. | L'utilisateur peut relancer manuellement via l'API. Le monitoring Docker détecte les services indisponibles. |

---

## 17. Modèle de données complet

Le modèle de données complet Neo4j V2 est documenté dans les sections par phase. Synthèse des types de nœuds :

| Type de nœud | Phase de création | Description | Propriétés clés |
|--------------|------------------|-------------|-----------------|
| `Document` | Pass 0 Structural | Document source | `document_id`, `title`, `doc_hash`, `tenant_id` |
| `Section` | Pass 0 Structural | Section hiérarchique | `section_id`, `heading`, `level`, `path` |
| `DocItem` | Pass 0 Structural | Item atomique Docling | `item_id`, `type`, `text_preview`, `page` |
| `Subject` | Pass 1.1 | Sujet central du document | `subject_id`, `name`, `structure_type` |
| `Theme` | Pass 1.1 | Thème identifié | `theme_id`, `name`, `description` |
| `Concept` | Pass 1.2 | Concept situé frugal | `concept_id`, `name`, `triggers`, `lex_key` |
| `Information` | Pass 1.4 | Assertion promue | `info_id`, `claim`, `exact_quote`, `claimkey_id` |
| `AssertionLog` | Pass 1.4 | Log de décision promotion | `assertion_id`, `status`, `reason` |
| `CanonicalConcept` | Pass 3 | Concept canonique (corpus-level) | `canonical_id`, `name`, `merged_from` |
| `CanonicalTheme` | Pass 3 | Thème canonique (corpus-level) | `canonical_id`, `name` |

**Total types :** 10 (vs 8 prévus par AV2-2 — les 2 supplémentaires sont des superpositions corpus-level).

---

## 18. Synthèse globale des risques

Cette section récapitule **tous les risques** identifiés dans les phases précédentes, consolidés et priorisés par gravité.

### 18.1 Risques critiques (🔴)

| ID | Phase | Risque | Plan d'action |
|----|-------|--------|---------------|
| R13-6 | Pass 1.3 (Extraction assertions) | **Fallback heuristique en production** — Si `allow_fallback=True`, assertions heuristiques (confiance 0.5, types approximatifs) polluent le graphe | Vérifier que `allow_fallback=False` en production. Ajouter un check au démarrage du worker. |
| R3-7 | Pass 3 (Consolidation) | **Détecteur de contradictions non implémenté** — Le modèle Contradiction est défini (6 natures, 4 niveaux) mais aucun composant ne l'instancie. Objectif clé du MVP V1 Usage B. | Implémenter `ContradictionDetector` : parcours Informations par ClaimKey, comparaison Value Contracts normalisés, création nœuds Contradiction. **Priorité haute MVP.** |

### 18.2 Risques modérés (🟡)

| ID | Phase | Risque | Plan d'action |
|----|-------|--------|---------------|
| R0-1 | Pass 0 (Extraction) | Shapes vectoriels non détectés | Phase 2.6 — Fallback VDS à implémenter |
| R0-4 | Pass 0 (Extraction) | Seuils de gating non calibrés | Phase 7 — Calibration sur corpus réel |
| R0-5 | Pass 0 (Extraction) | Table Summarizer — hallucination LLM | Monitoring + validation manuelle des résumés table |
| R0-6 | Pass 0 (Extraction) | DocContext faux positifs résiduels | Principe safe-by-default actif — monitoring |
| R0S-2 | Pass 0 Structural | DocItems très nombreux (>6700 observés) | Lazy persistence activée (~50-200 DocItems en Neo4j) |
| R0S-4 | Pass 0 Structural | Cache v5 — Sections non sérialisées | Re-build complet si sections critiques |
| R0S-6 | Pass 0 Structural | Deux schémas Neo4j coexistants (legacy + V2) | Retrait code legacy après validation V2 |
| R05-1 | Pass 0.5 (Coréférence) | Désactivée en V2 — pronoms non résolus | Refonte coréférence V2 à concevoir |
| R05-2 | Pass 0.5 (Coréférence) | OOM FastCoref sur gros documents | Section batching avec overlap 3K chars |
| R05-3 | Pass 0.5 (Coréférence) | Coreferee obsolète (dernier release 2022) | Swappable via interface ICorefEngine |
| R05-4 | Pass 0.5 (Coréférence) | Offset lookup simpliste (TODO) | Non impactant en V2 (désactivé) |
| R05-6 | Pass 0.5 (Coréférence) | Pas d'intégration avec Pass 1.x | Pipeline V2 gère différemment |
| R09-1 | Pass 0.9 (Global View) | Mode sync = toujours fallback (troncature) | Refactorer vers `build()` async |
| R09-2 | Pass 0.9 (Global View) | Pas de gestion budget tokens | Ajouter tiktoken ou réduire limite chars |
| R09-4 | Pass 0.9 (Global View) | Détection format réponse LLM fragile | Fallback extraction garantit un résumé |
| R09-6 | Pass 0.9 (Global View) | Pas de cache des résumés | Ajouter cache basé sur hash(section_text) |
| R11-1 | Pass 1.1 (Analyse doc) | Preview tronqué à 4000 chars | Compensé par meta-document Pass 0.9 |
| R11-3 | Pass 1.1 (Analyse doc) | Pas de validation croisée structure/contenu | Audit humain via champ justification |
| R11-5 | Pass 1.1 (Analyse doc) | Pas de détection de langue robuste | Risque faible — langues connues |
| R12-1 | Pass 1.2 (Concepts) | Budget étendu [20-40] vs frugalité ADR [5-15] | Croissance sub-linéaire + cap 50 |
| R12-2 | Pass 1.2 (Concepts) | Troncature JSON (LLM Contract) | Détection explicite + Structured Outputs |
| R12-3 | Pass 1.2 (Concepts) | Triggers trop permissifs petits documents | Fallback semi-rare et value patterns |
| R12-4 | Pass 1.2 (Concepts) | Pass 1.2b concepts de faible valeur | Critère C2 + rendement décroissant |
| R13-1 | Pass 1.3 (Assertions) | Reformulation LLM (mode classique) | Mode pointer élimine le risque |
| R13-2 | Pass 1.3 (Assertions) | Coexistence deux modes d'extraction | Convergence progressive vers pointer |
| R13-3 | Pass 1.3 (Assertions) | Seuil lexical Pointer Validator strict | Score value pattern compense |
| R14-1 | Pass 1.4 (Promotion) | ClaimKey Niveau B (LLM) absent | 15 patterns regex couvrent domaines fréquents |
| R14-2 | Pass 1.4 (Promotion) | Coexistence PromotionEngine V2 / PromotionPolicy MVP V1 | Convergence planifiée fin MVP |
| R14-3 | Pass 1.4 (Promotion) | Addressability non stricte (PROMOTED_UNLINKED) | Information-First prime + Pass 1.2b récupère |
| R14-5 | Pass 1.4 (Promotion) | Fingerprint sensible au claimkey_id | Pass 3 = déduplication de second niveau |
| R2-1 | Pass 2 (Relations) | Label générique `CONCEPT_RELATION` | Migration labels dynamiques APOC si besoin |
| R2-2 | Pass 2 (Relations) | Garde-fou à 3 relations arbitraire | Constante ajustable + monitoring filtrage |
| R2-3 | Pass 2 (Relations) | Heuristique de fallback peu fiable | Désactivé par défaut |
| R2-4 | Pass 2 (Relations) | Pas de distinction Scope vs Assertion | Taguer assertion_kind — non bloquant MVP |
| R2-5 | Pass 2 (Relations) | Absence DefensibilityTier / EvidenceBundle | Objectif architectural — MVP fonctionnel |
| R3-1 | Pass 3 (Consolidation) | Clustering par lex_key uniquement — pas d'embeddings | Implémenter cosine similarity (paramétrage en place) |
| R3-3 | Pass 3 (Consolidation) | Pas de purge avant retraitement batch | Ajouter `delete_pass3_data()` — **critique production** |
| R3-4 | Pass 3 (Consolidation) | Clustering thèmes trop strict | Aligner sur stratégie concepts |
| R3-5 | Pass 3 (Consolidation) | Mode incrémental ne crée jamais de canoniques | Exécution batch périodique requise |
| R3-8 | Pass 3 (Consolidation) | Pas de validation LLM cas ambigus | Implémenter validation (paramétrage en place) |
| RO-1 | Orchestration | `asyncio.run()` dans job synchrone | Workers RQ = processus isolés |
| RO-2 | Orchestration | Rollback partiel possible | Monitoring + garbage collection |
| RO-3 | Orchestration | Burst Mode — modèle local vs cloud | Dual-logging + gardes de frugalité |
| RO-4 | Orchestration | Spot interruption pendant écriture Neo4j | MERGE idempotent + retraitement complet |

### 18.3 Risques faibles (🟢)

| ID | Phase | Risque |
|----|-------|--------|
| R0-2 | Pass 0 | Concurrence Vision non bornée — semaphore atténue |
| R0-3 | Pass 0 | Cache version mismatch — invalidation automatique |
| R0-7 | Pass 0 | VisionSemanticReader placeholder — fallback 3-tier |
| R0S-3 | Pass 0 Structural | Chunks NARRATIVE trop longs — seuil 3000 chars configurable |
| R0S-5 | Pass 0 Structural | AssertionUnitIndexer import lazy — log warning émis |
| R0S-7 | Pass 0 Structural | Hash de document non déterministe — versionné v1: |
| R05-5 | Pass 0.5 | Named↔Named gating faux rejets — LLM Arbiter |
| R09-3 | Pass 0.9 | Perte info sections skip — impact mineur |
| R09-5 | Pass 0.9 | Modèle LLM hardcodé — acceptable beta |
| R09-7 | Pass 0.9 | Fourchette taille plus large que ADR — pragmatique |
| R11-2 | Pass 1.1 | Seuil HOSTILE fixe — impact mineur |
| R11-4 | Pass 1.1 | Fallback analyse = données non fiables — RuntimeError en prod |
| R12-5 | Pass 1.2 | Doublons LLM/raffinement — déduplication implémentée |
| R12-6 | Pass 1.2 | Pas de trigger_enricher séparé — fonctionnel en l'état |
| R12-7 | Pass 1.2 | Nettoyage JSON fragile — Structured Outputs élimine |
| R13-4 | Pass 1.3 | Spray & Pray — hard gate + soft gate + cap 5 |
| R13-5 | Pass 1.3 | Troncature texte 2000 chars — détectable |
| R13-7 | Pass 1.3 | Pré-filtres méta-descriptions — patterns EN+FR |
| R14-4 | Pass 1.4 | Theme Lint non implémenté — post-MVP |
| R14-6 | Pass 1.4 | Détection fragments verbes connus — extension multilingue possible |
| R14-7 | Pass 1.4 | Value Extractor limité 5 types — couvre cas fréquents |
| R14-8 | Pass 1.4 | Patterns META YAML — fallback 7 patterns minimal |
| R2-6 | Pass 2 | Pas de déduplication relations — MERGE + purge |
| R2-7 | Pass 2 | Persistance relation par relation — non critique MVP |
| R3-2 | Pass 3 | Nom représentatif arbitraire — acceptable MVP |
| R3-6 | Pass 3 | Persistance relation par relation — UNWIND possible |
| RO-5 | Orchestration | Excel pas dans ExtractionPipelineV2 — Q/A structuré |
| RO-6 | Orchestration | Watcher sans retry — relance manuelle API |

### 18.4 Avertissements architecturaux (⚠️)

| ID | Phase | Risque |
|----|-------|--------|
| R0-8 | Pass 0/0.5 | Pass 0.5 désactivée en mode V2 — décision architecturale consciente |

### 18.5 Statistiques consolidées

| Sévérité | Nombre | Pourcentage |
|----------|--------|-------------|
| 🔴 Critique | 2 | 3% |
| 🟡 Modéré | 35 | 53% |
| 🟢 Faible | 28 | 42% |
| ⚠️ Architectural | 1 | 2% |
| **Total** | **66** | **100%** |

**Top 5 des actions prioritaires :**

1. **🔴 R3-7** — Implémenter le `ContradictionDetector` (MVP V1 Usage B)
2. **🔴 R13-6** — Vérifier `allow_fallback=False` en production (check au démarrage)
3. **🟡 R3-3** — Ajouter `delete_pass3_data()` pour purge avant retraitement (critique production)
4. **🟡 R3-1** — Implémenter le clustering par embeddings (cosine similarity) pour Pass 3
5. **🟡 R05-1** — Concevoir la coréférence V2 pour le pipeline stratifié

---

## 19. Diagramme d'architecture global

```
╔═══════════════════════════════════════════════════════════════════════════════════╗
║                    OSMOSIS Pipeline V2 — Architecture Globale                    ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                 ║
║  POINTS D'ENTRÉE                                                                ║
║  ═══════════════                                                                ║
║  ┌──────────────┐  ┌──────────────┐                                             ║
║  │ API Upload   │  │ Folder       │                                             ║
║  │ (FastAPI)    │  │ Watcher      │                                             ║
║  └──────┬───────┘  └──────┬───────┘                                             ║
║         └────────┬─────────┘                                                    ║
║                  ▼                                                              ║
║  ┌───────────────────────────┐    ┌──────────────────────────────────────┐       ║
║  │ Dispatcher (dispatcher.py)│    │ Redis Queue (RQ)                     │       ║
║  │ enqueue_document_v2()     │───▶│ knowbase queue                       │       ║
║  │ enqueue_excel_ingestion() │    │ DEFAULT_JOB_TIMEOUT configurable     │       ║
║  └───────────────────────────┘    └────────────────┬─────────────────────┘       ║
║                                                    ▼                            ║
║  PIPELINE D'INGESTION (jobs_v2.py — RQ Worker)                                  ║
║  ═════════════════════════════════════════════                                   ║
║                                                                                 ║
║  ┌─ Pass 0 — EXTRACTION ──────────────────────────────────────────────────────┐  ║
║  │                                                                            │  ║
║  │  Docling ──▶ Vision Gating V4 ──▶ GPT-4o Vision ──▶ Merge ──▶ Linearize   │  ║
║  │                   │                                                        │  ║
║  │              Feature Signals                                               │  ║
║  │              (TFS, SDS, VDS, DPS, TVR)                                     │  ║
║  │                                                                            │  ║
║  │  + DocContext Extraction    + Table Summarizer    + Cache Versionné (v5)    │  ║
║  │                                                                            │  ║
║  └──────────────────────────────────┬─────────────────────────────────────────┘  ║
║                                     ▼                                           ║
║  ┌─ Pass 0 Structural ─────────────────────────────────────────────────────┐    ║
║  │  Document ──▶ Section (hiérarchie H1-H6) ──▶ DocItem (atomique)         │    ║
║  │  + TypeAwareChunks ──▶ Qdrant (knowwhere_proto)                         │    ║
║  │  + AssertionUnit Indexer                                                 │    ║
║  └──────────────────────────────────┬───────────────────────────────────────┘    ║
║                                     ▼                                           ║
║  ┌─ Pass 0.9 — GLOBAL VIEW ───────────────────────────────────────────────┐     ║
║  │  Section Summaries (LLM/fallback) ──▶ Meta-Document (15-25K chars)      │    ║
║  │  + TOC enrichie + Section hierarchy + Coverage metrics                   │    ║
║  └──────────────────────────────────┬───────────────────────────────────────┘    ║
║                                     ▼                                           ║
║  ┌─ Pass 1 — LECTURE STRATIFIÉE (Top-Down) ──────────────────────────────────┐  ║
║  │                                                                            │  ║
║  │  Pass 1.1: Document Analysis ──▶ Subject + Themes + Structure Type         │  ║
║  │       │                                                                    │  ║
║  │       ▼                                                                    │  ║
║  │  Pass 1.2: Concept Identification ──▶ 5-50 ConceptSitués frugaux           │  ║
║  │       │         + Pass 1.2b Refinement (itératif)                          │  ║
║  │       ▼                                                                    │  ║
║  │  Pass 1.3: Assertion Extraction ──▶ RawAssertions (verbatim + span)        │  ║
║  │       │         + Mode Pointer (unit → concept → assertion)                │  ║
║  │       │         + Pass 1.3b Anchor Resolution (assertion → DocItem)        │  ║
║  │       ▼                                                                    │  ║
║  │  Pass 1.4: Promotion + Linking ──▶ Information PROMOTED                    │  ║
║  │                + Value Contract + ClaimKey + Fingerprint Dedup              │  ║
║  │                + AssertionLog (PROMOTED | ABSTAINED | REJECTED)             │  ║
║  │                                                                            │  ║
║  └──────────────────────────────────┬─────────────────────────────────────────┘  ║
║                                     ▼                                           ║
║  ┌─ Pass 2 — ENRICHISSEMENT (mode: background | inline | scheduled) ─────────┐  ║
║  │                                                                            │  ║
║  │  2.0: Corpus Promotion      ──▶ ProtoConcept → CanonicalConcept            │  ║
║  │  2a:  Structural Topics     ──▶ HAS_TOPIC + COVERS relations               │  ║
║  │  2b-1: Classification fine  ──▶ Concept types enrichis                     │  ║
║  │  2b-2: Relations ADR        ──▶ CONCEPT_RELATION (segment-first)           │  ║
║  │  2c:  Normative Extraction  ──▶ NormativeRule + SpecFact                   │  ║
║  │                                                                            │  ║
║  └──────────────────────────────────┬─────────────────────────────────────────┘  ║
║                                     ▼                                           ║
║  ┌─ Pass 3 — CONSOLIDATION CORPUS (batch | incrémental) ─────────────────────┐  ║
║  │                                                                            │  ║
║  │  Entity Resolution (lex_key + variantes) ──▶ CanonicalConcept (SAME_AS)    │  ║
║  │  Theme Alignment (nom normalisé)          ──▶ CanonicalTheme (ALIGNED_TO)  │  ║
║  │  [À implémenter: ContradictionDetector via ClaimKey + Value Contract]       │  ║
║  │                                                                            │  ║
║  └────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                 ║
║  STOCKAGE DUAL                                                                  ║
║  ═════════════                                                                  ║
║  ┌────────────────────────┐    ┌────────────────────────────────────────────┐    ║
║  │ Neo4j                  │    │ Qdrant                                     │    ║
║  │ ─────                  │    │ ──────                                     │    ║
║  │ Document, Section,     │    │ Collection: knowwhere_proto                │    ║
║  │ DocItem, Subject,      │    │ TypeAwareChunks (NARRATIVE, TABLE,         │    ║
║  │ Theme, Concept,        │    │ KEY_VALUE, VISUAL, HEADING, LIST)          │    ║
║  │ Information,           │    │ Payload: anchored_concepts, metadata       │    ║
║  │ AssertionLog,          │    │                                            │    ║
║  │ CanonicalConcept,      │    │ Collection: rfp_qa                        │    ║
║  │ CanonicalTheme         │    │ Q/A RFP (pipeline séparé)                 │    ║
║  └────────────────────────┘    └────────────────────────────────────────────┘    ║
║                                                                                 ║
║  MODE BURST (optionnel)                                                         ║
║  ══════════════════════                                                         ║
║  ┌────────────────────────────────────────────────────────────────────────────┐  ║
║  │ EC2 Spot (GPU) — CloudFormation managed                                   │  ║
║  │ vLLM: Qwen 2.5 7B Instruct (:8000) + Embeddings: e5-large (:8001)        │  ║
║  │ Provider switch transparent + Spot interruption resilience                │  ║
║  └────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                 ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
```

---

## 20. Conclusion

### 20.1 Synthèse

Ce document constitue la **documentation technique exhaustive** du Pipeline d'Ingestion V2 d'OSMOSIS, couvrant les 11 passes du pipeline stratifié, de l'extraction brute (Pass 0) à la consolidation corpus (Pass 3), en passant par l'orchestration, le mode Burst et la gestion des jobs.

**Chiffres clés :**

| Métrique | Valeur |
|----------|--------|
| Passes documentées | 11 (Pass 0 → Pass 3, incluant sous-passes) |
| Fichiers source analysés | ~30 modules Python |
| Types de nœuds Neo4j | 10 (vs 8 prévus par ADR — 2 corpus-level ajoutés) |
| Nodes estimés par document | ~195 (vs ~4700 legacy — réduction 96%) |
| Risques identifiés | 66 (2 critiques, 35 modérés, 28 faibles, 1 architectural) |
| ADR de référence | 8 documents normatifs |
| Axes de vérification appliqués | 28+ axes systématiquement vérifiés |

### 20.2 Maturité du pipeline

Le Pipeline V2 est **fonctionnel et opérationnel** pour l'ingestion de documents (PDF, PPTX, DOCX). Les principales réalisations :

- ✅ **Extraction V2** unifiée (Docling + Vision Gating V4) avec cache versionné
- ✅ **Lecture stratifiée** top-down (Document Analysis → Concepts → Assertions → Promotion)
- ✅ **Dual storage** Neo4j + Qdrant opérationnel
- ✅ **Frugalité** : ~195 nodes/doc vs ~4700 legacy
- ✅ **Promotion Policy** avec AssertionLog traçable
- ✅ **Mode Burst** EC2 Spot avec résilience aux interruptions
- ✅ **Pass 2 en mode background** avec phases activables individuellement

### 20.3 Points d'attention prioritaires

1. **Détection de contradictions** (R3-7) — Composant clé du MVP V1 Usage B non implémenté
2. **Coréférence V2** (R05-1) — Pronoms non résolus dans le pipeline V2
3. **Purge Pass 3** (R3-3) — Risque de données obsolètes en production
4. **Clustering sémantique** (R3-1) — Embeddings non utilisés dans la résolution d'entités
5. **ClaimKey Niveau B** (R14-1) — LLM assisté pour couverture ClaimKey étendue

### 20.4 Prochaines étapes

- **MVP V1 Usage B** : Implémenter ContradictionDetector, valider le flux Challenge de Texte
- **Calibration** : Valider les seuils de gating (Phase 7) sur corpus réel client
- **Convergence** : Retirer le code legacy (schéma Neo4j V1, PromotionPolicy V1)
- **Performance** : Batch UNWIND pour persistance Neo4j, cache résumés Pass 0.9
- **Qualité** : Validation LLM pour clustering ambigus (Pass 3), coréférence V2
