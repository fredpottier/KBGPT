# ADR: Assertion-aware Knowledge Graph with Context Markers

**Status:** ✅ IMPLEMENTED (Janvier 2026)
**Date:** 2026-01-04
**Owner:** KnowWhere / OSMOSE Team
**Reviewers:** Claude Code, ChatGPT
**Path:** doc/ongoing/ADR_ASSERTION_AWARE_KG.md

---

## Implementation Status (Janvier 2026)

| Composant | Fichier | Status |
|-----------|---------|--------|
| **PR1: DocContextExtractor** | | ✅ **COMPLET** |
| DocContextExtractor | `extraction_v2/context/doc_context_extractor.py` | ✅ |
| Models (DocContextFrame, etc.) | `extraction_v2/context/models.py` | ✅ |
| CandidateMiner + CandidateGate | `extraction_v2/context/candidate_mining.py` | ✅ |
| Prompts LLM | `extraction_v2/context/prompts.py` | ✅ |
| Pipeline integration | `extraction_v2/pipeline.py` | ✅ |
| **PR2: AnchorContext + Inheritance** | | ✅ **COMPLET** |
| AnchorContext models | `extraction_v2/context/anchor_models.py` | ✅ |
| AnchorContextAnalyzer | `extraction_v2/context/anchor_context_analyzer.py` | ✅ |
| Heuristics (polarity, override) | `extraction_v2/context/heuristics.py` | ✅ |
| InheritanceEngine | `extraction_v2/context/inheritance.py` | ✅ |
| OSMOSE integration | `ingestion/osmose_agentique.py` | ✅ |
| **PR3: Diff Queries + UI** | | ✅ **COMPLET** |
| MarkerStore | `consolidation/marker_store.py` | ✅ |
| API /markers | `api/routers/markers.py` | ✅ |
| ConceptDiffService | `api/services/concept_diff_service.py` | ✅ |
| Frontend Compare UI | `frontend/src/app/compare/page.tsx` (~700 lignes) | ✅ |
| **PR4: Pipeline End-to-End** | | ✅ **COMPLET** |
| DocContextFrame flow | `jobs_v2.py` → `osmose_agentique.py` → Neo4j | ✅ |

**Note:** Les composants structurels (ZoneSegmenter, TemplateDetector, LinguisticCueDetector) sont dans `extraction_v2/context/structural/` - voir ADR_DOCUMENT_STRUCTURAL_AWARENESS.md.

---

## 1. Decision

We will evolve the Knowledge Graph to become **assertion-aware** by enriching extracted knowledge with **context markers** and **applicability signals** while keeping the system **100% domain-agnostic**.

Concretely:

1) Keep **CanonicalConcept** as the stable, corpus-level identity (unchanged).
2) Treat **ProtoConcept** as the document-level *assertion carrier* (no new entity required).
3) Add a **DocContextFrame** per document containing:
   - `strong_markers` (high-confidence dominant context markers)
   - `weak_markers` (low-confidence/context hints)
   - `doc_scope` classification: `GENERAL | VARIANT_SPECIFIC | MIXED`
   - `scope_confidence` and `scope_signals`
4) Enrich **Anchor** (and aggregate into ProtoConcept) with:
   - `polarity` (positive/negative/future/deprecated/conditional/unknown)
   - `scope` (general/constrained/unknown)
   - `local_markers` (explicit markers in the passage)
   - `is_override` + `override_type` (switch/range/generalization/null)
   - `confidence`
5) Implement **conservative context inheritance** from document → anchors/proto-concepts using a strict matrix (no inheritance by default for `MIXED`).
6) Store assertion properties on the existing Neo4j relation:
   - `(ProtoConcept)-[:EXTRACTED_FROM {...assertion props...}]->(Document)`
   (relation name remains `EXTRACTED_FROM`; its semantics becomes "assertion carrier")
7) Optionally materialize `(:Marker)` nodes for fast diff queries at scale:
   - `(ProtoConcept)-[:ASSERTED_WITH_MARKER]->(Marker)`

This enables generic comparative questions such as:
- "What is in A but not in B?"
- "What changed between A and B?"
- "What is valid for all variants?"

without requiring any domain schema (no explicit "version", "product", "year", etc.).

---

## 2. Rationale

### Why this approach?
- **Domain-agnosticism preserved:** markers are stored as raw strings; the system does not interpret them as "version/year/edition".
- **Comparative reasoning becomes possible:** the KG can compute set differences on contextualized assertions.
- **Noise control / safety:** a hybrid strategy prevents LLM hallucinated markers and avoids cross-contamination (especially for comparative documents).
- **Traceability:** evidence and confidence scores make the results auditable.

### Key insight
A document often declares its context once (cover/title/revision), then uses implicit references.
Therefore, chunks/anchors must **inherit** document context unless a local override explicitly changes it.

---

## 3. Rules

### 3.1 DocContext extraction (anti-hallucination)
We use a **two-step** strategy:

**Step 1: Candidate Mining (deterministic)**
Extract candidate markers from:
- filename
- first pages (cover/title)
- headers/footers (if available)
- revision/history blocks (if detectable)

Candidate mining uses generic pattern detection (alphanumeric codes, version strings, year-like tokens) and generic scope-language triggers (multi-language minimal list: "version/release/revision/edition/as of/from/since/applies to/all versions/…").

**Step 2: LLM Validation (Qwen 14B, burst mode)**
The LLM receives the candidate list + extracted text context and returns:
- `strong_markers` and `weak_markers` selected from candidates (or explicitly quoted text)
- `doc_scope` + confidence + 5 signals
- evidence quotes that justify the output

**Hard constraint:** LLM must not introduce markers not present in candidates or quoted text.

---

### 3.2 DocScope classification
Each document is classified as:
- `GENERAL`: no dominant markers; content intended to apply broadly
- `VARIANT_SPECIFIC`: a dominant context marker exists (strong or weak)
- `MIXED`: multiple variants compared/contrasted; high diversity and conflict signals

The system stores:
- `doc_scope`
- `scope_confidence`
- `scope_signals`:
  - marker_position_score
  - marker_repeat_score
  - scope_language_score
  - marker_diversity_score
  - conflict_score

---

### 3.3 AnchorContext analysis (heuristic first, LLM on demand)
For each Anchor:
1) Run fast heuristics to detect:
   - polarity candidates (negation, future, deprecated, conditional language)
   - local marker candidates
   - override patterns (contrast, "new in", "starting with", "unlike", "vs", etc.)
2) Call LLM only if:
   - polarity is unknown, or
   - override patterns detected, or
   - doc_scope is MIXED, or
   - heuristic conflict detected

---

### 3.4 Context inheritance matrix (conservative)

**DocScope = VARIANT_SPECIFIC**
- If `strong_markers` exists:
  - If `anchor.is_override` → use anchor local markers (override wins)
  - Else:
    - anchor.scope = constrained
    - inherit `strong_markers` as markers
    - qualifier_source = inherited_strong
    - confidence = min(anchor_conf, doc_conf) * 0.95
- If only `weak_markers` exists:
  - Same logic with qualifier_source = inherited_weak
  - confidence factor ~ 0.85

**DocScope = MIXED**
- Default: no inheritance, anchor.scope = unknown
- Allow weak inheritance only if:
  - no local markers, no override patterns, and neutral passage
  - confidence must remain low (<= 0.5)

**DocScope = GENERAL**
- Default: anchor.scope = general (no inherited markers)
- If anchor contains explicit "only for / applies to" markers → anchor can become constrained

---

### 3.5 Aggregation to ProtoConcept (conflict-aware)
ProtoConcept aggregates its anchors:

**Polarity**
- all positive → positive
- all negative → negative
- mixed → conflict (store conflict_flags + counter-evidence)

**Scope**
- if any constrained with confidence > 0.7 → constrained
- else if at least one general and no strong constrained → general
- else unknown

**Markers**
- merge markers weighted by confidence, keep top-K (K=3) to avoid marker explosion.

---

## 4. JSON Contracts

### 4.1 DocScopeAnalysis (LLM output)
```json
{
  "strong_markers": [{"value":"1809","evidence":"...quote...","source":"cover|header|revision|title"}],
  "weak_markers": [{"value":"2025","evidence":"...quote...","source":"filename|low_conf"}],
  "doc_scope": "GENERAL|VARIANT_SPECIFIC|MIXED",
  "scope_confidence": 0.0,
  "signals": {
    "marker_position_score": 0.0,
    "marker_repeat_score": 0.0,
    "scope_language_score": 0.0,
    "marker_diversity_score": 0.0,
    "conflict_score": 0.0
  },
  "evidence": ["quote1", "quote2"],
  "notes": "max 2 sentences, no assumptions"
}
```

### 4.2 AnchorContext (heuristic or LLM output)
```json
{
  "polarity": "positive|negative|future|deprecated|conditional|unknown",
  "scope": "general|constrained|unknown",
  "local_markers": [{"value":"2025","evidence":"...quote..."}],
  "is_override": true,
  "override_type": "switch|range|generalization|null",
  "confidence": 0.0,
  "evidence": ["quote1"]
}
```

### 4.3 DocContextFrame (stored on Document)
```json
{
  "document_id": "xxx",
  "strong_markers": ["1809"],
  "weak_markers": ["FPS03"],
  "strong_evidence": ["SAP S/4HANA 1809 Feature Pack"],
  "weak_evidence": ["filename contains FPS03"],
  "doc_scope": "VARIANT_SPECIFIC",
  "scope_confidence": 0.85,
  "scope_signals": {
    "marker_position_score": 0.9,
    "marker_repeat_score": 0.7,
    "scope_language_score": 0.3,
    "marker_diversity_score": 0.2,
    "conflict_score": 0.1
  }
}
```

---

## 5. Storage Strategy

### 5.1 Neo4j Model

```cypher
// Document with DocContextFrame
(d:Document {
    id: "xxx",
    name: "S4HANA_1809_BUSINESS_SCOPE.pdf",
    doc_scope: "VARIANT_SPECIFIC",
    scope_confidence: 0.85,
    strong_markers: ["1809"],
    weak_markers: ["FPS03"]
})

// ProtoConcept with assertion properties on relation
(pc:ProtoConcept {id: "pc_xxx", label: "Credit Management", ...})
-[:EXTRACTED_FROM {
    polarity: "positive",
    scope: "constrained",
    markers: ["1809"],
    qualifier_source: "inherited_strong",
    confidence: 0.85,
    is_override: false
}]->(d:Document)

// CanonicalConcept (unchanged)
(pc)-[:INSTANCE_OF]->(cc:CanonicalConcept {id: "cc_xxx", ...})

// Optional: Marker nodes for fast diff (scale optimization)
(m:Marker {value: "1809", kind: "numeric_code"})
(pc)-[:ASSERTED_WITH_MARKER]->(m)
```

### 5.2 Index Strategy

```cypher
// Essential indexes
CREATE INDEX doc_id IF NOT EXISTS FOR (d:Document) ON (d.id);
CREATE INDEX doc_scope IF NOT EXISTS FOR (d:Document) ON (d.doc_scope);

// For diff queries (if using Marker nodes)
CREATE INDEX marker_value IF NOT EXISTS FOR (m:Marker) ON (m.value);
```

### 5.3 Evidence Storage

**Guideline:** Store references, not full quotes, to avoid bloating Neo4j:
- `evidence_chunk_ids: ["chunk_xxx", "chunk_yyy"]`
- `evidence_spans: [[0, 45], [120, 180]]`
- Max 2 short evidence strings (< 100 chars) for quick display

---

## 6. Failure Modes and Detection

### FM-1: Marker noise / over-extraction
**Symptom:** too many documents become VARIANT_SPECIFIC; markers explode.
**Detection:** marker_diversity_score high; high weak_marker count; diff results become unstable.
**Mitigation:** tighten candidate mining; require evidence for strong_markers; cap markers; prefer strong markers only.

### FM-2: Contamination in comparative documents (MIXED)
**Symptom:** assertions incorrectly inherit a single marker in a multi-variant doc.
**Detection:** doc_scope=MIXED with inherited markers at high confidence.
**Mitigation:** enforce "no inheritance by default for MIXED"; require explicit overrides.

### FM-3: Missing implicit context (under-inheritance)
**Symptom:** document has a strong marker but many anchors remain unknown/general.
**Detection:** VARIANT_SPECIFIC docs with low inherited marker ratio.
**Mitigation:** check doc_context extraction coverage; ensure inheritance applied to neutral anchors.

### FM-4: Override missed (false inheritance)
**Symptom:** passages like "Unlike X, in Y..." still inherit doc markers.
**Detection:** override patterns present but `is_override=false`.
**Mitigation:** LLM on-demand triggers on contrast patterns; add heuristic triggers.

### FM-5: Polarity errors (negation/future/deprecated)
**Symptom:** concept counted as present though negated/deprecated.
**Detection:** conflicts; unusually high negative-to-positive mismatch across anchors.
**Mitigation:** strengthen heuristic lexicon; LLM fallback for ambiguous cases.

### FM-6: Query performance issues (marker filtering)
**Symptom:** slow diff queries on large graphs if markers are list properties.
**Detection:** query profiling shows list scans.
**Mitigation:** materialize Marker nodes and index `Marker.value`; join via `ASSERTED_WITH_MARKER`.

---

## 7. Implementation Plan

### PR 1: DocContextExtractor ✅ DONE
**Files:**
- `src/knowbase/extraction_v2/context/doc_context_extractor.py` ✅
- `src/knowbase/extraction_v2/context/models.py` ✅
- `src/knowbase/extraction_v2/context/candidate_mining.py` ✅ (1000+ lignes, CandidateGate complet)
- `src/knowbase/extraction_v2/context/prompts.py` ✅
- `src/knowbase/extraction_v2/pipeline.py` ✅
- `src/knowbase/extraction_v2/models/extraction_result.py` ✅

**Implémenté:**
- ✅ Candidate mining avec patterns structurels agnostiques
- ✅ CandidateGate avec 10+ filtres universels (dates, copyright, trimestres, etc.)
- ✅ LLM validation
- ✅ DocContextFrame storage on ExtractionResult
- ✅ Integration pipeline complète

### PR 2: AnchorContext + Inheritance ✅ DONE
**Files:**
- `src/knowbase/extraction_v2/context/anchor_models.py` ✅
- `src/knowbase/extraction_v2/context/anchor_context_analyzer.py` ✅
- `src/knowbase/extraction_v2/context/heuristics.py` ✅
- `src/knowbase/extraction_v2/context/inheritance.py` ✅
- `src/knowbase/ingestion/osmose_agentique.py` ✅

**Implémenté:**
- ✅ Heuristic-first AnchorContext analysis
- ✅ LLM on-demand pour cas ambigus
- ✅ Inheritance matrix implementation
- ✅ Aggregation to ProtoConcept

### PR 3: Diff Queries + UI ✅ DONE
**Files:**
- `src/knowbase/api/routers/markers.py` ✅
- `src/knowbase/api/services/concept_diff_service.py` ✅
- `src/knowbase/consolidation/marker_store.py` ✅
- `frontend/src/app/compare/page.tsx` ✅ (~700 lignes)

**Implémenté:**
- ✅ MarkerStore avec DiffResult
- ✅ API endpoints `/markers` et `/api/concepts/diff`
- ✅ Frontend Compare UI complet:
  - Sélection de markers (dropdown + saisie manuelle)
  - Exécution du diff
  - Statistiques (only_in_a, only_in_b, in_both, changed)
  - Tabs de navigation par catégorie
  - Filtrage par recherche
  - Rendu des cartes de concepts avec polarity, scope, confidence

---

## 8. Test Dataset

| Document | Expected doc_scope | Expected strong_markers |
|----------|-------------------|------------------------|
| `S4HANA_1809_BUSINESS_SCOPE_MASTER_L23.pdf` | VARIANT_SPECIFIC | ["1809"] |
| `20251212_Business-Scope-2025-SAP-Cloud-ERP-Private.pdf` | VARIANT_SPECIFIC | ["2025"] |
| `L2_GROW_with_SAP_Overview Oct 2024.pptx` | GENERAL | [] |
| `SAP-002_What's_New_in_SAP_S_4HANA_Cloud_Public_Edition_2508.pdf` | MIXED | ["2508"] (but comparative content) |

**Validation metrics:**
1. DocScope accuracy: % of docs with correct classification
2. Marker precision: % of strong_markers that are true context markers
3. Inheritance accuracy: % of assertions with correct inherited markers
4. Diff quality: top-20 differences contain true differences (not synonyms)

---

## 9. References

- Original discussion: Claude Code + ChatGPT brainstorming session (2026-01-04)
- Related ADR: `doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md`
- OSMOSE Architecture: `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
