# ADR-2024-12-30: Reducto-like Parsing Primitives in OSMOSE

**Status:** ⚠️ PARTIELLEMENT IMPLÉMENTÉ (Janvier 2026)
**Date:** 2024-12-30
**Authors:** OSMOSE Team
**Reviewers:** -

---

## Implementation Status (Janvier 2026)

| Composant | Fichier | Status |
|-----------|---------|--------|
| **Vision Gating V4** | | ✅ **COMPLET** |
| GatingEngine | `extraction_v2/gating/engine.py` | ✅ |
| Signals (RIS, VDS, TFS, SDS, VTS) | `extraction_v2/gating/signals.py` | ✅ |
| Weights & Thresholds | `extraction_v2/gating/weights.py` | ✅ |
| VisionUnit, GatingDecision | `extraction_v2/models/gating.py` | ✅ |
| **QW-1: Table Summaries** | | ❌ **NON FAIT** |
| Detection tableaux | - | ❌ Non fait |
| LLM summarization | - | ❌ Non fait |
| Storage summary + raw | - | ❌ Non fait |
| **QW-2: Confidence Scores** | | ⚠️ **PARTIEL** |
| parse_confidence (heuristique) | - | ❌ Non fait |
| extract_confidence (LLM) | - | ❌ Non fait |
| **QW-3: Diagram Interpreter** | | ❌ **NON FAIT** |
| Pass 0 pre-analyse | - | ❌ Non fait |
| Pass 1 VLM adaptatif | - | ❌ Non fait |
| DiagramAnalysis schema | - | ❌ Non fait |
| **MT-1: Layout-Aware Chunking** | | ❌ **NON FAIT** |
| layout_detector.py | - | ❌ Non fait |
| Chunking par region | - | ❌ Non fait |

**Ce qui est implémenté:**
- ✅ Vision Gating V4 complet avec 5 signaux (RIS, VDS, TFS, SDS, VTS)
- ✅ Décision VISION_REQUIRED / VISION_RECOMMENDED / NONE
- ✅ Règle de sécurité (RIS=1.0 ou VDS=1.0 → force Vision)
- ✅ Domain context pour ajustement des poids

**Ce qui reste à faire (Quick Wins):**
- QW-1: Table Summaries → Impact RAG +50% estimé
- QW-2: Confidence Scores → Debuggabilité
- QW-3: Diagram Interpreter → Extraction structurée diagrammes

---

## Context

L'analyse comparative entre Reducto (pipeline document AI "vision-first") et OSMOSE (pipeline semantique "meaning-first") a revele des lacunes structurelles dans la phase amont d'OSMOSE :

| Probleme | Impact mesure |
|----------|---------------|
| Tableaux non resumes | Hit-rate RAG ~30% vs ~80% avec summaries |
| Pas de scores de confiance | Debuggabilite nulle, filtrage impossible |
| Chunking par tokens | Tableaux coupes, structure perdue |
| Pas de detection layout | ~40% coverage vs ~90% sur docs complexes |

**Insight cle (ChatGPT):**
> "Un pipeline semantique, meme excellent, ne rattrape jamais une structure d'entree degradee."

Le Knowledge Graph, les relations, et le RAG d'OSMOSE travaillent actuellement sur une base partiellement bruitee. Ameliorer la phase de parsing augmente mecaniquement la valeur de toute la chaine aval.

---

## Decision

**Adopter les primitives de parsing inspirees de Reducto dans OSMOSE**, sans abandonner l'architecture semantique qui constitue notre differentiation.

### Scope: Ce que nous adoptons

| Primitive | Description | Priorite |
|-----------|-------------|----------|
| **Table Summaries** | Transformer tableaux en texte naturel avant embedding | Quick Win (QW-1) |
| **Confidence Scores** | `parse_confidence` + `extract_confidence` sur chaque extraction | Quick Win (QW-2) |
| **Diagram Interpreter** | Extraction structuree des diagrammes (elements, relations, labels) via VLM adaptatif | Quick Win (QW-3) |
| **Layout-Aware Chunking** | Detecter regions, ne jamais couper un tableau | Moyen Terme (MT-1) |

### Non-Goals: Ce que nous n'adoptons PAS

| Element | Raison |
|---------|--------|
| **Schema-based extraction** | Philosophie incompatible : Reducto extrait des *champs*, OSMOSE decouvre des *concepts + relations* |
| **Full Reducto replacement** | Lock-in, cout, donnees sensibles, perte de controle |
| **Layout model complexe (LayoutLMv3)** | Overkill initial, heuristiques suffisent pour v1 |
| **Bboxes pixel-level** | Nice-to-have, pas prioritaire vs impact RAG |

---

## Rationale

### Pourquoi ces primitives specifiquement ?

**1. Table Summaries (ROI maximal)**
```
Tableau brut:
| Annee | CA    | Marge |
| 2022  | 100M  | 15%   |
| 2023  | 120M  | 18%   |

Embedding direct → Vecteur faible (structure non semantique)

Table Summary:
"Le chiffre d'affaires a augmente de 20% entre 2022 et 2023,
passant de 100M a 120M, avec une amelioration de la marge
de 15% a 18%."

Embedding summary → Vecteur riche, requetes naturelles matchent
```

- Gain mesurable : x2-3 sur hit-rate RAG pour questions tableaux
- Risque : Faible (additif, pas de modification existant)
- Effort : 5 jours

**2. Confidence Scores (primitive, pas bonus)**

> "Sans score de confiance explicite, tout resultat est implicitement egalement vrai." — ChatGPT

- Signal de filtrage automatique
- Prerequis AI Act / auditabilite
- Garde-fou anti-hallucination
- Levier UX (afficher fiabilite)

```json
{
  "concept": "Croissance CA 2023",
  "value": "20%",
  "parse_confidence": 0.92,
  "extract_confidence": 0.88,
  "source_citation": "Rapport annuel p.12"
}
```

- Effort : 3 jours

**3. VLM Review Enhancement → Diagram Interpreter (evolution majeure)**

**Probleme identifie (analyse Claude Code 2024-12-31):**

Le pipeline Vision actuel (`vision_analyzer.py` → `ask_gpt_vision_summary()`) produit des **resumes prose** qui capturent le sens global mais **perdent les details granulaires** :

```
DIAGRAMME ARCHITECTURE (10 boxes, 5 fleches)
┌─────────┐     ┌─────────┐     ┌─────────┐
│ SAP GUI │────▶│ Fiori   │────▶│ HANA DB │
│ Port 32 │     │ Port 443│     │Port 30015│
└─────────┘     └─────────┘     └─────────┘

OUTPUT ACTUEL (prose):
"L'architecture montre trois composants connectes..."

CE QU'ON PERD:
- Labels individuels (SAP GUI, Fiori, HANA DB)
- Metadonnees (ports, versions)
- Relations explicites (fleches, directions)
- Structure tabulaire (si tableaux)
```

**Architecture cible : Pass 0 + Pass 1 Adaptatif**

```
┌─────────────────────────────────────────────────────────────┐
│  PASS 0 - Pre-analyse Locale (GRATUIT)                      │
│  ├─ vision_gating.py existant (patterns detection)         │
│  ├─ Analyse complexite image (histogramme, edges)          │
│  └─ Heuristiques texte OCR                                 │
│                                                             │
│  Output: SKIP | TEXT_ONLY | VISION_LITE | VISION_FULL      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  PASS 1 - VLM Conditionnel (1 seul appel)                   │
│                                                             │
│  VISION_LITE : Prompt court                                 │
│  → "Identify diagram type + list all text labels"          │
│                                                             │
│  VISION_FULL : Prompt structure complet                     │
│  → Extraction JSON : elements, relations, tables, confidence│
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  QUALITY GATE                                               │
│  if confidence < 0.7 → Fallback prose (comportement actuel) │
│  else → Utiliser extraction structuree pour le KG          │
└─────────────────────────────────────────────────────────────┘
```

**Schema DiagramAnalysis (output structure):**

```python
class DiagramElement(BaseModel):
    id: str
    element_type: Literal["box", "circle", "arrow", "text", "image", "table_cell"]
    label: str
    position: Optional[Dict[str, float]]  # {x, y, width, height} normalise 0-1
    metadata: Dict[str, Any]  # port, version, color, etc.
    confidence: float

class DiagramRelation(BaseModel):
    from_id: str
    to_id: str
    relation_type: Literal["arrow", "line", "contains", "groups"]
    label: Optional[str]
    confidence: float

class TableExtraction(BaseModel):
    headers: List[str]
    rows: List[List[str]]
    confidence: float

class DiagramAnalysis(BaseModel):
    diagram_type: Literal[
        "flowchart", "architecture", "org_chart", "table",
        "comparison", "timeline", "process", "hierarchy", "other"
    ]
    elements: List[DiagramElement]
    relations: List[DiagramRelation]
    tables: List[TableExtraction]
    overall_confidence: float
    semantic_summary: str  # Fallback prose (comportement actuel)
    extraction_method: Literal["vision_full", "vision_lite", "text_only"]
```

**Avantages vs approche 2-pass ChatGPT:**

| ChatGPT (2 passes VLM) | Notre Approche |
|------------------------|----------------|
| Pass A (inventaire) → Pass B (interpretation) | Pass 0 local (gratuit) + Pass 1 VLM unique |
| Cout tokens x2 | Cout optimise (~50% economie) |
| Systematique | Adaptatif selon complexite |

- Effort : 2-3 semaines
- Prerequis : QW-2 (Confidence Scores)

**4. Layout-Aware Chunking (regle structurelle)**

> "Ne jamais couper un tableau" — Regle non-negociable

Actuellement : HybridAnchorChunker decoupe par tokens (256), ignorant la structure.
Cible : Detecter regions (tableau, liste, paragraphe) et chunker par unite logique.

- Effort : 2-3 semaines

### Pourquoi PAS schema-based extraction ?

| Reducto | OSMOSE |
|---------|--------|
| Extraction declarative | Decouverte semantique |
| "Extrais le champ X" | "Quels concepts existent ?" |
| Champs predits | Concepts emergeants |
| Pas de KG | Knowledge Graph natif |

Adopter le schema-based tuerait la proposition de valeur OSMOSE :
- Cross-document reasoning
- Detection de contradictions
- Temporalite des concepts
- Relations semantiques

---

## Differentiation Preservee

**Phrase produit cle:**
> "Reducto sait extraire. OSMOSE sait arbitrer."

| Capacite | Reducto | OSMOSE |
|----------|---------|--------|
| Knowledge Graph | Non | Oui |
| Concepts canoniques | Non | Oui |
| Relations temporelles | Non | Oui |
| Cross-document linking | Non | Oui |
| Detection contradictions | Non | Oui (cible) |
| Graph-Guided Search | Non | Oui |

OSMOSE reste un systeme de **connaissance consolidee**, pas d'extraction locale.

---

## Implementation Plan

### Phase 0: Vision Gating V4 ✅ DONE (Janvier 2026)

```
✅ IMPLÉMENTÉ:
├── GatingEngine complet (extraction_v2/gating/engine.py)
│   ├── 5 signaux: RIS, VDS, TFS, SDS, VTS
│   ├── VNS (Vision Need Score) calculation
│   ├── Seuils: VISION_REQUIRED (≥0.60), VISION_RECOMMENDED (≥0.40), NONE (<0.40)
│   └── Règle sécurité: RIS=1.0 ou VDS=1.0 → force Vision
│
├── Signals (extraction_v2/gating/signals.py)
│   ├── compute_raster_image_score()
│   ├── compute_vector_drawing_score()
│   ├── compute_text_fragmentation_score()
│   ├── compute_spatial_dispersion_score()
│   └── compute_visual_table_score()
│
└── Weights & Domain Context (extraction_v2/gating/weights.py)
    ├── DEFAULT_GATING_WEIGHTS
    ├── GATING_THRESHOLDS
    └── get_weights_for_domain()
```

### Phase 1: Quick Wins ❌ NON FAIT

```
Semaine 1-2:
├── QW-1: Table Summaries ❌
│   ├── Detection heuristique tableaux (patterns |, tabs)
│   ├── Prompt LLM: "Resume ce tableau en langage naturel"
│   ├── Stockage: summary + raw dans payload Qdrant
│   └── Insertion: osmose_agentique.py entre segmentation et chunking
│
├── QW-2: Confidence Scores ❌
│   ├── parse_confidence: heuristique (longueur, structure, coherence)
│   ├── extract_confidence: retourne par LLM dans prompt
│   ├── Stockage: payload Qdrant + Neo4j
│   └── Insertion: osmose_agentique.py + hybrid_anchor_chunker.py
│
Semaine 3-4:
└── QW-3: Diagram Interpreter ❌
    ├── Pass 0 - Pre-analyse locale
    ├── Pass 1 - VLM Adaptatif
    ├── Schema DiagramAnalysis
    ├── Quality Gate
    └── Integration
```

### Phase 2: Moyen Terme ❌ NON FAIT

```
MT-1: Layout-Aware Chunking ❌
├── Nouveau composant: layout_detector.py
├── Modification: hybrid_anchor_chunker.py
└── Validation: 0 tableaux coupes sur set de test
```

### Phase 3: Optionnel (si necessaire)

```
MT-2: Multi-Pass Verification
├── Pass 1.5: LLM relit et corrige extractions Pass 1
├── Cout: +30% appels LLM
└── Gain: -40% erreurs

MT-3: Chart Extraction Pipeline
├── Pipeline 3 stages inspire Reducto
├── Effort: 3-4 semaines
└── Gain: +30-50% coverage sur presentations
```

---

## Metriques de Succes

| Metrique | Baseline | Cible Post-QW | Cible Post-MT |
|----------|----------|---------------|---------------|
| Hit-rate RAG (questions tableaux) | ~30% | >60% | >80% |
| Coverage extraction | ~60% | >75% | >90% |
| Chunks avec confidence | 0% | 100% | 100% |
| Tableaux coupes | ~40% | ~40% | 0% |
| Temps debug erreur | >30 min | <10 min | <5 min |
| **Labels diagrammes extraits** | ~20% | >70% | >85% |
| **Relations visuelles capturees** | ~10% | >60% | >80% |
| **Slides avec DiagramAnalysis** | 0% | >50% | >70% |

---

## Risks and Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Table summaries = hallucinations | Moyen | Prompt strict + validation croisee avec raw |
| Confidence scores non calibres | Faible | Calibration sur set annote, ajustement iteratif |
| Layout detection rate tableaux | Moyen | Fallback sur chunking tokens si detection echoue |
| Surcout LLM (summaries) | Faible | ~1 call supplementaire par tableau, acceptable |
| **DiagramAnalysis JSON mal forme** | Moyen | Validation Pydantic stricte + fallback prose |
| **Pass 0 routing incorrect** | Faible | Heuristiques conservatrices (VISION_FULL par defaut si doute) |
| **Labels extraits incomplets** | Moyen | Quality gate confidence + fusion avec OCR texte |
| **Surcout tokens VISION_FULL** | Moyen | Pass 0 filtre 60-70% slides triviales (SKIP/TEXT_ONLY) |

---

## Alternatives Considerees

### Alternative 1: Integrer Reducto en pre-processeur

```
Document → [Reducto API] → JSON propre → [OSMOSE Semantic]
```

**Rejete car:**
- Dependance externe critique
- Cout par document
- Donnees sensibles transitent
- Perte de controle sur la chaine

### Alternative 2: Adopter LayoutLMv3 / DocTR

**Differe car:**
- Complexite d'integration elevee
- Heuristiques suffisent pour 80% des cas
- A reconsiderer si heuristiques insuffisantes

### Alternative 3: Ne rien faire

**Rejete car:**
- Qualite RAG plafonnee
- Pas de debuggabilite
- Non-competitif sur documents complexes

---

## Decision Outcome

**Decision:** Implementer QW-1, QW-2, QW-3 immediatement, MT-1 en suivi.

**Impact attendu:**
- +50% qualite RAG sur documents avec tableaux
- Debuggabilite complete (confidence + citations)
- Base solide pour futures ameliorations

**Ce qui ne change PAS:**
- Architecture Knowledge Graph
- Extraction concepts semantique
- Relations et temporalite
- Differentiation vs Reducto/Copilot

---

## References

- `doc/ongoing/REDUCTO_VS_OSMOSE_ANALYSIS.md` — Analyse comparative complete
- `doc/ongoing/SCALING_ARCHITECTURE_REFLEXION.md` — Reflexion infrastructure
- `src/knowbase/ingestion/osmose_agentique.py` — Pipeline principal
- `src/knowbase/ingestion/hybrid_anchor_chunker.py` — Chunker actuel
- `src/knowbase/ingestion/components/transformers/vision_analyzer.py` — Pipeline Vision actuel
- `src/knowbase/ingestion/components/transformers/vision_gating.py` — Gating Vision (a enrichir)

---

## Historique des Revisions

| Date | Revision | Auteur |
|------|----------|--------|
| 2024-12-30 | Creation ADR initial | OSMOSE Team |
| 2024-12-31 | **Extension QW-3 → Diagram Interpreter** | Claude Code + ChatGPT (collaboration) |
|            | - Ajout architecture Pass 0 + Pass 1 adaptatif | |
|            | - Schema DiagramAnalysis (elements, relations, tables) | |
|            | - Metriques extraction diagrammes | |
|            | - Risques specifiques VLM structuree | |

---

*ADR approved for implementation. Review after Quick Wins completion.*
*QW-3 Diagram Interpreter: Analyse collaborative ChatGPT (theorie) + Claude Code (validation code).*
