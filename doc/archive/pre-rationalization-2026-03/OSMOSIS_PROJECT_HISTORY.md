# OSMOSIS - Histoire du Projet et Pivots Architecturaux

**Version:** 1.0
**Date:** 2026-01-25
**Objectif:** Documenter l'évolution du projet depuis ses origines jusqu'à aujourd'hui

---

## Table des Matières

1. [Vue d'Ensemble](#1-vue-densemble)
2. [Chronologie des Pivots](#2-chronologie-des-pivots)
3. [Évolutions Majeures Détaillées](#3-évolutions-majeures-détaillées)
4. [Architecture Actuelle](#4-architecture-actuelle)
5. [Leçons Apprises](#5-leçons-apprises)
6. [Références](#6-références)

---

## 1. Vue d'Ensemble

### 1.1 Nomenclature

Le projet a connu plusieurs noms au fil de son évolution :

| Période | Nom | Description |
|---------|-----|-------------|
| **2024 (origines)** | **SAP KB / KnowBase** | Base de connaissances RAG pour documentation SAP |
| **Oct 2024 - Oct 2025** | **KnowWhere** | "Le Cortex Documentaire des Organisations" - vision produit élargie |
| **Nov 2025 - présent** | **OSMOSE / OSMOSIS** | **O**rganic **S**emantic **M**emory **O**rganization & **S**mart **E**xtraction |

> **Convention actuelle:**
> - **OSMOSIS** = nom commercial/produit (UI, docs utilisateur)
> - **OSMOSE** = nom de code technique (logs, références internes)

### 1.2 Vision Fondamentale

> **"Les entreprises ne savent plus ce qu'elles savent."**

OSMOSIS résout le problème de la **fragmentation documentaire** en offrant :
- **Intelligence sémantique cross-lingual** (unification FR ↔ EN ↔ DE)
- **Knowledge Graph** avec traçabilité complète (provenance, preuves)
- **Gouvernance des facts** (détection de contradictions, timeline)
- **Différenciation vs Copilot/Gemini** (concept-based vs keyword-based)

---

## 2. Chronologie des Pivots

```
2024                      2025                           2026
──────────────────────────────────────────────────────────────────────────▶

[SAP KB]              [KnowWhere v1]      [OSMOSE]         [Graph-First]
   │                       │                  │                   │
   ▼                       ▼                  ▼                   ▼
┌─────────┐  Oct 2024  ┌─────────┐  Oct 2025  ┌─────────┐  Jan 2026  ┌─────────┐
│ RAG     │──────────▶│ Semantic │──────────▶│ Hybrid  │──────────▶│Structural│
│ Basique │           │  Core   │           │ Anchor  │           │  Graph  │
└─────────┘           └─────────┘           └─────────┘           └─────────┘
    │                      │                     │                     │
    │                      │                     │                     │
  Qdrant           Neo4j Custom           2-Pass Pipeline       Graph-First
   Only            + Facts Gov.          (10min vs 35min)        Runtime
```

### Jalons Clés

| Date | Jalon | Impact |
|------|-------|--------|
| **2024** | Création SAP KB | RAG vectoriel basique avec Qdrant |
| **Oct 2024** | Pivot KnowWhere | Vision "Cortex Documentaire", USP défini |
| **Dec 2024** | ADR Hybrid Anchor Model | Architecture 2 passes, -70% temps traitement |
| **Oct 2025** | Migration Graphiti → Neo4j Native | Facts structurés, détection conflits |
| **Oct 2025** | Phase 1 Semantic Core v2.1 | Cross-lingual extraction, 62 tests |
| **Jan 2026** | ADR Graph-First Architecture | Le graphe route, Qdrant valide |
| **Jan 2026** | Option C - Structural Graph | Structure Docling native vs linéarisation |
| **Jan 2026** | Assertion-aware KG | Evidence Bundles, relations prouvées |

---

## 3. Évolutions Majeures Détaillées

### 3.1 Origine : SAP KB (2024)

**Contexte:** Projet initial de base de connaissances pour documentation SAP.

**Architecture initiale:**
```
Documents (PDF, PPTX)
    ↓
Extraction texte + Chunking (512 tokens)
    ↓
Embeddings (OpenAI)
    ↓
Qdrant (recherche vectorielle)
    ↓
RAG basique (recherche + LLM)
```

**Limitations identifiées:**
- ❌ Pas de compréhension cross-document
- ❌ Pas de détection de contradictions
- ❌ Pas de graph de connaissances structuré
- ❌ Monolingue (anglais principalement)

---

### 3.2 Premier Pivot : KnowWhere (Oct 2024)

**Document de référence:** `doc/phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md`

**Raison du pivot:**
> Les outils existants (SharePoint, Copilot, Gemini) retrouvent des mots, pas le **contexte narratif**. OSMOSE doit comprendre les **concepts**, pas juste les documents.

**Vision produit:**
- **USP #1:** Semantic Concept Intelligence (extraction + unification)
- **USP #2:** Cross-Document Semantic Linking (relations IMPLEMENTS, DEFINES, AUDITS)
- **USP #3:** Semantic Governance (Living Ontology, gatekeeper)

**Use Case KILLER défini:** "Customer Retention Rate Evolution"
- 3 rapports définissent CRR différemment (2022, 2023, 2024)
- KnowWhere détecte l'évolution, avertit des contradictions

**Roadmap 32 semaines établie:**
- Phase 1: Semantic Core (sem 1-10)
- Phase 2: Dual-Graph + Gatekeeper (sem 11-18)
- Phase 3: Living Intelligence (sem 19-26)
- Phase 4: Enterprise Polish (sem 27-32)

---

### 3.3 Migration Graphiti → Neo4j Native (Oct 2025)

**Document de référence:** `doc/archive/DECISION_GRAPHITI_ALTERNATIVES_SYNTHESE.md`

**Problème identifié:**
Graphiti stocke les facts comme **texte dans les relations**, pas comme entités structurées.

```
Architecture Graphiti (incompatible):
Facts = Texte dans edges
"SAP S/4HANA Cloud has an SLA of 99.7%"
         ↓ (stored in edge.fact)

Notre vision (North Star):
Facts = Entités structurées
{subject: "SAP S/4HANA", predicate: "SLA", value: 99.7, unit: "%"}
```

**Impacts bloquants:**
| Fonctionnalité | Avec Graphiti | Avec Neo4j Custom |
|----------------|---------------|-------------------|
| Détection conflits | 500ms + LLM parsing | 50ms (comparaison directe) |
| Timeline temporelle | Complexe | Native (valid_from/until) |
| UI Gouvernance | Texte à parser | Table structurée |

**Décision:**
- ✅ Migrer vers **Neo4j Native + Custom Layer**
- Effort: 10-12 jours
- ROI: < 1 mois (économie LLM + vélocité dev)

**Architecture résultante:** `doc/archive/NORTH_STAR_NEO4J_NATIVE.md`
- Facts = First-class nodes Neo4j
- Détection conflits: CONTRADICTS, OVERRIDES, DUPLICATES, OUTDATED
- Workflow gouvernance: proposed → approved/rejected
- Timeline bi-temporelle: valid_time + transaction_time

---

### 3.4 ADR Hybrid Anchor Model (Déc 2024)

**Document de référence:** `doc/adr/ADR-20241229-hybrid-anchor-model.md`

**Problème critique:**
| Métrique | Valeur avant | Problème |
|----------|--------------|----------|
| Temps par document | **35+ minutes** | Inacceptable |
| Corpus 70 documents | **40+ heures** | Non viable |
| Concept-focused chunks | 11,713 / doc | Explosion combinatoire |
| Chunks génériques | 84 / doc | Ratio 140:1 |

**Cause racine:**
Les **concept-focused chunks** généraient des reformulations LLM pour chaque concept, causant une **duplication sémantique massive**.

**Solution - Architecture 2 Passes:**

```
┌─────────────────────────────────────────────────────────────────┐
│                         PASS 1 - SOCLE                          │
│              (~10 min/doc, système exploitable)                 │
├─────────────────────────────────────────────────────────────────┤
│  EXTRACT ──▶ GATE_CHECK ──▶ RELATIONS ──▶ CHUNK ──▶ ✓          │
│  Résultat : Graphe sain, recherche fonctionnelle               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (configurable: inline/background/scheduled)
┌─────────────────────────────────────────────────────────────────┐
│                     PASS 2 - ENRICHISSEMENT                     │
│                    (Non bloquant, optionnel)                    │
├─────────────────────────────────────────────────────────────────┤
│  CLASSIFY_FINE ──▶ ENRICH_RELATIONS ──▶ CROSS_DOC               │
└─────────────────────────────────────────────────────────────────┘
```

**6 Invariants Non-Négociables établis:**
1. Aucun concept sans anchor (traçabilité)
2. Aucun texte indexé généré par LLM (pas d'hallucinations)
3. Chunking indépendant des concepts (volumétrie prévisible)
4. Neo4j = Vérité, Qdrant = Projection
5. Pass 1 toujours exploitable (pas de dépendance cachée)
6. Payload Qdrant minimal (concept_id, label, role, span, chunk_id)

**Résultats:**
| Métrique | Avant | Après | Amélioration |
|----------|-------|-------|--------------|
| Temps Pass 1 | 35+ min | ~10 min | **-70%** |
| Chunks / doc | 11,797 | ~180 | **-98%** |
| Batches embeddings | 2,950 | ~45 | **-98%** |

---

### 3.5 Phase 1 Semantic Core v2.1 (Oct-Nov 2025)

**Document de référence:** `doc/phases/PHASE1_SEMANTIC_CORE.md`

**Objectif:**
> Démontrer que OSMOSE extrait et unifie concepts multilingues mieux que Copilot/Gemini.

**Changement architectural:**
```
AVANT (Narrative Approach):
❌ Keywords hardcodés monolingues (anglais only)
❌ Non-scalable pour environnements multilingues

APRÈS (Concept-First, Language-Agnostic):
✅ Extraction concepts multilingues automatique
✅ Cross-lingual unification (FR ↔ EN ↔ DE)
✅ Pipeline simplifié (4 étapes vs 6+)
```

**Pipeline v2.1:**
```
Document
   ↓
TopicSegmenter       → Segmentation sémantique (windowing + clustering)
   ↓
ConceptExtractor     → Triple méthode (NER + Clustering + LLM)
   ↓
SemanticIndexer      → Canonicalisation cross-lingual (threshold 0.85)
   ↓
ConceptLinker        → Linking cross-documents + DocumentRole
   ↓
Proto-KG (Neo4j + Qdrant)
```

**Composants livrés:**

| Composant | Lignes | Tests | Description |
|-----------|--------|-------|-------------|
| TopicSegmenter | 650 | 9 | Segmentation sémantique |
| ConceptExtractor | 750 | 15 | NER + Clustering + LLM |
| SemanticIndexer | 600 | 15 | Cross-lingual canonicalization |
| ConceptLinker | 450 | 12 | DocumentRole (DEFINES, IMPLEMENTS...) |
| Pipeline E2E | 300 | 11 | Orchestration complète |
| **Total** | **~4500** | **62** | |

**USP prouvé:**
- ✅ FR "authentification" = EN "authentication" = DE "Authentifizierung"
- ✅ Language-agnostic knowledge graph
- ✅ Pas de hardcoded keywords

---

### 3.6 ADR Graph-First Architecture (Jan 2026)

**Document de référence:** `doc/adr/ADR-20260106-graph-first-architecture.md`

**Bug déclencheur:** "Semantic Anchoring Bug"
```
Question: "Quel est le processus de transformation d'une proposition
           commerciale en contrat exécutable ?"

Attendu:   Concepts Solution Quotation Management ↔ Service Contract Execution
Obtenu:    Concepts Digital Transformation, AI-assisted Cloud Transformation
```

**Cause:** Le mot "transformation" dans la question a biaisé la recherche vectorielle vers des concepts sémantiquement proches du **mot**, pas du **sens**.

**Paradigme actuel vs cible:**

```
AVANT (Retrieval-First):
Question → Embedding → Qdrant (chunks) → Top-K → PUIS Graph Context → Synthèse

APRÈS (Graph-First):
Question → Concept Seeds → Graph Paths → Evidence Plan → Qdrant (filtrée) → Synthèse
```

**Principe non-négociable:**
> **Le KG devient le routeur, Qdrant devient la source de preuves.**

**Trois modes de réponse:**

| Mode | Condition | Audit |
|------|-----------|-------|
| **Reasoned** | Chemin sémantique trouvé dans KG | Chemin + preuves par arête |
| **Anchored** | Pas de chemin, mais ancrage structurel | Scope + citations |
| **Text-only** | Rien dans le KG | Citations + mention "pas de support KG" |

---

### 3.7 Option C - Structural Graph from Docling (Jan 2026)

**Document de référence:** `doc/adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md`

**Problème identifié:**
1. **Docling extrait une structure riche** (types, hiérarchie, provenance)
2. **Le Linearizer aplatit cette structure** en texte avec marqueurs
3. **Nous essayons de réinférer la structure** via heuristiques fragiles
4. **Cette approche est fondamentalement instable**

**Diagnostic empirique:**
- 90% des sections classées HIGH/MEDIUM (le filtre ne filtre pas)
- Réduction candidats de seulement 21.3% (attendu >70%)

**Axiome central:**
> **La structure du document doit être consommée sous forme structurée (DoclingDocument), jamais inférée depuis une linéarisation.**

**Solution - Structural Graph:**

```
DoclingDocument (structure riche)
  → DocItem nodes (Neo4j) + PageContext + SectionContext enrichi
  → Type-aware Chunks (NARRATIVE/TABLE/FIGURE)
  → Evidence-first Relation Engine
```

**Nouveau modèle de données:**

```cypher
// Hiérarchie document
(DocumentContext)-[:HAS_VERSION]->(DocumentVersion)-[:HAS_PAGE]->(PageContext)
(DocumentVersion)-[:HAS_SECTION]->(SectionContext)
(SectionContext)-[:CONTAINS]->(DocItem)

// DocItem = élément atomique avec provenance
(:DocItem {
  item_id,           // = Docling self_ref
  item_type,         // TEXT, HEADING, TABLE, FIGURE, LIST_ITEM...
  text,
  page_no,
  bbox_x0, bbox_y0, bbox_x1, bbox_y1,
  reading_order_index
})

// Chunking type-aware
(Chunk)-[:DERIVED_FROM]->(DocItem)
```

**Conséquences positives:**
1. Robustesse (plus de dépendance aux markers textuels)
2. Précision (`item_type=TABLE` est une vérité, pas une inférence)
3. Traçabilité (provenance complète: page, bbox, item_ids)
4. Moins de coût LLM (tables/figures ne passent pas par relation extraction)
5. Auditabilité ("Montre-moi où c'est écrit" = trivial)

---

### 3.8 Consolidation ADR (Jan 2026)

**Document de référence:** `doc/adr/CONSOLIDATED_ADR_OSMOSE.md`

Les ADRs suivants ont été consolidés pour former l'architecture actuelle:

1. **Option C - Structural Graph** : DoclingDocument → DocItem nodes
2. **Coverage is a Property** : Anchors pointent vers DocItem, pas vers chunks
3. **Dual Chunking Architecture** : DocItem (coverage) + TypeAwareChunk (retrieval)
4. **Unified Corpus Promotion** : Single-stage promotion (Pass 2.0)
5. **Corpus-Aware Lex-Key Normalization** : `compute_lex_key()` pour matching
6. **Structural Context Alignment** : `context_id` structurel sur ProtoConcept
7. **Coref Named↔Named Validation** : Gating + LLM + Cache
8. **Multi-Span Evidence Bundles** : Preuves fragmentées cross-section

---

## 4. Architecture Actuelle

### 4.1 Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OSMOSE Architecture 2026                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Documents (PDF, PPTX, DOCX)                                                │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────┐                                                            │
│  │   Docling   │  → Structure riche (DoclingDocument)                       │
│  └─────────────┘                                                            │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PASS 0 - STRUCTURAL GRAPH                    │        │
│  │  DocItem nodes + PageContext + SectionContext + structural_profile      │
│  └─────────────────────────────────────────────────────────────────┘        │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PASS 0.5 - LINGUISTIC LAYER                  │        │
│  │  FastCoref + Named↔Named Gating (LLM validation si risque)      │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PASS 1 - CONCEPT EXTRACTION                  │        │
│  │  ProtoConcept avec lex_key, context_id, anchor_status           │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PASS 2.0 - UNIFIED PROMOTION                 │        │
│  │  CanonicalConcept + INSTANCE_OF + MENTIONED_IN                  │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│        │                                                                    │
│        ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PASS 3 - RELATION EXTRACTION                 │        │
│  │  Intra-section, Evidence Bundles pour cross-section             │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│        │                                                                    │
│        ▼                                                                    │
│  ┌──────────────────┐     ┌──────────────────┐                              │
│  │      Neo4j       │     │      Qdrant      │                              │
│  │  (Source de      │     │  (Projection     │                              │
│  │   vérité)        │     │   retrieval)     │                              │
│  └──────────────────┘     └──────────────────┘                              │
│             │                      │                                        │
│             └───────────┬──────────┘                                        │
│                         │                                                   │
│                         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    GRAPH-FIRST RUNTIME                          │        │
│  │  Question → Seeds → Graph Paths → Evidence Plan → Qdrant Filter │        │
│  │  Modes: REASONED | ANCHORED | TEXT-ONLY                         │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Schéma Neo4j

```cypher
// Structural Layer (Option C)
(:DocumentContext {doc_id, tenant_id, title})
(:DocumentVersion {doc_id, doc_version_id, is_current})
(:PageContext {page_no, doc_version_id, page_width, page_height})
(:SectionContext {context_id, section_path, structural_profile})
(:DocItem {item_id, item_type, text, reading_order_index, charspan})

// Semantic Layer
(:ProtoConcept {concept_id, concept_name, lex_key, anchor_status, context_id})
(:CanonicalConcept {canonical_id, label, lex_key, type_bucket, stability})

// Relations
(:DocItem)-[:ON_PAGE]->(:PageContext)
(:SectionContext)-[:CONTAINS]->(:DocItem)
(:ProtoConcept)-[:ANCHORED_IN]->(:DocItem)
(:ProtoConcept)-[:INSTANCE_OF]->(:CanonicalConcept)
(:CanonicalConcept)-[:MENTIONED_IN]->(:SectionContext)
```

---

## 5. Leçons Apprises

### 5.1 Principes Architecturaux Validés

| Principe | Illustration |
|----------|--------------|
| **Structure > Inférence** | DocItem nodes vs parsing de markers textuels |
| **Graph-First > Retrieval-First** | Le KG route, Qdrant valide |
| **Preuves > Assertions** | Toute relation doit avoir evidence_ids |
| **Pass 1 standalone** | Système exploitable sans enrichissement |
| **Agnostic domaine** | POS-based, pas de whitelists métier |

### 5.2 Anti-Patterns Évités

1. **Concept-focused chunks** → Explosion combinatoire, abandonné
2. **Graphiti pour Facts** → Texte dans edges, migré vers Neo4j native
3. **Linéarisation comme source** → Structure perdue, remplacé par DocItem
4. **Retrieval-first RAG** → Biais vectoriel, remplacé par Graph-First

### 5.3 Décisions Techniques Clés

| Décision | Raison | Impact |
|----------|--------|--------|
| Neo4j = vérité, Qdrant = projection | Source unique, pas de désynchronisation | Cohérence garantie |
| Anchors obligatoires | Pas de concept sans preuve textuelle | KG sain, auditabilité |
| Lex-key normalization | Matching cross-doc fiable | Unification cross-lingual |
| context_id structurel | Lien SectionContext ↔ ProtoConcept | Pas d'explosion MENTIONED_IN |
| Evidence Bundles | Preuves fragmentées acceptées | Relations cross-section possibles |

---

## 6. Références

### Documents Fondateurs
- `doc/phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md` - Vision produit
- `doc/archive/NORTH_STAR_NEO4J_NATIVE.md` - Architecture RAG Hybride
- `doc/phases/PHASE1_SEMANTIC_CORE.md` - Phase 1 complète

### ADRs Chronologiques
- `doc/adr/ADR-20241229-hybrid-anchor-model.md` - Architecture 2 passes
- `doc/adr/ADR-20241230-option-a-prime-chunk-aligned-relations.md` - Relations Pass 2
- `doc/adr/ADR-20241230-reducto-parsing-primitives.md` - Parsing primitives
- `doc/adr/ADR-20250105-marker-normalization-layer.md` - Normalisation markers
- `doc/adr/ADR-20260101-document-structural-awareness.md` - Structural awareness
- `doc/adr/ADR-20260101-navigation-layer.md` - Contextual Navigation Graph
- `doc/adr/ADR-20260104-assertion-aware-kg.md` - Assertion-aware KG
- `doc/adr/ADR-20260106-graph-first-architecture.md` - Graph-First Architecture
- `doc/adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` - Option C Structural Graph
- `doc/adr/CONSOLIDATED_ADR_OSMOSE.md` - Consolidation ADRs 2026

### Archives
- `doc/archive/DECISION_GRAPHITI_ALTERNATIVES_SYNTHESE.md` - Migration Graphiti
- `doc/archive/GRAPHITI_ALTERNATIVES_ANALYSIS_RESULTS.md` - Analyse alternatives

---

## Changelog

| Date | Version | Changements |
|------|---------|-------------|
| 2026-01-25 | 1.0 | Création initiale - Synthèse historique complète |

---

*Document généré pour OSMOSIS - Organic Semantic Memory Organization & Smart Extraction*
