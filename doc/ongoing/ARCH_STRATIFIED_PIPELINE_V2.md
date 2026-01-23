# Architecture du Pipeline Stratifié V2

**Statut**: EN CONCEPTION
**Date**: 2026-01-23
**Branche**: `pivot/stratified-pipeline-v2`
**Réf**: ADR-20260123-stratified-reading-poc-validation.md
**Review**: ChatGPT 2026-01-23 (corrections intégrées)

---

## Contexte et Motivation

### Problème du Pipeline Legacy

| Métrique | Legacy | Cible V2 |
|----------|--------|----------|
| Nodes/document | ~4700 | < 100 |
| Types de nodes | ~15+ | ~6 |
| Passes d'enrichissement | 4 (complexes) | 2-3 (ciblés) |
| Temps traitement | 35+ min | < 10 min |

### Explosion des Nodes Legacy

```
Legacy (19 docs = 90K+ nodes):
├── ProtoConcept (milliers)
├── CanonicalConcept (centaines)
├── RawAssertion (dizaines de milliers)
├── Claim (milliers)
├── Relation (milliers)
├── DocumentContext (dizaines)
├── SectionContext (centaines)
├── WindowContext (milliers)
├── Topic (centaines)
├── NormativeRule (centaines)
├── SpecFact (centaines)
└── ... autres nodes de navigation
```

### Principes du Pipeline V2

1. **Frugalité** : Moins de nodes, plus de valeur par node
2. **Top-Down** : Structure → Concepts → Informations (validé par POC)
3. **Promotion Policy** : Seules les assertions défendables deviennent Information
4. **Overlay** : Information = pointeur vers source, pas copie
5. **Indépendance** : Pipeline V2 coexiste avec legacy jusqu'à validation

---

## Architecture Cible

### Principe Fondamental : Séparation Structure Documentaire / Structure Sémantique

**IMPORTANT** (feedback ChatGPT) : Ne pas confondre :
- **Structure documentaire** (DocItem, Section) = où c'est écrit, preuve, audit
- **Structure sémantique** (Subject, Theme, Concept) = ce que le lecteur comprend

Les deux sont nécessaires. L'Information doit être ancrée sur **DocItem** (preuve), pas sur des chunks retrieval.

### Hiérarchie V2 (8 types de nodes)

```
┌─────────────────────────────────────────────────────────────────┐
│                    STRUCTURE DOCUMENTAIRE                       │
│                    (Preuve, Audit, Localisation)                │
├─────────────────────────────────────────────────────────────────┤
│  Document (1)                                                   │
│      │                                                          │
│      ├── Section (5-20) ─── structure documentaire              │
│      │                                                          │
│      └── DocItem (50-200) ─── unités atomiques de preuve        │
│              │                                                  │
│              └── [TypeAwareChunk dans Qdrant = projection]      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ ANCHORED_IN
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    STRUCTURE SÉMANTIQUE                         │
│                    (Compréhension, Navigation)                  │
├─────────────────────────────────────────────────────────────────┤
│  Subject (1 par document)                                       │
│      │                                                          │
│      └── Theme (3-7) ─── axes thématiques                       │
│              │                                                  │
│              └── Concept (5-15) ─── entités clés                │
│                      │                                          │
│                      └── Information ─── assertions promues     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ LOGGED_IN
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    JOURNAL D'AUDIT                              │
│                    (Traçabilité, Gouvernance)                   │
├─────────────────────────────────────────────────────────────────┤
│  AssertionLog ─── toutes assertions candidates                  │
│      status: PROMOTED | ABSTAINED | REJECTED                    │
│      reason: (pourquoi promue/rejetée)                          │
└─────────────────────────────────────────────────────────────────┘
```

### Estimation Nodes V2 (révisée)

| Type | Par document | 19 docs | Rôle |
|------|--------------|---------|------|
| Document | 1 | 19 | Artefact, metadata, provenance |
| Section | ~10 | ~190 | Structure documentaire |
| DocItem | ~100 | ~1900 | Unités atomiques de preuve |
| Subject | 1 | 19 | Résumé sémantique |
| Theme | ~5 | ~95 | Axes thématiques |
| Concept | ~12 | ~230 | Entités clés frugales |
| Information | ~15 | ~285 | Assertions promues |
| AssertionLog | ~50 | ~950 | Journal audit (optionnel en prod) |
| **TOTAL** | **~195** | **~3700** | **~4% du legacy** |

> **Note** : Même avec DocItem + AssertionLog, on reste à ~4% du legacy (vs 1% sans).
> Le gain principal vient de la suppression de ProtoConcept, RawAssertion massif, WindowContext.

---

## Passes du Pipeline V2

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                      PASS 0 : EXTRACTION                        │
│  (Docling + Vision Gating - INCHANGÉ)                          │
│  Output: Chunks textuels + métadonnées                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PASS 1 : LECTURE STRATIFIÉE                   │
│  (POC validé - SemanticAssertionExtractor)                     │
│                                                                 │
│  1.1 Document Analysis    → Structure (CENTRAL/TRANS/CONTEXT)  │
│  1.2 Concept Identification → Concepts frugaux (5-15)          │
│  1.3 Assertion Extraction → Assertions typées + Promotion      │
│  1.4 Semantic Linking     → Information rattachées             │
│                                                                 │
│  Output: Subject, Themes, Concepts, Informations               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PASS 2 : ENRICHISSEMENT                       │
│  (Simplifié - uniquement ce qui ajoute de la valeur)           │
│                                                                 │
│  2.1 Relation Extraction  → Relations inter-concepts           │
│  2.2 Classification Fine  → Rôles sémantiques (optionnel)      │
│                                                                 │
│  Output: Relations enrichies                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PASS 3 : CONSOLIDATION CORPUS                 │
│  (Cross-document uniquement)                                    │
│                                                                 │
│  3.1 Entity Resolution    → Merge concepts similaires          │
│  3.2 Theme Alignment      → Harmonisation thèmes cross-doc     │
│                                                                 │
│  Output: Graphe consolidé                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Détail des Passes

### PASS 0 : Extraction + Structural Graph (MODIFIÉ)

Le pipeline d'extraction Docling + Vision Gating **crée maintenant le graphe structurel**.

**Input**: Document (PDF, PPTX, DOCX)
**Output**:
- **Document** node (metadata, hash, dates, langue, source)
- **Section** nodes (structure documentaire : headings, chapitres)
- **DocItem** nodes (unités atomiques : paragraphes, tables, listes)
- TypeAwareChunks → Qdrant (projection retrieval, dérivés de DocItem)

**Nodes créés en Pass 0**:

| Node | Quantité | Propriétés |
|------|----------|------------|
| Document | 1 | `doc_id`, `title`, `hash`, `source_url`, `language`, `created_at` |
| Section | 5-20 | `title`, `level`, `path`, `doc_id`, `order` |
| DocItem | 50-200 | `type` (paragraph/table/list/heading), `text`, `page`, `char_start`, `char_end`, `section_id` |

**Relations créées**:
- `(Document)-[:HAS_SECTION]->(Section)`
- `(Section)-[:CONTAINS_ITEM]->(DocItem)`
- `(Section)-[:PARENT_OF]->(Section)` (hiérarchie)

**Qdrant** (projection retrieval):
- TypeAwareChunks avec `docitem_id` pour mapping inverse
- `(TypeAwareChunk)-[DERIVED_FROM]->(DocItem)` (logique, pas persisté)

---

### PASS 1 : Lecture Stratifiée (NOUVEAU - POC validé)

#### 1.1 Document Analysis

**Objectif**: Déterminer la structure dominante du document.

**Input**: Tous les chunks du document
**Output**:
```python
{
  "structure": "CENTRAL" | "TRANSVERSAL" | "CONTEXTUAL",
  "justification": str,
  "subject": str,  # Résumé en 1 phrase
  "language": "fr" | "en" | "de"
}
```

**Garde-fou HOSTILE**: Si > 10 sujets distincts détectés → REJECT

#### 1.2 Concept Identification

**Objectif**: Identifier les concepts clés (5-15 max).

**Input**: Chunks + structure
**Output**:
```python
{
  "themes": [
    {"name": str, "children": [concept_names]}
  ],
  "concepts": [
    {
      "id": uuid,
      "name": str,
      "role": "CENTRAL" | "STANDARD" | "CONTEXTUAL",
      "theme_ref": str,
      "variants": [str]  # Traductions, synonymes
    }
  ],
  "refused_terms": [{"term": str, "reason": str}]
}
```

**Garde-fous**:
- Max 15 concepts (frugalité)
- Refus des termes génériques
- Refus des mentions uniques

#### 1.3 Assertion Extraction

**Objectif**: Extraire les assertions du document avec leur type.

**Input**: Chunks
**Output**:
```python
{
  "assertions": [
    {
      "id": uuid,
      "text": str,
      "type": "DEFINITIONAL" | "PRESCRIPTIVE" | "CAUSAL" |
              "FACTUAL" | "CONDITIONAL" | "PERMISSIVE" |
              "COMPARATIVE" | "PROCEDURAL",
      "confidence": float,
      "chunk_id": str,
      "span": {"start": int, "end": int}
    }
  ]
}
```

#### 1.4 Semantic Linking + Promotion + Journal

**Objectif**: Lier les assertions aux concepts, filtrer selon la Promotion Policy, ET journaliser toutes les décisions.

**Promotion Policy** (rappel):
| Type | Tier | Comportement |
|------|------|--------------|
| DEFINITIONAL | ALWAYS | Toujours → Information |
| PRESCRIPTIVE | ALWAYS | Toujours → Information |
| CAUSAL | ALWAYS | Toujours → Information |
| FACTUAL | CONDITIONAL | Si confiance ≥ 0.7 |
| CONDITIONAL | CONDITIONAL | Si confiance ≥ 0.7 |
| PERMISSIVE | CONDITIONAL | Si confiance ≥ 0.7 |
| COMPARATIVE | RARELY | Si confiance ≥ 0.9 |
| PROCEDURAL | NEVER | Jamais |

**Output**:
```python
{
  "informations": [
    {
      "id": uuid,
      "concept_id": uuid,
      "text": str,
      "type": str,
      "anchor": {
        "docitem_id": str,    # ANCRAGE SUR DOCITEM, PAS CHUNK
        "span_start": int,
        "span_end": int
      }
    }
  ],
  "assertion_log": [
    {
      "id": uuid,
      "text": str,
      "type": str,
      "status": "PROMOTED" | "ABSTAINED" | "REJECTED",
      "reason": str,          # Ex: "confiance 0.5 < seuil 0.7"
      "concept_id": uuid | null,
      "docitem_id": str
    }
  ]
}
```

#### Nodes créés en Pass 1

| Node | Quantité | Propriétés clés |
|------|----------|-----------------|
| Subject | 1 | text, structure, language, doc_id |
| Theme | 3-7 | name, subject_id |
| Concept | 5-15 | name, role, theme_id, variants |
| Information | 5-30 | text, type, concept_id |
| AssertionLog | ~50 | text, type, status, reason, concept_id, docitem_id |

**Relations créées**:
- `(Document)-[:HAS_SUBJECT]->(Subject)`
- `(Subject)-[:HAS_THEME]->(Theme)`
- `(Theme)-[:HAS_CONCEPT]->(Concept)`
- `(Concept)-[:HAS_INFORMATION]->(Information)`
- `(Information)-[:ANCHORED_IN]->(DocItem)` avec span_start/span_end
- `(AssertionLog)-[:LOGGED_FOR]->(Document)` (audit trail)

---

### PASS 2 : Enrichissement (SIMPLIFIÉ)

#### 2.1 Relation Extraction

**Objectif**: Extraire les relations sémantiques entre concepts.

**Input**: Concepts + chunks contextuels
**Output**:
```python
{
  "relations": [
    {
      "source_concept_id": uuid,
      "target_concept_id": uuid,
      "type": "REQUIRES" | "ENABLES" | "CONSTRAINS" |
              "IMPLEMENTS" | "EXTENDS" | "CONTRADICTS",
      "evidence": str,  # Citation source
      "chunk_id": str
    }
  ]
}
```

**Garde-fou**: Max 3 relations par concept (éviter explosion)

#### 2.2 Classification Fine (OPTIONNEL)

**Objectif**: Enrichir les rôles sémantiques des concepts.

Seulement si valeur ajoutée détectée (ex: domaine réglementaire).

#### Nodes créés en Pass 2

| Node | Quantité | Propriétés |
|------|----------|------------|
| (aucun nouveau node) | - | - |

**Relations créées**:
- `(Concept)-[:RELATION {type, evidence}]->(Concept)`

---

### PASS 3 : Consolidation Corpus (CROSS-DOC)

#### 3.1 Entity Resolution

**Objectif**: Fusionner les concepts identiques cross-documents.

**Algorithme**:
1. Embedding des noms de concepts + variants
2. Clustering par similarité (seuil: 0.85)
3. Validation LLM pour les cas ambigus
4. Création de `CanonicalConcept` comme point de fusion

#### 3.2 Theme Alignment

**Objectif**: Harmoniser les thèmes similaires cross-documents.

**Algorithme**:
1. Embedding des noms de thèmes
2. Clustering
3. Création de `CanonicalTheme` si convergence

#### Nodes créés en Pass 3

| Node | Quantité | Propriétés |
|------|----------|------------|
| CanonicalConcept | ~20% des concepts | name, merged_from[] |
| CanonicalTheme | ~30% des thèmes | name, merged_from[] |

**Relations créées**:
- `(Concept)-[:SAME_AS]->(CanonicalConcept)`
- `(Theme)-[:ALIGNED_TO]->(CanonicalTheme)`

---

## Comparaison Legacy vs V2

### Décisions par Node Legacy (Review ChatGPT)

| Node Legacy | Décision | Justification |
|-------------|----------|---------------|
| **ProtoConcept** | ✅ SUPPRIMÉ | Étape intermédiaire inutile. Pass 1 identifie directement 5-15 concepts pertinents. Candidats en mémoire transitoire, pas persistés. |
| **RawAssertion** | ⚠️ REMPLACÉ | **Ne pas supprimer le journal !** Remplacé par `AssertionLog` minimal avec status (PROMOTED/ABSTAINED/REJECTED) + raison. Essentiel pour audit, debug, contradictions. |
| **Claim** | ✅ SUPPRIMÉ | Redondant si AssertionLog existe. Information = assertion promue. |
| **WindowContext** | ✅ SUPPRIMÉ | Explosion combinatoire sans valeur. L'ancrage DocItem + span suffit. |
| **SectionContext** | ⚠️ CONSERVÉ | **Ne pas supprimer !** Renommé `Section`. Structure documentaire ≠ structure sémantique. Nécessaire pour localisation, audit, navigation. |
| **DocumentContext** | ⚠️ FUSIONNÉ | Fusionné dans `Document` (metadata + provenance + hash). Subject = résumé sémantique séparé. |
| **NormativeRule** | ✅ FUSIONNÉ | Devient Information avec `type=PRESCRIPTIVE`. |
| **SpecFact** | ✅ FUSIONNÉ | Devient Information avec `type=FACTUAL`. |
| **Topic** | ✅ REMPLACÉ | Remplacé par `Theme` (lecture stratifiée > clustering). Theme doit être relié à la structure documentaire. |

### Mapping conceptuel (révisé)

```
Legacy                          V2
──────                          ──
DocumentContext     ────────>   Document (metadata fusionnées)
                    ────────>   Subject (résumé sémantique séparé)
SectionContext      ────────>   Section (CONSERVÉ, renommé)
Topic               ────────>   Theme (lecture stratifiée)
ProtoConcept        ────────>   (supprimé, transitoire en mémoire)
CanonicalConcept    ────────>   Concept (direct)
RawAssertion        ────────>   AssertionLog (minimal, audit)
Claim               ────────>   Information (promue)
NormativeRule       ────────>   Information (type=PRESCRIPTIVE)
SpecFact            ────────>   Information (type=FACTUAL)
WindowContext       ────────>   (supprimé)
```

### Invariant Critique : Ancrage sur DocItem

**JAMAIS** ancrer Information/Concept sur des chunks retrieval.

```
✅ CORRECT:   (Information)-[:ANCHORED_IN]->(DocItem) + span
❌ INCORRECT: (Information)-[:ANCHORED_IN]->(Chunk)
```

Les chunks Qdrant sont des **projections retrieval** dérivées de DocItem, pas des surfaces de preuve.

---

## Implémentation

### Structure du code

```
src/knowbase/
├── stratified/                    # NOUVEAU - Pipeline V2
│   ├── __init__.py
│   ├── pipeline.py                # Orchestrateur principal
│   ├── pass1/
│   │   ├── document_analyzer.py   # 1.1
│   │   ├── concept_identifier.py  # 1.2
│   │   ├── assertion_extractor.py # 1.3
│   │   └── semantic_linker.py     # 1.4
│   ├── pass2/
│   │   ├── relation_extractor.py  # 2.1
│   │   └── classifier.py          # 2.2 (optionnel)
│   ├── pass3/
│   │   ├── entity_resolver.py     # 3.1
│   │   └── theme_aligner.py       # 3.2
│   ├── models/
│   │   └── schemas.py             # Pydantic models
│   └── prompts/
│       └── stratified_prompts.yaml
│
├── ingestion/                     # LEGACY - Inchangé
│   └── ... (pipeline actuel)
```

### Mode Burst (priorité)

Le mode Burst exécute Pass 1 + Pass 2 de manière synchrone immédiatement après extraction.

```python
class StratifiedPipeline:
    """Pipeline V2 - Mode Burst."""

    async def process_document(self, doc_path: str) -> PipelineResult:
        # Pass 0: Extraction (existant)
        chunks = await self.extractor.extract(doc_path)

        # Pass 1: Lecture Stratifiée
        analysis = await self.pass1.analyze_document(chunks)
        concepts = await self.pass1.identify_concepts(chunks, analysis)
        assertions = await self.pass1.extract_assertions(chunks)
        informations = await self.pass1.link_and_promote(assertions, concepts)

        # Persist Pass 1
        await self.graph.create_subject(analysis)
        await self.graph.create_themes(analysis.themes)
        await self.graph.create_concepts(concepts)
        await self.graph.create_informations(informations)

        # Pass 2: Enrichissement
        relations = await self.pass2.extract_relations(concepts, chunks)
        await self.graph.create_relations(relations)

        return PipelineResult(
            doc_id=doc_path,
            subject=analysis.subject,
            concepts_count=len(concepts),
            informations_count=len(informations),
            relations_count=len(relations)
        )
```

### Feature Flag

```yaml
# config/feature_flags.yaml
stratified_pipeline_v2:
  enabled: false  # Toggle pour activer V2
  mode: "burst"   # burst | background

  # Fallback sur legacy si V2 échoue
  fallback_to_legacy: true
```

---

---

## Interface Utilisateur V2

### Page Enrichissement V2 (nouvelle)

Créer une **nouvelle page** `/enrichment-v2` sans toucher à l'existante.

**Fonctionnalités** :
- Lancer Pass 1 (Lecture Stratifiée) sur un document
- Lancer Pass 2 (Relations) sur un document
- Lancer Pass 3 (Consolidation) manuellement sur tout le corpus
- Visualiser les résultats (Subject, Themes, Concepts, Informations)
- Consulter l'AssertionLog (debug : promoted/abstained/rejected)

**Stratégie** :
1. Créer `/enrichment-v2` avec toggle "Pipeline V2"
2. Valider sur corpus de test
3. Une fois V2 validé, supprimer la page legacy

---

## Plan d'Implémentation

### Phase 1 : Fondations (Semaine 1)

1. [ ] Créer structure `src/knowbase/stratified/`
2. [ ] Définir schéma Neo4j V2 (constraints, indexes)
3. [ ] Créer schemas Pydantic V2 (Document, Section, DocItem, Subject, Theme, Concept, Information, AssertionLog)
4. [ ] Migrer code POC Pass 1 vers `stratified/pass1/`

### Phase 2 : Pass 0 + Pass 1 (Semaine 2)

1. [ ] Implémenter Pass 0 : création Structural Graph (Document, Section, DocItem)
2. [ ] Adapter Pass 1 pour ancrage sur DocItem (pas chunks)
3. [ ] Implémenter AssertionLog (journal audit)
4. [ ] Tests unitaires Pass 0 + Pass 1

### Phase 3 : Pass 2 + Pass 3 (Semaine 3)

1. [ ] Implémenter Pass 2 : Relation Extractor simplifié
2. [ ] Implémenter Pass 3 : Entity Resolution + Theme Alignment
3. [ ] Mode manuel (on-demand) pour Pass 3
4. [ ] Tests unitaires Pass 2 + Pass 3

### Phase 4 : API + UI (Semaine 4)

1. [ ] Créer endpoints `/v2/*` (search, documents, enrich)
2. [ ] Créer page `/enrichment-v2` (frontend)
3. [ ] Tests d'intégration API
4. [ ] Tests E2E pipeline complet

### Phase 5 : Validation (Semaine 5)

1. [ ] Tests sur corpus de référence (19 docs)
2. [ ] Comparaison métriques Legacy vs V2
3. [ ] Review avec ChatGPT
4. [ ] Décision Go/No-Go

### Phase 6 : Migration (Si Go)

1. [ ] Feature flag activation progressive
2. [ ] Re-processing corpus existant
3. [ ] Période de coexistence (legacy + V2)
4. [ ] Décommissionnement legacy

---

## Décisions Tranchées (Review ChatGPT + Fred)

### ✅ Q1 — Qdrant : OPTION C (dual storage)

**Décision** : Qdrant pour retrieval, Neo4j pour graphe.

- Qdrant stocke les TypeAwareChunks (projection de DocItem) pour recherche vectorielle rapide
- Neo4j stocke le graphe sémantique complet (Document → DocItem → Subject → Theme → Concept → Information)
- Mapping via `docitem_id` dans les chunks Qdrant

### ✅ Q2 — Pass 3 timing : MODE MANUEL + BATCH

**Décision** : Deux modes disponibles.

| Mode | Usage | Déclenchement |
|------|-------|---------------|
| **Manuel** | Tests, validation, démo | Bouton dans UI (page enrichissement V2) |
| **Batch** | Production | Cron nocturne ou seuil configurable |

> **Note Fred** : Le mode manuel est essentiel pour les tests. Créer une nouvelle page d'enrichissement V2 sans casser l'existante, puis supprimer la legacy une fois V2 validé.

### ✅ Q3 — API : OPTION B (endpoints séparés)

**Décision** : Nouveaux endpoints `/v2/*` pendant la coexistence.

- `/v2/search` : Recherche sur graphe V2
- `/v2/documents` : Gestion documents V2
- `/v2/enrich` : Déclenchement Pass 2/3 manuel

Migration : une fois V2 validé, `/v2/*` devient `/` et legacy supprimé.

---

## Métriques de Succès

| Métrique | Legacy | Cible V2 | Validation |
|----------|--------|----------|------------|
| Nodes/document | ~4700 | < 100 | Neo4j count |
| Temps/document | 35+ min | < 10 min | Logs |
| Précision Information | ~60% | > 85% | Échantillon manuel |
| Ratio info/concept (normatif) | N/A | ≥ 2 | Automatique |
| Ratio info/concept (marketing) | N/A | < 1 | Automatique |

---

## Historique

| Date | Événement |
|------|-----------|
| 2026-01-23 | Création du document |
| 2026-01-23 | POC Lecture Stratifiée validé (ADR) |
| 2026-01-23 | Review ChatGPT : corrections intégrées (DocItem, AssertionLog, Section) |
| 2026-01-23 | Décisions tranchées : Qdrant dual, Pass 3 manuel+batch, API /v2/* |

