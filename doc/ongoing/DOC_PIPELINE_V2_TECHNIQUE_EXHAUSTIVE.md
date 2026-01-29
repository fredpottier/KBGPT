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

<!-- À compléter : analyse détaillée du code extraction_v2/ -->

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
