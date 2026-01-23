# Architecture du Pipeline Stratifié V2

**Statut**: EN CONCEPTION
**Date**: 2026-01-23
**Branche**: `pivot/stratified-pipeline-v2`
**Réf**: ADR-20260123-stratified-reading-poc-validation.md

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

### Hiérarchie Sémantique (6 types de nodes max)

```
Subject (1 par document)
    │
    ├── Theme (3-7 par document)
    │       │
    │       └── Concept (5-15 par document, total)
    │               │
    │               └── Information (assertions défendables)
    │
    └── [Relations inter-concepts]
```

### Estimation Nodes V2

| Type | Par document | 19 docs | Ratio vs Legacy |
|------|--------------|---------|-----------------|
| Subject | 1 | 19 | - |
| Theme | ~5 | ~95 | - |
| Concept | ~12 | ~230 | vs ~5000 ProtoConcept |
| Information | ~15 | ~285 | vs ~40000 RawAssertion |
| Relation | ~10 | ~190 | vs ~3000 |
| Document | 1 | 19 | inchangé |
| **TOTAL** | **~44** | **~840** | **~1% du legacy** |

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

### PASS 0 : Extraction (INCHANGÉ)

Le pipeline d'extraction Docling + Vision Gating reste identique.

**Input**: Document (PDF, PPTX, DOCX)
**Output**:
- Chunks textuels avec positions
- Métadonnées document
- Images extraites (si vision)

**Nodes créés**: Aucun (données en transit)

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

#### 1.4 Semantic Linking + Promotion

**Objectif**: Lier les assertions aux concepts ET filtrer selon la Promotion Policy.

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
      "assertion_id": uuid,
      "concept_id": uuid,
      "text": str,
      "type": str,
      "anchor": {
        "chunk_id": str,
        "span": {"start": int, "end": int}
      }
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
| Information | 5-30 | text, type, concept_id, anchor |

**Relations créées**:
- `(Subject)-[:HAS_THEME]->(Theme)`
- `(Theme)-[:CONTAINS]->(Concept)`
- `(Concept)-[:HAS_INFORMATION]->(Information)`
- `(Information)-[:ANCHORED_IN]->(Document)` avec span

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

### Nodes supprimés en V2

| Node Legacy | Raison suppression | Remplacement V2 |
|-------------|-------------------|-----------------|
| ProtoConcept | Étape intermédiaire inutile | Concept direct |
| RawAssertion | Trop de bruit | Information (filtrée) |
| Claim | Redondant avec Information | Information |
| WindowContext | Explosion combinatoire | Supprimé |
| SectionContext | Valeur limitée | Supprimé (anchor suffit) |
| DocumentContext | 1 seul utile | Subject |
| NormativeRule | Intégré dans Information | Information.type = PRESCRIPTIVE |
| SpecFact | Intégré dans Information | Information.type = FACTUAL |

### Mapping conceptuel

```
Legacy                          V2
──────                          ──
DocumentContext     ────────>   Subject
Topic               ────────>   Theme
ProtoConcept        ────────>   (supprimé)
CanonicalConcept    ────────>   Concept
RawAssertion        ────────>   (supprimé, filtré)
Claim               ────────>   Information
NormativeRule       ────────>   Information (type=PRESCRIPTIVE)
SpecFact            ────────>   Information (type=FACTUAL)
```

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

## Plan d'Implémentation

### Phase 1 : Core Pipeline (Semaine 1-2)

1. [ ] Migrer code POC vers `src/knowbase/stratified/`
2. [ ] Adapter pour mode Burst
3. [ ] Créer schemas Pydantic V2
4. [ ] Tests unitaires Pass 1

### Phase 2 : Intégration Neo4j (Semaine 2-3)

1. [ ] Définir schéma Neo4j V2 (constraints, indexes)
2. [ ] Implémenter GraphWriter V2
3. [ ] Tests d'intégration

### Phase 3 : Pass 2 Enrichissement (Semaine 3-4)

1. [ ] Relation Extractor simplifié
2. [ ] Tests

### Phase 4 : Validation (Semaine 4-5)

1. [ ] Tests E2E sur corpus de référence
2. [ ] Comparaison métriques Legacy vs V2
3. [ ] Décision Go/No-Go

### Phase 5 : Migration (Si Go)

1. [ ] Feature flag activation progressive
2. [ ] Re-processing corpus existant
3. [ ] Décommissionnement legacy

---

## Questions Ouvertes

### À décider

1. **Qdrant** : Garde-t-on les chunks dans Qdrant ou seulement Neo4j ?
   - Option A: Neo4j only (simplicité)
   - Option B: Qdrant pour search, Neo4j pour graph (actuel)

2. **Pass 3 timing** : Quand lancer la consolidation cross-doc ?
   - Option A: Après chaque document (coûteux)
   - Option B: Batch nocturne (latence)
   - Option C: Seuil (ex: tous les 10 docs)

3. **Rétrocompatibilité API** : Les endpoints `/search` doivent-ils fonctionner avec V2 ?
   - Si oui, adapter les queries
   - Si non, nouveaux endpoints `/v2/search`

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

